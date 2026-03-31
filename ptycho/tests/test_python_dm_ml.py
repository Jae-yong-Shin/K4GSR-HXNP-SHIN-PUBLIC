"""
test_python_dm_ml.py - Test Python DM + ML pipeline

Runs DM (10 iterations) followed by ML (5 iterations) and reports results
"""

import numpy as np
import h5py
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

# Add python_port to path
sys.path.insert(0, str(Path(__file__).parent))
from engines.DM import DM
from engines.ML import ML
from utils.verbose import verbose


def calculate_correlation(reconstructed, ground_truth):
    rec_flat = reconstructed.flatten()
    gt_flat = ground_truth.flatten()
    rec_c = rec_flat - np.mean(rec_flat)
    gt_c  = gt_flat  - np.mean(gt_flat)
    num = np.abs(np.sum(rec_c * np.conj(gt_c)))
    den = np.sqrt(np.sum(np.abs(rec_c)**2) * np.sum(np.abs(gt_c)**2))
    return float(num / (den + 1e-12))

verbose(2)

print("=" * 80)
print("Python DM + ML Pipeline Test")
print("=" * 80)

# Load MATLAB DM results
matlab_path = Path(__file__).parent.parent / "matlab_ref" / "matlab_dm_only_results.mat"
print(f"\nLoading test data from:")
print(f"  {matlab_path}")

def convert_complex(data):
    """Convert HDF5 structured complex to numpy complex"""
    if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
        return data['real'] + 1j * data['imag']
    return data

with h5py.File(matlab_path, 'r') as f:
    # Ground truth
    object_true = convert_complex(f['object_true'][()]).T
    probe_true = convert_complex(f['probe_true'][()]).T

    # MATLAB DM reconstruction results
    object_matlab = convert_complex(f['object_recon'][()]).T
    probe_matlab = convert_complex(f['probe_recon'][()]).T

    # Extract from p_0 structure
    p_0 = f['p_0']

    # fmag
    if p_0['fmag'].shape == (1, 1):
        fmag = f[p_0['fmag'][0, 0]][()].T
    else:
        fmag = p_0['fmag'][()].T

    # positions
    if p_0['positions'].shape == (1, 1):
        positions = f[p_0['positions'][0, 0]][()].T
    else:
        positions = p_0['positions'][()].T

    # asize
    if p_0['asize'].shape == (1, 1):
        asize = f[p_0['asize'][0, 0]][()].flatten().astype(int)
    else:
        asize = p_0['asize'][()].flatten().astype(int)

    # scanidxs
    if p_0['scanidxs'].shape == (1, 1):
        scanidxs = f[p_0['scanidxs'][0, 0]][()].flatten().astype(int)
    else:
        scanidxs = p_0['scanidxs'][()].flatten().astype(int)

    # object
    if p_0['object'].shape == (1, 1):
        object_initial = convert_complex(f[p_0['object'][0, 0]][()]).T
    else:
        object_initial = convert_complex(p_0['object'][()]).T

    # probes
    if p_0['probes'].shape == (1, 1):
        probes_initial = convert_complex(f[p_0['probes'][0, 0]][()]).T
    else:
        probes_initial = convert_complex(p_0['probes'][()]).T

print("\n" + "=" * 80)
print("1. Run Python DM (10 iterations)")
print("=" * 80)

p = {
    'numscans': 1,
    'asize': asize,
    'probe_modes': 1,
    'object_modes': 1,
    'numprobs': 1,
    'numobjs': 1,
    'positions': positions,
    'scanidxs': [scanidxs],
    'numpts': [len(scanidxs)],
    'share_probe_ID': np.array([0]),
    'share_object_ID': np.array([0]),
    'share_probe': False,
    'share_object': False,
    'fmag': fmag,
    'probes': probes_initial[:, :, np.newaxis, np.newaxis].copy(),
    'object': [object_initial.copy()],
    'number_iterations': 10,
    'probe_change_start': 1,
    'probe_regularization': np.array([0.1]),
    'average_start': 300,
    'average_interval': 5,
    'fmask': np.ones(tuple(asize) + (fmag.shape[2],)),  # 3D: (asize[0], asize[1], num_positions)
    'pfft_relaxation': 0.05,
    'probe_mask_bool': True,
    'probe_mask_area': 0.9,
    'probe_mask_use_auto': False,
    'probe_mask': np.ones(tuple(asize)),
    'count_bound': 0.04,
    'renorm': 1.0,
    'remove_scaling_ambiguity': True,
    'clip_object': True,
    'clip_max': 1.0,
    'clip_min': 0.0,
    'object_flat_region': None,
    'userflatregion': False,
    'compute_rfact': False,
    'use_display': False,
    'name': 'Python_DM_ML_Test',
}

print("\nRunning DM...")
p_dm, fdb_dm = DM(p)

object_dm = p_dm['object'][0].squeeze()
probe_dm = p_dm['probes'][:, :, 0, 0]

dm_obj_corr = calculate_correlation(object_dm, object_true)
dm_probe_corr = calculate_correlation(probe_dm, probe_true)

print(f"\nDM Results:")
print(f"  Object correlation: {dm_obj_corr:.6f}")
print(f"  Probe correlation: {dm_probe_corr:.6f}")
print(f"  Final error: {fdb_dm['error'][-1]:.6f}")

print("\n" + "=" * 80)
print("2. Run Python ML (5 iterations)")
print("=" * 80)

# Add ML parameters to p_dm
p_dm['opt_iter'] = 5
p_dm['opt_ftol'] = 1e-3  # Original tolerance
p_dm['opt_xtol'] = 1e-3  # Original tolerance
p_dm['opt_flags'] = np.array([1, 1])
p_dm['opt_errmetric'] = 'poisson'
p_dm['reg_mu'] = 0
p_dm['smooth_gradient'] = 0
p_dm['scale_gradient'] = False
p_dm['use_probe_support'] = False
p_dm['inv_intensity'] = False
p_dm['Nphot'] = 1e6
p_dm['numpos'] = len(scanidxs)
p_dm['object_size'] = np.array([[object_initial.shape[0], object_initial.shape[1]]])

print("\nRunning ML...")
p_ml, fdb_ml = ML(p_dm)

object_ml = p_ml['object'][0].squeeze()
probe_ml = p_ml['probes'][:, :, 0, 0]

ml_obj_corr = calculate_correlation(object_ml, object_true)
ml_probe_corr = calculate_correlation(probe_ml, probe_true)

print(f"\nML Results:")
print(f"  Object correlation: {ml_obj_corr:.6f}")
print(f"  Probe correlation: {ml_probe_corr:.6f}")

print("\n" + "=" * 80)
print("3. Summary")
print("=" * 80)

print(f"\n{'Stage':<20} {'Object Corr':<15} {'Probe Corr':<15} {'Improvement':<15}")
print("-" * 65)
print(f"{'DM (10 iter)':<20} {dm_obj_corr:.6f}        {dm_probe_corr:.6f}        -")
print(f"{'ML (5 iter)':<20} {ml_obj_corr:.6f}        {ml_probe_corr:.6f}        +{ml_obj_corr - dm_obj_corr:.6f}")

if ml_obj_corr > dm_obj_corr:
    print(f"\n[SUCCESS] ML improved DM results!")
    print(f"  Object: {dm_obj_corr:.6f} -> {ml_obj_corr:.6f} (+{(ml_obj_corr - dm_obj_corr)*100:.2f}%)")
    print(f"  Probe: {dm_probe_corr:.6f} -> {ml_probe_corr:.6f} (+{(ml_probe_corr - dm_probe_corr)*100:.2f}%)")
else:
    print(f"\n[WARNING] ML did not improve results")

print("\n" + "=" * 80)
print("Test Complete")
print("=" * 80)

# ── Reconstruction comparison visualization ──────────────────────────────────
print("\nGenerating reconstruction comparison image...")

def _phase_align(recon, ref):
    """Global phase align recon to ref."""
    ph = np.angle(np.sum(recon * np.conj(ref)))
    return recon * np.exp(-1j * ph)

def _amp_norm(img):
    """Normalize amplitude to [0, 1] for display."""
    a = np.abs(img)
    mn, mx = a.min(), a.max()
    return (a - mn) / (mx - mn + 1e-12)

matlab_corr_obj   = calculate_correlation(object_matlab, object_true)
matlab_corr_probe = calculate_correlation(probe_matlab,  probe_true)

cols = ['True', f'MATLAB DM\ncorr={matlab_corr_obj:.3f}',
        f'Python DM\ncorr={dm_obj_corr:.3f}',
        f'Python DM+ML\ncorr={ml_obj_corr:.3f}']

fig = plt.figure(figsize=(18, 20))
fig.suptitle('Reconstruction Comparison: MATLAB DM vs Python DM vs Python DM+ML',
             fontsize=13, fontweight='bold', y=0.98)

# ── Parameter info box ───────────────────────────────────────────────────────
param_text = (
    f"Dataset parameters\n"
    f"Object size: {object_true.shape[0]}×{object_true.shape[1]} px\n"
    f"Probe size:  {probe_true.shape[0]}×{probe_true.shape[1]} px\n"
    f"Positions:   {positions.shape[0]}\n"
    f"Scan area:   {asize[0]}×{asize[1]} px\n"
    f"\nAlgorithm parameters\n"
    f"DM iterations:  {p['number_iterations']}\n"
    f"ML iterations:  {p_dm['opt_iter']}\n"
    f"Probe modes:    {p['probe_modes']}\n"
    f"Object modes:   {p['object_modes']}\n"
    f"pfft_relax:     {p['pfft_relaxation']}\n"
    f"\nCorrelation (obj / probe)\n"
    f"MATLAB DM:   {matlab_corr_obj:.4f} / {matlab_corr_probe:.4f}\n"
    f"Python DM:   {dm_obj_corr:.4f} / {dm_probe_corr:.4f}\n"
    f"Python DM+ML:{ml_obj_corr:.4f} / {ml_probe_corr:.4f}"
)
ax_info = fig.add_axes([0.0, 0.0, 0.18, 1.0])
ax_info.axis('off')
ax_info.text(0.05, 0.95, param_text, transform=ax_info.transAxes,
             fontsize=8, verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='#f0f0f0', alpha=0.8))

# ── Image grid (4 rows × 4 cols) ────────────────────────────────────────────
# Rows: Object AMP | Object PHASE | Probe AMP | Probe PHASE
objs   = [object_true, object_matlab, object_dm, object_ml]
probes = [probe_true,  probe_matlab,  probe_dm,  probe_ml]
obj_titles = ['True', f'MATLAB DM\ncorr={matlab_corr_obj:.4f}',
              f'Python DM\ncorr={dm_obj_corr:.4f}',
              f'Python DM+ML\ncorr={ml_obj_corr:.4f}']
probe_titles = ['True', f'MATLAB DM\ncorr={matlab_corr_probe:.4f}',
                f'Python DM\ncorr={dm_probe_corr:.4f}',
                f'Python DM+ML\ncorr={ml_probe_corr:.4f}']

axes_obj_amp   = [fig.add_subplot(4, 4, c + 1)      for c in range(4)]
axes_obj_phase = [fig.add_subplot(4, 4, c + 1 + 4)  for c in range(4)]
axes_prb_amp   = [fig.add_subplot(4, 4, c + 1 + 8)  for c in range(4)]
axes_prb_phase = [fig.add_subplot(4, 4, c + 1 + 12) for c in range(4)]

for col in range(4):
    obj_aligned   = _phase_align(objs[col],   object_true)
    probe_aligned = _phase_align(probes[col], probe_true)

    # Object amplitude
    axes_obj_amp[col].imshow(_amp_norm(obj_aligned), cmap='gray', interpolation='nearest')
    axes_obj_amp[col].set_title(obj_titles[col] + '\n(amp)', fontsize=9)
    axes_obj_amp[col].axis('off')

    # Object phase
    axes_obj_phase[col].imshow(np.angle(obj_aligned), cmap='RdBu_r', interpolation='nearest')
    axes_obj_phase[col].set_title(obj_titles[col] + '\n(phase [rad])', fontsize=9)
    axes_obj_phase[col].axis('off')

    # Probe amplitude
    axes_prb_amp[col].imshow(_amp_norm(probe_aligned), cmap='gray', interpolation='nearest')
    axes_prb_amp[col].set_title(probe_titles[col] + '\n(amp)', fontsize=9)
    axes_prb_amp[col].axis('off')

    # Probe phase
    axes_prb_phase[col].imshow(np.angle(probe_aligned), cmap='RdBu_r', interpolation='nearest')
    axes_prb_phase[col].set_title(probe_titles[col] + '\n(phase [rad])', fontsize=9)
    axes_prb_phase[col].axis('off')

axes_obj_amp[0].set_ylabel('Object |amplitude|', fontsize=9)
axes_obj_phase[0].set_ylabel('Object phase [rad]', fontsize=9)
axes_prb_amp[0].set_ylabel('Probe |amplitude|', fontsize=9)
axes_prb_phase[0].set_ylabel('Probe phase [rad]', fontsize=9)

plt.subplots_adjust(left=0.18, right=0.98, top=0.92, bottom=0.02,
                    wspace=0.05, hspace=0.35)
out_path = Path(__file__).parent.parent / 'results' / 'dm_ml_reconstruction_results.png'
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {out_path}")
