"""
Quick test: verify ePIE engine works through engine_runner.py
"""
import sys
import numpy as np
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader
from server.engine_runner import EngineRunner

# Capture broadcast messages
messages = []
def mock_broadcast(msg):
    t = msg.get('type', '?')
    if t == 'iteration_update':
        it = msg.get('iteration', 0)
        err = msg.get('error', 0)
        has_preview = 'raw_object' in msg
        if it <= 3 or it % 10 == 0:
            print(f"  iter {it}: err={err:.4e}, preview={'Y' if has_preview else 'N'}")
    elif t == 'reconstruction_started':
        print(f"  STARTED: engine={msg.get('engine')}")
    elif t == 'reconstruction_complete':
        q = msg.get('quality', {})
        print(f"  COMPLETE: engine={msg.get('engine')}, time={msg.get('total_time_sec')}s")
        print(f"    quality: grade={q.get('grade')}, norm_error={q.get('norm_error', 'N/A')}")
        print(f"    convergence={q.get('convergence')}, obj_amp_max={q.get('obj_amp_max', 'N/A')}")
        if q.get('recommendations'):
            for r in q['recommendations']:
                print(f"    recommendation: {r}")
    elif t == 'pipeline_stage_change':
        print(f"  STAGE CHANGE: stage={msg.get('stage')}, engine={msg.get('engine')}")
    messages.append(msg)

def mock_complete(engine, p_out, elapsed, err_values):
    pass

# Generate synthetic data
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = int(1e8)

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
     'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9
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
truth = ds.object_true.squeeze()

print(f"Scenario: N={N_photons:.0e}, Npos={ds.Npos}, FWHM={fwhm_px:.1f}px")

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
    'object_true': truth,  # For GT comparison
}
dl.current_data = data

# =====================================================
# TEST 1: ePIE standalone via engine_runner
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 1: ePIE standalone (50 iter) via engine_runner")
print(f"{'=' * 60}")

runner = EngineRunner(mock_broadcast, mock_complete)
runner._gt_object = truth

params = {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
}
p = dl.build_p_dict(data, params)

messages.clear()
runner.start(p, 'ePIE', 'test1')
runner.worker_thread.join(timeout=120)

# Check results
complete_msgs = [m for m in messages if m.get('type') == 'reconstruction_complete']
if complete_msgs:
    q = complete_msgs[0].get('quality', {})
    print(f"\n  Result: grade={q.get('grade')}, norm_error={q.get('norm_error')}")
else:
    error_msgs = [m for m in messages if m.get('type') == 'reconstruction_error']
    if error_msgs:
        print(f"\n  ERROR: {error_msgs[0].get('error')}")
        print(error_msgs[0].get('traceback', ''))

# =====================================================
# TEST 2: ePIE_ML pipeline via engine_runner
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 2: ePIE50 + ML30 via engine_runner")
print(f"{'=' * 60}")

runner2 = EngineRunner(mock_broadcast, mock_complete)
runner2._gt_object = truth

params2 = {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
    'epie_iterations': 50, 'ml_iterations': 30,
}
p2 = dl.build_p_dict(data, params2)
for key in ('epie_iterations', 'ml_iterations'):
    p2[key] = params2[key]

messages.clear()
runner2.start(p2, 'ePIE_ML', 'test2')
runner2.worker_thread.join(timeout=300)

complete_msgs2 = [m for m in messages if m.get('type') == 'reconstruction_complete']
if complete_msgs2:
    q2 = complete_msgs2[0].get('quality', {})
    print(f"\n  Result: grade={q2.get('grade')}, norm_error={q2.get('norm_error')}")

print(f"\n{'=' * 60}")
print(f"  ALL TESTS DONE")
print(f"{'=' * 60}")
