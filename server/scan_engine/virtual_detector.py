#!/usr/bin/env python3
"""Virtual XRF detector for K4GSR BL10 NanoProbe Bluesky integration.

Simulates an XRF fluorescence detector that generates position-dependent
spectra during raster scans. Uses the data/ module (XRFSimulator, SampleMap)
to produce realistic element-specific count data.

Architecture:
    Bluesky RunEngine calls trigger() at each scan point:
        1. Read current sample SX/SY motor positions (via ophyd)
        2. Look up element concentrations at that position (SampleMap)
        3. Generate XRF spectrum (XRFSimulator)
        4. Extract per-element peak intensities
        5. Return values via read()

Usage:
    from virtual_detector import VirtualXRFDetector, create_test_sample
    from devices import create_devices

    devs = create_devices()
    sample = create_test_sample()
    vdet = VirtualXRFDetector('vxrf', name='vxrf',
                              sample_motors=(devs['sample'].sx, devs['sample'].sy),
                              sample_map=sample, energy_keV=10.0)

    # Use with raster_scan:
    RE(bp.grid_scan([vdet], sy, -10, 10, 21, sx, -10, 10, 21))
"""

import time
import logging
import numpy as np
from collections import OrderedDict
from typing import Optional, Tuple

from ophyd import Device, Signal, Component as Cpt
from ophyd.status import DeviceStatus

log = logging.getLogger("bl10-vdet")

# Import data simulation modules
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from data.xrf_sim import XRFSimulator, XRF_LINES
from data.detector import SampleMap, create_test_sample


class VirtualXRFDetector(Device):
    """Simulated XRF detector for Bluesky scans.

    Generates position-dependent XRF intensities by combining:
    - SampleMap: 2D element concentration distributions
    - XRFSimulator: realistic spectrum generation with Poisson noise

    Readable signals (updated on each trigger):
    - total_counts: total integrated XRF counts
    - fe_ka, cu_ka, zn_ka, au_la, ti_ka: per-element peak intensities
    """

    # Readable signals — updated on each trigger()
    total_counts = Cpt(Signal, value=0, kind='hinted')
    fe_ka = Cpt(Signal, value=0, kind='hinted')
    cu_ka = Cpt(Signal, value=0, kind='normal')
    zn_ka = Cpt(Signal, value=0, kind='normal')
    au_la = Cpt(Signal, value=0, kind='normal')
    ti_ka = Cpt(Signal, value=0, kind='normal')

    def __init__(self, *args, sample_motors=None, sample_map=None,
                 energy_keV=10.0, dwell_time=0.1, flux=1e9, **kwargs):
        """Initialize virtual XRF detector.

        Args:
            sample_motors: tuple (sx_motor, sy_motor) ophyd positioners
            sample_map: SampleMap instance with element distributions
            energy_keV: incident X-ray energy
            dwell_time: integration time per point (seconds)
            flux: incident photon flux (photons/sec)
        """
        super().__init__(*args, **kwargs)
        self._sample_motors = sample_motors
        self._sample_map = sample_map or create_test_sample()
        self._energy_keV = energy_keV
        self._dwell_time = dwell_time
        self._flux = flux
        self._xrf_sim = XRFSimulator(energy_keV=energy_keV)

        # Element → signal attribute mapping
        self._element_signals = {
            'Fe': self.fe_ka,
            'Cu': self.cu_ka,
            'Zn': self.zn_ka,
            'Au': self.au_la,
            'Ti': self.ti_ka,
        }

        # Full spectrum buffer (not sent via WebSocket, saved to HDF5)
        self._last_spectrum = None  # np.ndarray (4096,) after each trigger
        self._n_channels = 4096

    def trigger(self):
        """Trigger a single XRF measurement.

        Reads current motor positions, generates XRF spectrum,
        and updates all element signals.
        """
        status = DeviceStatus(self)

        try:
            # Get current sample position
            x_um, y_um = self._get_position()

            # Configure XRF simulator with position-dependent concentrations
            self._xrf_sim.clear_elements()
            for elem in self._sample_map.elements:
                conc = self._sample_map.get_concentration(elem, x_um, y_um)
                if conc > 0:
                    self._xrf_sim.add_element(elem, conc)

            # Generate spectrum
            spectrum = self._xrf_sim.generate(
                dwell_time=self._dwell_time,
                flux=self._flux
            )

            # Store full spectrum for HDF5 writing (not sent over WebSocket)
            self._last_spectrum = spectrum.copy()

            # Extract element peak intensities
            energy_axis = self._xrf_sim.get_energy_axis()
            total = int(np.sum(spectrum))
            self.total_counts.put(total)

            for elem, sig in self._element_signals.items():
                counts = self._extract_peak(spectrum, energy_axis, elem)
                sig.put(int(counts))

            status.set_finished()

        except Exception as e:
            log.error(f"VirtualXRF trigger error: {e}")
            status.set_exception(e)

        return status

    def _get_position(self) -> Tuple[float, float]:
        """Get current sample position from motors."""
        if self._sample_motors is not None:
            sx, sy = self._sample_motors
            try:
                x = sx.position if hasattr(sx, 'position') else sx.get()
                y = sy.position if hasattr(sy, 'position') else sy.get()
                if x is None or y is None:
                    return 50.0, 50.0
                # Convert motor units to sample map coordinates
                # Motor range typically ±50 um → map to 0-100 um
                map_w, map_h = self._sample_map.size_um
                x_um = x + map_w / 2.0
                y_um = y + map_h / 2.0
                return x_um, y_um
            except Exception:
                return 50.0, 50.0
        return 50.0, 50.0  # center of map

    def _extract_peak(self, spectrum, energy_axis, element: str) -> float:
        """Extract integrated counts around an element's primary peak."""
        if element not in XRF_LINES:
            return 0.0

        lines = XRF_LINES[element]
        # Use Ka or La (primary line)
        if 'Ka' in lines:
            peak_keV = lines['Ka']
        elif 'La' in lines:
            peak_keV = lines['La']
        else:
            return 0.0

        # Integration window: ±3 sigma around peak
        fwhm_keV = self._xrf_sim.fwhm_eV / 1000.0
        sigma_keV = fwhm_keV / 2.355
        window = 3.0 * sigma_keV

        mask = (energy_axis >= peak_keV - window) & (energy_axis <= peak_keV + window)
        return float(np.sum(spectrum[mask]))

    @property
    def energy_keV(self):
        return self._energy_keV

    @energy_keV.setter
    def energy_keV(self, value):
        self._energy_keV = value
        self._xrf_sim = XRFSimulator(energy_keV=value)
