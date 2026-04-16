#!/bin/bash
# Start vLLM server for Qwen3-32B with optimizations
# Usage: bash server/start_vllm.sh
#
# Requires: pip install vllm (in the active venv)
# Hardware: 2x NVIDIA A6000 (96GB total VRAM)
#
# The model will be downloaded from HuggingFace on first run (~64GB).
# Subsequent runs use the cached model.

set -e

MODEL="${VLLM_MODEL:-Qwen/Qwen3-32B}"
PORT="${VLLM_PORT:-8000}"
TP="${VLLM_TP:-2}"           # tensor parallel across 2 GPUs
MAX_LEN="${VLLM_MAX_LEN:-16384}"

echo "Starting vLLM server..."
echo "  Model: $MODEL"
echo "  Port: $PORT"
echo "  Tensor Parallel: $TP GPUs"
echo "  Max Seq Len: $MAX_LEN"
echo "  Prefix Caching: enabled"
echo ""

python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --tensor-parallel-size "$TP" \
    --max-model-len "$MAX_LEN" \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.90 \
    --port "$PORT" \
    --no-enable-log-requests \
    --trust-remote-code
