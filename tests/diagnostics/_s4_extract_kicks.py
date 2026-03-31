"""
Extract kick distributions from Shadow4's hybrid calculation internals.
=====================================================================
Manually replicates the hybrid diffraction pipeline for KB-V and KB-H
to extract the ACTUAL diffraction kick distributions separately from
the geometric ray tracing, answering:

1. What is the ACTUAL kick FWHM from S4's diffraction pattern?
2. Does the total FWHM follow quadrature or is it sub-quadrature?
3. Does intensity-weighting vs unweighting change the result?

Usage:
    conda run -n oasys_env python _s4_extract_kicks.py
"""

import os, sys, copy, time
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

from srxraylib.util.inverse_method_sampler import Sampler1D
from scipy.interpolate import interp1d


# ==============================================================
#  Ring & IVU24 Parameters
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
    'xbpm1':  31.2,
    'xbpm2':  57.0,
    'ssa':    58.0,
    'kbv':    149.69,
    'kbh':    149.90,
    'sample': 150.0,
}

M1_P = 30.4
M1_Q = 27.6
M2_P = 33.0
M2_Q = 25.0

KB_V_LEN = 0.300
KB_H_LEN = 0.100
M1_LEN = 0.600
M1_WID = 0.060
M2_LEN = 0.400
M2_WID = 0.040
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


def measure_fwhm_histogram(data, nbins=300):
    """
    Measure FWHM from a histogram of sample data.
    Returns FWHM in the same units as the input data.
    """
    h, edges = np.histogram(data, bins=nbins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    h = h.astype(float)
    mx = np.max(h)
    if mx <= 0:
        return 0.0
    hm = mx * 0.5

    # Find left crossing
    x0 = None
    for i in range(1, len(h)):
        if h[i-1] < hm <= h[i]:
            frac = (hm - h[i-1]) / (h[i] - h[i-1] + 1e-30)
            x0 = centers[i-1] + frac * (centers[i] - centers[i-1])
            break

    # Find right crossing
    x1 = None
    for i in range(1, len(h)):
        if h[i-1] >= hm > h[i]:
            frac = (hm - h[i-1]) / (h[i] - h[i-1] - 1e-30)
            x1 = centers[i-1] + frac * (centers[i] - centers[i-1])

    if x0 is None or x1 is None:
        return 0.0
    return x1 - x0


def build_beamline_to_ssa(E_keV, ssa_um, nrays, seed):
    """
    Build and trace the full S4 beamline from source to SSA exit.
    Returns beam at SSA (geometric only, no hybrid).
    """
    E_eV = E_keV * 1000.0
    ssa_half = ssa_um * 0.5e-6

    Sx, Sy, Sxp, Syp = photon_src(E_keV, harmonic=3)
    print(f"[Source] E={E_keV} keV, SSA={ssa_um} um, nrays={nrays}")
    print(f"  Sx={Sx*1e6:.2f} um, Sy={Sy*1e6:.2f} um")
    print(f"  Sxp={Sxp*1e6:.2f} urad, Syp={Syp*1e6:.2f} urad")

    src = SourceGaussian(
        nrays=nrays, seed=seed,
        sigmaX=Sx, sigmaY=0.0, sigmaZ=Sy,
        sigmaXprime=Sxp, sigmaZprime=Syp,
    )
    beam0 = S4Beam()
    beam0.generate_source(src)
    beam0.set_photon_energy_eV(E_eV)

    n_start = beam0.get_number_of_rays(nolost=1)
    print(f"  Source rays: {n_start}")

    # M1: Spherical mirror, sagittal H-focus
    p_m1 = POS['m1']
    q_m1 = POS['dcm'] - POS['m1']
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
            convexity=1, p_focus=M1_P, q_focus=M1_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=p_m1, q=q_m1, angle_radial=ANGLE_RAD),
        input_beam=beam0,
    )
    beam1, _ = m1_el.trace_beam()
    n1 = beam1.get_number_of_rays(nolost=1)
    print(f"[M1] {n1} good rays ({n1/n_start*100:.1f}%)")

    # DCM: Si(111) double crystal
    dcm1_el = S4PlaneCrystalElement(
        optical_element=S4PlaneCrystal(
            name="DCM Crystal 1", boundary_shape=None,
            material="Si", miller_index_h=1, miller_index_k=1, miller_index_l=1,
            asymmetry_angle=0.0, is_thick=0, thickness=0.010,
            f_central=True, f_phot_cent=0, phot_cent=E_eV,
            file_refl="", f_bragg_a=False, f_ext=0,
        ),
        coordinates=ElementCoordinates(
            p=0.0, q=0.020,
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0,
        ),
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
        coordinates=ElementCoordinates(
            p=0.020, q=POS['m2'] - POS['dcm'],
            angle_radial=0.0, angle_azimuthal=0.0, angle_radial_out=0.0,
        ),
        input_beam=beam2a,
    )
    beam2, _ = dcm2_el.trace_beam()
    n2 = beam2.get_number_of_rays(nolost=1)
    print(f"[DCM] {n2} good rays ({n2/n_start*100:.1f}%)")

    # M2: Spherical mirror, tangential V-focus
    q_m2 = POS['ssa'] - POS['m2']
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
            convexity=1, p_focus=M2_P, q_focus=M2_Q,
            grazing_angle=THETA_GRAZ, f_reflec=0,
        ),
        coordinates=ElementCoordinates(p=0.0, q=q_m2, angle_radial=ANGLE_RAD),
        input_beam=beam2,
    )
    beam3, _ = m2_el.trace_beam()
    n3 = beam3.get_number_of_rays(nolost=1)
    print(f"[M2] {n3} good rays ({n3/n_start*100:.1f}%)")

    # SSA: Rectangular aperture
    ssa_el = S4ScreenElement(
        optical_element=S4Screen(
            name="SSA",
            boundary_shape=Rectangle(
                x_left=-ssa_half, x_right=ssa_half,
                y_bottom=-ssa_half, y_top=ssa_half,
            ),
            i_abs=0, i_stop=0, thick=0.0, file_abs="",
        ),
        coordinates=ElementCoordinates(p=0.0, q=0.0),
        input_beam=beam3,
    )
    beam4, _ = ssa_el.trace_beam()
    n4 = beam4.get_number_of_rays(nolost=1)
    print(f"[SSA] {n4} good rays ({n4/n_start*100:.1f}%)")

    return beam4, n_start


def extract_kicks_for_mirror(beam_input, mirror_name, p_focus, q_focus, mirror_len,
                             col_pos, col_dir, q_image, n_bins_param=200,
                             n_peaks=20, fft_n_pts=1000000, random_seed=0,
                             is_swapped=False, p_coord=None):
    """
    Extract kick distribution for a KB mirror by manually replicating
    the hybrid calculation pipeline.

    Parameters
    ----------
    beam_input : S4Beam
        Input beam at mirror entrance (already traced to mirror position)
    mirror_name : str
        "KB-V" or "KB-H"
    p_focus, q_focus : float
        Object/image distances for the mirror
    mirror_len : float
        Mirror length in meters
    col_pos : int
        Column for position (0=X, 2=Z) -- at mirror surface
    col_dir : int
        Column for direction cosine (3=Xp, 5=Zp) -- at mirror surface
    q_image : float
        Image distance (mirror to sample)
    n_bins_param : int
        Number of histogram bins
    n_peaks : int
        Number of peaks for f_ff calculation
    fft_n_pts : int
        Max FFT points
    random_seed : int
        Random seed for sampling
    is_swapped : bool
        If True, beam has been X<->Z swapped (KB-H trick)
    p_coord : float or None
        Coordinate p value (drift before mirror). If None, uses p_focus.
        Use 0.0 when beam is already at the mirror position.
    """
    if p_coord is None:
        p_coord = p_focus

    print(f"\n{'='*70}")
    print(f"  EXTRACT KICKS: {mirror_name}")
    print(f"  p_focus={p_focus:.2f} m, q_focus={q_focus:.3f} m, L={mirror_len*1e3:.0f} mm")
    print(f"  p_coord={p_coord:.2f} m (drift before mirror)")
    print(f"  col_pos={col_pos}, col_dir={col_dir}")
    print(f"{'='*70}")

    # ---- Step 1: Create the mirror element and trace geometrically ----
    kbv_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name=mirror_name,
            boundary_shape=Rectangle(
                x_left=-KB_WID/2, x_right=KB_WID/2,
                y_bottom=-mirror_len/2, y_top=mirror_len/2,
            ),
            is_cylinder=True,
            cylinder_direction=Direction.TANGENTIAL,
            surface_calculation=SurfaceCalculation.INTERNAL,
            convexity=1,
            p_focus=p_focus,
            q_focus=q_focus,
            grazing_angle=THETA_GRAZ,
            f_reflec=0,
        ),
        coordinates=ElementCoordinates(
            p=p_coord,
            q=q_image,   # trace to image plane
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam_input,
    )
    beam_at_image, footprint = kbv_el.trace_beam()

    n_good_image = beam_at_image.get_number_of_rays(nolost=1)
    print(f"\n[Geometric trace] {n_good_image} good rays at image")

    # For tangential: col_pos=2 (Z), col_dir=5 (Zp) after swapping for KB-H
    # Since we always use tangential direction here, the relevant columns are Z (col 2) and Zp (col 5)
    # regardless of which mirror, because KB-H beam is already swapped

    # ---- Step 2: Retrace beam back to mirror surface ----
    # This replicates: hybrid_screen_beam.retrace(-coordinates.q())
    hybrid_screen_beam = beam_at_image.duplicate()
    # Filter to good rays only (same as hybrid does)
    hybrid_screen_beam.rays = hybrid_screen_beam.rays[np.where(hybrid_screen_beam.rays[:, 9] == 1)]
    hybrid_screen_beam.retrace(-q_image)

    # ---- Step 3: Get positions and angles at mirror surface ----
    # For tangential direction, always col 2 (Z) and col 5 (Zp)
    zz_screen = hybrid_screen_beam.rays[:, 2]   # Z positions at mirror
    zp_screen = hybrid_screen_beam.rays[:, 5]   # Z direction cosine
    yp_screen = hybrid_screen_beam.rays[:, 4]   # Y direction cosine
    xp_screen = hybrid_screen_beam.rays[:, 3]   # X direction cosine

    dz_rays = np.arctan(zp_screen / yp_screen)  # geometric divergence angle

    z_min = np.min(zz_screen)
    z_max = np.max(zz_screen)
    D = z_max - z_min  # projected footprint width

    print(f"\n[Mirror footprint]")
    print(f"  z_min = {z_min*1e6:.1f} um")
    print(f"  z_max = {z_max*1e6:.1f} um")
    print(f"  D = z_max - z_min = {D*1e6:.1f} um")
    print(f"  Expected mirror length = {mirror_len*1e3:.0f} mm")
    print(f"  Footprint / mirror = {D/mirror_len*100:.1f}%")

    n_rays_good = len(zz_screen)
    print(f"  Good rays at mirror surface: {n_rays_good}")

    # ---- Step 4: Geometric divergence statistics ----
    print(f"\n[Geometric divergence at mirror]")
    print(f"  dz_rays mean = {np.mean(dz_rays)*1e6:.4f} urad")
    print(f"  dz_rays std  = {np.std(dz_rays)*1e6:.4f} urad")
    print(f"  dz_rays FWHM ~ {np.std(dz_rays)*2.355*1e6:.4f} urad")

    # ---- Step 5: Compute geometric image positions ----
    # This is what S4 does in _convolve_wavefront_with_rays
    z_geo_image = zz_screen + q_image * np.tan(dz_rays)
    z_geo_fwhm = measure_fwhm_histogram(z_geo_image, nbins=300) * 1e9
    print(f"\n[Geometric focus at image]")
    print(f"  Geometric image FWHM = {z_geo_fwhm:.1f} nm")
    print(f"  Geometric image std  = {np.std(z_geo_image)*1e9:.1f} nm")

    # ---- Step 6: Get wavelength ----
    energy = hybrid_screen_beam.get_photon_energy_eV()
    wavelength = np.average(hybrid_screen_beam.get_photon_wavelength())
    print(f"\n[Wavelength]")
    print(f"  Energy = {np.average(energy):.1f} eV")
    print(f"  Lambda = {wavelength*1e10:.4f} A = {wavelength*1e9:.6f} nm")

    # ---- Step 7: Compute n_bins (same as hybrid) ----
    n_bins = min(n_bins_param, round(n_rays_good / 20))
    n_bins = max(n_bins, 10)
    print(f"\n[Histogram parameters]")
    print(f"  n_bins = {n_bins} (from min({n_bins_param}, {n_rays_good}//20))")

    # ---- Step 8: Make intensity-weighted histogram at mirror surface ----
    # ref=23 means weight by intensity (column 23 = |E|^2)
    ticket_w = hybrid_screen_beam.histo1(3, nbins=int(n_bins),
                                          xrange=[z_min, z_max],
                                          nolost=1, ref=23)
    hist_weighted = ticket_w['histogram']
    bins_w = ticket_w['bins']

    # Also make unweighted histogram
    ticket_u = hybrid_screen_beam.histo1(3, nbins=int(n_bins),
                                          xrange=[z_min, z_max],
                                          nolost=1, ref=0)
    hist_unweighted = ticket_u['histogram']
    bins_u = ticket_u['bins']

    print(f"\n[Histogram comparison: intensity-weighted vs unweighted]")
    print(f"  Weighted:   min={hist_weighted.min():.3f}, max={hist_weighted.max():.3f}, "
          f"ratio max/min={hist_weighted.max()/(hist_weighted.min()+1e-30):.2f}")
    print(f"  Unweighted: min={hist_unweighted.min():.0f}, max={hist_unweighted.max():.0f}, "
          f"ratio max/min={hist_unweighted.max()/(hist_unweighted.min()+1e-30):.2f}")
    print(f"  Weighted std/mean = {np.std(hist_weighted)/np.mean(hist_weighted):.4f}")
    print(f"  Unweighted std/mean = {np.std(hist_unweighted)/np.mean(hist_unweighted):.4f}")

    # ---- Step 9: Compute f_ff (far-field focal length) ----
    # Exact same formula as hybrid: f_ff = D^2 / (n_peaks * 2 * 0.88 * lambda)
    f_ff = D**2 / (n_peaks * 2 * 0.88 * wavelength)
    print(f"\n[Far-field focal length]")
    print(f"  f_ff = D^2 / (n_peaks * 2 * 0.88 * lambda)")
    print(f"  f_ff = ({D*1e6:.1f} um)^2 / ({n_peaks} * 2 * 0.88 * {wavelength*1e10:.4f} A)")
    print(f"  f_ff = {f_ff:.4f} m")
    print(f"  q_image = {q_image:.4f} m")
    print(f"  f_ff / q_image = {f_ff/q_image:.2f}")

    # ---- Step 10: Compute FFT size (same as hybrid) ----
    fft_size_raw = int(min(100 * D**2 / (wavelength * f_ff * 0.88), fft_n_pts))
    # Round up to power of 2
    N_fft = 1
    while N_fft < fft_size_raw:
        N_fft *= 2
    if N_fft > 131072:
        N_fft = 131072
    # Actually the hybrid uses the raw value, not power of 2
    N_fft = fft_size_raw
    print(f"\n[FFT parameters]")
    print(f"  fft_size_raw = {fft_size_raw}")
    print(f"  Using N_fft = {N_fft}")

    delta = (z_max - z_min) / (N_fft - 1)
    print(f"  delta = {delta*1e9:.4f} nm")

    # ---- Step 11: Create wavefront grid ----
    z_grid = np.linspace(z_min, z_max, N_fft)

    # ---- Step 12: Run the full Fresnel pipeline for WEIGHTED histogram ----
    def run_fresnel_pipeline(hist_vals, bin_positions, label):
        """
        Run the Fresnel propagation pipeline exactly as S4 hybrid does it.
        Returns (dif_zp_values, dif_zp_scale) - the angular diffraction pattern.
        """
        print(f"\n  --- Fresnel pipeline ({label}) ---")

        # S4 uses ScaledArray.initialize_from_range(histogram, bins[0], bins[-1])
        # Then interpolates onto the wavefront grid
        # The bin_positions from histo1 are bin edges (not centers)
        # ScaledArray uses the range [bins[0], bins[-1]] with len(histogram) points

        # Create interpolation from histogram
        n_hist = len(hist_vals)
        hist_positions = np.linspace(bin_positions[0], bin_positions[-1], n_hist)

        # S4 wavefront: initialize_from_range creates uniform grid
        # wavefront amplitude = sqrt(interpolated_histogram)
        interp_func = interp1d(hist_positions, hist_vals, kind='linear',
                               fill_value=0, bounds_error=False)
        hist_on_grid = interp_func(z_grid)
        hist_on_grid = np.maximum(hist_on_grid, 0)

        # Wavefront: sqrt(intensity) with thin-lens phase
        k = 2 * np.pi / wavelength
        amplitude = np.sqrt(hist_on_grid)
        # Phase shift: -k * x^2 / (2 * f_ff)  (ideal thin lens)
        phase = -k * z_grid**2 / (2 * f_ff)
        wavefront = amplitude * np.exp(1j * phase)

        print(f"    Amplitude: min={amplitude.min():.4f}, max={amplitude.max():.4f}")
        print(f"    Phase range: {phase.min():.4f} to {phase.max():.4f} rad")

        # Fresnel Transfer Function propagation over distance f_ff
        freqs = np.fft.fftfreq(N_fft, d=delta)
        H = np.exp(-1j * np.pi * wavelength * f_ff * freqs**2)
        propagated = np.fft.ifft(np.fft.fft(wavefront) * H)

        # Extract image region (same as hybrid)
        image_size = min(abs(z_max), abs(z_min)) * 2
        image_size_alt = n_peaks * 2 * 0.88 * wavelength * f_ff / abs(z_max - z_min)
        image_size = min(image_size, image_size_alt)
        print(f"    image_size = {image_size*1e6:.4f} um")
        print(f"    image_size (sym) = {min(abs(z_max), abs(z_min))*2*1e6:.4f} um")
        print(f"    image_size (peaks) = {image_size_alt*1e6:.4f} um")

        prop_delta = delta  # same grid spacing
        image_n_pts = int(round(image_size / prop_delta / 2) * 2 + 1)
        print(f"    image_n_pts = {image_n_pts}")

        half_pts = (image_n_pts - 1) / 2

        # Create image position array (spatial coordinates)
        image_positions = (np.arange(image_n_pts) - half_pts) * prop_delta

        # Interpolate propagated wavefront at image positions
        intensity = np.zeros(image_n_pts)
        for i in range(image_n_pts):
            pos = image_positions[i]
            # Convert to grid index
            idx_float = (pos - z_min) / delta
            i0 = int(np.floor(idx_float))
            i1 = i0 + 1
            if 0 <= i0 and i1 < N_fft:
                frac = idx_float - i0
                amp = propagated[i0] + (propagated[i1] - propagated[i0]) * frac
                intensity[i] = abs(amp)**2

        # Convert spatial axis to angular axis (same as hybrid: divide by f_ff)
        ang_positions = image_positions / f_ff

        print(f"    Angular range: {ang_positions[0]*1e6:.4f} to {ang_positions[-1]*1e6:.4f} urad")
        print(f"    Intensity: min={intensity.min():.6f}, max={intensity.max():.6f}")

        # FWHM of diffraction pattern itself
        diff_fwhm_ang = measure_fwhm_histogram(
            np.repeat(ang_positions, np.maximum(1, (intensity / intensity.max() * 1000).astype(int))),
            nbins=300
        )
        # Better: measure from the array directly
        hm_level = intensity.max() * 0.5
        left_idx = None
        right_idx = None
        for i in range(1, len(intensity)):
            if intensity[i-1] < hm_level <= intensity[i] and left_idx is None:
                frac = (hm_level - intensity[i-1]) / (intensity[i] - intensity[i-1] + 1e-30)
                left_idx = ang_positions[i-1] + frac * (ang_positions[i] - ang_positions[i-1])
            if intensity[i-1] >= hm_level > intensity[i]:
                frac = (hm_level - intensity[i-1]) / (intensity[i] - intensity[i-1] - 1e-30)
                right_idx = ang_positions[i-1] + frac * (ang_positions[i] - ang_positions[i-1])
        if left_idx is not None and right_idx is not None:
            diff_pattern_fwhm = right_idx - left_idx
            print(f"    Diffraction pattern angular FWHM = {diff_pattern_fwhm*1e6:.4f} urad")
            print(f"    Diffraction pattern spatial FWHM at image = {diff_pattern_fwhm*q_image*1e9:.1f} nm")
        else:
            diff_pattern_fwhm = 0
            print(f"    Diffraction pattern FWHM: could not determine")

        return intensity, ang_positions, diff_pattern_fwhm

    # ---- Run for WEIGHTED histogram ----
    print(f"\n{'='*50}")
    print(f"  WEIGHTED (ref=23) histogram")
    print(f"{'='*50}")
    int_w, ang_w, diff_fwhm_w = run_fresnel_pipeline(hist_weighted, bins_w, "weighted")

    # ---- Run for UNWEIGHTED histogram ----
    print(f"\n{'='*50}")
    print(f"  UNWEIGHTED (ref=0) histogram")
    print(f"{'='*50}")
    int_u, ang_u, diff_fwhm_u = run_fresnel_pipeline(hist_unweighted, bins_u, "unweighted")

    # ---- Step 13: Sample kicks from diffraction patterns ----
    print(f"\n{'='*50}")
    print(f"  SAMPLING AND CONVOLUTION")
    print(f"{'='*50}")

    def sample_and_convolve(intensity, ang_positions, label, seed_offset=0):
        """Sample from diffraction pattern and convolve with geometric rays."""
        s1d = Sampler1D(intensity, ang_positions)
        n_samples = len(zz_screen)
        pos_dif = s1d.get_n_sampled_points(n_samples,
                                            seed=None if random_seed is None else (random_seed + 1 + seed_offset))

        # Kick statistics
        kick_ang_std = np.std(pos_dif)
        kick_ang_fwhm = measure_fwhm_histogram(pos_dif, nbins=300)
        kick_spatial = pos_dif * q_image
        kick_spatial_fwhm = measure_fwhm_histogram(kick_spatial, nbins=300) * 1e9

        print(f"\n  [{label}] Kick distribution:")
        print(f"    Angular kick mean = {np.mean(pos_dif)*1e6:.6f} urad")
        print(f"    Angular kick std  = {kick_ang_std*1e6:.4f} urad")
        print(f"    Angular kick FWHM = {kick_ang_fwhm*1e6:.4f} urad")
        print(f"    Spatial kick FWHM = {kick_spatial_fwhm:.1f} nm (= ang_FWHM * q)")

        # Convolve: add diffraction kicks to geometric angles
        dz_conv = np.arctan(pos_dif) + dz_rays
        z_total = zz_screen + q_image * np.tan(dz_conv)
        total_fwhm = measure_fwhm_histogram(z_total, nbins=300) * 1e9

        quadrature = np.sqrt(z_geo_fwhm**2 + kick_spatial_fwhm**2)

        print(f"\n  [{label}] Total (convolved):")
        print(f"    Geometric FWHM  = {z_geo_fwhm:.1f} nm")
        print(f"    Kick FWHM       = {kick_spatial_fwhm:.1f} nm")
        print(f"    Total FWHM      = {total_fwhm:.1f} nm")
        print(f"    Quadrature      = {quadrature:.1f} nm")
        if quadrature > 0:
            print(f"    Total/Quadrature = {total_fwhm/quadrature:.4f}")

        return pos_dif, kick_spatial_fwhm, total_fwhm, quadrature

    pos_dif_w, kick_w, total_w, quad_w = sample_and_convolve(int_w, ang_w, "WEIGHTED")
    pos_dif_u, kick_u, total_u, quad_u = sample_and_convolve(int_u, ang_u, "UNWEIGHTED", seed_offset=100)

    # ---- Step 14: Diffraction limit check ----
    # Rayleigh criterion: theta_diff = 0.44 * lambda / a
    # where a is the half-aperture (mirror half-length projected)
    mirror_proj = mirror_len * np.sin(THETA_GRAZ)  # projected mirror length
    rayleigh_angle = 0.44 * wavelength / (mirror_proj / 2)
    rayleigh_spatial = rayleigh_angle * q_image
    airy_fwhm = 0.44 * wavelength / (mirror_proj / 2) * q_image  # Airy disk FWHM ~ 1.03 * lambda / D
    # More precisely: FWHM of Airy = 1.029 * lambda * f/D
    airy_exact = 1.029 * wavelength * q_image / mirror_proj  # using f=q for mirror

    print(f"\n  [Diffraction limit]")
    print(f"    Mirror projected length = {mirror_proj*1e6:.1f} um")
    print(f"    Rayleigh angle (0.44*lam/half_L) = {rayleigh_angle*1e6:.4f} urad")
    print(f"    Rayleigh spatial = {rayleigh_spatial*1e9:.1f} nm")
    print(f"    Airy FWHM (1.029*lam*q/L_proj) = {airy_exact*1e9:.1f} nm")

    # ---- Summary ----
    print(f"\n{'='*70}")
    print(f"  SUMMARY: {mirror_name}")
    print(f"{'='*70}")
    print(f"  Geometric FWHM      = {z_geo_fwhm:.1f} nm")
    print(f"  Kick FWHM (weighted)   = {kick_w:.1f} nm")
    print(f"  Kick FWHM (unweighted) = {kick_u:.1f} nm")
    print(f"  Total FWHM (weighted)   = {total_w:.1f} nm")
    print(f"  Total FWHM (unweighted) = {total_u:.1f} nm")
    print(f"  Quadrature (weighted)   = {quad_w:.1f} nm")
    print(f"  Quadrature (unweighted) = {quad_u:.1f} nm")
    print(f"  Diff pattern FWHM (weighted)   = {diff_fwhm_w*q_image*1e9:.1f} nm")
    print(f"  Diff pattern FWHM (unweighted) = {diff_fwhm_u*q_image*1e9:.1f} nm")
    print(f"  Airy limit = {airy_exact*1e9:.1f} nm")

    return {
        'mirror': mirror_name,
        'geo_fwhm_nm': z_geo_fwhm,
        'kick_fwhm_w_nm': kick_w,
        'kick_fwhm_u_nm': kick_u,
        'total_fwhm_w_nm': total_w,
        'total_fwhm_u_nm': total_u,
        'quad_w_nm': quad_w,
        'quad_u_nm': quad_u,
        'diff_pattern_fwhm_w_nm': diff_fwhm_w * q_image * 1e9,
        'diff_pattern_fwhm_u_nm': diff_fwhm_u * q_image * 1e9,
        'airy_nm': airy_exact * 1e9,
        'f_ff': f_ff,
        'footprint_um': D * 1e6,
    }


# ==============================================================
#  MAIN
# ==============================================================
if __name__ == '__main__':
    t0 = time.time()

    E_keV = 10.0
    SSA_um = 50
    NRAYS = 200000
    SEED = 12345

    print("="*70)
    print("  Shadow4 Kick Extraction: Manual Hybrid Replication")
    print(f"  E={E_keV} keV, SSA={SSA_um} um, nrays={NRAYS}")
    print("="*70)

    # ---- Build beamline to SSA ----
    beam_at_ssa, n_start = build_beamline_to_ssa(E_keV, SSA_um, NRAYS, SEED)

    # ==============================================================
    # KB-V: Tangential V-focus
    # ==============================================================
    p_kbv = POS['kbv'] - POS['ssa']     # 91.69 m from SSA
    q_kbv = POS['sample'] - POS['kbv']  # 0.31 m to sample

    print(f"\n\n{'#'*70}")
    print(f"#  KB-V ANALYSIS")
    print(f"#  p={p_kbv:.2f} m, q={q_kbv:.3f} m")
    print(f"{'#'*70}")

    result_v = extract_kicks_for_mirror(
        beam_input=beam_at_ssa,
        mirror_name="KB-V",
        p_focus=p_kbv,
        q_focus=q_kbv,
        mirror_len=KB_V_LEN,
        col_pos=2,    # Z for vertical
        col_dir=5,    # Zp for vertical
        q_image=q_kbv,
        n_bins_param=200,
        n_peaks=20,
        fft_n_pts=1000000,
        random_seed=0,
    )

    # ==============================================================
    # KB-H: Sagittal H-focus (via X<->Z swap trick)
    # ==============================================================
    p_kbh = POS['kbh'] - POS['ssa']     # 91.90 m from SSA
    q_kbh = POS['sample'] - POS['kbh']  # 0.10 m to sample

    # First, trace through KB-V geometrically (no hybrid) to get beam at KB-H position
    # Use wide boundary in X to avoid clipping horizontal rays needed for KB-H
    kbv_geo_el = S4EllipsoidMirrorElement(
        optical_element=S4EllipsoidMirror(
            name="KB-V-geo",
            boundary_shape=Rectangle(
                x_left=-0.5, x_right=0.5,       # 1m wide -- no horizontal clipping
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
            q=0.0,   # stay at mirror exit
            angle_radial=ANGLE_RAD,
        ),
        input_beam=beam_at_ssa,
    )
    beam_after_kbv, _ = kbv_geo_el.trace_beam()

    # Drift from KB-V to KB-H position
    dist_v_to_h = POS['kbh'] - POS['kbv']
    drift_el = S4ScreenElement(
        optical_element=S4Screen(name="drift_VH"),
        coordinates=ElementCoordinates(p=dist_v_to_h, q=0.0),
        input_beam=beam_after_kbv,
    )
    beam_at_kbh, _ = drift_el.trace_beam()

    # Swap X<->Z for KB-H (sagittal ellipsoid cylinder workaround)
    beam_at_kbh_swapped = _swap_xz(beam_at_kbh)

    n_kbh = beam_at_kbh_swapped.get_number_of_rays(nolost=1)
    print(f"\n[KB-H input] {n_kbh} good rays (after KB-V geo + drift + swap)")

    print(f"\n\n{'#'*70}")
    print(f"#  KB-H ANALYSIS (X<->Z swapped, tangential = horizontal)")
    print(f"#  p={p_kbh:.2f} m, q={q_kbh:.3f} m")
    print(f"{'#'*70}")

    result_h = extract_kicks_for_mirror(
        beam_input=beam_at_kbh_swapped,
        mirror_name="KB-H",
        p_focus=p_kbh,
        q_focus=q_kbh,
        mirror_len=KB_H_LEN,
        col_pos=2,    # Z (which is swapped X = horizontal)
        col_dir=5,    # Zp (which is swapped Xp)
        q_image=q_kbh,
        n_bins_param=200,
        n_peaks=20,
        fft_n_pts=1000000,
        random_seed=0,
        is_swapped=True,
        p_coord=0.0,  # beam already at KB-H position via drift
    )

    # ==============================================================
    # Final comparison table
    # ==============================================================
    elapsed = time.time() - t0

    print(f"\n\n{'='*70}")
    print(f"  FINAL COMPARISON TABLE")
    print(f"{'='*70}")
    print(f"  {'':30s}  {'KB-V (V)':>12s}  {'KB-H (H)':>12s}")
    print(f"  {'-'*30}  {'-'*12}  {'-'*12}")
    print(f"  {'Mirror length (mm)':30s}  {KB_V_LEN*1e3:12.0f}  {KB_H_LEN*1e3:12.0f}")
    print(f"  {'p (m)':30s}  {p_kbv:12.2f}  {p_kbh:12.2f}")
    print(f"  {'q (m)':30s}  {q_kbv:12.3f}  {q_kbh:12.3f}")
    print(f"  {'Footprint (um)':30s}  {result_v['footprint_um']:12.1f}  {result_h['footprint_um']:12.1f}")
    print(f"  {'f_ff (m)':30s}  {result_v['f_ff']:12.4f}  {result_h['f_ff']:12.4f}")
    print(f"  {'Geometric FWHM (nm)':30s}  {result_v['geo_fwhm_nm']:12.1f}  {result_h['geo_fwhm_nm']:12.1f}")
    print(f"  {'Kick FWHM weighted (nm)':30s}  {result_v['kick_fwhm_w_nm']:12.1f}  {result_h['kick_fwhm_w_nm']:12.1f}")
    print(f"  {'Kick FWHM unweighted (nm)':30s}  {result_v['kick_fwhm_u_nm']:12.1f}  {result_h['kick_fwhm_u_nm']:12.1f}")
    print(f"  {'Diff pattern FWHM w (nm)':30s}  {result_v['diff_pattern_fwhm_w_nm']:12.1f}  {result_h['diff_pattern_fwhm_w_nm']:12.1f}")
    print(f"  {'Diff pattern FWHM u (nm)':30s}  {result_v['diff_pattern_fwhm_u_nm']:12.1f}  {result_h['diff_pattern_fwhm_u_nm']:12.1f}")
    print(f"  {'Airy limit (nm)':30s}  {result_v['airy_nm']:12.1f}  {result_h['airy_nm']:12.1f}")
    print(f"  {'Total FWHM weighted (nm)':30s}  {result_v['total_fwhm_w_nm']:12.1f}  {result_h['total_fwhm_w_nm']:12.1f}")
    print(f"  {'Total FWHM unweighted (nm)':30s}  {result_v['total_fwhm_u_nm']:12.1f}  {result_h['total_fwhm_u_nm']:12.1f}")
    print(f"  {'Quadrature weighted (nm)':30s}  {result_v['quad_w_nm']:12.1f}  {result_h['quad_w_nm']:12.1f}")
    print(f"  {'Quadrature unweighted (nm)':30s}  {result_v['quad_u_nm']:12.1f}  {result_h['quad_u_nm']:12.1f}")

    # Ratios
    def safe_ratio(a, b):
        return a/b if b > 0 else float('nan')

    print(f"\n  {'RATIOS':30s}")
    print(f"  {'Total/Quadrature (w)':30s}  {safe_ratio(result_v['total_fwhm_w_nm'], result_v['quad_w_nm']):12.4f}  {safe_ratio(result_h['total_fwhm_w_nm'], result_h['quad_w_nm']):12.4f}")
    print(f"  {'Total/Quadrature (u)':30s}  {safe_ratio(result_v['total_fwhm_u_nm'], result_v['quad_u_nm']):12.4f}  {safe_ratio(result_h['total_fwhm_u_nm'], result_h['quad_u_nm']):12.4f}")
    print(f"  {'Kick_w / Kick_u':30s}  {safe_ratio(result_v['kick_fwhm_w_nm'], result_v['kick_fwhm_u_nm']):12.4f}  {safe_ratio(result_h['kick_fwhm_w_nm'], result_h['kick_fwhm_u_nm']):12.4f}")
    print(f"  {'Kick_w / Airy':30s}  {safe_ratio(result_v['kick_fwhm_w_nm'], result_v['airy_nm']):12.4f}  {safe_ratio(result_h['kick_fwhm_w_nm'], result_h['airy_nm']):12.4f}")

    print(f"\n  Total elapsed: {elapsed:.1f} s")
    print(f"\n  DONE.")
