"""
object_update_norm.py - Object update for DM engine

Python equivalent of engines.DM.object_update_norm MEX function
Pure Python version from DM.m lines 266-278

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np
import sys
from pathlib import Path

try:
    import cupy as cp
    def get_xp(arr):
        return cp.get_array_module(arr)
except ImportError:
    cp = None
    def get_xp(arr):
        return np

# Import set_projections from core
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'core'))
from set_projections import set_projections


def object_update_norm(p, cprobes, ob, pr_nrm, iter_scan, scan_id, prnum=None):
    """
    Object update with normalization for DM engine

    MATLAB equivalent: DM.m lines 266-278 (pure MATLAB version)

    Args:
        p: parameter dict with .object_modes, .numprobs, .asize
        cprobes: conjugate of probes (asize[0], asize[1], numprobs, probe_modes)
        ob: current object estimate (H, W) or (H, W, object_modes)
        pr_nrm: probe normalization accumulator (H, W)
        iter_scan: iterates for this scan (asize[0], asize[1], Npos, probe_modes)
                   or (asize[0], asize[1], Npos, probe_modes, object_modes)
        scan_id: scan ID (1-based MATLAB indexing!)
        prnum: probe number (only needed if object_modes > 1 or numprobs > 1)

    Returns:
        ob: updated object
        pr_nrm: updated probe normalization
    """
    object_modes = p.get('object_modes', 1)
    numprobs = p.get('numprobs', 1)

    # Get array module based on iter_scan type
    xp = get_xp(iter_scan)

    # MATLAB: if p.object_modes == 1 && p.numprobs == 1
    if object_modes == 1 and numprobs == 1:
        # MATLAB: cprobe = cprobes
        cprobe = cprobes

        # DEBUG: Check shapes before multiplication
        if cprobe.shape[0] != p['asize'][0] or cprobe.shape[1] != p['asize'][1]:
            print(f"WARNING: cprobe shape mismatch!")
            print(f"  Expected: ({p['asize'][0]}, {p['asize'][1]}, *, *)")
            print(f"  Got: {cprobe.shape}")
            print(f"  iter_scan shape: {iter_scan.shape}")

            # Fix: ensure cprobe has correct first two dimensions
            if cprobe.ndim == 4:
                # Take only the probe window
                cprobe = cprobe[:p['asize'][0], :p['asize'][1], :, :]

        # MATLAB: obj_update = sum(bsxfun(@times, cprobe, iter{ii}),4)
        # bsxfun(@times, a, b) -> a * b (broadcasting)
        # sum(..., 4) -> sum along dim 4 (MATLAB) = axis 3 (Python)
        # keepdims=True to preserve mode dimension for set_projections
        obj_update = xp.sum(cprobe * iter_scan, axis=3, keepdims=True)

        # MATLAB: ob{obnum} = core.set_projections(p, ob{obnum}, obj_update , ii)
        ob = set_projections(p, ob, obj_update, scan_id)

    else:
        # MATLAB: cprobe = cprobes(:,:,prnum,:)
        if prnum is None:
            raise ValueError("prnum required when object_modes > 1 or numprobs > 1")

        # Convert prnum from 1-based to 0-based
        prnum_py = prnum - 1 if isinstance(prnum, int) else prnum - 1
        cprobe = cprobes[:, :, prnum_py, :]

        # MATLAB: for obmode = 1:p.object_modes
        for obmode in range(object_modes):
            # MATLAB: obj_update = sum(bsxfun(@times, cprobe, iter{ii}(:,:,:,:,obmode)),4)
            obj_update = xp.sum(cprobe * iter_scan[:, :, :, :, obmode], axis=3, keepdims=True)

            # MATLAB: ob{obnum}(:,:,obmode) = core.set_projections(p, ob{obnum}(:,:,obmode), obj_update , ii)
            ob[:, :, obmode] = set_projections(p, ob[:, :, obmode], obj_update, scan_id)

    # MATLAB: pr_nrm{obnum} = core.set_projections(p, pr_nrm{obnum}, sum(abs(cprobe).^2,4) , ii)
    # Note: cprobe has no position dimension, but set_projections needs it
    # We need to broadcast to Npos positions
    Npos = iter_scan.shape[2]
    probe_norm_single = xp.sum(xp.abs(cprobe)**2, axis=3, keepdims=True)  # (asize, asize, 1, 1)
    probe_norm_update = xp.tile(probe_norm_single, (1, 1, Npos, 1))  # Broadcast to (asize, asize, Npos, 1)
    pr_nrm = set_projections(p, pr_nrm, probe_norm_update, scan_id)

    return ob, pr_nrm


# Module test
if __name__ == "__main__":
    print("Testing object_update_norm.py...")

    # Create test parameters
    p = {
        'object_modes': 1,
        'numprobs': 1,
        'asize': np.array([8, 8]),
        'positions': np.array([
            [0, 0],
            [4, 4],
        ]),
        'scanidxs': [
            np.array([1, 2])  # MATLAB 1-based
        ]
    }

    # Create test data
    asize = p['asize']
    Npos = 2
    probe_modes = 1
    object_modes = 1

    cprobes = np.ones((asize[0], asize[1], 1, probe_modes), dtype=complex)
    ob = np.zeros((20, 20), dtype=complex)
    pr_nrm = np.zeros((20, 20), dtype=float)
    iter_scan = np.ones((asize[0], asize[1], Npos, probe_modes), dtype=complex) * (1 + 1j)

    # Test
    ob_new, pr_nrm_new = object_update_norm(p, cprobes, ob, pr_nrm, iter_scan, scan_id=1)

    print(f"Object shape: {ob_new.shape}")
    print(f"Probe norm shape: {pr_nrm_new.shape}")
    print(f"Object max value: {np.max(np.abs(ob_new)):.2f}")
    print(f"Probe norm max value: {np.max(pr_nrm_new):.2f}")

    # Check that update happened
    assert np.any(ob_new != 0), "Object should be updated"
    assert np.any(pr_nrm_new != 0), "Probe norm should be updated"

    print("\nTest passed!")
