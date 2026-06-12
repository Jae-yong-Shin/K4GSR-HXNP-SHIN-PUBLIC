#!/usr/bin/env python3
"""EIGER2 SIMPLON-style stream simulator (Phase-1 C2 detector-path evaluation).

Emulates the DECTRIS SIMPLON stream-interface frame flow over a ZeroMQ PUSH
socket: a series-header message, one multipart message per frame
(json header / json frame-meta / compressed blob / json times), and one
series-end message per connected consumer. Message htypes follow the public
SIMPLON stream-v1 naming (dheader-1.0 / dimage-1.0 / dseries_end-1.0) but the
schema here is an EMULATION for writer benchmarking, not the vendor schema.

Frames are synthetic EIGER2-like images (default 1062x1028 = 1.09 Mpixel,
uint16): Poisson background + Bragg-like spots + a powder-like ring + module-
gap-like bands at the dtype max (mask value). To reach GB/s-class send rates
from Python, a small pool of frames (default 8) is generated and compressed
ONCE, then cycled; per-frame headers stay unique.

Compression is performed by the HDF5 filter pipeline itself (the pool is
written through h5py with the requested filter and the raw chunks are read
back with read_direct_chunk), so each blob is byte-identical to what the
corresponding HDF5 filter produces. This makes the blobs direct-chunk-write
compatible on the consumer side with zero recompression -- the same property
the real SIMPLON bslz4 stream is known for (exploited by Odin/LIMA writers).
A startup self-test round-trips blob #0 through write_direct_chunk + h5py
read and compares CRC32, so a filter/byte-format mismatch aborts immediately.

Supported compressions:
    bslz4  bitshuffle + LZ4 (HDF5 filter 32008, needs hdf5plugin) -- the
           EIGER2 production default; encoding label "bs<bits>-lz4<"
    lz4    plain LZ4 (HDF5 filter 32004, needs hdf5plugin); label "lz4<"
    zlib   gzip/deflate level 4 (built-in HDF5 filter); label "zlib"
    none   raw little-endian frames; label "raw<"

Usage (benchmark pair -- start the consumer first, see writer_bench.py):
    python eiger2_stream_sim.py --frames 3000 --compression bslz4 \
        --expect-peers 2 --endpoint tcp://127.0.0.1:17711 --json-out p.json

Socket topology (two channels, like the eiger-fan/odin split of control
metadata vs frame fan-out):
    PUSH  <endpoint>        frames (dimage), round-robin across N consumers,
                            plus N best-effort series-end copies (ordered
                            after the frames on each connection)
    PUB   <endpoint port+1> series header + series end, BROADCAST -- this
                            guarantees every consumer gets the config and the
                            end marker even when PUSH round-robin is skewed
                            by a full peer queue (HWM skipping)

The producer binds both, waits for --expect-peers connections on each (ZMQ
monitor events) plus a subscription-settle delay, then streams at --fps
(0 = max rate).
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import zlib

import numpy as np
import h5py
import zmq
from zmq.utils.monitor import recv_monitor_message

try:
    import hdf5plugin  # registers bslz4/lz4 HDF5 filters on import
    HAVE_HDF5PLUGIN = True
except ImportError:  # pragma: no cover
    HAVE_HDF5PLUGIN = False

log = logging.getLogger("eiger2-stream-sim")

DEFAULT_ENDPOINT = "tcp://127.0.0.1:17711"
DEFAULT_SHAPE = (1062, 1028)        # EIGER2-1M-like: 1.09 Mpixel
DEFAULT_POOL = 8
DEFAULT_SNDHWM = 100                # bounds producer-side queue memory
PEER_WAIT_TIMEOUT = 30.0


# ----------------------------------------------------------------------
# Synthetic frame generation
# ----------------------------------------------------------------------
def make_frame(rng, height, width, dtype, background_lam):
    """One synthetic EIGER2-like diffraction frame."""
    info = np.iinfo(dtype)
    img = rng.poisson(background_lam, size=(height, width)).astype(np.int64)

    # Bragg-like spots (small gaussians at random positions)
    nspots = 40
    ys = rng.integers(4, height - 4, nspots)
    xs = rng.integers(4, width - 4, nspots)
    amps = rng.integers(100, 4000, nspots)
    for y, x, a in zip(ys, xs, amps):
        yy, xx = np.mgrid[y - 3:y + 4, x - 3:x + 4]
        img[y - 3:y + 4, x - 3:x + 4] += (
            a * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 2.0)).astype(np.int64)

    # Powder-like ring around the frame center
    cy, cx = height / 2.0, width / 2.0
    yy, xx = np.mgrid[0:height, 0:width]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    ring_r = min(height, width) * 0.3
    img += (60.0 * np.exp(-((r - ring_r) ** 2) / (2 * 3.0 ** 2))).astype(np.int64)

    # Module-gap-like bands flagged at dtype max (EIGER gap-pixel convention)
    gap = height // 2
    img[gap - 6:gap + 6, :] = info.max

    return np.clip(img, 0, info.max).astype(dtype)


def filter_kwargs(compression):
    """h5py create_dataset kwargs for the requested compression."""
    if compression == "bslz4":
        if not HAVE_HDF5PLUGIN:
            raise RuntimeError("bslz4 requires hdf5plugin (pip install hdf5plugin)")
        try:
            return dict(hdf5plugin.Bitshuffle(nelems=0, cname="lz4"))
        except TypeError:  # hdf5plugin < 4.0 has lz4= instead of cname=
            return dict(hdf5plugin.Bitshuffle(nelems=0, lz4=True))
    if compression == "lz4":
        if not HAVE_HDF5PLUGIN:
            raise RuntimeError("lz4 requires hdf5plugin (pip install hdf5plugin)")
        return dict(hdf5plugin.LZ4(nbytes=0))
    if compression == "zlib":
        return {"compression": "gzip", "compression_opts": 4}
    if compression == "none":
        return {}
    raise ValueError(f"unknown compression {compression!r}")


def encoding_label(compression, dtype):
    bits = np.dtype(dtype).itemsize * 8
    return {
        "bslz4": f"bs{bits}-lz4<",
        "lz4": "lz4<",
        "zlib": "zlib",
        "none": "raw<",
    }[compression]


def build_pool(nframes, height, width, dtype, compression, background_lam, seed):
    """Generate the frame pool and compress it via the HDF5 filter pipeline.

    Returns (pool, ratio) where pool is a list of dicts
    {blob: bytes, crc32: int, raw_nbytes: int} -- blob is the exact byte
    stream the HDF5 filter produced for that frame (read_direct_chunk).
    """
    rng = np.random.default_rng(seed)
    frames = [make_frame(rng, height, width, dtype, background_lam)
              for _ in range(nframes)]
    kwargs = filter_kwargs(compression)

    fd, path = tempfile.mkstemp(suffix=".h5")
    os.close(fd)
    try:
        with h5py.File(path, "w") as f:
            d = f.create_dataset("pool", shape=(nframes, height, width),
                                 dtype=dtype, chunks=(1, height, width), **kwargs)
            for i, fr in enumerate(frames):
                d[i] = fr
        pool = []
        with h5py.File(path, "r") as f:
            d = f["pool"]
            for i, fr in enumerate(frames):
                _mask, blob = d.id.read_direct_chunk((i, 0, 0))
                pool.append({
                    "blob": bytes(blob),
                    "crc32": zlib.crc32(np.ascontiguousarray(fr).tobytes()),
                    "raw_nbytes": fr.nbytes,
                })
    finally:
        os.unlink(path)

    raw = sum(e["raw_nbytes"] for e in pool)
    comp = sum(len(e["blob"]) for e in pool)
    ratio = raw / comp if comp else 1.0
    log.info(f"pool: {nframes} frames {height}x{width} {dtype} {compression} "
             f"ratio={ratio:.2f}x ({raw / 1e6:.1f} MB raw -> {comp / 1e6:.1f} MB)")
    return pool, ratio


def selftest_roundtrip(pool, height, width, dtype, compression):
    """Prove blob/filter byte-format compatibility: write_direct_chunk one
    pool blob into a fresh dataset with the matching filter, read it back
    through the normal h5py (filter-decoding) path, compare CRC32."""
    entry = pool[0]
    kwargs = filter_kwargs(compression)
    fd, path = tempfile.mkstemp(suffix=".h5")
    os.close(fd)
    try:
        with h5py.File(path, "w") as f:
            d = f.create_dataset("d", shape=(1, height, width), dtype=dtype,
                                 chunks=(1, height, width), **kwargs)
            d.id.write_direct_chunk((0, 0, 0), entry["blob"], filter_mask=0)
        with h5py.File(path, "r") as f:
            back = f["d"][0]
    finally:
        os.unlink(path)
    crc = zlib.crc32(np.ascontiguousarray(back).tobytes())
    if crc != entry["crc32"]:
        raise RuntimeError(
            f"selftest FAILED: direct-chunk-write round-trip CRC mismatch "
            f"({crc:#x} != {entry['crc32']:#x}) for compression={compression}")
    log.info(f"selftest PASS: {compression} blob round-trips bit-exact "
             f"through write_direct_chunk + h5py read")


# ----------------------------------------------------------------------
# ZMQ producer
# ----------------------------------------------------------------------
def control_endpoint(endpoint):
    """Control (PUB) endpoint = data endpoint with port+1."""
    base, port = endpoint.rsplit(":", 1)
    return f"{base}:{int(port) + 1}"


def attach_peer_monitor(sock):
    """Attach the connection monitor BEFORE bind so no accept is missed."""
    return sock.get_monitor_socket(zmq.EVENT_ACCEPTED | zmq.EVENT_CONNECTED)


def wait_for_peers(sock, mon, n, timeout, label):
    """Block until n consumers have connected to the bound socket."""
    poller = zmq.Poller()
    poller.register(mon, zmq.POLLIN)
    got = 0
    deadline = time.monotonic() + timeout
    try:
        while got < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise RuntimeError(
                    f"only {got}/{n} consumers connected to {label} "
                    f"within {timeout}s")
            if poller.poll(min(left, 1.0) * 1000):
                ev = recv_monitor_message(mon)
                if ev["event"] in (zmq.EVENT_ACCEPTED, zmq.EVENT_CONNECTED):
                    got += 1
    finally:
        sock.disable_monitor()
        mon.close()
    log.info(f"{n} consumer(s) connected to {label}")


def stream(args):
    dtype = np.dtype(args.dtype)
    height, width = args.height, args.width
    pool, ratio = build_pool(args.pool, height, width, dtype, args.compression,
                             args.background_lam, args.seed)
    if not args.no_selftest:
        selftest_roundtrip(pool, height, width, dtype, args.compression)

    enc = encoding_label(args.compression, dtype)
    est_comp = int(np.mean([len(e["blob"]) for e in pool]))

    ctrl_ep = control_endpoint(args.endpoint)
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDHWM, args.sndhwm)
    mon_push = attach_peer_monitor(sock)   # attach BEFORE bind (no race)
    sock.bind(args.endpoint)
    ctrl = ctx.socket(zmq.PUB)
    mon_pub = attach_peer_monitor(ctrl)
    ctrl.bind(ctrl_ep)
    log.info(f"bound PUSH {args.endpoint} + PUB {ctrl_ep}, waiting for "
             f"{args.expect_peers} consumer(s)...")
    wait_for_peers(sock, mon_push, args.expect_peers, args.peer_timeout, "PUSH")
    wait_for_peers(ctrl, mon_pub, args.expect_peers, args.peer_timeout, "PUB")
    time.sleep(0.5)  # PUB slow-joiner: let subscriptions propagate

    header = {"htype": "dheader-1.0", "series": args.series}
    config = {
        "nimages": args.frames,
        "shape": [height, width],
        "dtype": str(dtype),
        "encoding": enc,
        "compression": args.compression,
        "est_comp_bytes": est_comp,
        "nwriters": args.expect_peers,
    }
    # Series header is BROADCAST so every consumer gets the config
    ctrl.send_multipart([json.dumps(header).encode(),
                         json.dumps(config).encode()])

    npool = len(pool)
    sent_raw = 0
    sent_comp = 0
    t0 = time.monotonic()
    for i in range(args.frames):
        e = pool[i % npool]
        if args.fps > 0:
            target = t0 + i / args.fps
            now = time.monotonic()
            if target > now:
                time.sleep(target - now)
        t_frame = time.monotonic()
        hdr = json.dumps({"htype": "dimage-1.0", "series": args.series,
                          "frame": i}).encode()
        meta = json.dumps({"shape": [height, width], "type": str(dtype),
                           "encoding": enc, "size": len(e["blob"]),
                           "size_raw": e["raw_nbytes"],
                           "crc32": e["crc32"]}).encode()
        times = json.dumps({"htype": "dimage_times-1.0",
                            "real_time_ns": int((time.monotonic() - t_frame) * 1e9),
                            "frame_time_ns": int(t_frame * 1e9)}).encode()
        sock.send_multipart([hdr, meta, e["blob"], times], copy=False)
        sent_raw += e["raw_nbytes"]
        sent_comp += len(e["blob"])
    t1 = time.monotonic()

    # End markers: N best-effort copies on PUSH (ordered after the frames on
    # each connection -- the fast path) + one PUB broadcast (the guaranteed
    # path when round-robin was skewed by a full peer queue).
    end = json.dumps({"htype": "dseries_end-1.0", "series": args.series}).encode()
    for _ in range(args.expect_peers):
        sock.send_multipart([end])
    ctrl.send_multipart([end])

    send_s = t1 - t0
    stats = {
        "role": "producer",
        "endpoint": args.endpoint,
        "control_endpoint": ctrl_ep,
        "frames": args.frames,
        "shape": [height, width],
        "dtype": str(dtype),
        "compression": args.compression,
        "encoding": enc,
        "pool_frames": npool,
        "compression_ratio": round(ratio, 3),
        "fps_limit": args.fps,
        "send_window_s": round(send_s, 4),
        "send_fps": round(args.frames / send_s, 1) if send_s > 0 else None,
        "send_raw_GBps": round(sent_raw / send_s / 1e9, 4) if send_s > 0 else None,
        "send_comp_GBps": round(sent_comp / send_s / 1e9, 4) if send_s > 0 else None,
        "raw_bytes": sent_raw,
        "comp_bytes": sent_comp,
        "note": ("send window = enqueue time on the PUSH socket; consumer-side "
                 "write window is the authoritative throughput measure"),
    }
    log.info(f"sent {args.frames} frames in {send_s:.2f}s "
             f"(enqueue rate {stats['send_raw_GBps']} GB/s raw, "
             f"{stats['send_fps']} fps)")

    # Linger so queued messages drain before the context closes
    sock.setsockopt(zmq.LINGER, int(args.drain_timeout * 1000))
    sock.close()
    ctrl.close(linger=int(args.drain_timeout * 1000))
    ctx.term()

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(stats, f, indent=1)
        log.info(f"stats -> {args.json_out}")
    return stats


def main():
    p = argparse.ArgumentParser(
        description="EIGER2 SIMPLON-style ZMQ stream simulator")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--frames", type=int, default=1000)
    p.add_argument("--fps", type=float, default=0.0,
                   help="frame rate limit, 0 = max rate (default)")
    p.add_argument("--width", type=int, default=DEFAULT_SHAPE[1])
    p.add_argument("--height", type=int, default=DEFAULT_SHAPE[0])
    p.add_argument("--dtype", choices=["uint8", "uint16", "uint32"],
                   default="uint16")
    p.add_argument("--compression", choices=["bslz4", "lz4", "zlib", "none"],
                   default="bslz4")
    p.add_argument("--pool", type=int, default=DEFAULT_POOL,
                   help="distinct pre-compressed frames to cycle")
    p.add_argument("--background-lam", type=float, default=2.0,
                   help="Poisson background mean (compressibility knob)")
    p.add_argument("--seed", type=int, default=20260612)
    p.add_argument("--series", type=int, default=1)
    p.add_argument("--expect-peers", type=int, default=1,
                   help="consumers that must connect before streaming")
    p.add_argument("--peer-timeout", type=float, default=PEER_WAIT_TIMEOUT)
    p.add_argument("--drain-timeout", type=float, default=60.0,
                   help="LINGER seconds for queued messages at close")
    p.add_argument("--sndhwm", type=int, default=DEFAULT_SNDHWM)
    p.add_argument("--json-out", default="", help="write producer stats JSON")
    p.add_argument("--no-selftest", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        stream(args)
    except Exception:
        log.exception("stream failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
