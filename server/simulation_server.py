"""
K4GSR Simulation Server -- Standalone WebSocket server for virtual experiments.

Provides high-fidelity physics simulations using xraylib, fisx, pymatgen, pyFAI, Larch.
Runs on a separate port (default 8002) from the main beamline server (8001).

Usage:
    python server/simulation_server.py [--port 8002] [--host 0.0.0.0]

Protocol (same as /ws/expt):
    Client -> Server:  {action: 'run',  mode: 'xrf2d', params: {..., beamline: {...}}}
    Client -> Server:  {action: 'cancel'}
    Client -> Server:  {action: 'list_modes'}
    Server -> Client:  {type: 'expt_progress', fraction: 0.5, msg: '...'}
    Server -> Client:  {type: 'expt_result',   mode: 'xrf2d', ...}
    Server -> Client:  {type: 'expt_done',     elapsed_sec: 1.23}
    Server -> Client:  {type: 'expt_error',    message: '...'}
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time

from constants import SIM_PORT

# Fix UnicodeEncodeError on Windows Korean OS
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sim-server")


# ---------------------------------------------------------------------------
# Engine discovery
# ---------------------------------------------------------------------------
def _discover_engines():
    """Import and instantiate all available simulation engines."""
    engines = {}
    engine_classes = []

    # Try importing each engine module
    try:
        from sim_engines.xrf_engine import XRFEngine
        engine_classes.append(XRFEngine)
    except ImportError as e:
        log.warning(f"XRF engine not available: {e}")

    try:
        from sim_engines.xrd_engine import XRDEngine
        engine_classes.append(XRDEngine)
    except ImportError as e:
        log.debug(f"XRD engine not available: {e}")

    try:
        from sim_engines.xafs_engine import XAFSEngine
        engine_classes.append(XAFSEngine)
    except ImportError as e:
        log.debug(f"XAFS engine not available: {e}")

    try:
        from sim_engines.xrdmap_engine import XRDMapEngine
        engine_classes.append(XRDMapEngine)
    except ImportError as e:
        log.debug(f"XRD Map engine not available: {e}")

    for cls in engine_classes:
        try:
            if cls.available():
                eng = cls()
                engines[eng.name()] = eng
                log.info(f"  Engine loaded: {eng.name()}")
            else:
                log.warning(f"  Engine {cls.__name__} not available (missing deps)")
        except Exception as e:
            log.warning(f"  Engine {cls.__name__} init failed: {e}")

    return engines


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------
class SimulationServer:
    def __init__(self, host="0.0.0.0", port=SIM_PORT):
        self.host = host
        self.port = port
        self.clients = set()
        self._engines = {}
        self._running_task = None

    async def handler(self, websocket):
        """Handle a single WebSocket connection."""
        self.clients.add(websocket)
        remote = websocket.remote_address
        log.info(f"Client connected: {remote}")

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "expt_error",
                        "message": "Invalid JSON",
                    }))
                    continue

                action = msg.get("action", "")

                if action == "run":
                    await self._handle_run(websocket, msg)

                elif action == "cancel":
                    await self._handle_cancel(websocket)

                elif action == "list_modes":
                    await websocket.send(json.dumps({
                        "type": "expt_modes",
                        "modes": list(self._engines.keys()),
                    }))

                elif action == "status":
                    await websocket.send(json.dumps({
                        "type": "sim_status",
                        "engines": list(self._engines.keys()),
                        "server": "simulation_server",
                        "port": self.port,
                    }))

                else:
                    await websocket.send(json.dumps({
                        "type": "expt_error",
                        "message": f"Unknown action: {action}",
                    }))

        except websockets.ConnectionClosed:
            log.info(f"Client disconnected: {remote}")
        except Exception as e:
            log.error(f"Handler error: {e}", exc_info=True)
        finally:
            self.clients.discard(websocket)

    async def _handle_run(self, ws, msg):
        """Dispatch an experiment run to the appropriate engine."""
        mode = msg.get("mode", "")
        params = msg.get("params", {})

        # Extract beamline context (same pattern as experiment_engine.py)
        beamline = params.pop("beamline", {})
        if not beamline:
            beamline = {
                "energy_keV": 10.0,
                "spot_h_nm": 50,
                "spot_v_nm": 50,
                "flux": 1e10,
                "ssaH": 50,
                "ssaV": 50,
            }

        engine = self._engines.get(mode)
        if not engine:
            available = list(self._engines.keys())
            await ws.send(json.dumps({
                "type": "expt_error",
                "message": f"Unknown mode '{mode}'. Available: {available}",
            }))
            return

        t0 = time.time()
        try:
            engine.reset()
            log.info(f"Running {mode}: E={beamline.get('energy_keV',0):.3f}keV, "
                     f"flux={beamline.get('flux',0):.2e}, "
                     f"spot={beamline.get('spot_h_nm',0):.0f}x"
                     f"{beamline.get('spot_v_nm',0):.0f}nm, "
                     f"SSA={beamline.get('ssaH',0)}x{beamline.get('ssaV',0)}um")
            await engine.run(ws, params, beamline)
            elapsed = time.time() - t0
            log.info(f"  {mode} completed in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0
            log.error(f"  {mode} error after {elapsed:.2f}s: {e}", exc_info=True)
            await ws.send(json.dumps({
                "type": "expt_error",
                "message": str(e),
            }))

    async def _handle_cancel(self, ws):
        """Cancel the running simulation."""
        for eng in self._engines.values():
            eng.cancel()
        await ws.send(json.dumps({"type": "expt_cancelled"}))
        log.info("Simulation cancelled by client")

    async def start(self):
        """Start the WebSocket server."""
        # Discover engines
        self._engines = _discover_engines()

        if not self._engines:
            log.warning("No simulation engines available! "
                        "Install: pip install xraylib fisx")

        log.info(f"Starting simulation server on ws://{self.host}:{self.port}/ws/sim")
        log.info(f"  Available modes: {list(self._engines.keys())}")

        async with websockets.serve(
            self.handler,
            self.host,
            self.port,
            max_size=50 * 1024 * 1024,  # 50 MB max message
            ping_interval=30,
            ping_timeout=60,
        ) as server:
            log.info(f"Simulation server ready on port {self.port}")
            # Wait forever
            await asyncio.Future()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="K4GSR Simulation Server")
    parser.add_argument("--port", type=int, default=SIM_PORT,
                        help=f"WebSocket port (default: {SIM_PORT})")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    # Add server/ to sys.path so sim_engines can be imported
    import os
    server_dir = os.path.dirname(os.path.abspath(__file__))
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)

    server = SimulationServer(host=args.host, port=args.port)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        log.info("Server stopped by user")


if __name__ == "__main__":
    main()
