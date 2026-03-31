#!/usr/bin/env python3
"""Simulated area detector for K4GSR BL10 NanoProbe.

Generates 2D detector images for:
  - XRF elemental maps (raster scan)
  - Diffraction patterns (2D Gaussian peaks on rings)
  - Transmission/fluorescence yield images

Output: NumPy arrays compatible with HDF5 storage.

Usage:
    from detector import AreaDetector
    det = AreaDetector(nx=256, ny=256)
    frame = det.generate_xrf_frame(position=(10, 20), sample=my_sample)
"""

import numpy as np
import logging
from typing import Tuple, Optional, Dict

log = logging.getLogger("detector-sim")


class SampleMap:
    """Define a virtual 2D sample with elemental distribution.

    The sample is a grid of composition values. Each cell has concentrations
    for multiple elements, creating spatial features for XRF mapping.
    """

    def __init__(self, size_um: Tuple[float, float] = (100.0, 100.0),
                 resolution_um: float = 0.5):
        """Create a sample map.

        Args:
            size_um: (width, height) in micrometers
            resolution_um: pixel size in um
        """
        self.size_um = size_um
        self.resolution_um = resolution_um
        self.nx = int(size_um[0] / resolution_um)
        self.ny = int(size_um[1] / resolution_um)
        self.elements: Dict[str, np.ndarray] = {}

    def add_uniform(self, element: str, concentration: float = 0.01):
        """Add uniform element distribution."""
        self.elements[element] = np.full((self.ny, self.nx), concentration)

    def add_gaussian_spot(self, element: str, center_um: Tuple[float, float],
                          sigma_um: float, peak_conc: float = 0.1):
        """Add a Gaussian hotspot."""
        if element not in self.elements:
            self.elements[element] = np.zeros((self.ny, self.nx))

        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        cx = center_um[0] / self.resolution_um
        cy = center_um[1] / self.resolution_um
        sigma_px = sigma_um / self.resolution_um

        spot = peak_conc * np.exp(-0.5 * ((xx - cx)**2 + (yy - cy)**2) / sigma_px**2)
        self.elements[element] += spot

    def add_stripe(self, element: str, direction: str = 'h',
                   center_um: float = 50.0, width_um: float = 10.0,
                   concentration: float = 0.05):
        """Add a stripe feature (horizontal or vertical)."""
        if element not in self.elements:
            self.elements[element] = np.zeros((self.ny, self.nx))

        if direction == 'h':
            cy = int(center_um / self.resolution_um)
            hw = int(width_um / self.resolution_um / 2)
            lo = max(0, cy - hw)
            hi = min(self.ny, cy + hw)
            self.elements[element][lo:hi, :] += concentration
        else:
            cx = int(center_um / self.resolution_um)
            hw = int(width_um / self.resolution_um / 2)
            lo = max(0, cx - hw)
            hi = min(self.nx, cx + hw)
            self.elements[element][:, lo:hi] += concentration

    def add_circle(self, element: str, center_um: Tuple[float, float],
                   radius_um: float, concentration: float = 0.05):
        """Add a circular feature (e.g. particle)."""
        if element not in self.elements:
            self.elements[element] = np.zeros((self.ny, self.nx))

        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        cx = center_um[0] / self.resolution_um
        cy = center_um[1] / self.resolution_um
        r_px = radius_um / self.resolution_um
        mask = ((xx - cx)**2 + (yy - cy)**2) <= r_px**2
        self.elements[element][mask] += concentration

    def get_concentration(self, element: str, x_um: float, y_um: float) -> float:
        """Get element concentration at a position."""
        if element not in self.elements:
            return 0.0
        ix = int(x_um / self.resolution_um)
        iy = int(y_um / self.resolution_um)
        ix = max(0, min(ix, self.nx - 1))
        iy = max(0, min(iy, self.ny - 1))
        return float(self.elements[element][iy, ix])


class AreaDetector:
    """Simulated area detector for generating 2D images."""

    def __init__(self, nx: int = 256, ny: int = 256):
        self.nx = nx
        self.ny = ny

    def generate_xrf_map(self, sample: SampleMap, element: str,
                         scan_area: Tuple[float, float, float, float],
                         scan_points: Tuple[int, int],
                         energy_keV: float = 10.0,
                         dwell_time: float = 0.1) -> np.ndarray:
        """Generate a 2D XRF elemental map.

        Args:
            sample: SampleMap with elemental distributions
            element: element to map
            scan_area: (x_start, y_start, x_stop, y_stop) in um
            scan_points: (nx, ny) number of scan points
            energy_keV: excitation energy
            dwell_time: per-pixel dwell time

        Returns:
            2D array of shape (ny, nx) — XRF counts
        """
        x_start, y_start, x_stop, y_stop = scan_area
        nx_scan, ny_scan = scan_points

        x_pos = np.linspace(x_start, x_stop, nx_scan)
        y_pos = np.linspace(y_start, y_stop, ny_scan)

        xrf_map = np.zeros((ny_scan, nx_scan), dtype=np.float64)

        for iy, y in enumerate(y_pos):
            for ix, x in enumerate(x_pos):
                conc = sample.get_concentration(element, x, y)
                # Simplified: counts proportional to concentration
                mean_counts = conc * 1e6 * dwell_time
                xrf_map[iy, ix] = np.random.poisson(max(mean_counts, 0.1))

        return xrf_map.astype(np.int32)

    def generate_diffraction_frame(self, two_theta_deg: float = 20.0,
                                   n_rings: int = 5,
                                   noise_level: float = 10.0) -> np.ndarray:
        """Generate a simulated 2D diffraction pattern.

        Args:
            two_theta_deg: center 2-theta angle
            n_rings: number of Debye rings
            noise_level: background noise level

        Returns:
            2D array of shape (ny, nx) — detector counts
        """
        frame = np.random.poisson(noise_level, (self.ny, self.nx)).astype(np.float64)

        cy, cx = self.ny / 2, self.nx / 2
        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        r = np.sqrt((xx - cx)**2 + (yy - cy)**2)

        for i in range(n_rings):
            ring_r = (i + 1) * self.nx / (2 * n_rings)
            ring_width = 2.0
            intensity = 1000.0 / (i + 1)**0.5
            ring = intensity * np.exp(-0.5 * ((r - ring_r) / ring_width)**2)
            frame += ring

        frame = np.random.poisson(np.maximum(frame, 0)).astype(np.int32)
        return frame


def create_test_sample() -> SampleMap:
    """Create a test sample with various features for demo purposes."""
    sample = SampleMap(size_um=(100, 100), resolution_um=0.5)

    # Background matrix (Fe-rich)
    sample.add_uniform('Fe', 0.02)

    # Cu inclusion (circular particle)
    sample.add_circle('Cu', center_um=(30, 40), radius_um=8, concentration=0.08)
    sample.add_circle('Cu', center_um=(70, 60), radius_um=5, concentration=0.05)

    # Zn stripe (grain boundary)
    sample.add_stripe('Zn', direction='v', center_um=50, width_um=3, concentration=0.04)

    # Au nanoparticles (small Gaussian spots)
    for pos in [(20, 20), (50, 70), (80, 30), (40, 85)]:
        sample.add_gaussian_spot('Au', center_um=pos, sigma_um=2, peak_conc=0.03)

    # Ti coating (horizontal layer)
    sample.add_stripe('Ti', direction='h', center_um=10, width_um=5, concentration=0.06)

    return sample
