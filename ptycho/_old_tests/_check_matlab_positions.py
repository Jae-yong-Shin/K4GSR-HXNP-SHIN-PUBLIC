"""Quick check MATLAB positions vs object."""
import numpy as np
import h5py
from pathlib import Path

mat_path = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat')

with h5py.File(str(mat_path), 'r') as f:
    object_true = f['object_true'][()].T if f['object_true'][()].ndim == 2 else f['object_true'][()]
    p_0 = f['p_0']

    if p_0['positions'].shape == (1, 1):
        positions = f[p_0['positions'][0, 0]][()].T
    else:
        positions = p_0['positions'][()].T

    if p_0['asize'].shape == (1, 1):
        asize = f[p_0['asize'][0, 0]][()].flatten().astype(int)
    else:
        asize = p_0['asize'][()].flatten().astype(int)

    if p_0['object'].shape == (1, 1):
        object_ref = f[p_0['object'][0, 0]]
        if object_ref.shape == (1, 1):
            object_initial = f[object_ref[0, 0]][()].T
        else:
            object_initial = object_ref[()].T
    else:
        object_initial = p_0['object'][()].T

print(f"object_true shape: {object_true.shape}")
print(f"object_initial shape: {object_initial.shape}")
print(f"asize: {asize}")
print(f"positions shape: {positions.shape}")
print(f"positions (first 5):")
for i in range(min(5, len(positions))):
    print(f"  [{i}] row={positions[i, 0]:.2f}, col={positions[i, 1]:.2f}")
print(f"positions range:")
print(f"  row: [{positions[:, 0].min():.2f}, {positions[:, 0].max():.2f}]")
print(f"  col: [{positions[:, 1].min():.2f}, {positions[:, 1].max():.2f}]")
print(f"\nobject_initial range needed for positions:")
print(f"  max row+asize: {positions[:, 0].max() + asize[0]:.0f}")
print(f"  max col+asize: {positions[:, 1].max() + asize[1]:.0f}")
print(f"  obj shape: {object_initial.shape}")

# Check MATLAB 1-based
print(f"\nIf positions are 1-based (subtract 1):")
pos_0 = positions - 1.0
print(f"  row: [{pos_0[:, 0].min():.2f}, {pos_0[:, 0].max():.2f}]")
print(f"  col: [{pos_0[:, 1].min():.2f}, {pos_0[:, 1].max():.2f}]")
print(f"  max row+asize: {pos_0[:, 0].max() + asize[0]:.0f}")
print(f"  max col+asize: {pos_0[:, 1].max() + asize[1]:.0f}")
