"""
Scenario B: Full DM200+ML50, comprehensive result image.
Same layout and colorscale standard as Scenario A.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

# Parameters
asize = 256
energy_keV = 10.0
z_m = 1.0
det_pixel_m = 75e-6
N_photons = int(1e8)
SCAN_AREA_UM = 0.6

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_m = lam * z_m / (asize * det_pixel_m)
pixel_nm = pixel_m * 1e9
scan_area_px = SCAN_AREA_UM * 1e-6 / pixel_m

print(f"Scenario B: pixel={pixel_nm:.2f}nm, scan_area={scan_area_px:.1f}px")

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 50e-9, 'fwhm_v_m': 80e-9,
     'focal_length_m': 0.205, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=SCAN_AREA_UM, scan_ly_um=SCAN_AREA_UM,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"Npos={ds.Npos}, overlap={ds.overlap:.2f}")

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 200, 'use_gpu': True,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

# ---- DM ----
from engines.gpu.DM import DM as DM_GPU
probes_in = p['probes'][:,:,0,0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print("Running DM 200...")
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=200)
print(f"DM done. err: {err_dm[1]:.4e} -> {err_dm[200]:.4e}")

# ---- ML ----
from engines.ML import ML
print("Running ML 50...")
p_ml = dict(p)
p_ml['opt_iter'] = 50
p_ml['opt_flags'] = [1, 1]
p_ml['opt_errmetric'] = 'poisson'
p_ml['object'] = [o[:,:,np.newaxis] if o.ndim == 2 else o for o in ob_dm]
if pr_dm.ndim == 2:
    p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
else:
    p_ml['probes'] = pr_dm
if isinstance(p_ml.get('object_size'), list):
    p_ml['object_size'] = np.array(p_ml['object_size'])
p_ml, fdb_ml = ML(p_ml)

ob_final = p_ml['object'][0].squeeze()
pr_final = p_ml['probes'][:,:,0,0] if p_ml['probes'].ndim == 4 else p_ml['probes'].squeeze()

# ---- Metrics (center crop) ----
truth = ds.object_true.squeeze()
oh, ow = ob_final.shape
th, tw = truth.shape
crop_px = int(scan_area_px)
ch = min(crop_px, oh, th)
cw = min(crop_px, ow, tw)

ob_center = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
tr_center = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
phase_diff = np.angle(np.sum(ob_center * np.conj(tr_center)))
ob_aligned = ob_center * np.exp(-1j * phase_diff)
norm_error = np.sqrt(np.sum(np.abs(ob_aligned - tr_center)**2) / np.sum(np.abs(tr_center)**2))
grade = "EXCELLENT" if norm_error < 0.15 else "GOOD" if norm_error < 0.30 else "MARGINAL" if norm_error < 0.50 else "POOR"

print(f"\nCenter crop {ch}x{cw}px error: {norm_error:.4f} ({grade})")

# ---- ML error from errorplot ----
from core.errorplot import errorplot
ml_errors = errorplot([])
errorplot()  # clear

# ---- Plot (MATLAB PtychoShelves sp_quantile standard) ----
def ptycho_clim(data_2d, mask=None, q_lo=1e-4, q_hi=1-1e-4):
    vals = data_2d[mask].ravel() if mask is not None else data_2d.ravel()
    vmin = float(np.percentile(vals, q_lo * 100))
    vmax = float(np.percentile(vals, q_hi * 100))
    if vmax <= vmin:
        vmax = vmin + 1e-12
    return vmin, vmax

def make_scan_mask(obj_shape, positions, asize):
    mask = np.zeros(obj_shape, dtype=bool)
    for pos in positions:
        r, c = int(round(pos[0])), int(round(pos[1]))
        mask[r:r+asize, c:c+asize] = True
    return mask

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 5, figsize=(22, 9))

input_probe = ds.probe
ob_full_aligned = ob_final * np.exp(-1j * phase_diff)
scan_mask = make_scan_mask(ob_full_aligned.shape, ds.positions_clean, asize)

amp_gt_full = np.abs(truth)
amp_recon_full = np.abs(ob_full_aligned)
gt_amp_clim = ptycho_clim(amp_gt_full, scan_mask)
rec_amp_clim = ptycho_clim(amp_recon_full, scan_mask)

# Apply scan mask to display: NaN outside scan area (MATLAB plot_mask style)
amp_gt_masked = np.where(scan_mask, amp_gt_full, np.nan)
phase_gt_masked = np.where(scan_mask, np.angle(truth), np.nan)
amp_recon_masked = np.where(scan_mask, amp_recon_full, np.nan)
phase_recon_masked = np.where(scan_mask, np.angle(ob_full_aligned), np.nan)

# Row 1: GT & Input
ax = axes[0,0]
ax.imshow(amp_gt_masked, cmap='jet', vmin=gt_amp_clim[0], vmax=gt_amp_clim[1])
ax.set_title('GT Object |O|')
ax.axis('off')

ax = axes[0,1]
ax.imshow(phase_gt_masked, cmap='hsv', vmin=-np.pi, vmax=np.pi)
ax.set_title('GT Phase')
ax.axis('off')

ax = axes[0,2]
amp_pin = np.abs(input_probe)
ax.imshow(amp_pin, cmap='jet')
ax.set_title(f'Input Probe |P|\nFWHM={fwhm_px:.1f}px')
ax.axis('off')

ax = axes[0,3]
phase_pin = np.angle(input_probe)
mask_pin = amp_pin > 0.05 * amp_pin.max()
ax.imshow(np.where(mask_pin, phase_pin, np.nan), cmap='hsv', vmin=-np.pi, vmax=np.pi)
ax.set_title('Input Probe Phase')
ax.axis('off')

ax = axes[0,4]
valid_dm = err_dm[1:]
ax.semilogy(range(1, len(valid_dm)+1), valid_dm, 'b-', linewidth=1.5)
ax.set_xlabel('Iteration')
ax.set_ylabel('Fourier Error')
ax.set_title(f'DM Error\n{err_dm[1]:.2e} -> {err_dm[200]:.2e}')
ax.grid(True, alpha=0.3)

# Row 2: Reconstruction
ax = axes[1,0]
ax.imshow(amp_recon_masked, cmap='jet', vmin=rec_amp_clim[0], vmax=rec_amp_clim[1])
ax.set_title(f'Recon |O|\ncenter err={norm_error:.4f} ({grade})')
ax.axis('off')

ax = axes[1,1]
ax.imshow(phase_recon_masked, cmap='hsv', vmin=-np.pi, vmax=np.pi)
ax.set_title('Recon Phase')
ax.axis('off')

ax = axes[1,2]
amp_prec = np.abs(pr_final)
ax.imshow(amp_prec, cmap='jet')
ax.set_title(f'Recon Probe |P|\nmax={amp_prec.max():.1f}')
ax.axis('off')

ax = axes[1,3]
phase_prec = np.angle(pr_final)
mask_prec = amp_prec > 0.05 * amp_prec.max()
ax.imshow(np.where(mask_prec, phase_prec, np.nan), cmap='hsv', vmin=-np.pi, vmax=np.pi)
ax.set_title('Recon Probe Phase')
ax.axis('off')

ax = axes[1,4]
if ml_errors is not None and len(ml_errors) > 0:
    ax.semilogy(range(1, len(ml_errors)+1), ml_errors, 'r-', linewidth=1.5)
    ax.set_title(f'ML Error\n{ml_errors[0]:.2e} -> {ml_errors[-1]:.2e}')
else:
    ax.text(0.5, 0.5, 'ML error\nnot available', ha='center', va='center', transform=ax.transAxes)
    ax.set_title('ML Error')
ax.set_xlabel('Iteration')
ax.set_ylabel('Error')
ax.grid(True, alpha=0.3)

fig.suptitle(f'Scenario B: 10keV, 50nm, asize=256, N_photons=1e8, scan_area={SCAN_AREA_UM}um\n'
             f'DM200+ML50 | Center crop {ch}x{cw}px | error={norm_error:.4f} ({grade})',
             fontsize=14, fontweight='bold')
plt.tight_layout()
out = Path(__file__).parent / '_scenario_b_full_compare.png'
fig.savefig(str(out), dpi=150)
plt.close()
print(f"\nSaved: {out}")
print("DONE")
