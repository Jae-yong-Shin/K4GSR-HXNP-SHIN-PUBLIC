"""Unit tests for CABridge — EPICS Channel Access bridge (mock-based)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestCABridgeImport:
    """Module import and fallback behavior."""

    def test_ca_bridge_importable(self):
        """ca_bridge module can be imported."""
        import ca_bridge
        assert hasattr(ca_bridge, 'CABridge')

    def test_has_pvstore_interface(self):
        """CABridge exposes PVStore-compatible API."""
        from ca_bridge import CABridge
        # Verify method signatures exist (without connecting)
        assert callable(getattr(CABridge, 'caput', None))
        assert callable(getattr(CABridge, 'caget', None))
        assert callable(getattr(CABridge, 'scan', None))
        assert callable(getattr(CABridge, 'get_changed', None))
        assert callable(getattr(CABridge, 'get_all', None))
        assert callable(getattr(CABridge, 'close', None))


class TestCABridgePVClassification:
    """PV naming convention: motor vs status PVs."""

    def test_motor_pv_rbv_suffix(self):
        """Motor PVs use .RBV suffix (not :RBV)."""
        # This test verifies the naming convention change
        motor_rbv = "BL10:M1:Pitch.RBV"
        assert motor_rbv.endswith(".RBV")
        base = motor_rbv[:-4]
        assert base == "BL10:M1:Pitch"

    def test_status_pv_no_rbv(self):
        """Status PVs (Ring, XBPM) don't have .RBV suffix."""
        status_pvs = [
            "BL10:RING:Current",
            "BL10:FE:Shutter",
            "BL10:XBPM1:X",
            "BL10:IC1:Current"
        ]
        for pv in status_pvs:
            assert not pv.endswith(".RBV")

    def test_motor_record_fields(self):
        """Standard motor record fields use dot notation."""
        base = "BL10:DCM:Theta"
        fields = {
            f"{base}.RBV": "readback",
            f"{base}.VELO": "velocity",
            f"{base}.DMOV": "done moving",
            f"{base}.STOP": "stop",
            f"{base}.HLM": "high limit",
            f"{base}.LLM": "low limit",
            f"{base}.EGU": "engineering units",
        }
        for pv, desc in fields.items():
            assert "." in pv, f"Motor field {desc} should use dot notation"
            parts = pv.split(".")
            assert len(parts) == 2, f"Motor field should have exactly one dot"


class TestPVStoreCompatibility:
    """PVStore and CABridge share the same interface."""

    def test_interface_methods_match(self, pv_store):
        """PVStore has same public methods as CABridge."""
        from ca_bridge import CABridge
        pv_methods = {'caput', 'caget', 'scan', 'get_changed', 'get_all'}
        for method in pv_methods:
            assert hasattr(pv_store, method), f"PVStore missing {method}"
            assert hasattr(CABridge, method), f"CABridge missing {method}"

    def test_get_all_returns_dict(self, pv_store):
        """get_all returns dict of PV name → value."""
        result = pv_store.get_all()
        assert isinstance(result, dict)
        assert len(result) > 0
        # All keys should be strings starting with BL10:
        for key in result:
            assert isinstance(key, str)
            assert key.startswith("BL10:")

    def test_get_changed_returns_dict(self, pv_store):
        """get_changed returns dict."""
        result = pv_store.get_changed()
        assert isinstance(result, dict)


class TestPVStoreCagetCaputRoundtrip:
    """D12: Integration tests — caput/caget round-trip via PVStore.

    Uses PVStore as a mock IOC to verify actual data flow.
    """

    def test_caput_caget_immediate_pv(self, pv_store):
        """caput a non-motor PV → caget returns new value immediately."""
        pv_name = "BL10:RING:Current"
        pv_store.caput(pv_name, 350.0)
        result = pv_store.caget(pv_name)
        assert result is not None
        assert abs(result['value'] - 350.0) < 0.01

    def test_caput_motor_starts_moving(self, pv_store):
        """caput a motor PV → motor starts moving toward setpoint."""
        pv_name = "BL10:DCM:Theta"
        pv = pv_store.pvs.get(pv_name)
        if pv is None:
            pytest.skip(f"{pv_name} not in PVStore")
        original = pv.value
        target = original + 1.0
        pv_store.caput(pv_name, target)
        assert pv.moving is True
        assert pv.setpoint == target

    def test_motor_reaches_target_after_scan(self, pv_store):
        """Motor reaches target after enough scan cycles."""
        pv_name = "BL10:IVU:Gap"
        pv = pv_store.pvs.get(pv_name)
        if pv is None:
            pytest.skip(f"{pv_name} not in PVStore")
        target = 8.0
        pv_store.caput(pv_name, target)
        # Run enough scan cycles for motor to arrive
        for _ in range(200):
            pv_store.scan()
        assert abs(pv.value - target) < 0.01
        assert pv.moving is False

    def test_caput_soft_limit_clamp(self, pv_store):
        """caput beyond soft limits clamps value."""
        pv_name = "BL10:IVU:Gap"
        pv = pv_store.pvs.get(pv_name)
        if pv is None:
            pytest.skip(f"{pv_name} not in PVStore")
        # Set way above high limit
        pv_store.caput(pv_name, 999.0)
        assert pv.setpoint <= pv.hi_limit

    def test_get_changed_after_caput(self, pv_store):
        """get_changed includes PV after caput."""
        pv_name = "BL10:RING:Current"
        pv_store.caput(pv_name, 123.0)
        changed = pv_store.get_changed()
        assert pv_name in changed
        assert changed[pv_name]['value'] == 123.0

    def test_get_changed_cleared_after_read(self, pv_store):
        """get_changed clears after read — second call returns empty."""
        pv_store.caput("BL10:RING:Current", 200.0)
        pv_store.get_changed()  # first read
        changed2 = pv_store.get_changed()  # second read
        assert "BL10:RING:Current" not in changed2

    def test_caget_rbv_suffix(self, pv_store):
        """caget with .RBV suffix returns motor readback."""
        pv_name = "BL10:IVU:Gap"
        result = pv_store.caget(pv_name + ".RBV")
        assert result is not None
        assert 'value' in result
