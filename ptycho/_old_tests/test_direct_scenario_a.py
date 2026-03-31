"""
Direct test with known-good Scenario A parameters (6.2keV, 200nm, asize=128, z=1m).
Verifies the DM engine itself works correctly.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = 1000

lambda_m = 1239.842e-9 / (energy_keV * 1e3)
dx_spec = lambda_m * z_m / (asize * det_pixel_m)
pixel_nm = dx_spec * 1e9

print(f"Direct test: Scenario A (6.2keV, 200nm, asize=128, z=1m)")
print(f"  dx = {pixel_nm:.2f} nm, FOV = {asize * pixel_nm:.0f} nm")

dl = DataLoader()
beam_params = {
    'fwhm_h_m': 200e-9,
    'fwhm_v_m': 200e-9,
    'focal_length_m': 0.3,
    'defocus_m': 0.0,
}
probe = dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
print(f"  Probe FWHM = {fwhm_px:.1f} px ({fwhm_px * pixel_nm:.1f} nm)")

# Compute scan area same as compare_recon.py
step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)
print(f"  scan_area = {scan_area_um:.2f} um")

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2f}")

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

from engines.gpu.DM import DM as DM_GPU
probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print(f"\nRunning DM 200 (direct, GPU)...")
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=200)

print(f"\nDM Error (selected):")
for i in [1, 2, 10, 50, 100, 150, 200]:
    if i < len(err_dm):
        print(f"  iter {i}: {err_dm[i]:.6e}")

from engines.ML import ML
print(f"\nRunning ML 50...")
p_ml = dict(p)
p_ml['opt_iter'] = 50
p_ml['opt_flags'] = [1, 1]
p_ml['opt_errmetric'] = 'poisson'
p_ml['object'] = [o[:, :, np.newaxis] if o.ndim == 2 else o for o in ob_dm]
if pr_dm.ndim == 2:
    p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
else:
    p_ml['probes'] = pr_dm
if isinstance(p_ml.get('object_size'), list):
    p_ml['object_size'] = np.array(p_ml['object_size'])
p_ml, fdb_ml = ML(p_ml)

ob_final = p_ml['object'][0].squeeze()

oa = np.abs(ob_final)
truth = ds.object_true.squeeze()
oh, ow = ob_final.shape
th, tw = truth.shape
ch, cw = min(oh, th), min(ow, tw)
ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
ob_aligned = ob_c * np.exp(-1j * phase_diff)
norm_error = np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

print(f"\n{'='*60}")
print(f"  QUALITY (Direct Call, Scenario A)")
print(f"{'='*60}")
print(f"  |obj|: [{oa.min():.4f}, {oa.max():.4f}]")
print(f"  Normalized error: {norm_error:.4f}")
if norm_error < 0.15:
    print(f"  >> EXCELLENT")
elif norm_error < 0.30:
    print(f"  >> GOOD")
elif norm_error < 0.50:
    print(f"  ** MARGINAL")
else:
    print(f"  !! POOR")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(14, 9))
    axes[0,0].imshow(np.abs(ds.probe), cmap='hot')
    axes[0,0].set_title(f'Input Probe |P|\nFWHM={fwhm_px:.1f}px')
    axes[0,1].imshow(np.abs(truth), cmap='gray')
    axes[0,1].set_title('Ground Truth |O|')
    axes[0,2].imshow(np.angle(truth), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,2].set_title('Ground Truth Phase')
    axes[1,0].imshow(oa, cmap='gray')
    axes[1,0].set_title(f'Recon |obj| max={oa.max():.3f}')
    axes[1,1].imshow(np.angle(ob_final), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1,1].set_title(f'Recon Phase\nerror={norm_error:.4f}')
    valid_err = err_dm[1:]
    axes[1,2].semilogy(range(1, len(valid_err)+1), valid_err)
    axes[1,2].set_xlabel('Iteration'); axes[1,2].set_ylabel('Fourier Error')
    axes[1,2].set_title('DM Error'); axes[1,2].grid(True, alpha=0.3)
    for ax in axes[:2, :3].flat:
        if ax != axes[1,2]: ax.axis('off')
    fig.suptitle(f'Direct: Scenario A (6.2keV, 200nm, asize=128)\n'
                 f'DM200+ML50, error={norm_error:.4f}', fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_direct_scenarioA_result.png'
    plt.savefig(out, dpi=150); plt.close()
    print(f"\nResult: {out}")
except ImportError:
    pass
