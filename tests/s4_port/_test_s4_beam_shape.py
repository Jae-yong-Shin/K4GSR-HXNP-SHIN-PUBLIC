"""Compare S4 geometric beam shape vs Gaussian, and test convolution with diffraction."""
import numpy as np
import sys
sys.path.insert(0, 'c:/Projects/K4GSR-Beamline/paper/validation')
from shadow4_bl10 import run_shadow4_bl10

# 1. Run S4 geometric-only
print("=== S4 Geometric beam shape ===")
r = run_shadow4_bl10(10.0, 50, nrays=200000, seed=12345, hybrid=False, verbose=False)
if not r:
    print("ERROR: S4 failed"); sys.exit(1)

# Extract marginal histograms
marg_v = r['fine_marg_v']
marg_h = r['fine_marg_h']
fov_v = r['fine_fov_v_m']
fov_h = r['fine_fov_h_m']
nbins = r['fine_grid']
fwhm_v_geo = r['fine_fwhm_v_m']
fwhm_h_geo = r['fine_fwhm_h_m']
sig_v = r['fine_sig_v_m']
sig_h = r['fine_sig_h_m']

print(f"  FWHM V = {fwhm_v_geo*1e9:.1f} nm, sigma V = {sig_v*1e9:.1f} nm, FWHM/sigma = {fwhm_v_geo/sig_v:.3f}")
print(f"  FWHM H = {fwhm_h_geo*1e9:.1f} nm, sigma H = {sig_h*1e9:.1f} nm, FWHM/sigma = {fwhm_h_geo/sig_h:.3f}")
print(f"  (Gaussian FWHM/sigma = 2.355)")

# Compute kurtosis from marginal
dx_v = 2 * fov_v / nbins
centers_v = np.linspace(-fov_v + dx_v/2, fov_v - dx_v/2, nbins)
dx_h = 2 * fov_h / nbins
centers_h = np.linspace(-fov_h + dx_h/2, fov_h - dx_h/2, nbins)

# Weighted kurtosis from marginal
def marginal_kurtosis(marg, centers):
    total = marg.sum()
    if total <= 0: return 0
    p = marg / total
    mean = np.sum(p * centers)
    var = np.sum(p * (centers - mean)**2)
    if var <= 0: return 0
    kurt = np.sum(p * (centers - mean)**4) / var**2 - 3  # excess kurtosis
    return kurt

kurt_v = marginal_kurtosis(np.array(marg_v, dtype=float), centers_v)
kurt_h = marginal_kurtosis(np.array(marg_h, dtype=float), centers_h)
print(f"  Kurtosis V = {kurt_v:.3f} (0=Gaussian, >0=heavy tails, <0=light tails)")
print(f"  Kurtosis H = {kurt_h:.3f}")

# 2. Generate diffraction kick distribution
print("\n=== Diffraction kick distribution ===")
E_keV = 10.0
lam = 12.398 / E_keV * 1e-10
D_V = 900e-6
D_H = 300e-6
sigma_foot_V = 255e-6
sigma_foot_H = 86e-6
n_peaks = 20
q_V = 0.31
q_H = 0.10

def compute_diffraction_profile(D, sigma_foot, lam, n_bins_out=501):
    """Compute diffraction kick angular profile using f_ff trick."""
    f_ff = D**2 / (n_peaks * 2 * 0.88 * lam)
    k = 2 * np.pi / lam

    # Gaussian footprint
    np.random.seed(42)
    n_rays = 50000
    foot = np.random.normal(0, sigma_foot, n_rays * 2)
    foot = foot[(foot > -D/2) & (foot < D/2)][:n_rays]

    # Histogram
    n_bins = 256
    h_margin = (foot.max() - foot.min()) * 0.02
    h_min = foot.min() - h_margin
    h_max = foot.max() + h_margin
    dz = (h_max - h_min) / n_bins
    hist, _ = np.histogram(foot, bins=n_bins, range=(h_min, h_max))

    # FFT size (Nyquist-aware)
    N_nyquist = int(np.ceil(lam * f_ff / dz**2))
    N = 1
    while N < max(n_bins * 2, N_nyquist * 4):
        N *= 2

    # Build wavefront
    wf = np.zeros(N, dtype=complex)
    n_half = n_bins // 2
    center = (h_min + h_max) / 2
    for i in range(n_bins):
        amp = np.sqrt(max(0, hist[i]))
        zc = h_min + (i + 0.5) * dz - center
        phi = -k * zc**2 / (2 * f_ff)
        di = (i - n_half) % N
        wf[di] = amp * np.exp(1j * phi)

    # Propagate
    fft = np.fft.fft(wf)
    freq = np.fft.fftfreq(N, dz)
    fft *= np.exp(-1j * np.pi * lam * f_ff * freq**2)
    output = np.fft.ifft(fft)

    # Intensity
    intensity = np.abs(output)**2
    shifted = np.fft.fftshift(intensity)

    # Angular grid
    dtheta = dz / f_ff
    theta = (np.arange(N) - N//2) * dtheta

    # Crop
    abs_zmin = abs(foot.min() - center)
    abs_zmax = abs(foot.max() - center)
    image_half = min(min(abs_zmax, abs_zmin), n_peaks * 0.88 * lam * f_ff / D)
    theta_max = image_half / f_ff
    mask = np.abs(theta) <= theta_max

    return theta[mask], shifted[mask], dtheta

# Get kick profiles
theta_v, kick_prof_v, dtheta_v = compute_diffraction_profile(D_V, sigma_foot_V, lam)
theta_h, kick_prof_h, dtheta_h = compute_diffraction_profile(D_H, sigma_foot_H, lam)

# Measure kick profile FWHM
def profile_fwhm(x, y):
    mx = y.max()
    above = np.where(y >= mx/2)[0]
    if len(above) < 2: return 0
    return x[above[-1]] - x[above[0]]

kick_fwhm_v = profile_fwhm(theta_v, kick_prof_v)
kick_fwhm_h = profile_fwhm(theta_h, kick_prof_h)
print(f"  KB-V kick FWHM = {kick_fwhm_v*1e6:.4f} urad = {kick_fwhm_v*q_V*1e9:.1f} nm at sample")
print(f"  KB-H kick FWHM = {kick_fwhm_h*1e6:.4f} urad = {kick_fwhm_h*q_H*1e9:.1f} nm at sample")

# 3. Convolve S4 geometric marginal with diffraction kick profile
print("\n=== Histogram convolution ===")

def convolve_and_fwhm(geo_marg, geo_dx, kick_theta, kick_prof, q):
    """Convolve geometric marginal with diffraction kicks in position space."""
    # Convert kick angular profile to position profile at sample
    kick_pos = kick_theta * q  # position at sample
    kick_dx = kick_pos[1] - kick_pos[0] if len(kick_pos) > 1 else 1e-12

    # Resample kick profile onto same grid as geometric
    kick_pos_resampled = np.arange(-len(geo_marg)//2, len(geo_marg)//2 + 1) * geo_dx
    kick_resampled = np.interp(kick_pos_resampled, kick_pos, kick_prof, left=0, right=0)

    # Convolve
    conv = np.convolve(geo_marg, kick_resampled, 'full')
    conv_x = np.arange(len(conv)) * geo_dx

    # Measure FWHM
    mx = conv.max()
    above = np.where(conv >= mx/2)[0]
    if len(above) < 2: return 0
    return (above[-1] - above[0]) * geo_dx

# S4 geometric marginal convolved with diffraction
conv_fwhm_v = convolve_and_fwhm(np.array(marg_v, dtype=float), dx_v, theta_v, kick_prof_v, q_V)
conv_fwhm_h = convolve_and_fwhm(np.array(marg_h, dtype=float), dx_h, theta_h, kick_prof_h, q_H)
print(f"  S4_geo conv kick V: FWHM = {conv_fwhm_v*1e9:.1f} nm (S4 hybrid = 44.8 nm)")
print(f"  S4_geo conv kick H: FWHM = {conv_fwhm_h*1e9:.1f} nm (S4 hybrid = 43.0 nm)")

# Gaussian geometric convolved with diffraction
def gaussian_marg(fwhm, nbins, fov):
    sigma = fwhm / 2.355
    x = np.linspace(-fov, fov, nbins)
    return np.exp(-x**2 / (2 * sigma**2)), x[1] - x[0]

gauss_marg_v, gauss_dx_v = gaussian_marg(fwhm_v_geo, nbins, fov_v)
gauss_marg_h, gauss_dx_h = gaussian_marg(fwhm_h_geo, nbins, fov_h)

gauss_conv_v = convolve_and_fwhm(gauss_marg_v, gauss_dx_v, theta_v, kick_prof_v, q_V)
gauss_conv_h = convolve_and_fwhm(gauss_marg_h, gauss_dx_h, theta_h, kick_prof_h, q_H)
print(f"  Gauss_geo conv kick V: FWHM = {gauss_conv_v*1e9:.1f} nm")
print(f"  Gauss_geo conv kick H: FWHM = {gauss_conv_h*1e9:.1f} nm")

# Top-hat geometric convolved with diffraction
def tophat_marg(fwhm, nbins, fov):
    x = np.linspace(-fov, fov, nbins)
    marg = np.where(np.abs(x) <= fwhm/2, 1.0, 0.0)
    return marg, x[1] - x[0]

th_marg_v, th_dx_v = tophat_marg(fwhm_v_geo, nbins, fov_v)
th_marg_h, th_dx_h = tophat_marg(fwhm_h_geo, nbins, fov_h)

th_conv_v = convolve_and_fwhm(th_marg_v, th_dx_v, theta_v, kick_prof_v, q_V)
th_conv_h = convolve_and_fwhm(th_marg_h, th_dx_h, theta_h, kick_prof_h, q_H)
print(f"  Tophat_geo conv kick V: FWHM = {th_conv_v*1e9:.1f} nm")
print(f"  Tophat_geo conv kick H: FWHM = {th_conv_h*1e9:.1f} nm")

# Quadrature predictions
quad_v = np.sqrt(fwhm_v_geo**2 + (kick_fwhm_v * q_V)**2)
quad_h = np.sqrt(fwhm_h_geo**2 + (kick_fwhm_h * q_H)**2)
print(f"\n  Quadrature V = {quad_v*1e9:.1f} nm")
print(f"  Quadrature H = {quad_h*1e9:.1f} nm")

print(f"\n=== SUMMARY TABLE ===")
print(f"{'Method':<25s} {'V (nm)':>8s} {'H (nm)':>8s}  {'V dev':>8s} {'H dev':>8s}")
print(f"{'S4 geometric':<25s} {fwhm_v_geo*1e9:8.1f} {fwhm_h_geo*1e9:8.1f}")
print(f"{'Kick FWHM (at sample)':<25s} {kick_fwhm_v*q_V*1e9:8.1f} {kick_fwhm_h*q_H*1e9:8.1f}")
print(f"{'S4 hybrid (reference)':<25s} {'44.8':>8s} {'43.0':>8s}")
print(f"{'S4_geo conv kick':<25s} {conv_fwhm_v*1e9:8.1f} {conv_fwhm_h*1e9:8.1f}  {abs(conv_fwhm_v*1e9-44.8)/44.8*100:7.1f}% {abs(conv_fwhm_h*1e9-43.0)/43.0*100:7.1f}%")
print(f"{'Gauss_geo conv kick':<25s} {gauss_conv_v*1e9:8.1f} {gauss_conv_h*1e9:8.1f}  {abs(gauss_conv_v*1e9-44.8)/44.8*100:7.1f}% {abs(gauss_conv_h*1e9-43.0)/43.0*100:7.1f}%")
print(f"{'Tophat_geo conv kick':<25s} {th_conv_v*1e9:8.1f} {th_conv_h*1e9:8.1f}  {abs(th_conv_v*1e9-44.8)/44.8*100:7.1f}% {abs(th_conv_h*1e9-43.0)/43.0*100:7.1f}%")
print(f"{'Quadrature (Gaussian)':<25s} {quad_v*1e9:8.1f} {quad_h*1e9:8.1f}  {abs(quad_v*1e9-44.8)/44.8*100:7.1f}% {abs(quad_h*1e9-43.0)/43.0*100:7.1f}%")
