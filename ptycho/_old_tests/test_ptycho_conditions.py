"""
Ptychography validity condition checker.

Checks whether the synthetic data satisfies fundamental ptychography requirements:
  1. Oversampling ratio >= 2 (Nyquist in diffraction plane)
  2. Probe FWHM >> 1 pixel (probe well-resolved)
  3. Overlap >= 60% (sufficient redundancy for phase retrieval)
  4. Number of positions >= ~50 (enough constraints)
"""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from server.data_loader import DataLoader
from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm

def check_conditions(label, asize, energy_keV, z_m, det_pixel_m, fwhm_nm,
                     f_m, overlap=0.75, scan_step_um=None,
                     scan_lx_um=3.0, scan_ly_um=3.0, N_photons=1000):
    """Check ptychography conditions for given parameters."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    # ---- 1. Pixel size (reconstruction real-space resolution) ----
    lambda_m = 1239.842e-9 / (energy_keV * 1e3)
    dx_m = lambda_m * z_m / (asize * det_pixel_m)
    dx_nm = dx_m * 1e9
    print(f"\n[Geometry]")
    print(f"  wavelength   = {lambda_m*1e10:.4f} A ({lambda_m*1e9:.4f} nm)")
    print(f"  dx (pixel)   = {dx_nm:.2f} nm")
    print(f"  field of view = {asize * dx_nm:.0f} nm = {asize * dx_nm / 1000:.2f} um")

    # ---- 2. Generate probe ----
    dl = DataLoader()
    beam_params = {
        'fwhm_h_m': fwhm_nm * 1e-9,
        'fwhm_v_m': fwhm_nm * 1e-9,
        'focal_length_m': f_m,
        'defocus_m': 0.0,
    }
    probe = dl._build_fresnel_probe(beam_params, asize, energy_keV, z_m, det_pixel_m)

    # Measure probe extent
    amp = np.abs(probe)
    half_max = amp.max() * 0.5
    n_above = (amp >= half_max).sum()
    fwhm_px = estimate_probe_fwhm(probe)
    fwhm_real_nm = fwhm_px * dx_nm

    # Also measure along H and V axes
    center = asize // 2
    h_profile = amp[center, :]
    v_profile = amp[:, center]
    h_fwhm_px = (h_profile >= h_profile.max() * 0.5).sum()
    v_fwhm_px = (v_profile >= v_profile.max() * 0.5).sum()

    print(f"\n[Probe]")
    print(f"  Requested FWHM = {fwhm_nm:.0f} nm")
    print(f"  Measured FWHM  = {fwhm_px:.1f} px ({fwhm_real_nm:.1f} nm)")
    print(f"  H FWHM = {h_fwhm_px} px ({h_fwhm_px * dx_nm:.1f} nm)")
    print(f"  V FWHM = {v_fwhm_px} px ({v_fwhm_px * dx_nm:.1f} nm)")
    print(f"  Probe extent (>{0.5}*max): {n_above} px")
    print(f"  sum|P|^2 = {float((amp**2).sum()):.1f}")

    # ---- 3. Oversampling ratio ----
    # Oversampling = probe_extent / 2 (Nyquist)
    # Or equivalently: D/asize >= 2 where D = object illuminated width / dx
    # For ptychography: we need the probe to be well-sampled
    oversampling = fwhm_px / 2.0
    print(f"\n[Oversampling]")
    print(f"  ratio = probe_FWHM / 2 = {fwhm_px:.1f} / 2 = {oversampling:.2f}")
    if oversampling >= 2.0:
        print(f"  >> OK (>= 2.0)")
    elif oversampling >= 1.0:
        print(f"  ** MARGINAL (1.0 ~ 2.0) - may reconstruct but quality limited")
    else:
        print(f"  !! FAIL (< 1.0) - probe under-sampled, reconstruction will fail")

    # ---- 4. Generate scan positions and check overlap ----
    gen = SyntheticPtycho.from_dataset(
        asize=asize, energy_keV=energy_keV, z_m=z_m,
        det_pixel_size_m=det_pixel_m, N_photons=N_photons,
        scan_step_um=scan_step_um, overlap=overlap,
        scan_lx_um=scan_lx_um, scan_ly_um=scan_ly_um,
        probe=probe)

    # Get positions without generating fmag (just to check)
    obj_h, obj_w = gen.object_true.shape[:2]
    ps = gen.pixel_size_m
    if gen._scan_ly_um is not None and ps is not None:
        scan_h = min(gen._scan_ly_um * 1e-6 / ps, float(obj_h - gen.Ny))
    else:
        scan_h = float(obj_h - gen.Ny)
    if gen._scan_lx_um is not None and ps is not None:
        scan_w = min(gen._scan_lx_um * 1e-6 / ps, float(obj_w - gen.Nx))
    else:
        scan_w = float(obj_w - gen.Nx)

    positions = gen._fermat_positions((scan_h, scan_w))
    Npos = len(positions)

    # Average nearest-neighbour distance
    if Npos > 1:
        nn_dists = []
        for i in range(Npos):
            d = np.sqrt(((positions - positions[i]) ** 2).sum(axis=1))
            d[i] = np.inf
            nn_dists.append(float(d.min()))
        avg_step_px = float(np.mean(nn_dists))
        actual_overlap = 1.0 - avg_step_px / max(fwhm_px, 1e-6)
    else:
        avg_step_px = 0
        actual_overlap = 0

    avg_step_nm = avg_step_px * dx_nm

    print(f"\n[Scan]")
    print(f"  Scan range   = {scan_lx_um:.1f} x {scan_ly_um:.1f} um")
    print(f"  Scan range   = {scan_w:.0f} x {scan_h:.0f} px")
    print(f"  N positions  = {Npos}")
    print(f"  Avg step     = {avg_step_px:.2f} px ({avg_step_nm:.1f} nm)")
    print(f"  Actual overlap = {actual_overlap:.1%}")

    if actual_overlap >= 0.70:
        print(f"  >> OK (>= 70%)")
    elif actual_overlap >= 0.50:
        print(f"  ** MARGINAL (50-70%) - may work but not ideal")
    else:
        print(f"  !! FAIL (< 50%) - insufficient overlap for phase retrieval")

    # ---- 5. Summary ----
    print(f"\n[Summary]")
    issues = []
    if oversampling < 1.0:
        issues.append(f"FAIL: oversampling={oversampling:.2f} < 1.0")
    elif oversampling < 2.0:
        issues.append(f"WARN: oversampling={oversampling:.2f} < 2.0")
    if fwhm_px < 5:
        issues.append(f"FAIL: probe FWHM={fwhm_px:.1f}px < 5px (too narrow)")
    if actual_overlap < 0.50:
        issues.append(f"FAIL: overlap={actual_overlap:.1%} < 50%")
    if Npos < 50:
        issues.append(f"WARN: only {Npos} positions (ideally >= 50)")

    if not issues:
        print(f"  All conditions PASS")
    else:
        for iss in issues:
            print(f"  {iss}")

    return {
        'dx_nm': dx_nm, 'fwhm_px': fwhm_px, 'oversampling': oversampling,
        'Npos': Npos, 'overlap': actual_overlap, 'avg_step_px': avg_step_px,
        'issues': issues,
    }


# ============================================================================
#  Scenario A: Known-good params (compare_recon.py verified: error=0.061)
# ============================================================================
res_a = check_conditions(
    label="A: Known-good (6.2keV, 200nm, overlap=0.75)",
    asize=128, energy_keV=6.2, z_m=5.0, det_pixel_m=75e-6,
    fwhm_nm=200.0, f_m=0.3, overlap=0.75,
    scan_lx_um=3.0, scan_ly_um=3.0, N_photons=1000,
)

# ============================================================================
#  Scenario B: JS-realistic (10keV, 50nm beam, asize=256, z=1m)
# ============================================================================
res_b = check_conditions(
    label="B: JS-realistic (10keV, 50nm, asize=256, z=1m)",
    asize=256, energy_keV=10.0, z_m=1.0, det_pixel_m=75e-6,
    fwhm_nm=50.0, f_m=0.205, overlap=0.75,
    scan_lx_um=0.3, scan_ly_um=0.3, N_photons=1000,
)

# ============================================================================
#  Scenario C: What if we adjust asize/z to get proper oversampling?
#  For 50nm beam: need dx ~ 10nm/px -> asize*det_pixel = lambda*z/dx
#  lambda(10keV) = 0.124nm, dx=10nm -> asize*75e-6 = 0.124e-9 * z / 10e-9
#  For asize=128: z = 128*75e-6 * 10e-9 / 0.124e-9 = 0.774 m
# ============================================================================
res_c = check_conditions(
    label="C: Adjusted (10keV, 50nm, asize=128, z=0.8m, optimized)",
    asize=128, energy_keV=10.0, z_m=0.8, det_pixel_m=75e-6,
    fwhm_nm=50.0, f_m=0.205, overlap=0.75,
    scan_lx_um=0.3, scan_ly_um=0.3, N_photons=1000,
)

print(f"\n\n{'='*70}")
print(f"  COMPARISON")
print(f"{'='*70}")
print(f"{'Scenario':<40} {'dx(nm)':>8} {'FWHM(px)':>9} {'OS':>6} {'Npos':>6} {'Overlap':>8}")
print(f"{'-'*40} {'-'*8} {'-'*9} {'-'*6} {'-'*6} {'-'*8}")
for label, r in [('A: 6.2keV/200nm/z=5m', res_a),
                  ('B: 10keV/50nm/z=1m', res_b),
                  ('C: 10keV/50nm/z=0.8m', res_c)]:
    print(f"{label:<40} {r['dx_nm']:>8.1f} {r['fwhm_px']:>9.1f} {r['oversampling']:>6.2f} {r['Npos']:>6} {r['overlap']:>7.1%}")
