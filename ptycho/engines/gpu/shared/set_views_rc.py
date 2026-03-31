"""
Object view setting for ptychography.

Sets (accumulates) object updates from views at given positions.
Supports both CPU and GPU operation.
"""

import numpy as np
from ..gpu_wrapper import USE_GPU, GPU_AVAILABLE

if GPU_AVAILABLE:
    import cupy as cp


def set_views_rc(obj_update, obj_illum, psi, aprobe, layer_ids, object_id, indices, cache, scan_ids=None, skip_ind=None):
    """
    Set object views with update and illumination accumulation.

    Equivalent to MATLAB's set_views_rc().

    Parameters
    ----------
    obj_update : ndarray or cupy.ndarray or list
        Object update accumulator [Nx_o, Ny_o]
    obj_illum : ndarray or cupy.ndarray or list
        Object illumination accumulator [Nx_o, Ny_o]
    psi : ndarray or cupy.ndarray
        Update direction [Nx_p, Ny_p, N]
    aprobe : ndarray or cupy.ndarray
        Probe intensity or conjugate [Nx_p, Ny_p, N]
    layer_ids : int
        Layer ID for multilayer ptychography
    object_id : int or array-like
        Object ID (scan or incoherent mode)
    indices : array-like
        Processed positions
    cache : dict
        Cache structure with ROI information
    scan_ids : array-like, optional
        Scan IDs for each position
    skip_ind : array-like, optional
        Indices to skip

    Returns
    -------
    obj_update : ndarray or cupy.ndarray or list
        Updated object update accumulator
    obj_illum : ndarray or cupy.ndarray or list
        Updated object illumination accumulator

    Notes
    -----
    Accumulates updates:
    - obj_update[roi] += psi * conj(aprobe)  (already done outside)
    - obj_illum[roi] += |aprobe|^2
    """
    # Handle skip indices
    if skip_ind is None:
        skip_ind = []
    cache_skip = cache.get('skip_ind', [])
    skip_ind = list(skip_ind) + list(cache_skip)

    # Multi-scan wrapper (recursive)
    if scan_ids is not None and len(scan_ids) > 0:
        if isinstance(obj_update, (list, tuple)):
            # Multi-scan case
            if all(sid == scan_ids[0] for sid in scan_ids):
                unq_scans = [scan_ids[0]]
            else:
                unq_scans = list(set(scan_ids))

            if len(unq_scans) > 1 or len(obj_update) > 1:
                for kk in unq_scans:
                    ind_mask = [sid == kk for sid in scan_ids]
                    skip_ind_local = [indices[i] for i, m in enumerate(ind_mask) if not m]

                    obj_update[kk], obj_illum[kk] = set_views_rc(
                        obj_update[kk], obj_illum[kk], psi, aprobe,
                        layer_ids, object_id, indices, cache,
                        scan_ids=None, skip_ind=skip_ind_local
                    )
                return obj_update, obj_illum

    # Single object case
    if isinstance(object_id, (list, tuple, np.ndarray)):
        object_id = object_id[0]

    if isinstance(obj_update, (list, tuple)):
        obj_upd = obj_update[object_id]
        obj_ill = obj_illum[object_id]
    else:
        obj_upd = obj_update
        obj_ill = obj_illum

    # Get valid indices
    if len(skip_ind) > 0:
        ind_ok = [i for i, idx in enumerate(indices) if idx not in skip_ind]
        ind_ok = np.array(ind_ok, dtype=np.uint16)
    else:
        ind_ok = np.arange(len(indices), dtype=np.uint16)

    if len(ind_ok) == 0:
        if isinstance(obj_update, (list, tuple)):
            return obj_update, obj_illum
        else:
            return obj_upd, obj_ill

    # Get ROI positions
    oROI_s = cache.get('oROI_s', {})
    if object_id in oROI_s:
        roi_data = oROI_s[object_id]
    elif min(object_id, len(oROI_s) - 1) in oROI_s:
        roi_data = oROI_s[min(object_id, len(oROI_s) - 1)]
    else:
        raise ValueError(f"ROI data not found for object_id={object_id}")

    x_ranges = roi_data[0]
    y_ranges = roi_data[1]

    # Set views
    if USE_GPU and GPU_AVAILABLE and isinstance(obj_upd, cp.ndarray):
        obj_upd, obj_ill = _set_views_gpu(
            obj_upd, obj_ill, psi, aprobe, x_ranges, y_ranges, indices, ind_ok
        )
    else:
        obj_upd, obj_ill = _set_views_cpu(
            obj_upd, obj_ill, psi, aprobe, x_ranges, y_ranges, indices, ind_ok
        )

    # Return (restore list structure if needed)
    if isinstance(obj_update, (list, tuple)):
        obj_update[object_id] = obj_upd
        obj_illum[object_id] = obj_ill
        return obj_update, obj_illum
    else:
        return obj_upd, obj_ill


def _set_views_cpu(obj_update, obj_illum, psi, aprobe, x_ranges, y_ranges, indices, ind_ok):
    """
    CPU implementation of view setting.

    Accumulates updates into object array.
    """
    Np_p = [psi.shape[0], psi.shape[1]]

    for i, idx in enumerate(ind_ok):
        pos_idx = indices[idx]

        x_start = x_ranges[pos_idx, 0]
        y_start = y_ranges[pos_idx, 0]

        # Accumulate update (psi already contains psi * conj(probe))
        obj_update[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ] += psi[:, :, idx]

        # Accumulate illumination
        obj_illum[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ] += aprobe[:, :, idx]

    return obj_update, obj_illum


def _set_views_gpu(obj_update, obj_illum, psi, aprobe, x_ranges, y_ranges, indices, ind_ok):
    """
    GPU implementation of view setting.

    Uses CuPy scatter operations or custom kernel.
    """
    Np_p = [psi.shape[0], psi.shape[1]]

    # Ensure arrays are on GPU
    if not isinstance(x_ranges, cp.ndarray):
        x_ranges = cp.asarray(x_ranges)
    if not isinstance(y_ranges, cp.ndarray):
        y_ranges = cp.asarray(y_ranges)
    if not isinstance(ind_ok, cp.ndarray):
        ind_ok = cp.asarray(ind_ok, dtype=cp.uint16)

    # Accumulate views (loop on GPU - could be optimized)
    for i in range(len(ind_ok)):
        idx = int(ind_ok[i])
        pos_idx = indices[idx]

        x_start = int(x_ranges[pos_idx, 0])
        y_start = int(y_ranges[pos_idx, 0])

        # Accumulate update
        obj_update[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ] += psi[:, :, idx]

        # Accumulate illumination
        obj_illum[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ] += aprobe[:, :, idx]

    return obj_update, obj_illum


# TODO: Implement GPU MEX equivalent using CuPy RawKernel
# This would use atomic operations for concurrent accumulation
