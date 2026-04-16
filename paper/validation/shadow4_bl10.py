"""
Shadow4 BL10 (K4GSR HXNP) Beamline Simulation + Hybrid Diffraction
====================================================================
Replicates the JS MC ray trace engine optical chain in Shadow4 for validation.
Uses SourceGaussian with the same photonSrc(E) convolved sigma as the JS engine
to isolate optical chain differences from source model differences.

Hybrid wave-optics corrections (shadow4-advanced + shadow-hybrid-methods):
  - SSA: Simple aperture Fraunhofer diffraction (BOTH_2X1D)
  - KB-V: Mirror finite-size diffraction (TANGENTIAL)
  - KB-H: Mirror finite-size diffraction (TANGENTIAL, via X<->Z swap trick)

Shadow4 API notes (v0.1.70):
  - angle_radial = pi/2 - grazing_angle  (angle to surface normal)
  - convexity=1 is needed for focusing mirrors at grazing incidence
  - KB-H (sagittal ellipsoid cylinder) not supported; use beam X<->Z swap trick
  - histo1: use calculate_widths=1 (not calfwhm)

Usage:
    conda run -n oasys_env python paper/validation/shadow4_bl10.py

Output:
    paper/validation/data/s4_{E}keV_ssa{SSA}.json  (one file per condition)
"""

import os, sys, json, time
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
# Support both shadow4-hybrid (pip, newer) and shadow4-advanced (oasys_env, older)
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


# --- Monkey-patch: shadow4 v0.1.79 renamed apply_mirror_reflection to _apply_mirror_reflection
#     shadow4-hybrid v0.0.7 still calls the old public name. Fix compatibility.
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
    """Extract S4Beam from hybrid trace_beam() result.

    shadow4-advanced (oasys): returns (beam, mirr_or_None, footprint_or_None)
    shadow4-hybrid (pip):     returns (HybridCalculationResult, None)
    """
    if isinstance(trace_result, tuple):
        first = trace_result[0]
    else:
        first = trace_result
    # If it's already an S4Beam, return directly
    if hasattr(first, 'get_number_of_rays'):
        return first
    # HybridCalculationResult from shadow4_hybrid
    if hasattr(first, 'far_field_beam') and first.far_field_beam is not None:
        fb = first.far_field_beam
        if hasattr(fb, 'wrapped_beam'):
            return fb.wrapped_beam
        return fb
    return first


# ==============================================================
#  K4GSR Ring & IVU24 Parameters (from js/shared/01_constants.js)
# ==============================================================
E_RING  = 4.0           # GeV
I_RING  = 0.4           # A
EMIT_X  = 62e-12        # m*rad
EMIT_Y  = 6.2e-12       # m*rad
BETA_X  = 6.334         # m
BETA_Y  = 2.841         # m
E_SPREAD = 1.20e-3      # relative
HC      = 12.3984       # keV*Angstrom

LAMBDA_U = 0.024        # m (24 mm period)
N_PERIODS = 123
L_UND   = N_PERIODS * LAMBDA_U   # 2.952 m

# Electron beam sigmas
SIG_EX  = sqrt(EMIT_X * BETA_X)    # ~19.81 um
SIG_EXP = sqrt(EMIT_X / BETA_X)    # ~3.13 urad
SIG_EY  = sqrt(EMIT_Y * BETA_Y)    # ~4.20 um
SIG_EYP = sqrt(EMIT_Y / BETA_Y)    # ~1.48 urad

# Component positions (from CD array in 01_constants.js)
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

# Mirror focal parameters (from 03_beam_profile.js)
M1_P = 30.4     # object distance for M1 bender model
M1_Q = 27.6     # image distance
M2_P = 33.0     # object distance for M2 bender model
M2_Q = 26.0     # image distance (M2@32m -> SSA@58m = 26m)

# KB mirror lengths (JTEC spec, confirmed)
KB_V_LEN = 0.300   # m (300 mm)
KB_H_LEN = 0.100   # m (100 mm)

# Mirror dimensions
M1_LEN = 0.600     # m
M1_WID = 0.060     # m
M2_LEN = 0.400     # m
M2_WID = 0.040     # m
KB_WID = 0.030     # m (both KB mirrors)

# Grazing incidence angle
THETA_GRAZ = 0.003  # rad (3 mrad)
# Shadow4 angle_radial = angle to surface normal
ANGLE_RAD = np.pi / 2 - THETA_GRAZ


def select_harmonic(E_keV):
    """Select lowest valid odd harmonic for given energy (replicates JS selectBest).

    Returns harmonic number n (1, 3, 5, ...).
    """
    lc = LAMBDA_U * 100  # period in cm (2.4 cm)
    for n in range(1, 16, 2):
        E1n = E_keV / n  # required fundamental energy
        K2 = 2 * (0.9498 * E_RING**2 / (lc * E1n) - 1)
        if K2 < 0.01 or K2 > 25:
            continue
        K = sqrt(K2)
        B0 = K / (0.9341 * lc)
        # Halbach inversion: solve gap from B0
        lo, hi = 4.0, 30.0
        for _ in range(50):
            mid = (lo + hi) / 2
            r = mid / (LAMBDA_U * 1000)  # gap/period_mm
            B0_try = 3.3 * exp(-5.08 * r + 1.54 * r * r)
            if B0_try > B0:
                lo = mid
            else:
                hi = mid
        gap = (lo + hi) / 2
        if 4.5 <= gap <= 30:
            return n
    return 1  # fallback


def photon_src(E_keV, harmonic=1):
    """
    Replicate JS photonSrc(E) -- convolved source sizes.
    Returns (Sx, Sy, Sxp, Syp) in meters and radians.
    """
    lm = HC / E_keV * 1e-10   # wavelength [m]
    n = harmonic

    # Single-electron radiation sizes (Elleaume + Tanaka-Kitamura)
    srp = 0.69 * sqrt(lm / (2 * n * L_UND))
    sr  = 2.740 / (4 * pi) * sqrt(2 * lm * L_UND / n)

    # Energy spread broadening (Qa, Qs)
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
    rays[:, [0, 2]] = rays[:, [2, 0]]   # X <-> Z
    rays[:, [3, 5]] = rays[:, [5, 3]]   # X' <-> Z'
    return S4Beam(N=rays.shape[0], array=rays)


def run_shadow4_bl10(E_keV, ssa_um, nrays=500000, seed=12345, verbose=True,
                     hybrid=True):
    """
    Run Shadow4 ray trace for BL10 at given energy and SSA size.

    Parameters
    ----------
    E_keV : float   -- photon energy in keV
    ssa_um : float  -- SSA full gap in micrometers (symmetric H=V)
    nrays : int     -- number of rays
    seed : int      -- random seed
    hybrid : bool   -- apply hybrid wave-optics diffraction (SSA + KB mirrors)

    Returns
    -------
    dict with histogram, marginals, FWHM, centroid, etc.
    """
    E_eV = E_keV * 1000.0
    ssa_half = ssa_um * 0.5e-6  # half-gap in meters

    # -----------------------------------------------------------
    # 1. SOURCE: Gaussian with photonSrc(E) convolved sigmas
    # -----------------------------------------------------------
    n_harm = select_harmonic(E_keV)
    Sx, Sy, Sxp, Syp = photon_src(E_keV, harmonic=n_harm)

    if verbose:
        print(f"[Source] E={E_keV} keV, SSA={ssa_um} um, nrays={nrays}, harmonic={n_harm}")
        print(f"  Sx={Sx*1e6:.2f} um, Sy={Sy*1e6:.2f} um")
        print(f"  Sxp={Sxp*1e6:.2f} urad, Syp={Syp*1e6:.2f} urad")

    src = SourceGaussian(
        nrays=nrays,
        seed=seed,
        sigmaX=Sx,
        sigmaY=0.0,        # along-beam (not used)
        sigmaZ=Sy,          # vertical = Shadow4 Z
        sigmaXprime=Sxp,
        sigmaZprime=Syp,
    )

    beam0 = S4Beam()
    beam0.generate_source(src)
    beam0.set_photon_energy_eV(E_eV)

    n_start = beam0.get_number_of_rays(nolost=1)
    if verbose:
        print(f"  Source rays: {n_start}")

    # --- Swap X<->Z to emulate horizontal deflection ---
    # After swap: S4_X = real_V (Sy), S4_Z = real_H (Sx)
    # M1 sagittal focuses S4_X = Sy (small) -> V-focus (matches MC)
    # M2 tangential focuses S4_Z = Sx (large) -> H-focus (matches MC)
    beam0 = _swap_xz(beam0)

    # -----------------------------------------------------------
    # 2. M1: Spherical mirror, sagittal V-focus
    #    convexity=1 for focusing at grazing incidence
    #    (vertical deflection in S4, equivalent to horizontal via swap)
    # -----------------------------------------------------------
    p_m1 = POS['m1']                  # source to M1
    q_m1 = POS['dcm'] - POS['m1']    # M1 to DCM

    m1_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M1",
            boundary_shape=Rectangle(
                x_left=-M1_WID/2, x_right=M1_WID/2,
                y_bottom=-M1_LEN/2, y_top=M1_LEN/2
            ),
            is_cylinder=1,
            cylinder_direction=Direction.SAGITTAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1,
            p_focus=M1_P,
            q_focus=M1_Q,
            grazing_angle=THETA_GRAZ,
            f_reflec=0,
        ),
        coordinates=ElementCoordinates(
            p=p_m1, q=q_m1,
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam0,
    )
    beam1, _ = m1_el.trace_beam()
    if verbose:
        n1 = beam1.get_number_of_rays(nolost=1)
        print(f"[M1] {n1} good rays ({n1/n_start*100:.1f}%)")

    # -----------------------------------------------------------
    # 3. DCM: Si(111) double crystal, sequential
    # -----------------------------------------------------------
    dcm1_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM Crystal 1",
            boundary_shape=None,
            material="Si",
            miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0,
            is_thick=0,
            thickness=0.010,
            f_central=True,
            f_phot_cent=0,
            phot_cent=E_eV,
            file_refl="",
            f_bragg_a=False,
            f_ext=0,
        ),
        coordinates=ElementCoordinates(
            p=0.0, q=0.020,  # 20mm crystal gap
            angle_radial=0.0, angle_radial_out=0.0,
        ),
        input_beam=beam1,
    )
    beam2a, _ = dcm1_el.trace_beam()
    if verbose:
        n2a = beam2a.get_number_of_rays(nolost=1)
        print(f"[DCM-1] {n2a} good rays")

    dcm2_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM Crystal 2",
            boundary_shape=None,
            material="Si",
            miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0,
            is_thick=0,
            thickness=0.010,
            f_central=True,
            f_phot_cent=0,
            phot_cent=E_eV,
            file_refl="",
            f_bragg_a=False,
            f_ext=0,
        ),
        coordinates=ElementCoordinates(
            p=0.020, q=POS['m2'] - POS['dcm'],
            angle_radial=0.0, angle_radial_out=0.0,
        ),
        input_beam=beam2a,
    )
    beam2, _ = dcm2_el.trace_beam()
    if verbose:
        n2 = beam2.get_number_of_rays(nolost=1)
        print(f"[DCM-2] {n2} good rays ({n2/n_start*100:.1f}%)")

    # -----------------------------------------------------------
    # 4. M2: Spherical mirror, tangential H-focus
    #    convexity=1 for focusing at grazing incidence
    #    (vertical deflection in S4, equivalent to horizontal via swap)
    # -----------------------------------------------------------
    q_m2 = POS['ssa'] - POS['m2']  # M2 to SSA

    m2_el = S4SphereMirrorElement(
        optical_element=S4SphereMirror(
            name="M2",
            boundary_shape=Rectangle(
                x_left=-M2_WID/2, x_right=M2_WID/2,
                y_bottom=-M2_LEN/2, y_top=M2_LEN/2
            ),
            is_cylinder=1,
            cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1,
            p_focus=M2_P,
            q_focus=M2_Q,
            grazing_angle=THETA_GRAZ,
            f_reflec=0,
        ),
        coordinates=ElementCoordinates(
            p=0.0, q=q_m2,
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam2,
    )
    beam3, _ = m2_el.trace_beam()

    # --- Swap back X<->Z to restore real-world coordinates ---
    beam3 = _swap_xz(beam3)
    if verbose:
        n3 = beam3.get_number_of_rays(nolost=1)
        print(f"[M2] {n3} good rays ({n3/n_start*100:.1f}%)")
        print(f"  beam sigma_X: {beam3.get_standard_deviation(1, nolost=1)*1e6:.2f} um")
        print(f"  beam sigma_Z: {beam3.get_standard_deviation(3, nolost=1)*1e6:.2f} um")

    # -----------------------------------------------------------
    # 5. SSA: Rectangular aperture
    # -----------------------------------------------------------
    ssa_el = S4ScreenElement(
        optical_element=S4Screen(
            name="SSA",
            boundary_shape=Rectangle(
                x_left=-ssa_half, x_right=ssa_half,
                y_bottom=-ssa_half, y_top=ssa_half,
            ),
            i_abs=0, i_stop=0,
            thick=0.0, file_abs="",
        ),
        coordinates=ElementCoordinates(
            p=0.0, q=0.0,   # beam already at SSA; drift to KB-V handled by KB-V element
        ),
        input_beam=beam3,
    )
    beam4, _ = ssa_el.trace_beam()
    if verbose:
        n4 = beam4.get_number_of_rays(nolost=1)
        print(f"[SSA] {n4} good rays ({n4/n_start*100:.1f}%)")

    # -----------------------------------------------------------
    # 5b. SSA HYBRID: Fraunhofer slit diffraction (both H and V)
    # -----------------------------------------------------------
    if hybrid:
        try:
            ssa_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.SIMPLE_APERTURE)
            ssa_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam4),      # beam AFTER geometric SSA trace
                optical_element=S4HybridOE(optical_element=ssa_el),
                diffraction_plane=HybridDiffractionPlane.BOTH_2X1D,
                propagation_type=HybridPropagationType.FAR_FIELD,
                n_bins_x=200, n_bins_z=200, n_peaks=20,
                fft_n_pts=int(1e6),
                analyze_geometry=False,   # avoid attribute error on partial-cut case
                random_seed=0,
            )
            ssa_hyb_el = S4HybridScreenElement(
                hybrid_screen=ssa_hyb_screen,
                hybrid_input_parameters=ssa_hyb_inp)
            beam4 = _extract_hybrid_beam(ssa_hyb_el.trace_beam())
            if verbose:
                print(f"[SSA-hybrid] applied ({beam4.get_number_of_rays(nolost=1)} rays)")
        except Exception as e:
            if verbose:
                print(f"[SSA-hybrid] SKIPPED: {e}")

    # -----------------------------------------------------------
    # 6. KB-V: Ellipsoidal mirror, tangential V-focus
    #    convexity=1, p from SSA, q to sample
    # -----------------------------------------------------------
    p_kbv = POS['kbv'] - POS['ssa']     # 91.69 m from SSA
    q_kbv = POS['sample'] - POS['kbv']  # 0.31 m to sample

    kbv_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-V",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_V_LEN/2, y_top=KB_V_LEN/2,
            ),
            is_cylinder=True,
            cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1,
            p_focus=p_kbv,
            q_focus=q_kbv,
            grazing_angle=THETA_GRAZ,
            f_reflec=0,
        ),
        coordinates=ElementCoordinates(
            p=p_kbv,
            q=0.0,   # stay at mirror exit, drift to KB-H handled separately
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam4,
    )
    beam5, _ = kbv_el.trace_beam()
    if verbose:
        n5 = beam5.get_number_of_rays(nolost=1)
        print(f"[KB-V] {n5} good rays ({n5/n_start*100:.1f}%)")

    # -----------------------------------------------------------
    # 6b. KB-V HYBRID: Mirror finite-size diffraction (tangential)
    # -----------------------------------------------------------
    if hybrid:
        try:
            kbv_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbv_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam5),      # beam AFTER KB-V geometric trace
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
                print(f"[KB-V-hybrid] applied ({beam5.get_number_of_rays(nolost=1)} rays)")
        except Exception as e:
            if verbose:
                print(f"[KB-V-hybrid] SKIPPED: {e}")

    # Drift from KB-V to KB-H position
    dist_v_to_h = POS['kbh'] - POS['kbv']  # 0.21 m
    drift_el = S4ScreenElement(
        optical_element=S4Screen(name="drift_VH"),
        coordinates=ElementCoordinates(p=dist_v_to_h, q=0.0),
        input_beam=beam5,
    )
    beam5d, _ = drift_el.trace_beam()

    # -----------------------------------------------------------
    # 7. KB-H: Ellipsoidal mirror, sagittal H-focus
    #    Sagittal ellipsoid cylinder not supported in Shadow4 v0.1.70.
    #    Workaround: swap X<->Z, apply tangential ellipsoid, swap back.
    # -----------------------------------------------------------
    p_kbh = POS['kbh'] - POS['ssa']     # 91.90 m from SSA
    q_kbh = POS['sample'] - POS['kbh']  # 0.10 m to sample

    # Swap X<->Z so that the horizontal axis becomes "Z" (tangential focus axis)
    beam5s = _swap_xz(beam5d)

    kbh_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-H",
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-KB_H_LEN/2, y_top=KB_H_LEN/2,
            ),
            is_cylinder=True,
            cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1,
            p_focus=p_kbh,
            q_focus=q_kbh,
            grazing_angle=THETA_GRAZ,
            f_reflec=0,
        ),
        coordinates=ElementCoordinates(
            p=0.0,
            q=q_kbh,   # drift to sample
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam5s,
    )
    beam6s, _ = kbh_el.trace_beam()

    # -----------------------------------------------------------
    # 7b. KB-H HYBRID: Mirror finite-size diffraction (tangential,
    #     applied in swapped coordinate space then swapped back)
    # -----------------------------------------------------------
    if hybrid:
        try:
            kbh_hyb_screen = S4HybridScreen(
                calculation_type=HybridCalculationType.MIRROR_OR_GRATING_SIZE)
            kbh_hyb_inp = HybridInputParameters(
                listener=_QuietHybridListener(),
                beam=S4HybridBeam(beam=beam6s),     # beam AFTER KB-H geometric (still swapped)
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
                print(f"[KB-H-hybrid] applied ({beam6s.get_number_of_rays(nolost=1)} rays)")
        except Exception as e:
            if verbose:
                print(f"[KB-H-hybrid] SKIPPED: {e}")

    # Swap back X<->Z to restore original coordinate convention
    beam6 = _swap_xz(beam6s)

    if verbose:
        n6 = beam6.get_number_of_rays(nolost=1)
        print(f"[KB-H] {n6} good rays ({n6/n_start*100:.1f}%)")

    # -----------------------------------------------------------
    # 8. Extract beam profile at sample
    # -----------------------------------------------------------
    nbins = 201
    n_good = beam6.get_number_of_rays(nolost=1)

    if n_good < 10:
        print(f"[WARNING] Only {n_good} good rays at sample -- results unreliable")
        return None

    # 1D marginals with FWHM (calculate_widths=1 for Shadow4 v0.1.70)
    ticket_h = beam6.histo1(col=1, nbins=nbins, nolost=1, ref=23, calculate_widths=1)
    ticket_v = beam6.histo1(col=3, nbins=nbins, nolost=1, ref=23, calculate_widths=1)

    # 2D histogram
    ticket_2d = beam6.histo2(col_h=1, col_v=3, nbins=nbins, ref=23,
                             nolost=1, calculate_widths=1)

    fwhm_h = ticket_h.get('fwhm', 0)
    fwhm_v = ticket_v.get('fwhm', 0)
    centroid_h = float(np.mean(beam6.get_column(1, nolost=1)))
    centroid_v = float(np.mean(beam6.get_column(3, nolost=1)))

    # -----------------------------------------------------------
    # 8b. Tight-FOV histogram (same convention as MC fine grid)
    #     201 bins, +/-5*sigma centered on centroid, min 80nm
    # -----------------------------------------------------------
    rays_h = beam6.get_column(1, nolost=1)
    rays_v = beam6.get_column(3, nolost=1)
    weights = beam6.get_column(23, nolost=1)

    sig_h = float(np.sqrt(np.average((rays_h - centroid_h)**2, weights=weights)))
    sig_v = float(np.sqrt(np.average((rays_v - centroid_v)**2, weights=weights)))

    fine_fov_h = max(sig_h * 5, 80e-9)
    fine_fov_v = max(sig_v * 5, 80e-9)
    if fine_fov_h > 0.5e-6: fine_fov_h = 0.5e-6
    if fine_fov_v > 0.5e-6: fine_fov_v = 0.5e-6

    fine_nbins = 201
    fine_edges_h = np.linspace(centroid_h - fine_fov_h, centroid_h + fine_fov_h, fine_nbins + 1)
    fine_edges_v = np.linspace(centroid_v - fine_fov_v, centroid_v + fine_fov_v, fine_nbins + 1)
    fine_marg_h, _ = np.histogram(rays_h, bins=fine_edges_h, weights=weights)
    fine_marg_v, _ = np.histogram(rays_v, bins=fine_edges_v, weights=weights)
    fine_centers_h = 0.5 * (fine_edges_h[:-1] + fine_edges_h[1:])
    fine_centers_v = 0.5 * (fine_edges_v[:-1] + fine_edges_v[1:])

    # Compute FWHM from tight histogram (same method as MC _margFwhm)
    def _fwhm_from_hist(marg, nbins, half_fov):
        mx = np.max(marg)
        if mx <= 0: return 0
        hm = mx * 0.5
        x0, x1 = -1, -1
        for i in range(1, nbins):
            if marg[i-1] < hm <= marg[i] and x0 < 0:
                x0 = (i-1) + (hm - marg[i-1]) / (marg[i] - marg[i-1] + 1e-30)
            if marg[i-1] >= hm > marg[i]:
                x1 = (i-1) + (hm - marg[i-1]) / (marg[i] - marg[i-1] - 1e-30)
        if x0 < 0 or x1 < 0: return 0
        return (x1 - x0) * (2 * half_fov / nbins)

    fine_fwhm_h = _fwhm_from_hist(fine_marg_h, fine_nbins, fine_fov_h)
    fine_fwhm_v = _fwhm_from_hist(fine_marg_v, fine_nbins, fine_fov_v)

    # -----------------------------------------------------------
    # 8c. Unified-FOV histogram: 301 bins, +/-150nm (matching MC)
    # -----------------------------------------------------------
    UNI_NBINS = 301
    UNI_FOV = 150e-9   # +/-150 nm
    uni_edges_h = np.linspace(centroid_h - UNI_FOV, centroid_h + UNI_FOV, UNI_NBINS + 1)
    uni_edges_v = np.linspace(centroid_v - UNI_FOV, centroid_v + UNI_FOV, UNI_NBINS + 1)
    uni_marg_h, _ = np.histogram(rays_h, bins=uni_edges_h, weights=weights)
    uni_marg_v, _ = np.histogram(rays_v, bins=uni_edges_v, weights=weights)
    uni_hist2d, _, _ = np.histogram2d(rays_h, rays_v,
                                       bins=[uni_edges_h, uni_edges_v],
                                       weights=weights)
    uni_centers = np.linspace(-UNI_FOV, UNI_FOV, UNI_NBINS)
    uni_fwhm_h = _fwhm_from_hist(uni_marg_h, UNI_NBINS, UNI_FOV)
    uni_fwhm_v = _fwhm_from_hist(uni_marg_v, UNI_NBINS, UNI_FOV)

    if verbose:
        print(f"\n[RESULT] Sample beam profile @ {E_keV} keV, SSA={ssa_um} um")
        print(f"  FWHM_H = {fwhm_h*1e9:.1f} nm  (auto-range)")
        print(f"  FWHM_V = {fwhm_v*1e9:.1f} nm  (auto-range)")
        print(f"  FWHM_H = {fine_fwhm_h*1e9:.1f} nm  (tight 5sig, {fine_nbins} bins)")
        print(f"  FWHM_V = {fine_fwhm_v*1e9:.1f} nm  (tight 5sig, {fine_nbins} bins)")
        print(f"  FWHM_H = {uni_fwhm_h*1e9:.1f} nm  (unified +/-150nm, {UNI_NBINS} bins)")
        print(f"  FWHM_V = {uni_fwhm_v*1e9:.1f} nm  (unified +/-150nm, {UNI_NBINS} bins)")
        print(f"  sig_H = {sig_h*1e9:.1f} nm, FOV_H = +/-{fine_fov_h*1e9:.1f} nm")
        print(f"  sig_V = {sig_v*1e9:.1f} nm, FOV_V = +/-{fine_fov_v*1e9:.1f} nm")
        print(f"  Centroid_H = {centroid_h*1e9:.1f} nm")
        print(f"  Centroid_V = {centroid_v*1e9:.1f} nm")
        print(f"  Throughput = {n_good}/{nrays} = {n_good/nrays*100:.2f}%")

    # Build result dict
    result = {
        "engine": "shadow4_hybrid" if hybrid else "shadow4",
        "energy_keV": E_keV,
        "ssa_um": ssa_um,
        "nrays_total": nrays,
        "nrays_good": int(n_good),
        "fwhm_h_m": float(fwhm_h) if fwhm_h else None,
        "fwhm_v_m": float(fwhm_v) if fwhm_v else None,
        "centroid_h_m": centroid_h,
        "centroid_v_m": centroid_v,
        "source_Sx_m": Sx,
        "source_Sy_m": Sy,
        "source_Sxp_rad": Sxp,
        "source_Syp_rad": Syp,
        # Original auto-range histogram data
        "hist2d": ticket_2d['histogram'].tolist() if ticket_2d.get('histogram') is not None else None,
        "marg_h": ticket_h['histogram'].tolist() if ticket_h.get('histogram') is not None else None,
        "marg_v": ticket_v['histogram'].tolist() if ticket_v.get('histogram') is not None else None,
        "bin_h_center": ticket_h['bin_center'].tolist() if ticket_h.get('bin_center') is not None else None,
        "bin_v_center": ticket_v['bin_center'].tolist() if ticket_v.get('bin_center') is not None else None,
        "nbins": nbins,
        # Tight-FOV histogram (unified convention: 201 bins, +/-5*sigma)
        "fine_marg_h": fine_marg_h.tolist(),
        "fine_marg_v": fine_marg_v.tolist(),
        "fine_fov_h_m": fine_fov_h,
        "fine_fov_v_m": fine_fov_v,
        "fine_fwhm_h_m": fine_fwhm_h,
        "fine_fwhm_v_m": fine_fwhm_v,
        "fine_grid": fine_nbins,
        "fine_sig_h_m": sig_h,
        "fine_sig_v_m": sig_v,
        # Unified-FOV histogram (301 bins, +/-150nm, matching MC)
        "uni_hist2d": uni_hist2d.tolist(),
        "uni_marg_h": uni_marg_h.tolist(),
        "uni_marg_v": uni_marg_v.tolist(),
        "uni_bin_center": uni_centers.tolist(),
        "uni_nbins": UNI_NBINS,
        "uni_fov_m": UNI_FOV,
        "uni_fwhm_h_m": uni_fwhm_h,
        "uni_fwhm_v_m": uni_fwhm_v,
    }
    return result


# ==============================================================
#  MAIN
# ==============================================================
if __name__ == '__main__':
    import statistics as _stat

    N_RAYS = 200000       # match MC ray count
    N_REPEATS = 5         # match MC repeat count
    SEEDS = [12345, 23456, 34567, 45678, 56789]

    CONDITIONS = [
        {"energy": 10.0, "ssa": 50,  "label": "10keV_ssa50"},
        {"energy": 5.0,  "ssa": 50,  "label": "5keV_ssa50"},
        {"energy": 20.0, "ssa": 50,  "label": "20keV_ssa50"},
        {"energy": 10.0, "ssa": 10,  "label": "10keV_ssa10"},
        {"energy": 10.0, "ssa": 200, "label": "10keV_ssa200"},
    ]

    out_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(out_dir, exist_ok=True)

    for cond in CONDITIONS:
        print(f"\n{'='*60}")
        print(f"  Condition: {cond['label']}  ({N_RAYS} rays x {N_REPEATS} repeats)")
        print(f"{'='*60}")

        fwhm_h_list = []
        fwhm_v_list = []
        fine_fwhm_h_list = []
        fine_fwhm_v_list = []
        n_good_list = []
        all_results = []

        for rep in range(N_REPEATS):
            t0 = time.time()
            result = run_shadow4_bl10(
                E_keV=cond['energy'],
                ssa_um=cond['ssa'],
                nrays=N_RAYS,
                seed=SEEDS[rep],
                verbose=(rep == 0),   # verbose only for first run
            )
            elapsed = time.time() - t0

            if result is None:
                print(f"  Rep {rep+1}: FAILED ({elapsed:.1f}s)")
                continue

            fh = result.get('fwhm_h_m', 0) or 0
            fv = result.get('fwhm_v_m', 0) or 0
            ffh = result.get('fine_fwhm_h_m', 0) or 0
            ffv = result.get('fine_fwhm_v_m', 0) or 0
            ng = result.get('nrays_good', 0)

            fwhm_h_list.append(fh)
            fwhm_v_list.append(fv)
            fine_fwhm_h_list.append(ffh)
            fine_fwhm_v_list.append(ffv)
            n_good_list.append(ng)
            all_results.append(result)

            print(f"  Rep {rep+1}: FWHM_H={ffh*1e9:.1f}nm, FWHM_V={ffv*1e9:.1f}nm, "
                  f"survived={ng}/{N_RAYS} ({elapsed:.1f}s)")

        if not fwhm_h_list:
            print(f"  ALL REPEATS FAILED for {cond['label']}")
            continue

        # Pick the run with most survived rays for best histogram quality
        best_idx = max(range(len(all_results)), key=lambda i: all_results[i]['nrays_good'])
        best = all_results[best_idx]

        # Add repeat statistics to best result
        n_runs = len(fwhm_h_list)
        best['n_repeats'] = n_runs
        best['fwhm_h_mean_m'] = _stat.mean(fwhm_h_list)
        best['fwhm_v_mean_m'] = _stat.mean(fwhm_v_list)
        best['fwhm_h_std_m'] = _stat.stdev(fwhm_h_list) if n_runs > 1 else 0
        best['fwhm_v_std_m'] = _stat.stdev(fwhm_v_list) if n_runs > 1 else 0
        best['fine_fwhm_h_mean_m'] = _stat.mean(fine_fwhm_h_list)
        best['fine_fwhm_v_mean_m'] = _stat.mean(fine_fwhm_v_list)
        best['fine_fwhm_h_std_m'] = _stat.stdev(fine_fwhm_h_list) if n_runs > 1 else 0
        best['fine_fwhm_v_std_m'] = _stat.stdev(fine_fwhm_v_list) if n_runs > 1 else 0
        best['nrays_good_mean'] = _stat.mean(n_good_list)

        print(f"\n  Summary ({n_runs} runs):")
        print(f"    Fine FWHM_H = {best['fine_fwhm_h_mean_m']*1e9:.1f} +/- {best['fine_fwhm_h_std_m']*1e9:.1f} nm")
        print(f"    Fine FWHM_V = {best['fine_fwhm_v_mean_m']*1e9:.1f} +/- {best['fine_fwhm_v_std_m']*1e9:.1f} nm")
        print(f"    Auto FWHM_H = {best['fwhm_h_mean_m']*1e9:.1f} +/- {best['fwhm_h_std_m']*1e9:.1f} nm")
        print(f"    Auto FWHM_V = {best['fwhm_v_mean_m']*1e9:.1f} +/- {best['fwhm_v_std_m']*1e9:.1f} nm")
        print(f"    Best run: rep {best_idx+1}, N={best['nrays_good']}")

        fname = os.path.join(out_dir, f"s4_{cond['label']}.json")
        with open(fname, 'w') as f:
            json.dump(best, f, indent=2)
        print(f"    Saved: {fname}")

    print("\nAll conditions complete.")
