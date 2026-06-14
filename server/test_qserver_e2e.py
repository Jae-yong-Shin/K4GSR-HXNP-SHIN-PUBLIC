#!/usr/bin/env python3
"""End-to-end test for the B1 bluesky-queueserver backend.

Runnable, blocking-assert E2E that exercises the REAL QueueServerRunner class
against a REAL separate-process RE Manager (spawned by the runner itself) backed
by an in-process fakeredis TCP server.

Device path
-----------
Uses the ophyd.sim path (QSERVER_DEVICE_PATH=sim): a simulated detector + motor,
no EPICS-CA. This proves the QUEUE MECHANICS (environment open/close, item add,
queue start/stop, history, abort) deterministically on Windows where live
EPICS-CA via the caproto soft IOC is flaky. Full real-device E2E (epics path,
soft IOC) is deferred to VM1 -- see TASK_B1_QUEUESERVER.md.

Steps (each asserted)
---------------------
  1. start()                 -> RE Manager subprocess + fakeredis up, API answers
  2. env_open()              -> worker environment exists
  3. queue_add(count)        -> 1 item queued
  4. queue_start() + poll    -> runs to completion, history shows 1 success
  5. abort path: queue_add a longer count -> queue_start -> abort()
                             -> queue stopped / manager returns to idle
  6. env_close()             -> environment torn down
  7. shutdown()              -> subprocess + fakeredis gone, no orphans

Zero-regression (separate test)
-------------------------------
  With SCAN_BACKEND unset, assert server.py's runner-construction branch yields a
  BlueskyRunner whose status() has the original shape (construction-branch check;
  no live in-process scan required).

Run:
    python server/test_qserver_e2e.py
Exit code 0 == all assertions passed.
"""

import os
import sys
import time

# Make server/ importable (constants, scan_engine, ...).
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# Force the sim device path for a deterministic, EPICS-free queue test.
os.environ["QSERVER_DEVICE_PATH"] = "sim"
os.environ["QSERVER_USE_FAKEREDIS"] = "1"

from scan_engine.qserver_runner import QueueServerRunner  # noqa: E402


def _poll_until(runner, predicate, timeout, label):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = runner.status()
        if predicate(last):
            return last
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for {label}; last status={last}")


def test_queue_e2e():
    t0 = time.time()
    timings = {}
    runner = QueueServerRunner()

    # 1. start
    t = time.time()
    runner.start()
    timings["start"] = time.time() - t
    st = runner.status()
    assert st["backend"] == "qserver", f"backend != qserver: {st}"
    assert st["state"] in ("idle", "connecting"), f"unexpected state: {st}"
    print(f"[e2e] 1. start OK ({timings['start']:.1f}s) state={st['state']}")

    try:
        # 2. env_open
        t = time.time()
        runner.env_open()
        st = _poll_until(
            runner,
            lambda s: s.get("queue", {}).get("worker_environment_exists"),
            60, "environment_open")
        timings["env_open"] = time.time() - t
        assert st["queue"]["worker_environment_exists"] is True
        print(f"[e2e] 2. env_open OK ({timings['env_open']:.1f}s)")

        # 3. queue_add (count plan over the sim detector)
        item_uid = runner.queue_add("count", detectors=["det"], num=3, delay=0.05)
        st = runner.status()
        assert st["queue"]["items_in_queue"] == 1, f"queue not 1: {st}"
        print(f"[e2e] 3. queue_add OK item_uid={str(item_uid)[:8]} "
              f"items_in_queue={st['queue']['items_in_queue']}")

        # 4. queue_start -> poll to completion -> history shows 1 success
        t = time.time()
        runner.queue_start()
        st = _poll_until(
            runner,
            lambda s: (s.get("queue", {}).get("manager_state") == "idle"
                       and s.get("queue", {}).get("items_in_queue") == 0
                       and (s.get("queue", {}).get("items_in_history") or 0) >= 1),
            60, "queue completion")
        timings["run_count"] = time.time() - t
        hist = runner.history_get().get("items", [])
        assert len(hist) >= 1, f"history empty: {hist}"
        exit_status = hist[-1].get("result", {}).get("exit_status")
        assert exit_status == "completed", f"exit_status != completed: {exit_status}"
        print(f"[e2e] 4. queue_start->complete OK ({timings['run_count']:.1f}s) "
              f"history={len(hist)} exit_status={exit_status}")

        # 5. abort path: add a longer plan, start, abort mid-run
        n_hist_before = runner.status()["queue"]["items_in_history"] or 0
        runner.queue_add("count", detectors=["det"], num=200, delay=0.1)
        runner.queue_start()
        # Wait until it is actually executing before aborting.
        _poll_until(
            runner,
            lambda s: s.get("queue", {}).get("manager_state") in
                      ("executing_queue", "starting_queue"),
            20, "executing (pre-abort)")
        time.sleep(0.5)
        t = time.time()
        runner.abort("E2E abort test")
        st = _poll_until(
            runner,
            lambda s: s.get("queue", {}).get("manager_state") == "idle",
            30, "idle after abort")
        timings["abort"] = time.time() - t
        assert st["queue"]["manager_state"] == "idle", f"not idle after abort: {st}"
        # The abort must INTERRUPT the long plan, not wait for it to finish
        # naturally (200 pts x 0.1s = ~20s). Assert it returned quickly.
        assert timings["abort"] < 15, \
            f"abort did not interrupt the running plan (took {timings['abort']:.1f}s)"
        # The interrupted run should be recorded as aborted/failed (not completed).
        hist2 = runner.history_get().get("items", [])
        assert len(hist2) > n_hist_before, \
            f"aborted run not recorded in history ({len(hist2)} <= {n_hist_before})"
        last_exit = hist2[-1].get("result", {}).get("exit_status") if hist2 else None
        assert last_exit in ("aborted", "failed", "halted"), \
            f"interrupted run exit_status should be aborted/failed, got {last_exit}"
        print(f"[e2e] 5. abort path OK ({timings['abort']:.1f}s) "
              f"state=idle last_exit={last_exit}")

        # Clear any residual queue so env_close is clean.
        runner.queue_clear()

        # 6. env_close
        t = time.time()
        runner.env_close()
        st = _poll_until(
            runner,
            lambda s: not s.get("queue", {}).get("worker_environment_exists"),
            30, "environment_close")
        timings["env_close"] = time.time() - t
        assert st["queue"]["worker_environment_exists"] is False
        print(f"[e2e] 6. env_close OK ({timings['env_close']:.1f}s)")

    finally:
        # 7. shutdown + orphan check
        proc = runner._proc
        pid = proc.pid if proc else None
        t = time.time()
        runner.shutdown()
        timings["shutdown"] = time.time() - t
        assert runner._proc is None, "subprocess handle not cleared"
        assert runner._fakeredis is None, "fakeredis not shut down"
        if pid is not None:
            # The subprocess must have actually exited.
            assert proc.poll() is not None, f"RE Manager pid {pid} still running"
        print(f"[e2e] 7. shutdown OK ({timings['shutdown']:.1f}s) "
              f"pid {pid} exited; no orphans")

    print(f"[e2e] queue E2E PASSED in {time.time() - t0:.1f}s; timings={timings}")
    return timings


def test_zero_regression_construction():
    """With SCAN_BACKEND unset, the construction branch yields a BlueskyRunner.

    Replicates server.py's selection logic (constants.SCAN_BACKEND_DEFAULT) and
    asserts the default builds BlueskyRunner with the original status() shape.
    Does NOT call .start() (no live IOC required).
    """
    from constants import SCAN_BACKEND_DEFAULT
    from scan_engine.runner import BlueskyRunner

    backend = os.environ.get("SCAN_BACKEND", SCAN_BACKEND_DEFAULT).strip().lower()
    assert backend == "inprocess", \
        f"default backend must be 'inprocess', got {backend!r}"

    # Build via the same branch server.py takes for the default.
    runner = BlueskyRunner(ws_callback=None, connect_timeout=1.0)
    assert isinstance(runner, BlueskyRunner)

    st = runner.status()
    # Original BlueskyRunner.status() keys (no 'backend', no 'queue').
    expected = {"state", "plan", "uid", "event_count", "last_error",
                "devices_connected", "auto_save", "data_dir"}
    assert expected.issubset(set(st.keys())), \
        f"status() missing original keys: {expected - set(st.keys())}"
    assert "backend" not in st, "in-process status() must NOT have 'backend'"
    assert st["state"] == "idle"
    print(f"[e2e] zero-regression OK: default branch -> BlueskyRunner, "
          f"status keys={sorted(st.keys())}")


def test_inprocess_queue_gating():
    """scan_handler's queue-action gating must reject the in-process backend.

    Replicates server.py's gating predicate against a BlueskyRunner and asserts
    queue actions would be refused (the informative scan_error path), i.e. the
    in-process backend does NOT pretend to have a queue.
    """
    from scan_engine.runner import BlueskyRunner
    runner = BlueskyRunner(ws_callback=None, connect_timeout=1.0)
    st = runner.status()
    # Predicate from server.py: route only if the method exists AND backend is
    # qserver. For queue_add the method does not even exist on BlueskyRunner.
    has_queue_add = hasattr(runner, "queue_add")
    is_qserver = st.get("backend") == "qserver"
    gated_out = (not has_queue_add) or (not is_qserver)
    assert gated_out, "in-process backend must be gated out of queue actions"
    assert not has_queue_add, "BlueskyRunner unexpectedly has queue_add"
    assert not is_qserver, "BlueskyRunner status must not report backend=qserver"
    print("[e2e] in-process queue gating OK: queue actions refused "
          "(no queue_add, backend != qserver)")


def main():
    print("=" * 70)
    print("B1 queueserver E2E (device path: ophyd.sim; redis: fakeredis TCP)")
    print("=" * 70)
    # Zero-regression + gating first (cheap, no subprocess).
    test_zero_regression_construction()
    test_inprocess_queue_gating()
    test_queue_e2e()
    print("=" * 70)
    print("ALL E2E ASSERTIONS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n[e2e] FAILED: {e}")
        sys.exit(1)
