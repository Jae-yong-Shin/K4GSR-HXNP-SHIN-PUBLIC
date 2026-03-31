"""
set_projections.py - Accumulate object patches (ported from cSAXS +core/set_projections.m)

Accumulate probe-sized patches back into full object at scan positions

Args:
    p: parameter structure with .asize, .positions, .scanidxs
    object: full-size object array
    obj_update: updated patches to accumulate
    scan_id: ID of current scan (1-based MATLAB indexing!)

Returns:
    object: updated full-size object (accumulated)

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np

try:
    import cupy as cp
    def get_xp(arr):
        return cp.get_array_module(arr)
except ImportError:
    cp = None
    def get_xp(arr):
        return np


def set_projections(p, obj, obj_update, scan_id):
    """
    Set (accumulate) object projections (patches) at scan positions

    MATLAB equivalent: +core/set_projections.m (lines 102-109, pure MATLAB version)

    Args:
        p: parameter dict/object with:
            - asize: probe size [height, width]
            - positions: (Npos_total, 2) array of positions (0-based in cSAXS!)
            - scanidxs: list of scan indices for each scan (1-based MATLAB!)
        obj: full object array (H, W) or (H, W, modes) - MODIFIED IN PLACE
        obj_update: updated patches (asize[0], asize[1], Npos, Nmodes)
        scan_id: scan index (1-based MATLAB!)

    Returns:
        obj: updated object (same reference, modified in place)
    """
    # Convert scan_id from 1-based to 0-based
    scan_id_py = scan_id - 1

    # Get array module (numpy or cupy) based on obj type
    xp = get_xp(obj)

    # MATLAB: Npos = length(p.scanidxs{scan_id})
    scanidxs_matlab = p['scanidxs'][scan_id_py]  # 1-based indices
    Npos = len(scanidxs_matlab)

    # MATLAB: Nmodes = size(object, 4)
    # In Python, modes might be 3rd dimension
    if obj.ndim == 2:
        Nmodes = 1
        obj = obj[:, :, None]  # Add mode dimension (None works with both np and cp)
    elif obj.ndim == 3:
        Nmodes = obj.shape[2]
    else:
        raise ValueError(f"Unexpected object shape: {obj.shape}")

    # Size check (use numpy for scalar comparisons)
    # MATLAB: if any(max(round(p.positions(...))) + p.asize > size(object))
    positions_for_scan = p['positions'][np.array(scanidxs_matlab) - 1, :]  # Convert to 0-based
    max_pos = np.max(np.round(positions_for_scan).astype(int), axis=0)
    asize = p['asize']
    if np.any(max_pos + asize > np.array(obj.shape[:2])):
        raise ValueError('Object is too small for given positions')

    # Pure Python/NumPy version (MATLAB lines 102-109)
    # MATLAB: id_0 = p.scanidxs{scan_id}(1)-1
    id_0 = scanidxs_matlab[0] - 1  # Convert to 0-based offset

    # MATLAB: for jj = p.scanidxs{scan_id}
    for i, jj_matlab in enumerate(scanidxs_matlab):
        jj_py = jj_matlab - 1  # Convert to 0-based

        # MATLAB: Indy = round(p.positions(jj,1)) + (1:p.asize(1))
        # MATLAB: Indx = round(p.positions(jj,2)) + (1:p.asize(2))
        pos_y = int(np.round(p['positions'][jj_py, 0]))  # 0-based offset
        pos_x = int(np.round(p['positions'][jj_py, 1]))

        Indy = slice(pos_y, pos_y + asize[0])
        Indx = slice(pos_x, pos_x + asize[1])

        # MATLAB: object(Indy,Indx,:) = object(Indy,Indx,:) + obj_update(:,:,min(jj-id_0,end),:)
        # Note: min(jj-id_0, end) is for safety, but in normal case jj-id_0 equals loop index
        # In Python: obj[Indy, Indx, :] += obj_update[:, :, i, :]
        obj[Indy, Indx, :] += obj_update[:, :, i, :]

    return obj


# Module test
if __name__ == "__main__":
    print("Testing set_projections.py...")

    # Create test object (start with zeros)
    obj = np.zeros((10, 10), dtype=float)

    # Create parameter structure
    # NOTE: In cSAXS, positions are stored as 0-based pixel offsets!
    p = {
        'asize': np.array([3, 3]),
        'positions': np.array([
            [0, 0],  # 0-based offset: write to (0,0)
            [2, 2],  # 0-based offset: write to (2,2)
            [4, 4],  # 0-based offset: write to (4,4)
        ]),
        'scanidxs': [
            np.array([1, 2, 3])  # MATLAB 1-based scan indices
        ]
    }

    # Create updates - simple 3x3 patches with constant values
    obj_update = np.zeros((3, 3, 3, 1), dtype=float)
    obj_update[:, :, 0, 0] = 1.0  # First patch: all ones
    obj_update[:, :, 1, 0] = 2.0  # Second patch: all twos
    obj_update[:, :, 2, 0] = 3.0  # Third patch: all threes

    # Test - accumulate patches into object
    result = set_projections(p, obj, obj_update, scan_id=1)

    print(f"Object shape: {result.shape}")
    print(f"Result (should have 1s at [0:3,0:3], 2s at [2:5,2:5], 3s at [4:7,4:7]):")
    print(result[:, :, 0].astype(int))

    # Check specific regions
    print("\nVerification:")
    print(f"  Top-left (0:3,0:3) should be 1: {result[0, 0, 0]} (overlap region may be higher)")
    print(f"  Middle (2:5,2:5) includes overlaps from patch 1 and 2")
    print(f"  Bottom-right pure region [6,6]: {result[6, 6, 0]} (should be 3)")

    # Test accumulation (call twice)
    print("\n--- Test accumulation (call twice) ---")
    obj2 = np.zeros((10, 10), dtype=float)
    result2 = set_projections(p, obj2, obj_update, scan_id=1)
    result2 = set_projections(p, result2, obj_update, scan_id=1)
    print(f"After 2 accumulations, [0,0] = {result2[0, 0, 0]} (should be 2)")
    print(f"After 2 accumulations, [6,6] = {result2[6, 6, 0]} (should be 6)")

    print("\nTests complete!")
