#!/usr/bin/env bash
# Phase-1 C2: EIGER2 writer benchmark matrix (VM1).
# Sequential short runs; every run's data files are deleted after their size
# is recorded; df is captured before and after as cleanup proof.
# Production services (:8001/:8002, soft IOC :5064) are not touched -- the
# harness only uses loopback TCP port 17711.
#
# Usage: bash run_vm1_bench.sh [PYTHON] [SRCDIR] [WORKDIR]
set -u

PY=${1:-$HOME/eiger2_eval/.venv/bin/python}
SRC=${2:-$HOME/eiger2_eval/detector_eval}
WORK=${3:-$HOME/eiger2_eval}
RUNS=$WORK/runs
DISK=$WORK/data
SHM=/dev/shm/eiger2_eval
EP=tcp://127.0.0.1:17711
FRAMES=${FRAMES:-3000}        # bslz4 runs (raw 6.55 GB, ~1.4 GB on storage)
FRAMES_NONE=${FRAMES_NONE:-1000}  # uncompressed runs (raw = stored 2.18 GB)

mkdir -p "$RUNS" "$DISK" "$SHM"
rm -f "$RUNS"/*.json "$RUNS"/*.txt

echo "=== df BEFORE ==="
df -h / /dev/shm | tee "$RUNS/df_before.txt"

# args: label mode writers outdir compression frames fps dtype
run_case () {
  label=$1; mode=$2; writers=$3; outdir=$4; comp=$5; frames=$6; fps=$7; dtype=$8
  echo ""
  echo "--- $label (mode=$mode writers=$writers comp=$comp frames=$frames fps=$fps dtype=$dtype) ---"
  rm -f "$outdir"/*.h5
  "$PY" "$SRC/writer_bench.py" --mode "$mode" --writers "$writers" \
      --outdir "$outdir" --endpoint "$EP" \
      --json-out "$RUNS/${label}_writer.json" &
  wpid=$!
  sleep 1
  "$PY" "$SRC/eiger2_stream_sim.py" --endpoint "$EP" \
      --expect-peers "$writers" --frames "$frames" --fps "$fps" \
      --compression "$comp" --dtype "$dtype" \
      --json-out "$RUNS/${label}_producer.json"
  wait $wpid
  du -sb "$outdir" 2>/dev/null | tee "$RUNS/${label}_du.txt"
  rm -f "$outdir"/*.h5
  sleep 1
}

# --- transport ceiling (no file writes) ---
run_case null_bslz4          null   1 "$DISK" bslz4 "$FRAMES"      0   uint16

# --- bslz4 (EIGER2 production compression), max rate ---
run_case single_disk_bslz4   single 1 "$DISK" bslz4 "$FRAMES"      0   uint16
run_case single_shm_bslz4    single 1 "$SHM"  bslz4 "$FRAMES"      0   uint16
run_case shard2_disk_bslz4   shard  2 "$DISK" bslz4 "$FRAMES"      0   uint16
run_case shard2_shm_bslz4    shard  2 "$SHM"  bslz4 "$FRAMES"      0   uint16
run_case shard4_disk_bslz4   shard  4 "$DISK" bslz4 "$FRAMES"      0   uint16
run_case shard4_shm_bslz4    shard  4 "$SHM"  bslz4 "$FRAMES"      0   uint16

# --- uncompressed (apples-to-apples with the C1 NDFileHDF5 table) ---
run_case single_disk_none    single 1 "$DISK" none  "$FRAMES_NONE" 0   uint16
run_case single_shm_none     single 1 "$SHM"  none  "$FRAMES_NONE" 0   uint16
run_case shard2_disk_none    shard  2 "$DISK" none  "$FRAMES_NONE" 0   uint16
run_case shard4_disk_none    shard  4 "$DISK" none  "$FRAMES_NONE" 0   uint16

# --- dtype variant + a rate-limited steady-state demo ---
run_case single_disk_bslz4_u32 single 1 "$DISK" bslz4 1500         0   uint32
run_case rate500_disk_bslz4  single 1 "$DISK" bslz4 2500           500 uint16

echo ""
echo "=== cleanup ==="
rm -rf "$SHM"
rm -f "$DISK"/*.h5
echo "=== df AFTER ==="
df -h / /dev/shm | tee "$RUNS/df_after.txt"

# --- merge everything into one machine-tagged result file ---
"$PY" - "$RUNS" "$WORK/eiger2_writer_bench.json" <<'PYEOF'
import glob
import json
import os
import platform
import subprocess
import sys
import time

runs_dir, out_path = sys.argv[1], sys.argv[2]

def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except OSError:
        return None

def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None

import numpy, h5py, zmq
try:
    import hdf5plugin
    h5p_ver = getattr(hdf5plugin, "version", "?")
except ImportError:
    h5p_ver = None

mem_kb = 0
with open("/proc/meminfo") as f:
    for line in f:
        if line.startswith("MemTotal"):
            mem_kb = int(line.split()[1])
            break

labels = sorted({os.path.basename(p).rsplit("_", 1)[0]
                 for p in glob.glob(os.path.join(runs_dir, "*_writer.json"))})
runs = []
for label in labels:
    du_txt = read_text(os.path.join(runs_dir, f"{label}_du.txt"))
    runs.append({
        "label": label,
        "producer": read_json(os.path.join(runs_dir, f"{label}_producer.json")),
        "writer": read_json(os.path.join(runs_dir, f"{label}_writer.json")),
        "du_bytes_before_delete": int(du_txt.split()[0]) if du_txt else None,
    })

combined = {
    "title": "EIGER2 stream-writer benchmark (Phase-1 C2)",
    "machine": {
        "tag": "operations VM (testbed)",
        "hostname": platform.node(),
        "kernel": platform.release(),
        "cpus": os.cpu_count(),
        "mem_MB": mem_kb // 1024,
        "storage": {"disk": "VM virtual disk /dev/xvda2 (ext4, ~/eiger2_eval)",
                    "tmpfs": "/dev/shm"},
    },
    "date": time.strftime("%Y-%m-%d %H:%M:%S"),
    "python": sys.version.split()[0],
    "packages": {"numpy": numpy.__version__, "h5py": h5py.__version__,
                 "hdf5plugin": h5p_ver, "pyzmq": zmq.__version__},
    "conventions": {
        "GB": "1e9 bytes",
        "raw_GBps": "uncompressed detector-data rate (spec-comparable)",
        "comp_GBps": "actual bytes-to-storage rate",
        "writer_window": "first frame recv -> file closed + fsync",
        "aggregate_window": "max(t_end) - min(t_first) across writers",
    },
    "df_before": read_text(os.path.join(runs_dir, "df_before.txt")),
    "df_after": read_text(os.path.join(runs_dir, "df_after.txt")),
    "runs": runs,
}
with open(out_path, "w") as f:
    json.dump(combined, f, indent=1)
print(f"merged {len(runs)} runs -> {out_path}")
PYEOF

echo "DONE"
