"""imshift_fft_ax.py

Port of MATLAB imshift_fft_ax.m (line-by-line).

MATLAB signature:
    function img = imshift_fft_ax(img, shift, ax, apply_fft)
        if nargin < 4; apply_fft = true; end
        if all(shift == 0); return; end
        isReal = isreal(img);
        Npix = size(img);
        if ndims(img) == 3
            Np = [1,1,Npix(3)];
        else
            Np = Npix; Np(ax) = 1;
        end
        Ng = ones(1,3);
        if ax > ndims(img); Npix(ax) = 1; end
        Ng(ax) = Npix(ax);
        if isscalar(shift)
            shift = shift .* ones(Np);
        end
        grid = ifftshift(-fix(Npix(ax)/2):ceil(Npix(ax)/2)-1)/Npix(ax);
        X = bsxfun(@times, reshape(shift,Np), reshape(grid,Ng));
        X = exp((-2i*pi)*X);
        if apply_fft
            img = fft(img, [], ax);
        end
        img = bsxfun(@times, img, X);
        if apply_fft
            img = ifft(img, [], ax);
        end
        if isReal; img = real(img); end
    end

Notes:
- No GPU: Garray(x)=x, gather(x)=x
- apply_fft uses fft/ifft along ax (for 3D partial-FFT behaviour is same for ax=1 vertical)
- For 2D img (Nlayers, Nangles) and ax=1 (rows): shift is (Nangles,) vector,
  grid is (Nlayers,), X has shape (Nlayers, Nangles).
- For 3D img (Nlayers, Nw, Nangles) and ax=1: shift is (Nangles,) → reshape to (1,1,Nangles),
  grid is (Nlayers,) → reshape to (Nlayers,1,1).
"""

import numpy as np


def imshift_fft_ax(img, shift, ax, apply_fft=True):
    """Shift image along axis `ax` (MATLAB 1-based) using FFT phase ramp.

    Parameters
    ----------
    img   : ndarray, real or complex
    shift : scalar or array of shifts (one per slice perpendicular to ax)
    ax    : int, MATLAB 1-based axis (ax=1 → Python axis 0 = rows)
    apply_fft : bool, if True perform FFT before and IFFT after multiplication

    Returns
    -------
    img : ndarray (same shape, same dtype category)
    """
    shift = np.asarray(shift, dtype=float)

    # if all(shift == 0); return; end
    if np.all(shift == 0):
        return img

    # isReal = isreal(img)
    is_real = np.isrealobj(img)

    # Npix = size(img)
    Npix = list(img.shape)
    ndim = img.ndim

    # Pad Npix to length 3 for consistent indexing
    Npix3 = Npix + [1] * (3 - len(Npix))

    ax0 = ax - 1  # Python 0-based axis

    # if ndims(img) == 3
    #     Np = [1,1,Npix(3)];
    # else
    #     Np = Npix; Np(ax) = 1;
    if ndim == 3:
        Np = [1, 1, Npix3[2]]
    else:
        Np = list(Npix3[:ndim]) + [1] * (3 - ndim)
        Np[ax0] = 1

    # Ng = ones(1,3); Ng(ax) = Npix(ax)
    Ng = [1, 1, 1]
    # if ax > ndims(img); Npix(ax) = 1; end
    if ax > ndim:
        Npix3[ax0] = 1
    Ng[ax0] = Npix3[ax0]

    N_ax = Npix3[ax0]

    # if isscalar(shift); shift = shift .* ones(Np); end
    if shift.ndim == 0 or shift.size == 1:
        shift_arr = float(shift) * np.ones(Np[:ndim] if ndim <= 3 else Np)
    else:
        shift_arr = shift

    # grid = ifftshift(-fix(N/2):ceil(N/2)-1) / N
    # Python: np.fft.ifftshift(np.arange(-N//2, ceil(N/2))) / N
    grid = np.fft.ifftshift(np.arange(-(N_ax // 2), int(np.ceil(N_ax / 2)))) / N_ax

    # reshape(shift, Np) and reshape(grid, Ng)
    # Trim Np and Ng to actual ndim for reshaping
    np_shape = Np[:ndim]
    ng_shape = Ng[:ndim]

    shift_r = shift_arr.reshape(np_shape)   # (1, Nangles) for 2D ax=1
    grid_r  = grid.reshape(ng_shape)        # (Nlayers, 1) for 2D ax=1

    # X = bsxfun(@times, shift_r, grid_r)
    X = shift_r * grid_r   # broadcast → (Nlayers, Nangles) for 2D ax=1

    # X = exp(-2i*pi * X)
    X = np.exp((-2j * np.pi) * X)

    # if apply_fft; img = fft(img, [], ax); end
    if apply_fft:
        img = np.fft.fft(img, axis=ax0)

    # img = bsxfun(@times, img, X)
    img = img * X

    # if apply_fft; img = ifft(img, [], ax); end
    if apply_fft:
        img = np.fft.ifft(img, axis=ax0)

    # if isReal; img = real(img); end
    if is_real:
        img = np.real(img)

    return img
