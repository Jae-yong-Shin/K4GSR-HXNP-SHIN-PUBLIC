"""
ML.py - Maximum Likelihood refinement

Python port of engines.ML from cSAXS Ptychoshelves package

Publications most relevant to the Maximum Likelihood refinement:
    + M. Guizar-Sicairos and J. R. Fienup, "Phase retrieval with transverse
      translation diversity: a nonlinear optimization approach," Opt. Express 16, 7264-7278 (2008)
    + P. Thibault and M. Guizar-Sicairos, "Maximum-likelihood refinement for
      coherent diffractive imaging," New J. Phys. 14, 063004 (2012).

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np
import time
import sys
from pathlib import Path

# Import GPU wrapper
sys.path.insert(0, str(Path(__file__).parent / 'gpu'))
try:
    from gpu_wrapper import Garray, Ggather, set_use_gpu, GPU_AVAILABLE
except ImportError:
    GPU_AVAILABLE = False
    def Garray(x): return x
    def Ggather(x): return x
    def set_use_gpu(x): pass

# Import ML functions
sys.path.insert(0, str(Path(__file__).parent / 'ml'))
from cgmin1 import cgmin1
from gradient_ptycho import gradient_ptycho

# Import core functions
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))
from errorplot import errorplot

# Import utils
sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))
from verbose import verbose


# Global variable for timing (matching MATLAB)
_opt_time = 0


def ML(p):
    """
    Maximum Likelihood refinement

    MATLAB equivalent: engines.ML

    Args:
        p: parameter dict containing all reconstruction parameters

    Returns:
        p: updated parameter dict with reconstructed object and probes
        fdb: feedback dict with status and error information
    """
    global _opt_time

    # Initialize feedback dict
    fdb = {'status': 0}  # core.engine_status equivalent

    # GPU support
    use_gpu = p.get('use_gpu', False)
    if use_gpu:
        set_use_gpu(True)
        # Move object and probe arrays to GPU for gradient computation
        p['object'] = [Garray(o) for o in p['object']]
        p['probes'] = Garray(p['probes'])

    # Clear errorplot
    errorplot()

    _opt_time = 0
    verbose(3, 'Starting non-linear optimization')

    # Probe mask generation
    if p.get('probe_mask_bool', False):
        if p.get('probe_mask_use_auto', False):
            verbose(3, 'Using a probe mask from probe autocorrelation.')
            # Auto-correlation method (not implemented yet)
            raise NotImplementedError('Probe mask from autocorrelation not implemented')
        else:
            verbose(3, 'Using a circular probe mask.')
            x, y = np.meshgrid(
                np.arange(-p['asize'][1]//2, np.floor((p['asize'][1]-1)/2) + 1),
                np.arange(-p['asize'][0]//2, np.floor((p['asize'][0]-1)/2) + 1)
            )
            to_threshold = x**2 + y**2

        to_threshold_flat = to_threshold.flatten()
        ind = np.argsort(to_threshold_flat)
        probe_mask_flat = np.zeros(np.prod(p['asize']))
        probe_mask_flat[ind[:int(np.ceil(p.get('probe_mask_area', 0.9) * np.prod(p['asize'])))]] = 1
        p['probe_mask'] = probe_mask_flat.reshape(p['asize'])
    else:
        p['probe_mask'] = np.ones(p['asize'])

    # Normalization factor
    fnorm = np.sqrt(np.prod(p['asize']))

    # Arranging optimization vector
    # NOTE: xopt MUST be CPU numpy array (CG optimizer requirement).
    # If GPU is active, gather arrays back to CPU before building xopt.
    xopt = []  # Optimization vector
    if p.get('opt_flags', [1, 1])[0] == 1:
        for obnum in range(p.get('numobjs', 1)):
            obj_cpu = np.asarray(Ggather(p['object'][obnum]))  # ensure CPU
            xopt.append(np.real(obj_cpu.flatten()))
            xopt.append(np.imag(obj_cpu.flatten()))

    if p.get('opt_flags', [1, 1])[1] == 1:
        probes_cpu = np.asarray(Ggather(p['probes']))  # ensure CPU
        xopt.append(np.real(probes_cpu.flatten()))
        xopt.append(np.imag(probes_cpu.flatten()))

    xopt = np.concatenate(xopt).astype(np.float32)  # assumed by the MEX scripts
    p['fmag'] = p['fmag'].astype(np.float32)

    if len(xopt) == 0:
        raise ValueError('At least one element of opt_flags must be 1')

    ### Optimization error metric
    if 'opt_errmetric' in p:
        opt_errmetric = p['opt_errmetric'].lower()
        if opt_errmetric == 'l1':
            verbose(2, 'Using ML-L1 error metric')
        elif opt_errmetric == 'l2':
            verbose(2, 'Using ML-L2 error metric')
        elif opt_errmetric == 'poisson':
            verbose(2, 'Using ML-Poisson')
        else:
            raise ValueError(f"{p['opt_errmetric']} is not defined")
    else:
        p['opt_errmetric'] = 'poisson'
        verbose(2, 'Using default Poisson error metric')

    ### Set specific variables needed for different metrics
    opt_errmetric = p['opt_errmetric'].lower()
    if opt_errmetric == 'poisson':
        fmag2 = p['fmag']**2
        renorm = p.get('renorm', 1.0)
        fmag2renorm = fmag2 / renorm**2

        # Approximation to log(n!) from Stirling
        # http://www.johndcook.com/blog/2010/08/16/how-to-compute-log-factorial/
        initialerror = renorm**2 * np.sum(
            p['fmask'].flatten() * (
                (fmag2renorm.flatten() + 0.5) * np.log(fmag2renorm.flatten() + 1) -
                fmag2renorm.flatten() -
                1 + 0.5 * np.log(2*np.pi) +
                1./(12*(fmag2renorm.flatten() + 1)) -
                1./(360*(fmag2renorm.flatten() + 1)**3) +
                1./(1260*(fmag2renorm.flatten() + 1)**5)
            )
        ) + np.sum(fmag2.flatten() * np.log(renorm**2))
    elif opt_errmetric == 'l1':
        initialerror = 0
        fmag2 = np.zeros_like(p['fmag'])
    elif opt_errmetric == 'l2':
        initialerror = 0
        fmag2 = p['fmag']**2
    else:
        raise ValueError(f"Error metric {p['opt_errmetric']} is not defined")

    ### Regularization
    Npix = 0
    reg_mu = p.get('reg_mu', 0)
    if reg_mu > 0:
        for obnum in range(p.get('numobjs', 1)):
            Npix = Npix + p['object_size'][obnum, 0] * p['object_size'][obnum, 1]
        Nm = np.prod(p['asize']) * p['fmag'].shape[2]
        K = 8 * Npix**2 / (Nm * p.get('Nphot', 1e6))
        creg = renorm**2 * reg_mu / K
    else:
        creg = 0

    ### Sieves preconditioning
    smooth_gradient_flag = p.get('smooth_gradient', 0)
    if smooth_gradient_flag != 0:
        if not isinstance(smooth_gradient_flag, np.ndarray):
            # Hanning regularization (not implemented yet)
            raise NotImplementedError('Hanning regularization not implemented')
        else:
            smooth_gradient = smooth_gradient_flag
    else:
        smooth_gradient = np.zeros((1, 1))

    ##############################
    ### Main optimization loop ###
    ##############################
    opt_time_start = time.time()

    # Record initial probe norm for post-CG ambiguity removal
    _pnorm_init2 = 0.0
    probes_init = Ggather(p['probes']) if use_gpu else p['probes']
    for pm in range(p.get('probe_modes', 1)):
        _pnorm_init2 += float(np.sum(np.abs(probes_init[:, :, 0, pm])**2))
    p['_ml_probe_norm_init'] = np.sqrt(_pnorm_init2)

    # Create wrapper function for gradient_ptycho
    def objective_func(x, *args):
        return gradient_ptycho(x, *args)

    # Run cgmin1
    result = cgmin1(
        objective_func,
        xopt.copy(),
        p.get('opt_iter', 10),  # itmax
        p.get('opt_ftol', 1e-3),  # ftol
        p.get('opt_xtol', 1e-3),  # xtol
        p, fmag2, initialerror, fnorm, creg, smooth_gradient
    )

    # Handle return value (could be x or (x, p))
    if isinstance(result, tuple):
        tmp, p_out = result
        if p_out is not None:
            p = p_out
    else:
        tmp = result

    _opt_time = time.time() - opt_time_start
    ##############################

    ###############################
    ### Arrange solution vector ###
    ###############################
    tmp_remaining = tmp.copy()

    if p['opt_flags'][0] == 1:
        for obnum in range(p.get('numobjs', 1)):
            objectelements = tuple(p['object_size'][obnum, :]) + (p.get('object_modes', 1),)
            numel = np.prod(objectelements)
            p['object'][obnum] = (tmp_remaining[:numel].reshape(objectelements) +
                                  1j * tmp_remaining[numel:2*numel].reshape(objectelements))
            tmp_remaining = tmp_remaining[2*numel:]

    if p['opt_flags'][1] == 1:
        probeelements = tuple(p['asize']) + (p.get('numprobs', 1), p.get('probe_modes', 1))
        numel = np.prod(probeelements)
        p['probes'] = (tmp_remaining[:numel].reshape(probeelements) +
                       1j * tmp_remaining[numel:2*numel].reshape(probeelements))
        tmp_remaining = tmp_remaining[2*numel:]

    if len(tmp_remaining) > 0:
        print('Warning: Temporary vector is not empty, optimized values not assigned')

    ############################################
    ### Remove probe-object scale ambiguity  ###
    ############################################
    # CG is unconstrained, so probe*object scale can drift.
    # Match probe norm to the initial probe norm (stored before CG)
    # so object amplitude stays in the same range as DM output.
    if p.get('opt_flags', [1, 1])[0] == 1 and p.get('opt_flags', [1, 1])[1] == 1:
        numprobs = p.get('numprobs', 1)
        probe_modes = p.get('probe_modes', 1)
        for prnum in range(numprobs):
            # Current probe power
            pnorm2 = 0.0
            for pm in range(probe_modes):
                pnorm2 += float(np.sum(np.abs(
                    Ggather(p['probes'][:, :, prnum, pm]))**2))
            pnorm_after = np.sqrt(pnorm2)
            pnorm_before = p.get('_ml_probe_norm_init', pnorm_after)
            if pnorm_after > 0 and abs(pnorm_after - pnorm_before) > 1e-10:
                scale = pnorm_before / pnorm_after  # ratio to restore
                p['probes'][:, :, prnum, :] = p['probes'][:, :, prnum, :] * scale
                # Compensate object (product preserved)
                for ii in range(p.get('numscans', 1)):
                    if int(p['share_probe_ID'][ii]) - 1 == prnum:
                        obnum = int(p['share_object_ID'][ii])
                        p['object'][obnum] = p['object'][obnum] / scale
        verbose(3, 'Restored probe norm to pre-ML value (scale ambiguity removed)')

    verbose(3, 'Finished')
    verbose(3, 'Time elapsed in optimization refinement: %f seconds', _opt_time)

    # Gather GPU arrays back to CPU before returning
    if use_gpu:
        p['object'] = [Ggather(o) for o in p['object']]
        p['probes'] = Ggather(p['probes'])
        set_use_gpu(False)

    # Prepare feedback
    fdb['error'] = errorplot([])
    fdb['status'] = 1  # Success

    # Clear errorplot for next run
    errorplot()

    return p, fdb


# Module test placeholder
if __name__ == "__main__":
    print("ML.py - Module loaded successfully")
    print("Full testing requires integration with ptychography data")
    print("Use compare_matlab_ml_exact.py for testing")
