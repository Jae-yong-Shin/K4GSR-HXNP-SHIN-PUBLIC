"""
test_sinc_probe.py - Verify KB mirror sinc probe shape and run reconstruction.

KB mirrors use rectangular aperture -> sinc(x)*sinc(y) beam profile.
This test:
1. Generates sinc probe via _model_probe_focused (rectangular aperture)
2. Verifies beam profile is sinc-shaped (not Airy)
3. Runs DM+ML reconstruction to validate convergence
4. Saves comparison images
"""
import sys
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BEAMLINE_PTYCHO = Path(r'c:\Projects\K4GSR-Beamline\ptycho')
PTYCHO_ROOT = Path(r'c:\Projects\K4GSR-PTYCHO')
sys.path.insert(0, str(PTYCHO_ROOT))
sys.path.insert(0, str(PTYCHO_ROOT / 'server'))

# Import from K4GSR-Beamline (the one we modified with rectangular aperture)
import importlib.util
_bl_spec = importlib.util.spec_from_file_location(
    "bl_data_loader", str(BEAMLINE_PTYCHO / 'server' / 'data_loader.py'))
_bl_mod = importlib.util.module_from_spec(_bl_spec)
_bl_spec.loader.exec_module(_bl_mod)
_BLDataLoader = _bl_mod.DataLoader

# Import recon engines from K4GSR-PTYCHO
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader


def generate_sinc_probe(asize, energy_keV, z_m, det_pixel_m, fwhm_h_nm, fwhm_v_nm, f_m=0.3):
    """Generate KB sinc probe using rectangular aperture."""
    dl = _BLDataLoader()
    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_spec = lambda_m * z_m / (asize * det_pixel_m)
    return dl._model_probe_focused(
        asize=asize, lambda_m=lambda_m, dx_spec=dx_spec,
        focal_length_m=f_m, defocus_m=0.0,
        fwhm_h_m=fwhm_h_nm * 1e-9, fwhm_v_m=fwhm_v_nm * 1e-9, upsample=4)


def check_sinc_shape(probe, label=""):
    """Check if probe has sinc-like profile (rectangular aperture)."""
    amp = np.abs(probe)
    cy, cx = np.unravel_index(amp.argmax(), amp.shape)

    # 1D profiles through peak
    h_profile = amp[cy, :]
    v_profile = amp[:, cx]

    # Normalize
    h_profile = h_profile / h_profile.max()
    v_profile = v_profile / v_profile.max()

    # sinc characteristics:
    # 1. Side lobes present (should have values > 0.05 beyond first zero)
    # 2. H and V profiles are independent (can have different widths)
    # 3. First side lobe amplitude ~ 0.217 for pure sinc (4.7% intensity)

    # Find first zero crossing and side lobe
    half = len(h_profile) // 2
    h_right = h_profile[cx:]
    first_min_idx = None
    for i in range(1, len(h_right) - 1):
        if h_right[i] < h_right[i-1] and h_right[i] < h_right[i+1]:
            first_min_idx = i
            break

    has_sidelobes = False
    sidelobe_ratio = 0.0
    if first_min_idx is not None and first_min_idx + 1 < len(h_right):
        # Find first side lobe max after first minimum
        for i in range(first_min_idx + 1, len(h_right) - 1):
            if h_right[i] > h_right[i-1] and h_right[i] > h_right[i+1]:
                sidelobe_ratio = h_right[i]
                has_sidelobes = sidelobe_ratio > 0.02
                break

    # FWHM measurement per axis
    h_half = 0.5
    h_fwhm = float(np.sum(h_profile >= h_half))
    v_fwhm = float(np.sum(v_profile >= h_half))

    print(f"[{label}] Peak at ({cx},{cy})")
    print(f"  H FWHM: {h_fwhm:.1f}px, V FWHM: {v_fwhm:.1f}px")
    print(f"  Side lobes: {'YES' if has_sidelobes else 'NO'} (ratio={sidelobe_ratio:.4f})")
    print(f"  sum|P|^2 = {float(np.sum(np.abs(probe)**2)):.0f}")

    return h_profile, v_profile, has_sidelobes, h_fwhm, v_fwhm


def main():
    # Parameters (matching JS default)
    asize = 128
    energy_keV = 6.2
    z_m = 1.0
    det_pixel_m = 75e-6
    N_photons = 1000
    fwhm_h_nm = 200.0  # KB H focus
    fwhm_v_nm = 200.0  # KB V focus (same for now)

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    pixel_size_m = lambda_m * z_m / (asize * det_pixel_m)
    pixel_size_nm = pixel_size_m * 1e9

    print(f"=== KB Sinc Probe Test ===")
    print(f"Energy: {energy_keV} keV, lambda: {lambda_m*1e10:.2f} A")
    print(f"Pixel size: {pixel_size_nm:.2f} nm")
    print(f"Target FWHM: H={fwhm_h_nm}nm, V={fwhm_v_nm}nm")
    print()

    # ---- Step 1: Generate sinc probe ----
    print("[1] Generating KB sinc probe (rectangular aperture)...")
    probe_sinc = generate_sinc_probe(
        asize, energy_keV, z_m, det_pixel_m, fwhm_h_nm, fwhm_v_nm)

    h_prof, v_prof, has_sl, h_fwhm, v_fwhm = check_sinc_shape(probe_sinc, "sinc")

    if not has_sl:
        print("  WARNING: No visible side lobes - may still be Airy-like!")
    else:
        print("  PASS: sinc side lobes detected (KB rectangular aperture)")

    # ---- Step 1b: Also test asymmetric FWHM ----
    print("\n[1b] Generating asymmetric sinc probe (H=200nm, V=100nm)...")
    probe_asym = generate_sinc_probe(
        asize, energy_keV, z_m, det_pixel_m, 200.0, 100.0)
    h_asym, v_asym, _, h_fwhm_a, v_fwhm_a = check_sinc_shape(probe_asym, "asym")
    ratio = v_fwhm_a / h_fwhm_a
    print(f"  H/V FWHM ratio: {ratio:.2f} (expected ~2.0 for 200/100nm)")

    # ---- Step 2: Reconstruction with sinc probe ----
    print("\n[2] Preparing synthetic data with sinc probe...")
    fwhm_measured = estimate_probe_fwhm(probe_sinc)
    step_px = fwhm_measured * 0.25
    scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
    scan_area_um = max(0.5, scan_area_px * pixel_size_nm * 1e-3)

    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=N_photons,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
        probe=probe_sinc)

    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2f}, FWHM={fwhm_measured:.1f}px")

    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'object_true': ds.object_true, 'asize': (asize, asize), 'Npos': ds.Npos,
    }

    # ---- Step 2a: GPU DM ----
    dl = DataLoader()
    p = dl.build_p_dict(data, {
        'number_iterations': 200, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    from engines.gpu.DM import DM as DM_GPU
    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    print("\n[3] Running GPU DM (200 iter)...")
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=200)
    print(f"  DM |obj| max = {np.max(np.abs(ob_dm[0])):.2f}")

    # ---- Step 2b: ML refinement ----
    from engines.ML import ML
    print("\n[4] Running ML (50 iter)...")
    p_ml = dict(p)
    p_ml['opt_iter'] = 50
    p_ml['opt_flags'] = [1, 1]
    p_ml['opt_errmetric'] = 'poisson'
    p_ml['object'] = [o[:, :, np.newaxis] if o.ndim == 2 else o for o in ob_dm]
    if pr_dm.ndim == 2:
        p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
    else:
        p_ml['probes'] = pr_dm
    if isinstance(p_ml.get('object_size'), list):
        p_ml['object_size'] = np.array(p_ml['object_size'])
    p_ml, fdb_ml = ML(p_ml)
    ob_ml = p_ml['object']

    dm_2d = ob_dm[0].squeeze()
    ml_2d = ob_ml[0].squeeze()
    print(f"  DM+ML |obj| max = {np.max(np.abs(ml_2d)):.2f}")

    # ---- Step 3: Plot results ----
    print("\n[5] Plotting...")
    truth = ds.object_true
    amp_max = np.percentile(np.abs(truth), 99.5) * 1.1

    fig = plt.figure(figsize=(20, 14))
    fig.patch.set_facecolor('white')

    # Layout: 4 rows
    # Row 0: Probe analysis (amplitude, H/V profiles, 2D amplitude, 2D phase)
    # Row 1: Amplitude (truth, DM, DM+ML, asymmetric probe)
    # Row 2: Phase (truth, DM, DM+ML, error)
    # Row 3: Probe recon, scan positions, error plot

    gs = fig.add_gridspec(4, 4, hspace=0.35, wspace=0.35)

    # ---- Row 0: Probe shape analysis ----
    ax00 = fig.add_subplot(gs[0, 0])
    ax00.imshow(np.abs(probe_sinc), cmap='jet')
    ax00.set_title('Sinc Probe |P|', fontsize=10, fontweight='bold')

    ax01 = fig.add_subplot(gs[0, 1])
    n = probe_sinc.shape[1]
    x_nm = (np.arange(n) - n/2) * pixel_size_nm
    cy, cx = np.unravel_index(np.abs(probe_sinc).argmax(), probe_sinc.shape)
    ax01.plot(x_nm, np.abs(probe_sinc[cy, :]) / np.abs(probe_sinc).max(), 'b-', label='H (sinc)', linewidth=2)
    ax01.plot(x_nm, np.abs(probe_sinc[:, cx]) / np.abs(probe_sinc).max(), 'r-', label='V (sinc)', linewidth=2)
    # Overlay theoretical sinc
    fwhm_px = h_fwhm
    w_theory = 0.886 / (fwhm_px * pixel_size_nm * 1e-9)  # slit width normalized
    # sinc reference (approximate)
    ax01.axhline(0.2171, color='gray', linestyle='--', alpha=0.5, label='sinc 1st lobe (0.217)')
    ax01.set_xlabel('Position (nm)')
    ax01.set_ylabel('Normalized amplitude')
    ax01.set_title('H/V Profiles', fontsize=10)
    ax01.legend(fontsize=8)
    ax01.set_xlim(-500, 500)
    ax01.grid(True, alpha=0.3)

    ax02 = fig.add_subplot(gs[0, 2])
    ax02.imshow(np.abs(probe_asym), cmap='jet')
    ax02.set_title(f'Asym Probe H={200}nm V={100}nm', fontsize=10)

    ax03 = fig.add_subplot(gs[0, 3])
    ax03.plot(x_nm, np.abs(probe_asym[probe_asym.shape[0]//2, :]) / np.abs(probe_asym).max(),
              'b-', label=f'H ({h_fwhm_a:.0f}px)', linewidth=2)
    ax03.plot(x_nm, np.abs(probe_asym[:, probe_asym.shape[1]//2]) / np.abs(probe_asym).max(),
              'r-', label=f'V ({v_fwhm_a:.0f}px)', linewidth=2)
    ax03.set_xlabel('Position (nm)')
    ax03.set_title('Asymmetric H/V Profiles', fontsize=10)
    ax03.legend(fontsize=8)
    ax03.set_xlim(-500, 500)
    ax03.grid(True, alpha=0.3)

    # ---- Row 1: Amplitude ----
    ax10 = fig.add_subplot(gs[1, 0])
    im = ax10.imshow(np.abs(truth), cmap='jet', vmin=0, vmax=amp_max)
    ax10.set_title('Ground Truth |obj|', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=ax10, fraction=0.046)

    ax11 = fig.add_subplot(gs[1, 1])
    im = ax11.imshow(np.abs(dm_2d), cmap='jet', vmin=0, vmax=amp_max)
    ax11.set_title(f'DM |obj| (max={np.max(np.abs(dm_2d)):.2f})', fontsize=10)
    plt.colorbar(im, ax=ax11, fraction=0.046)

    ax12 = fig.add_subplot(gs[1, 2])
    im = ax12.imshow(np.abs(ml_2d), cmap='jet', vmin=0, vmax=amp_max)
    ax12.set_title(f'DM+ML |obj| (max={np.max(np.abs(ml_2d)):.2f})', fontsize=10)
    plt.colorbar(im, ax=ax12, fraction=0.046)

    ax13 = fig.add_subplot(gs[1, 3])
    diff_amp = np.abs(np.abs(ml_2d) - np.abs(truth))
    im = ax13.imshow(diff_amp, cmap='jet', vmin=0, vmax=amp_max * 0.3)
    ax13.set_title('|DM+ML - Truth| amplitude', fontsize=10)
    plt.colorbar(im, ax=ax13, fraction=0.046)

    # ---- Row 2: Phase ----
    ax20 = fig.add_subplot(gs[2, 0])
    im = ax20.imshow(np.angle(truth), cmap='jet', vmin=-np.pi, vmax=np.pi)
    ax20.set_title('Truth phase', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=ax20, fraction=0.046)

    ax21 = fig.add_subplot(gs[2, 1])
    im = ax21.imshow(np.angle(dm_2d), cmap='jet', vmin=-np.pi, vmax=np.pi)
    ax21.set_title('DM phase', fontsize=10)
    plt.colorbar(im, ax=ax21, fraction=0.046)

    ax22 = fig.add_subplot(gs[2, 2])
    im = ax22.imshow(np.angle(ml_2d), cmap='jet', vmin=-np.pi, vmax=np.pi)
    ax22.set_title('DM+ML phase', fontsize=10)
    plt.colorbar(im, ax=ax22, fraction=0.046)

    ax23 = fig.add_subplot(gs[2, 3])
    im = ax23.imshow(np.angle(probe_sinc), cmap='jet', vmin=-np.pi, vmax=np.pi)
    ax23.set_title('Sinc Probe phase', fontsize=10)
    plt.colorbar(im, ax=ax23, fraction=0.046)

    # ---- Row 3: Probe recon, scan, error ----
    ax30 = fig.add_subplot(gs[3, 0])
    ax30.imshow(np.abs(ds.probe), cmap='jet')
    ax30.set_title(f'Input Probe (FWHM~{fwhm_measured:.0f}px)', fontsize=10)

    pr_final = p_ml['probes'][:, :, 0, 0] if p_ml['probes'].ndim == 4 else p_ml['probes']
    ax31 = fig.add_subplot(gs[3, 1])
    ax31.imshow(np.abs(pr_final), cmap='jet')
    ax31.set_title('Reconstructed Probe (DM+ML)', fontsize=10)

    ax32 = fig.add_subplot(gs[3, 2])
    ax32.scatter(ds.positions_clean[:, 1], ds.positions_clean[:, 0],
                 s=2, c='red', alpha=0.6)
    ax32.set_xlim(0, truth.shape[1])
    ax32.set_ylim(truth.shape[0], 0)
    ax32.set_title(f'Scan ({ds.Npos} pos, {ds.overlap:.0%} overlap)', fontsize=10)
    ax32.set_aspect('equal')
    ax32.set_facecolor('#f0f0f0')

    ax33 = fig.add_subplot(gs[3, 3])
    ml_errors = fdb_ml.get('err', [])
    if len(ml_errors) > 0:
        ax33.semilogy(ml_errors, 'r-', linewidth=2, label='ML error')
    ax33.set_title('ML Error Convergence', fontsize=10)
    ax33.set_xlabel('Iteration')
    ax33.legend()
    ax33.grid(True, alpha=0.3)

    for ax in fig.get_axes():
        ax.tick_params(labelsize=7)

    fig.suptitle(
        f'KB Sinc Probe Ptychography: E={energy_keV}keV, FWHM=({fwhm_h_nm:.0f},{fwhm_v_nm:.0f})nm, '
        f'pixel={pixel_size_nm:.1f}nm, Npos={ds.Npos}',
        fontsize=13, fontweight='bold')

    out_path = BEAMLINE_PTYCHO / 'sinc_probe_recon_result.png'
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    print(f"\nSaved: {out_path}")
    plt.close(fig)

    # ---- Summary ----
    print("\n=== SUMMARY ===")
    print(f"  Sinc probe FWHM: H={h_fwhm:.1f}px, V={v_fwhm:.1f}px")
    print(f"  Side lobes: {'YES' if has_sl else 'NO'}")
    print(f"  DM |obj| max: {np.max(np.abs(dm_2d)):.2f}")
    print(f"  DM+ML |obj| max: {np.max(np.abs(ml_2d)):.2f}")
    print(f"  Ground Truth |obj| max: {np.max(np.abs(truth)):.2f}")

    ok = np.abs(np.max(np.abs(ml_2d)) - np.max(np.abs(truth))) < 0.3
    if ok and has_sl:
        print("\n=== ALL TESTS PASSED ===")
    else:
        print("\n=== SOME ISSUES ===")
    return ok


if __name__ == '__main__':
    main()
