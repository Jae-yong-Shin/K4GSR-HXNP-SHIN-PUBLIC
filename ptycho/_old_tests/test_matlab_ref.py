"""
Test with MATLAB reference data: csaxs_dataset6.
Compare Python GPU DM output with MATLAB DM output.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

MATLAB_REF = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref')

# Load csaxs_dataset6
fmag_data = np.load(MATLAB_REF / 'csaxs_dataset6_diffraction.npy')
obj_true = np.load(MATLAB_REF / 'csaxs_dataset6_obj_true.npy')
positions = np.load(MATLAB_REF / 'csaxs_dataset6_positions.npy')
probe_true = np.load(MATLAB_REF / 'csaxs_dataset6_probe_true.npy')

print(f"MATLAB Reference: csaxs_dataset6")
print(f"  fmag: {fmag_data.shape}, dtype={fmag_data.dtype}")
print(f"  obj_true: {obj_true.shape}, dtype={obj_true.dtype}")
print(f"  positions: {positions.shape}, dtype={positions.dtype}")
print(f"  probe_true: {probe_true.shape}, dtype={probe_true.dtype}")
print(f"  fmag range: [{fmag_data.min():.4f}, {fmag_data.max():.4f}]")
print(f"  |obj| range: [{np.abs(obj_true).min():.4f}, {np.abs(obj_true).max():.4f}]")
print(f"  |probe| max: {np.abs(probe_true).max():.4f}")

asize = probe_true.shape[0]
Npos = positions.shape[0]
print(f"  asize={asize}, Npos={Npos}")

# Load MATLAB DM result
try:
    import h5py
    with h5py.File(str(MATLAB_REF / 'matlab_dm_only_results.mat'), 'r') as f:
        keys = list(f.keys())
        print(f"\nMATLAB DM results keys: {keys}")
        for k in keys:
            v = f[k]
            if hasattr(v, 'shape'):
                print(f"  {k}: shape={v.shape}, dtype={v.dtype}")
            else:
                print(f"  {k}: type={type(v)}")

        # Try to extract object
        if 'object_final' in keys:
            obj_matlab = np.array(f['object_final'])
            if obj_matlab.dtype.names == ('real', 'imag'):
                obj_matlab = obj_matlab['real'] + 1j * obj_matlab['imag']
            obj_matlab = obj_matlab.T  # MATLAB is column-major
            print(f"\n  MATLAB obj_final: shape={obj_matlab.shape}, |obj| range=[{np.abs(obj_matlab).min():.4f}, {np.abs(obj_matlab).max():.4f}]")
        elif 'object' in keys:
            obj_ref = f['object']
            if hasattr(obj_ref, 'shape'):
                obj_matlab = np.array(obj_ref)
                if obj_matlab.dtype.names == ('real', 'imag'):
                    obj_matlab = obj_matlab['real'] + 1j * obj_matlab['imag']
                obj_matlab = obj_matlab.T
                print(f"\n  MATLAB object: shape={obj_matlab.shape}, |obj| range=[{np.abs(obj_matlab).min():.4f}, {np.abs(obj_matlab).max():.4f}]")

        # Try to extract error history
        for err_key in ['error', 'err', 'fourier_error']:
            if err_key in keys:
                err_matlab = np.array(f[err_key]).flatten()
                print(f"\n  MATLAB {err_key}: shape={err_matlab.shape}")
                print(f"    first 5: {err_matlab[:5]}")
                print(f"    last 5: {err_matlab[-5:]}")

except Exception as e:
    print(f"Error loading MATLAB results: {e}")

# ============================================
# Run Python GPU DM with same data
# ============================================
print(f"\n{'='*60}")
print(f"  Running Python GPU DM with MATLAB ref data")
print(f"{'='*60}")

# Build object_init (ones, same size as obj_true or larger)
obj_h, obj_w = obj_true.shape[:2]
object_init = np.ones((obj_h, obj_w), dtype=np.complex64)

from server.data_loader import DataLoader
dl = DataLoader()

data = {
    'fmag': fmag_data,
    'positions': positions,
    'probes': probe_true,
    'object_init': object_init,
    'asize': (asize, asize),
    'Npos': Npos,
}

p = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': True,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

from engines.gpu.DM import DM as DM_GPU

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

print(f"  probe_in |P|^2 sum = {np.sum(np.abs(probes_in)**2):.1f}")
print(f"  obj_init shape = {ob[0].shape}")
print(f"  positions range: row=[{positions[:,0].min():.1f}, {positions[:,0].max():.1f}], col=[{positions[:,1].min():.1f}, {positions[:,1].max():.1f}]")

ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=50)

ob_py = ob_dm[0].squeeze()

def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

ne = norm_error(ob_py, obj_true.squeeze())
grade = "EXCELLENT" if ne < 0.15 else "GOOD" if ne < 0.30 else "MARGINAL" if ne < 0.50 else "POOR"
print(f"\n  Python GPU DM50: norm_error={ne:.4f}, |obj| max={np.abs(ob_py).max():.4f}, {grade}")
print(f"  Fourier error: iter1={err_dm[1]:.4e}, iter50={err_dm[50]:.4e}")
