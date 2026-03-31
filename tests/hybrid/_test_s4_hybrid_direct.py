"""Direct comparison: S4 WOFRY hybrid vs our JS-equivalent implementation.
Creates same Gaussian beam footprint and compares angular kick distributions."""
import numpy as np

# Parameters: 10keV, KB-V
lambda_m = 12.398 / 10.0 * 1e-10  # 0.124 nm
D = 900e-6  # beam footprint range = mirror aperture
sigma = 255e-6  # Gaussian sigma of footprint
n_peaks = 20
f_ff = D**2 / (n_peaks * 2 * 0.88 * lambda_m)
print(f"lambda = {lambda_m*1e10:.4f} A")
print(f"D = {D*1e6:.0f} um")
print(f"sigma = {sigma*1e6:.0f} um")
print(f"f_ff = {f_ff:.1f} m")
print(f"Airy FWHM = {0.88*lambda_m/D*1e6:.4f} urad")
print()

# Generate Gaussian footprint (same as MC would have)
np.random.seed(42)
n_rays = 5500
foot = np.random.normal(0, sigma, n_rays)
# Clip to mirror aperture
foot = foot[(foot > -D/2) & (foot < D/2)]
n_rays = len(foot)
print(f"Rays after clipping: {n_rays}")
print(f"Foot range: [{foot.min()*1e6:.1f}, {foot.max()*1e6:.1f}] um")
print(f"Foot sigma: {foot.std()*1e6:.1f} um")
print()

# ====== S4-like implementation (WOFRY-style, 4000 points, no padding) ======
def s4_hybrid_ff(foot, D, lambda_m, n_peaks=20, fft_size=4000):
    """S4 hybrid far-field: exact WOFRY implementation."""
    f_ff = D**2 / (n_peaks * 2 * 0.88 * lambda_m)
    k = 2 * np.pi / lambda_m

    # Histogram (200 bins like S4)
    n_bins = min(200, len(foot) // 20)
    n_bins = max(n_bins, 10)
    hist, bin_edges = np.histogram(foot, bins=n_bins)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    # Create wavefront: fft_size points spanning [z_min, z_max]
    z_min, z_max = foot.min(), foot.max()
    z = np.linspace(z_min, z_max, fft_size)
    dz = z[1] - z[0]

    # Interpolate histogram to wavefront grid
    amplitude = np.sqrt(np.maximum(0, np.interp(z, bin_centers, hist)))

    # Thin-lens phase
    z_centered = z - (z_min + z_max) / 2
    phase = -k * z_centered**2 / (2 * f_ff)
    wavefront = amplitude * np.exp(1j * phase)

    # Fresnel TF propagation (WOFRY-style, no padding)
    fft_scale = np.fft.fftfreq(fft_size) / dz
    fft = np.fft.fft(wavefront)
    kernel = np.exp(-1j * np.pi * lambda_m * f_ff * fft_scale**2)
    fft *= kernel
    output = np.fft.ifft(fft)

    # Intensity
    intensity = np.abs(output)**2

    # Image size cropping (S4 convention)
    center = (z_min + z_max) / 2
    abs_zmin = abs(z_min - center)
    abs_zmax = abs(z_max - center)
    image_half_1 = min(abs_zmax, abs_zmin)
    image_half_2 = n_peaks * 0.88 * lambda_m * f_ff / D
    image_half = min(image_half_1, image_half_2)

    # Angular coordinates
    theta = (z - center) / f_ff
    theta_max = image_half / f_ff

    # Crop
    mask = np.abs(theta) <= theta_max
    theta_crop = theta[mask]
    intens_crop = intensity[mask]

    return theta_crop, intens_crop, dz, f_ff

# ====== JS-like implementation (256 bins, padded to 8192) ======
def js_hybrid_ff(foot, D, lambda_m, n_peaks=20, n_bins=256):
    """JS-equivalent hybrid: 256 bins, zero-padded to 8192."""
    f_ff = D**2 / (n_peaks * 2 * 0.88 * lambda_m)
    k = 2 * np.pi / lambda_m

    # Histogram
    z_min, z_max = foot.min(), foot.max()
    h_margin = (z_max - z_min) * 0.02
    h_min = z_min - h_margin
    h_max = z_max + h_margin
    dz = (h_max - h_min) / n_bins
    hist = np.zeros(n_bins)
    for pos in foot:
        b = int((pos - h_min) / dz)
        if 0 <= b < n_bins:
            hist[b] += 1

    # FFT size (Nyquist-aware)
    N_nyquist = int(np.ceil(lambda_m * f_ff / dz**2))
    N = 1
    while N < max(n_bins * 2, N_nyquist * 4):
        N *= 2
    if N > 131072:
        N = 131072

    # Build wavefront: centered at DFT index 0
    re = np.zeros(N)
    im = np.zeros(N)
    n_half = n_bins // 2
    center = (h_min + h_max) / 2

    for i in range(n_bins):
        amp = np.sqrt(max(0, hist[i]))
        zc = h_min + (i + 0.5) * dz - center
        phi = -k * zc**2 / (2 * f_ff)
        di = i - n_half
        if di < 0:
            di += N
        re[di] = amp * np.cos(phi)
        im[di] = amp * np.sin(phi)

    wavefront = re + 1j * im

    # FFT
    fft = np.fft.fft(wavefront)

    # TF kernel
    for j in range(N):
        fj = j / (N * dz) if j <= N // 2 else (j - N) / (N * dz)
        phase = -np.pi * lambda_m * f_ff * fj**2
        fft[j] *= np.exp(1j * phase)

    # IFFT
    output = np.fft.ifft(fft)

    # Intensity
    intensity = np.abs(output)**2

    # fftshift
    shifted = np.fft.fftshift(intensity)

    # Angular grid
    theta = np.arange(N) * dz / f_ff
    theta = theta - theta[N // 2]

    # Image size cropping
    abs_zmin = abs(z_min - center)
    abs_zmax = abs(z_max - center)
    image_half_1 = min(abs_zmax, abs_zmin)
    image_half_2 = n_peaks * 0.88 * lambda_m * f_ff / D
    image_half = min(image_half_1, image_half_2)
    theta_max = image_half / f_ff

    mask = np.abs(theta) <= theta_max
    theta_crop = theta[mask]
    intens_crop = shifted[mask]

    return theta_crop, intens_crop, dz, f_ff, N

# Run both
print("=== S4-style (4000 pts, no pad) ===")
th_s4, int_s4, dz_s4, f_ff_s4 = s4_hybrid_ff(foot, D, lambda_m)
print(f"  dz = {dz_s4*1e6:.3f} um, N = 4000")

# FWHM measurement
peak = int_s4.max()
half_max = peak / 2
above = np.where(int_s4 >= half_max)[0]
if len(above) > 1:
    fwhm_s4 = th_s4[above[-1]] - th_s4[above[0]]
    print(f"  Angular FWHM = {fwhm_s4*1e6:.4f} urad")
    print(f"  Position FWHM at q=0.31m: {fwhm_s4*0.31*1e9:.1f} nm")
else:
    print("  Could not measure FWHM")
    fwhm_s4 = 0

print()
print("=== JS-style (256 bins, padded) ===")
th_js, int_js, dz_js, f_ff_js, N_js = js_hybrid_ff(foot, D, lambda_m)
print(f"  dz = {dz_js*1e6:.3f} um, N = {N_js}")

peak = int_js.max()
half_max = peak / 2
above = np.where(int_js >= half_max)[0]
if len(above) > 1:
    fwhm_js = th_js[above[-1]] - th_js[above[0]]
    print(f"  Angular FWHM = {fwhm_js*1e6:.4f} urad")
    print(f"  Position FWHM at q=0.31m: {fwhm_js*0.31*1e9:.1f} nm")
else:
    print("  Could not measure FWHM")
    fwhm_js = 0

print()
if fwhm_s4 > 0 and fwhm_js > 0:
    print(f"JS/S4 FWHM ratio: {fwhm_js/fwhm_s4:.4f}")
    print(f"Airy FWHM (uniform D): {0.88*lambda_m/D*1e6:.4f} urad")
    print(f"Gaussian far-field FWHM: {0.375*lambda_m/(sigma*np.sqrt(2))*1e6:.4f} urad")

# Also test with uniform aperture for validation
print()
print("=== Uniform aperture validation ===")
foot_uniform = np.linspace(-D/2, D/2, n_rays)
th_s4u, int_s4u, _, _ = s4_hybrid_ff(foot_uniform, D, lambda_m)
th_jsu, int_jsu, _, _, _ = js_hybrid_ff(foot_uniform, D, lambda_m)

peak_s4u = int_s4u.max()
above_s4u = np.where(int_s4u >= peak_s4u/2)[0]
fwhm_s4u = th_s4u[above_s4u[-1]] - th_s4u[above_s4u[0]] if len(above_s4u) > 1 else 0

peak_jsu = int_jsu.max()
above_jsu = np.where(int_jsu >= peak_jsu/2)[0]
fwhm_jsu = th_jsu[above_jsu[-1]] - th_jsu[above_jsu[0]] if len(above_jsu) > 1 else 0

print(f"  S4 uniform FWHM: {fwhm_s4u*1e6:.4f} urad (theory: {0.88*lambda_m/D*1e6:.4f})")
print(f"  JS uniform FWHM: {fwhm_jsu*1e6:.4f} urad (theory: {0.88*lambda_m/D*1e6:.4f})")
if fwhm_s4u > 0:
    print(f"  S4/theory: {fwhm_s4u/(0.88*lambda_m/D):.4f}")
if fwhm_jsu > 0:
    print(f"  JS/theory: {fwhm_jsu/(0.88*lambda_m/D):.4f}")
if fwhm_s4u > 0 and fwhm_jsu > 0:
    print(f"  JS/S4: {fwhm_jsu/fwhm_s4u:.4f}")
