"""
Compare K4GSR-Beamline's DM vs K4GSR-PTYCHO's DM using IDENTICAL data.
This isolates whether the engine difference causes divergence.
"""
import sys
import numpy as np
from pathlib import Path

BEAMLINE_PTYCHO = Path(r'c:\Projects\K4GSR-Beamline\ptycho')
PTYCHO_ROOT = Path(r'c:\Projects\K4GSR-PTYCHO')

# --- Use Beamline's synth_ptycho and DataLoader ---
sys.path.insert(0, str(BEAMLINE_PTYCHO))
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader

# Scenario A: 6.2keV, 200nm, asize=128
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = 1000

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_m = lam * z_m / (asize * det_pixel_m)
pixel_nm = pixel_m * 1e9

print(f"Scenario A: E={energy_keV}keV, asize={asize}, pixel={pixel_nm:.2f}nm")

# Build probe
dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9, 'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

# Compute scan area (same formula as compare_recon.py)
step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)
print(f"  probe FWHM={fwhm_px:.1f}px, scan_area={scan_area_um:.3f}um")

# Generate synthetic data
gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
print(f"  Npos={ds.Npos}, overlap={ds.overlap:.2f}")

# Build p dict
data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}
p = dl.build_p_dict(data, {
    'number_iterations': 200, 'use_gpu': True,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1, 'probe_inertia': 0.9,
})

probes_in = p['probes'][:, :, 0, 0] if p['probes'].ndim == 4 else p['probes']
ob_init = [o.squeeze() for o in p['object']] if isinstance(p['object'], list) else [p['object'].squeeze()]

# =====================================================
# Run Beamline's DM (K4GSR-Beamline/ptycho/engines)
# =====================================================
print(f"\n{'='*60}")
print(f"  ENGINE 1: K4GSR-Beamline DM")
print(f"{'='*60}")

# Import Beamline's engine
from engines.gpu.DM import DM as DM_BL

# Deep copy inputs
import copy
ob_bl = [o.copy() for o in ob_init]
pr_bl = probes_in.copy()
p_bl = copy.deepcopy(p)

ob_bl_out, pr_bl_out, err_bl = DM_BL(
    p_bl, ob=ob_bl, probes=pr_bl,
    fmag=p_bl['fmag'], positions=p_bl['positions'], num_iterations=50)

print(f"  BL DM errors: iter1={err_bl[1]:.4e}, iter25={err_bl[25]:.4e}, iter50={err_bl[50]:.4e}")

# =====================================================
# Run PTYCHO's DM (K4GSR-PTYCHO/engines)
# =====================================================
print(f"\n{'='*60}")
print(f"  ENGINE 2: K4GSR-PTYCHO DM")
print(f"{'='*60}")

# We need to import K4GSR-PTYCHO's DM without name collision
# Remove Beamline's engine from sys.modules
mods_to_remove = [k for k in sys.modules if k.startswith('engines')]
for k in mods_to_remove:
    del sys.modules[k]

# Now insert PTYCHO path at the front
sys.path.insert(0, str(PTYCHO_ROOT))

from engines.gpu.DM import DM as DM_PT

# Verify we loaded the right module
import engines.gpu.DM as dm_mod
print(f"  DM module: {dm_mod.__file__}")

# Deep copy same inputs
ob_pt = [o.copy() for o in ob_init]
pr_pt = probes_in.copy()
p_pt = copy.deepcopy(p)

ob_pt_out, pr_pt_out, err_pt = DM_PT(
    p_pt, ob=ob_pt, probes=pr_pt,
    fmag=p_pt['fmag'], positions=p_pt['positions'], num_iterations=50)

# PTYCHO version returns zeros for error, but let's check
non_zero = np.count_nonzero(err_pt)
print(f"  PT DM errors: non_zero_count={non_zero}")
if non_zero > 0:
    print(f"  iter1={err_pt[1]:.4e}, iter25={err_pt[25]:.4e}, iter50={err_pt[50]:.4e}")

# =====================================================
# Compare results: normalized error
# =====================================================
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

ob_bl_sq = ob_bl_out[0].squeeze() if isinstance(ob_bl_out, list) else ob_bl_out.squeeze()
ob_pt_sq = ob_pt_out[0].squeeze() if isinstance(ob_pt_out, list) else ob_pt_out.squeeze()

ne_bl = norm_error(ob_bl_sq, truth)
ne_pt = norm_error(ob_pt_sq, truth)

print(f"\n{'='*60}")
print(f"  COMPARISON: DM 50 iterations (no ML)")
print(f"{'='*60}")
print(f"  Beamline DM:  |obj| range [{np.abs(ob_bl_sq).min():.4f}, {np.abs(ob_bl_sq).max():.4f}], norm_error={ne_bl:.4f}")
print(f"  PTYCHO DM:    |obj| range [{np.abs(ob_pt_sq).min():.4f}, {np.abs(ob_pt_sq).max():.4f}], norm_error={ne_pt:.4f}")

# Check if objects are identical
diff_obj = np.max(np.abs(ob_bl_sq - ob_pt_sq))
print(f"  Max |obj_BL - obj_PT|: {diff_obj:.6e}")

diff_pr = np.max(np.abs(pr_bl_out - pr_pt_out))
print(f"  Max |probe_BL - probe_PT|: {diff_pr:.6e}")

if diff_obj < 1e-4:
    print(f"  >> Engines produce IDENTICAL results")
else:
    print(f"  >> Engines produce DIFFERENT results!")
    print(f"  >> This means the fourier_error computation HAS side effects")

# Save comparison image
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))

    axes[0,0].imshow(np.abs(truth), cmap='jet')
    axes[0,0].set_title('Ground Truth')
    axes[0,1].imshow(np.abs(ob_bl_sq), cmap='jet')
    axes[0,1].set_title(f'Beamline DM50\nerr={ne_bl:.4f}')
    axes[0,2].imshow(np.abs(ob_pt_sq), cmap='jet')
    axes[0,2].set_title(f'PTYCHO DM50\nerr={ne_pt:.4f}')

    axes[1,0].imshow(np.abs(ob_bl_sq - ob_pt_sq), cmap='hot')
    axes[1,0].set_title(f'|BL - PT| diff\nmax={diff_obj:.4e}')

    # Error curves
    axes[1,1].semilogy(err_bl[1:], 'b-', label='BL DM err')
    if non_zero > 0:
        axes[1,1].semilogy(err_pt[1:], 'r--', label='PT DM err')
    axes[1,1].legend()
    axes[1,1].set_title('DM Fourier Error')
    axes[1,1].grid(True, alpha=0.3)

    axes[1,2].text(0.5, 0.5,
                   f"Max obj diff: {diff_obj:.4e}\nMax probe diff: {diff_pr:.4e}\n"
                   f"BL norm_err: {ne_bl:.4f}\nPT norm_err: {ne_pt:.4f}",
                   transform=axes[1,2].transAxes, ha='center', va='center', fontsize=12)
    axes[1,2].set_title('Summary')
    axes[1,2].axis('off')

    fig.suptitle('Engine Comparison: Beamline DM vs PTYCHO DM (50 iter)', fontweight='bold')
    plt.tight_layout()
    out = BEAMLINE_PTYCHO / 'test_compare_engines_result.png'
    fig.savefig(str(out), dpi=150)
    plt.close()
    print(f"\nSaved: {out}")
except Exception as e:
    print(f"Plot error: {e}")
