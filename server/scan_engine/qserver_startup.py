#!/usr/bin/env python3
"""RE Manager startup helpers for the B1 queueserver backend.

Responsibilities:
  * locate the qserver startup profile + permissions file,
  * (re)generate ``existing_plans_and_devices.yaml`` from the live profile so
    the allowed-plans/devices registry matches the in-process engine,
  * build the ``start-re-manager`` argv,
  * optionally spawn an in-process ``fakeredis`` TCP server when no real Redis is
    reachable (local PoC / Windows). VM1 should run a real ``redis-server`` and
    set ``QSERVER_USE_FAKEREDIS=0``.

This module does NOT talk to the running manager (that is QueueServerRunner's
job via REManagerAPI). It only prepares the environment + process arguments.

See docs/tasks/TASK_B1_QUEUESERVER.md and TASK_PHASE1_ROADMAP.md s.B1.
"""

import os
import sys
import shutil
import logging
import threading
import subprocess

log = logging.getLogger("bl10-qserver-startup")


def _console_script(name):
    """Resolve a queueserver console script to an absolute path.

    bluesky-queueserver installs ``qserver-list-plans-devices`` and
    ``start-re-manager`` as console scripts in the SAME bin/Scripts dir as the
    running interpreter. Resolving them relative to ``sys.executable`` (rather
    than relying on PATH) lets the backend launch correctly when started via a
    bare ``venv/bin/python`` invocation (e.g. beamline_ctl) where the venv bin
    dir is NOT on PATH. Falls back to PATH lookup, then the bare name.
    """
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    for cand in (os.path.join(bindir, name), os.path.join(bindir, name + ".exe")):
        if os.path.isfile(cand):
            return cand
    found = shutil.which(name)
    return found if found else name

# Importable name of the startup profile package (relative to server/ on path).
STARTUP_MODULE = "scan_engine.qserver_profile"

# Directory that holds the profile package + permissions yaml.
_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "qserver_profile")
PERMISSIONS_PATH = os.path.join(_PROFILE_DIR, "user_group_permissions.yaml")

# Where the generated plans/devices list lives (regenerated each startup).
_SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
_EPD_DIR = os.path.join(_SERVER_DIR, "data")
EPD_FILENAME = "qserver_existing_plans_and_devices.yaml"
EPD_PATH = os.path.join(_EPD_DIR, EPD_FILENAME)


def _profile_env(extra=None):
    """Return an env dict where `server/` is importable as a package root.

    The startup profile imports ``scan_engine.qserver_profile``; the worker
    process must have ``server/`` on PYTHONPATH for that to resolve.
    """
    env = dict(os.environ)
    pp = env.get("PYTHONPATH", "")
    parts = [_SERVER_DIR] + ([pp] if pp else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def generate_existing_plans_and_devices(device_path=None, timeout=120):
    """Generate EPD_PATH from the live startup profile.

    Runs ``qserver-list-plans-devices --startup-module scan_engine.qserver_profile``.
    Returns the path on success, raises RuntimeError on failure.

    NOTE: ``--startup-module`` is used (not ``--startup-dir``) deliberately --
    on Windows the dir loader patches ``__file__`` with a backslash path and a
    folder like ``C:\\Users`` triggers a unicodeescape SyntaxError.
    """
    os.makedirs(_EPD_DIR, exist_ok=True)
    extra = {}
    if device_path:
        extra["QSERVER_DEVICE_PATH"] = device_path
    env = _profile_env(extra)

    argv = [
        _console_script("qserver-list-plans-devices"),
        "--startup-module", STARTUP_MODULE,
        "--file-dir", _EPD_DIR,
        "--file-name", EPD_FILENAME,
    ]
    log.info(f"Generating plans/devices list: {' '.join(argv)}")
    proc = subprocess.run(argv, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if proc.returncode != 0 or not os.path.exists(EPD_PATH):
        raise RuntimeError(
            f"qserver-list-plans-devices failed (rc={proc.returncode}):\n"
            f"{proc.stdout[-2000:]}")
    log.info(f"Plans/devices list written: {EPD_PATH}")
    return EPD_PATH


def build_re_manager_argv(zmq_control_addr, zmq_info_addr, redis_addr,
                          epd_path=None):
    """Build the ``start-re-manager`` argv list.

    Args:
        zmq_control_addr: e.g. ``tcp://127.0.0.1:60615`` (REQ/REP control).
        zmq_info_addr:    e.g. ``tcp://127.0.0.1:60625`` (console/status PUB).
        redis_addr:       e.g. ``127.0.0.1:60617``.
        epd_path:         path to existing_plans_and_devices.yaml (or None).
    """
    argv = [
        _console_script("start-re-manager"),
        "--startup-module", STARTUP_MODULE,
        "--zmq-control-addr", zmq_control_addr,
        "--zmq-info-addr", zmq_info_addr,
        "--zmq-publish-console", "ON",   # publish STDOUT/STDERR on QS_Console
        "--redis-addr", redis_addr,
        "--user-group-permissions", PERMISSIONS_PATH,
    ]
    if epd_path:
        argv += ["--existing-plans-devices", epd_path]
    return argv


def start_fakeredis_server(host, port):
    """Start an in-process fakeredis TCP server (local PoC / no real Redis).

    Returns the TcpFakeServer instance (call ``.shutdown()`` to stop) or raises
    if fakeredis is unavailable. The server is served on a daemon thread so it
    is reachable by the separate RE Manager process over real TCP.
    """
    from fakeredis import TcpFakeServer  # raises ImportError if not installed
    # Silence the benign socketserver "connection reset" tracebacks that
    # fakeredis emits when the RE Manager worker is torn down (its redis socket
    # is closed mid-request). These are harmless teardown noise.
    logging.getLogger("fakeredis").setLevel(logging.CRITICAL)

    class _QuietTcpFakeServer(TcpFakeServer):
        # socketserver prints a traceback to stderr on every client reset; the
        # RE Manager worker resets its redis socket when it is torn down, so
        # swallow those benign connection-reset errors.
        def handle_error(self, request, client_address):
            log.debug(f"fakeredis client {client_address} reset (ignored)")

    srv = _QuietTcpFakeServer((host, port), server_type="redis")
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="qserver-fakeredis")
    t.start()
    log.info(f"fakeredis TCP server started on {host}:{port}")
    return srv


def redis_reachable(host, port, timeout=0.5):
    """Return True if a real Redis server is reachable at host:port."""
    try:
        import redis
        r = redis.Redis(host=host, port=port, socket_connect_timeout=timeout)
        return bool(r.ping())
    except Exception:
        return False
