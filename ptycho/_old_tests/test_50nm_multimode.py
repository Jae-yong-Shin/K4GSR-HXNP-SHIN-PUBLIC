"""
50nm beam multi-mode verification test.

Based on known-good Scenario B parameters (10keV, 50nm, asize=256, z=1m).
Tests:
  1. Single-mode (f_coh=1.0) — baseline, must match GT
  2. Multi-mode forward + single-mode recon — expect degradation
  3. Multi-mode forward + multi-mode recon — should improve vs #2

Uses GPU DM engine with proper overlap (>=60%).

MEMORY: Known-good B params from test_full_pipeline.py:
  energy=10keV, z=1m, asize=256, FWHM=50nm, step=0.02um(60% overlap), N_photons=1000
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


def make_data(n_modes_fwd, f_coh, dl, beam_params,
              asize, energy_keV, z_m, det_pixel_m, N_photons):
    """Generate synthetic data with specified coherence."""
    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=N_photons,
        scan_step_um=None, overlap=0.70,   # 70% overlap for safety
        scan_lx_um=0.4, scan_ly_um=0.4,   # 400nm range
        probe=dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m),
        N_modes=n_modes_fwd,
        coherent_fraction=f_coh,
    )
    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    return ds


def run_dm_recon(ds, dl, n_modes_recon, n_iter=300):
    """Run GPU DM reconstruction."""
    from engines.gpu.DM import DM as DM_GPU

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
        'number_iterations': n_iter,
        'use_gpu': True,
        'pfft_relaxation': 0.05,
        'probe_change_start': 1,
        'object_change_start': 1,
        'probe_inertia': 0.9,
        'probe_modes': n_modes_recon,
    })

    # Prepare probes
    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']

    if n_modes_recon > 1:
        # Stack probe modes: (H, W, N_modes)
        Ny, Nx = probes_in.shape
        probes_3d = np.zeros((Ny, Nx, n_modes_recon), dtype=np.complex64)
        probes_3d[:, :, 0] = probes_in
        # Higher modes: scaled copies with random phase
        rng = np.random.default_rng(123)
        for m in range(1, n_modes_recon):
            scale = 0.3 ** m
            rand_phase = np.exp(2j * np.pi * rng.random((Ny, Nx)).astype(np.float32))
            probes_3d[:, :, m] = probes_in * scale * rand_phase
        probes_in = probes_3d

    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    t0 = time.time()
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=n_iter)
    elapsed = time.time() - t0

    return ob_dm[0], pr_dm, err_dm, elapsed


def compute_norm_error(recon, truth, margin):
    """Compute norm error between recon and truth (center cropped)."""
    oh, ow = recon.shape
    th, tw = truth.shape
    ch = min(oh, th) - 2 * margin
    cw = min(ow, tw) - 2 * margin
    if ch <= 0 or cw <= 0:
        return 1.0

    r = recon[oh // 2 - ch // 2:oh // 2 + ch // 2, ow // 2 - cw // 2:ow // 2 + cw // 2]
    t = truth[th // 2 - ch // 2:th // 2 + ch // 2, tw // 2 - cw // 2:tw // 2 + cw // 2]

    # Phase alignment
    phase_off = np.angle(np.sum(r * np.conj(t)))
    r_aligned = r * np.exp(-1j * phase_off)

    err = np.sqrt(np.sum(np.abs(r_aligned - t) ** 2) / np.sum(np.abs(t) ** 2))
    return float(err)


def main():
    # ── Parameters (50nm beam, known-good B) ──
    asize = 256
    energy_keV = 10.0
    z_m = 1.0
    det_pixel_m = 75e-6
    N_photons = 1000

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_m = lambda_m * z_m / (asize * det_pixel_m)
    dx_nm = dx_m * 1e9
    print(f"=== 50nm Beam Multi-mode Verification ===")
    print(f"  Energy: {energy_keV} keV, z: {z_m} m, asize: {asize}")
    print(f"  Pixel size: {dx_nm:.2f} nm")
    print(f"  FOV: {asize * dx_nm:.0f} nm")

    beam_params = {
        'fwhm_h_m': 50e-9,
        'fwhm_v_m': 80e-9,
        'focal_length_m': 0.205,
        'defocus_m': 0.0,
    }

    dl = DataLoader()
    probe = dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m)
    fwhm_px = estimate_probe_fwhm(probe)
    print(f"  Probe FWHM: {fwhm_px:.1f} px ({fwhm_px * dx_nm:.1f} nm)")

    # ── Scenarios ──
    scenarios = [
        {
            'name': 'S1: Single-mode (f_coh=1.0)',
            'n_modes_fwd': 1, 'f_coh': 1.0,
            'n_modes_recon': 1, 'n_iter': 300,
        },
        {
            'name': 'S2: 3-mode fwd, 1-mode recon (f_coh=0.5)',
            'n_modes_fwd': 3, 'f_coh': 0.5,
            'n_modes_recon': 1, 'n_iter': 300,
        },
        {
            'name': 'S3: 3-mode fwd, 3-mode recon (f_coh=0.5)',
            'n_modes_fwd': 3, 'f_coh': 0.5,
            'n_modes_recon': 3, 'n_iter': 300,
        },
    ]

    results = []
    margin = asize // 4  # crop margin for error calc

    for sc in scenarios:
        print(f"\n{'=' * 60}")
        print(f"  {sc['name']}")
        print(f"{'=' * 60}")

        # Generate data
        print("  Generating synthetic data...")
        ds = make_data(
            sc['n_modes_fwd'], sc['f_coh'], dl, beam_params,
            asize, energy_keV, z_m, det_pixel_m, N_photons)
        print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2%}, "
              f"probe_fwhm={ds.probe_fwhm:.1f}px, avg_step={ds.avg_step:.1f}px")

        # Check overlap is adequate
        if ds.overlap < 0.5:
            print(f"  WARNING: overlap={ds.overlap:.2%} < 50%, results may be poor!")

        # Run reconstruction
        print(f"  Running DM {sc['n_iter']} iter (modes_recon={sc['n_modes_recon']})...")
        ob_recon, pr_recon, err, elapsed = run_dm_recon(
            ds, dl, sc['n_modes_recon'], sc['n_iter'])

        # Compute quality
        norm_err = compute_norm_error(ob_recon, ds.object_true, margin)
        obj_amp_max = float(np.abs(ob_recon).max())
        gt_amp_max = float(np.abs(ds.object_true).max())

        final_err = float(err[sc['n_iter']]) if err[sc['n_iter']] > 0 else float(err[-1])
        print(f"  norm_error={norm_err:.4f}, obj_amp_max={obj_amp_max:.3f} "
              f"(GT={gt_amp_max:.3f}), fourier_err={final_err:.4e}, time={elapsed:.1f}s")

        results.append({
            'name': sc['name'],
            'ob_recon': ob_recon,
            'pr_recon': pr_recon,
            'err': err,
            'norm_error': norm_err,
            'obj_amp_max': obj_amp_max,
            'elapsed': elapsed,
            'gt': ds.object_true,
            'probe_gt': ds.probe,
            'n_iter': sc['n_iter'],
        })

    # ── Plot comparison ──
    n_sc = len(results)
    fig, axes = plt.subplots(3, n_sc + 1, figsize=(5 * (n_sc + 1), 15))

    gt = results[0]['gt']
    m = margin

    # GT column
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1
    axes[0, 0].imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    axes[0, 0].set_title('Ground Truth\n(amplitude)', fontweight='bold')
    axes[0, 0].axis('off')

    gt_phase = np.angle(gt[m:-m, m:-m])
    axes[1, 0].imshow(gt_phase, cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 0].set_title('Ground Truth\n(phase)', fontweight='bold')
    axes[1, 0].axis('off')

    # Probe GT
    p_gt = np.abs(results[0]['probe_gt'])
    axes[2, 0].imshow(p_gt, cmap='jet')
    axes[2, 0].set_title(f'Probe GT\nFWHM={estimate_probe_fwhm(results[0]["probe_gt"]):.1f}px',
                         fontweight='bold')
    axes[2, 0].axis('off')

    for i, res in enumerate(results):
        col = i + 1
        ob = res['ob_recon']
        oh, ow = ob.shape

        # Amplitude
        r_amp = np.abs(ob[m:-m if m > 0 else oh, m:-m if m > 0 else ow])
        r_vmin = np.percentile(r_amp, 1)
        r_vmax = np.percentile(r_amp, 99.5) * 1.1
        axes[0, col].imshow(r_amp, cmap='jet', vmin=r_vmin, vmax=r_vmax)
        axes[0, col].set_title(
            f'{res["name"]}\nnorm_err={res["norm_error"]:.4f}\n'
            f'|obj|max={res["obj_amp_max"]:.3f}',
            fontweight='bold', fontsize=9)
        axes[0, col].axis('off')

        # Phase
        r_phase = np.angle(ob[m:-m if m > 0 else oh, m:-m if m > 0 else ow])
        axes[1, col].imshow(r_phase, cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, col].set_title(f'Phase\n({res["elapsed"]:.0f}s)', fontsize=9)
        axes[1, col].axis('off')

        # Probe
        if res['pr_recon'].ndim == 3:
            # Multi-mode: show incoherent sum
            pr_amp = np.sqrt(np.sum(np.abs(res['pr_recon']) ** 2, axis=2))
            n_modes_str = f'{res["pr_recon"].shape[2]} modes'
        else:
            pr_amp = np.abs(res['pr_recon'])
            n_modes_str = '1 mode'
        axes[2, col].imshow(pr_amp, cmap='jet')
        axes[2, col].set_title(f'Probe recon\n({n_modes_str})', fontsize=9)
        axes[2, col].axis('off')

    fig.suptitle(
        f'50nm Beam Multi-mode Verification\n'
        f'{energy_keV}keV, asize={asize}, z={z_m}m, dx={dx_nm:.1f}nm',
        fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = str(Path(__file__).parent / '_50nm_multimode_verify.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n[SAVED] {out}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    for res in results:
        status = "PASS" if res['norm_error'] < 0.3 else "FAIL"
        print(f"  [{status}] {res['name']}: "
              f"norm_err={res['norm_error']:.4f}, "
              f"|obj|max={res['obj_amp_max']:.3f}")

    # S1 should be good (< 0.2)
    # S2 should be worse than S1 (mode mismatch)
    # S3 should be better than S2 (matching modes)
    if results[0]['norm_error'] < 0.3:
        print("\n  Single-mode baseline: OK")
    else:
        print("\n  WARNING: Single-mode baseline failed!")

    if len(results) >= 3:
        if results[2]['norm_error'] < results[1]['norm_error']:
            print("  Multi-mode recon improves over single-mode recon: OK")
        else:
            print("  WARNING: Multi-mode recon did NOT improve over single-mode!")


if __name__ == '__main__':
    main()
