"""
Gradient-based position refinement for ptychography.

Ports MATLAB +engines/+GPU/private/gradient_position_solver.m
and +engines/+GPU/private/get_img_grad.m

Algorithm:
  - Compute spatial gradient of object views (Fourier-domain differentiation)
  - Per-position shift: dx = sum(real(conj(grad_x*P) * xi)) / sum(|grad_x*P|^2)
  - Clip outlier shifts using MAD estimator
"""

import numpy as np
from ..gpu_wrapper import USE_GPU, GPU_AVAILABLE, Ggather

if GPU_AVAILABLE:
    import cupy as cp


# ── Image gradient ─────────────────────────────────────────────────────────────

def get_img_grad(img):
    """
    Spatial gradient via Fourier differentiation.

    Ports MATLAB get_img_grad.m

    Parameters
    ----------
    img : ndarray, shape [..., Ny, Nx]
        Complex-valued image stack (last two dims are spatial)

    Returns
    -------
    dX : ndarray
        Gradient along X (horizontal / column direction)
    dY : ndarray
        Gradient along Y (vertical / row direction)
    """
    if USE_GPU and GPU_AVAILABLE:
        xp = cp
    else:
        xp = np

    img = xp.asarray(img)
    Ny, Nx = img.shape[-2], img.shape[-1]

    # Frequency coordinates: fftshift so DC is at index Np//2
    kX = xp.fft.fftshift(xp.arange(Nx, dtype=np.float32)) / Nx - 0.5  # [Nx]
    kY = xp.fft.fftshift(xp.arange(Ny, dtype=np.float32)) / Ny - 0.5  # [Ny]

    # Broadcast shapes: [..., 1, Nx] and [..., Ny, 1]
    kX = kX[..., np.newaxis, :]   # [1, Nx]
    kY = kY[..., :, np.newaxis]   # [Ny, 1]

    if USE_GPU and GPU_AVAILABLE:
        # GPU: 2D FFT is faster (avoid separate 1D FFTs)
        F = xp.fft.fft2(img, axes=(-2, -1))
        dX = xp.fft.ifft2(F * (2j * np.pi * kX), axes=(-2, -1))
        dY = xp.fft.ifft2(F * (2j * np.pi * kY), axes=(-2, -1))
    else:
        # CPU: separate 1D FFTs along each axis (avoids redundant computation)
        fX = xp.fft.fft(img, axis=-1)   # FFT along columns
        fY = xp.fft.fft(img, axis=-2)   # FFT along rows
        dX = xp.fft.ifft(fX * (2j * np.pi * kX), axis=-1)
        dY = xp.fft.ifft(fY * (2j * np.pi * kY), axis=-2)

    return dX.astype(np.complex64), dY.astype(np.complex64)


# ── MAD estimator ──────────────────────────────────────────────────────────────

def _mad(x):
    """Median absolute deviation (robust scale estimator)."""
    x = np.asarray(x).ravel()
    return float(np.median(np.abs(x - np.median(x))))


# ── Position solver ────────────────────────────────────────────────────────────

def gradient_position_solver(xi, O_views, P, probe_position_search=1, iter_num=1):
    """
    Estimate per-position shifts from exit-wave residual.

    Ports MATLAB gradient_position_solver.m (real-space gradient method).

    Parameters
    ----------
    xi : ndarray, shape [N_pos, Ny, Nx]
        Exit-wave update / residual (backward propagated)
    O_views : ndarray, shape [N_pos, Ny, Nx]
        Object views at current probe positions
    P : ndarray, shape [Ny, Nx]
        Current probe estimate (single mode)
    probe_position_search : int
        Start iteration for position refinement (default 1)
    iter_num : int
        Current iteration number

    Returns
    -------
    pos_update : ndarray, shape [N_pos, 2]
        Position correction in pixels: [delta_row, delta_col]
        Returns zeros if iter_num < probe_position_search
    """
    N_pos = xi.shape[0]

    if iter_num < probe_position_search:
        return np.zeros((N_pos, 2), dtype=np.float32)

    if USE_GPU and GPU_AVAILABLE:
        xp = cp
    else:
        xp = np

    xi_g      = xp.asarray(xi)       # [N_pos, Ny, Nx]
    O_views_g = xp.asarray(O_views)  # [N_pos, Ny, Nx]
    P_g       = xp.asarray(P)        # [Ny, Nx]

    # ── Object spatial gradient ────────────────────────────────────────────────
    # dx_O, dy_O: [N_pos, Ny, Nx]
    dx_O, dy_O = get_img_grad(O_views_g)

    # ── Shift coefficients ─────────────────────────────────────────────────────
    # For each position: numerator = sum_xy( real(conj(grad*P) * xi) )
    #                  denom     = sum_xy( |grad*P|^2 )
    P_bc = P_g[np.newaxis, :, :]  # [1, Ny, Nx] – broadcast over positions

    dx_OP = dx_O * P_bc   # [N_pos, Ny, Nx]
    dy_OP = dy_O * P_bc

    # Sum over spatial dims (axes -2, -1) to get per-position scalar
    nom_dx   = xp.sum(xp.real(xp.conj(dx_OP) * xi_g), axis=(-2, -1))  # [N_pos]
    denom_dx = xp.sum(xp.abs(dx_OP) ** 2,              axis=(-2, -1))  # [N_pos]

    nom_dy   = xp.sum(xp.real(xp.conj(dy_OP) * xi_g), axis=(-2, -1))
    denom_dy = xp.sum(xp.abs(dy_OP) ** 2,              axis=(-2, -1))

    # Per-position shifts [N_pos]
    dx = Ggather(nom_dx / (denom_dx + 1e-9)).astype(np.float32)
    dy = Ggather(nom_dy / (denom_dy + 1e-9)).astype(np.float32)

    # Stack → [N_pos, 2]: [delta_row(y), delta_col(x)]
    shift = np.stack([dy, dx], axis=-1)  # Note: row=Y direction, col=X direction

    # ── Outlier rejection ──────────────────────────────────────────────────────
    # MATLAB: max_shift = min(0.1, 10*mad(shift))
    # MATLAB mad() with 2D input computes per-column MAD → separate X/Y clipping limits
    mad_row = _mad(shift[:, 0])   # Y / row direction
    mad_col = _mad(shift[:, 1])   # X / col direction
    max_shift_row = min(0.1, 10.0 * mad_row)
    max_shift_col = min(0.1, 10.0 * mad_col)
    shift[:, 0] = np.clip(shift[:, 0], -max_shift_row, max_shift_row)
    shift[:, 1] = np.clip(shift[:, 1], -max_shift_col, max_shift_col)

    if iter_num % 5 == 0 or iter_num == 1:
        avg = float(np.mean(np.abs(shift)))
        mx  = float(np.max(np.abs(shift)))
        print(f'  [PosRef] iter={iter_num}  avg={avg:.4f}px  max={mx:.4f}px'
              f'  max_clip row={max_shift_row:.4f}px col={max_shift_col:.4f}px')

    return shift


# ── Position application ────────────────────────────────────────────────────────

def apply_position_update(positions, pos_update, obj_shape, probe_shape):
    """
    Apply position corrections and clamp to valid object range.

    Parameters
    ----------
    positions : ndarray, shape [N_pos, 2]
        Current positions [row, col] (pixel)
    pos_update : ndarray, shape [N_pos, 2]
        Position deltas from gradient_position_solver
    obj_shape : tuple (obj_r, obj_c)
        Object array size
    probe_shape : tuple (Ny, Nx)
        Probe array size

    Returns
    -------
    positions : ndarray, shape [N_pos, 2]
        Updated and clamped positions
    """
    positions = positions + pos_update

    # Clamp: probe window must remain inside object
    row_max = obj_shape[0] - probe_shape[0]
    col_max = obj_shape[1] - probe_shape[1]

    positions[:, 0] = np.clip(positions[:, 0], 0, row_max)
    positions[:, 1] = np.clip(positions[:, 1], 0, col_max)

    return positions.astype(np.float32)
