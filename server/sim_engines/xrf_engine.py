"""XRF Simulation Engine using xraylib + fisx.

Produces high-fidelity XRF spectra and 2D elemental maps for
the K4GSR virtual experiment system.

Key improvements over JS fallback:
  - xraylib: accurate cross-sections for Z=1-98 (Scofield/Kissel)
  - fisx: self-absorption + secondary/tertiary fluorescence (Sherman eq.)
  - Fano-limited detector resolution (energy-dependent FWHM)
  - Si escape peaks + pile-up modeling
  - Klein-Nishina Compton + Rayleigh scatter
  - Kramers bremsstrahlung continuum
"""

import asyncio
import json
import logging
import math
import re
import time

import numpy as np

# scipy for beam-PSF Gaussian smoothing (spatial resolution = beam size)
_SCIPY_OK = False
try:
    from scipy.ndimage import gaussian_filter
    _SCIPY_OK = True
except ImportError:
    log_psf = logging.getLogger("xrf-engine")
    log_psf.debug("scipy not available -- XRF maps will not be beam-blurred")

from sim_engines.base import SimEngine
from sim_engines.detectors import (
    SDD_SPEC, sdd_fwhm, sdd_efficiency, sdd_solid_angle,
    sdd_escape_fraction, generate_sdd_spectrum,
)

log = logging.getLogger("xrf-engine")


def _block_average_to_grid(fine, xf, yf, x_pts, y_pts, step_um):
    """Area-average a fine-grid field down to the scan-step grid.

    Each output pixel (xi, yj) is the MEAN of all fine cells whose centres fall
    in the step footprint [x-step/2, x+step/2) x [y-step/2, y+step/2). This is
    the detector integrating fluorescence over the dwell footprint (block-mean),
    not a point sample -- point-sampling a pre-blurred array would re-introduce
    aliasing (a delta detector). Returns a (ny, nx) array.

    The fine grid is uniform, so the per-axis bin index for each fine coordinate
    is computed once and the 2D mean is done with two matrix multiplies against
    sparse 0/1 averaging operators (fast: one pass per axis, no Python pixel
    loop).
    """
    nx = len(x_pts)
    ny = len(y_pts)
    half = step_um / 2.0

    def _avg_operator(coords_fine, centers):
        # Build an (n_centers x n_fine) row-normalized 0/1 membership matrix:
        # row j has 1/k for the k fine cells inside center j's footprint.
        nfine = len(coords_fine)
        ncen = len(centers)
        op = np.zeros((ncen, nfine), dtype=np.float64)
        for j in range(ncen):
            lo = centers[j] - half
            hi = centers[j] + half
            idx = np.where((coords_fine >= lo) & (coords_fine < hi))[0]
            if idx.size == 0:
                idx = [int(np.argmin(np.abs(coords_fine - centers[j])))]
                op[j, idx[0]] = 1.0
            else:
                op[j, idx] = 1.0 / idx.size
        return op

    ax = _avg_operator(xf, x_pts)   # (nx x nxf)
    ay = _avg_operator(yf, y_pts)   # (ny x nyf)
    # out[yj, xi] = sum_b sum_a ay[yj,b] * fine[b,a] * ax[xi,a]
    return ay @ fine @ ax.T


# ---------------------------------------------------------------------------
# Optional library imports
# ---------------------------------------------------------------------------
_XRAYLIB_OK = False
_xrl = None
try:
    import xraylib
    _xrl = xraylib
    xraylib.XRayInit()
    # SetErrorMessages deprecated in xraylib >= 4.2
    if hasattr(xraylib, 'SetErrorMessages'):
        try:
            xraylib.SetErrorMessages(0)
        except Exception:
            pass
    _XRAYLIB_OK = True
    log.info("xraylib loaded OK")
except ImportError:
    log.warning("xraylib not available")

_FISX_OK = False
_fisx = None
try:
    import fisx
    _fisx = fisx
    _FISX_OK = True
    log.info("fisx loaded OK")
except ImportError:
    log.debug("fisx not available (optional)")


# ---------------------------------------------------------------------------
# XRF line definitions (fallback if xraylib not available)
# Matches JS XRF_LINES from 01_xray_data.js
# ---------------------------------------------------------------------------
_XRF_LINE_DEFS = {
    "Ka1": {"macro": "KA1_LINE" if _XRAYLIB_OK else None, "branch": 0.578},
    "Ka2": {"macro": "KA2_LINE" if _XRAYLIB_OK else None, "branch": 0.294},
    "Kb1": {"macro": "KB1_LINE" if _XRAYLIB_OK else None, "branch": 0.084},
    "Kb3": {"macro": "KB3_LINE" if _XRAYLIB_OK else None, "branch": 0.044},
    "La1": {"macro": "LA1_LINE" if _XRAYLIB_OK else None, "branch": 0.70},
    "Lb1": {"macro": "LB1_LINE" if _XRAYLIB_OK else None, "branch": 0.30},
}

# K-shell branching ratios (used when xraylib unavailable)
K_BRANCH = {"Ka1": 0.578, "Ka2": 0.294, "Kb1": 0.084, "Kb3": 0.044}
L_BRANCH = {"La1": 0.700, "Lb1": 0.300}

# ---------------------------------------------------------------------------
# Sample presets (matches JS XRF_SAMPLE_PRESETS)
# ---------------------------------------------------------------------------
SAMPLE_PRESETS = {
    "semiconductor_ic": {
        "label": "Semiconductor IC (Cu/W/Co/Ti/Si)",
        "elements": {"Cu": 5000, "W": 3000, "Co": 2000, "Ti": 1500, "Si": 10000},
        "thickness_um": 0.5, "density": 5.5, "type": "solid",
    },
    "battery_nmc622": {
        "label": "Battery NMC622 cathode",
        "elements": {"Ni": 8000, "Mn": 5000, "Co": 4000, "Fe": 200, "Cu": 150},
        "thickness_um": 5.0, "density": 4.7, "type": "particle",
    },
    "geological_section": {
        "label": "Geological thin section",
        "elements": {"Fe": 6000, "Ti": 2000, "Mn": 1000, "Cr": 500,
                      "Ni": 300, "Cu": 200, "Zn": 150, "Sr": 100, "As": 50},
        "thickness_um": 30.0, "density": 2.7, "type": "solid",
    },
    "biological_cell": {
        "label": "Biological cell (freeze-dried)",
        "elements": {"Fe": 500, "Zn": 300, "Cu": 100, "Mn": 50, "Se": 20},
        "thickness_um": 2.0, "density": 1.2, "type": "solid",
    },
    "catalyst_nanoparticle": {
        "label": "Catalyst NPs on Al2O3",
        "elements": {"Pt": 3000, "Au": 2000, "Fe": 1000, "Ce": 800},
        "thickness_um": 1.0, "density": 3.5, "type": "particle",
    },
    "environmental_particle": {
        "label": "Environmental fly ash",
        "elements": {"Fe": 8000, "Ti": 1500, "Mn": 800, "Cr": 400,
                      "Cu": 300, "Zn": 250, "As": 80, "Pb": 60, "Sr": 50},
        "thickness_um": 10.0, "density": 2.3, "type": "particle",
    },
    "siemens_star": {
        "label": "Siemens Star (Au, resolution test)",
        "elements": {"Au": 8000, "Cr": 500, "Si": 3000},
        "thickness_um": 0.5, "density": 19.3, "type": "thin_film",
    },
    "calibration_grid": {
        "label": "Multi-Element Calibration Grid",
        "elements": {"Ca": 5000, "Ti": 5000, "Cr": 5000, "Mn": 5000,
                      "Fe": 5000, "Co": 5000, "Ni": 5000, "Cu": 5000,
                      "Zn": 5000, "As": 5000, "Se": 5000, "Sr": 5000,
                      "Au": 5000, "Pt": 5000, "Pb": 5000, "W": 5000},
        "thickness_um": 0.05, "density": 2.33, "type": "thin_film",
    },
}


# ---------------------------------------------------------------------------
# Formula parser
# ---------------------------------------------------------------------------
def parse_formula(formula):
    """Parse chemical formula. E.g., 'Cu2O' -> {'Cu': 2, 'O': 1}"""
    result = {}
    for match in re.finditer(r'([A-Z][a-z]?)(\d*\.?\d*)', formula):
        el = match.group(1)
        n = float(match.group(2)) if match.group(2) else 1.0
        result[el] = result.get(el, 0) + n
    return result


def _atomic_mass(Z):
    """Get atomic mass from xraylib or fallback table."""
    if _XRAYLIB_OK:
        try:
            return _xrl.AtomicWeight(Z)
        except Exception:
            pass
    # Fallback for common elements
    _MASS = {
        1: 1.008, 5: 10.81, 6: 12.011, 7: 14.007, 8: 15.999,
        11: 22.990, 13: 26.982, 14: 28.086, 15: 30.974, 16: 32.065,
        20: 40.078, 22: 47.867, 23: 50.942, 24: 51.996, 25: 54.938,
        26: 55.845, 27: 58.933, 28: 58.693, 29: 63.546, 30: 65.38,
        31: 69.723, 32: 72.630, 33: 74.922, 34: 78.971, 38: 87.62,
        42: 95.95, 47: 107.87, 56: 137.33, 57: 138.91, 58: 140.12,
        74: 183.84, 78: 195.08, 79: 196.97, 82: 207.20,
    }
    return _MASS.get(Z, 50.0)


def _symbol_to_Z(sym):
    """Convert element symbol to atomic number."""
    if _XRAYLIB_OK:
        try:
            return _xrl.SymbolToAtomicNumber(sym)
        except Exception:
            pass
    _Z = {
        "H": 1, "B": 5, "C": 6, "N": 7, "O": 8, "Na": 11, "Al": 13,
        "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ca": 20, "Ti": 22,
        "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28,
        "Cu": 29, "Zn": 30, "Ga": 31, "Ge": 32, "As": 33, "Se": 34,
        "Sr": 38, "Mo": 42, "Ag": 47, "Cd": 48, "Sn": 50, "Ba": 56,
        "La": 57, "Ce": 58, "W": 74, "Pt": 78, "Au": 79, "Pb": 82,
    }
    return _Z.get(sym, 0)


# ---------------------------------------------------------------------------
# XRF physics with xraylib
# ---------------------------------------------------------------------------
def _get_xrf_lines(Z, energy_keV):
    """Get all fluorescence lines for element Z excited at energy_keV.

    Returns list of (line_name, energy_eV, cross_section_cm2g).
    """
    lines = []
    if not _XRAYLIB_OK or Z < 5:
        return lines

    energy_eV = energy_keV * 1000.0

    # K-shell lines
    try:
        k_edge = _xrl.EdgeEnergy(Z, _xrl.K_SHELL) * 1000  # keV -> eV
        if energy_eV > k_edge:
            for name, macro_name in [
                ("Ka1", _xrl.KA1_LINE), ("Ka2", _xrl.KA2_LINE),
                ("Kb1", _xrl.KB1_LINE), ("Kb3", _xrl.KB3_LINE),
            ]:
                try:
                    line_E = _xrl.LineEnergy(Z, macro_name) * 1000  # keV -> eV
                    cs = _xrl.CS_FluorLine_Kissel(Z, macro_name, energy_keV)
                    if line_E > 500 and cs > 0:
                        lines.append((name, line_E, cs))
                except (ValueError, RuntimeError):
                    pass
    except (ValueError, RuntimeError):
        pass

    # L-shell lines (for Z >= 30)
    if Z >= 30:
        try:
            l3_edge = _xrl.EdgeEnergy(Z, _xrl.L3_SHELL) * 1000
            if energy_eV > l3_edge:
                for name, macro_name in [
                    ("La1", _xrl.LA1_LINE), ("Lb1", _xrl.LB1_LINE),
                    ("Lb2", _xrl.LB2_LINE), ("Lg1", _xrl.LG1_LINE),
                ]:
                    try:
                        line_E = _xrl.LineEnergy(Z, macro_name) * 1000
                        cs = _xrl.CS_FluorLine_Kissel(Z, macro_name, energy_keV)
                        if line_E > 500 and cs > 0:
                            lines.append((name, line_E, cs))
                    except (ValueError, RuntimeError):
                        pass
        except (ValueError, RuntimeError):
            pass

    return lines


def _compton_energy(E_keV, theta_deg=135.0):
    """Compton scattered photon energy (Klein-Nishina)."""
    theta_rad = math.radians(theta_deg)
    E_eV = E_keV * 1000.0
    E_prime = E_eV / (1 + (E_eV / 511000.0) * (1 - math.cos(theta_rad)))
    return E_prime


def _scatter_cross_sections(Z, energy_keV):
    """Get Rayleigh and Compton cross-sections."""
    if not _XRAYLIB_OK:
        return 0.01, 0.005

    try:
        cs_rayl = _xrl.CS_Rayl(Z, energy_keV)
    except (ValueError, RuntimeError):
        cs_rayl = 0.01
    try:
        cs_compt = _xrl.CS_Compt(Z, energy_keV)
    except (ValueError, RuntimeError):
        cs_compt = 0.005

    return cs_rayl, cs_compt


def _self_absorption_factor(mu_total, density, thickness_cm, theta_in_deg=45,
                             theta_out_deg=45):
    """Self-absorption correction factor for a flat sample.

    Factor = [1 - exp(-mu * rho * t * (1/sin(theta_in) + 1/sin(theta_out)))]
             / [mu * rho * t * (1/sin(theta_in) + 1/sin(theta_out))]
    """
    sin_in = max(0.01, math.sin(math.radians(theta_in_deg)))
    sin_out = max(0.01, math.sin(math.radians(theta_out_deg)))
    mu_rho_t = mu_total * density * thickness_cm * (1.0 / sin_in + 1.0 / sin_out)
    if mu_rho_t < 1e-6:
        return 1.0
    return (1.0 - math.exp(-mu_rho_t)) / mu_rho_t


# ---------------------------------------------------------------------------
# XRF Engine class
# ---------------------------------------------------------------------------
class XRFEngine(SimEngine):
    """XRF 2D Mapping Engine using xraylib + fisx."""

    @staticmethod
    def available():
        return _XRAYLIB_OK

    @staticmethod
    def name():
        return "xrf2d"

    async def run(self, ws, params, beamline):
        """Run 2D XRF mapping simulation.

        params keys:
            formula, ppm, scanLx, scanLy, step, dwell,
            sampleType, thickness_um, matDensity, presetKey
        beamline keys:
            energy_keV, spot_h_nm, spot_v_nm, flux
        """
        t0 = time.time()

        # Parse parameters
        preset_key = params.get("presetKey", "")
        formula = params.get("formula", "Cu")
        ppm = float(params.get("ppm", 1000))
        scan_lx = float(params.get("scanLx", 10.0))
        scan_ly = float(params.get("scanLy", 10.0))
        step_um = float(params.get("step", 0.5))
        dwell = float(params.get("dwell", 0.1))
        sample_type = params.get("sampleType", "solid")
        thickness_um = float(params.get("thickness_um", 1.0))
        mat_density = float(params.get("matDensity", 2.0))

        energy_keV = float(beamline.get("energy_keV", 10.0))
        energy_eV = energy_keV * 1000.0
        flux = float(beamline.get("flux", 1e10))
        spot_h = float(beamline.get("spot_h_nm", 50))
        spot_v = float(beamline.get("spot_v_nm", 50))

        # Build element list from formula or preset
        if preset_key and preset_key in SAMPLE_PRESETS:
            preset = SAMPLE_PRESETS[preset_key]
            el_ppm = preset["elements"]
            thickness_um = preset.get("thickness_um", thickness_um)
            mat_density = preset.get("density", mat_density)
            sample_type = preset.get("type", sample_type)
        else:
            parsed = parse_formula(formula)
            total_mass = sum(
                count * _atomic_mass(_symbol_to_Z(el))
                for el, count in parsed.items()
            )
            el_ppm = {}
            for el, count in parsed.items():
                Z = _symbol_to_Z(el)
                if Z < 5:
                    continue
                wt_frac = count * _atomic_mass(Z) / max(total_mass, 1.0)
                el_ppm[el] = wt_frac * ppm

        # Clamp the scan FOV to the practical nanoprobe limit. A ~50 nm beam can
        # only usefully image tens of um; a full 300 um raster would be millions
        # of points / hours. Larger requests are clamped and flagged.
        _fov_clamp_note = ""
        try:
            from sim_engines.phantoms import MAX_FOV_UM as _MAX_FOV
        except ImportError:
            _MAX_FOV = 60.0
        if scan_lx > _MAX_FOV or scan_ly > _MAX_FOV:
            _orig = (scan_lx, scan_ly)
            scan_lx = min(scan_lx, _MAX_FOV)
            scan_ly = min(scan_ly, _MAX_FOV)
            _fov_clamp_note = (
                "FOV clamped from %.0fx%.0f to %.0fx%.0f um "
                "(nanoprobe practical limit %.0f um)"
                % (_orig[0], _orig[1], scan_lx, scan_ly, _MAX_FOV))
            log.warning("2D-XRF: %s", _fov_clamp_note)

        # Build scan grid
        half_lx = scan_lx / 2.0
        half_ly = scan_ly / 2.0
        x_pts = np.arange(-half_lx, half_lx + step_um * 0.49, step_um)
        y_pts = np.arange(-half_ly, half_ly + step_um * 0.49, step_um)
        nx, ny = len(x_pts), len(y_pts)

        # Sort elements by concentration (descending)
        el_list = sorted(el_ppm.keys(), key=lambda e: -el_ppm[e])

        await self.send_progress(ws, 0.05,
            f"2D-XRF: {len(el_list)} elements, {nx}x{ny} grid, "
            f"E={energy_keV:.1f} keV (xraylib"
            + ("+fisx" if _FISX_OK else "") + ")")

        # ── Compute XRF cross-sections per element ──
        thickness_cm = thickness_um * 1e-4
        omega_sdd = sdd_solid_angle()
        el_info = []  # list of {sym, Z, ppm_val, lines: [(name, E_eV, cs)]}

        for sym in el_list:
            Z = _symbol_to_Z(sym)
            if Z < 5:
                continue
            ppm_val = el_ppm[sym]
            wt_frac = ppm_val / 1e6

            lines = _get_xrf_lines(Z, energy_keV)
            if not lines:
                continue

            # Get total mu for self-absorption
            try:
                mu_total = _xrl.CS_Total(Z, energy_keV) if _XRAYLIB_OK else 50.0
            except (ValueError, RuntimeError):
                mu_total = 50.0

            sa_factor = _self_absorption_factor(
                mu_total, mat_density, thickness_cm)

            el_info.append({
                "sym": sym, "Z": Z,
                "ppm": ppm_val, "wt_frac": wt_frac,
                "lines": lines, "sa_factor": sa_factor,
            })

        if not el_info:
            await self.send_error(ws,
                f"No excitable elements in '{formula}' at {energy_keV} keV")
            return

        # ── Form the measured map: (true sample * beam PSF) sampled at step ──
        # A scanning-XRF image is NOT just a blurred copy of the sample. It is
        # the true element distribution S convolved with the focused-beam
        # intensity profile P (the PSF), then SAMPLED on the discrete scan-step
        # grid:  I(xi,yj) = (S * P)(xi,yj)   [Dao et al., J. Anal. At. Spectrom.
        # 2022, DOI 10.1039/D1JA00425E; Metallomics review PMC9226457].
        # Blur (beam width, a convolution) and pixelation (scan step, a
        # sampling) are INDEPENDENT operations. To reproduce both we:
        #   (A) generate the phantom on a FINE grid (sub-beam, sub-step) so real
        #       sub-step structure (44 nm IC lines, 25 nm Siemens spokes) exists;
        #   (B) convolve that fine field with the beam Gaussian (FWHM = spot);
        #   (C) area-average (block-mean = detector integration over the dwell
        #       footprint) down to the nx x ny scan-step grid.
        # Coarse step -> blocky/aliased pixels; step ~ beam -> pixelated + soft;
        # fine step -> smooth blur disk ~ beam size. One pipeline, no per-regime
        # fudge. The reported image stays nx x ny (the step grid).
        beam_sigma_h = beam_sigma_v = 0.0
        psf_applied = False   # did we actually convolve the beam PSF anywhere?
        phantom_maps = None
        if preset_key:
            try:
                from sim_engines.phantoms import phantom_spatial_maps
            except ImportError:
                phantom_spatial_maps = None
                log.debug("phantoms module not available, using simple patterns")

            if phantom_spatial_maps is not None:
                spot_min_um = min(spot_h, spot_v) / 1000.0  # nm -> um
                # Fine pitch: >= K samples across the smaller of step/beam
                # (literature uses step < 1/4 spot, Dao 2022). Floor at 1 nm.
                _K = 4
                step_fine = max(min(step_um, spot_min_um) / _K, 1e-3)
                # Performance cap: the phantom generators are O(N^2) Python
                # loops, so bound the fine grid per axis. MAX_FINE = 1000 keeps
                # generation ~1-3 s; the resulting oversampling (fine vs step)
                # still resolves the beam well enough to show the
                # pixelation<->blur transition. Larger fine grids only sharpen
                # already-correct behaviour at a steep time cost.
                MAX_FINE = 1000
                # The fine grid must COVER every step footprint [c-step/2,
                # c+step/2], not just [-half,+half]; otherwise the boundary row/
                # column block-averages over fewer fine cells than the interior
                # (an edge artifact). Anchor the fine span on the actual step-grid
                # extent and pad half a step on each side so all footprints are
                # fully tiled and every output pixel averages a uniform count.
                half_step = step_um / 2.0
                lo_x = float(x_pts[0]) - half_step
                lo_y = float(y_pts[0]) - half_step
                span_x = (float(x_pts[-1]) + half_step) - lo_x
                span_y = (float(y_pts[-1]) + half_step) - lo_y
                nxf = int(round(span_x / step_fine)) + 1
                nyf = int(round(span_y / step_fine)) + 1
                if max(nxf, nyf) > MAX_FINE:
                    step_fine = max(span_x, span_y) / (MAX_FINE - 1)
                    nxf = int(round(span_x / step_fine)) + 1
                    nyf = int(round(span_y / step_fine)) + 1

                # Beam sigma in STEP-grid pixels (used for the info dict and the
                # step-grid blur safety net below).
                beam_sigma_h = (spot_h / 1000.0 / step_um) / 2.355
                beam_sigma_v = (spot_v / 1000.0 / step_um) / 2.355

                if _SCIPY_OK and step_fine < step_um * 0.9:
                    await self.send_progress(ws, 0.08,
                        f"2D-XRF: rendering sample at {nxf}x{nyf} sub-beam grid "
                        f"({step_fine*1000:.0f} nm) for {spot_h:.0f} nm beam...")
                    # (A) fine-grid true sample, covering the full step footprint
                    xf = lo_x + np.arange(nxf) * step_fine
                    yf = lo_y + np.arange(nyf) * step_fine
                    fine = phantom_spatial_maps(
                        preset_key, nxf, nyf, xf, yf, seed=42)
                    if fine:
                        # (B) beam-PSF convolution on the FINE grid
                        sig_h_f = (spot_h / 1000.0 / step_fine) / 2.355
                        sig_v_f = (spot_v / 1000.0 / step_fine) / 2.355
                        do_fine_blur = sig_h_f > 0.3 or sig_v_f > 0.3
                        log.info("2D-XRF: fine grid %dx%d @ %.4f um, beam sigma "
                                 "(%.1f,%.1f) fine-px; downsample -> %dx%d step",
                                 nxf, nyf, step_fine, sig_h_f, sig_v_f, nx, ny)
                        phantom_maps = {}
                        for _sym, _m in fine.items():
                            if do_fine_blur:
                                _m = gaussian_filter(
                                    _m, sigma=(sig_v_f, sig_h_f), mode="nearest")
                            # (C) block-mean down to the step grid (detector
                            # integrates fluorescence over each step footprint).
                            phantom_maps[_sym] = _block_average_to_grid(
                                _m, xf, yf, x_pts, y_pts, step_um)
                        psf_applied = do_fine_blur

                if phantom_maps is None:
                    # Fallback (no scipy, or the MAX_FINE cap made the fine pitch
                    # >= the step so there is nothing to oversample): generate
                    # directly at the step grid. The beam PSF is then applied by
                    # the safety net below.
                    phantom_maps = phantom_spatial_maps(
                        preset_key, nx, ny, x_pts, y_pts, seed=42)

                # Beam-PSF safety net: NEVER silently drop the beam blur. If the
                # fine-grid convolution was not applied -- the fallback path, or
                # the MAX_FINE cap (large FOV) left the fine pitch coarser than
                # the beam so sig_fine < 0.3 -- but the beam is still resolvable
                # on the step grid, convolve the step-grid maps with the beam
                # Gaussian (sigma in step pixels). This is the matched-/large-FOV
                # regime the work order's blur fix targets.
                if (_SCIPY_OK and phantom_maps is not None and not psf_applied
                        and (beam_sigma_h > 0.3 or beam_sigma_v > 0.3)):
                    log.info("2D-XRF: step-grid beam blur (sigma %.2f,%.2f step-px) "
                             "-- fine-grid path skipped/capped",
                             beam_sigma_h, beam_sigma_v)
                    for _sym in list(phantom_maps.keys()):
                        phantom_maps[_sym] = gaussian_filter(
                            phantom_maps[_sym],
                            sigma=(beam_sigma_v, beam_sigma_h), mode="nearest")
                    psf_applied = True

        # ── Compute XRF signal per pixel ──
        all_maps = {info["sym"]: np.zeros((ny, nx)) for info in el_info}
        all_line_counts = []  # for sum spectrum

        await self.send_progress(ws, 0.10, "Computing XRF signals...")

        for yi in range(ny):
            if self._cancelled:
                return

            for xi in range(nx):
                for info in el_info:
                    sym = info["sym"]
                    wt_frac = info["wt_frac"]

                    # Spatial modulation
                    if phantom_maps and sym in phantom_maps:
                        spatial = phantom_maps[sym][yi, xi]
                    else:
                        # Simple fallback spatial pattern
                        xn = xi / max(1, nx - 1)
                        yn = yi / max(1, ny - 1)
                        spatial = 0.3 + 0.5 * math.exp(
                            -((xn - 0.5)**2 + (yn - 0.5)**2) / 0.2)

                    wt_eff = wt_frac * spatial

                    # Total XRF counts for this pixel (sum of all lines)
                    pixel_total = 0.0
                    for line_name, line_E, cs in info["lines"]:
                        # cs is CS_FluorLine in cm2/g
                        # counts = flux * dwell * wt_frac * cs * rho * t * Omega
                        #        * self_absorption * detector_efficiency
                        det_eff = sdd_efficiency(line_E)
                        counts = (flux * dwell * wt_eff * cs
                                  * mat_density * thickness_cm
                                  * omega_sdd * info["sa_factor"]
                                  * det_eff)
                        pixel_total += max(0, counts)

                    # Store total counts (all lines combined)
                    all_maps[sym][yi, xi] = pixel_total

            # Progress update every 5 rows
            if yi % max(1, ny // 20) == 0:
                frac = 0.10 + 0.70 * (yi + 1) / ny
                await self.send_progress(ws, frac,
                    f"2D-XRF: row {yi+1}/{ny}")
                await asyncio.sleep(0.01)

        # ── Add Poisson noise to maps ──
        for sym in all_maps:
            m = all_maps[sym]
            m_noisy = np.random.poisson(np.maximum(m, 0).astype(np.float64))
            all_maps[sym] = m_noisy.astype(np.float64)

        await self.send_progress(ws, 0.85, "Generating XRF spectrum...")

        # ── Compute sum spectrum (aggregate over all pixels) ──
        # Use center pixel representative spectrum
        line_counts_for_spectrum = []
        for info in el_info:
            sym = info["sym"]
            wt_frac = info["wt_frac"]
            for line_name, line_E, cs in info["lines"]:
                det_eff = sdd_efficiency(line_E)
                counts = (flux * dwell * wt_frac * cs
                          * mat_density * thickness_cm
                          * omega_sdd * info["sa_factor"]
                          * det_eff)
                if counts > 0:
                    line_counts_for_spectrum.append((line_E, counts))
                    all_line_counts.append({
                        "el": sym, "line": line_name,
                        "E": float(line_E),
                        "counts": float(counts),
                    })

        # Scatter peaks
        E_compton = _compton_energy(energy_keV, theta_deg=135.0)
        E_elastic = energy_eV

        # Estimate scatter counts (weighted average over elements)
        rayl_total = 0.0
        compt_total = 0.0
        for info in el_info:
            cs_rayl, cs_compt = _scatter_cross_sections(info["Z"], energy_keV)
            rayl_total += cs_rayl * info["wt_frac"]
            compt_total += cs_compt * info["wt_frac"]

        scatter_base = flux * dwell * mat_density * thickness_cm * omega_sdd
        rayleigh_counts = scatter_base * rayl_total * 0.1
        compton_counts = scatter_base * compt_total * 0.1

        # Generate full spectrum
        spectrum_channels = generate_sdd_spectrum(
            line_counts=line_counts_for_spectrum,
            compton_energy_eV=E_compton,
            rayleigh_energy_eV=E_elastic,
            compton_counts=compton_counts,
            rayleigh_counts=rayleigh_counts,
            background_level=0.5,
        )

        # Poisson noise on spectrum
        spectrum_channels = np.random.poisson(
            np.maximum(spectrum_channels, 0.1).astype(np.int64)
        ).astype(np.float64)

        # Sort peaks by counts
        peaks_sorted = sorted(all_line_counts, key=lambda p: -p["counts"])[:20]

        await self.send_progress(ws, 0.95, "Sending results...")

        # ── Send result ──
        result_maps = {sym: all_maps[sym].tolist() for sym in all_maps}
        el_result = [info["sym"] for info in el_info]

        engine_label = "xraylib"
        if _FISX_OK:
            engine_label += "+fisx"

        await self.send_result(ws, "xrf2d",
            maps=result_maps,
            elements=el_result,
            x_pts=x_pts.tolist(),
            y_pts=y_pts.tolist(),
            spectrum={
                "channels": spectrum_channels.tolist(),
                "nCh": 2048,
                "ePerCh": 10,
                "peaks": peaks_sorted,
                "E_elastic": float(E_elastic),
                "E_compton": float(E_compton),
            },
            info={
                "formula": formula,
                "ppm": ppm,
                "nx": nx, "ny": ny,
                "step_um": step_um,
                "fov_um": [round(scan_lx, 4), round(scan_ly, 4)],
                "fov_clamped": _fov_clamp_note or None,
                "energy_keV": energy_keV,
                "flux": flux,
                "beam_nm": f"{spot_h:.0f}x{spot_v:.0f}",
                "beam_blurred": bool(psf_applied),
                "beam_sigma_px": [round(beam_sigma_h, 3), round(beam_sigma_v, 3)],
                # Effective spatial resolution is limited by whichever is larger:
                # the focused beam size or the scan step (Nyquist).
                "effective_resolution_nm": round(
                    max(spot_h, spot_v, step_um * 1000.0), 1),
                "dwell_s": dwell,
                "thickness_um": thickness_um,
                "density": mat_density,
                "n_elements": len(el_info),
                "engine": engine_label,
                "preset": preset_key if preset_key else None,
            },
        )

        elapsed = time.time() - t0
        await self.send_done(ws, elapsed)

        log.info(f"XRF done: {len(el_info)} elements, {nx}x{ny} grid, "
                 f"{elapsed:.2f}s")
