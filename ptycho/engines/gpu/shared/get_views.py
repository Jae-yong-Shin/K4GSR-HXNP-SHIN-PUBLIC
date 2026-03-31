"""
Object view extraction for ptychography.

Extracts object views (regions of interest) for each scan position.
Supports both CPU and GPU operation.
"""

import numpy as np
from ..gpu_wrapper import USE_GPU, GPU_AVAILABLE, Gzeros, Garray

if GPU_AVAILABLE:
    import cupy as cp


def get_views(object_array, obj_proj, layer_ids, object_id, indices, cache, scan_ids=None, skip_ind=None):
    """
    Extract object views for given positions.

    Equivalent to MATLAB's get_views().

    Parameters
    ----------
    object_array : ndarray or cupy.ndarray or cell-like
        Object array [Nx_o, Ny_o] or cell array for multi-scan
    obj_proj : ndarray or cupy.ndarray
        Preallocated array for views [Nx_p, Ny_p, N]
    layer_ids : int
        Layer ID for multilayer ptychography
    object_id : int or array-like
        Object ID (scan or incoherent mode)
    indices : array-like
        Processed positions
    cache : dict
        Cache structure with ROI information:
        - 'oROI_s': {object_id: [{1: x_ranges, 2: y_ranges}]}
        - 'skip_ind': indices to skip
    scan_ids : array-like, optional
        Scan IDs for each position (multi-scan support)
    skip_ind : array-like, optional
        Additional indices to skip

    Returns
    -------
    obj_proj : ndarray or cupy.ndarray
        [Nx_p, Ny_p, N] array with object views

    Notes
    -----
    For CPU: Uses advanced indexing
    For GPU: Uses CuPy indexing (or custom kernel if needed)
    """
    Np_p = [obj_proj.shape[0], obj_proj.shape[1]]
    N_positions = len(indices)

    # Resize obj_proj if needed
    if obj_proj.shape[2] != N_positions or obj_proj.size == 0:
        if obj_proj.size == 0:
            obj_proj = Gzeros([Np_p[0], Np_p[1], N_positions], is_complex=True)
        else:
            # Create new array with correct size
            if USE_GPU and GPU_AVAILABLE:
                obj_proj = cp.zeros([Np_p[0], Np_p[1], N_positions], dtype=obj_proj.dtype)
            else:
                obj_proj = np.zeros([Np_p[0], Np_p[1], N_positions], dtype=obj_proj.dtype)

    # Handle skip indices
    if skip_ind is None:
        skip_ind = []
    cache_skip = cache.get('skip_ind', [])
    skip_ind = list(skip_ind) + list(cache_skip)

    # Multi-scan wrapper (recursive)
    if scan_ids is not None and len(scan_ids) > 0:
        if isinstance(object_array, (list, tuple)):
            # Multi-scan or multi-object case
            if all(sid == scan_ids[0] for sid in scan_ids):
                unq_scans = [scan_ids[0]]
            else:
                unq_scans = list(set(scan_ids))

            if len(unq_scans) > 1 or len(object_array) > 1:
                # Call recursively for each scan
                for kk in unq_scans:
                    ind_mask = [sid == kk for sid in scan_ids]
                    skip_ind_local = [indices[i] for i, m in enumerate(ind_mask) if not m]
                    obj_proj = get_views(
                        object_array[kk], obj_proj, layer_ids, object_id,
                        indices, cache, scan_ids=None, skip_ind=skip_ind_local
                    )
                return obj_proj

    # Single object case
    if isinstance(object_id, (list, tuple, np.ndarray)):
        object_id = object_id[0]

    if isinstance(object_array, (list, tuple)):
        object_array = object_array[object_id]

    # Get valid indices (not in skip_ind)
    if len(skip_ind) > 0:
        ind_ok = [i for i, idx in enumerate(indices) if idx not in skip_ind]
        ind_ok = np.array(ind_ok, dtype=np.uint16)
    else:
        ind_ok = np.arange(len(indices), dtype=np.uint16)

    if len(ind_ok) == 0:
        return obj_proj

    # Get ROI positions
    oROI_s = cache.get('oROI_s', {})
    if object_id in oROI_s:
        roi_data = oROI_s[object_id]
    elif min(object_id, len(oROI_s) - 1) in oROI_s:
        roi_data = oROI_s[min(object_id, len(oROI_s) - 1)]
    else:
        raise ValueError(f"ROI data not found for object_id={object_id}")

    # Extract ROI ranges
    # MATLAB format: cache.oROI_s{object_id}{1}(indices, 1) for x
    #                cache.oROI_s{object_id}{2}(indices, 1) for y
    x_ranges = roi_data[0]  # Assuming {1} → [0]
    y_ranges = roi_data[1]  # Assuming {2} → [1]

    # Extract views
    if USE_GPU and GPU_AVAILABLE and isinstance(object_array, cp.ndarray):
        # GPU path
        obj_proj = _get_views_gpu(object_array, obj_proj, x_ranges, y_ranges, indices, ind_ok)
    else:
        # CPU path
        obj_proj = _get_views_cpu(object_array, obj_proj, x_ranges, y_ranges, indices, ind_ok)

    return obj_proj


def _get_views_cpu(object_array, obj_proj, x_ranges, y_ranges, indices, ind_ok):
    """
    CPU implementation of view extraction.

    Uses NumPy advanced indexing to extract rectangular regions.
    """
    Np_p = [obj_proj.shape[0], obj_proj.shape[1]]

    for i, idx in enumerate(ind_ok):
        pos_idx = indices[idx]

        # Get start positions
        x_start = x_ranges[pos_idx, 0]
        y_start = y_ranges[pos_idx, 0]

        # Extract view
        obj_proj[:, :, idx] = object_array[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ]

    return obj_proj


def _get_views_gpu(object_array, obj_proj, x_ranges, y_ranges, indices, ind_ok):
    """
    GPU implementation of view extraction.

    Uses CuPy advanced indexing or custom kernel.
    """
    Np_p = [obj_proj.shape[0], obj_proj.shape[1]]

    # Ensure x_ranges, y_ranges are on GPU
    if not isinstance(x_ranges, cp.ndarray):
        x_ranges = cp.asarray(x_ranges)
    if not isinstance(y_ranges, cp.ndarray):
        y_ranges = cp.asarray(y_ranges)

    # Convert indices to GPU
    if not isinstance(ind_ok, cp.ndarray):
        ind_ok = cp.asarray(ind_ok, dtype=cp.uint16)

    # Extract views (loop on GPU - could be optimized with custom kernel)
    for i in range(len(ind_ok)):
        idx = int(ind_ok[i])
        pos_idx = indices[idx]

        x_start = int(x_ranges[pos_idx, 0])
        y_start = int(y_ranges[pos_idx, 0])

        obj_proj[:, :, idx] = object_array[
            y_start:y_start + Np_p[0],
            x_start:x_start + Np_p[1]
        ]

    return obj_proj


# TODO: Implement GPU MEX equivalent using CuPy RawKernel for better performance
# This would replace _get_views_gpu with a compiled CUDA kernel
