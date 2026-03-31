#!/bin/bash
# K4GSR Virtual Beamline -- one-click startup script
# Usage: bash server/start_beamline.sh
# Starts: (1) caproto Soft IOC, (2) main server (auto-detects Bluesky mode)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="/tmp"
IOC_LOG="$LOG_DIR/soft_ioc.log"
SERVER_LOG="$LOG_DIR/beamline_server.log"

# Use venv python if available, else system python
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "============================================"
echo "  K4GSR Virtual Beamline Startup"
echo "============================================"
echo "Project: $PROJECT_DIR"
echo "Python:  $VENV_PYTHON"
echo ""

# --- Stop existing processes ---
echo "[1/3] Stopping existing processes..."
pkill -f "soft_ioc.py" 2>/dev/null || true
pkill -f "server/server.py" 2>/dev/null || true
sleep 1

# --- Start Soft IOC ---
echo "[2/3] Starting caproto Soft IOC..."
cd "$PROJECT_DIR"
nohup "$VENV_PYTHON" server/epics/soft_ioc.py --interfaces 0.0.0.0 > "$IOC_LOG" 2>&1 &
IOC_PID=$!
echo "  PID: $IOC_PID (log: $IOC_LOG)"

# Wait for IOC to be ready (listen on port 5064)
echo "  Waiting for IOC..."
for i in $(seq 1 10); do
    if "$VENV_PYTHON" -c "
from caproto.threading.client import Context
ctx = Context()
pvs = ctx.get_pvs('BL10:DCM:Theta', timeout=2)
resp = pvs[0].read(timeout=2)
print('BL10:DCM:Theta =', float(resp.data[0]))
" 2>/dev/null; then
        echo "  Soft IOC ready."
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "  WARNING: IOC not responding after 20s. Check $IOC_LOG"
    fi
    sleep 2
done

# --- Start Main Server ---
echo "[3/3] Starting main server (auto-detect mode)..."
nohup "$VENV_PYTHON" server/server.py > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
echo "  PID: $SERVER_PID (log: $SERVER_LOG)"

# Wait for server to be ready
sleep 5

echo ""
echo "============================================"
echo "  Startup Complete"
echo "============================================"
echo "  Soft IOC:  PID $IOC_PID  (port 5064)"
echo "  Server:    PID $SERVER_PID  (port 8001)"
echo ""
echo "  Logs:"
echo "    IOC:    tail -f $IOC_LOG"
echo "    Server: tail -f $SERVER_LOG"
echo ""
echo "  Status:"
grep -E "(Auto-detect|ready|Started|endpoint)" "$SERVER_LOG" 2>/dev/null || echo "  (server still starting...)"
echo ""
echo "  Connect browser to: http://<this-ip>:8001"
echo "============================================"
