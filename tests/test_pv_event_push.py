"""B3 unit test: event-triggered PV push with burst coalescing.

Exercises the REAL server.pv_event_push_loop / server._send_pv_batch /
server._pv_snapshot code paths against a fake CABridge-like store and fake
websocket clients (no CA, no IOC, no network).

Scenario (single asyncio run):
  1. Isolated event       -> leading-edge flush, latency measured.
  2. 1000 rapid changes   -> (a) coalescing: far fewer messages than changes.
     on 5 PVs                (b) every final value is delivered.
  3. Idle period          -> (c) ONLY full-snapshot keepalives are sent.
  4. Schema               -> every entry has the exact key set the old
                              periodic loop sends ({pv, value, severity,
                              timestamp, _ts_pv_send}); cross-checked by
                              actually running the old pv_broadcast_loop.
  5. CABridge.on_change   -> hook fires from _on_rbv_change/_on_status_change
                              (bare instance, no caproto Context needed) and
                              a broken hook does not raise.

Run:  python tests/test_pv_event_push.py     (standalone, prints measurements)
  or: python -m pytest tests/test_pv_event_push.py -v
"""
import asyncio
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'server')))

# Must be set BEFORE the push loop task starts (read at task start).
COALESCE_MS = 50.0
SNAPSHOT_S = 0.5          # fast keepalive so the idle test stays short
os.environ["PV_PUSH_COALESCE_MS"] = str(COALESCE_MS)
os.environ["PV_PUSH_SNAPSHOT_S"] = str(SNAPSHOT_S)

import server  # noqa: E402  (server/server.py)

PV_NAMES = ["BL10:TEST:PV%d" % i for i in range(5)]
N_CHANGES = 1000


class FakeStore:
    """Minimal CABridge-compatible store: dirty-map + get_changed/get_all.

    external_change() mimics a caproto monitor callback firing on a worker
    thread: update value, record dirty entry, invoke on_change hook.
    """

    def __init__(self, pv_names):
        self._lock = threading.Lock()
        self._values = {n: 0.0 for n in pv_names}
        self._changed = {}
        self._motor_names = set()   # _pv_snapshot() reads this (CABridge attr)
        self.on_change = None
        self.pvs = self._values
        self.scan_rate = 0.05       # only used by the OLD periodic loop

    def external_change(self, name, value):
        now = time.time()
        with self._lock:
            self._values[name] = value
            self._changed[name] = {"pv": name, "value": value,
                                   "severity": 0, "timestamp": now}
        cb = self.on_change
        if cb is not None:
            cb(name, value)

    def scan(self):
        pass  # CABridge-style no-op (old loop calls this)

    def get_changed(self):
        with self._lock:
            out = dict(self._changed)
            self._changed.clear()
        return out

    def get_all(self):
        now = time.time()
        with self._lock:
            return {n: {"pv": n, "value": v, "severity": 0, "timestamp": now}
                    for n, v in self._values.items()}


class FakeWS:
    def __init__(self):
        self.messages = []          # list of (recv_monotonic, raw_text)

    async def send(self, text):
        self.messages.append((time.monotonic(), text))


def _entries(messages):
    """Flatten raw websocket texts -> list of per-PV dicts (JSON arrays)."""
    out = []
    for _, raw in messages:
        batch = json.loads(raw)
        assert isinstance(batch, list), "wire format must be a JSON array"
        out.extend(batch)
    return out


async def _event_push_scenario():
    """Run the real pv_event_push_loop against FakeStore; return measurements."""
    store = FakeStore(PV_NAMES)
    ws = FakeWS()
    server._pv_dirty = asyncio.Event()      # fresh Event bound to THIS loop
    server.pv_store = store
    server.pv_clients.clear()
    server.pv_clients[ws] = set(PV_NAMES)   # client subscribed to all 5 PVs

    loop = asyncio.get_running_loop()

    def notify(_name, _value):              # same pattern as server main()
        loop.call_soon_threadsafe(server._pv_dirty.set)

    store.on_change = notify
    task = asyncio.create_task(server.pv_event_push_loop())
    await asyncio.sleep(0.1)                # task up; initial idle

    res = {}

    # ── 1. Isolated event: leading-edge flush latency ─────────────────
    ws.messages.clear()
    t_send = time.monotonic()
    store.external_change(PV_NAMES[0], 111.0)
    for _ in range(200):
        if ws.messages:
            break
        await asyncio.sleep(0.005)
    assert ws.messages, "isolated change was never delivered"
    res["isolated_latency_ms"] = (ws.messages[0][0] - t_send) * 1000.0

    # ── 2. Burst: N_CHANGES rapid changes on 5 PVs (worker thread) ────
    ws.messages.clear()
    final_values = {}

    def burst():
        for i in range(N_CHANGES):
            name = PV_NAMES[i % len(PV_NAMES)]
            val = float(i)
            final_values[name] = val
            store.external_change(name, val)
            time.sleep(0.0005)              # ~2000 changes/s target

    t0 = time.monotonic()
    th = threading.Thread(target=burst)
    th.start()
    while th.is_alive():
        await asyncio.sleep(0.01)
    await asyncio.sleep(3 * COALESCE_MS / 1000.0)   # trailing-window flush
    res["burst_duration_s"] = time.monotonic() - t0
    res["burst_n_messages"] = len(ws.messages)
    res["burst_entries"] = _entries(ws.messages)
    res["final_values"] = dict(final_values)

    # ── 3. Idle: only snapshot keepalives ─────────────────────────────
    ws.messages.clear()
    idle_window = 3.2 * SNAPSHOT_S
    await asyncio.sleep(idle_window)
    res["idle_window_s"] = idle_window
    res["idle_messages"] = list(ws.messages)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return res


async def _old_loop_schema_capture():
    """Run the OLD periodic pv_broadcast_loop briefly; capture one message."""
    store = FakeStore(PV_NAMES)
    ws = FakeWS()
    server.pv_store = store
    server.pv_clients.clear()
    server.pv_clients[ws] = set(PV_NAMES)
    task = asyncio.create_task(server.pv_broadcast_loop())
    store.external_change(PV_NAMES[0], 9.5)   # old loop polls _changed
    for _ in range(100):
        if ws.messages:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert ws.messages, "old periodic loop sent nothing"
    return _entries(ws.messages)


def test_event_push_coalescing_final_values_idle_schema():
    _run_and_check()


def _run_and_check():
    res = asyncio.run(_event_push_scenario())

    # (a) Coalescing: far fewer messages than changes
    n_msgs = res["burst_n_messages"]
    expected_max = res["burst_duration_s"] / (COALESCE_MS / 1000.0) + 3
    assert n_msgs >= 2, "burst should span multiple coalescing windows"
    assert n_msgs <= N_CHANGES / 10, (
        f"coalescing failed: {n_msgs} messages for {N_CHANGES} changes")
    assert n_msgs <= expected_max, (
        f"{n_msgs} messages > rate bound {expected_max:.1f} "
        f"(1 per {COALESCE_MS} ms window)")

    # (b) Every final value delivered (last entry per PV in the burst phase)
    last_seen = {}
    for e in res["burst_entries"]:
        last_seen[e["pv"]] = e["value"]
    for pv, val in res["final_values"].items():
        assert last_seen.get(pv) == val, (
            f"final value lost for {pv}: sent {val}, last delivered "
            f"{last_seen.get(pv)}")

    # (c) Idle period: only full-snapshot keepalives, at the snapshot rate
    idle_msgs = res["idle_messages"]
    n_snap_expected = res["idle_window_s"] / SNAPSHOT_S
    assert 1 <= len(idle_msgs) <= n_snap_expected + 1, (
        f"idle: expected ~{n_snap_expected:.0f} keepalives, "
        f"got {len(idle_msgs)}")
    for _, raw in idle_msgs:
        batch = json.loads(raw)
        pvs_in_msg = {e["pv"] for e in batch}
        assert pvs_in_msg == set(PV_NAMES), (
            f"idle message is not a full snapshot: {sorted(pvs_in_msg)}")

    # (d) Schema identical to the old periodic loop (zero-change browser)
    old_entries = asyncio.run(_old_loop_schema_capture())
    old_keys = set(old_entries[0].keys())
    assert old_keys == {"pv", "value", "severity", "timestamp", "_ts_pv_send"}
    for e in res["burst_entries"] + _entries(res["idle_messages"]):
        assert set(e.keys()) == old_keys, (
            f"schema drift vs old loop: {sorted(e.keys())}")
        assert isinstance(e["pv"], str)
        assert isinstance(e["value"], (int, float))
        assert isinstance(e["severity"], int)
        assert isinstance(e["timestamp"], float)
        assert isinstance(e["_ts_pv_send"], float)

    return res  # for standalone reporting


def test_cabridge_on_change_hook():
    """CABridge subscribe callbacks must fire on_change (no Context needed)."""
    from ca_bridge import CABridge

    br = object.__new__(CABridge)            # bypass __init__ (needs IOC)
    br._lock = threading.Lock()
    br._values = {}
    br._severities = {}
    br._changed = {}
    calls = []
    br.on_change = lambda n, v: calls.append((n, v))

    class FakeResponse:
        data = [4.25]

    br._on_rbv_change("BL10:M1:Pitch", FakeResponse())
    assert br._values["BL10:M1:Pitch"] == 4.25
    assert "BL10:M1:Pitch" in br._changed
    assert "BL10:M1:Pitch.RBV" in br._changed      # .RBV alias preserved
    assert calls == [("BL10:M1:Pitch", 4.25)]

    br._on_status_change("BL10:RING:Current", FakeResponse())
    assert ("BL10:RING:Current", 4.25) in calls

    # A broken hook must never raise into the caproto monitor thread
    br.on_change = lambda n, v: 1 / 0
    br._on_rbv_change("BL10:M1:Pitch", FakeResponse())   # no exception

    # No hook set -> no-op
    br.on_change = None
    br._on_rbv_change("BL10:M1:Pitch", FakeResponse())


if __name__ == "__main__":
    print("=" * 64)
    print("B3 event-push unit test (coalescing / final values / idle / schema)")
    print("=" * 64)
    r = _run_and_check()
    test_cabridge_on_change_hook()
    ratio = N_CHANGES / max(r["burst_n_messages"], 1)
    print(f"isolated-event delivery latency : "
          f"{r['isolated_latency_ms']:.1f} ms (old loop: 0-100 ms poll tick)")
    print(f"burst: {N_CHANGES} changes on 5 PVs in "
          f"{r['burst_duration_s']:.2f} s -> {r['burst_n_messages']} "
          f"messages ({ratio:.0f}x coalescing, window {COALESCE_MS:.0f} ms)")
    print(f"idle {r['idle_window_s']:.1f} s -> {len(r['idle_messages'])} "
          f"full-snapshot keepalive(s), nothing else "
          f"(PV_PUSH_SNAPSHOT_S={SNAPSHOT_S})")
    print("schema: identical key set to old periodic loop "
          "{pv, value, severity, timestamp, _ts_pv_send}")
    print("CABridge.on_change hook: PASS (incl. broken-hook isolation)")
    print("ALL PASS")
