"""GPU-accelerated Difference Map (DM) ptychography reconstruction engine.

Port of MATLAB +engines/+GPU/DM.m from cSAXS PtychoShelves package.
Uses inertia-based overlap solver matching MATLAB GPU DM algorithm.

Key changes from CPU DM mirror (previous version):
- Object/probe updates use inertia blending (not reset/cfact)   — DM.m L286, L353
- MAX_ILLUM delta regularization for object                      — ptycho_solver.m L273
- Iteration 0 probe amplitude correction                        — DM.m L179
- Probe orthogonalization at final iteration (multi-mode)        — ptycho_solver.m L359
- No remove_scaling_ambiguity (not in MATLAB GPU DM)

Fourier projection: engines/dm/fourier_dm_loop.py (verified equivalent to MATLAB).

Reference:
    P. Thibault et al., "High-Resolution Scanning X-ray Diffraction Microscopy,"
    Science 321, 379-382 (2008)
"""

import numpy as np
import sys
from pathlib import Path

try:
    import cupy as cp
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False

# Core modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.get_projections import get_projections
from utils.verbose import verbose

# DM Fourier projection (verified equivalent to MATLAB — NOT modified)
from engines.dm.fourier_dm_loop import fourier_dm_loop

# Shared GPU modules
from engines.gpu.shared import get_reciprocal_model
from engines.gpu.shared.apply_probe_contraints import apply_probe_contraints


def _to_gpu(x):
    if isinstance(x, cp.ndarray):
        return x
    return cp.asarray(x)


def _to_cpu(x):
    if isinstance(x, np.ndarray):
        return x
    return cp.asnumpy(x)


def DM(p):
    """
    GPU Difference Map reconstruction — port of +engines/+GPU/DM.m.

    Inertia-based overlap solver, multi-mode probe, probe orthogonalization.

    Args:
        p: parameter dict (probe_inertia default 0.3)

    Returns:
        p: updated parameter dict
        fdb: feedback dict
    """
    from .gpu_wrapper import set_use_gpu

    if not GPU_AVAILABLE:
        raise RuntimeError('CuPy not available for GPU DM')

    fdb = {'status': 'running'}

    try:
        set_use_gpu(True)

        # ====== Initialization ======

        if 'use_mex' not in p:
            p['use_mex'] = np.zeros(3, dtype=bool)
        elif len(np.atleast_1d(p['use_mex'])) == 1:
            p['use_mex'] = np.tile(p['use_mex'], 3)

        numscans = p['numscans']
        asize = p['asize']
        probe_modes = p['probe_modes']
        object_modes = p['object_modes']
        numprobs = p.get('numprobs', 1)
        numobjs = p.get('numobjs', 1)

        # DM parameters — get_defaults.m + DM.m
        probe_inertia = p.get('probe_inertia', 0.3)          # get_defaults.m
        number_iterations = p.get('number_iterations', 100)
        probe_change_start = p.get('probe_change_start', 1)  # DM.m L314
        object_change_start = p.get('object_change_start', 1)
        numpts = p.get('numpts', [len(p['scanidxs'][i]) for i in range(numscans)])

        # Build iter_scans and fmag_scans on GPU
        iter_scans = []
        fmag_scans = []

        for ii in range(numscans):
            Npos = len(p['scanidxs'][ii])
            iter_shape = (asize[0], asize[1], Npos, probe_modes)
            if object_modes > 1:
                iter_shape += (object_modes,)
            iter_scans.append(cp.zeros(iter_shape, dtype=complex))

            scanidxs_py = np.array(p['scanidxs'][ii]) - 1
            fmag_scan = p['fmag'][:, :, scanidxs_py].astype(float)
            if fmag_scan.ndim == 3:
                fmag_scan = fmag_scan[:, :, :, np.newaxis]
            fmag_scans.append(_to_gpu(fmag_scan))

        # Pre-allocated obj_proj buffer
        obj_proj = None
        if object_modes == 1 and numprobs == 1:
            Npos_first = len(p['scanidxs'][0])
            obj_proj = cp.zeros((asize[0], asize[1], Npos_first, 1), dtype=complex)

        # Probe support — DM.m apply_probe_contraints (mode 1 only)
        # Build mode dict for apply_probe_contraints — matches MATLAB self.modes{1}
        probe_mask_bool = p.get('probe_mask_bool', False)
        if probe_mask_bool:
            if p.get('probe_mask_use_auto', False):
                to_threshold = -np.real(p['auto'])
            else:
                y, x = np.mgrid[
                    -asize[0]//2:asize[0]//2 + (asize[0] % 2),
                    -asize[1]//2:asize[1]//2 + (asize[1] % 2)
                ]
                to_threshold = x**2 + y**2
            probe_mask_area = p.get('probe_mask_area', 0.9)
            probe_support = (to_threshold
                             < np.quantile(to_threshold, probe_mask_area))
            probe_support_gpu = _to_gpu(
                probe_support.astype(np.float32)
            )
        else:
            probe_support_gpu = None  # no real-space support

        # Fourier-space probe support (optional)
        probe_support_fft_raw = p.get('probe_support_fft', None)
        if probe_support_fft_raw is not None:
            probe_support_fft_gpu = _to_gpu(
                np.asarray(probe_support_fft_raw, dtype=np.float32)
            )
        else:
            probe_support_fft_gpu = None

        # Mode dict for apply_probe_contraints — MATLAB self.modes{1}
        probe_constraint_mode = {
            'probe_support': probe_support_gpu,
            'support_fwd_propagation_factor': None,   # far-field: no ASM
            'support_back_propagation_factor': None,   # far-field: no ASM
            'probe_support_fft': probe_support_fft_gpu,
            'probe_scale_upd': [0],
            'probe_scale_window': None,
            'distances': [np.inf],  # far-field propagation
        }

        # Objects → GPU
        p['object_size'] = []
        ob = []
        for i in range(numobjs):
            obj_i = p['object'][i]
            p['object_size'].append(obj_i.shape)
            ob.append(_to_gpu(obj_i.astype(complex)))

        # Probes → GPU
        probes = _to_gpu(p['probes'].astype(complex))

        # Object averaging accumulator — ptycho_solver.m L372
        avob = [cp.zeros_like(ob[i]) for i in range(numobjs)]

        # Initialize iter_scans = probe * object_view — DM.m L110-130
        for ii in range(numscans):
            scan_id = ii + 1
            prnum = p['share_probe_ID'][ii]
            obnum = p['share_object_ID'][ii]

            if object_modes == 1 and numprobs == 1:
                obj_proj = get_projections(p, ob[obnum], scan_id, obj_proj)
                iter_scans[ii] = probes * obj_proj
            else:
                for obmode in range(object_modes):
                    obj_proj_t = get_projections(p, ob[obnum][:, :, obmode], scan_id)
                    iter_scans[ii][:, :, :, :, obmode] = probes[:, :, prnum-1, :] * obj_proj_t

        # Power bound
        p['power_bound'] = p.get('count_bound', 1.0) * p.get('renorm', 1.0)**2

        # Flat region
        object_flat_region = p.get('object_flat_region', None)
        if object_flat_region is not None:
            p['userflatregion'] = True
            p['userflatind'] = (object_flat_region == 1)
        else:
            p['userflatregion'] = False

        # fmask → GPU
        p['fmask'] = _to_gpu(p.get('fmask', np.ones((asize[0], asize[1]))))

        # MAX_ILLUM state — ptycho_solver.m L273-287
        # Initialize as zeros to match MATLAB: illum_sum_0 starts as Gzeros
        max_illum = 1.0
        illum_sum_prev = cp.zeros(ob[0].shape[:2], dtype=float)

        verbose(2, 'GPU DM initialization complete. Starting main loop...')

        # ====== Main Loop — DM.m + ptycho_solver.m ======

        err = np.zeros(number_iterations)
        numav = 0
        mode_fft = {'distances': [np.inf]}  # far-field propagation

        for it in range(number_iterations):
            verbose(2, f'GPU DM Iteration # {it+1} of {number_iterations}')

            # === 1. Iteration 0: probe amplitude correction — DM.m L179-217 ===
            # Uses orthogonal FFT convention (/fnorm) to match fourier_dm_loop
            if it == 0:
                sum_modF2 = 0.0
                sum_aPsi2 = 0.0
                fnorm_corr = cp.sqrt(cp.array(float(np.prod(asize))))

                for ii in range(numscans):
                    obnum = p['share_object_ID'][ii]
                    prnum_py = p['share_probe_ID'][ii] - 1
                    scanidxs_py = np.array(p['scanidxs'][ii]) - 1

                    for jj in range(len(scanidxs_py)):
                        pos = p['positions'][int(scanidxs_py[jj])]
                        r = int(np.round(float(pos[0])))
                        c = int(np.round(float(pos[1])))
                        obj_view = ob[obnum][r:r+asize[0], c:c+asize[1]]

                        # Incoherent sum over probe modes — DM.m L195-200
                        # Orthogonal FFT: divide by fnorm to match fmag convention
                        Psi_list = []
                        for ll in range(probe_modes):
                            psi_ll = obj_view * probes[:, :, prnum_py, ll]
                            Psi_ll = cp.fft.fft2(psi_ll) / fnorm_corr
                            Psi_list.append(Psi_ll)
                        aPsi = get_reciprocal_model(Psi_list)

                        modF = fmag_scans[ii][:, :, jj, 0]
                        sum_modF2 += float(cp.sum(modF**2))
                        sum_aPsi2 += float(cp.sum(aPsi**2))

                if sum_aPsi2 > 0:
                    corr = np.sqrt(sum_modF2 / sum_aPsi2)
                    probes = probes * corr
                    verbose(2, f'  Probe amplitude corrected by {corr:.4f}')

                # Re-initialize iter_scans with corrected probes,
                # then skip to next iteration — DM.m L216-217
                for ii_r in range(numscans):
                    scan_id_r = ii_r + 1
                    obnum_r = p['share_object_ID'][ii_r]
                    if object_modes == 1 and numprobs == 1:
                        obj_proj_r = get_projections(
                            p, ob[obnum_r], scan_id_r, obj_proj
                        )
                        iter_scans[ii_r] = probes * obj_proj_r
                    else:
                        for obmode in range(object_modes):
                            obj_proj_t = get_projections(
                                p, ob[obnum_r][:, :, obmode], scan_id_r
                            )
                            prnum_r = p['share_probe_ID'][ii_r] - 1
                            iter_scans[ii_r][:, :, :, :, obmode] = (
                                probes[:, :, prnum_r, :] * obj_proj_t
                            )
                verbose(2, '  Iter 0: psi_dash re-initialized, '
                        'skipping Fourier loop (DM.m L216)')
                continue  # skip fourier_dm_loop at iter 0 — DM.m returns

            # === 2. MAX_ILLUM — ptycho_solver.m L273-287 ===
            if it == 1 or it % 10 == 0:
                aprobe2_m1 = cp.abs(probes[:, :, 0, 0])**2   # mode 1 only
                illum_sum = cp.zeros(ob[0].shape[:2], dtype=float)

                for ii in range(numscans):
                    scanidxs_py = np.array(p['scanidxs'][ii]) - 1
                    for jj in range(len(scanidxs_py)):
                        pos = p['positions'][int(scanidxs_py[jj])]
                        r = int(np.round(float(pos[0])))
                        c = int(np.round(float(pos[1])))
                        illum_sum[r:r+asize[0], c:c+asize[1]] += aprobe2_m1

                # MATLAB recursion: illum = (illum_prev + fresh) / 2
                # illum_sum_0 starts as zeros, set_views adds fresh, then /2
                # — ptycho_solver.m L279
                illum_sum = (illum_sum_prev + illum_sum) / 2
                illum_sum_prev = illum_sum.copy()
                max_illum = max(float(cp.max(illum_sum)), 1e-10)

            # === 3. Overlap solver (skip at iter 0) — DM.m L224-380 ===
            if it > 0:
                breakprobeloop = False

                for inner in range(10):
                    if breakprobeloop:
                        break

                    probes_old = probes.copy()

                    # Zero accumulators — DM.m L224-227
                    obj_upd = [cp.zeros_like(ob[i]) for i in range(numobjs)]
                    obj_ill = [cp.zeros(ob[i].shape[:2], dtype=float)
                               for i in range(numobjs)]

                    prb_upd = [[cp.zeros((asize[0], asize[1]), dtype=complex)
                                for _ in range(probe_modes)]
                               for _ in range(numprobs)]
                    prb_ill = [cp.zeros((asize[0], asize[1]), dtype=float)
                               for _ in range(numprobs)]

                    # Accumulate over scans — DM.m L230-340
                    for ii in range(numscans):
                        scan_id = ii + 1
                        prnum_py = p['share_probe_ID'][ii] - 1
                        obnum = p['share_object_ID'][ii]
                        scanidxs_py = np.array(p['scanidxs'][ii]) - 1
                        Npos_scan = len(scanidxs_py)

                        # Object views (asize, asize, Npos, 1) — DM.m L232
                        obj_proj_views = get_projections(
                            p, ob[obnum], scan_id, obj_proj
                        )
                        # (asize, asize, Npos)
                        obj_views = obj_proj_views[:, :, :, 0]

                        # QQ_probe: per-mode — DM.m L318-325
                        if it + 1 >= probe_change_start:
                            for ll in range(probe_modes):
                                prb_upd[prnum_py][ll] += cp.sum(
                                    iter_scans[ii][:, :, :, ll]
                                    * cp.conj(obj_views),
                                    axis=2
                                )
                            # prb_ill is same for all modes
                            prb_ill[prnum_py] += cp.sum(
                                cp.abs(obj_views)**2, axis=2
                            )

                        # QQ_object: last mode only — DM.m L335-340
                        if it + 1 >= object_change_start:
                            last_ll = probe_modes - 1
                            probe_last = probes[:, :, prnum_py, last_ll]
                            aprobe2_last = cp.abs(probe_last)**2

                            for jj in range(Npos_scan):
                                pos = p['positions'][int(scanidxs_py[jj])]
                                r = int(np.round(float(pos[0])))
                                c = int(np.round(float(pos[1])))

                                psi_jj = iter_scans[ii][:, :, jj, last_ll]
                                obj_upd[obnum][
                                    r:r+asize[0], c:c+asize[1]
                                ] += psi_jj * cp.conj(probe_last)

                                obj_ill[obnum][
                                    r:r+asize[0], c:c+asize[1]
                                ] += aprobe2_last

                    # Update probe with inertia — DM.m L353-362
                    if it + 1 >= probe_change_start:
                        for prnum_idx in range(numprobs):
                            for ll in range(probe_modes):
                                probe_new = (
                                    prb_upd[prnum_idx][ll]
                                    / (prb_ill[prnum_idx] + 1e-6)
                                )
                                # Constraint on mode 1 only — DM.m L357
                                if ll == 0:
                                    probe_new = apply_probe_contraints(
                                        probe_new, probe_constraint_mode
                                    )

                                probes[:, :, prnum_idx, ll] = (
                                    probe_inertia
                                    * probes_old[:, :, prnum_idx, ll]
                                    + (1 - probe_inertia) * probe_new
                                )

                    # Update object with inertia — DM.m L286, L349
                    if it + 1 >= object_change_start:
                        delta = max_illum * 1e-4   # ptycho_solver.m L275

                        for obnum_idx in range(numobjs):
                            denom = obj_ill[obnum_idx] + delta
                            # Expand dims for 3D object (multi-mode)
                            if ob[obnum_idx].ndim == 3:
                                denom = denom[:, :, None]

                            ob[obnum_idx] = (
                                probe_inertia * ob[obnum_idx]
                                + (1 - probe_inertia)
                                * obj_upd[obnum_idx] / denom
                            )

                            # Positivity constraint — DM.m L289
                            pos_c = p.get('positivity_constraint_object', 0)
                            if pos_c != 0:
                                ob[obnum_idx] = (
                                    pos_c * cp.maximum(0, cp.real(ob[obnum_idx]))
                                    + (1 - pos_c) * ob[obnum_idx]
                                )

                            # Flat region
                            if p['userflatregion']:
                                ob_cpu = _to_cpu(ob[obnum_idx])
                                ob_cpu[p['userflatind']] = np.mean(
                                    ob_cpu[p['userflatind']]
                                )
                                ob[obnum_idx] = _to_gpu(ob_cpu)

                    # Convergence check — DM.m L369-377
                    if it + 1 >= probe_change_start:
                        prch = float(cp.sqrt(
                            cp.sum(cp.abs(probes - probes_old)**2)
                            / (cp.sum(cp.abs(probes_old)**2) + 1e-30)
                        ))
                        # min 2 inner iterations when keep_on_gpu — DM.m
                        if prch < 0.01 and inner >= 1:
                            breakprobeloop = True

            # === 4. Fourier DM loop — DM.m L390-450 ===
            iter_scans, er2 = fourier_dm_loop(
                p, ob, probes, iter_scans, fmag_scans, obj_proj=obj_proj
            )

            # === 5. Error metric ===
            total_numpts = (sum(numpts) if isinstance(numpts, list)
                           else int(numpts))
            err[it] = 2 * np.sqrt(er2 / (np.prod(asize) * total_numpts))
            verbose(3, f'GPU DM Error: {err[it]:12.3f}')

            # === 6. Object averaging — ptycho_solver.m L372-380 ===
            average_start = p.get(
                'average_start', int(0.9 * number_iterations) + 1
            )
            if it + 1 >= average_start:
                for obnum_idx in range(numobjs):
                    avob[obnum_idx] += ob[obnum_idx]
                numav += 1

            # === 7. Probe orthogonalization — ptycho_solver.m L359-383 ===
            # DM: ONLY at the final iteration — probe_modes_ortho.m
            if probe_modes > 1 and it == number_iterations - 1:
                for prnum_idx in range(numprobs):
                    P = probes[:, :, prnum_idx, :]   # (Ny, Nx, Nmodes)
                    N = probe_modes

                    # Gram matrix A = M^H M — probe_modes_ortho.m L100-106
                    # MATLAB dot(A,B) = sum(conj(A).*B) — conj on FIRST
                    A = cp.zeros((N, N), dtype=complex)
                    for i in range(N):
                        for j in range(N):
                            A[i, j] = cp.sum(
                                cp.conj(P[:, :, i]) * P[:, :, j]
                            )

                    # Eigendecomposition + sort descending — L108-111
                    eigenvalues, eigenvectors = cp.linalg.eigh(A)
                    idx = cp.argsort(eigenvalues)[::-1]

                    # Orthogonal mode construction — L114-119
                    P_ortho = cp.zeros_like(P)
                    for j in range(N):
                        for i in range(N):
                            P_ortho[:, :, j] += (
                                P[:, :, i] * eigenvectors[i, idx[j]]
                            )

                    probes[:, :, prnum_idx, :] = P_ortho

                verbose(2, 'GPU DM: Probe modes orthogonalized')

            # Error metric in p
            p['error_metric'] = {
                'iteration': np.arange(1, it + 2),
                'value': err[:it + 1],
                'err_metric': 'RMS',
                'method': p.get('name', 'DM_GPU')
            }

            # === 8. Callback ===
            _cb = p.get('_iteration_callback')
            if _cb:
                _cb_data = {
                    'type': 'iteration_update', 'engine': 'DM',
                    'iteration': it + 1,
                    'total_iterations': number_iterations,
                    'error': float(err[it]),
                }
                _user_pi = p.get('preview_interval', 0)
                _preview_interval = (_user_pi if _user_pi > 0
                                     else max(5, number_iterations // 5))
                if ((it + 1) % _preview_interval == 0
                        or it == number_iterations - 1):
                    _cb_data['include_preview'] = True
                    _cb_data['object'] = _to_cpu(ob[0])
                    _cb_data['probes'] = _to_cpu(probes)
                _cb(_cb_data)

            _ce = p.get('_cancel_event')
            if _ce and _ce.is_set():
                verbose(2, 'GPU DM cancelled at iteration %d' % (it + 1))
                break

        # ====== Post-processing ======

        verbose(3, 'GPU DM: Finished difference map')

        for obnum_idx in range(numobjs):
            if numav > 0:
                avob[obnum_idx] = avob[obnum_idx] / numav
            else:
                avob[obnum_idx] = ob[obnum_idx]

        # GPU → CPU
        probes = _to_cpu(probes)
        ob = [_to_cpu(o) for o in ob]
        avob = [_to_cpu(a) for a in avob]
        if isinstance(p.get('fmask'), cp.ndarray):
            p['fmask'] = _to_cpu(p['fmask'])

        p['probes'] = probes
        p['object'] = ob
        p['object_avg'] = avob

        fdb['status'] = 'completed'
        fdb['error'] = err
        fdb['iterations'] = number_iterations

    finally:
        set_use_gpu(False)

    return p, fdb
