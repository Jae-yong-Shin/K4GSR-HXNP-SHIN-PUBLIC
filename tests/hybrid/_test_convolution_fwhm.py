"""
Test: FWHM of convolutions between different distribution shapes.

Goal: Determine whether convolution of Gaussian with Airy (sinc^2) gives
sub-quadrature FWHM, which would explain why Shadow4 gives ~41nm while
MC ray tracing gives ~50nm.

Key insight: quadrature addition sqrt(a^2 + b^2) is exact ONLY for
Gaussian * Gaussian. For other shape combinations the actual FWHM can
be significantly different.
"""

import numpy as np

# =============================================================
# 1. Define distributions on a fine grid
# =============================================================
dx = 0.1  # nm
x = np.arange(-500, 500 + dx/2, dx)  # -500 to +500 nm
N = len(x)

# --- Gaussian(FWHM=33nm) ---
fwhm_gauss33 = 33.0
sigma_33 = fwhm_gauss33 / (2 * np.sqrt(2 * np.log(2)))  # = 33 / 2.3548 = 14.01nm
gauss_33 = np.exp(-x**2 / (2 * sigma_33**2))
gauss_33 /= np.sum(gauss_33) * dx  # normalize to unit area

# --- Airy 1D: sinc^2(pi*x/a), FWHM = 37nm ---
# For sinc^2: FWHM ~ 0.886 * a, so a = 37 / 0.886
fwhm_airy37 = 37.0
a_airy = fwhm_airy37 / 0.8859  # 0.8859 is more precise
airy_37 = np.ones_like(x)
mask_nonzero = (x != 0)
arg = np.pi * x[mask_nonzero] / a_airy
airy_37[mask_nonzero] = (np.sin(arg) / arg)**2
airy_37 /= np.sum(airy_37) * dx

# --- Rect (uniform): FWHM = 34nm ---
fwhm_rect34 = 34.0
half_w = fwhm_rect34 / 2.0  # 17nm
rect_34 = np.where(np.abs(x) < half_w, 1.0, 0.0)
# handle edge exactly
rect_34[np.abs(np.abs(x) - half_w) < dx/2] = 0.5
rect_34 /= np.sum(rect_34) * dx

# --- Gaussian(FWHM=37nm) for quadrature reference ---
fwhm_gauss37 = 37.0
sigma_37 = fwhm_gauss37 / (2 * np.sqrt(2 * np.log(2)))
gauss_37 = np.exp(-x**2 / (2 * sigma_37**2))
gauss_37 /= np.sum(gauss_37) * dx


# =============================================================
# Helper: measure FWHM from a 1D profile by half-max crossings
# =============================================================
def measure_fwhm(x_arr, y_arr):
    """Measure FWHM by interpolating half-maximum crossings."""
    y_max = np.max(y_arr)
    half_max = y_max / 2.0

    # Find where y crosses half-max (rising and falling)
    above = y_arr >= half_max
    # Find first crossing (left side)
    diff = np.diff(above.astype(int))

    # Rising edges (0->1 transitions)
    rising = np.where(diff == 1)[0]
    # Falling edges (1->0 transitions)
    falling = np.where(diff == -1)[0]

    if len(rising) == 0 or len(falling) == 0:
        return float('nan')

    # Interpolate left crossing
    i_left = rising[0]
    x_left = x_arr[i_left] + (half_max - y_arr[i_left]) / (y_arr[i_left+1] - y_arr[i_left]) * (x_arr[i_left+1] - x_arr[i_left])

    # Interpolate right crossing
    i_right = falling[-1]
    x_right = x_arr[i_right] + (half_max - y_arr[i_right]) / (y_arr[i_right+1] - y_arr[i_right]) * (x_arr[i_right+1] - x_arr[i_right])

    return x_right - x_left


# =============================================================
# Verify individual FWHMs
# =============================================================
print("=" * 70)
print("INDIVIDUAL DISTRIBUTION FWHM VERIFICATION")
print("=" * 70)
print(f"  Gaussian (target 33nm):  measured = {measure_fwhm(x, gauss_33):.2f} nm")
print(f"  Airy/sinc2 (target 37nm): measured = {measure_fwhm(x, airy_37):.2f} nm")
print(f"  Rect (target 34nm):      measured = {measure_fwhm(x, rect_34):.2f} nm")
print(f"  Gaussian (target 37nm):  measured = {measure_fwhm(x, gauss_37):.2f} nm")
print()


# =============================================================
# 2. Compute convolutions and measure FWHM
# =============================================================
def convolve_and_measure(f, g, x_arr, dx_val):
    """Convolve two distributions and return (x_conv, y_conv, fwhm)."""
    y_conv = np.convolve(f, g, mode='full') * dx_val
    n_conv = len(y_conv)
    x_conv = np.arange(n_conv) * dx_val
    x_conv -= x_conv[n_conv // 2]  # center
    fwhm = measure_fwhm(x_conv, y_conv)
    return x_conv, y_conv, fwhm


print("=" * 70)
print("CONVOLUTION RESULTS")
print("=" * 70)
print(f"{'Case':<45} {'FWHM':>8} {'Quad':>8} {'Ratio':>8}")
print("-" * 70)

# (a) Gaussian(33) * Gaussian(37) -- should be sqrt(33^2 + 37^2) = 49.57nm
_, _, fwhm_gg = convolve_and_measure(gauss_33, gauss_37, x, dx)
quad_gg = np.sqrt(33**2 + 37**2)
print(f"  (a) Gauss(33) * Gauss(37)                  {fwhm_gg:8.2f} {quad_gg:8.2f} {fwhm_gg/quad_gg:8.4f}")

# (b) Gaussian(33) * Airy(37) -- THE KEY TEST
_, _, fwhm_ga = convolve_and_measure(gauss_33, airy_37, x, dx)
quad_ga = np.sqrt(33**2 + 37**2)
print(f"  (b) Gauss(33) * Airy(37)   *** KEY ***      {fwhm_ga:8.2f} {quad_ga:8.2f} {fwhm_ga/quad_ga:8.4f}")

# (c) Rect(34) * Airy(37)
_, _, fwhm_ra = convolve_and_measure(rect_34, airy_37, x, dx)
quad_ra = np.sqrt(34**2 + 37**2)
print(f"  (c) Rect(34) * Airy(37)                    {fwhm_ra:8.2f} {quad_ra:8.2f} {fwhm_ra/quad_ra:8.4f}")

# (d) will be done below (MC style)

# (e) Rect(34) * Gaussian(37)
_, _, fwhm_rg = convolve_and_measure(rect_34, gauss_37, x, dx)
quad_rg = np.sqrt(34**2 + 37**2)
print(f"  (e) Rect(34) * Gauss(37)                   {fwhm_rg:8.2f} {quad_rg:8.2f} {fwhm_rg/quad_rg:8.4f}")

# Extra: Airy * Airy for completeness
fwhm_airy33 = 33.0
a_airy33 = fwhm_airy33 / 0.8859
airy_33 = np.ones_like(x)
mask33 = (x != 0)
arg33 = np.pi * x[mask33] / a_airy33
airy_33[mask33] = (np.sin(arg33) / arg33)**2
airy_33 /= np.sum(airy_33) * dx

_, _, fwhm_aa = convolve_and_measure(airy_33, airy_37, x, dx)
quad_aa = np.sqrt(33**2 + 37**2)
print(f"  (f) Airy(33) * Airy(37)                    {fwhm_aa:8.2f} {quad_aa:8.2f} {fwhm_aa/quad_aa:8.4f}")

print()
print("  Ratio < 1.0 means sub-quadrature (actual FWHM < quadrature prediction)")
print("  Ratio = 1.0 means exact quadrature (Gauss*Gauss only)")
print("  Ratio > 1.0 means super-quadrature")
print()

# =============================================================
# 3. Analysis: what FWHM would explain Shadow4 = 41nm?
# =============================================================
print("=" * 70)
print("SHADOW4 vs MC ANALYSIS")
print("=" * 70)
print(f"  If geometric source FWHM = 33nm and KB diffraction FWHM = 37nm:")
print(f"    Quadrature prediction:           {quad_ga:.1f} nm  (MC ray tracing result)")
print(f"    Gauss*Airy convolution:           {fwhm_ga:.1f} nm  (wave-optics convolution)")
print(f"    Shadow4 measured:                 ~41 nm")
print(f"    MC measured:                      ~50 nm")
print()
if fwhm_ga < quad_ga:
    deficit = quad_ga - fwhm_ga
    print(f"  --> Gauss*Airy is {deficit:.1f}nm BELOW quadrature ({fwhm_ga/quad_ga:.3f}x)")
    print(f"      This {'CAN' if abs(fwhm_ga - 41) < 5 else 'CANNOT'} explain the Shadow4 vs MC discrepancy.")
else:
    print(f"  --> Gauss*Airy is NOT sub-quadrature. Other effects must explain Shadow4.")
print()


# =============================================================
# 4. Monte Carlo style test
# =============================================================
print("=" * 70)
print("MONTE CARLO STYLE TEST (50000 samples)")
print("=" * 70)

np.random.seed(42)
N_mc = 50000

# Generate Gaussian samples (FWHM=33nm)
mc_gauss = np.random.normal(0, sigma_33, N_mc)

# Generate Airy (sinc^2) samples via inverse CDF
# sinc^2 PDF: p(x) = sinc^2(pi*x/a) / integral
# Use rejection sampling since CDF is not analytically invertible
def sample_sinc2(a_param, n_samples):
    """Sample from sinc^2(pi*x/a) distribution using rejection sampling."""
    samples = []
    # sinc^2 peak is 1 at x=0
    # For efficiency, sample in range [-10*a, 10*a]
    x_range = 10 * a_param
    while len(samples) < n_samples:
        batch_size = n_samples * 3  # oversample
        x_try = np.random.uniform(-x_range, x_range, batch_size)
        u = np.random.uniform(0, 1, batch_size)
        arg_try = np.pi * x_try / a_param
        # sinc^2 value (handle x=0)
        sinc2_val = np.ones_like(arg_try)
        nz = arg_try != 0
        sinc2_val[nz] = (np.sin(arg_try[nz]) / arg_try[nz])**2
        accepted = x_try[u < sinc2_val]
        samples.extend(accepted.tolist())
    return np.array(samples[:n_samples])

mc_airy = sample_sinc2(a_airy, N_mc)

# Sum them (convolution in sample space)
mc_total = mc_gauss + mc_airy

# Measure FWHM from histogram
bins = np.linspace(-200, 200, 2001)
hist_total, bin_edges = np.histogram(mc_total, bins=bins, density=True)
bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

fwhm_mc = measure_fwhm(bin_centers, hist_total)

# Also measure individual component histograms for verification
hist_gauss, _ = np.histogram(mc_gauss, bins=bins, density=True)
hist_airy, _ = np.histogram(mc_airy, bins=bins, density=True)

fwhm_mc_gauss = measure_fwhm(bin_centers, hist_gauss)
fwhm_mc_airy = measure_fwhm(bin_centers, hist_airy)

print(f"  Gaussian samples FWHM (target 33nm): {fwhm_mc_gauss:.1f} nm")
print(f"  Airy samples FWHM (target 37nm):     {fwhm_mc_airy:.1f} nm")
print(f"  Sum (Gauss+Airy) FWHM:               {fwhm_mc:.1f} nm")
print(f"  Quadrature prediction:                {quad_ga:.1f} nm")
print(f"  Ratio (MC / quadrature):              {fwhm_mc/quad_ga:.4f}")
print(f"  Analytic convolution FWHM:            {fwhm_ga:.1f} nm")
print()


# =============================================================
# 5. Summary table
# =============================================================
print("=" * 70)
print("SUMMARY: Sub-quadrature behavior by distribution shape")
print("=" * 70)
print()
print(f"  Distribution pair          | FWHM_1 | FWHM_2 | Conv FWHM | Quad pred | Ratio")
print(f"  {'-'*85}")
print(f"  Gauss * Gauss              |  33.0  |  37.0  |  {fwhm_gg:7.2f}  |  {quad_gg:7.2f}  | {fwhm_gg/quad_gg:.4f}")
print(f"  Gauss * Airy (sinc^2)      |  33.0  |  37.0  |  {fwhm_ga:7.2f}  |  {quad_ga:7.2f}  | {fwhm_ga/quad_ga:.4f}")
print(f"  Rect  * Airy (sinc^2)      |  34.0  |  37.0  |  {fwhm_ra:7.2f}  |  {quad_ra:7.2f}  | {fwhm_ra/quad_ra:.4f}")
print(f"  Rect  * Gauss              |  34.0  |  37.0  |  {fwhm_rg:7.2f}  |  {quad_rg:7.2f}  | {fwhm_rg/quad_rg:.4f}")
print(f"  Airy  * Airy               |  33.0  |  37.0  |  {fwhm_aa:7.2f}  |  {quad_aa:7.2f}  | {fwhm_aa/quad_aa:.4f}")
print(f"  Gauss * Airy (MC 50k)      |  33.0  |  37.0  |  {fwhm_mc:7.1f}   |  {quad_ga:7.2f}  | {fwhm_mc/quad_ga:.4f}")
print()
print("  Conclusion:")
if fwhm_ga < quad_ga * 0.95:
    print(f"  --> Gauss*Airy convolution is SIGNIFICANTLY sub-quadrature ({fwhm_ga/quad_ga:.3f}x)")
    print(f"      The sinc^2 tails are wide but contain little area near half-max,")
    print(f"      so the FWHM grows slower than quadrature predicts.")
    print(f"      This explains why Shadow4 (wave-optics) gives ~41nm while")
    print(f"      MC ray tracing (quadrature assumption) gives ~50nm.")
elif fwhm_ga < quad_ga:
    print(f"  --> Gauss*Airy is mildly sub-quadrature ({fwhm_ga/quad_ga:.3f}x)")
    print(f"      This partially explains the Shadow4 vs MC discrepancy.")
else:
    print(f"  --> Gauss*Airy is NOT sub-quadrature. Other effects needed.")
print()
