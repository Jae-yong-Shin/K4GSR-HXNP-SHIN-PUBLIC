"""
GPU-accelerated Extended Ptychographic Iterative Engine (ePIE).

Robust single-engine reconstruction that works from scratch (ones init).
Unlike DM (diverges) or LSQML (needs DM output), ePIE uses simple
per-position sequential updates with proven convergence.

Reference:
    Maiden & Rodenburg, "An improved ptychographical phase retrieval
    algorithm for diffractive imaging," Ultramicroscopy 109(10), 1256 (2009).

Update equations:
    psi = O[roi] * P
    Psi = FFT(psi)
    Psi_c = modulus_constraint(Psi, fmag)
    psi_c = IFFT(Psi_c)
    delta = psi_c - psi

    O[roi] += alpha_o * conj(P) / (max(|P|^2) + eps) * delta
    P      += alpha_p * conj(O[roi]) / (max(|O[roi]|^2) + eps) * delta

where alpha_o, alpha_p are step sizes (typically 1.0).
"""

import numpy as np
import time
import sys as _sys
from .gpu_wrapper import (
    Garray, Gzeros, Gfun, Ggather, norm2, sum2, set_use_gpu, USE_GPU, GPU_AVAILABLE
)
from .shared import (
    fft2_safe, ifft2_safe,
    fwd_fourier_proj, back_fourier_proj,
    modulus_constraint, get_reciprocal_model,
)

if GPU_AVAILABLE:
    import cupy as cp


def ePIE(p, ob, probes, fmag, positions, num_iterations=10, return_positions=False):
    """
    ePIE reconstruction algorithm.

    Parameters
    ----------
    p : dict
        - probe_change_start: iteration to start probe update (default 1)
        - object_change_start: iteration to start object update (default 1)
        - alpha_object: object step size (default 1.0)
        - alpha_probe: probe step size (default 1.0)
        - pfft_relaxation: Fourier relaxation parameter (default 0.05)
        - use_gpu: bool
    ob : list of ndarrays  [Ny_o, Nx_o]
    probes : ndarray        [Ny_p, Nx_p] (single mode) or [Ny_p, Nx_p, Nmodes]
    fmag : ndarray          [Ny_p, Nx_p, Npos]
    positions : ndarray     [Npos, 2]  (row, col)
    num_iterations : int
    return_positions : bool

    Returns
    -------
    ob, probes, fourier_error  [, positions if return_positions]
    """
    if 'use_gpu' in p:
        set_use_gpu(p['use_gpu'])

    # Parameters
    probe_change_start = p.get('probe_change_start', 1)
    object_change_start = p.get('object_change_start', 1)
    alpha_o = p.get('alpha_object', 1.0)
    alpha_p = p.get('alpha_probe', 1.0)
    pfft_relaxation = p.get('pfft_relaxation', 0.05)

    # Dimensions
    Np_p = [probes.shape[0], probes.shape[1]]
    Np_o = [ob[0].shape[0], ob[0].shape[1]]
    Npos = positions.shape[0]

    # Multimode support
    single_mode_input = (probes.ndim == 2)
    if single_mode_input:
        probes = probes[:, :, np.newaxis]
    Nmodes = probes.shape[2]

    # Move to GPU
    if USE_GPU and GPU_AVAILABLE:
        ob = [Garray(o) for o in ob]
        probes = Garray(probes)
        fmag = Garray(fmag)
        positions = Garray(positions)

    fourier_error = np.zeros(num_iterations + 1)
    mode = {'distances': [np.inf]}

    # xp shorthand
    xp = cp if (USE_GPU and GPU_AVAILABLE) else np

    # ============================================================
    # Iter 0: Probe amplitude correction
    # ============================================================
    print(f"[ePIE] Npos={Npos}, asize={Np_p}, obj={Np_o}, modes={Nmodes}, iters={num_iterations}")
    _sys.stdout.flush()

    probe_amp = [0.0, 0.0]
    for ii in range(Npos):
        pos = positions[ii]
        obj_view = _get_view(ob[0], pos, Np_p)
        modF = fmag[:, :, ii]
        Psi_list = []
        for m in range(Nmodes):
            psi_m = obj_view * probes[:, :, m]
            Psi_m = fwd_fourier_proj(psi_m, mode)
            Psi_list.append(Psi_m)
        aPsi = get_reciprocal_model(Psi_list)

        if USE_GPU and GPU_AVAILABLE:
            probe_amp[0] += float(Ggather(sum2(modF**2)))
            probe_amp[1] += float(Ggather(sum2(aPsi**2)))
        else:
            probe_amp[0] += float(np.sum(modF**2))
            probe_amp[1] += float(np.sum(aPsi**2))

    corr = np.sqrt(probe_amp[0] / probe_amp[1])
    probes = probes * corr
    print(f"  Probe amplitude corrected by {corr:.4f}")

    # Save initial probe power for normalization
    probe_power_init = float(Ggather(sum2(xp.abs(probes)**2))) if USE_GPU and GPU_AVAILABLE \
                       else float(np.sum(np.abs(probes)**2))

    # Iteration callback / cancel support
    _cb = p.get('_iteration_callback')
    _ce = p.get('_cancel_event')
    _preview_interval = max(5, num_iterations // 5)

    # ============================================================
    # Main ePIE iterations
    # ============================================================
    _t0 = time.time()
    for it in range(1, num_iterations + 1):
        _iter_t0 = time.time()

        err_num = 0.0
        err_den = 0.0

        # Randomize position order each iteration (helps convergence)
        if USE_GPU and GPU_AVAILABLE:
            order = np.random.permutation(Npos)
        else:
            order = np.random.permutation(Npos)

        for idx in range(Npos):
            ii = order[idx]
            pos = positions[ii]
            obj_view = _get_view(ob[0], pos, Np_p)
            modF = fmag[:, :, ii]

            # Forward model: incoherent sum over modes
            Psi_list = []
            psi_list = []
            for m in range(Nmodes):
                psi_m = obj_view * probes[:, :, m]
                Psi_m = fwd_fourier_proj(psi_m, mode)
                psi_list.append(psi_m)
                Psi_list.append(Psi_m)
            aPsi = get_reciprocal_model(Psi_list)

            # Fourier error
            diff2 = (aPsi - modF)**2
            if USE_GPU and GPU_AVAILABLE:
                err_num += float(Ggather(xp.sum(diff2)))
                err_den += float(Ggather(xp.sum(modF**2)))
            else:
                err_num += float(np.sum(diff2))
                err_den += float(np.sum(modF**2))

            # Modulus constraint
            Psi_c_list = modulus_constraint(modF, aPsi, Psi_list, mask=None,
                                            relaxation=pfft_relaxation)

            # Back-propagate and apply ePIE updates
            for m in range(Nmodes):
                chi_m = Psi_c_list[m] - Psi_list[m]
                delta_m = back_fourier_proj(chi_m, mode)

                # Object update: O += alpha_o * conj(P) / max(|P|^2) * delta
                if it >= object_change_start:
                    P_m = probes[:, :, m]
                    P_abs2_max = float(Ggather(xp.max(xp.abs(P_m)**2))) if USE_GPU and GPU_AVAILABLE \
                                 else float(np.max(np.abs(P_m)**2))
                    obj_upd = alpha_o * xp.conj(P_m) / (P_abs2_max + 1e-10) * delta_m
                    _set_view_add(ob[0], pos, Np_p, obj_upd)

                # Probe update: P += alpha_p * conj(O) / max(|O|^2) * delta
                if it >= probe_change_start:
                    # Re-read obj_view after object update
                    obj_view_new = _get_view(ob[0], pos, Np_p)
                    O_abs2_max = float(Ggather(xp.max(xp.abs(obj_view_new)**2))) if USE_GPU and GPU_AVAILABLE \
                                 else float(np.max(np.abs(obj_view_new)**2))
                    probe_upd = alpha_p * xp.conj(obj_view_new) / (O_abs2_max + 1e-10) * delta_m
                    probes[:, :, m] = probes[:, :, m] + probe_upd

        # Fourier error
        if err_den > 0:
            fourier_error[it] = err_num / err_den

        # Probe power normalization (prevent scaling drift)
        if it >= probe_change_start and probe_power_init > 0:
            cur_power = float(Ggather(sum2(xp.abs(probes)**2))) if USE_GPU and GPU_AVAILABLE \
                        else float(np.sum(np.abs(probes)**2))
            if cur_power > 0:
                scale = np.sqrt(probe_power_init / cur_power)
                probes = probes * scale
                ob[0] = ob[0] / scale

        _iter_dt = time.time() - _iter_t0
        _elapsed = time.time() - _t0
        _eta = _iter_dt * (num_iterations - it)
        _err = fourier_error[it]
        if it <= 3 or it % 10 == 0 or it == num_iterations:
            print(f"  [ePIE {it}/{num_iterations}] err={_err:.4e} | {_iter_dt:.1f}s/iter | "
                  f"elapsed {_elapsed:.0f}s | ETA {_eta:.0f}s")
            _sys.stdout.flush()

        # Iteration callback
        if _cb:
            _cb_data = {
                'type': 'iteration_update', 'engine': 'ePIE',
                'iteration': it, 'total_iterations': num_iterations,
                'error': float(_err) if _err != 0 else 0.0,
            }
            if it % _preview_interval == 0 or it == num_iterations:
                _cb_data['include_preview'] = True
                _cb_data['object'] = Ggather(ob[0]) if USE_GPU and GPU_AVAILABLE else ob[0]
                _cb_data['probes'] = Ggather(probes) if USE_GPU and GPU_AVAILABLE else probes
            _cb(_cb_data)
        if _ce and _ce.is_set():
            print(f'  ePIE cancelled at iteration {it}')
            break

    # Gather from GPU
    if USE_GPU and GPU_AVAILABLE:
        ob = [Ggather(o) for o in ob]
        probes = Ggather(probes)

    # Squeeze back to 2D if input was single-mode
    if single_mode_input:
        probes = probes[:, :, 0]

    positions_final = Ggather(positions).astype(np.float32) if USE_GPU and GPU_AVAILABLE \
                      else np.asarray(positions, dtype=np.float32)

    print("[ePIE Complete]")
    if return_positions:
        return ob, probes, fourier_error, positions_final
    return ob, probes, fourier_error


def _get_view(obj, pos, Np_p):
    """Extract object view at position."""
    if USE_GPU and GPU_AVAILABLE:
        pos = cp.asnumpy(pos) if isinstance(pos, cp.ndarray) else pos
    r = int(np.round(float(pos[0])))
    c = int(np.round(float(pos[1])))
    return obj[r:r+Np_p[0], c:c+Np_p[1]]


def _set_view_add(obj, pos, Np_p, update):
    """Add update to object view at position (in-place)."""
    if USE_GPU and GPU_AVAILABLE:
        pos = cp.asnumpy(pos) if isinstance(pos, cp.ndarray) else pos
    r = int(np.round(float(pos[0])))
    c = int(np.round(float(pos[1])))
    obj[r:r+Np_p[0], c:c+Np_p[1]] += update
