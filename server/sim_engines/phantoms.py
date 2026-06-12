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
#  Vectorized helpers (numpy) -- same math as the scalar versions above,
#  evaluated over whole coordinate arrays so the phantom generators can run
#  on large fine grids without per-pixel Python loops. Results match the
#  scalar functions to floating-point precision (verified in tests).
# ======================================================================

_I32 = np.int64(0xFFFFFFFF)


def _i32_vec(v):
    """Truncate an int64 array to 32-bit signed (JS ``| 0``), vectorized.

    Casting the low 32 bits through int32 wraps modulo 2^32 in C semantics,
    giving the same signed value as ``where(x >= 2^31, x - 2^32, x)`` but
    without the extra comparison/select pass (verified bit-identical).
    """
    return (v & _I32).astype(np.int32).astype(np.int64)


_HASH_A = np.int32(73856093)
_HASH_B = np.int32(19349663)
_HASH_C = np.int32(83492791)
_HASH_M = np.int32(0x45d9f3b)
_HASH_MASK = np.int32(0x7FFFFFFF)


def _ihash_vec(ix, iy, seed):
    """Vectorized ``_ihash`` for integer coordinate arrays -> float in [0,1].

    Computed in native int32 so the multiplies/shifts wrap modulo 2^32 exactly
    like the JS ``| 0`` truncation (verified bit-identical to the int64 form
    over random negative/large coordinates and scalar/array seeds). int32 is
    half the memory bandwidth of int64 and avoids the explicit 32-bit-truncation
    passes, which dominates cost on the ~1000x1000 fine grids. *seed* may be a
    scalar or an int array broadcastable to ix/iy (the geological phantom seeds
    noise per grain id).
    """
    ix = np.asarray(ix, dtype=np.int32)
    iy = np.asarray(iy, dtype=np.int32)
    if hasattr(seed, "__len__"):
        s = np.asarray(seed, dtype=np.int32)
    else:
        sv = int(seed) & 0xFFFFFFFF
        s = np.int32(sv if sv < 0x80000000 else sv - 0x100000000)
    with np.errstate(over="ignore"):   # int32 wraparound is intentional (== | 0)
        h = ((ix * _HASH_A) ^ (iy * _HASH_B) ^ (s * _HASH_C)) & _HASH_MASK
        h = ((h >> 16) ^ h) * _HASH_M
        h = ((h >> 16) ^ h) * _HASH_M
        h = (h >> 16) ^ h
        h = h & _HASH_MASK
    return h.astype(np.float64) / 2147483647.0


def _value_noise_2d_vec(x, y, freq, seed):
    """Vectorized bilinear value noise over coordinate arrays."""
    fx = x * freq
    fy = y * freq
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    tx = fx - ix
    ty = fy - iy
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    v00 = _ihash_vec(ix,     iy,     seed)
    v10 = _ihash_vec(ix + 1, iy,     seed)
    v01 = _ihash_vec(ix,     iy + 1, seed)
    v11 = _ihash_vec(ix + 1, iy + 1, seed)
    return (v00 * (1 - tx) + v10 * tx) * (1 - ty) + \
           (v01 * (1 - tx) + v11 * tx) * ty


def _fbm_2d_vec(x, y, octaves, freq, seed):
    """Vectorized fractal Brownian motion over coordinate arrays."""
    val = np.zeros_like(x, dtype=np.float64)
    amp = 1.0
    total_amp = 0.0
    f = float(freq)
    for o in range(octaves):
        val = val + amp * _value_noise_2d_vec(x, y, f, seed + o * 97)
        total_amp += amp
        f *= 2.0
        amp *= 0.5
    return val / total_amp


def _voronoi_fields(X, Y, centers):
    """Vectorized nearest/second-nearest Voronoi query over coordinate grids.

    X, Y: (H, W) coordinate arrays. centers: list of {x, y}.
    Returns (ids, dist_center, dist_edge) arrays, matching _query_voronoi:
      dist_edge = (second_nearest - nearest) * 0.5.
    """
    cx = np.array([c["x"] for c in centers], dtype=np.float64)
    cy = np.array([c["y"] for c in centers], dtype=np.float64)
    # distances^2 to every center: shape (H, W, ncenters) would be large, so
    # iterate centers but keep running nearest/second-nearest as arrays.
    H, W = X.shape
    best = np.full((H, W), np.inf)
    second = np.full((H, W), np.inf)
    ids = np.zeros((H, W), dtype=np.int64)
    for c in range(len(centers)):
        dxc = X - cx[c]
        dyc = Y - cy[c]
        d2 = dxc * dxc + dyc * dyc
        closer = d2 < best
        # second-nearest bookkeeping, in place to avoid a full-grid alloc per
        # centre: everywhere second competes with d2; at pixels that just found
        # a new nearest, the OLD best drops to second (read before best update).
        np.minimum(second, d2, out=second)
        second[closer] = best[closer]
        ids[closer] = c
        best[closer] = d2[closer]
    dist_center = np.sqrt(best)
    dist_edge = (np.sqrt(second) - dist_center) * 0.5
    return ids, dist_center, dist_edge


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


def _bbox_indices(x_p, y_p, cx, cy, rx, ry=None):
    """Index slices of the (ascending) scan grid covering the centre +/- (rx, ry).

    Returns ``(ys, xs)`` slice objects (empty if the box is off-grid). Lets a
    small object's per-pixel work be confined to its footprint instead of
    sweeping the whole (up to ~1000x1000) fine grid -- a pure speedup, since
    every contribution is zero outside the object's footprint. ``ry`` defaults
    to ``rx`` (square box). Requires x_p/y_p sorted ascending (always true for
    physical scan coordinates).
    """
    if ry is None:
        ry = rx
    # searchsorted assumes ascending; all production callers build ascending
    # physical scan grids. Fail loudly rather than silently drop the object if a
    # future caller passes a descending grid.
    assert x_p[0] <= x_p[-1] and y_p[0] <= y_p[-1], \
        "_bbox_indices requires ascending x_p/y_p"
    xi0 = int(np.searchsorted(x_p, cx - rx, side="left"))
    xi1 = int(np.searchsorted(x_p, cx + rx, side="right"))
    yi0 = int(np.searchsorted(y_p, cy - ry, side="left"))
    yi1 = int(np.searchsorted(y_p, cy + ry, side="right"))
    return slice(yi0, yi1), slice(xi0, xi1)


# ======================================================================
#  Fixed physical sizes (single source of truth)
# ======================================================================
# Each phantom now models a sample of a FIXED physical size, like a real
# specimen, instead of one that shrank/grew to fill the scan field of view.
# The scan grid (x_p/y_p) is physical um centered at 0, so a sample of extent
# L_um occupies a fixed [-L/2, +L/2] window: a small FOV zooms into its centre,
# a large FOV shows the whole sample surrounded by matrix/background. Feature
# sizes are therefore absolute and the focused-beam PSF blur (applied in
# xrf_engine.py) reveals the true resolution limit (~beam size) regardless of
# FOV. See docs and the per-phantom comments below for the chosen dimensions.
IC_L_X_UM = 2.0               # IC cross-section width (lateral extent)
IC_L_Y_UM = 6.0              # IC cross-section height (M1..M7 stack + substrate)
BATTERY_EXTENT_UM = 30.0      # NMC cathode region (5-12 um secondary particles)
GEO_EXTENT_UM = 300.0         # geological thin section (10-200 um mineral grains)
BIO_CELL_RADIUS_UM = 10.0     # eukaryotic cell radius (20 um diameter)
CATALYST_RADIUS_UM = 1.5      # catalyst support particle radius (3 um diameter)
ENV_PARTICLE_RADIUS_UM = 5.0  # fly-ash particle radius (10 um diameter)
SIEMENS_OUTER_R_UM = 15.0     # Siemens star outer radius (30 um diameter)
SIEMENS_INNER_R_UM = 0.286    # hub radius: spokes narrow to ~25 nm here (50 nm beam)
CALGRID_EXTENT_UM = 300.0     # multi-element calibration pad array


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

    # Fixed BEOL cross-section: IC_L_X_UM wide x IC_L_Y_UM tall, centred at 0.
    # Geometry is in PHYSICAL units (um): the layer y-positions/heights and the
    # line pitches are absolute, so the M1 lines stay ~44 nm and the barrier
    # liner ~6 nm regardless of the scan field of view. The pattern-local
    # fractions (fx, fy in 0..1) are only used for the texture noise.
    Lx = IC_L_X_UM
    Ly = IC_L_Y_UM
    half_x = Lx / 2.0
    half_y = Ly / 2.0
    ti_edge_um = 0.006   # 6 nm Ti/TiN barrier liner

    # 7 metal layers, hierarchical pitch (bottom = finest M1, top = widest M7).
    # y_um = layer bottom (um, from pattern bottom); h_um = layer height (um);
    # pitch_um = line+space period (um); duty = metal fraction of the pitch.
    layers = [
        {"y_um": 0.24, "h_um": 0.21, "pitch_um": 0.044, "duty": 0.45},  # M1
        {"y_um": 0.60, "h_um": 0.24, "pitch_um": 0.044, "duty": 0.48},  # M2
        {"y_um": 1.02, "h_um": 0.27, "pitch_um": 0.060, "duty": 0.48},  # M3
        {"y_um": 1.56, "h_um": 0.30, "pitch_um": 0.090, "duty": 0.50},  # M4
        {"y_um": 2.22, "h_um": 0.36, "pitch_um": 0.140, "duty": 0.50},  # M5
        {"y_um": 3.00, "h_um": 0.45, "pitch_um": 0.220, "duty": 0.52},  # M6
        {"y_um": 3.96, "h_um": 0.57, "pitch_um": 0.330, "duty": 0.55},  # M7
    ]

    # Staggered offsets: each layer shifted by half-pitch from the previous one.
    for li in range(len(layers)):
        layers[li]["x_off"] = (li % 2) * layers[li]["pitch_um"] * 0.5

    # Vectorized over the whole grid. The metal layers and via gaps occupy
    # disjoint y-bands, so each pixel belongs to at most one layer/via and the
    # per-band np.where masks combine without conflict (same result as the
    # scalar per-pixel loop, which only ever matched one band).
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    IX, IY = np.meshgrid(np.arange(n_x, dtype=np.int64),
                         np.arange(n_y, dtype=np.int64))

    # Pattern-local physical coords (um), origin at the pattern's bottom-left.
    x_pat = X + half_x
    y_pat = Y + half_y
    inside = (x_pat >= 0.0) & (x_pat <= Lx) & (y_pat >= 0.0) & (y_pat <= Ly)
    fx = x_pat / Lx   # == fx_bg outside the pattern (same noise field)
    fy = y_pat / Ly

    cu = np.zeros((n_y, n_x), dtype=np.float64)
    w = np.zeros((n_y, n_x), dtype=np.float64)
    co = np.zeros((n_y, n_x), dtype=np.float64)
    ti = np.zeros((n_y, n_x), dtype=np.float64)
    si_in = np.ones((n_y, n_x), dtype=np.float64)   # inside-pattern Si (pre-texture)
    in_metal = np.zeros((n_y, n_x), dtype=bool)

    for li, ly in enumerate(layers):
        in_layer = inside & (y_pat > ly["y_um"]) & (y_pat < ly["y_um"] + ly["h_um"])
        x_shifted = x_pat + ly["x_off"]
        x_mod = np.mod(x_shifted, ly["pitch_um"]) / ly["pitch_um"]
        in_metal_l = in_layer & (x_mod < ly["duty"])
        cu_l = 0.82 + 0.15 * _value_noise_2d_vec(fx, fy, 25, seed + li)
        # Co cap: thin top border of each Cu line.
        in_band = y_pat - ly["y_um"]
        co_cap = in_metal_l & (in_band < ly["h_um"] * 0.07)
        # Ti/TiN barrier: thin side edges (physical 6 nm).
        edge_dist = np.minimum(x_mod, ly["duty"] - x_mod) * ly["pitch_um"]
        ti_edge = in_metal_l & (edge_dist < ti_edge_um)
        # cu_val: base, then *0.3 under Co cap, then *0.2 at Ti barrier (in order).
        cu_l = np.where(co_cap, cu_l * 0.3, cu_l)
        cu_l = np.where(ti_edge, cu_l * 0.2, cu_l)
        cu = np.where(in_metal_l, cu_l, cu)
        co = np.where(co_cap, np.maximum(co, 0.65), co)
        ti = np.where(ti_edge, np.maximum(ti, 0.50), ti)
        si_in = np.where(in_metal_l, 0.04, si_in)
        in_metal = in_metal | in_metal_l

    # W vias between adjacent layers (only where not in metal).
    for vi in range(len(layers) - 1):
        v_top = layers[vi]["y_um"] + layers[vi]["h_um"]
        v_bot = layers[vi + 1]["y_um"]
        in_gap = inside & (~in_metal) & (y_pat > v_top) & (y_pat < v_bot)
        via_pitch = layers[vi + 1]["pitch_um"]
        via_w_frac = 0.12
        x_shifted = x_pat + layers[vi]["x_off"]
        v_mod = np.mod(x_shifted, via_pitch) / via_pitch
        in_via = in_gap & (v_mod < via_w_frac)
        w_l = 0.72 + 0.25 * _ihash_vec(IX, IY, seed + 100 + vi)
        w = np.where(in_via, w_l, w)
        ti = np.where(in_via, np.maximum(ti, 0.18), ti)
        si_in = np.where(in_via, 0.04, si_in)

    # Si/SiO2 ILD with texture (voids, porosity). Outside the pattern the base
    # is 0.04; inside it is si_in (1.0 default, 0.04 in metal/via).
    tex = 0.65 + 0.35 * _fbm_2d_vec(fx, fy, 3, 10, seed + 200)
    si = np.where(inside, si_in, 0.04) * tex

    maps["Cu"] = cu
    maps["W"] = w
    maps["Co"] = co
    maps["Ti"] = ti
    maps["Si"] = si
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
            # Fixed 30 um cathode region (centred at 0), independent of FOV.
            "cx": rng["next"]() * BATTERY_EXTENT_UM - BATTERY_EXTENT_UM / 2.0,
            "cy": rng["next"]() * BATTERY_EXTENT_UM - BATTERY_EXTENT_UM / 2.0,
            "r":  1.5 + rng["next"]() * 4.0,       # 1.5-5.5 um radius
            "ni_grad": 0.4 + rng["next"]() * 0.6,
            "shape_seed": rng["next_int"](10000),
            "n_cracks": 3 + rng["next_int"](4),     # 3-6 radial cracks
            "crack_seed": rng["next_int"](10000),
        })

    # Vectorized with a per-particle bounding box. The fine grid can be up to
    # ~1000x1000, but each secondary particle covers only a small footprint, so
    # confining its noise/where work to a [c-r_max, c+r_max] window is a big
    # speedup with IDENTICAL output (every contribution is zero outside the
    # disc, and the maximum/where writes only touch inside-particle pixels). The
    # local arrays are slices of the global grids, so per-pixel coordinates and
    # pixel-index hashes are unchanged.
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    IX, IY = np.meshgrid(np.arange(n_x, dtype=np.int64),
                         np.arange(n_y, dtype=np.int64))

    ni_map = np.zeros((n_y, n_x), dtype=np.float64)
    mn_map = np.zeros((n_y, n_x), dtype=np.float64)
    co_map = np.zeros((n_y, n_x), dtype=np.float64)
    fe_map = np.zeros((n_y, n_x), dtype=np.float64)
    cu_map = np.zeros((n_y, n_x), dtype=np.float64)
    in_part_mask = np.zeros((n_y, n_x), dtype=bool)

    for pi2, pp in enumerate(particles):
        # r_perturbed <= r*(1+0.12); pad the box slightly for safety.
        ys, xs = _bbox_indices(x_p, y_p, pp["cx"], pp["cy"], pp["r"] * 1.13)
        Xl, Yl = X[ys, xs], Y[ys, xs]
        if Xl.size == 0:
            continue
        IXl, IYl = IX[ys, xs], IY[ys, xs]
        dx = Xl - pp["cx"]
        dy = Yl - pp["cy"]
        dist = np.sqrt(dx * dx + dy * dy)
        angle = np.arctan2(dy, dx)
        r_perturbed = pp["r"] * (1.0 + 0.12 * _fbm_2d_vec(
            angle * 2, np.full_like(angle, pi2), 3, 2, pp["shape_seed"]))
        inside = dist < r_perturbed
        if not np.any(inside):
            continue
        r_norm = np.where(inside, dist / r_perturbed, 0.0)
        in_part_mask[ys, xs] |= inside

        # Radial intergranular cracks (small fixed set per particle).
        in_crack = np.zeros_like(inside)
        crack_rng = _phantom_rng(pp["crack_seed"])
        for _ci in range(pp["n_cracks"]):
            crack_angle = crack_rng["next"]() * math.pi * 2
            crack_w = 0.015 + crack_rng["next"]() * 0.01
            da = angle - crack_angle
            da = np.where(da > math.pi, da - 2.0 * math.pi, da)
            da = np.where(da < -math.pi, da + 2.0 * math.pi, da)
            in_crack = in_crack | (inside & (r_norm > 0.25) & (np.abs(da) < crack_w))

        # Crack regions: depleted signal with Fe enrichment.
        crack_int = np.where(in_crack, (r_norm - 0.25) / 0.75, 0.0)
        ni_l, mn_l = ni_map[ys, xs], mn_map[ys, xs]
        co_l, fe_l, cu_l = co_map[ys, xs], fe_map[ys, xs], cu_map[ys, xs]
        ni_l = np.maximum(ni_l, np.where(in_crack, 0.05, 0.0))
        mn_l = np.maximum(mn_l, np.where(in_crack, 0.02, 0.0))
        co_l = np.maximum(co_l, np.where(in_crack, 0.02, 0.0))
        fe_l = np.maximum(fe_l, np.where(in_crack, 0.18 * crack_int, 0.0))

        # Primary grain texture (non-crack region only).
        not_crack = inside & ~in_crack
        grain_noise = _fbm_2d_vec(Xl * 3, Yl * 3, 2, 4, seed + pi2 * 7)

        ni_val = np.where(not_crack,
            (0.35 + 0.65 * r_norm * pp["ni_grad"]) *
            (0.85 + 0.15 * grain_noise), 0.0)
        # NiO rock-salt surface layer: scalar does max(ni_val, 0.95), so a grain
        # value already above 0.95 is KEPT (not overwritten down to 0.95).
        ni_val = np.where(not_crack & (r_norm > 0.92),
                          np.maximum(ni_val, 0.95), ni_val)
        ni_l = np.maximum(ni_l, ni_val)

        mn_val = np.where(not_crack,
            (0.75 - 0.35 * r_norm) * (0.9 + 0.1 * grain_noise), 0.0)
        mn_l = np.maximum(mn_l, mn_val)

        co_val = np.where(not_crack,
            (0.55 + 0.45 * (1 - r_norm * 0.5)) *
            (0.85 + 0.15 * grain_noise), 0.0)
        co_l = np.maximum(co_l, co_val)

        gb_prox = 1.0 - 4.0 * np.abs(grain_noise - 0.5)
        fe_gb = not_crack & (gb_prox > 0.6) & (r_norm > 0.3)
        fe_l = np.maximum(fe_l, np.where(fe_gb, gb_prox * 0.25, 0.0))

        # Cu contamination hotspots (pixel-index hash). The scalar `continue`d on
        # crack pixels BEFORE this block, so Cu is added on NON-crack pixels only.
        cu_hotspot = not_crack & (_ihash_vec(IXl, IYl, seed + 500) > 0.97)
        cu_val = np.where(cu_hotspot,
            0.15 + _ihash_vec(IXl, IYl, seed + 501) * 0.3, 0.0)
        cu_l = np.maximum(cu_l, cu_val)

        ni_map[ys, xs], mn_map[ys, xs] = ni_l, mn_l
        co_map[ys, xs], fe_map[ys, xs], cu_map[ys, xs] = co_l, fe_l, cu_l

    # Binder/carbon background where no particle.
    bg = ~in_part_mask
    ni_map = np.where(bg, 0.01 * _value_noise_2d_vec(X, Y, 1, seed + 300), ni_map)
    mn_map = np.where(bg, 0.008, mn_map)
    co_map = np.where(bg, 0.008, co_map)

    maps["Ni"] = ni_map
    maps["Mn"] = mn_map
    maps["Co"] = co_map
    maps["Fe"] = fe_map
    maps["Cu"] = cu_map
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

    # Voronoi grains (20-40) over a FIXED 300 um thin-section window (centred
    # at 0), so grain size (~15-60 um) is physical and independent of the FOV.
    n_grains = 20 + rng["next_int"](20)
    centers = _build_voronoi_centers(n_grains, seed + 10,
                                     GEO_EXTENT_UM, GEO_EXTENT_UM,
                                     -GEO_EXTENT_UM / 2.0, -GEO_EXTENT_UM / 2.0)
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
    frac_offset = (0.3 + rng["next"]() * 0.4) * GEO_EXTENT_UM - GEO_EXTENT_UM / 2.0

    # Vectorized over the whole grid.
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    IX, IY = np.meshgrid(np.arange(n_x, dtype=np.int64),
                         np.arange(n_y, dtype=np.int64))

    grain_ids, _dc, d_edge = _voronoi_fields(X, Y, centers)
    mineral = np.array(mineral_types, dtype=np.int64)[grain_ids]
    is_gb = d_edge < 0.15

    fe = np.zeros((n_y, n_x), dtype=np.float64)
    ti = np.zeros((n_y, n_x), dtype=np.float64)
    mn = np.zeros((n_y, n_x), dtype=np.float64)
    cr = np.zeros((n_y, n_x), dtype=np.float64)
    ni = np.zeros((n_y, n_x), dtype=np.float64)
    cu = np.zeros((n_y, n_x), dtype=np.float64)
    zn = np.zeros((n_y, n_x), dtype=np.float64)
    sr = np.zeros((n_y, n_x), dtype=np.float64)
    as_ = np.zeros((n_y, n_x), dtype=np.float64)

    sd = seed + grain_ids  # per-grain noise seed (array, supported by _ihash_vec)

    # Quartz (0)
    mq = mineral == 0
    sr = np.where(mq, 0.02 + 0.01 * _value_noise_2d_vec(X, Y, 4, sd), sr)
    # Feldspar (1)
    mf = mineral == 1
    sr = np.where(mf, 0.3 + 0.1 * _value_noise_2d_vec(X, Y, 5, sd), sr)
    fe = np.where(mf, 0.05, fe)
    # Garnet (2) -- concentric zoning about each grain centre
    mg = mineral == 2
    gcx = np.array([c["x"] for c in centers], dtype=np.float64)[grain_ids]
    gcy = np.array([c["y"] for c in centers], dtype=np.float64)[grain_ids]
    zone_phase = np.sin(np.sqrt((X - gcx) ** 2 + (Y - gcy) ** 2) * 3.0)
    fe = np.where(mg, 0.6 + 0.3 * zone_phase, fe)
    mn = np.where(mg, 0.3 - 0.2 * zone_phase, mn)
    cr = np.where(mg, 0.02 + 0.01 * _value_noise_2d_vec(X, Y, 6, sd + 50), cr)
    # Pyroxene (3)
    mp = mineral == 3
    fe = np.where(mp, 0.4 + 0.2 * _value_noise_2d_vec(X, Y, 3, sd), fe)
    mn = np.where(mp, 0.1 + 0.05 * _value_noise_2d_vec(X, Y, 3, sd + 10), mn)
    ti = np.where(mp, 0.05, ti)
    # Mica (4)
    mm = mineral == 4
    fe = np.where(mm, 0.3 + 0.1 * _value_noise_2d_vec(X, Y, 4, sd), fe)
    ti = np.where(mm, 0.15 + 0.1 * _value_noise_2d_vec(X, Y, 5, sd + 20), ti)

    # Grain boundary enrichment
    fe = np.where(is_gb, fe + 0.15, fe)
    cu = np.where(is_gb, cu + 0.05 * _ihash_vec(IX, IY, seed + 600), cu)
    zn = np.where(is_gb, zn + 0.03, zn)

    # Fracture zone
    frac_dist = np.abs((X - x_p[0]) * frac_cos -
                       (Y - y_p[0]) * frac_sin - frac_offset)
    in_frac = frac_dist < 0.3
    fe = np.where(in_frac, fe * 0.2, fe)
    cu = np.where(in_frac, cu + 0.1, cu)
    as_ = np.where(in_frac, as_ + 0.05, as_)

    # Tiny random inclusions (pixel-index hash)
    nicu = _ihash_vec(IX, IY, seed + 700) > 0.98
    ni = np.where(nicu, ni + 0.3, ni)
    cu = np.where(nicu, cu + 0.2, cu)
    crh = _ihash_vec(IX, IY, seed + 800) > 0.99
    cr = np.where(crh, cr + 0.5, cr)

    maps["Fe"] = fe; maps["Ti"] = ti; maps["Mn"] = mn; maps["Cr"] = cr
    maps["Ni"] = ni; maps["Cu"] = cu; maps["Zn"] = zn; maps["Sr"] = sr
    maps["As"] = as_
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
    # Fixed 20 um cell (10 um radius) centred at 0; all sub-features below are
    # fractions of cell_r so they auto-scale to physical sizes (vesicles ~0.8 um).
    cx = 0.0
    cy = 0.0
    cell_r = BIO_CELL_RADIUS_UM
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

    # Vectorized over the whole grid.
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))

    fe = np.zeros((n_y, n_x), dtype=np.float64)
    zn = np.zeros((n_y, n_x), dtype=np.float64)
    cu = np.zeros((n_y, n_x), dtype=np.float64)
    mn = np.zeros((n_y, n_x), dtype=np.float64)
    se = np.zeros((n_y, n_x), dtype=np.float64)

    # Irregular cell boundary
    angle_pt = np.arctan2(Y - cy, X - cx)
    pert_r = cell_r * (1.0 + 0.12 * _fbm_2d_vec(
        angle_pt * 3, np.zeros_like(angle_pt), 3, 2, seed + 100))
    dist_c = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    in_cell = dist_c < pert_r

    # Cytoplasm Cu (everywhere inside the cell)
    cu = np.where(in_cell, 0.25 + 0.15 * _fbm_2d_vec(X, Y, 3, 2, seed + 200), 0.0)

    # Nucleus
    dist_n = np.sqrt((X - nucl_cx) ** 2 + (Y - nucl_cy) ** 2)
    in_nuc = in_cell & (dist_n < nucl_r)
    zn = np.where(in_nuc,
        0.6 + 0.2 * _fbm_2d_vec(X * 3, Y * 3, 2, 5, seed + 300)
        + 0.12 * np.abs(np.sin(X * 8 + Y * 6)), zn)
    cu = np.where(in_nuc, cu + 0.1, cu)
    mn = np.where(in_nuc, mn + 0.02, mn)

    # Mitochondria (Fe-rich elongated blobs) -- small fixed list, each confined
    # to its bounding box (semi-major axis 'len' bounds the rotated ellipse).
    for mt in mitos:
        ys, xs = _bbox_indices(x_p, y_p, mt["x"], mt["y"], mt["len"])
        Xl, Yl = X[ys, xs], Y[ys, xs]
        if Xl.size == 0:
            continue
        mdx = Xl - mt["x"]
        mdy = Yl - mt["y"]
        ca = math.cos(mt["angle"]); sa = math.sin(mt["angle"])
        rx = ca * mdx + sa * mdy
        ry = -sa * mdx + ca * mdy
        ell_d = (rx / mt["len"]) ** 2 + (ry / mt["wid"]) ** 2
        m = in_cell[ys, xs] & (ell_d < 1.0)
        fe[ys, xs] = np.where(m, fe[ys, xs] + 0.7 * (1.0 - ell_d), fe[ys, xs])
        mn[ys, xs] = np.where(m, mn[ys, xs] + 0.12 * (1.0 - ell_d), mn[ys, xs])

    # Zn vesicles -- small fixed list, each confined to its bounding box.
    for ve in vesicles:
        ys, xs = _bbox_indices(x_p, y_p, ve["x"], ve["y"], ve["r"])
        Xl, Yl = X[ys, xs], Y[ys, xs]
        if Xl.size == 0:
            continue
        vd = np.sqrt((Xl - ve["x"]) ** 2 + (Yl - ve["y"]) ** 2)
        m = in_cell[ys, xs] & (vd < ve["r"])
        zn[ys, xs] = np.where(m, zn[ys, xs] + 0.8 * (1.0 - vd / ve["r"]), zn[ys, xs])

    # Se: barely detectable (selenoproteins), only inside the cell
    se = np.where(in_cell, 0.015 + 0.01 * _value_noise_2d_vec(X, Y, 2, seed + 400), 0.0)

    maps["Fe"] = fe; maps["Zn"] = zn; maps["Cu"] = cu
    maps["Mn"] = mn; maps["Se"] = se
    return maps


# -- 5. Catalyst NPs on support ----------------------------------------
# Models noble-metal nanoparticles (Pt, Au, bimetallic Pt-Au core-shell)
# dispersed on an Fe-oxide support particle with mesoporous structure.
# Ce decoration around NP perimeters models a CeO2 promoter.

def _phantom_catalyst_np(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Pt", "Au", "Fe", "Ce"], n_x, n_y)
    rng = _phantom_rng(seed)
    # Fixed 3 um support particle (1.5 um radius) centred at 0, independent of FOV.
    cx = 0.0
    cy = 0.0
    part_r = CATALYST_RADIUS_UM

    # Support pore structure (Voronoi-based), over the fixed particle window.
    n_pores = 8 + rng["next_int"](5)
    pore_centers = _build_voronoi_centers(
        n_pores, seed + 50,
        2.0 * CATALYST_RADIUS_UM, 2.0 * CATALYST_RADIUS_UM,
        -CATALYST_RADIUS_UM, -CATALYST_RADIUS_UM)
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
        np_r = 0.005 + rng["next"]() * 0.010  # 5-15 nm radius (um) — true NP size
        np_type = rng["next"]()  # 0-0.5 Pt, 0.5-0.8 bimetallic, 0.8-1 Au
        nps.append({"x": npx, "y": npy, "r": np_r, "type": np_type})

    # Vectorized over the whole grid. The per-pixel scalar loop did, in order:
    #   (1) skip pixels outside the perturbed support boundary,
    #   (2) Fe matrix; if inside ANY pore -> Fe *= 0.1 and skip NPs,
    #   (3) for each NP (in list order) add Pt/Au + Ce, with a per-NP Au clamp.
    # Each step below reproduces that exactly with masks, accumulating over the
    # NP list in the same order so the floating-point result is identical.
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))

    dx = X - cx
    dy = Y - cy
    angle_pt = np.arctan2(dy, dx)
    pert_r = part_r * (1.0 + 0.15 * _fbm_2d_vec(
        angle_pt * 3, np.zeros_like(angle_pt), 3, 2, seed + 100))
    dist_c = np.sqrt(dx * dx + dy * dy)
    inside = dist_c < pert_r

    # Fe in support matrix (only inside the particle).
    fe_val = 0.15 + 0.1 * _fbm_2d_vec(X * 2, Y * 2, 3, 3, seed + 200)

    # Pores: low signal. A pixel is "in pore" if inside ANY pore disc.
    in_pore = np.zeros((n_y, n_x), dtype=bool)
    for pi2 in range(n_pores):
        pd = np.sqrt((X - pore_centers[pi2]["x"]) ** 2 +
                     (Y - pore_centers[pi2]["y"]) ** 2)
        in_pore = in_pore | (pd < pore_radii[pi2])
    in_pore = in_pore & inside           # pore branch only reached inside

    # NP region: inside the support, not in a pore.
    np_region = inside & ~in_pore

    pt = np.zeros((n_y, n_x), dtype=np.float64)
    au = np.zeros((n_y, n_x), dtype=np.float64)
    ce = np.zeros((n_y, n_x), dtype=np.float64)

    for np_obj in nps:
        npd = np.sqrt((X - np_obj["x"]) ** 2 + (Y - np_obj["y"]) ** 2)
        in_np = np_region & (npd < np_obj["r"])
        if not np.any(in_np):
            continue
        r_norm = npd / np_obj["r"]        # < 1 wherever in_np

        if np_obj["type"] < 0.5:
            # Pure Pt NP
            pt = np.where(in_np, pt + 0.9 * (1.0 - r_norm), pt)
        elif np_obj["type"] < 0.8:
            # Core-shell: Pt core (r<0.5), Au shell (r>=0.5), per-NP Au clamp.
            core = in_np & (r_norm < 0.5)
            shell = in_np & (r_norm >= 0.5)
            pt = np.where(core, pt + 0.9 * (1.0 - r_norm * 2), pt)
            au = np.where(shell, au + 0.8 * ((r_norm - 0.5) * 2), au)
            au = np.where(shell, np.minimum(au, 0.8), au)
        else:
            # Pure Au NP
            au = np.where(in_np, au + 0.85 * (1.0 - r_norm), au)

        # Ce decoration around NPs: only INSIDE this NP (r_norm < 1, so the
        # scalar's r_norm<1.3 bound is always satisfied) with r_norm > 0.6.
        ce_mask = in_np & (r_norm > 0.6) & (r_norm < 1.3)
        ce = np.where(ce_mask, ce + 0.3 * (1.0 - np.abs(r_norm - 0.95) * 3), ce)

    # Fe: pore pixels are depleted (x0.1); non-pore inside keep matrix value;
    # outside the particle stays zero (scalar `continue`).
    fe = np.where(inside, fe_val, 0.0)
    fe = np.where(in_pore, fe_val * 0.1, fe)

    maps["Pt"] = np.where(np_region, np.minimum(1.0, pt), 0.0)
    maps["Au"] = np.where(np_region, np.minimum(1.0, au), 0.0)
    maps["Fe"] = fe
    maps["Ce"] = np.where(np_region, np.maximum(0.0, ce), 0.0)
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
    # Fixed 10 um fly-ash particle (5 um radius) centred at 0, independent of FOV.
    cx = 0.0
    cy = 0.0
    part_r = ENV_PARTICLE_RADIUS_UM

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

    # Vectorized over the whole grid; everything is gated by the inside mask so
    # pixels outside the perturbed particle stay zero (scalar `continue`).
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    IX, IY = np.meshgrid(np.arange(n_x, dtype=np.int64),
                         np.arange(n_y, dtype=np.int64))

    dx = X - cx
    dy = Y - cy
    angle_pt = np.arctan2(dy, dx)
    pert_r = part_r * (1.0 + 0.2 * _fbm_2d_vec(
        angle_pt * 2.5, np.zeros_like(angle_pt), 4, 2, seed + 100))
    dist_c = np.sqrt(dx * dx + dy * dy)
    inside = dist_c < pert_r
    r_norm = np.where(inside, dist_c / pert_r, 0.0)

    # Layered internal structure (concentric zones: 0=core..3=rim).
    zone = np.clip(np.floor(r_norm * 4).astype(np.int64), 0, 3)
    fe_base = np.array([0.5, 0.6, 0.4, 0.8], dtype=np.float64)  # rim-enriched
    fe = fe_base[zone] + 0.1 * _fbm_2d_vec(X * 2, Y * 2, 2, 3, seed + 200)

    # Mn: relatively uniform with slight texture.
    mn2 = 0.15 + 0.05 * _value_noise_2d_vec(X, Y, 3, seed + 300)

    # Oxidation rim: Fe-enriched shell + surface-adsorbed trace elements.
    rim = inside & (r_norm > 0.8)
    fe = np.where(rim, fe + 0.3 * (r_norm - 0.8) / 0.2, fe)
    as_ = np.where(rim, 0.08 * (r_norm - 0.8) / 0.2, 0.0)
    pb = np.where(rim, 0.06 * (r_norm - 0.8) / 0.2, 0.0)

    # Provenance tracer.
    sr = 0.03 + 0.02 * _value_noise_2d_vec(X, Y, 2, seed + 400)

    ti = np.zeros((n_y, n_x), dtype=np.float64)
    cr = np.zeros((n_y, n_x), dtype=np.float64)
    zn = np.zeros((n_y, n_x), dtype=np.float64)

    # Crystallite inclusions (only inside the particle; accumulate in order).
    for inc in inclusions:
        inc_d = np.sqrt((X - inc["x"]) ** 2 + (Y - inc["y"]) ** 2)
        in_inc = inside & (inc_d < inc["r"])
        inc_f = 1.0 - inc_d / inc["r"]
        if inc["type"] == 0:
            ti = np.where(in_inc, ti + 0.8 * inc_f, ti)      # TiO2
        elif inc["type"] == 1:
            cr = np.where(in_inc, cr + 0.6 * inc_f, cr)      # chromite
        else:
            zn = np.where(in_inc, zn + 0.5 * inc_f, zn)      # ZnO

    # Scattered Cu: smelter emission signature (pixel-index hash, inside only).
    cu = np.where(inside & (_ihash_vec(IX, IY, seed + 500) > 0.96), 0.2, 0.0)

    # Zero everything outside the particle (scalar `continue`).
    maps["Fe"] = np.where(inside, fe, 0.0)
    maps["Ti"] = ti
    maps["Mn"] = np.where(inside, mn2, 0.0)
    maps["Cr"] = cr
    maps["Cu"] = cu
    maps["Zn"] = zn
    maps["As"] = as_
    maps["Pb"] = pb
    maps["Sr"] = np.where(inside, sr, 0.0)
    return maps


# -- 7. Siemens star resolution test pattern ----------------------------
# Standard X-ray nanoprobe calibration pattern: 36 alternating Au/gap
# wedge spokes converging toward a central hub on Si3N4 membrane.
# Spoke width decreases linearly toward center, naturally testing
# spatial resolution.  Concentric calibration rings at 25/50/75/100%.

def _phantom_siemens_star(n_x, n_y, x_p, y_p, scan_w, scan_h, seed):
    maps = _alloc_maps(["Au", "Cr", "Si"], n_x, n_y)
    # Fixed 30 um resolution target (15 um outer radius) centred at 0. With 36
    # spokes the tangential Au-spoke width shrinks from ~1.3 um at the rim to
    # 25 nm at the hub radius (~0.286 um), so a 50 nm beam resolves the outer
    # spokes and washes out the inner ones -- the beam-size readout. Independent
    # of FOV: a small FOV zooms into the unresolvable centre, FOV >= 30 um shows
    # the whole star. See SIEMENS_OUTER_R_UM / SIEMENS_INNER_R_UM.
    outer_r = SIEMENS_OUTER_R_UM
    inner_r = SIEMENS_INNER_R_UM   # central unresolved hub (spokes -> ~25 nm here)
    n_spokes = 36
    ring_fracs = [0.25, 0.50, 0.75, 1.0]
    ring_w = outer_r * 0.012

    # Vectorized over the whole grid (centred at 0).
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    dist = np.sqrt(X * X + Y * Y)

    au = np.zeros((n_y, n_x), dtype=np.float64)
    cr = np.zeros((n_y, n_x), dtype=np.float64)
    si = np.full((n_y, n_x), 0.05, dtype=np.float64)   # Si3N4 membrane outside

    inside = dist <= outer_r * 1.05
    si[inside] = 0.12                                   # membrane inside pattern

    hub = dist <= inner_r
    au[hub] = 0.90
    cr[hub] = 0.08

    # Spoke region: inner_r < dist <= outer_r
    spoke_zone = (dist > inner_r) & (dist <= outer_r)
    angle = np.arctan2(Y, X)
    spoke_period = 2.0 * math.pi / n_spokes
    phase = np.mod(angle + math.pi, spoke_period) / spoke_period
    is_au = spoke_zone & (phase < 0.5)
    noise = 0.05 * _value_noise_2d_vec(X * 2.0, Y * 2.0, 4, seed + 10)
    au = np.where(is_au, 0.82 + noise, au)
    cr = np.where(is_au, 0.06, cr)

    # Concentric calibration rings (always Au), only inside the pattern.
    for rf in ring_fracs:
        ring_r = outer_r * rf
        on_ring = spoke_zone & (np.abs(dist - ring_r) < ring_w)
        au = np.where(on_ring, np.maximum(au, 0.75), au)
        cr = np.where(on_ring, np.maximum(cr, 0.05), cr)

    maps["Au"] = au
    maps["Cr"] = cr
    maps["Si"] = si
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

    # Fixed 300 um calibration array centred at 0 (a quantitative standard must
    # have fixed pad dimensions, ~49 um, independent of the scan field of view).
    _margin = margin  # retained for the inset (10% border inside the array)
    grid_x0 = -CALGRID_EXTENT_UM / 2.0 + CALGRID_EXTENT_UM * _margin
    grid_y0 = -CALGRID_EXTENT_UM / 2.0 + CALGRID_EXTENT_UM * _margin
    grid_w = CALGRID_EXTENT_UM * (1.0 - 2.0 * _margin)
    grid_h = CALGRID_EXTENT_UM * (1.0 - 2.0 * _margin)
    cell_w = grid_w / grid_n
    cell_h = grid_h / grid_n
    pad_half_w = cell_w * (1.0 - gap_frac) / 2.0
    pad_half_h = cell_h * (1.0 - gap_frac) / 2.0

    # Vectorized over the whole grid (each pixel falls in exactly one cell).
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))

    maps["Si"][:] = 0.08                       # Si substrate everywhere
    rel_x = X - grid_x0
    rel_y = Y - grid_y0
    in_array = (rel_x >= 0) & (rel_x < grid_w) & (rel_y >= 0) & (rel_y < grid_h)
    gi = np.floor(rel_x / cell_w).astype(np.int64)
    gj = np.floor(rel_y / cell_h).astype(np.int64)

    # One pass per cell (16 cells), confined to each pad's bounding box. Off-grid
    # pads (most of them when the FOV frames a sub-region of the 300 um array)
    # have an empty box and are skipped, and the per-pad value-noise is evaluated
    # only over the pad footprint -- identical output, far less work.
    for gj_i in range(grid_n):
        for gi_i in range(grid_n):
            elem_idx = gj_i * grid_n + gi_i
            if elem_idx >= len(pad_elements):
                continue
            elem = pad_elements[elem_idx]
            cell_cx = grid_x0 + (gi_i + 0.5) * cell_w
            cell_cy = grid_y0 + (gj_i + 0.5) * cell_h
            ys, xs = _bbox_indices(x_p, y_p, cell_cx, cell_cy,
                                   pad_half_w, pad_half_h)
            Xl, Yl = X[ys, xs], Y[ys, xs]
            if Xl.size == 0:
                continue
            adx = np.abs(Xl - cell_cx)
            ady = np.abs(Yl - cell_cy)
            cell_mask = (in_array[ys, xs] & (gi[ys, xs] == gi_i)
                         & (gj[ys, xs] == gj_i)
                         & (adx <= pad_half_w) & (ady <= pad_half_h))
            val = 0.70 + 0.15 * _value_noise_2d_vec(
                Xl, Yl, 8, seed + elem_idx * 17)
            maps[elem][ys, xs] = np.where(cell_mask, val, maps[elem][ys, xs])
            maps["Si"][ys, xs] = np.where(  # suppressed under pad
                cell_mask, 0.01, maps["Si"][ys, xs])

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

    # Vectorized over the whole grid via the Voronoi field helper.
    X, Y = np.meshgrid(np.asarray(x_p, dtype=np.float64),
                       np.asarray(y_p, dtype=np.float64))
    ids, _dc, d_edge = _voronoi_fields(X, Y, centers)
    gp = np.array(grain_phase, dtype=np.float64)[ids]
    go = np.array(grain_orient, dtype=np.float64)[ids]

    # Smooth transition at grain boundary (dist_edge < 0.2).
    near_edge = d_edge < 0.2
    phase_map = np.where(
        near_edge,
        gp * 0.7 + 0.3 * _value_noise_2d_vec(X, Y, 10, seed + 99),
        gp)
    orient_map = go + 0.002 * _value_noise_2d_vec(X, Y, 5, seed + 50)

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


# Practical upper bound on the XRF scan FOV for a ~50 nm nanoprobe. A 50 nm
# beam can only usefully image tens of um (KB/piezo scan range; a full 300 um
# raster would be millions of points / hours). Larger samples (geological thin
# section, calibration array) are physically 300 um but only a sub-region is
# scanned, so their recommended FOV is capped here. The engine also clamps any
# requested FOV to this value.
MAX_FOV_UM = 60.0

# Recommended full scan field of view (um) when a preset is chosen.
# For samples that fit, this frames the whole sample; for large samples
# (geological / calibration) it frames a representative sub-region (the nanoprobe
# does not raster the entire 300 um specimen). A smaller FOV zooms into the
# centre (fine detail / resolution limit). The UI / NLP defaults to this.
RECOMMENDED_FOV_UM = {
    "semiconductor_ic":       max(IC_L_X_UM, IC_L_Y_UM),    # 6 um (full stack)
    "battery_nmc622":         BATTERY_EXTENT_UM,             # 30 um (full)
    "geological_section":     50.0,                          # sub-region of 300 um
    "biological_cell":        2.0 * BIO_CELL_RADIUS_UM,      # 20 um (full cell)
    "catalyst_nanoparticle":  2.0 * CATALYST_RADIUS_UM,      # 3 um (full particle)
    "environmental_particle": 2.0 * ENV_PARTICLE_RADIUS_UM,  # 10 um (full particle)
    "siemens_star":           2.0 * SIEMENS_OUTER_R_UM,      # 30 um (full star)
    "calibration_grid":       50.0,                          # ~one pad of 300 um array
}


def recommended_fov_um(preset_key):
    """Return the recommended full FOV (um) for a preset, or None if unknown."""
    return RECOMMENDED_FOV_UM.get(preset_key)


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
