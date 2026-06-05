#!/usr/bin/env python3
"""End-to-end latency measurement for the K4GSR ID10 Hard X-ray Nanoprobe virtual
beamline server (HANBIT). Released publicly so the reported latency tables can be
reproduced.

Measures:
  1. Scan event pipeline:   RunEngine document callback -> /ws/scan -> client recv
  2. PV monitoring pipeline: motor write -> CA bridge -> /ws/pv -> client recv

Usage:
  python tools/measure_latency.py \
      --ws-base ws://localhost:8001 \
      --label localhost \
      --scenario localhost \
      --duration 10 \
      --n-points 51 \
      --out paper/JSR_Paper_review/response/latency_data

Server prerequisites (HANBIT server):
  1) caproto soft IOC:  python server/epics/soft_ioc.py
  2) HANBIT server:      python server/server.py --bluesky
  3) WebSocket endpoints reachable at <ws-base>/ws/scan and <ws-base>/ws/pv

The --label / --scenario tags are written into the output JSON so that multiple
runs (e.g. localhost, intra-testbed LAN, remote NAT) can be combined into one
comparison table.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import urllib.request

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)


def probe_rtt(http_url, n=20, timeout=3):
    """Single-clock TCP RTT estimate (no NTP required).

    Performs N synchronous HTTP GET / requests against `http_url` and returns
    timing statistics. Used to (i) characterise the network path between
    client and server independent of clock sync, and (ii) optionally estimate
    cross-clock offset when only one-way server timestamps are available
    (offset = RTT/2 - apparent_one_way under symmetric-path assumption).
    """
    rtts = []
    for _ in range(n):
        t0 = time.time()
        try:
            with urllib.request.urlopen(http_url, timeout=timeout) as r:
                r.read(0)
            rtts.append((time.time() - t0) * 1000)
        except Exception:
            pass
    if not rtts:
        return None
    s = _stats(rtts); s.update({"unit": "ms", "samples": len(rtts), "url": http_url})
    return s


def _stats(vals):
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return {
        "count": n,
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "stdev": round(statistics.stdev(vals), 2) if n > 1 else 0,
        "p10": round(s[int(n * 0.1)], 2),
        "p90": round(s[int(n * 0.9)], 2),
    }


async def measure_scan_latency(ws_base, plan_name, n_points, **scan_params):
    url = f"{ws_base}/ws/scan"
    print(f"\n[scan] connecting: {url}")
    default = {
        "energy_scan": {"e_start": 9.9, "e_stop": 10.1, "n_points": n_points},
        "alignment_scan": {"motor": "BL10:DCM:DTheta2", "start": -0.01, "stop": 0.01, "n_points": n_points},
    }
    params = dict(scan_params) if scan_params else default.get(plan_name, {"n_points": n_points})
    params["n_points"] = n_points

    events = []
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"action": "submit", "plan_name": plan_name, "params": params}))
        print(f"[scan] submitted {plan_name} {params}")
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
                ts_recv = time.time()
                msg = json.loads(raw)
                if msg.get("type") == "scan_event":
                    msg["_ts_client_recv"] = ts_recv
                    events.append(msg)
                    if msg.get("doc_type") == "event":
                        ts_cb = msg.get("_ts_callback", 0)
                        total = (ts_recv - ts_cb) * 1000 if ts_cb else 0
                        print(f"  event #{msg.get('event_count',0):3d} | total={total:6.1f} ms")
                    if msg.get("doc_type") == "stop":
                        break
                elif msg.get("type") == "error":
                    print(f"[scan] ERROR: {msg.get('message')}")
                    break
        except asyncio.TimeoutError:
            print("[scan] TIMEOUT")
    return events


async def measure_pv_latency(ws_base, duration_s, motor_pv):
    url = f"{ws_base}/ws/pv"
    print(f"\n[pv] connecting: {url}")
    pv_events = []
    async with websockets.connect(url) as ws_pv:
        rbv_pv = motor_pv + ".RBV"
        await ws_pv.send(json.dumps({"action": "subscribe", "pv": motor_pv}))
        await ws_pv.send(json.dumps({"action": "subscribe", "pv": rbv_pv}))
        print(f"[pv] subscribed: {motor_pv}, {rbv_pv}")
        async with websockets.connect(url) as ws_write:
            start = time.time()
            wc = 0
            while time.time() - start < duration_s:
                val = 0.001 * (wc % 2)
                ts_write = time.time()
                await ws_write.send(json.dumps({"action": "put", "pv": motor_pv, "value": val}))
                wc += 1
                try:
                    while True:
                        raw = await asyncio.wait_for(ws_pv.recv(), timeout=0.25)
                        ts_recv = time.time()
                        msg = json.loads(raw)
                        # Server may send a list (batched updates) or a dict.
                        items = msg if isinstance(msg, list) else [msg]
                        for it in items:
                            if not isinstance(it, dict):
                                continue
                            ts_send = it.get("_ts_pv_send")
                            if ts_send is None:
                                continue
                            lat = (ts_recv - ts_send) * 1000
                            pv_events.append({
                                "pv": it.get("pv", "?"),
                                "value": it.get("value"),
                                "ts_write": ts_write,
                                "ts_send": ts_send,
                                "ts_recv": ts_recv,
                                "latency_send_to_recv_ms": lat,
                                "latency_write_to_recv_ms": (ts_recv - ts_write) * 1000,
                            })
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.15)
    return pv_events


def analyze_scan(events):
    docs = [e for e in events if e.get("doc_type") == "event" and e.get("_ts_callback")]
    if not docs:
        return None
    totals = [(e["_ts_client_recv"] - e["_ts_callback"]) * 1000 for e in docs]
    cb2send = [(e["_ts_send"] - e["_ts_callback"]) * 1000 for e in docs]
    send2ws = [(e["_ts_ws_send"] - e["_ts_send"]) * 1000 for e in docs]
    ws2cl = [(e["_ts_client_recv"] - e["_ts_ws_send"]) * 1000 for e in docs]
    return {
        "total": _stats(totals),
        "callback_to_send": _stats(cb2send),
        "send_to_ws": _stats(send2ws),
        "ws_to_client": _stats(ws2cl),
    }


def analyze_pv(pv_events):
    if not pv_events:
        return None
    return {
        "send_to_recv": _stats([e["latency_send_to_recv_ms"] for e in pv_events]),
        "write_to_recv": _stats([e["latency_write_to_recv_ms"] for e in pv_events]),
    }


def format_summary(label, scenario, scan_stats, pv_stats):
    L = []
    L.append("=" * 70)
    L.append(f"LATENCY MEASUREMENT  label={label}  scenario={scenario}")
    L.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("=" * 70)
    if scan_stats:
        s = scan_stats["total"]
        L.append(f"[scan] total ms  n={s['count']}  median={s['median']}  mean={s['mean']}  "
                 f"min={s['min']}  max={s['max']}  p10={s['p10']}  p90={s['p90']}")
        for k in ("callback_to_send", "send_to_ws", "ws_to_client"):
            v = scan_stats[k]
            L.append(f"  {k:18s} median={v['median']}  mean={v['mean']}  max={v['max']}")
    if pv_stats:
        for k in ("send_to_recv", "write_to_recv"):
            v = pv_stats[k]
            L.append(f"[pv] {k:14s} n={v['count']}  median={v['median']}  mean={v['mean']}  "
                     f"max={v['max']}  p10={v['p10']}  p90={v['p90']}")
    return "\n".join(L)


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ws-base", default="ws://localhost:8001",
                    help="WebSocket base URL, e.g. ws://v.v.v.v:8001")
    ap.add_argument("--label", default=None,
                    help="Short tag stored in the output JSON (default derived from --ws-base host)")
    ap.add_argument("--scenario", default="custom",
                    choices=["localhost", "lan", "remote", "custom"],
                    help="Scenario tag: localhost (same machine), lan (intra-testbed), "
                         "remote (across campus/NAT)")
    ap.add_argument("--duration", type=float, default=10.0,
                    help="PV monitoring duration (seconds)")
    ap.add_argument("--n-points", type=int, default=51, help="Energy scan points")
    ap.add_argument("--motor", default="BL10:DCM:DTheta2",
                    help="PV used for the PV monitoring measurement")
    ap.add_argument("--out", default=None,
                    help="Output directory for *.json and *.txt (default: cwd)")
    ap.add_argument("--skip-scan", action="store_true")
    ap.add_argument("--skip-pv", action="store_true")
    ap.add_argument("--rtt-probe", type=int, default=20,
                    help="Number of HTTP GET / probes used to measure the "
                         "single-clock TCP RTT (set 0 to disable)")
    return ap.parse_args()


async def amain(args):
    label = args.label or args.ws_base.replace("ws://", "").replace("/", "_")
    print(f"label={label}  scenario={args.scenario}  ws_base={args.ws_base}")

    # Single-clock TCP RTT probe: lets us characterise the network path and
    # estimate cross-host clock offset without needing NTP.
    rtt_stats = None
    if args.rtt_probe > 0:
        http_url = args.ws_base.replace("ws://", "http://").replace("wss://", "https://")
        if not http_url.endswith("/"):
            http_url += "/"
        print(f"\n[rtt] probing {http_url} (n={args.rtt_probe}) ...")
        rtt_stats = probe_rtt(http_url, n=args.rtt_probe)
        if rtt_stats:
            print(f"[rtt] median={rtt_stats['median']} ms  min={rtt_stats['min']} ms  "
                  f"max={rtt_stats['max']} ms  (n={rtt_stats['samples']})")

    scan_events = []
    if not args.skip_scan:
        try:
            scan_events = await measure_scan_latency(args.ws_base, "energy_scan", args.n_points)
        except Exception as e:
            print(f"[scan] failed: {e}")
    scan_stats = analyze_scan(scan_events)

    pv_events = []
    if not args.skip_pv:
        try:
            pv_events = await measure_pv_latency(args.ws_base, args.duration, args.motor)
        except Exception as e:
            print(f"[pv] failed: {e}")
    pv_stats = analyze_pv(pv_events)

    summary = format_summary(label, args.scenario, scan_stats, pv_stats)
    print("\n" + summary)

    out_dir = args.out or "."
    os.makedirs(out_dir, exist_ok=True)
    base = f"latency_{args.scenario}_{label.replace(':','_').replace('.','_')}"
    json_path = os.path.join(out_dir, base + ".json")
    txt_path = os.path.join(out_dir, base + ".txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S'),
            "label": label,
            "scenario": args.scenario,
            "ws_base": args.ws_base,
            "tcp_rtt": rtt_stats,
            "scan": {"stats": scan_stats,
                     "raw_events": [{
                         "event_num": e.get("event_count", 0),
                         "doc_type": e.get("doc_type"),
                         "ts_callback": e.get("_ts_callback"),
                         "ts_send": e.get("_ts_send"),
                         "ts_ws_send": e.get("_ts_ws_send"),
                         "ts_client_recv": e.get("_ts_client_recv"),
                     } for e in scan_events if e.get("_ts_callback")]},
            "pv": {"stats": pv_stats, "raw_events": pv_events[:300]},
        }, f, indent=2)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\nsaved: {json_path}\nsaved: {txt_path}")


if __name__ == "__main__":
    asyncio.run(amain(parse_args()))
