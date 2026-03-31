"""
GPU-accelerated Iterative Least-Squares Maximum-Likelihood (LSQML) ptychography engine.

Based on MATLAB +engines/+GPU/LSQML.m

Reference:
    Odstrčil et al., "Iterative least-squares solver for generalized maximum-
    likelihood ptychography," Optics Express 26(3), 3108 (2018).
    doi: 10.1364/OE.26.003108
"""
import numpy as np
from .gpu_wrapper import (
    Garray, Gzeros, Gfun, Ggather, norm2, sum2, set_use_gpu, USE_GPU, GPU_AVAILABLE
)
from .shared import (
    fwd_fourier_proj, back_fourier_proj,
    modulus_constraint, get_reciprocal_model,
    gradient_position_solver, apply_position_update,
)

if GPU_AVAILABLE:
    import cupy as cp


def LSQML(p, ob, probes, fmag, positions, num_iterations=10, return_positions=False):
    """
    LSQML reconstruction algorithm (simplified GPU version).

    Parameters
    ----------
    p : dict
        - probe_modes, object_modes
        - probe_change_start, object_change_start
        - beta_LSQ: LSQ step scaling (default 0.9)
        - beta_probe: probe step (default 1.0)
        - beta_object: object step (default 1.0)
        - pfft_relaxation: Fourier relaxation (default 0.05)
        - probe_position_search: int, iteration to start position refinement (0=disabled)
        - use_gpu: bool
    ob : list of ndarrays  [Ny_o, Nx_o]
    probes : ndarray        [Ny_p, Nx_p] (single mode) or [Ny_p, Nx_p, Nmodes] (multimode)
    fmag : ndarray          [Ny_p, Nx_p, Npos]
    positions : ndarray     [Npos, 2]  (row, col)
    num_iterations : int
    return_positions : bool
        If True, also return the final (potentially refined) positions array.

    Returns
    -------
    ob, probes, fourier_error  [, positions_final if return_positions=True]
    probes returned with same ndim as input (2D single-mode or 3D multimode).
    """
    if 'use_gpu' in p:
        set_use_gpu(p['use_gpu'])

    # Parameters
    probe_change_start = p.get('probe_change_start', 1)
    object_change_start = p.get('object_change_start', 1)
    beta_LSQ = p.get('beta_LSQ', 0.9)
    beta_probe_scale = p.get('beta_probe', 1.0)
    beta_object_scale = p.get('beta_object', 1.0)
    pfft_relaxation = p.get('pfft_relaxation', 0.05)
    delta_p = p.get('delta_p', 0.1)
    probe_position_search = p.get('probe_position_search', 0)  # 0 = disabled

    # Dimensions
    Np_p = [probes.shape[0], probes.shape[1]]
    Np_o = [ob[0].shape[0], ob[0].shape[1]]
    Npos = positions.shape[0]

    # Multimode: always work with (Ny, Nx, Nmodes) internally
    single_mode_input = (probes.ndim == 2)
    if single_mode_input:
        probes = probes[:, :, np.newaxis]   # (Ny, Nx, 1)
    Nmodes = probes.shape[2]

    # Move to GPU
    if USE_GPU and GPU_AVAILABLE:
        ob = [Garray(o) for o in ob]
        probes = Garray(probes)
        fmag = Garray(fmag)
        positions = Garray(positions)

    fourier_error = np.zeros(num_iterations + 1)
    mode = {'distances': [np.inf]}

    # ============================================================
    # Iter 0: probe amplitude correction
    # ============================================================
    print(f"[Iter 0] Probe amplitude correction... (Nmodes={Nmodes})")
    probe_amp = [0.0, 0.0]

    for ii in range(Npos):
        pos = positions[ii]
        obj_view = _get_view(ob[0], pos, Np_p)
        modF = fmag[:, :, ii]

        # Incoherent sum over modes
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
    probes = probes * corr   # scale all modes uniformly
    print(f"  Probe amplitude corrected by {corr:.4f}")

    # Cache: illumination sum for object preconditioning
    if USE_GPU and GPU_AVAILABLE:
        xp = cp
    else:
        xp = np

    illum_sum = xp.zeros(Np_o, dtype=np.float32)
    for ii in range(Npos):
        pos = positions[ii]
        pos_np = cp.asnumpy(pos) if USE_GPU and GPU_AVAILABLE else pos
        r, c = int(round(float(pos_np[0]))), int(round(float(pos_np[1])))
        # Sum illumination over all probe modes
        for m in range(Nmodes):
            illum_sum[r:r+Np_p[0], c:c+Np_p[1]] += xp.abs(probes[:, :, m])**2
    MAX_ILLUM = float(xp.max(illum_sum)) if hasattr(xp, 'max') else float(np.max(illum_sum))

    # ============================================================
    # Main LSQML iterations
    # ============================================================
    for iter in range(1, num_iterations + 1):
        print(f"[Iter {iter}/{num_iterations}]")

        if USE_GPU and GPU_AVAILABLE:
            xp = cp
        else:
            xp = np

        # Error accumulation
        err_num = 0.0   # sum |aPsi - modF|^2
        err_den = 0.0   # sum |modF|^2

        # Accumulators
        obj_update = xp.zeros(Np_o, dtype=np.complex64)
        obj_illum = xp.zeros(Np_o, dtype=np.float32)

        beta_probe_all = xp.zeros(Npos, dtype=np.float32)
        beta_object_all = xp.zeros(Npos, dtype=np.float32)

        # Per-mode probe updates
        probe_update_sum = xp.zeros(list(Np_p) + [Nmodes], dtype=np.complex64)
        probe_illum_sum = xp.zeros(Np_p, dtype=np.float32)  # shared across modes

        # Stores for position refinement (use mode 0 for gradient)
        xi_list = []       # chi_rs per position (mode 0)
        O_views_list = []  # object views per position

        # --------------------------------------------------------
        # Per-position LSQ step calculations (for beta estimation)
        # --------------------------------------------------------
        for ii in range(Npos):
            pos = positions[ii]
            obj_view = _get_view(ob[0], pos, Np_p)
            modF = fmag[:, :, ii]

            # Forward model: incoherent superposition over modes
            Psi_list = []
            for m in range(Nmodes):
                psi_m = obj_view * probes[:, :, m]
                Psi_m = fwd_fourier_proj(psi_m, mode)
                Psi_list.append(Psi_m)
            aPsi = get_reciprocal_model(Psi_list)  # sqrt(sum_m |Psi_m|^2)

            # Accumulate Fourier error
            diff2 = (aPsi - modF)**2
            if USE_GPU and GPU_AVAILABLE:
                err_num += float(Ggather(xp.sum(diff2)))
                err_den += float(Ggather(xp.sum(modF**2)))
            else:
                err_num += float(np.sum(diff2))
                err_den += float(np.sum(modF**2))

            # Modulus constraint (applied simultaneously to all modes)
            constrained_list = modulus_constraint(modF, aPsi, Psi_list, mask=None,
                                                  relaxation=pfft_relaxation)

            # Per-mode residuals and back-propagation
            chi_rs_list = []
            dO_total = xp.zeros(Np_p, dtype=np.complex64)
            for m in range(Nmodes):
                chi_m = constrained_list[m] - Psi_list[m]   # Fourier-space residual
                chi_rs_m = back_fourier_proj(chi_m, mode)    # real-space residual
                chi_rs_list.append(chi_rs_m)
                dO_total += chi_rs_m * xp.conj(probes[:, :, m])   # object gradient (sum modes)

            # Use mode-0 chi_rs for posref store
            chi_rs = chi_rs_list[0]
            dO = dO_total

            # Store for position refinement (mode 0)
            if probe_position_search > 0:
                xi_list.append(Ggather(chi_rs).astype(np.complex64))
                O_views_list.append(Ggather(obj_view).astype(np.complex64))

            # Optimal LSQ step (Odstrčil 2018 eq.16-17, mode-0 approximation).
            # FIX: dO_mode0 = chi_rs_0 * conj(P_0) to keep self-consistent with P_0.
            # Using dO_total (all modes) with P_0 gave 3x over-estimated beta_object.
            if beta_LSQ > 0 and iter >= probe_change_start and iter >= object_change_start:
                dO_mode0 = chi_rs_list[0] * xp.conj(probes[:, :, 0])  # mode-0 only, consistent
                dP0 = chi_rs_list[0] * xp.conj(obj_view)
                bp, bo = _get_optimal_lsq_step(chi_rs_list[0], dO_mode0, dP0, obj_view,
                                                probes[:, :, 0], beta_LSQ)
                beta_probe_all[ii] = beta_probe_scale * bp
                beta_object_all[ii] = beta_object_scale * bo
            else:
                beta_probe_all[ii] = beta_probe_scale
                beta_object_all[ii] = beta_object_scale

            # Accumulate probe update (per mode)
            if iter >= probe_change_start:
                for m in range(Nmodes):
                    probe_update_sum[:, :, m] += chi_rs_list[m] * xp.conj(obj_view)
                probe_illum_sum += xp.abs(obj_view)**2

            # Accumulate object update
            if iter >= object_change_start:
                r_np = int(round(float(Ggather(pos[0]) if USE_GPU and GPU_AVAILABLE else pos[0])))
                c_np = int(round(float(Ggather(pos[1]) if USE_GPU and GPU_AVAILABLE else pos[1])))
                # FIX: dO = dO_total already sums Nmodes contributions; beta was computed
                # from mode-0 only (MATLAB LSQML.m line 302: beta_object /= par.probe_modes).
                # Without this division, with Nmodes=3 we get 3x overshoot per iteration.
                obj_update[r_np:r_np+Np_p[0], c_np:c_np+Np_p[1]] += (
                    dO * beta_object_all[ii] / Nmodes
                )
                for m in range(Nmodes):
                    obj_illum[r_np:r_np+Np_p[0], c_np:c_np+Np_p[1]] += (
                        xp.abs(probes[:, :, m])**2
                    )

        # --------------------------------------------------------
        # Apply updates
        # --------------------------------------------------------
        # Object update with preconditioning
        if iter >= object_change_start:
            if delta_p > 0:
                # FIX: standard Tikhonov preconditioning (Odstrčil 2018).
                # Previous sqrt(obj_illum^2 + ...) was overly aggressive in
                # low-illumination regions, causing large spurious updates.
                denom = obj_illum + delta_p * MAX_ILLUM
                ob[0] = ob[0] + obj_update / (denom + 1e-10)
            else:
                ob[0] = ob[0] + obj_update / (obj_illum + 1e-6)

            # NOTE: amplitude clipping (|T| <= 1) removed.
            # It caused catastrophic quality degradation: synthetic-data objects
            # are not normalized to unit amplitude, so clipping every iteration
            # systematically destroyed the reconstruction.

        # Probe update (mean over all positions, per mode)
        if iter >= probe_change_start:
            beta_probe_mean = float(xp.mean(beta_probe_all))
            illum_denom = probe_illum_sum + 1e-6
            for m in range(Nmodes):
                probe_new_m = probe_update_sum[:, :, m] / illum_denom
                probes[:, :, m] = probes[:, :, m] + beta_probe_mean * probe_new_m

        # --------------------------------------------------------
        # Position refinement (after object/probe updates)
        # --------------------------------------------------------
        if probe_position_search > 0 and len(xi_list) > 0:
            xi_all = np.stack(xi_list, axis=0)        # [N_pos, Ny, Nx]
            O_views_all = np.stack(O_views_list, axis=0)  # [N_pos, Ny, Nx]
            P_cpu = Ggather(probes[:, :, 0]).astype(np.complex64)  # mode 0 for posref

            pos_update = gradient_position_solver(
                xi_all, O_views_all, P_cpu,
                probe_position_search=probe_position_search,
                iter_num=iter
            )

            positions_np = Ggather(positions).astype(np.float32) if USE_GPU and GPU_AVAILABLE else np.asarray(positions, dtype=np.float32)
            positions_np = apply_position_update(positions_np, pos_update, tuple(Np_o), tuple(Np_p))

            if USE_GPU and GPU_AVAILABLE:
                positions = Garray(positions_np)
            else:
                positions = positions_np

        # Fourier error for this iteration
        iter_error = err_num / (err_den + 1e-30)
        fourier_error[iter] = iter_error

        # Average beta info
        bp_avg = float(xp.mean(beta_probe_all))
        bo_avg = float(xp.mean(beta_object_all))
        print(f"  error={iter_error:.6f}, beta_probe={bp_avg:.4f}, beta_object={bo_avg:.4f}")

        # Iteration callback (for WebSocket UI)
        _cb = p.get('_iteration_callback')
        if _cb:
            _cb_data = {
                'type': 'iteration_update', 'engine': 'LSQML',
                'iteration': iter, 'total_iterations': num_iterations,
                'error': iter_error,
            }
            _user_pi = p.get('preview_interval', 0)
            _preview_interval = _user_pi if _user_pi > 0 else max(1, num_iterations // 20)
            if iter % _preview_interval == 0 or iter == num_iterations:
                _cb_data['include_preview'] = True
                _cb_data['object'] = Ggather(ob[0]) if USE_GPU and GPU_AVAILABLE else ob[0]
                _cb_data['probes'] = Ggather(probes) if USE_GPU and GPU_AVAILABLE else probes
            _cb(_cb_data)
        _ce = p.get('_cancel_event')
        if _ce and _ce.is_set():
            print(f'  LSQML cancelled by user at iteration {iter}')
            break

    # Gather
    if USE_GPU and GPU_AVAILABLE:
        ob = [Ggather(o) for o in ob]
        probes = Ggather(probes)

    # Squeeze back to 2D if input was single-mode (backward compatibility)
    if single_mode_input:
        probes = probes[:, :, 0]

    # Final positions (CPU float32)
    positions_final = Ggather(positions).astype(np.float32) if USE_GPU and GPU_AVAILABLE \
                      else np.asarray(positions, dtype=np.float32)

    # Reset GPU flag to prevent state leaking to subsequent engines
    set_use_gpu(False)

    print("[LSQML Complete]")
    if return_positions:
        return ob, probes, fourier_error, positions_final
    return ob, probes, fourier_error


def _get_view(obj, pos, Np_p):
    """Extract object view at position."""
    if USE_GPU and GPU_AVAILABLE:
        pos = cp.asnumpy(pos) if isinstance(pos, cp.ndarray) else pos
    r = int(round(float(pos[0])))
    c = int(round(float(pos[1])))
    return obj[r:r+Np_p[0], c:c+Np_p[1]]


def _get_optimal_lsq_step(chi_rs, dO, dP, O, P, beta_LSQ):
    """
    Compute optimal probe and object step lengths via coupled 2x2 LSQ.

    Port of MATLAB +engines/+GPU/+LSQML/get_optimal_LSQ_step.m (lines 88-125).
    Solves the coupled system:

        [AA1+lam,  AA2  ] [beta_O]   [Atb1]
        [AA2*,   AA4+lam] [beta_P] = [Atb2]

    where:
        AA1 = sum(|dOP|^2),  AA4 = sum(|dPO|^2)
        AA2 = sum(conj(dOP) * dPO)      (cross-term)
        Atb1 = sum(conj(dOP) * chi),  Atb2 = sum(conj(dPO) * chi)
        lam = 0.5 (Tikhonov regularization on diagonal)

    Returns
    -------
    beta_probe, beta_object : float
    """
    def _to_f64(arr):
        if USE_GPU and GPU_AVAILABLE:
            return cp.asnumpy(arr).astype(np.complex128)
        return np.asarray(arr, dtype=np.complex128)

    chi_64 = _to_f64(chi_rs)
    dO_64  = _to_f64(dO)
    dP_64  = _to_f64(dP)
    O_64   = _to_f64(O)
    P_64   = _to_f64(P)

    dOP = dO_64 * P_64   # object-direction exit-wave perturbation
    dPO = dP_64 * O_64   # probe-direction exit-wave perturbation

    # Build 2x2 normal equation matrix (MATLAB lines 88-100)
    AA1 = float(np.sum(np.abs(dOP) ** 2))       # object self
    AA4 = float(np.sum(np.abs(dPO) ** 2))       # probe self
    AA2 = complex(np.sum(np.conj(dOP) * dPO))   # cross-term

    # Right-hand side
    Atb1 = complex(np.sum(np.conj(dOP) * chi_64))  # object RHS
    Atb2 = complex(np.sum(np.conj(dPO) * chi_64))  # probe RHS

    # Tikhonov regularization (MATLAB: lambda = 0.5)
    lam = 0.5

    # Solve 2x2 system: A * x = b
    # A = [[AA1+lam, AA2], [conj(AA2), AA4+lam]]
    A = np.array([[AA1 + lam, AA2],
                  [np.conj(AA2), AA4 + lam]], dtype=np.complex128)
    b = np.array([Atb1, Atb2], dtype=np.complex128)

    # Safety clamp: if raw LSQ step > MAX_BETA, the linearization is
    # breaking down (e.g., starting from raw DM output).  Clamp to prevent
    # runaway divergence while still allowing the coupled system to work
    # normally when steps are moderate.
    MAX_BETA = 1.0

    try:
        x = np.linalg.solve(A, b)
        beta_object = min(MAX_BETA, max(0.0, float(np.real(x[0])))) * beta_LSQ
        beta_probe  = min(MAX_BETA, max(0.0, float(np.real(x[1])))) * beta_LSQ
    except np.linalg.LinAlgError:
        # Fallback to decoupled if singular
        beta_object = min(MAX_BETA, max(0.0, float(np.real(Atb1)) / (AA1 + lam))) * beta_LSQ
        beta_probe  = min(MAX_BETA, max(0.0, float(np.real(Atb2)) / (AA4 + lam))) * beta_LSQ

    return beta_probe, beta_object
