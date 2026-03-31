"""
DM.py - Difference Map algorithm for ptychography

Python port of cSAXS +engines/DM.m

Publications:
    P. Thibault, M. Dierolf, A. Menzel, O. Bunk, C. David, F. Pfeiffer,
    "High-Resolution Scanning X-ray Diffraction Microscopy," Science 321, 379-382 (2008)

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np
import sys
from pathlib import Path
import time

# Import GPU wrapper
sys.path.insert(0, str(Path(__file__).parent / 'gpu'))
try:
    from gpu_wrapper import Garray, Ggather, set_use_gpu, GPU_AVAILABLE
except ImportError:
    GPU_AVAILABLE = False
    def Garray(x): return x
    def Ggather(x): return x
    def set_use_gpu(x): pass

# Import dependencies
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.get_projections import get_projections
from core.set_projections import set_projections
from utils.verbose import verbose
from utils.pshift import pshift

# Import math functions (avoid conflict with builtin math module)
sys.path.insert(0, str(Path(__file__).parent.parent / 'math'))
from norm2 import norm2
from sum2 import sum2

# Import DM engine functions
from engines.dm.object_update_norm import object_update_norm
from engines.dm.probe_update_norm import probe_update_norm
from engines.dm.fourier_dm_loop import fourier_dm_loop


def DM(p):
    """
    Difference Map reconstruction algorithm

    MATLAB equivalent: +engines/DM.m

    Args:
        p: parameter dict with:
            - numscans, asize, positions, scanidxs
            - probes, object, fmag
            - probe_modes, object_modes, numprobs
            - Niter, probe_change_start
            - use_mex, probe_mask_bool, etc.

    Returns:
        p: updated parameter dict
        fdb: feedback dict with status info
    """
    # Initialize feedback
    fdb = {'status': 'running'}

    # ========== Initialization Section (MATLAB lines 73-184) ==========

    # MATLAB: if ~isfield(p, 'use_mex')
    if 'use_mex' not in p:
        p['use_mex'] = np.zeros(3, dtype=bool)
    elif len(np.atleast_1d(p['use_mex'])) == 1:
        if np.any(p['use_mex']):
            verbose(3, 'Using mex files for DM.')
        p['use_mex'] = np.tile(p['use_mex'], 3)

    # GPU support
    use_gpu = p.get('use_gpu', False)
    if use_gpu:
        set_use_gpu(True)

    # MATLAB: iter = cell(p.numscans,1)
    # Python: list of arrays
    numscans = p['numscans']
    asize = p['asize']
    probe_modes = p['probe_modes']
    object_modes = p['object_modes']

    iter_scans = []
    fmag_scans = []

    for ii in range(numscans):
        # MATLAB: iter{ii} = complex(zeros([p.asize, length(p.scanidxs{ii}), p.probe_modes, p.object_modes]))
        Npos = len(p['scanidxs'][ii])
        iter_shape = (asize[0], asize[1], Npos, probe_modes, object_modes)
        iter_scans.append(np.zeros(iter_shape, dtype=complex))

        # MATLAB: fmag{ii} = double(p.fmag(:,:,p.scanidxs{ii}))
        # Convert scanidxs from 1-based to 0-based
        # Note: fmag needs probe_modes dimension for fourier_dm_loop
        scanidxs_py = np.array(p['scanidxs'][ii]) - 1
        fmag_scan = p['fmag'][:, :, scanidxs_py].astype(float)
        # Add probe_modes dimension if not present
        if fmag_scan.ndim == 3:
            fmag_scan = fmag_scan[:, :, :, np.newaxis]
        fmag_scans.append(fmag_scan)

    # MATLAB: if p.object_modes == 1 && p.numprobs == 1
    obj_proj = None
    numprobs = p.get('numprobs', 1)
    if object_modes == 1 and numprobs == 1:
        # MATLAB: obj_proj = complex(zeros([p.asize, length(p.scanidxs{1})]))
        Npos_first = len(p['scanidxs'][0])
        obj_proj = np.zeros((asize[0], asize[1], Npos_first, 1), dtype=complex)

    # MATLAB: if p.probe_mask_bool
    probe_mask_bool = p.get('probe_mask_bool', False)
    if probe_mask_bool:
        probe_mask_use_auto = p.get('probe_mask_use_auto', False)
        if probe_mask_use_auto:
            verbose(3, 'Using a probe mask from probe autocorrelation.')
            # Note: 'auto' variable should be pre-computed in p
            to_threshold = -np.real(p['auto'])
        else:
            verbose(3, 'Using a circular probe mask.')
            # MATLAB: [x,y] = meshgrid(...)
            y, x = np.mgrid[
                -asize[0]//2:asize[0]//2 + (asize[0] % 2),
                -asize[1]//2:asize[1]//2 + (asize[1] % 2)
            ]
            to_threshold = x**2 + y**2

        # MATLAB: p.probe_mask = to_threshold < quantile(to_threshold(:), p.probe_mask_area)
        probe_mask_area = p.get('probe_mask_area', 0.9)
        p['probe_mask'] = to_threshold < np.quantile(to_threshold, probe_mask_area)
    else:
        p['probe_mask'] = 1.0

    # MATLAB: for i = 1:p.numobjs
    numobjs = p.get('numobjs', 1)
    p['object_size'] = []
    ob = []

    for i in range(numobjs):
        # MATLAB: p.object_size(i,:) = size(p.object{i})
        obj_i = p['object'][i]
        p['object_size'].append(obj_i.shape)

        # MATLAB: ob{i} = double(p.object{i})
        ob.append(obj_i.astype(complex))

    # MATLAB: p.probes = double(p.probes)
    probes = p['probes'].astype(complex)

    # MATLAB: for obnum = 1:p.numobjs
    #         avob{obnum} = zeros([p.object_size(obnum,:) p.object_modes])
    avob = []
    for obnum in range(numobjs):
        obj_size = p['object_size'][obnum]
        # Always include object_modes dimension to match ob[obnum] shape (H, W, modes)
        avob_shape = (int(obj_size[0]), int(obj_size[1]), object_modes)
        avob.append(np.zeros(avob_shape, dtype=complex))

    # MATLAB: get views from probes and objects (lines 143-158)
    for ii in range(numscans):
        # Convert to 1-based for function calls
        scan_id = ii + 1

        # MATLAB: prnum = p.share_probe_ID(ii)
        # MATLAB: obnum = p.share_object_ID(ii)
        prnum = p['share_probe_ID'][ii]
        obnum = p['share_object_ID'][ii]

        # MATLAB: if p.object_modes == 1 && p.numprobs == 1
        if object_modes == 1 and numprobs == 1:
            # MATLAB: obj_proj = core.get_projections(p, ob{obnum}, ii, obj_proj)
            obj_proj = get_projections(p, ob[obnum], scan_id, obj_proj)

            # MATLAB: iter{ii} = bsxfun(@times, p.probes, obj_proj)
            iter_scans[ii] = probes * obj_proj

        else:
            # MATLAB: for obmode = 1:p.object_modes
            for obmode in range(object_modes):
                # MATLAB: obj_proj = core.get_projections(p, ob{obnum}(:,:,obmode), ii)
                obj_proj = get_projections(p, ob[obnum][:, :, obmode], scan_id)

                # MATLAB: iter{ii}(:,:,:,:,obmode) = bsxfun(@times, p.probes(:,:,prnum,:), obj_proj)
                # Convert prnum from 1-based to 0-based
                prnum_py = prnum - 1 if isinstance(prnum, int) else prnum - 1
                iter_scans[ii][:, :, :, :, obmode] = probes[:, :, prnum_py, :] * obj_proj

    # MATLAB: p.power_bound = p.count_bound*p.renorm^2
    count_bound = p.get('count_bound', 1.0)
    renorm = p.get('renorm', 1.0)
    p['power_bound'] = count_bound * renorm**2

    # MATLAB: Set indices for user supplied flat mask
    object_flat_region = p.get('object_flat_region', None)
    if object_flat_region is not None:
        p['userflatregion'] = True
        if numscans > 1 and not p.get('share_object', False):
            raise ValueError('Object flat region not yet implemented for multiple objects. Set object_flat_region = None')

        # Check size
        if np.any(np.array(p['object_size'][0]) != np.array(object_flat_region.shape)):
            raise ValueError('Mask object_flat_region does not match size of object')
        else:
            p['userflatind'] = (object_flat_region == 1)
    else:
        p['userflatregion'] = False

    # Move core arrays to GPU if use_gpu is enabled
    if use_gpu:
        probes = Garray(probes)
        ob = [Garray(o) for o in ob]
        iter_scans = [Garray(it) for it in iter_scans]
        fmag_scans = [Garray(fm) for fm in fmag_scans]
        avob = [Garray(a) for a in avob]
        # Move obj_proj buffer to GPU if allocated
        if obj_proj is not None:
            obj_proj = Garray(obj_proj)
        # Move pr_nrm placeholders (they will be re-initialized in the loop, so no action needed here)

    verbose(2, 'DM initialization complete. Starting main loop...')

    # ========== Main Loop (MATLAB lines 185-561) ==========

    # MATLAB: Prepare statistics (lines 197-202)
    proj1_time = 0.0
    proj2_time = 0.0
    plot_time = 0.0
    objproj_time = 0.0
    probeproj_time = 0.0
    elsewheretime = 0.0

    # MATLAB: cfact_temp = p.probe_regularization * p.numpts (lines 205-213)
    probe_regularization = p.get('probe_regularization', np.ones(numscans))
    numpts = p.get('numpts', [len(p['scanidxs'][i]) for i in range(numscans)])
    cfact_temp = probe_regularization * numpts

    share_probe = p.get('share_probe', False)
    if share_probe:
        cfact = np.zeros(numprobs)
        for ii in range(numscans):
            prnum = p['share_probe_ID'][ii]
            cfact[prnum-1] += cfact_temp[ii]  # Convert to 0-based
    else:
        cfact = cfact_temp

    # MATLAB: err = 0; rfact = 0; numav = 0 (lines 215-217)
    number_iterations = p.get('number_iterations', 100)
    err = np.zeros(number_iterations)
    compute_rfact = p.get('compute_rfact', False)
    if compute_rfact:
        rfact = np.zeros(number_iterations)
    numav = 0

    # MATLAB: for it=1:p.number_iterations (line 219)
    for it in range(number_iterations):
        verbose(2, f'Iteration # {it+1} of {number_iterations}')

        # ===== 1. Projection 1: Overlap constraint =====
        verbose(3, ' - projection 1: overlap constraint - ')
        proj1_start = time.time()

        # MATLAB: Check for user break (lines 231-238)
        # (Skipped in Python version - can use KeyboardInterrupt)

        # MATLAB: The simple iterative scheme (lines 241-355)
        prch0 = 0
        breakprobeloop = False

        for inner in range(10):
            if not breakprobeloop:
                # MATLAB: cprobes = conj(p.probes) (line 245)
                # DEBUG: Check probes shape before conjugation
                verbose(3, f'Iteration {it+1}: probes shape = {probes.shape}')
                # Use xp (cupy or numpy) to match the probes array type
                try:
                    import cupy as cp
                    _xp = cp.get_array_module(probes)
                except ImportError:
                    _xp = np
                cprobes = _xp.conj(probes)

                # MATLAB: Initialize ob and pr_nrm (lines 246-253)
                pr_nrm = []
                for obnum in range(numobjs):
                    # MATLAB: pr_nrm{obnum} = 1e-8 * ones(p.object_size(obnum,:))
                    pr_nrm.append(_xp.ones(p['object_size'][obnum]) * 1e-10)

                    # MATLAB: ob{obnum} = 1e-8*(1+1i)*ones([p.object_size(obnum,:) p.object_modes])
                    if object_modes == 1:
                        ob[obnum] = _xp.ones(p['object_size'][obnum], dtype=complex) * (1e-10 * (1 + 1j))
                    else:
                        ob_shape = (p['object_size'][obnum][0], p['object_size'][obnum][1], object_modes)
                        ob[obnum] = _xp.ones(ob_shape, dtype=complex) * (1e-10 * (1 + 1j))

                # MATLAB: Object update loop (lines 254-281)
                for ii in range(numscans):
                    objtic_start = time.time()

                    prnum = p['share_probe_ID'][ii]
                    obnum = p['share_object_ID'][ii]

                    # Use pure Python version (not MEX)
                    # Call object_update_norm
                    ob[obnum], pr_nrm[obnum] = object_update_norm(
                        p, cprobes, ob[obnum], pr_nrm[obnum],
                        iter_scans[ii], ii+1, prnum=prnum
                    )

                    objproj_time += time.time() - objtic_start

                # MATLAB: Normalize object (lines 283-299)
                for obnum in range(numobjs):
                    # MATLAB: ob{obnum} = bsxfun(@rdivide, ob{obnum}, pr_nrm{obnum})
                    ob[obnum] = ob[obnum] / pr_nrm[obnum]

                    # MATLAB: if p.userflatregion (lines 286-288)
                    if p['userflatregion']:
                        userflatind = p['userflatind']
                        ob[obnum][userflatind] = np.mean(ob[obnum][userflatind])

                    # MATLAB: if p.clip_object (lines 291-296)
                    clip_object = p.get('clip_object', False)
                    if clip_object:
                        aob = np.abs(ob[obnum])
                        clip_max = p.get('clip_max', np.inf)
                        clip_min = p.get('clip_min', 0)
                        too_high = aob > clip_max
                        too_low = aob < clip_min
                        ob[obnum] = ((1 - too_high) * (1 - too_low) * ob[obnum] +
                                     (too_high * clip_max + too_low * clip_min) * ob[obnum] / (aob + 1e-10))

                # MATLAB: Probe update (lines 300-353)
                probe_change_start = p.get('probe_change_start', 0)
                if probe_change_start >= it+1:
                    breakprobeloop = True
                else:
                    # MATLAB: Defining the new probes (regularization) (lines 303-305)
                    # nprobes: (asize, asize, numprobs, probe_modes)
                    verbose(3, f'cfact shape: {cfact.shape}, numprobs: {numprobs}')
                    verbose(3, f'probes shape before nprobes init: {probes.shape}')
                    # Convert cfact to the same device as probes for GPU compatibility
                    cfact_xp = _xp.asarray(cfact) if _xp is not np else cfact
                    nprobes = probes * cfact_xp.reshape(1, 1, -1, 1)
                    verbose(3, f'nprobes shape after init: {nprobes.shape}')
                    # pr_denoms: (asize, asize, numprobs) - no probe_modes dimension!
                    pr_denoms = _xp.ones((asize[0], asize[1], numprobs)) * cfact_xp.reshape(1, 1, -1)
                    verbose(3, f'pr_denoms shape: {pr_denoms.shape}')

                    for ii in range(numscans):
                        probetic_start = time.time()

                        prnum = p['share_probe_ID'][ii]
                        obnum = p['share_object_ID'][ii]

                        # MATLAB: Initialize nprobe and pr_denom (lines 311-312)
                        # nprobe: (asize, asize, probe_modes)
                        nprobe = nprobes[:, :, prnum-1, :]
                        # pr_denom: (asize, asize) - 2D!
                        pr_denom = pr_denoms[:, :, prnum-1]

                        # Use pure Python version
                        # Call probe_update_norm
                        nprobe, pr_denom = probe_update_norm(
                            p, ob[obnum], iter_scans[ii],
                            nprobe, pr_denom, ii+1, obj_proj=obj_proj
                        )

                        # Store back
                        verbose(3, f'Before store: nprobe shape = {nprobe.shape}, pr_denom shape = {pr_denom.shape}')
                        verbose(3, f'prnum = {prnum}, prnum-1 = {prnum-1}')
                        nprobes[:, :, prnum-1, :] = nprobe
                        verbose(3, f'After nprobes store: nprobes shape = {nprobes.shape}')
                        pr_denoms[:, :, prnum-1] = pr_denom
                        verbose(3, f'After pr_denoms store: pr_denoms shape = {pr_denoms.shape}')

                        probeproj_time += time.time() - probetic_start

                    # MATLAB: probe_new = bsxfun(@rdivide, nprobes, pr_denoms) (line 340)
                    verbose(3, f'Before division: nprobes shape = {nprobes.shape}, pr_denoms shape = {pr_denoms.shape}')
                    probe_new = nprobes / pr_denoms[:, :, :, None]
                    verbose(3, f'After division: probe_new shape = {probe_new.shape}')

                    # MATLAB: probe_new = bsxfun(@times, p.probe_mask, probe_new) (line 341)
                    pm_raw = p['probe_mask']
                    pm_shape = pm_raw.shape if hasattr(pm_raw, 'shape') else '(scalar)'
                    verbose(3, f'Before probe_mask: probe_new shape = {probe_new.shape}, probe_mask shape = {pm_shape}')
                    # Fix: reshape probe_mask to 4D for correct broadcasting
                    # Handle scalar probe_mask (when probe_mask_bool=False, mask = 1.0)
                    if not hasattr(pm_raw, 'ndim'):
                        # scalar
                        probe_mask_4d = pm_raw
                    else:
                        # Use Garray to ensure probe_mask is on same device as probe_new
                        probe_mask_arr = Garray(pm_raw) if use_gpu else pm_raw
                        if probe_mask_arr.ndim == 2:
                            probe_mask_4d = probe_mask_arr[:, :, None, None]
                        else:
                            probe_mask_4d = probe_mask_arr
                    probe_new = probe_mask_4d * probe_new
                    verbose(3, f'After probe_mask: probe_new shape = {probe_new.shape}')

                    # MATLAB: get relative residuum (line 344)
                    prch = _xp.sqrt(
                        _xp.sum(_xp.sum(_xp.sum(_xp.abs(probes - probe_new)**2, axis=0), axis=0), axis=1) /
                        _xp.sum(_xp.sum(_xp.sum(_xp.abs(probes)**2, axis=0), axis=0), axis=1)
                    )
                    # Convert to numpy for scalar comparisons
                    prch_np = np.asarray(Ggather(prch)) if use_gpu else np.asarray(prch)

                    for prnum_idx in range(numprobs):
                        verbose(3, f'Change in probe {prnum_idx+1}: {prch_np[prnum_idx]*100:.2f}%%')

                    # MATLAB: p.probes = probe_new (line 348)
                    verbose(3, f'Updating probes: old shape = {probes.shape}, new shape = {probe_new.shape}')
                    probes = probe_new

                    # MATLAB: if all(prch < 0.01) (line 350-352)
                    if np.all(prch_np < 0.01):
                        breakprobeloop = True

        proj1_time += time.time() - proj1_start

        # ===== 2. Fourier projection =====
        er2 = 0.0
        verbose(3, ' - projection 2: Fourier modulus constraint - ')

        # MATLAB: Perform normalization of probe (lines 367-384)
        average_start = p.get('average_start', number_iterations + 1)
        remove_scaling_ambiguity = p.get('remove_scaling_ambiguity', True)

        if it+1 < average_start and remove_scaling_ambiguity:
            pnorm = norm2(probes)
            # Convert to numpy for scalar operations (norm2 may return cupy array)
            pnorm_np = np.array(Ggather(pnorm)) if use_gpu else np.asarray(pnorm)

            # Check if each scan has unique probe and object
            unique_probe_ids = len(np.unique(p['share_probe_ID']))
            unique_object_ids = len(np.unique(p['share_object_ID']))

            # Compute one scalar norm per probe group (total power across all modes).
            # All modes of a probe MUST be scaled by the SAME factor to preserve
            # relative mode power ratios. Using per-mode norms would equalize modes.
            # For multimode: norm2 returns (numprobs, probe_modes); collapse to (numprobs,)
            # Use SUM (not mean) to get total probe power: sqrt(sum_m(||Pm||^2))
            # With mean, object is scaled by 1/sqrt(Nmodes) → darker images in multimode.
            if pnorm_np.ndim > 1:
                pnorm_per_probe = np.sqrt(np.sum(pnorm_np**2, axis=tuple(range(1, pnorm_np.ndim))))  # (numprobs,)
            else:
                pnorm_per_probe = np.atleast_1d(pnorm_np.flatten())  # (numprobs,)

            if unique_probe_ids == numscans and unique_object_ids == numscans:
                # Individual normalization: all modes of each probe scaled by same scalar
                for prnum_idx in range(numprobs):
                    ps = float(pnorm_per_probe[prnum_idx])
                    if ps > 0:
                        probes[:, :, prnum_idx, :] = probes[:, :, prnum_idx, :] / ps
                for ii in range(numscans):
                    prnum_idx = min(int(p['share_probe_ID'][ii]), numprobs - 1)
                    pnorm_scalar = float(pnorm_per_probe[prnum_idx])
                    ob[ii] = ob[ii] * pnorm_scalar
            else:
                # Shared normalization
                pnorm_mean = float(np.mean(pnorm_per_probe))
                probes = probes / pnorm_mean
                for ii in range(numscans):
                    ob[ii] = ob[ii] * pnorm_mean

        # MATLAB: Call Fourier_DM_loop (pure Python version, lines 455-501)
        proj2_start = time.time()

        # Prepare fmask
        fmask = p.get('fmask', np.ones((asize[0], asize[1])))
        if use_gpu:
            fmask = Garray(fmask)
        p['fmask'] = fmask

        # Call fourier_dm_loop
        iter_scans, er2 = fourier_dm_loop(p, ob, probes, iter_scans, fmag_scans, obj_proj=obj_proj)

        # MATLAB: if p.center_probe (lines 504-525) - SKIPPED for simplicity

        proj2_time += time.time() - proj2_start

        # ===== 3. Error metric calculation =====
        # MATLAB: err(it) = 2*sqrt(er2/(prod(p.asize)*sum(p.numpts))) (line 528)
        err[it] = 2 * np.sqrt(er2 / (np.prod(asize) * np.sum(numpts)))

        if compute_rfact:
            # rfact calculation would go here (skipped for now)
            verbose(3, f'Error: {err[it]:12.3f}')
        else:
            verbose(3, f'Error: {err[it]:12.3f}')

        # ===== 4. Object averaging =====
        # MATLAB: if (it >= p.average_start) && mod(it, p.average_interval)==0 (lines 536-541)
        average_interval = p.get('average_interval', 1)
        if it+1 >= average_start and (it+1) % average_interval == 0:
            for obnum in range(numobjs):
                avob[obnum] = avob[obnum] + ob[obnum]
            numav += 1

        # Update error metric in p
        p['error_metric'] = {
            'iteration': np.arange(1, it+2),
            'value': err[:it+1],
            'err_metric': 'RMS',
            'method': p.get('name', 'DM')
        }

        # ===== 5. Iteration callback (for WebSocket UI) =====
        _cb = p.get('_iteration_callback')
        if _cb:
            _cb_data = {
                'type': 'iteration_update', 'engine': 'DM',
                'iteration': it + 1, 'total_iterations': number_iterations,
                'error': float(err[it]),
            }
            _preview_interval = max(5, number_iterations // 5)
            if (it + 1) % _preview_interval == 0 or it == number_iterations - 1:
                _cb_data['include_preview'] = True
                _cb_data['object'] = Ggather(ob[0]) if use_gpu else ob[0]
                _cb_data['probes'] = Ggather(probes) if use_gpu else probes
            _cb(_cb_data)
        _ce = p.get('_cancel_event')
        if _ce and _ce.is_set():
            verbose(2, 'DM cancelled by user at iteration %d' % (it + 1))
            break

    # ========== Post-processing (MATLAB lines 562-606) ==========

    verbose(3, 'Finished difference map')
    verbose(3, f'Time elapsed in projection 1: {proj1_time:.2f} seconds')
    verbose(3, f'             in object projection: {objproj_time:.2f} seconds')
    verbose(3, f'             in probe projection: {probeproj_time:.2f} seconds')
    verbose(3, f'Time elapsed in projection 2: {proj2_time:.2f} seconds')

    # MATLAB: Average (lines 572-579)
    for obnum in range(numobjs):
        if numav > 0:
            avob[obnum] = avob[obnum] / numav
        else:
            avob[obnum] = ob[obnum]

    # Gather GPU arrays back to CPU before returning
    # Also gather any arrays stored in p that were moved to GPU during the run
    if use_gpu:
        probes = Ggather(probes)
        ob = [Ggather(o) for o in ob]
        avob = [Ggather(a) for a in avob]
        # fmask was moved to GPU inside the loop; gather it back so downstream
        # engines (ML, LSQML) receive a plain NumPy array in p['fmask'].
        if 'fmask' in p:
            p['fmask'] = Ggather(p['fmask'])
        set_use_gpu(False)

    # Update p with final state
    p['probes'] = probes
    p['object'] = ob
    p['object_avg'] = avob

    fdb['status'] = 'completed'
    fdb['error'] = err
    fdb['iterations'] = number_iterations

    return p, fdb


# Module test
if __name__ == "__main__":
    print("Testing DM.py initialization...")

    # Create minimal test parameters
    asize = np.array([32, 32])
    Npos = 5

    p = {
        'numscans': 1,
        'asize': asize,
        'probe_modes': 1,
        'object_modes': 1,
        'numprobs': 1,
        'numobjs': 1,
        'positions': np.random.rand(Npos, 2) * 10,  # Random positions
        'scanidxs': [np.arange(1, Npos+1)],  # 1-based MATLAB indexing
        'share_probe_ID': np.array([1]),
        'share_object_ID': np.array([0]),  # 0-based Python indexing
        'probes': np.ones((asize[0], asize[1], 1, 1), dtype=complex) * 0.5,
        'object': [np.ones((100, 100), dtype=complex)],
        'fmag': np.ones((asize[0], asize[1], Npos)) * 0.5,
        'probe_mask_bool': False,
        'count_bound': 1.0,
        'renorm': 1.0,
    }

    # Add required parameters for main loop
    p['number_iterations'] = 5  # Run 5 iterations for testing
    p['fmask'] = np.ones((asize[0], asize[1]))  # No mask
    p['pfft_relaxation'] = 0.05
    p['numpts'] = [Npos]
    p['probe_regularization'] = np.array([0.1])
    p['probe_change_start'] = 0
    p['average_start'] = 10  # Don't average during test
    p['name'] = 'DM_test'

    # Test full DM run
    p_out, fdb = DM(p)

    print(f"Status: {fdb['status']}")
    print(f"Iterations: {fdb['iterations']}")
    print(f"Final error: {fdb['error'][-1]:.6f}")
    print(f"Probe shape: {p_out['probes'].shape}")
    print(f"Object shape: {p_out['object'][0].shape}")
    print(f"Object avg shape: {p_out['object_avg'][0].shape}")

    # Note: With random test data, error may not decrease
    # Real ptychography data will show error reduction
    print(f"Error history: {fdb['error']}")

    # Check that algorithm completed without crashes
    assert fdb['status'] == 'completed', "DM should complete successfully"

    print("\nDM reconstruction test passed!")
