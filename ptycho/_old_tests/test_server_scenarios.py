"""
test_server_scenarios.py - End-to-end ptycho pipeline verification through server data_loader.

Three coherence scenarios:
  A: Full coherence     (SSA=5um,   f_coh=1.0,  N_modes=1)
  B: Partial coherence  (SSA=50um,  f_coh=0.3,  N_modes=3)
  C: Strong partial     (SSA=100um, f_coh=0.15, N_modes=5)

Each scenario: generate synthetic data -> DM 300 -> ML 100 -> norm_error + FSC
"""
import sys
import time
import numpy as np
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# -- Setup paths (only K4GSR-Beamline/ptycho) --
PTYCHO_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PTYCHO_DIR))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm


# ============================================================
#  FSC (Fourier Shell Correlation) -- inline implementation
# ============================================================
def fsc_2d(img1, img2, pixel_size_nm=1.0):
    """
    Compute Fourier Shell Correlation between two 2D complex images.

    Parameters
    ----------
    img1, img2 : np.ndarray (2D, complex or real)
        Images to compare. Will be center-cropped to same size.
    pixel_size_nm : float
        Pixel size in nm for frequency -> spatial resolution conversion.

    Returns
    -------
    freq : np.ndarray
        Spatial frequency values (1/nm).
    fsc : np.ndarray
        FSC curve (correlation per ring).
    resolution_nm : float
        Resolution at FSC=0.5 threshold. np.inf if never crosses.
    """
    # Ensure complex
    img1 = np.asarray(img1, dtype=np.complex128)
    img2 = np.asarray(img2, dtype=np.complex128)

    # Center-crop to same size
    ny = min(img1.shape[0], img2.shape[0])
    nx = min(img1.shape[1], img2.shape[1])
    def _crop(im, ny, nx):
        cy, cx = im.shape[0] // 2, im.shape[1] // 2
        return im[cy - ny // 2: cy - ny // 2 + ny,
                   cx - nx // 2: cx - nx // 2 + nx]
    img1 = _crop(img1, ny, nx)
    img2 = _crop(img2, ny, nx)

    # Phase-align: find global phase offset that minimizes ||img1 - img2*exp(i*phi)||
    cross = np.sum(img1 * np.conj(img2))
    phase_offset = np.angle(cross)
    img2 = img2 * np.exp(1j * phase_offset)

    # 2D FFT (centered)
    F1 = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(img1)))
    F2 = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(img2)))

    # Radial coordinate grid
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=pixel_size_nm))
    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=pixel_size_nm))
    FY, FX = np.meshgrid(fy, fx, indexing='ij')
    R = np.sqrt(FX**2 + FY**2)

    # Radial binning
    max_freq = 0.5 / pixel_size_nm  # Nyquist
    n_bins = min(ny, nx) // 2
    bin_edges = np.linspace(0, max_freq, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    fsc_vals = np.zeros(n_bins)
    for i in range(n_bins):
        mask = (R >= bin_edges[i]) & (R < bin_edges[i + 1])
        if mask.sum() == 0:
            fsc_vals[i] = 0.0
            continue
        num = np.abs(np.sum(F1[mask] * np.conj(F2[mask])))
        den = np.sqrt(np.sum(np.abs(F1[mask])**2) * np.sum(np.abs(F2[mask])**2))
        fsc_vals[i] = num / max(den, 1e-30)

    # Resolution at FSC = 0.5 threshold
    resolution_nm = np.inf
    for i in range(len(fsc_vals) - 1):
        if fsc_vals[i] >= 0.5 and fsc_vals[i + 1] < 0.5:
            # Linear interpolation
            f0 = bin_centers[i]
            f1 = bin_centers[i + 1]
            fsc0 = fsc_vals[i]
            fsc1 = fsc_vals[i + 1]
            f_cross = f0 + (0.5 - fsc0) / (fsc1 - fsc0) * (f1 - f0)
            resolution_nm = 1.0 / max(f_cross, 1e-30)
            break

    return bin_centers, fsc_vals, resolution_nm


# ============================================================
#  Norm error (phase-aligned, cropped)
# ============================================================
def norm_error(obj_true, obj_recon, margin=10):
    """
    Normalized reconstruction error with phase alignment.
    ||O_true - O_recon * exp(i*phi)||^2 / ||O_true||^2
    """
    ot = np.asarray(obj_true, dtype=np.complex128)
    orc = np.asarray(obj_recon, dtype=np.complex128)

    # Center-crop to same size
    ny = min(ot.shape[0], orc.shape[0])
    nx = min(ot.shape[1], orc.shape[1])
    cy1, cx1 = ot.shape[0] // 2, ot.shape[1] // 2
    cy2, cx2 = orc.shape[0] // 2, orc.shape[1] // 2
    ot = ot[cy1 - ny // 2: cy1 - ny // 2 + ny,
            cx1 - nx // 2: cx1 - nx // 2 + nx]
    orc = orc[cy2 - ny // 2: cy2 - ny // 2 + ny,
              cx2 - nx // 2: cx2 - nx // 2 + nx]

    # Apply margin
    if margin > 0:
        ot = ot[margin:-margin, margin:-margin]
        orc = orc[margin:-margin, margin:-margin]

    # Phase-align
    cross = np.sum(ot * np.conj(orc))
    phi = np.angle(cross)
    orc_aligned = orc * np.exp(1j * phi)

    err = np.sum(np.abs(ot - orc_aligned)**2) / np.sum(np.abs(ot)**2)
    return float(err)


# ============================================================
#  Run single scenario
# ============================================================
def run_scenario(label, f_coh, n_modes, energy_keV=10.0, asize=128):
    """Generate synthetic data and run DM 300 + ML 100."""
    print(f"\n{'='*70}")
    print(f"  Scenario {label}: f_coh={f_coh:.2f}, N_modes={n_modes}")
    print(f"{'='*70}")

    z_m = 0.15
    det_pixel_m = 75e-6
    N_photons = 1e8
    overlap = 0.75
    scan_lx_um = 0.25
    scan_ly_um = 0.25

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_spec = lambda_m * z_m / (asize * det_pixel_m)
    pixel_nm = dx_spec * 1e9

    print(f"  dx = {pixel_nm:.2f} nm, FOV = {asize * pixel_nm:.0f} nm")

    dl = DataLoader()

    # Build Fresnel probe (KB mirror, 50nm spot)
    beam_params = {
        'fwhm_h_m': 50e-9,
        'fwhm_v_m': 50e-9,
        'focal_length_m': 0.1,
        'defocus_m': 0.0,
    }
    probe = dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m)
    fwhm_px = estimate_probe_fwhm(probe)
    print(f"  Probe FWHM = {fwhm_px:.1f} px ({fwhm_px * pixel_nm:.1f} nm)")

    # Generate synthetic data
    t0 = time.time()
    gen = SyntheticPtycho.from_dataset(
        dataset_id=6,
        asize=asize,
        energy_keV=energy_keV,
        z_m=z_m,
        det_pixel_size_m=det_pixel_m,
        N_photons=N_photons,
        scan_step_um=None,
        overlap=overlap,
        scan_lx_um=scan_lx_um,
        scan_ly_um=scan_ly_um,
        probe=probe,
        N_modes=n_modes,
        coherent_fraction=f_coh,
    )
    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    t_gen = time.time() - t0
    print(f"  Generated: Npos={ds.Npos}, overlap={ds.overlap:.2f} ({t_gen:.1f}s)")

    # Store ground truth
    obj_true = ds.object_true.copy()

    # Build p dict for engine
    data = {
        'fmag': ds.fmag,
        'positions': ds.positions_clean,
        'probes': ds.probe,
        'object_init': ds.object_init,
        'asize': (asize, asize),
        'Npos': ds.Npos,
        'object_true': obj_true,
    }

    # ── Stage 1: DM 300 iterations ──
    print(f"\n  [DM] Running 300 iterations...")
    t0 = time.time()
    p_dm = dl.build_p_dict(data, {
        'number_iterations': 300,
        'use_gpu': True,
        'pfft_relaxation': 0.05,
        'probe_change_start': 1,
        'probe_modes': 1,  # DM runs single mode
    })
    p_dm['object_true'] = obj_true  # for error tracking

    from server.engine_runner import EngineRunner
    messages = []
    runner = EngineRunner(
        broadcast_fn=lambda msg: messages.append(msg),
    )
    # Run DM directly (not through runner thread for simplicity)
    try:
        from engines.gpu.DM import DM as DM_GPU
        probes_in = p_dm['probes']
        if probes_in.ndim == 4:
            probes_in = probes_in[:, :, 0, 0]
        ob = p_dm['object']
        if isinstance(ob, list):
            ob = [o.squeeze() if o.ndim > 2 else o for o in ob]
        ob_dm, pr_dm, err_dm = DM_GPU(
            p_dm, ob=ob, probes=probes_in,
            fmag=p_dm['fmag'], positions=p_dm['positions'],
            num_iterations=300
        )
    except Exception as e:
        print(f"  [DM] GPU failed ({e}), trying CPU...")
        from engines.DM import DM
        p_dm['use_gpu'] = False
        p_out_dm, fdb_dm = DM(p_dm)
        ob_dm = p_out_dm['object']
        pr_dm = p_out_dm['probes']
        err_dm = fdb_dm.get('error', [])

    t_dm = time.time() - t0
    print(f"  [DM] Done in {t_dm:.1f}s")

    # Get DM object
    if isinstance(ob_dm, list):
        obj_dm = ob_dm[0].squeeze() if hasattr(ob_dm[0], 'squeeze') else ob_dm[0]
    else:
        obj_dm = ob_dm.squeeze() if hasattr(ob_dm, 'squeeze') else ob_dm

    # Get DM probe
    if hasattr(pr_dm, 'ndim'):
        probe_dm = pr_dm.squeeze() if pr_dm.ndim > 2 else pr_dm
    else:
        probe_dm = pr_dm

    ne_dm = norm_error(obj_true, obj_dm)
    print(f"  [DM] norm_error = {ne_dm:.6f}")

    # ── Stage 2: ML 100 iterations (from DM result) ──
    print(f"\n  [ML] Running 100 iterations from DM result...")
    t0 = time.time()

    # Build ML input from DM output
    p_ml = dict(p_dm)
    if isinstance(obj_dm, np.ndarray):
        if obj_dm.ndim == 2:
            p_ml['object'] = [obj_dm[:, :, np.newaxis].astype(np.complex128)]
        else:
            p_ml['object'] = [obj_dm.astype(np.complex128)]
    else:
        p_ml['object'] = [np.array(obj_dm, dtype=np.complex128)]

    if hasattr(pr_dm, 'ndim'):
        if pr_dm.ndim == 2:
            p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1).astype(np.complex128)
        elif pr_dm.ndim == 3:
            p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, pr_dm.shape[2]).astype(np.complex128)
        else:
            p_ml['probes'] = pr_dm.astype(np.complex128)
    else:
        p_ml['probes'] = np.array(pr_dm, dtype=np.complex128).reshape(asize, asize, 1, 1)

    p_ml['opt_iter'] = 100
    p_ml['opt_flags'] = [1, 1]
    p_ml['opt_errmetric'] = 'poisson'
    p_ml['opt_ftol'] = 1e-4
    p_ml['opt_xtol'] = 1e-4
    p_ml['use_gpu'] = True

    if isinstance(p_ml.get('object_size'), list):
        p_ml['object_size'] = np.array(p_ml['object_size'])

    try:
        from engines.ML import ML
        p_out_ml, fdb_ml = ML(p_ml)
    except Exception as e:
        print(f"  [ML] Error: {e}")
        import traceback
        traceback.print_exc()
        # Use DM result as fallback
        p_out_ml = p_ml
        fdb_ml = {'error': []}

    t_ml = time.time() - t0
    print(f"  [ML] Done in {t_ml:.1f}s")

    # Get ML object
    obj_ml = p_out_ml['object']
    if isinstance(obj_ml, list):
        obj_ml = obj_ml[0]
    if hasattr(obj_ml, 'squeeze'):
        obj_ml = obj_ml.squeeze()

    ne_ml = norm_error(obj_true, obj_ml)
    print(f"  [ML] norm_error = {ne_ml:.6f}")

    # ── FSC ──
    freq, fsc_vals, res_nm = fsc_2d(obj_true, obj_ml, pixel_size_nm=pixel_nm)
    print(f"  FSC resolution (0.5 threshold) = {res_nm:.2f} nm")

    return {
        'label': label,
        'f_coh': f_coh,
        'n_modes': n_modes,
        'obj_true': obj_true,
        'obj_dm': obj_dm,
        'obj_ml': obj_ml,
        'ne_dm': ne_dm,
        'ne_ml': ne_ml,
        'freq': freq,
        'fsc': fsc_vals,
        'res_nm': res_nm,
        'pixel_nm': pixel_nm,
        't_dm': t_dm,
        't_ml': t_ml,
        'err_dm': err_dm if hasattr(err_dm, '__len__') else [err_dm],
    }


# ============================================================
#  Save comparison figure
# ============================================================
def save_comparison(results, outpath):
    """Save comparison images with FSC plots for all scenarios."""
    n = len(results)
    fig, axes = plt.subplots(n, 5, figsize=(25, 5 * n), dpi=120)
    if n == 1:
        axes = axes[np.newaxis, :]

    for i, r in enumerate(results):
        # Column 0: True object amplitude
        amp_true = np.abs(r['obj_true'])
        vmax_amp = np.percentile(amp_true, 99.5) * 1.1
        axes[i, 0].imshow(amp_true, cmap='jet', vmin=0, vmax=vmax_amp)
        axes[i, 0].set_title(f"Scenario {r['label']}: True |O|")
        axes[i, 0].axis('off')

        # Column 1: DM object amplitude
        amp_dm = np.abs(r['obj_dm'])
        # Crop to match true
        ny = min(amp_true.shape[0], amp_dm.shape[0])
        nx = min(amp_true.shape[1], amp_dm.shape[1])
        cy, cx = amp_dm.shape[0] // 2, amp_dm.shape[1] // 2
        amp_dm_crop = amp_dm[cy - ny // 2: cy - ny // 2 + ny,
                             cx - nx // 2: cx - nx // 2 + nx]
        axes[i, 1].imshow(amp_dm_crop, cmap='jet', vmin=0, vmax=vmax_amp)
        axes[i, 1].set_title(f"DM 300 |O| (err={r['ne_dm']:.4f})")
        axes[i, 1].axis('off')

        # Column 2: ML object amplitude
        amp_ml = np.abs(r['obj_ml'])
        cy, cx = amp_ml.shape[0] // 2, amp_ml.shape[1] // 2
        amp_ml_crop = amp_ml[cy - ny // 2: cy - ny // 2 + ny,
                             cx - nx // 2: cx - nx // 2 + nx]
        axes[i, 2].imshow(amp_ml_crop, cmap='jet', vmin=0, vmax=vmax_amp)
        axes[i, 2].set_title(f"DM+ML 100 |O| (err={r['ne_ml']:.4f})")
        axes[i, 2].axis('off')

        # Column 3: Phase of ML reconstruction
        phase_ml = np.angle(r['obj_ml'])
        cy, cx = phase_ml.shape[0] // 2, phase_ml.shape[1] // 2
        phase_ml_crop = phase_ml[cy - ny // 2: cy - ny // 2 + ny,
                                 cx - nx // 2: cx - nx // 2 + nx]
        axes[i, 3].imshow(phase_ml_crop, cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[i, 3].set_title(f"DM+ML phase")
        axes[i, 3].axis('off')

        # Column 4: FSC curve
        ax_fsc = axes[i, 4]
        ax_fsc.plot(r['freq'], r['fsc'], 'b-', linewidth=2, label='FSC')
        ax_fsc.axhline(y=0.5, color='r', linestyle='--', linewidth=1, label='0.5 threshold')
        if np.isfinite(r['res_nm']):
            ax_fsc.axvline(x=1.0 / r['res_nm'], color='g', linestyle=':', linewidth=1,
                           label=f'Res={r["res_nm"]:.1f} nm')
        ax_fsc.set_xlabel('Spatial freq (1/nm)')
        ax_fsc.set_ylabel('FSC')
        ax_fsc.set_title(f"FSC: {r['label']} (res={r['res_nm']:.1f} nm)")
        ax_fsc.set_ylim(-0.1, 1.1)
        ax_fsc.legend(loc='lower left', fontsize=8)
        ax_fsc.grid(True, alpha=0.3)

    plt.suptitle(
        'Ptycho Coherence Scenarios: Full / Partial / Strong Partial\n'
        'DM 300 + ML 100 | 10 keV, 50nm beam, asize=128, z=0.15m, 1e8 photons',
        fontsize=14, fontweight='bold', y=1.02
    )
    plt.tight_layout()
    plt.savefig(outpath, dpi=120, bbox_inches='tight')
    print(f"\n  Saved: {outpath}")
    plt.close()


# ============================================================
#  Main
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("  Ptycho Pipeline E2E Test: 3 Coherence Scenarios")
    print("  DM 300 + ML 100 | 10 keV, 50nm beam, 128px, z=0.15m, 1e8 photons")
    print("=" * 70)

    t_start = time.time()

    scenarios = [
        ('A', 1.0,  1),   # Full coherence (SSA=5um)
        ('B', 0.3,  3),   # Partial coherence (SSA=50um)
        ('C', 0.15, 5),   # Strong partial coherence (SSA=100um)
    ]

    results = []
    for label, f_coh, n_modes in scenarios:
        r = run_scenario(label, f_coh, n_modes)
        results.append(r)

    # ── Summary ──
    t_total = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"{'Scenario':<12} {'f_coh':>6} {'Modes':>6} {'DM err':>10} {'ML err':>10} {'FSC res':>10} {'DM time':>8} {'ML time':>8}")
    print(f"{'-'*12} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")
    for r in results:
        res_str = f"{r['res_nm']:.1f} nm" if np.isfinite(r['res_nm']) else "N/A"
        print(f"{r['label']:<12} {r['f_coh']:>6.2f} {r['n_modes']:>6d} {r['ne_dm']:>10.6f} {r['ne_ml']:>10.6f} {res_str:>10} {r['t_dm']:>7.1f}s {r['t_ml']:>7.1f}s")
    print(f"\nTotal time: {t_total:.1f}s")

    # Save comparison figure
    outpath = str(PTYCHO_DIR / 'test_server_scenarios_result.png')
    save_comparison(results, outpath)

    # ── Pass/Fail check ──
    all_ok = True
    for r in results:
        if r['ne_ml'] > 0.5:
            print(f"\n  WARN: Scenario {r['label']} ML norm_error={r['ne_ml']:.4f} > 0.5 (poor reconstruction)")
            all_ok = False
        if r['ne_ml'] > r['ne_dm'] * 10:
            print(f"\n  WARN: Scenario {r['label']} ML ({r['ne_ml']:.4f}) >> DM ({r['ne_dm']:.4f}) -- ML may have diverged")
            all_ok = False

    if all_ok:
        print("\n  All scenarios passed quality checks.")
    else:
        print("\n  Some scenarios had warnings -- check results.")

    print(f"\n  Output: {outpath}")
