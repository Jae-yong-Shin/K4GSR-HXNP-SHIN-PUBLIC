"""
Verify JS Guigay thick Bragg implementation against S4 reference rocking curves.
Implements the EXACT same formulas as _guigayThickBragg() in 01_mc_engine.js,
then compares with crystalpy S4 reference data.
"""
import json
import numpy as np
import os

# Physical constants (same as JS)
HC = 12.3984193  # hc in keV*Angstrom

# Si crystal d-spacings (same as JS D_SI)
D_SI = {'111': 3.13542, '311': 1.63749}

def guigay_thick_bragg(vdn, E_keV, thB, psi, crystal='111'):
    """
    Exact Python mirror of JS _guigayThickBragg().
    psi = dict with psi0_re, psi0_im, psiH_re, psiH_im, psiHb_re, psiHb_im
    Returns (R_s, R_p)
    """
    d_m = D_SI[crystal] * 1e-10  # d-spacing [m]
    lam_m = HC / E_keV * 1e-10   # wavelength [m]
    g = lam_m / d_m              # |H|/k

    # alpha = g * (2*vdn - g)
    alpha = g * (2 * vdn - g)

    # guigay_b = gamma_0 / gamma_H
    KH_norm_sq = 1 - 2*g*vdn + g*g
    KH_norm = np.sqrt(abs(KH_norm_sq))
    gamma_H = (vdn - g) / KH_norm if KH_norm > 1e-15 else -vdn
    guigay_b = vdn / gamma_H if abs(gamma_H) > 1e-15 else -1.0

    # effective psi_0 = conj(psi_0)
    ep0 = complex(psi['psi0_re'], -psi['psi0_im'])

    # w = b * alpha/2 + ep0 * (b-1)/2
    w = guigay_b * alpha * 0.5 + ep0 * (guigay_b - 1) * 0.5

    # omega = pi/lambda * w
    piOverLam = np.pi / lam_m
    omega = piOverLam * w

    # --- SIGMA ---
    eph = complex(psi['psiH_re'], -psi['psiH_im'])
    ephb = complex(psi['psiHb_re'], -psi['psiHb_im'])
    uhb = ephb * piOverLam

    # asquared = (pi/lam)^2 * (b * eph * ephb + w^2)
    piOL2 = piOverLam * piOverLam
    asq = piOL2 * (guigay_b * eph * ephb + w * w)

    # aa = 1/sqrt(2) * (Im(asq)/sqrt(|asq|-Re(asq)) + i*sqrt(|asq|-Re(asq)))
    asq_abs = abs(asq)
    q = asq_abs - asq.real
    if q < 1e-40:
        q = 1e-40
    sqrtQ = np.sqrt(q)
    invSqrt2 = 1.0 / np.sqrt(2.0)
    aa = invSqrt2 * complex(asq.imag / sqrtQ, sqrtQ)

    # complex_amplitude_s = (aa + omega) / uhb
    cs = (aa + omega) / uhb if abs(uhb) > 1e-30 else 0
    R_s = abs(cs) ** 2

    # --- PI ---
    cos2thB = np.cos(2 * thB)
    eph_p = eph * cos2thB
    ephb_p = ephb * cos2thB
    uhb_p = ephb_p * piOverLam

    asq_p = piOL2 * (guigay_b * eph_p * ephb_p + w * w)
    asq_p_abs = abs(asq_p)
    q_p = asq_p_abs - asq_p.real
    if q_p < 1e-40:
        q_p = 1e-40
    sqrtQp = np.sqrt(q_p)
    aa_p = invSqrt2 * complex(asq_p.imag / sqrtQp, sqrtQp)

    cp = (aa_p + omega) / uhb_p if abs(uhb_p) > 1e-30 else 0
    R_p = abs(cp) ** 2

    # Clamp
    R_s = max(0, min(1, R_s))
    R_p = max(0, min(1, R_p))

    return R_s, R_p


# Load S4 reference data
ref_path = os.path.join(os.path.dirname(__file__),
                        'paper', 'validation', 'data', 's4_rocking_curve_ref.json')
with open(ref_path, 'r') as f:
    ref = json.load(f)

print("=" * 70)
print("Guigay Thick Bragg: Python mirror of JS vs S4 crystalpy reference")
print("=" * 70)

for label in ['5.0keV', '10.0keV', '20.0keV']:
    d = ref[label]
    E_eV = d['E_eV']
    E_keV = E_eV / 1000.0
    thB = d['theta_B_rad']
    crystal = '111'

    # Psi values from S4 reference
    psi = {
        'psi0_re': d['psi_0_re'],
        'psi0_im': d['psi_0_im'],
        'psiH_re': d['psi_H_re'],
        'psiH_im': d['psi_H_im'],
        'psiHb_re': d['psi_H_bar_re'],
        'psiHb_im': d['psi_H_bar_im'],
    }

    # S4 reference rocking curve
    dev_urad_ref = np.array(d['dev_urad'])
    R_s_ref = np.array(d['R_s_thick'])
    R_p_ref = np.array(d['R_p_thick'])

    # Compute using our Guigay implementation
    vdn_center = np.sin(thB)  # gamma_0 at exact Bragg
    R_s_ours = np.zeros(len(dev_urad_ref))
    R_p_ours = np.zeros(len(dev_urad_ref))

    for i, dev_urad in enumerate(dev_urad_ref):
        dev_rad = dev_urad * 1e-6
        # vdn = sin(thB + dev)
        vdn = np.sin(thB + dev_rad)
        Rs, Rp = guigay_thick_bragg(vdn, E_keV, thB, psi, crystal)
        R_s_ours[i] = Rs
        R_p_ours[i] = Rp

    # Compare peak reflectivities
    peak_Rs_ours = np.max(R_s_ours)
    peak_Rp_ours = np.max(R_p_ours)
    peak_Rs_s4 = d['peak_R_s']
    peak_Rp_s4 = d['peak_R_p']

    # FWHM comparison (Darwin width)
    half_max_s = peak_Rs_ours * 0.5
    above_half_s = dev_urad_ref[R_s_ours >= half_max_s]
    dw_ours = above_half_s[-1] - above_half_s[0] if len(above_half_s) >= 2 else 0

    half_max_s_ref = peak_Rs_s4 * 0.5
    above_half_ref = dev_urad_ref[R_s_ref >= half_max_s_ref]
    dw_ref = above_half_ref[-1] - above_half_ref[0] if len(above_half_ref) >= 2 else 0

    # RMS difference in rocking curve
    rms_s = np.sqrt(np.mean((R_s_ours - R_s_ref) ** 2))
    rms_p = np.sqrt(np.mean((R_p_ours - R_p_ref) ** 2))

    print(f"\n--- {label} (theta_B = {np.degrees(thB):.2f} deg) ---")
    print(f"  Peak R_s: ours={peak_Rs_ours:.6f}, S4={peak_Rs_s4:.6f}, "
          f"diff={abs(peak_Rs_ours-peak_Rs_s4):.6f} ({abs(peak_Rs_ours-peak_Rs_s4)/peak_Rs_s4*100:.2f}%)")
    print(f"  Peak R_p: ours={peak_Rp_ours:.6f}, S4={peak_Rp_s4:.6f}, "
          f"diff={abs(peak_Rp_ours-peak_Rp_s4):.6f} ({abs(peak_Rp_ours-peak_Rp_s4)/peak_Rp_s4*100:.2f}%)")
    print(f"  Darwin width (sigma): ours={dw_ours:.1f} urad, S4={dw_ref:.1f} urad, "
          f"diff={abs(dw_ours-dw_ref):.1f} urad ({abs(dw_ours-dw_ref)/max(dw_ref,0.01)*100:.1f}%)")
    print(f"  RMS diff: sigma={rms_s:.6f}, pi={rms_p:.6f}")

    # Spot check: verify intermediate values at center
    vdn_c = np.sin(thB)
    d_m = D_SI[crystal] * 1e-10
    lam_m = HC / E_keV * 1e-10
    g = lam_m / d_m
    alpha_c = g * (2 * vdn_c - g)
    KH_sq = 1 - 2*g*vdn_c + g*g
    KH_n = np.sqrt(abs(KH_sq))
    gH_c = (vdn_c - g) / KH_n if KH_n > 1e-15 else -vdn_c
    b_c = vdn_c / gH_c if abs(gH_c) > 1e-15 else -1.0
    print(f"  alpha_center: ours={alpha_c:.6e}, S4={d['alpha_center']:.6e}")
    print(f"  guigay_b_center: ours={b_c:.6f}, S4={d['guigay_b_center']:.6f}")

print("\n" + "=" * 70)
print("PASS/FAIL: peak R_s diff < 0.001, Darwin width diff < 1 urad")
all_pass = True
for label in ['5.0keV', '10.0keV', '20.0keV']:
    d = ref[label]
    E_keV = d['E_eV'] / 1000.0
    thB = d['theta_B_rad']
    psi = {
        'psi0_re': d['psi_0_re'], 'psi0_im': d['psi_0_im'],
        'psiH_re': d['psi_H_re'], 'psiH_im': d['psi_H_im'],
        'psiHb_re': d['psi_H_bar_re'], 'psiHb_im': d['psi_H_bar_im'],
    }
    dev_urad_ref = np.array(d['dev_urad'])
    R_s_ref = np.array(d['R_s_thick'])
    R_s_ours = np.array([guigay_thick_bragg(np.sin(thB + du*1e-6), E_keV, thB, psi)[0]
                          for du in dev_urad_ref])
    peak_diff = abs(np.max(R_s_ours) - d['peak_R_s'])

    half_s = np.max(R_s_ours) * 0.5
    above_s = dev_urad_ref[R_s_ours >= half_s]
    dw = above_s[-1] - above_s[0] if len(above_s) >= 2 else 0
    above_ref = dev_urad_ref[R_s_ref >= d['peak_R_s']*0.5]
    dw_ref = above_ref[-1] - above_ref[0] if len(above_ref) >= 2 else 0
    dw_diff = abs(dw - dw_ref)

    ok = peak_diff < 0.001 and dw_diff < 1.0
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
    print(f"  {label}: peak_diff={peak_diff:.6f}, dw_diff={dw_diff:.1f} urad -> {status}")

print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILED'}")
