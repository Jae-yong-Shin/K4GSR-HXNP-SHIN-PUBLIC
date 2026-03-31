"""
Test engine pipeline: LSQML standalone vs DM+LSQML
Verify that LSQML works from scratch (no DM needed).
Also tests effect of N_photons on reconstruction quality.
"""
import sys
import numpy as np
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader


def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))


def make_scenario(N_photons=int(1e8), asize=128, energy_keV=6.2):
    """Generate synthetic data for a scenario."""
    z_m = 1.0
    det_pixel_m = 75e-6
    lam = 1239.842e-9 / (energy_keV * 1e3)
    pixel_m = lam * z_m / (asize * det_pixel_m)
    pixel_nm = pixel_m * 1e9

    dl = DataLoader()
    probe = dl._build_fresnel_probe(
        {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
         'focal_length_m': 0.3, 'defocus_m': 0.0},
        asize, energy_keV, z_m, det_pixel_m)
    fwhm_px = estimate_probe_fwhm(probe)

    step_px = fwhm_px * 0.25
    scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
    scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=N_photons,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
        probe=probe)
    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    return ds, dl, fwhm_px


def run_lsqml(p, n_iter=50):
    """Run LSQML from p dict."""
    from engines.gpu.LSQML import LSQML

    probes = p['probes']
    if probes.ndim == 4:
        probes_in = probes[:, :, 0, :] if probes.shape[3] > 1 else probes[:, :, 0, 0]
    else:
        probes_in = probes

    ob = p['object']
    if isinstance(ob, list):
        ob = [o.squeeze() if o.ndim > 2 else o for o in ob]
    elif isinstance(ob, np.ndarray):
        ob = [ob.squeeze() if ob.ndim > 2 else ob]

    t0 = time.time()
    ob_out, pr_out, err = LSQML(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'],
        num_iterations=n_iter)
    dt = time.time() - t0
    return ob_out, pr_out, err, dt


def run_dm(p, n_iter=50):
    """Run GPU DM from p dict."""
    from engines.gpu.DM import DM as DM_GPU

    probes = p['probes']
    if probes.ndim == 4:
        probes_in = probes[:, :, 0, 0]
    else:
        probes_in = probes

    ob = p['object']
    if isinstance(ob, list):
        ob = [o.squeeze() for o in ob]
    else:
        ob = [ob.squeeze()]

    t0 = time.time()
    ob_out, pr_out, err = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'],
        num_iterations=n_iter)
    dt = time.time() - t0
    return ob_out, pr_out, err, dt


# =====================================================
print("=" * 70)
print("  ENGINE PIPELINE TEST")
print("=" * 70)

# Generate data with high N_photons
N_PHOTONS = int(1e8)
ds, dl, fwhm_px = make_scenario(N_photons=N_PHOTONS)
truth = ds.object_true.squeeze()
print(f"\nScenario: N_photons={N_PHOTONS:.0e}, Npos={ds.Npos}, FWHM={fwhm_px:.1f}px")
print(f"  |truth| range=[{np.abs(truth).min():.4f}, {np.abs(truth).max():.4f}]")
print(f"  fmag range=[{ds.fmag.min():.1f}, {ds.fmag.max():.1f}]")

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (128, 128), 'Npos': ds.Npos,
}

# =====================================================
# TEST 1: LSQML standalone (50 iter, from ones init)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 1: LSQML standalone (50 iter, ones init)")
print(f"{'=' * 60}")

import copy
p1 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
ob1, pr1, err1, dt1 = run_lsqml(p1, 50)
ob1_sq = ob1[0].squeeze()
ne1 = norm_error(ob1_sq, truth)
grade1 = "EXCELLENT" if ne1 < 0.15 else "GOOD" if ne1 < 0.30 else "MARGINAL" if ne1 < 0.50 else "POOR"
print(f"\n  LSQML50: norm_error={ne1:.4f} ({grade1}), |obj| max={np.abs(ob1_sq).max():.4f}, time={dt1:.1f}s")

# =====================================================
# TEST 2: DM50 standalone (current fixed version)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 2: DM standalone (50 iter)")
print(f"{'=' * 60}")

p2 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})
ob2, pr2, err2, dt2 = run_dm(p2, 50)
ob2_sq = ob2[0].squeeze()
ne2 = norm_error(ob2_sq, truth)
grade2 = "EXCELLENT" if ne2 < 0.15 else "GOOD" if ne2 < 0.30 else "MARGINAL" if ne2 < 0.50 else "POOR"
print(f"\n  DM50: norm_error={ne2:.4f} ({grade2}), |obj| max={np.abs(ob2_sq).max():.4f}, time={dt2:.1f}s")

# =====================================================
# TEST 3: DM50 + LSQML50
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 3: DM50 + LSQML50 pipeline")
print(f"{'=' * 60}")

p3 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})
ob3_dm, pr3_dm, err3_dm, dt3_dm = run_dm(p3, 50)
ne3_dm = norm_error(ob3_dm[0].squeeze(), truth)
print(f"  DM50: norm_error={ne3_dm:.4f}, |obj| max={np.abs(ob3_dm[0]).max():.4f}, time={dt3_dm:.1f}s")

# Feed DM output to LSQML
p3b = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
# Replace object and probe with DM output
p3b['object'] = ob3_dm
if pr3_dm.ndim == 2:
    p3b['probes'] = pr3_dm.reshape(pr3_dm.shape[0], pr3_dm.shape[1], 1, 1)
else:
    p3b['probes'] = pr3_dm

ob3, pr3, err3, dt3 = run_lsqml(p3b, 50)
ob3_sq = ob3[0].squeeze()
ne3 = norm_error(ob3_sq, truth)
grade3 = "EXCELLENT" if ne3 < 0.15 else "GOOD" if ne3 < 0.30 else "MARGINAL" if ne3 < 0.50 else "POOR"
print(f"\n  DM50+LSQML50: norm_error={ne3:.4f} ({grade3}), |obj| max={np.abs(ob3_sq).max():.4f}, time={dt3_dm+dt3:.1f}s")

# =====================================================
# TEST 4: LSQML with low N_photons (N=1000)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 4: LSQML standalone (50 iter, N_photons=1000)")
print(f"{'=' * 60}")

ds_low, dl_low, fwhm_low = make_scenario(N_photons=1000)
truth_low = ds_low.object_true.squeeze()
data_low = {
    'fmag': ds_low.fmag, 'positions': ds_low.positions_clean,
    'probes': ds_low.probe, 'object_init': ds_low.object_init,
    'asize': (128, 128), 'Npos': ds_low.Npos,
}
p4 = dl_low.build_p_dict(data_low, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
print(f"  N_photons=1000, fmag range=[{ds_low.fmag.min():.4f}, {ds_low.fmag.max():.4f}]")
ob4, pr4, err4, dt4 = run_lsqml(p4, 50)
ob4_sq = ob4[0].squeeze()
ne4 = norm_error(ob4_sq, truth_low)
grade4 = "EXCELLENT" if ne4 < 0.15 else "GOOD" if ne4 < 0.30 else "MARGINAL" if ne4 < 0.50 else "POOR"
print(f"\n  LSQML50 (N=1000): norm_error={ne4:.4f} ({grade4}), |obj| max={np.abs(ob4_sq).max():.4f}, time={dt4:.1f}s")

# =====================================================
# SUMMARY
# =====================================================
print(f"\n{'=' * 70}")
print(f"  SUMMARY")
print(f"{'=' * 70}")
print(f"  N_photons=1e8:")
print(f"    LSQML50 standalone:  norm_error={ne1:.4f} ({grade1})")
print(f"    DM50 standalone:     norm_error={ne2:.4f} ({grade2})")
print(f"    DM50+LSQML50:       norm_error={ne3:.4f} ({grade3})")
print(f"  N_photons=1000:")
print(f"    LSQML50 standalone:  norm_error={ne4:.4f} ({grade4})")
print(f"  Ground Truth: |obj| max={np.abs(truth).max():.4f}")

# =====================================================
# SAVE
# =====================================================
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 4, figsize=(20, 10))

    # Row 1: N_photons=1e8
    axes[0, 0].imshow(np.abs(truth), cmap='jet')
    axes[0, 0].set_title(f'Ground Truth\n|obj| max={np.abs(truth).max():.3f}')

    axes[0, 1].imshow(np.abs(ob1_sq), cmap='jet')
    axes[0, 1].set_title(f'LSQML50 standalone\nerr={ne1:.4f} ({grade1})')

    axes[0, 2].imshow(np.abs(ob2_sq), cmap='jet')
    axes[0, 2].set_title(f'DM50 standalone\nerr={ne2:.4f} ({grade2})')

    axes[0, 3].imshow(np.abs(ob3_sq), cmap='jet')
    axes[0, 3].set_title(f'DM50+LSQML50\nerr={ne3:.4f} ({grade3})')

    # Row 2: errors + low N
    axes[1, 0].imshow(np.abs(ob4_sq), cmap='jet')
    axes[1, 0].set_title(f'LSQML50 (N=1000)\nerr={ne4:.4f} ({grade4})')

    # Error curves
    ax = axes[1, 1]
    ax.semilogy(err1[1:], 'g-', lw=2, label='LSQML50')
    ax.semilogy(err2[1:], 'b-', lw=2, label='DM50')
    ax.legend()
    ax.set_title('N=1e8: Fourier Errors')
    ax.grid(True, alpha=0.3)

    ax = axes[1, 2]
    ax.semilogy(err3[1:], 'r-', lw=2, label='DM50+LSQML50')
    ax.semilogy(err4[1:], 'm--', lw=2, label='LSQML50 (N=1000)')
    ax.legend()
    ax.set_title('Fourier Errors (pipeline)')
    ax.grid(True, alpha=0.3)

    # Summary text
    ax = axes[1, 3]
    ax.axis('off')
    summary = (
        f"SUMMARY (asize=128, 6.2keV, 200nm)\n\n"
        f"N_photons=1e8:\n"
        f"  LSQML50:      {ne1:.4f} ({grade1})\n"
        f"  DM50:         {ne2:.4f} ({grade2})\n"
        f"  DM50+LSQML50: {ne3:.4f} ({grade3})\n\n"
        f"N_photons=1000:\n"
        f"  LSQML50:      {ne4:.4f} ({grade4})\n"
    )
    ax.text(0.1, 0.9, summary, transform=ax.transAxes, va='top', ha='left',
            fontsize=11, fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightyellow'))

    for ax in axes.flat:
        ax.tick_params(labelsize=7)

    fig.suptitle('Engine Pipeline Test', fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_engine_pipeline_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
