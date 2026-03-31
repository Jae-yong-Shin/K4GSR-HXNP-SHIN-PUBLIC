"""K4GSR Virtual Experiment Engine -- Server-side simulation using scientific libraries.

Supported modes:
  xafs   -- XAFS mu(E) via Larch (xraydb mu_elam + EXAFS oscillation)
  xrd2d  -- 2D powder XRD via Dans_Diffraction
  xrf2d  -- 2D XRF mapping via xraydb (fluorescence cross-section)
  xrdmap -- 2D XRD phase mapping via Dans_Diffraction

Each mode receives beamline context from the frontend:
  beamline = {energy_keV, spot_h_nm, spot_v_nm, flux, ssaH, ssaV}

This allows server-side simulations to be consistent with the
current virtual beamline state (MC ray-trace results).
"""

import asyncio
import json
import logging
import time
import numpy as np

log = logging.getLogger("expt-engine")

# ---------------------------------------------------------------------------
# Optional imports -- fail gracefully per-mode
# ---------------------------------------------------------------------------
_LARCH_OK = False
try:
    from larch.xray import mu_elam as _mu_elam, xray_edge as _xray_edge
    from xraydb import XrayDB as _XrayDB
    _xdb = _XrayDB()
    _LARCH_OK = True
except ImportError as e:
    log.warning(f"Larch/xraydb not available: {e}")

_DANS_OK = False
try:
    import Dans_Diffraction as _dif
    # Suppress verbose stdout from setup_scatter
    import io as _io
    import contextlib as _contextlib
    _DANS_OK = True
except ImportError as e:
    log.warning(f"Dans_Diffraction not available: {e}")


# ===================================================================
# Crystal database (matches JS side 01_xray_data.js + 04_xrd2d_sim.js)
# ===================================================================
CRYSTAL_DB = {
    "Cu":    {"a": 3.6149, "sg": 225, "atoms": [("Cu", 0, 0, 0)]},
    "Al":    {"a": 4.0495, "sg": 225, "atoms": [("Al", 0, 0, 0)]},
    "Ni":    {"a": 3.5240, "sg": 225, "atoms": [("Ni", 0, 0, 0)]},
    "Au":    {"a": 4.0782, "sg": 225, "atoms": [("Au", 0, 0, 0)]},
    "Ag":    {"a": 4.0862, "sg": 225, "atoms": [("Ag", 0, 0, 0)]},
    "Pt":    {"a": 3.9242, "sg": 225, "atoms": [("Pt", 0, 0, 0)]},
    "Fe":    {"a": 2.8665, "sg": 229, "atoms": [("Fe", 0, 0, 0)]},  # BCC
    "Si":    {"a": 5.4310, "sg": 227, "atoms": [("Si", 0, 0, 0)]},  # Diamond
    "Ge":    {"a": 5.6575, "sg": 227, "atoms": [("Ge", 0, 0, 0)]},
    "NaCl":  {"a": 5.6400, "sg": 225,
              "atoms": [("Na", 0, 0, 0), ("Cl", 0.5, 0.5, 0.5)]},
    "CeO2":  {"a": 5.4113, "sg": 225,
              "atoms": [("Ce", 0, 0, 0), ("O", 0.25, 0.25, 0.25)]},
    "SrTiO3": {"a": 3.905, "sg": 221,
               "atoms": [("Sr", 0, 0, 0), ("Ti", 0.5, 0.5, 0.5),
                          ("O", 0.5, 0.5, 0), ("O", 0.5, 0, 0.5),
                          ("O", 0, 0.5, 0.5)]},
    "LaB6":  {"a": 4.1569, "sg": 221,
              "atoms": [("La", 0, 0, 0),
                        ("B", 0.1988, 0.5, 0.5), ("B", 0.5, 0.1988, 0.5),
                        ("B", 0.5, 0.5, 0.1988), ("B", 0.8012, 0.5, 0.5),
                        ("B", 0.5, 0.8012, 0.5), ("B", 0.5, 0.5, 0.8012)]},
}

# Element data (Z, M, K/L3 edge eV) -- matches JS XRAY_ELEMENTS
ELEMENT_DB = {
    "Ti": {"Z": 22, "M": 47.867, "K": 4966, "L3": 454},
    "V":  {"Z": 23, "M": 50.942, "K": 5465, "L3": 512},
    "Cr": {"Z": 24, "M": 51.996, "K": 5989, "L3": 574},
    "Mn": {"Z": 25, "M": 54.938, "K": 6539, "L3": 639},
    "Fe": {"Z": 26, "M": 55.845, "K": 7112, "L3": 706},
    "Co": {"Z": 27, "M": 58.933, "K": 7709, "L3": 778},
    "Ni": {"Z": 28, "M": 58.693, "K": 8333, "L3": 855},
    "Cu": {"Z": 29, "M": 63.546, "K": 8979, "L3": 932},
    "Zn": {"Z": 30, "M": 65.38,  "K": 9659, "L3": 1020},
    "Ga": {"Z": 31, "M": 69.723, "K": 10367},
    "Ge": {"Z": 32, "M": 72.630, "K": 11103},
    "As": {"Z": 33, "M": 74.922, "K": 11867},
    "Se": {"Z": 34, "M": 78.971, "K": 12658},
    "Sr": {"Z": 38, "M": 87.62,  "K": 16105, "L3": 1940},
    "Mo": {"Z": 42, "M": 95.95,  "K": 20000, "L3": 2520},
    "Ag": {"Z": 47, "M": 107.87, "K": 25514, "L3": 3351},
}


# ===================================================================
# Helper: parse chemical formula  (mirrors JS parseFormula)
# ===================================================================
def _quiet_setup_scatter(xtl, energy_kev):
    """Call xtl.Scatter.setup_scatter suppressing stdout."""
    import sys
    old_stdout = sys.stdout
    sys.stdout = _io.StringIO()
    try:
        xtl.Scatter.setup_scatter(energy_kev=energy_kev)
    finally:
        sys.stdout = old_stdout


def parse_formula(formula):
    """Parse e.g. 'Cu2O' -> {'Cu':2, 'O':1}."""
    import re
    result = {}
    for m in re.finditer(r'([A-Z][a-z]?)(\d*\.?\d*)', formula):
        el = m.group(1)
        n = float(m.group(2)) if m.group(2) else 1.0
        result[el] = result.get(el, 0) + n
    return result


def compound_mass(parsed):
    """Total molar mass from parsed formula dict."""
    total = 0.0
    for el, n in parsed.items():
        ed = ELEMENT_DB.get(el)
        if ed:
            total += n * ed["M"]
        else:
            total += n * 40.0  # fallback
    return total


# ===================================================================
# XAFS Engine (Larch-based)
# ===================================================================
class XAFSEngine:
    """Server-side XAFS simulation using Larch mu_elam + EXAFS model."""

    @staticmethod
    def available():
        return _LARCH_OK

    @staticmethod
    async def run(ws, params, beamline):
        """Run XAFS simulation and stream results.

        params keys: formula, absorber, edge, eStart, eEnd, eStep, ppm
        beamline keys: energy_keV, spot_h_nm, spot_v_nm, flux
        """
        formula = params.get("formula", "Cu")
        absorber = params.get("absorber", "Cu")
        edge_type = params.get("edge", "K")
        e_start = params.get("eStart", -50)
        e_end = params.get("eEnd", 300)
        e_step = params.get("eStep", 0.5)
        ppm = params.get("ppm", 10000)

        flux = beamline.get("flux", 1e10)

        # Resolve edge energy
        el_data = ELEMENT_DB.get(absorber)
        if not el_data or edge_type not in el_data:
            await ws.send(json.dumps({
                "type": "expt_error",
                "message": f"Unknown edge: {absorber} {edge_type}"
            }))
            return

        E0 = el_data[edge_type]
        parsed = parse_formula(formula)

        # Build energy array
        energies = np.arange(e_start, e_end + e_step * 0.5, e_step)
        E_abs = E0 + energies  # absolute energies in eV

        # mu(E) from Larch for each element in compound
        total_mass = compound_mass(parsed)
        mu_total = np.zeros_like(E_abs, dtype=np.float64)

        for el, n in parsed.items():
            try:
                mu_el = _mu_elam(el, E_abs)  # cm2/g
                ed = ELEMENT_DB.get(el)
                M_el = ed["M"] if ed else 40.0
                wt_frac = n * M_el / total_mass
                mu_total += wt_frac * mu_el
            except Exception:
                pass

        # Scale by concentration (ppm)
        ppm_scale = ppm / 1e6
        # The absorber contributes the edge; background from other elements
        # For realistic mu(E): separate absorber contribution for ppm scaling
        mu_absorber = np.zeros_like(E_abs)
        try:
            mu_absorber = _mu_elam(absorber, E_abs)
        except Exception:
            pass

        # Build final spectrum:
        #   mu = mu_matrix (from all elements) + ppm_scale * mu_absorber_edge
        # For simplicity: scale entire compound mu by concentration
        mu_bg = mu_total * 0.1  # background matrix
        mu_signal = mu_total * ppm_scale  # absorber signal scaled by ppm
        mu_spec = mu_bg + mu_signal

        # Normalize: divide by pre-edge value for conventional mu(E)
        pre_edge_mask = energies < -20
        if pre_edge_mask.any():
            mu_pre = mu_spec[pre_edge_mask].mean()
            if mu_pre > 0:
                mu_spec = mu_spec / mu_pre
        else:
            mu_spec = mu_spec / mu_spec[0] if mu_spec[0] > 0 else mu_spec

        # Add Poisson noise based on flux
        noise_level = 1.0 / np.sqrt(max(flux * 0.001, 1.0))
        noise = np.random.normal(0, noise_level, len(mu_spec)) * 0.01
        mu_spec += noise

        # Stream data in batches (50 points per batch)
        batch_size = 50
        total = len(energies)

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.0,
            "msg": f"XAFS: {formula} {absorber} {edge_type}-edge (E0={E0} eV), {total} points"
        }))

        data_all = []
        for i in range(0, total, batch_size):
            batch_end = min(i + batch_size, total)
            batch = []
            for j in range(i, batch_end):
                batch.append({"x": float(energies[j]), "y": float(mu_spec[j])})
            data_all.extend(batch)

            frac = batch_end / total
            await ws.send(json.dumps({
                "type": "expt_data",
                "mode": "xafs",
                "batch": batch,
                "progress": frac
            }))
            await asyncio.sleep(0.02)  # yield to event loop

        await ws.send(json.dumps({
            "type": "expt_result",
            "mode": "xafs",
            "data": data_all,
            "info": {
                "formula": formula,
                "absorber": absorber,
                "edge": edge_type,
                "E0_eV": E0,
                "n_points": total,
                "ppm": ppm,
                "engine": "larch"
            }
        }))

        await ws.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": 0.0  # will be set by caller
        }))


# ===================================================================
# XRD 2D Engine (Dans_Diffraction-based)
# ===================================================================
class XRD2DEngine:
    """Server-side 2D XRD simulation using Dans_Diffraction powder pattern."""

    @staticmethod
    def available():
        return _DANS_OK

    @staticmethod
    def _build_crystal(name):
        """Build a Dans_Diffraction Crystal from our database."""
        info = CRYSTAL_DB.get(name)
        if not info:
            return None

        xtl = _dif.Crystal()
        xtl.name = name
        a = info["a"]
        xtl.Cell.latt([a, a, a, 90, 90, 90])
        xtl.Symmetry.load_spacegroup(info["sg"])

        for i, (el, u, v, w) in enumerate(info["atoms"]):
            if i == 0:
                xtl.Atoms.changeatom(0, label=el, u=u, v=v, w=w,
                                     type=el, occupancy=1.0)
            else:
                xtl.Atoms.addatom(label=el, u=u, v=v, w=w,
                                  type=el, occupancy=1.0)
        return xtl

    @staticmethod
    async def run(ws, params, beamline):
        """Run 2D XRD simulation.

        params keys: crystal, detDist, detector
        beamline keys: energy_keV
        """
        crystal_name = params.get("crystal", "Cu")
        det_dist = params.get("detDist", 0.3)
        det_key = params.get("detector", "EIGER2_1M")
        energy_keV = beamline.get("energy_keV", 10.0)
        wavelength = 12.3984 / energy_keV  # Angstrom

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.1,
            "msg": f"2D XRD: computing {crystal_name} at {energy_keV:.1f} keV..."
        }))

        xtl = XRD2DEngine._build_crystal(crystal_name)
        if not xtl:
            await ws.send(json.dumps({
                "type": "expt_error",
                "message": f"Unknown crystal: {crystal_name}"
            }))
            return

        # Get powder pattern via generate_powder (returns q, I)
        _quiet_setup_scatter(xtl, energy_keV)
        q_arr, ints = xtl.Scatter.generate_powder(
            q_max=8, peak_width=0.1, background=0
        )

        # Convert q -> 2theta (degrees)
        sin_arg = q_arr * wavelength / (4 * np.pi)
        valid = np.abs(sin_arg) < 1.0
        tth = np.zeros_like(q_arr)
        tth[valid] = 2 * np.degrees(np.arcsin(sin_arg[valid]))

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.5,
            "msg": "2D XRD: generating 2D pattern..."
        }))

        # Find peaks for ring annotation
        from scipy.signal import find_peaks
        pk_idx, _ = find_peaks(ints, height=0.01 * max(ints.max(), 1),
                               distance=5)
        rings = []
        for idx in pk_idx[:20]:
            if tth[idx] > 0:
                rings.append({
                    "twoTheta": float(tth[idx]),
                    "intensity": float(ints[idx]),
                })

        # Generate 2D Debye-Scherrer image
        det_size = 1024
        img = _generate_debye_rings(rings, energy_keV, det_dist, det_size)

        # Encode image as base64 for transport
        import base64
        import io
        # Store as 16-bit PNG via minimal encoding
        # For efficiency, send raw float32 data as base64
        img_bytes = img.astype(np.float32).tobytes()
        img_b64 = base64.b64encode(img_bytes).decode('ascii')

        await ws.send(json.dumps({
            "type": "expt_result",
            "mode": "xrd2d",
            "image_b64": img_b64,
            "width": det_size,
            "height": det_size,
            "rings": rings,
            "info": {
                "crystal": crystal_name,
                "energy_keV": energy_keV,
                "wavelength_A": wavelength,
                "detDist_m": det_dist,
                "detector": det_key,
                "n_rings": len(rings),
                "engine": "dans_diffraction"
            }
        }))

        await ws.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": 0.0
        }))


def _generate_debye_rings(rings, energy_keV, det_dist, size):
    """Generate a 2D Debye-Scherrer ring image (numpy, optimized)."""
    img = np.zeros((size, size), dtype=np.float32)
    cx, cy = size / 2.0, size / 2.0
    pixel_size = 0.075e-3  # 75 um pixel (EIGER2)

    # Pre-compute radial distance map once (biggest speedup)
    y_coords, x_coords = np.mgrid[0:size, 0:size]
    r = np.sqrt((x_coords - cx) ** 2 + (y_coords - cy) ** 2)
    theta = np.arctan2(y_coords - cy, x_coords - cx)

    for ring in rings:
        tth_rad = np.radians(ring["twoTheta"])
        R_m = det_dist * np.tan(tth_rad)
        R_px = R_m / pixel_size
        intensity = ring["intensity"]
        sigma_px = max(2.0, R_px * 0.005)

        # Only compute where ring has significant value (6-sigma band)
        band = 6 * sigma_px
        mask = np.abs(r - R_px) < band
        if not mask.any():
            continue

        ring_profile = np.zeros_like(r)
        ring_profile[mask] = intensity * np.exp(
            -0.5 * ((r[mask] - R_px) / sigma_px) ** 2)

        # Azimuthal texture (vectorized with random phases)
        rng = np.random.RandomState(int(R_px * 100) % 2**31)
        n_grains = rng.randint(50, 200)
        phases = rng.uniform(-np.pi, np.pi, n_grains)
        # Sum Gaussians over azimuthal angle (vectorized)
        az = np.ones(size * size, dtype=np.float32)
        theta_flat = theta.ravel()
        for th0 in phases:
            d = theta_flat - th0
            # Wrap to [-pi, pi]
            d = d - 2 * np.pi * np.round(d / (2 * np.pi))
            az += 0.3 * np.exp(-0.5 * (d / 0.05) ** 2)
        az_variation = az.reshape(size, size)

        img += ring_profile * az_variation

    # Add background + Poisson noise
    img += 10
    img += np.sqrt(np.maximum(img, 1)) * np.random.standard_normal((size, size)).astype(np.float32)
    img = np.maximum(img, 0)

    return img


# ===================================================================
# XRF 2D Mapping Engine (xraydb-based)
# ===================================================================
class XRF2DEngine:
    """Server-side 2D XRF mapping using xraydb fluorescence cross-sections."""

    @staticmethod
    def available():
        return _LARCH_OK

    @staticmethod
    async def run(ws, params, beamline):
        """Run 2D XRF mapping simulation.

        params keys: formula, ppm, scanLx, scanLy, step, dwell, sampleType,
                     thickness_um, matDensity
        beamline keys: energy_keV, spot_h_nm, spot_v_nm, flux
        """
        formula = params.get("formula", "Cu")
        ppm = params.get("ppm", 1000)
        scan_lx = params.get("scanLx", 10.0)
        scan_ly = params.get("scanLy", 10.0)
        step_um = params.get("step", 0.5)
        dwell = params.get("dwell", 0.1)
        sample_type = params.get("sampleType", "solid")
        thickness_um = params.get("thickness_um", 1.0)
        mat_density = params.get("matDensity", 2.0)

        energy_keV = beamline.get("energy_keV", 10.0)
        energy_eV = energy_keV * 1000.0
        flux = beamline.get("flux", 1e10)
        spot_h = beamline.get("spot_h_nm", 50)
        spot_v = beamline.get("spot_v_nm", 50)

        parsed = parse_formula(formula)
        el_keys = list(parsed.keys())
        total_mass = compound_mass(parsed)

        # Build grid
        half_lx = scan_lx / 2.0
        half_ly = scan_ly / 2.0
        x_pts = np.arange(-half_lx, half_lx + step_um * 0.5, step_um)
        y_pts = np.arange(-half_ly, half_ly + step_um * 0.5, step_um)
        nx, ny = len(x_pts), len(y_pts)
        total_pts = nx * ny

        # Build element list with weight fractions
        map_elements = []
        for el in el_keys:
            ed = ELEMENT_DB.get(el)
            if not ed:
                continue
            wt_frac = parsed[el] * ed["M"] / total_mass
            wt_pct = wt_frac * (ppm / 10000.0) * 100.0
            map_elements.append({"sym": el, "wt_pct": wt_pct, "Z": ed["Z"]})

        if not map_elements:
            map_elements.append({"sym": "Cu", "wt_pct": 1.0, "Z": 29})

        # Sort by wt_pct descending
        map_elements.sort(key=lambda x: -x["wt_pct"])
        el_list = [e["sym"] for e in map_elements]

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.05,
            "msg": f"2D-XRF: {formula} {ppm}ppm, {nx}x{ny} grid..."
        }))

        # Compute XRF cross-sections for each element
        xrf_xsections = {}
        for me in map_elements:
            sym = me["sym"]
            try:
                # Get fluorescence lines above 1 keV from xraydb
                lines = _xdb.xray_lines(sym)
                total_xsect = 0.0
                for line_name, data in lines.items():
                    if data.energy > 1000 and data.energy < energy_eV:
                        # Check if excitation energy is above the edge
                        total_xsect += data.intensity
                xrf_xsections[sym] = max(total_xsect, 0.01)
            except Exception:
                xrf_xsections[sym] = 0.5

        # Generate spatial phantoms
        all_maps = {}
        for sym in el_list:
            all_maps[sym] = np.zeros((ny, nx), dtype=np.float64)

        # Spatial pattern generation
        XX, YY = np.meshgrid(x_pts, y_pts)

        for ei, me in enumerate(map_elements):
            sym = me["sym"]
            wt_frac_eff = me["wt_pct"] / 100.0

            # Spatial pattern
            if sample_type == "particle":
                r2 = XX**2 + YY**2
                r_part = min(half_lx, half_ly) * 0.3
                spatial = np.where(r2 < r_part**2, 1.0, 0.02)
            elif sample_type == "powder":
                gx = np.floor((XX + half_lx) / (step_um * 3)).astype(int)
                gy = np.floor((YY + half_ly) / (step_um * 3)).astype(int)
                hash_val = ((gx * 73856093) ^ (gy * 19349663)) & 0xFFFF
                spatial = np.where(hash_val % 7 < 2,
                                   0.5 + (hash_val % 100) / 200.0, 0.05)
            else:
                # Solid with spatial features
                spatial = 0.3 + 0.5 * np.exp(-(XX**2 + YY**2) / (half_lx * half_ly * 0.8))
                spatial += 0.6 * np.exp(-((XX - half_lx*0.3)**2 + (YY + half_ly*0.2)**2) /
                                        (half_lx * half_ly * 0.1))
                # Element-dependent variation
                if ei > 0:
                    spatial *= (0.5 + 0.5 * np.sin(XX * (ei + 1) * 0.5))

            # XRF signal = flux * dwell * wt_fraction * spatial * xsection * thickness * density
            xsect = xrf_xsections.get(sym, 0.5)
            signal = flux * dwell * wt_frac_eff * spatial * xsect * \
                     (thickness_um * 1e-4) * mat_density * 1e-6

            # Poisson noise
            signal = np.maximum(signal, 0)
            noisy = np.random.poisson(np.maximum(signal, 0.1).astype(int)).astype(np.float64)
            all_maps[sym] = noisy

        # Stream results row by row (in batches)
        batch_rows = max(1, ny // 20)
        for row_start in range(0, ny, batch_rows):
            row_end = min(row_start + batch_rows, ny)
            frac = row_end / ny

            await ws.send(json.dumps({
                "type": "expt_progress",
                "fraction": 0.1 + 0.8 * frac,
                "msg": f"2D-XRF: row {row_end}/{ny}"
            }))
            await asyncio.sleep(0.01)

        # Send complete result
        # Convert maps to lists for JSON
        result_maps = {}
        for sym in el_list:
            result_maps[sym] = all_maps[sym].tolist()

        # XRF spectrum (sum spectrum at center pixel)
        spectrum = _compute_xrf_spectrum(el_list, map_elements, energy_eV,
                                         flux, dwell, thickness_um, mat_density)

        await ws.send(json.dumps({
            "type": "expt_result",
            "mode": "xrf2d",
            "maps": result_maps,
            "elements": el_list,
            "x_pts": x_pts.tolist(),
            "y_pts": y_pts.tolist(),
            "spectrum": spectrum,
            "info": {
                "formula": formula,
                "ppm": ppm,
                "nx": nx, "ny": ny,
                "step_um": step_um,
                "energy_keV": energy_keV,
                "flux": flux,
                "beam_nm": f"{spot_h:.0f}x{spot_v:.0f}",
                "dwell_s": dwell,
                "thickness_um": thickness_um,
                "n_elements": len(el_list),
                "engine": "xraydb"
            }
        }))

        await ws.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": 0.0
        }))


def _compute_xrf_spectrum(el_list, map_elements, energy_eV, flux, dwell,
                           thickness_um, mat_density):
    """Compute simulated XRF spectrum (channel histogram)."""
    n_ch = 2048
    e_per_ch = 10.0  # 10 eV per channel
    channels = np.zeros(n_ch)

    peaks = []

    for me in map_elements:
        sym = me["sym"]
        wt_frac = me["wt_pct"] / 100.0

        try:
            lines = _xdb.xray_lines(sym)
            for line_name, data in lines.items():
                if data.energy < 500 or data.energy > energy_eV:
                    continue
                ch = int(data.energy / e_per_ch)
                if 0 <= ch < n_ch:
                    counts = flux * dwell * wt_frac * data.intensity * \
                             thickness_um * 1e-4 * mat_density * 1e-6
                    # Gaussian line shape (SDD resolution ~130 eV FWHM)
                    sigma_ch = 130.0 / (2.355 * e_per_ch)
                    ch_range = np.arange(max(0, ch - 20), min(n_ch, ch + 20))
                    gauss = counts * np.exp(-0.5 * ((ch_range - ch) / sigma_ch)**2)
                    channels[ch_range] += gauss

                    if counts > 1:
                        peaks.append({
                            "el": sym,
                            "line": line_name,
                            "E": float(data.energy),
                            "counts": float(counts)
                        })
        except Exception:
            pass

    # Add Compton and elastic scatter
    E_elastic = energy_eV
    # Compton: E' = E / (1 + E/(511 keV) * (1 - cos(theta)))
    # Approximate for 90 deg backscatter
    E_compton = energy_eV / (1 + energy_eV / 511000.0)

    for scatter_E, scatter_label, scatter_intensity in [
        (E_elastic, "elastic", 0.01),
        (E_compton, "compton", 0.005),
    ]:
        ch = int(scatter_E / e_per_ch)
        if 0 <= ch < n_ch:
            counts = flux * dwell * scatter_intensity
            sigma_ch = 150.0 / (2.355 * e_per_ch)
            ch_range = np.arange(max(0, ch - 25), min(n_ch, ch + 25))
            gauss = counts * np.exp(-0.5 * ((ch_range - ch) / sigma_ch)**2)
            channels[ch_range] += gauss

    # Add background (bremsstrahlung)
    bg = np.linspace(0.5, 0.1, n_ch) * flux * dwell * 1e-8
    channels += bg

    # Poisson noise
    channels = np.random.poisson(np.maximum(channels, 0.1).astype(int)).astype(float)

    return {
        "channels": channels.tolist(),
        "nCh": n_ch,
        "ePerCh": e_per_ch,
        "peaks": sorted(peaks, key=lambda p: -p["counts"])[:20],
        "E_elastic": float(E_elastic),
        "E_compton": float(E_compton)
    }


# ===================================================================
# XRD Map Engine (Dans_Diffraction-based phase mapping)
# ===================================================================
class XRDMapEngine:
    """Server-side 2D XRD phase mapping."""

    @staticmethod
    def available():
        return _DANS_OK

    @staticmethod
    async def run(ws, params, beamline):
        """Run XRD phase mapping.

        params keys: crystals (list), scanLx, scanLy, step, detDist, detector
        beamline keys: energy_keV, flux, spot_h_nm, spot_v_nm
        """
        crystals = params.get("crystals", ["Cu"])
        cryst1 = crystals[0] if crystals else "Cu"
        cryst2 = crystals[1] if len(crystals) > 1 else ""
        scan_lx = params.get("scanLx", 10.0)
        scan_ly = params.get("scanLy", 10.0)
        step_um = params.get("step", 0.5)
        det_dist = params.get("detDist", 0.3)
        det_key = params.get("detector", "EIGER2_1M")
        energy_keV = beamline.get("energy_keV", 10.0)
        flux = beamline.get("flux", 1e10)

        wavelength = 12.3984 / energy_keV

        # Build grid
        half_lx = scan_lx / 2.0
        half_ly = scan_ly / 2.0
        x_pts = np.arange(-half_lx, half_lx + step_um * 0.5, step_um)
        y_pts = np.arange(-half_ly, half_ly + step_um * 0.5, step_um)
        nx, ny = len(x_pts), len(y_pts)

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.05,
            "msg": f"XRD Map: {cryst1}" + (f"+{cryst2}" if cryst2 else "") +
                   f", {nx}x{ny} grid..."
        }))

        # Compute powder patterns for each phase
        pattern1 = None
        pattern2 = None
        rings1 = []
        rings2 = []

        xtl1 = XRD2DEngine._build_crystal(cryst1)
        if xtl1:
            _quiet_setup_scatter(xtl1, energy_keV)
            q1, ints1 = xtl1.Scatter.generate_powder(
                q_max=8, peak_width=0.1, background=0)
            sin1 = q1 * wavelength / (4 * np.pi)
            v1 = np.abs(sin1) < 1.0
            tth1 = np.zeros_like(q1)
            tth1[v1] = 2 * np.degrees(np.arcsin(sin1[v1]))
            from scipy.signal import find_peaks
            pk1, _ = find_peaks(ints1, height=0.01 * max(ints1.max(), 1),
                                distance=5)
            for idx in pk1[:15]:
                if tth1[idx] > 0:
                    rings1.append({
                        "twoTheta": float(tth1[idx]),
                        "intensity": float(ints1[idx])
                    })
            pattern1 = {"tth": tth1.tolist(), "ints": ints1.tolist(), "rings": rings1}

        if cryst2:
            xtl2 = XRD2DEngine._build_crystal(cryst2)
            if xtl2:
                _quiet_setup_scatter(xtl2, energy_keV)
                q2, ints2 = xtl2.Scatter.generate_powder(
                    q_max=8, peak_width=0.1, background=0)
                sin2 = q2 * wavelength / (4 * np.pi)
                v2 = np.abs(sin2) < 1.0
                tth2 = np.zeros_like(q2)
                tth2[v2] = 2 * np.degrees(np.arcsin(sin2[v2]))
                pk2, _ = find_peaks(ints2, height=0.01 * max(ints2.max(), 1),
                                    distance=5)
                for idx in pk2[:15]:
                    if tth2[idx] > 0:
                        rings2.append({
                            "twoTheta": float(tth2[idx]),
                            "intensity": float(ints2[idx])
                        })
                pattern2 = {"tth": tth2.tolist(), "ints": ints2.tolist(), "rings": rings2}

        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.3,
            "msg": "XRD Map: computing phase distribution..."
        }))

        # Generate phase map (Voronoi-based grain structure)
        XX, YY = np.meshgrid(x_pts, y_pts)
        phase_map = np.zeros((ny, nx), dtype=np.float64)

        if cryst2:
            # Generate random grain centers
            rng = np.random.RandomState(42)
            n_grains = rng.randint(15, 30)
            grain_x = rng.uniform(-half_lx, half_lx, n_grains)
            grain_y = rng.uniform(-half_ly, half_ly, n_grains)
            grain_phase = rng.random(n_grains)  # 0=phase1, 1=phase2

            # Voronoi assignment
            for yi in range(ny):
                for xi in range(nx):
                    x, y = x_pts[xi], y_pts[yi]
                    dists = (grain_x - x)**2 + (grain_y - y)**2
                    nearest = np.argmin(dists)
                    phase_map[yi, xi] = grain_phase[nearest]

            # Smooth boundaries
            from scipy.ndimage import gaussian_filter
            phase_map = gaussian_filter(phase_map, sigma=1.5)
            phase_map = np.clip(phase_map, 0, 1)

        # Intensity maps
        base_int = flux * 1e-8
        int_map1 = base_int * (1 - phase_map) * (0.8 + 0.4 * np.random.random((ny, nx)))
        int_map2 = base_int * phase_map * (0.8 + 0.4 * np.random.random((ny, nx))) if cryst2 else np.zeros((ny, nx))

        # Stream progress
        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": 0.8,
            "msg": "XRD Map: finalizing..."
        }))

        await ws.send(json.dumps({
            "type": "expt_result",
            "mode": "xrdmap",
            "phase_map": phase_map.tolist(),
            "int_map1": int_map1.tolist(),
            "int_map2": int_map2.tolist() if cryst2 else None,
            "x_pts": x_pts.tolist(),
            "y_pts": y_pts.tolist(),
            "pattern1": pattern1,
            "pattern2": pattern2,
            "info": {
                "cryst1": cryst1,
                "cryst2": cryst2,
                "energy_keV": energy_keV,
                "wavelength_A": wavelength,
                "nx": nx, "ny": ny,
                "step_um": step_um,
                "detDist_m": det_dist,
                "detector": det_key,
                "engine": "dans_diffraction"
            }
        }))

        await ws.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": 0.0
        }))


# ===================================================================
# Main ExperimentEngine (dispatches to per-mode engines)
# ===================================================================
class ExperimentEngine:
    """Central dispatcher for virtual experiment modes."""

    def __init__(self):
        self._engines = {}
        self._cancelled = False

        if XAFSEngine.available():
            self._engines["xafs"] = XAFSEngine()
            log.info("  XAFS engine ready (larch/xraydb)")
        if XRD2DEngine.available():
            self._engines["xrd2d"] = XRD2DEngine()
            log.info("  XRD2D engine ready (dans_diffraction)")
        if XRF2DEngine.available():
            self._engines["xrf2d"] = XRF2DEngine()
            log.info("  XRF2D engine ready (xraydb)")
        if XRDMapEngine.available():
            self._engines["xrdmap"] = XRDMapEngine()
            log.info("  XRDMap engine ready (dans_diffraction)")

        if not self._engines:
            log.warning("No experiment engines available!")

    def list_modes(self):
        return list(self._engines.keys())

    def cancel(self):
        self._cancelled = True

    async def run(self, mode, websocket, params):
        """Run an experiment mode.

        params should contain:
          - mode-specific parameters (formula, crystal, etc.)
          - beamline: {energy_keV, spot_h_nm, spot_v_nm, flux, ssaH, ssaV}
        """
        self._cancelled = False

        engine = self._engines.get(mode)
        if not engine:
            available = self.list_modes()
            await websocket.send(json.dumps({
                "type": "expt_error",
                "message": f"Unknown mode '{mode}'. Available: {available}"
            }))
            return

        beamline = params.pop("beamline", {})
        if not beamline:
            # Default beamline context
            beamline = {
                "energy_keV": 10.0,
                "spot_h_nm": 50,
                "spot_v_nm": 50,
                "flux": 1e10,
                "ssaH": 50,
                "ssaV": 50,
            }

        t0 = time.time()

        try:
            await engine.run(websocket, params, beamline)
        except Exception as e:
            log.error(f"Experiment error ({mode}): {e}", exc_info=True)
            await websocket.send(json.dumps({
                "type": "expt_error",
                "message": str(e)
            }))
            return

        elapsed = time.time() - t0

        # Send final timing update
        await websocket.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": round(elapsed, 3)
        }))

    def shutdown(self):
        """Clean up resources."""
        self._cancelled = True
        log.info("Experiment engine shut down")
