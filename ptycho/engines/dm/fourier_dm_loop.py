"""
fourier_dm_loop.py - Fourier projection for DM engine

Python equivalent of engines.DM.Fourier_DM_loop_par2 MEX function
Pure Python version from DM.m lines 461-501

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

# Import get_projections from core and sum2 from math
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'math'))
from get_projections import get_projections
from sum2 import sum2


def fourier_dm_loop(p, ob, probes, iter_scans, fmag_scans, obj_proj=None):
    """
    Fourier projection loop for DM engine

    MATLAB equivalent: DM.m lines 461-501 (pure MATLAB version)

    Args:
        p: parameter dict with:
            - numscans, asize, object_modes, numprobs
            - share_probe_ID, share_object_ID
            - fmask, pfft_relaxation
            - scanidxs, numpos
        ob: list of object arrays
        probes: probe array (asize, asize, numprobs, probe_modes)
        iter_scans: list of iterate arrays (one per scan)
        fmag_scans: list of measured Fourier magnitudes (one per scan)
        obj_proj: optional pre-allocated buffer

    Returns:
        iter_scans: updated iterates
        er2: error metric (scalar)
    """
    numscans = p.get('numscans', 1)
    object_modes = p.get('object_modes', 1)
    numprobs = p.get('numprobs', 1)
    asize = p['asize']

    # Get array module based on first iter_scan array
    xp = get_xp(iter_scans[0])

    er2 = 0.0

    # MATLAB: for ii = 1:p.numscans
    for ii in range(numscans):
        # Convert to 1-based for function calls
        scan_id = ii + 1

        # MATLAB: prnum = p.share_probe_ID(ii)
        # MATLAB: obnum = p.share_object_ID(ii)
        prnum = p['share_probe_ID'][ii]
        obnum = p['share_object_ID'][ii]

        # MATLAB: fnorm = sqrt(prod(p.asize))
        fnorm = xp.sqrt(xp.array(float(np.prod(asize))))

        # MATLAB: p1 = zeros([p.asize,length(p.scanidxs{ii}),p.probe_modes,p.object_modes])
        Npos = len(p['scanidxs'][ii])
        probe_modes = probes.shape[3]
        p1_shape = (asize[0], asize[1], Npos, probe_modes, object_modes)
        p1 = xp.zeros(p1_shape, dtype=complex)

        # MATLAB: if p.object_modes == 1 && p.numprobs == 1
        if object_modes == 1 and numprobs == 1:
            # MATLAB: obj_proj = core.get_projections(p, ob{obnum}, ii, obj_proj)
            obj_proj = get_projections(p, ob[obnum], scan_id, obj_proj)

            # MATLAB: p1 = bsxfun(@times, p.probes, obj_proj)
            # probes: (asize, asize, 1, probe_modes)
            # obj_proj: (asize, asize, Npos, 1)
            # result: (asize, asize, Npos, probe_modes)
            # Assign to first object mode
            p1[:, :, :, :, 0] = probes * obj_proj

        else:
            # MATLAB: for obmode = 1:p.object_modes
            for obmode in range(object_modes):
                # MATLAB: obj_proj = core.get_projections(p, ob{obnum}(:,:,obmode), ii)
                obj_proj = get_projections(p, ob[obnum][:, :, obmode], scan_id)

                # MATLAB: p1(:,:,:,:,obmode) = bsxfun(@times, p.probes(:,:,prnum,:), obj_proj)
                # Convert prnum from 1-based to 0-based
                prnum_py = prnum - 1 if isinstance(prnum, int) else prnum - 1
                p1[:, :, :, :, obmode] = probes[:, :, prnum_py, :] * obj_proj

        # Squeeze object_modes dimension if it's 1
        if object_modes == 1:
            p1 = xp.squeeze(p1, axis=4)

        # MATLAB: f = fft2(2*p1 - iter{ii}) / fnorm
        iter_scan = iter_scans[ii]
        f = xp.fft.fft2(2*p1 - iter_scan, axes=(0, 1)) / fnorm

        # MATLAB: af = abs(f)
        af = xp.abs(f)

        # MATLAB: ph = f ./ (af+1e-3)
        ph = f / (af + 1e-10)

        # MATLAB: fmag_target = bsxfun(@times, af, fmag{ii}./sqrt(sum(af.^2,4)))
        # sum(af^2, 4) -> sum over probe_modes (axis 3)
        # Add epsilon to avoid division by zero
        fmag_target = af * (fmag_scans[ii] / xp.sqrt(xp.sum(af**2, axis=3, keepdims=True) + 1e-10))

        # MATLAB: fdev = af - fmag_target
        fdev = af - fmag_target

        # MATLAB: if size(p.fmask,3)==p.numpos
        fmask = p['fmask']
        numpos = p.get('numpos', sum(len(p['scanidxs'][i]) for i in range(numscans)))
        if fmask.ndim == 3 and fmask.shape[2] == numpos:
            # MATLAB: fmaski = p.fmask(:,:,p.scanidxs{ii})
            # Convert scanidxs from 1-based to 0-based
            scanidxs_py = np.array(p['scanidxs'][ii]) - 1
            fmaski = fmask[:, :, scanidxs_py]
        else:
            fmaski = fmask

        # Ensure fmaski has correct shape for broadcasting with af (asize, asize, Npos, probe_modes)
        # Add dimensions as needed
        while fmaski.ndim < 4:
            fmaski = fmaski[:, :, None] if fmaski.ndim == 2 else xp.expand_dims(fmaski, axis=-1)

        # MATLAB: af = bsxfun(@times, af, 1-fmaski) + bsxfun(@times, fmaski, fmag_target + fdev * p.pfft_relaxation)
        pfft_relaxation = p.get('pfft_relaxation', 0.05)
        af = af * (1 - fmaski) + fmaski * (fmag_target + fdev * pfft_relaxation)

        # MATLAB: p2 = fnorm*ifft2(af .* ph)
        p2 = fnorm * xp.fft.ifft2(af * ph, axes=(0, 1))

        # MATLAB: df = p2 - p1
        df = p2 - p1

        # MATLAB: iter{ii} = iter{ii} + df
        iter_scans[ii] = iter_scan + df

        # MATLAB: er2 = sum2(squeeze(sum2(abs(df).^2)))
        # sum2 reduces first 2 dimensions
        df_abs2 = xp.abs(df)**2
        temp = sum2(df_abs2)  # sum over spatial dimensions
        temp = xp.squeeze(temp)  # remove singleton dimensions
        er2 += float(sum2(temp)) if temp.ndim >= 2 else float(xp.sum(temp))

    return iter_scans, er2


# Module test
if __name__ == "__main__":
    print("Testing fourier_dm_loop.py...")

    # Create test parameters
    asize = np.array([8, 8])
    Npos = 2
    probe_modes = 1
    object_modes = 1

    p = {
        'numscans': 1,
        'object_modes': object_modes,
        'numprobs': 1,
        'asize': asize,
        'positions': np.array([
            [0, 0],
            [4, 4],
        ]),
        'scanidxs': [
            np.array([1, 2])  # MATLAB 1-based
        ],
        'share_probe_ID': np.array([1]),  # 1-based
        'share_object_ID': np.array([0]),  # 0-based (Python list index)
        'fmask': np.ones((asize[0], asize[1], 1)),  # No mask
        'pfft_relaxation': 0.05,
        'numpos': Npos
    }

    # Create test data
    ob = [np.ones((20, 20), dtype=complex) * (1 + 0.5j)]
    probes = np.ones((asize[0], asize[1], 1, probe_modes), dtype=complex) * 0.5
    iter_scans = [np.ones((asize[0], asize[1], Npos, probe_modes), dtype=complex) * (0.3 + 0.3j)]
    fmag_scans = [np.ones((asize[0], asize[1], Npos, probe_modes)) * 0.5]

    # Save original for comparison
    iter_scans_original = [x.copy() for x in iter_scans]

    # Test
    iter_new, er2 = fourier_dm_loop(p, ob, probes, iter_scans, fmag_scans)

    print(f"Updated iterates shape: {iter_new[0].shape}")
    print(f"Error metric (er2): {er2:.6f}")
    print(f"Iterate max value: {np.max(np.abs(iter_new[0])):.4f}")

    # Check that update happened
    assert np.any(iter_new[0] != iter_scans_original[0]), "Iterates should be updated"
    assert er2 >= 0, "Error metric should be non-negative"

    print("\nTest passed!")
