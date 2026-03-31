"""
Compare reconstruction: direct engine call vs server pipeline.
Uses IDENTICAL data to isolate the issue.
"""
import sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

# Same params as Scenario A
asize = 128
energy_keV = 6.2
z_m = 5.0
det_pixel_m = 75e-6
N_photons = 1000
fwhm_nm = 200.0
f_m = 0.3

lambda_m = 1239.842e-9 / (energy_keV * 1e3)
dx_spec = lambda_m * z_m / (asize * det_pixel_m)
pixel_nm = dx_spec * 1e9
print(f"dx = {pixel_nm:.2f} nm")

# ── Generate probe (same as server) ──
dl = DataLoader()
beam_params = {
    'fwhm_h_m': fwhm_nm * 1e-9,
    'fwhm_v_m': fwhm_nm * 1e-9,
    'focal_length_m': f_m,
    'defocus_m': 0.0,
}
probe = dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
print(f"Probe FWHM = {fwhm_px:.1f} px ({fwhm_px * pixel_nm:.1f} nm)")

# ── Generate synthetic data ──
gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=3.0, scan_ly_um=3.0,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"Npos = {ds.Npos}, overlap = {ds.overlap:.2f}")

# ── Build p dict (same as server) ──
data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'object_true': ds.object_true, 'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 200, 'use_gpu': True,
})
print(f"\n── build_p_dict output ──")
print(f"  p['probes'].shape = {p['probes'].shape}, dtype = {p['probes'].dtype}")
print(f"  p['object'][0].shape = {p['object'][0].shape}, dtype = {p['object'][0].dtype}")
print(f"  p['fmag'].shape = {p['fmag'].shape}")
print(f"  p['positions'].shape = {p['positions'].shape}")
print(f"  p['pfft_relaxation'] = {p.get('pfft_relaxation')}")
print(f"  p['number_iterations'] = {p.get('number_iterations')}")

# ── Run DM directly (same as engine_runner._run_dm) ──
from engines.gpu.DM import DM as DM_GPU

probes_4d = p['probes']
probes_in = probes_4d[:, :, 0, 0] if probes_4d.ndim == 4 else probes_4d
ob = [o.squeeze() for o in p['object']]

print(f"\n── DM input ──")
print(f"  probes_in.shape = {probes_in.shape}, dtype = {probes_in.dtype}")
print(f"  ob[0].shape = {ob[0].shape}, dtype = {ob[0].dtype}")
print(f"  sum|probe|^2 = {float((np.abs(probes_in)**2).sum()):.1f}")

print(f"\nRunning DM (200 iter, GPU)...")
t0 = time.time()
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'],
    num_iterations=200)
dt = time.time() - t0
print(f"  DM done: {dt:.1f}s")
print(f"  DM |obj| range: [{np.abs(ob_dm[0]).min():.4f}, {np.abs(ob_dm[0]).max():.4f}]")
if hasattr(err_dm, '__len__') and len(err_dm) > 0:
    print(f"  DM final error: {err_dm[-1] if len(err_dm) else 'N/A'}")

# ── Run ML ──
from engines.ML import ML
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

print(f"\nRunning ML (50 iter)...")
t0 = time.time()
p_ml, fdb_ml = ML(p_ml)
dt = time.time() - t0
ob_ml = p_ml['object'][0].squeeze()
pr_ml = p_ml['probes'][:, :, 0, 0] if p_ml['probes'].ndim == 4 else p_ml['probes']
print(f"  ML done: {dt:.1f}s")
print(f"  ML |obj| range: [{np.abs(ob_ml).min():.4f}, {np.abs(ob_ml).max():.4f}]")

ml_err = fdb_ml.get('err', [])
if len(ml_err):
    print(f"  ML final error: {ml_err[-1]:.6f}")

# ── Compare with truth ──
truth = ds.object_true
# Center crop to match
oh, ow = ob_ml.shape
th, tw = truth.shape
if oh != th or ow != tw:
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_ml[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
else:
    ob_c, tr_c = ob_ml, truth

# Phase-shift alignment
phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
ob_aligned = ob_c * np.exp(-1j * phase_diff)
error = np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))
print(f"\n  Normalized error vs truth: {error:.4f}")

# ── Save image ──
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))

    axes[0,0].imshow(np.abs(probe), cmap='hot')
    axes[0,0].set_title(f'Input Probe |P|\nFWHM={fwhm_px:.1f}px')
    axes[0,1].imshow(np.angle(probe), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,1].set_title('Input Probe Phase')
    axes[0,2].imshow(np.abs(truth), cmap='gray')
    axes[0,2].set_title(f'Ground Truth |O|')
    axes[0,3].imshow(np.angle(truth), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[0,3].set_title('Ground Truth Phase')

    axes[1,0].imshow(np.abs(ob_dm[0].squeeze()), cmap='gray')
    axes[1,0].set_title(f'DM |obj|\nmax={np.abs(ob_dm[0]).max():.3f}')
    axes[1,1].imshow(np.abs(ob_ml), cmap='gray')
    axes[1,1].set_title(f'ML |obj|\nmax={np.abs(ob_ml).max():.3f}')
    axes[1,2].imshow(np.angle(ob_ml), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1,2].set_title(f'ML Phase\nerror={error:.4f}')
    axes[1,3].imshow(np.abs(pr_ml), cmap='hot')
    axes[1,3].set_title(f'Recon Probe |P|')

    for ax in axes.flat:
        ax.axis('off')

    fig.suptitle(f'Direct Engine Call: DM200+ML50, {ds.Npos} pos, '
                 f'E={energy_keV}keV, FWHM={fwhm_nm}nm', fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_direct_recon.png'
    plt.savefig(out, dpi=150)
    print(f"\nImage: {out}")
except ImportError:
    pass
