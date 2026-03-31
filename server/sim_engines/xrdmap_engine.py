"""XRD Phase Map Simulation Engine -- 2D spatially-resolved XRD using pymatgen.

Produces a 2D phase map with Voronoi grain structure and per-phase XRD patterns.
Reuses the XRD engine's crystal database and pymatgen XRDCalculator for accurate
peak positions and intensities.

Output protocol (same as experiment_engine.XRDMapEngine):
    {type:'expt_result', mode:'xrdmap',
     phase_map: [[...]], int_map1: [[...]], int_map2: [[...]],
     x_pts: [...], y_pts: [...],
     pattern1: {tth:[...], ints:[...], rings:[...]},
     pattern2: {tth:[...], ints:[...], rings:[...]},
     info: {cryst1, cryst2, energy_keV, wavelength_A, nx, ny, ...}}
"""

import asyncio
import logging
import math
import time

import numpy as np

from sim_engines.base import SimEngine

log = logging.getLogger("xrdmap-engine")

# ---------------------------------------------------------------------------
# Optional library imports
# ---------------------------------------------------------------------------
_PYMATGEN_OK = False
try:
    from pymatgen.core import Lattice, Structure
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    _PYMATGEN_OK = True
except ImportError:
    log.warning("pymatgen not available -- XRD Map engine disabled")

# Reuse crystal DB from xrd_engine
_XRD_DB_OK = False
try:
    from sim_engines.xrd_engine import _CRYSTAL_DB, get_structure, get_crystal_keys
    _XRD_DB_OK = True
except ImportError:
    log.warning("xrd_engine crystal DB not importable")

# Phantom generator for Voronoi grain structure
_PHANTOM_OK = False
try:
    from sim_engines.phantoms import phantom_xrd_phase_map
    _PHANTOM_OK = True
except ImportError:
    log.debug("phantoms module not available -- using numpy fallback for phase map")

# scipy for Gaussian smoothing
_SCIPY_OK = False
try:
    from scipy.ndimage import gaussian_filter
    _SCIPY_OK = True
except ImportError:
    log.debug("scipy not available -- grain boundaries will be sharp")


# ===================================================================
# Helper: compute XRD peaks for a crystal using pymatgen
# ===================================================================

def _compute_peaks(crystal_key, energy_keV):
    """Compute diffraction peaks for a crystal at given energy.

    Returns:
        peaks: list of dicts {twoTheta, intensity, hkl}
        tth_array: numpy array of 2theta values (dense, for 1D pattern)
        ints_array: numpy array of intensity values (dense, for 1D pattern)
        or (None, None, None) on failure
    """
    structure = get_structure(crystal_key)
    if structure is None:
        return None, None, None

    lambda_A = 12.3984 / energy_keV

    try:
        calculator = XRDCalculator(wavelength=lambda_A)
        pattern = calculator.get_pattern(structure, two_theta_range=(0, 90))
    except Exception as exc:
        log.warning("pymatgen XRD failed for %s: %s", crystal_key, exc)
        return None, None, None

    # Extract peaks
    peaks = []
    for i in range(len(pattern.x)):
        tth = float(pattern.x[i])
        intensity = float(pattern.y[i])
        hkl_list = pattern.hkls[i]
        hkl_str = ""
        if hkl_list:
            hkl_tuple = hkl_list[0].get("hkl", None)
            if hkl_tuple is not None:
                hkl_str = "".join(str(int(h)) for h in hkl_tuple)
        if intensity > 0.5:
            peaks.append({
                "twoTheta": tth,
                "intensity": intensity,
                "hkl": hkl_str,
            })

    # Build dense 1D pattern (for JS rendering)
    # Use a fine grid of 2theta values with Gaussian broadening
    tth_min = 0.0
    tth_max = 90.0
    n_pts = 4500  # 0.02 deg steps
    tth_arr = np.linspace(tth_min, tth_max, n_pts)
    ints_arr = np.zeros(n_pts, dtype=np.float64)

    for pk in peaks:
        center = pk["twoTheta"]
        amp = pk["intensity"]
        # Gaussian broadening with FWHM ~0.1 deg
        sigma = 0.1 / 2.3548
        ints_arr += amp * np.exp(-0.5 * ((tth_arr - center) / sigma) ** 2)

    return peaks, tth_arr, ints_arr


# ===================================================================
# Phase map generation (Voronoi or simple fallback)
# ===================================================================

def _generate_phase_map(nx, ny, x_pts, y_pts, cryst1, cryst2, seed=42):
    """Generate a 2D phase fraction map.

    Returns:
        phase_map: np.ndarray (ny, nx) -- 0.0 = pure phase1, 1.0 = pure phase2
    """
    if not cryst2:
        return np.zeros((ny, nx), dtype=np.float64)

    # Try using the Voronoi phantom generator first
    if _PHANTOM_OK:
        result = phantom_xrd_phase_map(nx, ny, x_pts, y_pts, cryst1, cryst2, seed)
        if result is not None and "phase_map" in result:
            return result["phase_map"]

    # Fallback: numpy-based Voronoi
    rng = np.random.RandomState(seed)
    n_grains = rng.randint(15, 30)
    half_lx = (x_pts[-1] - x_pts[0]) / 2.0
    half_ly = (y_pts[-1] - y_pts[0]) / 2.0
    cx = (x_pts[0] + x_pts[-1]) / 2.0
    cy = (y_pts[0] + y_pts[-1]) / 2.0

    grain_x = rng.uniform(cx - half_lx, cx + half_lx, n_grains)
    grain_y = rng.uniform(cy - half_ly, cy + half_ly, n_grains)
    grain_phase = rng.random(n_grains)

    # Vectorised Voronoi assignment
    XX, YY = np.meshgrid(x_pts, y_pts)  # (ny, nx)
    phase_map = np.zeros((ny, nx), dtype=np.float64)

    for yi in range(ny):
        for xi in range(nx):
            dists = (grain_x - XX[yi, xi]) ** 2 + (grain_y - YY[yi, xi]) ** 2
            nearest = np.argmin(dists)
            phase_map[yi, xi] = grain_phase[nearest]

    # Smooth grain boundaries
    if _SCIPY_OK:
        phase_map = gaussian_filter(phase_map, sigma=1.5)
        phase_map = np.clip(phase_map, 0.0, 1.0)

    return phase_map


# ===================================================================
# XRD Map Engine class
# ===================================================================

class XRDMapEngine(SimEngine):
    """2D XRD phase mapping engine using pymatgen + Voronoi phantom."""

    @staticmethod
    def available():
        return _PYMATGEN_OK and _XRD_DB_OK

    @staticmethod
    def name():
        return "xrdmap"

    async def run(self, ws, params, beamline):
        """Run 2D XRD phase mapping simulation.

        Args:
            ws: websocket connection
            params: {crystals, scanLx, scanLy, step, detDist, detector}
            beamline: {energy_keV, flux, spot_h_nm, spot_v_nm}
        """
        t0 = time.time()
        self.reset()

        # -- Parse parameters --
        crystals = params.get("crystals", ["Cu"])
        cryst1 = crystals[0] if crystals else "Cu"
        cryst2 = crystals[1] if len(crystals) > 1 else ""
        scan_lx = float(params.get("scanLx", 10.0))
        scan_ly = float(params.get("scanLy", 10.0))
        step_um = float(params.get("step", 0.5))
        det_dist = float(params.get("detDist", 0.3))
        det_key = params.get("detector", "EIGER2_1M")
        energy_keV = float(beamline.get("energy_keV", 10.0))
        flux = float(beamline.get("flux", 1e10))
        spot_h_nm = float(beamline.get("spot_h_nm", 50.0))
        spot_v_nm = float(beamline.get("spot_v_nm", 50.0))
        wavelength_A = 12.3984 / energy_keV

        # -- Build scan grid --
        half_lx = scan_lx / 2.0
        half_ly = scan_ly / 2.0
        x_pts = np.arange(-half_lx, half_lx + step_um * 0.5, step_um)
        y_pts = np.arange(-half_ly, half_ly + step_um * 0.5, step_um)
        nx = len(x_pts)
        ny = len(y_pts)

        label = cryst1 + ("+" + cryst2 if cryst2 else "")
        await self.send_progress(ws, 0.05,
            "XRD Map: %s, %dx%d grid (%d pts) ..." % (label, nx, ny, nx * ny))

        if self._cancelled:
            return

        # -- Compute XRD peaks for phase 1 --
        await self.send_progress(ws, 0.10,
            "XRD Map: computing peaks for %s (E=%.1f keV) ..." % (cryst1, energy_keV))

        loop = asyncio.get_event_loop()
        peaks1, tth1, ints1 = await loop.run_in_executor(
            None, _compute_peaks, cryst1, energy_keV)

        if peaks1 is None:
            await self.send_error(ws,
                "Unknown crystal '%s'. Available: %s" % (
                    cryst1, ", ".join(get_crystal_keys())))
            return

        rings1 = [{"twoTheta": p["twoTheta"], "intensity": p["intensity"]}
                   for p in peaks1]
        pattern1 = {
            "tth": tth1.tolist(),
            "ints": ints1.tolist(),
            "rings": rings1,
        }

        if self._cancelled:
            return

        # -- Compute XRD peaks for phase 2 (if dual-phase) --
        pattern2 = None
        if cryst2:
            await self.send_progress(ws, 0.20,
                "XRD Map: computing peaks for %s ..." % cryst2)

            peaks2, tth2, ints2 = await loop.run_in_executor(
                None, _compute_peaks, cryst2, energy_keV)

            if peaks2 is None:
                await self.send_error(ws,
                    "Unknown crystal '%s'. Available: %s" % (
                        cryst2, ", ".join(get_crystal_keys())))
                return

            rings2 = [{"twoTheta": p["twoTheta"], "intensity": p["intensity"]}
                       for p in peaks2]
            pattern2 = {
                "tth": tth2.tolist(),
                "ints": ints2.tolist(),
                "rings": rings2,
            }

        if self._cancelled:
            return

        # -- Generate Voronoi-based phase map --
        await self.send_progress(ws, 0.30,
            "XRD Map: generating phase distribution (Voronoi grains) ...")

        phase_map = await loop.run_in_executor(
            None, _generate_phase_map,
            nx, ny, x_pts, y_pts, cryst1, cryst2, 42)

        if self._cancelled:
            return

        await self.send_progress(ws, 0.60,
            "XRD Map: computing intensity maps ...")

        # -- Compute intensity maps --
        rng = np.random.RandomState(12345)
        base_int = flux * 1e-8

        # Phase 1 intensity: proportional to (1 - phase fraction)
        noise1 = 0.8 + 0.4 * rng.random((ny, nx))
        int_map1 = base_int * (1.0 - phase_map) * noise1

        # Phase 2 intensity: proportional to phase fraction
        if cryst2:
            noise2 = 0.8 + 0.4 * rng.random((ny, nx))
            int_map2 = base_int * phase_map * noise2
        else:
            int_map2 = np.zeros((ny, nx), dtype=np.float64)

        # -- Apply beam-size spatial blurring --
        # Beam size determines spatial resolution: when beam > step, features blur
        spot_h_um = spot_h_nm / 1000.0  # nm -> um
        spot_v_um = spot_v_nm / 1000.0
        sigma_h_px = spot_h_um / step_um  # beam FWHM in pixel units
        sigma_v_px = spot_v_um / step_um
        # Convert FWHM to Gaussian sigma: sigma = FWHM / 2.355
        sigma_h = sigma_h_px / 2.355
        sigma_v = sigma_v_px / 2.355

        if _SCIPY_OK and (sigma_h > 0.3 or sigma_v > 0.3):
            log.info("XRD Map: beam blur sigma=(%.2f, %.2f) px "
                     "(beam=%.0fx%.0f nm, step=%.2f um)",
                     sigma_h, sigma_v, spot_h_nm, spot_v_nm, step_um)
            phase_map = gaussian_filter(phase_map, sigma=(sigma_v, sigma_h))
            phase_map = np.clip(phase_map, 0.0, 1.0)
            int_map1 = gaussian_filter(int_map1, sigma=(sigma_v, sigma_h))
            if cryst2:
                int_map2 = gaussian_filter(int_map2, sigma=(sigma_v, sigma_h))

        if self._cancelled:
            return

        await self.send_progress(ws, 0.85,
            "XRD Map: encoding results ...")

        # -- Stream rows progressively --
        n_batches = min(10, ny)
        rows_per_batch = max(1, ny // n_batches)

        for batch_i in range(0, ny, rows_per_batch):
            end_row = min(batch_i + rows_per_batch, ny)
            frac = 0.85 + 0.10 * (end_row / ny)
            await self.send_progress(ws, frac,
                "XRD Map: row %d/%d ..." % (end_row, ny))

            if self._cancelled:
                return

        await self.send_progress(ws, 0.95, "XRD Map: sending result ...")

        # -- Send final result --
        elapsed = time.time() - t0

        await self.send_result(ws, "xrdmap",
            phase_map=phase_map.tolist(),
            int_map1=int_map1.tolist(),
            int_map2=int_map2.tolist() if cryst2 else None,
            x_pts=x_pts.tolist(),
            y_pts=y_pts.tolist(),
            pattern1=pattern1,
            pattern2=pattern2,
            info={
                "cryst1": cryst1,
                "cryst2": cryst2,
                "energy_keV": float(energy_keV),
                "wavelength_A": float(wavelength_A),
                "flux": float(flux),
                "spot_h_nm": float(spot_h_nm),
                "spot_v_nm": float(spot_v_nm),
                "effective_resolution_nm": float(max(spot_h_nm, spot_v_nm, step_um * 1000)),
                "nx": nx,
                "ny": ny,
                "step_um": float(step_um),
                "detDist_m": float(det_dist),
                "detector": det_key,
                "n_grains": int(phase_map.max() > 0) and "voronoi" or "single",
                "engine": "pymatgen",
            },
        )

        await self.send_done(ws, elapsed)

        log.info("XRD Map done: %s%s, %dx%d, %.2fs",
                 cryst1, "/" + cryst2 if cryst2 else "", nx, ny, elapsed)
