"""get_phase_gradient_1D.py

Port of MATLAB get_phase_gradient_1D.m (line-by-line).

MATLAB:
    function d_img = get_phase_gradient_1D(img, ax, step, shift)
        if isreal(img); img = exp(1i*img); end
        if nargin < 2; ax = 2; end
        if nargin < 3; step = 0.5; end
        if nargin < 4; shift = 0; end
        assert(step >= 0)
        pad_distance = 8;
        img = padarray(img, circshift([pad_distance,0,0], ax-1), 'symmetric', 'both');
        img = smooth_edges(img, pad_distance, ax);   % SKIP - just pad
        if step == 0
            img = img ./ (abs(img) + eps);
            d_img = get_img_grad(img, ax);
            d_img = imag(conj(img).*d_img);
        else
            d_img = angle(imshift_fft_ax(img,-step+shift,ax) .* conj(imshift_fft_ax(img,step+shift,ax)))/(2*step);
        end
        ind = circshift({pad_distance:size(d_img,ax)-pad_distance-1,':', ':'},ax-1);
        d_img = d_img(ind{:});
    end

Called as: get_phase_gradient_1D(stack_object, 1, 1)
  -> ax=1, step=1, shift=0
  -> pads 8 rows on each side of 3D stack (Nlayers, Nw, Nangles)
  -> d_img = angle(imshift_fft_ax(img, -1, 1) * conj(imshift_fft_ax(img, 1, 1))) / 2
  -> crop: MATLAB pad_distance:size-pad_distance-1 (1-based)
           = 8..N-8-1 (1-based, inclusive) = N-16 rows
           0-based Python: img[7 : 7+orig_N] = img[7 : padded_N-9]

Notes on MATLAB crop:
    MATLAB indices: pad_distance : size(d_img,ax) - pad_distance - 1
    = 8 : (orig_N + 16) - 8 - 1
    = 8 : orig_N + 7    (1-based, inclusive) -> orig_N elements
    Python 0-based: [7 : 7 + orig_N]
    = [pad_distance-1 : pad_distance-1 + orig_N]

smooth_edges is SKIPPED (adds minor edge artefacts, acceptable for comparison).
"""

import numpy as np
from utils.imshift_fft_ax import imshift_fft_ax


def get_phase_gradient_1D(img, ax=2, step=0.5, shift_val=0):
    """Compute 1-D phase gradient along axis `ax` (MATLAB 1-based).

    Parameters
    ----------
    img       : ndarray, real (phase map) or complex
    ax        : int, MATLAB axis (1=rows/axis0, 2=cols/axis1)
    step      : float, half-step for finite difference (must be >= 0)
    shift_val : float, additional shift offset (default 0)

    Returns
    -------
    d_img : ndarray, phase gradient (same dtype category, same shape as input)
    """
    # if isreal(img); img = exp(1i*img); end
    if np.isrealobj(img):
        img = np.exp(1j * img)

    assert step >= 0, "step must be >= 0"

    pad_distance = 8
    ax0 = ax - 1   # Python 0-based axis

    # img = padarray(img, circshift([pad_distance,0,0], ax-1), 'symmetric', 'both')
    # circshift([8,0,0], ax-1):
    #   ax=1: shift by 0 -> [8,0,0]  (pad 8 along axis 0)
    #   ax=2: shift by 1 -> [0,8,0]  (pad 8 along axis 1)
    #   ax=3: shift by 2 -> [0,0,8]  (pad 8 along axis 2)
    # For img with ndim < 3: pad along ax0 only
    ndim = img.ndim
    pad_config = [[0, 0]] * ndim
    if ax0 < ndim:
        pad_config[ax0] = [pad_distance, pad_distance]
    img = np.pad(img, pad_config, mode='symmetric')

    # smooth_edges: SKIPPED

    # Compute phase gradient
    if step == 0:
        raise NotImplementedError("step=0 (analytic gradient) not implemented")
    else:
        # d_img = angle(imshift_fft_ax(img,-step+shift,ax) .* conj(imshift_fft_ax(img,step+shift,ax))) / (2*step)
        img_neg = imshift_fft_ax(img, -step + shift_val, ax)
        img_pos = imshift_fft_ax(img,  step + shift_val, ax)
        d_img = np.angle(img_neg * np.conj(img_pos)) / (2.0 * step)

    # Crop back to original size
    # MATLAB: ind = circshift({pad_distance:size-pad_distance-1,':', ':'}, ax-1)
    # For ax=1 (axis 0): slice rows [8..N-8-1] (1-based) = [7..N-9] (0-based)
    # = [pad_distance-1 : padded_N - pad_distance - 1]
    padded_N = d_img.shape[ax0]
    orig_N   = padded_N - 2 * pad_distance
    crop_start = pad_distance - 1          # 0-based start: index 7 for pad=8
    crop_end   = crop_start + orig_N       # exclusive end

    slices = [slice(None)] * d_img.ndim
    slices[ax0] = slice(crop_start, crop_end)
    d_img = d_img[tuple(slices)]

    return d_img
