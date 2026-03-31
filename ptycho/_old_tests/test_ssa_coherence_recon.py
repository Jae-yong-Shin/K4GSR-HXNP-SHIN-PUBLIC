"""
test_ssa_coherence_recon.py - SSA coherence model reconstruction verification

Runs 5 scenarios comparing single-mode vs multi-mode reconstruction
under different SSA conditions to verify the NanoMAX criterion implementation.

Uses GPU DM engine (multi-mode probe supported) for all scenarios.

Scenarios:
  A. SSA = 7 um (fully coherent, 10 keV) -> 1 mode fwd -> 1 mode recon (baseline)
  B. SSA = 30 um (mild partial coh) -> 3 mode fwd -> 1 mode recon
  C. SSA = 30 um (mild partial coh) -> 3 mode fwd -> 3 mode recon
  D. SSA = 50 um (strong partial coh) -> 4 mode fwd -> 1 mode recon
  E. SSA = 50 um (strong partial coh) -> 4 mode fwd -> 4 mode recon

Usage:
    python test_ssa_coherence_recon.py
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from server.engine_runner import EngineRunner
from synth_ptycho import estimate_probe_fwhm


# -- NanoMAX criterion coherence calculation -----------------------------------

def nanomax_coherence(energy_keV, ssa_um):
    """
    Compute coherent fraction and mode count using NanoMAX criterion.
    """
    lam_m = 1239.842e-9 / (energy_keV * 1e3)

    # Source parameters (K4GSR BL10)
    emit_x, emit_y = 58e-12, 5.8e-12
    sig_src_h = 19.5e-6
    sig_src_v = 4.0e-6
    sig_div_h = emit_x / sig_src_h
    sig_div_v = emit_y / sig_src_v

    # SSA at 58 m
    R_ssa = 58.0
    sig_beam_h = np.sqrt(sig_src_h**2 + (sig_div_h * R_ssa)**2)
    sig_beam_v = np.sqrt(sig_src_v**2 + (sig_div_v * R_ssa)**2)

    # KB mirror parameters
    kbh_len, kbv_len = 0.100, 0.300
    graze = 3e-3
    A_KB_H = kbh_len * np.sin(graze)
    A_KB_V = kbv_len * np.sin(graze)
    kbh_pos, kbv_pos = 149.90, 149.69
    L_SSA_to_KBH = kbh_pos - R_ssa
    L_SSA_to_KBV = kbv_pos - R_ssa

    # Coherent source sigma (NanoMAX)
    sig_coh_h = lam_m * L_SSA_to_KBH / (2 * np.pi * A_KB_H)
    sig_coh_v = lam_m * L_SSA_to_KBV / (2 * np.pi * A_KB_V)

    # SSA effective sigma (rectangular aperture)
    sqrt3 = np.sqrt(3)
    ssa_sig = ssa_um * 1e-6 / (2 * sqrt3)
    sig_eff_h = min(sig_beam_h, ssa_sig)
    sig_eff_v = min(sig_beam_v, ssa_sig)

    # Mode count
    M_H = max(1.0, sig_eff_h / sig_coh_h)
    M_V = max(1.0, sig_eff_v / sig_coh_v)
    M_total = M_H * M_V
    N_modes = int(np.ceil(M_total))
    f_coh = min(1.0, 1.0 / M_total)

    return {
        'f_coh': f_coh, 'N_modes': N_modes,
        'M_H': M_H, 'M_V': M_V, 'M_total': M_total,
        'sig_coh_h_um': sig_coh_h * 1e6,
        'sig_coh_v_um': sig_coh_v * 1e6,
        'sig_eff_h_um': sig_eff_h * 1e6,
        'sig_eff_v_um': sig_eff_v * 1e6,
    }


# -- Reconstruction with direct p_out extraction ------------------------------

def run_scenario(label, ssa_um, energy_keV, n_modes_forward, n_modes_recon,
                 n_iter=300, use_gpu=True):
    """
    Run a single scenario using GPU DM engine.
    Returns: (quality, obj_recon, obj_true, elapsed, coh)
    """
    coh = nanomax_coherence(energy_keV, ssa_um)
    f_coh = coh['f_coh']

    print(f'\n{"="*70}')
    print(f'  {label}')
    print(f'  SSA={ssa_um}um, {energy_keV}keV, f_coh={f_coh:.3f}, '
          f'M_total={coh["M_total"]:.1f} ({coh["N_modes"]} physics modes)')
    print(f'  Forward: {n_modes_forward} modes, Recon: {n_modes_recon} modes')
    print(f'{"="*70}')

    # Generate synthetic data
    params = {
        'dataset_id': 6,
        'asize': 128,
        'energy_keV': energy_keV,
        'material': 'Au',
        'objheight': 1e-6,
        'z_m': 5.0,
        'det_pixel_m': 75e-6,
        'scan_step_um': 1.5,
        'scan_lx_um': 10.0,
        'scan_ly_um': 10.0,
        'N_photons': int(1e8),
        'mc_probe': {
            'fwhm_h_m': 200e-9,
            'fwhm_v_m': 200e-9,
            'focal_length_m': 0.1,
            'defocus_m': 0.0,
        },
        'N_modes': n_modes_forward,
        'coherent_fraction': f_coh if n_modes_forward > 1 else 1.0,
    }

    loader = DataLoader()
    data = loader.generate_synthetic(params)
    print(f'  Data: fmag={data["fmag"].shape}, Npos={data["Npos"]}, '
          f'dx={data["pixel_size_nm"]:.1f}nm')

    # Use DM engine (GPU with multi-mode support)
    engine_type = 'DM'

    engine_params = {
        'number_iterations': n_iter,
        'use_gpu': use_gpu,
        'probe_modes': n_modes_recon,
    }
    p = loader.build_p_dict(data, engine_params)

    results = {}
    p_out_holder = [None]

    def capture_broadcast(msg):
        mtype = msg.get('type', '')
        if mtype == 'iteration_update':
            it = msg.get('iteration', 0)
            err = msg.get('error', 'N/A')
            if it % 50 == 0 or it == 1 or it == n_iter:
                print(f'    iter {it}: error={err}')
        elif mtype == 'reconstruction_complete':
            results['complete'] = msg

    # Monkey-patch EngineRunner to capture p_out
    original_send = EngineRunner._send_complete

    def patched_send(self_runner, p_out_arg, fdb, engine_type_arg, job_id):
        p_out_holder[0] = p_out_arg
        original_send(self_runner, p_out_arg, fdb, engine_type_arg, job_id)

    EngineRunner._send_complete = patched_send

    runner = EngineRunner(capture_broadcast)
    runner._gt_object = data.get('object_true')

    t0 = time.time()
    runner.start(p, engine_type, 'test')
    runner.worker_thread.join(timeout=600)
    elapsed = time.time() - t0

    # Restore original
    EngineRunner._send_complete = original_send

    if 'complete' not in results:
        print('  !! FAILED - reconstruction did not complete!')
        return None, None, data.get('object_true'), elapsed, coh

    msg = results['complete']
    quality = msg.get('quality', {})

    # Extract reconstructed object
    obj_recon = None
    if p_out_holder[0] is not None:
        p_out = p_out_holder[0]
        obj = p_out['object']
        if isinstance(obj, list):
            obj_recon = obj[0].squeeze()
        elif isinstance(obj, np.ndarray):
            obj_recon = obj.squeeze()

    gpu_str = 'GPU' if use_gpu else 'CPU'
    print(f'\n  Result: {elapsed:.1f}s (DM, {gpu_str})')
    print(f'  Grade: {quality.get("grade", "?")}')
    print(f'  Convergence: {quality.get("convergence", "?")}')
    print(f'  norm_error: {quality.get("norm_error", "N/A")}')
    amp_max = quality.get('obj_amp_max', 0)
    if isinstance(amp_max, (int, float)):
        print(f'  obj_amp_max: {amp_max:.4f}')
    else:
        print(f'  obj_amp_max: {amp_max}')
    if quality.get('recommendations'):
        for rec in quality['recommendations']:
            print(f'  >> {rec}')

    return quality, obj_recon, data.get('object_true'), elapsed, coh


# -- Image plotting ------------------------------------------------------------

def save_comparison_figure(results_list, output_path):
    """
    Save comparison figure: Row 0 = object amp (recon), Row 1 = GT, Row 2 = metrics.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
    except ImportError:
        print('[WARN] matplotlib not available, skipping figure')
        return

    n = len(results_list)
    fig = plt.figure(figsize=(4.5 * n, 13))
    gs = GridSpec(3, n, height_ratios=[1, 1, 0.7], hspace=0.25, wspace=0.2)

    for i, r in enumerate(results_list):
        quality = r['quality'] or {}
        coh = r['coh'] or {}
        obj_true = r['obj_true']
        obj_recon = r['obj_recon']

        # Crop region (remove border padding)
        if obj_true is not None:
            oh, ow = obj_true.shape
            m = 64
            gt_amp = np.abs(obj_true[m:oh-m, m:ow-m])
        else:
            gt_amp = np.ones((100, 100))

        vmin_gt = np.percentile(gt_amp, 1)
        vmax_gt = np.percentile(gt_amp, 99.5) * 1.1

        # Row 0: Reconstructed object amplitude
        ax0 = fig.add_subplot(gs[0, i])
        if obj_recon is not None:
            rh, rw = obj_recon.shape
            m_r = 64
            if rh > 2 * m_r and rw > 2 * m_r:
                recon_amp = np.abs(obj_recon[m_r:rh-m_r, m_r:rw-m_r])
            else:
                recon_amp = np.abs(obj_recon)
            vmin_r = np.percentile(recon_amp, 1)
            vmax_r = np.percentile(recon_amp, 99.5) * 1.1
            ax0.imshow(recon_amp, cmap='jet', vmin=vmin_r, vmax=vmax_r)
        else:
            ax0.text(0.5, 0.5, 'FAILED', transform=ax0.transAxes,
                    ha='center', va='center', fontsize=14, color='red')
        ax0.set_title(r['label'], fontsize=9, fontweight='bold')
        ax0.axis('off')
        if i == 0:
            ax0.set_ylabel('Reconstructed', fontsize=10, fontweight='bold')

        # Row 1: Ground truth
        ax1 = fig.add_subplot(gs[1, i])
        ax1.imshow(gt_amp, cmap='jet', vmin=vmin_gt, vmax=vmax_gt)
        ax1.axis('off')
        if i == 0:
            ax1.set_ylabel('Ground Truth', fontsize=10, fontweight='bold')

        # Row 2: Metrics
        ax2 = fig.add_subplot(gs[2, i])
        norm_err = quality.get('norm_error', -1)
        grade = quality.get('grade', '?')
        info_text = (
            f'SSA: {r.get("ssa_um", "?")} um\n'
            f'f_coh: {coh.get("f_coh", 0):.3f}\n'
            f'M_H={coh.get("M_H",0):.1f} x M_V={coh.get("M_V",0):.1f}\n'
            f'Fwd: {r.get("n_fwd", 1)} mode  Recon: {r.get("n_rec", 1)} mode\n'
            f'Grade: {grade}\n'
            f'norm_error: {norm_err:.4f}\n'
            f'|obj|_max: {quality.get("obj_amp_max", 0):.3f}\n'
            f'Time: {r.get("elapsed", 0):.1f}s'
        )
        ax2.text(0.5, 0.5, info_text, transform=ax2.transAxes,
                fontsize=8, va='center', ha='center', fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
        ax2.axis('off')

    fig.suptitle('SSA Coherence - Reconstruction Verification (NanoMAX Criterion, GPU DM)',
                 fontsize=13, fontweight='bold', y=0.98)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'\n[SAVED] {output_path}')


# -- Main ----------------------------------------------------------------------

if __name__ == '__main__':
    energy = 10.0  # keV

    # Print coherence table
    print('='*70)
    print('  NanoMAX Criterion Coherence Table (10 keV)')
    print('='*70)
    print(f'  {"SSA(um)":>8} {"f_coh":>8} {"M_H":>6} {"M_V":>6} {"M_total":>8} {"N_modes":>8}')
    print('-'*55)
    for ssa in [5, 7, 10, 15, 20, 30, 50, 75, 100]:
        c = nanomax_coherence(energy, ssa)
        tag = ''
        if c['N_modes'] == 1:
            tag = ' <- coherent'
        elif ssa >= 100:
            tag = ' <- saturated'
        print(f'  {ssa:>8} {c["f_coh"]:>8.3f} {c["M_H"]:>6.2f} '
              f'{c["M_V"]:>6.2f} {c["M_total"]:>8.1f} {c["N_modes"]:>8}{tag}')

    # -- 5 Scenarios -----------------------------------------------------------
    all_results = []
    DM_ITER = 300

    # A: Fully coherent (SSA=7um) - baseline
    qa, oa, gt_a, ta, ca = run_scenario(
        'A: SSA=7um (coherent)', 7, energy,
        n_modes_forward=1, n_modes_recon=1, n_iter=DM_ITER)
    all_results.append({
        'label': 'A: SSA=7um\n1-mode fwd\n1-mode recon',
        'quality': qa, 'obj_recon': oa, 'obj_true': gt_a,
        'elapsed': ta, 'coh': ca,
        'ssa_um': 7, 'n_fwd': 1, 'n_rec': 1,
    })

    # B: SSA=30um, partial coh -> single-mode recon (shows degradation)
    coh_30 = nanomax_coherence(energy, 30)
    n_fwd_30 = min(coh_30['N_modes'], 5)  # cap at 5 practical modes
    qb, ob_r, gt_b, tb, cb = run_scenario(
        'B: SSA=30um, multi-fwd, 1-recon', 30, energy,
        n_modes_forward=n_fwd_30, n_modes_recon=1, n_iter=DM_ITER)
    all_results.append({
        'label': f'B: SSA=30um\n{n_fwd_30}-mode fwd\n1-mode recon',
        'quality': qb, 'obj_recon': ob_r, 'obj_true': gt_b,
        'elapsed': tb, 'coh': cb,
        'ssa_um': 30, 'n_fwd': n_fwd_30, 'n_rec': 1,
    })

    # C: SSA=30um, partial coh -> multi-mode recon (shows recovery)
    qc, oc, gt_c, tc, cc = run_scenario(
        'C: SSA=30um, multi-fwd, multi-recon', 30, energy,
        n_modes_forward=n_fwd_30, n_modes_recon=n_fwd_30, n_iter=DM_ITER,
        use_gpu=True)
    all_results.append({
        'label': f'C: SSA=30um\n{n_fwd_30}-mode fwd\n{n_fwd_30}-mode recon',
        'quality': qc, 'obj_recon': oc, 'obj_true': gt_c,
        'elapsed': tc, 'coh': cc,
        'ssa_um': 30, 'n_fwd': n_fwd_30, 'n_rec': n_fwd_30,
    })

    # D: SSA=50um, strong partial coh -> single-mode recon
    coh_50 = nanomax_coherence(energy, 50)
    n_fwd_50 = min(coh_50['N_modes'], 5)  # cap at 5
    qd, od, gt_d, td, cd = run_scenario(
        'D: SSA=50um, multi-fwd, 1-recon', 50, energy,
        n_modes_forward=n_fwd_50, n_modes_recon=1, n_iter=DM_ITER)
    all_results.append({
        'label': f'D: SSA=50um\n{n_fwd_50}-mode fwd\n1-mode recon',
        'quality': qd, 'obj_recon': od, 'obj_true': gt_d,
        'elapsed': td, 'coh': cd,
        'ssa_um': 50, 'n_fwd': n_fwd_50, 'n_rec': 1,
    })

    # E: SSA=50um -> multi-mode recon
    qe, oe, gt_e, te, ce = run_scenario(
        'E: SSA=50um, multi-fwd, multi-recon', 50, energy,
        n_modes_forward=n_fwd_50, n_modes_recon=n_fwd_50, n_iter=DM_ITER,
        use_gpu=True)
    all_results.append({
        'label': f'E: SSA=50um\n{n_fwd_50}-mode fwd\n{n_fwd_50}-mode recon',
        'quality': qe, 'obj_recon': oe, 'obj_true': gt_e,
        'elapsed': te, 'coh': ce,
        'ssa_um': 50, 'n_fwd': n_fwd_50, 'n_rec': n_fwd_50,
    })

    # -- Summary table ---------------------------------------------------------
    print('\n' + '='*95)
    print('  SUMMARY: SSA Coherence Reconstruction Verification (GPU DM)')
    print('='*95)
    print(f'  {"Label":<15} {"SSA":>5} {"f_coh":>7} {"M_tot":>6} '
          f'{"Fwd":>4} {"Rec":>4} {"Grade":<10} {"norm_err":>9} {"|obj|max":>9} {"Time":>7}')
    print('-'*95)
    for r in all_results:
        q = r['quality'] or {}
        c = r['coh'] or {}
        lbl = r['label'].split('\n')[0]
        amp_max = q.get('obj_amp_max', 0)
        if not isinstance(amp_max, (int, float)):
            amp_max = 0.0
        print(f'  {lbl:<15} '
              f'{r["ssa_um"]:>5} '
              f'{c.get("f_coh", 0):>7.3f} '
              f'{c.get("M_total", 0):>6.1f} '
              f'{r["n_fwd"]:>4} '
              f'{r["n_rec"]:>4} '
              f'{q.get("grade", "?"):<10} '
              f'{q.get("norm_error", -1):>9.4f} '
              f'{amp_max:>9.4f} '
              f'{r.get("elapsed", 0):>7.1f}')

    # -- Observations ----------------------------------------------------------
    print('\n' + '='*70)
    print('  OBSERVATIONS:')
    print('='*70)

    pairs = [
        (0, 1, 'Coherent(7um) vs Partial(30um) single-mode'),
        (1, 2, 'SSA=30um: single-mode vs multi-mode recon'),
        (0, 3, 'Coherent(7um) vs Partial(50um) single-mode'),
        (3, 4, 'SSA=50um: single-mode vs multi-mode recon'),
    ]
    for ia, ib, desc in pairs:
        qa_cmp = all_results[ia]['quality'] or {}
        qb_cmp = all_results[ib]['quality'] or {}
        ne_a = qa_cmp.get('norm_error', -1)
        ne_b = qb_cmp.get('norm_error', -1)
        if ne_a > 0 and ne_b > 0:
            delta_pct = (ne_b / ne_a - 1) * 100
            arrow = 'worse' if delta_pct > 0 else 'better'
            print(f'  {desc}:')
            print(f'    norm_error {ne_a:.4f} -> {ne_b:.4f} ({delta_pct:+.1f}% {arrow})')

    # Save figure
    out_path = str(Path(__file__).parent / 'ssa_coherence_recon_comparison.png')
    save_comparison_figure(all_results, out_path)

    print('\n' + '='*70)
    print('  ALL SCENARIOS COMPLETE')
    print('='*70)
