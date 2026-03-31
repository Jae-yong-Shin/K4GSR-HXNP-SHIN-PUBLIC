"""
Full reconstruction verification test.
- Generates synthetic data with MC probe (including phase)
- Runs DM reconstruction (50 iterations for speed)
- Compares reconstructed object with ground truth
- Saves comparison images to _recon_verify_*.png
"""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.data_loader import DataLoader

# ── Step 1: Generate synthetic data with MC probe ──
print("=" * 60)
print("Step 1: Generate synthetic data")
print("=" * 60)

loader = DataLoader()

# Create realistic MC probe (Gaussian beam from KB mirrors)
grid = 101
xx = np.linspace(-1, 1, grid)
yy = np.linspace(-1, 1, grid)
XX, YY = np.meshgrid(xx, yy)
sigma_h, sigma_v = 0.2, 0.15  # asymmetric KB focus
hist2d = np.exp(-(XX**2/(2*sigma_h**2) + YY**2/(2*sigma_v**2))) * 1e4

params = {
    'dataset_id': 6,       # Mandrill
    'material': 'Au',
    'energy_keV': 10.0,
    'objheight': 1e-6,
    'asize': 128,
    'scan_step_um': 0.02,  # 20nm step, ~60% overlap with 50nm beam
    'scan_lx_um': 0.5,     # small area for fast test
    'scan_ly_um': 0.5,
    'z_m': 2.0,
    'N_photons': 5000,     # moderate photon count
    'noise_sigma': 0.0,
    'rng_seed': 42,
    'det_pixel_m': 75e-6,
    'mc_probe': {
        'hist2d': hist2d.flatten().tolist(),
        'grid': grid,
        'fov_h_m': 500e-9, 'fov_v_m': 500e-9,
        'fwhm_h_m': 50e-9, 'fwhm_v_m': 50e-9,
        'kb_q_v': 0.31, 'kb_q_h': 0.10,
    },
}

t0 = time.time()
data = loader.generate_synthetic(params)
t_gen = time.time() - t0

print(f"  Generated in {t_gen:.2f}s")
print(f"  Npos: {data['Npos']}")
print(f"  fmag shape: {data['fmag'].shape}")
print(f"  probe shape: {data['probes'].shape}")
print(f"  probe amp max: {np.abs(data['probes']).max():.4f}")
ph = np.angle(data['probes'])
mask = np.abs(data['probes']) > 0.1 * np.abs(data['probes']).max()
print(f"  probe phase PV (beam): {ph[mask].max()-ph[mask].min():.4f} rad")
print(f"  object_true shape: {data['object_true'].shape}")
print(f"  fmag range: [{data['fmag'].min():.2f}, {data['fmag'].max():.2f}]")

# ── Step 2: Run DM reconstruction ──
print()
print("=" * 60)
print("Step 2: DM Reconstruction (50 iterations)")
print("=" * 60)

engine_params = {
    'number_iterations': 50,
    'use_gpu': False,
}

p = loader.build_p_dict(data, engine_params)

errors = []
def on_iter(d):
    it = d.get('iteration', 0)
    err = d.get('error', 0)
    errors.append(err)
    if it % 10 == 0 or it == 1 or it == 50:
        print(f"  iter {it:3d}: error = {err:.6f}")

p['_iteration_callback'] = on_iter

from engines.DM import DM
t0 = time.time()
p_out, fdb = DM(p)
t_recon = time.time() - t0
print(f"  Reconstruction done in {t_recon:.2f}s")
if errors:
    print(f"  Error: {errors[0]:.6f} -> {errors[-1]:.6f} (ratio: {errors[-1]/errors[0]:.4f})")

# ── Step 3: Extract results ──
obj_recon = p_out['object'][0] if isinstance(p_out['object'], list) else p_out['object']
if obj_recon.ndim > 2:
    obj_recon = obj_recon[:, :, 0]

probes_out = p_out['probes']
if probes_out.ndim == 4:
    probe_recon = probes_out[:, :, 0, 0]
elif probes_out.ndim == 3:
    probe_recon = probes_out[:, :, 0]
else:
    probe_recon = probes_out

obj_true = data['object_true']
probe_in = data['probes']

print(f"\n  Object recon shape: {obj_recon.shape}")
print(f"  Object recon amp: [{np.abs(obj_recon).min():.4e}, {np.abs(obj_recon).max():.4e}]")
print(f"  Object true amp: [{np.abs(obj_true).min():.4e}, {np.abs(obj_true).max():.4e}]")
print(f"  Probe recon amp: [{np.abs(probe_recon).min():.6f}, {np.abs(probe_recon).max():.6f}]")
print(f"  Probe input amp: [{np.abs(probe_in).min():.6f}, {np.abs(probe_in).max():.6f}]")

# ── Step 4: Quality metrics ──
print()
print("=" * 60)
print("Step 3: Quality Metrics")
print("=" * 60)

# Crop object to illuminated region for comparison
# Find the region that was actually illuminated
positions = data['positions']
asize = 128
pos_min_r = int(positions[:, 0].min())
pos_max_r = int(positions[:, 0].max()) + asize
pos_min_c = int(positions[:, 1].min())
pos_max_c = int(positions[:, 1].max()) + asize

# Crop both to illuminated region
h, w = obj_recon.shape
r0 = max(0, pos_min_r)
r1 = min(h, pos_max_r)
c0 = max(0, pos_min_c)
c1 = min(w, pos_max_c)

obj_crop = obj_recon[r0:r1, c0:c1]
true_crop = obj_true[r0:r1, c0:c1]

# Phase correlation (remove global phase offset)
def phase_correlation(a, b):
    """Correlation of phase images, accounting for global offset."""
    pa = np.angle(a).flatten()
    pb = np.angle(b).flatten()
    # Remove global phase offset
    offset = np.mean(pa - pb)
    pa_adj = pa - offset
    # Pearson correlation
    pa_c = pa_adj - pa_adj.mean()
    pb_c = pb - pb.mean()
    denom = np.sqrt(np.sum(pa_c**2) * np.sum(pb_c**2))
    if denom < 1e-20:
        return 0.0
    return np.sum(pa_c * pb_c) / denom

# Amplitude correlation
def amp_correlation(a, b):
    aa = np.abs(a).flatten()
    ab = np.abs(b).flatten()
    aa_c = aa - aa.mean()
    ab_c = ab - ab.mean()
    denom = np.sqrt(np.sum(aa_c**2) * np.sum(ab_c**2))
    if denom < 1e-20:
        return 0.0
    return np.sum(aa_c * ab_c) / denom

amp_corr = amp_correlation(obj_crop, true_crop)
ph_corr = phase_correlation(obj_crop, true_crop)
print(f"  Object amplitude correlation: {amp_corr:.4f}")
print(f"  Object phase correlation:     {ph_corr:.4f}")
print(f"  (> 0.8 is good, > 0.9 is excellent)")

# Probe amplitude correlation
probe_amp_corr = amp_correlation(probe_recon, probe_in)
print(f"  Probe amplitude correlation:  {probe_amp_corr:.4f}")

# ── Step 5: Save images ──
print()
print("=" * 60)
print("Step 4: Save comparison images")
print("=" * 60)

try:
    from PIL import Image

    def save_complex_image(arr, path, title=""):
        """Save amplitude and phase side by side."""
        amp = np.abs(arr)
        phase = np.angle(arr)

        # Normalize amplitude to [0, 255]
        amp_norm = amp - amp.min()
        if amp_norm.max() > 0:
            amp_norm = (amp_norm / amp_norm.max() * 255).astype(np.uint8)
        else:
            amp_norm = np.zeros_like(amp, dtype=np.uint8)

        # Normalize phase to [0, 255]
        phase_norm = phase - phase.min()
        if phase_norm.max() > 0:
            phase_norm = (phase_norm / phase_norm.max() * 255).astype(np.uint8)
        else:
            phase_norm = np.zeros_like(phase, dtype=np.uint8)

        # Side by side
        h, w = amp_norm.shape
        combined = np.zeros((h, w * 2 + 4), dtype=np.uint8)
        combined[:, :w] = amp_norm
        combined[:, w+4:] = phase_norm

        img = Image.fromarray(combined, mode='L')
        img.save(path)
        print(f"  Saved: {path} ({combined.shape[1]}x{combined.shape[0]}) [{title}]")

    # Object true
    save_complex_image(true_crop, '_recon_verify_obj_true.png', 'Object Ground Truth (amp|phase)')

    # Object reconstructed
    save_complex_image(obj_crop, '_recon_verify_obj_recon.png', 'Object Reconstructed (amp|phase)')

    # Probe input
    save_complex_image(probe_in, '_recon_verify_probe_input.png', 'Probe Input (amp|phase)')

    # Probe reconstructed
    save_complex_image(probe_recon, '_recon_verify_probe_recon.png', 'Probe Reconstructed (amp|phase)')

    # Error convergence
    if errors:
        err_arr = np.array(errors)
        h_err = 100
        w_err = len(errors)
        err_img = np.zeros((h_err, max(w_err, 10)), dtype=np.uint8)
        err_norm = err_arr / (err_arr.max() + 1e-20)
        for i, e in enumerate(err_norm):
            col_h = int((1 - e) * (h_err - 1))
            err_img[col_h:, i] = 200
        img_err = Image.fromarray(err_img, mode='L')
        img_err.save('_recon_verify_error.png')
        print(f"  Saved: _recon_verify_error.png (error convergence)")

except ImportError:
    print("  PIL not available, saving as raw numpy instead")
    np.save('_recon_verify_obj_true.npy', true_crop)
    np.save('_recon_verify_obj_recon.npy', obj_crop)
    np.save('_recon_verify_probe_input.npy', probe_in)
    np.save('_recon_verify_probe_recon.npy', probe_recon)
    print("  Saved .npy files")

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Npos: {data['Npos']}")
print(f"  Generate time: {t_gen:.1f}s")
print(f"  Recon time: {t_recon:.1f}s ({50} DM iters)")
print(f"  Error reduction: {errors[0]:.4f} -> {errors[-1]:.4f}")
print(f"  Object amp correlation: {amp_corr:.4f}")
print(f"  Object phase correlation: {ph_corr:.4f}")
print(f"  Probe amp correlation: {probe_amp_corr:.4f}")
if amp_corr > 0.8 and ph_corr > 0.5:
    print("  VERDICT: Reconstruction quality OK")
elif amp_corr > 0.5:
    print("  VERDICT: Reconstruction partially converged (needs more iterations)")
else:
    print("  VERDICT: Reconstruction quality POOR - investigate!")
