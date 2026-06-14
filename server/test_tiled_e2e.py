#!/usr/bin/env python3
"""End-to-end test for the B2 Tiled data-access PoC (manuscript para 39).

Proves that Tiled serves the project's REAL scan output faithfully:

  1. Ensure a real scan HDF5/NeXus file exists (generated via the project's
     NexusWriter -- the exact live-scan write path; see make_sample_scan.py).
  2. Spawn ``tiled serve config`` as a subprocess on a local port.
  3. Client (tiled.client.from_uri) connects, lists >= 1 catalog entry, opens a
     run, and reads known datasets into numpy.
  4. ASSERT the Tiled-served arrays match the SOURCE file read directly with
     h5py: same shape + values at machine precision (< 1e-9 for floats, exact
     for ints). This is the faithfulness proof.
  5. Tear down the subprocess; ASSERT no orphan child processes survive; clean
     any generated demo file; print timings.

Runnable two ways:
    pytest server/test_tiled_e2e.py -v
    python server/test_tiled_e2e.py        # standalone, prints a report

All asserts are blocking (the standalone runner exits non-zero on failure).

LOCAL PoC ONLY. NO facility auth (deferred to B4).
"""

import os
import sys
import time
import logging

import numpy as np
import h5py
import psutil

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from tiled.client import from_uri

from data_access.tiled_serve import TiledServer
from data_access.make_sample_scan import make_sample_scan

log = logging.getLogger("tiled-e2e")

# A distinct port so the test never collides with a hand-run server (8010).
_E2E_PORT = 8019
# Float match tolerance (spec: < 1e-9). Floats round-trip msgpack at full f64
# precision, so this is effectively exact; we assert it explicitly.
_FLOAT_ATOL = 1e-9

# Datasets we assert on (1-D float columns + the 2-D int spectra).
_FLOAT_COLS = ("sample_x", "sample_y", "I0", "It", "Fe_Ka")
_INT_DATASET = "xrf_spectra"


def _read_source(path):
    """Read the ground-truth arrays straight from the file with h5py."""
    out = {}
    with h5py.File(path, "r") as f:
        for col in _FLOAT_COLS:
            out[col] = f[f"entry/data/{col}"][...]
        out[_INT_DATASET] = f[f"entry/data/{_INT_DATASET}"][...]
        out["_entry_attrs"] = dict(f["entry"].attrs)
    return out


def run_e2e():
    """Execute the full E2E flow. Raises AssertionError on any mismatch.

    Returns a dict of timings + a report for the standalone runner.
    """
    t0 = time.perf_counter()
    report = {}

    # --- 1. Ensure a real scan file (generated via NexusWriter live path). ----
    gen_path = os.path.abspath(
        os.path.join(_SERVER_DIR, "data", "scans", "_e2e_tiled_probe.h5"))
    if os.path.exists(gen_path):
        os.remove(gen_path)
    make_sample_scan(out_path=gen_path)
    assert os.path.exists(gen_path), "sample scan file was not created"
    size_mb = os.path.getsize(gen_path) / 1e6
    report["generated_file"] = gen_path
    report["generated_size_mb"] = size_mb
    t_gen = time.perf_counter()

    # Ground truth from the source file (h5py, direct).
    src = _read_source(gen_path)

    # --- 2. Spawn the Tiled server subprocess. --------------------------------
    # Serve only the dir holding our generated file; use a private work dir so we
    # control the served set deterministically.
    srv = TiledServer(scans_dir=os.path.dirname(gen_path), port=_E2E_PORT)
    proc_children_before = set()
    try:
        url = srv.start()
        t_start = time.perf_counter()

        # Record the subprocess + its children so we can assert no orphans later.
        server_pid = srv._proc.pid
        try:
            server_proc = psutil.Process(server_pid)
            proc_children_before = {c.pid for c in
                                    server_proc.children(recursive=True)}
        except psutil.NoSuchProcess:
            server_proc = None

        # --- 3. Client connects, lists, opens, reads into numpy. --------------
        client = from_uri(url, api_key=srv.api_key)
        runs = list(client.keys())
        assert len(runs) >= 1, f"expected >=1 catalog entry, got {runs}"
        report["n_runs"] = len(runs)
        report["runs"] = runs

        # Find the run corresponding to our generated file.
        run_name = os.path.splitext(os.path.basename(gen_path))[0]
        assert run_name in runs, (
            f"generated run {run_name!r} not in catalog {runs}")
        run = client[run_name]
        data = run["entry"]["data"]

        served_cols = list(data.keys())
        for col in _FLOAT_COLS:
            assert col in served_cols, f"missing served column {col!r}"
        assert _INT_DATASET in served_cols, "missing served xrf_spectra"

        # --- 4. ASSERT Tiled == source (shape + values, machine precision). ---
        max_float_diff = 0.0
        for col in _FLOAT_COLS:
            tiled_arr = np.asarray(data[col].read())
            src_arr = src[col]
            assert tiled_arr.shape == src_arr.shape, (
                f"{col}: shape {tiled_arr.shape} != source {src_arr.shape}")
            assert tiled_arr.dtype == src_arr.dtype, (
                f"{col}: dtype {tiled_arr.dtype} != source {src_arr.dtype}")
            diff = float(np.max(np.abs(tiled_arr - src_arr)))
            max_float_diff = max(max_float_diff, diff)
            assert diff < _FLOAT_ATOL, (
                f"{col}: max abs diff {diff} >= tol {_FLOAT_ATOL}")
        report["max_float_abs_diff"] = max_float_diff

        # 2-D int spectra: exact match required.
        tiled_spec = np.asarray(data[_INT_DATASET].read())
        src_spec = src[_INT_DATASET]
        assert tiled_spec.shape == src_spec.shape, (
            f"xrf_spectra shape {tiled_spec.shape} != {src_spec.shape}")
        assert tiled_spec.dtype == src_spec.dtype, (
            f"xrf_spectra dtype {tiled_spec.dtype} != {src_spec.dtype}")
        assert np.array_equal(tiled_spec, src_spec), (
            "xrf_spectra int values differ between Tiled and source")
        report["xrf_exact_int_match"] = True

        # Metadata (NeXus /entry attrs) preserved.
        entry_md = dict(run["entry"].metadata)
        assert entry_md.get("scan_type") == src["_entry_attrs"].get("scan_type")
        assert int(entry_md.get("num_points")) == \
            int(src["_entry_attrs"].get("num_points"))
        report["metadata_scan_type"] = entry_md.get("scan_type")
        t_read = time.perf_counter()

    finally:
        # --- 5. Teardown + orphan assertion. ----------------------------------
        srv.shutdown()
    t_teardown = time.perf_counter()

    # The server pid and any children it spawned must all be gone. A reused PID
    # belonging to an unrelated process is NOT an orphan, so we only flag a
    # surviving pid if its command line still looks like tiled/uvicorn.
    orphans = []
    for pid in {server_pid} | proc_children_before:
        if not psutil.pid_exists(pid):
            continue
        try:
            cmd = " ".join(psutil.Process(pid).cmdline()).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            cmd = ""
        if any(tok in cmd for tok in ("tiled", "uvicorn")):
            orphans.append((pid, cmd[:80]))
    assert not orphans, f"orphan Tiled processes survived teardown: {orphans}"
    report["orphan_count"] = len(orphans)

    # --- cleanup generated file -----------------------------------------------
    if os.path.exists(gen_path):
        os.remove(gen_path)
    report["cleaned_generated_file"] = not os.path.exists(gen_path)

    report["timings_s"] = {
        "generate": round(t_gen - t0, 3),
        "server_start": round(t_start - t_gen, 3),
        "client_read+assert": round(t_read - t_start, 3),
        "teardown": round(t_teardown - t_read, 3),
        "total": round(t_teardown - t0, 3),
    }
    return report


# ── pytest entry point ────────────────────────────────────────────────────────
def test_tiled_e2e():
    """pytest wrapper: run the full E2E and assert success markers."""
    report = run_e2e()
    assert report["n_runs"] >= 1
    assert report["max_float_abs_diff"] < _FLOAT_ATOL
    assert report["xrf_exact_int_match"] is True
    assert report["orphan_count"] == 0
    assert report["cleaned_generated_file"] is True


# ── standalone runner ─────────────────────────────────────────────────────────
def _main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("=" * 68)
    print("B2 Tiled PoC -- end-to-end test")
    print("=" * 68)
    try:
        rep = run_e2e()
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR: {type(e).__name__}: {e}")
        return 2

    print("\nRESULT: PASS")
    print(f"  catalog runs           : {rep['n_runs']}  {rep['runs']}")
    print(f"  generated file         : {os.path.basename(rep['generated_file'])}"
          f"  ({rep['generated_size_mb']:.3f} MB)")
    print(f"  max float abs diff     : {rep['max_float_abs_diff']:.3e} "
          f"(tol {_FLOAT_ATOL:.0e})")
    print(f"  xrf int exact match    : {rep['xrf_exact_int_match']}")
    print(f"  metadata scan_type     : {rep['metadata_scan_type']}")
    print(f"  orphan processes       : {rep['orphan_count']}")
    print(f"  generated file cleaned : {rep['cleaned_generated_file']}")
    print("  timings (s)            :")
    for k, v in rep["timings_s"].items():
        print(f"      {k:<22} {v}")
    if rep["generated_size_mb"] > 50:
        print(f"  NOTE: generated file was {rep['generated_size_mb']:.1f} MB "
              "(>50 MB); it was removed at teardown (df-style note).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
