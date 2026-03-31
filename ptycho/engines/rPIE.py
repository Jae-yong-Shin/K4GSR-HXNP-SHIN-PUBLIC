"""
rPIE — regularized Ptychographic Iterative Engine

Sequential per-position reconstruction with:
- Wiener-filter denominator (rPIE regularization)
- Multi-mode probe (partial coherence)
- Gradient-based position refinement
- Soft circular probe support
- Object/probe inertia damping
- Best-result tracking

Setting alpha=1, beta=1 reduces to standard ePIE.

References:
    Maiden, A.M. & Rodenburg, J.M., "An improved ptychographical phase
    retrieval algorithm for diffractive imaging," Ultramicroscopy 109,
    1256-1262 (2009). [ePIE]

    Maiden, A., Johnson, D., Li, P., "Further improvements to the
    ptychographical iterative engine," Optica 4(7), 736-745 (2017). [rPIE]

    Thibault, P. & Menzel, A., "Reconstructing state mixtures from
    diffraction measurements," Nature 494, 68-71 (2013). [multi-mode]
"""

import numpy as np
import time


def rPIE(p, ob, probes, fmag, positions,
         num_iterations=200, alpha=0.5, beta=0.5,
         probe_support_radius=0.9, obj_inertia=0.01,
         probe_inertia=0.0, n_probe_modes=1,
         position_refine_start=0, mode_seed_power=0.01,
         obj_amp_clip=None, track_best=True, fmask=None,
         mode_start_iter=20):
    """
    Run rPIE reconstruction.

    Args:
        p: parameter dict (carries _iteration_callback, _cancel_event, use_gpu)
        ob: list of 2D complex arrays [object]
        probes: 2D or 3D complex array (Ny, Nx) or (Ny, Nx, Nmodes)
        fmag: (Ny, Nx, Npos) float — Fourier magnitudes (DC at corner)
        positions: (Npos, 2) float — [row, col] in pixels
        num_iterations: number of iterations
        alpha: object regularization (0=aggressive, 1=ePIE)
        beta: probe regularization (0=aggressive, 1=ePIE)
        probe_support_radius: soft mask radius (fraction of half-width)
        obj_inertia: damping (fraction of previous object retained)
        probe_inertia: damping (fraction of previous probe retained)
        n_probe_modes: number of incoherent probe modes
        position_refine_start: iteration to start position refinement (0=off)
        mode_seed_power: initial power fraction for secondary modes
        obj_amp_clip: clip object amplitude (None=off)
        track_best: return result at minimum error iteration
        fmask: (Ny, Nx) or (Ny, Nx, Npos) float mask (1=good, 0=bad)
        mode_start_iter: iteration to activate secondary probe modes (default 20)

    Returns:
        (ob_list, probes_array, error_list)
        ob_list: list of 2D complex arrays
        probes_array: (Ny, Nx) or (Ny, Nx, Nmodes) complex
        error_list: list of normalized errors per iteration
    """
    use_gpu = p.get('use_gpu', False)
    _cb = p.get('_iteration_callback')
    _ce = p.get('_cancel_event')
    engine_label = p.get('_engine_label', 'rPIE')

    if use_gpu:
        return _rPIE_gpu(
            p, ob, probes, fmag, positions, num_iterations,
            alpha, beta, probe_support_radius, obj_inertia,
            probe_inertia, n_probe_modes, position_refine_start,
            mode_seed_power, obj_amp_clip, track_best, fmask,
            mode_start_iter, _cb, _ce, engine_label)
    else:
        return _rPIE_cpu(
            p, ob, probes, fmag, positions, num_iterations,
            alpha, beta, probe_support_radius, obj_inertia,
            probe_inertia, n_probe_modes, position_refine_start,
            mode_seed_power, obj_amp_clip, track_best, fmask,
            mode_start_iter, _cb, _ce, engine_label)


# ──────────────────────────── helpers ────────────────────────────

def _make_probe_support(asize, radius_frac, xp):
    """Soft circular probe support mask with Gaussian taper."""
    ny, nx = asize
    Y, X = np.mgrid[-ny // 2:ny // 2, -nx // 2:nx // 2]
    R = np.sqrt(X ** 2 + Y ** 2)
    support_radius = radius_frac * ny / 2
    ps = np.ones(asize, dtype=np.float64)
    outside = R > support_radius
    ps[outside] = np.exp(-((R[outside] - support_radius) / 3.0) ** 2)
    return xp.asarray(ps) if xp is not np else ps


def _init_modes(probe0, n_modes, seed_power, asize, xp):
    """Initialize probe modes array: mode0 = given probe, rest = noise.
    Always generates noise on CPU with fixed seed for reproducibility."""
    probes = xp.zeros((n_modes, asize[0], asize[1]), dtype=probe0.dtype)
    probes[0] = probe0
    if xp is np:
        p0_power = float(np.sum(np.abs(probe0) ** 2))
    else:
        p0_power = float(xp.sum(xp.abs(probe0) ** 2))
    mode_rng = np.random.RandomState(12345)
    for m in range(1, n_modes):
        noise_np = mode_rng.randn(*asize) + 1j * mode_rng.randn(*asize)
        target_pwr = p0_power * seed_power
        noise_np *= np.sqrt(target_pwr / (np.sum(np.abs(noise_np) ** 2) + 1e-20))
        probes[m] = xp.asarray(noise_np) if xp is not np else noise_np
    return probes


def _orthogonalize_modes(probes, n_modes, asize, xp):
    """SVD-based orthogonalization, sorted by power (always on CPU)."""
    if xp is np:
        P_mat = probes.reshape(n_modes, -1)
    else:
        P_mat = xp.asnumpy(probes).reshape(n_modes, -1)
    U, S, Vh = np.linalg.svd(P_mat, full_matrices=False)
    P_ortho = (np.diag(S) @ Vh).reshape(n_modes, asize[0], asize[1])
    pwr = np.sum(np.abs(P_ortho) ** 2, axis=(1, 2))
    P_ortho = P_ortho[np.argsort(-pwr)]
    if xp is np:
        return P_ortho
    return xp.asarray(P_ortho)


# ──────────────────────────── CPU impl ────────────────────────────

def _rPIE_cpu(p, ob, probes_in, fmag, positions_in, num_iterations,
              alpha, beta, probe_support_radius, obj_inertia,
              probe_inertia, n_probe_modes, position_refine_start,
              mode_seed_power, obj_amp_clip, track_best, fmask,
              mode_start_iter, _cb, _ce, engine_label='rPIE'):

    xp = np
    asize = (fmag.shape[0], fmag.shape[1])
    Npos = fmag.shape[2]
    positions = positions_in.copy().astype(np.float64)

    # Object
    obj_2d = ob[0].copy() if isinstance(ob, list) else ob.copy()
    if obj_2d.ndim > 2:
        obj_2d = obj_2d.squeeze()
    obj_h, obj_w = obj_2d.shape

    # Probe initialization
    if probes_in.ndim == 3:
        probe0 = probes_in[:, :, 0].astype(np.complex128)
    elif probes_in.ndim == 2:
        probe0 = probes_in.astype(np.complex128)
    else:
        probe0 = probes_in.squeeze().astype(np.complex128)

    # Probe amplitude correction — scale probe so model intensity matches data
    model_fft = np.fft.fft2(probe0)
    model_intensity = float(np.sum(np.abs(model_fft) ** 2))
    measured_intensity = float(np.mean(np.sum(fmag ** 2, axis=(0, 1))))
    if model_intensity > 0:
        corr = np.sqrt(measured_intensity / model_intensity)
        if abs(corr - 1.0) > 0.1:
            probe0 *= corr
            print(f'  rPIE: Probe amplitude corrected by {corr:.4f}')

    probes = _init_modes(probe0, n_probe_modes, mode_seed_power, asize, xp)

    # Mask
    fmask_2d = fmask if fmask is not None else np.ones(asize, dtype=np.float32)

    # Probe support
    probe_support = _make_probe_support(asize, probe_support_radius, xp)

    # Freq grids for position refinement
    do_pos_refine = position_refine_start > 0
    if do_pos_refine:
        ky = np.fft.fftfreq(asize[0]) * 2j * np.pi
        kx = np.fft.fftfreq(asize[1]) * 2j * np.pi

    pos_corrections = np.zeros((Npos, 2), dtype=np.float64)
    errors = []
    best_error = float('inf')
    best_obj = None
    best_probes = None
    best_iter = 0
    t0 = time.time()
    _user_pi = p.get('preview_interval', 0)
    preview_interval = _user_pi if _user_pi > 0 else max(1, num_iterations // 20)
    rng = np.random.RandomState(42)

    for it in range(1, num_iterations + 1):
        order = rng.permutation(Npos)
        err_sum = 0.0
        obj_prev = obj_2d.copy() if obj_inertia > 0 else None
        probes_prev = probes.copy() if probe_inertia > 0 else None

        # Delayed mode activation: only primary mode until mode_start_iter
        n_active = 1 if (n_probe_modes > 1 and it < mode_start_iter) else n_probe_modes

        for idx in order:
            r = int(round(positions[idx, 0]))
            c = int(round(positions[idx, 1]))
            r = max(0, min(r, obj_h - asize[0]))
            c = max(0, min(c, obj_w - asize[1]))

            obj_patch = obj_2d[r:r + asize[0], c:c + asize[1]]

            # Forward propagation
            I_model = np.zeros(asize, dtype=np.float64)
            psi_modes = np.zeros_like(probes)
            Psi_modes = np.zeros_like(probes)
            for m in range(n_active):
                psi_modes[m] = probes[m] * obj_patch
                Psi_modes[m] = np.fft.fft2(psi_modes[m])
                I_model += np.abs(Psi_modes[m]) ** 2

            I_model_sqrt = np.sqrt(I_model + 1e-20)
            target_mag = fmag[:, :, idx]
            mask = fmask_2d if fmask_2d.ndim == 2 else fmask_2d[:, :, idx]

            err_sum += float(np.sum(mask * (I_model_sqrt - target_mag) ** 2))

            # Modulus constraint
            ratio = mask * target_mag / (I_model_sqrt + 1e-10) + (1 - mask)
            dpsi_modes = np.zeros_like(probes)
            for m in range(n_active):
                Psi_corrected = Psi_modes[m] * ratio
                psi_corrected = np.fft.ifft2(Psi_corrected)
                dpsi_modes[m] = psi_corrected - psi_modes[m]

            # Object update (rPIE Wiener-filter denominator)
            probe_intensity = np.zeros(asize, dtype=np.float64)
            obj_update_num = np.zeros(asize, dtype=np.complex128)
            for m in range(n_active):
                probe_intensity += np.abs(probes[m]) ** 2
                obj_update_num += np.conj(probes[m]) * dpsi_modes[m]
            probe_max2 = np.max(probe_intensity)
            obj_denom = (1 - alpha) * probe_intensity + alpha * probe_max2 + 1e-10
            obj_2d[r:r + asize[0], c:c + asize[1]] += obj_update_num / obj_denom

            # Probe update
            obj_abs2 = np.abs(obj_patch) ** 2
            obj_max2 = np.max(obj_abs2)
            probe_denom = (1 - beta) * obj_abs2 + beta * obj_max2 + 1e-10
            for m in range(n_active):
                probes[m] += np.conj(obj_patch) * dpsi_modes[m] / probe_denom

            # Position refinement
            if do_pos_refine and it >= position_refine_start:
                psi0 = psi_modes[0]
                Psi0 = np.fft.fft2(psi0)
                dpsi_dy = np.fft.ifft2(Psi0 * ky[:, None])
                dpsi_dx = np.fft.ifft2(Psi0 * kx[None, :])
                xi = dpsi_modes[0]
                dy = float(np.real(np.sum(np.conj(dpsi_dy) * xi))) / \
                     (float(np.sum(np.abs(dpsi_dy) ** 2)) + 1e-10)
                dx = float(np.real(np.sum(np.conj(dpsi_dx) * xi))) / \
                     (float(np.sum(np.abs(dpsi_dx) ** 2)) + 1e-10)
                dy = np.clip(dy, -0.5, 0.5)
                dx = np.clip(dx, -0.5, 0.5)
                new_r = np.clip(pos_corrections[idx, 0] + dy, -3.0, 3.0)
                new_c = np.clip(pos_corrections[idx, 1] + dx, -3.0, 3.0)
                positions[idx, 0] += (new_r - pos_corrections[idx, 0])
                positions[idx, 1] += (new_c - pos_corrections[idx, 1])
                pos_corrections[idx, 0] = new_r
                pos_corrections[idx, 1] = new_c

        # Post-iteration constraints
        for m in range(n_active):
            probes[m] *= probe_support

        if probe_inertia > 0 and probes_prev is not None:
            probes = (1 - probe_inertia) * probes + probe_inertia * probes_prev

        if n_active > 1:
            probes = _orthogonalize_modes(probes, n_probe_modes, asize, xp)

        if obj_inertia > 0 and obj_prev is not None:
            obj_2d = (1 - obj_inertia) * obj_2d + obj_inertia * obj_prev

        if obj_amp_clip is not None and obj_amp_clip > 0:
            amp = np.abs(obj_2d)
            too_high = amp > obj_amp_clip
            if np.any(too_high):
                obj_2d[too_high] *= obj_amp_clip / amp[too_high]

        # Normalized error
        total_intensity = float(np.sum(fmag ** 2))
        err_norm = err_sum / (total_intensity + 1e-10)
        errors.append(err_norm)

        # Track best
        if track_best and err_norm < best_error:
            best_error = err_norm
            best_obj = obj_2d.copy()
            best_probes = probes.copy()
            best_iter = it

        # Callback
        if _cb:
            cb_data = {
                'type': 'iteration_update', 'engine': engine_label,
                'iteration': it, 'total_iterations': num_iterations,
                'error': err_norm,
            }
            if it % preview_interval == 0 or it == num_iterations:
                cb_data['include_preview'] = True
                cb_data['object'] = obj_2d
                cb_data['probes'] = probes[0]  # (modes,H,W) → (H,W) primary mode
            _cb(cb_data)

        # Cancel check
        if _ce and _ce.is_set():
            break

    # Restore best
    if track_best and best_obj is not None:
        obj_2d = best_obj
        probes = best_probes

    # Return: (ob_list, probes_ndarray, error_list)
    # probes shape: (Ny, Nx) for single mode, (Ny, Nx, Nmodes) for multi
    if n_probe_modes == 1:
        probes_out = probes[0]
    else:
        probes_out = np.moveaxis(probes, 0, -1)  # (modes,Ny,Nx) -> (Ny,Nx,modes)

    return [obj_2d], probes_out, errors, positions.astype(np.float32)


# ──────────────────────────── GPU impl ────────────────────────────

def _rPIE_gpu(p, ob, probes_in, fmag_np, positions_in, num_iterations,
              alpha, beta, probe_support_radius, obj_inertia,
              probe_inertia, n_probe_modes, position_refine_start,
              mode_seed_power, obj_amp_clip, track_best, fmask_np,
              mode_start_iter, _cb, _ce, engine_label='rPIE'):

    import cupy as cp

    asize = (fmag_np.shape[0], fmag_np.shape[1])
    Npos = fmag_np.shape[2]
    positions = positions_in.copy().astype(np.float64)

    fmag = cp.asarray(fmag_np, dtype=cp.float32)
    fmask = cp.asarray(fmask_np if fmask_np is not None else np.ones(asize, dtype=np.float32))

    # Object
    obj_np = ob[0].copy() if isinstance(ob, list) else ob.copy()
    if obj_np.ndim > 2:
        obj_np = obj_np.squeeze()
    obj_h, obj_w = obj_np.shape
    obj = cp.asarray(obj_np, dtype=cp.complex128)

    # Probe initialization
    if probes_in.ndim == 3:
        probe0_np = probes_in[:, :, 0].astype(np.complex128)
    elif probes_in.ndim == 2:
        probe0_np = probes_in.astype(np.complex128)
    else:
        probe0_np = probes_in.squeeze().astype(np.complex128)

    # Probe amplitude correction — scale probe so model intensity matches data
    model_fft = np.fft.fft2(probe0_np)
    model_intensity = float(np.sum(np.abs(model_fft) ** 2))
    measured_intensity = float(np.mean(np.sum(fmag_np ** 2, axis=(0, 1))))
    if model_intensity > 0:
        corr = np.sqrt(measured_intensity / model_intensity)
        if abs(corr - 1.0) > 0.1:
            probe0_np *= corr
            print(f'  rPIE: Probe amplitude corrected by {corr:.4f}')

    probe0 = cp.asarray(probe0_np)
    probes = _init_modes(probe0, n_probe_modes, mode_seed_power, asize, cp)

    # Probe support
    probe_support = _make_probe_support(asize, probe_support_radius, cp)

    # Freq grids for position refinement
    do_pos_refine = position_refine_start > 0
    if do_pos_refine:
        ky = cp.asarray(np.fft.fftfreq(asize[0]) * 2j * np.pi)
        kx = cp.asarray(np.fft.fftfreq(asize[1]) * 2j * np.pi)

    pos_corrections = np.zeros((Npos, 2), dtype=np.float64)
    errors = []
    best_error = float('inf')
    best_obj_cpu = None
    best_probes_cpu = None
    best_iter = 0
    t0 = time.time()
    _user_pi = p.get('preview_interval', 0)
    preview_interval = _user_pi if _user_pi > 0 else max(1, num_iterations // 20)
    rng = np.random.RandomState(42)

    for it in range(1, num_iterations + 1):
        order = rng.permutation(Npos)
        err_sum = 0.0
        obj_prev = obj.copy() if obj_inertia > 0 else None
        probes_prev = probes.copy() if probe_inertia > 0 else None

        # Delayed mode activation: only primary mode until mode_start_iter
        n_active = 1 if (n_probe_modes > 1 and it < mode_start_iter) else n_probe_modes

        for idx in order:
            r = int(round(positions[idx, 0]))
            c = int(round(positions[idx, 1]))
            r = max(0, min(r, obj_h - asize[0]))
            c = max(0, min(c, obj_w - asize[1]))

            obj_patch = obj[r:r + asize[0], c:c + asize[1]]

            # Forward propagation
            I_model = cp.zeros(asize, dtype=cp.float64)
            psi_modes = cp.zeros_like(probes)
            Psi_modes = cp.zeros_like(probes)
            for m in range(n_active):
                psi_modes[m] = probes[m] * obj_patch
                Psi_modes[m] = cp.fft.fft2(psi_modes[m])
                I_model += cp.abs(Psi_modes[m]) ** 2

            I_model_sqrt = cp.sqrt(I_model + 1e-20)
            target_mag = fmag[:, :, idx]
            mask = fmask if fmask.ndim == 2 else fmask[:, :, idx]

            err_sum += float(cp.sum(mask * (I_model_sqrt - target_mag) ** 2))

            # Modulus constraint
            ratio = mask * target_mag / (I_model_sqrt + 1e-10) + (1 - mask)
            dpsi_modes = cp.zeros_like(probes)
            for m in range(n_active):
                Psi_corrected = Psi_modes[m] * ratio
                psi_corrected = cp.fft.ifft2(Psi_corrected)
                dpsi_modes[m] = psi_corrected - psi_modes[m]

            # Object update
            probe_intensity = cp.zeros(asize, dtype=cp.float64)
            obj_update_num = cp.zeros(asize, dtype=cp.complex128)
            for m in range(n_active):
                probe_intensity += cp.abs(probes[m]) ** 2
                obj_update_num += cp.conj(probes[m]) * dpsi_modes[m]
            probe_max2 = float(cp.max(probe_intensity))
            obj_denom = (1 - alpha) * probe_intensity + alpha * probe_max2 + 1e-10
            obj[r:r + asize[0], c:c + asize[1]] += obj_update_num / obj_denom

            # Probe update
            obj_abs2 = cp.abs(obj_patch) ** 2
            obj_max2 = float(cp.max(obj_abs2))
            probe_denom = (1 - beta) * obj_abs2 + beta * obj_max2 + 1e-10
            for m in range(n_active):
                probes[m] += cp.conj(obj_patch) * dpsi_modes[m] / probe_denom

            # Position refinement
            if do_pos_refine and it >= position_refine_start:
                psi_total = cp.sum(psi_modes[:n_active], axis=0)
                Psi_total = cp.fft.fft2(psi_total)
                dpsi_total = cp.sum(dpsi_modes[:n_active], axis=0)
                dpsi_dy = cp.fft.ifft2(Psi_total * ky[:, None])
                dpsi_dx = cp.fft.ifft2(Psi_total * kx[None, :])
                dy = float(cp.real(cp.sum(cp.conj(dpsi_dy) * dpsi_total))) / \
                     (float(cp.sum(cp.abs(dpsi_dy) ** 2)) + 1e-10)
                dx = float(cp.real(cp.sum(cp.conj(dpsi_dx) * dpsi_total))) / \
                     (float(cp.sum(cp.abs(dpsi_dx) ** 2)) + 1e-10)
                dy = np.clip(dy, -0.5, 0.5)
                dx = np.clip(dx, -0.5, 0.5)
                new_r = np.clip(pos_corrections[idx, 0] + dy, -3.0, 3.0)
                new_c = np.clip(pos_corrections[idx, 1] + dx, -3.0, 3.0)
                positions[idx, 0] += (new_r - pos_corrections[idx, 0])
                positions[idx, 1] += (new_c - pos_corrections[idx, 1])
                pos_corrections[idx, 0] = new_r
                pos_corrections[idx, 1] = new_c

        # Post-iteration constraints
        for m in range(n_active):
            probes[m] *= probe_support

        if probe_inertia > 0 and probes_prev is not None:
            probes = (1 - probe_inertia) * probes + probe_inertia * probes_prev

        if n_active > 1:
            probes = _orthogonalize_modes(probes, n_probe_modes, asize, cp)

        if obj_inertia > 0 and obj_prev is not None:
            obj = (1 - obj_inertia) * obj + obj_inertia * obj_prev

        if obj_amp_clip is not None and obj_amp_clip > 0:
            amp = cp.abs(obj)
            too_high = amp > obj_amp_clip
            if cp.any(too_high):
                obj[too_high] *= obj_amp_clip / amp[too_high]

        # Normalized error
        total_intensity = float(cp.sum(fmag ** 2))
        err_norm = err_sum / (total_intensity + 1e-10)
        errors.append(err_norm)

        # Track best
        if track_best and err_norm < best_error:
            best_error = err_norm
            best_obj_cpu = cp.asnumpy(obj)
            best_probes_cpu = cp.asnumpy(probes)
            best_iter = it

        # Callback (send CPU arrays for preview)
        if _cb:
            cb_data = {
                'type': 'iteration_update', 'engine': engine_label,
                'iteration': it, 'total_iterations': num_iterations,
                'error': err_norm,
            }
            if it % preview_interval == 0 or it == num_iterations:
                cb_data['include_preview'] = True
                cb_data['object'] = cp.asnumpy(obj)
                cb_data['probes'] = cp.asnumpy(probes[0])  # (modes,H,W) → (H,W) primary mode
            _cb(cb_data)

        # Cancel check
        if _ce and _ce.is_set():
            break

    # Restore best
    if track_best and best_obj_cpu is not None:
        obj_np = best_obj_cpu
        probes_np = best_probes_cpu
    else:
        obj_np = cp.asnumpy(obj)
        probes_np = cp.asnumpy(probes)

    # Return: (ob_list, probes_ndarray, error_list)
    if n_probe_modes == 1:
        probes_out = probes_np[0]
    else:
        probes_out = np.moveaxis(probes_np, 0, -1)  # (modes,Ny,Nx) -> (Ny,Nx,modes)

    return [obj_np], probes_out, errors, positions.astype(np.float32)
