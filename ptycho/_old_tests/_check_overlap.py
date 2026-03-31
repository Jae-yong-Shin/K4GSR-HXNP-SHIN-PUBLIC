"""Check probe size vs scan step - overlap diagnostic."""
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader

params = {
    'dataset_id': 6, 'asize': 128,
    'energy_keV': 10.0, 'material': 'Au', 'objheight': 1e-6,
    'z_m': 5.0, 'det_pixel_m': 75e-6,
    'scan_step_um': 1.5, 'scan_lx_um': 10.0, 'scan_ly_um': 10.0,
    'N_photons': int(1e8),
    'mc_probe': {
        'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
        'focal_length_m': 0.1, 'defocus_m': 0.0,
    },
    'N_modes': 1, 'coherent_fraction': 1.0,
}

loader = DataLoader()
data = loader.generate_synthetic(params)

probe = data['probes']
positions = data['positions']
dx_nm = data['pixel_size_nm']
asize = 128

print(f"=== Overlap Diagnostic ===")
print(f"pixel_size: {dx_nm:.2f} nm")
print(f"probe shape: {probe.shape}")
print(f"positions: {positions.shape[0]} pts")

# Probe profile
amp = np.abs(probe)
print(f"\nProbe amplitude:")
print(f"  max: {amp.max():.4f}")
print(f"  sum|P|^2: {(amp**2).sum():.1f}")

# FWHM of probe
row_profile = amp[asize//2, :]
half_max = row_profile.max() / 2
above = np.where(row_profile > half_max)[0]
if len(above) > 1:
    fwhm_px = above[-1] - above[0]
else:
    fwhm_px = 0
print(f"  FWHM (row profile): {fwhm_px} px = {fwhm_px * dx_nm:.0f} nm")

# Effective probe extent (where amplitude > 1% of max)
thresh_1pct = amp.max() * 0.01
above_1pct = np.where(amp > thresh_1pct)
extent_h = above_1pct[0].max() - above_1pct[0].min() if len(above_1pct[0]) else 0
extent_w = above_1pct[1].max() - above_1pct[1].min() if len(above_1pct[1]) else 0
print(f"  1% extent: {extent_h} x {extent_w} px")

# Probe power distribution
total_power = (amp**2).sum()
core_mask = amp > amp.max() * 0.5
core_power = (amp[core_mask]**2).sum()
print(f"  Power in core (>50% max): {core_power/total_power*100:.1f}%")

sidelobe_power = total_power - core_power
print(f"  Power in sidelobes: {sidelobe_power/total_power*100:.1f}%")

# Scan step in pixels
step_px = 1.5e3 / dx_nm  # 1.5 um -> nm -> px
print(f"\nScan step: 1.5 um = {step_px:.1f} px")
print(f"Overlap (vs FWHM): {(1 - step_px/fwhm_px)*100:.0f}%" if fwhm_px > 0 else "Overlap: N/A")
print(f"Overlap (vs 1% extent): {(1 - step_px/max(extent_h,extent_w))*100:.0f}%")

# Nearest-neighbor distance
from scipy.spatial import distance
if len(positions) > 1:
    D = distance.cdist(positions, positions)
    np.fill_diagonal(D, np.inf)
    nn_dist = D.min(axis=1)
    print(f"\nNearest neighbor distances:")
    print(f"  mean: {nn_dist.mean():.1f} px = {nn_dist.mean()*dx_nm:.0f} nm")
    print(f"  min:  {nn_dist.min():.1f} px")
    print(f"  max:  {nn_dist.max():.1f} px")

# Object
obj_true = data.get('object_true')
if obj_true is not None:
    obj_amp = np.abs(obj_true)
    obj_phase = np.angle(obj_true)
    print(f"\nObject:")
    print(f"  shape: {obj_true.shape}")
    print(f"  amplitude range: [{obj_amp.min():.4f}, {obj_amp.max():.4f}]")
    print(f"  phase range: [{obj_phase.min():.4f}, {obj_phase.max():.4f}] rad")

# Save probe image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 4, figsize=(20, 5))

# Probe amplitude (log scale)
axes[0].imshow(np.log10(amp + 1e-10), cmap='jet')
axes[0].set_title(f'Probe amplitude (log)\nFWHM={fwhm_px}px, 1%extent={extent_h}x{extent_w}px')

# Probe profile
axes[1].semilogy(row_profile, 'b-', label='row profile')
axes[1].axhline(half_max, color='r', ls='--', label=f'FWHM={fwhm_px}px')
axes[1].axvline(asize//2 - step_px/2, color='g', ls=':', label=f'step={step_px:.0f}px')
axes[1].axvline(asize//2 + step_px/2, color='g', ls=':')
axes[1].set_title('Probe row profile (log)')
axes[1].legend(fontsize=8)

# Scan positions on object
if obj_true is not None:
    axes[2].imshow(np.abs(obj_true), cmap='jet')
    axes[2].scatter(positions[:,1], positions[:,0], c='red', s=10, alpha=0.7)
    axes[2].set_title(f'Scan positions on object\n{len(positions)} pts, step={step_px:.0f}px')

# Object phase
if obj_true is not None:
    axes[3].imshow(np.angle(obj_true), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[3].set_title(f'Object phase\nrange=[{obj_phase.min():.2f}, {obj_phase.max():.2f}] rad')

plt.tight_layout()
out = str(Path(__file__).parent / '_overlap_diagnostic.png')
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n[SAVED] {out}")
