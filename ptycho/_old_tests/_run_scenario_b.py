"""
Scenario B: N_photons=1e8, scan_area=0.6um
10keV, 50nm beam, asize=256, z=1m
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

print(f"\n{'='*60}")
print(f"  Scenario B: 10keV, 50nm, asize=256, N_photons=1e8")
print(f"{'='*60}")
print(f"  pixel={pixel_nm:.2f}nm, scan_area={SCAN_AREA_UM}um")

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 50e-9, 'fwhm_v_m': 80e-9,
     'focal_length_m': 0.205, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
print(f"  probe FWHM={fwhm_px:.1f}px ({fwhm_px*pixel_nm:.1f}nm)")

scan_area_px = SCAN_AREA_UM * 1e-6 / pixel_m
obj_size = int(np.ceil(scan_area_px)) + asize + 20
print(f"  scan_area={scan_area_px:.1f}px, object={obj_size}px")

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=SCAN_AREA_UM, scan_ly_um=SCAN_AREA_UM,
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

probes_in = p['probes'][:,:,0,0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print(f"\n  Running DM 200 iterations...")
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=200)

print(f"  DM error: iter1={err_dm[1]:.4e} -> iter200={err_dm[200]:.4e}")

from engines.ML import ML

print(f"\n  Running ML 50 iterations...")
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
pr_final = p_ml['probes'][:,:,0,0] if p_ml['probes'].ndim == 4 else p_ml['probes']

# Quality metric
truth = ds.object_true.squeeze()
oh, ow = ob_final.shape
th, tw = truth.shape
ch, cw = min(oh, th), min(ow, tw)
ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
ob_aligned = ob_c * np.exp(-1j * phase_diff)
norm_error = np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

grade = "EXCELLENT" if norm_error < 0.15 else "GOOD" if norm_error < 0.30 else "MARGINAL" if norm_error < 0.50 else "POOR"
print(f"\n{'='*60}")
print(f"  RESULT: Scenario B (N_photons=1e8)")
print(f"{'='*60}")
print(f"  |obj| range: [{np.abs(ob_final).min():.4f}, {np.abs(ob_final).max():.4f}]")
print(f"  Normalized error: {norm_error:.4f} -> {grade}")

# Save result image
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))

    # Row 1: Input
    axes[0,0].imshow(np.abs(ds.probe), cmap='jet')
    axes[0,0].set_title(f'Input Probe |P|\nFWHM={fwhm_px:.1f}px')
    axes[0,1].imshow(np.abs(truth), cmap='jet')
    axes[0,1].set_title('Ground Truth |O|')
    axes[0,2].imshow(np.angle(truth), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,2].set_title('Ground Truth Phase')

    # Row 2: Reconstruction
    oa = np.abs(ob_final)
    p99 = np.percentile(oa, 99.5) * 1.1
    axes[1,0].imshow(oa, cmap='jet', vmin=0, vmax=p99)
    axes[1,0].set_title(f'Recon |obj|\nmax={oa.max():.3f}')
    axes[1,1].imshow(np.angle(ob_final), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1,1].set_title(f'Recon Phase\nerror={norm_error:.4f} ({grade})')

    # Error convergence
    valid_err = err_dm[1:]
    axes[1,2].semilogy(range(1, len(valid_err)+1), valid_err)
    axes[1,2].set_xlabel('Iteration')
    axes[1,2].set_ylabel('Fourier Error')
    axes[1,2].set_title('DM Error Convergence')
    axes[1,2].grid(True, alpha=0.3)

    for ax in axes.flat:
        if ax != axes[1,2]:
            ax.axis('off')

    fig.suptitle(f'Scenario B: 10keV, 50nm, asize=256, N_photons=1e8\n'
                 f'DM200+ML50, scan_area={SCAN_AREA_UM}um, error={norm_error:.4f} ({grade})',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / '_scenario_b_1e8_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
