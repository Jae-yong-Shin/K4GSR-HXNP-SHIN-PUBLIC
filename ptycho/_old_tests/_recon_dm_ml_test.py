"""
DM+ML reconstruction test — mirrors what the browser actually runs.
"""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.data_loader import DataLoader
from server.engine_runner import EngineRunner

loader = DataLoader()

# Create MC probe
grid = 101
xx = np.linspace(-1, 1, grid)
yy = np.linspace(-1, 1, grid)
XX, YY = np.meshgrid(xx, yy)
hist2d = np.exp(-(XX**2/(2*0.2**2) + YY**2/(2*0.15**2))) * 1e4

params = {
    'dataset_id': 6, 'material': 'Au', 'energy_keV': 10.0,
    'objheight': 1e-6, 'asize': 128, 'scan_step_um': 0.02,
    'scan_lx_um': 0.5, 'scan_ly_um': 0.5, 'z_m': 2.0,
    'N_photons': 5000, 'noise_sigma': 0.0, 'rng_seed': 42,
    'det_pixel_m': 75e-6,
    'mc_probe': {
        'hist2d': hist2d.flatten().tolist(),
        'grid': grid,
        'fov_h_m': 500e-9, 'fov_v_m': 500e-9,
        'fwhm_h_m': 50e-9, 'fwhm_v_m': 50e-9,
        'kb_q_v': 0.31, 'kb_q_h': 0.10,
    },
}

print("Generating synthetic data...")
t0 = time.time()
data = loader.generate_synthetic(params)
print(f"  Done: {data['Npos']} positions in {time.time()-t0:.1f}s")

# Build p dict for DM stage
dm_iter = 100
ml_iter = 20
print(f"\n=== DM stage ({dm_iter} iterations) ===")

engine_params_dm = {
    'number_iterations': dm_iter,
    'use_gpu': False,
}
p = loader.build_p_dict(data, engine_params_dm)

dm_errors = []
def on_dm_iter(d):
    it = d.get('iteration', 0)
    err = d.get('error', 0)
    dm_errors.append(err)
    if it % 20 == 0 or it == 1:
        print(f"  DM iter {it:3d}: error = {err:.6f}")

p['_iteration_callback'] = on_dm_iter

from engines.DM import DM
t0 = time.time()
p_out, fdb_dm = DM(p)
t_dm = time.time() - t0
print(f"  DM done: {t_dm:.1f}s, final error: {dm_errors[-1]:.6f}")

# ── ML stage ──
print(f"\n=== ML stage ({ml_iter} iterations) ===")

# Fix up DM output for ML compatibility (same as engine_runner._run_dm_ml)
p_out['opt_iter'] = ml_iter

if isinstance(p_out.get('object_size'), list):
    p_out['object_size'] = np.array(p_out['object_size'])

# Ensure object arrays have mode dimension (ML expects 3D: H, W, object_modes)
for i, o in enumerate(p_out['object']):
    if isinstance(o, np.ndarray) and o.ndim == 2:
        p_out['object'][i] = o[:, :, np.newaxis]

ml_errors = []
def on_ml_iter(d):
    it = d.get('iteration', 0)
    err = d.get('error', 0)
    ml_errors.append(err)
    if it % 5 == 0 or it == 1:
        print(f"  ML iter {it:3d}: error = {err:.6f}")

p_out['_iteration_callback'] = on_ml_iter
p_out['_cancel_event'] = None
p_out['use_gpu'] = False

from engines.ML import ML
t0 = time.time()
p_final, fdb_ml = ML(p_out)
t_ml = time.time() - t0
print(f"  ML done: {t_ml:.1f}s")
if ml_errors:
    print(f"  ML errors: {ml_errors[0]:.6f} -> {ml_errors[-1]:.6f}")

# ── Extract results ──
obj_recon = p_final['object'][0] if isinstance(p_final['object'], list) else p_final['object']
if obj_recon.ndim > 2:
    obj_recon = obj_recon[:, :, 0]
probes_out = p_final['probes']
if probes_out.ndim == 4:
    probe_recon = probes_out[:, :, 0, 0]
elif probes_out.ndim == 3:
    probe_recon = probes_out[:, :, 0]
else:
    probe_recon = probes_out

obj_true = data['object_true']
probe_in = data['probes']

# ── Quality metrics ──
positions = data['positions']
asize = 128
pos_min_r = int(positions[:, 0].min())
pos_max_r = int(positions[:, 0].max()) + asize
pos_min_c = int(positions[:, 1].min())
pos_max_c = int(positions[:, 1].max()) + asize
h, w = obj_recon.shape
r0, r1 = max(0, pos_min_r), min(h, pos_max_r)
c0, c1 = max(0, pos_min_c), min(w, pos_max_c)
obj_crop = obj_recon[r0:r1, c0:c1]
true_crop = obj_true[r0:r1, c0:c1]

def corr(a, b):
    a = a.flatten().astype(float)
    b = b.flatten().astype(float)
    a -= a.mean(); b -= b.mean()
    d = np.sqrt(np.sum(a**2) * np.sum(b**2))
    return np.sum(a * b) / d if d > 1e-20 else 0.0

amp_c = corr(np.abs(obj_crop), np.abs(true_crop))
# Phase with global offset removal
pa = np.angle(obj_crop).flatten()
pb = np.angle(true_crop).flatten()
pa -= np.mean(pa - pb)
ph_c = corr(pa, pb)
pr_c = corr(np.abs(probe_recon), np.abs(probe_in))

print(f"\n=== Quality ===")
print(f"  Object amp correlation:  {amp_c:.4f}")
print(f"  Object phase correlation: {ph_c:.4f}")
print(f"  Probe amp correlation:   {pr_c:.4f}")
print(f"  Object recon amp: [{np.abs(obj_recon).min():.4e}, {np.abs(obj_recon).max():.4e}]")
print(f"  Object true amp:  [{np.abs(obj_true).min():.4e}, {np.abs(obj_true).max():.4e}]")

# ── Save images ──
try:
    from PIL import Image
    def save_cx(arr, path, title=""):
        amp = np.abs(arr)
        phase = np.angle(arr)
        an = amp - amp.min()
        if an.max() > 0: an = (an / an.max() * 255).astype(np.uint8)
        else: an = np.zeros_like(amp, dtype=np.uint8)
        pn = phase - phase.min()
        if pn.max() > 0: pn = (pn / pn.max() * 255).astype(np.uint8)
        else: pn = np.zeros_like(phase, dtype=np.uint8)
        h, w = an.shape
        c = np.zeros((h, w*2+4), dtype=np.uint8)
        c[:, :w] = an; c[:, w+4:] = pn
        Image.fromarray(c, mode='L').save(path)
        print(f"  Saved: {path} [{title}]")

    save_cx(true_crop, '_recon_dm_ml_obj_true.png', 'GT amp|phase')
    save_cx(obj_crop, '_recon_dm_ml_obj_recon.png', 'Recon amp|phase')
    save_cx(probe_in, '_recon_dm_ml_probe_in.png', 'Probe in amp|phase')
    save_cx(probe_recon, '_recon_dm_ml_probe_recon.png', 'Probe recon amp|phase')
except ImportError:
    print("  PIL not available")

print(f"\n  Total time: {t_dm + t_ml:.1f}s (DM {dm_iter} + ML {ml_iter})")
verdict = "GOOD" if amp_c > 0.7 and ph_c > 0.5 else "PARTIAL" if amp_c > 0.3 or ph_c > 0.3 else "POOR"
print(f"  VERDICT: {verdict}")
