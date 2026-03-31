#!/bin/bash
# Run vLLM 32b benchmark after waiting for 235b Ollama benchmark to finish.
# Usage: nohup bash server/run_vllm_benchmark.sh &> /tmp/vllm_bench.log &
#
# Steps:
#   1. Wait for any running benchmark (PID 111014 or test_nlp_benchmark.py)
#   2. Unload Ollama models to free GPU VRAM
#   3. Start vLLM server in background (downloads Qwen3-32B if needed)
#   4. Wait for vLLM to be ready (health check)
#   5. Run benchmark with NLP_ENGINE=vllm
#   6. Shut down vLLM server

set -e
cd "$(dirname "$0")/.."
LOG=/tmp/vllm_bench.log

echo "=== vLLM Benchmark Script ==="
echo "Started: $(date)"
echo ""

# ── Step 1: Wait for running benchmark ──
echo "[1/6] Waiting for existing benchmarks to finish..."
while pgrep -f "test_nlp_benchmark.py" > /dev/null 2>&1; do
    echo "  Benchmark still running ($(date +%H:%M:%S)), waiting 60s..."
    sleep 60
done
echo "  No benchmarks running."

# ── Step 2: Unload Ollama models ──
echo "[2/6] Unloading Ollama models to free VRAM..."
# Send keep_alive=0 to unload all models
curl -s http://localhost:11434/api/ps | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    name = m['name']
    print(f'  Unloading {name}...')
" 2>/dev/null || true

# Force unload by generating with keep_alive=0
for model in $(curl -s http://localhost:11434/api/ps | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    print(m['name'])
" 2>/dev/null); do
    curl -s http://localhost:11434/api/generate -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":0}" > /dev/null 2>&1 || true
    echo "  Sent unload request for $model"
done

sleep 5
echo "  Ollama models unloaded."

# ── Step 3: Start vLLM server ──
echo "[3/6] Starting vLLM server..."
source .venv/bin/activate

# Check if model is already downloaded
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-32B}"
echo "  Model: $VLLM_MODEL"
echo "  If first run, model download (~64GB) will take time."

python3 -m vllm.entrypoints.openai.api_server \
    --model "$VLLM_MODEL" \
    --tensor-parallel-size 2 \
    --max-model-len 16384 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.90 \
    --port 8000 \
    --disable-log-requests \
    --trust-remote-code &
VLLM_PID=$!
echo "  vLLM PID: $VLLM_PID"

# ── Step 4: Wait for vLLM to be ready ──
echo "[4/6] Waiting for vLLM to be ready..."
MAX_WAIT=600
WAITED=0
while ! curl -s http://localhost:8000/health > /dev/null 2>&1; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "  ERROR: vLLM did not start within ${MAX_WAIT}s"
        kill $VLLM_PID 2>/dev/null || true
        exit 1
    fi
    echo "  Not ready yet (${WAITED}s elapsed), waiting 15s..."
    sleep 15
    WAITED=$((WAITED + 15))
done
echo "  vLLM server ready! (took ${WAITED}s)"

# ── Step 5: Run benchmark ──
echo "[5/6] Running vLLM benchmark..."
echo "  Start time: $(date)"

NLP_ENGINE=vllm \
VLLM_MODEL="$VLLM_MODEL" \
VLLM_BASE_URL="http://localhost:8000/v1" \
python3 server/test_nlp_benchmark.py --engine vllm

echo "  End time: $(date)"

# ── Step 6: Shut down vLLM ──
echo "[6/6] Shutting down vLLM server..."
kill $VLLM_PID 2>/dev/null || true
wait $VLLM_PID 2>/dev/null || true
echo "  vLLM server stopped."

echo ""
echo "=== vLLM Benchmark Complete ==="
echo "Finished: $(date)"
