#!/bin/bash
# =============================================================
#  K4GSR NLP Workstation Setup Script
#  Target: A6000 x2 (96GB VRAM) workstation
#  Usage:  bash setup_workstation.sh
# =============================================================

set -e

echo "================================================"
echo "  K4GSR NLP Workstation Setup"
echo "  A6000 x2 (96GB VRAM)"
echo "================================================"
echo ""

# -----------------------------------------------------------
# 1. Check NVIDIA GPU
# -----------------------------------------------------------
echo "[1/6] Checking GPU..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "WARNING: nvidia-smi not found. Install NVIDIA drivers first."
fi
echo ""

# -----------------------------------------------------------
# 2. Install Ollama
# -----------------------------------------------------------
echo "[2/6] Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo "Ollama already installed: $(ollama --version)"
else
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Ollama installed: $(ollama --version)"
fi
echo ""

# -----------------------------------------------------------
# 3. Pull models
# -----------------------------------------------------------
echo "[3/6] Pulling Ollama models..."
echo "This will download large models. Make sure you have enough disk space."
echo ""

# Primary: Qwen3-32B (dense, best for fine-tuning, ~20GB Q4)
echo "--- Pulling qwen3:32b (20GB, dense, primary) ---"
ollama pull qwen3:32b

# Secondary: Qwen3-235B-A22B (MoE, highest baseline, ~142GB Q4)
echo ""
echo "--- Pulling qwen3:235b-a22b (142GB, MoE, secondary) ---"
echo "This is a very large download. Press Ctrl+C to skip."
echo "You can pull it later with: ollama pull qwen3:235b-a22b"
sleep 3
ollama pull qwen3:235b-a22b || echo "Skipped 235b. Pull later if needed."

echo ""

# -----------------------------------------------------------
# 4. Python environment
# -----------------------------------------------------------
echo "[4/6] Setting up Python 3.11 environment..."

if command -v python3.11 &> /dev/null; then
    PY=python3.11
elif command -v python3 &> /dev/null; then
    PY=python3
    echo "WARNING: python3.11 not found, using $(python3 --version)"
else
    echo "ERROR: Python not found. Install Python 3.11 first."
    echo "  sudo apt install python3.11 python3.11-venv"
    exit 1
fi

# Create venv if not exists
VENV_DIR="$(dirname "$0")/../.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PY -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install requests python-dotenv aiohttp

# For fine-tuning (install separately if needed)
echo ""
echo "For LoRA fine-tuning, also install:"
echo "  pip install unsloth torch transformers datasets peft trl"
echo ""

# -----------------------------------------------------------
# 5. Configure .env
# -----------------------------------------------------------
echo "[5/6] Configuring .env..."

ENV_FILE="$(dirname "$0")/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$(dirname "$0")/.env.example" "$ENV_FILE"
    echo "Created .env from .env.example"
fi

# Set to use ollama with qwen3:32b
sed -i 's/^NLP_ENGINE=.*/NLP_ENGINE=ollama/' "$ENV_FILE"
sed -i 's/^OLLAMA_MODEL=.*/OLLAMA_MODEL=qwen3:32b/' "$ENV_FILE"
echo "Set NLP_ENGINE=ollama, OLLAMA_MODEL=qwen3:32b"
echo ""

# -----------------------------------------------------------
# 6. Verify setup
# -----------------------------------------------------------
echo "[6/6] Verifying..."

echo "--- Ollama models ---"
ollama list

echo ""
echo "--- Quick model test ---"
echo "Testing qwen3:32b with a simple prompt..."
ollama run qwen3:32b --format json "Reply with JSON: {\"status\": \"ok\"}" 2>/dev/null | head -1 || echo "Model test skipped (ollama serve may not be running)"

echo ""
echo "================================================"
echo "  Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Start Ollama server:  ollama serve"
echo "  2. Run baseline test:    python server/test_nlp_qwen3.py"
echo "  3. If pass rate < 95%:   python server/lora_finetune.py"
echo "  4. Try 235b model:       Edit .env -> OLLAMA_MODEL=qwen3:235b-a22b"
echo ""
echo "Test with different models:"
echo "  OLLAMA_MODEL=qwen3:32b  python server/test_nlp_qwen3.py"
echo "  OLLAMA_MODEL=qwen3:235b-a22b  python server/test_nlp_qwen3.py"
echo ""
