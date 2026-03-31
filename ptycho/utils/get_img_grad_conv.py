"""get_img_grad_conv.py

Port of MATLAB get_img_grad_conv.m (line-by-line).

MATLAB:
    function [dX, dY, dZ] = get_img_grad_conv(img, win_size, axis)
        ker = get_kernel(win_size);
        if nargin < 3 || any(axis == 2)
            dX = convn(img, reshape(ker,1,[],1), 'same');
        end
        if nargout > 1 || (nargin > 2 && any(axis == 1))
            dY = convn(img, reshape(ker,[],1,1), 'same');
            if nargout == 1; dX = dY; end
        end
        if nargout > 2 || (nargin > 2 && any(axis == 3))
            dZ = convn(img, reshape(ker,1,1,[]), 'same');
            if nargout == 1; dX = dZ; end
        end
    end

    function ker = get_kernel(win_size)
        N = max(9, 2*win_size+1);
        grid = 2i*pi*(fftshift((0:N-1)/N) - 0.5);
        ker = -real(fftshift(fft(grid)))/length(grid);
        ker = ker(ceil(end/2)+(-ceil(win_size):ceil(win_size)));
        ker = single(ker);
    end

Called as: get_img_grad_conv(m_invar, 2, 1)
  -> axis=1, win_size=2
  -> dY = convn(img, reshape(ker,[],1,1), 'same') -> kernel along rows (axis 0 in Python)
  -> N = max(9, 2*2+1) = 9, truncated to centre 2*ceil(2)+1 = 5 elements
"""

import numpy as np
from scipy.ndimage import convolve1d


def get_kernel(win_size):
    """Compute derivative kernel of half-width win_size.

    MATLAB:
        N = max(9, 2*win_size+1)
        grid = 2i*pi*(fftshift((0:N-1)/N) - 0.5)
        ker = -real(fftshift(fft(grid)))/N
        ker = ker(ceil(N/2)+(-ceil(win_size):ceil(win_size)))
    """
    win_size = int(win_size)
    N = max(9, 2 * win_size + 1)

    # grid = 2i*pi*(fftshift((0:N-1)/N) - 0.5)
    freq = np.fft.fftshift(np.arange(N) / N) - 0.5
    grid = 2j * np.pi * freq

    # ker = -real(fftshift(fft(grid))) / N
    ker = -np.real(np.fft.fftshift(np.fft.fft(grid))) / N

    # ker = ker(ceil(N/2) + (-ceil(win_size) : ceil(win_size)))
    # MATLAB ceil(N/2) is 1-based centre index
    # For N=9: ceil(9/2) = 5 (1-based) -> 0-based: 4
    centre = int(np.ceil(N / 2)) - 1   # 0-based centre
    half   = int(np.ceil(win_size))
    ker = ker[centre - half: centre + half + 1]

    return ker.astype(np.float32)


def get_img_grad_conv(img, win_size, axis=None):
    """Compute image gradient along specified MATLAB axis using convolution.

    Parameters
    ----------
    img      : ndarray (any shape, real or float)
    win_size : int, half-width of derivative kernel
    axis     : int, MATLAB axis (1=rows/axis0, 2=cols/axis1)

    Returns
    -------
    grad : ndarray, gradient along specified axis (same shape as img)
    """
    ker = get_kernel(win_size)

    if axis == 1:
        # dY = convn(img, reshape(ker,[],1,1), 'same') -> convolve along rows (axis 0)
        return convolve1d(img.astype(float), ker.astype(float), axis=0, mode='reflect')
    elif axis == 2:
        # dX = convn(img, reshape(ker,1,[],1), 'same') -> convolve along cols (axis 1)
        return convolve1d(img.astype(float), ker.astype(float), axis=1, mode='reflect')
    elif axis == 3:
        # dZ = convn(img, reshape(ker,1,1,[]), 'same') -> convolve along depth (axis 2)
        return convolve1d(img.astype(float), ker.astype(float), axis=2, mode='reflect')
    else:
        # Default: axis=None or axis=2 (MATLAB default is axis 2 = cols)
        return convolve1d(img.astype(float), ker.astype(float), axis=1, mode='reflect')
