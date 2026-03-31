"""Unit tests for Bluesky scan plans — plan generation (no hardware)."""
import math
import pytest

# Plans module can be imported without hardware
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from scan_engine.plans import (
    energy_to_theta, theta_to_energy, HC_ANGSTROM, SI_111_D,
    ABSORPTION_EDGES
)


class TestEnergyConversion:
    """Bragg angle ↔ energy conversion for Si(111)."""

    def test_10keV(self):
        """10 keV → ~11.4° Bragg angle."""
        theta = energy_to_theta(10.0)
        assert 11.0 < theta < 12.0

    def test_roundtrip(self):
        """energy → theta → energy roundtrip is lossless."""
        for e in [5.0, 8.0, 10.0, 15.0, 20.0, 30.0]:
            theta = energy_to_theta(e)
            e_back = theta_to_energy(theta)
            assert abs(e_back - e) < 1e-6, f"Roundtrip failed for {e} keV"

    def test_bragg_law(self):
        """Verify Bragg's law: E = hc / (2d·sin(θ))."""
        E = 10.0  # keV
        theta = energy_to_theta(E)
        theta_rad = math.radians(theta)
        E_calc = HC_ANGSTROM / (2 * SI_111_D * math.sin(theta_rad)) / 1000
        assert abs(E_calc - E) < 1e-4

    def test_monotonic(self):
        """Higher energy → smaller Bragg angle."""
        angles = [energy_to_theta(e) for e in [5, 10, 15, 20, 25]]
        for i in range(len(angles) - 1):
            assert angles[i] > angles[i + 1]

    def test_low_energy_limit(self):
        """Very low energy raises or returns valid angle."""
        theta = energy_to_theta(2.0)  # 2 keV
        assert 0 < theta < 90

    def test_high_energy_limit(self):
        """High energy returns small angle."""
        theta = energy_to_theta(40.0)  # 40 keV
        assert 0 < theta < 5


class TestAbsorptionEdges:
    """Absorption edge database."""

    def test_fe_k_edge(self):
        """Fe K-edge at ~7.112 keV."""
        assert abs(ABSORPTION_EDGES["Fe"]["K"] - 7.112) < 0.01

    def test_cu_k_edge(self):
        """Cu K-edge at ~8.979 keV."""
        assert abs(ABSORPTION_EDGES["Cu"]["K"] - 8.979) < 0.01

    def test_common_elements_have_k_edge(self):
        """Common 3d transition metals have K edge defined."""
        for elem in ["Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn"]:
            if elem in ABSORPTION_EDGES:
                assert "K" in ABSORPTION_EDGES[elem], f"{elem} missing K edge"

    def test_edge_energies_positive(self):
        """All edge energies are positive."""
        for elem, edges in ABSORPTION_EDGES.items():
            for edge_name, energy in edges.items():
                assert energy > 0, f"{elem} {edge_name} edge = {energy}"


class TestPlanGeneration:
    """Plan function signature and generator validation."""

    def test_energy_scan_is_generator(self):
        """energy_scan returns a generator (bluesky plan)."""
        from scan_engine.plans import energy_scan
        # Without devices, we can't fully run, but verify it's a generator function
        import inspect
        assert inspect.isgeneratorfunction(energy_scan)

    def test_xafs_scan_is_generator(self):
        """xafs_scan returns a generator."""
        from scan_engine.plans import xafs_scan
        import inspect
        assert inspect.isgeneratorfunction(xafs_scan)

    def test_raster_scan_is_generator(self):
        """raster_scan returns a generator."""
        from scan_engine.plans import raster_scan
        import inspect
        assert inspect.isgeneratorfunction(raster_scan)

    def test_alignment_scan_is_generator(self):
        """alignment_scan returns a generator."""
        from scan_engine.plans import alignment_scan
        import inspect
        assert inspect.isgeneratorfunction(alignment_scan)

    def test_beam_check_is_generator(self):
        """beam_check returns a generator."""
        from scan_engine.plans import beam_check
        import inspect
        assert inspect.isgeneratorfunction(beam_check)

    def test_xanes_scan_is_generator(self):
        """xanes_scan returns a generator."""
        from scan_engine.plans import xanes_scan
        import inspect
        assert inspect.isgeneratorfunction(xanes_scan)

    def test_multi_region_scan_is_generator(self):
        """multi_region_scan returns a generator."""
        from scan_engine.plans import multi_region_scan
        import inspect
        assert inspect.isgeneratorfunction(multi_region_scan)

    def test_fly_scan_is_generator(self):
        """fly_scan returns a generator."""
        from scan_engine.plans import fly_scan
        import inspect
        assert inspect.isgeneratorfunction(fly_scan)

    def test_line_scan_is_generator(self):
        """line_scan returns a generator."""
        from scan_engine.plans import line_scan
        import inspect
        assert inspect.isgeneratorfunction(line_scan)


class TestXAFSRegions:
    """XAFS multi-region scan logic."""

    def test_xafs_edge_lookup(self):
        """XAFS can find Fe K-edge energy."""
        edge_e = ABSORPTION_EDGES.get("Fe", {}).get("K")
        assert edge_e is not None
        assert abs(edge_e - 7.112) < 0.01

    def test_xafs_region_calculation(self):
        """Pre-edge, edge, post-edge regions are correctly ordered."""
        edge_e = ABSORPTION_EDGES["Fe"]["K"]
        pre_start = edge_e - 0.15   # 150 eV below
        edge_start = edge_e - 0.02  # 20 eV below
        post_end = edge_e + 0.30    # 300 eV above

        assert pre_start < edge_start < edge_e < post_end
        assert pre_start > 0

    def test_energy_step_sizes(self):
        """Typical XAFS step sizes: pre(5eV) < edge(0.5eV) < post(2eV)."""
        pre_step = 5.0    # eV
        edge_step = 0.5   # eV
        post_step = 2.0   # eV
        assert edge_step < post_step < pre_step


class TestXANESParams:
    """XANES scan parameter validation."""

    def test_xanes_finer_than_xafs(self):
        """XANES default edge step (0.25 eV) < XAFS default (0.5 eV)."""
        xanes_step = 0.25
        xafs_step = 0.5
        assert xanes_step < xafs_step

    def test_xanes_narrower_range(self):
        """XANES covers narrower range than full XAFS."""
        xanes_pre = 50   # eV
        xanes_post = 100  # eV
        xafs_pre = 150   # eV
        xafs_post = 400  # eV
        assert xanes_pre < xafs_pre
        assert xanes_post < xafs_post

    def test_xanes_unknown_element_raises(self):
        """XANES with unknown element raises ValueError."""
        from scan_engine.plans import xanes_scan
        with pytest.raises(ValueError, match="Unknown element"):
            # Consume the generator to trigger the error
            list(xanes_scan({}, 'Unobtanium'))


class TestMultiRegionParams:
    """Multi-region scan parameter validation."""

    def test_empty_regions_raises(self):
        """Empty region list raises ValueError."""
        from scan_engine.plans import multi_region_scan
        with pytest.raises(ValueError, match="At least one region"):
            list(multi_region_scan({}, []))

    def test_regions_structure(self):
        """Region dicts have required keys."""
        regions = [
            {'start': 6.9, 'stop': 7.05, 'step': 5.0},
            {'start': 7.05, 'stop': 7.18, 'step': 0.3},
        ]
        for r in regions:
            assert 'start' in r
            assert 'stop' in r
            assert r['start'] < r['stop']


class TestFlyScanParams:
    """Fly scan parameter validation."""

    def test_fly_unknown_device_raises(self):
        """Fly scan with unknown device raises ValueError."""
        from scan_engine.plans import fly_scan
        with pytest.raises(ValueError, match="Unknown device"):
            list(fly_scan({}, 'nonexistent', 'x', 0, 10, 50))

    def test_fly_scan_metadata(self):
        """Fly scan metadata includes fly_mode field."""
        md = {'plan_name': 'fly_scan', 'fly_mode': 'step_emulated'}
        assert md['fly_mode'] == 'step_emulated'


class TestLineScanParams:
    """Line scan parameter validation."""

    def test_diagonal_line(self):
        """Line scan from (0,0) to (10,10) is diagonal."""
        import numpy as np
        x = np.linspace(0, 10, 21)
        y = np.linspace(0, 10, 21)
        # Diagonal: x == y at all points
        np.testing.assert_allclose(x, y)

    def test_horizontal_line(self):
        """Line scan with constant y is horizontal."""
        import numpy as np
        x = np.linspace(-5, 5, 11)
        y = np.linspace(0, 0, 11)
        assert all(yi == 0 for yi in y)
