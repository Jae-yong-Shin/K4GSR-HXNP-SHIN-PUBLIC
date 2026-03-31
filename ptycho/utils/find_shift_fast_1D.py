"""find_shift_fast_1D.py

Port of MATLAB find_shift_fast_1D.m (line-by-line).

Only ax=1 (rows/vertical, Python axis 0) is implemented.
o1 shape: (Nlayers, Nangles), o2 shape: (Nlayers,) or (Nlayers, 1).
Result shift is (Nangles,) sub-pixel vertical shifts.
"""

import numpy as np
from scipy.signal.windows import tukey
from scipy.signal import convolve2d


def find_shift_fast_1D(o1, o2, ax=2, sigma=0.0, padding=0):
    """Find 1-D sub-pixel vertical shift between o1 columns and reference o2.

    Parameters
    ----------
    o1      : ndarray (Nlayers, Nangles), complex or real
    o2      : ndarray (Nlayers,) or (Nlayers, 1) or (Nlayers, Nangles), reference
    ax      : int, MATLAB axis (only ax=1 tested/implemented)
    sigma   : float, pre-filter width (0 = no pre-filter)
    padding : int, zero-padding added symmetrically along ax (even-rounded)

    Returns
    -------
    shift : ndarray (Nangles,), sub-pixel vertical shifts
    """
    # if ax ~= 1; error('Not tested'); end
    if ax != 1:
        raise NotImplementedError(f'find_shift_fast_1D: ax={ax} not tested')

    # padding = ceil(padding/2)*2  (round up to even)
    padding = int(np.ceil(padding / 2.0) * 2)

    # max_shift = size(o1, ax) / 3  (ax=1 -> shape[0])
    max_shift = o1.shape[0] / 3.0

    # Ndims = ndims(o1)
    Ndims = o1.ndim   # 2

    # symmetrize: o1 = cat(1, o1, flipud(o1))
    o1 = np.concatenate([o1, np.flipud(o1)], axis=0)
    # o2 may be 1D
    if o2.ndim == 1:
        o2 = o2[:, np.newaxis]
    o2 = np.concatenate([o2, np.flipud(o2)], axis=0)

    # Npix = size(o1)
    Npix = list(o1.shape)   # [2*Nlayers, Nangles]
    N = Npix[0]
    shape = [N, 1]          # broadcast shape for axis-0 operations

    # --- sigma pre-filter ---
    if sigma > 0:
        o1 = np.fft.fft(o1, axis=0)
        o2 = np.fft.fft(o2, axis=0)

        # x = reshape((-N/2+1 : N/2) / N, shape)
        x_vec = np.arange(-N // 2 + 1, N // 2 + 1) / N

        # spectral_filter = fftshift(exp(1 / (-(x^2)/sigma^2)))
        with np.errstate(divide='ignore', invalid='ignore'):
            exponent = np.where(x_vec == 0,
                                -np.inf,
                                1.0 / (-(x_vec ** 2) / (sigma ** 2)))
        sf = np.fft.fftshift(np.exp(exponent))

        # zero out spectral_filter(floor(end/2 + [-3:3]))
        # MATLAB 1-based: floor(N/2) in 1-based = N//2 -> 0-based: N//2 - 1
        mid = N // 2 - 1   # 0-based centre
        zero_idx = np.arange(mid - 3, mid + 4)
        zero_idx = zero_idx[(zero_idx >= 0) & (zero_idx < N)]
        sf[zero_idx] = 0.0

        sf = sf.reshape(shape)
        o1 = o1 * sf
        o2 = o2 * sf
        o1 = np.fft.ifft(o1, axis=0)
        o2 = np.fft.ifft(o2, axis=0)

    # remove symmetrization: o1 = o1(1:end/2, :)
    half = o1.shape[0] // 2
    o1 = o1[:half, :]
    o2 = o2[:half, :]

    # padding: padarray(o1, padding/2, 'both')
    if padding > 0:
        half_pad = padding // 2
        pad_cfg = [[half_pad, half_pad]] + [[0, 0]] * (o1.ndim - 1)
        o1 = np.pad(o1, pad_cfg, mode='constant', constant_values=0)
        o2 = np.pad(o2, pad_cfg, mode='constant', constant_values=0)

    # update Npix and shape
    N = o1.shape[0]
    shape = [N, 1]

    # Tukey window: spatial_filter = reshape(tukeywin(prod(shape)), shape)
    # prod([N,1]) = N, tukeywin(N, 0.5)
    tukey_win = tukey(N, alpha=0.5)
    spatial_filter = tukey_win.reshape(shape)

    o1 = o1 * spatial_filter
    o2 = o2 * spatial_filter

    # FFT along axis 0
    o1 = np.fft.fft(o1, axis=0)
    o2 = np.fft.fft(o2, axis=0)

    # xcorrmat = abs(ifft(o1 .* conj(o2), [], ax))
    xcorrmat = np.abs(np.fft.ifft(o1 * np.conj(o2), axis=0))

    # circshift(xcorrmat, floor(N/2), ax)
    xcorrmat = np.roll(xcorrmat, int(np.floor(N / 2)), axis=0)

    # zero out rows outside max_shift window
    # MATLAB: xcorrmat([1:ceil(N/2-max_shift), ceil(N/2+max_shift):end], :) = 0
    lo = int(np.ceil(N / 2.0 - max_shift))   # 1-based upper bound of low block
    hi = int(np.ceil(N / 2.0 + max_shift))   # 1-based lower bound of high block
    if lo > 0:
        xcorrmat[:lo, :] = 0.0
    if hi <= N:
        xcorrmat[hi - 1:, :] = 0.0

    # CoM peak detection
    WIN = 10
    kernel_size = (WIN, 1)

    # max along axis 0 -> shape (1, Nangles)
    max_vals = np.max(xcorrmat, axis=0, keepdims=True)

    # mask = conv2(xcorrmat == max_vals, ones(kernel_size), 'same')
    eq_mask = (xcorrmat == max_vals).astype(np.float32)
    mask = convolve2d(eq_mask, np.ones(kernel_size, dtype=np.float32), mode='same')

    # xcorrmat(~mask) = nan
    xcorrmat = xcorrmat.astype(np.float64)
    xcorrmat[mask == 0] = np.nan

    # xcorrmat = max(0, xcorrmat - min(xcorrmat, [], 1))
    min_vals = np.nanmin(xcorrmat, axis=0, keepdims=True)
    xcorrmat = np.maximum(0.0, xcorrmat - min_vals)

    # xcorrmat(~mask) = 0
    xcorrmat[mask == 0] = 0.0

    # xcorrmat = (xcorrmat / max(xcorrmat, [], 1))^4
    max_vals2 = np.max(xcorrmat, axis=0, keepdims=True)
    with np.errstate(divide='ignore', invalid='ignore'):
        xcorrmat = np.where(max_vals2 > 0, xcorrmat / max_vals2, 0.0) ** 4

    # MASS = sum(xcorrmat, 1) -> shape (Nangles,)
    MASS = np.sum(xcorrmat, axis=0)

    # grid = reshape(1:N, shape) -> (N, 1) 1-based row indices
    grid = np.arange(1, N + 1, dtype=float).reshape(shape)

    # shift = sum(xcorrmat * grid, 1) / MASS - floor(N/2) - 1
    shift = np.sum(xcorrmat * grid, axis=0) / (MASS + 1e-12) - int(np.floor(N / 2)) - 1

    return shift.ravel()   # (Nangles,)
