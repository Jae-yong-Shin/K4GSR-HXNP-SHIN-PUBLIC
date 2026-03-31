"""
Shadow4 Hybrid Diffraction Kick Diagnostic
===========================================
Runs the full BL10 beamline at 10keV SSA50 twice:
  1) GEOMETRIC only (no hybrid) -- captures beam FWHM at sample
  2) WITH HYBRID (SSA + KB diffraction) -- captures beam FWHM at sample

Then computes the effective diffraction contribution:
  kick = sqrt(FWHM_hybrid^2 - FWHM_geo^2)

And compares with the Airy prediction:
  FWHM_Airy = 0.886 * lambda / D
where D = projected mirror aperture = L * sin(theta).

Also dumps the beam footprint on each KB mirror to find the ACTUAL
illuminated aperture D_actual vs the nominal mirror length.

Usage:
    conda run -n oasys_env python _s4_kick_diagnostic.py
"""

import os, sys, time
import numpy as np
from math import sqrt, pi, exp, erf

# --- Shadow4 imports ---
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

# --- Hybrid diffraction imports ---
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
    """Suppresses verbose hybrid status messages; only prints warnings/errors."""
    def status_message(self, message): pass
    def set_progress_value(self, value): pass
    def warning_message(self, message=""):
        if "abort" in message.lower() or "unaltered" in message.lower():
            print(f"  [HYBRID WARN] {message.strip()}")
    def error_message(self, message=""):
        print(f"  [HYBRID ERROR] {message}")


# Monkey-patch for shadow4 v0.1.79 compatibility
def _patch_mirror_classes():
    try:
        from shadow4.beamline.optical_elements.mirrors import s4_mirror
        basecls = s4_mirror.S4MirrorElement
        if hasattr(basecls, '_apply_mirror_reflection_and_reflectivity') and not hasattr(basecls, 'apply_mirror_reflection_and_reflectivity'):
            basecls.apply_mirror_reflection_and_reflectivity = basecls._apply_mirror_reflection_and_reflectivity
        oe_cls = s4_mirror.S4Mirror
        if hasattr(oe_cls, '_apply_mirror_reflection') and not hasattr(oe_cls, 'apply_mirror_reflection'):
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
E_RING  = 4.0
I_RING  = 0.4
EMIT_X  = 62e-12
EMIT_Y  = 6.2e-12
BETA_X  = 6.334
BETA_Y  = 2.841
E_SPREAD = 1.20e-3
HC      = 12.3984

LAMBDA_U = 0.024
N_PERIODS = 123
L_UND   = N_PERIODS * LAMBDA_U

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
    'ssa':    58.0,
    'kbv':    149.69,
    'kbh':    149.90,
    'sample': 150.0,
}

M1_P = 30.4;  M1_Q = 27.6
M2_P = 33.0;  M2_Q = 25.0

KB_V_LEN = 0.300
KB_H_LEN = 0.100
M1_LEN = 0.600; M1_WID = 0.060
M2_LEN = 0.400; M2_WID = 0.040
KB_WID = 0.030

THETA_GRAZ = 0.003
ANGLE_RAD = np.pi / 2 - THETA_GRAZ


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
    """Swap X<->Z and X'<->Z' columns in a beam (for sagittal KB-H trick)."""
    rays = beam.get_rays().copy()
    rays[:, [0, 2]] = rays[:, [2, 0]]
    rays[:, [3, 5]] = rays[:, [5, 3]]
    return S4Beam(N=rays.shape[0], array=rays)


def _fwhm_from_ticket(ticket):
    """Extract FWHM from histo1 ticket."""
    return ticket.get('fwhm', 0) or 0


def run_beamline(E_keV, ssa_um, nrays, seed, hybrid=False, verbose=True,
                 dump_kb_footprints=False):
    """
    Run full BL10 beamline.

    If dump_kb_footprints=True, returns (beam_at_sample, kbv_footprint_dict, kbh_footprint_dict)
    Otherwise returns beam_at_sample.
    """
    E_eV = E_keV * 1000.0
    ssa_half = ssa_um * 0.5e-6

    Sx, Sy, Sxp, Syp = photon_src(E_keV, harmonic=3)

    if verbose:
        print(f"[Source] E={E_keV} keV, SSA={ssa_um} um, nrays={nrays}, hybrid={hybrid}")

    src = SourceGaussian(
        nrays=nrays, seed=seed,
        sigmaX=Sx, sigmaY=0.0, sigmaZ=Sy,
        sigmaXprime=Sxp, sigmaZprime=Syp,
    )
    beam0 = S4Beam()
    beam0.generate_source(src)
    beam0.set_photon_energy_eV(E_eV)
    n_start = beam0.get_number_of_rays(nolost=1)

    # ------- M1: Spherical, sagittal H-focus -------
    p_m1 = POS['m1']
    q_m1 = POS['dcm'] - POS['m1']
    m1_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M1",
            boundary_shape=Rectangle(
                x_left=-M1_WID/2, x_right=M1_WID/2,
                y_bottom=-M1_LEN/2, y_top=M1_LEN/2),
            is_cylinder=1, cylinder_direction=Direction.SAGITTAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1, p_focus=M1_P, q_focus=M1_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=p_m1, q=q_m1, angle_radial=ANGLE_RAD),
        input_beam=beam0,
    )
    beam1, _ = m1_el.trace_beam()
    if verbose:
        print(f"[M1] {beam1.get_number_of_rays(nolost=1)} good rays")

    # ------- DCM: Si(111) double crystal -------
    dcm1_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM Crystal 1", boundary_shape=None,
            material="Si", miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0, is_thick=0, thickness=0.010,
            f_central=True, f_phot_cent=0, phot_cent=E_eV,
            file_refl="", f_bragg_a=False, f_ext=0,
        ),
        coordinates=ElementCoordinates(p=0.0, q=0.020,
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0),
        input_beam=beam1,
    )
    beam2a, _ = dcm1_el.trace_beam()

    dcm2_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM Crystal 2", boundary_shape=None,
            material="Si", miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0, is_thick=0, thickness=0.010,
            f_central=True, f_phot_cent=0, phot_cent=E_eV,
            file_refl="", f_bragg_a=False, f_ext=0,
        ),
        coordinates=ElementCoordinates(p=0.020, q=POS['m2'] - POS['dcm'],
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0),
        input_beam=beam2a,
    )
    beam2, _ = dcm2_el.trace_beam()
    if verbose:
        print(f"[DCM] {beam2.get_number_of_rays(nolost=1)} good rays")

    # ------- M2: Spherical, tangential V-focus -------
    q_m2 = POS['ssa'] - POS['m2']
    m2_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M2",
            boundary_shape=Rectangle(
                x_left=-M2_WID/2, x_right=M2_WID/2,
                y_bottom=-M2_LEN/2, y_top=M2_LEN/2),
            is_cylinder=1, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1, p_focus=M2_P, q_focus=M2_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=0.0, q=q_m2, angle_radial=ANGLE_RAD),
        input_beam=beam2,
    )
    beam3, _ = m2_el.trace_beam()
    if verbose:
        print(f"[M2] {beam3.get_number_of_rays(nolost=1)} good rays")

    # ------- SSA: Rectangular aperture -------
    ssa_el = S4ScreenElement(
        optical_element=S4Screen(
            name="SSA",
            boundary_shape=Rectangle(
                x_left=-ssa_half, x_right=ssa_half,
                y_bottom=-ssa_half, y_top=ssa_half),
            i_abs=0, i_stop=0, thick=0.0, file_abs="",
        ),
        coordinates=ElementCoordinates(p=0.0, q=0.0),
        input_beam=beam3,
    )
    beam4, _ = ssa_el.trace_beam()
    if verbose:
        n4 = beam4.get_number_of_rays(nolost=1)
        print(f"[SSA] {n4} good rays ({n4/n_start*100:.1f}%)")

    # SSA Hybrid
    if hybrid:
        try:
            ssa_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.SIMPLE_APERTURE)
            ssa_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam4),
                optical_element=S4HybridOE(optical_element=ssa_el),
                diffraction_plane=HybridDiffractionPlane.BOTH_2X1D,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False,
                random_seed=0,
            )
            ssa_hyb_el = S4HybridScreenElement(
                hybrid_screen=ssa_hyb_screen,
                hybrid_input_parameters=ssa_hyb_inp)
            beam4 = _extract_hybrid_beam(ssa_hyb_el.trace_beam())
            if verbose:
                print(f"[SSA-hybrid] applied")
        except Exception as e:
            if verbose:
                print(f"[SSA-hybrid] SKIPPED: {e}")

    # ------- KB-V: Ellipsoidal, tangential V-focus -------
    p_kbv = POS['kbv'] - POS['ssa']
    q_kbv = POS['sample'] - POS['kbv']

    kbv_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-V",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_V_LEN/2, y_top=KB_V_LEN/2),
            is_cylinder=True, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1, p_focus=p_kbv, q_focus=q_kbv,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=p_kbv, q=0.0, angle_radial=ANGLE_RAD),
        input_beam=beam4,
    )
    beam5, mirr_kbv = kbv_el.trace_beam()

    # Dump KB-V footprint
    kbv_footprint = None
    if dump_kb_footprints and mirr_kbv is not None:
        # mirr_kbv is the beam at the mirror surface (mirror frame)
        # col 1 = X (sagittal), col 2 = Y (along mirror), col 3 = Z (tangential/normal)
        kbv_y = mirr_kbv.get_column(2, nolost=1)  # along mirror length
        kbv_z = mirr_kbv.get_column(3, nolost=1)  # tangential direction at surface
        kbv_x = mirr_kbv.get_column(1, nolost=1)  # sagittal direction
        kbv_footprint = {
            'y_min_mm': float(np.min(kbv_y)) * 1e3,
            'y_max_mm': float(np.max(kbv_y)) * 1e3,
            'y_range_mm': float(np.max(kbv_y) - np.min(kbv_y)) * 1e3,
            'x_min_mm': float(np.min(kbv_x)) * 1e3,
            'x_max_mm': float(np.max(kbv_x)) * 1e3,
            'x_range_mm': float(np.max(kbv_x) - np.min(kbv_x)) * 1e3,
            'n_rays': len(kbv_y),
            'y_sigma_mm': float(np.std(kbv_y)) * 1e3,
            'y_fwhm_mm': float(np.std(kbv_y)) * 2.355 * 1e3,  # Gaussian approx
        }
        if verbose:
            print(f"[KB-V footprint] Y range: {kbv_footprint['y_min_mm']:.2f} to {kbv_footprint['y_max_mm']:.2f} mm "
                  f"(span={kbv_footprint['y_range_mm']:.2f} mm, FWHM~{kbv_footprint['y_fwhm_mm']:.2f} mm)")
            print(f"                 X range: {kbv_footprint['x_min_mm']:.3f} to {kbv_footprint['x_max_mm']:.3f} mm "
                  f"(span={kbv_footprint['x_range_mm']:.3f} mm)")

    if verbose:
        n5 = beam5.get_number_of_rays(nolost=1)
        print(f"[KB-V] {n5} good rays ({n5/n_start*100:.1f}%)")

    # KB-V Hybrid
    if hybrid:
        try:
            kbv_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbv_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam5),
                optical_element=S4HybridOE(optical_element=kbv_el),
                diffraction_plane=HybridDiffractionPlane.TANGENTIAL,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False,
                random_seed=0,
            )
            kbv_hyb_el = S4HybridScreenElement(
                hybrid_screen=kbv_hyb_screen,
                hybrid_input_parameters=kbv_hyb_inp)
            beam5 = _extract_hybrid_beam(kbv_hyb_el.trace_beam())
            if verbose:
                print(f"[KB-V-hybrid] applied")
        except Exception as e:
            if verbose:
                print(f"[KB-V-hybrid] SKIPPED: {e}")

    # Drift KB-V to KB-H
    dist_v_to_h = POS['kbh'] - POS['kbv']
    drift_el = S4ScreenElement(
        optical_element=S4Screen(name="drift_VH"),
        coordinates=ElementCoordinates(p=dist_v_to_h, q=0.0),
        input_beam=beam5,
    )
    beam5d, _ = drift_el.trace_beam()

    # ------- KB-H: Ellipsoidal, sagittal H-focus (swap trick) -------
    p_kbh = POS['kbh'] - POS['ssa']
    q_kbh = POS['sample'] - POS['kbh']

    beam5s = _swap_xz(beam5d)

    kbh_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-H",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_H_LEN/2, y_top=KB_H_LEN/2),
            is_cylinder=True, cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1, p_focus=p_kbh, q_focus=q_kbh,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=0.0, q=q_kbh, angle_radial=ANGLE_RAD),
        input_beam=beam5s,
    )
    beam6s, mirr_kbh = kbh_el.trace_beam()

    # Dump KB-H footprint (note: beam is X<->Z swapped, so mirror Y is along length)
    kbh_footprint = None
    if dump_kb_footprints and mirr_kbh is not None:
        kbh_y = mirr_kbh.get_column(2, nolost=1)  # along mirror
        kbh_z = mirr_kbh.get_column(3, nolost=1)
        kbh_x = mirr_kbh.get_column(1, nolost=1)
        kbh_footprint = {
            'y_min_mm': float(np.min(kbh_y)) * 1e3,
            'y_max_mm': float(np.max(kbh_y)) * 1e3,
            'y_range_mm': float(np.max(kbh_y) - np.min(kbh_y)) * 1e3,
            'x_min_mm': float(np.min(kbh_x)) * 1e3,
            'x_max_mm': float(np.max(kbh_x)) * 1e3,
            'x_range_mm': float(np.max(kbh_x) - np.min(kbh_x)) * 1e3,
            'n_rays': len(kbh_y),
            'y_sigma_mm': float(np.std(kbh_y)) * 1e3,
            'y_fwhm_mm': float(np.std(kbh_y)) * 2.355 * 1e3,
        }
        if verbose:
            print(f"[KB-H footprint] Y range: {kbh_footprint['y_min_mm']:.2f} to {kbh_footprint['y_max_mm']:.2f} mm "
                  f"(span={kbh_footprint['y_range_mm']:.2f} mm, FWHM~{kbh_footprint['y_fwhm_mm']:.2f} mm)")
            print(f"                 X range: {kbh_footprint['x_min_mm']:.3f} to {kbh_footprint['x_max_mm']:.3f} mm "
                  f"(span={kbh_footprint['x_range_mm']:.3f} mm)")

    # KB-H Hybrid
    if hybrid:
        try:
            kbh_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbh_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam6s),
                optical_element=S4HybridOE(optical_element=kbh_el),
                diffraction_plane=HybridDiffractionPlane.TANGENTIAL,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False,
                random_seed=0,
            )
            kbh_hyb_el = S4HybridScreenElement(
                hybrid_screen=kbh_hyb_screen,
                hybrid_input_parameters=kbh_hyb_inp)
            beam6s = _extract_hybrid_beam(kbh_hyb_el.trace_beam())
            if verbose:
                print(f"[KB-H-hybrid] applied")
        except Exception as e:
            if verbose:
                print(f"[KB-H-hybrid] SKIPPED: {e}")

    # Swap back
    beam6 = _swap_xz(beam6s)

    if verbose:
        n6 = beam6.get_number_of_rays(nolost=1)
        print(f"[Sample] {n6} good rays ({n6/n_start*100:.1f}%)")

    if dump_kb_footprints:
        return beam6, kbv_footprint, kbh_footprint
    return beam6


# ==============================================================
#  MAIN
# ==============================================================
if __name__ == '__main__':
    E_keV = 10.0
    ssa_um = 50
    nrays = 200000
    seed = 0

    lam = HC / E_keV * 1e-10  # wavelength in meters
    print(f"Wavelength at {E_keV} keV: {lam*1e10:.4f} A = {lam*1e9:.4f} nm")

    # =====================================================
    #  RUN 1: GEOMETRIC (no hybrid)
    # =====================================================
    print("\n" + "="*70)
    print("  RUN 1: GEOMETRIC (no hybrid)")
    print("="*70)
    t0 = time.time()
    beam_geo, kbv_fp, kbh_fp = run_beamline(
        E_keV, ssa_um, nrays, seed,
        hybrid=False, verbose=True, dump_kb_footprints=True
    )
    t_geo = time.time() - t0
    print(f"Geometric trace time: {t_geo:.1f}s")

    # FWHM at sample (geometric)
    tk_h_geo = beam_geo.histo1(col=1, nbins=200, nolost=1, ref=23, calculate_widths=1)
    tk_v_geo = beam_geo.histo1(col=3, nbins=200, nolost=1, ref=23, calculate_widths=1)
    fwhm_h_geo = _fwhm_from_ticket(tk_h_geo)
    fwhm_v_geo = _fwhm_from_ticket(tk_v_geo)

    print(f"\n  GEOMETRIC FWHM_H = {fwhm_h_geo*1e9:.2f} nm")
    print(f"  GEOMETRIC FWHM_V = {fwhm_v_geo*1e9:.2f} nm")

    # =====================================================
    #  RUN 2: WITH HYBRID (SSA + KB diffraction)
    # =====================================================
    print("\n" + "="*70)
    print("  RUN 2: HYBRID (SSA + KB diffraction)")
    print("="*70)
    t0 = time.time()
    beam_hyb = run_beamline(
        E_keV, ssa_um, nrays, seed,
        hybrid=True, verbose=True, dump_kb_footprints=False
    )
    t_hyb = time.time() - t0
    print(f"Hybrid trace time: {t_hyb:.1f}s")

    # FWHM at sample (hybrid)
    tk_h_hyb = beam_hyb.histo1(col=1, nbins=200, nolost=1, ref=23, calculate_widths=1)
    tk_v_hyb = beam_hyb.histo1(col=3, nbins=200, nolost=1, ref=23, calculate_widths=1)
    fwhm_h_hyb = _fwhm_from_ticket(tk_h_hyb)
    fwhm_v_hyb = _fwhm_from_ticket(tk_v_hyb)

    print(f"\n  HYBRID FWHM_H = {fwhm_h_hyb*1e9:.2f} nm")
    print(f"  HYBRID FWHM_V = {fwhm_v_hyb*1e9:.2f} nm")

    # =====================================================
    #  ANALYSIS: Effective diffraction kick
    # =====================================================
    print("\n" + "="*70)
    print("  ANALYSIS: Effective Diffraction Kick")
    print("="*70)

    # Effective kick = sqrt(hybrid^2 - geo^2)
    if fwhm_h_hyb > fwhm_h_geo:
        kick_h = sqrt(fwhm_h_hyb**2 - fwhm_h_geo**2)
    else:
        kick_h = 0
        print("  WARNING: Hybrid H is narrower than geometric -- no broadening detected!")

    if fwhm_v_hyb > fwhm_v_geo:
        kick_v = sqrt(fwhm_v_hyb**2 - fwhm_v_geo**2)
    else:
        kick_v = 0
        print("  WARNING: Hybrid V is narrower than geometric -- no broadening detected!")

    print(f"\n  Effective diffraction kick (H): {kick_h*1e9:.2f} nm")
    print(f"  Effective diffraction kick (V): {kick_v*1e9:.2f} nm")

    # =====================================================
    #  KB Mirror Footprints -- ACTUAL illuminated aperture
    # =====================================================
    print("\n" + "="*70)
    print("  KB MIRROR FOOTPRINTS (actual beam illumination)")
    print("="*70)

    # KB-V: mirror length = 300mm, beam footprint from geometric trace
    D_kbv_nominal = KB_V_LEN * np.sin(THETA_GRAZ)  # projected aperture
    q_kbv = POS['sample'] - POS['kbv']
    if kbv_fp:
        # The footprint Y is along-mirror coordinate
        # Projected aperture D = footprint_range * sin(theta)
        D_kbv_actual_full = kbv_fp['y_range_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        D_kbv_actual_fwhm = kbv_fp['y_fwhm_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        print(f"\n  KB-V: mirror length = {KB_V_LEN*1e3:.0f} mm, q = {q_kbv:.2f} m")
        print(f"    Beam footprint on mirror: {kbv_fp['y_range_mm']:.2f} mm (full range), "
              f"FWHM ~ {kbv_fp['y_fwhm_mm']:.2f} mm")
        print(f"    Mirror length: {KB_V_LEN*1e3:.0f} mm")
        print(f"    Fill factor: {kbv_fp['y_range_mm'] / (KB_V_LEN*1e3) * 100:.1f}% (range), "
              f"{kbv_fp['y_fwhm_mm'] / (KB_V_LEN*1e3) * 100:.1f}% (FWHM)")
        print(f"    D_nominal (mirror) = {D_kbv_nominal*1e6:.1f} um")
        print(f"    D_actual  (full range) = {D_kbv_actual_full*1e6:.1f} um")
        print(f"    D_actual  (FWHM) = {D_kbv_actual_fwhm*1e6:.1f} um")

    # KB-H: mirror length = 100mm, beam footprint from geometric trace
    D_kbh_nominal = KB_H_LEN * np.sin(THETA_GRAZ)
    q_kbh = POS['sample'] - POS['kbh']
    if kbh_fp:
        D_kbh_actual_full = kbh_fp['y_range_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        D_kbh_actual_fwhm = kbh_fp['y_fwhm_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        print(f"\n  KB-H: mirror length = {KB_H_LEN*1e3:.0f} mm, q = {q_kbh:.2f} m")
        print(f"    Beam footprint on mirror: {kbh_fp['y_range_mm']:.2f} mm (full range), "
              f"FWHM ~ {kbh_fp['y_fwhm_mm']:.2f} mm")
        print(f"    Mirror length: {KB_H_LEN*1e3:.0f} mm")
        print(f"    Fill factor: {kbh_fp['y_range_mm'] / (KB_H_LEN*1e3) * 100:.1f}% (range), "
              f"{kbh_fp['y_fwhm_mm'] / (KB_H_LEN*1e3) * 100:.1f}% (FWHM)")
        print(f"    D_nominal (mirror) = {D_kbh_nominal*1e6:.1f} um")
        print(f"    D_actual  (full range) = {D_kbh_actual_full*1e6:.1f} um")
        print(f"    D_actual  (FWHM) = {D_kbh_actual_fwhm*1e6:.1f} um")

    # =====================================================
    #  Airy prediction vs Shadow4 hybrid
    # =====================================================
    print("\n" + "="*70)
    print("  AIRY PREDICTION vs SHADOW4 HYBRID")
    print("="*70)

    # Airy FWHM = 0.886 * lambda / D
    # Using NOMINAL aperture (full mirror)
    airy_v_nominal = 0.886 * lam / D_kbv_nominal * q_kbv  # at focal plane
    airy_h_nominal = 0.886 * lam / D_kbh_nominal * q_kbh

    # Wait -- Airy formula for a focusing mirror:
    #   spot size = 0.886 * lambda * f / D
    # where f = focal length (= q for mirrors), D = projected aperture
    # This is equivalent to: 0.886 * lambda / (D/f) = 0.886 * lambda / (2*NA)
    # For grazing incidence: D = L * sin(theta), and f = q
    # So Airy FWHM = 0.886 * lambda * q / D

    print(f"\n  Wavelength = {lam*1e10:.4f} A = {lam*1e9:.4f} nm")

    print(f"\n  === KB-V (Vertical focus) ===")
    print(f"    D_nominal = L * sin(theta) = {KB_V_LEN*1e3:.0f} mm * sin({THETA_GRAZ*1e3:.0f} mrad) = {D_kbv_nominal*1e6:.1f} um")
    print(f"    q = {q_kbv:.2f} m")
    print(f"    Airy FWHM (nominal D) = 0.886 * {lam*1e9:.4f} nm * {q_kbv:.2f} m / {D_kbv_nominal*1e6:.1f} um")
    print(f"                          = {airy_v_nominal*1e9:.2f} nm")
    if kbv_fp:
        D_kbv_for_airy = kbv_fp['y_range_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        airy_v_actual = 0.886 * lam * q_kbv / D_kbv_for_airy
        print(f"    Airy FWHM (actual D, full range) = {airy_v_actual*1e9:.2f} nm")
        D_kbv_fwhm = kbv_fp['y_fwhm_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        airy_v_fwhm_D = 0.886 * lam * q_kbv / D_kbv_fwhm
        print(f"    Airy FWHM (actual D, beam FWHM)  = {airy_v_fwhm_D*1e9:.2f} nm")

    print(f"\n  === KB-H (Horizontal focus) ===")
    print(f"    D_nominal = L * sin(theta) = {KB_H_LEN*1e3:.0f} mm * sin({THETA_GRAZ*1e3:.0f} mrad) = {D_kbh_nominal*1e6:.1f} um")
    print(f"    q = {q_kbh:.2f} m")
    print(f"    Airy FWHM (nominal D) = 0.886 * {lam*1e9:.4f} nm * {q_kbh:.2f} m / {D_kbh_nominal*1e6:.1f} um")
    print(f"                          = {airy_h_nominal*1e9:.2f} nm")
    if kbh_fp:
        D_kbh_for_airy = kbh_fp['y_range_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        airy_h_actual = 0.886 * lam * q_kbh / D_kbh_for_airy
        print(f"    Airy FWHM (actual D, full range) = {airy_h_actual*1e9:.2f} nm")
        D_kbh_fwhm = kbh_fp['y_fwhm_mm'] * 1e-3 * np.sin(THETA_GRAZ)
        airy_h_fwhm_D = 0.886 * lam * q_kbh / D_kbh_fwhm
        print(f"    Airy FWHM (actual D, beam FWHM)  = {airy_h_fwhm_D*1e9:.2f} nm")

    # =====================================================
    #  SUMMARY TABLE
    # =====================================================
    print("\n" + "="*70)
    print("  SUMMARY TABLE")
    print("="*70)
    print(f"{'':30s} {'Horizontal':>15s} {'Vertical':>15s}")
    print(f"{'-'*60}")
    print(f"{'FWHM geometric (nm)':30s} {fwhm_h_geo*1e9:15.2f} {fwhm_v_geo*1e9:15.2f}")
    print(f"{'FWHM hybrid (nm)':30s} {fwhm_h_hyb*1e9:15.2f} {fwhm_v_hyb*1e9:15.2f}")
    print(f"{'Effective kick (nm)':30s} {kick_h*1e9:15.2f} {kick_v*1e9:15.2f}")
    print(f"{'Airy FWHM, nominal D (nm)':30s} {airy_h_nominal*1e9:15.2f} {airy_v_nominal*1e9:15.2f}")
    if kbh_fp and kbv_fp:
        print(f"{'Airy FWHM, actual D (nm)':30s} {airy_h_actual*1e9:15.2f} {airy_v_actual*1e9:15.2f}")
    print(f"{'kick / Airy(nominal)':30s} {kick_h/airy_h_nominal if airy_h_nominal > 0 else 0:15.3f} {kick_v/airy_v_nominal if airy_v_nominal > 0 else 0:15.3f}")
    if kbh_fp and kbv_fp:
        print(f"{'kick / Airy(actual)':30s} {kick_h/airy_h_actual if airy_h_actual > 0 else 0:15.3f} {kick_v/airy_v_actual if airy_v_actual > 0 else 0:15.3f}")
    print(f"{'-'*60}")
    if kbv_fp:
        print(f"{'KB-V fill factor (%)':30s} {'':15s} {kbv_fp['y_range_mm'] / (KB_V_LEN*1e3) * 100:15.1f}")
    if kbh_fp:
        print(f"{'KB-H fill factor (%)':30s} {kbh_fp['y_range_mm'] / (KB_H_LEN*1e3) * 100:15.1f}")
    print(f"{'Geometric trace time (s)':30s} {t_geo:15.1f}")
    print(f"{'Hybrid trace time (s)':30s} {t_hyb:15.1f}")

    # =====================================================
    #  INTERPRETATION
    # =====================================================
    print("\n" + "="*70)
    print("  INTERPRETATION")
    print("="*70)
    if kick_v > 0 and airy_v_nominal > 0:
        ratio_v = kick_v / airy_v_nominal
        if 0.5 < ratio_v < 2.0:
            print(f"  V: Shadow4 hybrid kick ({kick_v*1e9:.1f} nm) is within 2x of Airy prediction "
                  f"({airy_v_nominal*1e9:.1f} nm). Ratio = {ratio_v:.2f}")
        else:
            print(f"  V: Shadow4 hybrid kick ({kick_v*1e9:.1f} nm) DIFFERS significantly from Airy "
                  f"({airy_v_nominal*1e9:.1f} nm). Ratio = {ratio_v:.2f}")
    if kick_h > 0 and airy_h_nominal > 0:
        ratio_h = kick_h / airy_h_nominal
        if 0.5 < ratio_h < 2.0:
            print(f"  H: Shadow4 hybrid kick ({kick_h*1e9:.1f} nm) is within 2x of Airy prediction "
                  f"({airy_h_nominal*1e9:.1f} nm). Ratio = {ratio_h:.2f}")
        else:
            print(f"  H: Shadow4 hybrid kick ({kick_h*1e9:.1f} nm) DIFFERS significantly from Airy "
                  f"({airy_h_nominal*1e9:.1f} nm). Ratio = {ratio_h:.2f}")

    print("\n  NOTE: If fill factor < 100%, the beam underfills the mirror.")
    print("  In this case, Airy(actual D) is more relevant than Airy(nominal D).")
    print("  S4 hybrid uses the ACTUAL illuminated aperture, not the mirror length.")
    print("\nDone.")
