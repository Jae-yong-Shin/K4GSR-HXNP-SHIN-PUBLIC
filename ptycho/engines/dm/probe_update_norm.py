"""
probe_update_norm.py - Probe update for DM engine

Python equivalent of engines.DM.probe_update_norm MEX function
Pure Python version from DM.m lines 321-332

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

# Import get_projections from core
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'core'))
from get_projections import get_projections


def probe_update_norm(p, ob, iter_scan, nprobe, pr_denom, scan_id, obj_proj=None):
    """
    Probe update with normalization for DM engine

    MATLAB equivalent: DM.m lines 321-332 (pure MATLAB version)

    Args:
        p: parameter dict with .object_modes, .numprobs, .asize
        ob: current object estimate (H, W) or (H, W, object_modes)
        iter_scan: iterates for this scan (asize[0], asize[1], Npos, probe_modes)
                   or (asize[0], asize[1], Npos, probe_modes, object_modes)
        nprobe: probe numerator accumulator (asize[0], asize[1])
        pr_denom: probe denominator accumulator (asize[0], asize[1])
        scan_id: scan ID (1-based MATLAB indexing!)
        obj_proj: optional pre-allocated buffer for get_projections

    Returns:
        nprobe: updated probe numerator
        pr_denom: updated probe denominator
    """
    object_modes = p.get('object_modes', 1)
    numprobs = p.get('numprobs', 1)

    # Get array module based on iter_scan type
    xp = get_xp(iter_scan)

    # MATLAB: if p.object_modes == 1 && p.numprobs == 1
    if object_modes == 1 and numprobs == 1:
        # MATLAB: obj_proj = core.get_projections(p, ob{obnum}, ii, obj_proj)
        obj_proj = get_projections(p, ob, scan_id, obj_proj)

        # MATLAB: nprobe = nprobe + sum(bsxfun(@times,iter{ii}, conj(obj_proj)), 3)
        # sum over positions (dim 3 in MATLAB = axis 2 in Python)
        # MATLAB sum removes trailing singletons, NumPy doesn't - squeeze explicitly
        nprobe_update = xp.sum(iter_scan * xp.conj(obj_proj), axis=2)
        if nprobe_update.shape[-1] == 1 and nprobe.ndim < nprobe_update.ndim:
            nprobe_update = xp.squeeze(nprobe_update, axis=-1)
        nprobe = nprobe + nprobe_update

        # MATLAB: pr_denom = pr_denom + sum(abs(obj_proj).^2,3)
        # sum over positions (dim 3 in MATLAB = axis 2 in Python)
        # MATLAB sum removes trailing singletons, NumPy doesn't - squeeze explicitly
        pr_denom_update = xp.sum(xp.abs(obj_proj)**2, axis=2)
        if pr_denom_update.shape[-1] == 1 and pr_denom.ndim < pr_denom_update.ndim:
            pr_denom_update = xp.squeeze(pr_denom_update, axis=-1)
        pr_denom = pr_denom + pr_denom_update

    else:
        # MATLAB: for obmode = 1:p.object_modes
        for obmode in range(object_modes):
            # MATLAB: obj_proj = core.get_projections(p, ob{obnum}(:,:,obmode), ii)
            obj_proj = get_projections(p, ob[:, :, obmode], scan_id)

            # MATLAB: nprobe = nprobe + sum(bsxfun(@times,iter{ii}(:,:,:,:,obmode), conj(obj_proj)),3)
            # MATLAB sum removes trailing singletons, NumPy doesn't - squeeze explicitly
            nprobe_update = xp.sum(iter_scan[:, :, :, :, obmode] * xp.conj(obj_proj), axis=2)
            if nprobe_update.shape[-1] == 1 and nprobe.ndim < nprobe_update.ndim:
                nprobe_update = xp.squeeze(nprobe_update, axis=-1)
            nprobe = nprobe + nprobe_update

            # MATLAB: pr_denom = pr_denom + sum(abs(obj_proj).^2,3)
            # MATLAB sum removes trailing singletons, NumPy doesn't - squeeze explicitly
            pr_denom_update = xp.sum(xp.abs(obj_proj)**2, axis=2)
            if pr_denom_update.shape[-1] == 1 and pr_denom.ndim < pr_denom_update.ndim:
                pr_denom_update = xp.squeeze(pr_denom_update, axis=-1)
            pr_denom = pr_denom + pr_denom_update

    return nprobe, pr_denom


# Module test
if __name__ == "__main__":
    print("Testing probe_update_norm.py...")

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

    ob = np.ones((20, 20), dtype=complex) * (1 + 0.5j)
    # nprobe and pr_denom should have probe_modes dimension!
    nprobe = np.zeros((asize[0], asize[1], probe_modes), dtype=complex)
    pr_denom = np.zeros((asize[0], asize[1], probe_modes), dtype=float)
    iter_scan = np.ones((asize[0], asize[1], Npos, probe_modes), dtype=complex) * (0.5 + 0.5j)

    # Test
    nprobe_new, pr_denom_new = probe_update_norm(p, ob, iter_scan, nprobe, pr_denom, scan_id=1)

    print(f"Probe numerator shape: {nprobe_new.shape}")
    print(f"Probe denominator shape: {pr_denom_new.shape}")
    print(f"Probe numerator max: {np.max(np.abs(nprobe_new)):.2f}")
    print(f"Probe denominator max: {np.max(pr_denom_new):.2f}")

    # Check that update happened
    assert np.any(nprobe_new != 0), "Probe numerator should be updated"
    assert np.any(pr_denom_new != 0), "Probe denominator should be updated"

    # Check shapes (should NOT have position dimension after sum, but should have probe_modes)
    expected_shape = (8, 8, probe_modes)
    assert nprobe_new.shape == expected_shape, f"Expected {expected_shape} but got {nprobe_new.shape}"
    assert pr_denom_new.shape == expected_shape, f"Expected {expected_shape} but got {pr_denom_new.shape}"

    print("\nTest passed!")
