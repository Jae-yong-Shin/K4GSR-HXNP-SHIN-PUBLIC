#!/usr/bin/env python3
"""Latency measurement script for the K4GSR BL10 virtual beamline paper.

Measures end-to-end latency for:
  1. Scan event pipeline: RunEngine callback -> WebSocket -> client receive
  2. PV monitoring pipeline: IOC -> CA bridge poll -> WebSocket -> client receive

Usage:
  1. Start soft IOC:   python server/epics/soft_ioc.py
  2. Start server:      python server/server.py --bluesky
  3. Run this script:   python paper/measure_latency.py

Output:
  - Console summary statistics
  - paper/latency_results.json  (raw data for supplementary)
  - paper/latency_summary.txt   (formatted summary for paper)
"""

import asyncio
import json
import time
import sys
import os
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)


WS_BASE = "ws://localhost:8001"
SCAN_URL = f"{WS_BASE}/ws/scan"
PV_URL = f"{WS_BASE}/ws/pv"


async def measure_scan_latency(plan_name="energy_scan", n_points=51, **scan_params):
    """Measure scan event pipeline latency."""
    print(f"\n{'='*60}")
    print(f"SCAN LATENCY MEASUREMENT: {plan_name}, {n_points} points")
    print(f"{'='*60}")

    default_params = {
        "energy_scan": {"e_start": 9.9, "e_stop": 10.1, "n_points": n_points},
        "alignment_scan": {"motor": "BL10:DCM:DTheta2", "start": -0.01, "stop": 0.01, "n_points": n_points},
    }
    if scan_params:
        params = scan_params
        params["n_points"] = n_points
    else:
        params = default_params.get(plan_name, {"n_points": n_points})

    events = []
    scan_done = asyncio.Event()

    async with websockets.connect(SCAN_URL) as ws:
        # Submit scan
        submit_msg = {
            "action": "submit",
            "plan_name": plan_name,
            "params": params
        }
        await ws.send(json.dumps(submit_msg))
        print(f"Scan submitted: {plan_name} with {params}")

        # Collect events
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                ts_recv = time.time()
                msg = json.loads(raw)

                if msg.get("type") == "scan_event":
                    msg["_ts_client_recv"] = ts_recv
                    events.append(msg)

                    doc_type = msg.get("doc_type", "?")
                    if doc_type == "event":
                        ts_cb = msg.get("_ts_callback", 0)
                        ts_send = msg.get("_ts_send", 0)
                        ts_ws = msg.get("_ts_ws_send", 0)
                        total = (ts_recv - ts_cb) * 1000 if ts_cb else 0
                        print(f"  event #{msg.get('event_count',0):3d} | "
                              f"callback->send: {(ts_send-ts_cb)*1000:.1f}ms | "
                              f"send->ws: {(ts_ws-ts_send)*1000:.1f}ms | "
                              f"ws->client: {(ts_recv-ts_ws)*1000:.1f}ms | "
                              f"TOTAL: {total:.1f}ms")

                    if doc_type == "stop":
                        break

                elif msg.get("type") == "error":
                    print(f"ERROR: {msg.get('message')}")
                    break

        except asyncio.TimeoutError:
            print("TIMEOUT: scan did not complete within 120s")

    return events


async def measure_pv_latency(duration_s=10, motor_pv="BL10:DCM:DTheta2"):
    """Measure PV monitoring pipeline latency by writing to a motor and timing updates."""
    print(f"\n{'='*60}")
    print(f"PV LATENCY MEASUREMENT: {duration_s}s, motor={motor_pv}")
    print(f"{'='*60}")

    pv_events = []

    async with websockets.connect(PV_URL) as ws_pv:
        # Subscribe to the motor readback
        rbv_pv = motor_pv + ".RBV"
        await ws_pv.send(json.dumps({"action": "subscribe", "pv": motor_pv}))
        await ws_pv.send(json.dumps({"action": "subscribe", "pv": rbv_pv}))
        print(f"Subscribed to {motor_pv} and {rbv_pv}")

        # Write small oscillating values to trigger PV updates
        async with websockets.connect(PV_URL) as ws_write:
            start = time.time()
            write_count = 0
            while time.time() - start < duration_s:
                # Write a small offset
                val = 0.001 * (write_count % 2)  # oscillate between 0 and 0.001
                ts_write = time.time()
                await ws_write.send(json.dumps({
                    "action": "put",
                    "pv": motor_pv,
                    "value": val
                }))
                write_count += 1

                # Collect PV updates for ~200ms
                try:
                    while True:
                        raw = await asyncio.wait_for(ws_pv.recv(), timeout=0.25)
                        ts_recv = time.time()
                        msg = json.loads(raw)
                        if msg.get("_ts_pv_send"):
                            latency = (ts_recv - msg["_ts_pv_send"]) * 1000
                            pv_events.append({
                                "pv": msg.get("pv", "?"),
                                "value": msg.get("value"),
                                "ts_write": ts_write,
                                "ts_poll": msg.get("timestamp", 0),
                                "ts_send": msg["_ts_pv_send"],
                                "ts_recv": ts_recv,
                                "latency_send_to_recv_ms": latency,
                                "latency_write_to_recv_ms": (ts_recv - ts_write) * 1000
                            })
                            print(f"  PV update: {msg.get('pv','?')} = {msg.get('value',0):.6f} | "
                                  f"send->recv: {latency:.1f}ms | "
                                  f"write->recv: {(ts_recv-ts_write)*1000:.1f}ms")
                except asyncio.TimeoutError:
                    pass

                await asyncio.sleep(0.15)  # wait before next write

    return pv_events


def analyze_scan_events(events):
    """Compute statistics from scan event latencies."""
    event_docs = [e for e in events if e.get("doc_type") == "event" and e.get("_ts_callback")]

    if not event_docs:
        return None

    totals = []
    cb_to_send = []
    send_to_ws = []
    ws_to_client = []

    for e in event_docs:
        tc = e["_ts_callback"]
        ts = e["_ts_send"]
        tw = e["_ts_ws_send"]
        tr = e["_ts_client_recv"]

        totals.append((tr - tc) * 1000)
        cb_to_send.append((ts - tc) * 1000)
        send_to_ws.append((tw - ts) * 1000)
        ws_to_client.append((tr - tw) * 1000)

    def stats(vals):
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "count": n,
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "stdev": round(statistics.stdev(vals), 2) if n > 1 else 0,
            "p10": round(vals_sorted[int(n*0.1)], 2),
            "p90": round(vals_sorted[int(n*0.9)], 2),
        }

    return {
        "total": stats(totals),
        "callback_to_send": stats(cb_to_send),
        "send_to_ws": stats(send_to_ws),
        "ws_to_client": stats(ws_to_client),
    }


def analyze_pv_events(pv_events):
    """Compute PV latency statistics."""
    if not pv_events:
        return None

    send_to_recv = [e["latency_send_to_recv_ms"] for e in pv_events]
    write_to_recv = [e["latency_write_to_recv_ms"] for e in pv_events]

    def stats(vals):
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "count": n,
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "stdev": round(statistics.stdev(vals), 2) if n > 1 else 0,
            "p10": round(vals_sorted[int(n*0.1)], 2),
            "p90": round(vals_sorted[int(n*0.9)], 2),
        }

    return {
        "send_to_recv": stats(send_to_recv),
        "write_to_recv": stats(write_to_recv),
    }


def format_summary(scan_stats, pv_stats, scan_events, pv_events):
    """Format a human-readable summary."""
    lines = []
    lines.append("=" * 70)
    lines.append("LATENCY MEASUREMENT RESULTS")
    lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Platform: localhost (server + client on same machine)")
    lines.append("=" * 70)

    if scan_stats:
        lines.append("")
        lines.append("1. SCAN EVENT PIPELINE (RunEngine callback -> WebSocket -> client)")
        lines.append(f"   Events measured: {scan_stats['total']['count']}")
        lines.append(f"   Total latency:")
        lines.append(f"     Median: {scan_stats['total']['median']:.1f} ms")
        lines.append(f"     Mean:   {scan_stats['total']['mean']:.1f} ms")
        lines.append(f"     Min:    {scan_stats['total']['min']:.1f} ms")
        lines.append(f"     Max:    {scan_stats['total']['max']:.1f} ms")
        lines.append(f"     P10:    {scan_stats['total']['p10']:.1f} ms")
        lines.append(f"     P90:    {scan_stats['total']['p90']:.1f} ms")
        lines.append(f"   Breakdown (mean):")
        lines.append(f"     RunEngine callback -> async send:  {scan_stats['callback_to_send']['mean']:.1f} ms")
        lines.append(f"     Async send -> WebSocket send:      {scan_stats['send_to_ws']['mean']:.1f} ms")
        lines.append(f"     WebSocket send -> client receive:  {scan_stats['ws_to_client']['mean']:.1f} ms")

    if pv_stats:
        lines.append("")
        lines.append("2. PV MONITORING PIPELINE (IOC -> CA poll -> WebSocket -> client)")
        lines.append(f"   PV updates measured: {pv_stats['send_to_recv']['count']}")
        lines.append(f"   WebSocket send -> client receive:")
        lines.append(f"     Median: {pv_stats['send_to_recv']['median']:.1f} ms")
        lines.append(f"     Mean:   {pv_stats['send_to_recv']['mean']:.1f} ms")
        lines.append(f"     P10:    {pv_stats['send_to_recv']['p10']:.1f} ms")
        lines.append(f"     P90:    {pv_stats['send_to_recv']['p90']:.1f} ms")
        lines.append(f"   Motor write -> client receive (includes ~100ms polling):")
        lines.append(f"     Median: {pv_stats['write_to_recv']['median']:.1f} ms")
        lines.append(f"     Mean:   {pv_stats['write_to_recv']['mean']:.1f} ms")
        lines.append(f"     P10:    {pv_stats['write_to_recv']['p10']:.1f} ms")
        lines.append(f"     P90:    {pv_stats['write_to_recv']['p90']:.1f} ms")
        lines.append(f"   Note: Total PV monitoring latency = polling interval (~100ms)")
        lines.append(f"         + WebSocket transport + JSON serialization")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


async def main():
    print("K4GSR BL10 Virtual Beamline - Latency Measurement")
    print("Connecting to server at localhost:8001...")

    # 1. Scan latency measurement
    try:
        scan_events = await measure_scan_latency(
            plan_name="energy_scan",
            n_points=51,
            e_start=9.9, e_stop=10.1
        )
    except Exception as e:
        print(f"Scan measurement failed: {e}")
        scan_events = []

    scan_stats = analyze_scan_events(scan_events) if scan_events else None

    # 2. PV latency measurement
    try:
        pv_events = await measure_pv_latency(duration_s=10)
    except Exception as e:
        print(f"PV measurement failed: {e}")
        pv_events = []

    pv_stats = analyze_pv_events(pv_events) if pv_events else None

    # 3. Generate reports
    summary = format_summary(scan_stats, pv_stats, scan_events, pv_events)
    print("\n" + summary)

    # Save results
    output_dir = os.path.dirname(__file__)

    results = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S'),
        "scan": {
            "stats": scan_stats,
            "raw_events": [{
                "event_num": e.get("event_count", 0),
                "doc_type": e.get("doc_type"),
                "ts_callback": e.get("_ts_callback"),
                "ts_send": e.get("_ts_send"),
                "ts_ws_send": e.get("_ts_ws_send"),
                "ts_client_recv": e.get("_ts_client_recv"),
            } for e in scan_events if e.get("_ts_callback")]
        },
        "pv": {
            "stats": pv_stats,
            "raw_events": pv_events[:200]  # limit raw data size
        }
    }

    json_path = os.path.join(output_dir, "latency_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw data saved: {json_path}")

    txt_path = os.path.join(output_dir, "latency_summary.txt")
    with open(txt_path, "w") as f:
        f.write(summary)
    print(f"Summary saved: {txt_path}")


if __name__ == "__main__":
    asyncio.run(main())
