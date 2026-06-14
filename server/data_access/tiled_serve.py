#!/usr/bin/env python3
"""Tiled server launcher for the B2 data-access PoC (manuscript para 39).

Spawns ``tiled serve config <materialized.yml>`` as a SEPARATE local process that
serves the existing scan-output directory (NeXus/HDF5) read-only over HTTP. The
served tree is a pyobject ``MapAdapter`` (data_access.tiled_tree:scans_tree) that
maps each scan file to Tiled's native HDF5 adapter, so the runs are immediately
listable/readable by a ``tiled.client`` (numpy) client -- no separate register
step (the SQL-catalog register path is unusable for nested HDF5 in Tiled 0.2.3;
see tiled_tree.py + TASK_B2_TILED.md).

This MIRRORS the process-management style of
``server/scan_engine/qserver_startup.py`` + ``qserver_runner.py``:
  * a ``_kill_process_tree`` reaper so no orphan uvicorn/worker processes survive
    teardown (uvicorn may spawn children on some platforms),
  * a readiness wait that polls the server ``/healthz`` (not a fixed sleep),
  * subprocess Popen in its own process group on POSIX so the whole tree is
    reaped.

OPT-IN / DEFAULT-OFF (read this)
  Nothing imports or starts this from the production ``server.py``. It is a
  standalone helper. The convenience env gate ``TILED_ENABLED`` (default off,
  see constants.TILED_ENABLED_DEFAULT) exists only so a future integrating
  session can wrap this behind a documented, default-off switch; this module
  itself never auto-starts.

SCOPE
  LOCAL PoC ONLY. Binds loopback. Anonymous READ-ONLY. NO facility auth --
  operational deployment + auth are deferred to B4. See TASK_B2_TILED.md.

Tiled version validated: 0.2.3 (extras: tiled[server,client] + dask).

Usage (programmatic):
    from data_access.tiled_serve import TiledServer
    srv = TiledServer(scans_dir="/path/to/server/data/scans")
    url = srv.start()                 # spawns process, waits ready, registers
    # ... use tiled.client.from_uri(url, api_key=srv.api_key) ...
    srv.shutdown()                    # reaps the whole process tree

Usage (CLI):
    python -m data_access.tiled_serve --scans-dir <dir> [--port 8010]
    # runs until Ctrl-C; prints the URL + api key.
"""

import os
import sys
import time
import signal
import string
import secrets
import logging
import argparse
import tempfile
import subprocess
import urllib.request
import urllib.error

# Make ``server/`` importable so ``constants`` resolves whether this is run as a
# module (``python -m data_access.tiled_serve``) or as a script.
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from constants import (TILED_HOST, TILED_PORT, TILED_STARTUP_TIMEOUT,
                       TILED_POLL_INTERVAL)

log = logging.getLogger("tiled-serve")

# Committed config template (with ${...} placeholders).
_CONFIG_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tiled_config.yml")
# Default scan-output directory (same dir the Bluesky runner auto-saves into).
DEFAULT_SCANS_DIR = os.path.join(_SERVER_DIR, "data", "scans")


def _kill_process_tree(proc, timeout=10):
    """Terminate a process AND its children (no orphan uvicorn workers).

    Mirrors qserver_runner._kill_process_tree: on Windows ``taskkill /T`` kills
    the child tree; on POSIX the runner starts the process in its own group so
    we can ``killpg``. The parent handle is reaped regardless.
    """
    if proc is None:
        return
    pid = proc.pid
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=timeout)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
    except Exception as e:
        log.debug(f"tree-kill error for pid {pid}: {e}")
    try:
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _generate_api_key(n=32):
    """Generate a difficult-to-guess single-user API key (fresh per launch)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _serve_env():
    """Env for the subprocess with ``server/`` on PYTHONPATH.

    ``tiled serve config`` imports the pyobject tree
    ``data_access.tiled_tree:scans_tree`` in the worker process; that import
    resolves only if ``server/`` is on PYTHONPATH.
    """
    env = dict(os.environ)
    pp = env.get("PYTHONPATH", "")
    parts = [_SERVER_DIR] + ([pp] if pp else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


class TiledServer:
    """Manage a local ``tiled serve config`` subprocess for the B2 PoC."""

    def __init__(self, scans_dir=None, host=None, port=None,
                 work_dir=None, startup_timeout=None):
        """Args:
            scans_dir: directory of scan .h5 files to serve (default: the
                       runner's server/data/scans).
            host/port: bind address (default loopback + TILED_PORT).
            work_dir:  where to put the generated catalog DB + materialized
                       config (default: a fresh temp dir, cleaned on shutdown).
            startup_timeout: max seconds to wait for /healthz.
        """
        self.scans_dir = os.path.abspath(scans_dir or DEFAULT_SCANS_DIR)
        self.host = host or TILED_HOST
        self.port = int(port or TILED_PORT)
        self.startup_timeout = float(startup_timeout or TILED_STARTUP_TIMEOUT)
        self.api_key = _generate_api_key()

        self._own_workdir = work_dir is None
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="tiled_b2_")
        self._config_path = os.path.join(self._work_dir, "tiled_config.local.yml")
        self._proc = None

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"

    def _materialize_config(self):
        """Render the committed template with concrete local paths + api key.

        Uses explicit token replacement (not string.Template) so that ``${...}``
        appearing in the template's *prose comments* is left untouched -- only
        the concrete ``${NAME}`` placeholders below are substituted.
        """
        with open(_CONFIG_TEMPLATE, "r", encoding="utf-8") as f:
            text = f.read()
        os.makedirs(self.scans_dir, exist_ok=True)
        subs = {
            "${SCANS_DIR}": self.scans_dir.replace("\\", "/"),
            "${API_KEY}": self.api_key,
            "${HOST}": self.host,
            "${PORT}": str(self.port),
        }
        for token, value in subs.items():
            text = text.replace(token, value)
        with open(self._config_path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info(f"Materialized Tiled config: {self._config_path}")
        return self._config_path

    def _healthz_ok(self):
        """Return True once the server answers /healthz with HTTP 200."""
        try:
            with urllib.request.urlopen(self.url + "/healthz",
                                        timeout=2.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, ConnectionError, OSError):
            return False

    def _wait_ready(self):
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                out = ""
                try:
                    out = self._proc.stdout.read() if self._proc.stdout else ""
                except Exception:
                    pass
                raise RuntimeError(
                    f"tiled serve exited early (rc={self._proc.returncode}):\n"
                    f"{out[-2000:]}")
            if self._healthz_ok():
                return
            time.sleep(TILED_POLL_INTERVAL)
        raise RuntimeError(f"Tiled server did not become ready within "
                           f"{self.startup_timeout:.0f}s at {self.url}")

    def start(self):
        """Spawn the server and wait until it is ready.

        The pyobject tree builds the run index at startup (no separate register
        step). Returns the base URL of the running server.
        """
        if self._proc is not None:
            log.warning("TiledServer already started")
            return self.url

        self._materialize_config()
        argv = [sys.executable, "-m", "tiled", "serve", "config",
                self._config_path]
        log.info(f"Starting Tiled: {' '.join(argv[2:])} (bind {self.url})")

        popen_kw = {}
        if not sys.platform.startswith("win"):
            # Own process group so _kill_process_tree can killpg the tree.
            popen_kw["preexec_fn"] = os.setsid
        self._proc = subprocess.Popen(
            argv, env=_serve_env(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, **popen_kw)
        log.info(f"Tiled subprocess pid={self._proc.pid}")

        try:
            self._wait_ready()
        except Exception:
            self.shutdown()
            raise
        log.info(f"Tiled server ready at {self.url}")
        return self.url

    def shutdown(self):
        """Reap the server process tree and clean the temp work dir."""
        if self._proc is not None:
            _kill_process_tree(self._proc)
            self._proc = None
            log.info("Tiled server shut down")
        if self._own_workdir and os.path.isdir(self._work_dir):
            try:
                import shutil
                shutil.rmtree(self._work_dir, ignore_errors=True)
            except Exception as e:
                log.debug(f"workdir cleanup error: {e}")

    # Context-manager sugar.
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()


def _main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s: %(message)s")
    ap = argparse.ArgumentParser(
        description="Launch the B2 Tiled PoC server (local, read-only).")
    ap.add_argument("--scans-dir", default=None,
                    help="scan .h5 directory (default: server/data/scans)")
    ap.add_argument("--host", default=None, help="bind host (default loopback)")
    ap.add_argument("--port", type=int, default=None,
                    help=f"bind port (default {TILED_PORT})")
    args = ap.parse_args(argv)

    srv = TiledServer(scans_dir=args.scans_dir, host=args.host, port=args.port)
    srv.start()
    # Interactive CLI feedback (print allowed for CLI helpers, coding std s.6).
    print(f"Tiled serving at {srv.url}")
    print(f"API key (write side): {srv.api_key}")
    print("Anonymous READ access is ON (local PoC). Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
