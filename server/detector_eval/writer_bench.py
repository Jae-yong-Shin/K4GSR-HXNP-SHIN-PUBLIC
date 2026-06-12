#!/usr/bin/env python3
"""EIGER2 stream consumer/writer benchmark (Phase-1 C2 detector-path evaluation).

Consumes the ZMQ PUSH stream from eiger2_stream_sim.py and measures sustained
HDF5 write throughput in three modes:

    null    one consumer that discards frames -- measures the loopback ZMQ
            transport + Python recv ceiling (upper bound for any writer)
    single  one writer process, one chunked HDF5 file -- the NDFileHDF5-like
            single-writer topology
    shard   N writer processes; ZMQ PUSH round-robins frames across the N
            PULL sockets, each writer writes its own shard file, and a
            master file with an HDF5 Virtual Dataset (VDS) maps the global
            frame order -- the Odin odin-data topology (M FrameReceivers ->
            M FrameProcessors -> M files + VDS master)

Writers use h5py direct chunk writes (dset.id.write_direct_chunk): because
the producer blobs are byte-exact HDF5-filter streams, compressed frames go
to disk with ZERO recompression, exactly like Odin/LIMA EIGER writers.
Integrity is checked by CRC32 (carried in each frame's meta header) on
read-back samples (--verify), after the timed window.

Each consumer has two sockets (matching the producer's two channels): PULL
for frames and SUB (endpoint port+1) for the broadcast series header / end
marker. The PUSH end copy arrives in order after a writer's frames (fast
path); the PUB broadcast guarantees termination when round-robin was skewed;
after a PUB end the writer drains the PULL queue until it idles briefly.

Timing convention: per-writer window = (last frame recv - first frame recv)
+ (close + fsync duration) -- drain/idle gaps after the last frame are NOT
counted, so the fallback path cannot inflate the window (--no-fsync to skip
fsync). Aggregate window = max(t_first_i + window_i) - min(t_first_i) across
writers. GB = 1e9 bytes. Raw GB/s (uncompressed detector data rate) is the
headline number; compressed GB/s is the actual bytes-to-storage rate.

Safety (C1 ENOSPC lesson): each writer aborts before writing if the
estimated series volume exceeds 40% of the target filesystem's free space.

Usage:
    python writer_bench.py --mode shard --writers 4 --outdir /dev/shm/ew \
        --endpoint tcp://127.0.0.1:17711 --json-out w.json
    # then start eiger2_stream_sim.py with --expect-peers 4
"""

import argparse
import json
import logging
import multiprocessing as mp
import os
import shutil
import sys
import time
import zlib

import numpy as np
import h5py
import zmq

try:
    import hdf5plugin  # registers bslz4/lz4 filters for create/read paths
    HAVE_HDF5PLUGIN = True
except ImportError:  # pragma: no cover
    HAVE_HDF5PLUGIN = False

log = logging.getLogger("eiger2-writer-bench")

DEFAULT_ENDPOINT = "tcp://127.0.0.1:17711"
DEFAULT_RCVHWM = 100          # bounds per-writer queue memory
DATASET_PATH = "entry/data/data"
GROW_BLOCK = 512              # dataset resize granularity (frames)
RECV_IDLE_TIMEOUT_S = 15.0    # give up if the stream stalls this long
DRAIN_IDLE_S = 1.0            # post-PUB-end PULL drain idle threshold
START_TIMEOUT_S = 60.0        # give up if no series starts at all
FREE_SPACE_FRACTION = 0.4     # C1 rule: never budget >40% of free space


def control_endpoint(endpoint):
    """Control (SUB) endpoint = data endpoint with port+1."""
    base, port = endpoint.rsplit(":", 1)
    return f"{base}:{int(port) + 1}"


def _filter_kwargs(compression):
    if compression == "bslz4":
        if not HAVE_HDF5PLUGIN:
            raise RuntimeError("bslz4 requires hdf5plugin")
        try:
            return dict(hdf5plugin.Bitshuffle(nelems=0, cname="lz4"))
        except TypeError:  # hdf5plugin < 4.0 has lz4= instead of cname=
            return dict(hdf5plugin.Bitshuffle(nelems=0, lz4=True))
    if compression == "lz4":
        if not HAVE_HDF5PLUGIN:
            raise RuntimeError("lz4 requires hdf5plugin")
        return dict(hdf5plugin.LZ4(nbytes=0))
    if compression == "zlib":
        return {"compression": "gzip", "compression_opts": 4}
    if compression == "none":
        return {}
    raise ValueError(f"unknown compression {compression!r}")


def _fsync_file(path):
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ----------------------------------------------------------------------
# Writer process
# ----------------------------------------------------------------------
def writer_proc(widx, opts, ready_evt, result_q):
    """One PULL consumer. opts is a plain dict (spawn-safe)."""
    res = {"writer": widx, "ok": False, "error": None}
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.setsockopt(zmq.RCVHWM, opts["rcvhwm"])
    sock.connect(opts["endpoint"])
    csock = ctx.socket(zmq.SUB)
    csock.setsockopt(zmq.SUBSCRIBE, b"")
    csock.connect(control_endpoint(opts["endpoint"]))
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)
    poller.register(csock, zmq.POLLIN)
    ready_evt.set()

    write_files = opts["mode"] != "null"
    f = dset = None
    path = ""
    cfg = {}
    frame_ids = []
    crcs = []
    nframes = 0
    raw_bytes = 0
    comp_bytes = 0
    cap = 0
    t_first = t_last = None
    ending = False        # PUB end seen -> drain PULL, then stop
    done = False

    def handle_control(parts):
        """Broadcast channel: series header or series end."""
        nonlocal cfg, f, dset, cap, path, ending
        head = json.loads(bytes(parts[0]))
        htype = head.get("htype", "")
        if htype.startswith("dheader") and not cfg:
            cfg = json.loads(bytes(parts[1]))
            if write_files:
                h, w = cfg["shape"]
                per_frame = (cfg["est_comp_bytes"] if cfg["compression"] != "none"
                             else h * w * np.dtype(cfg["dtype"]).itemsize)
                est_total = cfg["nimages"] * per_frame * 1.3  # 30% margin
                free = shutil.disk_usage(opts["outdir"]).free
                if est_total > FREE_SPACE_FRACTION * free:
                    raise RuntimeError(
                        f"budget check: est series {est_total / 1e9:.2f} GB > "
                        f"{FREE_SPACE_FRACTION:.0%} of free "
                        f"{free / 1e9:.2f} GB on {opts['outdir']} (C1 rule)")
                path = os.path.join(opts["outdir"], f"shard_{widx:02d}.h5")
                f = h5py.File(path, "w", libver="latest")
                cap = GROW_BLOCK
                dset = f.create_dataset(
                    DATASET_PATH, shape=(cap, h, w),
                    maxshape=(None, h, w), dtype=cfg["dtype"],
                    chunks=(1, h, w), **_filter_kwargs(cfg["compression"]))
        elif htype.startswith("dseries_end"):
            ending = True

    t_spawn = time.monotonic()
    try:
        while not done:
            timeout_ms = int((DRAIN_IDLE_S if ending else RECV_IDLE_TIMEOUT_S)
                             * 1000)
            events = dict(poller.poll(timeout_ms))
            if not events:
                if ending:
                    break  # PULL queue drained after the PUB end broadcast
                if t_first is not None or cfg:
                    res["error"] = (f"stream idle >{RECV_IDLE_TIMEOUT_S}s "
                                    f"without a series end, gave up")
                    break
                if time.monotonic() - t_spawn > START_TIMEOUT_S:
                    res["error"] = f"no series within {START_TIMEOUT_S}s"
                    break
                continue  # still waiting for the series to start

            if csock in events:
                handle_control(csock.recv_multipart())

            if sock in events:
                parts = sock.recv_multipart(copy=False)
                head = json.loads(bytes(parts[0].buffer))
                htype = head.get("htype", "")
                if htype.startswith("dimage"):
                    if write_files and dset is None:
                        raise RuntimeError(
                            "frame before series header (control channel "
                            "not connected in time?)")
                    if t_first is None:
                        t_first = time.monotonic()
                    meta = json.loads(bytes(parts[1].buffer))
                    blob = parts[2]
                    if write_files:
                        if nframes >= cap:
                            cap += GROW_BLOCK
                            dset.resize(cap, axis=0)
                        dset.id.write_direct_chunk((nframes, 0, 0),
                                                   blob.buffer, filter_mask=0)
                    frame_ids.append(head["frame"])
                    crcs.append(meta["crc32"])
                    raw_bytes += meta["size_raw"]
                    comp_bytes += meta["size"]
                    nframes += 1
                    t_last = time.monotonic()
                elif htype.startswith("dseries_end"):
                    done = True  # ordered fast path: all our frames are in

        t_close0 = time.monotonic()
        if write_files and f is not None:
            dset.resize(nframes, axis=0)
            f.create_dataset("entry/data/frame_id",
                             data=np.asarray(frame_ids, dtype=np.int64))
            f.flush()
            f.close()
            f = None
            if opts["fsync"]:
                _fsync_file(path)
        close_s = time.monotonic() - t_close0

        # Post-window integrity check: read back k frames through the normal
        # h5py filter-decoding path and compare CRC32 with the stream meta.
        verify = {"checked": 0, "ok": True}
        if write_files and opts["verify"] > 0 and nframes > 0:
            rng = np.random.default_rng(widx)
            picks = rng.choice(nframes, size=min(opts["verify"], nframes),
                               replace=False)
            with h5py.File(path, "r") as fr:
                d = fr[DATASET_PATH]
                for li in picks:
                    arr = d[int(li)]
                    crc = zlib.crc32(np.ascontiguousarray(arr).tobytes())
                    if crc != crcs[int(li)]:
                        verify["ok"] = False
                        res["error"] = f"CRC mismatch at local frame {li}"
                    verify["checked"] += 1

        # Window excludes any post-last-frame drain idle (fallback path)
        window = None
        if t_first is not None and t_last is not None:
            window = (t_last - t_first) + close_s
        res.update({
            "ok": res["error"] is None,
            "config": cfg,
            "file": path if write_files else None,
            "file_bytes": os.path.getsize(path) if (write_files and path) else 0,
            "frames": nframes,
            "raw_bytes": raw_bytes,
            "comp_bytes": comp_bytes,
            "t_first": t_first,
            "t_end_eff": (t_first + window) if window else None,
            "close_s": round(close_s, 4),
            "window_s": round(window, 4) if window else None,
            "raw_GBps": round(raw_bytes / window / 1e9, 4) if window else None,
            "comp_GBps": round(comp_bytes / window / 1e9, 4) if window else None,
            "fps": round(nframes / window, 1) if window else None,
            "ended_via": "drain-idle" if (ending and not done) else "push-end",
            "frame_ids": frame_ids,
            "crcs": crcs,
            "verify": verify,
        })
    except Exception as e:  # propagate to parent via the queue
        res["error"] = f"{type(e).__name__}: {e}"
        if f is not None:
            try:
                f.close()
            except Exception:
                pass
    finally:
        sock.close(linger=0)
        csock.close(linger=0)
        ctx.term()
        result_q.put(res)


# ----------------------------------------------------------------------
# VDS master file (Odin pattern: M shard files + 1 master)
# ----------------------------------------------------------------------
def build_vds_master(outdir, results, cfg):
    """Map every global frame id to its (shard file, local index)."""
    h, w = cfg["shape"]
    total = sum(r["frames"] for r in results)
    layout = h5py.VirtualLayout(shape=(total, h, w), dtype=cfg["dtype"])
    for r in results:
        vs = h5py.VirtualSource(os.path.basename(r["file"]), DATASET_PATH,
                                shape=(r["frames"], h, w))
        for lidx, gid in enumerate(r["frame_ids"]):
            layout[gid] = vs[lidx]
    master = os.path.join(outdir, "master_vds.h5")
    t0 = time.monotonic()
    with h5py.File(master, "w", libver="latest") as f:
        f.create_virtual_dataset(DATASET_PATH, layout, fillvalue=0)
    dt = time.monotonic() - t0
    return master, total, dt


def verify_vds(master, results, cfg, k):
    """Read k random GLOBAL frames through the VDS and CRC-check them."""
    crc_by_gid = {}
    for r in results:
        for lidx, gid in enumerate(r["frame_ids"]):
            crc_by_gid[gid] = r["crcs"][lidx]
    total = len(crc_by_gid)
    rng = np.random.default_rng(12345)
    picks = rng.choice(total, size=min(k, total), replace=False)
    ok = True
    with h5py.File(master, "r") as f:
        d = f[DATASET_PATH]
        for gid in picks:
            arr = d[int(gid)]
            crc = zlib.crc32(np.ascontiguousarray(arr).tobytes())
            if crc != crc_by_gid[int(gid)]:
                ok = False
                log.error(f"VDS CRC mismatch at global frame {gid}")
    return {"checked": int(len(picks)), "ok": ok}


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------
def run(args):
    nwriters = 1 if args.mode in ("null", "single") else args.writers
    if args.mode != "null":
        os.makedirs(args.outdir, exist_ok=True)

    opts = {
        "mode": args.mode,
        "endpoint": args.endpoint,
        "outdir": args.outdir,
        "rcvhwm": args.rcvhwm,
        "fsync": not args.no_fsync,
        "verify": args.verify,
    }
    mpctx = mp.get_context()
    result_q = mpctx.Queue()
    procs = []
    for widx in range(nwriters):
        ready = mpctx.Event()
        proc = mpctx.Process(target=writer_proc,
                             args=(widx, opts, ready, result_q), daemon=True)
        proc.start()
        if not ready.wait(timeout=15):
            raise RuntimeError(f"writer {widx} failed to become ready")
        procs.append(proc)
    log.info(f"{nwriters} consumer(s) ready ({args.mode} mode), "
             f"endpoint {args.endpoint} -- start the producer now")

    results = []
    deadline = time.monotonic() + args.timeout
    for _ in range(nwriters):
        left = deadline - time.monotonic()
        if left <= 0:
            raise RuntimeError("timed out waiting for writer results")
        results.append(result_q.get(timeout=left))
    for proc in procs:
        proc.join(timeout=10)
        if proc.is_alive():
            proc.terminate()
    results.sort(key=lambda r: r["writer"])

    errors = [r["error"] for r in results if r["error"]]
    if errors:
        for e in errors:
            log.error(f"writer error: {e}")

    # Aggregate over the union window (same machine -> same monotonic clock)
    started = [r for r in results
               if r.get("t_first") is not None and r.get("t_end_eff")]
    agg = {}
    if started:
        t_first = min(r["t_first"] for r in started)
        t_end = max(r["t_end_eff"] for r in started)
        window = t_end - t_first
        frames = sum(r["frames"] for r in started)
        raw = sum(r["raw_bytes"] for r in started)
        comp = sum(r["comp_bytes"] for r in started)
        agg = {
            "window_s": round(window, 4),
            "frames": frames,
            "fps": round(frames / window, 1),
            "raw_GBps": round(raw / window / 1e9, 4),
            "comp_GBps": round(comp / window / 1e9, 4),
            "raw_bytes": raw,
            "comp_bytes": comp,
            "frames_per_writer": [r.get("frames", 0) for r in results],
        }

    vds = None
    if args.mode == "shard" and started and not errors:
        cfg = started[0]["config"]
        master, total, dt = build_vds_master(args.outdir, results, cfg)
        vds = {"file": master, "frames": total, "build_s": round(dt, 4)}
        if args.verify_vds > 0:
            vds["verify"] = verify_vds(master, results, cfg, args.verify_vds)
        log.info(f"VDS master {master}: {total} frames, built in {dt:.2f}s, "
                 f"verify={vds.get('verify')}")

    # Drop bulky per-frame lists from the report (kept only for VDS/verify)
    for r in results:
        r.pop("frame_ids", None)
        r.pop("crcs", None)

    report = {
        "role": "writer-bench",
        "mode": args.mode,
        "writers": nwriters,
        "outdir": args.outdir if args.mode != "null" else None,
        "endpoint": args.endpoint,
        "fsync": not args.no_fsync,
        "aggregate": agg,
        "per_writer": results,
        "vds": vds,
        "errors": errors,
    }
    if agg:
        log.info(f"[{args.mode} x{nwriters}] {agg['frames']} frames in "
                 f"{agg['window_s']}s = {agg['raw_GBps']} GB/s raw "
                 f"({agg['comp_GBps']} GB/s to storage), {agg['fps']} fps")
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(report, f, indent=1)
        log.info(f"report -> {args.json_out}")
    return 1 if errors else 0


def main():
    p = argparse.ArgumentParser(
        description="HDF5 writer benchmark for the EIGER2 stream simulator")
    p.add_argument("--mode", choices=["null", "single", "shard"],
                   default="single")
    p.add_argument("--writers", type=int, default=2,
                   help="writer processes in shard mode")
    p.add_argument("--outdir", default="./eiger2_bench_out")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--rcvhwm", type=int, default=DEFAULT_RCVHWM)
    p.add_argument("--no-fsync", action="store_true",
                   help="skip fsync before closing the timing window")
    p.add_argument("--verify", type=int, default=2,
                   help="frames per writer to CRC-check after the window")
    p.add_argument("--verify-vds", type=int, default=4,
                   help="global frames to CRC-check through the VDS master")
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--json-out", default="", help="write report JSON")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        sys.exit(run(args))
    except Exception:
        log.exception("writer bench failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
