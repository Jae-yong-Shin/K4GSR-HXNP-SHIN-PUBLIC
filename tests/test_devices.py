"""Unit tests for ophyd device definitions (no EPICS connection)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestDeviceImport:
    """Device module import and class availability."""

    def test_devices_importable(self):
        """scan_engine.devices can be imported."""
        from scan_engine import devices
        assert devices is not None

    def test_create_devices_exists(self):
        """create_devices factory function exists."""
        from scan_engine.devices import create_devices
        assert callable(create_devices)

    def test_connect_devices_exists(self):
        """connect_devices function exists."""
        from scan_engine.devices import connect_devices
        assert callable(connect_devices)


class TestDeviceClasses:
    """Verify all device classes are defined with correct structure."""

    def _get_class(self, name):
        import scan_engine.devices as mod
        return getattr(mod, name, None)

    def test_bl10_mirror(self):
        """BL10Mirror has required axes."""
        cls = self._get_class("BL10Mirror")
        assert cls is not None
        # Check component names
        for axis in ["z", "pitch", "pitch_f", "tx", "roll", "yaw",
                      "bend_u", "bend_d"]:
            assert hasattr(cls, axis), f"BL10Mirror missing axis: {axis}"

    def test_bl10_dcm(self):
        """BL10DCM has theta and chi axes."""
        cls = self._get_class("BL10DCM")
        assert cls is not None
        for axis in ["theta", "chi1", "tx"]:
            assert hasattr(cls, axis), f"BL10DCM missing axis: {axis}"

    def test_bl10_kbv(self):
        """BL10KBV has pitch, bend axes."""
        cls = self._get_class("BL10KBV")
        assert cls is not None
        for axis in ["pitch", "bend_u", "bend_d"]:
            assert hasattr(cls, axis), f"BL10KBV missing axis: {axis}"

    def test_bl10_kbh(self):
        """BL10KBH has pitch, bend axes."""
        cls = self._get_class("BL10KBH")
        assert cls is not None
        for axis in ["pitch", "bend_u", "bend_d"]:
            assert hasattr(cls, axis), f"BL10KBH missing axis: {axis}"

    def test_bl10_sample(self):
        """BL10Sample has coarse + fine + scan stages."""
        cls = self._get_class("BL10Sample")
        assert cls is not None
        for axis in ["cx", "cy", "cz", "fx", "fy", "fz", "sx", "sy"]:
            assert hasattr(cls, axis), f"BL10Sample missing axis: {axis}"

    def test_bl10_ssa(self):
        """BL10SSA has gap and center controls."""
        cls = self._get_class("BL10SSA")
        assert cls is not None
        for axis in ["hgap", "vgap", "hcen", "vcen"]:
            assert hasattr(cls, axis), f"BL10SSA missing axis: {axis}"

    def test_bl10_wbslit(self):
        """BL10WBSlit has blade and gap controls."""
        cls = self._get_class("BL10WBSlit")
        assert cls is not None
        for axis in ["top", "bot", "inb", "outb", "hgap", "vgap"]:
            assert hasattr(cls, axis), f"BL10WBSlit missing axis: {axis}"


class TestDeviceCreation:
    """create_devices() factory test (no connection)."""

    def test_create_devices_returns_dict(self):
        """create_devices returns dict of device instances."""
        from scan_engine.devices import create_devices
        devices = create_devices()
        assert isinstance(devices, dict)
        assert len(devices) > 0

    def test_expected_device_keys(self):
        """Device dict has expected keys."""
        from scan_engine.devices import create_devices
        devices = create_devices()
        expected = ["m1", "m2", "dcm", "ssa", "kbv", "kbh",
                     "sample", "det", "ivu", "wbs", "ring"]
        for key in expected:
            assert key in devices, f"Missing device: {key}"

    def test_device_pv_prefix(self):
        """All EPICS devices use BL10: prefix (virtual detectors excluded)."""
        from scan_engine.devices import create_devices
        devices = create_devices()
        for name, dev in devices.items():
            if name.startswith('v'):  # virtual devices (vxrf etc.)
                continue
            prefix = getattr(dev, 'prefix', '')
            if prefix:
                assert "BL10" in prefix, \
                    f"Device {name} prefix={prefix} missing BL10"


class TestEpicsMotorUsage:
    """Verify EpicsMotor is used (not PVPositionerComparator)."""

    def test_no_pv_positioner_comparator(self):
        """BL10SimMotor / PVPositionerComparator not used."""
        import scan_engine.devices as mod
        with open(mod.__file__, encoding='utf-8') as f:
            source = f.read()
        assert "PVPositionerComparator" not in source, \
            "Should use EpicsMotor, not PVPositionerComparator"

    def test_uses_epics_motor(self):
        """EpicsMotor is imported and used."""
        import scan_engine.devices as mod
        with open(mod.__file__, encoding='utf-8') as f:
            source = f.read()
        assert "EpicsMotor" in source
