"""imfilter_high_pass_1d.py

Port of MATLAB imfilter_high_pass_1d.m (line-by-line).

MATLAB:
    function img = imfilter_high_pass_1d(img, ax, sigma, padding, apply_fft)
        if nargin < 4, padding = 0; end
        if nargin < 5, apply_fft = true; end
        Ndims = ndims(img);
        padding = ceil(padding);
        if padding > 0
            pad_vec = zeros(Ndims,1); pad_vec(ax) = padding;
            img = padarray(img, pad_vec, 'symmetric', 'both');
        end
        Npix = size(img);
        shape = ones(1,Ndims); shape(ax) = Npix(ax);
        isReal = isreal(img);
        if apply_fft; img = fft(img,[],ax); end
        x = reshape((-Npix(ax)/2:Npix(ax)/2-1)/Npix(ax), shape);
        sigma = 256/(Npix(ax)-2*padding)*sigma;
        if sigma == 0
            spectral_filter = 2i*pi*(fftshift((0:Npix(ax)-1)/Npix(ax))-0.5);
        else
            spectral_filter = fftshift(exp(1./(-(x.^2)/(sigma)^2)));
        end
        img = bsxfun(@times, img, spectral_filter);
        if apply_fft; img = ifft(img,[],ax); end
        if isReal; img = real(img); end
        if padding > 0
            % crop back to original size
            s = [slice(None)] * Ndims
            s[ax-1] = slice(padding, Npix[ax-1] - padding)
            img = img[tuple(s)]
        end
    end

Notes:
- Padding is added along `ax` symmetrically, so Npix(ax) increases by 2*padding.
- spectral_filter for sigma>0: exp(1/(-(x^2)/sigma^2)) = exp(-sigma^2/x^2)
  This is a high-pass filter: near x=0 → 0, large |x| → 1.
- sigma is rescaled: sigma_eff = 256 / (Npix_ax - 2*padding) * sigma_input
  (this normalises sigma relative to the un-padded size)
- x = (-N/2 : N/2-1) / N  (centred frequency grid, NOT fftshifted)
  spectral_filter = fftshift(f(x))  → puts DC at centre then fftshifts back to FFT order
- For 2D img (Nlayers, Nangles) with ax=1 (rows):
    filter shape = (Npix_ax, 1) for broadcasting
"""

import numpy as np


def imfilter_high_pass_1d(img, ax, sigma, padding=0, apply_fft=True):
    """1-D high-pass spectral filter along axis `ax` (MATLAB 1-based).

    Parameters
    ----------
    img       : ndarray (real or complex)
    ax        : int, MATLAB 1-based axis
    sigma     : float, filter width (0 = pure derivative filter)
    padding   : int, symmetric padding along ax before filtering (default 0)
    apply_fft : bool, apply FFT/IFFT around the multiplication (default True)

    Returns
    -------
    img : filtered ndarray (same shape as input)
    """
    # Ndims = ndims(img)
    Ndims = img.ndim
    ax0   = ax - 1          # Python 0-based axis

    # padding = ceil(padding)
    padding = int(np.ceil(padding))

    # if padding > 0 → pad symmetrically along ax
    if padding > 0:
        pad_config = [[0, 0]] * Ndims
        pad_config[ax0] = [padding, padding]
        img = np.pad(img, pad_config, mode='symmetric')

    # Npix = size(img)
    Npix = img.shape
    N    = Npix[ax0]

    # shape = ones(1, Ndims); shape(ax) = N
    shape = [1] * Ndims
    shape[ax0] = N

    # isReal = isreal(img)
    is_real = np.isrealobj(img)

    # if apply_fft; img = fft(img, [], ax); end
    if apply_fft:
        img = np.fft.fft(img, axis=ax0)

    # x = reshape((-N/2 : N/2-1) / N, shape)
    x_vec = np.arange(-N / 2, N / 2) / N    # length N, centred frequency grid
    x     = x_vec.reshape(shape)             # broadcastable

    # sigma = 256 / (N - 2*padding) * sigma_input
    orig_N  = N - 2 * padding if padding > 0 else N
    sigma_eff = 256.0 / orig_N * sigma

    # spectral_filter
    if sigma_eff == 0:
        # spectral_filter = 2i*pi*(fftshift((0:N-1)/N) - 0.5)
        freq = np.fft.fftshift(np.arange(N) / N) - 0.5
        spectral_filter = (2j * np.pi * freq).reshape(shape)
    else:
        # spectral_filter = fftshift(exp(1 / (-(x^2) / sigma^2)))
        with np.errstate(divide='ignore', invalid='ignore'):
            exponent = np.where(x_vec == 0,
                                -np.inf,
                                1.0 / (-(x_vec ** 2) / (sigma_eff ** 2)))
        f = np.exp(exponent)
        # fftshift → rearrange so DC is in centre, then apply
        f_shift = np.fft.fftshift(f)
        spectral_filter = f_shift.reshape(shape)

    # img = bsxfun(@times, img, spectral_filter)
    img = img * spectral_filter

    # if apply_fft; img = ifft(img, [], ax); end
    if apply_fft:
        img = np.fft.ifft(img, axis=ax0)

    # if isReal; img = real(img); end
    if is_real:
        img = np.real(img)

    # if padding > 0 → crop back to original size
    if padding > 0:
        slices = [slice(None)] * Ndims
        slices[ax0] = slice(padding, N - padding)
        img = img[tuple(slices)]

    return img
