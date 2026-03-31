"""
get_projections.py - Extract object projections (ported from cSAXS +core/get_projections.m)

Extract probe-sized patches from full object at scan positions

Args:
    p: parameter structure with .asize, .positions, .scanidxs
    object: full-size object array
    scan_id: ID of current scan (1-based MATLAB indexing!)
    obj_proj: optional pre-allocated output array

Returns:
    obj_proj: extracted patches (asize[0], asize[1], Npos, Nmodes)

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


def get_projections(p, obj, scan_id, obj_proj=None):
    """
    Get object projections (patches) at scan positions

    MATLAB equivalent: +core/get_projections.m (lines 106-112, pure MATLAB version)

    Args:
        p: parameter dict/object with:
            - asize: probe size [height, width]
            - positions: (Npos_total, 2) array of positions (1-based MATLAB!)
            - scanidxs: list of scan indices for each scan (1-based MATLAB!)
        obj: full object array (H, W) or (H, W, modes)
        scan_id: scan index (1-based MATLAB!)
        obj_proj: optional pre-allocated output

    Returns:
        obj_proj: (asize[0], asize[1], Npos, Nmodes) extracted patches
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

    # MATLAB: if nargin < 4
    if obj_proj is None:
        # MATLAB: obj_proj = zeros([p.asize, Npos, Nmodes], 'like', object)
        asize = p['asize']
        obj_proj = xp.zeros((asize[0], asize[1], Npos, Nmodes), dtype=obj.dtype)

    # Size check
    # MATLAB: if any(max(round(p.positions(...))) + p.asize > [size(object,1), size(object,2)])
    positions_for_scan = p['positions'][np.array(scanidxs_matlab) - 1, :]  # Convert to 0-based (keep as numpy for indexing)
    max_pos = np.max(np.round(positions_for_scan).astype(int), axis=0)
    asize = p['asize']
    if np.any(max_pos + asize > np.array(obj.shape[:2])):
        raise ValueError('Object is too small for given positions')

    # Pure Python/NumPy version (MATLAB lines 106-112)
    # MATLAB: id_0 = p.scanidxs{scan_id}(1) - 1
    id_0 = scanidxs_matlab[0] - 1  # Convert to 0-based offset

    # MATLAB: for jj = p.scanidxs{scan_id}
    for i, jj_matlab in enumerate(scanidxs_matlab):
        jj_py = jj_matlab - 1  # Convert to 0-based

        # MATLAB: Indy = round(p.positions(jj,1)) + (1:p.asize(1))
        # MATLAB positions is 0-based offset, (1:N) is 1-based range
        # positions(jj,1) + (1:3) = [pos+1, pos+2, pos+3] in MATLAB 1-based
        # In Python 0-based: [pos, pos+1, pos+2]
        pos_y = int(np.round(p['positions'][jj_py, 0]))  # 0-based offset
        pos_x = int(np.round(p['positions'][jj_py, 1]))

        # MATLAB (1:N) starts from 1, so positions+1 is first element
        # Python: just use positions as starting index
        Indy = slice(pos_y, pos_y + asize[0])
        Indx = slice(pos_x, pos_x + asize[1])

        # MATLAB: obj_proj(:,:,jj-id_0,:) = object(Indy, Indx, :)
        # In Python: obj_proj[:, :, i, :] = obj[Indy, Indx, :]
        obj_proj[:, :, i, :] = obj[Indy, Indx, :]

    return obj_proj


# Module test
if __name__ == "__main__":
    print("Testing get_projections.py...")

    # Create test object
    obj = np.arange(100).reshape(10, 10).astype(float)

    # Create parameter structure
    # NOTE: In cSAXS, positions are stored as 0-based pixel offsets!
    p = {
        'asize': np.array([3, 3]),
        'positions': np.array([
            [0, 0],  # 0-based offset: extract from (0,0)
            [2, 2],  # 0-based offset: extract from (2,2)
            [4, 4],  # 0-based offset: extract from (4,4)
        ]),
        'scanidxs': [
            np.array([1, 2, 3])  # MATLAB 1-based scan indices
        ]
    }

    # Test
    result = get_projections(p, obj, scan_id=1)

    print(f"Object shape: {obj.shape}")
    print(f"Result shape: {result.shape}")  # Should be (3, 3, 3, 1)

    # Check first patch (position [1,1] in MATLAB = [0,0] in Python)
    print("\nFirst patch (from position [0,0]):")
    print(result[:, :, 0, 0].astype(int))
    print("Expected:")
    print(obj[0:3, 0:3].astype(int))

    # Check second patch
    print("\nSecond patch (from position [2,2]):")
    print(result[:, :, 1, 0].astype(int))
    print("Expected:")
    print(obj[2:5, 2:5].astype(int))

    print("\nTests complete!")
