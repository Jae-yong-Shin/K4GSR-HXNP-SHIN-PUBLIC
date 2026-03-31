"""
Test the CPU DM engine (MATLAB-faithful port: engines/DM.py)
vs GPU DM (simplified: engines/gpu/DM.py)
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader

# Scenario A
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9, 'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=1000,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)

truth = ds.object_true.squeeze()
print(f"Scenario A: Npos={ds.Npos}, FWHM={fwhm_px:.1f}px")

def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

# Build p dict using DataLoader (it creates MATLAB-style p)
data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,  # CPU!
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

# Need to set verbose level
import utils.verbose as vb
vb.VERBOSE_LEVEL = 1

# ============================================
# CPU DM (MATLAB-faithful: engines/DM.py)
# ============================================
print(f"\n{'='*60}")
print(f"  CPU DM (engines/DM.py - MATLAB port)")
print(f"{'='*60}")

import copy
p_cpu = copy.deepcopy(p)
# CPU DM needs count_bound
p_cpu['count_bound'] = 1.0
p_cpu['name'] = 'DM_cpu'

from engines.DM import DM as DM_CPU
p_cpu_out, fdb_cpu = DM_CPU(p_cpu)

ob_cpu = p_cpu_out['object'][0].squeeze()
ne_cpu = norm_error(ob_cpu, truth)
err_cpu = fdb_cpu['error']

print(f"\nCPU DM error history (selected):")
for i in [0, 1, 4, 9, 19, 29, 39, 49]:
    if i < len(err_cpu):
        print(f"  iter {i+1:3d}: {err_cpu[i]:.6e}")

print(f"\nCPU DM result: norm_error={ne_cpu:.4f}, |obj| max={np.abs(ob_cpu).max():.4f}")
grade_cpu = "EXCELLENT" if ne_cpu < 0.15 else "GOOD" if ne_cpu < 0.30 else "MARGINAL" if ne_cpu < 0.50 else "POOR"
print(f"  Grade: {grade_cpu}")

# ============================================
# GPU DM for comparison
# ============================================
print(f"\n{'='*60}")
print(f"  GPU DM (engines/gpu/DM.py - simplified)")
print(f"{'='*60}")

p_gpu = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': True,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

from engines.gpu.DM import DM as DM_GPU

probes_in = p_gpu['probes'][:, :, 0, 0] if p_gpu['probes'].ndim == 4 else p_gpu['probes']
ob_init = [o.squeeze() for o in p_gpu['object']] if isinstance(p_gpu['object'], list) else [p_gpu['object'].squeeze()]

ob_gpu_out, pr_gpu_out, err_gpu = DM_GPU(
    p_gpu, ob=ob_init, probes=probes_in,
    fmag=p_gpu['fmag'], positions=p_gpu['positions'], num_iterations=50)

ob_gpu = ob_gpu_out[0].squeeze()
ne_gpu = norm_error(ob_gpu, truth)
grade_gpu = "EXCELLENT" if ne_gpu < 0.15 else "GOOD" if ne_gpu < 0.30 else "MARGINAL" if ne_gpu < 0.50 else "POOR"

print(f"\nGPU DM result: norm_error={ne_gpu:.4f}, |obj| max={np.abs(ob_gpu).max():.4f}")
print(f"  Grade: {grade_gpu}")

# ============================================
# SUMMARY
# ============================================
print(f"\n{'='*60}")
print(f"  COMPARISON")
print(f"{'='*60}")
print(f"  CPU DM (MATLAB port): norm_error={ne_cpu:.4f} ({grade_cpu})")
print(f"  GPU DM (simplified):  norm_error={ne_gpu:.4f} ({grade_gpu})")
print(f"  Max |obj_CPU - obj_GPU|: {np.max(np.abs(ob_cpu[:ob_gpu.shape[0], :ob_gpu.shape[1]] - ob_gpu)):.4e}" if ob_cpu.shape == ob_gpu.shape else "  shapes differ")

# Save plot
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))

    axes[0].imshow(np.abs(truth), cmap='jet')
    axes[0].set_title('Ground Truth')

    axes[1].imshow(np.abs(ob_cpu), cmap='jet')
    axes[1].set_title(f'CPU DM50\nerr={ne_cpu:.4f} ({grade_cpu})')

    axes[2].imshow(np.abs(ob_gpu), cmap='jet')
    axes[2].set_title(f'GPU DM50\nerr={ne_gpu:.4f} ({grade_gpu})')

    # Error curves
    axes[3].semilogy(range(1, len(err_cpu)+1), err_cpu, 'b-', lw=2, label='CPU DM')
    axes[3].semilogy(range(1, len(err_gpu)), err_gpu[1:], 'r-', lw=2, label='GPU DM fourier')
    axes[3].legend()
    axes[3].set_title('Error Convergence')
    axes[3].grid(True, alpha=0.3)

    fig.suptitle('CPU DM (MATLAB port) vs GPU DM (simplified)', fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_cpu_dm_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
