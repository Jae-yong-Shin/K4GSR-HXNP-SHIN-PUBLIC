"""Detector models for K4GSR simulation engines.

SDD (Silicon Drift Detector) -- for XRF
EIGER2 (area detector) -- for XRD
"""

import math
import numpy as np


# ===================================================================
# SDD Detector Model (Rayspec 3-channel)
# Matches JS SDD_SPEC in 01_xray_data.js
# ===================================================================

SDD_SPEC = {
    "nChannels": 3,
    "activeArea_mm2": 50,         # per channel
    "thickness_mm": 0.45,         # Si active thickness
    "beWindow_um": 12.5,          # Be entrance window
    "fwhm_MnKa_eV": 130,         # FWHM at Mn Ka (5.9 keV)
    "distance_mm": 25,            # sample-to-detector distance
    "takeoff_deg": 45,            # angle from sample surface
    "maxCountRate_cps": 1e6,      # per channel
}

# Fano factor for Si
SI_FANO_FACTOR = 0.115
SI_PAIR_ENERGY_eV = 3.62         # energy to create electron-hole pair
SI_ESCAPE_ENERGY_eV = 1740       # Si Ka escape peak energy


def sdd_fwhm(energy_eV, fwhm_noise_eV=80.0):
    """Energy-dependent FWHM of SDD (Gaussian model).

    FWHM(E) = sqrt(noise^2 + 5.545 * F * eps * E)
    where F=Fano factor, eps=pair creation energy.
    """
    return math.sqrt(
        fwhm_noise_eV ** 2
        + 5.545 * SI_FANO_FACTOR * SI_PAIR_ENERGY_eV * energy_eV
    )


def sdd_efficiency(energy_eV, be_window_um=12.5, si_thickness_mm=0.45):
    """Detection efficiency of SDD (Be window transmission * Si absorption).

    Args:
        energy_eV: photon energy in eV
        be_window_um: Be entrance window thickness in um
        si_thickness_mm: Si active layer thickness in mm

    Returns:
        efficiency (0.0 to 1.0)
    """
    energy_keV = energy_eV / 1000.0
    if energy_keV <= 0:
        return 0.0

    # Be window transmission (approximate mu/rho for Be)
    # mu/rho ~ 1.5 * (1/E)^2.8 cm2/g for Be at low energy
    be_density = 1.848  # g/cm3
    be_thickness_cm = be_window_um * 1e-4
    mu_be = 1.5 * (1.0 / energy_keV) ** 2.8  # rough approximation
    t_be = math.exp(-mu_be * be_density * be_thickness_cm)

    # Si absorption (detector active layer)
    si_density = 2.33  # g/cm3
    si_thickness_cm = si_thickness_mm * 0.1
    # mu/rho for Si: ~ 50 * (1/E)^2.7 below K-edge (1839 eV)
    if energy_eV < 1839:
        mu_si = 100.0 * (1.0 / energy_keV) ** 3.0
    else:
        mu_si = 50.0 * (1.0 / energy_keV) ** 2.7

    a_si = 1.0 - math.exp(-mu_si * si_density * si_thickness_cm)

    return max(0.0, min(1.0, t_be * a_si))


def sdd_solid_angle(n_channels=3, area_mm2=50, distance_mm=25):
    """Solid angle subtended by SDD (sr).

    Omega = n * A / (4 * pi * d^2)  (simplified for small detectors)
    """
    area_cm2 = area_mm2 * 1e-2  # mm2 -> cm2
    dist_cm = distance_mm * 0.1
    return n_channels * area_cm2 / (4 * math.pi * dist_cm ** 2)


def sdd_escape_fraction(energy_eV):
    """Si escape peak fraction (approximate).

    Only significant above Si K-edge (1839 eV).
    Escape peak appears at E - 1.74 keV.
    """
    if energy_eV < 2500:
        return 0.0
    # Approximate: 0.5% at 3 keV, 2% at 6 keV, decreasing above 10 keV
    e_keV = energy_eV / 1000.0
    if e_keV < 6:
        return 0.005 + 0.005 * (e_keV - 2.5) / 3.5
    else:
        return 0.02 * math.exp(-0.1 * (e_keV - 6))


def generate_sdd_spectrum(line_counts, energy_range_eV=(0, 20480),
                          n_channels=2048, e_per_channel=10,
                          fwhm_noise_eV=80.0,
                          compton_energy_eV=None, rayleigh_energy_eV=None,
                          compton_counts=0, rayleigh_counts=0,
                          background_level=0.5):
    """Generate a full SDD spectrum from fluorescence line counts.

    Args:
        line_counts: list of (energy_eV, counts) for each fluorescence line
        energy_range_eV: (min, max) energy range
        n_channels: number of spectrum channels
        e_per_channel: eV per channel
        fwhm_noise_eV: electronic noise contribution to FWHM
        compton_energy_eV: Compton scatter peak energy
        rayleigh_energy_eV: elastic scatter peak energy
        compton_counts: Compton scatter peak counts
        rayleigh_counts: elastic scatter peak counts
        background_level: continuum background amplitude

    Returns:
        channels: np.ndarray of shape (n_channels,) -- counts per channel
    """
    channels = np.zeros(n_channels, dtype=np.float64)
    energies = np.arange(n_channels) * e_per_channel + energy_range_eV[0]

    # Add fluorescence lines as Gaussians
    for line_E, counts in line_counts:
        if counts <= 0 or line_E <= 0:
            continue
        fwhm = sdd_fwhm(line_E, fwhm_noise_eV)
        sigma = fwhm / 2.3548
        ch_center = (line_E - energy_range_eV[0]) / e_per_channel
        # Only compute within +/- 5 sigma
        ch_lo = max(0, int(ch_center - 5 * sigma / e_per_channel))
        ch_hi = min(n_channels, int(ch_center + 5 * sigma / e_per_channel) + 1)
        if ch_lo >= ch_hi:
            continue
        e_slice = energies[ch_lo:ch_hi]
        gauss = counts * np.exp(-0.5 * ((e_slice - line_E) / sigma) ** 2)
        channels[ch_lo:ch_hi] += gauss

        # Si escape peak
        escape_frac = sdd_escape_fraction(line_E)
        if escape_frac > 0:
            escape_E = line_E - SI_ESCAPE_ENERGY_eV
            if escape_E > energy_range_eV[0]:
                esc_sigma = sdd_fwhm(escape_E, fwhm_noise_eV) / 2.3548
                esc_center = (escape_E - energy_range_eV[0]) / e_per_channel
                ech_lo = max(0, int(esc_center - 4 * esc_sigma / e_per_channel))
                ech_hi = min(n_channels,
                             int(esc_center + 4 * esc_sigma / e_per_channel) + 1)
                if ech_lo < ech_hi:
                    e_esc = energies[ech_lo:ech_hi]
                    esc_gauss = (counts * escape_frac
                                 * np.exp(-0.5 * ((e_esc - escape_E)
                                                   / esc_sigma) ** 2))
                    channels[ech_lo:ech_hi] += esc_gauss

    # Add Compton scatter peak
    if compton_energy_eV and compton_counts > 0:
        fwhm_c = sdd_fwhm(compton_energy_eV, fwhm_noise_eV) * 2.5  # broader
        sigma_c = fwhm_c / 2.3548
        ch_c = (compton_energy_eV - energy_range_eV[0]) / e_per_channel
        ch_lo = max(0, int(ch_c - 5 * sigma_c / e_per_channel))
        ch_hi = min(n_channels, int(ch_c + 5 * sigma_c / e_per_channel) + 1)
        if ch_lo < ch_hi:
            e_slice = energies[ch_lo:ch_hi]
            channels[ch_lo:ch_hi] += compton_counts * np.exp(
                -0.5 * ((e_slice - compton_energy_eV) / sigma_c) ** 2)

    # Add Rayleigh (elastic) scatter peak
    if rayleigh_energy_eV and rayleigh_counts > 0:
        fwhm_r = sdd_fwhm(rayleigh_energy_eV, fwhm_noise_eV)
        sigma_r = fwhm_r / 2.3548
        ch_r = (rayleigh_energy_eV - energy_range_eV[0]) / e_per_channel
        ch_lo = max(0, int(ch_r - 5 * sigma_r / e_per_channel))
        ch_hi = min(n_channels, int(ch_r + 5 * sigma_r / e_per_channel) + 1)
        if ch_lo < ch_hi:
            e_slice = energies[ch_lo:ch_hi]
            channels[ch_lo:ch_hi] += rayleigh_counts * np.exp(
                -0.5 * ((e_slice - rayleigh_energy_eV) / sigma_r) ** 2)

    # Add bremsstrahlung continuum background
    if background_level > 0:
        # Kramers' law: I(E) ~ (E0 - E) / E
        E0 = rayleigh_energy_eV if rayleigh_energy_eV else 10000
        for i in range(n_channels):
            e = energies[i]
            if 0 < e < E0:
                channels[i] += background_level * (E0 - e) / e

    return channels


# ===================================================================
# EIGER2 Area Detector Model
# Matches JS EIGER_DETECTORS in 04_xrd2d_sim.js
# ===================================================================

EIGER_DETECTORS = {
    "EIGER2_1M": {
        "pixelsH": 1028,
        "pixelsV": 1062,
        "pixelSize_m": 75e-6,
        "nModulesH": 1,
        "nModulesV": 2,
        "modulePixelsH": 514,
        "modulePixelsV": 514,
        "gapH": 0,             # no horizontal gap for 1M
        "gapV": 34,            # 34 pixel vertical gap
        "activeAreaH_m": 0.07710,
        "activeAreaV_m": 0.07965,
        "siThickness_um": 450,
        "maxFrameRate_Hz": 2000,
    },
    "EIGER2_4M": {
        "pixelsH": 2068,
        "pixelsV": 2162,
        "pixelSize_m": 75e-6,
        "nModulesH": 2,
        "nModulesV": 4,
        "modulePixelsH": 514,
        "modulePixelsV": 514,
        "gapH": 12,            # 12 pixel horizontal gap
        "gapV": 37,            # 37 pixel vertical gap
        "activeAreaH_m": 0.15510,
        "activeAreaV_m": 0.16215,
        "siThickness_um": 450,
        "maxFrameRate_Hz": 500,
    },
}


def eiger_gap_mask(detector_key="EIGER2_1M"):
    """Generate module gap mask for EIGER detector.

    Returns:
        mask: np.ndarray of shape (pixelsV, pixelsH), dtype bool.
              True = active pixel, False = gap.
    """
    det = EIGER_DETECTORS.get(detector_key, EIGER_DETECTORS["EIGER2_1M"])
    nH = det["pixelsH"]
    nV = det["pixelsV"]
    mask = np.ones((nV, nH), dtype=bool)

    modH = det["modulePixelsH"]
    modV = det["modulePixelsV"]
    gapH = det["gapH"]
    gapV = det["gapV"]
    nMH = det["nModulesH"]
    nMV = det["nModulesV"]

    # Vertical gaps
    if gapV > 0 and nMV > 1:
        for m in range(1, nMV):
            y_start = m * modV + (m - 1) * gapV
            y_end = min(y_start + gapV, nV)
            mask[y_start:y_end, :] = False

    # Horizontal gaps
    if gapH > 0 and nMH > 1:
        for m in range(1, nMH):
            x_start = m * modH + (m - 1) * gapH
            x_end = min(x_start + gapH, nH)
            mask[:, x_start:x_end] = False

    return mask
