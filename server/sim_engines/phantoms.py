"""
phantoms.py -- Realistic Sample Phantom Generators (Python port)

Procedural 2D phantom maps for XRF/XRD simulation presets.
All generators are deterministic (seeded) and produce per-element spatial maps.

Faithfully ported from js/experiment/08_phantoms.js.  The xorshift128 PRNG,
integer hash, value-noise, FBM, and Voronoi helpers reproduce the *exact*
same numerical sequence as the JavaScript originals for any given seed.
"""

import math
import numpy as np

# ======================================================================
#  Deterministic PRNG  (xorshift128, matches the JS implementation)
# ======================================================================

def _phantom_rng(seed):
    """Return a dict with ``next()`` and ``next_int(max)`` callables.

    Uses xorshift128 -- four 32-bit state words initialised from *seed*
    via a simple LCG warm-up, identical to the JS ``_phantomRNG``.
    """
    # Force 32-bit signed int via & 0xFFFFFFFF then interpret as signed
    # We work in Python ints but mask to 32 bits where JS does ``| 0``.
    _mask = 0xFFFFFFFF

    s = [0, 0, 0, 0]
    s[0] = (int(seed) or 42) & _mask
    s[1] = (int(seed) * 1664525 + 1013904223) & _mask
    s[2] = (s[1] * 1664525 + 1013904223) & _mask
    s[3] = (s[2] * 1664525 + 1013904223) & _mask

    # Convert to signed 32-bit for XOR-shift arithmetic
    def _to_signed(v):
        v = v & _mask
        return v - 0x100000000 if v >= 0x80000000 else v

    # Initialise as signed
    for i in range(4):
        s[i] = _to_signed(s[i])

    def _next():
        t = s[3]
        # t ^= t << 11  (keep 32-bit)
        t = (t ^ ((t << 11) & _mask)) & _mask
        t = _to_signed(t)
        # t ^= t >>> 8  (unsigned right shift)
        t = t ^ ((t & _mask) >> 8)
        t = _to_signed(t)

        s[3] = s[2]
        s[2] = s[1]
        s[1] = s[0]

        s0 = s[0]
        # s0 ^= s0 >>> 19
        s0 = s0 ^ ((s0 & _mask) >> 19)
        s0 = _to_signed(s0)
        # s0 ^= t
        s0 = _to_signed(s0 ^ t)
        s[0] = s0

        return (s[0] & _mask) / 4294967296.0

    def _next_int(mx):
        return int(math.floor(_next() * mx))

    return {"next": _next, "next_int": _next_int}


# ======================================================================
#  Integer hash  (deterministic spatial lookup) -> [0, 1]
# ======================================================================

def _ihash(x, y, seed):
    """Deterministic hash of integer coordinates to [0, 1].

    Must replicate JS 32-bit signed integer overflow behaviour:
    ``(x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)`` etc.
    """
    _mask = 0xFFFFFFFF

    def _i32(v):
        """Truncate to 32-bit signed integer (JS ``| 0``)."""
        v = int(v) & _mask
        return v - 0x100000000 if v >= 0x80000000 else v

    x = int(x)
    y = int(y)
    seed = int(seed)

    # First combine -- JS ``& 0x7FFFFFFF``
    h = ((x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)) & 0x7FFFFFFF

    # Two rounds of mixing -- JS ``| 0`` after each multiply
    h = _i32(((_i32((h >> 16) ^ h)) * 0x45d9f3b))
    h = _i32(((_i32((h >> 16) ^ h)) * 0x45d9f3b))
    h = _i32((h >> 16) ^ h)

    return (h & 0x7FFFFFFF) / 2147483647.0


# ======================================================================
#  2D Value noise  (bilinear interpolation of hashed grid)
# ======================================================================

def _value_noise_2d(x, y, freq, seed):
    fx = x * freq
    fy = y * freq
    ix = int(math.floor(fx))
    iy = int(math.floor(fy))
    tx = fx - ix
    ty = fy - iy
    # Smoothstep
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)

    v00 = _ihash(ix,     iy,     seed)
    v10 = _ihash(ix + 1, iy,     seed)
    v01 = _ihash(ix,     iy + 1, seed)
    v11 = _ihash(ix + 1, iy + 1, seed)

    return (v00 * (1 - tx) + v10 * tx) * (1 - ty) + \
           (v01 * (1 - tx) + v11 * tx) * ty


# ======================================================================
#  FBM  (fractal Brownian motion)
# ======================================================================

def _fbm_2d(x, y, octaves, freq, seed):
    val = 0.0
    amp = 1.0
    total_amp = 0.0
    for o in range(octaves):
        val += amp * _value_noise_2d(x, y, freq, seed + o * 97)
        total_amp += amp
        freq *= 2.0
        amp *= 0.5
    return val / total_amp


# ======================================================================
#  Voronoi tessellation
# ======================================================================

def _build_voronoi_centers(n_cells, seed, w, h, ox, oy):
    """Build a list of Voronoi centre dicts ``{x, y}``."""
    rng = _phantom_rng(seed)
    centers = []
    for _ in range(n_cells):
        centers.append({"x": rng["next"]() * w + ox,
                        "y": rng["next"]() * h + oy})
    return centers


def _query_voronoi(x, y, centers):
    """Find nearest Voronoi centre; return id, distCenter, distEdge."""
    best_d = float("inf")
    best_d2 = float("inf")
    best_id = 0
    for c in range(len(centers)):
        dx = x - centers[c]["x"]
        dy = y - centers[c]["y"]
        d2 = dx * dx + dy * dy
        if d2 < best_d:
            best_d2 = best_d
            best_d = d2
            best_id = c
        elif d2 < best_d2:
            best_d2 = d2
    return {
        "id": best_id,
        "dist_center": math.sqrt(best_d),
        "dist_edge": (math.sqrt(best_d2) - math.sqrt(best_d)) * 0.5,
    }


# ======================================================================
#  Helper: allocate per-element 2D maps as numpy arrays
# ======================================================================

def _alloc_maps(elems, n_x, n_y):
    """Return ``{element: np.zeros((nY, nX), dtype=np.float64)}``."""
    return {el: np.zeros((n_y, n_x), dtype=np.float64) for el in elems}


# ======================================================================
#  XRF Phantom Generators
# ======================================================================

# -- 1. Semiconductor IC cross-section ---------------------------------
# Models a realistic BEOL (back-end-of-line) cross-section inspired by
# advanced 14nm-class technology nodes: 7 metal layers with hierarchical
# pitch (M1 finest, M7 widest), staggered line offsets between adjacent
# layers, W vias at proper line intersections, Co cap layers on Cu lines,
# Ti/TiN barrier liner at Cu sidewalls, and SiO2/low-k ILD matrix.

def _phantom_semiconductor_ic(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Cu", "W", "Co", "Ti", "Si"], n_x, n_y)

    # 7 metal layers with hierarchical pitch (bottom = finest, top = widest)
    layers = [
        {"y_frac": 0.04, "h": 0.035, "pitch": 0.055, "duty": 0.45},  # M1
        {"y_frac": 0.10, "h": 0.040, "pitch": 0.055, "duty": 0.48},  # M2
        {"y_frac": 0.17, "h": 0.045, "pitch": 0.075, "duty": 0.48},  # M3
        {"y_frac": 0.26, "h": 0.050, "pitch": 0.10,  "duty": 0.50},  # M4
        {"y_frac": 0.37, "h": 0.060, "pitch": 0.14,  "duty": 0.50},  # M5
        {"y_frac": 0.50, "h": 0.075, "pitch": 0.20,  "duty": 0.52},  # M6
        {"y_frac": 0.66, "h": 0.095, "pitch": 0.30,  "duty": 0.55},  # M7
    ]

    # Staggered offsets: each layer shifted by half-pitch from previous
    for li in range(len(layers)):
        layers[li]["x_off"] = (li % 2) * layers[li]["pitch"] * 0.5

    for yi in range(n_y):
        for xi in range(n_x):
            nx = xi / max(1, n_x - 1)
            ny = yi / max(1, n_y - 1)
            cu_val = 0.0
            w_val = 0.0
            co_val = 0.0
            ti_val = 0.0
            si_val = 1.0
            in_metal = False

            for li, ly in enumerate(layers):
                if ny > ly["y_frac"] and ny < ly["y_frac"] + ly["h"]:
                    x_shifted = nx + ly["x_off"]
                    x_mod = (x_shifted % ly["pitch"]) / ly["pitch"]
                    if x_mod < ly["duty"]:
                        in_metal = True
                        cu_val = 0.82 + 0.15 * _value_noise_2d(
                            nx, ny, 25, seed + li)
                        # Co cap: thin top border of each Cu line
                        in_band = ny - ly["y_frac"]
                        if in_band < ly["h"] * 0.07:
                            co_val = max(co_val, 0.65)
                            cu_val *= 0.3
                        # Ti/TiN barrier: thin side edges
                        edge_dist = min(
                            x_mod, ly["duty"] - x_mod) * ly["pitch"]
                        if edge_dist < 0.006:
                            ti_val = max(ti_val, 0.50)
                            cu_val *= 0.2
                        si_val = 0.04

            # W vias between adjacent layers at line intersections
            if not in_metal:
                for vi in range(len(layers) - 1):
                    v_top = layers[vi]["y_frac"] + layers[vi]["h"]
                    v_bot = layers[vi + 1]["y_frac"]
                    if ny > v_top and ny < v_bot:
                        via_pitch = layers[vi + 1]["pitch"]
                        via_w_frac = 0.12
                        x_shifted = nx + layers[vi]["x_off"]
                        v_mod = (x_shifted % via_pitch) / via_pitch
                        if v_mod < via_w_frac:
                            w_val = 0.72 + 0.25 * _ihash(
                                xi, yi, seed + 100 + vi)
                            ti_val = max(ti_val, 0.18)
                            si_val = 0.04

            # Si/SiO2 ILD with texture (voids, porosity)
            si_val *= (0.65 + 0.35 * _fbm_2d(nx, ny, 3, 10, seed + 200))

            maps["Cu"][yi, xi] = cu_val
            maps["W"][yi, xi] = w_val
            maps["Co"][yi, xi] = co_val
            maps["Ti"][yi, xi] = ti_val
            maps["Si"][yi, xi] = si_val

    return maps


# -- 2. Battery NMC622 cathode -----------------------------------------
# Models a Li-ion battery cathode composed of NMC622 (LiNi0.6Mn0.2Co0.2O2)
# secondary particles with cycling degradation features:
#   - Ni core-shell gradient (surface enrichment from cycling)
#   - Mn decreasing toward surface (leaching during cycling)
#   - Co slightly enriched at core
#   - Radial intergranular cracks (cycling-induced mechanical degradation)
#   - NiO rock-salt surface degradation layer
#   - Fe impurities at grain boundaries and crack surfaces
#   - Cu contamination hotspots from current collector dissolution

def _phantom_battery_nmc(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Ni", "Mn", "Co", "Fe", "Cu"], n_x, n_y)
    rng = _phantom_rng(seed)
    n_parts = 8 + rng["next_int"](5)  # 8-12 secondary particles
    particles = []
    for _ in range(n_parts):
        particles.append({
            "cx": rng["next"]() * scan_w + x_p[0],
            "cy": rng["next"]() * scan_h + y_p[0],
            "r":  1.5 + rng["next"]() * 4.0,       # 1.5-5.5 um radius
            "ni_grad": 0.4 + rng["next"]() * 0.6,
            "shape_seed": rng["next_int"](10000),
            "n_cracks": 3 + rng["next_int"](4),     # 3-6 radial cracks
            "crack_seed": rng["next_int"](10000),
        })

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            ni_val = 0.0
            mn_val = 0.0
            co_val = 0.0
            fe_val = 0.0
            cu_val = 0.0
            in_part = False

            for pi2, pp in enumerate(particles):
                dx = px - pp["cx"]
                dy = py - pp["cy"]
                dist = math.sqrt(dx * dx + dy * dy)
                # Perturbed radius for irregular particle shape
                angle = math.atan2(dy, dx)
                r_perturbed = pp["r"] * (1.0 + 0.12 * _fbm_2d(
                    angle * 2, pi2, 3, 2, pp["shape_seed"]))
                if dist >= r_perturbed:
                    continue

                in_part = True
                r_norm = dist / r_perturbed

                # Check if pixel is in a radial intergranular crack
                in_crack = False
                crack_rng = _phantom_rng(pp["crack_seed"])
                for _ci in range(pp["n_cracks"]):
                    crack_angle = crack_rng["next"]() * math.pi * 2
                    crack_w = 0.015 + crack_rng["next"]() * 0.01
                    da = angle - crack_angle
                    # Normalize to -pi..pi
                    if da > math.pi:
                        da -= 2.0 * math.pi
                    if da < -math.pi:
                        da += 2.0 * math.pi
                    # Cracks visible only in outer 75% of particle
                    if r_norm > 0.25 and abs(da) < crack_w:
                        in_crack = True
                        break

                if in_crack:
                    # Crack: depleted signal with Fe enrichment at surfaces
                    crack_int = (r_norm - 0.25) / 0.75
                    ni_val = max(ni_val, 0.05)
                    mn_val = max(mn_val, 0.02)
                    co_val = max(co_val, 0.02)
                    fe_val = max(fe_val, 0.18 * crack_int)
                    continue

                # Primary grain texture (sub-micron grains)
                grain_noise = _fbm_2d(px * 3, py * 3, 2, 4,
                                      seed + pi2 * 7)

                # Ni: enriched at surface (cycling degradation)
                ni_val = max(ni_val,
                    (0.35 + 0.65 * r_norm * pp["ni_grad"]) *
                    (0.85 + 0.15 * grain_noise))

                # NiO rock-salt surface layer (Ni2+ enrichment)
                if r_norm > 0.92:
                    ni_val = max(ni_val, 0.95)

                # Mn: decreases toward surface (leaching during cycling)
                mn_val = max(mn_val,
                    (0.75 - 0.35 * r_norm) *
                    (0.9 + 0.1 * grain_noise))

                # Co: slight core enrichment
                co_val = max(co_val,
                    (0.55 + 0.45 * (1 - r_norm * 0.5)) *
                    (0.85 + 0.15 * grain_noise))

                # Fe at grain boundaries
                gb_prox = 1.0 - 4.0 * abs(grain_noise - 0.5)
                if gb_prox > 0.6 and r_norm > 0.3:
                    fe_val = max(fe_val, gb_prox * 0.25)

                # Cu contamination: sparse hotspots
                if _ihash(xi, yi, seed + 500) > 0.97:
                    cu_val = max(cu_val,
                        0.15 + _ihash(xi, yi, seed + 501) * 0.3)

            if not in_part:
                # Binder/carbon background
                ni_val = 0.01 * _value_noise_2d(px, py, 1, seed + 300)
                mn_val = 0.008
                co_val = 0.008

            maps["Ni"][yi, xi] = ni_val
            maps["Mn"][yi, xi] = mn_val
            maps["Co"][yi, xi] = co_val
            maps["Fe"][yi, xi] = fe_val
            maps["Cu"][yi, xi] = cu_val

    return maps


# -- 3. Geological thin section -----------------------------------------
# Models a polished geological thin section with Voronoi-based mineral
# grains.  Mineral types: quartz, feldspar, garnet (concentric zoning),
# pyroxene, mica.  Includes grain-boundary enrichment, a fracture zone,
# and random micro-inclusions of Ni-Cu and Cr.

def _phantom_geological(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    elems = ["Fe", "Ti", "Mn", "Cr", "Ni", "Cu", "Zn", "Sr", "As"]
    maps = _alloc_maps(elems, n_x, n_y)
    rng = _phantom_rng(seed)

    # Voronoi grains (20-40)
    n_grains = 20 + rng["next_int"](20)
    centers = _build_voronoi_centers(n_grains, seed + 10, scan_w, scan_h,
                                     x_p[0], y_p[0])
    # Mineral types: 0=quartz, 1=feldspar, 2=garnet, 3=pyroxene, 4=mica
    mineral_types = []
    for _ in range(n_grains):
        r = rng["next"]()
        if r < 0.30:
            mineral_types.append(0)
        elif r < 0.55:
            mineral_types.append(1)
        elif r < 0.70:
            mineral_types.append(2)
        elif r < 0.85:
            mineral_types.append(3)
        else:
            mineral_types.append(4)

    # Fracture line
    frac_angle = 0.3 + rng["next"]() * 0.4
    frac_cos = math.cos(frac_angle)
    frac_sin = math.sin(frac_angle)
    frac_offset = (0.3 + rng["next"]() * 0.4) * scan_w + x_p[0]

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            vor = _query_voronoi(px, py, centers)
            g_id = vor["id"]
            d_edge = vor["dist_edge"]
            mineral = mineral_types[g_id]
            is_gb = d_edge < 0.15

            fe = 0.0
            ti = 0.0
            mn = 0.0
            cr = 0.0
            ni = 0.0
            cu = 0.0
            zn = 0.0
            sr = 0.0
            as_ = 0.0

            if mineral == 0:  # Quartz
                sr = 0.02 + 0.01 * _value_noise_2d(px, py, 4, seed + g_id)
            elif mineral == 1:  # Feldspar
                sr = 0.3 + 0.1 * _value_noise_2d(px, py, 5, seed + g_id)
                fe = 0.05
            elif mineral == 2:  # Garnet -- concentric zoning
                gcx = centers[g_id]["x"]
                gcy = centers[g_id]["y"]
                dist_c = math.sqrt((px - gcx) ** 2 + (py - gcy) ** 2)
                zone_phase = math.sin(dist_c * 3.0)
                fe = 0.6 + 0.3 * zone_phase
                mn = 0.3 - 0.2 * zone_phase  # anticorrelated with Fe
                cr = 0.02 + 0.01 * _value_noise_2d(px, py, 6, seed + g_id + 50)
            elif mineral == 3:  # Pyroxene
                fe = 0.4 + 0.2 * _value_noise_2d(px, py, 3, seed + g_id)
                mn = 0.1 + 0.05 * _value_noise_2d(px, py, 3, seed + g_id + 10)
                ti = 0.05
            else:  # Mica
                fe = 0.3 + 0.1 * _value_noise_2d(px, py, 4, seed + g_id)
                ti = 0.15 + 0.1 * _value_noise_2d(px, py, 5, seed + g_id + 20)

            # Grain boundary enrichment
            if is_gb:
                fe += 0.15
                cu += 0.05 * _ihash(xi, yi, seed + 600)
                zn += 0.03

            # Fracture zone
            frac_dist = abs((px - x_p[0]) * frac_cos -
                            (py - y_p[0]) * frac_sin - frac_offset)
            if frac_dist < 0.3:
                fe *= 0.2
                cu += 0.1
                as_ += 0.05

            # Tiny random inclusions
            if _ihash(xi, yi, seed + 700) > 0.98:
                ni += 0.3
                cu += 0.2
            if _ihash(xi, yi, seed + 800) > 0.99:
                cr += 0.5

            maps["Fe"][yi, xi] = fe
            maps["Ti"][yi, xi] = ti
            maps["Mn"][yi, xi] = mn
            maps["Cr"][yi, xi] = cr
            maps["Ni"][yi, xi] = ni
            maps["Cu"][yi, xi] = cu
            maps["Zn"][yi, xi] = zn
            maps["Sr"][yi, xi] = sr
            maps["As"][yi, xi] = as_

    return maps


# -- 4. Biological cell ------------------------------------------------
# Models a single eukaryotic cell with:
#   - Irregular cell membrane (FBM-perturbed circle)
#   - Off-centre nucleus enriched in Zn (chromatin) with fine texture
#   - Fe-rich mitochondria (elongated ellipsoidal blobs)
#   - Zn-containing vesicles scattered in the cytoplasm
#   - Uniform Se background (selenoproteins, barely detectable)
#   - Cytoplasmic Cu (cuproenzymes)

def _phantom_bio_cell(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Fe", "Zn", "Cu", "Mn", "Se"], n_x, n_y)
    cx = scan_w / 2.0 + x_p[0]
    cy = scan_h / 2.0 + y_p[0]
    cell_r = min(scan_w, scan_h) * 0.40
    nucl_r = cell_r * 0.35
    nucl_cx = cx - cell_r * 0.1
    nucl_cy = cy + cell_r * 0.05

    # Mitochondria positions
    rng = _phantom_rng(seed)
    n_mito = 12 + rng["next_int"](8)
    mitos = []
    for _ in range(n_mito):
        a = rng["next"]() * math.pi * 2
        d = (0.3 + rng["next"]() * 0.5) * cell_r
        mitos.append({
            "x": cx + d * math.cos(a),
            "y": cy + d * math.sin(a),
            "angle": rng["next"]() * math.pi,
            "len": 0.4 + rng["next"]() * 1.2,
            "wid": 0.12 + rng["next"]() * 0.18,
        })

    # Zn vesicles
    n_ves = 18 + rng["next_int"](12)
    vesicles = []
    for _ in range(n_ves):
        a2 = rng["next"]() * math.pi * 2
        d2 = rng["next"]() * cell_r * 0.8
        vesicles.append({
            "x": cx + d2 * math.cos(a2),
            "y": cy + d2 * math.sin(a2),
            "r": 0.08 + rng["next"]() * 0.18,
        })

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            fe = 0.0
            zn = 0.0
            cu = 0.0
            mn = 0.0
            se = 0.0

            # Irregular cell boundary
            angle_pt = math.atan2(py - cy, px - cx)
            pert_r = cell_r * (1.0 + 0.12 * _fbm_2d(angle_pt * 3, 0, 3, 2,
                                                      seed + 100))
            dist_c = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if dist_c >= pert_r:
                continue

            # Cytoplasm Cu
            cu = 0.25 + 0.15 * _fbm_2d(px, py, 3, 2, seed + 200)

            # Nucleus
            dist_n = math.sqrt((px - nucl_cx) ** 2 + (py - nucl_cy) ** 2)
            if dist_n < nucl_r:
                zn += 0.6 + 0.2 * _fbm_2d(px * 3, py * 3, 2, 5, seed + 300)
                cu += 0.1
                mn += 0.02
                zn += 0.12 * abs(math.sin(px * 8 + py * 6))

            # Mitochondria (Fe-rich elongated blobs)
            for mi2 in range(n_mito):
                mdx = px - mitos[mi2]["x"]
                mdy = py - mitos[mi2]["y"]
                ca = math.cos(mitos[mi2]["angle"])
                sa = math.sin(mitos[mi2]["angle"])
                rx = ca * mdx + sa * mdy
                ry = -sa * mdx + ca * mdy
                ell_d = (rx / mitos[mi2]["len"]) ** 2 + \
                        (ry / mitos[mi2]["wid"]) ** 2
                if ell_d < 1.0:
                    fe += 0.7 * (1.0 - ell_d)
                    mn += 0.12 * (1.0 - ell_d)

            # Zn vesicles
            for vi2 in range(n_ves):
                vd = math.sqrt((px - vesicles[vi2]["x"]) ** 2 +
                               (py - vesicles[vi2]["y"]) ** 2)
                if vd < vesicles[vi2]["r"]:
                    zn += 0.8 * (1.0 - vd / vesicles[vi2]["r"])

            # Se: barely detectable (selenoproteins)
            se = 0.015 + 0.01 * _value_noise_2d(px, py, 2, seed + 400)

            maps["Fe"][yi, xi] = fe
            maps["Zn"][yi, xi] = zn
            maps["Cu"][yi, xi] = cu
            maps["Mn"][yi, xi] = mn
            maps["Se"][yi, xi] = se

    return maps


# -- 5. Catalyst NPs on support ----------------------------------------
# Models noble-metal nanoparticles (Pt, Au, bimetallic Pt-Au core-shell)
# dispersed on an Fe-oxide support particle with mesoporous structure.
# Ce decoration around NP perimeters models a CeO2 promoter.

def _phantom_catalyst_np(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Pt", "Au", "Fe", "Ce"], n_x, n_y)
    rng = _phantom_rng(seed)
    cx = scan_w / 2.0 + x_p[0]
    cy = scan_h / 2.0 + y_p[0]
    part_r = min(scan_w, scan_h) * 0.42

    # Support pore structure (Voronoi-based)
    n_pores = 8 + rng["next_int"](5)
    pore_centers = _build_voronoi_centers(n_pores, seed + 50,
                                          scan_w, scan_h, x_p[0], y_p[0])
    pore_radii = []
    for _ in range(n_pores):
        pore_radii.append(0.3 + rng["next"]() * 0.8)  # um

    # Nanoparticles scattered on support
    n_nps = 25 + rng["next_int"](20)
    nps = []
    for _ in range(n_nps):
        a = rng["next"]() * math.pi * 2
        d = rng["next"]() * part_r * 0.85
        npx = cx + d * math.cos(a)
        npy = cy + d * math.sin(a)
        np_r = 0.08 + rng["next"]() * 0.25  # 80-330 nm radius
        np_type = rng["next"]()  # 0-0.5 Pt, 0.5-0.8 bimetallic, 0.8-1 Au
        nps.append({"x": npx, "y": npy, "r": np_r, "type": np_type})

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            pt_val = 0.0
            au_val = 0.0
            fe_val = 0.0
            ce_val = 0.0

            # Irregular support particle boundary
            angle_pt = math.atan2(py - cy, px - cx)
            pert_r = part_r * (1.0 + 0.15 * _fbm_2d(angle_pt * 3, 0, 3, 2,
                                                      seed + 100))
            dist_c = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if dist_c >= pert_r:
                continue

            # Fe in support matrix
            fe_val = 0.15 + 0.1 * _fbm_2d(px * 2, py * 2, 3, 3, seed + 200)

            # Pores: low signal
            in_pore = False
            for pi2 in range(n_pores):
                pd = math.sqrt((px - pore_centers[pi2]["x"]) ** 2 +
                               (py - pore_centers[pi2]["y"]) ** 2)
                if pd < pore_radii[pi2]:
                    in_pore = True
                    break
            if in_pore:
                fe_val *= 0.1
                maps["Fe"][yi, xi] = fe_val
                continue

            # Nanoparticles
            for np_obj in nps:
                npd = math.sqrt((px - np_obj["x"]) ** 2 +
                                (py - np_obj["y"]) ** 2)
                if npd >= np_obj["r"]:
                    continue
                r_norm = npd / np_obj["r"]

                if np_obj["type"] < 0.5:
                    # Pure Pt NP
                    pt_val += 0.9 * (1.0 - r_norm)
                elif np_obj["type"] < 0.8:
                    # Core-shell: Pt core, Au shell
                    if r_norm < 0.5:
                        pt_val += 0.9 * (1.0 - r_norm * 2)
                    else:
                        au_val += 0.8 * ((r_norm - 0.5) * 2)
                        au_val = min(au_val, 0.8)
                else:
                    # Pure Au NP
                    au_val += 0.85 * (1.0 - r_norm)

                # Ce decoration around NPs
                if r_norm > 0.6 and r_norm < 1.3:
                    ce_val += 0.3 * (1.0 - abs(r_norm - 0.95) * 3)

            maps["Pt"][yi, xi] = min(1.0, pt_val)
            maps["Au"][yi, xi] = min(1.0, au_val)
            maps["Fe"][yi, xi] = fe_val
            maps["Ce"][yi, xi] = max(0.0, ce_val)

    return maps


# -- 6. Environmental particle (fly ash) --------------------------------
# Models a spheroidal fly-ash particle from coal combustion.  Features:
#   - Concentric compositional zones (core -> rim Fe enrichment from
#     post-depositional oxidation)
#   - Crystallite inclusions (TiO2 rutile, chromite, ZnO)
#   - Surface-adsorbed trace elements (As, Pb) on oxidation rim
#   - Provenance tracer (Sr)
#   - Scattered Cu hotspots (smelter emission signature)

def _phantom_env_particle(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    elems = ["Fe", "Ti", "Mn", "Cr", "Cu", "Zn", "As", "Pb", "Sr"]
    maps = _alloc_maps(elems, n_x, n_y)
    rng = _phantom_rng(seed)
    cx = scan_w / 2.0 + x_p[0]
    cy = scan_h / 2.0 + y_p[0]
    part_r = min(scan_w, scan_h) * 0.40

    # Embedded crystallite inclusions
    n_inc = 4 + rng["next_int"](4)
    inclusions = []
    for _ in range(n_inc):
        a = rng["next"]() * math.pi * 2
        d = rng["next"]() * part_r * 0.6
        el_type = rng["next_int"](3)  # 0=TiO2, 1=chromite, 2=ZnO
        inclusions.append({
            "x": cx + d * math.cos(a),
            "y": cy + d * math.sin(a),
            "r": 0.2 + rng["next"]() * 0.6,
            "type": el_type,
        })

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            fe = 0.0
            ti = 0.0
            mn2 = 0.0
            cr = 0.0
            cu = 0.0
            zn = 0.0
            as_ = 0.0
            pb = 0.0
            sr = 0.0

            # Irregular particle shape (FBM-perturbed)
            angle_pt = math.atan2(py - cy, px - cx)
            pert_r = part_r * (1.0 + 0.2 * _fbm_2d(angle_pt * 2.5, 0, 4, 2,
                                                     seed + 100))
            dist_c = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if dist_c >= pert_r:
                continue
            r_norm = dist_c / pert_r

            # Layered internal structure (concentric zones)
            zone = int(math.floor(r_norm * 4))  # 0=core,1=mid1,2=mid2,3=rim
            fe_base = [0.5, 0.6, 0.4, 0.8]  # Fe enriched at rim (oxidation)
            fe = fe_base[min(3, zone)] + \
                0.1 * _fbm_2d(px * 2, py * 2, 2, 3, seed + 200)

            # Mn: relatively uniform with slight texture
            mn2 = 0.15 + 0.05 * _value_noise_2d(px, py, 3, seed + 300)

            # Oxidation rim: Fe-enriched shell
            if r_norm > 0.8:
                fe += 0.3 * (r_norm - 0.8) / 0.2
                # Surface-adsorbed trace elements
                as_ = 0.08 * (r_norm - 0.8) / 0.2
                pb = 0.06 * (r_norm - 0.8) / 0.2

            # Provenance tracer
            sr = 0.03 + 0.02 * _value_noise_2d(px, py, 2, seed + 400)

            # Crystallite inclusions
            for inc in inclusions:
                inc_d = math.sqrt((px - inc["x"]) ** 2 +
                                  (py - inc["y"]) ** 2)
                if inc_d < inc["r"]:
                    inc_f = 1.0 - inc_d / inc["r"]
                    if inc["type"] == 0:
                        ti += 0.8 * inc_f      # TiO2
                    elif inc["type"] == 1:
                        cr += 0.6 * inc_f       # chromite
                    else:
                        zn += 0.5 * inc_f       # ZnO

            # Scattered Cu: smelter emission signature
            if _ihash(xi, yi, seed + 500) > 0.96:
                cu += 0.2

            maps["Fe"][yi, xi] = fe
            maps["Ti"][yi, xi] = ti
            maps["Mn"][yi, xi] = mn2
            maps["Cr"][yi, xi] = cr
            maps["Cu"][yi, xi] = cu
            maps["Zn"][yi, xi] = zn
            maps["As"][yi, xi] = as_
            maps["Pb"][yi, xi] = pb
            maps["Sr"][yi, xi] = sr

    return maps


# -- 7. Siemens star resolution test pattern ----------------------------
# Standard X-ray nanoprobe calibration pattern: 36 alternating Au/gap
# wedge spokes converging toward a central hub on Si3N4 membrane.
# Spoke width decreases linearly toward center, naturally testing
# spatial resolution.  Concentric calibration rings at 25/50/75/100%.

def _phantom_siemens_star(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Au", "Cr", "Si"], n_x, n_y)
    cx = scan_w / 2.0 + x_p[0]
    cy = scan_h / 2.0 + y_p[0]
    outer_r = min(scan_w, scan_h) * 0.43
    inner_r = outer_r * 0.025   # central unresolved hub
    n_spokes = 36
    ring_fracs = [0.25, 0.50, 0.75, 1.0]
    ring_w = outer_r * 0.012

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            dx = px - cx
            dy = py - cy
            dist = math.sqrt(dx * dx + dy * dy)

            # Si3N4 membrane background
            maps["Si"][yi, xi] = 0.05

            if dist > outer_r * 1.05:
                continue

            # Inside pattern area: higher Si from membrane
            maps["Si"][yi, xi] = 0.12

            if dist <= inner_r:
                # Central hub: solid Au
                maps["Au"][yi, xi] = 0.90
                maps["Cr"][yi, xi] = 0.08
                continue

            if dist > outer_r:
                continue

            # Spoke pattern using angular position
            angle = math.atan2(dy, dx)
            spoke_period = 2.0 * math.pi / n_spokes
            phase = ((angle + math.pi) % spoke_period) / spoke_period

            is_au = phase < 0.5

            if is_au:
                noise = 0.05 * _value_noise_2d(
                    px * 2, py * 2, 4, seed + 10)
                maps["Au"][yi, xi] = 0.82 + noise
                maps["Cr"][yi, xi] = 0.06  # adhesion layer

            # Concentric calibration rings (always Au)
            for rf in ring_fracs:
                ring_r = outer_r * rf
                if abs(dist - ring_r) < ring_w:
                    maps["Au"][yi, xi] = max(
                        maps["Au"][yi, xi], 0.75)
                    maps["Cr"][yi, xi] = max(
                        maps["Cr"][yi, xi], 0.05)

    return maps


# -- 8. Multi-element calibration grid ---------------------------------
# 4x4 array of single-element rectangular pads on Si substrate.
# Elements arranged in approximate order of increasing atomic number.
# Standard calibration sample for quantitative XRF at synchrotron
# nanoprobe beamlines.

def _phantom_calibration_grid(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    pad_elements = [
        "Ca", "Ti", "Cr", "Mn",
        "Fe", "Co", "Ni", "Cu",
        "Zn", "As", "Se", "Sr",
        "Au", "Pt", "Pb", "W",
    ]
    all_elems = list(set(pad_elements + ["Si"]))
    maps = _alloc_maps(all_elems, n_x, n_y)

    grid_n = 4
    margin = 0.10
    gap_frac = 0.18

    grid_x0 = x_p[0] + scan_w * margin
    grid_y0 = y_p[0] + scan_h * margin
    grid_w = scan_w * (1.0 - 2.0 * margin)
    grid_h = scan_h * (1.0 - 2.0 * margin)
    cell_w = grid_w / grid_n
    cell_h = grid_h / grid_n
    pad_half_w = cell_w * (1.0 - gap_frac) / 2.0
    pad_half_h = cell_h * (1.0 - gap_frac) / 2.0

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            # Si substrate everywhere
            maps["Si"][yi, xi] = 0.08

            rel_x = px - grid_x0
            rel_y = py - grid_y0

            if rel_x < 0 or rel_x >= grid_w:
                continue
            if rel_y < 0 or rel_y >= grid_h:
                continue

            gi = int(math.floor(rel_x / cell_w))
            gj = int(math.floor(rel_y / cell_h))

            if gi < 0 or gi >= grid_n or gj < 0 or gj >= grid_n:
                continue

            # Center of this cell
            cell_cx = grid_x0 + (gi + 0.5) * cell_w
            cell_cy = grid_y0 + (gj + 0.5) * cell_h

            adx = abs(px - cell_cx)
            ady = abs(py - cell_cy)

            if adx <= pad_half_w and ady <= pad_half_h:
                elem_idx = gj * grid_n + gi
                if elem_idx < len(pad_elements):
                    elem = pad_elements[elem_idx]
                    val = 0.70 + 0.15 * _value_noise_2d(
                        px, py, 8, seed + elem_idx * 17)
                    maps[elem][yi, xi] = val
                    maps["Si"][yi, xi] = 0.01  # suppressed under pad

    return maps


# ======================================================================
#  XRD Phase Map Phantom  (Voronoi grain structure)
# ======================================================================

def phantom_xrd_phase_map(n_x, n_y, x_p, y_p, cryst1, cryst2, seed=42):
    """Generate a two-phase Voronoi grain map for XRD scanning.

    Returns dict with:
      - ``phase_map``:  np.ndarray (nY, nX)  -- 0.0 = phase 1, 1.0 = phase 2
      - ``orient_map``: np.ndarray (nY, nX)  -- small angular offset per grain
      - ``n_grains``:   int
    Returns ``None`` if *cryst2* is falsy (single-phase sample).
    """
    seed = seed or 42
    if not cryst2:
        return None  # single-phase: no need for fancy map

    scan_w = x_p[n_x - 1] - x_p[0]
    scan_h = y_p[n_y - 1] - y_p[0]
    rng = _phantom_rng(seed)
    n_grains = 15 + rng["next_int"](15)
    centers = _build_voronoi_centers(n_grains, seed + 10,
                                     scan_w, scan_h, x_p[0], y_p[0])
    grain_phase = []
    grain_orient = []
    frac2 = 0.3 + rng["next"]() * 0.3

    for _ in range(n_grains):
        grain_phase.append(1 if rng["next"]() < frac2 else 0)
        grain_orient.append(rng["next"]() * 0.02 - 0.01)

    phase_map = np.zeros((n_y, n_x), dtype=np.float64)
    orient_map = np.zeros((n_y, n_x), dtype=np.float64)

    for yi in range(n_y):
        for xi in range(n_x):
            px = x_p[xi]
            py = y_p[yi]
            vor = _query_voronoi(px, py, centers)
            base_frac = grain_phase[vor["id"]]
            # Smooth transition at grain boundary
            if vor["dist_edge"] < 0.2:
                base_frac = base_frac * 0.7 + \
                    0.3 * _value_noise_2d(px, py, 10, seed + 99)
            phase_map[yi, xi] = base_frac
            orient_map[yi, xi] = grain_orient[vor["id"]] + \
                0.002 * _value_noise_2d(px, py, 5, seed + 50)

    return {
        "phase_map": phase_map,
        "orient_map": orient_map,
        "n_grains": n_grains,
    }


# ======================================================================
#  Dispatcher
# ======================================================================

_GENERATORS = {
    "semiconductor_ic":       _phantom_semiconductor_ic,
    "battery_nmc622":         _phantom_battery_nmc,
    "geological_section":     _phantom_geological,
    "biological_cell":        _phantom_bio_cell,
    "catalyst_nanoparticle":  _phantom_catalyst_np,
    "environmental_particle": _phantom_env_particle,
    "siemens_star":           _phantom_siemens_star,
    "calibration_grid":       _phantom_calibration_grid,
}


def phantom_spatial_maps(preset_key, n_x, n_y, x_p, y_p, seed=42):
    """Generate XRF element maps for the named phantom preset.

    Parameters
    ----------
    preset_key : str
        One of ``'semiconductor_ic'``, ``'battery_nmc622'``,
        ``'geological_section'``, ``'biological_cell'``,
        ``'catalyst_nanoparticle'``, ``'environmental_particle'``.
    n_x, n_y : int
        Number of scan points in X and Y.
    x_p, y_p : array-like of float
        Physical coordinates of scan points (length *n_x* and *n_y*).
    seed : int, optional
        Deterministic seed (default 42).

    Returns
    -------
    dict of {str: np.ndarray}
        Mapping from element symbol to a ``(n_y, n_x)`` float64 array,
        or ``None`` if *preset_key* is not recognised.
    """
    seed = seed or 42
    fn = _GENERATORS.get(preset_key)
    if fn is None:
        return None
    scan_w = x_p[n_x - 1] - x_p[0]
    scan_h = y_p[n_y - 1] - y_p[0]
    return fn(n_x, n_y, x_p, y_p, scan_w, scan_h, seed)
