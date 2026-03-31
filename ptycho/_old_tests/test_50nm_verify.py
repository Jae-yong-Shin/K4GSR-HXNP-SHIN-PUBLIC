"""
50nm beam verification: DM->ML pipeline, fermat + raster scan.

Uses asize=128 for speed (still 50nm beam physics).
Compares:
  S1: Single-mode, fermat scan
  S2: Single-mode, raster scan
  S3: 3-mode fwd + 1-mode recon, fermat scan
  S4: 3-mode fwd + 3-mode recon, fermat scan

DM 200 iter -> ML 50 iter (PtychoShelves standard pipeline).

Known-good: z=1m gives dx~13nm for asize=128 10keV -> FWHM~7px (too small).
Use z=5m -> dx~65nm -> 50nm beam FWHM~54px (WRONG: beam is in physical units, not pixels).

Actually: FWHM_px = FWHM_physical / pixel_size.
  z=1m, asize=128: dx = 0.124nm * 1m / (128 * 75e-6m) = 12.92nm. FWHM=50nm/12.92nm = 3.9px (TOO SMALL)
  z=5m, asize=128: dx = 0.124nm * 5m / (128 * 75e-6m) = 64.6nm. FWHM=50nm/64.6nm = 0.77px (WAY TOO SMALL)

Problem: 50nm beam with asize=128 requires z to give dx << 50nm.
  z=0.1m: dx = 0.124nm * 0.1m / (128 * 75e-6m) = 1.29nm. FWHM=50nm/1.29nm = 38.7px (GOOD!)
  z=0.2m: dx = 0.124nm * 0.2m / (128 * 75e-6m) = 2.58nm. FWHM=50nm/2.58nm = 19.4px (OK)

Use z=0.15m: dx = 1.94nm, FWHM = 50/1.94 = 25.8px (good overlap)
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
Z_M = 0.15          # -> dx ~ 1.94 nm, FWHM ~ 26 px
DET_PIXEL_M = 75e-6
N_PHOTONS = 1000
DM_ITER = 200
ML_ITER = 50

BEAM_PARAMS = {
    'fwhm_h_m': 50e-9,
    'fwhm_v_m': 50e-9,    # symmetric for simplicity
    'focal_length_m': 0.1,
    'defocus_m': 0.0,
}


def make_data(n_modes_fwd, f_coh, dl, scan_type='fermat'):
    """Generate synthetic data."""
    gen = SyntheticPtycho.from_dataset(
        asize=ASIZE, energy_keV=ENERGY_KEV, z_m=Z_M,
        det_pixel_size_m=DET_PIXEL_M, N_photons=N_PHOTONS,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=0.15, scan_ly_um=0.15,  # 150nm range
        probe=dl._build_fresnel_probe(BEAM_PARAMS, ASIZE, ENERGY_KEV, Z_M, DET_PIXEL_M),
        N_modes=n_modes_fwd,
        coherent_fraction=f_coh,
    )
    ds = gen.generate(noise_sigma=0.0, rng_seed=42, scan_type=scan_type)
    return ds


def run_dm_ml(ds, dl, n_modes_recon):
    """Run DM -> ML pipeline."""
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

    # Prepare probes for DM
    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']

    if n_modes_recon > 1:
        # PtychoShelves-style Hermite mode initialization
        from synth_ptycho import _hermite_poly
        Ny, Nx = probes_in.shape
        probes_3d = np.zeros((Ny, Nx, n_modes_recon), dtype=np.complex64)
        probes_3d[:, :, 0] = probes_in

        Emod = np.zeros(n_modes_recon)
        for m in range(1, n_modes_recon):
            Emod[m] = 0.02
        Emod[0] = 1.0 - Emod.sum()
        Etot = float(np.sum(np.abs(probes_in) ** 2))

        p0_power = float(np.sum(np.abs(probes_3d[:, :, 0]) ** 2))
        if p0_power > 0:
            probes_3d[:, :, 0] *= np.sqrt(Emod[0] * Etot / p0_power)

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
            pk_power = float(np.sum(np.abs(mode_probe) ** 2))
            if pk_power > 0:
                mode_probe *= np.sqrt(Emod[m] * Etot / pk_power)
            probes_3d[:, :, m] = mode_probe.astype(np.complex64)

        probes_in = probes_3d

    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    # ── DM ──
    t0 = time.time()
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=DM_ITER)
    dm_time = time.time() - t0

    dm_final_err = float(err_dm[DM_ITER]) if err_dm[DM_ITER] > 0 else 0.0
    print(f"    DM done: fourier_err={dm_final_err:.4e}, time={dm_time:.0f}s")

    # ── ML (refinement) ──
    p_ml = dict(p)
    p_ml['opt_iter'] = ML_ITER
    p_ml['opt_flags'] = [1, 1]
    p_ml['opt_errmetric'] = 'poisson'

    # Pack object for ML: needs [obj_h, obj_w, 1] shape
    ob_for_ml = [o[:, :, np.newaxis] if o.ndim == 2 else o for o in ob_dm]
    p_ml['object'] = ob_for_ml

    # Pack probe for ML: needs [Ny, Nx, 1, n_modes] shape
    if pr_dm.ndim == 2:
        p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
    elif pr_dm.ndim == 3:
        # (Ny, Nx, Nmodes) -> (Ny, Nx, 1, Nmodes)
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
    """Compute norm error (center cropped, phase-aligned)."""
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

    print(f"=== 50nm Beam Verification (DM->ML) ===")
    print(f"  Energy: {ENERGY_KEV} keV, z: {Z_M} m, asize: {ASIZE}")
    print(f"  Pixel size: {dx_nm:.2f} nm")
    print(f"  FOV: {ASIZE * dx_nm:.0f} nm")
    print(f"  Expected probe FWHM: {50.0 / dx_nm:.1f} px")
    print(f"  Pipeline: DM {DM_ITER} -> ML {ML_ITER}")

    dl = DataLoader()
    probe = dl._build_fresnel_probe(BEAM_PARAMS, ASIZE, ENERGY_KEV, Z_M, DET_PIXEL_M)
    fwhm_px = estimate_probe_fwhm(probe)
    print(f"  Actual probe FWHM: {fwhm_px:.1f} px ({fwhm_px * dx_nm:.1f} nm)")

    scenarios = [
        {'name': 'S1: 1-mode fermat',  'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1, 'scan': 'fermat'},
        {'name': 'S2: 1-mode raster',  'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1, 'scan': 'raster'},
        {'name': 'S3: 3-mode fwd 1-recon', 'n_fwd': 3, 'f_coh': 0.5, 'n_recon': 1, 'scan': 'fermat'},
        {'name': 'S4: 3-mode fwd 3-recon', 'n_fwd': 3, 'f_coh': 0.5, 'n_recon': 3, 'scan': 'fermat'},
    ]

    results = []
    margin = ASIZE // 4

    for sc in scenarios:
        print(f"\n{'=' * 60}")
        print(f"  {sc['name']}")
        print(f"{'=' * 60}")

        ds = make_data(sc['n_fwd'], sc['f_coh'], dl, scan_type=sc['scan'])
        print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2%}, "
              f"FWHM={ds.probe_fwhm:.1f}px, step={ds.avg_step:.1f}px, "
              f"scan={sc['scan']}")

        if ds.overlap < 0.5:
            print(f"  WARNING: overlap={ds.overlap:.2%} < 50%!")

        ob_final, pr_final, err_dm, total_time = run_dm_ml(ds, dl, sc['n_recon'])

        norm_err = compute_norm_error(ob_final, ds.object_true, margin)
        obj_max = float(np.abs(ob_final).max())
        gt_max = float(np.abs(ds.object_true).max())

        print(f"  RESULT: norm_error={norm_err:.4f}, |obj|max={obj_max:.3f} "
              f"(GT={gt_max:.3f}), time={total_time:.0f}s")

        results.append({
            'name': sc['name'], 'ob': ob_final, 'pr': pr_final,
            'err_dm': err_dm, 'norm_error': norm_err,
            'obj_max': obj_max, 'gt': ds.object_true,
            'probe_gt': ds.probe, 'time': total_time,
            'ds': ds,
        })

    # ── Plot ──
    n = len(results)
    fig, axes = plt.subplots(3, n + 1, figsize=(4 * (n + 1), 12))

    gt = results[0]['gt']
    m = margin

    # GT column
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1
    axes[0, 0].imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    axes[0, 0].set_title('Ground Truth\n(amplitude)', fontweight='bold', fontsize=9)
    axes[0, 0].axis('off')

    axes[1, 0].imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 0].set_title('Ground Truth\n(phase)', fontweight='bold', fontsize=9)
    axes[1, 0].axis('off')

    axes[2, 0].imshow(np.abs(results[0]['probe_gt']), cmap='jet')
    axes[2, 0].set_title(f'Probe GT\nFWHM={fwhm_px:.1f}px', fontweight='bold', fontsize=9)
    axes[2, 0].axis('off')

    for i, res in enumerate(results):
        col = i + 1
        ob = res['ob']
        oh, ow = ob.shape

        r_amp = np.abs(ob[m:oh - m, m:ow - m]) if m > 0 else np.abs(ob)
        r_vmin = np.percentile(r_amp, 1)
        r_vmax = np.percentile(r_amp, 99.5) * 1.1
        axes[0, col].imshow(r_amp, cmap='jet', vmin=r_vmin, vmax=r_vmax)
        axes[0, col].set_title(
            f'{res["name"]}\nerr={res["norm_error"]:.4f}\n|obj|={res["obj_max"]:.3f}',
            fontweight='bold', fontsize=8)
        axes[0, col].axis('off')

        r_ph = np.angle(ob[m:oh - m, m:ow - m]) if m > 0 else np.angle(ob)
        axes[1, col].imshow(r_ph, cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, col].set_title(f'Phase ({res["time"]:.0f}s)', fontsize=8)
        axes[1, col].axis('off')

        if res['pr'].ndim == 3:
            pr_amp = np.sqrt(np.sum(np.abs(res['pr']) ** 2, axis=2))
            modes_str = f'{res["pr"].shape[2]}modes'
        else:
            pr_amp = np.abs(res['pr'])
            modes_str = '1mode'
        axes[2, col].imshow(pr_amp, cmap='jet')
        axes[2, col].set_title(f'Probe ({modes_str})', fontsize=8)
        axes[2, col].axis('off')

    fig.suptitle(
        f'50nm Beam: DM{DM_ITER}->ML{ML_ITER}\n'
        f'{ENERGY_KEV}keV, asize={ASIZE}, z={Z_M}m, dx={dx_nm:.2f}nm',
        fontsize=13, fontweight='bold')
    plt.tight_layout()
    out = str(Path(__file__).parent / '_50nm_verify.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n[SAVED] {out}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    for res in results:
        status = "PASS" if res['norm_error'] < 0.3 else "WARN" if res['norm_error'] < 0.5 else "FAIL"
        print(f"  [{status}] {res['name']}: err={res['norm_error']:.4f}, |obj|={res['obj_max']:.3f}")

    # Expectations:
    # S1, S2: norm_error < 0.2 (single-mode baseline)
    # S3: worse than S1 (mode mismatch)
    # S4: better than S3 (matching modes), possibly close to S1


if __name__ == '__main__':
    main()
