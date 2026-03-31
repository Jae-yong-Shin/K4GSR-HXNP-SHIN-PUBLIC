"""
gradient_ptycho.py - Main code to compute error metric and gradient

Python port of engines.ML.gradient_ptycho from cSAXS Ptychoshelves package

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np
import sys
from pathlib import Path

try:
    import cupy as cp
    def get_xp(arr):
        return cp.get_array_module(arr)
except ImportError:
    cp = None
    def get_xp(arr):
        return np

# Import core functions
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'core'))
from get_projections import get_projections
from set_projections import set_projections
from errorplot import errorplot

# Import utils
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'utils'))
from verbose import verbose


def gradient_ptycho(xopt, p, fmag2, initialerror, fnorm, creg, smooth_gradient):
    """
    Main code to compute error metric and gradient

    MATLAB equivalent: engines.ML.gradient_ptycho

    Args:
        xopt: optimization vector (real and imaginary parts concatenated)
        p: parameter dict
        fmag2: squared magnitude of Fourier data (for Poisson)
        initialerror: initial error offset
        fnorm: normalization factor (sqrt(prod(asize)))
        creg: regularization coefficient
        smooth_gradient: smoothing kernel for gradient preconditioning

    Returns:
        func: objective function value
        grad: gradient vector (same size as xopt)
        p: updated parameter dict (with updated object and probes)
    """

    ### Initialize variables ###
    func = 0  # Should be zero except for poisson (factorial factor)
    _opt_flags = p.get('opt_flags', [1, 1])

    # Determine array module from p['probes'] or p['object'] (may be GPU arrays)
    if _opt_flags[1] == 1 and p.get('probes') is not None:
        xp = get_xp(p['probes'])
    elif _opt_flags[0] == 1 and len(p.get('object', [])) > 0:
        xp = get_xp(p['object'][0])
    else:
        xp = np

    # Initialize gradient arrays on the appropriate device
    grado = {}
    for ii in range(p['numobjs']):
        grado[ii] = xp.zeros(tuple(p['object_size'][ii, :]) + (p['object_modes'],),
                             dtype=complex)

    gradp = xp.zeros((p['asize'][0], p['asize'][1], p['numprobs'], p['probe_modes']),
                     dtype=complex)

    ######################################
    ### Arrange optimization variables ###
    ######################################
    ob = {}
    xopt_remaining = xopt.copy()  # xopt is always CPU numpy (CG optimizer)

    if _opt_flags[0] == 1:
        for obnum in range(p['numobjs']):
            numel_ob = int(np.prod(grado[obnum].shape))
            # Build complex object on CPU then move to GPU if needed
            ob_cpu = (xopt_remaining[:numel_ob].reshape(grado[obnum].shape) +
                      1j * xopt_remaining[numel_ob:2*numel_ob].reshape(grado[obnum].shape))
            ob[obnum] = xp.asarray(ob_cpu) if xp is not np else ob_cpu
            xopt_remaining = xopt_remaining[2*numel_ob:]

    if _opt_flags[1] == 1:
        numel_pr = int(np.prod(gradp.shape))
        # Build complex probes on CPU then move to GPU if needed
        probes_cpu = (xopt_remaining[:numel_pr].reshape(gradp.shape) +
                      1j * xopt_remaining[numel_pr:2*numel_pr].reshape(gradp.shape))
        probes = xp.asarray(probes_cpu) if xp is not np else probes_cpu
    else:
        probes = p['probes']

    ############################
    ### Compute error metric ###
    ############################
    verbose(3, 'Computing gradient')

    # Main loop over scans
    for ii in range(p['numscans']):
        prnum = int(p['share_probe_ID'][ii]) - 1  # MATLAB 1-based → Python 0-based
        obnum = int(p['share_object_ID'][ii])
        # For multimode: probe_all is (H, W, probe_modes); single-mode: squeeze to (H, W)
        probe_all_raw = probes[:, :, prnum, :]  # (H, W, probe_modes)
        if probe_all_raw.ndim == 3 and probe_all_raw.shape[2] > 1:
            probe_all = probe_all_raw   # (H, W, probe_modes) — multimode
        else:
            probe_all = probe_all_raw.squeeze()[:, :, np.newaxis]  # (H, W, 1) — single mode
        n_probe_modes = probe_all.shape[2]

        Iq_all = 0
        psiq_all = {}  # key: (obmode, prmode)
        obj_proj = {}

        for obmode in range(p['object_modes']):
            obj_proj[obmode] = get_projections(p, ob[obnum][:, :, obmode], ii + 1)  # MATLAB 1-based
            # Ensure obj_proj is 3D: (H, W, N_pos)
            obj_p_raw = obj_proj[obmode]
            obj_p = obj_p_raw[:, :, :, 0] if obj_p_raw.ndim == 4 else obj_p_raw  # (H, W, N_pos)
            for prmode in range(n_probe_modes):
                probe_m = probe_all[:, :, prmode]  # (H, W) — no fnorm (DM-consistent)
                psiq_all[(obmode, prmode)] = xp.fft.fft2(
                    obj_p * probe_m[:, :, None], axes=(0, 1))  # (H, W, N_pos)
                Iq_all = Iq_all + xp.abs(psiq_all[(obmode, prmode)])**2

        # Error metric computation
        # Currently implementing only Poisson (most commonly used)
        opt_errmetric = p.get('opt_errmetric', 'poisson').lower()

        if opt_errmetric == 'poisson':
            for jj_matlab in p['scanidxs'][ii]:  # Loop through diffraction patterns (MATLAB 1-based)
                jj = jj_matlab - 1  # Convert to Python 0-based
                jj_idx = jj_matlab - p['scanidxs'][ii][0]  # Index in Iq_all

                Iq = Iq_all[:, :, jj_idx]

                # fmask and fmag2 are CPU arrays; move slice to GPU if needed
                fmask_jj = xp.asarray(p['fmask'][:, :, jj]) if xp is not np else p['fmask'][:, :, jj]
                fmag2_jj = xp.asarray(fmag2[:, :, jj]) if xp is not np else fmag2[:, :, jj]

                # Invariant to intensity fluctuations
                if p.get('inv_intensity', False):
                    alpha = float(xp.sum(fmask_jj * fmag2_jj) / xp.sum(fmask_jj * Iq))
                else:
                    alpha = 1.0

                func = func - float(xp.sum(fmask_jj *
                                     (fmag2_jj * xp.log(alpha * Iq + np.finfo(float).eps) -
                                      alpha * Iq)))

                # Compute gradients
                Indy = slice(round(p['positions'][jj_matlab-1, 0]),  # positions is 0-based in Python
                            round(p['positions'][jj_matlab-1, 0]) + p['asize'][0])
                Indx = slice(round(p['positions'][jj_matlab-1, 1]),
                            round(p['positions'][jj_matlab-1, 1]) + p['asize'][1])

                for obmode in range(p['object_modes']):
                    for prmode in range(n_probe_modes):
                        # psiq_all[(obmode,prmode)] is (H, W, N_pos); select position jj_idx
                        psiq = psiq_all[(obmode, prmode)][:, :, jj_idx]  # (H, W)

                        # chir = IFFT(fmask * (alpha - I0/I) * psiq)
                        chir = xp.fft.ifft2(fmask_jj *
                                           (alpha - fmag2_jj / (Iq + np.finfo(float).eps)) *
                                           psiq)  # (H, W) — no fnorm (DM-consistent)

                        probe_m = probe_all[:, :, prmode]  # (H, W)

                        if _opt_flags[0] == 1:
                            grado[obnum][Indy, Indx, obmode] = grado[obnum][Indy, Indx, obmode] + \
                                2 * xp.conj(probe_m) * chir

                        if _opt_flags[1] == 1:
                            gradp[:, :, prnum, prmode] = gradp[:, :, prnum, prmode] + \
                                2 * xp.conj(ob[obnum][Indy, Indx, obmode]) * chir

    func = func + initialerror

    ##############################
    ### Sieves preconditioning ###
    ##############################
    if np.any(smooth_gradient != 0) and _opt_flags[0]:
        from scipy.signal import convolve2d
        for obnum in range(p['numobjs']):
            for obmode in range(p['object_modes']):
                # convolve2d requires CPU arrays; gather if on GPU
                grado_slice = grado[obnum][:, :, obmode]
                if xp is not np:
                    grado_slice_cpu = np.asarray(grado_slice.get())
                    grado_slice_cpu = convolve2d(grado_slice_cpu, smooth_gradient, mode='same')
                    grado[obnum][:, :, obmode] = xp.asarray(grado_slice_cpu)
                else:
                    grado[obnum][:, :, obmode] = convolve2d(grado_slice, smooth_gradient, mode='same')

    #############################
    ### Object regularization ###
    #############################
    if (creg > 0) and _opt_flags[0]:
        for obnum in range(p['numobjs']):
            for obmode in range(p['object_modes']):
                # Compute regularization term
                R = xp.sum(xp.abs(ob[obnum][1:, :-1, obmode] - ob[obnum][:-1, :-1, obmode])**2) + \
                    xp.sum(xp.abs(ob[obnum][:-1, 1:, obmode] - ob[obnum][:-1, :-1, obmode])**2)
                norm_r = xp.sum(xp.abs(ob[obnum][:, :, obmode])**2)
                func = func + float(creg * R / norm_r)

                # Gradient contribution
                grado[obnum][1:-1, 1:-1, obmode] = grado[obnum][1:-1, 1:-1, obmode] + \
                    creg * ((8 + 2*R/norm_r) * ob[obnum][1:-1, 1:-1, obmode] -
                           2 * ob[obnum][:-2, 1:-1, obmode] - 2 * ob[obnum][2:, 1:-1, obmode] -
                           2 * ob[obnum][1:-1, :-2, obmode] - 2 * ob[obnum][1:-1, 2:, obmode])

    # Normalized error, err_chi close to 1 is good result for poisson noise
    err_chi = 2 * np.sqrt(float(func) / np.prod(p['asize']) / p['numpos'] / p['renorm']**2)

    func = float(func)

    # Update errorplot and print progress
    errorplot(err_chi)
    iteration = len(errorplot([]))
    verbose(2, 'Iteration # %d of %d', iteration, p.get('opt_iter', 0))
    verbose(3, 'Starting linesearch, Error = %f', err_chi)

    #################################
    ### Probe support constraint ####
    #################################
    if p.get('use_probe_support', False) and _opt_flags[1]:
        probe_mask_arr = xp.asarray(p['probe_mask']) if xp is not np else p['probe_mask']
        gradp = gradp * probe_mask_arr[:, :, None, None]

    ###############################
    ### Scaling preconditioning ###
    ###############################
    avobint = 0
    if p.get('scale_gradient', False) and _opt_flags[1]:
        for ii in range(p['numscans']):
            if p.get('share_probe', False):
                avobint = avobint + float(xp.sum(xp.abs(grado[ii].flatten())**2))
                if ii == p['numscans'] - 1:
                    avobint = avobint / p['numscans']
                    gradp = xp.sqrt(avobint / xp.sum(xp.abs(gradp.flatten())**2)) * gradp
            else:
                scale = xp.sqrt(xp.sum(xp.abs(grado[ii].flatten())**2) /
                               xp.sum(xp.abs(gradp[:, :, ii, :].flatten())**2))
                gradp[:, :, ii, :] = scale * gradp[:, :, ii, :]

    ##################################
    ### Arranging gradients vector ###
    ##################################
    # Gradients must be returned as CPU numpy arrays (CG optimizer requirement)
    grad = []  # Optimization vector
    if _opt_flags[0] == 1:
        for obnum in range(p['numobjs']):
            grado_flat = grado[obnum].flatten()
            if xp is not np:
                grado_flat = np.asarray(grado_flat.get())
            grad.append(np.real(grado_flat))
            grad.append(np.imag(grado_flat))
    if _opt_flags[1] == 1:
        gradp_flat = gradp.flatten()
        if xp is not np:
            gradp_flat = np.asarray(gradp_flat.get())
        grad.append(np.real(gradp_flat))
        grad.append(np.imag(gradp_flat))

    if len(grad) == 0:
        raise ValueError('At least one element of opt_flags must be 1')

    grad = np.concatenate(grad)

    # Update p with current reconstructions (keep on GPU if GPU mode)
    p['object'] = [ob[i] for i in range(p['numobjs'])]
    p['probes'] = probes

    # Update error metric in p
    p['error_metric'] = {
        'value': errorplot([]),
        'iteration': np.arange(1, len(errorplot([])) + 1),
        'err_metric': '-LogLik',
        'method': 'ML'
    }

    return func, grad, p


# Note: Full testing requires integration with ML.py and actual ptychography data
# Module-level tests will be performed in compare_matlab_ml_exact.py
if __name__ == "__main__":
    print("gradient_ptycho.py - Module loaded successfully")
    print("Full testing will be performed in integration tests")
