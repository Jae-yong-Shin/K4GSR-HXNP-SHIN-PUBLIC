"""
Test ePIE engine: standalone from ones initialization.
Compare with DM and LSQML.
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


# Generate data
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = int(1e8)

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
     'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9
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
truth = ds.object_true.squeeze()

print(f"Scenario: N={N_photons:.0e}, Npos={ds.Npos}, FWHM={fwhm_px:.1f}px")
print(f"  |truth| range=[{np.abs(truth).min():.4f}, {np.abs(truth).max():.4f}]")

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}

# =====================================================
# TEST: ePIE standalone (50 iterations)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  ePIE standalone (50 iter, ones init)")
print(f"{'=' * 60}")

p = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})

from engines.gpu.ePIE import ePIE

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

t0 = time.time()
ob_out, pr_out, err = ePIE(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'],
    num_iterations=50)
dt = time.time() - t0

ob_sq = ob_out[0].squeeze()
ne = norm_error(ob_sq, truth)
grade = "EXCELLENT" if ne < 0.15 else "GOOD" if ne < 0.30 else "MARGINAL" if ne < 0.50 else "POOR"

print(f"\n  ePIE50: norm_error={ne:.4f} ({grade})")
print(f"  |obj| max={np.abs(ob_sq).max():.4f}, time={dt:.1f}s")

# Track per-iteration quality
print(f"\n  Per-iteration quality:")
for n_iter in [5, 10, 20, 30, 50]:
    p_n = dl.build_p_dict(data, {
        'number_iterations': n_iter, 'use_gpu': False,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1,
    })
    probes_n = p_n['probes'][:, :, 0, 0] if p_n['probes'].ndim == 4 else p_n['probes']
    ob_n = [o.squeeze() for o in p_n['object']] if isinstance(p_n['object'], list) else [p_n['object'].squeeze()]

    ob_n_out, _, _ = ePIE(
        p_n, ob=ob_n, probes=probes_n,
        fmag=p_n['fmag'], positions=p_n['positions'],
        num_iterations=n_iter)

    ob_n_sq = ob_n_out[0].squeeze()
    ne_n = norm_error(ob_n_sq, truth)
    grade_n = "EXCELLENT" if ne_n < 0.15 else "GOOD" if ne_n < 0.30 else "MARGINAL" if ne_n < 0.50 else "POOR"
    print(f"    ePIE {n_iter:3d}: norm_error={ne_n:.4f} ({grade_n}), |obj| max={np.abs(ob_n_sq).max():.4f}")

# Save comparison image
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))

    axes[0].imshow(np.abs(truth), cmap='jet')
    axes[0].set_title('Ground Truth')

    axes[1].imshow(np.abs(ob_sq), cmap='jet')
    axes[1].set_title(f'ePIE50\nerr={ne:.4f} ({grade})')

    axes[2].imshow(np.angle(ob_sq * np.exp(-1j * np.angle(np.sum(ob_sq * np.conj(truth))))),
                   cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[2].set_title('ePIE50 Phase')

    axes[3].semilogy(range(1, len(err)), err[1:], 'g-', lw=2)
    axes[3].set_title('Fourier Error')
    axes[3].grid(True, alpha=0.3)
    axes[3].set_xlabel('Iteration')

    fig.suptitle('ePIE: Standalone from ones initialization', fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_epie_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
