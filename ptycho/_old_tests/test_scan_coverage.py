"""
Test Scenario A & B with scan_area = 1.1 um (same as compare_recon.py).
Scenario B was previously 0.3 um — too small for meaningful object features.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

SCAN_AREA_UM = None  # compute from formula (same as compare_recon.py)

def run_scenario(label, asize, energy_keV, z_m, det_pixel_m, fwhm_h_nm, fwhm_v_nm, f_m):
    lam = 1239.842e-9 / (energy_keV * 1e3)
    pixel_m = lam * z_m / (asize * det_pixel_m)
    pixel_nm = pixel_m * 1e9

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  pixel={pixel_nm:.2f}nm, asize={asize}, E={energy_keV}keV, z={z_m}m")

    dl = DataLoader()
    probe = dl._build_fresnel_probe(
        {'fwhm_h_m': fwhm_h_nm*1e-9, 'fwhm_v_m': fwhm_v_nm*1e-9,
         'focal_length_m': f_m, 'defocus_m': 0.0},
        asize, energy_keV, z_m, det_pixel_m)
    fwhm_px = estimate_probe_fwhm(probe)
    print(f"  probe FWHM={fwhm_px:.1f}px ({fwhm_px*pixel_nm:.1f}nm)")

    # Compute scan_area from formula (same as compare_recon.py)
    step_px = fwhm_px * 0.25
    scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
    scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)
    obj_size = int(np.ceil(scan_area_px)) + asize + 20
    print(f"  scan_area={scan_area_px:.1f}px ({scan_area_um:.3f}um), object={obj_size}px")

    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=1000,
        scan_step_um=None, overlap=0.75,
        scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
        probe=probe)
    ds = gen.generate(noise_sigma=0.0, rng_seed=42)
    print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2f}")

    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'asize': (asize, asize), 'Npos': ds.Npos,
    }
    p = dl.build_p_dict(data, {
        'number_iterations': 200, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    from engines.gpu.DM import DM as DM_GPU
    probes_in = p['probes'][:,:,0,0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    print(f"  Running DM 200...")
    ob_dm, pr_dm, err_dm = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=200)

    print(f"  DM error: iter1={err_dm[1]:.4e} -> iter200={err_dm[200]:.4e}")

    from engines.ML import ML
    print(f"  Running ML 50...")
    p_ml = dict(p)
    p_ml['opt_iter'] = 50
    p_ml['opt_flags'] = [1, 1]
    p_ml['opt_errmetric'] = 'poisson'
    p_ml['object'] = [o[:,:,np.newaxis] if o.ndim == 2 else o for o in ob_dm]
    if pr_dm.ndim == 2:
        p_ml['probes'] = pr_dm.reshape(pr_dm.shape[0], pr_dm.shape[1], 1, 1)
    else:
        p_ml['probes'] = pr_dm
    if isinstance(p_ml.get('object_size'), list):
        p_ml['object_size'] = np.array(p_ml['object_size'])
    p_ml, fdb_ml = ML(p_ml)

    ob_final = p_ml['object'][0].squeeze()

    # Normalized error (proper metric)
    truth = ds.object_true.squeeze()
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    norm_error = np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

    grade = "EXCELLENT" if norm_error < 0.15 else "GOOD" if norm_error < 0.30 else "MARGINAL" if norm_error < 0.50 else "POOR"
    print(f"\n  |obj| range: [{np.abs(ob_final).min():.4f}, {np.abs(ob_final).max():.4f}]")
    print(f"  Normalized error: {norm_error:.4f} -> {grade}")

    return {
        'label': label, 'norm_error': norm_error, 'grade': grade,
        'ob_final': ob_final, 'truth': truth, 'probe': ds.probe,
        'err_dm': err_dm, 'err_ml': fdb_ml.get('err', []),
        'positions': ds.positions_clean, 'Npos': ds.Npos,
        'fwhm_px': fwhm_px, 'pixel_nm': pixel_nm,
    }


if __name__ == '__main__':
    # Scenario A: 6.2keV, 200nm, asize=128
    res_a = run_scenario("Scenario A: 6.2keV, 200nm, asize=128, z=1m",
                         asize=128, energy_keV=6.2, z_m=1.0, det_pixel_m=75e-6,
                         fwhm_h_nm=200, fwhm_v_nm=200, f_m=0.3)

    # Scenario B: 10keV, 50nm, asize=256
    res_b = run_scenario("Scenario B: 10keV, 50nm, asize=256, z=1m",
                         asize=256, energy_keV=10.0, z_m=1.0, det_pixel_m=75e-6,
                         fwhm_h_nm=50, fwhm_v_nm=80, f_m=0.205)

    print(f"\n{'='*60}")
    print(f"  SUMMARY (scan_area from formula)")
    print(f"{'='*60}")
    print(f"  Scenario A: norm_error={res_a['norm_error']:.4f} ({res_a['grade']})")
    print(f"  Scenario B: norm_error={res_b['norm_error']:.4f} ({res_b['grade']})")

    # Save comparison plot
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 4, figsize=(18, 9))
        for row, res in enumerate([res_a, res_b]):
            axes[row,0].imshow(np.abs(res['probe']), cmap='jet')
            axes[row,0].set_title(f'Probe |P| FWHM={res["fwhm_px"]:.1f}px')
            axes[row,1].imshow(np.abs(res['truth']), cmap='jet')
            axes[row,1].set_title('Ground Truth')
            axes[row,2].imshow(np.abs(res['ob_final']), cmap='jet')
            axes[row,2].set_title(f'Recon |obj| err={res["norm_error"]:.4f}')
            axes[row,3].scatter(res['positions'][:,1], res['positions'][:,0], s=1, c='red', alpha=0.5)
            axes[row,3].set_xlim(0, res['truth'].shape[1])
            axes[row,3].set_ylim(res['truth'].shape[0], 0)
            axes[row,3].set_title(f'{res["Npos"]} positions')
            axes[row,3].set_aspect('equal')
            axes[row,0].set_ylabel(res['label'].split(':')[0], fontsize=11, fontweight='bold')

        for ax in axes.flat:
            ax.tick_params(labelsize=7)
        fig.suptitle(f'Scan Coverage Test: scan_area from formula\n'
                     f'A: {res_a["grade"]} ({res_a["norm_error"]:.4f}), '
                     f'B: {res_b["grade"]} ({res_b["norm_error"]:.4f})',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        out = Path(__file__).parent / 'test_scan_coverage_result.png'
        fig.savefig(str(out), dpi=150)
        plt.close()
        print(f"\nSaved: {out}")
    except Exception as e:
        print(f"Plot error: {e}")
