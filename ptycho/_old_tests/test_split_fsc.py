"""
Split-data Phase FSC: proper ptychography resolution estimation.

Method:
  1. Generate synthetic data (full dataset)
  2. Split scan positions into even/odd subsets
  3. Reconstruct each subset independently (DM+ML)
  4. Compute FSC on PHASE images of the two reconstructions

This is the standard approach for ptychography (no GT needed).
We also compare with GT-phase FSC for validation.

Scenarios:
  S1: 1-mode, f_coh=1.0 (fully coherent baseline)
  S3: 3fwd-1recon, f_coh=0.3 (mode mismatch)
  S4: 3fwd-3recon, f_coh=0.3 (correct model)
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, _hermite_poly
from fsc import fsc_phase, split_positions, plot_fsc

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Parameters ──
ASIZE = 128
ENERGY_KEV = 10.0
Z_M = 0.15
DET_PIXEL_M = 75e-6
N_PHOTONS = int(1e8)
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
    """Hermite-mode initial probes (PtychoShelves convention)."""
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

    return probes_3d


def run_dm_ml_subset(ds, dl, n_modes_recon, pos_indices, label=''):
    """Run DM+ML on a subset of scan positions."""
    from engines.gpu.DM import DM as DM_GPU
    from engines.ML import ML

    asize = ds.asize
    fmag_sub = ds.fmag[:, :, pos_indices]  # fmag is [Ny, Nx, Npos]
    pos_sub = ds.positions_clean[pos_indices]
    Npos_sub = len(pos_indices)

    data = {
        'fmag': fmag_sub,
        'positions': pos_sub,
        'probes': ds.probe,
        'object_init': ds.object_init,
        'asize': (asize, asize),
        'Npos': Npos_sub,
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
    print(f"    [{label}] DM done: {dm_time:.0f}s")

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
    print(f"    [{label}] ML done: {ml_time:.0f}s")

    ob_final = p_ml['object'][0].squeeze()
    return ob_final, dm_time + ml_time


def main():
    lambda_m = 1239.842e-9 / (ENERGY_KEV * 1e3)
    dx_m = lambda_m * Z_M / (ASIZE * DET_PIXEL_M)
    dx_nm = dx_m * 1e9

    print("=== Split-data Phase FSC Resolution Estimation ===")
    print(f"  Energy: {ENERGY_KEV} keV, z: {Z_M} m, asize: {ASIZE}")
    print(f"  Pixel size: {dx_nm:.2f} nm, FOV: {ASIZE*dx_nm:.0f} nm")
    print(f"  N_photons: {N_PHOTONS:.0e}")
    print(f"  Pipeline: DM {DM_ITER} -> ML {ML_ITER}")
    print(f"  Method: even/odd split -> 2x independent recon -> phase FSC")

    dl = DataLoader()

    scenarios = [
        {'name': 'S1: 1-mode (baseline)', 'tag': 'S1', 'n_fwd': 1, 'f_coh': 1.0, 'n_recon': 1},
        {'name': 'S3: 3fwd-1recon f=0.3', 'tag': 'S3', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 1},
        {'name': 'S4: 3fwd-3recon f=0.3', 'tag': 'S4', 'n_fwd': 3, 'f_coh': 0.3, 'n_recon': 3},
    ]

    results = []
    margin = ASIZE // 4

    for sc in scenarios:
        print(f"\n{'=' * 70}")
        print(f"  {sc['name']}")
        print(f"{'=' * 70}")

        ds = make_data(sc['n_fwd'], sc['f_coh'], dl)
        Npos = ds.Npos
        print(f"  Npos={Npos} (will split to ~{Npos//2} each)")

        # Split positions
        idx_even, idx_odd = split_positions(Npos, method='even_odd')
        print(f"  Split: even={len(idx_even)}, odd={len(idx_odd)}")

        # Reconstruct each half independently
        print(f"  --- Half 1 (even positions) ---")
        ob_even, t_even = run_dm_ml_subset(ds, dl, sc['n_recon'], idx_even, label='even')

        print(f"  --- Half 2 (odd positions) ---")
        ob_odd, t_odd = run_dm_ml_subset(ds, dl, sc['n_recon'], idx_odd, label='odd')

        total_time = t_even + t_odd

        # Split-data Phase FSC (the correct method)
        fsc_split = fsc_phase(ob_even, ob_odd, pixel_size_nm=dx_nm, margin=margin)

        # Also compute GT-phase FSC for comparison (using full-data recon)
        # Run full reconstruction
        print(f"  --- Full data (for GT comparison) ---")
        ob_full, t_full = run_dm_ml_subset(ds, dl, sc['n_recon'],
                                            np.arange(Npos), label='full')
        fsc_gt = fsc_phase(ob_full, ds.object_true, pixel_size_nm=dx_nm, margin=margin)

        split_res = fsc_split['resolution_nm']
        split_hb = fsc_split['resolution_half_bit_nm']
        gt_res = fsc_gt['resolution_nm']
        gt_hb = fsc_gt['resolution_half_bit_nm']

        print(f"\n  RESULTS:")
        print(f"    Split-data phase FSC @0.5:    {split_res:.1f} nm" if split_res else "    Split-data phase FSC @0.5:    N/A")
        print(f"    Split-data phase FSC @1/2bit: {split_hb:.1f} nm" if split_hb else "    Split-data phase FSC @1/2bit: N/A")
        print(f"    GT-phase FSC @0.5:            {gt_res:.1f} nm" if gt_res else "    GT-phase FSC @0.5:            N/A")
        print(f"    GT-phase FSC @1/2bit:         {gt_hb:.1f} nm" if gt_hb else "    GT-phase FSC @1/2bit:         N/A")
        print(f"    Total time: {total_time:.0f}s (split) + {t_full:.0f}s (full)")

        results.append({
            'name': sc['name'], 'tag': sc['tag'],
            'ob_even': ob_even, 'ob_odd': ob_odd, 'ob_full': ob_full,
            'gt': ds.object_true,
            'fsc_split': fsc_split, 'fsc_gt': fsc_gt,
            'time_split': total_time, 'time_full': t_full,
            'n_fwd': sc['n_fwd'], 'n_recon': sc['n_recon'],
        })

    # ── Plot ──
    n = len(results)
    fig, axes = plt.subplots(3, n, figsize=(6 * n, 14))

    for i, res in enumerate(results):
        m = margin
        ob_full = res['ob_full']
        gt = res['gt']
        oh, ow = ob_full.shape

        # Row 0: Phase comparison (GT vs Full recon)
        axes[0, i].imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[0, i].set_title(f'{res["tag"]}: GT phase', fontweight='bold', fontsize=10)
        axes[0, i].axis('off')

        # Row 1: Phase of full reconstruction
        axes[1, i].imshow(np.angle(ob_full[m:oh-m, m:ow-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, i].set_title(f'Recon phase ({res["n_fwd"]}fwd-{res["n_recon"]}rec)',
                             fontweight='bold', fontsize=10)
        axes[1, i].axis('off')

        # Row 2: FSC comparison (split-data vs GT)
        freq_s = res['fsc_split']['freq_nm_inv']
        freq_g = res['fsc_gt']['freq_nm_inv']
        ax = axes[2, i]
        ax.plot(freq_s[1:], res['fsc_split']['fsc'][1:], 'b-', linewidth=1.5, label='Split-data')
        ax.plot(freq_g[1:], res['fsc_gt']['fsc'][1:], 'r-', linewidth=1.5, alpha=0.7, label='vs GT')
        ax.plot(freq_s[1:], res['fsc_split']['half_bit'][1:], 'g--', linewidth=0.8, alpha=0.5, label='1/2-bit')
        ax.axhline(y=0.5, color='k', linestyle='--', linewidth=0.8, alpha=0.5)

        split_r = res['fsc_split']['resolution_nm']
        gt_r = res['fsc_gt']['resolution_nm']
        lbl = f'{res["tag"]}\nSplit: '
        lbl += f'{split_r:.1f} nm' if split_r else 'N/A'
        lbl += f'\nGT: '
        lbl += f'{gt_r:.1f} nm' if gt_r else 'N/A'
        ax.set_title(lbl, fontweight='bold', fontsize=9)
        ax.set_xlabel('Spatial freq (1/nm)', fontsize=8)
        ax.set_ylabel('FSC', fontsize=8)
        ax.set_ylim(-0.05, 1.05)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    fig.suptitle(
        f'Split-data Phase FSC vs GT-Phase FSC\n'
        f'DM{DM_ITER}+ML{ML_ITER}, {ENERGY_KEV}keV, 50nm beam, N_ph=1e8',
        fontsize=13, fontweight='bold')
    plt.tight_layout()
    out = str(OUT_DIR / '_split_fsc_comparison.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n[SAVED] {out}")

    # ── Summary ──
    print(f"\n{'=' * 80}")
    print(f"  SUMMARY: Split-data Phase FSC vs GT-Phase FSC")
    print(f"{'=' * 80}")
    print(f"  {'Tag':<5} {'Scenario':<28} {'Split@0.5':>10} {'Split@1/2b':>10} {'GT@0.5':>10} {'GT@1/2b':>10}")
    print(f"  {'-'*5} {'-'*28} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for res in results:
        fs = res['fsc_split']
        fg = res['fsc_gt']
        s05 = '%.1f nm' % fs['resolution_nm'] if fs['resolution_nm'] else 'N/A'
        shb = '%.1f nm' % fs['resolution_half_bit_nm'] if fs['resolution_half_bit_nm'] else 'N/A'
        g05 = '%.1f nm' % fg['resolution_nm'] if fg['resolution_nm'] else 'N/A'
        ghb = '%.1f nm' % fg['resolution_half_bit_nm'] if fg['resolution_half_bit_nm'] else 'N/A'
        print(f"  {res['tag']:<5} {res['name']:<28} {s05:>10} {shb:>10} {g05:>10} {ghb:>10}")


if __name__ == '__main__':
    main()
