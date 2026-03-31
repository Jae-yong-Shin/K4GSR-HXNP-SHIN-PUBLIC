"""find_shift_fast_2D - Sub-pixel shift via cross-correlation.

Ported from PSI cSAXS: +utils/find_shift_fast_2D.m
License: CC BY-NC-SA 4.0. Python port: K4GSR-TOMOGRAPHY 2026.

Sign convention (verified against MATLAB source):
  xcorr(o1, shift(o1, dr, dc)) peak is at (-dr, -dc) from center.
  find_shift_fast_2D(o1, o2) returns [x=col_shift, y=row_shift] where
  x = -(shift applied to o1 cols to create o2),  y = -(row shift).
  This is the CORRECTION shift: apply to o2 to recover o1.
  Equivalently: returns shift of o1 relative to o2.

Usage:
    from utils.find_shift_fast_2D import find_shift_fast_2D
    shift = find_shift_fast_2D(o1, o2, sigma=0.01, apply_fft=True)
    # shift = [x, y] = [col_shift, row_shift], shape (2,) or (N,2)

MATLAB->NumPy convention summary:
  MATLAB size=[rows,cols,depth] == numpy shape
  MATLAB meshgrid(x,y): X[i,j]=x[j] (same as np.meshgrid)
  MATLAB nx=rows=Ny, ny=cols=Nx (confusing in source, preserved)
  MATLAB tukeywin -> scipy.signal.windows.tukey
  MATLAB fftshift_2D -> np.fft.fftshift(a, axes=(0,1))
  1-based index sum (1:M) -> np.arange(1, M+1)
"""

import numpy as np
from scipy.signal.windows import tukey
from scipy.signal import fftconvolve

def _fftshift_2d(a):
    return np.fft.fftshift(a, axes=(0, 1))

def _find_center_fast(xcorrmat):
    is_2d = xcorrmat.ndim == 2
    if is_2d:
        xcorrmat = xcorrmat[:, :, np.newaxis]
    Ny, Nx, Nslices = xcorrmat.shape
    MASS = xcorrmat.reshape(Ny * Nx, Nslices).sum(axis=0)
    col_sums = xcorrmat.sum(axis=0)
    col_idx = np.arange(1, Nx + 1, dtype=float)
    x = np.einsum("is,i->s", col_sums, col_idx) / MASS - np.floor(Nx / 2) - 1
    row_sums = xcorrmat.sum(axis=1)
    row_idx = np.arange(1, Ny + 1, dtype=float)
    y = np.einsum("is,i->s", row_sums, row_idx) / MASS - np.floor(Ny / 2) - 1
    if is_2d:
        return float(x[0]), float(y[0])
    return x, y

def find_shift_fast_2D(o1, o2, sigma=0.01, apply_fft=True, method="full_range"):
    o1 = np.asarray(o1, dtype=complex)
    o2 = np.asarray(o2, dtype=complex)
    is_2d = o1.ndim == 2
    if is_2d:
        o1 = o1[:, :, np.newaxis]
        o2 = o2[:, :, np.newaxis]
    Ny, Nx, Nslices = o1.shape
    if apply_fft:
        win_r = tukey(Ny, 0.5).reshape(-1, 1)
        win_c = tukey(Nx, 0.5).reshape(1, -1)
        sp_f = win_r * win_c
        o1 = o1 * sp_f[:, :, np.newaxis]
        o2 = o2 * sp_f[:, :, np.newaxis]
        o1 = np.fft.fft2(o1, axes=(0, 1))
        o2 = np.fft.fft2(o2, axes=(0, 1))
    if sigma > 0:
        x_v = np.arange(-Ny // 2, Ny // 2) / Ny
        y_v = np.arange(-Nx // 2, Nx // 2) / Nx
        X, Y = np.meshgrid(x_v, y_v)
        r2 = X**2 + Y**2
        with np.errstate(divide="ignore", invalid="ignore"):
            exp_arg = np.where(r2 > 0, 1.0 / (-(r2) / sigma**2), -np.inf)
        sf = np.fft.fftshift(np.exp(exp_arg))
        filt = sf.T
        o1 = o1 * filt[:, :, np.newaxis]
        o2 = o2 * filt[:, :, np.newaxis]
    xcorrmat = np.abs(np.fft.ifft2(o1 * np.conj(o2), axes=(0, 1)))
    xcorrmat = _fftshift_2d(xcorrmat)
    if method == "full_range":
        result = _method_full_range(xcorrmat, Ny, Nx, Nslices)
    elif method == "limited_range":
        result = _method_limited_range(xcorrmat, Ny, Nx, Nslices)
    else:
        raise ValueError("Unknown method")
    return result[0] if is_2d else result

def _proc_fr_slice(sl, kernel):
    sl = sl.copy()
    maxval = float(np.max(sl))
    peak_ind = (sl == maxval).astype(np.float32)
    mask_dil = fftconvolve(peak_ind, kernel, mode="same")
    mb = mask_dil > 0.5
    sl[~mb] = np.nan
    minval = float(np.nanmin(sl))
    sl = np.maximum(0.0, sl - minval)
    sl[~mb] = 0.0
    maxval2 = float(np.max(sl))
    if maxval2 > 0:
        sl = (sl / maxval2) ** 2
    sl = np.maximum(0.0, sl - 0.5) ** 2
    return sl

def _method_full_range(xcorrmat, Ny, Nx, Nslices):
    WIN = 5
    kernel = np.ones((WIN, WIN), dtype=np.float32)
    xc = xcorrmat.astype(float).copy()
    if xc.ndim == 2:
        xc = _proc_fr_slice(xc, kernel)
    else:
        for s in range(Nslices):
            xc[:, :, s] = _proc_fr_slice(xc[:, :, s], kernel)
    x, y = _find_center_fast(xc)
    if np.isscalar(x):
        return np.array([[x, y]])
    return np.column_stack([x, y])

def _method_limited_range(xcorrmat, Ny, Nx, Nslices):
    MAX_SHIFT = 10
    MAX_SHIFT_X = int(min(np.floor(Ny / 2 - 0.5), MAX_SHIFT))
    MAX_SHIFT_Y = int(min(np.floor(Nx / 2 - 0.5), MAX_SHIFT))
    mxcorr = xcorrmat if xcorrmat.ndim == 2 else xcorrmat.mean(axis=2)
    m0, n0 = np.unravel_index(np.argmax(mxcorr), mxcorr.shape)
    m = m0 + 1
    n = n0 + 1
    ri = (m - 1 + np.arange(-MAX_SHIFT_X, MAX_SHIFT_X + 1)) % Ny
    ci = (n - 1 + np.arange(-MAX_SHIFT_Y, MAX_SHIFT_Y + 1)) % Nx
    if xcorrmat.ndim == 2:
        sub = xcorrmat[np.ix_(ri, ci)].copy()
    else:
        sub = xcorrmat[np.ix_(ri, ci, np.arange(Nslices))].copy()
    mx = float(np.max(sub))
    if mx > 0:
        sub = sub / mx
    xc = np.maximum(0.0, sub - 0.5) ** 2
    x_loc, y_loc = _find_center_fast(xc)
    off_x = float(n) - np.floor(Nx / 2) - 1
    off_y = float(m) - np.floor(Ny / 2) - 1
    if np.isscalar(x_loc):
        return np.array([[x_loc + off_x, y_loc + off_y]])
    return np.column_stack([x_loc + off_x, y_loc + off_y])
