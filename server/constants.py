import os
"""Centralized constants for K4GSR beamline server.

All magic numbers (ports, timeouts, prefixes) should be defined here
and imported by other server modules. See docs/knowledge/28_python_coding_standard.md.
"""

# --- Network Ports ---
WS_PORT = 8001          # Main WebSocket server
SIM_PORT = 8002         # Simulation server (xraylib/pyFAI)
PTYCHO_PORT = 8765      # Ptycho reconstruction server
EPICS_CA_PORT = 5064    # caproto Soft IOC (Channel Access)
KOHZU_CA_PORT = 5070    # KOHZU ARIES hardware IOC
XBPM2_CA_PORT = 5072    # Sydor T4U quadEM IOC

# --- Hardware IPs (SW4 Device Network) ---
KOHZU_IP = os.environ.get("KOHZU_IP", "<YOUR_DEVICE_IP>")  # Override via environment
XBPM2_IP = os.environ.get("XBPM2_IP", "<YOUR_DEVICE_IP>")  # Override via environment

# --- Timeouts (seconds) ---
CA_CONNECT_TIMEOUT = 3.0        # caproto Context.get_pvs() timeout
CA_SUBSCRIBE_TIMEOUT = 5.0      # _stop_ptycho_server wait timeout
BLUESKY_CONNECT_TIMEOUT = 10.0  # ophyd device connection (standalone)
BLUESKY_HYBRID_TIMEOUT = 3.0    # ophyd device connection (hybrid mode)
PV_DISCOVERY_INTERVAL = 30.0    # PV auto-discovery probe interval

# --- PV ---
PV_PREFIX = "BL10"      # Beamline PV prefix

# --- Scan ---
DEFAULT_SCAN_RATE = 0.1  # PVStore heartbeat interval (seconds)

# --- PV push (B3: event-triggered broadcast, manuscript ¶78) ---
# Defaults only -- server.py reads the env vars at task-start time (after
# deploy/config.env has been loaded), NOT at import time, so config.env
# values are honored.
PV_PUSH_MODE_DEFAULT = "event"       # "event" | "periodic" (env PV_PUSH_MODE)
PV_PUSH_COALESCE_MS_DEFAULT = 50.0   # burst coalescing window (env PV_PUSH_COALESCE_MS)
PV_PUSH_SNAPSHOT_S_DEFAULT = 5.0     # idle keepalive/full-snapshot period (env PV_PUSH_SNAPSHOT_S)

# --- Scan backend (B1: bluesky-queueserver, manuscript para 31) ---
# server.py reads SCAN_BACKEND at task-start time (after config.env load), NOT
# at import time, so config.env is honored. "inprocess" is the regression-
# critical default; "qserver" builds QueueServerRunner instead.
SCAN_BACKEND_DEFAULT = "inprocess"   # "inprocess" | "qserver" (env SCAN_BACKEND)
QSERVER_ZMQ_PORT = 60615             # RE Manager 0MQ control port (zmq REQ/REP)
QSERVER_ZMQ_INFO_PORT = 60625        # RE Manager 0MQ console/status publish port
QSERVER_REDIS_PORT = 60617           # Redis (or fakeredis) port used by RE Manager
QSERVER_POLL_INTERVAL = 0.5          # status poll interval (seconds)
QSERVER_STARTUP_TIMEOUT = 60.0       # max wait for RE Manager to answer status

# --- Tiled data-access PoC (B2, manuscript para 39) ---
# LOCAL PoC ONLY, opt-in, default-OFF. Operational deployment + facility auth
# are deferred to B4 (see docs/tasks/TASK_B2_TILED.md). The production server.py
# does NOT start this; tiled_serve.py is a standalone launcher.
TILED_ENABLED_DEFAULT = False        # env TILED_ENABLED ("1"/"true" enables)
TILED_PORT = 8010                    # local Tiled HTTP port (loopback only)
TILED_HOST = "127.0.0.1"             # bind loopback only (no facility exposure)
TILED_STARTUP_TIMEOUT = 60.0         # max wait for Tiled /healthz to answer
TILED_POLL_INTERVAL = 0.25           # readiness poll interval (seconds)
