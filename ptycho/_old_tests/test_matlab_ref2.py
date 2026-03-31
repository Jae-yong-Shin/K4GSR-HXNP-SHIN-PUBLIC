"""
Test Python GPU DM with MATLAB reference data (csaxs_dataset6).
Compare Python output with MATLAB DM output.
Fix: transpose fmag from (Npos, Ny, Nx) to (Ny, Nx, Npos).
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

MATLAB_REF = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref')

# ========================================
# 1. Load MATLAB reference data
# ========================================
print("=" * 60)
print("  Loading MATLAB reference data: csaxs_dataset6")
print("=" * 60)

fmag_data = np.load(MATLAB_REF / 'csaxs_dataset6_diffraction.npy')     # (43, 192, 192)
obj_true   = np.load(MATLAB_REF / 'csaxs_dataset6_obj_true.npy')       # (329, 336)
positions  = np.load(MATLAB_REF / 'csaxs_dataset6_positions.npy')      # (43, 2)
probe_true = np.load(MATLAB_REF / 'csaxs_dataset6_probe_true.npy')     # (192, 192)

# Transpose fmag: (Npos, Ny, Nx) -> (Ny, Nx, Npos)
fmag_data = np.transpose(fmag_data, (1, 2, 0))
print(f"  fmag (transposed): {fmag_data.shape}, dtype={fmag_data.dtype}")
print(f"  obj_true: {obj_true.shape}, |obj| range=[{np.abs(obj_true).min():.4f}, {np.abs(obj_true).max():.4f}]")
print(f"  positions: {positions.shape}")
print(f"  probe_true: {probe_true.shape}, |P| max={np.abs(probe_true).max():.4f}")

asize = probe_true.shape[0]
Npos = positions.shape[0]

# Load MATLAB DM result for comparison
import h5py
with h5py.File(str(MATLAB_REF / 'matlab_dm_only_results.mat'), 'r') as f:
    obj_r = np.array(f['object_recon'])
    if obj_r.dtype.names == ('real', 'imag'):
        obj_matlab = obj_r['real'] + 1j * obj_r['imag']
    else:
        obj_matlab = obj_r
    obj_matlab = obj_matlab.T  # column-major -> row-major

    pr_r = np.array(f['probe_recon'])
    if pr_r.dtype.names == ('real', 'imag'):
        pr_matlab = pr_r['real'] + 1j * pr_r['imag']
    else:
        pr_matlab = pr_r
    pr_matlab = pr_matlab.T

print(f"  MATLAB obj_recon: {obj_matlab.shape}, |obj| range=[{np.abs(obj_matlab).min():.4f}, {np.abs(obj_matlab).max():.4f}]")
print(f"  MATLAB probe_recon: {pr_matlab.shape}, |P| max={np.abs(pr_matlab).max():.4f}")

# ========================================
# 2. Norm error function
# ========================================
def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

ne_matlab = norm_error(obj_matlab, obj_true.squeeze())
print(f"  MATLAB DM norm_error: {ne_matlab:.4f}")

# ========================================
# 3. Run Python GPU DM
# ========================================
print(f"\n{'=' * 60}")
print(f"  Running Python GPU DM with MATLAB ref data")
print(f"{'=' * 60}")

# Build object_init (ones, same size as MATLAB's object)
obj_h, obj_w = obj_matlab.shape
object_init = np.ones((obj_h, obj_w), dtype=np.complex64)

from server.data_loader import DataLoader
dl = DataLoader()

data = {
    'fmag': fmag_data.astype(np.float32),
    'positions': positions,
    'probes': probe_true.astype(np.complex64),
    'object_init': object_init,
    'asize': (asize, asize),
    'Npos': Npos,
}

p = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,  # CPU for safety
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

from engines.gpu.DM import DM as DM_GPU

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print(f"  probe_in |P|^2 sum = {np.sum(np.abs(probes_in)**2):.1f}")
print(f"  probe_in |P| max = {np.abs(probes_in).max():.4f}")
print(f"  obj_init shape = {ob[0].shape}")

# Run DM 50
ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=50)

ob_py = ob_dm[0].squeeze()

ne_py = norm_error(ob_py, obj_true.squeeze())
grade = "EXCELLENT" if ne_py < 0.15 else "GOOD" if ne_py < 0.30 else "MARGINAL" if ne_py < 0.50 else "POOR"
print(f"\n  Python DM50: norm_error={ne_py:.4f}, |obj| max={np.abs(ob_py).max():.4f}, {grade}")
print(f"  MATLAB DM:   norm_error={ne_matlab:.4f}, |obj| max={np.abs(obj_matlab).max():.4f}")

# ========================================
# 4. Track norm_error per iteration
# ========================================
print(f"\n{'=' * 60}")
print(f"  Python DM: norm_error vs iteration")
print(f"{'=' * 60}")

for n_iter in [1, 2, 5, 10, 20, 50]:
    # Reset
    probes_in2 = p['probes'][:, :, 0, 0].copy() if p['probes'].ndim == 4 else p['probes'].copy()
    ob2 = [o.squeeze().copy() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze().copy()]
    import copy
    p2 = copy.deepcopy(p)

    ob_n, pr_n, err_n = DM_GPU(
        p2, ob=ob2, probes=probes_in2,
        fmag=p2['fmag'], positions=p2['positions'], num_iterations=n_iter)

    ob_n_sq = ob_n[0].squeeze()
    ne_n = norm_error(ob_n_sq, obj_true.squeeze())
    grade_n = "EXCELLENT" if ne_n < 0.15 else "GOOD" if ne_n < 0.30 else "MARGINAL" if ne_n < 0.50 else "POOR"
    print(f"  DM {n_iter:3d}: norm_error={ne_n:.4f}, |obj| max={np.abs(ob_n_sq).max():.4f}, {grade_n}")

# ========================================
# 5. Save comparison image
# ========================================
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))

    axes[0].imshow(np.abs(obj_true.squeeze()), cmap='jet')
    axes[0].set_title('Ground Truth')

    axes[1].imshow(np.abs(obj_matlab), cmap='jet')
    axes[1].set_title(f'MATLAB DM\nerr={ne_matlab:.4f}')

    axes[2].imshow(np.abs(ob_py), cmap='jet')
    axes[2].set_title(f'Python DM50\nerr={ne_py:.4f}, {grade}')

    axes[3].semilogy(range(1, len(err_dm)), err_dm[1:], 'b-', lw=2, label='Python DM err')
    axes[3].legend()
    axes[3].set_title('Fourier Error')
    axes[3].grid(True, alpha=0.3)

    fig.suptitle('MATLAB ref data: Python DM vs MATLAB DM', fontweight='bold')
    plt.tight_layout()
    out = Path(__file__).parent / 'test_matlab_ref2_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
