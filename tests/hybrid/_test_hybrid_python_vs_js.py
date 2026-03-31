"""
_test_hybrid_python_vs_js.py
============================
Python port of _hybridFF1D from js/raytrace/01_mc_engine.js (lines 630-770),
then comparison tests for KB-V mirror at 10 keV.

Tests:
  1. Uniform footprint  -> kick FWHM vs Airy
  2. Gaussian footprint (sigma=255um) -> kick FWHM vs Airy
  3. Full convolution: geometric + kick -> total FWHM
  4. Peaked Gaussian footprint (sigma=100um) -> total FWHM
"""

import numpy as np
import math

# ---------------------------------------------------------------------------
# Helper: next power of 2
# ---------------------------------------------------------------------------
def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p

# ---------------------------------------------------------------------------
# Helper: inverse CDF sampling (exact port of JS _inverseCdfSample)
# ---------------------------------------------------------------------------
def _inverse_cdf_sample(pdf, n, x_min, x_max, n_samples, rng=None):
    if rng is None:
        rng = np.random.default_rng()
    dx = (x_max - x_min) / (n - 1)
    # Build CDF (S4: cumsum, subtract cdf[0], normalize)
    cdf = np.cumsum(pdf).astype(np.float64)
    cdf0 = cdf[0]
    cdf -= cdf0
    cdf_max = cdf[-1]
    if cdf_max <= 0:
        return rng.uniform(x_min, x_max, size=n_samples)
    cdf /= cdf_max
    # Sample
    samples = np.empty(n_samples, dtype=np.float64)
    for s in range(n_samples):
        u = rng.random()
        # Binary search: first index where cdf >= u
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) >> 1
            if cdf[mid] < u:
                lo = mid + 1
            else:
                hi = mid
        ix = lo
        if ix > 0:
            ix -= 1
        # Linear interpolation within [ix, ix+1]
        delta_val = 0.0
        if ix < n - 1:
            pendent = cdf[ix + 1] - cdf[ix]
            if pendent > 0:
                delta_val = (u - cdf[ix]) / pendent
        samples[s] = x_min + (ix + delta_val) * dx
    return samples

# ---------------------------------------------------------------------------
# Core: _hybridFF1D_python  (exact port of JS lines 630-770)
# ---------------------------------------------------------------------------
def _hybridFF1D_python(foot_arr, n_alive, D, lam, n_samples, rng=None):
    """
    Exact Python port of JS _hybridFF1D.

    Parameters
    ----------
    foot_arr : array of shape (n_alive,), ray positions on mirror [m]
    n_alive  : int, number of valid rays
    D        : float, mirror aperture [m]
    lam      : float, wavelength [m]
    n_samples: int, number of angular kick samples to return
    rng      : numpy random generator

    Returns
    -------
    kicks : array of shape (n_samples,), angular kicks [rad]
    """
    if rng is None:
        rng = np.random.default_rng()
    if D < 1e-12 or n_alive < 3:
        return np.zeros(n_samples)

    n_peaks = 20
    k = 2 * math.pi / lam

    # S4: f_ff = D^2 / (n_peaks * 2 * 0.88 * lam)
    f_ff = D * D / (n_peaks * 2 * 0.88 * lam)

    # --- Step 1: Histogram footprint ---
    n_bins = min(200, round(n_alive / 20))
    if n_bins < 10:
        n_bins = 10

    z_min = np.min(foot_arr[:n_alive])
    z_max = np.max(foot_arr[:n_alive])
    if z_max - z_min < 1e-15:
        return np.zeros(n_samples)

    dz_hist = (z_max - z_min) / n_bins
    hist = np.zeros(n_bins, dtype=np.float64)
    for i in range(n_alive):
        b = int(math.floor((foot_arr[i] - z_min) / dz_hist))
        if b >= n_bins:
            b = n_bins - 1
        if b >= 0:
            hist[b] += 1

    # hist_delta = (zMax - zMin) / (nBins - 1) for ScaledArray interpolation
    hist_delta = (z_max - z_min) / (n_bins - 1) if n_bins > 1 else 1e-15

    # --- Step 2: FFT size ---
    fft_size_raw = round(100 * D * D / (lam * f_ff * 0.88))
    if fft_size_raw > 1000000:
        fft_size_raw = 1000000
    if fft_size_raw < n_bins * 2:
        fft_size_raw = n_bins * 2
    N = _next_pow2(fft_size_raw)
    if N > 131072:
        N = 131072

    # --- Step 3: Create wavefront on grid [zMin, zMax] with N points ---
    delta = (z_max - z_min) / (N - 1)
    z_grid = z_min + np.arange(N, dtype=np.float64) * delta

    # --- Step 4: Interpolate histogram onto wavefront, sqrt, thin-lens phase ---
    wavefront = np.zeros(N, dtype=np.complex128)
    for j in range(N):
        z = z_grid[j]
        frac_idx = (z - z_min) / hist_delta
        idx0 = int(math.floor(frac_idx))
        idx1 = idx0 + 1
        # S4 clamp
        if idx0 < 0:
            idx0 = 0; idx1 = 0
        if idx1 >= n_bins:
            idx1 = n_bins - 1
            if idx0 >= n_bins:
                idx0 = n_bins - 1
        if idx0 == idx1:
            interp_val = hist[idx0]
        else:
            frac = frac_idx - idx0
            interp_val = hist[idx0] + (hist[idx1] - hist[idx0]) * frac
        amp = math.sqrt(max(0.0, interp_val))
        phi = -k * z * z / (2 * f_ff)
        wavefront[j] = amp * (math.cos(phi) + 1j * math.sin(phi))

    # --- Step 5: Fresnel TF propagation ---
    wf_fft = np.fft.fft(wavefront)
    coeff = -math.pi * lam * f_ff
    freq_indices = np.arange(N, dtype=np.float64)
    freq_indices[N // 2:] -= N
    f_arr = freq_indices / (N * delta)
    phase_arr = coeff * f_arr * f_arr
    tf = np.cos(phase_arr) + 1j * np.sin(phase_arr)
    wf_fft *= tf
    wavefront = np.fft.ifft(wf_fft)

    re = np.real(wavefront)
    im = np.imag(wavefront)

    # --- Step 6: Extract image intensity ---
    image_size = min(abs(z_max), abs(z_min)) * 2
    image_size = min(image_size,
                     n_peaks * 2 * 0.88 * lam * f_ff / abs(z_max - z_min))

    image_n_pts = round(image_size / delta / 2) * 2 + 1
    if image_n_pts < 3:
        image_n_pts = 3
    if image_n_pts > N:
        image_n_pts = N

    half_pts = (image_n_pts - 1) / 2.0
    intensity = np.zeros(image_n_pts, dtype=np.float64)
    for ip in range(image_n_pts):
        pos = (ip - half_pts) * delta
        wf_frac = (pos - z_min) / delta
        i0 = int(math.floor(wf_frac))
        i1 = i0 + 1
        if i0 < 0 or i1 >= N:
            intensity[ip] = 0.0
            continue
        frac = wf_frac - i0
        re_i = re[i0] + (re[i1] - re[i0]) * frac
        im_i = im[i0] + (im[i1] - im[i0]) * frac
        intensity[ip] = re_i * re_i + im_i * im_i

    # S4: convert to angular coordinates
    ang_min = -half_pts * delta / f_ff
    ang_max = half_pts * delta / f_ff

    # --- Step 7: CDF sampling ---
    kicks = _inverse_cdf_sample(intensity, image_n_pts, ang_min, ang_max,
                                n_samples, rng=rng)
    return kicks

# ---------------------------------------------------------------------------
# FWHM from histogram (robust)
# ---------------------------------------------------------------------------
def fwhm_from_samples(samples, n_bins=300):
    """Estimate FWHM from a sample array via histogram."""
    h, edges = np.histogram(samples, bins=n_bins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    h = h.astype(np.float64)
    hmax = h.max()
    if hmax <= 0:
        return 0.0
    # Find left and right half-max crossings
    above = np.where(h >= hmax / 2)[0]
    if len(above) == 0:
        return 0.0
    left = centers[above[0]]
    right = centers[above[-1]]
    return right - left

# ===========================================================================
# Main test
# ===========================================================================
def main():
    print("=" * 72)
    print("  _hybridFF1D Python vs JS comparison")
    print("  KB-V mirror at 10 keV")
    print("=" * 72)

    # --- Parameters ---
    energy_keV = 10.0
    lam = 12.3984 / energy_keV * 1e-10  # wavelength [m]
    D = 900e-6  # KB-V aperture [m]
    q = 0.31    # KB-V image distance [m]

    airy_angle = 0.886 * lam / D  # Airy diffraction angle [rad]
    airy_spot = airy_angle * q    # Airy spot size at sample [m]

    print(f"\n  Energy     : {energy_keV} keV")
    print(f"  Wavelength : {lam*1e10:.4f} A = {lam:.6e} m")
    print(f"  Aperture D : {D*1e6:.0f} um")
    print(f"  Image dist : {q*1e3:.0f} mm")
    print(f"  Airy angle : {airy_angle*1e6:.3f} urad")
    print(f"  Airy spot  : {airy_spot*1e9:.2f} nm")

    n_rays = 10000
    n_repeats = 20
    rng = np.random.default_rng(42)

    # ===================================================================
    # TEST 1: UNIFORM footprint
    # ===================================================================
    print("\n" + "-" * 72)
    print("  TEST 1: UNIFORM footprint")
    print("-" * 72)

    kick_fwhms_uniform = []
    for rep in range(n_repeats):
        foot = rng.uniform(-D / 2, D / 2, size=n_rays)
        kicks = _hybridFF1D_python(foot, n_rays, D, lam, n_rays, rng=rng)
        spot = kicks * q
        fw = fwhm_from_samples(spot, n_bins=300)
        kick_fwhms_uniform.append(fw)

    mean_fw_uni = np.mean(kick_fwhms_uniform)
    std_fw_uni = np.std(kick_fwhms_uniform)
    ratio_uni = mean_fw_uni / airy_spot

    print(f"  Kick FWHM at sample : {mean_fw_uni*1e9:.2f} +/- {std_fw_uni*1e9:.2f} nm")
    print(f"  Airy spot           : {airy_spot*1e9:.2f} nm")
    print(f"  Ratio (kick/Airy)   : {ratio_uni:.3f}")
    print(f"  -> Uniform slit should give ~1.0x Airy (sinc^2 pattern)")

    # ===================================================================
    # TEST 2: GAUSSIAN footprint, sigma=255um (FWHM = 600um = 67% of D)
    # ===================================================================
    print("\n" + "-" * 72)
    print("  TEST 2: GAUSSIAN footprint, sigma=255um (FWHM=600um, 67% of D)")
    print("-" * 72)

    sigma_foot = 255e-6  # m
    fwhm_foot = sigma_foot * 2.355
    print(f"  Footprint sigma     : {sigma_foot*1e6:.0f} um")
    print(f"  Footprint FWHM      : {fwhm_foot*1e6:.0f} um ({fwhm_foot/D*100:.0f}% of D)")

    kick_fwhms_gauss = []
    for rep in range(n_repeats):
        foot = rng.normal(0, sigma_foot, size=n_rays * 2)
        foot = foot[np.abs(foot) <= D / 2][:n_rays]
        if len(foot) < n_rays:
            extra = rng.normal(0, sigma_foot, size=n_rays * 4)
            extra = extra[np.abs(extra) <= D / 2]
            foot = np.concatenate([foot, extra])[:n_rays]
        kicks = _hybridFF1D_python(foot, n_rays, D, lam, n_rays, rng=rng)
        spot = kicks * q
        fw = fwhm_from_samples(spot, n_bins=300)
        kick_fwhms_gauss.append(fw)

    mean_fw_gauss = np.mean(kick_fwhms_gauss)
    std_fw_gauss = np.std(kick_fwhms_gauss)
    ratio_gauss = mean_fw_gauss / airy_spot

    print(f"  Kick FWHM at sample : {mean_fw_gauss*1e9:.2f} +/- {std_fw_gauss*1e9:.2f} nm")
    print(f"  Airy spot           : {airy_spot*1e9:.2f} nm")
    print(f"  Ratio (kick/Airy)   : {ratio_gauss:.3f}")
    print(f"  -> Gaussian apodization should give > 1.0x Airy (broader diffraction)")

    # ===================================================================
    # TEST 3: FULL CONVOLUTION (Gaussian footprint)
    # ===================================================================
    print("\n" + "-" * 72)
    print("  TEST 3: FULL CONVOLUTION (geometric + diffraction)")
    print("-" * 72)

    geo_fwhm_nm = 33.0  # nm
    geo_sigma = geo_fwhm_nm * 1e-9 / 2.355

    total_fwhms = []
    for rep in range(n_repeats):
        # Geometric positions at sample
        geo_pos = rng.normal(0, geo_sigma, size=n_rays)

        # Diffraction kicks from Gaussian footprint
        foot = rng.normal(0, sigma_foot, size=n_rays * 2)
        foot = foot[np.abs(foot) <= D / 2][:n_rays]
        if len(foot) < n_rays:
            extra = rng.normal(0, sigma_foot, size=n_rays * 4)
            extra = extra[np.abs(extra) <= D / 2]
            foot = np.concatenate([foot, extra])[:n_rays]
        kicks = _hybridFF1D_python(foot, n_rays, D, lam, n_rays, rng=rng)

        # Total position = geometric + kick * q
        total_pos = geo_pos + kicks * q
        fw = fwhm_from_samples(total_pos, n_bins=300)
        total_fwhms.append(fw)

    mean_total = np.mean(total_fwhms)
    std_total = np.std(total_fwhms)
    quadrature = math.sqrt(geo_fwhm_nm**2 + (mean_fw_gauss * 1e9)**2)

    print(f"  Geometric FWHM      : {geo_fwhm_nm:.1f} nm")
    print(f"  Kick FWHM           : {mean_fw_gauss*1e9:.2f} nm")
    print(f"  Quadrature expected  : sqrt({geo_fwhm_nm:.1f}^2 + {mean_fw_gauss*1e9:.2f}^2) = {quadrature:.2f} nm")
    print(f"  Measured total FWHM  : {mean_total*1e9:.2f} +/- {std_total*1e9:.2f} nm")
    print(f"  Ratio (total/quad)   : {mean_total*1e9/quadrature:.3f}")
    print()
    print(f"  Comparison with other codes:")
    print(f"    S4 (Shadow4) result    : ~41 nm")
    print(f"    MC hybrid result       : ~50 nm")
    print(f"    This Python hybrid     : {mean_total*1e9:.1f} nm")

    # ===================================================================
    # TEST 4: PEAKED GAUSSIAN footprint, sigma=100um (FWHM=236um, 26% of D)
    # ===================================================================
    print("\n" + "-" * 72)
    print("  TEST 4: PEAKED GAUSSIAN footprint, sigma=100um (FWHM=236um, 26% of D)")
    print("-" * 72)

    sigma_peaked = 100e-6
    fwhm_peaked = sigma_peaked * 2.355
    print(f"  Footprint sigma     : {sigma_peaked*1e6:.0f} um")
    print(f"  Footprint FWHM      : {fwhm_peaked*1e6:.0f} um ({fwhm_peaked/D*100:.0f}% of D)")

    kick_fwhms_peaked = []
    for rep in range(n_repeats):
        foot = rng.normal(0, sigma_peaked, size=n_rays * 2)
        foot = foot[np.abs(foot) <= D / 2][:n_rays]
        if len(foot) < n_rays:
            extra = rng.normal(0, sigma_peaked, size=n_rays * 4)
            extra = extra[np.abs(extra) <= D / 2]
            foot = np.concatenate([foot, extra])[:n_rays]
        kicks = _hybridFF1D_python(foot, n_rays, D, lam, n_rays, rng=rng)
        spot = kicks * q
        fw = fwhm_from_samples(spot, n_bins=300)
        kick_fwhms_peaked.append(fw)

    mean_fw_peaked = np.mean(kick_fwhms_peaked)
    std_fw_peaked = np.std(kick_fwhms_peaked)
    ratio_peaked = mean_fw_peaked / airy_spot

    print(f"  Kick FWHM at sample : {mean_fw_peaked*1e9:.2f} +/- {std_fw_peaked*1e9:.2f} nm")
    print(f"  Airy spot           : {airy_spot*1e9:.2f} nm")
    print(f"  Ratio (kick/Airy)   : {ratio_peaked:.3f}")

    # Full convolution with peaked
    total_fwhms_peaked = []
    for rep in range(n_repeats):
        geo_pos = rng.normal(0, geo_sigma, size=n_rays)
        foot = rng.normal(0, sigma_peaked, size=n_rays * 2)
        foot = foot[np.abs(foot) <= D / 2][:n_rays]
        if len(foot) < n_rays:
            extra = rng.normal(0, sigma_peaked, size=n_rays * 4)
            extra = extra[np.abs(extra) <= D / 2]
            foot = np.concatenate([foot, extra])[:n_rays]
        kicks = _hybridFF1D_python(foot, n_rays, D, lam, n_rays, rng=rng)
        total_pos = geo_pos + kicks * q
        fw = fwhm_from_samples(total_pos, n_bins=300)
        total_fwhms_peaked.append(fw)

    mean_total_peaked = np.mean(total_fwhms_peaked)
    std_total_peaked = np.std(total_fwhms_peaked)
    quadrature_peaked = math.sqrt(geo_fwhm_nm**2 + (mean_fw_peaked * 1e9)**2)

    print(f"\n  Full convolution:")
    print(f"  Geometric FWHM      : {geo_fwhm_nm:.1f} nm")
    print(f"  Kick FWHM           : {mean_fw_peaked*1e9:.2f} nm")
    print(f"  Quadrature expected  : sqrt({geo_fwhm_nm:.1f}^2 + {mean_fw_peaked*1e9:.2f}^2) = {quadrature_peaked:.2f} nm")
    print(f"  Measured total FWHM  : {mean_total_peaked*1e9:.2f} +/- {std_total_peaked*1e9:.2f} nm")

    # ===================================================================
    # SUMMARY
    # ===================================================================
    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  {'Footprint':<25} {'Kick FWHM (nm)':<18} {'Total FWHM (nm)':<18} {'Ratio/Airy':<12}")
    print(f"  {'-'*25} {'-'*18} {'-'*18} {'-'*12}")
    print(f"  {'Uniform':<25} {mean_fw_uni*1e9:>8.2f}          {'N/A':>8}          {ratio_uni:>8.3f}")
    print(f"  {'Gaussian s=255um':<25} {mean_fw_gauss*1e9:>8.2f}          {mean_total*1e9:>8.2f}          {ratio_gauss:>8.3f}")
    print(f"  {'Gaussian s=100um':<25} {mean_fw_peaked*1e9:>8.2f}          {mean_total_peaked*1e9:>8.2f}          {ratio_peaked:>8.3f}")
    print()
    print(f"  Airy limit           : {airy_spot*1e9:.2f} nm")
    print(f"  S4 reference         : ~41 nm total")
    print(f"  MC reference         : ~50 nm total")
    print()

    # --- Interpretation ---
    print("  INTERPRETATION:")
    print("  ---------------")
    print(f"  1. Uniform footprint gives kick/Airy = {ratio_uni:.2f}")
    if ratio_uni > 0.9 and ratio_uni < 1.15:
        print("     -> Consistent with sinc^2 diffraction (close to Airy, as expected)")
    else:
        print(f"     -> Deviation from Airy: footprint shape affects diffraction envelope")
    print()
    print(f"  2. Gaussian (s=255um) footprint gives kick/Airy = {ratio_gauss:.2f}")
    if ratio_gauss > 1.0:
        print("     -> Gaussian apodization BROADENS diffraction (fewer illuminated fringes)")
        print("        The effective aperture is smaller than D, so diffraction is wider.")
    else:
        print("     -> Surprisingly narrow diffraction. Check algorithm.")
    print()
    print(f"  3. Full convolution with Gaussian footprint:")
    print(f"     Total = {mean_total*1e9:.1f} nm vs quadrature = {quadrature:.1f} nm")
    if abs(mean_total * 1e9 - quadrature) / quadrature < 0.1:
        print("     -> Good agreement with quadrature (Gaussian + Gaussian convolution)")
    else:
        print("     -> Deviation from quadrature (non-Gaussian kick distribution)")
    print()
    print(f"  4. Peaked Gaussian (s=100um) footprint:")
    print(f"     Total = {mean_total_peaked*1e9:.1f} nm vs Gaussian total = {mean_total*1e9:.1f} nm")
    if mean_total_peaked > mean_total:
        print("     -> Peaked footprint gives LARGER total (more diffraction broadening)")
    else:
        print("     -> Peaked footprint gives smaller total")
    print()
    print("  Physics: When the footprint is narrower than D, the effective aperture")
    print("  is reduced, causing MORE diffraction broadening. This is the key")
    print("  difference between geometric ray tracing and hybrid methods.")

    print("\n" + "=" * 72)
    print("  ALGORITHM DIAGNOSTIC: Internal parameters")
    print("=" * 72)
    # Show internal parameters for one run
    n_peaks = 20
    f_ff = D * D / (n_peaks * 2 * 0.88 * lam)
    fft_size_raw = round(100 * D * D / (lam * f_ff * 0.88))
    N = _next_pow2(fft_size_raw)
    if N > 131072:
        N = 131072
    delta_wf = D / (N - 1)

    print(f"  n_peaks              : {n_peaks}")
    print(f"  f_ff                 : {f_ff:.6f} m = {f_ff*1e3:.3f} mm")
    print(f"  fft_size_raw         : {fft_size_raw}")
    print(f"  N (power of 2)       : {N}")
    print(f"  delta (wavefront)    : {delta_wf:.6e} m = {delta_wf*1e9:.2f} nm")
    print(f"  k                    : {2*math.pi/lam:.6e} 1/m")
    print(f"  Fresnel coeff        : {-math.pi*lam*f_ff:.6e}")

    # image parameters
    z_min_approx = -D / 2
    z_max_approx = D / 2
    image_size_1 = min(abs(z_max_approx), abs(z_min_approx)) * 2
    image_size_2 = n_peaks * 2 * 0.88 * lam * f_ff / abs(z_max_approx - z_min_approx)
    image_size = min(image_size_1, image_size_2)
    image_n_pts = round(image_size / delta_wf / 2) * 2 + 1

    print(f"  image_size (option1) : {image_size_1*1e6:.3f} um (2*min(|zMax|,|zMin|))")
    print(f"  image_size (option2) : {image_size_2*1e6:.3f} um (n_peaks*2*0.88*lam*f_ff/D)")
    print(f"  image_size (chosen)  : {image_size*1e6:.3f} um")
    print(f"  image_n_pts          : {image_n_pts}")
    print(f"  image angular range  : +/- {(image_n_pts-1)/2*delta_wf/f_ff*1e6:.3f} urad")
    print(f"  image spatial range  : +/- {(image_n_pts-1)/2*delta_wf/f_ff*q*1e9:.2f} nm at sample")

    print("\n" + "=" * 72)
    print("  Done.")
    print("=" * 72)

if __name__ == "__main__":
    main()
