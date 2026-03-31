"""
Shadow4 Geometric-Only vs Hybrid FWHM comparison for 10keV SSA50.
=================================================================
Measures beam FWHM and throughput at every intermediate position:
  Source -> M1 -> DCM -> M2 -> SSA -> KB-V -> KB-H -> Sample

Two parallel paths after SSA:
  (A) Geometric-only: pure ray tracing, no hybrid wave-optics
  (B) Hybrid: SSA Fraunhofer + KB-V/KB-H mirror diffraction

Goal: determine if MC geometric beam (34.4nm H, 29.8nm V) matches
      Shadow4 geometric beam (i.e. without diffraction broadening).

Usage:
    conda run -n oasys_env python _s4_geometric_only.py
"""

import os, sys, time
import numpy as np
from math import sqrt, pi, exp, erf

# ---- Shadow4 imports ----
from shadow4.sources.source_geometrical.source_gaussian import SourceGaussian
from shadow4.beam.s4_beam import S4Beam
from shadow4.beamline.optical_elements.mirrors.s4_sphere_mirror import (
    S4SphereMirror, S4SphereMirrorElement)
from shadow4.beamline.optical_elements.mirrors.s4_ellipsoid_mirror import (
    S4EllipsoidMirror, S4EllipsoidMirrorElement)
from shadow4.beamline.optical_elements.crystals.s4_plane_crystal import (
    S4PlaneCrystal, S4PlaneCrystalElement)
from shadow4.beamline.optical_elements.absorbers.s4_screen import (
    S4Screen, S4ScreenElement)
from shadow4.beamline.s4_optical_element_decorators import SurfaceCalculation

from syned.beamline.element_coordinates import ElementCoordinates
from syned.beamline.shape import Rectangle, Direction

# ---- Hybrid imports ----
try:
    from shadow4_hybrid.s4_hybrid_screen import (
        HybridCalculationType, HybridDiffractionPlane,
        HybridPropagationType, HybridInputParameters,
        S4HybridScreen, S4HybridScreenElement,
        S4HybridBeam, S4HybridOE,
    )
    _HYBRID_PKG = 'shadow4_hybrid'
except ImportError:
    from shadow4_advanced.hybrid.s4_hybrid_screen import (
        S4HybridScreen, S4HybridScreenElement,
        S4HybridBeam, S4HybridOE,
    )
    from hybrid_methods.coherence.hybrid_screen import (
        HybridCalculationType, HybridDiffractionPlane,
        HybridPropagationType, HybridInputParameters,
    )
    _HYBRID_PKG = 'shadow4_advanced'

try:
    if _HYBRID_PKG == 'shadow4_hybrid':
        from shadow4_hybrid.s4_hybrid_screen import HybridListener
    else:
        from hybrid_methods.coherence.hybrid_screen import HybridListener
except ImportError:
    class HybridListener:
        def status_message(self, message): pass
        def set_progress_value(self, value): pass
        def warning_message(self, message=""): pass
        def error_message(self, message=""): pass


class _QuietHybridListener(HybridListener):
    def status_message(self, message): pass
    def set_progress_value(self, value): pass
    def warning_message(self, message=""):
        if "abort" in message.lower() or "unaltered" in message.lower():
            print(f"  [HYBRID WARN] {message.strip()}")
    def error_message(self, message=""):
        print(f"  [HYBRID ERROR] {message}")


# ---- Monkey-patch for shadow4 v0.1.79 compat ----
def _patch_mirror_classes():
    try:
        from shadow4.beamline.optical_elements.mirrors import s4_mirror
        basecls = s4_mirror.S4MirrorElement
        if hasattr(basecls, '_apply_mirror_reflection_and_reflectivity') and \
           not hasattr(basecls, 'apply_mirror_reflection_and_reflectivity'):
            basecls.apply_mirror_reflection_and_reflectivity = basecls._apply_mirror_reflection_and_reflectivity
        oe_cls = s4_mirror.S4Mirror
        if hasattr(oe_cls, '_apply_mirror_reflection') and \
           not hasattr(oe_cls, 'apply_mirror_reflection'):
            oe_cls.apply_mirror_reflection = oe_cls._apply_mirror_reflection
    except Exception:
        pass
_patch_mirror_classes()


def _extract_hybrid_beam(trace_result):
    """Extract S4Beam from hybrid trace_beam() result."""
    if isinstance(trace_result, tuple):
        first = trace_result[0]
    else:
        first = trace_result
    if hasattr(first, 'get_number_of_rays'):
        return first
    if hasattr(first, 'far_field_beam') and first.far_field_beam is not None:
        fb = first.far_field_beam
        if hasattr(fb, 'wrapped_beam'):
            return fb.wrapped_beam
        return fb
    return first


# ==============================================================
#  K4GSR Ring & IVU24 Parameters
# ==============================================================
E_RING   = 4.0
I_RING   = 0.4
EMIT_X   = 62e-12
EMIT_Y   = 6.2e-12
BETA_X   = 6.334
BETA_Y   = 2.841
E_SPREAD = 1.20e-3
HC       = 12.3984

LAMBDA_U  = 0.024
N_PERIODS = 123
L_UND     = N_PERIODS * LAMBDA_U

SIG_EX  = sqrt(EMIT_X * BETA_X)
SIG_EXP = sqrt(EMIT_X / BETA_X)
SIG_EY  = sqrt(EMIT_Y * BETA_Y)
SIG_EYP = sqrt(EMIT_Y / BETA_Y)

POS = {
    'ivu':    0.0,
    'fmask':  17.0,
    'mmask':  22.0,
    'wbslit': 27.8,
    'atten':  28.3,
    'm1':     29.0,
    'dcm':    30.4,
    'm2':     32.0,
    'xbpm1':  31.2,
    'xbpm2':  57.0,
    'ssa':    58.0,
    'kbv':    149.69,
    'kbh':    149.90,
    'sample': 150.0,
}

M1_P = 30.4;  M1_Q = 27.6
M2_P = 33.0;  M2_Q = 25.0

KB_V_LEN = 0.300;  KB_H_LEN = 0.100;  KB_WID = 0.030
M1_LEN = 0.600;  M1_WID = 0.060
M2_LEN = 0.400;  M2_WID = 0.040

THETA_GRAZ = 0.003
ANGLE_RAD  = np.pi / 2 - THETA_GRAZ


def photon_src(E_keV, harmonic=1):
    """Replicate JS photonSrc(E) -- convolved source sizes."""
    lm = HC / E_keV * 1e-10
    n = harmonic
    srp = 0.69 * sqrt(lm / (2 * n * L_UND))
    sr  = 2.740 / (4 * pi) * sqrt(2 * lm * L_UND / n)
    se = 2 * pi * n * N_PERIODS * E_SPREAD
    Qa_v = sqrt(max(0, 2*se*se - 1 + exp(-2*se*se) +
                     sqrt(2*pi) * se * erf(sqrt(2)*se)))
    Qa = max(1.0, Qa_v)
    se4 = se / 4
    Qa4 = sqrt(max(0, 2*se4*se4 - 1 + exp(-2*se4*se4) +
                     sqrt(2*pi) * se4 * erf(sqrt(2)*se4)))
    Qs = max(1.0, Qa4**(2.0/3.0)) if Qa4 > 0.01 else 1.0
    rpc = srp * Qa
    rc  = sr * Qs
    Sx  = sqrt(SIG_EX**2  + rc**2)
    Sy  = sqrt(SIG_EY**2  + rc**2)
    Sxp = sqrt(SIG_EXP**2 + rpc**2)
    Syp = sqrt(SIG_EYP**2 + rpc**2)
    return Sx, Sy, Sxp, Syp


def _swap_xz(beam):
    """Swap X<->Z and X'<->Z' columns (for sagittal KB-H trick)."""
    rays = beam.get_rays().copy()
    rays[:, [0, 2]] = rays[:, [2, 0]]
    rays[:, [3, 5]] = rays[:, [5, 3]]
    return S4Beam(N=rays.shape[0], array=rays)


def _beam_stats(beam, label=""):
    """Compute beam statistics from good rays."""
    good = beam.get_rays()
    good = good[good[:, 9] >= 0]
    n = len(good)
    if n < 10:
        return {'label': label, 'n': n, 'sig_h_um': 0, 'sig_v_um': 0,
                'fwhm_h_nm': 0, 'fwhm_v_nm': 0}

    x = good[:, 0]  # horizontal
    z = good[:, 2]  # vertical
    w = good[:, 22] if good.shape[1] > 22 else np.ones(n)  # intensity weights

    mean_x = np.average(x, weights=w)
    mean_z = np.average(z, weights=w)
    sig_h = sqrt(np.average((x - mean_x)**2, weights=w))
    sig_v = sqrt(np.average((z - mean_z)**2, weights=w))

    fwhm_h = _hist_fwhm(x, w)
    fwhm_v = _hist_fwhm(z, w)

    return {
        'label': label, 'n': n,
        'sig_h_um': sig_h * 1e6,
        'sig_v_um': sig_v * 1e6,
        'fwhm_h_nm': fwhm_h * 1e9,
        'fwhm_v_nm': fwhm_v * 1e9,
    }


def _hist_fwhm(vals, weights=None, nbins=401):
    """Compute FWHM from weighted histogram with linear interpolation."""
    if weights is None:
        weights = np.ones_like(vals)

    # Tight FOV: center +/- 5*sigma, minimum 80nm
    mean = np.average(vals, weights=weights)
    sig = sqrt(np.average((vals - mean)**2, weights=weights))
    fov = max(sig * 10, 80e-9)

    edges = np.linspace(mean - fov, mean + fov, nbins + 1)
    hist, _ = np.histogram(vals, bins=edges, weights=weights)
    centers = (edges[:-1] + edges[1:]) / 2.0

    mx = hist.max()
    if mx <= 0:
        return 0.0
    hm = mx * 0.5

    # Find left crossing
    x0 = None
    for i in range(1, nbins):
        if hist[i-1] < hm <= hist[i]:
            frac = (hm - hist[i-1]) / (hist[i] - hist[i-1] + 1e-30)
            x0 = centers[i-1] + frac * (centers[i] - centers[i-1])
            break

    # Find right crossing
    x1 = None
    for i in range(1, nbins):
        if hist[i-1] >= hm > hist[i]:
            frac = (hm - hist[i-1]) / (hist[i] - hist[i-1] - 1e-30)
            x1 = centers[i-1] + frac * (centers[i] - centers[i-1])

    if x0 is None or x1 is None:
        return 0.0
    return abs(x1 - x0)


def run_beamline(E_keV, ssa_um, nrays, seed, hybrid=False, verbose=True):
    """
    Run full beamline, returning beam stats at each stage.
    If hybrid=True, applies SSA/KB diffraction corrections.
    Returns ordered dict of (stage_name -> beam_stats_dict).
    """
    E_eV = E_keV * 1000.0
    ssa_half = ssa_um * 0.5e-6

    Sx, Sy, Sxp, Syp = photon_src(E_keV, harmonic=3)

    if verbose:
        mode = "HYBRID" if hybrid else "GEOMETRIC"
        print(f"\n[{mode}] E={E_keV}keV, SSA={ssa_um}um, nrays={nrays}")
        print(f"  Source: Sx={Sx*1e6:.2f}um, Sy={Sy*1e6:.2f}um, "
              f"Sxp={Sxp*1e6:.2f}urad, Syp={Syp*1e6:.2f}urad")

    results = {}

    # 1. SOURCE
    src = SourceGaussian(nrays=nrays, seed=seed,
                         sigmaX=Sx, sigmaY=0.0, sigmaZ=Sy,
                         sigmaXprime=Sxp, sigmaZprime=Syp)
    beam = S4Beam()
    beam.generate_source(src)
    beam.set_photon_energy_eV(E_eV)
    results['1_source'] = _beam_stats(beam, 'Source')

    # 2. M1: Spherical, sagittal H-focus
    p_m1 = POS['m1']
    q_m1 = POS['dcm'] - POS['m1']
    m1_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M1",
            boundary_shape=Rectangle(
                x_left=-M1_WID/2, x_right=M1_WID/2,
                y_bottom=-M1_LEN/2, y_top=M1_LEN/2),
            is_cylinder=1, cylinder_direction=Direction.SAGITTAL,
            surface_calculation=SurfaceCalculation.INTERNAL, convexity=1,
            p_focus=M1_P, q_focus=M1_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0),
        coordinates=ElementCoordinates(p=p_m1, q=q_m1, angle_radial=ANGLE_RAD),
        input_beam=beam)
    beam, _ = m1_el.trace_beam()
    results['2_after_M1'] = _beam_stats(beam, 'After M1')

    # 3. DCM: Si(111) double crystal
    dcm1_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM_c1", boundary_shape=None,
            material="Si", miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0, is_thick=0, thickness=0.010,
            f_central=True, f_phot_cent=0, phot_cent=E_eV,
            file_refl="", f_bragg_a=False, f_ext=0),
        coordinates=ElementCoordinates(
            p=0.0, q=0.020,
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0),
        input_beam=beam)
    beam, _ = dcm1_el.trace_beam()

    dcm2_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM_c2", boundary_shape=None,
            material="Si", miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0, is_thick=0, thickness=0.010,
            f_central=True, f_phot_cent=0, phot_cent=E_eV,
            file_refl="", f_bragg_a=False, f_ext=0),
        coordinates=ElementCoordinates(
            p=0.020, q=POS['m2'] - POS['dcm'],
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0),
        input_beam=beam)
    beam, _ = dcm2_el.trace_beam()
    results['3_after_DCM'] = _beam_stats(beam, 'After DCM')

    # 4. M2: Spherical, tangential V-focus
    q_m2 = POS['ssa'] - POS['m2']
    m2_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M2",
            boundary_shape=Rectangle(
                x_left=-M2_WID/2, x_right=M2_WID/2,
                y_bottom=-M2_LEN/2, y_top=M2_LEN/2),
            is_cylinder=1, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL, convexity=1,
            p_focus=M2_P, q_focus=M2_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0),
        coordinates=ElementCoordinates(p=0.0, q=q_m2, angle_radial=ANGLE_RAD),
        input_beam=beam)
    beam, _ = m2_el.trace_beam()
    results['4_after_M2'] = _beam_stats(beam, 'After M2')

    # 5. SSA: Rectangular aperture
    ssa_el = S4ScreenElement(
        optical_element=S4Screen(
            name="SSA",
            boundary_shape=Rectangle(
                x_left=-ssa_half, x_right=ssa_half,
                y_bottom=-ssa_half, y_top=ssa_half),
            i_abs=0, i_stop=0, thick=0.0, file_abs=""),
        coordinates=ElementCoordinates(p=0.0, q=0.0),
        input_beam=beam)
    beam_ssa, _ = ssa_el.trace_beam()
    results['5_at_SSA'] = _beam_stats(beam_ssa, 'At SSA')

    # 5b. SSA Hybrid (if requested)
    if hybrid:
        try:
            ssa_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.SIMPLE_APERTURE)
            ssa_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam_ssa),
                optical_element=S4HybridOE(optical_element=ssa_el),
                diffraction_plane=HybridDiffractionPlane.BOTH_2X1D,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False, random_seed=0)
            ssa_hyb_el = S4HybridScreenElement(
                hybrid_screen=ssa_hyb_screen,
                hybrid_input_parameters=ssa_hyb_inp)
            beam_ssa = _extract_hybrid_beam(ssa_hyb_el.trace_beam())
            if verbose:
                print(f"  [SSA hybrid applied]")
        except Exception as e:
            if verbose:
                print(f"  [SSA hybrid SKIPPED: {e}]")

    # 6. KB-V: Ellipsoidal, tangential V-focus
    p_kbv = POS['kbv'] - POS['ssa']
    q_kbv = POS['sample'] - POS['kbv']
    kbv_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-V",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_V_LEN/2, y_top=KB_V_LEN/2),
            is_cylinder=True, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL, convexity=1,
            p_focus=p_kbv, q_focus=q_kbv,
            grazing_angle=THETA_GRAZ, f_reflec=0),
        coordinates=ElementCoordinates(p=p_kbv, q=0.0, angle_radial=ANGLE_RAD),
        input_beam=beam_ssa)
    beam_kbv, _ = kbv_el.trace_beam()
    results['6_after_KBV'] = _beam_stats(beam_kbv, 'After KB-V')

    # 6b. KB-V Hybrid
    if hybrid:
        try:
            kbv_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbv_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam_kbv),
                optical_element=S4HybridOE(optical_element=kbv_el),
                diffraction_plane=HybridDiffractionPlane.TANGENTIAL,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False, random_seed=0)
            kbv_hyb_el = S4HybridScreenElement(
                hybrid_screen=kbv_hyb_screen,
                hybrid_input_parameters=kbv_hyb_inp)
            beam_kbv = _extract_hybrid_beam(kbv_hyb_el.trace_beam())
            if verbose:
                print(f"  [KB-V hybrid applied]")
        except Exception as e:
            if verbose:
                print(f"  [KB-V hybrid SKIPPED: {e}]")

    # Drift KB-V -> KB-H
    dist_v_to_h = POS['kbh'] - POS['kbv']
    drift_el = S4ScreenElement(
        optical_element=S4Screen(name="drift_VH"),
        coordinates=ElementCoordinates(p=dist_v_to_h, q=0.0),
        input_beam=beam_kbv)
    beam_d, _ = drift_el.trace_beam()

    # 7. KB-H: Ellipsoidal, sagittal H-focus (swap trick)
    p_kbh = POS['kbh'] - POS['ssa']
    q_kbh = POS['sample'] - POS['kbh']
    beam_s = _swap_xz(beam_d)

    kbh_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-H",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_H_LEN/2, y_top=KB_H_LEN/2),
            is_cylinder=True, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL, convexity=1,
            p_focus=p_kbh, q_focus=q_kbh,
            grazing_angle=THETA_GRAZ, f_reflec=0),
        coordinates=ElementCoordinates(p=0.0, q=q_kbh, angle_radial=ANGLE_RAD),
        input_beam=beam_s)
    beam_kbh_s, _ = kbh_el.trace_beam()

    # 7b. KB-H Hybrid
    if hybrid:
        try:
            kbh_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbh_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam_kbh_s),
                optical_element=S4HybridOE(optical_element=kbh_el),
                diffraction_plane=HybridDiffractionPlane.TANGENTIAL,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False, random_seed=0)
            kbh_hyb_el = S4HybridScreenElement(
                hybrid_screen=kbh_hyb_screen,
                hybrid_input_parameters=kbh_hyb_inp)
            beam_kbh_s = _extract_hybrid_beam(kbh_hyb_el.trace_beam())
            if verbose:
                print(f"  [KB-H hybrid applied]")
        except Exception as e:
            if verbose:
                print(f"  [KB-H hybrid SKIPPED: {e}]")

    # Swap back to restore coordinates
    beam_sample = _swap_xz(beam_kbh_s)
    results['7_at_sample'] = _beam_stats(beam_sample, 'At Sample')

    return results


def print_table(title, results, n_start):
    """Pretty-print beam stats table."""
    print(f"\n{'='*85}")
    print(f"  {title}")
    print(f"{'='*85}")
    print(f"  {'Stage':<25} {'Rays':>8} {'Throughput':>10} {'sig_H(um)':>10} "
          f"{'sig_V(um)':>10} {'FWHM_H':>12} {'FWHM_V':>12}")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*12} {'-'*12}")

    for key in sorted(results.keys()):
        d = results[key]
        n = d['n']
        pct = n / n_start * 100 if n_start > 0 else 0
        fh = d['fwhm_h_nm']
        fv = d['fwhm_v_nm']

        # For upstream elements where FWHM is large, show in um
        if fh > 10000:
            fh_str = f"{fh/1000:.1f} um"
        else:
            fh_str = f"{fh:.1f} nm"

        if fv > 10000:
            fv_str = f"{fv/1000:.1f} um"
        else:
            fv_str = f"{fv:.1f} nm"

        print(f"  {d['label']:<25} {n:>8d} {pct:>9.1f}% {d['sig_h_um']:>10.3f} "
              f"{d['sig_v_um']:>10.3f} {fh_str:>12s} {fv_str:>12s}")


def main():
    E_KEV = 10.0
    SSA_UM = 50
    NRAYS = 200000
    N_REPEATS = 3
    SEEDS = [12345, 23456, 34567]

    print("="*85)
    print("  Shadow4 Geometric-Only vs Hybrid FWHM Comparison")
    print(f"  Condition: {E_KEV}keV, SSA={SSA_UM}um, {NRAYS} rays x {N_REPEATS} repeats")
    print("="*85)

    # --- Run GEO path multiple times ---
    print(f"\n--- GEOMETRIC-ONLY runs ---")
    geo_fwhm_h_list = []
    geo_fwhm_v_list = []
    geo_n_list = []
    geo_results = None

    for rep in range(N_REPEATS):
        t0 = time.time()
        geo_results = run_beamline(E_KEV, SSA_UM, NRAYS, SEEDS[rep],
                                    hybrid=False, verbose=(rep == 0))
        elapsed = time.time() - t0

        sample = geo_results['7_at_sample']
        geo_fwhm_h_list.append(sample['fwhm_h_nm'])
        geo_fwhm_v_list.append(sample['fwhm_v_nm'])
        geo_n_list.append(sample['n'])

        print(f"  GEO rep {rep+1}: FWHM_H={sample['fwhm_h_nm']:.1f}nm, "
              f"FWHM_V={sample['fwhm_v_nm']:.1f}nm, "
              f"rays={sample['n']}/{NRAYS}, time={elapsed:.1f}s")

    # Print full table for last run
    print_table(f"GEOMETRIC-ONLY ({E_KEV}keV, SSA={SSA_UM}um) -- last run detail",
                geo_results, NRAYS)

    # --- Run HYBRID path multiple times ---
    print(f"\n--- HYBRID runs ---")
    hyb_fwhm_h_list = []
    hyb_fwhm_v_list = []
    hyb_n_list = []
    hyb_results = None

    for rep in range(N_REPEATS):
        t0 = time.time()
        hyb_results = run_beamline(E_KEV, SSA_UM, NRAYS, SEEDS[rep],
                                    hybrid=True, verbose=(rep == 0))
        elapsed = time.time() - t0

        sample = hyb_results['7_at_sample']
        hyb_fwhm_h_list.append(sample['fwhm_h_nm'])
        hyb_fwhm_v_list.append(sample['fwhm_v_nm'])
        hyb_n_list.append(sample['n'])

        print(f"  HYB rep {rep+1}: FWHM_H={sample['fwhm_h_nm']:.1f}nm, "
              f"FWHM_V={sample['fwhm_v_nm']:.1f}nm, "
              f"rays={sample['n']}/{NRAYS}, time={elapsed:.1f}s")

    # Print full table for last run
    print_table(f"HYBRID ({E_KEV}keV, SSA={SSA_UM}um) -- last run detail",
                hyb_results, NRAYS)

    # --- Summary comparison ---
    geo_mean_h = np.mean(geo_fwhm_h_list)
    geo_std_h  = np.std(geo_fwhm_h_list, ddof=1) if len(geo_fwhm_h_list) > 1 else 0
    geo_mean_v = np.mean(geo_fwhm_v_list)
    geo_std_v  = np.std(geo_fwhm_v_list, ddof=1) if len(geo_fwhm_v_list) > 1 else 0
    geo_mean_n = np.mean(geo_n_list)

    hyb_mean_h = np.mean(hyb_fwhm_h_list)
    hyb_std_h  = np.std(hyb_fwhm_h_list, ddof=1) if len(hyb_fwhm_h_list) > 1 else 0
    hyb_mean_v = np.mean(hyb_fwhm_v_list)
    hyb_std_v  = np.std(hyb_fwhm_v_list, ddof=1) if len(hyb_fwhm_v_list) > 1 else 0
    hyb_mean_n = np.mean(hyb_n_list)

    print(f"\n{'='*85}")
    print(f"  FINAL SUMMARY: {E_KEV}keV, SSA={SSA_UM}um ({N_REPEATS} repeats)")
    print(f"{'='*85}")
    print(f"  {'Method':<15} {'FWHM_H (nm)':>20} {'FWHM_V (nm)':>20} {'Survived':>12}")
    print(f"  {'-'*15} {'-'*20} {'-'*20} {'-'*12}")
    print(f"  {'GEOMETRIC':<15} {geo_mean_h:>8.1f} +/- {geo_std_h:<6.1f}  "
          f"{geo_mean_v:>8.1f} +/- {geo_std_v:<6.1f}  {geo_mean_n:>8.0f}")
    print(f"  {'HYBRID':<15} {hyb_mean_h:>8.1f} +/- {hyb_std_h:<6.1f}  "
          f"{hyb_mean_v:>8.1f} +/- {hyb_std_v:<6.1f}  {hyb_mean_n:>8.0f}")
    print(f"  {'DIFF (H-G)':<15} {hyb_mean_h - geo_mean_h:>8.1f} {'':>14s} "
          f"{hyb_mean_v - geo_mean_v:>8.1f}")
    print(f"\n  MC geometric reference: 34.4 nm H, 29.8 nm V")
    print(f"{'='*85}")


if __name__ == '__main__':
    main()
