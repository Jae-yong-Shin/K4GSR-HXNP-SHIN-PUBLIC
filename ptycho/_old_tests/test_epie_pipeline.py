"""
Test ePIE-based pipeline:
1. ePIE 200 iterations (extended)
2. ePIE50 + LSQML50
3. ePIE50 + ML50
"""
import sys
import numpy as np
import time
import copy
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

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}

from engines.gpu.ePIE import ePIE
from engines.gpu.LSQML import LSQML

results = {}

# =====================================================
# TEST 1: ePIE 50 (baseline)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 1: ePIE 50 iterations")
print(f"{'=' * 60}")
p1 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
probes_in = p1['probes'][:, :, 0, 0] if p1['probes'].ndim == 4 else p1['probes']
ob_in = [o.squeeze() for o in p1['object']] if isinstance(p1['object'], list) else [p1['object'].squeeze()]

t0 = time.time()
ob1, pr1, err1 = ePIE(p1, ob=ob_in, probes=probes_in,
                       fmag=p1['fmag'], positions=p1['positions'], num_iterations=50)
dt1 = time.time() - t0
ne1 = norm_error(ob1[0].squeeze(), truth)
g1 = "EXCELLENT" if ne1 < 0.15 else "GOOD" if ne1 < 0.30 else "MARGINAL" if ne1 < 0.50 else "POOR"
results['ePIE50'] = (ne1, g1, dt1, err1)
print(f"  ePIE50: norm_error={ne1:.4f} ({g1}), |obj| max={np.abs(ob1[0]).max():.4f}, time={dt1:.1f}s")

# =====================================================
# TEST 2: ePIE50 + LSQML50
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 2: ePIE50 + LSQML50")
print(f"{'=' * 60}")

# Build p for LSQML with ePIE output
p2 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
p2['object'] = ob1  # ePIE output
if pr1.ndim == 2:
    p2['probes'] = pr1.reshape(pr1.shape[0], pr1.shape[1], 1, 1)
else:
    p2['probes'] = pr1

probes2 = p2['probes'][:, :, 0, 0] if p2['probes'].ndim == 4 else p2['probes']
ob2 = [o.squeeze() for o in p2['object']] if isinstance(p2['object'], list) else [p2['object'].squeeze()]

t0 = time.time()
ob2_out, pr2_out, err2 = LSQML(p2, ob=ob2, probes=probes2,
                                 fmag=p2['fmag'], positions=p2['positions'], num_iterations=50)
dt2 = time.time() - t0
ne2 = norm_error(ob2_out[0].squeeze(), truth)
g2 = "EXCELLENT" if ne2 < 0.15 else "GOOD" if ne2 < 0.30 else "MARGINAL" if ne2 < 0.50 else "POOR"
results['ePIE50+LSQML50'] = (ne2, g2, dt1 + dt2, err2)
print(f"  ePIE50+LSQML50: norm_error={ne2:.4f} ({g2}), |obj| max={np.abs(ob2_out[0]).max():.4f}, "
      f"time={dt1+dt2:.1f}s")

# =====================================================
# TEST 3: ePIE50 + ML50
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 3: ePIE50 + ML50")
print(f"{'=' * 60}")

from engines.ML import ML

p3 = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
p3['opt_iter'] = 50
p3['opt_flags'] = [1, 1]
p3['opt_errmetric'] = 'poisson'
# Use ePIE output
p3['object'] = [o[:, :, np.newaxis] if o.ndim == 2 else o for o in ob1]
if pr1.ndim == 2:
    p3['probes'] = pr1.reshape(pr1.shape[0], pr1.shape[1], 1, 1)
else:
    p3['probes'] = pr1
if isinstance(p3.get('object_size'), list):
    p3['object_size'] = np.array(p3['object_size'])

t0 = time.time()
p3_out, fdb3 = ML(p3)
dt3 = time.time() - t0
ob3 = p3_out['object'][0].squeeze()
ne3 = norm_error(ob3, truth)
g3 = "EXCELLENT" if ne3 < 0.15 else "GOOD" if ne3 < 0.30 else "MARGINAL" if ne3 < 0.50 else "POOR"
ml_err = fdb3.get('error', [])
results['ePIE50+ML50'] = (ne3, g3, dt1 + dt3, ml_err)
print(f"  ePIE50+ML50: norm_error={ne3:.4f} ({g3}), |obj| max={np.abs(ob3).max():.4f}, time={dt1+dt3:.1f}s")

# =====================================================
# TEST 4: ePIE 200 iterations
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 4: ePIE 200 iterations")
print(f"{'=' * 60}")
p4 = dl.build_p_dict(data, {
    'number_iterations': 200, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
probes4 = p4['probes'][:, :, 0, 0] if p4['probes'].ndim == 4 else p4['probes']
ob4 = [o.squeeze() for o in p4['object']] if isinstance(p4['object'], list) else [p4['object'].squeeze()]

t0 = time.time()
ob4_out, pr4_out, err4 = ePIE(p4, ob=ob4, probes=probes4,
                               fmag=p4['fmag'], positions=p4['positions'], num_iterations=200)
dt4 = time.time() - t0
ne4 = norm_error(ob4_out[0].squeeze(), truth)
g4 = "EXCELLENT" if ne4 < 0.15 else "GOOD" if ne4 < 0.30 else "MARGINAL" if ne4 < 0.50 else "POOR"
results['ePIE200'] = (ne4, g4, dt4, err4)
print(f"  ePIE200: norm_error={ne4:.4f} ({g4}), |obj| max={np.abs(ob4_out[0]).max():.4f}, time={dt4:.1f}s")

# =====================================================
# SUMMARY
# =====================================================
print(f"\n{'=' * 70}")
print(f"  PIPELINE COMPARISON")
print(f"{'=' * 70}")
for name, (ne, g, dt, _) in results.items():
    print(f"  {name:25s}: norm_error={ne:.4f} ({g:10s}), time={dt:.1f}s")

# =====================================================
# SAVE
# =====================================================
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 4, figsize=(22, 11))

    amp_max = np.percentile(np.abs(truth), 99.5) * 1.1

    axes[0, 0].imshow(np.abs(truth), cmap='jet', vmin=0, vmax=amp_max)
    axes[0, 0].set_title('Ground Truth')

    axes[0, 1].imshow(np.abs(ob1[0].squeeze()), cmap='jet', vmin=0, vmax=amp_max)
    ne, g = results['ePIE50'][:2]
    axes[0, 1].set_title(f'ePIE50\nerr={ne:.4f} ({g})')

    axes[0, 2].imshow(np.abs(ob2_out[0].squeeze()), cmap='jet', vmin=0, vmax=amp_max)
    ne, g = results['ePIE50+LSQML50'][:2]
    axes[0, 2].set_title(f'ePIE50+LSQML50\nerr={ne:.4f} ({g})')

    axes[0, 3].imshow(np.abs(ob3), cmap='jet', vmin=0, vmax=amp_max)
    ne, g = results['ePIE50+ML50'][:2]
    axes[0, 3].set_title(f'ePIE50+ML50\nerr={ne:.4f} ({g})')

    axes[1, 0].imshow(np.abs(ob4_out[0].squeeze()), cmap='jet', vmin=0, vmax=amp_max)
    ne, g = results['ePIE200'][:2]
    axes[1, 0].set_title(f'ePIE200\nerr={ne:.4f} ({g})')

    # Error curves
    ax = axes[1, 1]
    ax.semilogy(err1[1:], 'g-', lw=2, label='ePIE50')
    ax.semilogy(err4[1:], 'b-', lw=2, label='ePIE200')
    ax.legend()
    ax.set_title('ePIE Fourier Errors')
    ax.grid(True, alpha=0.3)

    ax = axes[1, 2]
    ax.semilogy(err2[1:], 'r-', lw=2, label='LSQML50 (after ePIE)')
    if len(ml_err) > 0:
        ax.semilogy(ml_err, 'm-', lw=2, label='ML50 (after ePIE)')
    ax.legend()
    ax.set_title('Refinement Errors')
    ax.grid(True, alpha=0.3)

    # Summary
    ax = axes[1, 3]
    ax.axis('off')
    summary_text = "PIPELINE COMPARISON\n\n"
    for name, (ne, g, dt, _) in results.items():
        summary_text += f"{name:25s}: {ne:.4f} ({g})\n"
    ax.text(0.1, 0.9, summary_text, transform=ax.transAxes, va='top', ha='left',
            fontsize=11, fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightyellow'))

    for ax in axes.flat:
        ax.tick_params(labelsize=7)

    fig.suptitle('ePIE Pipeline: Standalone + Refinement', fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_epie_pipeline_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    import traceback
    print(f"Plot error: {e}")
    traceback.print_exc()
