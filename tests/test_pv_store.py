"""Unit tests for PVStore — in-memory motor/PV simulation."""
import math
import time
import pytest


def _val(result):
    """Extract scalar value from caget result (dict with 'value' key, or None)."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result["value"]
    return result


class TestPVStoreInit:
    """PVStore initialization and PV catalog."""

    def test_all_pvs_present(self, pv_store):
        """All expected PV groups exist."""
        snapshot = pv_store.get_all()
        groups = ["IVU", "M1", "M2", "DCM", "SSA", "KBV", "KBH",
                  "ZP", "SAM", "DET", "WBS", "FMASK", "MMASK", "ATT",
                  "RING", "FE", "XBPM", "IC1"]
        for g in groups:
            matching = [k for k in snapshot if k.startswith(f"BL10:{g}")]
            assert len(matching) > 0, f"No PVs found for {g}"

    def test_motor_count(self, pv_store):
        """At least 70 motor PVs exist."""
        snapshot = pv_store.get_all()
        motor_pvs = [k for k in snapshot if not any(
            k.startswith(f"BL10:{p}") for p in ("RING", "FE", "XBPM", "IC1")
        )]
        assert len(motor_pvs) >= 70

    def test_initial_dcm_theta(self, pv_store):
        """DCM:Theta starts at Bragg angle for ~10 keV."""
        val = _val(pv_store.caget("BL10:DCM:Theta"))
        assert 8 < val < 15, f"DCM:Theta={val} outside expected range"

    def test_ring_current(self, pv_store):
        """Ring current starts near 400 mA."""
        val = _val(pv_store.caget("BL10:RING:Current"))
        assert 390 < val < 410


class TestPVStoreCagetCaput:
    """Read/write operations."""

    def test_caput_caget_roundtrip(self, pv_store):
        """caput followed by scan+caget returns target value."""
        pv_store.caput("BL10:SAM:SX", 5.0)
        for _ in range(200):
            pv_store.scan()
        val = _val(pv_store.caget("BL10:SAM:SX"))
        assert abs(val - 5.0) < 0.1

    def test_caput_unknown_pv(self, pv_store):
        """caput to unknown PV auto-creates it (dynamic PV store)."""
        result = pv_store.caput("BL10:NONEXIST:X", 1.0)
        # PVStore dynamically creates unknown PVs on write
        assert result is True

    def test_caget_unknown_pv(self, pv_store):
        """caget of unknown PV returns default value dict (dynamic creation)."""
        val = pv_store.caget("BL10:NONEXIST:X")
        # PVStore returns a record dict with default value=0.0
        assert val is not None
        assert val['value'] == 0.0

    def test_soft_limit_enforcement(self, pv_store):
        """Writing beyond soft limit clamps value to limit."""
        pv = pv_store.pvs.get("BL10:IVU:Gap")
        if pv and pv.hi_limit < 1e6:
            original_hi = pv.hi_limit
            pv_store.caput("BL10:IVU:Gap", original_hi + 100)
            # caput clamps to limit, so setpoint should be at hi_limit
            assert pv.setpoint == original_hi, \
                f"Setpoint {pv.setpoint} should be clamped to {original_hi}"


class TestPVStoreMotorMovement:
    """Motor simulation accuracy."""

    def test_motor_moves_toward_setpoint(self, pv_store):
        """Motor position converges toward setpoint."""
        initial = _val(pv_store.caget("BL10:M1:Pitch"))
        target = initial + 0.5
        pv_store.caput("BL10:M1:Pitch", target)
        pv_store.scan()
        after = _val(pv_store.caget("BL10:M1:Pitch"))
        assert abs(after - target) < abs(initial - target)

    def test_motor_completes_movement(self, pv_store):
        """Motor arrives at setpoint after sufficient scan cycles."""
        pv_store.caput("BL10:SAM:FX", 2.0)
        for _ in range(500):
            pv_store.scan()
        val = _val(pv_store.caget("BL10:SAM:FX"))
        assert abs(val - 2.0) < 0.05


class TestPVStoreChangedTracking:
    """get_changed() differential update tracking."""

    def test_get_changed_after_caput(self, pv_store):
        """get_changed returns PV that was just written."""
        pv_store.get_changed()  # drain
        pv_store.caput("BL10:SAM:CX", 1.0)
        pv_store.scan()
        changed = pv_store.get_changed()
        assert "BL10:SAM:CX" in changed

    def test_get_changed_empty_after_drain(self, pv_store):
        """Second get_changed call returns no motor changes."""
        pv_store.get_changed()  # drain
        # No caput, no scan, so no motor changes
        changed = pv_store.get_changed()
        # Ring/XBPM noise may still cause changes
        motor_changed = {k: v for k, v in changed.items()
                         if not any(k.startswith(f"BL10:{p}")
                                    for p in ("RING", "XBPM", "IC1", "FE"))}
        assert len(motor_changed) == 0

    def test_noise_pvs_change(self, pv_store):
        """Ring/XBPM PVs change due to noise simulation."""
        pv_store.get_changed()
        pv_store.scan()
        changed = pv_store.get_changed()
        noise_pvs = [k for k in changed if "RING" in k or "XBPM" in k]
        assert len(noise_pvs) > 0, "Noise PVs should change every scan"
