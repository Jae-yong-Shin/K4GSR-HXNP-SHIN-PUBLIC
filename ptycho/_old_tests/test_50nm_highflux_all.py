"""
High-flux (1e8 photons) complete multi-mode verification.

Realistic BL10 conditions. All scenarios with individual result images.

Scenarios:
  S1: 1-mode fwd, 1-mode recon (baseline, fully coherent)
  S2: 1-mode fwd, 1-mode recon, raster scan
  S3: 3-mode fwd, 1-mode recon (mode mismatch, f=0.3)
  S4: 3-mode fwd, 3-mode recon (correct model, f=0.3)
  S5: 5-mode fwd, 1-mode recon (stronger mismatch, f=0.3)
  S6: 5-mode fwd, 5-mode recon (correct model, f=0.3)
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm, _hermite_poly
from fsc import fsc_2d, plot_fsc

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ── Parameters ──
ASIZE = 128
ENERGY_KEV = 10.0
Z_M = 0.15
DET_PIXEL_M = 75e-6
N_PHOTONS = int(1e8)   # high flux, realistic BL10
DM_ITER = 300
ML_ITER = 100

BEAM_PARAMS = {
    'fwhm_h_m': 50e-9,
    'fwhm_v_m': 50e-9,
    'focal_length_m': 0.1,
    'defocus_m': 0.0,
}

OUT_DIR = Path(__file__).parent


def make_data(n_modes_fwd, f_coh, dl, scan_type='fermat'):
    gen = SyntheticPtycho.from_dataset(
        asize=ASIZE, energy_keV=ENERGY_KEV, z_m=Z_M,
        det_pixel_size_m=DET_PIXEL_M, N_photons=N_PHOTONS,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=0.25, scan_ly_um=0.25,
        probe=dl._build_fresnel_probe(BEAM_PARAMS, ASIZE, ENERGY_KEV, Z_M, DET_PIXEL_M),
        N_modes=n_modes_fwd,
        coherent_fraction=f_coh,
    )
    ds = gen.generate(noise_sigma=0.0, rng_seed=42, scan_type=scan_type)
    return ds


def init_multimode_probe(probes_in, n_modes):
    """Create Hermite-mode initial probes (PtychoShelves convention)."""
    Ny, Nx = probes_in.shape
    probes_3d = np.zeros((Ny, Nx, n_modes), dtype=np.complex64)
    probes_3d[:, :, 0] = probes_in

    Emod = np.zeros(n_modes)
    for m in range(1, n_modes):
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

    for m in range(1, n_modes):
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

    for m in range(n_modes):
        pk = float(np.sum(np.abs(probes_3d[:, :, m]) ** 2))
        print(f"    init mode {m}: power={pk:.4e} ({pk/max(Etot,1e-30)*100:.1f}%)")
    return probes_3d


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
        probes_in = init_multimode_probe(probes_in, n_modes_recon)

    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    # DM
    t0 = time.time()
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=DM_ITER)
    dm_time = time.time() - t0
    dm_final_err = float(err_dm[DM_ITER]) if err_dm[DM_ITER] > 0 else 0.0
    print(f"    DM done: fourier_err={dm_final_err:.4e}, time={dm_time:.0f}s")

    # ML
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
    print(f"    ML done: time={ml_time:.0f}s")

    ob_final = p_ml['object'][0].squeeze()
    pr_final = p_ml['probes'].squeeze()
    return ob_final, pr_final, err_dm, dm_time + ml_time


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


def save_individual_image(res, gt, margin, dx_nm, scenario_tag):
    """Save individual scenario result image with FSC plot."""
    ob = res['ob']
    oh, ow = ob.shape
    m = margin

    fig = plt.figure(figsize=(10, 14))
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.8])

    # Row 0: amplitude
    ax00 = fig.add_subplot(gs[0, 0])
    ax01 = fig.add_subplot(gs[0, 1])
    # Row 1: phase
    ax10 = fig.add_subplot(gs[1, 0])
    ax11 = fig.add_subplot(gs[1, 1])
    # Row 2: FSC (merged across both columns)
    ax_fsc = fig.add_subplot(gs[2, :])

    # GT amplitude
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1
    ax00.imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    ax00.set_title('Ground Truth (amplitude)', fontweight='bold', fontsize=10)
    ax00.axis('off')

    # Recon amplitude
    r_amp = np.abs(ob[m:oh - m, m:ow - m])
    r_vmin = np.percentile(r_amp, 1)
    r_vmax = np.percentile(r_amp, 99.5) * 1.1
    ax01.imshow(r_amp, cmap='jet', vmin=r_vmin, vmax=r_vmax)
    fsc_res = res.get('fsc_result')
    res_str = ''
    if fsc_res is not None and fsc_res['resolution_nm'] is not None:
        res_str = ', res=%.1f nm' % fsc_res['resolution_nm']
    ax01.set_title('Recon (amplitude)\nerr=%s, |obj|=%s%s' % (
        '%.4f' % res['norm_error'], '%.3f' % res['obj_max'], res_str),
                   fontweight='bold', fontsize=10)
    ax01.axis('off')

    # GT phase
    ax10.imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    ax10.set_title('Ground Truth (phase)', fontweight='bold', fontsize=10)
    ax10.axis('off')

    # Recon phase
    ax11.imshow(np.angle(ob[m:oh - m, m:ow - m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    ax11.set_title('Recon (phase) [%.0fs]' % res['time'], fontweight='bold', fontsize=10)
    ax11.axis('off')

    # FSC plot
    if fsc_res is not None:
        plot_fsc(fsc_res, title=res['tag'], ax=ax_fsc)
    else:
        ax_fsc.text(0.5, 0.5, 'FSC not computed', ha='center', va='center',
                    fontsize=12, transform=ax_fsc.transAxes)

    fig.suptitle(
        '%s -- N_photons=1e8, DM%d+ML%d\n%skeV, asize=%d, dx=%.2fnm' % (
            res['name'], DM_ITER, ML_ITER, ENERGY_KEV, ASIZE, dx_nm),
        fontsize=13, fontweight='bold')
    plt.tight_layout()
    out = str(OUT_DIR / ('_highflux_%s.png' % scenario_tag))
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print("  [SAVED] %s" % out)
    return out


def main():
    lambda_m = 1239.842e-9 / (ENERGY_KEV * 1e3)
    dx_m = lambda_m * Z_M / (ASIZE * DET_PIXEL_M)
    dx_nm = dx_m * 1e9

    print(f"=== High-Flux Complete Verification (N_photons=1e8) ===")
    print(f"  Energy: {ENERGY_KEV} keV, z: {Z_M} m, asize: {ASIZE}")
    print(f"  Pixel size: {dx_nm:.2f} nm, FOV: {ASIZE*dx_nm:.0f} nm")
    print(f"  N_photons: {N_PHOTONS:.0e}")
    print(f"  Pipeline: DM {DM_ITER} -> ML {ML_ITER}")

    dl = DataLoader()

    scenarios = [
        {'name': 'S1: 1-mode fermat (baseline)', 'tag': 'S1', 'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1, 'scan': 'fermat'},
        {'name': 'S2: 1-mode raster', 'tag': 'S2', 'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1, 'scan': 'raster'},
        {'name': 'S3: 3fwd-1recon f=0.3', 'tag': 'S3', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 1, 'scan': 'fermat'},
        {'name': 'S4: 3fwd-3recon f=0.3', 'tag': 'S4', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 3, 'scan': 'fermat'},
        {'name': 'S5: 5fwd-1recon f=0.3', 'tag': 'S5', 'n_fwd': 5, 'f_coh': 0.3, 'n_recon': 1, 'scan': 'fermat'},
        {'name': 'S6: 5fwd-5recon f=0.3', 'tag': 'S6', 'n_fwd': 5, 'f_coh': 0.3, 'n_recon': 5, 'scan': 'fermat'},
    ]

    results = []
    margin = ASIZE // 4

    for sc in scenarios:
        print(f"\n{'=' * 60}")
        print(f"  {sc['name']}")
        print(f"{'=' * 60}")

        ds = make_data(sc['n_fwd'], sc['f_coh'], dl, scan_type=sc['scan'])
        print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2%}, scan={sc['scan']}")
        print(f"  probe power: {float(np.sum(np.abs(ds.probe)**2)):.4e}")
        print(f"  fmag max: {float(ds.fmag.max()):.2f}, fmag^2 sum: {float(np.sum(ds.fmag**2)):.4e}")

        ob_final, pr_final, err_dm, total_time = run_dm_ml(ds, dl, sc['n_recon'])

        norm_err = compute_norm_error(ob_final, ds.object_true, margin)
        obj_max = float(np.abs(ob_final).max())
        gt_max = float(np.abs(ds.object_true).max())

        # Compute FSC
        fsc_result = fsc_2d(ob_final, ds.object_true, pixel_size_nm=dx_nm)
        fsc_res_05 = fsc_result['resolution_nm']
        fsc_res_hb = fsc_result['resolution_half_bit_nm']
        fsc_res_str = ''
        if fsc_res_05 is not None:
            fsc_res_str += ', FSC_0.5=%.1f nm' % fsc_res_05
        if fsc_res_hb is not None:
            fsc_res_str += ', FSC_1/2bit=%.1f nm' % fsc_res_hb

        print(f"  RESULT: norm_error={norm_err:.4f}, |obj|max={obj_max:.3f} "
              f"(GT={gt_max:.3f}), time={total_time:.0f}s{fsc_res_str}")

        res = {
            'name': sc['name'], 'tag': sc['tag'],
            'ob': ob_final, 'pr': pr_final,
            'norm_error': norm_err, 'obj_max': obj_max,
            'gt': ds.object_true, 'time': total_time,
            'n_fwd': sc['n_fwd'], 'n_recon': sc['n_recon'],
            'f_coh': sc['f_coh'], 'scan': sc['scan'],
            'fsc_result': fsc_result,
        }
        results.append(res)

        # Save individual image
        save_individual_image(res, ds.object_true, margin, dx_nm, sc['tag'])

    # ── Combined comparison plot (3 rows: amplitude, phase, FSC) ──
    n = len(results)
    fig = plt.figure(figsize=(3.5 * (n + 1), 11))
    gs = fig.add_gridspec(3, n + 1, height_ratios=[1, 1, 0.8])
    gt = results[0]['gt']
    m = margin

    # Row 0: amplitude images
    ax_gt_amp = fig.add_subplot(gs[0, 0])
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1
    ax_gt_amp.imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    ax_gt_amp.set_title('Ground Truth\n(amplitude)', fontweight='bold', fontsize=9)
    ax_gt_amp.axis('off')

    # Row 1: phase images
    ax_gt_ph = fig.add_subplot(gs[1, 0])
    ax_gt_ph.imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    ax_gt_ph.set_title('Ground Truth\n(phase)', fontweight='bold', fontsize=9)
    ax_gt_ph.axis('off')

    # Row 2, col 0: empty (no FSC for ground truth)
    ax_gt_fsc = fig.add_subplot(gs[2, 0])
    ax_gt_fsc.axis('off')

    for i, res in enumerate(results):
        col = i + 1
        ob = res['ob']
        oh, ow = ob.shape

        # Amplitude
        ax_amp = fig.add_subplot(gs[0, col])
        r_amp = np.abs(ob[m:oh - m, m:ow - m])
        r_vmin = np.percentile(r_amp, 1)
        r_vmax = np.percentile(r_amp, 99.5) * 1.1
        ax_amp.imshow(r_amp, cmap='jet', vmin=r_vmin, vmax=r_vmax)
        fsc_r = res.get('fsc_result')
        res_lbl = ''
        if fsc_r is not None and fsc_r['resolution_nm'] is not None:
            res_lbl = '\nres=%.1f nm' % fsc_r['resolution_nm']
        ax_amp.set_title(
            '%s: err=%.4f\n|obj|=%.2f%s' % (res['tag'], res['norm_error'], res['obj_max'], res_lbl),
            fontweight='bold', fontsize=8)
        ax_amp.axis('off')

        # Phase
        ax_ph = fig.add_subplot(gs[1, col])
        r_ph = np.angle(ob[m:oh - m, m:ow - m])
        ax_ph.imshow(r_ph, cmap='hsv', vmin=-np.pi, vmax=np.pi)
        lbl = '%dfwd-%drec' % (res['n_fwd'], res['n_recon'])
        if res['scan'] == 'raster':
            lbl += ' raster'
        ax_ph.set_title('%s\n%.0fs' % (lbl, res['time']), fontsize=8)
        ax_ph.axis('off')

        # FSC
        ax_fsc = fig.add_subplot(gs[2, col])
        if fsc_r is not None:
            plot_fsc(fsc_r, title=res['tag'], ax=ax_fsc)
            ax_fsc.set_title(res['tag'], fontsize=8, fontweight='bold')
        else:
            ax_fsc.axis('off')

    fig.suptitle(
        'High-Flux Complete: DM%d+ML%d (N_ph=1e8)\n%skeV, asize=%d, dx=%.2fnm' % (
            DM_ITER, ML_ITER, ENERGY_KEV, ASIZE, dx_nm),
        fontsize=12, fontweight='bold')
    plt.tight_layout()
    out_combined = str(OUT_DIR / '_highflux_all.png')
    plt.savefig(out_combined, dpi=150, bbox_inches='tight')
    plt.close()
    print("\n[SAVED] %s" % out_combined)

    # ── Summary ──
    print(f"\n{'=' * 90}")
    print(f"  SUMMARY (N_photons = {N_PHOTONS:.0e}, DM{DM_ITER}+ML{ML_ITER})")
    print(f"{'=' * 90}")
    print(f"  {'Tag':<5} {'Scenario':<30} {'err':>8} {'|obj|':>8} {'FSC@0.5':>10} {'FSC@1/2b':>10} {'time':>6}")
    print(f"  {'-'*5} {'-'*30} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*6}")
    for res in results:
        status = "PASS" if res['norm_error'] < 0.3 else "WARN" if res['norm_error'] < 0.5 else "FAIL"
        fsc_r = res.get('fsc_result')
        fsc_05_str = '%.1f nm' % fsc_r['resolution_nm'] if (fsc_r and fsc_r['resolution_nm']) else 'N/A'
        fsc_hb_str = '%.1f nm' % fsc_r['resolution_half_bit_nm'] if (fsc_r and fsc_r['resolution_half_bit_nm']) else 'N/A'
        print(f"  [{status}] {res['tag']:<3} {res['name']:<28} {res['norm_error']:8.4f} {res['obj_max']:8.3f} {fsc_05_str:>10} {fsc_hb_str:>10} {res['time']:5.0f}s")

    # Validation checks
    s1 = results[0]['norm_error']
    s2 = results[1]['norm_error']
    s3 = results[2]['norm_error']
    s4 = results[3]['norm_error']
    s5 = results[4]['norm_error']
    s6 = results[5]['norm_error']

    print(f"\n  Validation:")
    print(f"    S2 ~ S1 (raster vs fermat):          {s2:.4f} ~ {s1:.4f} (diff={abs(s2-s1):.4f})")
    print(f"    S3 > S1 (3-mode mismatch):            {s3:.4f} > {s1:.4f} = {s3 > s1}")
    print(f"    S4 < S3 (3-mode correct recon):       {s4:.4f} < {s3:.4f} = {s4 < s3}")
    print(f"    S5 > S3 (5-mode > 3-mode mismatch):   {s5:.4f} > {s3:.4f} = {s5 > s3}")
    print(f"    S6 < S5 (5-mode correct recon):       {s6:.4f} < {s5:.4f} = {s6 < s5}")
    print(f"    S4 < S1 (multi-mode helps baseline):  {s4:.4f} < {s1:.4f} = {s4 < s1}")

    all_pass = (s3 > s1) and (s4 < s3)
    print(f"\n  OVERALL: {'ALL CORE VALIDATIONS PASSED' if all_pass else 'SOME VALIDATIONS FAILED'}")


if __name__ == '__main__':
    main()
