"""
Scenario A: crop center of recon and compare to ground truth.
Reloads the DM+ML result from saved data or re-runs.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

# Same params as _run_scenario_a.py
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = int(1e8)
SCAN_AREA_UM = 1.1

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_m = lam * z_m / (asize * det_pixel_m)
pixel_nm = pixel_m * 1e9
scan_area_px = SCAN_AREA_UM * 1e-6 / pixel_m

# Regenerate data (same seed -> same result)
dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
     'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=SCAN_AREA_UM, scan_ly_um=SCAN_AREA_UM,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)

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

# Run DM
from engines.gpu.DM import DM as DM_GPU
probes_in = p['probes'][:,:,0,0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print("Running DM 200...")
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=200)

# Skip ML (DM only for center comparison)
ob_final = ob_dm[0].squeeze()

# Ground truth
truth = ds.object_true.squeeze()
oh, ow = ob_final.shape
th, tw = truth.shape

# Crop center (scan area only)
crop_px = int(scan_area_px)  # ~53 px
ch = min(crop_px, oh, th)
cw = min(crop_px, ow, tw)

ob_center = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
tr_center = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]

# Phase alignment
phase_diff = np.angle(np.sum(ob_center * np.conj(tr_center)))
ob_aligned = ob_center * np.exp(-1j * phase_diff)

# Amplitude alignment: normalize recon to match truth amplitude scale
scale = np.sqrt(np.sum(np.abs(tr_center)**2) / np.sum(np.abs(ob_aligned)**2))
ob_scaled = ob_aligned * scale

# Error metrics
norm_error_raw = np.sqrt(np.sum(np.abs(ob_aligned - tr_center)**2) / np.sum(np.abs(tr_center)**2))
norm_error_scaled = np.sqrt(np.sum(np.abs(ob_scaled - tr_center)**2) / np.sum(np.abs(tr_center)**2))

# Also try full-object comparison with center crop
full_ch, full_cw = min(oh, th), min(ow, tw)
ob_full_c = ob_final[oh//2-full_ch//2:oh//2+full_ch//2, ow//2-full_cw//2:ow//2+full_cw//2]
tr_full_c = truth[th//2-full_ch//2:th//2+full_ch//2, tw//2-full_cw//2:tw//2+full_cw//2]
pd_full = np.angle(np.sum(ob_full_c * np.conj(tr_full_c)))
norm_error_full = np.sqrt(np.sum(np.abs(ob_full_c * np.exp(-1j * pd_full) - tr_full_c)**2) / np.sum(np.abs(tr_full_c)**2))

print(f"\n{'='*60}")
print(f"  Center Crop Comparison (crop={ch}x{cw} px = scan area)")
print(f"{'='*60}")
print(f"  Full object error (no crop): {norm_error_full:.4f}")
print(f"  Center crop error (raw):     {norm_error_raw:.4f}")
print(f"  Center crop error (scaled):  {norm_error_scaled:.4f}")
print(f"  Amplitude scale factor:       {scale:.4f}")
print(f"  |recon center|: [{np.abs(ob_center).min():.4f}, {np.abs(ob_center).max():.4f}]")
print(f"  |truth center|: [{np.abs(tr_center).min():.4f}, {np.abs(tr_center).max():.4f}]")

grade_raw = "EXCELLENT" if norm_error_raw < 0.15 else "GOOD" if norm_error_raw < 0.30 else "MARGINAL" if norm_error_raw < 0.50 else "POOR"
grade_scaled = "EXCELLENT" if norm_error_scaled < 0.15 else "GOOD" if norm_error_scaled < 0.30 else "MARGINAL" if norm_error_scaled < 0.50 else "POOR"
print(f"  Grade (raw):    {grade_raw}")
print(f"  Grade (scaled): {grade_scaled}")

# Save comparison image
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 4, figsize=(18, 9))

    # Row 1: Full object
    axes[0,0].imshow(np.abs(truth), cmap='jet')
    axes[0,0].set_title('Ground Truth |O|')
    axes[0,1].imshow(np.abs(ob_final), cmap='jet')
    axes[0,1].set_title(f'Recon |O| (full)\nerr={norm_error_full:.4f}')
    axes[0,2].imshow(np.angle(truth), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,2].set_title('Truth Phase')
    axes[0,3].imshow(np.angle(ob_final), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,3].set_title('Recon Phase')

    # Row 2: Center crop
    p99_tr = np.percentile(np.abs(tr_center), 99.5) * 1.1
    axes[1,0].imshow(np.abs(tr_center), cmap='jet', vmin=0, vmax=p99_tr)
    axes[1,0].set_title(f'Truth Center\n{ch}x{cw}px')
    axes[1,1].imshow(np.abs(ob_scaled), cmap='jet', vmin=0, vmax=p99_tr)
    axes[1,1].set_title(f'Recon Center (scaled)\nerr={norm_error_scaled:.4f} ({grade_scaled})')
    axes[1,2].imshow(np.angle(tr_center), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1,2].set_title('Truth Center Phase')
    axes[1,3].imshow(np.angle(ob_scaled), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1,3].set_title(f'Recon Center Phase\nerr_raw={norm_error_raw:.4f} ({grade_raw})')

    for ax in axes.flat:
        ax.axis('off')
    fig.suptitle(f'Scenario A: Center Crop ({ch}x{cw}px) vs Full Object\n'
                 f'DM200 only, N_photons=1e8, scan_area={SCAN_AREA_UM}um\n'
                 f'Full err={norm_error_full:.4f}, Center err(raw)={norm_error_raw:.4f}, Center err(scaled)={norm_error_scaled:.4f}',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / '_scenario_a_crop_compare.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
