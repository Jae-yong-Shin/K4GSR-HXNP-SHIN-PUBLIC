"""
Extended 50nm beam multi-mode verification.

Larger scan area (more positions) + stronger partial coherence (f_coh=0.3).
Validates that multi-mode recon (S4) outperforms single-mode recon (S3)
when forward data has significant partial coherence.

Scenarios:
  S1: 1-mode fwd, 1-mode recon (baseline)
  S3: 3-mode fwd, 1-mode recon (mode mismatch -> worse)
  S4: 3-mode fwd, 3-mode recon (correct model -> better than S3)
  S5: 5-mode fwd, 1-mode recon (stronger mismatch)
  S6: 5-mode fwd, 5-mode recon (correct model)
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ── Parameters ──
ASIZE = 128
ENERGY_KEV = 10.0
Z_M = 0.15
DET_PIXEL_M = 75e-6
N_PHOTONS = 1000
DM_ITER = 300
ML_ITER = 100

BEAM_PARAMS = {
    'fwhm_h_m': 50e-9,
    'fwhm_v_m': 50e-9,
    'focal_length_m': 0.1,
    'defocus_m': 0.0,
}


def make_data(n_modes_fwd, f_coh, dl, scan_type='fermat'):
    gen = SyntheticPtycho.from_dataset(
        asize=ASIZE, energy_keV=ENERGY_KEV, z_m=Z_M,
        det_pixel_size_m=DET_PIXEL_M, N_photons=N_PHOTONS,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=0.25, scan_ly_um=0.25,  # larger area -> more positions
        probe=dl._build_fresnel_probe(BEAM_PARAMS, ASIZE, ENERGY_KEV, Z_M, DET_PIXEL_M),
        N_modes=n_modes_fwd,
        coherent_fraction=f_coh,
    )
    ds = gen.generate(noise_sigma=0.0, rng_seed=42, scan_type=scan_type)
    return ds


def run_dm_ml(ds, dl, n_modes_recon):
    from engines.gpu.DM import DM as DM_GPU
    from engines.ML import ML

    asize = ds.asize
    data = {
        'fmag': ds.fmag,
        'positions': ds.positions_clean,
        'probes': ds.probe,
        'object_init': ds.object_init,
        'asize': (asize, asize),
        'Npos': ds.Npos,
    }
    p = dl.build_p_dict(data, {
        'number_iterations': DM_ITER,
        'use_gpu': True,
        'pfft_relaxation': 0.05,
        'probe_change_start': 1,
        'object_change_start': 1,
        'probe_inertia': 0.9,
        'probe_modes': n_modes_recon,
    })

    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']

    if n_modes_recon > 1:
        # PtychoShelves-style Hermite mode initialization
        # Reference: +core/prepare_initial_probes.m (mode_start='herm')
        from synth_ptycho import _hermite_poly
        Ny, Nx = probes_in.shape
        probes_3d = np.zeros((Ny, Nx, n_modes_recon), dtype=np.complex64)
        probes_3d[:, :, 0] = probes_in

        # mode_start_pow: 2% per higher mode (MATLAB default)
        Emod = np.zeros(n_modes_recon)
        for m in range(1, n_modes_recon):
            Emod[m] = 0.02
        Emod[0] = 1.0 - Emod.sum()
        Etot = float(np.sum(np.abs(probes_in) ** 2))

        # Scale mode 0
        p0_power = float(np.sum(np.abs(probes_3d[:, :, 0]) ** 2))
        if p0_power > 0:
            probes_3d[:, :, 0] *= np.sqrt(Emod[0] * Etot / p0_power)

        # Probe sigma for Hermite coordinate
        probe_amp = np.abs(probes_in)
        thresh = probe_amp.max() * 0.5
        above_h = np.where(probe_amp.sum(axis=1) > thresh * Nx * 0.01)[0]
        above_w = np.where(probe_amp.sum(axis=0) > thresh * Ny * 0.01)[0]
        sig_y = max(float(above_h[-1] - above_h[0]) / 2.355, 3.0) if len(above_h) > 1 else Ny / 6.0
        sig_x = max(float(above_w[-1] - above_w[0]) / 2.355, 3.0) if len(above_w) > 1 else Nx / 6.0

        yy = (np.arange(Ny, dtype=np.float64) - Ny / 2.0) / sig_y
        xx = (np.arange(Nx, dtype=np.float64) - Nx / 2.0) / sig_x
        YY, XX = np.meshgrid(yy, xx, indexing='ij')

        herm_orders = [(1, 0), (0, 1), (1, 1), (2, 0), (0, 2),
                       (2, 1), (1, 2), (2, 2), (3, 0), (0, 3)]

        for m in range(1, n_modes_recon):
            idx = m - 1
            if idx < len(herm_orders):
                ny_ord, nx_ord = herm_orders[idx]
            else:
                ny_ord, nx_ord = idx // 3 + 1, idx % 3

            hy = _hermite_poly(ny_ord, YY)
            hx = _hermite_poly(nx_ord, XX)
            modulation = (hy * hx).astype(np.float64)
            mode_probe = probes_in.astype(np.complex128) * modulation

            # Normalize: ||P_m||^2 = Emod[m] * Etot
            pk_power = float(np.sum(np.abs(mode_probe) ** 2))
            if pk_power > 0:
                mode_probe *= np.sqrt(Emod[m] * Etot / pk_power)
            probes_3d[:, :, m] = mode_probe.astype(np.complex64)

        probes_in = probes_3d

    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    t0 = time.time()
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=DM_ITER)
    dm_time = time.time() - t0

    dm_final_err = float(err_dm[DM_ITER]) if err_dm[DM_ITER] > 0 else 0.0
    print(f"    DM done: fourier_err={dm_final_err:.4e}, time={dm_time:.0f}s")

    # ML refinement
    p_ml = dict(p)
    p_ml['opt_iter'] = ML_ITER
    p_ml['opt_flags'] = [1, 1]
    p_ml['opt_errmetric'] = 'poisson'

    ob_for_ml = [o[:, :, np.newaxis] if o.ndim == 2 else o for o in ob_dm]
    p_ml['object'] = ob_for_ml

    if pr_dm.ndim == 2:
        p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
    elif pr_dm.ndim == 3:
        p_ml['probes'] = pr_dm[:, :, np.newaxis, :]
    else:
        p_ml['probes'] = pr_dm

    if isinstance(p_ml.get('object_size'), list):
        p_ml['object_size'] = np.array(p_ml['object_size'])

    t1 = time.time()
    p_ml, fdb_ml = ML(p_ml)
    ml_time = time.time() - t1

    ob_final = p_ml['object'][0].squeeze()
    pr_final = p_ml['probes'].squeeze()
    print(f"    ML done: time={ml_time:.0f}s")

    total_time = dm_time + ml_time
    return ob_final, pr_final, err_dm, total_time


def compute_norm_error(recon, truth, margin):
    oh, ow = recon.shape
    th, tw = truth.shape
    ch = min(oh, th) - 2 * margin
    cw = min(ow, tw) - 2 * margin
    if ch <= 0 or cw <= 0:
        return 1.0

    r = recon[oh // 2 - ch // 2:oh // 2 + ch // 2, ow // 2 - cw // 2:ow // 2 + cw // 2]
    t = truth[th // 2 - ch // 2:th // 2 + ch // 2, tw // 2 - cw // 2:tw // 2 + cw // 2]

    phase_off = np.angle(np.sum(r * np.conj(t)))
    r_aligned = r * np.exp(-1j * phase_off)

    err = np.sqrt(np.sum(np.abs(r_aligned - t) ** 2) / np.sum(np.abs(t) ** 2))
    return float(err)


def main():
    lambda_m = 1239.842e-9 / (ENERGY_KEV * 1e3)
    dx_m = lambda_m * Z_M / (ASIZE * DET_PIXEL_M)
    dx_nm = dx_m * 1e9

    print(f"=== Extended Multi-mode Verification ===")
    print(f"  Energy: {ENERGY_KEV} keV, z: {Z_M} m, asize: {ASIZE}")
    print(f"  Pixel size: {dx_nm:.2f} nm")
    print(f"  Pipeline: DM {DM_ITER} -> ML {ML_ITER}")

    dl = DataLoader()
    probe = dl._build_fresnel_probe(BEAM_PARAMS, ASIZE, ENERGY_KEV, Z_M, DET_PIXEL_M)
    fwhm_px = estimate_probe_fwhm(probe)
    print(f"  Probe FWHM: {fwhm_px:.1f} px ({fwhm_px * dx_nm:.1f} nm)")

    scenarios = [
        {'name': 'S1: 1-mode (baseline)', 'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1},
        {'name': 'S3: 3fwd-1recon f=0.3', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 1},
        {'name': 'S4: 3fwd-3recon f=0.3', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 3},
        {'name': 'S5: 5fwd-1recon f=0.3', 'n_fwd': 5, 'f_coh': 0.3, 'n_recon': 1},
        {'name': 'S6: 5fwd-5recon f=0.3', 'n_fwd': 5, 'f_coh': 0.3, 'n_recon': 5},
    ]

    results = []
    margin = ASIZE // 4

    for sc in scenarios:
        print(f"\n{'=' * 60}")
        print(f"  {sc['name']}")
        print(f"{'=' * 60}")

        ds = make_data(sc['n_fwd'], sc['f_coh'], dl)
        print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2%}")

        ob_final, pr_final, err_dm, total_time = run_dm_ml(ds, dl, sc['n_recon'])

        norm_err = compute_norm_error(ob_final, ds.object_true, margin)
        obj_max = float(np.abs(ob_final).max())
        gt_max = float(np.abs(ds.object_true).max())

        print(f"  RESULT: norm_error={norm_err:.4f}, |obj|max={obj_max:.3f} "
              f"(GT={gt_max:.3f}), time={total_time:.0f}s")

        results.append({
            'name': sc['name'], 'ob': ob_final, 'pr': pr_final,
            'norm_error': norm_err, 'obj_max': obj_max,
            'gt': ds.object_true, 'time': total_time,
        })

    # ── Plot ──
    n = len(results)
    fig, axes = plt.subplots(2, n + 1, figsize=(3.5 * (n + 1), 7))

    gt = results[0]['gt']
    m = margin
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1

    axes[0, 0].imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    axes[0, 0].set_title('Ground Truth\n(amplitude)', fontweight='bold', fontsize=9)
    axes[0, 0].axis('off')
    axes[1, 0].imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 0].set_title('Ground Truth\n(phase)', fontweight='bold', fontsize=9)
    axes[1, 0].axis('off')

    for i, res in enumerate(results):
        col = i + 1
        ob = res['ob']
        oh, ow = ob.shape
        r_amp = np.abs(ob[m:oh - m, m:ow - m])
        r_vmin = np.percentile(r_amp, 1)
        r_vmax = np.percentile(r_amp, 99.5) * 1.1
        axes[0, col].imshow(r_amp, cmap='jet', vmin=r_vmin, vmax=r_vmax)
        axes[0, col].set_title(
            f'{res["name"]}\nerr={res["norm_error"]:.4f}',
            fontweight='bold', fontsize=8)
        axes[0, col].axis('off')

        r_ph = np.angle(ob[m:oh - m, m:ow - m])
        axes[1, col].imshow(r_ph, cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, col].set_title(f'Phase ({res["time"]:.0f}s)', fontsize=8)
        axes[1, col].axis('off')

    fig.suptitle(
        f'Extended Multi-mode: DM{DM_ITER}->ML{ML_ITER} (f_coh=0.3)\n'
        f'{ENERGY_KEV}keV, asize={ASIZE}, dx={dx_nm:.2f}nm',
        fontsize=12, fontweight='bold')
    plt.tight_layout()
    out = str(Path(__file__).parent / '_50nm_extended.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n[SAVED] {out}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    for res in results:
        status = "PASS" if res['norm_error'] < 0.3 else "WARN" if res['norm_error'] < 0.5 else "FAIL"
        print(f"  [{status}] {res['name']}: err={res['norm_error']:.4f}")

    # Validation checks:
    s1_err = results[0]['norm_error']
    s3_err = results[1]['norm_error']
    s4_err = results[2]['norm_error']
    s5_err = results[3]['norm_error']
    s6_err = results[4]['norm_error']

    print(f"\n  Validation:")
    print(f"    S3 > S1 (mode mismatch): {s3_err:.4f} > {s1_err:.4f} = {s3_err > s1_err}")
    print(f"    S4 < S3 (correct recon):  {s4_err:.4f} < {s3_err:.4f} = {s4_err < s3_err}")
    print(f"    S5 > S3 (more modes):     {s5_err:.4f} > {s3_err:.4f} = {s5_err > s3_err}")
    print(f"    S6 < S5 (correct recon):  {s6_err:.4f} < {s5_err:.4f} = {s6_err < s5_err}")


if __name__ == '__main__':
    main()
