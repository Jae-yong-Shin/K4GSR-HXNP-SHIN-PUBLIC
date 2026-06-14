#!/usr/bin/env python3
"""Tiled client demo -- the B2 'programmatic read-back' deliverable (para 39).

Connects to the local Tiled PoC server with ``tiled.client.from_uri``, lists the
catalog entries (scan runs), opens one run, reads its detector/motor arrays into
numpy, and prints a summary. This is the programmatic data-access path the
manuscript promises: the existing scan output (NeXus/HDF5) is read back over HTTP
without any bespoke file parsing on the client.

It can either drive its own local server (default: it starts TiledServer, runs
the demo, tears it down) or connect to an already-running server via --url.

LOCAL PoC ONLY, read-only, anonymous. NO facility auth (deferred to B4).

Usage:
    python -m data_access.tiled_demo                  # self-hosted demo
    python -m data_access.tiled_demo --url http://127.0.0.1:8010 --api-key KEY
    python -m data_access.tiled_demo --ensure-sample  # make a scan file first
"""

import os
import sys
import argparse
import logging

import numpy as np

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from tiled.client import from_uri  # noqa: E402

log = logging.getLogger("tiled-demo")


def _summarize_run(run):
    """Print a structured summary of one scan run node + return read arrays.

    Returns a dict {column_name: numpy_array} for the 1-D /entry/data columns
    plus 'xrf_spectra' if present.
    """
    print(f"\n--- run: {run.uri.rsplit('/', 1)[-1] if hasattr(run, 'uri') else run} ---")
    entry = run["entry"]
    md = dict(entry.metadata)
    print(f"  scan_type = {md.get('scan_type')}   uid = {md.get('uid')}   "
          f"num_points = {md.get('num_points')}")
    print(f"  start = {md.get('start_time')}   end = {md.get('end_time')}")

    data = entry["data"]
    cols = list(data.keys())
    print(f"  /entry/data columns: {cols}")

    arrays = {}
    for name in cols:
        node = data[name]
        arr = np.asarray(node.read())
        arrays[name] = arr
        if arr.ndim == 1:
            print(f"    {name:<12} shape={arr.shape} dtype={arr.dtype} "
                  f"min={arr.min():.4g} max={arr.max():.4g} mean={arr.mean():.4g}")
        else:
            print(f"    {name:<12} shape={arr.shape} dtype={arr.dtype} "
                  f"sum={arr.sum()} (2-D)")
    return arrays


def run_demo(url, api_key=None):
    """Connect to a Tiled server at *url*, list runs, read one, print a summary.

    Returns the dict of numpy arrays read from the first run (for callers/tests).
    """
    log.info(f"Connecting to Tiled at {url}")
    client = from_uri(url, api_key=api_key)

    runs = list(client.keys())
    print(f"Tiled catalog: {len(runs)} run(s) -> {runs}")
    if not runs:
        print("No runs found. Generate one with data_access.make_sample_scan "
              "or pass --ensure-sample.")
        return {}

    # Open the first run and read its arrays into numpy.
    first = client[runs[0]]
    arrays = _summarize_run(first)
    print("\nProgrammatic read-back OK: arrays are plain numpy, ready for "
          "downstream analysis (no HDF5 parsing on the client).")
    return arrays


def _main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description="Tiled B2 client read-back demo.")
    ap.add_argument("--url", default=None,
                    help="connect to an existing server (else self-host)")
    ap.add_argument("--api-key", default=None,
                    help="API key for an existing server (--url)")
    ap.add_argument("--ensure-sample", action="store_true",
                    help="generate a sample scan file before serving")
    ap.add_argument("--port", type=int, default=None,
                    help="port for the self-hosted server")
    args = ap.parse_args(argv)

    if args.url:
        run_demo(args.url, api_key=args.api_key)
        return 0

    # Self-hosted: optionally make a sample file, start server, demo, teardown.
    from data_access.tiled_serve import TiledServer, DEFAULT_SCANS_DIR
    import glob
    if args.ensure_sample or not glob.glob(os.path.join(DEFAULT_SCANS_DIR,
                                                        "*.h5")):
        from data_access.make_sample_scan import make_sample_scan
        path = make_sample_scan()
        log.info(f"Generated sample scan: {path}")

    srv = TiledServer(port=args.port)
    try:
        url = srv.start()
        run_demo(url, api_key=srv.api_key)
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
