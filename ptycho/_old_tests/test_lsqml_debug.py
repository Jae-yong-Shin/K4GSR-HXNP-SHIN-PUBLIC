"""
Debug LSQML beta_object = 0 issue.
Diagnose why the 2x2 LSQ system gives zero object step.
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader

# Generate data
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

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 1, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})

# Manually debug the LSQ step for position 0
from engines.gpu.shared import fwd_fourier_proj, back_fourier_proj, modulus_constraint, get_reciprocal_model

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob_init = p['object'][0].squeeze() if isinstance(p['object'], list) else p['object'].squeeze()

Np_p = [probes_in.shape[0], probes_in.shape[1]]
mode = {'distances': [np.inf]}

print("=" * 60)
print("  LSQML beta debug: position 0")
print("=" * 60)

pos = p['positions'][0]
r, c = int(round(float(pos[0]))), int(round(float(pos[1])))
obj_view = ob_init[r:r+Np_p[0], c:c+Np_p[1]]
modF = p['fmag'][:, :, 0]

print(f"  obj_view: shape={obj_view.shape}, |O| range=[{np.abs(obj_view).min():.4f}, {np.abs(obj_view).max():.4f}]")
print(f"  probe: |P| range=[{np.abs(probes_in).min():.4f}, {np.abs(probes_in).max():.4f}]")
print(f"  modF: range=[{modF.min():.1f}, {modF.max():.1f}]")

# Forward model
psi = obj_view * probes_in
Psi = fwd_fourier_proj(psi, mode)
aPsi = get_reciprocal_model([Psi])

print(f"\n  |psi| max={np.abs(psi).max():.4f}")
print(f"  |Psi| max={np.abs(Psi).max():.1f}")
print(f"  aPsi range=[{aPsi.min():.1f}, {aPsi.max():.1f}]")
print(f"  modF-aPsi residual: max={np.abs(modF - aPsi).max():.4f}, mean={np.abs(modF - aPsi).mean():.4f}")

# Modulus constraint
Psi_c = modulus_constraint(modF, aPsi, [Psi], mask=None, relaxation=0.05)
chi = Psi_c[0] - Psi
chi_rs = back_fourier_proj(chi, mode)

print(f"\n  |chi| max (Fourier)={np.abs(chi).max():.6f}")
print(f"  |chi_rs| max (real-space)={np.abs(chi_rs).max():.6f}")

# Gradients
dO = chi_rs * np.conj(probes_in)
dP = chi_rs * np.conj(obj_view)

print(f"\n  |dO| max={np.abs(dO).max():.6f}")
print(f"  |dP| max={np.abs(dP).max():.6f}")

# LSQ step debug
dOP = dO * probes_in.astype(np.complex128)   # object-direction exit-wave perturbation
dPO = dP * obj_view.astype(np.complex128)    # probe-direction exit-wave perturbation

AA1 = float(np.sum(np.abs(dOP)**2))   # object self
AA4 = float(np.sum(np.abs(dPO)**2))   # probe self
AA2 = complex(np.sum(np.conj(dOP) * dPO))  # cross-term

chi_64 = chi_rs.astype(np.complex128)
Atb1 = complex(np.sum(np.conj(dOP) * chi_64))
Atb2 = complex(np.sum(np.conj(dPO) * chi_64))

lam_reg = 0.5

print(f"\n  LSQ 2x2 system:")
print(f"    AA1 (obj self)  = {AA1:.6e}")
print(f"    AA4 (probe self)= {AA4:.6e}")
print(f"    AA2 (cross)     = {AA2}")
print(f"    |AA2|           = {abs(AA2):.6e}")
print(f"    Atb1 (obj RHS)  = {Atb1}")
print(f"    Atb2 (probe RHS)= {Atb2}")
print(f"    lambda          = {lam_reg}")

A = np.array([[AA1 + lam_reg, AA2],
              [np.conj(AA2), AA4 + lam_reg]], dtype=np.complex128)
b = np.array([Atb1, Atb2], dtype=np.complex128)

print(f"\n  A matrix:")
print(f"    [{AA1+lam_reg:.4e},  {AA2:.4e}]")
print(f"    [{np.conj(AA2):.4e},  {AA4+lam_reg:.4e}]")
print(f"  b vector: [{Atb1:.4e}, {Atb2:.4e}]")

x = np.linalg.solve(A, b)
print(f"\n  Raw solution: beta_object={x[0]}, beta_probe={x[1]}")
print(f"    Re(x[0])={float(np.real(x[0])):.6e}, Re(x[1])={float(np.real(x[1])):.6e}")

# Clipped
MAX_BETA = 1.0
beta_LSQ = 0.9
beta_object = min(MAX_BETA, max(0.0, float(np.real(x[0])))) * beta_LSQ
beta_probe = min(MAX_BETA, max(0.0, float(np.real(x[1])))) * beta_LSQ
print(f"\n  Clipped: beta_object={beta_object:.6f}, beta_probe={beta_probe:.6f}")

# Check: what if we DON'T use the coupled system?
# Decoupled (independent) steps:
beta_object_dec = max(0.0, float(np.real(Atb1)) / (AA1 + lam_reg)) * beta_LSQ
beta_probe_dec = max(0.0, float(np.real(Atb2)) / (AA4 + lam_reg)) * beta_LSQ
print(f"\n  Decoupled: beta_object={beta_object_dec:.6f}, beta_probe={beta_probe_dec:.6f}")

# Key insight: is the cross-term AA2 too large?
print(f"\n  Coupling ratio: |AA2|/sqrt(AA1*AA4) = {abs(AA2)/np.sqrt(AA1*AA4):.6f}")
print(f"  AA1/AA4 ratio = {AA1/AA4:.4f}")
print(f"  This means obj perturbation is {AA1/AA4:.1f}x larger than probe perturbation")
print(f"  → probe update dominates, absorbing the chi_rs signal")
print(f"  → coupled system pushes object beta to ~0")

# What if we use a simpler approach: fixed beta_object?
print(f"\n  ===== Diagnostic: what would update look like with fixed beta_object=1.0? =====")
obj_update_at_pos = dO * 1.0
print(f"  |obj_update| max = {np.abs(obj_update_at_pos).max():.6e}")
print(f"  |obj_update| / |obj_view| ratio = {np.abs(obj_update_at_pos).max() / np.abs(obj_view).max():.6e}")
