"""
Test if the object update delta is the cause of DM divergence.
MATLAB uses delta = MAX_ILLUM * 1e-4 (adaptive), Python uses 1e-4 (fixed).
"""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader

# Scenario A
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9, 'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)
step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=1000,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)

truth = ds.object_true.squeeze()

def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))

# First: estimate what MAX_ILLUM should be
# MAX_ILLUM = max(sum_over_positions(|probe|^2)) at each pixel
print(f"Scenario A: Npos={ds.Npos}, probe |P|^2 max = {np.max(np.abs(ds.probe)**2):.2f}")
# Rough estimate: MAX_ILLUM ~ Npos * max(|probe|^2) for center pixel
# But actually it depends on overlap
# Let's compute it properly
positions = ds.positions_clean
Np_p = [asize, asize]
Np_o = [ds.object_init.squeeze().shape[0], ds.object_init.squeeze().shape[1]]

aprobe = np.abs(ds.probe)**2
illum = np.zeros(Np_o, dtype=np.float32)
for ii in range(ds.Npos):
    pos = positions[ii]
    r, c = int(round(pos[0])), int(round(pos[1]))
    illum[r:r+Np_p[0], c:c+Np_p[1]] += aprobe

MAX_ILLUM = float(illum.max())
print(f"MAX_ILLUM = {MAX_ILLUM:.2f}")
print(f"MATLAB delta = MAX_ILLUM * 1e-4 = {MAX_ILLUM * 1e-4:.4f}")
print(f"Python delta = 1e-4 = 0.0001")
print(f"Ratio: {MAX_ILLUM * 1e-4 / 1e-4:.0f}x")

# Now patch the DM engine and test different delta values
from engines.gpu import DM as dm_module
import engines.gpu.DM as dm_file

# Save original
_orig_update_object = dm_file._update_object

def make_patched_update(delta_val):
    def _patched_update_object(obj, obj_update, obj_illum, inertia):
        obj = inertia * obj + (1 - inertia) * (obj_update / (obj_illum + delta_val))
        return obj
    return _patched_update_object

results = []
for delta_mult in [1e-4, 1e-2, 1.0, MAX_ILLUM * 1e-4, MAX_ILLUM * 1e-3]:
    # Monkey-patch
    dm_file._update_object = make_patched_update(delta_mult)

    data = {
        'fmag': ds.fmag, 'positions': ds.positions_clean,
        'probes': ds.probe, 'object_init': ds.object_init,
        'asize': (asize, asize), 'Npos': ds.Npos,
    }
    p = dl.build_p_dict(data, {
        'number_iterations': 50, 'use_gpu': True,
        'pfft_relaxation': 0.05, 'probe_change_start': 1,
        'object_change_start': 1, 'probe_inertia': 0.9,
    })

    probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
    ob = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

    ob_dm, pr_dm, err_dm = dm_file.DM(
        p, ob=ob, probes=probes_in,
        fmag=p['fmag'], positions=p['positions'], num_iterations=50)

    ob_sq = ob_dm[0].squeeze()
    ne = norm_error(ob_sq, truth)
    grade = "EXCELLENT" if ne < 0.15 else "GOOD" if ne < 0.30 else "MARGINAL" if ne < 0.50 else "POOR"
    results.append({'delta': delta_mult, 'norm_error': ne, 'amp_max': np.abs(ob_sq).max(),
                    'fourier_err': err_dm[50], 'grade': grade})
    print(f"  delta={delta_mult:.4e}: norm_err={ne:.4f}, |obj| max={np.abs(ob_sq).max():.4f}, fourier_err={err_dm[50]:.4e}, {grade}")

# Restore original
dm_file._update_object = _orig_update_object

print(f"\n{'='*60}")
print(f"  DELTA COMPARISON (DM 50 iter)")
print(f"{'='*60}")
print(f"  {'Delta':>12s}  {'Norm Error':>12s}  {'Fourier Err':>12s}  {'|obj| max':>10s}  {'Grade':>10s}")
for r in results:
    print(f"  {r['delta']:12.4e}  {r['norm_error']:12.4f}  {r['fourier_err']:12.4e}  {r['amp_max']:10.4f}  {r['grade']:>10s}")
