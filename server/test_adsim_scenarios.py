#!/usr/bin/env python3
"""ADSim operations-scenario validation (Phase-1 C1): five PASS/FAIL scenarios.

Standalone script, run ON VM1 (the ADSim IOC is loopback-only on CA port
5080; HDF5 files are written locally by the IOC). Follows the C1 E2E + load
test (`server/test_adsim_bluesky.py`); this script validates OPERATIONS
behavior on top of the proven data path:

    S1  Back-to-back runs      5 consecutive count(det, num=3) in ONE
                               RunEngine session -> 5 distinct HDF5 files,
                               (3,1024,1024) each, no stale Capture state.
    S2  Abort mid-scan         count(det, num=50) paused after exactly 5
                               events (custom plan wrapper), RE.abort() ->
                               clean 'abort' stop doc, IOC still responsive,
                               partial HDF5 readable (frame count checked),
                               follow-up count(num=3) succeeds.
    S3  IOC restart resilience kill + restart the IOC, then count(num=3)
                               with the SAME ophyd device object (CA
                               reconnect; bounded wait_for_connection).
    S4  Concurrent reader      second PROCESS polls cam1:ArrayCounter_RBV
                               at 5 Hz during a 100-frame count() on the
                               same loopback CA -> no timeouts, monotonic.
    S5  Hybrid dual-IOC scan   ONE grid_scan drives the REAL production
                               soft-IOC motor BL10:DET:Z (CA 5064) and the
                               ADSim detector (CA 5080) in the same process,
                               then RESTORES the motor (caget within 1 MRES).
                               This is the zero-change hybrid-mode core the
                               paper's Phase-2 plan needs.

IOC lifecycle is managed BY THIS SCRIPT (fresh start at boot, kill+restart
inside S3, kill at exit unless --keep-ioc) so process groups can be killed
cleanly (no orphan `tail -f /dev/null`).

CA environment: BOTH entries are required before the first CA connection —
    127.0.0.1        -> production soft IOC on the default port 5064 (S5)
    127.0.0.1:5080   -> ADSim IOC (ensure_adsim_ca_env)
EPICS_CA_SERVER_PORT is never touched (process-wide override would redirect
production CA traffic — see ad_devices.py docstring).

PRODUCTION SAFETY: the only production PV written is BL10:DET:Z (simulated
motor on the caproto soft IOC) — small moves inside its soft limits, position
restored and verified afterward. Ports 8001/8002/5064 servers untouched.

Usage (from ~/K4GSR-Beamline):
    .venv/bin/python server/test_adsim_scenarios.py
    .venv/bin/python server/test_adsim_scenarios.py --keep-ioc --keep-files

Note (S1 "sequential file numbering"): FileStoreHDF5IterativeWrite re-stages
NDFileHDF5 FileNumber to 0 with a FRESH uuid file name on every run (ophyd
filestore design — one file per run, `<uuid>_000000.h5`). Sequencing across
runs is therefore verified as: 5 distinct names + strictly increasing file
mtimes + per-run sequential datum point numbers (0,1,2) + FileNumber_RBV
returning to the same post-run value (1) every run (no stale increment).
"""

import os
import sys
import json
import time
import signal
import argparse
import threading
import subprocess
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── CA env: BOTH production (5064 default port) and ADSim (5080) ─────────
from scan_engine.ad_devices import (  # noqa: E402
    ensure_adsim_ca_env, get_adsim_detector, prime_hdf5_plugin,
    ADSIM_PREFIX, ADSIM_DATA_DIR)


def ensure_dual_ca_env():
    """Production 5064 (plain host entry) + ADSim 5080, AUTO=NO."""
    addr = os.environ.get("EPICS_CA_ADDR_LIST", "")
    if "127.0.0.1" not in addr.split():
        os.environ["EPICS_CA_ADDR_LIST"] = (addr + " 127.0.0.1").strip()
    ensure_adsim_ca_env()  # appends 127.0.0.1:5080, pins AUTO=NO


ensure_dual_ca_env()  # MUST precede the first CA connection (env snapshot)

# NOTE: server/epics (soft-IOC package) shadows pyepics when server/ is on
# sys.path — ophyd therefore runs on its CAPROTO control layer here (same
# configuration the C1 E2E validated). Ad-hoc gets below use a caproto
# threading-client Context as well; do NOT `import epics` in this script.
_ctx = None
_pv_cache = {}


def _caget(pvname, timeout=2.0):
    """caproto threading-client get; returns None on timeout/disconnect."""
    global _ctx
    if _ctx is None:
        from caproto.threading.client import Context
        _ctx = Context()
    try:
        if pvname not in _pv_cache:
            (_pv_cache[pvname],) = _ctx.get_pvs(pvname)
        pv = _pv_cache[pvname]
        pv.wait_for_connection(timeout=timeout)
        val = pv.read(timeout=timeout).data[0]
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


H5_DATASET = "entry/data/data"
MOTOR_PV = os.environ.get("ADSIM_S5_MOTOR", "BL10:DET:Z")
IOC_DIR = os.path.expanduser("~/ADSim_build/iocSim")
IOC_LOG = os.path.expanduser("~/ADSim_build/logs/ioc.log")
PING_PV = ADSIM_PREFIX + "cam1:Manufacturer_RBV"


# ═══════════════════════════════════════════════════════════════════════
# IOC lifecycle (script-managed so process groups die cleanly)
# ═══════════════════════════════════════════════════════════════════════
_ioc_proc = None


def _ioc_binary():
    """simDetectorApp path from the st.cmd shebang (env-overridable)."""
    env_bin = os.environ.get("ADSIM_IOC_BIN")
    if env_bin:
        return env_bin
    with open(os.path.join(IOC_DIR, "st.cmd")) as f:
        first = f.readline().strip()
    if not first.startswith("#!"):
        raise RuntimeError(f"st.cmd has no shebang: {first!r}")
    return first[2:].strip()


def _ioc_pgids():
    """Process-group ids of any running simDetectorApp (incl. bash wrapper)."""
    r = subprocess.run(["pgrep", "-f", "simDetectorApp"],
                       capture_output=True, text=True)
    pgids = set()
    own = os.getpgid(0)
    for pid in r.stdout.split():
        rr = subprocess.run(["ps", "-o", "pgid=", "-p", pid],
                            capture_output=True, text=True)
        s = rr.stdout.strip()
        if s and int(s) != own:
            pgids.add(int(s))
    return pgids


def kill_ioc(grace=8.0):
    """SIGTERM the IOC process group(s), escalate to SIGKILL."""
    global _ioc_proc
    pgids = _ioc_pgids()
    for pgid in pgids:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    t0 = time.monotonic()
    while time.monotonic() - t0 < grace:
        if not _ioc_pgids():
            _ioc_proc = None
            return True
        time.sleep(0.3)
    for pgid in _ioc_pgids():
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
    _ioc_proc = None
    return not _ioc_pgids()


def start_ioc(ready_timeout=60.0):
    """Start the IOC (tail|simDetectorApp pattern) and wait for CA-ready.

    Returns seconds from process start to first successful caget."""
    global _ioc_proc
    os.makedirs(os.path.dirname(IOC_LOG), exist_ok=True)
    logf = open(IOC_LOG, "ab")
    _ioc_proc = subprocess.Popen(
        ["bash", "-c", f"tail -f /dev/null | {_ioc_binary()} st.cmd"],
        cwd=IOC_DIR, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < ready_timeout:
        if _caget(PING_PV, timeout=1.0) is not None:
            return time.monotonic() - t0
        time.sleep(0.5)
    raise RuntimeError(f"IOC not CA-ready within {ready_timeout}s "
                       f"(see {IOC_LOG})")


def ioc_responsive():
    v = _caget(PING_PV, timeout=2.0)
    return v is not None, v


# ═══════════════════════════════════════════════════════════════════════
# Bluesky document collector (counts + event payloads)
# ═══════════════════════════════════════════════════════════════════════
class DocCollector:
    def __init__(self):
        self.counts = Counter()
        self.start_doc = None
        self.stop_doc = None
        self.events = []
        self.datum_points = []

    def __call__(self, name, doc):
        self.counts[name] += 1
        if name == "start":
            self.start_doc = doc
        elif name == "stop":
            self.stop_doc = doc
        elif name == "event":
            self.events.append(doc)
        elif name == "datum":
            self.datum_points.append(doc.get("datum_kwargs", {})
                                     .get("point_number"))

    def summary(self):
        order = ["start", "descriptor", "resource", "datum", "event", "stop"]
        parts = [f"{k}={self.counts.get(k, 0)}" for k in order]
        status = (self.stop_doc.get("exit_status", "?")
                  if self.stop_doc else "NO-STOP")
        return " ".join(parts) + f" exit_status={status}"


def h5_frames(path, expect_xy=(1024, 1024)):
    """(n_frames, detail) of an IOC-written HDF5 file; (-1, why) on error."""
    import h5py
    if not path or not os.path.isfile(path):
        return -1, f"file missing: {path!r}"
    try:
        with h5py.File(path, "r") as f:
            if H5_DATASET not in f:
                return -1, f"dataset {H5_DATASET} missing (keys: {list(f)})"
            shape = f[H5_DATASET].shape
    except Exception as e:
        return -1, f"h5py open failed: {e}"
    if tuple(shape[1:]) != tuple(expect_xy):
        return -1, f"bad frame shape {shape}"
    return shape[0], (f"{os.path.basename(path)} shape={shape} "
                      f"({os.path.getsize(path)/1e6:.1f} MB)")


# ═══════════════════════════════════════════════════════════════════════
# S1 — Back-to-back runs (one RunEngine session)
# ═══════════════════════════════════════════════════════════════════════
def s1_back_to_back(RE, det, files):
    from bluesky.plans import count
    runs, problems = [], []
    for i in range(5):
        col = DocCollector()
        RE(count([det], num=3), col)
        path = det.hdf5.full_file_name.get()
        files.append(path)
        cap = int(det.hdf5.capture.get())          # stale-state probe
        ncap = int(det.hdf5.num_captured.get())
        fnum = int(det.hdf5.file_number.get())
        nfr, detail = h5_frames(path)
        mtime = os.path.getmtime(path) if os.path.isfile(path) else 0
        runs.append(dict(path=path, cap=cap, ncap=ncap, fnum=fnum,
                         nfr=nfr, mtime=mtime, col=col, detail=detail))
        if col.stop_doc.get("exit_status") != "success":
            problems.append(f"run{i+1} exit={col.stop_doc.get('exit_status')}")
        if col.counts["event"] != 3 or col.counts["datum"] != 3:
            problems.append(f"run{i+1} docs: {col.summary()}")
        if nfr != 3:
            problems.append(f"run{i+1} frames={nfr} ({detail})")
        if cap != 0:
            problems.append(f"run{i+1} stale Capture={cap} after unstage")
        if ncap != 3:
            problems.append(f"run{i+1} NumCaptured_RBV={ncap}")
        if sorted(col.datum_points) != [0, 1, 2]:
            problems.append(f"run{i+1} datum points {col.datum_points}")
    names = [r["path"] for r in runs]
    if len(set(names)) != 5:
        problems.append(f"files not distinct: {names}")
    mtimes = [r["mtime"] for r in runs]
    if not all(b > a for a, b in zip(mtimes, mtimes[1:])):
        problems.append(f"file mtimes not strictly increasing: {mtimes}")
    fnums = [r["fnum"] for r in runs]
    if len(set(fnums)) != 1:  # filestore re-stages 0 -> RBV 1 every run
        problems.append(f"FileNumber_RBV drifted across runs: {fnums}")
    ev = (f"5 runs OK: files={[os.path.basename(n) for n in names]} "
          f"all (3,1024,1024); Capture=0 + NumCaptured=3 + FileNumber_RBV="
          f"{fnums[0]} after every run; datum points 0..2 each; "
          f"mtimes strictly increasing")
    return not problems, (ev if not problems else "; ".join(problems))


# ═══════════════════════════════════════════════════════════════════════
# S2 — Abort mid-scan (pause after exactly 5 events, then RE.abort())
# ═══════════════════════════════════════════════════════════════════════
def _abortable_count(dets, num, pause_after):
    """count()-like plan that hard-pauses after `pause_after` events."""
    from bluesky import plan_stubs as bps, preprocessors as bpp

    @bpp.stage_decorator(dets)
    @bpp.run_decorator(md={"plan_name": "abortable_count"})
    def inner():
        for i in range(num):
            yield from bps.checkpoint()
            yield from bps.one_shot(dets)
            if i + 1 == pause_after:
                yield from bps.pause()
    return (yield from inner())


def s2_abort_midscan(RE, det, files):
    from bluesky.plans import count
    from bluesky.utils import RunEngineInterrupted
    problems = []

    col = DocCollector()
    interrupted = False
    try:
        RE(_abortable_count([det], 50, 5), col)
    except RunEngineInterrupted:
        interrupted = True
    if not interrupted:
        problems.append("plan completed without pausing")
    if RE.state != "paused":
        problems.append(f"RE.state={RE.state!r} after pause (want 'paused')")
    if RE.state == "paused":
        RE.abort(reason="S2 scenario: abort after 5/50 events")
    t0 = time.monotonic()
    while RE.state != "idle" and time.monotonic() - t0 < 15:
        time.sleep(0.1)
    if RE.state != "idle":
        problems.append(f"RE.state={RE.state!r} after abort (want 'idle')")
    status = col.stop_doc.get("exit_status") if col.stop_doc else "NO-STOP"
    if status != "abort":
        problems.append(f"stop doc exit_status={status!r} (want 'abort')")

    ok_ioc, manu = ioc_responsive()
    if not ok_ioc:
        problems.append("IOC unresponsive after abort (caget Manufacturer_RBV)")

    part = det.hdf5.full_file_name.get()
    files.append(part)
    nfr, detail = h5_frames(part)
    if nfr < 0:
        problems.append(f"partial file unreadable: {detail}")
    elif nfr != col.counts["event"]:
        problems.append(f"partial frames={nfr} != events={col.counts['event']}")

    col2 = DocCollector()
    RE(count([det], num=3), col2)
    f2 = det.hdf5.full_file_name.get()
    files.append(f2)
    nfr2, detail2 = h5_frames(f2)
    if col2.stop_doc.get("exit_status") != "success" or nfr2 != 3:
        problems.append(f"follow-up count failed: {col2.summary()} / {detail2}")

    ev = (f"paused after {col.counts['event']} events, abort clean "
          f"(exit_status={status}, RE idle); IOC responsive "
          f"(Manufacturer={manu!r}); partial file intact with {nfr} frames "
          f"({detail}); follow-up count(3) OK ({detail2})")
    return not problems, (ev if not problems else "; ".join(problems))


# ═══════════════════════════════════════════════════════════════════════
# S3 — IOC restart resilience (same device object, CA reconnect)
# ═══════════════════════════════════════════════════════════════════════
def s3_ioc_restart(RE, det, files):
    from bluesky.plans import count
    problems = []

    col0 = DocCollector()                      # pre-restart successful run
    RE(count([det], num=3), col0)
    files.append(det.hdf5.full_file_name.get())
    if col0.stop_doc.get("exit_status") != "success":
        problems.append(f"pre-restart run failed: {col0.summary()}")

    if not kill_ioc():
        problems.append("IOC did not die")
    down = _caget(PING_PV, timeout=2.0) is None
    if not down:
        problems.append("IOC still answers CA after kill")

    t0 = time.monotonic()
    ca_ready = start_ioc(ready_timeout=60.0)   # boot -> first caget
    reconn = None
    for attempt in range(3):                   # bounded reconnect wait
        try:
            det.wait_for_connection(timeout=30.0)
            reconn = time.monotonic() - t0
            break
        except Exception as e:
            if attempt == 2:
                problems.append(f"wait_for_connection failed 3x: {e}")
    primed = prime_hdf5_plugin(det)            # plugin is unprimed post-boot

    col = DocCollector()
    RE(count([det], num=3), col)               # SAME device object
    path = det.hdf5.full_file_name.get()
    files.append(path)
    nfr, detail = h5_frames(path)
    if col.stop_doc.get("exit_status") != "success" or nfr != 3:
        problems.append(f"post-restart run failed: {col.summary()} / {detail}")

    ev = (f"IOC killed (CA dead confirmed) + restarted: CA-ready {ca_ready:.1f}s, "
          f"device reconnected {reconn:.1f}s after boot "
          f"(same ophyd object, re-primed={primed}); "
          f"count(3) OK ({detail})" if reconn is not None else
          f"reconnect failed; " + "; ".join(problems))
    return not problems, (ev if not problems else "; ".join(problems))


# ═══════════════════════════════════════════════════════════════════════
# S4 — Concurrent reader (second process polls ArrayCounter_RBV at 5 Hz)
# ═══════════════════════════════════════════════════════════════════════
_POLLER_SRC = r"""
import os, sys, time, json
pvname, sentinel, max_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
from caproto.threading.client import Context   # independent CA client
ctx = Context()
(pv,) = ctx.get_pvs(pvname)
try:
    pv.wait_for_connection(timeout=10)
    print("POLLER-READY", flush=True)
except Exception:
    print("POLLER-NOCONN", flush=True)
samples, timeouts = [], 0
t0 = time.time()
while time.time() - t0 < max_s and not os.path.exists(sentinel):
    try:
        samples.append(int(pv.read(timeout=1.0).data[0]))
    except Exception:
        timeouts += 1
    time.sleep(0.2)
mono = all(b >= a for a, b in zip(samples, samples[1:]))
print(json.dumps({"n": len(samples), "timeouts": timeouts,
                  "monotonic": mono,
                  "first": samples[0] if samples else None,
                  "last": samples[-1] if samples else None}), flush=True)
"""


def s4_concurrent_reader(RE, det, files):
    from bluesky.plans import count
    problems = []
    sentinel = os.path.join(ADSIM_DATA_DIR, f".s4_done_{os.getpid()}")
    if os.path.exists(sentinel):
        os.remove(sentinel)

    lines = []
    proc = subprocess.Popen(
        [sys.executable, "-c", _POLLER_SRC,
         ADSIM_PREFIX + "cam1:ArrayCounter_RBV", sentinel, "300"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    reader = threading.Thread(
        target=lambda: [lines.append(l.rstrip()) for l in proc.stdout],
        daemon=True)
    reader.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 20 and "POLLER-READY" not in lines:
        if "POLLER-NOCONN" in lines:
            break
        time.sleep(0.2)
    if "POLLER-READY" not in lines:
        problems.append(f"poller did not connect: {lines}")

    col = DocCollector()
    t_run = time.monotonic()
    RE(count([det], num=100), col)
    run_s = time.monotonic() - t_run
    path = det.hdf5.full_file_name.get()
    files.append(path)
    nfr, detail = h5_frames(path)
    if col.stop_doc.get("exit_status") != "success" or nfr != 100:
        problems.append(f"100-frame run failed: {col.summary()} / {detail}")

    open(sentinel, "w").close()                # stop the poller
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        problems.append("poller did not exit")
    reader.join(timeout=5)
    if os.path.exists(sentinel):
        os.remove(sentinel)

    res = None
    for line in reversed(lines):
        if line.startswith("{"):
            res = json.loads(line)
            break
    if res is None:
        problems.append(f"no poller result: {lines}")
    else:
        if res["timeouts"] != 0:
            problems.append(f"poller CA timeouts: {res['timeouts']}")
        if not res["monotonic"]:
            problems.append("poller counters not monotonic")
        if res["n"] < 10 or res["last"] is None or res["last"] <= res["first"]:
            problems.append(f"poller saw too little: {res}")

    ev = (f"100-frame count in {run_s:.1f}s ({detail}); concurrent poller "
          f"(separate process, 5 Hz): {res['n']} samples, 0 timeouts, "
          f"monotonic counter {res['first']} -> {res['last']}"
          if res else "no poller result")
    return not problems, (ev if not problems else "; ".join(problems))


# ═══════════════════════════════════════════════════════════════════════
# S5 — Hybrid dual-IOC grid_scan (production motor 5064 + ADSim det 5080)
# ═══════════════════════════════════════════════════════════════════════
def s5_hybrid_dual_ioc(RE, det, files):
    from bluesky.plans import grid_scan
    from ophyd import EpicsMotor
    problems = []

    motor = EpicsMotor(MOTOR_PV, name="detz")
    motor.wait_for_connection(timeout=10.0)
    initial = float(motor.user_readback.get())                    # FIRST
    mres = float(_caget(MOTOR_PV + ".MRES", timeout=3.0) or 1e-6)
    llm = float(_caget(MOTOR_PV + ".LLM", timeout=3.0))
    hlm = float(_caget(MOTOR_PV + ".HLM", timeout=3.0))
    span, pad = 1.0, 0.05
    center = min(max(initial, llm + span + pad), hlm - span - pad)
    if abs(center - initial) > 1e-9:
        print(f"  [S5] +/-{span} mm window shifted inside soft limits "
              f"[{llm}, {hlm}]: center {initial} -> {center}")

    delta = None
    try:
        col = DocCollector()
        RE(grid_scan([det], motor, center - span, center + span, 3), col)
        path = det.hdf5.full_file_name.get()
        files.append(path)
        nfr, detail = h5_frames(path)
        if col.stop_doc.get("exit_status") != "success":
            problems.append(f"grid_scan failed: {col.summary()}")
        if col.counts["event"] != 3 or nfr != 3:
            problems.append(f"events={col.counts['event']} frames={nfr}")
        rbs = []
        for n, ev_doc in enumerate(col.events):
            data = ev_doc.get("data", {})
            if "detz" not in data or "adsim_image" not in data:
                problems.append(f"event {n+1} missing motor/detector key: "
                                f"{sorted(data)}")
            else:
                rbs.append(float(data["detz"]))
        targets = [center - span, center, center + span]
        if rbs and any(abs(r - t) > 1e-3 for r, t in zip(rbs, targets)):
            problems.append(f"motor readbacks {rbs} != targets {targets}")
    finally:
        # ALWAYS restore the production motor, even if the scan blew up
        try:
            motor.move(initial, wait=True, timeout=60.0)
        except Exception as e:
            problems.append(f"restore move failed: {e}")
        rbv = _caget(MOTOR_PV + ".RBV", timeout=3.0)   # fresh CA read
        if rbv is None:
            problems.append("restore verify caget failed")
        else:
            delta = abs(float(rbv) - initial)
            if delta > mres:
                problems.append(f"motor NOT restored: |{rbv} - {initial}| "
                                f"= {delta} > 1 MRES ({mres})")

    ev = (f"one RunEngine drove {MOTOR_PV} (soft IOC :5064) + ADSim det "
          f"(:5080): 3 events each with motor readback + detector datum "
          f"(readbacks {rbs}); {detail}; motor restored to {initial} "
          f"(caget delta {delta:.2e} <= 1 MRES {mres:.0e})")
    return not problems, (ev if not problems else
                          "; ".join(problems) +
                          f" [restore delta={delta}]")


# ═══════════════════════════════════════════════════════════════════════
# Artifact cleanup — keep ONE file per scenario, delete the rest
# ═══════════════════════════════════════════════════════════════════════
def cleanup_files(created, keep_all=False):
    print("\n=== HDF5 artifacts ===")
    for label, paths in created.items():
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            continue
        keep = paths[0]
        print(f"  {label}: keep {os.path.basename(keep)} "
              f"({os.path.getsize(keep)/1e6:.1f} MB)")
        if keep_all:
            continue
        for p in paths[1:]:
            try:
                os.remove(p)
                print(f"          rm   {os.path.basename(p)}")
            except OSError as e:
                print(f"          rm FAILED {p}: {e}")


# ═══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep-ioc", action="store_true",
                    help="leave the ADSim IOC running at exit")
    ap.add_argument("--keep-files", action="store_true",
                    help="keep every HDF5 file (default: one per scenario)")
    ap.add_argument("--only", nargs="*", default=None,
                    metavar="S#", help="run only these scenarios (e.g. S2 S5)")
    args = ap.parse_args()

    print(f"EPICS_CA_ADDR_LIST = {os.environ['EPICS_CA_ADDR_LIST']}")
    print(f"EPICS_CA_AUTO_ADDR_LIST = {os.environ['EPICS_CA_AUTO_ADDR_LIST']}")

    # Fresh IOC owned by this script (clean process-group kills)
    if _ioc_pgids():
        print("[ioc] killing pre-existing ADSim IOC...")
        kill_ioc()
    boot = start_ioc()
    print(f"[ioc] started, CA-ready in {boot:.1f}s")

    from bluesky import RunEngine
    RE = RunEngine({})                          # ONE session for everything
    t0 = time.monotonic()
    det = get_adsim_detector()                  # connect + prime
    print(f"[det] connected+primed in {time.monotonic() - t0:.1f}s")

    scenarios = [
        ("S1", "back-to-back runs", s1_back_to_back),
        ("S2", "abort mid-scan", s2_abort_midscan),
        ("S3", "IOC restart resilience", s3_ioc_restart),
        ("S4", "concurrent reader", s4_concurrent_reader),
        ("S5", "hybrid dual-IOC grid_scan", s5_hybrid_dual_ioc),
    ]
    created = {}
    results = []
    for sid, label, fn in scenarios:
        if args.only and sid not in args.only:
            continue
        print(f"\n--- {sid} {label} ---")
        files = created.setdefault(f"{sid} {label}", [])
        try:
            if _caget(PING_PV, timeout=2.0) is None:        # S3 fallout guard
                print(f"[{sid}] IOC down before scenario — restarting")
                start_ioc()
                det.wait_for_connection(timeout=30.0)
                prime_hdf5_plugin(det)
            ok, evidence = fn(RE, det, files)
        except Exception as e:
            import traceback
            traceback.print_exc()
            ok, evidence = False, f"exception: {e!r}"
            if RE.state != "idle":              # leave RE usable for the next
                try:
                    RE.abort(reason=f"{sid} exception cleanup")
                except Exception:
                    pass
        results.append((sid, label, ok, evidence))
        print(f"[{'PASS' if ok else 'FAIL'}] {sid} {label}\n    {evidence}")

    cleanup_files(created, keep_all=args.keep_files)

    if not args.keep_ioc:
        kill_ioc()
        print("[ioc] killed at exit")

    print("\n=== SCENARIO SUMMARY ===")
    n_fail = 0
    for sid, label, ok, _ in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {sid} {label}")
        n_fail += 0 if ok else 1
    print(f"\n{'ALL 5 SCENARIOS PASS' if n_fail == 0 else f'{n_fail} FAILURE(S)'}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
