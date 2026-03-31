"""
Two analytical beam size models (KB acceptance D fixed):
  Model F (Flat-top): SSA defines effective source (FWHM = SSA width)
  Model G (Gaussian): Beam Gaussian defines effective source (FWHM = 2.355*sigma)

Both use Airy diffraction from KB acceptance: diff = 0.886 * lambda * q / D
"""
import math

# --- Ring / Electron beam ---
E_RING  = 4.0        # GeV
EMIT_X  = 62e-12     # m-rad
EMIT_Y  = 6.2e-12    # m-rad
BETA_X  = 6.334      # m
BETA_Y  = 2.841      # m
E_SPREAD = 1.20e-3
LAMBDA_U = 0.024      # m
N_PERIODS = 123
L_UND   = N_PERIODS * LAMBDA_U   # 2.952 m
HC      = 12.39842    # keV-Angstrom

SIG_EX  = math.sqrt(EMIT_X * BETA_X)
SIG_EY  = math.sqrt(EMIT_Y * BETA_Y)
SIG_EXP = math.sqrt(EMIT_X / BETA_X)
SIG_EYP = math.sqrt(EMIT_Y / BETA_Y)

# --- Beamline geometry ---
POS_SSA  = 58.0
POS_KBV  = 149.69
POS_KBH  = 149.90
POS_SAMPLE = 150.0

M1_P = 30.4;  M1_Q = 27.6;  M1_DM = M1_Q / M1_P
M2_P = 33.0;  M2_Q = 25.0;  M2_DM = M2_Q / M2_P

KB_V_LEN = 0.300;  KB_H_LEN = 0.100;  KB_PITCH = 3.0e-3
D_KB_H = KB_H_LEN * math.sin(KB_PITCH)  # 300 um
D_KB_V = KB_V_LEN * math.sin(KB_PITCH)  # 900 um

pV = POS_KBV - POS_SSA;  qV = POS_SAMPLE - POS_KBV  # 91.69, 0.31
pH = POS_KBH - POS_SSA;  qH = POS_SAMPLE - POS_KBH  # 91.90, 0.10
MV = qV / pV;  MH = qH / pH

GAMMA_E = E_RING * 1e3 / 0.51100

def select_best(E_keV):
    for n in [1, 3, 5, 7, 9, 11, 13, 15]:
        E1_need = E_keV / n
        rhs = 0.9498 * E_RING**2 / (2.4 * E1_need)
        K2 = 2 * (rhs - 1)
        if K2 < 0: continue
        K = math.sqrt(K2)
        if K < 0.5 or K > 3.0: continue
        return n, K
    return 1, 1.0

def photonSrc(E_keV):
    lm = (HC / E_keV) * 1e-10
    n, K = select_best(E_keV)
    srp = 0.69 * math.sqrt(lm / (2 * n * L_UND))
    sr  = 2.740 / (4 * math.pi) * math.sqrt(2 * lm * L_UND / n)
    se = 2 * math.pi * n * N_PERIODS * E_SPREAD
    def Qa_calc(s):
        val = 2*s*s - 1 + math.exp(-2*s*s) + math.sqrt(2*math.pi)*s*math.erf(math.sqrt(2)*s)
        return math.sqrt(max(0, val))
    Qa = max(1, Qa_calc(se))
    se4 = se / 4
    Qa4 = Qa_calc(se4)
    Qs = max(1, Qa4**(2.0/3)) if Qa4 > 0.01 else 1.0
    rpc = srp * Qa;  rc = sr * Qs
    return {
        'Sx': math.sqrt(SIG_EX**2 + rc**2),
        'Sy': math.sqrt(SIG_EY**2 + rc**2),
        'Sxp': math.sqrt(SIG_EXP**2 + rpc**2),
        'Syp': math.sqrt(SIG_EYP**2 + rpc**2),
        'n': n, 'K': K
    }


def compute(E_keV, ssaH_um, ssaV_um):
    ps = photonSrc(E_keV)
    lam = (HC / E_keV) * 1e-10  # m

    # Beam Gaussian sigma at SSA (M1 sagittal -> V focus, M2 tangential -> H focus)
    sigH_ssa = ps['Sx'] * M2_DM   # m
    sigV_ssa = ps['Sy'] * M1_DM   # m
    fwhm_beam_H_ssa = sigH_ssa * 2.355 * 1e6  # um
    fwhm_beam_V_ssa = sigV_ssa * 2.355 * 1e6  # um

    # --- Diffraction (SAME for both models: Airy from KB acceptance) ---
    diff_H = 0.886 * lam * qH / D_KB_H * 1e9  # nm
    diff_V = 0.886 * lam * qV / D_KB_V * 1e9  # nm

    # --- Model F (Flat-top): source FWHM = SSA width ---
    geo_F_H = ssaH_um * 1e-3 * MH * 1e6   # SSA(um) -> mm -> * MH -> um -> nm
    geo_F_V = ssaV_um * 1e-3 * MV * 1e6
    # Simpler: SSA(um) * M * 1e3 (um->nm)
    geo_F_H = ssaH_um * MH * 1e3   # nm
    geo_F_V = ssaV_um * MV * 1e3   # nm
    total_F_H = math.sqrt(geo_F_H**2 + diff_H**2)
    total_F_V = math.sqrt(geo_F_V**2 + diff_V**2)

    # --- Model G (Gaussian): source FWHM = beam Gaussian FWHM ---
    geo_G_H = fwhm_beam_H_ssa * MH * 1e3  # um * M * 1e3 -> nm
    geo_G_V = fwhm_beam_V_ssa * MV * 1e3  # nm
    total_G_H = math.sqrt(geo_G_H**2 + diff_H**2)
    total_G_V = math.sqrt(geo_G_V**2 + diff_V**2)

    return {
        'beam_H_um': fwhm_beam_H_ssa, 'beam_V_um': fwhm_beam_V_ssa,
        'diff_H': diff_H, 'diff_V': diff_V,
        'geo_F_H': geo_F_H, 'geo_F_V': geo_F_V,
        'geo_G_H': geo_G_H, 'geo_G_V': geo_G_V,
        'F_H': total_F_H, 'F_V': total_F_V,
        'G_H': total_G_H, 'G_V': total_G_V,
        'lam_nm': lam * 1e9,
    }


CONDITIONS = [
    ('5keV SSA50x50',   5.0,  50, 50),
    ('10keV SSA50x50', 10.0,  50, 50),
    ('20keV SSA50x50', 20.0,  50, 50),
    ('5keV SSA20x10',   5.0,  20, 10),
    ('10keV SSA20x10', 10.0,  20, 10),
    ('20keV SSA20x10', 20.0,  20, 10),
]


def main():
    print("=" * 120)
    print("ANALYTICAL BEAM SIZE: Flat-top vs Gaussian Source Profile")
    print("  Model F (Flat-top): FWHM_geo = SSA_size x M_KB  (SSA clips beam -> uniform source)")
    print("  Model G (Gaussian): FWHM_geo = 2.355*sigma_beam x M_KB  (SSA open -> Gaussian source)")
    print("  Both: FWHM_diff = 0.886 * lambda * q / D_KB  (Airy from KB acceptance)")
    print(f"  D_KB: H = {D_KB_H*1e6:.0f} um, V = {D_KB_V*1e6:.0f} um (fixed)")
    print(f"  M_KB: H = {MH:.6f}, V = {MV:.6f}")
    print("=" * 120)

    # Source info
    print("\nBeam FWHM at SSA (Gaussian, no clipping):")
    for E in [5, 10, 20]:
        ps = photonSrc(E)
        bH = ps['Sx'] * M2_DM * 2.355e6
        bV = ps['Sy'] * M1_DM * 2.355e6
        print(f"  {E:2d} keV (n={ps['n']}): H = {bH:.1f} um,  V = {bV:.1f} um")

    # Detailed breakdown
    print()
    for name, E, ssaH, ssaV in CONDITIONS:
        r = compute(E, ssaH, ssaV)
        clip_H = "CLIP" if ssaH < r['beam_H_um'] else "open"
        clip_V = "CLIP" if ssaV < r['beam_V_um'] else "open"
        print(f"--- {name} (lam={r['lam_nm']:.4f} nm, beam@SSA: H={r['beam_H_um']:.1f}um V={r['beam_V_um']:.1f}um, "
              f"SSA: {ssaH}x{ssaV}um [{clip_H}/{clip_V}]) ---")
        print(f"  Flat-top:  geo_H={r['geo_F_H']:6.1f}  diff_H={r['diff_H']:6.1f}  -> H = {r['F_H']:6.1f} nm")
        print(f"             geo_V={r['geo_F_V']:6.1f}  diff_V={r['diff_V']:6.1f}  -> V = {r['F_V']:6.1f} nm")
        print(f"  Gaussian:  geo_H={r['geo_G_H']:6.1f}  diff_H={r['diff_H']:6.1f}  -> H = {r['G_H']:6.1f} nm")
        print(f"             geo_V={r['geo_G_V']:6.1f}  diff_V={r['diff_V']:6.1f}  -> V = {r['G_V']:6.1f} nm")
        print()

    # Summary table
    print("=" * 120)
    print("SUMMARY: Flat-top (F) vs Gaussian (G)  [unit: nm]")
    print()
    hdr = (f"{'Condition':<18s} | {'SSA':>7s} | {'Beam@SSA':>10s} |"
           f" {'geo_F_H':>7s} {'geo_G_H':>7s} {'diff_H':>7s} | {'F_H':>7s} {'G_H':>7s} |"
           f" {'geo_F_V':>7s} {'geo_G_V':>7s} {'diff_V':>7s} | {'F_V':>7s} {'G_V':>7s} |")
    print(hdr)
    print("-" * len(hdr))
    for name, E, ssaH, ssaV in CONDITIONS:
        r = compute(E, ssaH, ssaV)
        print(f"{name:<18s} | {ssaH:3d}x{ssaV:<3d} | {r['beam_H_um']:4.1f}x{r['beam_V_um']:<4.1f} |"
              f" {r['geo_F_H']:7.1f} {r['geo_G_H']:7.1f} {r['diff_H']:7.1f} | {r['F_H']:7.1f} {r['G_H']:7.1f} |"
              f" {r['geo_F_V']:7.1f} {r['geo_G_V']:7.1f} {r['diff_V']:7.1f} | {r['F_V']:7.1f} {r['G_V']:7.1f} |")

    # MC expected range
    print()
    print("=" * 80)
    print("MC simulation result should fall between F and G:")
    print(f"{'Condition':<18s} | {'H range (nm)':>22s} | {'V range (nm)':>22s} |")
    print("-" * 70)
    for name, E, ssaH, ssaV in CONDITIONS:
        r = compute(E, ssaH, ssaV)
        lo_H, hi_H = min(r['F_H'], r['G_H']), max(r['F_H'], r['G_H'])
        lo_V, hi_V = min(r['F_V'], r['G_V']), max(r['F_V'], r['G_V'])
        print(f"{name:<18s} | {lo_H:7.1f} ~ {hi_H:7.1f}      | {lo_V:7.1f} ~ {hi_V:7.1f}      |")

    print("\nDone.")


if __name__ == '__main__':
    main()
