#!/bin/bash
# =============================================================
#  K4GSR BL10 NanoProbe -- Service Control Script
#
#  Usage:
#    bash deploy/beamline_ctl.sh start    # Start all services
#    bash deploy/beamline_ctl.sh stop     # Stop all services
#    bash deploy/beamline_ctl.sh restart  # Restart all services
#    bash deploy/beamline_ctl.sh status   # Show service status
#    bash deploy/beamline_ctl.sh logs     # Tail all logs
#    bash deploy/beamline_ctl.sh logs ioc # Tail specific service log
#    bash deploy/beamline_ctl.sh health   # Run health checks
#
#  All settings from deploy/config.env.
# =============================================================

set -uo pipefail

# Ignore SIGHUP so SSH disconnects don't kill the startup process
trap '' HUP

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[ERROR] Config file not found: $CONFIG_FILE"
    exit 1
fi

source "$CONFIG_FILE"

# ---- Auto-detect actual install dir (override config.env if needed) ----
# The script lives in deploy/, so the repo root is one level up.
_ACTUAL_INSTALL="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ ! -d "$INSTALL_DIR" ] || [ ! -f "${INSTALL_DIR}/server/server.py" ]; then
    INSTALL_DIR="$_ACTUAL_INSTALL"
fi
# Use project dir for logs if LOG_DIR doesn't exist and can't be created
if [ ! -d "$LOG_DIR" ]; then
    if mkdir -p "$LOG_DIR" 2>/dev/null; then
        : # created OK
    else
        LOG_DIR="$INSTALL_DIR"
    fi
fi

# ---- Derived variables ----
VENV_PYTHON="${INSTALL_DIR}/.venv/bin/python"
IOC_LOG="${LOG_DIR}/soft_ioc.log"
SERVER_LOG="${LOG_DIR}/server.log"
SIM_LOG="${LOG_DIR}/simulation.log"

# PID files for non-systemd mode
PID_DIR="${LOG_DIR}/pids"
IOC_PID_FILE="${PID_DIR}/soft_ioc.pid"
XBPM2_PID_FILE="${PID_DIR}/xbpm2_ioc.pid"
SERVER_PID_FILE="${PID_DIR}/server.pid"
SIM_PID_FILE="${PID_DIR}/simulation.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# ---- Detect service manager ----
# Use systemd if services are installed, otherwise use direct process management
USE_SYSTEMD="no"
if systemctl list-unit-files k4gsr-server.service &>/dev/null 2>&1; then
    USE_SYSTEMD="yes"
fi

# ---- Helper functions ----

_is_port_open() {
    local port="$1"
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":${port} "
    elif command -v netstat &>/dev/null; then
        netstat -tlnp 2>/dev/null | grep -q ":${port} "
    else
        return 1
    fi
}

_read_pid() {
    local pid_file="$1"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$pid_file"
    fi
    return 1
}

_build_server_args() {
    local args=""
    case "$SERVER_MODE" in
        standalone)
            args="--standalone"
            ;;
        full)
            args="--ca-bridge --bluesky"
            ;;
        hybrid)
            args="--ca-bridge --bluesky"
            if [ -n "$SOFT_IOC_EXCLUDE_GROUPS" ]; then
                args="$args --exclude-groups $SOFT_IOC_EXCLUDE_GROUPS"
            fi
            ;;
    esac
    args="$args --port ${PORT_SERVER}"
    echo "$args"
}

# ==============================================================
# Commands
# ==============================================================

cmd_start() {
    echo -e "${CYAN}Starting K4GSR Beamline services...${NC}"
    echo "  Mode: $SERVER_MODE"
    echo ""

    mkdir -p "$PID_DIR"

    if [ "$USE_SYSTEMD" = "yes" ]; then
        # ---- systemd mode ----
        if [ "$ENABLE_SOFT_IOC" = "yes" ]; then
            echo -n "  [IOC]    "
            sudo systemctl start k4gsr-ioc.service && echo -e "${GREEN}started${NC}" || echo -e "${RED}failed${NC}"
        fi

        echo -n "  [Server] "
        sudo systemctl start k4gsr-server.service && echo -e "${GREEN}started${NC}" || echo -e "${RED}failed${NC}"

    else
        # ---- direct process mode ----
        cd "$INSTALL_DIR"

        # 1. Soft IOC
        if [ "$ENABLE_SOFT_IOC" = "yes" ]; then
            if _is_port_open "$PORT_EPICS_CA"; then
                echo -e "  [IOC]    ${YELLOW}already running (port $PORT_EPICS_CA)${NC}"
            else
                local ioc_args="--interfaces 0.0.0.0"
                # soft_ioc always serves ALL PVs (including SAM group).
                # In hybrid mode, KOHZU IOC also serves BL10:SAM:CX/CY/CZ.
                # CA Bridge ADDR_LIST has KOHZU port first → CX/CY/CZ go to KOHZU.
                # SAM sub-motors (FX/FY/FZ/Phi/SX/SY/Theta) not in KOHZU yet →
                # served by soft_ioc (simulation) until real hardware arrives.
                echo -n "  [IOC]    starting... "
                nohup "$VENV_PYTHON" server/epics/soft_ioc.py $ioc_args \
                    >> "$IOC_LOG" 2>&1 &
                echo $! > "$IOC_PID_FILE"
                echo -e "${GREEN}PID $! (log: $IOC_LOG)${NC}"

                # Wait for IOC readiness
                for i in $(seq 1 15); do
                    if _is_port_open "$PORT_EPICS_CA"; then
                        echo -e "  [IOC]    ${GREEN}ready${NC}"
                        break
                    fi
                    if [ "$i" -eq 15 ]; then
                        echo -e "  [IOC]    ${YELLOW}timeout waiting for port $PORT_EPICS_CA${NC}"
                    fi
                    sleep 1
                done
            fi
        fi

        # 2. XBPM2 IOC (T4U quadEM, only in hybrid mode)
        if [ "$SERVER_MODE" = "hybrid" ] && [ -n "${XBPM2_IOC_DIR:-}" ] && [ -d "${XBPM2_IOC_DIR}" ]; then
            if pgrep -f "quadEMTestApp.*st.cmd" > /dev/null 2>&1; then
                echo -e "  [XBPM2]  ${YELLOW}already running${NC}"
            else
                echo -n "  [XBPM2]  starting... "
                _XBPM2_DIR="$XBPM2_IOC_DIR"
                _XBPM2_BIN="$(cd "$XBPM2_IOC_DIR/../.." && pwd)/bin/linux-x86_64/quadEMTestApp"
                _XBPM2_LOG="${XBPM2_LOG:-$HOME/xbpm2_ioc.log}"
                nohup bash -c "export EPICS_CAS_SERVER_PORT=${XBPM2_CA_PORT:-5072}; cd '$_XBPM2_DIR' && tail -f /dev/null | '$_XBPM2_BIN' st.cmd" \
                    >> "$_XBPM2_LOG" 2>&1 &
                echo $! > "$XBPM2_PID_FILE"
                echo -e "${GREEN}PID $! (log: $_XBPM2_LOG)${NC}"
                sleep 3
                if pgrep -f "quadEMTestApp.*st.cmd" > /dev/null 2>&1; then
                    echo -e "  [XBPM2]  ${GREEN}ready${NC}"
                else
                    echo -e "  [XBPM2]  ${YELLOW}may have failed -- check log${NC}"
                fi
            fi
        fi

        # 3. Main Server
        if _is_port_open "$PORT_SERVER"; then
            echo -e "  [Server] ${YELLOW}already running (port $PORT_SERVER)${NC}"
        else
            local server_args
            server_args=$(_build_server_args)
            echo -n "  [Server] starting ($SERVER_MODE mode)... "
            # Export nano scanner hardware config to server subprocess
            local _env_exports=""
            if [ -n "${SMARACT_LIB_DIR:-}" ]; then
                _env_exports="export LD_LIBRARY_PATH=${SMARACT_LIB_DIR}:\${LD_LIBRARY_PATH:-}; "
            fi
            if [ -n "${MCS2_BRIDGE_HOST:-}" ]; then
                _env_exports="${_env_exports}export MCS2_BRIDGE_HOST='${MCS2_BRIDGE_HOST}'; "
                _env_exports="${_env_exports}export MCS2_BRIDGE_PORT='${MCS2_BRIDGE_PORT:-5555}'; "
            fi
            if [ -n "${PICOSCALE_LOCATOR:-}" ]; then
                _env_exports="${_env_exports}export PICOSCALE_LOCATOR='${PICOSCALE_LOCATOR}'; "
            fi
            nohup bash -c "${_env_exports}\"$VENV_PYTHON\" server/server.py $server_args" \
                >> "$SERVER_LOG" 2>&1 &
            echo $! > "$SERVER_PID_FILE"
            echo -e "${GREEN}PID $! (log: $SERVER_LOG)${NC}"

            # Wait for readiness (CA Bridge + Bluesky init can take ~60s)
            for i in $(seq 1 90); do
                if _is_port_open "$PORT_SERVER"; then
                    echo -e "  [Server] ${GREEN}ready (${i}s)${NC}"
                    break
                fi
                if [ "$i" -eq 90 ]; then
                    echo -e "  [Server] ${YELLOW}timeout waiting for port $PORT_SERVER${NC}"
                fi
                sleep 1
            done
        fi

        # 4. Simulation Server (optional, with watchdog auto-restart)
        if [ "$ENABLE_SIMULATION_SERVER" = "yes" ]; then
            if _is_port_open "$PORT_SIMULATION"; then
                echo -e "  [SimSrv] ${YELLOW}already running (port $PORT_SIMULATION)${NC}"
            else
                echo -n "  [SimSrv] starting... "
                # Watchdog: automatically restarts simulation_server.py if it crashes
                _SIM_PY="$VENV_PYTHON"
                _SIM_DIR="$INSTALL_DIR"
                _SIM_LOG="$SIM_LOG"
                nohup bash -c "
while true; do
    cd '$_SIM_DIR'
    '$_SIM_PY' server/simulation_server.py >> '$_SIM_LOG' 2>&1
    echo '[watchdog] simulation_server exited, restarting in 3s...' >> '$_SIM_LOG'
    sleep 3
done" &
                echo $! > "$SIM_PID_FILE"
                echo -e "${GREEN}PID $! (watchdog)${NC}"

                # Wait for readiness
                for i in $(seq 1 15); do
                    if _is_port_open "$PORT_SIMULATION"; then
                        echo -e "  [SimSrv] ${GREEN}ready (${i}s)${NC}"
                        break
                    fi
                    if [ "$i" -eq 15 ]; then
                        echo -e "  [SimSrv] ${YELLOW}timeout waiting for port $PORT_SIMULATION${NC}"
                    fi
                    sleep 1
                done
            fi
        fi
    fi

    echo ""
    cmd_status
}

cmd_stop() {
    echo -e "${CYAN}Stopping K4GSR Beamline services...${NC}"

    if [ "$USE_SYSTEMD" = "yes" ]; then
        echo -n "  [Server] "
        sudo systemctl stop k4gsr-server.service 2>/dev/null && echo -e "${GREEN}stopped${NC}" || echo "not running"
        echo -n "  [IOC]    "
        sudo systemctl stop k4gsr-ioc.service 2>/dev/null && echo -e "${GREEN}stopped${NC}" || echo "not running"
    else
        # Stop by PID file, then fallback to pkill
        for svc in server simulation xbpm2_ioc soft_ioc; do
            local pid_file="${PID_DIR}/${svc}.pid"
            local pid
            if pid=$(_read_pid "$pid_file"); then
                kill "$pid" 2>/dev/null
                rm -f "$pid_file"
            fi
        done

        # Fallback: force-kill by process name (SIGKILL for reliability)
        pkill -9 -f "server/server.py" 2>/dev/null || true
        pkill -9 -f "simulation_server.py" 2>/dev/null || true
        pkill -9 -f "soft_ioc.py" 2>/dev/null || true
        pkill -9 -f "quadEMTestApp.*st.cmd" 2>/dev/null || true

        sleep 2
        echo -e "  ${GREEN}All services stopped.${NC}"
    fi
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

cmd_status() {
    echo -e "${CYAN}K4GSR Beamline Service Status${NC}"
    echo "  Mode: $SERVER_MODE"
    echo ""

    # Check each port
    local services=("Soft IOC:${PORT_EPICS_CA}" "Server:${PORT_SERVER}" "Simulation:${PORT_SIMULATION}")

    for entry in "${services[@]}"; do
        local name="${entry%%:*}"
        local port="${entry##*:}"
        printf "  %-14s port %-5s " "[$name]" "$port"

        if _is_port_open "$port"; then
            echo -e "${GREEN}RUNNING${NC}"
        else
            echo -e "${RED}STOPPED${NC}"
        fi
    done

    echo ""

    # vLLM workstation connectivity
    printf "  %-14s %s:%s " "[vLLM]" "$VLLM_HOST" "$VLLM_PORT"
    if curl -s --connect-timeout 3 "http://${VLLM_HOST}:${VLLM_PORT}/health" &>/dev/null || \
       curl -s --connect-timeout 3 "http://${VLLM_HOST}:${VLLM_PORT}/v1/models" &>/dev/null; then
        echo -e "${GREEN}REACHABLE${NC}"
    else
        echo -e "${YELLOW}UNREACHABLE${NC}"
    fi

    # KOHZU controller (only in hybrid mode)
    if [ "$SERVER_MODE" = "hybrid" ]; then
        printf "  %-14s %s:%s " "[KOHZU]" "$KOHZU_CONTROLLER_IP" "$KOHZU_CONTROLLER_PORT"
        if timeout 2 bash -c "echo > /dev/tcp/$KOHZU_CONTROLLER_IP/$KOHZU_CONTROLLER_PORT" 2>/dev/null; then
            echo -e "${GREEN}REACHABLE${NC}"
        else
            echo -e "${YELLOW}UNREACHABLE${NC}"
        fi

        # XBPM2 T4U electrometer
        if [ -n "${XBPM2_IP:-}" ]; then
            printf "  %-14s %s " "[XBPM2]" "$XBPM2_IP"
            if timeout 2 ping -c 1 "$XBPM2_IP" &>/dev/null; then
                echo -e "${GREEN}REACHABLE${NC}"
            else
                echo -e "${YELLOW}UNREACHABLE${NC}"
            fi
        fi
    fi
}

cmd_logs() {
    local target="${1:-all}"

    case "$target" in
        ioc)    tail -f "$IOC_LOG" ;;
        server) tail -f "$SERVER_LOG" ;;
        sim)    tail -f "$SIM_LOG" ;;
        all)    tail -f "$IOC_LOG" "$SERVER_LOG" 2>/dev/null ;;
        *)      echo "Usage: beamline_ctl.sh logs [ioc|server|sim|all]"; exit 1 ;;
    esac
}

cmd_health() {
    echo -e "${CYAN}K4GSR Health Check${NC}"
    echo ""

    local all_ok=true

    # 1. Server WebSocket
    echo -n "  [WS Connect]   "
    if command -v python3 &>/dev/null; then
        if python3 -c "
import asyncio, websockets
async def check():
    async with websockets.connect('ws://localhost:${PORT_SERVER}/ws/pv') as ws:
        await ws.send('{\"action\":\"get_all\"}')
        resp = await asyncio.wait_for(ws.recv(), timeout=5)
        return len(resp) > 10
asyncio.run(check())
" 2>/dev/null; then
            echo -e "${GREEN}OK${NC}"
        else
            echo -e "${RED}FAIL${NC}"
            all_ok=false
        fi
    else
        echo -e "${YELLOW}SKIP (python3 not found)${NC}"
    fi

    # 2. EPICS CA (if IOC enabled)
    if [ "$ENABLE_SOFT_IOC" = "yes" ]; then
        echo -n "  [EPICS CA]      "
        if "$VENV_PYTHON" -c "
from caproto.threading.client import Context
ctx = Context()
pvs = ctx.get_pvs('BL10:DCM:Theta', timeout=3)
resp = pvs[0].read(timeout=3)
print(float(resp.data[0]))
" 2>/dev/null; then
            echo -e "  ${GREEN}OK${NC}"
        else
            echo -e "${RED}FAIL${NC}"
            all_ok=false
        fi
    fi

    # 3. vLLM
    echo -n "  [vLLM API]      "
    if curl -s --connect-timeout 5 "http://${VLLM_HOST}:${VLLM_PORT}/v1/models" 2>/dev/null | grep -q "id"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${YELLOW}UNAVAILABLE (NLP will use fallback)${NC}"
    fi

    echo ""
    if [ "$all_ok" = true ]; then
        echo -e "  Overall: ${GREEN}HEALTHY${NC}"
    else
        echo -e "  Overall: ${RED}DEGRADED${NC}"
    fi
}

# ==============================================================
# Main
# ==============================================================

case "${1:-help}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    logs)    cmd_logs "${2:-all}" ;;
    health)  cmd_health ;;
    *)
        echo "K4GSR Beamline Service Control"
        echo ""
        echo "Usage: $(basename "$0") <command>"
        echo ""
        echo "Commands:"
        echo "  start    Start all configured services"
        echo "  stop     Stop all services"
        echo "  restart  Stop then start all services"
        echo "  status   Show service status and port checks"
        echo "  logs     Tail service logs (logs [ioc|server|sim|all])"
        echo "  health   Run connectivity health checks"
        echo ""
        echo "Config: $CONFIG_FILE"
        ;;
esac
