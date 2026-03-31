"""
compare_recon.py - Compare reconstruction results: circular (Airy) vs rectangular (sinc) probe
Both use identical Fresnel propagation, only aperture shape differs.
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

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader


class ProbeGen:
    @staticmethod
    def _prop_free_ff(win, lambda_m, z, pixsize):
        N = win.shape[0]
        z_n = z / pixsize
        lam_n = lambda_m / pixsize
        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2
        src_phase = np.exp(1j * np.pi * r2 / (lam_n * z_n))
        ft = np.fft.fft2(np.fft.fftshift(win * src_phase))
        ft = np.fft.ifftshift(ft)
        obs_phase = np.exp(1j * np.pi * lam_n * z_n * r2 / N**2)
        return -1j * obs_phase * ft

    def make_probe(self, asize, lambda_m, dx_spec, f, fwhm_h_m, fwhm_v_m,
                   shape='rect', upsample=4):
        """Generate probe with either circular or rectangular aperture."""
        N = upsample * asize
        dx_pupil = f * lambda_m / (N * dx_spec)
        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2

        if shape == 'circ':
            # Circular aperture (Airy) — use average FWHM
            fwhm_avg = (fwhm_h_m + fwhm_v_m) / 2.0
            aperture_m = 0.886 * lambda_m * 2.0 * f / fwhm_avg
            r_pix = aperture_m / (2.0 * dx_pupil)
            r = np.sqrt(r2)
            edge_w = max(5, int(r_pix * 0.02) + 1)
            inner = r_pix - edge_w
            outer = r_pix + edge_w
            w = np.zeros_like(r)
            w[r <= inner] = 1.0
            transition = (r > inner) & (r < outer)
            w[transition] = 0.5 * (1.0 + np.cos(
                np.pi * (r[transition] - inner) / (outer - inner)))
        else:
            # Rectangular aperture (sinc)
            aperture_h = 0.886 * lambda_m * f / fwhm_h_m
            aperture_v = 0.886 * lambda_m * f / fwhm_v_m
            hw_h = aperture_h / (2.0 * dx_pupil)
            hw_v = aperture_v / (2.0 * dx_pupil)
            edge_w_h = max(5, int(hw_h * 0.02) + 1)
            edge_w_v = max(5, int(hw_v * 0.02) + 1)
            ax = np.abs(xx[0, :])
            wh = np.zeros(N, dtype=np.float64)
            wh[ax <= hw_h - edge_w_h] = 1.0
            th = (ax > hw_h - edge_w_h) & (ax < hw_h + edge_w_h)
            wh[th] = 0.5 * (1.0 + np.cos(np.pi * (ax[th] - (hw_h - edge_w_h)) / (2 * edge_w_h)))
            ay = np.abs(yy[:, 0])
            wv = np.zeros(N, dtype=np.float64)
            wv[ay <= hw_v - edge_w_v] = 1.0
            tv = (ay > hw_v - edge_w_v) & (ay < hw_v + edge_w_v)
            wv[tv] = 0.5 * (1.0 + np.cos(np.pi * (ay[tv] - (hw_v - edge_w_v)) / (2 * edge_w_v)))
            w = wv[:, np.newaxis] * wh[np.newaxis, :]

        # Identical thin lens phase + Fresnel propagation for both
        lens_phase = np.exp(-1j * np.pi * r2 * dx_pupil**2 / (lambda_m * f))
        probe_hr = self._prop_free_ff(w * lens_phase, lambda_m, f, dx_pupil)

        c = N // 2
        h = asize // 2
        probe = probe_hr[c - h:c + h, c - h:c + h].copy()

        # Apodization
        ax2 = np.arange(asize, dtype=np.float64) - asize / 2.0
        axx, ayy = np.meshgrid(ax2, ax2)
        ar = np.sqrt(axx**2 + ayy**2)
        taper = np.clip((asize * 0.50 - ar) / (asize * 0.08), 0.0, 1.0)
        probe *= taper

        # Normalize: sum(|P|^2) = asize^2
        power = float((np.abs(probe)**2).sum())
        if power > 0:
            probe *= float(asize) / np.sqrt(power)
        return probe.astype(np.complex64)


def run_recon(probe, label, asize, energy_keV, z_m, det_pixel_m, N_photons):
    """Run DM + ML reconstruction and return results."""
    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    pixel_nm = lambda_m * z_m / (asize * det_pixel_m) * 1e9

    fwhm_px = estimate_probe_fwhm(probe)
    step_px = fwhm_px * 0.25
    scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
    scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=N_photons,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
        probe=probe)

    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    print(f"  [{label}] Npos={ds.Npos}, FWHM={fwhm_px:.1f}px, overlap={ds.overlap:.2f}")

    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'object_true': ds.object_true, 'asize': (asize, asize), 'Npos': ds.Npos,
    }

    dl = DataLoader()
    p = dl.build_p_dict(data, {
        'number_iterations': 200, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    from engines.gpu.DM import DM as DM_GPU
    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    print(f"  [{label}] Running GPU DM (200 iter)...")
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=200)

    from engines.ML import ML
    print(f"  [{label}] Running ML (50 iter)...")
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
    pr_ml = p_ml['probes'][:, :, 0, 0] if p_ml['probes'].ndim == 4 else p_ml['probes']

    return {
        'truth': ds.object_true,
        'probe_in': ds.probe,
        'probe_out': pr_ml,
        'dm': ob_dm[0].squeeze(),
        'ml': ob_ml[0].squeeze(),
        'err_ml': fdb_ml.get('err', []),
        'positions': ds.positions_clean,
        'Npos': ds.Npos,
        'overlap': ds.overlap,
        'fwhm_px': fwhm_px,
    }


def main():
    asize = 128
    energy_keV = 6.2
    z_m = 1.0
    det_pixel_m = 75e-6
    N_photons = 1000
    fwhm_nm = 200.0
    f_m = 0.3

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_spec = lambda_m * z_m / (asize * det_pixel_m)
    pixel_nm = dx_spec * 1e9

    pg = ProbeGen()

    print("=== Generating probes ===")
    probe_circ = pg.make_probe(asize, lambda_m, dx_spec, f_m,
                                fwhm_nm*1e-9, fwhm_nm*1e-9, shape='circ')
    probe_rect = pg.make_probe(asize, lambda_m, dx_spec, f_m,
                                fwhm_nm*1e-9, fwhm_nm*1e-9, shape='rect')

    print(f"  Circular: |P| max={np.abs(probe_circ).max():.2f}")
    print(f"  Rectangular: |P| max={np.abs(probe_rect).max():.2f}")

    print("\n=== Reconstruction: Circular (Airy) ===")
    res_circ = run_recon(probe_circ, "Circ", asize, energy_keV, z_m, det_pixel_m, N_photons)

    print("\n=== Reconstruction: Rectangular (sinc) ===")
    res_rect = run_recon(probe_rect, "Rect", asize, energy_keV, z_m, det_pixel_m, N_photons)

    # ---- PLOT ----
    # Center-crop both to same size for comparison
    tc = res_circ['truth']
    tr = res_rect['truth']
    sz = min(tc.shape[0], tr.shape[0])
    def ccrop(arr, sz):
        cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
        h = sz // 2
        return arr[cy-h:cy-h+sz, cx-h:cx-h+sz]
    # Crop all results to common size
    for key in ['truth', 'dm', 'ml']:
        res_circ[key] = ccrop(res_circ[key], sz)
        res_rect[key] = ccrop(res_rect[key], sz)

    truth = res_circ['truth']
    amp_max = np.percentile(np.abs(truth), 99.5) * 1.1

    fig, axes = plt.subplots(4, 4, figsize=(20, 18))
    fig.patch.set_facecolor('white')

    # Row 0: Probes (input)
    im = axes[0, 0].imshow(np.abs(res_circ['probe_in']), cmap='jet')
    axes[0, 0].set_title(f'Circ Probe |P| (FWHM~{res_circ["fwhm_px"]:.0f}px)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[0, 0], fraction=0.046)

    im = axes[0, 1].imshow(np.abs(res_rect['probe_in']), cmap='jet')
    axes[0, 1].set_title(f'Rect Probe |P| (FWHM~{res_rect["fwhm_px"]:.0f}px)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[0, 1], fraction=0.046)

    im = axes[0, 2].imshow(np.angle(res_circ['probe_in']), cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[0, 2].set_title('Circ Probe Phase', fontsize=10)
    plt.colorbar(im, ax=axes[0, 2], fraction=0.046)

    im = axes[0, 3].imshow(np.angle(res_rect['probe_in']), cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[0, 3].set_title('Rect Probe Phase', fontsize=10)
    plt.colorbar(im, ax=axes[0, 3], fraction=0.046)

    # Row 1: Object amplitude (truth, circ DM+ML, rect DM+ML, difference)
    im = axes[1, 0].imshow(np.abs(truth), cmap='jet', vmin=0, vmax=amp_max)
    axes[1, 0].set_title('Ground Truth |obj|', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[1, 0], fraction=0.046)

    im = axes[1, 1].imshow(np.abs(res_circ['ml']), cmap='jet', vmin=0, vmax=amp_max)
    axes[1, 1].set_title(f'Circ DM+ML |obj| (max={np.abs(res_circ["ml"]).max():.2f})', fontsize=10)
    plt.colorbar(im, ax=axes[1, 1], fraction=0.046)

    im = axes[1, 2].imshow(np.abs(res_rect['ml']), cmap='jet', vmin=0, vmax=amp_max)
    axes[1, 2].set_title(f'Rect DM+ML |obj| (max={np.abs(res_rect["ml"]).max():.2f})', fontsize=10)
    plt.colorbar(im, ax=axes[1, 2], fraction=0.046)

    diff = np.abs(np.abs(res_rect['ml']) - np.abs(res_circ['ml']))
    im = axes[1, 3].imshow(diff, cmap='jet', vmin=0, vmax=amp_max * 0.3)
    axes[1, 3].set_title('|Rect - Circ| amplitude diff', fontsize=10)
    plt.colorbar(im, ax=axes[1, 3], fraction=0.046)

    # Row 2: Phase (truth, circ, rect, diff)
    im = axes[2, 0].imshow(np.angle(truth), cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 0].set_title('Truth Phase', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[2, 0], fraction=0.046)

    im = axes[2, 1].imshow(np.angle(res_circ['ml']), cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 1].set_title('Circ DM+ML Phase', fontsize=10)
    plt.colorbar(im, ax=axes[2, 1], fraction=0.046)

    im = axes[2, 2].imshow(np.angle(res_rect['ml']), cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 2].set_title('Rect DM+ML Phase', fontsize=10)
    plt.colorbar(im, ax=axes[2, 2], fraction=0.046)

    # Reconstructed probes
    im = axes[2, 3].imshow(np.abs(res_rect['probe_out']), cmap='jet')
    axes[2, 3].set_title('Rect Recon Probe |P|', fontsize=10)
    plt.colorbar(im, ax=axes[2, 3], fraction=0.046)

    # Row 3: Error plots, probe profiles
    c = asize // 2
    x_nm = (np.arange(asize) - c) * pixel_nm

    if len(res_circ['err_ml']) > 0:
        axes[3, 0].semilogy(res_circ['err_ml'], 'b-', lw=2, label='Circ ML')
    if len(res_rect['err_ml']) > 0:
        axes[3, 0].semilogy(res_rect['err_ml'], 'r-', lw=2, label='Rect ML')
    axes[3, 0].set_title('ML Error Convergence', fontsize=10)
    axes[3, 0].legend()
    axes[3, 0].grid(True, alpha=0.3)
    axes[3, 0].set_xlabel('Iteration')

    # Input probe 1D comparison
    axes[3, 1].plot(x_nm, np.abs(res_circ['probe_in'][c, :]) / np.abs(res_circ['probe_in']).max(),
                    'b-', lw=2, label='Circ')
    axes[3, 1].plot(x_nm, np.abs(res_rect['probe_in'][c, :]) / np.abs(res_rect['probe_in']).max(),
                    'r-', lw=2, label='Rect')
    axes[3, 1].set_title('Input Probe H Profile', fontsize=10)
    axes[3, 1].set_xlabel('Position (nm)')
    axes[3, 1].legend()
    axes[3, 1].set_xlim(-400, 400)
    axes[3, 1].grid(True, alpha=0.3)

    # Recon probe comparison
    axes[3, 2].plot(x_nm, np.abs(res_circ['probe_out'][c, :]) / np.abs(res_circ['probe_out']).max(),
                    'b-', lw=2, label='Circ recon')
    axes[3, 2].plot(x_nm, np.abs(res_rect['probe_out'][c, :]) / np.abs(res_rect['probe_out']).max(),
                    'r-', lw=2, label='Rect recon')
    axes[3, 2].set_title('Recon Probe H Profile', fontsize=10)
    axes[3, 2].set_xlabel('Position (nm)')
    axes[3, 2].legend()
    axes[3, 2].set_xlim(-400, 400)
    axes[3, 2].grid(True, alpha=0.3)

    # Scan positions
    axes[3, 3].scatter(res_rect['positions'][:, 1], res_rect['positions'][:, 0],
                       s=2, c='red', alpha=0.6)
    axes[3, 3].set_xlim(0, truth.shape[1])
    axes[3, 3].set_ylim(truth.shape[0], 0)
    axes[3, 3].set_title(f'Scan ({res_rect["Npos"]} pos, {res_rect["overlap"]:.0%})', fontsize=10)
    axes[3, 3].set_aspect('equal')
    axes[3, 3].set_facecolor('#f0f0f0')

    for ax in axes.flat:
        ax.tick_params(labelsize=7)

    fig.suptitle(
        f'Reconstruction Comparison: Circular (Airy) vs Rectangular (sinc) Probe\n'
        f'E={energy_keV}keV, FWHM={fwhm_nm}nm, f={f_m}m, pixel={pixel_nm:.1f}nm',
        fontsize=13, fontweight='bold')
    plt.tight_layout()

    out_path = BEAMLINE_PTYCHO / 'compare_recon_circ_vs_rect.png'
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    print(f"\nSaved: {out_path}")
    plt.close(fig)

    # Summary
    print("\n=== SUMMARY ===")
    print(f"  Circular: DM+ML |obj| max = {np.abs(res_circ['ml']).max():.3f}")
    print(f"  Rectangular: DM+ML |obj| max = {np.abs(res_rect['ml']).max():.3f}")
    print(f"  Ground Truth: |obj| max = {np.abs(truth).max():.3f}")
    t_max = np.abs(truth).max()
    err_c = abs(np.abs(res_circ['ml']).max() - t_max)
    err_r = abs(np.abs(res_rect['ml']).max() - t_max)
    print(f"  Circ error: {err_c:.3f}, Rect error: {err_r:.3f}")
    print(f"  BOTH OK" if err_c < 0.3 and err_r < 0.3 else "  WARNING: large amplitude error")


if __name__ == '__main__':
    main()
