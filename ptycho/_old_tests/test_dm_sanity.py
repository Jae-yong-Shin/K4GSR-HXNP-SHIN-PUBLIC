"""
Minimal DM sanity test: verify that for noise-free synthetic data,
the initial exit wave already matches fmag perfectly (error=0),
and DM should maintain low error.

This tests the forward model consistency between SyntheticPtycho and DM.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader

# Use simple parameters
asize = 64
energy_keV = 10.0
z_m = 1.0
det_pixel_m = 75e-6
N_photons = 1000

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_m = lam * z_m / (asize * det_pixel_m)
pixel_nm = pixel_m * 1e9

print(f"Sanity test: asize={asize}, pixel={pixel_nm:.2f}nm")

# Build probe (simple gaussian)
dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 100e-9, 'fwhm_v_m': 100e-9, 'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
print(f"  Probe FWHM={fwhm_px:.1f}px")

# Generate synthetic data - small, noiseless
gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=0.5, scan_ly_um=0.5,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2f}")

# =========================================================
# TEST 1: Verify forward model consistency
# =========================================================
print(f"\n{'='*60}")
print(f"  TEST 1: Forward model consistency")
print(f"{'='*60}")

# Reconstruct the exit wave with TRUE object and probe
truth = ds.object_true.squeeze()
probe_scaled = ds.probe  # this is the scaled probe from SyntheticPtycho
positions = ds.positions_clean
fmag = ds.fmag

print(f"  probe |P|^2 sum = {np.sum(np.abs(probe_scaled)**2):.1f}")
print(f"  fmag shape = {fmag.shape}")
print(f"  fmag max = {fmag.max():.2f}, min = {fmag.min():.4f}")

# For each position, compute FFT(probe * obj) and compare to fmag
errors = []
for ii in range(min(10, ds.Npos)):
    pos = positions[ii]
    r, c = int(round(pos[0])), int(round(pos[1]))
    obj_patch = truth[r:r+asize, c:c+asize]

    # SyntheticPtycho forward model: fft2 (no shift, no normalization)
    psi = probe_scaled * obj_patch
    Psi = np.fft.fft2(psi)
    aPsi = np.abs(Psi)

    modF = fmag[:, :, ii]

    # Compare
    rel_err = np.sqrt(np.sum((modF - aPsi)**2) / np.sum(modF**2))
    errors.append(rel_err)
    if ii < 3:
        print(f"  pos {ii}: modF max={modF.max():.2f}, aPsi max={aPsi.max():.2f}, "
              f"rel_err={rel_err:.4e}")

print(f"  Mean initial Fourier error (true obj+probe): {np.mean(errors):.4e}")

# =========================================================
# TEST 2: What does DM see at iteration 0?
# =========================================================
print(f"\n{'='*60}")
print(f"  TEST 2: DM initial state (ones object)")
print(f"{'='*60}")

# DM starts with object_init = ones
obj_init = ds.object_init.squeeze()  # should be ones
print(f"  obj_init: min={np.abs(obj_init).min():.4f}, max={np.abs(obj_init).max():.4f}")

# After probe amplitude correction, what's the initial Fourier error?
errors_init = []
for ii in range(min(10, ds.Npos)):
    pos = positions[ii]
    r, c = int(round(pos[0])), int(round(pos[1]))
    obj_patch = obj_init[r:r+asize, c:c+asize]

    psi = probe_scaled * obj_patch
    Psi = np.fft.fft2(psi)
    aPsi = np.abs(Psi)

    modF = fmag[:, :, ii]
    rel_err = np.sqrt(np.sum((modF - aPsi)**2) / np.sum(modF**2))
    errors_init.append(rel_err)

print(f"  Mean initial Fourier error (ones obj): {np.mean(errors_init):.4e}")
print(f"  (This is how far the initial guess is from the data)")

# =========================================================
# TEST 3: Run DM 20 iterations and track error carefully
# =========================================================
print(f"\n{'='*60}")
print(f"  TEST 3: DM 20 iterations")
print(f"{'='*60}")

data = {
    'fmag': fmag, 'positions': positions,
    'probes': probe_scaled, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 20, 'use_gpu': True,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

from engines.gpu.DM import DM as DM_GPU

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

ob_dm, pr_dm, err_dm = DM_GPU(
    p, ob=ob, probes=probes_in,
    fmag=p['fmag'], positions=p['positions'], num_iterations=20)

print(f"\n  DM Fourier error history:")
for i in range(1, 21):
    status = "DIVERGING" if i > 1 and err_dm[i] > err_dm[i-1] else "OK"
    print(f"    iter {i:3d}: {err_dm[i]:.6e}  {status}")

# =========================================================
# TEST 4: Check DM with pfft_relaxation=0 (full constraint)
# =========================================================
print(f"\n{'='*60}")
print(f"  TEST 4: DM with pfft_relaxation=0 (full modulus constraint)")
print(f"{'='*60}")

p2 = dl.build_p_dict(data, {
    'number_iterations': 20, 'use_gpu': True,
    'pfft_relaxation': 0.0,  # FULL constraint
    'probe_change_start': 1,
    'object_change_start': 1,
    'probe_inertia': 0.9,
})

probes_in2 = p2['probes'][:, :, 0, 0] if p2['probes'].ndim == 4 else p2['probes']
ob2 = [o.squeeze() for o in p2['object']] if isinstance(p2['object'], list) else [p2['object'].squeeze()]

ob_dm2, pr_dm2, err_dm2 = DM_GPU(
    p2, ob=ob2, probes=probes_in2,
    fmag=p2['fmag'], positions=p2['positions'], num_iterations=20)

print(f"\n  DM (relaxation=0) Fourier error:")
for i in range(1, 21):
    status = "DIVERGING" if i > 1 and err_dm2[i] > err_dm2[i-1] else "OK"
    print(f"    iter {i:3d}: {err_dm2[i]:.6e}  {status}")

# =========================================================
# TEST 5: Check if obj/probe update causes the divergence
# (Run DM with NO probe/object update to see pure Fourier error)
# =========================================================
print(f"\n{'='*60}")
print(f"  TEST 5: DM with NO probe/obj update (probe_change_start=9999)")
print(f"{'='*60}")

p3 = dl.build_p_dict(data, {
    'number_iterations': 20, 'use_gpu': True,
    'pfft_relaxation': 0.05,
    'probe_change_start': 9999,  # never update
    'object_change_start': 9999, # never update
    'probe_inertia': 0.9,
})

probes_in3 = p3['probes'][:, :, 0, 0] if p3['probes'].ndim == 4 else p3['probes']
ob3 = [o.squeeze() for o in p3['object']] if isinstance(p3['object'], list) else [p3['object'].squeeze()]

ob_dm3, pr_dm3, err_dm3 = DM_GPU(
    p3, ob=ob3, probes=probes_in3,
    fmag=p3['fmag'], positions=p3['positions'], num_iterations=20)

print(f"\n  DM (no update) Fourier error:")
for i in range(1, 21):
    status = "DIVERGING" if i > 1 and err_dm3[i] > err_dm3[i-1] else "OK"
    print(f"    iter {i:3d}: {err_dm3[i]:.6e}  {status}")
