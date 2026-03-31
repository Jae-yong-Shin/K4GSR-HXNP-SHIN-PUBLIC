"""XRD 2D Simulation Engine using pymatgen XRDCalculator + pyFAI-style geometry.

Produces realistic 2D powder XRD patterns on EIGER2 detectors with:
  - pymatgen: accurate structure factor calculation and peak positions
  - Pseudo-Voigt ring profiles (eta * Lorentzian + (1-eta) * Gaussian)
  - Azimuthal grain texture (polycrystalline spottiness)
  - Poisson noise, air-scatter background, beam stop mask
  - EIGER module gap mask

This replaces the older experiment_engine.XRD2DEngine (Dans_Diffraction-based).
"""

import asyncio
import base64
import logging
import math
import time

import numpy as np

from sim_engines.base import SimEngine
from sim_engines.detectors import EIGER_DETECTORS, eiger_gap_mask

log = logging.getLogger("xrd-engine")

# ---------------------------------------------------------------------------
# Optional library imports
# ---------------------------------------------------------------------------
_PYMATGEN_OK = False
_PYFAI_OK = False

try:
    from pymatgen.core import Lattice, Structure
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    _PYMATGEN_OK = True
    log.info("pymatgen loaded OK")
except ImportError:
    log.warning("pymatgen not available -- XRD engine disabled")

try:
    import pyFAI
    _PYFAI_OK = True
    log.info("pyFAI loaded OK")
except ImportError:
    log.debug("pyFAI not available (optional, geometry fallback used)")


# ===================================================================
# Crystal database  (matches JS CRYSTALS in 01_xray_data.js
#                    and CRYSTAL_DB in experiment_engine.py)
# ===================================================================
# Each entry stores lattice parameters, space group number, and
# fractional atomic positions so we can build pymatgen Structure objects.
#
# Cubic:       a only (b=c=a, alpha=beta=gamma=90)
# Tetragonal:  a, c  (b=a, alpha=beta=gamma=90)
# Hexagonal:   a, c  (b=a, alpha=beta=90, gamma=120)
# Monoclinic:  a, b, c, beta  (alpha=gamma=90)
# ---------------------------------------------------------------------------

_CRYSTAL_DB = {
    "Cu": {
        "name": "Copper", "system": "cubic", "sg": 225,
        "a": 3.6149,
        "species": ["Cu"], "coords": [[0, 0, 0]],
    },
    "Fe": {
        "name": "Iron (bcc)", "system": "cubic", "sg": 229,
        "a": 2.8665,
        "species": ["Fe"], "coords": [[0, 0, 0]],
    },
    "Ni": {
        "name": "Nickel", "system": "cubic", "sg": 225,
        "a": 3.5238,
        "species": ["Ni"], "coords": [[0, 0, 0]],
    },
    "Si": {
        "name": "Silicon", "system": "cubic", "sg": 227,
        "a": 5.4310,
        "species": ["Si", "Si"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "Au": {
        "name": "Gold", "system": "cubic", "sg": 225,
        "a": 4.0782,
        "species": ["Au"], "coords": [[0, 0, 0]],
    },
    "Pt": {
        "name": "Platinum", "system": "cubic", "sg": 225,
        "a": 3.9242,
        "species": ["Pt"], "coords": [[0, 0, 0]],
    },
    "Al": {
        "name": "Aluminum", "system": "cubic", "sg": 225,
        "a": 4.0495,
        "species": ["Al"], "coords": [[0, 0, 0]],
    },
    "Ag": {
        "name": "Silver", "system": "cubic", "sg": 225,
        "a": 4.0862,
        "species": ["Ag"], "coords": [[0, 0, 0]],
    },
    "Ge": {
        "name": "Germanium", "system": "cubic", "sg": 227,
        "a": 5.6575,
        "species": ["Ge", "Ge"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "NaCl": {
        "name": "Sodium Chloride", "system": "cubic", "sg": 225,
        "a": 5.6402,
        "species": ["Na", "Cl"], "coords": [[0, 0, 0], [0.5, 0.5, 0.5]],
    },
    "CeO2": {
        "name": "Ceria", "system": "cubic", "sg": 225,
        "a": 5.4113,
        "species": ["Ce", "O"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "SrTiO3": {
        "name": "Strontium Titanate", "system": "cubic", "sg": 221,
        "a": 3.9050,
        "species": ["Sr", "Ti", "O", "O", "O"],
        "coords": [[0.5, 0.5, 0.5], [0, 0, 0],
                    [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
    },
    "LaB6": {
        "name": "Lanthanum Hexaboride", "system": "cubic", "sg": 221,
        "a": 4.1569,
        "species": ["La", "B", "B", "B", "B", "B", "B"],
        "coords": [[0, 0, 0],
                    [0.1997, 0.5, 0.5], [0.5, 0.1997, 0.5],
                    [0.5, 0.5, 0.1997], [0.8003, 0.5, 0.5],
                    [0.5, 0.8003, 0.5], [0.5, 0.5, 0.8003]],
    },
    "Cu2O": {
        "name": "Cuprite", "system": "cubic", "sg": 224,
        "a": 4.2696,
        "species": ["Cu", "Cu", "Cu", "Cu", "O", "O"],
        "coords": [[0.25, 0.25, 0.25], [0.75, 0.75, 0.25],
                    [0.75, 0.25, 0.75], [0.25, 0.75, 0.75],
                    [0, 0, 0], [0.5, 0.5, 0.5]],
    },
    "CuO": {
        "name": "Tenorite", "system": "monoclinic", "sg": 15,
        "a": 4.6837, "b": 3.4226, "c": 5.1288, "beta": 99.54,
        "species": ["Cu", "O"],
        "coords": [[0.25, 0.25, 0], [0, 0.4184, 0.25]],
    },
    "Fe2O3": {
        "name": "Hematite", "system": "hexagonal", "sg": 167,
        "a": 5.0356, "c": 13.7489,
        "species": ["Fe", "O"],
        "coords": [[0, 0, 0.35530], [0.3059, 0, 0.25]],
    },
    "Fe3O4": {
        "name": "Magnetite", "system": "cubic", "sg": 227,
        "a": 8.3969,
        "species": ["Fe", "Fe", "O"],
        "coords": [[0.125, 0.125, 0.125], [0.5, 0.5, 0.5],
                    [0.2549, 0.2549, 0.2549]],
    },
    "NiO": {
        "name": "Bunsenite", "system": "cubic", "sg": 225,
        "a": 4.1771,
        "species": ["Ni", "O"],
        "coords": [[0, 0, 0], [0.5, 0.5, 0.5]],
    },
    "TiO2": {
        "name": "Rutile", "system": "tetragonal", "sg": 136,
        "a": 4.5941, "c": 2.9589,
        "species": ["Ti", "O"],
        "coords": [[0, 0, 0], [0.3049, 0.3049, 0]],
    },
    "Al2O3": {
        "name": "Corundum", "system": "hexagonal", "sg": 167,
        "a": 4.7589, "c": 12.9910,
        "species": ["Al", "O"],
        "coords": [[0, 0, 0.3520], [0.3064, 0, 0.25]],
    },
    "ZnO": {
        "name": "Wurtzite", "system": "hexagonal", "sg": 186,
        "a": 3.2498, "c": 5.2066,
        "species": ["Zn", "O"],
        "coords": [[0.3333, 0.6667, 0], [0.3333, 0.6667, 0.3819]],
    },
    # --- Additional common crystals ---
    "GaAs": {
        "name": "Gallium Arsenide", "system": "cubic", "sg": 216,
        "a": 5.6533,
        "species": ["Ga", "As"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "InP": {
        "name": "Indium Phosphide", "system": "cubic", "sg": 216,
        "a": 5.8687,
        "species": ["In", "P"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "GaN": {
        "name": "Gallium Nitride", "system": "hexagonal", "sg": 186,
        "a": 3.1890, "c": 5.1855,
        "species": ["Ga", "N"],
        "coords": [[0.3333, 0.6667, 0], [0.3333, 0.6667, 0.3750]],
    },
    "BaTiO3": {
        "name": "Barium Titanate", "system": "cubic", "sg": 221,
        "a": 4.0094,
        "species": ["Ba", "Ti", "O", "O", "O"],
        "coords": [[0.5, 0.5, 0.5], [0, 0, 0],
                    [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
    },
    "LiCoO2": {
        "name": "Lithium Cobalt Oxide", "system": "hexagonal", "sg": 166,
        "a": 2.8160, "c": 14.0540,
        "species": ["Li", "Co", "O"],
        "coords": [[0, 0, 0.5], [0, 0, 0], [0, 0, 0.2605]],
    },
    "LiFePO4": {
        "name": "Lithium Iron Phosphate", "system": "monoclinic", "sg": 62,
        "a": 10.3290, "b": 6.0100, "c": 4.6920, "beta": 90.0,
        "species": ["Li", "Fe", "P", "O"],
        "coords": [[0, 0, 0], [0.2822, 0.25, 0.9748],
                    [0.0948, 0.25, 0.4181], [0.0966, 0.25, 0.7429]],
    },
    "MoS2": {
        "name": "Molybdenite", "system": "hexagonal", "sg": 194,
        "a": 3.1600, "c": 12.2940,
        "species": ["Mo", "S"],
        "coords": [[0.3333, 0.6667, 0.25], [0.3333, 0.6667, 0.621]],
    },
    "WC": {
        "name": "Tungsten Carbide", "system": "hexagonal", "sg": 187,
        "a": 2.9060, "c": 2.8370,
        "species": ["W", "C"],
        "coords": [[0, 0, 0], [0.3333, 0.6667, 0.5]],
    },
    "Diamond": {
        "name": "Diamond", "system": "cubic", "sg": 227,
        "a": 3.5668,
        "species": ["C", "C"], "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
    "W": {
        "name": "Tungsten", "system": "cubic", "sg": 229,
        "a": 3.1652,
        "species": ["W"], "coords": [[0, 0, 0]],
    },
    "Ti": {
        "name": "Titanium", "system": "hexagonal", "sg": 194,
        "a": 2.9508, "c": 4.6855,
        "species": ["Ti"],
        "coords": [[0.3333, 0.6667, 0.25]],
    },
    "Cr": {
        "name": "Chromium", "system": "cubic", "sg": 229,
        "a": 2.8839,
        "species": ["Cr"], "coords": [[0, 0, 0]],
    },
    "Co": {
        "name": "Cobalt", "system": "hexagonal", "sg": 194,
        "a": 2.5071, "c": 4.0695,
        "species": ["Co"],
        "coords": [[0.3333, 0.6667, 0.25]],
    },
    "Mn": {
        "name": "Manganese", "system": "cubic", "sg": 217,
        "a": 8.9125,
        "species": ["Mn", "Mn"],
        "coords": [[0.3170, 0.3170, 0.3170], [0.3564, 0.3564, 0.0414]],
    },
    "PbTiO3": {
        "name": "Lead Titanate", "system": "tetragonal", "sg": 99,
        "a": 3.9042, "c": 4.1525,
        "species": ["Pb", "Ti", "O", "O", "O"],
        "coords": [[0, 0, 0], [0.5, 0.5, 0.5381],
                    [0.5, 0.5, 0.1118], [0.5, 0, 0.6174], [0, 0.5, 0.6174]],
    },
    "VO2": {
        "name": "Vanadium Dioxide (Rutile)", "system": "tetragonal", "sg": 136,
        "a": 4.5546, "c": 2.8514,
        "species": ["V", "O"],
        "coords": [[0, 0, 0], [0.3001, 0.3001, 0]],
    },
    "MgO": {
        "name": "Periclase", "system": "cubic", "sg": 225,
        "a": 4.2112,
        "species": ["Mg", "O"],
        "coords": [[0, 0, 0], [0.5, 0.5, 0.5]],
    },
    "CaF2": {
        "name": "Fluorite", "system": "cubic", "sg": 225,
        "a": 5.4626,
        "species": ["Ca", "F"],
        "coords": [[0, 0, 0], [0.25, 0.25, 0.25]],
    },
}


def get_crystal_keys():
    """Return list of available crystal keys."""
    return list(_CRYSTAL_DB.keys())


def get_structure(key):
    """Build a pymatgen Structure from the crystal database.

    Args:
        key: Crystal key (e.g. 'Cu', 'NaCl', 'Fe2O3')

    Returns:
        pymatgen.core.Structure or None if key not found / pymatgen unavailable
    """
    if not _PYMATGEN_OK:
        return None

    info = _CRYSTAL_DB.get(key)
    if info is None:
        return None

    system = info.get("system", "cubic")
    a = info["a"]
    b = info.get("b", a)
    c = info.get("c", a)
    alpha = 90.0
    beta_deg = info.get("beta", 90.0)
    gamma = 90.0

    if system == "hexagonal":
        gamma = 120.0
    elif system == "monoclinic":
        pass  # beta already set from info
    # cubic and tetragonal: all angles 90

    lattice = Lattice.from_parameters(a, b, c, alpha, beta_deg, gamma)

    structure = Structure.from_spacegroup(
        info["sg"], lattice,
        info["species"], info["coords"]
    )
    return structure


# ===================================================================
# 2D ring pattern generation helpers
# ===================================================================

def _pseudo_voigt(x, x0, fwhm, eta=0.5):
    """Pseudo-Voigt profile: eta * Lorentz + (1-eta) * Gauss.

    Vectorised -- x can be ndarray, x0 and fwhm are scalars.

    Args:
        x:    angle array (degrees)
        x0:   peak center (degrees)
        fwhm: full width at half max (degrees)
        eta:  mixing parameter 0..1 (0=pure Gauss, 1=pure Lorentz)

    Returns:
        profile values (same shape as x)
    """
    sigma = fwhm / 2.3548200  # FWHM -> sigma for Gaussian
    gamma = fwhm / 2.0        # FWHM -> half-width for Lorentzian

    dx = x - x0
    gauss = np.exp(-0.5 * (dx / sigma) * (dx / sigma))
    lorentz = 1.0 / (1.0 + (dx / gamma) * (dx / gamma))

    return eta * lorentz + (1.0 - eta) * gauss


def _generate_2d_pattern(peaks, energy_keV, det_dist, det_key,
                         beamstop_radius_mm=2.0, background_level=5.0,
                         eta_pv=0.4, grain_count_range=(60, 200),
                         flux=1e10):
    """Generate a 2D Debye-Scherrer ring pattern on an EIGER detector.

    All operations are numpy-vectorised (no pixel-by-pixel loops).

    Args:
        peaks: list of dicts with keys 'twoTheta', 'intensity', 'hkl'
        energy_keV: X-ray energy
        det_dist: sample-to-detector distance (m)
        det_key: EIGER detector model key
        beamstop_radius_mm: beam stop radius in mm
        background_level: mean background counts
        eta_pv: Pseudo-Voigt mixing parameter
        grain_count_range: (min, max) grains for azimuthal texture
        flux: photon flux (ph/s) -- scales ring intensity and Poisson noise

    Returns:
        image: np.ndarray float32 (nV, nH)
        ring_annotations: list of dicts with 'R' (px) added
    """
    det = EIGER_DETECTORS.get(det_key, EIGER_DETECTORS["EIGER2_1M"])
    nH = det["pixelsH"]
    nV = det["pixelsV"]
    pixel_size = det["pixelSize_m"]  # metres

    cx = nH / 2.0
    cy = nV / 2.0

    # Pre-compute radial distance map and 2theta map (vectorised)
    yy, xx = np.mgrid[0:nV, 0:nH]
    dx_m = (xx - cx) * pixel_size
    dy_m = (yy - cy) * pixel_size
    r_m = np.sqrt(dx_m * dx_m + dy_m * dy_m)

    # 2theta in degrees for every pixel
    two_theta_map = np.degrees(np.arctan2(r_m, det_dist))

    # Azimuthal angle for grain texture
    theta_az = np.arctan2(dy_m, dx_m)  # -pi to pi

    # Accumulate ring contributions
    image = np.zeros((nV, nH), dtype=np.float64)

    ring_annotations = []
    rng = np.random.RandomState(42)

    for pk in peaks:
        tth_deg = pk["twoTheta"]
        intensity = pk["intensity"]
        hkl_str = pk.get("hkl", "")

        if tth_deg <= 0 or intensity <= 0:
            continue

        # Ring radius in pixels
        tth_rad = math.radians(tth_deg)
        R_m = det_dist * math.tan(tth_rad)
        R_px = R_m / pixel_size

        # Adaptive FWHM: instrumental + size broadening
        # Wider rings at higher 2theta (Caglioti formula approximation)
        U, V, W = 0.01, -0.005, 0.003
        tan_th = math.tan(tth_rad / 2.0)
        fwhm_deg = max(0.05, math.sqrt(
            abs(U * tan_th * tan_th + V * tan_th + W)
        ))

        # Only compute within a band of 8*FWHM around the ring
        band_deg = 8.0 * fwhm_deg

        # Skip rings that are entirely outside detector field
        max_det_r_px = math.sqrt(cx * cx + cy * cy)
        # Convert band to pixels: how far from ring center (in px)
        if tth_deg + band_deg < 90:
            band_r_px = det_dist * math.tan(math.radians(tth_deg + band_deg)) / pixel_size - R_px
        else:
            band_r_px = max_det_r_px  # ring extends beyond 90 deg
        if R_px - abs(band_r_px) > max_det_r_px:
            continue
        mask = np.abs(two_theta_map - tth_deg) < band_deg
        if not mask.any():
            continue

        # Pseudo-Voigt radial profile (only within band)
        profile = np.zeros((nV, nH), dtype=np.float64)
        profile[mask] = intensity * _pseudo_voigt(
            two_theta_map[mask], tth_deg, fwhm_deg, eta=eta_pv
        )

        # Azimuthal grain texture (polycrystalline spottiness)
        n_grains = rng.randint(grain_count_range[0], grain_count_range[1])
        grain_phases = rng.uniform(-math.pi, math.pi, n_grains)
        grain_widths = rng.uniform(0.03, 0.08, n_grains)
        grain_amps = rng.uniform(0.1, 0.5, n_grains)

        # Vectorised azimuthal modulation
        az_mod = np.ones((nV, nH), dtype=np.float64)
        theta_flat = theta_az[mask]
        az_flat = np.ones(theta_flat.shape[0], dtype=np.float64)
        for gi in range(n_grains):
            d = theta_flat - grain_phases[gi]
            # Wrap to [-pi, pi]
            d = d - 2.0 * math.pi * np.round(d / (2.0 * math.pi))
            az_flat += grain_amps[gi] * np.exp(
                -0.5 * (d / grain_widths[gi]) * (d / grain_widths[gi])
            )
        az_mod[mask] = az_flat

        image += profile * az_mod

        ring_annotations.append({
            "R": float(R_px),
            "I": float(intensity),
            "fwhm": float(fwhm_deg),
            "hkl": hkl_str,
            "twoTheta": float(tth_deg),
        })

    # --- Scale intensity by flux ---
    # pymatgen gives relative intensity 0-100; convert to photon counts
    # Reference: 1e10 ph/s -> peak intensity ~1000 counts (typical 1s exposure)
    flux_scale = max(flux, 1.0) / 1e10 * 10.0  # 10 counts per unit intensity at 1e10
    image *= flux_scale

    # --- Background: uniform + radial air-scatter falloff ---
    # Air scatter: approximately 1/r^2 falloff from beam center
    bg_scaled = background_level * flux_scale
    r_px = r_m / pixel_size
    r_safe = np.maximum(r_px, 1.0)
    air_scatter = bg_scaled * 50.0 / (r_safe + 50.0)
    image += bg_scaled + air_scatter

    # --- Beam stop mask (set to 0) ---
    beamstop_r_px = (beamstop_radius_mm * 1e-3) / pixel_size
    beamstop_mask = r_px < beamstop_r_px
    image[beamstop_mask] = 0.0

    # --- Module gap mask ---
    gap_mask = eiger_gap_mask(det_key)

    # --- Poisson noise (only on active pixels) ---
    image_pos = np.maximum(image, 0.0)
    image = rng.poisson(image_pos.astype(np.float64)).astype(np.float32)

    # Re-apply masks after noise
    image[beamstop_mask] = 0.0
    # Gap pixels: -1 to match JS convention (renderXRD2D checks val<0 for gaps)
    image[~gap_mask] = -1.0

    return image, ring_annotations


# ===================================================================
# XRD Engine class
# ===================================================================

class XRDEngine(SimEngine):
    """2D powder XRD engine using pymatgen XRDCalculator + EIGER geometry."""

    @staticmethod
    def available():
        """True if pymatgen is importable (pyFAI is optional)."""
        return _PYMATGEN_OK

    @staticmethod
    def name():
        return "xrd2d"

    async def run(self, ws, params, beamline):
        """Simulate 2D XRD pattern and send via websocket.

        Args:
            ws: websocket connection
            params: {crystal, detDist, detector}
            beamline: {energy_keV, spot_h_nm, spot_v_nm, flux, ssaH, ssaV}
        """
        t0 = time.time()
        self.reset()

        # ── Parse parameters ──
        crystal_key = params.get("crystal", "Cu")
        det_dist = float(params.get("detDist", 0.3))
        det_key = params.get("detector", "EIGER2_1M")
        energy_keV = float(beamline.get("energy_keV", 10.0))
        flux = float(beamline.get("flux", 1e10))
        lambda_A = 12.3984 / energy_keV  # wavelength in Angstroms

        await self.send_progress(ws, 0.05,
            "2D-XRD: building crystal structure '%s' ..." % crystal_key)

        # ── Build crystal structure ──
        structure = get_structure(crystal_key)
        if structure is None:
            await self.send_error(ws,
                "Unknown crystal '%s'. Available: %s" % (
                    crystal_key, ", ".join(get_crystal_keys())))
            return

        if self._cancelled:
            return

        # ── Calculate diffraction pattern with pymatgen ──
        await self.send_progress(ws, 0.15,
            "2D-XRD: computing diffraction pattern (E=%.1f keV, lambda=%.4f A) ..."
            % (energy_keV, lambda_A))

        try:
            calculator = XRDCalculator(wavelength=lambda_A)
            pattern = calculator.get_pattern(structure, two_theta_range=(0, 90))
        except Exception as exc:
            await self.send_error(ws,
                "pymatgen XRD calculation failed: %s" % str(exc))
            return

        if self._cancelled:
            return

        # ── Extract peaks ──
        peaks = []
        for i in range(len(pattern.x)):
            tth = float(pattern.x[i])
            intensity = float(pattern.y[i])
            # Get hkl label from pattern
            hkl_list = pattern.hkls[i]
            if hkl_list:
                # hkls is list of dicts, take first one
                hkl_tuple = hkl_list[0].get("hkl", None)
                if hkl_tuple is not None:
                    hkl_str = "".join(str(int(h)) for h in hkl_tuple)
                else:
                    hkl_str = ""
            else:
                hkl_str = ""

            if intensity > 0.5:  # Skip very weak peaks
                peaks.append({
                    "twoTheta": tth,
                    "intensity": intensity,
                    "hkl": hkl_str,
                })

        if not peaks:
            await self.send_error(ws,
                "No diffraction peaks found for '%s' at %.1f keV" % (
                    crystal_key, energy_keV))
            return

        log.info("XRD peaks: %d peaks for %s (E=%.1f keV)",
                 len(peaks), crystal_key, energy_keV)

        await self.send_progress(ws, 0.30,
            "2D-XRD: %d peaks found, generating 2D detector image ..." % len(peaks))

        if self._cancelled:
            return

        # ── Generate 2D detector image (vectorised) ──
        # Run the heavy computation in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()

        def _compute():
            return _generate_2d_pattern(
                peaks, energy_keV, det_dist, det_key,
                beamstop_radius_mm=2.0,
                background_level=5.0,
                eta_pv=0.4,
                flux=flux,
            )

        image, ring_annotations = await loop.run_in_executor(None, _compute)

        if self._cancelled:
            return

        await self.send_progress(ws, 0.85,
            "2D-XRD: encoding image for transfer ...")

        # ── Get detector dimensions ──
        det = EIGER_DETECTORS.get(det_key, EIGER_DETECTORS["EIGER2_1M"])
        nH = det["pixelsH"]
        nV = det["pixelsV"]

        # ── Encode image as base64 Float32Array ──
        img_bytes = image.astype(np.float32).tobytes()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")

        await self.send_progress(ws, 0.95, "2D-XRD: sending result ...")

        # ── Send result ──
        elapsed = time.time() - t0

        await self.send_result(ws, "xrd2d",
            image_b64=img_b64,
            width=nH,
            height=nV,
            rings=ring_annotations,
            info={
                "crystal": crystal_key,
                "energy_keV": float(energy_keV),
                "wavelength_A": float(lambda_A),
                "detDist_m": float(det_dist),
                "detector": det_key,
                "flux": float(flux),
                "n_rings": len(ring_annotations),
                "n_peaks_total": len(peaks),
                "engine": "pymatgen" + ("+pyFAI" if _PYFAI_OK else ""),
            },
        )

        await self.send_done(ws, elapsed)

        log.info("XRD done: %s, %d rings, %dx%d image, %.2fs",
                 crystal_key, len(ring_annotations), nH, nV, elapsed)
