"""Quick test: check reconstruction quality with current probe (including phase)."""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.data_loader import DataLoader

loader = DataLoader()

# Simulate what the browser sends
params = {
    'dataset_id': 6,       # Mandrill
    'material': 'Au',
    'energy_keV': 10.0,
    'objheight': 1e-6,
    'asize': 128,
    'scan_step_um': 0.02,  # ~20nm step for 50nm beam = ~60% overlap
    'scan_lx_um': 3.0,
    'scan_ly_um': 3.0,
    'z_m': 2.0,
    'N_photons': 1000,     # low photon count
    'noise_sigma': 0.0,
    'rng_seed': 42,
    'det_pixel_m': 75e-6,
    'mc_probe': None,  # No MC probe -> Gaussian fallback
}

print("=== Step 1: Generate synthetic data (Gaussian probe, no phase) ===")
t0 = time.time()
data_nophase = loader.generate_synthetic(params)
t1 = time.time()
print(f"  Generated in {t1-t0:.2f}s")
print(f"  fmag shape: {data_nophase['fmag'].shape}")
print(f"  Npos: {data_nophase['Npos']}")
print(f"  probe shape: {data_nophase['probes'].shape}")
print(f"  object_true shape: {data_nophase['object_true'].shape}")
print(f"  probe max amp: {np.abs(data_nophase['probes']).max():.4f}")
print(f"  probe phase range: [{np.angle(data_nophase['probes']).min():.4f}, {np.angle(data_nophase['probes']).max():.4f}]")
print(f"  fmag range: [{data_nophase['fmag'].min():.2f}, {data_nophase['fmag'].max():.2f}]")

# Now with MC probe (fake one for testing)
print("\n=== Step 2: Generate synthetic data (MC probe with phase) ===")
# Create a fake MC histogram (Gaussian beam)
grid = 101
xx = np.linspace(-1, 1, grid)
yy = np.linspace(-1, 1, grid)
XX, YY = np.meshgrid(xx, yy)
sigma_h = 0.2  # ~50nm beam in normalized units
sigma_v = 0.15
hist2d = np.exp(-(XX**2/(2*sigma_h**2) + YY**2/(2*sigma_v**2)))
hist2d *= 1e4  # photon counts

params_mc = dict(params)
params_mc['mc_probe'] = {
    'hist2d': hist2d.flatten().tolist(),
    'grid': grid,
    'fov_h_m': 500e-9,   # 500nm half-extent
    'fov_v_m': 500e-9,
    'fwhm_h_m': 50e-9,
    'fwhm_v_m': 50e-9,
    'kb_q_v': 0.31,
    'kb_q_h': 0.10,
}

t0 = time.time()
data_phase = loader.generate_synthetic(params_mc)
t1 = time.time()
print(f"  Generated in {t1-t0:.2f}s")
print(f"  fmag shape: {data_phase['fmag'].shape}")
print(f"  Npos: {data_phase['Npos']}")
print(f"  probe shape: {data_phase['probes'].shape}")
print(f"  probe max amp: {np.abs(data_phase['probes']).max():.4f}")
probe_phase = np.angle(data_phase['probes'])
print(f"  probe phase range: [{probe_phase.min():.4f}, {probe_phase.max():.4f}]")
print(f"  probe phase PV (where amp>10% of max): ", end="")
amp = np.abs(data_phase['probes'])
mask = amp > 0.1 * amp.max()
if mask.any():
    ph_masked = probe_phase[mask]
    print(f"{ph_masked.max() - ph_masked.min():.4f} rad")
else:
    print("N/A")
print(f"  fmag range: [{data_phase['fmag'].min():.2f}, {data_phase['fmag'].max():.2f}]")

# Run short DM reconstruction on BOTH
from server.engine_runner import EngineRunner

results = {}
for label, data in [("no_phase", data_nophase), ("with_phase", data_phase)]:
    print(f"\n=== Step 3: DM reconstruction ({label}) ===")

    engine_params = {
        'number_iterations': 30,  # quick test
        'use_gpu': False,
    }

    p = loader.build_p_dict(data, engine_params)
    p['_cancel_event'] = None

    errors = []
    def make_cb(errors_list):
        def cb(d):
            it = d.get('iteration', 0)
            err = d.get('error', 0)
            errors_list.append(err)
            if it % 10 == 0 or it == 1:
                print(f"    iter {it}: error={err:.6f}")
        return cb
    p['_iteration_callback'] = make_cb(errors)

    from engines.DM import DM
    t0 = time.time()
    p_out, fdb = DM(p)
    t1 = time.time()

    print(f"  Done in {t1-t0:.2f}s")
    print(f"  Final error: {errors[-1]:.6f}" if errors else "  No errors recorded")

    # Check object quality
    obj = p_out['object'][0] if isinstance(p_out['object'], list) else p_out['object']
    obj_true = data['object_true']

    # Object phase correlation with ground truth
    if obj.ndim > 2:
        obj = obj[:,:,0]

    print(f"  Object shape: {obj.shape}")
    print(f"  Object amp range: [{np.abs(obj).min():.4e}, {np.abs(obj).max():.4e}]")
    print(f"  Object phase range: [{np.angle(obj).min():.4f}, {np.angle(obj).max():.4f}]")

    # Check probe
    probes = p_out['probes']
    if probes.ndim == 4:
        probe_out = probes[:,:,0,0]
    elif probes.ndim == 3:
        probe_out = probes[:,:,0]
    else:
        probe_out = probes
    print(f"  Probe amp range: [{np.abs(probe_out).min():.6f}, {np.abs(probe_out).max():.6f}]")
    print(f"  Probe phase range: [{np.angle(probe_out).min():.4f}, {np.angle(probe_out).max():.4f}]")

    results[label] = {
        'errors': errors,
        'obj': obj,
        'probe': probe_out,
    }

# Compare
print("\n=== Comparison ===")
if results.get('no_phase') and results.get('with_phase'):
    e1 = results['no_phase']['errors'][-1] if results['no_phase']['errors'] else float('inf')
    e2 = results['with_phase']['errors'][-1] if results['with_phase']['errors'] else float('inf')
    print(f"  No-phase final error:   {e1:.6f}")
    print(f"  With-phase final error: {e2:.6f}")
    print(f"  Ratio: {e2/e1:.2f}x" if e1 > 0 else "")

print("\nDone!")
