#!/usr/bin/env python3
"""ADSim detector E2E test: ophyd device -> Bluesky plans -> HDF5 files.

Standalone script, run ON VM1 (the ADSim IOC is loopback-only on CA port
5080; the HDF5 files are written to the local filesystem by the IOC).

Prerequisite: the ADSim IOC is running —
    cd ~/ADSim_build/iocSim
    nohup bash -c "tail -f /dev/null | \
      /usr/local/epics/EPICS_R7.0/modules/synApps/support/areaDetector-R3-12-1/\
ADSimDetector/iocs/simDetectorIOC/bin/linux-x86_64/simDetectorApp st.cmd" \
      > ~/ADSim_build/logs/ioc.log 2>&1 &

Usage (from ~/K4GSR-Beamline):
    .venv/bin/python server/test_adsim_bluesky.py               # E2E: count + grid_scan
    .venv/bin/python server/test_adsim_bluesky.py --num 5
    .venv/bin/python server/test_adsim_bluesky.py --load 12     # + throughput bursts
    .venv/bin/python server/test_adsim_bluesky.py --load-only 12

What it verifies:
    1. count([det], num=N): document stream (start/descriptor/event/stop +
       resource/datum) counts, one HDF5 file with N frames of the right shape.
    2. grid_scan([det], motor1, motor2) with 2 ophyd.sim soft motors
       (3x3 = 9 points): same checks, 9 frames in one file.
    3. --load: sustained-throughput bursts (Continuous acquire + HDF5 Stream
       capture) to /dev/shm (ramdisk) vs ~/ADSim_build/data (disk) for
       UInt8 / UInt16 / Float32 1024x1024 frames; reports driver MB/s vs
       HDF5-written MB/s and dropped frames. Ramdisk files are deleted.
       Each burst is BUDGET-LIMITED (finite NumCapture sized to <=40% of the
       free space on the target) — an unbounded 12 s burst at ~700 MB/s
       filled the 7.8 GB tmpfs, the HDF5 close failed with ENOSPC, the IOC
       pinned the deleted file's fd and then SEGFAULTED (observed 2026-06-12).
       Never let NDFileHDF5 hit a full filesystem.

Env handling: appends 127.0.0.1:5080 to EPICS_CA_ADDR_LIST (via
ensure_adsim_ca_env) BEFORE the first CA connection. EPICS_CA_SERVER_PORT
is intentionally NOT touched — host:port addressing keeps the production
soft IOC (5064) reachable from the same process.
"""

import os
import sys
import time
import shutil
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_engine.ad_devices import (  # noqa: E402
    ensure_adsim_ca_env, get_adsim_detector, ADSIM_DATA_DIR)

H5_DATASET = "entry/data/data"  # NDFileHDF5 default layout
LOAD_DTYPES = ["UInt8", "UInt16", "Float32"]
DTYPE_BYTES = {"UInt8": 1, "UInt16": 2, "Float32": 4}
RAMDISK_DIR = "/dev/shm/adsim_load"
DISK_DIR = os.path.join(ADSIM_DATA_DIR, "load")


# ═══════════════════════════════════════════════════════════════════════
# Document-stream collector
# ═══════════════════════════════════════════════════════════════════════
class DocCollector:
    """Counts Bluesky documents by type and keeps start/stop docs."""

    def __init__(self):
        self.counts = Counter()
        self.start_doc = None
        self.stop_doc = None

    def __call__(self, name, doc):
        self.counts[name] += 1
        if name == "start":
            self.start_doc = doc
        elif name == "stop":
            self.stop_doc = doc

    def summary(self):
        order = ["start", "descriptor", "resource", "datum", "event", "stop"]
        parts = [f"{k}={self.counts.get(k, 0)}" for k in order]
        extra = [f"{k}={v}" for k, v in self.counts.items() if k not in order]
        status = self.stop_doc.get("exit_status", "?") if self.stop_doc else "NO-STOP"
        return " ".join(parts + extra) + f" exit_status={status}"


def verify_h5(path, expect_frames, expect_xy=(1024, 1024)):
    """Open the HDF5 file the IOC wrote and check frame count + shape."""
    import h5py
    if not path or not os.path.isfile(path):
        return False, f"file missing: {path!r}"
    with h5py.File(path, "r") as f:
        if H5_DATASET not in f:
            return False, f"dataset {H5_DATASET} missing (keys: {list(f)})"
        ds = f[H5_DATASET]
        shape, dtype = ds.shape, ds.dtype
    ok = (shape[0] == expect_frames and tuple(shape[1:]) == tuple(expect_xy))
    size_mb = os.path.getsize(path) / 1e6
    return ok, f"{os.path.basename(path)} shape={shape} dtype={dtype} ({size_mb:.1f} MB)"


# ═══════════════════════════════════════════════════════════════════════
# E2E: count + grid_scan
# ═══════════════════════════════════════════════════════════════════════
def run_e2e(det, num, do_grid=True):
    from bluesky import RunEngine
    from bluesky.plans import count, grid_scan

    RE = RunEngine({})
    results = []  # (label, pass, doc summary, h5 detail)

    # --- count(det, num=N) ---
    col = DocCollector()
    RE(count([det], num=num), col)
    h5_path = det.hdf5.full_file_name.get()
    ok_h5, detail = verify_h5(h5_path, num)
    ok_docs = (col.counts.get("event") == num and col.counts.get("datum") == num
               and col.counts.get("start") == 1 and col.counts.get("stop") == 1
               and col.stop_doc.get("exit_status") == "success")
    results.append((f"count(num={num})", ok_docs and ok_h5,
                    col.summary(), detail))

    # --- grid_scan with 2 soft motors (3x3) ---
    if do_grid:
        from ophyd.sim import motor1, motor2
        col = DocCollector()
        RE(grid_scan([det], motor1, -1, 1, 3, motor2, -1, 1, 3), col)
        h5_path = det.hdf5.full_file_name.get()
        ok_h5, detail = verify_h5(h5_path, 9)
        ok_docs = (col.counts.get("event") == 9 and col.counts.get("datum") == 9
                   and col.stop_doc.get("exit_status") == "success")
        results.append(("grid_scan(3x3, motor1/motor2)", ok_docs and ok_h5,
                        col.summary(), detail))

    return results


# ═══════════════════════════════════════════════════════════════════════
# Load test: Continuous acquire -> HDF5 Stream bursts (budget-limited)
# ═══════════════════════════════════════════════════════════════════════
def _stop_acquire(cam, timeout=15.0):
    """Robust acquire stop: fire-and-forget put + RBV poll (set().wait()
    raised UnknownStatusFailure when the IOC was busy/dying)."""
    try:
        cam.acquire.put(0, wait=False)
    except Exception as e:
        print(f"  [warn] acquire put(0) failed: {e}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if int(cam.acquire.get()) == 0:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    print("  [warn] acquire did not stop within timeout")
    return False


def load_burst(det, target_dir, dtype, duration, budget_bytes):
    """One burst: free-running acquire, HDF5 Stream capture into target_dir.

    NumCapture is finite (budget-limited to fit the target filesystem), so
    the plugin closes the file by itself when the budget is reached — the
    burst can never ENOSPC the target (which segfaulted the IOC when tried
    unbounded). The measurement window ends at file close or `duration`,
    whichever comes first. The HDF5 plugin runs non-blocking (queue 20 from
    st.cmd) so the driver free-runs; DroppedArrays = writer behind.
    """
    os.makedirs(target_dir, exist_ok=True)
    cam, hdf = det.cam, det.hdf5
    label = f"load_{dtype.lower()}"
    fbytes = DTYPE_BYTES[dtype] * 1024 * 1024
    free = shutil.disk_usage(target_dir).free
    n_cap = int(min(budget_bytes, free * 0.4) // fbytes)
    if n_cap < 10:
        print(f"  {dtype:8s} SKIPPED (free {free/1e9:.1f} GB too small)")
        return None

    _stop_acquire(cam)
    time.sleep(0.2)
    cam.data_type.set(dtype).wait()
    cam.size.size_x.set(1024).wait()
    cam.size.size_y.set(1024).wait()
    cam.acquire_time.set(0.0).wait()
    cam.acquire_period.set(0.0).wait()
    cam.image_mode.set("Continuous").wait()
    cam.array_callbacks.set(1).wait()

    hdf.enable.set(1).wait()
    hdf.blocking_callbacks.set("No").wait()
    hdf.file_write_mode.set("Stream").wait()
    hdf.num_capture.set(n_cap).wait()
    hdf.file_path.set(target_dir.rstrip("/") + "/").wait()
    hdf.file_name.set(label).wait()
    hdf.file_template.set("%s%s_%6.6d.h5").wait()
    hdf.file_number.set(0).wait()
    cam.array_counter.set(0).wait()
    hdf.array_counter.set(0).wait()
    hdf.dropped_arrays.set(0).wait()

    hdf.capture.set(1).wait()      # LazyOpen=1: file opens on first frame
    t0 = time.monotonic()
    cam.acquire.put(1, wait=False)
    # window ends at budget-reached file close, or at `duration`
    while True:
        dt = time.monotonic() - t0
        if int(hdf.capture.get()) == 0 or dt >= duration:
            break
        time.sleep(0.1)
    n_driver = int(cam.array_counter.get())
    n_written = int(hdf.num_captured.get())
    n_dropped = int(hdf.dropped_arrays.get())
    _stop_acquire(cam)
    if int(hdf.capture.get()) == 1:      # duration hit first: drain + close
        time.sleep(0.5)
        hdf.capture.put(0, wait=True)
    time.sleep(0.3)

    h5_path = hdf.full_file_name.get()
    fsize = os.path.getsize(h5_path) if os.path.isfile(h5_path) else 0
    return {
        "dir": target_dir, "dtype": dtype, "dt": dt, "n_cap": n_cap,
        "n_driver": n_driver, "n_written": n_written, "n_dropped": n_dropped,
        "driver_mbs": n_driver * fbytes / dt / 1e6,
        "driver_fps": n_driver / dt,
        "written_mbs": n_written * fbytes / dt / 1e6,
        "file_mbs": fsize / dt / 1e6,
        "file_mb": fsize / 1e6, "path": h5_path,
    }


def run_load(det, duration):
    rows = []
    try:
        for target, budget in ((RAMDISK_DIR, 3.0e9), (DISK_DIR, 6.0e9)):
            free_gb = shutil.disk_usage(os.path.dirname(target)).free / 1e9
            print(f"\n[load] target={target} (free {free_gb:.1f} GB, "
                  f"budget {budget/1e9:.0f} GB/burst)")
            for dtype in LOAD_DTYPES:
                r = load_burst(det, target, dtype, duration, budget)
                if r is None:
                    continue
                rows.append(r)
                print(f"  {dtype:8s} {r['dt']:5.1f}s driver {r['driver_fps']:6.1f} fps "
                      f"{r['driver_mbs']:7.1f} MB/s | written {r['n_written']:5d}"
                      f"/{r['n_cap']} ({r['written_mbs']:7.1f} MB/s, file "
                      f"{r['file_mbs']:7.1f} MB/s, {r['file_mb']:.0f} MB) | "
                      f"dropped {r['n_dropped']}")
                # delete burst file immediately (ramdisk is small)
                if os.path.isfile(r["path"]):
                    os.remove(r["path"])
    finally:
        _stop_acquire(det.cam)
        try:
            det.hdf5.capture.put(0, wait=True)
        except Exception:
            pass
        shutil.rmtree(RAMDISK_DIR, ignore_errors=True)
        # restore boot-ish defaults
        det.cam.data_type.set("UInt8").wait()
        det.cam.acquire_time.set(0.05).wait()
        det.cam.acquire_period.set(0.1).wait()

    print("\n| dir | dtype | window s | driver fps | driver MB/s | "
          "written MB/s | file MB/s | dropped |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        tag = "ramdisk" if r["dir"] == RAMDISK_DIR else "disk"
        print(f"| {tag} | {r['dtype']} | {r['dt']:.1f} | {r['driver_fps']:.1f} | "
              f"{r['driver_mbs']:.1f} | {r['written_mbs']:.1f} | "
              f"{r['file_mbs']:.1f} | {r['n_dropped']} |")
    return rows


# ═══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--num", type=int, default=5, help="frames for count()")
    ap.add_argument("--no-grid", action="store_true", help="skip grid_scan")
    ap.add_argument("--load", type=float, nargs="?", const=12.0, default=None,
                    metavar="SEC", help="run throughput bursts (default 12 s each)")
    ap.add_argument("--load-only", type=float, nargs="?", const=12.0,
                    default=None, metavar="SEC", help="bursts only, skip E2E")
    args = ap.parse_args()

    ensure_adsim_ca_env()  # BEFORE first CA connection
    print(f"EPICS_CA_ADDR_LIST = {os.environ['EPICS_CA_ADDR_LIST']}")

    t0 = time.monotonic()
    det = get_adsim_detector()  # connects + primes HDF5 plugin
    print(f"connected+primed in {time.monotonic() - t0:.1f} s "
          f"(prefix {det.prefix}, ADCore array_size={det.hdf5.array_size.get()})")

    failed = 0
    if args.load_only is None:
        results = run_e2e(det, args.num, do_grid=not args.no_grid)
        print("\n=== E2E results ===")
        for label, ok, docs, detail in results:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}\n"
                  f"       docs: {docs}\n       h5:   {detail}")
            failed += 0 if ok else 1

    dur = args.load_only if args.load_only is not None else args.load
    if dur is not None:
        run_load(det, dur)

    print(f"\n{'ALL PASS' if failed == 0 else f'{failed} FAILURE(S)'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
