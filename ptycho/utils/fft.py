"""
fft.py - Unitary 2D FFT functions for ptychography engines.

Convention: F(k) = (1/sqrt(N)) * sum_n x(n) * exp(-i*2*pi*k*n/N)

This is the "ortho" (unitary) normalization where Parseval's theorem gives:
    sum(|F(k)|^2) = sum(|x(n)|^2)

All ptychography engines should use these functions to ensure consistent
normalization between forward model, modulus constraint, and probe scaling.

PtychoShelves equivalent: fft2(x)/fnorm and fnorm*ifft2(x) where fnorm = sqrt(prod(asize)).
"""

import numpy as np

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    cp = None
    HAS_CUPY = False


def _get_xp(x):
    """Get array module (numpy or cupy) for the given array."""
    if HAS_CUPY:
        return cp.get_array_module(x)
    return np


def fft2(x, axes=(0, 1)):
    """Unitary 2D FFT.

    Equivalent to np.fft.fft2(x) / sqrt(N) where N = product of transform dimensions.
    Uses norm='ortho' for exact unitary normalization.

    Parameters
    ----------
    x : ndarray (numpy or cupy)
        Input array. The FFT is computed over the first two axes by default.
    axes : tuple of int
        Axes over which to compute the FFT. Default (0, 1).

    Returns
    -------
    ndarray : Unitary FFT of x.
    """
    xp = _get_xp(x)
    return xp.fft.fft2(x, axes=axes, norm='ortho')


def ifft2(x, axes=(0, 1)):
    """Unitary 2D inverse FFT.

    Equivalent to sqrt(N) * np.fft.ifft2(x).
    Uses norm='ortho' for exact unitary normalization.

    Parameters
    ----------
    x : ndarray (numpy or cupy)
        Input array in Fourier space.
    axes : tuple of int
        Axes over which to compute the IFFT. Default (0, 1).

    Returns
    -------
    ndarray : Unitary IFFT of x.
    """
    xp = _get_xp(x)
    return xp.fft.ifft2(x, axes=axes, norm='ortho')
