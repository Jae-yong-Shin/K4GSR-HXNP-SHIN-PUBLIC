"""
Fourier propagation functions for ptychography.

Implements forward and backward Fourier propagation
with support for near-field (ASM), far-field, and corrections.
"""

import numpy as np
from .fft_utils import fft2_safe, ifft2_safe, fftshift_2D
from ..gpu_wrapper import USE_GPU, GPU_AVAILABLE

if GPU_AVAILABLE:
    import cupy as cp


def fwd_fourier_proj(psi, mode, ind=None):
    """
    Forward Fourier propagation to detector plane.

    Equivalent to MATLAB's fwd_fourier_proj().

    Parameters
    ----------
    psi : ndarray or cupy.ndarray
        [Nx, Ny, N] array, exit-wave in sample plane
    mode : dict
        Mode structure containing:
        - distances: propagation distance(s)
        - ASM_factor: Angular Spectrum Method factor (near-field)
        - FAR_factor: Far-field factor
        - probe_rotation_all: rotation angles (optional)
        - probe_scale_upd: scale updates (optional)
        - tilted_plane_propagate_back: tilted plane function (optional)
    ind : array-like, optional
        Indices for position-dependent operations

    Returns
    -------
    Psi : ndarray or cupy.ndarray
        [Nx, Ny, N] array, propagated to detector plane

    Notes
    -----
    Propagation modes:
    - distance == 0: No propagation
    - distance == inf: Far-field (FFT only)
    - distance == -inf: Far-field backward
    - ASM_factor exists: Near-field Angular Spectrum Method
    - FAR_factor exists: Almost far-field
    """
    Psi = psi  # Work with copy (or reference)

    try:
        # Tilted plane correction (if provided)
        if mode.get('tilted_plane_propagate_back') is not None:
            Psi = mode['tilted_plane_propagate_back'](Psi)

        # Rotation correction (if provided)
        if ind is not None and mode.get('probe_rotation_all') is not None:
            if np.any(mode['probe_rotation_all']):
                # TODO: Implement imrotate_ax_fft
                # Psi = imrotate_ax_fft(Psi, -mode['probe_rotation_all'][ind], 3)
                pass

        # Scale correction (if provided)
        if mode.get('probe_scale_upd') is not None:
            if len(mode['probe_scale_upd']) > 0 and mode['probe_scale_upd'][-1] != 0:
                # TODO: Implement imrescale_frft
                # Psi = imrescale_frft(Psi, 1 + mode['probe_scale_upd'][-1])
                pass

        # Propagation
        distance = mode.get('distances', [0])[-1]

        if distance == 0:
            # No propagation
            pass

        elif distance == np.inf:
            # Far-field (fully)
            Psi = fft2_safe(Psi)

        elif distance == -np.inf:
            # Far-field backward
            Psi = ifft2_safe(Psi)

        elif mode.get('FAR_factor') is not None:
            # Almost far-field
            Psi = Psi * mode['FAR_factor']
            Psi = fftshift_2D(fft2_safe(fftshift_2D(Psi)))

        elif mode.get('ASM_factor') is not None:
            # Near-field (Angular Spectrum Method)
            Psi = fft2_safe(Psi)
            Psi = Psi * mode['ASM_factor']
            Psi = ifft2_safe(Psi)

        else:
            raise NotImplementedError(
                f"Propagation mode not implemented for distance={distance}"
            )

    except Exception as err:
        raise RuntimeError(f"Error in fwd_fourier_proj: {err}")

    return Psi


def back_fourier_proj(Psi, mode, ind=None):
    """
    Backward Fourier propagation to sample plane.

    Equivalent to MATLAB's back_fourier_proj().

    Parameters
    ----------
    Psi : ndarray or cupy.ndarray
        [Nx, Ny, N] array, wavefront in detector plane
    mode : dict
        Mode structure (same as fwd_fourier_proj)
    ind : array-like, optional
        Indices for position-dependent operations

    Returns
    -------
    psi : ndarray or cupy.ndarray
        [Nx, Ny, N] array, back-propagated to sample plane

    Notes
    -----
    Performs inverse of fwd_fourier_proj().
    Order of operations is reversed.
    """
    psi = Psi  # Work with copy (or reference)

    try:
        # Propagation (inverse order)
        distance = mode.get('distances', [0])[-1]

        if distance == 0:
            # No propagation
            pass

        elif distance == np.inf:
            # Far-field backward
            psi = ifft2_safe(psi)

        elif distance == -np.inf:
            # Far-field forward
            psi = fft2_safe(psi)

        elif mode.get('FAR_factor') is not None:
            # Almost far-field (inverse)
            psi = fftshift_2D(ifft2_safe(fftshift_2D(psi)))
            psi = psi * np.conj(mode['FAR_factor'])

        elif mode.get('ASM_factor') is not None:
            # Near-field ASM (inverse)
            psi = fft2_safe(psi)
            psi = psi * np.conj(mode['ASM_factor'])
            psi = ifft2_safe(psi)

        else:
            raise NotImplementedError(
                f"Propagation mode not implemented for distance={distance}"
            )

        # Scale correction (inverse, if provided)
        if mode.get('probe_scale_upd') is not None:
            if len(mode['probe_scale_upd']) > 0 and mode['probe_scale_upd'][-1] != 0:
                # TODO: Implement imrescale_frft (inverse)
                # psi = imrescale_frft(psi, 1 / (1 + mode['probe_scale_upd'][-1]))
                pass

        # Rotation correction (inverse, if provided)
        if ind is not None and mode.get('probe_rotation_all') is not None:
            if np.any(mode['probe_rotation_all']):
                # TODO: Implement imrotate_ax_fft (inverse)
                # psi = imrotate_ax_fft(psi, mode['probe_rotation_all'][ind], 3)
                pass

        # Tilted plane correction (inverse, if provided)
        if mode.get('tilted_plane_propagate') is not None:
            psi = mode['tilted_plane_propagate'](psi)

    except Exception as err:
        raise RuntimeError(f"Error in back_fourier_proj: {err}")

    return psi
