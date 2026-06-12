---
title: "detector_eval — EIGER2 Data-Path Evaluation Harness"
category: other
status: current
updated: 2026-06-12
tags: [phase1, detector, eiger2, simplon, zeromq, hdf5, odin, benchmark]
summary: "SIMPLON-style ZMQ 스트림 시뮬레이터 + 단일/N-shard HDF5 writer 벤치마크 사용법. 결과/결정은 docs/tasks/TASK_C2_EIGER2_EVAL.md."
---

# detector_eval — EIGER2 high-rate data-path evaluation harness (Phase-1 C2)

Quantifies the writer topologies available for the future EIGER2 integration
(manuscript ¶27/28) **without detector hardware**: a SIMPLON-stream-style ZMQ
producer feeds synthetic compressed EIGER2-like frames to interchangeable
consumers, so the single-writer ceiling (NDFileHDF5-like) can be compared
against the Odin-style N-writer sharded topology on the same machine.

Results + decision: `docs/tasks/TASK_C2_EIGER2_EVAL.md`.
Measured baseline this extends: `docs/tasks/TASK_C1_ADSIM.md` §4 (NDFileHDF5
single-writer ceiling on VM1).

## Files

| File | Purpose |
|------|---------|
| `eiger2_stream_sim.py` | ZMQ PUSH producer. SIMPLON-stream-v1-style messages (`dheader-1.0` / `dimage-1.0` / `dseries_end-1.0`); synthetic 1.09-Mpixel frames; bslz4 / lz4 / zlib / none compression **performed by the HDF5 filter pipeline itself** (`read_direct_chunk`), so blobs are byte-exact filter streams; startup self-test round-trips a blob through `write_direct_chunk` + h5py read (CRC32). |
| `writer_bench.py` | Consumer benchmark. Modes: `null` (transport ceiling), `single` (one writer, one chunked HDF5 file), `shard` (N writers, ZMQ round-robin farm-out, N shard files + VDS master — the odin-data topology). Direct chunk writes (zero recompression), fsync-closed timing window, CRC32 read-back verification, C1 ENOSPC budget rule (abort if estimate > 40% of free space). |
| `run_vm1_bench.sh` | Sequential benchmark matrix driver for VM1. Captures `df` before/after, deletes all data files after each run, merges per-run JSONs into one machine-tagged result file. |

## Dependencies

Separate venv (do **not** install into the production `~/K4GSR-Beamline/.venv`):

```bash
mkdir -p ~/eiger2_eval && cd ~/eiger2_eval
python3.11 -m venv .venv
.venv/bin/pip install numpy h5py hdf5plugin pyzmq
```

`hdf5plugin` provides the bitshuffle-LZ4 (32008) and LZ4 (32004) HDF5 filters
used both to build the compressed frame pool and to decode on verification.

## Quick start (two terminals, any machine)

```bash
# 1) consumers first (they connect and wait)
python writer_bench.py --mode shard --writers 4 --outdir /dev/shm/ew \
    --endpoint tcp://127.0.0.1:17711 --json-out w.json

# 2) producer (binds, waits for 4 connections, streams, sends 4 end msgs)
python eiger2_stream_sim.py --endpoint tcp://127.0.0.1:17711 \
    --expect-peers 4 --frames 3000 --compression bslz4 --json-out p.json
```

`--expect-peers` must equal the consumer count. Two channels are used (both
must be free): frames go over PUSH on the given endpoint; the series header
and end marker are broadcast over PUB on **port+1** (PUSH round-robin cannot
guarantee per-peer delivery of control messages when a peer queue is full).
Writers also get best-effort PUSH end copies, ordered after their frames.

## Full matrix on VM1

```bash
# from the dev PC (WSL)
scp eiger2_stream_sim.py writer_bench.py run_vm1_bench.sh \
    <user>@<operations-vm>:~/eiger2_eval/detector_eval/
ssh <user>@<operations-vm> 'bash ~/eiger2_eval/detector_eval/run_vm1_bench.sh'
# result: ~/eiger2_eval/eiger2_writer_bench.json  -> commit to paper/validation/data/
```

VM1 rules: production services (:8001/:8002, soft IOC :5064, ADSim :5080) are
never touched — the harness uses loopback TCP port 17711 only. Runs are
seconds-long, sequential, and every data file is deleted after its size is
recorded (`df` before/after is part of the result JSON).

## Measurement conventions

- **raw GB/s** (GB = 1e9 bytes): uncompressed detector-data rate — the number
  comparable to detector specifications and to the C1 NDFileHDF5 table.
- **comp GB/s**: actual bytes-to-storage rate after compression.
- Writer window: first frame received → file closed **and fsync'd**
  (stricter than C1, which noted its disk numbers were page-cache-assisted).
- Aggregate over N writers: `max(t_end) - min(t_first)`.
- Integrity: every run CRC32-checks sample frames read back through the
  normal h5py filter-decoding path; shard runs additionally CRC-check global
  frames through the VDS master.

## Known limitations (also in TASK_C2_EIGER2_EVAL.md)

- Loopback ZMQ, not a real 10/40 GbE NIC + DCU; no packet loss / NIC IRQ load.
- Frame pool of 8 distinct images cycled (Python cannot generate GB/s of
  unique data) — compression ratio is fixed by the pool, stated per run.
- Synthetic compressibility (Poisson background + spots + ring + gap bands)
  approximates but does not reproduce real diffraction statistics.
- Python writers; odin-data's C++ FrameReceiver/FrameProcessor would have
  lower per-frame overhead. Numbers here are a *lower bound* on the topology.
