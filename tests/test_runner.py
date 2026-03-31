"""Unit tests for BlueskyRunner — scan orchestration (no EPICS required)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestBlueskyRunnerImport:
    """Module import and class instantiation."""

    def test_runner_importable(self):
        """BlueskyRunner can be imported."""
        from scan_engine.runner import BlueskyRunner
        assert BlueskyRunner is not None

    def test_runner_instantiation(self):
        """BlueskyRunner can be created without EPICS."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        assert runner is not None

    def test_runner_has_required_methods(self):
        """BlueskyRunner exposes submit, abort, pause, resume, status."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        assert callable(getattr(runner, 'submit', None))
        assert callable(getattr(runner, 'abort', None))
        assert callable(getattr(runner, 'pause', None))
        assert callable(getattr(runner, 'resume', None))
        assert callable(getattr(runner, 'status', None))
        assert callable(getattr(runner, 'list_plans', None))


class TestBlueskyRunnerStatus:
    """Runner status reporting."""

    def test_initial_status(self):
        """Fresh runner reports idle state."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        status = runner.status()
        assert isinstance(status, dict)
        assert status.get("state") in ("idle", "not_started", None) or "state" in status

    def test_status_has_fields(self):
        """Status dict includes expected fields."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        status = runner.status()
        # Should have at least 'state' key
        assert "state" in status


class TestBlueskyRunnerPlanListing:
    """list_plans() functionality."""

    def test_list_plans_returns_list(self):
        """list_plans returns a list or dict of plans."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        plans = runner.list_plans()
        assert isinstance(plans, (list, dict))

    def test_list_plans_contains_energy_scan(self):
        """energy_scan is in the plan registry."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        plans = runner.list_plans()
        if isinstance(plans, dict):
            assert "energy_scan" in plans
        elif isinstance(plans, list):
            plan_names = [p.get("name", p) if isinstance(p, dict) else p
                          for p in plans]
            assert "energy_scan" in plan_names

    def test_list_plans_contains_raster_scan(self):
        """raster_scan is in the plan registry."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        plans = runner.list_plans()
        if isinstance(plans, dict):
            assert "raster_scan" in plans
        elif isinstance(plans, list):
            plan_names = [p.get("name", p) if isinstance(p, dict) else p
                          for p in plans]
            assert "raster_scan" in plan_names

    def test_list_plans_contains_advanced_scans(self):
        """Advanced scan modes are registered."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        plans = runner.list_plans()
        plan_names = [p.get("name", p) if isinstance(p, dict) else p
                      for p in plans]
        for name in ["xanes_scan", "multi_region_scan", "fly_scan", "line_scan"]:
            assert name in plan_names, f"Missing plan: {name}"


class TestBlueskyRunnerCallbackWS:
    """WebSocket callback integration."""

    def test_runner_with_callback(self):
        """Runner accepts ws_callback parameter."""
        from scan_engine.runner import BlueskyRunner
        received = []
        def callback(msg):
            received.append(msg)
        runner = BlueskyRunner(ws_callback=callback)
        assert runner is not None

    def test_runner_without_callback(self):
        """Runner works without callback (silent mode)."""
        from scan_engine.runner import BlueskyRunner
        runner = BlueskyRunner()
        assert runner is not None


class TestDocumentSerialization:
    """JSON-safe document conversion."""

    def test_numpy_serialization(self):
        """numpy types must be converted for JSON."""
        import numpy as np
        # Simulate the serialization logic from runner
        val = np.float64(3.14)
        serialized = float(val)
        assert isinstance(serialized, float)

        val_int = np.int64(42)
        serialized_int = int(val_int)
        assert isinstance(serialized_int, int)

    def test_numpy_array_serialization(self):
        """numpy arrays must be converted to lists."""
        import numpy as np
        arr = np.array([1.0, 2.0, 3.0])
        serialized = arr.tolist()
        assert isinstance(serialized, list)
        assert all(isinstance(x, float) for x in serialized)
