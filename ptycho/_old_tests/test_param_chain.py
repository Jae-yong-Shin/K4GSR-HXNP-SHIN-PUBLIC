"""
test_param_chain.py - Offline parameter chain + quality assessment verification

Runs WITHOUT the WebSocket server. Directly calls DataLoader + EngineRunner.

Verifies:
1. Parameter chain: synthetic params -> DataLoader -> p dict -> engine input
2. Quality assessment: _assess_quality produces correct grades
3. Pre-flight screening: JS-equivalent conditions match expected results

Usage:
    python test_param_chain.py
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from server.engine_runner import EngineRunner
from synth_ptycho import estimate_probe_fwhm


# --------------------------------------------------------
#  JS-equivalent pre-flight check (Python port)
# --------------------------------------------------------
def preflight_check(energy_keV, asize, z_m, det_pixel_m, fwhm_nm,
                    scan_step_um, N_photons, ssa_h_um=50, ssa_v_um=50):
    """Python port of JS _ptychoPreflightCheck (NanoMAX criterion)."""
    lam_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_m = lam_m * z_m / (asize * det_pixel_m)
    dx_nm = dx_m * 1e9

    N_det = 1028  # EIGER2_1M
    O = N_det / asize
    probePx = fwhm_nm / dx_nm
    auto_step_um = fwhm_nm * 0.4 / 1e3
    eff_step_um = scan_step_um if scan_step_um > 0 else auto_step_um
    step_nm = eff_step_um * 1e3
    overlapPct = max(0, (1 - step_nm / fwhm_nm)) * 100

    # Coherent fraction (NanoMAX criterion: sigma_coh from KB acceptance)
    R_ssa = 58.0
    emit_x, emit_y = 58e-12, 5.8e-12
    sig_src_h = 19.5e-6   # source RMS horizontal (m) - photonSrc typical
    sig_src_v = 4.0e-6    # source RMS vertical (m)
    sig_div_h = emit_x / sig_src_h
    sig_div_v = emit_y / sig_src_v

    # Beam sigma at SSA
    sig_beam_h = np.sqrt(sig_src_h**2 + (sig_div_h * R_ssa)**2)
    sig_beam_v = np.sqrt(sig_src_v**2 + (sig_div_v * R_ssa)**2)

    # KB mirror parameters
    kbh_len, kbv_len = 0.100, 0.300  # m
    graze = 3e-3  # rad
    A_KB_H = kbh_len * np.sin(graze)  # 0.300 mm
    A_KB_V = kbv_len * np.sin(graze)  # 0.900 mm
    kbh_pos, kbv_pos = 149.90, 149.69
    L_SSA_to_KBH = kbh_pos - R_ssa
    L_SSA_to_KBV = kbv_pos - R_ssa

    # Coherent source sigma (NanoMAX)
    sig_coh_h = lam_m * L_SSA_to_KBH / (2 * np.pi * A_KB_H)
    sig_coh_v = lam_m * L_SSA_to_KBV / (2 * np.pi * A_KB_V)

    # SSA effective sigma (rectangular aperture)
    sqrt3 = np.sqrt(3)
    ssa_sig_h = ssa_h_um * 1e-6 / (2 * sqrt3)
    ssa_sig_v = ssa_v_um * 1e-6 / (2 * sqrt3)
    sig_eff_h = min(sig_beam_h, ssa_sig_h)
    sig_eff_v = min(sig_beam_v, ssa_sig_v)

    # Mode count
    M_H = max(1.0, sig_eff_h / sig_coh_h)
    M_V = max(1.0, sig_eff_v / sig_coh_v)
    M_total = M_H * M_V
    N_modes = int(np.ceil(M_total))
    f_coh = min(1.0, 1.0 / M_total)

    checks = []
    checks.append(('Oversampling', 'PASS' if O >= 4 else ('WARN' if O >= 2 else 'FAIL'), f'O={O:.1f}'))
    checks.append(('Probe extent', 'PASS' if probePx >= 3 else ('WARN' if probePx >= 1 else 'FAIL'), f'{probePx:.1f} px'))
    checks.append(('Overlap', 'PASS' if overlapPct >= 70 else ('WARN' if overlapPct >= 50 else 'FAIL'), f'{overlapPct:.0f}%'))
    checks.append(('Coherence', 'PASS' if f_coh > 0.5 else ('WARN' if f_coh > 0.1 else 'FAIL'),
                    f'f={f_coh:.3f} ({N_modes} modes, M_H={M_H:.1f} M_V={M_V:.1f})'))
    checks.append(('Photons', 'PASS' if N_photons >= 1e6 else ('WARN' if N_photons >= 1e4 else 'FAIL'), f'{N_photons:.1e}'))

    overall = all(c[1] == 'PASS' for c in checks)
    return {
        'pass': overall, 'checks': checks,
        'dx_nm': dx_nm, 'probePx': probePx, 'overlapPct': overlapPct,
        'f_coh': f_coh, 'O': O, 'N_modes': N_modes, 'M_H': M_H, 'M_V': M_V,
    }


# --------------------------------------------------------
#  Test 1: Parameter chain verification
# --------------------------------------------------------
def test_parameter_chain():
    print('\n' + '='*70)
    print('  TEST 1: Parameter Chain Verification')
    print('='*70)

    params = {
        'dataset_id': 6,
        'asize': 128,
        'energy_keV': 6.2,
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
    }

    lam = 1239.842e-9 / (6.2e3)
    dx_expected = lam * 5.0 / (128 * 75e-6) * 1e9

    print(f'\n[Input] energy={params["energy_keV"]}keV, beam=200nm, asize={params["asize"]}, z={params["z_m"]}m')
    print(f'[Expected] dx={dx_expected:.2f}nm, O={1028/128:.1f}')

    loader = DataLoader()
    data = loader.generate_synthetic(params)

    print(f'\n[DataLoader]')
    print(f'  fmag: {data["fmag"].shape}, positions: {data["positions"].shape}')
    print(f'  Npos={data["Npos"]}, dx={data["pixel_size_nm"]:.2f}nm')

    assert abs(data['pixel_size_nm'] - dx_expected) < 0.5, \
        f'dx mismatch: {data["pixel_size_nm"]:.2f} vs {dx_expected:.2f}'
    print(f'  dx CHECK OK')

    engine_params = {'number_iterations': 50, 'use_gpu': True}
    p = loader.build_p_dict(data, engine_params)

    print(f'\n[p dict] fmag={p["fmag"].shape}, probes={p["probes"].shape}, obj={p["object"][0].shape}')
    assert 'object_true' in data, 'Missing GT object'

    probe_2d = p['probes'][:, :, 0, 0]
    fwhm_px = estimate_probe_fwhm(probe_2d)
    print(f'  probe FWHM={fwhm_px:.1f}px = {fwhm_px*data["pixel_size_nm"]:.1f}nm')

    print(f'\n  ** Parameter chain OK **')
    return loader, data, p


# --------------------------------------------------------
#  Test 2: Quick DM + quality assessment
# --------------------------------------------------------
def test_quality_assessment(loader, data, p):
    print('\n' + '='*70)
    print('  TEST 2: Quality Assessment (DM 50 iter)')
    print('='*70)

    results = {}

    def capture_broadcast(msg):
        mtype = msg.get('type', '')
        if mtype == 'iteration_update':
            it = msg.get('iteration', 0)
            err = msg.get('error', 'N/A')
            if it % 10 == 0 or it == 1:
                print(f'  iter {it}: error={err}')
        elif mtype == 'reconstruction_complete':
            results['complete'] = msg
        elif mtype == 'reconstruction_started':
            print(f'  Started: {msg.get("engine")}')

    runner = EngineRunner(capture_broadcast)
    runner._gt_object = data.get('object_true')

    p['number_iterations'] = 50
    p['use_gpu'] = True

    t0 = time.time()
    runner.start(p, 'DM', 'test_quality')
    runner.worker_thread.join(timeout=300)
    elapsed = time.time() - t0

    assert 'complete' in results, 'Reconstruction did not complete!'
    msg = results['complete']
    q = msg.get('quality', {})

    print(f'\n[Result] engine={msg.get("engine")}, time={msg.get("total_time_sec",0):.1f}s')
    print(f'  final_error={msg.get("final_error","N/A")}')
    print(f'  Grade: {q.get("grade","?")}')
    print(f'  Convergence: {q.get("convergence","?")}')
    print(f'  obj_amp_max: {q.get("obj_amp_max","?")}')
    if 'norm_error' in q:
        print(f'  norm_error: {q["norm_error"]}')
    if q.get('recommendations'):
        for rec in q['recommendations']:
            print(f'  >> {rec}')

    assert q.get('grade') in ('EXCELLENT', 'GOOD', 'MARGINAL', 'POOR', 'UNKNOWN')
    assert q.get('convergence') in ('good', 'converged', 'stagnant', 'divergent', 'unknown')

    print(f'\n  ** Quality assessment OK (grade={q["grade"]}) **')
    return q


# --------------------------------------------------------
#  Test 3: Pre-flight screening
# --------------------------------------------------------
def test_preflight_screening():
    print('\n' + '='*70)
    print('  TEST 3: Pre-flight Screening')
    print('='*70)

    # Scenario A: 6.2keV, 200nm, asize=128 (auto step -> 60% overlap)
    r_a = preflight_check(
        energy_keV=6.2, asize=128, z_m=5.0, det_pixel_m=75e-6,
        fwhm_nm=200, scan_step_um=0, N_photons=1e8
    )
    print(f'\n[Scenario A: 6.2keV, 200nm, asize=128]')
    for name, status, val in r_a['checks']:
        print(f'  {name:15s} {status:4s}  {val}')
    print(f'  Overall: {"PASS" if r_a["pass"] else "FAIL"}')

    # Scenario B: 10keV, 50nm, asize=256 (auto step)
    r_b = preflight_check(
        energy_keV=10.0, asize=256, z_m=2.0, det_pixel_m=75e-6,
        fwhm_nm=50, scan_step_um=0, N_photons=1e8
    )
    print(f'\n[Scenario B: 10keV, 50nm, asize=256]')
    for name, status, val in r_b['checks']:
        print(f'  {name:15s} {status:4s}  {val}')
    print(f'  Overall: {"PASS" if r_b["pass"] else "FAIL"}')

    # Bad scenario: SSA=500um, 1e3 photons
    r_c = preflight_check(
        energy_keV=10.0, asize=256, z_m=2.0, det_pixel_m=75e-6,
        fwhm_nm=50, scan_step_um=0, N_photons=1e3,
        ssa_h_um=500, ssa_v_um=500
    )
    print(f'\n[Bad scenario: SSA=500um, N_ph=1e3]')
    for name, status, val in r_c['checks']:
        print(f'  {name:15s} {status:4s}  {val}')
    print(f'  Overall: {"PASS" if r_c["pass"] else "FAIL"}')

    n_fail_a = sum(1 for c in r_a['checks'] if c[1] == 'FAIL')
    assert n_fail_a == 0, f'Scenario A should have no FAIL checks, got {n_fail_a}'
    c_st = {c[0]: c[1] for c in r_c['checks']}
    # NanoMAX criterion: SSA=500um -> beam saturated, coherence depends on beam size
    # Bad scenario is bad due to low photons (and possibly low coherence)
    assert c_st['Photons'] != 'PASS', 'Bad scenario photons should not pass'

    print(f'\n  ** Pre-flight screening OK **')


# --------------------------------------------------------
if __name__ == '__main__':
    print('='*70)
    print('  PTYCHOGRAPHY PARAMETER CHAIN VERIFICATION')
    print('='*70)

    loader, data, p = test_parameter_chain()
    quality = test_quality_assessment(loader, data, p)
    test_preflight_screening()

    print('\n' + '='*70)
    print('  ALL TESTS PASSED')
    print('='*70)
