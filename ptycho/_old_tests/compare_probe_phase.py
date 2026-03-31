"""
compare_probe_phase.py - Compare circular (Airy) vs rectangular (sinc) probe
Side-by-side: amplitude, phase, 1D profiles
Verify that Fresnel propagation is identical, only aperture shape differs.
"""
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BEAMLINE_PTYCHO = Path(r'c:\Projects\K4GSR-Beamline\ptycho')


class ProbeGenerator:
    """Standalone probe generator for comparison."""

    @staticmethod
    def _prop_free_ff(win, lambda_m, z, pixsize):
        """Far-field Fresnel propagation (port of cSAXS utils.prop_free_ff)."""
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

    def circular_probe(self, asize, lambda_m, dx_spec,
                       focal_length_m, defocus_m=0.0,
                       fwhm_m=50e-9, upsample=4):
        """ORIGINAL circular aperture probe (Airy) - copied from git history."""
        f = focal_length_m
        defocus = defocus_m

        # Airy disk: FWHM ~ 0.886 * lambda / NA,  NA = D / (2*f)
        aperture_m = 0.886 * lambda_m * 2.0 * f / fwhm_m

        N = upsample * asize
        dx_pupil = (f + defocus) * lambda_m / (N * dx_spec)
        r_pix = aperture_m / (2.0 * dx_pupil)

        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2
        r = np.sqrt(r2)

        # Circular aperture with Hanning edge
        edge_w = max(5, int(r_pix * 0.02) + 1)
        inner = r_pix - edge_w
        outer = r_pix + edge_w
        w = np.zeros_like(r)
        w[r <= inner] = 1.0
        transition = (r > inner) & (r < outer)
        w[transition] = 0.5 * (1.0 + np.cos(
            np.pi * (r[transition] - inner) / (outer - inner)))

        # Thin lens phase
        lens_phase = np.exp(-1j * np.pi * r2 * dx_pupil**2 / (lambda_m * f))

        # Far-field propagation
        probe_hr = self._prop_free_ff(w * lens_phase, lambda_m, f + defocus, dx_pupil)

        # Crop
        c = N // 2
        h = asize // 2
        probe = probe_hr[c - h:c + h, c - h:c + h].copy()

        # Apodization
        ax = np.arange(asize, dtype=np.float64) - asize / 2.0
        axx, ayy = np.meshgrid(ax, ax)
        ar = np.sqrt(axx**2 + ayy**2)
        edge_start = asize * 0.42
        edge_end = asize * 0.50
        taper = np.clip((edge_end - ar) / (edge_end - edge_start), 0.0, 1.0)
        probe *= taper

        # Normalize
        power = float((np.abs(probe)**2).sum())
        if power > 0:
            probe *= float(asize) / np.sqrt(power)
        return probe.astype(np.complex64), w, lens_phase

    def rectangular_probe(self, asize, lambda_m, dx_spec,
                          focal_length_m, defocus_m=0.0,
                          fwhm_h_m=50e-9, fwhm_v_m=50e-9, upsample=4):
        """NEW rectangular aperture probe (sinc) - current code."""
        f = focal_length_m
        defocus = defocus_m

        aperture_h = 0.886 * lambda_m * f / fwhm_h_m
        aperture_v = 0.886 * lambda_m * f / fwhm_v_m

        N = upsample * asize
        dx_pupil = (f + defocus) * lambda_m / (N * dx_spec)
        hw_h = aperture_h / (2.0 * dx_pupil)
        hw_v = aperture_v / (2.0 * dx_pupil)

        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2

        edge_w_h = max(5, int(hw_h * 0.02) + 1)
        edge_w_v = max(5, int(hw_v * 0.02) + 1)

        ax = np.abs(xx[0, :])
        wh = np.zeros(N, dtype=np.float64)
        inner_h = hw_h - edge_w_h
        outer_h = hw_h + edge_w_h
        wh[ax <= inner_h] = 1.0
        trans_h = (ax > inner_h) & (ax < outer_h)
        wh[trans_h] = 0.5 * (1.0 + np.cos(
            np.pi * (ax[trans_h] - inner_h) / (outer_h - inner_h)))

        ay = np.abs(yy[:, 0])
        wv = np.zeros(N, dtype=np.float64)
        inner_v = hw_v - edge_w_v
        outer_v = hw_v + edge_w_v
        wv[ay <= inner_v] = 1.0
        trans_v = (ay > inner_v) & (ay < outer_v)
        wv[trans_v] = 0.5 * (1.0 + np.cos(
            np.pi * (ay[trans_v] - inner_v) / (outer_v - inner_v)))

        w = wv[:, np.newaxis] * wh[np.newaxis, :]

        # Thin lens phase (IDENTICAL to circular version)
        lens_phase = np.exp(-1j * np.pi * r2 * dx_pupil**2 / (lambda_m * f))

        # Far-field propagation (IDENTICAL to circular version)
        probe_hr = self._prop_free_ff(w * lens_phase, lambda_m, f + defocus, dx_pupil)

        # Crop
        c = N // 2
        h = asize // 2
        probe = probe_hr[c - h:c + h, c - h:c + h].copy()

        # Apodization
        ax2 = np.arange(asize, dtype=np.float64) - asize / 2.0
        axx, ayy = np.meshgrid(ax2, ax2)
        ar = np.sqrt(axx**2 + ayy**2)
        edge_start = asize * 0.42
        edge_end = asize * 0.50
        taper = np.clip((edge_end - ar) / (edge_end - edge_start), 0.0, 1.0)
        probe *= taper

        # Normalize
        power = float((np.abs(probe)**2).sum())
        if power > 0:
            probe *= float(asize) / np.sqrt(power)
        return probe.astype(np.complex64), w, lens_phase


def main():
    asize = 128
    energy_keV = 6.2
    z_m = 1.0
    det_pixel_m = 75e-6
    fwhm_nm = 200.0
    f_m = 0.3

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_spec = lambda_m * z_m / (asize * det_pixel_m)
    pixel_nm = dx_spec * 1e9

    gen = ProbeGenerator()

    # Generate both probes
    print("Generating circular (Airy) probe...")
    probe_circ, w_circ, lp_circ = gen.circular_probe(
        asize, lambda_m, dx_spec, f_m, fwhm_m=fwhm_nm * 1e-9)

    print("Generating rectangular (sinc) probe...")
    probe_rect, w_rect, lp_rect = gen.rectangular_probe(
        asize, lambda_m, dx_spec, f_m, fwhm_h_m=fwhm_nm * 1e-9, fwhm_v_m=fwhm_nm * 1e-9)

    # Verify propagation is identical
    print("\n=== PROPAGATION COMPARISON ===")
    print(f"Lens phase identical: {np.allclose(lp_circ, lp_rect)}")
    print(f"Lens phase max diff: {np.max(np.abs(lp_circ - lp_rect)):.2e}")

    # Probe stats
    for label, p in [("Circular (Airy)", probe_circ), ("Rectangular (sinc)", probe_rect)]:
        amp = np.abs(p)
        phase = np.angle(p)
        cy, cx = np.unravel_index(amp.argmax(), amp.shape)
        mask = amp > 0.1 * amp.max()
        print(f"\n{label}:")
        print(f"  |P| max={amp.max():.4f}, sum|P|^2={float(np.sum(amp**2)):.0f}")
        print(f"  Phase at center: {phase[cy, cx]:.4f} rad")
        print(f"  Phase PV (>10% mask): {phase[mask].max() - phase[mask].min():.4f} rad")

    # ---- PLOT ----
    fig, axes = plt.subplots(4, 4, figsize=(20, 18))
    fig.patch.set_facecolor('white')

    c = asize // 2
    x_nm = (np.arange(asize) - c) * pixel_nm

    # ---- Row 0: Pupil plane (aperture functions) ----
    N = 4 * asize  # upsample=4
    pupil_c = N // 2
    pupil_hw = min(200, N // 2)  # crop window for display

    axes[0, 0].imshow(w_circ[pupil_c-pupil_hw:pupil_c+pupil_hw,
                              pupil_c-pupil_hw:pupil_c+pupil_hw], cmap='jet')
    axes[0, 0].set_title('Circular Aperture (pupil)', fontsize=10, fontweight='bold')

    axes[0, 1].imshow(w_rect[pupil_c-pupil_hw:pupil_c+pupil_hw,
                              pupil_c-pupil_hw:pupil_c+pupil_hw], cmap='jet')
    axes[0, 1].set_title('Rectangular Aperture (pupil)', fontsize=10, fontweight='bold')

    # 1D pupil profiles
    axes[0, 2].plot(w_circ[pupil_c, pupil_c-pupil_hw:pupil_c+pupil_hw], 'b-', label='Circ H', lw=2)
    axes[0, 2].plot(w_circ[pupil_c-pupil_hw:pupil_c+pupil_hw, pupil_c], 'b--', label='Circ V', lw=1)
    axes[0, 2].plot(w_rect[pupil_c, pupil_c-pupil_hw:pupil_c+pupil_hw], 'r-', label='Rect H', lw=2)
    axes[0, 2].plot(w_rect[pupil_c-pupil_hw:pupil_c+pupil_hw, pupil_c], 'r--', label='Rect V', lw=1)
    axes[0, 2].set_title('Pupil 1D Profiles', fontsize=10)
    axes[0, 2].legend(fontsize=8)
    axes[0, 2].grid(True, alpha=0.3)

    # Lens phase (same for both)
    lp_crop = np.angle(lp_circ[pupil_c-pupil_hw:pupil_c+pupil_hw,
                                pupil_c-pupil_hw:pupil_c+pupil_hw])
    im = axes[0, 3].imshow(lp_crop, cmap='jet')
    axes[0, 3].set_title('Lens Phase (identical)', fontsize=10)
    plt.colorbar(im, ax=axes[0, 3], fraction=0.046)

    # ---- Row 1: Amplitude comparison ----
    amp_circ = np.abs(probe_circ)
    amp_rect = np.abs(probe_rect)
    vmax = max(amp_circ.max(), amp_rect.max()) * 1.05

    im = axes[1, 0].imshow(amp_circ, cmap='jet', vmin=0, vmax=vmax)
    axes[1, 0].set_title('Circular |P| (Airy)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[1, 0], fraction=0.046)

    im = axes[1, 1].imshow(amp_rect, cmap='jet', vmin=0, vmax=vmax)
    axes[1, 1].set_title('Rectangular |P| (sinc)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[1, 1], fraction=0.046)

    # 1D amplitude profiles
    axes[1, 2].plot(x_nm, amp_circ[c, :] / amp_circ.max(), 'b-', label='Circ H', lw=2)
    axes[1, 2].plot(x_nm, amp_rect[c, :] / amp_rect.max(), 'r-', label='Rect H', lw=2)
    axes[1, 2].axhline(0.2171, color='gray', ls='--', alpha=0.5, label='sinc 1st lobe')
    axes[1, 2].set_xlabel('Position (nm)')
    axes[1, 2].set_title('H Profile Comparison', fontsize=10)
    axes[1, 2].legend(fontsize=8)
    axes[1, 2].set_xlim(-500, 500)
    axes[1, 2].grid(True, alpha=0.3)

    # Amplitude difference
    diff_amp = np.abs(amp_rect - amp_circ)
    im = axes[1, 3].imshow(diff_amp, cmap='jet')
    axes[1, 3].set_title('|sinc| - |Airy| difference', fontsize=10)
    plt.colorbar(im, ax=axes[1, 3], fraction=0.046)

    # ---- Row 2: Phase comparison ----
    phase_circ = np.angle(probe_circ)
    phase_rect = np.angle(probe_rect)

    im = axes[2, 0].imshow(phase_circ, cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 0].set_title('Circular Phase (Airy)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[2, 0], fraction=0.046)

    im = axes[2, 1].imshow(phase_rect, cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 1].set_title('Rectangular Phase (sinc)', fontsize=10, fontweight='bold')
    plt.colorbar(im, ax=axes[2, 1], fraction=0.046)

    # 1D phase profiles
    axes[2, 2].plot(x_nm, phase_circ[c, :], 'b-', label='Circ H', lw=2)
    axes[2, 2].plot(x_nm, phase_rect[c, :], 'r-', label='Rect H', lw=2)
    axes[2, 2].set_xlabel('Position (nm)')
    axes[2, 2].set_ylabel('Phase (rad)')
    axes[2, 2].set_title('H Phase Comparison', fontsize=10)
    axes[2, 2].legend(fontsize=8)
    axes[2, 2].set_xlim(-500, 500)
    axes[2, 2].grid(True, alpha=0.3)

    # Phase difference
    # Unwrap phase difference to see structure
    phase_diff = phase_rect - phase_circ
    # wrap to [-pi, pi]
    phase_diff = np.angle(np.exp(1j * phase_diff))
    im = axes[2, 3].imshow(phase_diff, cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[2, 3].set_title('Phase difference (rect - circ)', fontsize=10)
    plt.colorbar(im, ax=axes[2, 3], fraction=0.046)

    # ---- Row 3: Masked phase (high-amp region only) + V profiles ----
    # Show phase only where amplitude is significant
    mask_circ = amp_circ > 0.05 * amp_circ.max()
    mask_rect = amp_rect > 0.05 * amp_rect.max()

    phase_masked_c = np.where(mask_circ, phase_circ, np.nan)
    phase_masked_r = np.where(mask_rect, phase_rect, np.nan)

    im = axes[3, 0].imshow(phase_masked_c, cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[3, 0].set_title('Circ Phase (masked >5%)', fontsize=10)
    plt.colorbar(im, ax=axes[3, 0], fraction=0.046)

    im = axes[3, 1].imshow(phase_masked_r, cmap='jet', vmin=-np.pi, vmax=np.pi)
    axes[3, 1].set_title('Rect Phase (masked >5%)', fontsize=10)
    plt.colorbar(im, ax=axes[3, 1], fraction=0.046)

    # V profiles
    axes[3, 2].plot(x_nm, amp_circ[:, c] / amp_circ.max(), 'b-', label='Circ V', lw=2)
    axes[3, 2].plot(x_nm, amp_rect[:, c] / amp_rect.max(), 'r-', label='Rect V', lw=2)
    axes[3, 2].set_xlabel('Position (nm)')
    axes[3, 2].set_title('V Profile Comparison', fontsize=10)
    axes[3, 2].legend(fontsize=8)
    axes[3, 2].set_xlim(-500, 500)
    axes[3, 2].grid(True, alpha=0.3)

    axes[3, 3].plot(x_nm, phase_circ[:, c], 'b-', label='Circ V phase', lw=2)
    axes[3, 3].plot(x_nm, phase_rect[:, c], 'r-', label='Rect V phase', lw=2)
    axes[3, 3].set_xlabel('Position (nm)')
    axes[3, 3].set_ylabel('Phase (rad)')
    axes[3, 3].set_title('V Phase Comparison', fontsize=10)
    axes[3, 3].legend(fontsize=8)
    axes[3, 3].set_xlim(-500, 500)
    axes[3, 3].grid(True, alpha=0.3)

    for ax in axes.flat:
        ax.tick_params(labelsize=7)

    fig.suptitle(
        f'Probe Comparison: Circular (Airy) vs Rectangular (sinc)\n'
        f'E={energy_keV}keV, FWHM={fwhm_nm}nm, f={f_m}m, pixel={pixel_nm:.1f}nm, asize={asize}',
        fontsize=13, fontweight='bold')
    plt.tight_layout()

    out_path = BEAMLINE_PTYCHO / 'compare_circ_vs_rect_probe.png'
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    print(f"\nSaved: {out_path}")
    plt.close(fig)


if __name__ == '__main__':
    main()
