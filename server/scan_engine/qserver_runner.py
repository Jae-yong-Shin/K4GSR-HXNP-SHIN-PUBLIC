#!/usr/bin/env python3
"""bluesky-queueserver backend runner (B1, manuscript para 31).

QueueServerRunner MIRRORS the public interface of BlueskyRunner so server.py can
hold either object behind a single ``bluesky_runner`` variable. The in-process
RunEngine is replaced by a SEPARATE-PROCESS RE Manager that this class drives
over 0MQ via ``bluesky_queueserver_api.zmq.REManagerAPI``.

Lifecycle:
    runner = QueueServerRunner(ws_callback=broadcast_scan_event)
    runner.start()      # spawn RE Manager (+ fakeredis if needed), connect API
    runner.submit_async('energy_scan', loop, e_start=8.9, e_stop=9.1, n_points=50)
    runner.status()     # {'state':..., 'backend':'qserver', 'queue':{...}, ...}
    runner.shutdown()   # terminate RE Manager subprocess + fakeredis

Single-plan parity (BlueskyRunner-compatible):
    submit  = environment_open (if needed) -> item_add(plan) -> queue_start
    abort   = re_abort + queue_stop
    pause   = re_pause
    resume  = re_resume

Queue-native extras (no in-process equivalent):
    queue_add / queue_start / queue_stop / queue_clear / queue_get /
    history_get / env_open / env_close

What is streamed to ws_callback (this tranche):
    A background poller diffs the RE Manager ``status()`` and emits, in the
    SAME ``{'type':'scan_event', ...}`` envelope the browser already consumes:
      * doc_type='start'  when a queue item begins running (manager_state ->
        'executing_queue' / a new running_item_uid appears),
      * doc_type='stop'   when a run finishes (a new history item appears),
      * doc_type='status' on queue-length / manager-state transitions.
    Full per-event document streaming (descriptor/event) is intentionally NOT
    forwarded in B1 -- the RE Manager runs in a separate process and re-emitting
    every Bluesky event document over 0MQ console is heavy for this PoC. The
    'start'/'stop'/'status' transitions are sufficient for the queue UI; full
    document streaming is a documented follow-up (see TASK_B1_QUEUESERVER.md).
"""

import os
import sys
import time
import signal
import logging
import threading
import subprocess

from constants import (QSERVER_ZMQ_PORT, QSERVER_ZMQ_INFO_PORT,
                       QSERVER_REDIS_PORT, QSERVER_POLL_INTERVAL,
                       QSERVER_STARTUP_TIMEOUT)
from . import qserver_startup as _startup

log = logging.getLogger("bl10-qserver-runner")


def _kill_process_tree(proc, timeout=10):
    """Terminate a process AND its children.

    The RE Manager runs its RE Worker as a multiprocessing child; on Windows a
    plain ``proc.terminate()`` on the parent orphans that worker (it keeps the
    0MQ/redis ports + environment alive). Kill the whole tree.
    """
    if proc is None:
        return
    pid = proc.pid
    try:
        if sys.platform.startswith("win"):
            # /T kills the child tree, /F forces. Suppress taskkill chatter.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=timeout)
        else:
            # POSIX: terminate the process group (runner starts it in its own).
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
    except Exception as e:
        log.debug(f"tree-kill error for pid {pid}: {e}")
    # Reap the parent handle regardless.
    try:
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

# qserver manager_state -> BlueskyRunner-style state vocabulary.
_STATE_MAP = {
    "initializing": "connecting",
    "idle": "idle",
    "paused": "paused",
    "creating_environment": "connecting",
    "executing_queue": "running",
    "executing_task": "running",
    "starting_queue": "running",
    "closing_environment": "connecting",
    "destroying_environment": "connecting",
}


class QueueServerRunner:
    """Drive a separate-process RE Manager, mirroring BlueskyRunner's API."""

    def __init__(self, ws_callback=None, connect_timeout: float = 10.0):
        self._ws_callback = ws_callback
        self._connect_timeout = connect_timeout

        self._device_path = os.environ.get("QSERVER_DEVICE_PATH",
                                           "epics").strip().lower()
        self._zmq_port = int(os.environ.get("QSERVER_ZMQ_PORT", QSERVER_ZMQ_PORT))
        self._zmq_info_port = int(os.environ.get("QSERVER_ZMQ_INFO_PORT",
                                                 QSERVER_ZMQ_INFO_PORT))
        self._redis_port = int(os.environ.get("QSERVER_REDIS_PORT",
                                              QSERVER_REDIS_PORT))
        self._zmq_control_addr = f"tcp://127.0.0.1:{self._zmq_port}"
        self._zmq_info_addr = f"tcp://127.0.0.1:{self._zmq_info_port}"
        self._redis_addr = f"127.0.0.1:{self._redis_port}"

        self._RM = None                 # REManagerAPI instance
        self._proc = None               # start-re-manager subprocess
        self._fakeredis = None          # TcpFakeServer (if used)
        self._loop = None               # asyncio loop for ws callbacks
        self._state = "idle"            # mirrors BlueskyRunner._state vocabulary
        self._last_error = None
        self._current_plan = None
        self._current_uid = None
        self._event_count = 0

        # Status poller (status-diff -> ws_callback) state.
        self._poll_thread = None
        self._poll_stop = threading.Event()
        self._last_manager_state = None
        self._last_history_len = 0
        self._last_queue_len = None

        # Compat shim: server.py references runner._scan_db for the history
        # endpoint. The qserver keeps its own history (RE Manager), so we expose
        # None and route /ws/scan history -> RM.history_get() instead.
        self._scan_db = None

    # ── BlueskyRunner-compatible surface ──────────────────────────────────
    @property
    def state(self):
        return self._state

    def status(self) -> dict:
        """Return BlueskyRunner-shaped status + 'backend' and 'queue' fields."""
        base = {
            "state": self._state,
            "plan": self._current_plan,
            "uid": self._current_uid,
            "event_count": self._event_count,
            "last_error": self._last_error,
            "devices_connected": self._RM is not None,
            "auto_save": True,
            "data_dir": _startup._EPD_DIR,
            "backend": "qserver",
        }
        rm_status = self._rm_status()
        if rm_status is not None:
            base["state"] = _STATE_MAP.get(
                rm_status.get("manager_state"), self._state)
            self._state = base["state"]
            base["queue"] = {
                "manager_state": rm_status.get("manager_state"),
                "items_in_queue": rm_status.get("items_in_queue"),
                "items_in_history": rm_status.get("items_in_history"),
                "running_item_uid": rm_status.get("running_item_uid"),
                "queue_stop_pending": rm_status.get("queue_stop_pending"),
                "worker_environment_exists":
                    rm_status.get("worker_environment_exists"),
                "re_state": rm_status.get("re_state"),
            }
        else:
            base["queue"] = {"manager_state": None, "error": self._last_error}
        return base

    def start(self):
        """Spawn the RE Manager (and fakeredis if needed) and connect the API."""
        if self._proc is not None:
            log.warning("QueueServerRunner already started")
            return
        self._state = "connecting"
        log.info("Starting bluesky-queueserver backend "
                 f"(device_path={self._device_path})...")
        try:
            # 1. Redis: prefer a real server; fall back to in-process fakeredis.
            use_fake = os.environ.get("QSERVER_USE_FAKEREDIS", "auto").lower()
            real_ok = _startup.redis_reachable("127.0.0.1", self._redis_port)
            if use_fake in ("1", "true", "yes") or (use_fake == "auto"
                                                    and not real_ok):
                self._fakeredis = _startup.start_fakeredis_server(
                    "127.0.0.1", self._redis_port)
            else:
                log.info(f"Using real Redis at {self._redis_addr}")

            # 2. Generate plans/devices list matching the live profile.
            epd_path = _startup.generate_existing_plans_and_devices(
                device_path=self._device_path)

            # 3. Spawn the RE Manager subprocess.
            argv = _startup.build_re_manager_argv(
                self._zmq_control_addr, self._zmq_info_addr,
                self._redis_addr, epd_path)
            env = _startup._profile_env(
                {"QSERVER_DEVICE_PATH": self._device_path})
            popen_kw = {}
            if not sys.platform.startswith("win"):
                # Own process group so _kill_process_tree can killpg the worker.
                popen_kw["preexec_fn"] = os.setsid
            self._proc = subprocess.Popen(
                argv, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, **popen_kw)
            log.info(f"RE Manager subprocess pid={self._proc.pid}")

            # 4. Connect the control API and wait for the manager to answer.
            from bluesky_queueserver_api.zmq import REManagerAPI
            self._RM = REManagerAPI(zmq_control_addr=self._zmq_control_addr)
            self._wait_manager_up(QSERVER_STARTUP_TIMEOUT)

            self._state = "idle"
            log.info("QueueServerRunner ready (RE Manager responding)")
        except Exception as e:
            self._state = "error"
            self._last_error = str(e)
            log.error(f"QueueServerRunner start failed: {e}")
            self.shutdown()
            raise

    def submit(self, plan_name: str, **params):
        """Single-plan parity: open env if needed -> item_add -> queue_start.

        Returns the queue item uid (the closest analog to a run uid at submit
        time) or None on failure. Mirrors BlueskyRunner.submit's return contract.
        """
        if self._RM is None:
            log.error("QueueServerRunner not started")
            return None
        try:
            self._ensure_environment()
            uid = self._add_item(plan_name, params)
            self._current_plan = plan_name
            self._current_uid = uid
            self._event_count = 0
            self._RM.queue_start()
            self._state = "running"
            log.info(f"Submitted to queue + started: {plan_name}({params})")
            return uid
        except Exception as e:
            self._last_error = str(e)
            log.error(f"submit failed: {e}")
            return None

    def submit_async(self, plan_name: str, loop, **params):
        """Submit in a background thread (BlueskyRunner-compatible signature)."""
        self._loop = loop
        self._ensure_poller()

        def _run():
            self.submit(plan_name, **params)

        threading.Thread(target=_run, daemon=True,
                         name=f"qserver-submit-{plan_name}").start()

    def abort(self, reason: str = "User abort"):
        """Abort the running plan + stop the queue.

        RE Manager semantics: re_abort/re_stop/re_halt act on a PAUSED Run
        Engine, so an immediate abort of a running plan is pause -> wait-for-
        paused -> re_abort. queue_stop then prevents the next queued item from
        starting. If the RE is already idle/paused, the pause step is skipped.
        """
        if self._RM is None:
            return
        log.info(f"Aborting (qserver): {reason}")
        # Stop the queue first so no further items start after the abort.
        try:
            self._RM.queue_stop()
        except Exception as e:
            log.debug(f"queue_stop (pre-abort): {e}")
        try:
            st = self._rm_status() or {}
            re_state = st.get("re_state")
            if re_state == "running":
                # Pause, then abort the now-paused plan.
                self._RM.re_pause()
                try:
                    self._RM.wait_for_idle_or_paused(timeout=15)
                except Exception:
                    pass
            self._RM.re_abort()
        except Exception as e:
            # If re_abort still rejected (e.g. RE already idle), fall back to a
            # halt which is unconditional; ignore if that also fails.
            log.warning(f"re_abort: {e}")
            try:
                self._RM.re_halt()
            except Exception as e2:
                log.debug(f"re_halt fallback: {e2}")
        self._current_plan = None
        self._refresh_state()

    def pause(self):
        """Pause the running plan (re_pause)."""
        if self._RM is None:
            return
        try:
            self._RM.re_pause()
            self._state = "paused"
        except Exception as e:
            self._last_error = str(e)
            log.warning(f"pause: {e}")

    def resume(self):
        """Resume a paused plan (re_resume)."""
        if self._RM is None:
            return
        try:
            self._RM.re_resume()
            self._state = "running"
        except Exception as e:
            self._last_error = str(e)
            log.warning(f"resume: {e}")

    def list_plans(self) -> list:
        """Return allowed plans from the RE Manager (BlueskyRunner-shaped list).

        Falls back to an empty list if the environment is not open yet.
        """
        if self._RM is None:
            return []
        try:
            resp = self._RM.plans_allowed()
            plans = resp.get("plans_allowed", {})
            out = []
            for name, meta in plans.items():
                params = [p.get("name") for p in (meta.get("parameters") or [])]
                out.append({"name": name,
                            "desc": (meta.get("description") or "").split("\n")[0],
                            "params": params})
            return out
        except Exception as e:
            log.warning(f"list_plans: {e}")
            return []

    def shutdown(self):
        """Tear down poller, API, RE Manager subprocess, and fakeredis."""
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3)
        # Try a graceful environment close so the worker exits cleanly.
        if self._RM is not None:
            try:
                st = self._rm_status()
                if st and st.get("worker_environment_exists"):
                    self._RM.environment_close()
                    self._RM.wait_for_idle(timeout=10)
            except Exception:
                pass
            try:
                self._RM.close()
            except Exception:
                pass
            self._RM = None
        if self._proc is not None:
            _kill_process_tree(self._proc)
            self._proc = None
        if self._fakeredis is not None:
            try:
                self._fakeredis.shutdown()
            except Exception:
                pass
            self._fakeredis = None
        self._state = "idle"
        log.info("QueueServerRunner shut down")

    # Alias so callers using either name work (server.py uses shutdown()).
    def stop(self):
        self.shutdown()

    # ── Queue-native methods (no in-process equivalent) ───────────────────
    def env_open(self):
        self._ensure_environment()
        return self._rm_status()

    def env_close(self):
        if self._RM is None:
            return None
        self._RM.environment_close()
        self._RM.wait_for_idle(timeout=self._connect_timeout + 10)
        return self._rm_status()

    def queue_add(self, plan_name: str, **params):
        """Add a plan to the queue WITHOUT starting it. Returns item uid."""
        if self._RM is None:
            return None
        self._ensure_environment()
        return self._add_item(plan_name, params)

    def queue_start(self):
        if self._RM is None:
            return None
        self._ensure_poller()
        self._RM.queue_start()
        self._refresh_state()
        return self._rm_status()

    def queue_stop(self):
        if self._RM is None:
            return None
        self._RM.queue_stop()
        self._refresh_state()
        return self._rm_status()

    def queue_clear(self):
        if self._RM is None:
            return None
        self._RM.queue_clear()
        return self._rm_status()

    def queue_get(self):
        if self._RM is None:
            return {"items": [], "running_item": {}}
        try:
            return self._RM.queue_get()
        except Exception as e:
            log.warning(f"queue_get: {e}")
            return {"items": [], "running_item": {}, "error": str(e)}

    def history_get(self):
        if self._RM is None:
            return {"items": []}
        try:
            return self._RM.history_get()
        except Exception as e:
            log.warning(f"history_get: {e}")
            return {"items": [], "error": str(e)}

    # ── Internal helpers ──────────────────────────────────────────────────
    def _rm_status(self):
        if self._RM is None:
            return None
        try:
            return self._RM.status()
        except Exception as e:
            self._last_error = str(e)
            return None

    def _wait_manager_up(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._RM.status()
                return
            except Exception:
                time.sleep(QSERVER_POLL_INTERVAL)
        raise RuntimeError("RE Manager did not respond within "
                           f"{timeout:.0f}s (check subprocess/redis)")

    def _ensure_environment(self):
        """Open the worker environment if it is not already open."""
        st = self._rm_status()
        if st and st.get("worker_environment_exists"):
            return
        log.info("Opening RE Manager environment...")
        self._RM.environment_open()
        self._RM.wait_for_idle(timeout=self._connect_timeout + 30)

    def _add_item(self, plan_name, params):
        """Add a plan item to the queue; return its item uid."""
        from bluesky_queueserver_api import BPlan
        # Project plan wrappers take **kwargs only (no positional device args),
        # so forward params as kwargs. This matches scan_engine.qserver_profile.
        item = BPlan(plan_name, **(params or {}))
        resp = self._RM.item_add(item=item)
        return (resp.get("item", {}) or {}).get("item_uid")

    def _refresh_state(self):
        st = self._rm_status()
        if st is not None:
            self._state = _STATE_MAP.get(st.get("manager_state"), self._state)

    def _ensure_poller(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="qserver-status-poll")
        self._poll_thread.start()

    def _poll_loop(self):
        """Diff RE Manager status and emit scan_event transitions to ws."""
        while not self._poll_stop.is_set():
            st = self._rm_status()
            if st is not None:
                try:
                    self._emit_transitions(st)
                except Exception as e:
                    log.debug(f"poll emit error: {e}")
            self._poll_stop.wait(QSERVER_POLL_INTERVAL)

    def _emit_transitions(self, st):
        ms = st.get("manager_state")
        hist_len = st.get("items_in_history") or 0
        queue_len = st.get("items_in_queue")

        # run-begin: manager entered an executing state.
        if ms in ("executing_queue", "starting_queue") and \
                self._last_manager_state not in ("executing_queue",
                                                 "starting_queue"):
            self._current_uid = st.get("running_item_uid")
            self._emit_event("start", st)

        # run-end: a new item appeared in history.
        if hist_len > self._last_history_len:
            self._emit_event("stop", st)

        # generic queue/state transition.
        if ms != self._last_manager_state or queue_len != self._last_queue_len:
            self._emit_event("status", st)

        self._last_manager_state = ms
        self._last_history_len = hist_len
        self._last_queue_len = queue_len
        self._state = _STATE_MAP.get(ms, self._state)

    def _emit_event(self, doc_type, st):
        """Forward a transition to ws_callback in the scan_event envelope."""
        if not self._ws_callback:
            return
        event = {
            "type": "scan_event",
            "doc_type": doc_type,
            "doc": {
                "manager_state": st.get("manager_state"),
                "items_in_queue": st.get("items_in_queue"),
                "items_in_history": st.get("items_in_history"),
                "running_item_uid": st.get("running_item_uid"),
                "re_state": st.get("re_state"),
            },
            "plan": self._current_plan,
            "event_count": self._event_count,
            "backend": "qserver",
            "_ts_send": time.time(),
        }
        try:
            import asyncio
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._ws_callback(event), self._loop)
            else:
                self._ws_callback(event)
        except Exception as e:
            log.warning(f"ws emit error: {e}")
