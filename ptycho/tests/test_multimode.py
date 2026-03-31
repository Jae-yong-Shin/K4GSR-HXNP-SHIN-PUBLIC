"""
test_multimode.py - Test Python DM+ML with 3 probe modes
"""
import numpy as np
import h5py
import matplotlib.pyplot as plt
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path.cwd()))
from engines.DM import DM
from engines.ML import ML
from utils.verbose import verbose

print("="*80)
print("Python Multi-mode Ptychography Test (3 probe modes)")
print("="*80)

# Load MATLAB results
print("\nLoading MATLAB multi-mode results...")
with h5py.File(str(Path(__file__).parent.parent / 'matlab_ref' / 'matlab_multimode_results.mat'), 'r') as f:
    # Ground truth
    def convert_complex(data):
        if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
            return data['real'] + 1j * data['imag']
        return data

    object_true = convert_complex(f['object_true'][()]).T
    probe_true = convert_complex(f['probe_true'][()]).T

    # MATLAB results
    object_matlab_dm = convert_complex(f['object_dm'][()]).T
    probe_matlab_dm_mode1 = convert_complex(f['probe_dm_mode1'][()]).T
    probe_matlab_dm_mode2 = convert_complex(f['probe_dm_mode2'][()]).T
    probe_matlab_dm_mode3 = convert_complex(f['probe_dm_mode3'][()]).T
    probe_matlab_dm_incoh = convert_complex(f['probe_dm_incoherent'][()]).T

    object_matlab_ml = convert_complex(f['object_ml'][()]).T
    probe_matlab_ml_mode1 = convert_complex(f['probe_ml_mode1'][()]).T
    probe_matlab_ml_mode2 = convert_complex(f['probe_ml_mode2'][()]).T
    probe_matlab_ml_mode3 = convert_complex(f['probe_ml_mode3'][()]).T
    probe_matlab_ml_incoh = convert_complex(f['probe_ml_incoherent'][()]).T

    print(f"MATLAB results loaded:")
    print(f"  Object shape: {object_matlab_ml.shape}")
    print(f"  Probe shape: {probe_matlab_ml_mode1.shape}")

    # Load initial conditions for Python
    p_0 = f['p_0']

    # Load fmag
    if p_0['fmag'].shape == (1, 1):
        fmag = f[p_0['fmag'][0, 0]][()].T
    else:
        fmag = p_0['fmag'][()].T

    # Load positions
    if p_0['positions'].shape == (1, 1):
        positions = f[p_0['positions'][0, 0]][()].T
    else:
        positions = p_0['positions'][()].T

    # Load asize
    if p_0['asize'].shape == (1, 1):
        asize = f[p_0['asize'][0, 0]][()].flatten().astype(int)
    else:
        asize = p_0['asize'][()].flatten().astype(int)

    # Load scanidxs
    if p_0['scanidxs'].shape == (1, 1):
        scanidxs = f[p_0['scanidxs'][0, 0]][()].flatten().astype(int)
    else:
        scanidxs = p_0['scanidxs'][()].flatten().astype(int)

    # Load initial object
    if p_0['object'].shape == (1, 1):
        object_ref = f[p_0['object'][0, 0]]
        if object_ref.shape == (1, 1):
            object_initial = convert_complex(f[object_ref[0, 0]][()]).T
        else:
            object_initial = convert_complex(object_ref[()]).T
    else:
        object_initial = convert_complex(p_0['object'][()]).T

    # Load initial probes (3 modes)
    if p_0['probes'].shape == (1, 1):
        probes_ref = f[p_0['probes'][0, 0]]
        if probes_ref.shape == (1, 1):
            probes_initial = convert_complex(f[probes_ref[0, 0]][()]).T
        else:
            probes_initial = convert_complex(probes_ref[()]).T
    else:
        probes_initial = convert_complex(p_0['probes'][()]).T

print(f"\nInitial conditions:")
print(f"  fmag shape: {fmag.shape}")
print(f"  positions shape: {positions.shape}")
print(f"  asize: {asize}")
print(f"  scanidxs shape: {scanidxs.shape}")
print(f"  object_initial shape: {object_initial.shape}")
print(f"  probes_initial shape: {probes_initial.shape}")

# Calculate initial probe mode powers
mode1_init_power = np.sum(np.abs(probes_initial[:, :, 0, 0])**2)
mode2_init_power = np.sum(np.abs(probes_initial[:, :, 0, 1])**2)
mode3_init_power = np.sum(np.abs(probes_initial[:, :, 0, 2])**2)
total_init_power = mode1_init_power + mode2_init_power + mode3_init_power

print(f"\nInitial probe mode powers:")
print(f"  Mode 1: {100 * mode1_init_power / total_init_power:.2f}%")
print(f"  Mode 2: {100 * mode2_init_power / total_init_power:.2f}%")
print(f"  Mode 3: {100 * mode3_init_power / total_init_power:.2f}%")

# Run Python DM with 3 probe modes
print("\n" + "="*80)
print("Running Python DM (10 iterations, 3 probe modes)")
print("="*80 + "\n")

verbose(0)  # Suppress output

p = {
    'numscans': 1,
    'asize': asize,
    'probe_modes': 3,  # KEY: 3 probe modes
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
    'probes': probes_initial.copy(),  # 3 modes: (H, W, 1, 3)
    'object': [object_initial.copy()],
    'number_iterations': 10,
    'probe_change_start': 1,
    'probe_regularization': np.array([0.1]),
    'average_start': 300,
    'average_interval': 5,
    'fmask': np.ones(tuple(asize) + (fmag.shape[2],)),
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
    'name': 'Python_DM_Multimode',
    'use_gpu': True,
}

p_dm, fdb_dm = DM(p)

# Extract DM results
object_python_dm = p_dm['object'][0].squeeze()
probe_python_dm_mode1 = p_dm['probes'][:, :, 0, 0]
probe_python_dm_mode2 = p_dm['probes'][:, :, 0, 1]
probe_python_dm_mode3 = p_dm['probes'][:, :, 0, 2]

# Calculate incoherent sum
probe_python_dm_incoh = np.sqrt(
    np.abs(probe_python_dm_mode1)**2 +
    np.abs(probe_python_dm_mode2)**2 +
    np.abs(probe_python_dm_mode3)**2
)

# Calculate correlations
def calc_corr(a, b):
    # Crop both to minimum common size if shapes differ
    if a.shape != b.shape:
        min_r = min(a.shape[0], b.shape[0])
        min_c = min(a.shape[1], b.shape[1])
        a = a[:min_r, :min_c]
        b = b[:min_r, :min_c]
    a_flat = a.flatten()
    b_flat = b.flatten()
    a_centered = a_flat - np.mean(a_flat)
    b_centered = b_flat - np.mean(b_flat)
    numerator = np.abs(np.sum(a_centered * np.conj(b_centered)))
    denominator = np.sqrt(np.sum(np.abs(a_centered)**2) * np.sum(np.abs(b_centered)**2))
    return numerator / denominator

dm_obj_corr = calc_corr(object_python_dm, object_true)
dm_probe_corr = calc_corr(probe_python_dm_incoh, np.abs(probe_true))

# Calculate mode powers
dm_mode1_power = np.sum(np.abs(probe_python_dm_mode1)**2)
dm_mode2_power = np.sum(np.abs(probe_python_dm_mode2)**2)
dm_mode3_power = np.sum(np.abs(probe_python_dm_mode3)**2)
dm_total_power = dm_mode1_power + dm_mode2_power + dm_mode3_power

print(f"\nPython DM Results (3 modes):")
print(f"  Object correlation: {dm_obj_corr:.6f}")
print(f"  Probe correlation (incoherent): {dm_probe_corr:.6f}")
print(f"  Mode 1 power: {100 * dm_mode1_power / dm_total_power:.2f}%")
print(f"  Mode 2 power: {100 * dm_mode2_power / dm_total_power:.2f}%")
print(f"  Mode 3 power: {100 * dm_mode3_power / dm_total_power:.2f}%")

# Run Python ML (DM → ML pattern, standard c_solver recipe)
print("\n" + "="*80)
print("Running Python ML (5 iterations, 3 probe modes)  [DM→ML recipe]")
print("="*80 + "\n")

p_dm['opt_iter'] = 5
p_dm['opt_ftol'] = 1e-3
p_dm['opt_xtol'] = 1e-3
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
p_dm['use_gpu'] = True

p_ml, fdb_ml = ML(p_dm)

# Extract ML results
object_python_ml = p_ml['object'][0].squeeze()
probe_python_ml_mode1 = p_ml['probes'][:, :, 0, 0]
probe_python_ml_mode2 = p_ml['probes'][:, :, 0, 1]
probe_python_ml_mode3 = p_ml['probes'][:, :, 0, 2]

probe_python_ml_incoh = np.sqrt(
    np.abs(probe_python_ml_mode1)**2 +
    np.abs(probe_python_ml_mode2)**2 +
    np.abs(probe_python_ml_mode3)**2
)

ml_obj_corr = calc_corr(object_python_ml, object_true)
ml_probe_corr = calc_corr(probe_python_ml_incoh, np.abs(probe_true))

ml_mode1_power = np.sum(np.abs(probe_python_ml_mode1)**2)
ml_mode2_power = np.sum(np.abs(probe_python_ml_mode2)**2)
ml_mode3_power = np.sum(np.abs(probe_python_ml_mode3)**2)
ml_total_power = ml_mode1_power + ml_mode2_power + ml_mode3_power

print(f"\nPython ML Results (3 modes):")
print(f"  Object correlation: {ml_obj_corr:.6f}")
print(f"  Probe correlation (incoherent): {ml_probe_corr:.6f}")
print(f"  Mode 1 power: {100 * ml_mode1_power / ml_total_power:.2f}%")
print(f"  Mode 2 power: {100 * ml_mode2_power / ml_total_power:.2f}%")
print(f"  Mode 3 power: {100 * ml_mode3_power / ml_total_power:.2f}%")

# Run Python LSQML (DM → LSQML pattern, GPU MLc recipe)
# Uses DM output as initial guess; LSQML is a standalone refinement engine
# Parameters follow template_ptycho.m GPU engine defaults:
#   delta_p=0.1 ("usually safe"), beta_object/probe=1 ("should not exceed 1"),
#   pfft_relaxation=0.05, beta_LSQ=0.9
# apply_multimodal_update=True because all 3 modes are physical probe modes,
#   not background modes (template note: set False only when higher modes account
#   for measurement artefacts/background)
print("\n" + "="*80)
print("Running Python LSQML (10 iterations, 3 probe modes)  [DM→LSQML recipe]")
print("="*80 + "\n")

from engines.gpu.LSQML import LSQML

# Extract DM output as LSQML initial conditions
ob_lsqml_in   = [p_dm['object'][0].squeeze().copy()]  # squeeze (Ny,Nx,1) → (Ny,Nx)
# p_dm['probes'] shape: (Ny, Nx, Nscans=1, Nmodes=3) → LSQML expects (Ny, Nx, Nmodes)
probes_lsqml_in = p_dm['probes'][:, :, 0, :].copy()

p_lsqml = {
    'probe_modes':          3,
    'object_modes':         1,
    'probe_change_start':   1,
    'object_change_start':  1,
    'beta_LSQ':             0.9,    # LSQ step scaling
    'beta_probe':           1.0,    # should not exceed 1
    'beta_object':          1.0,    # should not exceed 1
    'pfft_relaxation':      0.05,   # Fourier domain relaxation (DM default)
    'delta_p':              0.1,    # LSQ dumping constant; 0.1 is usually safe
    'probe_position_search': 0,     # disabled (inf = enabled in template, we keep off for basic test)
    'use_gpu':              False,
}

ob_lsqml_out, probes_lsqml_out, fourier_error_lsqml = LSQML(
    p_lsqml,
    ob_lsqml_in,
    probes_lsqml_in,
    fmag,
    positions,
    num_iterations=10,
)

# Extract LSQML results
object_python_lsqml   = ob_lsqml_out[0].squeeze()
probe_python_lsqml_mode1 = probes_lsqml_out[:, :, 0]
probe_python_lsqml_mode2 = probes_lsqml_out[:, :, 1]
probe_python_lsqml_mode3 = probes_lsqml_out[:, :, 2]

probe_python_lsqml_incoh = np.sqrt(
    np.abs(probe_python_lsqml_mode1)**2 +
    np.abs(probe_python_lsqml_mode2)**2 +
    np.abs(probe_python_lsqml_mode3)**2
)

lsqml_obj_corr   = calc_corr(object_python_lsqml, object_true)
lsqml_probe_corr = calc_corr(probe_python_lsqml_incoh, np.abs(probe_true))

lsqml_mode1_power = np.sum(np.abs(probe_python_lsqml_mode1)**2)
lsqml_mode2_power = np.sum(np.abs(probe_python_lsqml_mode2)**2)
lsqml_mode3_power = np.sum(np.abs(probe_python_lsqml_mode3)**2)
lsqml_total_power = lsqml_mode1_power + lsqml_mode2_power + lsqml_mode3_power

print(f"\nPython LSQML Results (3 modes):")
print(f"  Object correlation: {lsqml_obj_corr:.6f}")
print(f"  Probe correlation (incoherent): {lsqml_probe_corr:.6f}")
print(f"  Mode 1 power: {100 * lsqml_mode1_power / lsqml_total_power:.2f}%")
print(f"  Mode 2 power: {100 * lsqml_mode2_power / lsqml_total_power:.2f}%")
print(f"  Mode 3 power: {100 * lsqml_mode3_power / lsqml_total_power:.2f}%")

# Create comparison visualization
print("\n" + "="*80)
print("Creating comparison visualization")
print("="*80)

# ── 10 rows × 6 cols ─────────────────────────────────────────────────────────
# Cols: True | MATLAB DM | Python DM | MATLAB ML | Python ML | Python LSQML
# Rows (paired amp/phase):
#   1: Object AMP      2: Object PHASE
#   3: Mode 1 AMP      4: Mode 1 PHASE
#   5: Mode 2 AMP      6: Mode 2 PHASE
#   7: Mode 3 AMP      8: Mode 3 PHASE
#   9: Incoherent AMP 10: (param info / blank)
# MATLAB has no LSQML results; Python LSQML col shows DM→LSQML recipe result.
NROWS, NCOLS = 10, 6
fig = plt.figure(figsize=(26, 36))

def _add_img(row, col, data, title, cmap='gray', is_phase=False):
    ax = plt.subplot(NROWS, NCOLS, (row - 1) * NCOLS + col)
    if is_phase:
        display_data = np.angle(data)
        cmap = 'RdBu_r'
        suffix = '(phase [rad])'
    else:
        display_data = np.abs(data)
        suffix = '(amp)'
    im = ax.imshow(display_data, cmap=cmap)
    ax.set_title(title + '\n' + suffix, fontsize=8)
    ax.axis('off')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    return ax

def _add_label(row, col, text):
    ax = plt.subplot(NROWS, NCOLS, (row - 1) * NCOLS + col)
    ax.axis('off')
    ax.text(0.5, 0.5, text, ha='center', va='center',
            fontsize=13, fontweight='bold', transform=ax.transAxes)
    return ax

# Row 1: Object AMP
_add_img(1, 1, object_true,         'Ground Truth\nObject')
_add_img(1, 2, object_matlab_dm,    'MATLAB DM\nObject')
_add_img(1, 3, object_python_dm,    'Python DM\nObject')
_add_img(1, 4, object_matlab_ml,    'MATLAB ML\nObject')
_add_img(1, 5, object_python_ml,    'Python ML\nObject')
_add_img(1, 6, object_python_lsqml, 'Python LSQML\nObject')

# Row 2: Object PHASE
_add_img(2, 1, object_true,         'Ground Truth\nObject',        is_phase=True)
_add_img(2, 2, object_matlab_dm,    'MATLAB DM\nObject',           is_phase=True)
_add_img(2, 3, object_python_dm,    'Python DM\nObject',           is_phase=True)
_add_img(2, 4, object_matlab_ml,    'MATLAB ML\nObject',           is_phase=True)
_add_img(2, 5, object_python_ml,    'Python ML\nObject',           is_phase=True)
_add_img(2, 6, object_python_lsqml, 'Python LSQML\nObject',        is_phase=True)

# Row 3: Probe Mode 1 AMP
_add_img(3, 1, probe_true,               'Ground Truth\nProbe')
_add_img(3, 2, probe_matlab_dm_mode1,    'MATLAB DM\nMode 1')
_add_img(3, 3, probe_python_dm_mode1,    'Python DM\nMode 1')
_add_img(3, 4, probe_matlab_ml_mode1,    'MATLAB ML\nMode 1')
_add_img(3, 5, probe_python_ml_mode1,    'Python ML\nMode 1')
_add_img(3, 6, probe_python_lsqml_mode1, 'Python LSQML\nMode 1')

# Row 4: Probe Mode 1 PHASE
_add_img(4, 1, probe_true,               'Ground Truth\nProbe',         is_phase=True)
_add_img(4, 2, probe_matlab_dm_mode1,    'MATLAB DM\nMode 1',           is_phase=True)
_add_img(4, 3, probe_python_dm_mode1,    'Python DM\nMode 1',           is_phase=True)
_add_img(4, 4, probe_matlab_ml_mode1,    'MATLAB ML\nMode 1',           is_phase=True)
_add_img(4, 5, probe_python_ml_mode1,    'Python ML\nMode 1',           is_phase=True)
_add_img(4, 6, probe_python_lsqml_mode1, 'Python LSQML\nMode 1',        is_phase=True)

# Row 5: Probe Mode 2 AMP
_add_label(5, 1, 'Mode 2')
_add_img(5, 2, probe_matlab_dm_mode2,    'MATLAB DM\nMode 2')
_add_img(5, 3, probe_python_dm_mode2,    'Python DM\nMode 2')
_add_img(5, 4, probe_matlab_ml_mode2,    'MATLAB ML\nMode 2')
_add_img(5, 5, probe_python_ml_mode2,    'Python ML\nMode 2')
_add_img(5, 6, probe_python_lsqml_mode2, 'Python LSQML\nMode 2')

# Row 6: Probe Mode 2 PHASE
_add_label(6, 1, 'Mode 2\nPhase')
_add_img(6, 2, probe_matlab_dm_mode2,    'MATLAB DM\nMode 2',           is_phase=True)
_add_img(6, 3, probe_python_dm_mode2,    'Python DM\nMode 2',           is_phase=True)
_add_img(6, 4, probe_matlab_ml_mode2,    'MATLAB ML\nMode 2',           is_phase=True)
_add_img(6, 5, probe_python_ml_mode2,    'Python ML\nMode 2',           is_phase=True)
_add_img(6, 6, probe_python_lsqml_mode2, 'Python LSQML\nMode 2',        is_phase=True)

# Row 7: Probe Mode 3 AMP
_add_label(7, 1, 'Mode 3')
_add_img(7, 2, probe_matlab_dm_mode3,    'MATLAB DM\nMode 3')
_add_img(7, 3, probe_python_dm_mode3,    'Python DM\nMode 3')
_add_img(7, 4, probe_matlab_ml_mode3,    'MATLAB ML\nMode 3')
_add_img(7, 5, probe_python_ml_mode3,    'Python ML\nMode 3')
_add_img(7, 6, probe_python_lsqml_mode3, 'Python LSQML\nMode 3')

# Row 8: Probe Mode 3 PHASE
_add_label(8, 1, 'Mode 3\nPhase')
_add_img(8, 2, probe_matlab_dm_mode3,    'MATLAB DM\nMode 3',           is_phase=True)
_add_img(8, 3, probe_python_dm_mode3,    'Python DM\nMode 3',           is_phase=True)
_add_img(8, 4, probe_matlab_ml_mode3,    'MATLAB ML\nMode 3',           is_phase=True)
_add_img(8, 5, probe_python_ml_mode3,    'Python ML\nMode 3',           is_phase=True)
_add_img(8, 6, probe_python_lsqml_mode3, 'Python LSQML\nMode 3',        is_phase=True)

# Row 9: Incoherent sum AMP (real-valued — no phase row)
_add_label(9, 1, 'Incoherent\nSum')
_add_img(9, 2, probe_matlab_dm_incoh,    'MATLAB DM\nIncoherent')
_add_img(9, 3, probe_python_dm_incoh,    'Python DM\nIncoherent')
_add_img(9, 4, probe_matlab_ml_incoh,    'MATLAB ML\nIncoherent')
_add_img(9, 5, probe_python_ml_incoh,    'Python ML\nIncoherent')
_add_img(9, 6, probe_python_lsqml_incoh, 'Python LSQML\nIncoherent')

# Row 10: blank (param info is shown via fig.add_axes below)

plt.suptitle('Multi-mode Reconstruction Comparison (3 Probe Modes)\n'
             'Recipes: DM→ML (c_solver standard) | DM→LSQML (GPU MLc)',
             fontsize=14, fontweight='bold')

# ── Parameter info panel (top-right corner) ──────────────────────────────────
dm_mode_powers = [
    100 * dm_mode1_power / dm_total_power,
    100 * dm_mode2_power / dm_total_power,
    100 * dm_mode3_power / dm_total_power,
]
dm_mat_corr = calc_corr(object_matlab_dm, object_true)
ml_mat_corr = calc_corr(object_matlab_ml, object_true)
probe_dm_mat = calc_corr(probe_matlab_dm_incoh, np.abs(probe_true))
probe_ml_mat = calc_corr(probe_matlab_ml_incoh, np.abs(probe_true))

lsqml_mode_powers = [
    100 * lsqml_mode1_power / lsqml_total_power,
    100 * lsqml_mode2_power / lsqml_total_power,
    100 * lsqml_mode3_power / lsqml_total_power,
]

param_text = (
    "Dataset parameters\n"
    f"  Object size:  {object_true.shape[0]}×{object_true.shape[1]} px\n"
    f"  Probe size:   {probe_true.shape[0]}×{probe_true.shape[1]} px\n"
    f"  Positions:    {positions.shape[0]}\n"
    f"  Scan area:    {asize[0]}×{asize[1]} px\n\n"
    "Algorithm parameters\n"
    f"  DM iters:       10  (pfft_relax=0.05)\n"
    f"  ML iters:        5  (DM→ML recipe)\n"
    f"  LSQML iters:    10  (DM→LSQML recipe)\n"
    f"    delta_p=0.1, beta_ob/pr=1.0\n"
    f"    beta_LSQ=0.9\n"
    f"  Probe modes:     3  (physical modes)\n"
    f"  Object modes:    1\n\n"
    "Object correlation (vs true)\n"
    f"  MATLAB DM:      {dm_mat_corr:.4f}\n"
    f"  Python DM:      {dm_obj_corr:.4f}\n"
    f"  MATLAB ML:      {ml_mat_corr:.4f}\n"
    f"  Python ML:      {ml_obj_corr:.4f}\n"
    f"  Python LSQML:   {lsqml_obj_corr:.4f}\n\n"
    "Probe corr (incoherent)\n"
    f"  MATLAB DM:      {probe_dm_mat:.4f}\n"
    f"  Python DM:      {dm_probe_corr:.4f}\n"
    f"  MATLAB ML:      {probe_ml_mat:.4f}\n"
    f"  Python ML:      {ml_probe_corr:.4f}\n"
    f"  Python LSQML:   {lsqml_probe_corr:.4f}\n\n"
    "Mode power (Python DM)\n"
    f"  Mode 1: {dm_mode_powers[0]:.1f}%\n"
    f"  Mode 2: {dm_mode_powers[1]:.1f}%\n"
    f"  Mode 3: {dm_mode_powers[2]:.1f}%\n\n"
    "Mode power (Python LSQML)\n"
    f"  Mode 1: {lsqml_mode_powers[0]:.1f}%\n"
    f"  Mode 2: {lsqml_mode_powers[1]:.1f}%\n"
    f"  Mode 3: {lsqml_mode_powers[2]:.1f}%"
)

ax_info = fig.add_axes([0.83, 0.02, 0.16, 0.3])
ax_info.axis('off')
ax_info.text(0.02, 0.98, param_text, transform=ax_info.transAxes,
             fontsize=7.5, verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='#e8f4e8', alpha=0.9))

plt.tight_layout(rect=[0, 0, 0.83, 0.97])

output_path = str(Path(__file__).parent.parent / 'results' / 'multimode_comparison.png')
plt.savefig(output_path, dpi=150, bbox_inches='tight')
print(f"\nComparison image saved to: {output_path}")

# Print summary
print("\n" + "="*80)
print("COMPARISON SUMMARY")
print("="*80)
print("\nObject Correlation (vs ground truth):")
print(f"  MATLAB DM:     {calc_corr(object_matlab_dm,  object_true):.6f}")
print(f"  Python DM:     {dm_obj_corr:.6f}")
print(f"  MATLAB ML:     {calc_corr(object_matlab_ml,  object_true):.6f}")
print(f"  Python ML:     {ml_obj_corr:.6f}")
print(f"  Python LSQML:  {lsqml_obj_corr:.6f}   (DM→LSQML recipe)")
print("\nProbe Correlation Incoherent (vs ground truth):")
print(f"  MATLAB DM:     {calc_corr(probe_matlab_dm_incoh, np.abs(probe_true)):.6f}")
print(f"  Python DM:     {dm_probe_corr:.6f}")
print(f"  MATLAB ML:     {calc_corr(probe_matlab_ml_incoh, np.abs(probe_true)):.6f}")
print(f"  Python ML:     {ml_probe_corr:.6f}")
print(f"  Python LSQML:  {lsqml_probe_corr:.6f}   (DM→LSQML recipe)")
print("="*80)

print("\nDone! Multi-mode test completed.")
