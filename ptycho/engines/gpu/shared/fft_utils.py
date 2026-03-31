"""
FFT utility functions for ptychography.

Provides safe FFT/iFFT operations that work on both CPU and GPU.
"""

import numpy as np
from ..gpu_wrapper import USE_GPU, GPU_AVAILABLE

if GPU_AVAILABLE:
    import cupy as cp


def fft2_safe(array):
    """
    Safe 2D FFT (works on CPU or GPU).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array (can be 2D or 3D with batch dimension)

    Returns
    -------
    ndarray or cupy.ndarray
        FFT result

    Notes
    -----
    Handles both 2D arrays [Nx, Ny] and 3D arrays [Nx, Ny, N_batch].
    For 3D, applies FFT to first two dimensions.
    """
    if USE_GPU and GPU_AVAILABLE:
        if isinstance(array, cp.ndarray):
            if array.ndim == 2:
                return cp.fft.fft2(array)
            elif array.ndim == 3:
                # Apply FFT to first two axes
                return cp.fft.fft2(array, axes=(0, 1))
            else:
                return cp.fft.fftn(array)
        else:
            # Convert to GPU first
            array_gpu = cp.asarray(array)
            if array.ndim == 2:
                return cp.fft.fft2(array_gpu)
            elif array.ndim == 3:
                return cp.fft.fft2(array_gpu, axes=(0, 1))
            else:
                return cp.fft.fftn(array_gpu)
    else:
        if array.ndim == 2:
            return np.fft.fft2(array)
        elif array.ndim == 3:
            return np.fft.fft2(array, axes=(0, 1))
        else:
            return np.fft.fftn(array)


def ifft2_safe(array):
    """
    Safe 2D inverse FFT (works on CPU or GPU).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array (can be 2D or 3D with batch dimension)

    Returns
    -------
    ndarray or cupy.ndarray
        Inverse FFT result

    Notes
    -----
    Handles both 2D arrays [Nx, Ny] and 3D arrays [Nx, Ny, N_batch].
    For 3D, applies iFFT to first two dimensions.
    """
    if USE_GPU and GPU_AVAILABLE:
        if isinstance(array, cp.ndarray):
            if array.ndim == 2:
                return cp.fft.ifft2(array)
            elif array.ndim == 3:
                return cp.fft.ifft2(array, axes=(0, 1))
            else:
                return cp.fft.ifftn(array)
        else:
            array_gpu = cp.asarray(array)
            if array.ndim == 2:
                return cp.fft.ifft2(array_gpu)
            elif array.ndim == 3:
                return cp.fft.ifft2(array_gpu, axes=(0, 1))
            else:
                return cp.fft.ifftn(array_gpu)
    else:
        if array.ndim == 2:
            return np.fft.ifft2(array)
        elif array.ndim == 3:
            return np.fft.ifft2(array, axes=(0, 1))
        else:
            return np.fft.ifftn(array)


def fftshift_2D(array):
    """
    2D FFT shift (works on CPU or GPU).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array

    Returns
    -------
    ndarray or cupy.ndarray
        Shifted array

    Notes
    -----
    Shifts zero-frequency component to center.
    For 3D arrays, shifts only first two dimensions.
    """
    if USE_GPU and GPU_AVAILABLE:
        if isinstance(array, cp.ndarray):
            if array.ndim == 2:
                return cp.fft.fftshift(array)
            elif array.ndim == 3:
                return cp.fft.fftshift(array, axes=(0, 1))
            else:
                return cp.fft.fftshift(array)
        else:
            array_gpu = cp.asarray(array)
            if array.ndim == 2:
                return cp.fft.fftshift(array_gpu)
            elif array.ndim == 3:
                return cp.fft.fftshift(array_gpu, axes=(0, 1))
            else:
                return cp.fft.fftshift(array_gpu)
    else:
        if array.ndim == 2:
            return np.fft.fftshift(array)
        elif array.ndim == 3:
            return np.fft.fftshift(array, axes=(0, 1))
        else:
            return np.fft.fftshift(array)


def ifftshift_2D(array):
    """
    2D inverse FFT shift (works on CPU or GPU).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array

    Returns
    -------
    ndarray or cupy.ndarray
        Shifted array
    """
    if USE_GPU and GPU_AVAILABLE:
        if isinstance(array, cp.ndarray):
            if array.ndim == 2:
                return cp.fft.ifftshift(array)
            elif array.ndim == 3:
                return cp.fft.ifftshift(array, axes=(0, 1))
            else:
                return cp.fft.ifftshift(array)
        else:
            array_gpu = cp.asarray(array)
            if array.ndim == 2:
                return cp.fft.ifftshift(array_gpu)
            elif array.ndim == 3:
                return cp.fft.ifftshift(array_gpu, axes=(0, 1))
            else:
                return cp.fft.ifftshift(array_gpu)
    else:
        if array.ndim == 2:
            return np.fft.ifftshift(array)
        elif array.ndim == 3:
            return np.fft.ifftshift(array, axes=(0, 1))
        else:
            return np.fft.ifftshift(array)
