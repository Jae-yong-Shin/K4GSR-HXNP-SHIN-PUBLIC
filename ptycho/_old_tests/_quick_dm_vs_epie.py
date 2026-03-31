"""Quick diagnostic: same synthetic data, DM vs ePIE, with images."""
import sys, time, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from server.engine_runner import EngineRunner

def run_engine(engine_type, n_iter, use_gpu=True):
    params = {
        'dataset_id': 6, 'asize': 128,
        'energy_keV': 10.0, 'material': 'Au', 'objheight': 1e-6,
        'z_m': 5.0, 'det_pixel_m': 75e-6,
        'scan_step_um': 1.5, 'scan_lx_um': 10.0, 'scan_ly_um': 10.0,
        'N_photons': int(1e8),
        'mc_probe': {
            'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
            'focal_length_m': 0.1, 'defocus_m': 0.0,
        },
        'N_modes': 1, 'coherent_fraction': 1.0,
    }

    loader = DataLoader()
    data = loader.generate_synthetic(params)
    p = loader.build_p_dict(data, {
        'number_iterations': n_iter,
        'use_gpu': use_gpu,
        'probe_modes': 1,
    })

    results = {}
    p_out_holder = [None]

    def cb(msg):
        if msg.get('type') == 'reconstruction_complete':
            results['complete'] = msg

    original_send = EngineRunner._send_complete
    def patched_send(self_r, p_out, fdb, et, jid):
        p_out_holder[0] = p_out
        original_send(self_r, p_out, fdb, et, jid)
    EngineRunner._send_complete = patched_send

    runner = EngineRunner(cb)
    runner._gt_object = data.get('object_true')
    t0 = time.time()
    runner.start(p, engine_type, 'test')
    runner.worker_thread.join(timeout=600)
    elapsed = time.time() - t0
    EngineRunner._send_complete = original_send

    obj_recon = None
    if p_out_holder[0]:
        obj = p_out_holder[0]['object']
        obj_recon = obj[0].squeeze() if isinstance(obj, list) else obj.squeeze()

    quality = results.get('complete', {}).get('quality', {})
    return obj_recon, data['object_true'], quality, elapsed


if __name__ == '__main__':
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    print("=== DM 300 iter ===")
    obj_dm, gt, q_dm, t_dm = run_engine('DM', 300)
    print(f"  norm_error={q_dm.get('norm_error','?')}, obj_max={q_dm.get('obj_amp_max','?')}, time={t_dm:.1f}s")

    print("\n=== ePIE 200 iter ===")
    obj_epie, _, q_epie, t_epie = run_engine('ePIE', 200)
    print(f"  norm_error={q_epie.get('norm_error','?')}, obj_max={q_epie.get('obj_amp_max','?')}, time={t_epie:.1f}s")

    # Plot comparison
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))

    m = 64
    gt_amp = np.abs(gt[m:-m, m:-m])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1

    # GT
    axes[0, 0].imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    axes[0, 0].set_title('Ground Truth (amplitude)', fontweight='bold')
    axes[0, 0].axis('off')

    axes[1, 0].imshow(np.angle(gt[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 0].set_title('Ground Truth (phase)', fontweight='bold')
    axes[1, 0].axis('off')

    # DM
    if obj_dm is not None:
        dm_amp = np.abs(obj_dm[m:-m, m:-m])
        axes[0, 1].imshow(dm_amp, cmap='jet',
                          vmin=np.percentile(dm_amp, 1),
                          vmax=np.percentile(dm_amp, 99.5) * 1.1)
        axes[0, 1].set_title(f'DM 300iter\nnorm_err={q_dm.get("norm_error",0):.4f}\n|obj|max={q_dm.get("obj_amp_max",0):.3f}',
                             fontweight='bold', fontsize=10)
        axes[1, 1].imshow(np.angle(obj_dm[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, 1].set_title('DM (phase)')
    else:
        axes[0, 1].text(0.5, 0.5, 'FAILED', transform=axes[0, 1].transAxes, ha='center', fontsize=20, color='red')
        axes[1, 1].text(0.5, 0.5, 'FAILED', transform=axes[1, 1].transAxes, ha='center', fontsize=20, color='red')
    axes[0, 1].axis('off')
    axes[1, 1].axis('off')

    # ePIE
    if obj_epie is not None:
        epie_amp = np.abs(obj_epie[m:-m, m:-m])
        axes[0, 2].imshow(epie_amp, cmap='jet',
                          vmin=np.percentile(epie_amp, 1),
                          vmax=np.percentile(epie_amp, 99.5) * 1.1)
        axes[0, 2].set_title(f'ePIE 200iter\nnorm_err={q_epie.get("norm_error",0):.4f}\n|obj|max={q_epie.get("obj_amp_max",0):.3f}',
                             fontweight='bold', fontsize=10)
        axes[1, 2].imshow(np.angle(obj_epie[m:-m, m:-m]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
        axes[1, 2].set_title('ePIE (phase)')
    else:
        axes[0, 2].text(0.5, 0.5, 'FAILED', transform=axes[0, 2].transAxes, ha='center', fontsize=20, color='red')
        axes[1, 2].text(0.5, 0.5, 'FAILED', transform=axes[1, 2].transAxes, ha='center', fontsize=20, color='red')
    axes[0, 2].axis('off')
    axes[1, 2].axis('off')

    fig.suptitle('Same Data: GT vs DM vs ePIE (single-mode, coherent)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = str(Path(__file__).parent / '_dm_vs_epie_diagnostic.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'\n[SAVED] {out}')
