"""
Generate Fig 4: MC vs Shadow4 beam profile comparison
=====================================================
Uses unified 301x301 histograms at +/-150nm FOV.
MC data: JS MC engine via Node.js standalone
S4 data: Shadow4 via workstation

Usage:
    python paper/validation/generate_fig4.py

Output:
    paper/figures/_panels/fig4_mc_2d.png
    paper/figures/_panels/fig4_s4_2d.png
    paper/figures/_panels/fig4_h_profile.png
    paper/figures/_panels/fig4_v_profile.png
    paper/figures/fig4_mc_vs_shadow4.tif  (combined 2x2)
"""

import os, sys, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

# Paths
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MC_JSON = os.path.join(BASE, 'paper/validation/data/mc_10keV_ssa50_js.json')
S4_JSON = os.path.join(BASE, 'paper/validation/data/s4_10keV_ssa50_uni.json')
PANEL_DIR = os.path.join(BASE, 'paper/figures/_panels')
FIG_DIR = os.path.join(BASE, 'paper/figures')

os.makedirs(PANEL_DIR, exist_ok=True)

# JSR 2-column figure style
DPI = 600
plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 9,
    'axes.labelsize': 9,
    'axes.titlesize': 10,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'legend.fontsize': 8,
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
})


def load_json(path):
    with open(path) as f:
        return json.load(f)


def fwhm_from_profile(x, y):
    """Compute FWHM from 1D profile by half-max interpolation."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    mx = np.max(y)
    if mx <= 0:
        return 0
    hm = mx * 0.5
    # Left crossing
    x0 = x[0]
    for i in range(1, len(y)):
        if y[i - 1] < hm <= y[i]:
            t = (hm - y[i - 1]) / (y[i] - y[i - 1] + 1e-30)
            x0 = x[i - 1] + t * (x[i] - x[i - 1])
            break
    # Right crossing
    x1 = x[-1]
    for i in range(len(y) - 1, 0, -1):
        if y[i] < hm <= y[i - 1]:
            t = (hm - y[i]) / (y[i - 1] - y[i] + 1e-30)
            x1 = x[i] + t * (x[i - 1] - x[i])
            break
    return abs(x1 - x0)


# ====== Load data ======
mc = load_json(MC_JSON)
s4 = load_json(S4_JSON)

# MC: flat array -> 2D
NBINS = mc['uni_nbins']  # 301
FOV_nm = mc['uni_fov_nm']  # 150
mc_hist2d = np.array(mc['uni_hist2d']).reshape(NBINS, NBINS)
mc_margH = np.array(mc['uni_margH'])
mc_margV = np.array(mc['uni_margV'])

# S4: nested array -> 2D
# np.histogram2d(rays_h, rays_v) gives hist[H_idx, V_idx]
# imshow displays rows=Y, cols=X, so we need .T to get hist[V_idx, H_idx]
s4_hist2d = np.array(s4['uni_hist2d']).T
s4_margH = np.array(s4['uni_marg_h'])
s4_margV = np.array(s4['uni_marg_v'])

# Bin centers (nm)
bin_centers = np.linspace(-FOV_nm, FOV_nm, NBINS)

# ====== FWHM from marginals ======
mc_fwhm_h = fwhm_from_profile(bin_centers, mc_margH)
mc_fwhm_v = fwhm_from_profile(bin_centers, mc_margV)
s4_fwhm_h = fwhm_from_profile(bin_centers, s4_margH)
s4_fwhm_v = fwhm_from_profile(bin_centers, s4_margV)

print(f'MC FWHM:  H={mc_fwhm_h:.1f}nm  V={mc_fwhm_v:.1f}nm')
print(f'S4 FWHM:  H={s4_fwhm_h:.1f}nm  V={s4_fwhm_v:.1f}nm')
print(f'Dev:  H={((mc_fwhm_h - s4_fwhm_h) / s4_fwhm_h * 100):+.1f}%  '
      f'V={((mc_fwhm_v - s4_fwhm_v) / s4_fwhm_v * 100):+.1f}%')

# ====== Normalize ======
mc_norm = mc_hist2d / mc_hist2d.max() if mc_hist2d.max() > 0 else mc_hist2d
s4_norm = s4_hist2d / s4_hist2d.max() if s4_hist2d.max() > 0 else s4_hist2d

# ====== Individual panels ======

def plot_2d(hist_norm, title, fwhm_h, fwhm_v, outpath):
    """Plot a single 2D beam profile panel."""
    fig, ax = plt.subplots(figsize=(3.2, 3.0))
    extent = [-FOV_nm, FOV_nm, -FOV_nm, FOV_nm]
    im = ax.imshow(hist_norm, origin='lower', extent=extent,
                   cmap='inferno', vmin=0, vmax=1, aspect='equal',
                   interpolation='bilinear')
    ax.set_xlabel('H (nm)')
    ax.set_ylabel('V (nm)')
    ax.set_title(title, fontweight='bold')
    cb = fig.colorbar(im, ax=ax, shrink=0.85, pad=0.02)
    cb.set_label('Normalized intensity')
    fig.tight_layout()
    fig.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    print(f'  Saved: {outpath}')


def plot_profile(bin_c, mc_marg, s4_marg, axis_label, mc_fw, s4_fw, outpath):
    """Plot 1D profile overlay."""
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    mc_n = mc_marg / mc_marg.max() if mc_marg.max() > 0 else mc_marg
    s4_n = s4_marg / s4_marg.max() if s4_marg.max() > 0 else s4_marg
    ax.plot(bin_c, mc_n, '-', color='#e74c3c', lw=1.2, label=f'MC ({mc_fw:.1f} nm)')
    ax.plot(bin_c, s4_n, '--', color='#2980b9', lw=1.2, label=f'S4 ({s4_fw:.1f} nm)')
    ax.axhline(0.5, color='gray', lw=0.5, ls=':')
    ax.set_xlabel(f'{axis_label} (nm)')
    ax.set_ylabel('Normalized intensity')
    ax.set_xlim(-100, 100)
    ax.set_ylim(-0.05, 1.1)
    ax.legend(loc='upper right')
    fig.tight_layout()
    fig.savefig(outpath, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    print(f'  Saved: {outpath}')


# Generate individual panels
print('\nGenerating panels...')
plot_2d(mc_norm, 'MC Ray Tracing', mc_fwhm_h, mc_fwhm_v,
        os.path.join(PANEL_DIR, 'fig4_mc_2d.png'))
plot_2d(s4_norm, 'Shadow4', s4_fwhm_h, s4_fwhm_v,
        os.path.join(PANEL_DIR, 'fig4_s4_2d.png'))
plot_profile(bin_centers, mc_margH, s4_margH, 'H', mc_fwhm_h, s4_fwhm_h,
             os.path.join(PANEL_DIR, 'fig4_h_profile.png'))
plot_profile(bin_centers, mc_margV, s4_margV, 'V', mc_fwhm_v, s4_fwhm_v,
             os.path.join(PANEL_DIR, 'fig4_v_profile.png'))


# ====== Combined 2x2 figure ======
print('\nGenerating combined figure...')
fig, axes = plt.subplots(2, 2, figsize=(6.85, 5.5))
extent = [-FOV_nm, FOV_nm, -FOV_nm, FOV_nm]

# (a) MC 2D
ax = axes[0, 0]
im = ax.imshow(mc_norm, origin='lower', extent=extent,
               cmap='inferno', vmin=0, vmax=1, aspect='equal',
               interpolation='bilinear')
ax.set_xlabel('H (nm)')
ax.set_ylabel('V (nm)')
ax.set_title('(a) MC Ray Tracing', fontweight='bold')
fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

# (b) S4 2D
ax = axes[0, 1]
im = ax.imshow(s4_norm, origin='lower', extent=extent,
               cmap='inferno', vmin=0, vmax=1, aspect='equal',
               interpolation='bilinear')
ax.set_xlabel('H (nm)')
ax.set_ylabel('V (nm)')
ax.set_title('(b) Shadow4', fontweight='bold')
fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

# (c) H profile overlay
ax = axes[1, 0]
mc_mH_n = mc_margH / mc_margH.max() if mc_margH.max() > 0 else mc_margH
s4_mH_n = s4_margH / s4_margH.max() if s4_margH.max() > 0 else s4_margH
ax.plot(bin_centers, mc_mH_n, '-', color='#e74c3c', lw=1.2,
        label=f'MC ({mc_fwhm_h:.1f} nm)')
ax.plot(bin_centers, s4_mH_n, '--', color='#2980b9', lw=1.2,
        label=f'S4 ({s4_fwhm_h:.1f} nm)')
ax.axhline(0.5, color='gray', lw=0.5, ls=':')
ax.set_xlabel('H (nm)')
ax.set_ylabel('Normalized intensity')
ax.set_xlim(-100, 100)
ax.set_ylim(-0.05, 1.1)
ax.set_title('(c) H profile', fontweight='bold')
ax.legend(loc='upper right', fontsize=7)

# (d) V profile overlay
ax = axes[1, 1]
mc_mV_n = mc_margV / mc_margV.max() if mc_margV.max() > 0 else mc_margV
s4_mV_n = s4_margV / s4_margV.max() if s4_margV.max() > 0 else s4_margV
ax.plot(bin_centers, mc_mV_n, '-', color='#e74c3c', lw=1.2,
        label=f'MC ({mc_fwhm_v:.1f} nm)')
ax.plot(bin_centers, s4_mV_n, '--', color='#2980b9', lw=1.2,
        label=f'S4 ({s4_fwhm_v:.1f} nm)')
ax.axhline(0.5, color='gray', lw=0.5, ls=':')
ax.set_xlabel('V (nm)')
ax.set_ylabel('Normalized intensity')
ax.set_xlim(-100, 100)
ax.set_ylim(-0.05, 1.1)
ax.set_title('(d) V profile', fontweight='bold')
ax.legend(loc='upper right', fontsize=7)

fig.tight_layout(pad=1.0)
tif_path = os.path.join(FIG_DIR, 'fig4_mc_vs_shadow4.tif')
fig.savefig(tif_path, dpi=DPI, bbox_inches='tight')
png_path = os.path.join(PANEL_DIR, 'fig4_combined.png')
fig.savefig(png_path, dpi=150, bbox_inches='tight')
plt.close(fig)
print(f'  Saved: {tif_path}')
print(f'  Saved: {png_path}')

# ====== Comparison summary ======
print(f'\n=== Comparison Summary ===')
print(f'MC:  H={mc_fwhm_h:.1f}nm  V={mc_fwhm_v:.1f}nm  '
      f'({mc["nFocused"]} focused / {mc["nTotal"]} total)')
print(f'S4:  H={s4_fwhm_h:.1f}nm  V={s4_fwhm_v:.1f}nm  '
      f'({s4["nrays_good"]} good / {s4["nrays_total"]} total)')
print(f'Dev: H={((mc_fwhm_h - s4_fwhm_h) / s4_fwhm_h * 100):+.1f}%  '
      f'V={((mc_fwhm_v - s4_fwhm_v) / s4_fwhm_v * 100):+.1f}%')
