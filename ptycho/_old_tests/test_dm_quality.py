"""
DM quality evolution: track norm_error vs iteration to see if
object quality improves even as Fourier error increases.
"""
import sys
import numpy as np
from pathlib import Path
import copy

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader
from engines.gpu.DM import DM as DM_GPU
from engines.gpu.gpu_wrapper import Ggather, USE_GPU, GPU_AVAILABLE

# Scenario A: 6.2keV, 200nm, asize=128
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9, 'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=1000,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"Scenario A: Npos={ds.Npos}, FWHM={fwhm_px:.1f}px, scan_area={scan_area_um:.3f}um")

truth = ds.object_true.squeeze()

def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

# Track quality at multiple DM stopping points
quality_history = []

for n_iter in [1, 2, 5, 10, 20, 50, 100, 200]:
    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'asize': (asize, asize), 'Npos': ds.Npos,
    }
    p = dl.build_p_dict(data, {
        'number_iterations': n_iter, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=n_iter)

    ob_sq = ob_dm[0].squeeze() if isinstance(ob_dm, list) else ob_dm.squeeze()
    ne = norm_error(ob_sq, truth)
    fe = err_dm[n_iter] if n_iter < len(err_dm) else err_dm[-1]
    amp_max = np.abs(ob_sq).max()

    quality_history.append({
        'n_iter': n_iter, 'norm_error': ne, 'fourier_error': fe,
        'amp_max': amp_max
    })
    print(f"  DM {n_iter:4d} iters: norm_err={ne:.4f}, fourier_err={fe:.4e}, |obj| max={amp_max:.4f}")

print(f"\n{'='*60}")
print(f"  DM Quality Evolution")
print(f"{'='*60}")
print(f"  {'Iter':>6s}  {'Norm Error':>12s}  {'Fourier Err':>12s}  {'|obj| max':>10s}  {'Grade':>10s}")
for q in quality_history:
    grade = "EXCELLENT" if q['norm_error'] < 0.15 else "GOOD" if q['norm_error'] < 0.30 else "MARGINAL" if q['norm_error'] < 0.50 else "POOR"
    print(f"  {q['n_iter']:6d}  {q['norm_error']:12.4f}  {q['fourier_error']:12.4e}  {q['amp_max']:10.4f}  {grade:>10s}")

# Now try with DM + ML
print(f"\n{'='*60}")
print(f"  DM+ML Quality (DM N iter + ML 50 iter)")
print(f"{'='*60}")

for dm_iters in [10, 50, 100, 200]:
    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'asize': (asize, asize), 'Npos': ds.Npos,
    }
    p = dl.build_p_dict(data, {
        'number_iterations': dm_iters, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=dm_iters)

    # ML refinement
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
    p_ml, fdb_ml = ML(p_ml)

    ob_final = p_ml['object'][0].squeeze()
    ne = norm_error(ob_final, truth)
    amp_max = np.abs(ob_final).max()
    grade = "EXCELLENT" if ne < 0.15 else "GOOD" if ne < 0.30 else "MARGINAL" if ne < 0.50 else "POOR"
    print(f"  DM{dm_iters}+ML50: norm_err={ne:.4f}, |obj| max={amp_max:.4f}, {grade}")

# Save summary plot
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    iters = [q['n_iter'] for q in quality_history]
    nerrs = [q['norm_error'] for q in quality_history]
    ferrs = [q['fourier_error'] for q in quality_history]

    axes[0].semilogx(iters, nerrs, 'bo-', lw=2)
    axes[0].axhline(0.15, color='g', ls='--', alpha=0.5, label='EXCELLENT')
    axes[0].axhline(0.30, color='b', ls='--', alpha=0.5, label='GOOD')
    axes[0].axhline(0.50, color='orange', ls='--', alpha=0.5, label='MARGINAL')
    axes[0].set_xlabel('DM Iterations')
    axes[0].set_ylabel('Normalized Error')
    axes[0].set_title('Object Quality vs DM Iterations')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].loglog(iters, ferrs, 'rs-', lw=2)
    axes[1].set_xlabel('DM Iterations')
    axes[1].set_ylabel('Fourier Error')
    axes[1].set_title('Fourier Error vs DM Iterations')
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(nerrs, ferrs, 'ko-', lw=2)
    axes[2].set_xlabel('Normalized Error (Object Quality)')
    axes[2].set_ylabel('Fourier Error')
    axes[2].set_title('Fourier vs Normalized Error')
    axes[2].grid(True, alpha=0.3)

    fig.suptitle('DM Quality Evolution: Scenario A (6.2keV, 200nm)', fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_dm_quality_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
