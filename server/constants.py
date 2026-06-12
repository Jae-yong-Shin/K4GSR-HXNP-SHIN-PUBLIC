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
