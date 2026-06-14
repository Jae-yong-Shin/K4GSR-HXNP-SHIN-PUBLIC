#!/usr/bin/env python3
"""Generate a real scan HDF5/NeXus file via the project's NexusWriter (B2 PoC).

This mirrors the EXACT live-scan write path used by
``server/scan_engine/runner.py`` (``_open_live_writer`` -> ``create_extensible_1d``
+ ``append_value`` per event -> ``write_xrf_spectrum`` rows -> ``finalize``), so
the file produced here is byte-structurally identical to what the Bluesky
RunEngine auto-saves during a real ``raster_scan`` / ``energy_scan``.

We do NOT run a live RunEngine here (that needs a soft IOC + ophyd connections);
instead we drive the SAME NexusWriter the runner uses, with deterministic
synthetic event data, so the Tiled read-back can be asserted bit-for-bit
against the source file. The on-disk NeXus layout is the deliverable being
proven, and that layout is owned entirely by NexusWriter.

Usage:
    python -m data_access.make_sample_scan [--out PATH] [--seed N]

Returns (when imported): the written file path.

See docs/tasks/TASK_B2_TILED.md and TASK_PHASE1_ROADMAP.md s.B2.
"""

import os
import sys
import argparse
import logging
from datetime import datetime

import numpy as np

# Make ``server/`` importable so ``data.writer`` resolves the same way the
# runner imports it (the runner uses a relative ``..data.writer`` import).
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from data.writer import NexusWriter  # noqa: E402

log = logging.getLogger("tiled-sample-scan")

# Default output dir = the SAME directory the runner auto-saves into.
DEFAULT_SCAN_DIR = os.path.join(_SERVER_DIR, "data", "scans")

# Deterministic raster geometry (small, fast, but multi-column + 2D spectra).
_NX = 8
_NY = 6
_N_POINTS = _NX * _NY          # 48 events
_N_CHANNELS = 256              # MCA channels (small for a quick PoC file)
_ENERGY_KEV = 10.0


def make_sample_scan(out_path=None, seed=20260614):
    """Write one deterministic raster scan file via NexusWriter.

    The columns and 2D ``xrf_spectra`` are written exactly as the live runner
    writes them (extensible 1D datasets appended per event, an extensible 2D
    spectra dataset with one row per event).

    Returns the absolute path of the written file.
    """
    rng = np.random.default_rng(seed)

    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(DEFAULT_SCAN_DIR,
                                f"{ts}_raster_scan_b2tiled.h5")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Build deterministic per-event columns (what bp.grid_scan would emit).
    xs = np.tile(np.linspace(-10.0, 10.0, _NX), _NY)            # um
    ys = np.repeat(np.linspace(-7.5, 7.5, _NY), _NX)            # um
    # A smooth 2D "elemental" signal + small noise -> i0/it/fe channels.
    fe = (1000.0 * np.exp(-((xs / 6.0) ** 2 + (ys / 4.0) ** 2))
          + rng.normal(0.0, 5.0, _N_POINTS))
    i0 = 1.0e7 + rng.normal(0.0, 1.0e4, _N_POINTS)
    it = i0 * np.exp(-0.3 - fe / 2.0e4)

    columns = {
        "sample_x": xs.astype(np.float64),
        "sample_y": ys.astype(np.float64),
        "I0": i0.astype(np.float64),
        "It": it.astype(np.float64),
        "Fe_Ka": fe.astype(np.float64),
    }
    # Per-event XRF spectra (int32 counts), Poisson around the Fe signal.
    spectra = np.zeros((_N_POINTS, _N_CHANNELS), dtype=np.int32)
    ka_ch = 64  # arbitrary "Fe Ka" channel
    for i in range(_N_POINTS):
        base = rng.poisson(2.0, _N_CHANNELS).astype(np.int32)
        peak = int(max(fe[i], 0.0))
        lo = max(ka_ch - 3, 0)
        hi = min(ka_ch + 4, _N_CHANNELS)
        base[lo:hi] += rng.poisson(peak / 20.0, hi - lo).astype(np.int32)
        spectra[i] = base

    # --- Drive NexusWriter exactly like runner._open/_write/_close_live_writer.
    with NexusWriter(out_path, overwrite=True) as w:
        w.write_metadata(
            energy_keV=_ENERGY_KEV,
            scan_type="raster",
            uid="b2tiled0",
            num_points=_N_POINTS,
        )
        # First-event step: create extensible datasets (runner does this lazily).
        for key in sorted(columns.keys()):
            w.create_extensible_1d(key)
        w.create_extensible_dataset("xrf_spectra", _N_CHANNELS, dtype=np.int32)

        # Append per event (the live streaming path).
        for i in range(_N_POINTS):
            for key in sorted(columns.keys()):
                w.append_value(key, float(columns[key][i]))
            w.append_row("xrf_spectra", spectra[i])

        w.finalize()

    log.info("Sample scan written: %s (%d events, %d channels)",
             out_path, _N_POINTS, _N_CHANNELS)
    return out_path


def _main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Generate a sample scan HDF5 file.")
    ap.add_argument("--out", default=None, help="output .h5 path")
    ap.add_argument("--seed", type=int, default=20260614, help="RNG seed")
    args = ap.parse_args(argv)
    path = make_sample_scan(out_path=args.out, seed=args.seed)
    # CLI feedback (interactive helper -> print allowed per coding standard s.6).
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
