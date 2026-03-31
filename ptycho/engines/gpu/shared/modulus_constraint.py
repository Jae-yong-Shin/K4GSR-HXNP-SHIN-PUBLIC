"""
Modulus constraint for ptychography reconstruction.

Implements relaxed modulus constraint for DM and ML engines.
Based on MATLAB +engines/+GPU/private/modulus_constraint.m
"""

import numpy as np
from ..gpu_wrapper import Gfun, USE_GPU, GPU_AVAILABLE

if GPU_AVAILABLE:
    import cupy as cp


def modulus_constraint(modF, aPsi, Psi, mask=None, relaxation=0.05):
    """
    Apply relaxed modulus constraint.

    Parameters
    ----------
    modF : ndarray
        Measured Fourier magnitude (sqrt of intensity)
    aPsi : ndarray
        Calculated Fourier magnitude
    Psi : list of ndarrays
        Fourier-transformed exit waves for each mode
    mask : ndarray, optional
        Binary mask (1 = ignore, 0 = use), shape [Ny, Nx]
    relaxation : float
        Relaxation parameter (default 0.05)

    Returns
    -------
    Psi_constrained : list of ndarrays
        Updated Fourier exit waves

    Notes
    -----
    Constraint: Psi' = Psi * (W + (1-W) * modF / aPsi)
    where W is the relaxation weight (mask or constant)

    For DM: relaxation controls how strongly to enforce the constraint.
    - W = 0: full constraint (Psi' = Psi * modF / aPsi)
    - W = 1: no constraint (Psi' = Psi)
    - W = 0.05: 95% constraint, 5% relaxation
    """
    Nmodes = len(Psi)

    # Determine weight W
    if mask is None:
        # Uniform relaxation
        W = relaxation
    else:
        # Combine mask with relaxation
        # mask: 1 = ignore (W=1), 0 = use (W=relaxation)
        if USE_GPU and GPU_AVAILABLE:
            xp = cp
        else:
            xp = np

        if isinstance(mask, (int, float)):
            W = mask
        else:
            W = xp.maximum(mask, relaxation)

    # Calculate modulus ratio R = modF / aPsi
    # R = (W + (1-W) * modF / aPsi)
    if USE_GPU and GPU_AVAILABLE:
        R = Gfun(_modulus_ratio_kernel, modF, aPsi, W)
    else:
        R = _modulus_ratio_cpu(modF, aPsi, W)

    # Apply to all modes
    Psi_constrained = []
    for i in range(Nmodes):
        Psi_constrained.append(Psi[i] * R)

    return Psi_constrained


def _modulus_ratio_kernel(modF, aPsi, W):
    """GPU kernel for modulus ratio calculation."""
    if isinstance(W, (int, float)):
        # Scalar relaxation
        R = W + (1.0 - W) * modF / (aPsi + 1e-9)
    else:
        # Array relaxation
        R = W + (1.0 - W) * modF / (aPsi + 1e-9)
    return R


def _modulus_ratio_cpu(modF, aPsi, W):
    """CPU version of modulus ratio calculation."""
    if isinstance(W, (int, float)):
        R = W + (1.0 - W) * modF / (aPsi + 1e-9)
    else:
        R = W + (1.0 - W) * modF / (aPsi + 1e-9)
    return R


def get_reciprocal_model(Psi):
    """
    Calculate reciprocal amplitude model from exit wave(s).

    For single mode: aPsi = |Psi|
    For multiple modes: aPsi = sqrt(sum_i |Psi_i|^2)

    Parameters
    ----------
    Psi : list of ndarrays
        Fourier-transformed exit waves

    Returns
    -------
    aPsi : ndarray
        Reciprocal amplitude model
    """
    if len(Psi) == 1:
        # Single mode: simple absolute value
        if USE_GPU and GPU_AVAILABLE:
            aPsi = cp.abs(Psi[0])
        else:
            aPsi = np.abs(Psi[0])
    else:
        # Multiple modes: incoherent sum
        if USE_GPU and GPU_AVAILABLE:
            xp = cp
        else:
            xp = np

        aPsi2 = xp.zeros_like(Psi[0], dtype=np.float32)
        for psi in Psi:
            aPsi2 += xp.abs(psi)**2
        aPsi = xp.sqrt(aPsi2)

    return aPsi
