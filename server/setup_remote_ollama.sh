#!/bin/bash
# =============================================================
#  K4GSR Remote Server Setup for A6000 Workstation
#  Installs: Ollama + Qwen3/GLM models + Python server + file sync
#  Run this on the Linux workstation
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================"
echo "  K4GSR Remote Server Setup (A6000 Workstation)"
echo "================================================"
echo ""

# -----------------------------------------------------------
# 1. Check GPU & RAM
# -----------------------------------------------------------
echo "[1/7] Checking hardware..."
if command -v nvidia-smi &> /dev/null; then
    echo "GPU:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "WARNING: nvidia-smi not found. Install NVIDIA drivers first."
    echo "  Ubuntu: sudo apt install nvidia-driver-550"
    exit 1
fi
TOTAL_RAM=$(free -g | awk '/Mem:/{print $2}')
echo "RAM: ${TOTAL_RAM}GB"
echo ""

# -----------------------------------------------------------
# 2. Install Ollama
# -----------------------------------------------------------
echo "[2/7] Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo "Ollama already installed: $(ollama --version)"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Ollama installed."
fi
echo ""

# -----------------------------------------------------------
# 3. Configure Ollama to listen on all interfaces
# -----------------------------------------------------------
echo "[3/7] Configuring Ollama for remote access..."

OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
sudo mkdir -p "$OVERRIDE_DIR"
sudo tee "$OVERRIDE_DIR/override.conf" > /dev/null <<'CONF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
CONF

sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 2

echo "Ollama now listening on 0.0.0.0:11434"
echo ""

# -----------------------------------------------------------
# 4. Pull models
# -----------------------------------------------------------
echo "[4/7] Pulling Ollama models..."

echo ""
echo "--- qwen3:32b (20GB, dense, primary) ---"
ollama pull qwen3:32b

echo ""
echo "--- GLM-5 cloud (Ollama hosted, 744B MoE) ---"
ollama pull glm-5:cloud || echo "GLM-5 cloud pull failed. May need latest Ollama version."

echo ""
echo "Optional large models (pull manually if needed):"
echo "  ollama pull qwen3:235b-a22b     # 142GB, MoE, local"
echo ""
echo "--- GLM-5 local GGUF (for offline use) ---"
if [ "$TOTAL_RAM" -ge 256 ] 2>/dev/null; then
    echo "RAM >= 256GB detected. You can run GLM-5 Q2 locally."
    echo "To install GLM-5 GGUF locally:"
    echo "  pip install huggingface-hub hf-transfer"
    echo "  huggingface-cli download unsloth/GLM-5-GGUF UD-IQ2_XXS/GLM-5-UD-IQ2_XXS.gguf --local-dir ./models"
    echo "  # Then register with Ollama via Modelfile or use llama.cpp directly"
else
    echo "RAM < 256GB. GLM-5 local GGUF not recommended."
    echo "Use glm-5:cloud (Ollama hosted) instead."
fi
echo ""

# -----------------------------------------------------------
# 5. Python environment + dependencies
# -----------------------------------------------------------
echo "[5/7] Setting up Python environment..."

if command -v python3.11 &> /dev/null; then
    PY=python3.11
elif command -v python3 &> /dev/null; then
    PY=python3
    echo "WARNING: python3.11 preferred. Using $($PY --version)"
else
    echo "ERROR: Python not found. Install Python 3.11:"
    echo "  sudo apt install python3.11 python3.11-venv"
    exit 1
fi

VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PY -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install websockets requests python-dotenv aiohttp -q
echo "Python environment ready: $(python --version)"
echo ""

# -----------------------------------------------------------
# 6. Configure .env
# -----------------------------------------------------------
echo "[6/7] Configuring .env..."

ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
    echo "Created .env from .env.example"
fi

sed -i 's/^NLP_ENGINE=.*/NLP_ENGINE=ollama/' "$ENV_FILE"
sed -i 's/^OLLAMA_MODEL=.*/OLLAMA_MODEL=qwen3:32b/' "$ENV_FILE"
echo "Set NLP_ENGINE=ollama, OLLAMA_MODEL=qwen3:32b"
echo ""

# -----------------------------------------------------------
# 7. Setup file sync (rsync watcher)
# -----------------------------------------------------------
echo "[7/7] Setting up file sync helper..."

cat > "$PROJECT_DIR/sync_from_dev.sh" <<'SYNCEOF'
#!/bin/bash
# =============================================================
#  Sync server/ files from development PC via rsync
#  Usage: ./sync_from_dev.sh <DEV_PC_IP> [SSH_USER]
#  Example: ./sync_from_dev.sh 192.168.1.100 owner
# =============================================================
DEV_IP="${1:?Usage: $0 <DEV_PC_IP> [SSH_USER]}"
DEV_USER="${2:-owner}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Syncing from ${DEV_USER}@${DEV_IP}..."
rsync -avz --delete \
    -e ssh \
    "${DEV_USER}@${DEV_IP}:/c/Projects/K4GSR-Beamline/server/" \
    "$PROJECT_DIR/server/" \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc'

rsync -avz \
    -e ssh \
    "${DEV_USER}@${DEV_IP}:/c/Projects/K4GSR-Beamline/js/nlp/" \
    "$PROJECT_DIR/js/nlp/"

echo "Sync complete. Restart server if needed:"
echo "  kill \$(pgrep -f 'python server/server.py') 2>/dev/null; python server/server.py &"
SYNCEOF
chmod +x "$PROJECT_DIR/sync_from_dev.sh"

# Auto-sync watcher (optional - uses inotifywait)
cat > "$PROJECT_DIR/watch_and_restart.sh" <<'WATCHEOF'
#!/bin/bash
# =============================================================
#  Watch server/ for changes and auto-restart Python server
#  Usage: ./watch_and_restart.sh
#  Requires: inotify-tools (sudo apt install inotify-tools)
# =============================================================
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v inotifywait &> /dev/null; then
    echo "Install inotify-tools first: sudo apt install inotify-tools"
    exit 1
fi

echo "Watching server/ for changes... (Ctrl+C to stop)"

# Start server initially
source "$PROJECT_DIR/.venv/bin/activate"
python "$PROJECT_DIR/server/server.py" &
SERVER_PID=$!
echo "Server started (PID: $SERVER_PID)"

while true; do
    inotifywait -q -r -e modify,create "$PROJECT_DIR/server/" --include '\.py$'
    echo ""
    echo "[$(date +%H:%M:%S)] File changed. Restarting server..."
    kill $SERVER_PID 2>/dev/null
    sleep 1
    python "$PROJECT_DIR/server/server.py" &
    SERVER_PID=$!
    echo "Server restarted (PID: $SERVER_PID)"
done
WATCHEOF
chmod +x "$PROJECT_DIR/watch_and_restart.sh"

echo "Created sync helpers:"
echo "  sync_from_dev.sh     - Pull files from dev PC via rsync"
echo "  watch_and_restart.sh - Auto-restart server on file changes"
echo ""

echo ""
echo "================================================"
echo "  Setup Complete!"
echo "================================================"
echo ""

MY_IP=$(hostname -I | awk '{print $1}')
echo "Workstation IP: $MY_IP"
echo ""
echo "========== Quick Reference =========="
echo ""
echo "--- Start server ---"
echo "  cd $PROJECT_DIR"
echo "  source .venv/bin/activate"
echo "  python server/server.py"
echo ""
echo "--- Or use auto-restart watcher ---"
echo "  ./watch_and_restart.sh"
echo ""
echo "--- Sync files from dev PC (no git needed) ---"
echo "  ./sync_from_dev.sh <DEV_PC_IP> <SSH_USER>"
echo ""
echo "--- Switch model ---"
echo "  Edit server/.env -> OLLAMA_MODEL=glm-5:cloud"
echo "  Edit server/.env -> OLLAMA_MODEL=qwen3:32b"
echo "  Edit server/.env -> OLLAMA_MODEL=qwen3:235b-a22b"
echo ""
echo "--- Run NLP tests ---"
echo "  python server/test_nlp_qwen3.py"
echo ""
echo "--- On Windows PC ---"
echo "  Browser: file:///V4_36.html?server=$MY_IP"
echo "  WebSocket auto-connects to ws://$MY_IP:8001"
echo ""
