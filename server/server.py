#!/usr/bin/env python3
"""K4GSR Virtual Beamline — WebSocket Server

Endpoints:
  ws://localhost:8001/ws/pv    EPICS PV bridge (SimIOC compatible)
  ws://localhost:8001/ws/chat  NLP chat agent (Claude API)
  ws://localhost:8001/ws/scan  Bluesky scan control (submit/abort/pause/resume)
  ws://localhost:8001/ws/expt  Virtual experiment engine (server-side computation)

Usage:
  python server/server.py --mode hybrid --port 8001        # Recommended: auto-reads deploy/config.env
  python server/server.py --mode standalone                # PVStore only (no EPICS, no Bluesky)
  python server/server.py --mode full                      # soft_ioc + CA bridge + Bluesky (no HW exclude)
  python server/server.py --ca-bridge --bluesky            # Explicit flags (legacy, still works)
  python server/server.py --ca-bridge --bluesky --exclude-groups SAM XBPM2 SCAN  # Explicit hybrid
"""

import asyncio
import json
import logging
import signal
import subprocess
import sys
import os
import time
from typing import Dict, Set

import websockets
from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers

from pv_store import PVStore
from constants import (WS_PORT, SIM_PORT, PTYCHO_PORT, EPICS_CA_PORT,
                       CA_CONNECT_TIMEOUT, BLUESKY_CONNECT_TIMEOUT,
                       BLUESKY_HYBRID_TIMEOUT, PV_DISCOVERY_INTERVAL,
                       DEFAULT_SCAN_RATE, PV_PUSH_MODE_DEFAULT,
                       PV_PUSH_COALESCE_MS_DEFAULT, PV_PUSH_SNAPSHOT_S_DEFAULT,
                       SCAN_BACKEND_DEFAULT)

# Optional CA bridge (for --ca-bridge mode)
try:
    from ca_bridge import CABridge
    _CA_AVAILABLE = True
except ImportError:
    _CA_AVAILABLE = False

# Optional NLP agent (fails gracefully if API key missing)
_NLP_IMPORT_ERROR = None
try:
    from nlp_agent import NLPAgent
    _NLP_AVAILABLE = True
except ImportError as e:
    _NLP_AVAILABLE = False
    _NLP_IMPORT_ERROR = str(e)
except Exception as e:
    _NLP_AVAILABLE = False
    _NLP_IMPORT_ERROR = str(e)

# Optional RAG engine (fails gracefully if chromadb/sentence-transformers missing)
_RAG_IMPORT_ERROR = None
try:
    from rag_engine import BeamlineRAG
    _RAG_AVAILABLE = True
except ImportError as e:
    _RAG_AVAILABLE = False
    _RAG_IMPORT_ERROR = str(e)
except Exception as e:
    _RAG_AVAILABLE = False
    _RAG_IMPORT_ERROR = str(e)

# Optional Bluesky scan engine (for --bluesky mode)
try:
    from scan_engine.runner import BlueskyRunner
    _BLUESKY_AVAILABLE = True
except ImportError:
    _BLUESKY_AVAILABLE = False

# Optional bluesky-queueserver backend (B1; opt-in via SCAN_BACKEND=qserver).
# Importing this must NOT affect the in-process default path in any way.
try:
    from scan_engine.qserver_runner import QueueServerRunner
    _QSERVER_AVAILABLE = True
except ImportError:
    _QSERVER_AVAILABLE = False

# Optional experiment engine (for /ws/expt)
try:
    from experiment_engine import ExperimentEngine
    _EXPT_AVAILABLE = True
except ImportError:
    _EXPT_AVAILABLE = False

# Optional PV auto-discovery (for hybrid mode)
try:
    from pv_discovery import PVDiscovery
    _DISCOVERY_AVAILABLE = True
except ImportError:
    _DISCOVERY_AVAILABLE = False

# Safety checker
try:
    from safety import SafetyChecker
    _SAFETY_AVAILABLE = True
except ImportError:
    _SAFETY_AVAILABLE = False

# Nano scanner service (MCS2 bridge + PicoScale)
try:
    from nano_scanner_service import NanoScannerService
    _NANO_AVAILABLE = True
except ImportError:
    _NANO_AVAILABLE = False

# C4: Structured logging with rotation
_LOG_FILE = os.environ.get("LOG_FILE", "")
_log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_datefmt = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(
    level=logging.INFO,
    format=_log_fmt,
    datefmt=_log_datefmt,
    force=True
)
if _LOG_FILE:
    import logging.handlers
    _rot_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=50 * 1024 * 1024, backupCount=5, encoding='utf-8')
    _rot_handler.setFormatter(logging.Formatter(_log_fmt, datefmt=_log_datefmt))
    logging.getLogger().addHandler(_rot_handler)
log = logging.getLogger("beamline-server")

# K4GSR-PTYCHO server subprocess management
_PTYCHO_PROJECT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "K4GSR-PTYCHO"))
_ptycho_proc = None

def _start_ptycho_server(port=8765):
    """Start K4GSR-PTYCHO ptycho_server.py as a subprocess."""
    global _ptycho_proc
    ptycho_script = os.path.join(_PTYCHO_PROJECT, "server", "ptycho_server.py")
    if not os.path.isfile(ptycho_script):
        log.warning(f"K4GSR-PTYCHO not found: {ptycho_script}")
        return False
    # Check if port is already in use (another instance running)
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", port))
        s.close()
    except OSError:
        log.info(f"K4GSR-PTYCHO port {port} already in use (server may be running)")
        return True
    # Start subprocess
    try:
        _ptycho_proc = subprocess.Popen(
            [sys.executable, ptycho_script, "--port", str(port)],
            cwd=_PTYCHO_PROJECT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        log.info(f"K4GSR-PTYCHO server started (PID {_ptycho_proc.pid}, port {port})")
        return True
    except Exception as e:
        log.warning(f"Failed to start K4GSR-PTYCHO server: {e}")
        return False

def _stop_ptycho_server():
    """Stop K4GSR-PTYCHO subprocess if we started it."""
    global _ptycho_proc
    if _ptycho_proc and _ptycho_proc.poll() is None:
        log.info(f"Stopping K4GSR-PTYCHO server (PID {_ptycho_proc.pid})...")
        _ptycho_proc.terminate()
        try:
            _ptycho_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ptycho_proc.kill()
        _ptycho_proc = None

# ── First-run .env setup ──
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def _interactive_setup():
    """Guide user through NLP backend configuration if .env is missing."""
    print("\n" + "=" * 60)
    print("  K4GSR Virtual Beamline - First Run Setup")
    print("=" * 60)
    print("\nNo .env file found. Let's configure the NLP chat backend.\n")
    print("Choose an NLP engine:\n")
    print("  1) ollama   - Local LLM (free, offline, requires Ollama installed)")
    print("  2) groq     - Groq API  (free tier, fast, needs API key)")
    print("  3) gemini   - Google Gemini (free tier, needs API key)")
    print("  4) claude   - Anthropic Claude (paid, highest quality)")
    print("  5) deepseek - DeepSeek (very cheap, $0.28/1M tok, good Korean)")
    print("  6) openai   - OpenAI GPT-4o-mini (reliable, $0.15/1M tok)")
    print("  7) mistral  - Mistral Small (cheapest, $0.06/1M tok)")
    print("  8) skip     - No NLP (server runs without chat feature)\n")

    choice = ""
    while choice not in ("1", "2", "3", "4", "5", "6", "7", "8"):
        choice = input("Enter choice [1-8]: ").strip()

    engines = {
        "1": "ollama", "2": "groq", "3": "gemini", "4": "claude",
        "5": "deepseek", "6": "openai", "7": "mistral"
    }
    if choice == "8":
        # Write minimal .env with no engine
        with open(_ENV_PATH, "w") as f:
            f.write("# NLP disabled\nNLP_ENGINE=\n")
        print("\nNLP disabled. You can edit server/.env later to enable it.")
        return

    engine = engines[choice]
    lines = [f"NLP_ENGINE={engine}\n"]

    if engine == "ollama":
        url = input("Ollama URL [http://localhost:11434]: ").strip()
        if not url:
            url = "http://localhost:11434"
        model = input("Ollama model [qwen2.5:7b]: ").strip()
        if not model:
            model = "qwen2.5:7b"
        lines.append(f"OLLAMA_URL={url}\n")
        lines.append(f"OLLAMA_MODEL={model}\n")
        print(f"\nMake sure Ollama is running with: ollama pull {model}")

    elif engine == "groq":
        print("\nGet a free API key at: https://console.groq.com/keys")
        key = input("GROQ_API_KEY: ").strip()
        lines.append(f"GROQ_API_KEY={key}\n")
        lines.append("GROQ_MODEL=llama-3.3-70b-versatile\n")

    elif engine == "gemini":
        print("\nGet a free API key at: https://aistudio.google.com/apikey")
        key = input("GOOGLE_API_KEY: ").strip()
        lines.append(f"GOOGLE_API_KEY={key}\n")
        lines.append("GEMINI_MODEL=gemini-2.0-flash\n")

    elif engine == "claude":
        print("\nGet an API key at: https://console.anthropic.com/settings/keys")
        key = input("ANTHROPIC_API_KEY: ").strip()
        lines.append(f"ANTHROPIC_API_KEY={key}\n")
        lines.append("CLAUDE_MODEL=claude-sonnet-4-5-20250929\n")

    elif engine == "deepseek":
        print("\nGet an API key at: https://platform.deepseek.com/api_keys")
        print("Free 10M tokens on signup, no credit card required.")
        key = input("DEEPSEEK_API_KEY: ").strip()
        lines.append(f"DEEPSEEK_API_KEY={key}\n")
        lines.append("DEEPSEEK_MODEL=deepseek-chat\n")

    elif engine == "openai":
        print("\nGet an API key at: https://platform.openai.com/api-keys")
        key = input("OPENAI_API_KEY: ").strip()
        lines.append(f"OPENAI_API_KEY={key}\n")
        lines.append("OPENAI_MODEL=gpt-4o-mini\n")

    elif engine == "mistral":
        print("\nGet an API key at: https://console.mistral.ai/api-keys")
        key = input("MISTRAL_API_KEY: ").strip()
        lines.append(f"MISTRAL_API_KEY={key}\n")
        lines.append("MISTRAL_MODEL=mistral-small-latest\n")

    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)
    print(f"\nSaved to server/.env (engine: {engine})")
    print("You can edit server/.env anytime to change settings.\n")

# ── Global State ──
pv_store = PVStore(scan_rate=DEFAULT_SCAN_RATE)
nlp_agent = None
bluesky_runner = None
expt_engine = None
nano_scanner_svc = None       # NanoScannerService instance
hw_groups: Set[str] = set()   # PV group prefixes served by real hardware IOC
pv_discovery = None           # PVDiscovery instance (hybrid mode only)
safety_checker = None         # SafetyChecker instance

# Client tracking: websocket → set of subscribed PV names
pv_clients: Dict[object, Set[str]] = {}
chat_clients: Set[object] = set()
scan_clients: Set[object] = set()
expt_clients: Set[object] = set()

# B3 (event push): wake-up signal for pv_event_push_loop. Set from caproto
# callback threads via loop.call_soon_threadsafe (see main()). The dirty-SET
# itself is CABridge._changed (a {pv: entry} map -- rapid changes to the same
# PV overwrite each other, last value wins), drained atomically by
# pv_store.get_changed().
_pv_dirty = asyncio.Event()


# ── WebSocket helpers ──
def _ws_error(msg: str) -> str:
    """Standardized WebSocket error response (all endpoints)."""
    return json.dumps({"type": "error", "message": msg})


# ══════════════════════════════════════════════════════════════════════
# PV Endpoint Handler
# ══════════════════════════════════════════════════════════════════════
async def pv_handler(websocket):
    """Handle a single PV client connection."""
    pv_clients[websocket] = set()
    remote = websocket.remote_address
    log.info(f"PV client connected: {remote}")

    # Send PV source info if hybrid mode (hw_groups non-empty)
    if hw_groups:
        sources = {}
        for pv_name in pv_store.pvs:
            is_hw = any(pv_name.startswith(f"BL10:{g}:") for g in hw_groups)
            sources[pv_name] = "hardware" if is_hw else "simulation"
        try:
            await websocket.send(json.dumps({
                "action": "pv_sources",
                "sources": sources,
                "hw_groups": list(hw_groups)
            }))
        except Exception:
            pass

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(_ws_error("Invalid JSON"))
                continue

            action = msg.get("action")
            pv_name = msg.get("pv")

            if action == "subscribe" and pv_name:
                pv_clients[websocket].add(pv_name)
                # Send current value immediately
                result = pv_store.caget(pv_name)
                if result:
                    await websocket.send(json.dumps(result))

            elif action == "put" and pv_name:
                value = msg.get("value")
                if value is not None:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        await websocket.send(_ws_error(f"Invalid value for {pv_name}"))
                        continue

                    # Safety check (if available)
                    if safety_checker is not None:
                        confirmed = msg.get("confirmed", False)
                        check = safety_checker.check_move(pv_name, value, confirmed)
                        if not check["ok"]:
                            await websocket.send(json.dumps({
                                "action": "safety_reject",
                                **check
                            }))
                            continue

                    ok = pv_store.caput(pv_name, value)
                    if not ok:
                        await websocket.send(_ws_error(f"Unknown PV: {pv_name}"))

            elif action == "get" and pv_name:
                result = pv_store.caget(pv_name)
                if result:
                    await websocket.send(json.dumps(result))
                else:
                    await websocket.send(_ws_error(f"Unknown PV: {pv_name}"))

            elif action == "home" and pv_name:
                # Home a motor: write 1 to .HOMF (forward home)
                direction = msg.get("direction", "forward")
                home_field = ".HOMF" if direction == "forward" else ".HOMR"
                home_pv = pv_name + home_field
                log.info(f"Homing motor: {pv_name} ({direction})")
                try:
                    ok = pv_store.caput(home_pv, 1)
                    await websocket.send(json.dumps({
                        "action": "home",
                        "pv": pv_name,
                        "status": "started" if ok else "failed",
                        "direction": direction
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({
                        "action": "home",
                        "pv": pv_name,
                        "status": "error",
                        "error": str(e)
                    }))

            elif action == "estop":
                # Emergency stop: write 1 to .STOP for all motors (or specific PV)
                stopped = []
                if pv_name:
                    # Stop single motor
                    pv_store.caput(pv_name + ".STOP", 1)
                    stopped.append(pv_name)
                else:
                    # Stop ALL motors
                    for name in list(pv_store.pvs.keys()):
                        if hasattr(pv_store, '_motor_pvs'):
                            # CABridge: stop only motors
                            if name in pv_store._motor_pvs:
                                pv_store.caput(name + ".STOP", 1)
                                stopped.append(name)
                        else:
                            # PVStore: check if it has speed (is motor)
                            pv = pv_store.pvs.get(name)
                            if pv and hasattr(pv, 'speed') and pv.speed > 0:
                                pv.moving = False
                                stopped.append(name)
                log.warning(f"ESTOP: stopped {len(stopped)} motors")
                await websocket.send(json.dumps({
                    "action": "estop",
                    "stopped": stopped,
                    "count": len(stopped)
                }))

            elif action == "list":
                # Return list of all available PVs
                all_pvs = list(pv_store.pvs.keys())
                await websocket.send(json.dumps({
                    "action": "list",
                    "pvs": all_pvs,
                    "count": len(all_pvs)
                }))

            else:
                await websocket.send(_ws_error(f"Unknown action: {action}"))

    except websockets.ConnectionClosed:
        pass
    finally:
        pv_clients.pop(websocket, None)
        log.info(f"PV client disconnected: {remote}")


# ══════════════════════════════════════════════════════════════════════
# Chat Endpoint Handler
# ══════════════════════════════════════════════════════════════════════
async def chat_handler(websocket):
    """Handle a single NLP chat client connection."""
    chat_clients.add(websocket)
    remote = websocket.remote_address
    log.info(f"Chat client connected: {remote}")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(_ws_error("Invalid JSON"))
                continue

            action = msg.get("action")

            if action == "chat":
                text = msg.get("text", "").strip()
                context = msg.get("context", {})
                language = msg.get("language", "ko")
                log.info("Chat request: lang=%s, mode=%s, text='%s'",
                         language, context.get("mode", "?"), text[:80])

                if not text:
                    await websocket.send(_ws_error("Empty message"))
                    continue

                if nlp_agent is None:
                    reason = "NLP agent not available. "
                    if not _NLP_AVAILABLE:
                        reason += f"Import failed: {_NLP_IMPORT_ERROR}. Try: pip install httpx python-dotenv"
                    else:
                        engine = os.environ.get("NLP_ENGINE", "").strip()
                        if not engine:
                            reason += "NLP_ENGINE is empty in server/.env"
                        else:
                            reason += f"Engine '{engine}' failed to initialize. Check API key in server/.env"
                    await websocket.send(_ws_error(reason))
                    continue

                # Send "thinking" indicator
                await websocket.send(json.dumps({
                    "type": "thinking"
                }))

                # Get NLP response (async)
                try:
                    response = await nlp_agent.process(text, context, language=language)
                    await websocket.send(json.dumps(response))
                except Exception as e:
                    log.error(f"NLP error: {e}")
                    await websocket.send(_ws_error(f"NLP processing error: {str(e)}"))
                    continue

            elif action == "status":
                # Return beamline status summary
                ring_current = pv_store.caget("BL10:RING:Current")
                dcm_theta = pv_store.caget("BL10:DCM:Theta")
                ivu_gap = pv_store.caget("BL10:IVU:Gap")
                await websocket.send(json.dumps({
                    "type": "status",
                    "data": {
                        "ring_current": ring_current["value"] if ring_current else None,
                        "dcm_theta": dcm_theta["value"] if dcm_theta else None,
                        "ivu_gap": ivu_gap["value"] if ivu_gap else None,
                        "pv_count": len(pv_store.pvs),
                        "client_count": len(pv_clients) + len(chat_clients)
                    }
                }))

            else:
                await websocket.send(_ws_error(f"Unknown action: {action}"))

    except websockets.ConnectionClosed:
        pass
    finally:
        chat_clients.discard(websocket)
        log.info(f"Chat client disconnected: {remote}")


# ══════════════════════════════════════════════════════════════════════
# Scan Event Broadcast
# ══════════════════════════════════════════════════════════════════════
async def broadcast_scan_event(event: dict):
    """Broadcast a Bluesky scan event to all scan + chat clients."""
    event['_ts_ws_send'] = time.time()
    doc_type = event.get('doc_type', '?')
    msg = json.dumps(event)
    targets = list(scan_clients) + list(chat_clients)
    log.debug(f"Broadcast scan {doc_type} to {len(targets)} clients")
    for ws in targets:
        try:
            await ws.send(msg)
        except Exception as e:
            log.warning(f"Broadcast send error: {e}")


# ══════════════════════════════════════════════════════════════════════
# Scan Data Helpers
# ══════════════════════════════════════════════════════════════════════
def _load_scan_h5_data(uid, runner):
    """Load scan data from HDF5 file and return as JSON-serializable dict."""
    if not runner or not runner._scan_db:
        return {"type": "scan_data", "error": "No scan database"}

    scan = runner._scan_db.get_scan(uid)
    if not scan:
        return {"type": "scan_data", "error": f"Scan not found: {uid[:8]}"}

    h5_file = scan.get('h5_file')
    if not h5_file:
        return {"type": "scan_data", "error": "No H5 file for this scan"}

    scan_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), 'data', 'scans'))
    filepath = os.path.normpath(os.path.join(scan_dir, h5_file))
    if not filepath.startswith(scan_dir):
        return {"type": "scan_data", "error": "Invalid file path"}
    if not os.path.exists(filepath):
        return {"type": "scan_data", "error": f"H5 file not found: {h5_file}"}

    try:
        import h5py
        result = {"type": "scan_data", "uid": uid,
                  "plan_name": scan.get('plan_name', ''),
                  "data": {"columns": [], "values": {}, "n_points": 0}}
        with h5py.File(filepath, 'r') as f:
            data_grp = f.get('entry/data')
            if data_grp is None:
                return result
            for key in data_grp.keys():
                ds = data_grp[key]
                if len(ds.shape) == 1 and ds.shape[0] > 0:
                    values = ds[:].tolist()
                    result["data"]["columns"].append(key)
                    result["data"]["values"][key] = values
                    result["data"]["n_points"] = max(
                        result["data"]["n_points"], len(values))
        return result
    except Exception as e:
        return {"type": "scan_data", "error": str(e)}


def _encode_h5_for_download(uid, filename, runner):
    """Read H5 file and encode as base64 for browser download."""
    import base64

    scan_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), 'data', 'scans'))
    filepath = os.path.normpath(os.path.join(scan_dir, filename))
    if not filepath.startswith(scan_dir):
        return {"type": "h5_download", "error": "Invalid file path"}

    if not os.path.exists(filepath):
        return {"type": "h5_download", "error": f"File not found: {filename}"}

    # Limit file size to 50MB for WebSocket transfer
    file_size = os.path.getsize(filepath)
    if file_size > 50 * 1024 * 1024:
        return {"type": "h5_download",
                "error": f"File too large ({file_size // (1024*1024)}MB). "
                         "Use direct file access instead."}

    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        encoded = base64.b64encode(raw).decode('ascii')
        return {"type": "h5_download", "filename": filename,
                "data": encoded, "size": file_size}
    except Exception as e:
        return {"type": "h5_download", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# Scan Endpoint Handler
# ══════════════════════════════════════════════════════════════════════
async def scan_handler(websocket):
    """Handle a single Bluesky scan client connection."""
    scan_clients.add(websocket)
    remote = websocket.remote_address
    log.info(f"Scan client connected: {remote}")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(_ws_error("Invalid JSON"))
                continue

            action = msg.get("action")

            # Nano scanner actions (MCS2 + PicoScale direct control)
            if action and action.startswith("nano_"):
                if nano_scanner_svc is None:
                    await websocket.send(_ws_error(
                        "Nano scanner not available. Check MCS2_BRIDGE_HOST in config.env"))
                else:
                    resp = await nano_scanner_svc.handle_action(msg)
                    await websocket.send(json.dumps(resp, default=str))
                continue

            if bluesky_runner is None:
                await websocket.send(_ws_error("Bluesky runner not available. Start server with --bluesky flag."))
                continue

            if action == "submit":
                plan_name = msg.get("plan_name")
                params = msg.get("params", {})
                if not plan_name:
                    await websocket.send(_ws_error("Missing plan_name"))
                    continue

                if bluesky_runner.state == 'running':
                    await websocket.send(_ws_error("A plan is already running"))
                    continue

                # Submit plan in background thread
                loop = asyncio.get_running_loop()
                bluesky_runner.submit_async(plan_name, loop, **params)
                await websocket.send(json.dumps({
                    "type": "scan_submitted",
                    "plan_name": plan_name,
                    "params": params,
                    "status": bluesky_runner.status()
                }))
                log.info(f"Scan submitted: {plan_name}({params})")

            elif action == "abort":
                reason = msg.get("reason", "User abort")
                bluesky_runner.abort(reason)
                await websocket.send(json.dumps({
                    "type": "scan_aborted",
                    "reason": reason,
                    "status": bluesky_runner.status()
                }))
                log.info(f"Scan aborted: {reason}")

            elif action == "pause":
                bluesky_runner.pause()
                await websocket.send(json.dumps({
                    "type": "scan_paused",
                    "status": bluesky_runner.status()
                }))

            elif action == "resume":
                bluesky_runner.resume()
                await websocket.send(json.dumps({
                    "type": "scan_resumed",
                    "status": bluesky_runner.status()
                }))

            elif action == "status":
                await websocket.send(json.dumps({
                    "type": "scan_status",
                    "status": bluesky_runner.status()
                }))

            elif action == "list_plans":
                await websocket.send(json.dumps({
                    "type": "scan_plans",
                    "plans": bluesky_runner.list_plans()
                }))

            elif action == "list_history":
                limit = msg.get("limit", 50)
                offset = msg.get("offset", 0)
                plan_filter = msg.get("plan_filter")
                if bluesky_runner._scan_db:
                    history = bluesky_runner._scan_db.list_scans(
                        limit=limit, offset=offset, plan_filter=plan_filter)
                    total = bluesky_runner._scan_db.count(plan_filter)
                    await websocket.send(json.dumps({
                        "type": "scan_history",
                        "history": history,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                    }))
                else:
                    await websocket.send(json.dumps({
                        "type": "scan_history",
                        "history": [],
                        "total": 0,
                    }))

            elif action == "get_scan_data":
                uid = msg.get("uid", "")
                scan_data = _load_scan_h5_data(uid, bluesky_runner)
                await websocket.send(json.dumps(scan_data))

            elif action == "download_h5":
                uid = msg.get("uid", "")
                filename = msg.get("filename", "")
                h5_resp = _encode_h5_for_download(uid, filename, bluesky_runner)
                await websocket.send(json.dumps(h5_resp))

            # ── B1: queue-native actions (require SCAN_BACKEND=qserver) ──
            # Routed to the runner only if it implements the queue method. The
            # in-process BlueskyRunner has no queue, so we return a clear,
            # informative message instead of faking one.
            elif action in ("queue_add", "queue_start", "queue_stop",
                            "queue_clear", "queue_status", "queue_get",
                            "history"):
                # queue_status maps to runner.status(); the rest map 1:1 to a
                # runner method of the same name (history -> history_get).
                method_name = {"queue_status": "status",
                               "history": "history_get"}.get(action, action)
                if not hasattr(bluesky_runner, method_name) or \
                        getattr(bluesky_runner, "state", None) is None or \
                        bluesky_runner.status().get("backend") != "qserver":
                    await websocket.send(json.dumps({
                        "type": "scan_error",
                        "message": "queue actions require SCAN_BACKEND=qserver "
                                   "(active backend has no queue)",
                        "action": action,
                    }))
                    continue
                try:
                    if action == "queue_add":
                        plan_name = msg.get("plan_name")
                        if not plan_name:
                            await websocket.send(_ws_error("Missing plan_name"))
                            continue
                        params = msg.get("params", {})
                        item_uid = bluesky_runner.queue_add(plan_name, **params)
                        await websocket.send(json.dumps({
                            "type": "queue_item_added",
                            "plan_name": plan_name,
                            "item_uid": item_uid,
                            "status": bluesky_runner.status(),
                        }))
                    elif action == "queue_start":
                        loop = asyncio.get_running_loop()
                        bluesky_runner._loop = loop
                        bluesky_runner.queue_start()
                        await websocket.send(json.dumps({
                            "type": "queue_started",
                            "status": bluesky_runner.status(),
                        }))
                    elif action == "queue_stop":
                        bluesky_runner.queue_stop()
                        await websocket.send(json.dumps({
                            "type": "queue_stopped",
                            "status": bluesky_runner.status(),
                        }))
                    elif action == "queue_clear":
                        bluesky_runner.queue_clear()
                        await websocket.send(json.dumps({
                            "type": "queue_cleared",
                            "status": bluesky_runner.status(),
                        }))
                    elif action == "queue_status":
                        await websocket.send(json.dumps({
                            "type": "queue_status",
                            "status": bluesky_runner.status(),
                        }))
                    elif action == "queue_get":
                        await websocket.send(json.dumps({
                            "type": "queue_contents",
                            "queue": bluesky_runner.queue_get(),
                        }, default=str))
                    elif action == "history":
                        await websocket.send(json.dumps({
                            "type": "queue_history",
                            "history": bluesky_runner.history_get(),
                        }, default=str))
                except Exception as e:
                    log.exception("Queue action error")
                    await websocket.send(_ws_error(str(e)))
                    continue

            else:
                await websocket.send(_ws_error(f"Unknown action: {action}"))

    except websockets.ConnectionClosed:
        pass
    finally:
        scan_clients.discard(websocket)
        # D9: abort nano scan if the requesting client disconnected
        if nano_scanner_svc and nano_scanner_svc._scanning:
            log.warning("Scan client disconnected while scanning — aborting nano scan")
            nano_scanner_svc._abort_scan()
        log.info(f"Scan client disconnected: {remote}")


# ══════════════════════════════════════════════════════════════════════
# Experiment Endpoint Handler (Phase 2 placeholder)
# ══════════════════════════════════════════════════════════════════════
async def expt_handler(websocket):
    """Handle a virtual experiment client connection."""
    expt_clients.add(websocket)
    remote = websocket.remote_address
    log.info(f"Experiment client connected: {remote}")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(_ws_error("Invalid JSON"))
                continue

            action = msg.get("action")

            if expt_engine is None:
                await websocket.send(_ws_error("Experiment engine not available."))
                continue

            if action == "run":
                mode = msg.get("mode", "")
                params = msg.get("params", {})
                try:
                    await expt_engine.run(mode, websocket, params)
                except Exception as e:
                    log.error(f"Experiment run error: {e}")
                    await websocket.send(_ws_error(str(e)))
                    continue

            elif action == "cancel":
                if expt_engine:
                    expt_engine.cancel()
                    await websocket.send(json.dumps({
                        "type": "expt_cancelled"
                    }))

            elif action == "list_modes":
                modes = expt_engine.list_modes() if expt_engine else []
                await websocket.send(json.dumps({
                    "type": "expt_modes",
                    "modes": modes
                }))

            else:
                await websocket.send(_ws_error(f"Unknown action: {action}"))

    except websockets.ConnectionClosed:
        pass
    finally:
        expt_clients.discard(websocket)
        log.info(f"Experiment client disconnected: {remote}")


# ══════════════════════════════════════════════════════════════════════
# HTTP Static File Server (serves HTML bundle to browsers)
# ══════════════════════════════════════════════════════════════════════
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_BUNDLE_NAME = "virtual_beamline_nanoprobe_V4_38_bundle.html"
_BUNDLE_PATH = os.path.join(_PROJECT_ROOT, _BUNDLE_NAME)
# D8: Optional WebSocket API key (empty = auth disabled for dev)
_WS_API_KEY = os.environ.get("WS_API_KEY", "")

async def process_request(connection, request):
    """Serve HTML bundle for browser access. WebSocket paths pass through.
    D8: Optional API key authentication for WebSocket endpoints.
    """
    if request.path.startswith("/ws/"):
        # D8: Check API key if configured (empty key = auth disabled)
        if _WS_API_KEY:
            from urllib.parse import parse_qs
            path_str = str(request.path)
            qs = parse_qs(path_str.split("?", 1)[1]) if "?" in path_str else {}
            token = qs.get("token", [None])[0]
            if token != _WS_API_KEY:
                body = b'{"error":"unauthorized"}'
                return Response(403, "Forbidden",
                                Headers([("Content-Type", "application/json")]), body)
        return None  # Proceed with WebSocket upgrade

    if request.path in ("/", f"/{_BUNDLE_NAME}"):
        if not os.path.isfile(_BUNDLE_PATH):
            body = b"<h1>Bundle not found</h1><p>Run build first.</p>"
            return Response(404, "Not Found", Headers([("Content-Type", "text/html")]), body)
        with open(_BUNDLE_PATH, "rb") as f:
            body = f.read()
        return Response(200, "OK", Headers([
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-cache"),
        ]), body)

    # Favicon (avoid 404 noise in logs)
    if request.path == "/favicon.ico":
        return Response(204, "No Content", Headers(), b"")

    # Static asset routing: vendor/ (uplot, plotly), js/ (ESM source), assets/, archive/legacy_html/
    # Without this, browser fetches for href="vendor/uplot-1.6.31.min.css" fell through to the
    # WebSocket upgrade path and returned HTTP 426 / InvalidUpgrade, breaking page load.
    _STATIC_PREFIXES = ("/vendor/", "/js/", "/assets/", "/archive/")
    _STATIC_CT = {
        ".css": "text/css; charset=utf-8",
        ".js":  "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".json":"application/json; charset=utf-8",
        ".html":"text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg":"image/jpeg",
        ".gif": "image/gif",
        ".woff":"font/woff",
        ".woff2":"font/woff2",
        ".map": "application/json; charset=utf-8",
    }
    if any(request.path.startswith(p) for p in _STATIC_PREFIXES):
        rel = request.path.lstrip("/").split("?", 1)[0]
        fpath = os.path.normpath(os.path.join(_PROJECT_ROOT, rel))
        if not fpath.startswith(_PROJECT_ROOT) or not os.path.isfile(fpath):
            return Response(404, "Not Found",
                            Headers([("Content-Type", "text/plain; charset=utf-8")]),
                            b"static file not found")
        ext = os.path.splitext(fpath)[1].lower()
        ct = _STATIC_CT.get(ext, "application/octet-stream")
        with open(fpath, "rb") as f:
            data = f.read()
        return Response(200, "OK", Headers([
            ("Content-Type", ct),
            ("Cache-Control", "public, max-age=3600"),
        ]), data)

    return None  # Unknown path → WebSocket upgrade attempt


# ══════════════════════════════════════════════════════════════════════
# WebSocket Router
# ══════════════════════════════════════════════════════════════════════
async def router(websocket):
    """Route connections based on URL path."""
    path = websocket.request.path if websocket.request else "/"

    if path == "/ws/pv":
        await pv_handler(websocket)
    elif path == "/ws/chat":
        await chat_handler(websocket)
    elif path == "/ws/scan":
        await scan_handler(websocket)
    elif path == "/ws/expt":
        await expt_handler(websocket)
    else:
        await websocket.close(4000, f"Unknown path: {path}")


# ══════════════════════════════════════════════════════════════════════
# PV Scan + Broadcast Loop
# ══════════════════════════════════════════════════════════════════════
async def pv_broadcast_loop():
    """Run PV scan at 100ms intervals and broadcast changes to subscribers."""
    while True:
        pv_store.scan()
        changed = pv_store.get_changed()

        if changed and pv_clients:
            import time as _time
            _ts_pv_send = _time.time()
            # Build per-client message lists
            for ws, subs in list(pv_clients.items()):
                msgs = []
                for pv_name, data in changed.items():
                    if pv_name in subs:
                        data_with_ts = dict(data)
                        data_with_ts['_ts_pv_send'] = _ts_pv_send
                        msgs.append(json.dumps(data_with_ts))

                if msgs:
                    try:
                        # Batch: send all PV updates as JSON array (D7)
                        await ws.send("[" + ",".join(msgs) + "]")
                    except websockets.ConnectionClosed:
                        pv_clients.pop(ws, None)

        await asyncio.sleep(pv_store.scan_rate)


# ══════════════════════════════════════════════════════════════════════
# B3: Event-Triggered PV Push (CA-bridge modes; manuscript ¶78)
# ══════════════════════════════════════════════════════════════════════
async def _send_pv_batch(changed: dict) -> int:
    """Send one batched PV message to every subscribed client.

    EXACT same wire format as pv_broadcast_loop (zero-change for the
    browser): a JSON array of {pv, value, severity, timestamp, _ts_pv_send}
    objects, per-client filtered to its subscription set.
    Returns the number of websocket messages sent.
    """
    if not changed or not pv_clients:
        return 0
    _ts_pv_send = time.time()
    sent = 0
    for ws, subs in list(pv_clients.items()):
        msgs = []
        for pv_name, data in changed.items():
            if pv_name in subs:
                data_with_ts = dict(data)
                data_with_ts['_ts_pv_send'] = _ts_pv_send
                msgs.append(json.dumps(data_with_ts))
        if msgs:
            try:
                await ws.send("[" + ",".join(msgs) + "]")
                sent += 1
            except websockets.ConnectionClosed:
                pv_clients.pop(ws, None)
    return sent


def _pv_snapshot() -> dict:
    """Full PV snapshot incl. motor .RBV aliases.

    get_all() only returns base names, but the browser subscribes to BOTH
    the base PV and '<pv>.RBV' for motors (js/control/02_epics.js), so the
    keepalive snapshot mirrors the .RBV aliasing that get_changed() does.
    """
    snap = pv_store.get_all()
    motor_names = getattr(pv_store, '_motor_names', None)
    if motor_names:
        for name in motor_names:
            entry = snap.get(name)
            if entry is not None:
                rbv = dict(entry)
                rbv['pv'] = name + '.RBV'
                snap[name + '.RBV'] = rbv
    return snap


async def pv_event_push_loop():
    """Event-triggered PV push with burst coalescing (B3, replaces the
    10 Hz polling loop in CA-bridge modes).

    - caproto monitor callbacks (CABridge) record entries in the dirty-set
      (_changed) and wake this task via call_soon_threadsafe(_pv_dirty.set).
    - Leading edge: an isolated change is flushed IMMEDIATELY (no poll-tick
      wait -- the old loop added 0..100 ms, mean ~50 ms).
    - Burst coalescing / rate bound: after a flush, further changes are
      accumulated and flushed as ONE batched message per coalescing window
      (env PV_PUSH_COALESCE_MS, default 50 ms) -- at most ~20 msg/s/client
      no matter how fast the 86 PVs storm.
    - Idle: nothing is sent except a full-snapshot keepalive every
      PV_PUSH_SNAPSHOT_S seconds (default 5 s) covering late-joining
      clients and drift; it is also forced at that period under continuous
      traffic (noise PVs never go idle in hybrid mode).
    - Fallback: env PV_PUSH_MODE=periodic restores pv_broadcast_loop
      (selected in main(); old code path kept intact).
    """
    coalesce_s = float(os.environ.get(
        "PV_PUSH_COALESCE_MS", PV_PUSH_COALESCE_MS_DEFAULT)) / 1000.0
    snapshot_s = float(os.environ.get(
        "PV_PUSH_SNAPSHOT_S", PV_PUSH_SNAPSHOT_S_DEFAULT))
    log.info(f"PV event push: coalesce={coalesce_s * 1000:.0f}ms, "
             f"snapshot keepalive={snapshot_s:.1f}s")
    last_flush = 0.0     # monotonic time of last change-flush
    last_snapshot = time.monotonic()
    while True:
        try:
            await asyncio.wait_for(_pv_dirty.wait(), timeout=snapshot_s)
        except asyncio.TimeoutError:
            # Idle for snapshot_s -> keepalive/full snapshot only
            try:
                await _send_pv_batch(_pv_snapshot())
            except Exception as e:
                log.debug(f"PV snapshot send error: {e}")
            last_snapshot = time.monotonic()
            continue

        # Burst coalescing: enforce >= coalesce_s between change-flushes.
        # First event after a quiet spell passes straight through
        # (leading-edge flush); a storm accumulates in the dirty-set and is
        # flushed as one batch when the window expires.
        remaining = coalesce_s - (time.monotonic() - last_flush)
        if remaining > 0:
            await asyncio.sleep(remaining)
        _pv_dirty.clear()
        changed = pv_store.get_changed()
        if changed:
            last_flush = time.monotonic()
            try:
                await _send_pv_batch(changed)
            except Exception as e:
                log.debug(f"PV event push send error: {e}")
        # Drift guard: under continuous traffic the idle timeout above never
        # fires, so force the low-rate snapshot here as well.
        if time.monotonic() - last_snapshot >= snapshot_s:
            try:
                await _send_pv_batch(_pv_snapshot())
            except Exception as e:
                log.debug(f"PV snapshot send error: {e}")
            last_snapshot = time.monotonic()


# ══════════════════════════════════════════════════════════════════════
# PV Auto-Discovery Loop (hybrid mode)
# ══════════════════════════════════════════════════════════════════════
async def pv_discovery_loop():
    """Periodically scan for new PVs from hardware IOCs."""
    if pv_discovery is None:
        return
    while True:
        await asyncio.sleep(pv_discovery.probe_interval)
        try:
            loop = asyncio.get_event_loop()
            new_pvs = await loop.run_in_executor(None, pv_discovery.scan)
            if new_pvs:
                msg = json.dumps({
                    "action": "pv_discovered",
                    "pvs": new_pvs,
                    "message": f"{len(new_pvs)} new PV(s) detected from hardware IOC"
                })
                for ws in list(pv_clients.keys()):
                    try:
                        await ws.send(msg)
                    except Exception:
                        pass
                log.info(f"PV Discovery: {len(new_pvs)} new PVs broadcast to clients")
        except Exception as e:
            log.debug(f"PV discovery scan error: {e}")


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════
def _load_config_env():
    """Load deploy/config.env into os.environ.

    Reads KEY=VALUE lines from config.env (bash-style). Strips quotes.
    Skips comments (#) and empty lines. Does NOT overwrite existing env vars.
    This ensures --mode hybrid works regardless of how server.py is started.
    """
    config_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'deploy', 'config.env'),
        os.path.join(os.path.dirname(__file__), 'deploy', 'config.env'),
        os.path.expanduser('~/K4GSR-Beamline/deploy/config.env'),
    ]
    for path in config_paths:
        path = os.path.normpath(path)
        if os.path.isfile(path):
            loaded = 0
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    key, _, val = line.partition('=')
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # $HOME expansion
                    if '$HOME' in val:
                        val = val.replace('$HOME', os.path.expanduser('~'))
                    if key and key not in os.environ:
                        os.environ[key] = val
                        loaded += 1
            log.info(f"Loaded {loaded} vars from {path}")
            return
    log.warning("config.env not found in any expected location")


def _try_ioc_connect(timeout: float = CA_CONNECT_TIMEOUT) -> bool:
    """Probe whether a caproto Soft IOC is reachable on the local network.

    Attempts a single CA get on BL10:DCM:Theta. Returns True if successful.
    """
    try:
        from caproto.threading.client import Context
        ctx = Context()
        pvs = ctx.get_pvs('BL10:DCM:Theta', timeout=timeout)
        resp = pvs[0].read(timeout=timeout)
        val = float(resp.data[0])
        log.info(f"IOC probe: BL10:DCM:Theta = {val} (IOC reachable)")
        return True
    except Exception as e:
        log.debug(f"IOC probe failed: {e}")
        return False


async def main():
    global nlp_agent, pv_store, bluesky_runner, expt_engine, hw_groups, pv_discovery, safety_checker, nano_scanner_svc

    # First-run: interactive .env setup if missing
    if not os.path.exists(_ENV_PATH):
        _interactive_setup()

    port = WS_PORT
    ca_bridge_mode = False
    bluesky_mode = False
    standalone_mode = False
    ioc_addr = None  # EPICS_CA_ADDR_LIST override (e.g. "192.168.1.100 127.0.0.1")
    exclude_groups = []  # PV groups served by real hardware IOC

    # Parse command line
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
            i += 2
        elif arg == "--ioc-addr" and i + 1 < len(sys.argv):
            ioc_addr = sys.argv[i + 1]
            i += 2
        elif arg == "--exclude-groups" and i + 1 < len(sys.argv):
            # Collect group names until next flag
            i += 1
            while i < len(sys.argv) and not sys.argv[i].startswith('-'):
                exclude_groups.append(sys.argv[i].upper())
                i += 1
        elif arg == "--ca-bridge":
            ca_bridge_mode = True
            i += 1
        elif arg == "--bluesky":
            bluesky_mode = True
            i += 1
        elif arg == "--standalone":
            standalone_mode = True
            i += 1
        elif arg == "--mode" and i + 1 < len(sys.argv):
            # Shorthand: --mode standalone|full|hybrid
            # Reads deploy/config.env automatically for exclude_groups + CA ports.
            mode_name = sys.argv[i + 1].lower()
            i += 2
            if mode_name == "standalone":
                standalone_mode = True
            elif mode_name in ("full", "hybrid"):
                ca_bridge_mode = True
                bluesky_mode = True
                if mode_name == "hybrid":
                    # Auto-load config.env for exclude_groups + CA port env vars
                    _load_config_env()
                    cfg_groups = os.environ.get("SOFT_IOC_EXCLUDE_GROUPS", "")
                    if cfg_groups and not exclude_groups:
                        exclude_groups = cfg_groups.split()
                        log.info(f"--mode hybrid: loaded exclude_groups "
                                 f"from config.env: {exclude_groups}")
            else:
                log.warning(f"Unknown --mode '{mode_name}', "
                            f"expected: standalone|full|hybrid")
        else:
            i += 1

    # Set hw_groups from exclude_groups (these are served by real hardware IOC)
    if exclude_groups:
        hw_groups = set(exclude_groups)
        log.info(f"Hardware groups (from --exclude-groups): {', '.join(hw_groups)}")

    # Apply --ioc-addr: set EPICS_CA_ADDR_LIST for real/hybrid IOC connection
    if ioc_addr:
        os.environ["EPICS_CA_ADDR_LIST"] = ioc_addr
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        log.info(f"EPICS_CA_ADDR_LIST set to: {ioc_addr}")

    # Auto-detect mode: if no explicit flags, probe for IOC
    if not ca_bridge_mode and not bluesky_mode and not standalone_mode:
        if _CA_AVAILABLE and _BLUESKY_AVAILABLE:
            log.info("Auto-detect: probing for caproto Soft IOC...")
            if _try_ioc_connect(timeout=CA_CONNECT_TIMEOUT):
                ca_bridge_mode = True
                bluesky_mode = True
                log.info("Auto-detect: IOC found -> CA Bridge + Bluesky mode")
            else:
                log.info("Auto-detect: IOC not found -> Standalone PVStore mode")
        else:
            log.info("Auto-detect: caproto/bluesky not installed -> Standalone mode")

    # CA Bridge mode: route WebSocket <-> caproto IOC via Channel Access
    if ca_bridge_mode:
        if not _CA_AVAILABLE:
            log.error("--ca-bridge requires caproto. Install: pip install caproto")
            sys.exit(1)
        if ioc_addr:
            log.info(f"CA Bridge mode: connecting to IOC(s) at {ioc_addr}")
        else:
            log.info("CA Bridge mode: connecting to local Soft IOC...")
        try:
            # Build hw_groups_ports: {group_name: ca_port} from env vars
            # Maps PV group prefix -> config.env variable name for CA port.
            # e.g. KOHZU_CA_PORT=5070 → {"SAM": 5070}
            hw_groups_ports = {}
            group_port_map = {
                "SAM":   "KOHZU_CA_PORT",    # KOHZU sample stages (CX/CY/CZ)
                "XBPM2": "XBPM2_CA_PORT",    # Sydor Diamond BPM (T4U quadEM)
                "SCAN":  "SMARACT_CA_PORT",  # Fast Nano Scanner (MCS2+PicoScale)
            }
            # Default CA ports per group (fallback if env var missing)
            default_ports = {"SAM": 5070, "XBPM2": 5072, "SCAN": 5073}
            for grp in hw_groups:
                env_key = group_port_map.get(grp, f"{grp}_CA_PORT")
                default_port = default_ports.get(grp, EPICS_CA_PORT)
                grp_port = int(os.environ.get(env_key, default_port))
                hw_groups_ports[grp] = grp_port
            soft_port = int(os.environ.get("SOFT_IOC_CA_PORT", EPICS_CA_PORT))

            ref_store = PVStore()
            pv_store = CABridge(
                ref_store.pvs,
                hw_groups_ports=hw_groups_ports,
                soft_port=soft_port,
                timeout=10.0,
            )
            log.info("CA Bridge active: WebSocket <-> CA <-> IOC(s)")
            # Initialize PV discovery for hybrid mode
            if hw_groups and _DISCOVERY_AVAILABLE:
                known = set(ref_store.pvs.keys())
                pv_discovery = PVDiscovery(known, probe_interval=PV_DISCOVERY_INTERVAL)
                # Skip non-motor groups (e.g. DBPM) from axis-based probing
                skip_str = os.environ.get("DISCOVERY_SKIP_GROUPS", "")
                skip_groups = set(skip_str.split()) if skip_str else set()
                candidates = pv_discovery.generate_candidates(
                    hw_groups, skip_groups=skip_groups)
                pv_discovery.set_candidates(candidates)
                log.info(f"PV Discovery: {len(candidates)} candidate PVs for "
                         f"{', '.join(hw_groups - skip_groups)}"
                         f"{' (skip: ' + ','.join(skip_groups) + ')' if skip_groups else ''}")
        except Exception as e:
            log.error(f"CA Bridge failed: {e}")
            log.error("Is soft_ioc.py running? Start it first:")
            log.error("  python server/epics/soft_ioc.py")
            sys.exit(1)
    else:
        log.info("Standalone mode: internal PVStore simulation")

    # Initialize safety checker
    if _SAFETY_AVAILABLE:
        safety_checker = SafetyChecker(pv_store, hw_groups)
        log.info(f"Safety checker active (hw_groups: {', '.join(hw_groups) if hw_groups else 'none'})")

    # Reload .env into environment (needed if _interactive_setup just created it,
    # since nlp_agent.py's load_dotenv ran before .env existed)
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=True)
    except ImportError:
        pass

    # Initialize RAG engine if available and enabled
    rag_engine = None
    _rag_enabled = os.environ.get("RAG_ENABLED", "true").strip().lower() not in ("false", "0", "no")
    if not _rag_enabled:
        log.info("RAG disabled (RAG_ENABLED=false in .env)")
    elif _RAG_AVAILABLE:
        try:
            docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
            rag_engine = BeamlineRAG(docs_dir)
            chunk_count = rag_engine.index_documents()
            log.info(f"RAG engine ready: {chunk_count} chunks indexed")
        except Exception as e:
            log.warning(f"RAG engine failed to initialize: {e}")
            rag_engine = None
    else:
        if _RAG_IMPORT_ERROR:
            log.info(f"RAG disabled (import error: {_RAG_IMPORT_ERROR})")
        else:
            log.info("RAG disabled (chromadb/sentence-transformers not installed)")

    # Initialize NLP agent if available
    if _NLP_AVAILABLE:
        engine = os.environ.get("NLP_ENGINE", "").strip()
        log.info(f".env loaded: NLP_ENGINE='{engine}'")
        if not engine:
            log.info("NLP disabled (NLP_ENGINE is empty in .env)")
        else:
            try:
                nlp_agent = NLPAgent(rag_engine=rag_engine)
                log.info(f"NLP agent initialized (engine: {engine})")
            except Exception as e:
                log.warning(f"NLP agent failed to initialize: {e}")
                log.warning(f"  .env path: {_ENV_PATH}")
                log.warning(f"  NLP_ENGINE={engine}")
                if engine == "groq":
                    key = os.environ.get("GROQ_API_KEY", "")
                    log.warning(f"  GROQ_API_KEY={'set (' + str(len(key)) + ' chars)' if key else 'NOT SET'}")
                elif engine == "gemini":
                    key = os.environ.get("GOOGLE_API_KEY", "")
                    log.warning(f"  GOOGLE_API_KEY={'set (' + str(len(key)) + ' chars)' if key else 'NOT SET'}")
                elif engine == "claude":
                    key = os.environ.get("ANTHROPIC_API_KEY", "")
                    log.warning(f"  ANTHROPIC_API_KEY={'set (' + str(len(key)) + ' chars)' if key else 'NOT SET'}")
                log.warning("Check server/.env and restart.")
                nlp_agent = None
    else:
        log.warning(f"NLP agent module not loaded: {_NLP_IMPORT_ERROR}")
        log.warning("Try: pip install httpx python-dotenv")

    # Initialize Bluesky runner if requested.
    #
    # B1 mode switch: SCAN_BACKEND selects which runner is built behind the
    # backend-agnostic `bluesky_runner` variable. "inprocess" (default/unset) is
    # the regression-critical path and is constructed EXACTLY as before. Only
    # "qserver" builds the separate-process QueueServerRunner instead.
    if bluesky_mode:
        scan_backend = os.environ.get(
            "SCAN_BACKEND", SCAN_BACKEND_DEFAULT).strip().lower()
        if scan_backend == "qserver":
            if not _QSERVER_AVAILABLE:
                log.error("SCAN_BACKEND=qserver requires bluesky-queueserver. "
                          "Install: pip install bluesky-queueserver "
                          "bluesky-queueserver-api")
                sys.exit(1)
            log.info("Initializing scan engine (backend=qserver, RE Manager)...")
            try:
                _bs_timeout = (BLUESKY_HYBRID_TIMEOUT if hw_groups
                               else BLUESKY_CONNECT_TIMEOUT)
                bluesky_runner = QueueServerRunner(
                    ws_callback=broadcast_scan_event,
                    connect_timeout=_bs_timeout)
                bluesky_runner.start()
                log.info("bluesky-queueserver RE Manager ready")
            except Exception as e:
                log.warning(f"queueserver initialization failed: {e}")
                log.warning("Scan engine will not be available "
                            "(check redis / RE Manager subprocess).")
                bluesky_runner = None
        else:
            if not _BLUESKY_AVAILABLE:
                log.error("--bluesky requires bluesky+ophyd. Install: pip install bluesky ophyd")
                sys.exit(1)
            log.info("Initializing Bluesky scan engine (backend=inprocess)...")
            try:
                # In hybrid mode, some PVs (e.g. SAM sub-motors) are not yet
                # served by any IOC → use short connect timeout to avoid delay.
                _bs_timeout = BLUESKY_HYBRID_TIMEOUT if hw_groups else BLUESKY_CONNECT_TIMEOUT
                bluesky_runner = BlueskyRunner(ws_callback=broadcast_scan_event,
                                               connect_timeout=_bs_timeout)
                bluesky_runner.start()
                log.info("Bluesky RunEngine ready")
            except Exception as e:
                log.warning(f"Bluesky initialization failed: {e}")
                log.warning("Scan engine will not be available. Is soft_ioc.py running?")
                bluesky_runner = None

    # Initialize nano scanner service (MCS2 bridge + PicoScale)
    if _NANO_AVAILABLE:
        _mcs2_host = os.environ.get("MCS2_BRIDGE_HOST", "").strip()
        _mcs2_port = int(os.environ.get("MCS2_BRIDGE_PORT", "5555"))
        _ps_locator = os.environ.get("PICOSCALE_LOCATOR", "").strip()
        try:
            nano_scanner_svc = NanoScannerService(
                pv_store=pv_store,
                bridge_host=_mcs2_host,
                bridge_port=_mcs2_port,
                ps_locator=_ps_locator)

            async def _nano_broadcast(msg):
                for ws in list(scan_clients):
                    try:
                        await ws.send(json.dumps(msg, default=str))
                    except Exception:
                        pass
            nano_scanner_svc.set_broadcast(_nano_broadcast)

            await nano_scanner_svc.start()
            log.info(f"Nano scanner service ready "
                     f"(MCS2: {_mcs2_host or 'mock'}:{_mcs2_port}, "
                     f"PS: {_ps_locator or 'mock'})")
        except Exception as e:
            log.warning(f"Nano scanner init failed: {e}")
            nano_scanner_svc = None
    else:
        log.info("Nano scanner service not available (import failed)")

    # Initialize experiment engine if available
    if _EXPT_AVAILABLE:
        try:
            expt_engine = ExperimentEngine()
            log.info(f"Experiment engine ready: {expt_engine.list_modes()}")
        except Exception as e:
            log.warning(f"Experiment engine init failed: {e}")
            expt_engine = None
    else:
        log.info("Experiment engine not available (experiment_engine.py not found)")

    # Start K4GSR-PTYCHO reconstruction server (subprocess)
    _ptycho_ok = _start_ptycho_server(port=PTYCHO_PORT)
    if _ptycho_ok:
        log.info("K4GSR-PTYCHO server: ws://localhost:8765")
    else:
        log.warning("K4GSR-PTYCHO server not available (ptychography will use offline mode)")

    log.info(f"PV Store: {len(pv_store.pvs)} PVs initialized")

    # Start PV broadcast loop (B3: event push vs periodic 10 Hz poll)
    # PV_PUSH_MODE=event (default): CA-bridge modes use the event-triggered
    #   push (caproto monitor callback -> dirty-set -> coalesced batch).
    # PV_PUSH_MODE=periodic: old 10 Hz polling loop (fallback, kept intact).
    # Standalone PVStore ALWAYS uses the periodic loop: PVStore state only
    #   evolves inside scan() (motor stepping + noise are generated by the
    #   10 Hz tick itself), so the tick IS the event source -- and the noise
    #   PVs change every tick, so event push would degenerate to the same
    #   10 Hz with extra machinery.
    push_mode = os.environ.get("PV_PUSH_MODE", PV_PUSH_MODE_DEFAULT).strip().lower()
    use_event_push = (push_mode == "event" and ca_bridge_mode
                      and hasattr(pv_store, "on_change"))
    if use_event_push:
        _main_loop = asyncio.get_running_loop()

        def _pv_change_notify(_name, _value):
            # Runs on caproto callback threads -- hand off to asyncio loop.
            # (Same cross-thread pattern as BlueskyRunner ws_callback.)
            try:
                _main_loop.call_soon_threadsafe(_pv_dirty.set)
            except RuntimeError:
                pass  # event loop already closed (shutdown)

        pv_store.on_change = _pv_change_notify
        broadcast_task = asyncio.create_task(pv_event_push_loop())
        log.info("PV push mode: event (PV_PUSH_MODE=periodic to restore 10 Hz loop)")
    else:
        if push_mode == "event" and not ca_bridge_mode:
            log.info("PV push mode: periodic (standalone PVStore is tick-driven; "
                     "event push applies to CA-bridge modes only)")
        else:
            log.info(f"PV push mode: periodic (PV_PUSH_MODE={push_mode})")
        broadcast_task = asyncio.create_task(pv_broadcast_loop())

    # Start PV discovery loop (hybrid mode only)
    discovery_task = None
    if pv_discovery is not None:
        discovery_task = asyncio.create_task(pv_discovery_loop())
        log.info("PV Discovery loop started (30s interval)")

    # Start WebSocket server
    stop = asyncio.get_event_loop().create_future()

    # Handle shutdown signals
    def handle_signal():
        if not stop.done():
            stop.set_result(True)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        _test_sock = __import__('socket').socket(__import__('socket').AF_INET, __import__('socket').SOCK_STREAM)
        _test_sock.bind(("0.0.0.0", port))
        _test_sock.close()
    except OSError:
        log.error(f"Port {port} is already in use!")
        log.error("Another server instance may be running.")
        log.error(f"  Windows: run 'netstat -ano | findstr :{port}' to find the process")
        log.error("  Then:    taskkill /PID <pid> /F")
        log.error("  Or use:  python server/server.py --port 8002")
        sys.exit(1)

    # C3: Optional TLS support (set TLS_CERT_PATH + TLS_KEY_PATH env vars)
    ssl_ctx = None
    _cert = os.environ.get("TLS_CERT_PATH", "")
    _key = os.environ.get("TLS_KEY_PATH", "")
    if _cert and _key and os.path.isfile(_cert) and os.path.isfile(_key):
        import ssl as _ssl
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(_cert, _key)
        log.info(f"TLS enabled: cert={_cert}")

    async with serve(router, "0.0.0.0", port, origins=None,
                     process_request=process_request,
                     ssl=ssl_ctx) as server:
        proto = "wss" if ssl_ctx else "ws"
        mode = "CA Bridge + Bluesky" if (ca_bridge_mode and bluesky_mode) else \
               "CA Bridge" if ca_bridge_mode else \
               "Bluesky" if bluesky_mode else "Standalone"
        log.info(f"Server started on {proto}://0.0.0.0:{port} [{mode}]")
        log.info(f"  Web UI:        http://localhost:{port}/")
        log.info(f"  PV endpoint:   ws://localhost:{port}/ws/pv")
        log.info(f"  Chat endpoint: ws://localhost:{port}/ws/chat")
        log.info(f"  Scan endpoint: ws://localhost:{port}/ws/scan {'(active)' if bluesky_runner else '(inactive)'}")
        log.info(f"  Nano scanner:  ws://localhost:{port}/ws/scan {'(active)' if nano_scanner_svc else '(inactive)'}")
        log.info(f"  Expt endpoint: ws://localhost:{port}/ws/expt {'(active)' if expt_engine else '(inactive)'}")
        log.info("Press Ctrl+C to stop")

        try:
            await stop
        except asyncio.CancelledError:
            pass

    # D10: Graceful shutdown — cancel tasks and await completion
    log.info("Shutting down...")
    broadcast_task.cancel()
    if discovery_task:
        discovery_task.cancel()
    # Await cancelled tasks to finish cleanly
    for task in [broadcast_task, discovery_task]:
        if task is not None:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    if bluesky_runner:
        bluesky_runner.shutdown()
    if nano_scanner_svc:
        await nano_scanner_svc.stop()
        # Wait for scan thread to finish if running
        if nano_scanner_svc._scan_thread and nano_scanner_svc._scan_thread.is_alive():
            nano_scanner_svc._scan_thread.join(timeout=5.0)
    if expt_engine and hasattr(expt_engine, 'shutdown'):
        expt_engine.shutdown()
    _stop_ptycho_server()
    log.info("Server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
