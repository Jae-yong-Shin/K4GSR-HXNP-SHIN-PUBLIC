"""
Generate S4/crystalpy reference rocking curves for Si(111) at 5, 10, 20 keV.
Dumps all intermediate values needed for JS porting validation.
"""
import numpy as np
import json, os
from crystalpy.diffraction.GeometryType import BraggDiffraction
from crystalpy.diffraction.DiffractionSetupDabax import DiffractionSetupDabax
from crystalpy.diffraction.PerfectCrystalDiffraction import PerfectCrystalDiffraction
from crystalpy.util.Vector import Vector
from crystalpy.util.Photon import Photon
from crystalpy.util.ComplexAmplitudePhoton import ComplexAmplitudePhoton
import scipy.constants as codata

# Si(111) setup
setup = DiffractionSetupDabax(
    geometry_type=BraggDiffraction(),
    crystal_name="Si",
    thickness=0.010,  # 10 mm
    miller_h=1, miller_k=1, miller_l=1,
    asymmetry_angle=0.0,
    azimuthal_angle=0.0,
)

print("Si(111) d-spacing: %.6f A" % setup.dSpacing())
print("Si(111) V_cell: %.4f A^3 = %.10e m^3" % (setup.unitcellVolume(), setup.unitcellVolumeSI()))
print()

results = {}

for E_eV in [5000.0, 10000.0, 20000.0]:
    E_keV = E_eV / 1000.0
    print(f"=== {E_keV} keV ===")

    theta_B = setup.angleBragg(E_eV)
    print(f"  theta_B: {np.degrees(theta_B):.6f} deg = {theta_B:.8f} rad")

    psi_0, psi_H, psi_H_bar = setup.psiAll(E_eV)
    print(f"  psi_0:     {psi_0}")
    print(f"  psi_H:     {psi_H}")
    print(f"  psi_H_bar: {psi_H_bar}")

    lam = codata.h * codata.c / (E_eV * codata.e)
    k = 2 * np.pi / lam

    # Scan deviation angles
    n_pts = 401
    dev_urad = np.linspace(-100, 100, n_pts)
    dev_rad = dev_urad * 1e-6

    # Bragg geometry: ray at grazing angle theta_B from surface
    # surface normal outwards = (0,0,1)
    # ray direction = (cos(theta_B+dev), 0, -sin(theta_B+dev))
    # grazing angle from surface = theta_B+dev
    angles = theta_B + dev_rad
    vx = np.cos(angles)
    vy = np.zeros_like(angles)
    vz = -np.sin(angles)

    energies = np.full(n_pts, E_eV)

    photon_in = ComplexAmplitudePhoton(
        energies,
        Vector(vx, vy, vz),
        Esigma=np.ones(n_pts, dtype=complex),
        Epi=np.ones(n_pts, dtype=complex),
    )

    surface_normal = Vector(0, 0, 1)
    bragg_normal = surface_normal.getVectorH(
        surface_normal,
        setup.dSpacingSI(),
        asymmetry_angle=0.0,
        azimuthal_angle=0.0)

    # Use numpy calculation strategy (flag=1) to avoid mpmath issues
    pcd = PerfectCrystalDiffraction(
        geometry_type=BraggDiffraction(),
        bragg_normal=bragg_normal,
        surface_normal=surface_normal,
        bragg_angle=setup.angleBragg(energies),
        psi_0=psi_0,
        psi_H=psi_H,
        psi_H_bar=psi_H_bar,
        thickness=setup.thickness(),
        d_spacing=setup.dSpacingSI(),
        calculation_strategy_flag=1,  # numpy (not mpmath)
    )

    # Intermediate values
    mid = n_pts // 2
    alpha = pcd._calculateAlphaGuigay(photon_in)
    guigay_b = pcd._calculateGuigayB(photon_in)
    gamma_0 = pcd._calculateGamma(photon_in)
    print(f"  alpha[center]: {float(alpha[mid]):.10e}")
    print(f"  guigay_b[center]: {float(guigay_b[mid]):.10f}")
    print(f"  gamma_0[center]: {float(gamma_0[mid]):.10f}")

    # Thick crystal reflectivity
    coeffs = pcd.calculateDiffractionGuigay(photon_in, is_thick=1)
    R_s = np.array([float(np.abs(x)**2) for x in coeffs["S"]])
    R_p = np.array([float(np.abs(x)**2) for x in coeffs["P"]])

    print(f"  Peak R_s: {R_s.max():.6f}, Peak R_p: {R_p.max():.6f}")

    # Darwin width
    half_max = R_s.max() / 2
    above = np.where(R_s > half_max)[0]
    dw_urad = dev_urad[above[-1]] - dev_urad[above[0]] if len(above) > 1 else 0
    print(f"  Darwin width (sigma): {dw_urad:.2f} urad = {dw_urad/1e6*206265:.2f} arcsec")

    # DCM (2-crystal)
    R_dcm = R_s * R_s
    half_dcm = R_dcm.max() / 2
    above_dcm = np.where(R_dcm > half_dcm)[0]
    dw_dcm = dev_urad[above_dcm[-1]] - dev_urad[above_dcm[0]] if len(above_dcm) > 1 else 0
    print(f"  DCM 2-crystal width: {dw_dcm:.2f} urad")

    # Get single-energy psi values for reference
    psi_0_s, psi_H_s, psi_H_bar_s = setup.psiAll(E_eV)

    results[f"{E_keV}keV"] = {
        "E_eV": E_eV,
        "theta_B_rad": float(theta_B),
        "d_spacing_A": float(setup.dSpacing()),
        "d_spacing_m": float(setup.dSpacingSI()),
        "V_cell_m3": float(setup.unitcellVolumeSI()),
        "wavelength_m": float(lam),
        "psi_0_re": float(np.real(psi_0_s).flat[0]), "psi_0_im": float(np.imag(psi_0_s).flat[0]),
        "psi_H_re": float(np.real(psi_H_s).flat[0]), "psi_H_im": float(np.imag(psi_H_s).flat[0]),
        "psi_H_bar_re": float(np.real(psi_H_bar_s).flat[0]), "psi_H_bar_im": float(np.imag(psi_H_bar_s).flat[0]),
        "alpha_center": float(alpha[mid]),
        "guigay_b_center": float(guigay_b[mid]),
        "gamma_0_center": float(gamma_0[mid]),
        "darwin_width_urad": float(dw_urad),
        "peak_R_s": float(R_s.max()),
        "peak_R_p": float(R_p.max()),
        "dev_urad": dev_urad.tolist(),
        "R_s_thick": R_s.tolist(),
        "R_p_thick": R_p.tolist(),
        "R_dcm_2crystal": R_dcm.tolist(),
    }
    print()

out_path = os.path.join(os.path.dirname(__file__), 'paper', 'validation', 'data', 's4_rocking_curve_ref.json')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"Saved to {out_path}")
