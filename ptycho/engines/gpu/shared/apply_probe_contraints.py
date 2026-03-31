"""
Probe support constraints for ptychography reconstruction.

Line-by-line port of MATLAB +engines/+GPU/+shared/apply_probe_contraints.m
from cSAXS PtychoShelves.

Applies support constraints on the probe in real space, Fourier space,
or any other plane via ASM propagation factors.

Note: function name preserves MATLAB's original spelling ("contraints").
"""

import numpy as np

try:
    import cupy as cp
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False


def _get_xp(arr):
    """Return numpy or cupy module based on array type."""
    if GPU_AVAILABLE and isinstance(arr, cp.ndarray):
        return cp
    return np


def apply_probe_contraints(probe, mode):
    """
    Apply support constraints on probe in real and Fourier space.

    Port of MATLAB apply_probe_contraints.m (L78-135).

    Parameters
    ----------
    probe : ndarray or cupy.ndarray (Ny, Nx) or (Ny, Nx, N)
        Complex probe array.
    mode : dict
        Mode structure containing:
        - probe_support : ndarray or None
            Real-space support mask (binary). None = skip.
        - support_fwd_propagation_factor : ndarray, scalar, or None
            Forward propagation factor. inf = far-field FFT.
        - support_back_propagation_factor : ndarray, scalar, or None
            Back propagation factor. inf = far-field iFFT.
        - probe_support_fft : ndarray or None
            Fourier-space support mask. None = skip.
        - probe_scale_upd : list/array
            Scale update values. Last element checked for != 0.
        - probe_scale_window : ndarray or None
            Windowing for subpixel rescaling.
        - distances : list
            Propagation distances ([inf] for far-field).

    Returns
    -------
    probe : ndarray or cupy.ndarray
        Constrained probe.
    """
    from .fft_utils import fft2_safe, ifft2_safe, fftshift_2D
    from .fourier_proj import fwd_fourier_proj, back_fourier_proj

    xp = _get_xp(probe)

    # ---- Real-space support constraint ---- apply_probe_contraints.m L83-104
    probe_support = mode.get('probe_support', None)
    if probe_support is not None:
        # Optional forward propagation before applying support — L85-91
        support_fwd = mode.get('support_fwd_propagation_factor', None)
        if support_fwd is not None:
            if xp.isscalar(support_fwd) and xp.isinf(support_fwd):
                # Propagate to infinity — L87
                probe = fftshift_2D(fft2_safe(fftshift_2D(probe)))
            else:
                # ASM propagation — L89
                probe = ifft2_safe(fft2_safe(probe) * support_fwd)

        # Apply real-space support — L94
        if isinstance(probe_support, (int, float)):
            probe = probe * probe_support
        else:
            if GPU_AVAILABLE and isinstance(probe, cp.ndarray):
                if not isinstance(probe_support, cp.ndarray):
                    probe_support = cp.asarray(probe_support)
            # Broadcast: support (Ny,Nx) with probe (Ny,Nx) or (Ny,Nx,N)
            if probe_support.ndim == 2 and probe.ndim == 3:
                probe = probe * probe_support[:, :, None]
            else:
                probe = probe * probe_support

        # Optional back propagation after applying support — L96-102
        support_back = mode.get('support_back_propagation_factor', None)
        if support_back is not None:
            if xp.isscalar(support_back) and xp.isinf(support_back):
                # Propagate back from infinity — L98
                probe = fftshift_2D(ifft2_safe(fftshift_2D(probe)))
            else:
                # ASM back propagation — L100
                probe = ifft2_safe(fft2_safe(probe) * support_back)

    # ---- Probe scale window (before Fourier constraint) ---- L108-112
    probe_scale_upd = mode.get('probe_scale_upd', [0])
    probe_scale_window = mode.get('probe_scale_window', None)

    if probe_scale_upd[-1] > 0 and probe_scale_window is not None:
        # Apply windowing for subpixel rescaling — L111
        if GPU_AVAILABLE and isinstance(probe, cp.ndarray):
            if not isinstance(probe_scale_window, cp.ndarray):
                probe_scale_window = cp.asarray(probe_scale_window)
        probe = probe * probe_scale_window

    # ---- Fourier-space constraint ---- L113-134
    probe_support_fft = mode.get('probe_support_fft', None)

    if probe_support_fft is not None or probe_scale_upd[-1] != 0:
        # Propagate probe to detector plane — L117
        probe = fwd_fourier_proj(probe, mode)

        # Apply Fourier support — L120-127
        if probe_support_fft is not None:
            if GPU_AVAILABLE and isinstance(probe, cp.ndarray):
                if not isinstance(probe_support_fft, cp.ndarray):
                    probe_support_fft = cp.asarray(probe_support_fft)

            probe_support_fft_shifted = mode.get(
                'probe_support_fft_shifted', None
            )
            if probe_support_fft_shifted is None:
                # Simple Fourier mask — L122
                if probe_support_fft.ndim == 2 and probe.ndim == 3:
                    probe = probe * probe_support_fft[:, :, None]
                else:
                    probe = probe * probe_support_fft
            else:
                # Relaxed Fourier constraint — L124-125
                if GPU_AVAILABLE and isinstance(probe, cp.ndarray):
                    if not isinstance(probe_support_fft_shifted, cp.ndarray):
                        probe_support_fft_shifted = cp.asarray(
                            probe_support_fft_shifted
                        )
                relax = mode.get('probe_support_fft_relax', 0.0)
                not_fft = 1 - probe_support_fft_shifted
                not_fft_plain = 1 - probe_support_fft
                energy_shifted = xp.sum(xp.abs(probe * not_fft) ** 2)
                energy_plain = xp.sum(xp.abs(probe * not_fft_plain) ** 2)
                corFac = xp.sqrt(energy_shifted / (energy_plain + 1e-30))
                probe = (probe * probe_support_fft
                         + probe * not_fft_plain * (1 + relax * (corFac - 1)))

        # Scale window after Fourier constraint — L128-130
        if probe_scale_upd[-1] < 0 and probe_scale_window is not None:
            if GPU_AVAILABLE and isinstance(probe, cp.ndarray):
                if not isinstance(probe_scale_window, cp.ndarray):
                    probe_scale_window = cp.asarray(probe_scale_window)
            probe = probe * probe_scale_window

        # Propagate probe back to sample plane — L133
        probe = back_fourier_proj(probe, mode)

    return probe
