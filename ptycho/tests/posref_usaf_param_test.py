"""
posref_usaf_param_test.py
==========================
Python-only test: USAF dataset with varying overlap and photon count.

Generates synthetic ptychography data from the USAF ground-truth object
(loaded from matlab_posref_comparison_ds5.mat) with configurable:
  - overlap  : scan overlap fraction (0.5 = 50%, 0.75 = 75%, 0.9 = 90%)
  - N_photons: peak photon count per diffraction pattern

Runs LSQML with/without position refinement and compares quality.

Output: posref_usaf_param_test.png
"""

import numpy as np
import h5py
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from engines.gpu.gpu_wrapper import set_use_gpu, check_gpu_available
from engines.gpu.LSQML import LSQML


# ── probe & position generators ──────────────────────────────────────────────

def make_probe(Np=128, support_radius=0.9):
    """
    Circular aperture probe (disk in Fourier space = Airy in real space).
    Returns complex64 array [Np, Np].
    """
    Y, X = np.mgrid[-Np//2:Np//2, -Np//2:Np//2]
    R = np.sqrt(X**2 + Y**2)
    mask = (R <= support_radius * Np / 2).astype(np.complex64)
    probe = np.fft.ifft2(np.fft.ifftshift(mask)).astype(np.complex64)
    probe /= np.abs(probe).max()
    return probe


def fermat_positions(scan_range_px, probe_px, overlap):
    """
    Fermat spiral scan positions with given overlap fraction.
    overlap = 1 - step/FWHM, where FWHM is estimated as probe_px / 4
    (approximate FWHM of circular aperture Airy probe with radius 0.9*Np/2).

    Returns positions [N, 2] in pixels (row, col), guaranteed to fit inside object.
    """
    golden_angle = np.pi * (3 - np.sqrt(5))  # ≈ 137.5°
    # Effective FWHM of Airy probe for support_radius=0.9
    probe_fwhm = probe_px * 0.9 / 2.44 * 2   # ~ 47 px for Np=128
    step = probe_fwhm * (1 - overlap)

    # Number of positions from area/step^2
    area = scan_range_px[0] * scan_range_px[1]
    N_approx = max(20, int(area / step**2 * 1.5))
    N_approx = min(N_approx, 200)  # cap for speed

    positions = []
    for k in range(N_approx):
        r = step * np.sqrt(k)
        theta = k * golden_angle
        row = r * np.cos(theta) + scan_range_px[0] / 2
        col = r * np.sin(theta) + scan_range_px[1] / 2
        # Keep positions where probe fits inside object
        if 0 <= row <= scan_range_px[0] and 0 <= col <= scan_range_px[1]:
            positions.append([row, col])

    positions = np.array(positions, dtype=np.float32)
    return positions


def simulate_diffraction(obj, probe, positions, N_photons, rng_seed=42):
    """
    Forward model: fmag = sqrt(Poisson(|FFT(probe * obj_view)|^2 * N_photons / max_I))

    Returns fmag [Np, Np, Npos] float32.
    """
    rng = np.random.default_rng(rng_seed)
    Ny, Nx = probe.shape
    Npos = len(positions)
    fmag = np.zeros((Ny, Nx, Npos), dtype=np.float32)

    # Compute normalization factor from mean intensity over all positions
    intensities = []
    for ii, pos in enumerate(positions):
        r = int(round(float(pos[0])))
        c = int(round(float(pos[1])))
        r = np.clip(r, 0, obj.shape[0] - Ny)
        c = np.clip(c, 0, obj.shape[1] - Nx)
        exit_wave = probe * obj[r:r+Ny, c:c+Nx]
        Psi = np.fft.fft2(exit_wave)
        I = np.abs(Psi)**2
        intensities.append(I.max())

    I_scale = np.median(intensities)  # scale so median-max pattern has N_photons counts

    for ii, pos in enumerate(positions):
        r = int(round(float(pos[0])))
        c = int(round(float(pos[1])))
        r = np.clip(r, 0, obj.shape[0] - Ny)
        c = np.clip(c, 0, obj.shape[1] - Nx)
        exit_wave = probe * obj[r:r+Ny, c:c+Nx]
        Psi = np.fft.fft2(exit_wave)
        I = np.abs(Psi)**2
        I_counts = I / I_scale * N_photons
        noisy = rng.poisson(np.maximum(I_counts, 0).astype(np.float64)).astype(np.float32)
        fmag[:, :, ii] = np.sqrt(noisy)

    return fmag


# ── utilities ──────────────────────────────────────────────────────────────────

def corr(a1, a2):
    r = min(a1.shape[0], a2.shape[0])
    c = min(a1.shape[1], a2.shape[1])
    a1 = a1[:r, :c].ravel().astype(np.complex128)
    a2 = a2[:r, :c].ravel().astype(np.complex128)
    a1 -= a1.mean(); a2 -= a2.mean()
    denom = np.sqrt(np.sum(np.abs(a1)**2) * np.sum(np.abs(a2)**2))
    if denom < 1e-30: return 0.0
    return float(np.abs(np.dot(a1.conj(), a2)) / denom)


def add_position_noise(positions, sigma=3.0, seed=42):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, positions.shape).astype(np.float32)
    return positions + noise, noise


def run_lsqml(ob_init, probe, fmag, positions, use_posref, gpu, n_iter=50):
    p = dict(
        probe_modes=1, object_modes=1,
        probe_change_start=1, object_change_start=1,
        beta_LSQ=0.5, beta_probe=1.0, beta_object=1.0,
        pfft_relaxation=0.1, delta_p=0.1,
        use_gpu=gpu,
        probe_position_search=5 if use_posref else 0,
    )
    t0 = time.time()
    if use_posref:
        ob_r, pr_r, _, pos_r = LSQML(p, [ob_init.copy()], probe.copy(),
                                       fmag, positions.copy(), n_iter,
                                       return_positions=True)
    else:
        ob_r, pr_r, _ = LSQML(p, [ob_init.copy()], probe.copy(),
                                fmag, positions.copy(), n_iter)
        pos_r = positions.copy()
    elapsed = time.time() - t0
    return ob_r[0], pr_r, pos_r, elapsed


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    root = Path(__file__).parent.parent

    # Load USAF ground truth object from MATLAB .mat
    mat_path = root / 'matlab_posref_comparison_ds5.mat'
    print(f'Loading USAF object from {mat_path.name}...')
    with h5py.File(mat_path, 'r') as f:
        v = f['object_true'][()]
        if v.dtype.names and 'real' in v.dtype.names:
            obj_true = (v['real'] + 1j * v['imag']).T.astype(np.complex64)
        else:
            obj_true = v.T.astype(np.complex64)

    print(f'  object_true: {obj_true.shape}  |amp| range [{np.abs(obj_true).min():.3f}, {np.abs(obj_true).max():.3f}]')

    gpu = check_gpu_available()
    set_use_gpu(gpu)
    print(f'  GPU: {"ON" if gpu else "OFF"}\n')

    Np = 128   # probe/patch size
    probe = make_probe(Np, support_radius=0.9)
    obj_h, obj_w = obj_true.shape[:2]
    scan_range = (obj_h - Np, obj_w - Np)   # max valid scan range

    # Test configurations: (overlap, N_photons_label, N_photons)
    configs = [
        (0.50, '50% overlap / low photons (baseline)',    100),
        (0.75, '75% overlap / low photons',               100),
        (0.50, '50% overlap / high photons (1k)',        1000),
        (0.75, '75% overlap / high photons (1k)',        1000),
        (0.90, '90% overlap / high photons (1k)',        1000),
        (0.75, '75% overlap / very high photons (10k)', 10000),
    ]

    results = []
    N_ITER = 50
    NOISE_SIGMA = 3.0

    for overlap, label, N_photons in configs:
        print('=' * 65)
        print(f'{label}')
        print('=' * 65)

        positions_clean = fermat_positions(scan_range, Np, overlap)
        Npos = len(positions_clean)

        # Effective step (px)
        diffs = []
        for i in range(len(positions_clean)):
            d = np.sqrt(((positions_clean - positions_clean[i])**2).sum(axis=1))
            d[i] = np.inf
            diffs.append(d.min())
        avg_step = float(np.mean(diffs))
        probe_fwhm = Np * 0.9 / 2.44 * 2
        actual_overlap = 1 - avg_step / probe_fwhm

        print(f'  Npos={Npos}  avg_step={avg_step:.1f}px  actual_overlap={actual_overlap:.1%}  N_photons={N_photons}')

        # Simulate diffraction
        fmag = simulate_diffraction(obj_true, probe, positions_clean, N_photons, rng_seed=7)
        print(f'  fmag: {fmag.shape}  max={fmag.max():.2f}  mean={fmag.mean():.3f}')

        # Add position noise
        positions_noisy, pos_noise = add_position_noise(positions_clean, NOISE_SIGMA, seed=42)
        positions_noisy[:, 0] = np.clip(positions_noisy[:, 0], 0, scan_range[0])
        positions_noisy[:, 1] = np.clip(positions_noisy[:, 1], 0, scan_range[1])
        pos_err_init = float(np.mean(np.sqrt(np.sum((positions_noisy - positions_clean)**2, axis=1))))
        print(f'  pos noise sigma={NOISE_SIGMA}px  mean_err={pos_err_init:.3f}px')

        # Initial object (amplitude of probe-weighted illumination → uniform start)
        ob_init = np.ones(obj_true.shape, dtype=np.complex64)

        # Run no-posref
        print(f'  [1/2] LSQML {N_ITER} iter, NO posref...')
        ob_nr, pr_nr, _, t_nr = run_lsqml(ob_init, probe, fmag, positions_noisy, False, gpu, N_ITER)
        c_nr_obj   = corr(ob_nr, obj_true)
        c_nr_probe = corr(pr_nr, probe)
        print(f'       Obj={c_nr_obj:.4f}  ({t_nr:.1f}s)')

        # Run with posref
        print(f'  [2/2] LSQML {N_ITER} iter, WITH posref...')
        ob_pr, pr_pr, pos_rec, t_pr = run_lsqml(ob_init, probe, fmag, positions_noisy, True, gpu, N_ITER)
        c_pr_obj   = corr(ob_pr, obj_true)
        c_pr_probe = corr(pr_pr, probe)
        pos_err_after = float(np.mean(np.sqrt(np.sum((pos_rec - positions_clean)**2, axis=1))))
        recovery = 100 * (pos_err_init - pos_err_after) / pos_err_init
        print(f'       Obj={c_pr_obj:.4f}  ({t_pr:.1f}s)  pos {pos_err_init:.2f}→{pos_err_after:.2f}px ({recovery:+.1f}%)')

        results.append({
            'label': label,
            'overlap': actual_overlap,
            'N_photons': N_photons,
            'Npos': Npos,
            'c_nr_obj': c_nr_obj,
            'c_pr_obj': c_pr_obj,
            'c_nr_probe': c_nr_probe,
            'c_pr_probe': c_pr_probe,
            'pos_err_init': pos_err_init,
            'pos_err_after': pos_err_after,
            'recovery': recovery,
            'ob_nr': ob_nr,
            'ob_pr': ob_pr,
        })
        print()

    # ── Visualization ─────────────────────────────────────────────────────────
    BG = '#111'
    n = len(results)
    fig, axes = plt.subplots(3, n, figsize=(n * 4.5, 13), facecolor=BG,
                              gridspec_kw={'hspace': 0.05, 'wspace': 0.04})

    vmax_obj = np.percentile(np.abs(obj_true), 99)
    axes[0, 0].imshow(np.abs(obj_true[:obj_true.shape[0]//2+30, :obj_true.shape[1]//2+30]),
                      cmap='gray', vmin=0, vmax=vmax_obj, aspect='equal')
    axes[0, 0].set_title('Ground Truth', color='white', fontsize=9)

    for ax in axes.ravel():
        ax.set_facecolor(BG)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values(): sp.set_edgecolor('#444')

    for ci, r in enumerate(results):
        col = axes[:, ci]

        def show(ax, img, cv, border):
            ax.imshow(np.abs(img), cmap='gray', vmin=0, vmax=vmax_obj, aspect='equal')
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_edgecolor(border); sp.set_linewidth(2)
            color = 'lime' if cv >= 0.70 else ('yellow' if cv >= 0.55 else 'red')
            ax.text(0.03, 0.03, f'r={cv:.3f}', transform=ax.transAxes, fontsize=8,
                    color=color, bbox=dict(facecolor='black', alpha=0.6, pad=1.5),
                    verticalalignment='bottom')

        title = r['label'].replace(' / ', '\n')
        axes[0, ci].set_title(f'{title}\n({r["Npos"]}pts, {r["actual_overlap"]:.0%} ovlp)',
                               color='white', fontsize=7.5, pad=4)

        show(axes[0, ci], obj_true,  None,        None)  # will be overwritten below
        show(axes[1, ci], r['ob_nr'], r['c_nr_obj'], '#ff9944')
        show(axes[2, ci], r['ob_pr'], r['c_pr_obj'], '#44ff88')

        # pos recovery annotation
        rec_color = 'lime' if r['recovery'] > 50 else ('yellow' if r['recovery'] > 20 else 'red')
        axes[2, ci].text(0.03, 0.97,
                         f'pos {r["pos_err_init"]:.1f}→{r["pos_err_after"]:.1f}px\n{r["recovery"]:+.0f}%',
                         transform=axes[2, ci].transAxes, fontsize=7,
                         color=rec_color, va='top',
                         bbox=dict(facecolor='black', alpha=0.6, pad=1.5))

    # Re-draw row 0 as ground truth repeated
    for ci in range(n):
        axes[0, ci].imshow(np.abs(obj_true), cmap='gray', vmin=0, vmax=vmax_obj, aspect='equal')
        axes[0, ci].set_xticks([]); axes[0, ci].set_yticks([])
        for sp in axes[0, ci].spines.values(): sp.set_edgecolor('#888'); sp.set_linewidth(1)

    row_labels = ['Ground Truth', 'No posref (orange)', 'With posref (green)']
    for ri, label in enumerate(row_labels):
        axes[ri, 0].set_ylabel(label, fontsize=8.5, color='white', labelpad=6, fontweight='bold')

    plt.suptitle('USAF: Effect of Overlap & Photon Count on Position Refinement\n'
                 f'(noise σ={NOISE_SIGMA}px, LSQML {N_ITER} iter)',
                 fontsize=12, y=1.01, color='white')

    out = Path(__file__).parent / 'posref_usaf_param_test.png'
    plt.savefig(out, dpi=130, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'\n[OK] Saved: {out.name}')

    # Summary table
    print('\n' + '=' * 75)
    print(f'{"Config":<38} {"Npos":>5} {"NoRef":>6} {"Posref":>6} {"PosRec":>7}')
    print('-' * 75)
    for r in results:
        print(f'{r["label"][:38]:<38} {r["Npos"]:>5} {r["c_nr_obj"]:>6.3f} {r["c_pr_obj"]:>6.3f} {r["recovery"]:>+6.1f}%')
    print('=' * 75)
    print('\n[ALL DONE]')
