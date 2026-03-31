#!/usr/bin/env python3
"""XRF spectrum simulation for K4GSR BL10 NanoProbe.

Generates realistic X-ray fluorescence spectra with:
  - Element-specific emission lines (Ka, Kb, La, Lb)
  - Scatter peaks (elastic + Compton)
  - Detector response (Gaussian broadening, escape peaks, pile-up)
  - Background (bremsstrahlung + shelf)
  - Statistical noise (Poisson)

Usage:
    from xrf_sim import XRFSimulator
    sim = XRFSimulator(energy_keV=10.0)
    sim.add_element('Fe', concentration=0.05)
    sim.add_element('Cu', concentration=0.02)
    spectrum = sim.generate(dwell_time=1.0)
    # spectrum: np.array of shape (4096,) — counts per channel
"""

import numpy as np
import logging
from typing import Dict, List, Tuple, Optional

log = logging.getLogger("xrf-sim")

# ═══════════════════════════════════════════════════════════════════════
# XRF emission line database (energies in keV)
# ═══════════════════════════════════════════════════════════════════════
XRF_LINES = {
    'Ti': {'Ka': 4.511, 'Kb': 4.932},
    'V':  {'Ka': 4.952, 'Kb': 5.427},
    'Cr': {'Ka': 5.415, 'Kb': 5.947},
    'Mn': {'Ka': 5.899, 'Kb': 6.490},
    'Fe': {'Ka': 6.404, 'Kb': 7.058},
    'Co': {'Ka': 6.930, 'Kb': 7.649},
    'Ni': {'Ka': 7.478, 'Kb': 8.265},
    'Cu': {'Ka': 8.048, 'Kb': 8.905},
    'Zn': {'Ka': 8.639, 'Kb': 9.572},
    'As': {'Ka': 10.544, 'Kb': 11.726},
    'Se': {'Ka': 11.222, 'Kb': 12.496},
    'Br': {'Ka': 11.924, 'Kb': 13.292},
    'Sr': {'Ka': 14.165, 'Kb': 15.836},
    'Mo': {'Ka': 17.479, 'Kb': 19.608},
    'Ag': {'Ka': 22.163, 'Kb': 24.942},
    'Pt': {'La': 9.442, 'Lb': 11.072},
    'Au': {'La': 9.713, 'Lb': 11.443},
    'Pb': {'La': 10.551, 'Lb': 12.614},
}

# Relative intensity of Kb to Ka (or Lb to La)
KB_KA_RATIO = {
    'Ka': 1.0, 'Kb': 0.15,
    'La': 1.0, 'Lb': 0.5,
}


class XRFSimulator:
    """Simulate XRF spectra for a given excitation energy and sample composition."""

    def __init__(self, energy_keV: float = 10.0, n_channels: int = 4096,
                 ev_per_channel: float = 10.0, fwhm_eV: float = 130.0):
        """Initialize simulator.

        Args:
            energy_keV: incident X-ray energy
            n_channels: number of MCA channels
            ev_per_channel: energy per channel (eV)
            fwhm_eV: detector energy resolution at 5.9 keV (Mn Ka)
        """
        self.energy_keV = energy_keV
        self.n_channels = n_channels
        self.ev_per_channel = ev_per_channel
        self.fwhm_eV = fwhm_eV
        self.elements: Dict[str, float] = {}  # element → concentration (0-1)

        # Energy axis (keV)
        self.energy_axis = np.arange(n_channels) * ev_per_channel / 1000.0

    def add_element(self, symbol: str, concentration: float = 0.01):
        """Add an element to the sample.

        Args:
            symbol: element symbol (e.g. 'Fe', 'Cu')
            concentration: weight fraction (0-1)
        """
        if symbol not in XRF_LINES:
            log.warning(f"Unknown element: {symbol}")
            return
        self.elements[symbol] = concentration

    def clear_elements(self):
        """Remove all elements."""
        self.elements.clear()

    def _gaussian(self, center_keV: float, area: float) -> np.ndarray:
        """Generate a Gaussian peak.

        Resolution scales with sqrt(energy): FWHM(E) = FWHM_ref * sqrt(E/5.9)
        """
        fwhm_keV = self.fwhm_eV / 1000.0 * np.sqrt(center_keV / 5.9)
        sigma = fwhm_keV / 2.3548
        return area * np.exp(-0.5 * ((self.energy_axis - center_keV) / sigma) ** 2) / \
               (sigma * np.sqrt(2 * np.pi))

    def generate(self, dwell_time: float = 1.0, flux: float = 1e9,
                 include_scatter: bool = True,
                 include_background: bool = True) -> np.ndarray:
        """Generate a complete XRF spectrum.

        Args:
            dwell_time: measurement time in seconds
            flux: incident photon flux (photons/sec)
            include_scatter: add elastic + Compton scatter peaks
            include_background: add bremsstrahlung background

        Returns:
            np.array of shape (n_channels,) — integer counts per channel
        """
        spectrum = np.zeros(self.n_channels, dtype=np.float64)
        total_rate = flux * dwell_time

        # ── XRF emission lines ──
        for elem, conc in self.elements.items():
            lines = XRF_LINES.get(elem, {})
            for line_name, line_keV in lines.items():
                # Only emit if excitation energy > emission energy
                if line_keV >= self.energy_keV:
                    continue

                # Approximate fluorescence yield and cross-section
                base_rate = total_rate * conc * 0.001  # simplified
                rel_intensity = KB_KA_RATIO.get(line_name, 0.15)
                area = base_rate * rel_intensity

                if area > 0:
                    spectrum += self._gaussian(line_keV, area)

                    # Si escape peak (1.74 keV below main peak)
                    escape_keV = line_keV - 1.74
                    if escape_keV > 0:
                        spectrum += self._gaussian(escape_keV, area * 0.005)

        # ── Scatter peaks ──
        if include_scatter:
            # Elastic (Rayleigh) scatter
            elastic_rate = total_rate * 1e-5
            spectrum += self._gaussian(self.energy_keV, elastic_rate)

            # Compton scatter (shifted to lower energy)
            compton_shift = self.energy_keV ** 2 / (511 + self.energy_keV)
            compton_keV = self.energy_keV - compton_shift
            if compton_keV > 0:
                # Compton peak is broader
                fwhm_save = self.fwhm_eV
                self.fwhm_eV *= 3.0
                spectrum += self._gaussian(compton_keV, elastic_rate * 0.5)
                self.fwhm_eV = fwhm_save

        # ── Background ──
        if include_background:
            # Bremsstrahlung continuum (exponential decay)
            bkg_rate = total_rate * 1e-7
            bkg = bkg_rate * np.exp(-self.energy_axis / (self.energy_keV * 0.3))
            # Cut off above excitation energy
            bkg[self.energy_axis > self.energy_keV * 1.05] = 0
            spectrum += bkg

            # Low-energy shelf (from incomplete charge collection)
            shelf = np.cumsum(spectrum[::-1])[::-1] * 0.001
            spectrum += shelf

        # ── Poisson noise ──
        spectrum = np.maximum(spectrum, 0)
        spectrum = np.random.poisson(spectrum.astype(np.float64)).astype(np.int32)

        return spectrum

    def get_energy_axis(self) -> np.ndarray:
        """Return energy axis in keV."""
        return self.energy_axis.copy()

    def identify_peaks(self, spectrum: np.ndarray, threshold: float = 100
                       ) -> List[Dict]:
        """Simple peak identification in a spectrum.

        Args:
            spectrum: counts array
            threshold: minimum peak height

        Returns:
            List of {'element': str, 'line': str, 'energy_keV': float,
                     'channel': int, 'counts': int}
        """
        results = []
        for elem, lines in XRF_LINES.items():
            for line_name, line_keV in lines.items():
                if line_keV >= self.energy_keV:
                    continue
                ch = int(line_keV * 1000 / self.ev_per_channel)
                if 0 <= ch < self.n_channels:
                    # Check +-3 channels around expected position
                    lo = max(0, ch - 3)
                    hi = min(self.n_channels, ch + 4)
                    peak_counts = int(np.max(spectrum[lo:hi]))
                    if peak_counts >= threshold:
                        results.append({
                            'element': elem,
                            'line': line_name,
                            'energy_keV': line_keV,
                            'channel': ch,
                            'counts': peak_counts
                        })
        results.sort(key=lambda x: x['energy_keV'])
        return results
