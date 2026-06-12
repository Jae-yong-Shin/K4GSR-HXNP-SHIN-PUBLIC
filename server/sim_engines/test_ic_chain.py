"""Validation script for ic_chain.py (runnable, no pytest dependency).

Run:  python server/sim_engines/test_ic_chain.py
Exit code 0 = all PASS, 1 = any FAIL (blocking asserts).

Tests (design doc TASK_XANES_IC_SIM.md section 3d):
  (a) Identity: noiseless, zero air, identical ideal chambers ->
      ln(I0/I1) minus the ANALYTIC smooth gas term reconstructs mu_t
      to machine precision (<1e-12). Repeated with air + mixed config
      using the full chain factor G(E).
  (b) Cross-check at 5 energies x 2 gases against DIRECT
      xraydb.ionchamber_fluxes calls (volts=1, sensitivity=1 A/V trick,
      as in paper/validation/run_ionchamber_reference.py) -- rel err <1e-9.
  (c) Realistic Fe K-edge demo (7.0-7.3 keV, mu_t step 0.3->1.3,
      N2/N2 10 cm, flux 1e11): edge-jump SNR improves ~sqrt(10)
      between dwell 0.1 s and 1.0 s (+-10%).
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ic_chain  # noqa: E402
from ic_chain import run_ic_chain  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print("[%s] %s %s" % (status, name, detail))
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# (a) Identity: noiseless reconstruction to machine precision
# ---------------------------------------------------------------------------
def test_a_identity():
    print("\n=== (a) Identity: noiseless mu_t reconstruction ===")
    E = np.arange(7000.0, 7300.0 + 0.25, 0.5)  # eV
    # synthetic mu_t with an edge step + oscillations (not flat, not smooth)
    mu_t = (0.3 + 1.0 / (1.0 + np.exp(-(E - 7112.0) / 1.5))
            + 0.05 * np.sin((E - 7112.0) / 7.0) * (E > 7112.0))

    # --- a1: zero air, identical ideal chambers, no dark, no prefocus ratio
    cfg = {"gas": "N2", "length_cm": 10.0, "pressure_atm": 1.0,
           "air_before_cm": 0.0, "air_after_cm": 0.0}
    res = run_ic_chain(E, mu_t, 1.0e11, dwell_s=None,
                       i0=cfg, i1={"gas": "N2", "length_cm": 10.0,
                                   "pressure_atm": 1.0, "air_path_cm": 0.0},
                       dark0_A=0.0, dark1_A=0.0, seed=None)
    # identical chambers + zero air: analytic smooth term = -ln(T_i0)
    gas_term = -np.log(res["T_i0"])
    recon = res["mu_obs"] - gas_term
    err1 = np.max(np.abs(recon - mu_t))
    check("a1 zero-air identical chambers: |mu_obs - gas_term - mu_t|",
          err1 < 1e-12, "max=%.3e (<1e-12)" % err1)

    # mu_obs must equal mu_obs_ideal exactly in noiseless mode (dark=0)
    err1b = np.max(np.abs(res["mu_obs"] - res["mu_obs_ideal"]))
    check("a1 noiseless mode: mu_obs == mu_obs_ideal", err1b == 0.0,
          "max=%.3e" % err1b)

    # --- a2: general config (air segments, different gases, prefocus ratio)
    #     full analytic chain factor:
    #     mu_obs = mu_t - ln(G),
    #     G = T_i0 * T_airA * T_air_s2d * (resp1/resp0) / ratio_prefocus
    res2 = run_ic_chain(
        E, mu_t, 1.0e11, dwell_s=None,
        i0={"gas": "N2", "length_cm": 10.0, "pressure_atm": 1.0,
            "air_before_cm": 5.0, "air_after_cm": 2.0},
        i1={"gas": "Ar", "length_cm": 10.0, "pressure_atm": 0.5,
            "air_path_cm": 12.0},
        dark0_A=0.0, dark1_A=0.0, ratio_prefocus=0.37, seed=None)
    G = (res2["T_i0"] * res2["T_airA"] * res2["T_air_s2d"]
         * res2["resp1_A_per_phps"] / res2["resp0_A_per_phps"] / 0.37)
    recon2 = res2["mu_obs"] + np.log(G)
    err2 = np.max(np.abs(recon2 - mu_t))
    check("a2 general config (air+Ar 0.5 atm+ratio): identity",
          err2 < 1e-12, "max=%.3e (<1e-12)" % err2)


# ---------------------------------------------------------------------------
# (b) Cross-check vs DIRECT xraydb.ionchamber_fluxes (volts trick)
# ---------------------------------------------------------------------------
def test_b_xraydb_crosscheck():
    print("\n=== (b) Cross-check vs xraydb.ionchamber_fluxes ===")
    import xraydb

    energies = [5000.0, 8000.0, 10000.0, 15000.0, 20000.0]
    gases = ["N2", "Ar"]
    length_cm = 10.0
    worst_i = 0.0
    worst_t = 0.0

    for gas in gases:
        for E in energies:
            # volts trick (A3 reference): volts=1, sensitivity=1 A/V
            # -> chamber current is exactly 1 A, fl.incident is the flux
            #    that produces it.
            fl = xraydb.ionchamber_fluxes(gas=gas, volts=1.0,
                                          length=length_cm, energy=E,
                                          sensitivity=1.0,
                                          sensitivity_units="A/V")
            # our chain: zero air, mu_t=0 sample, flux_in = fl.incident
            res = run_ic_chain(np.array([E]), np.array([0.0]), fl.incident,
                               dwell_s=None,
                               i0={"gas": gas, "length_cm": length_cm,
                                   "pressure_atm": 1.0,
                                   "air_before_cm": 0.0,
                                   "air_after_cm": 0.0},
                               dark0_A=0.0, dark1_A=0.0, seed=None)
            rel_i = abs(res["I0_A"][0] - 1.0)
            rel_t = abs(res["T_i0"][0]
                        - fl.transmitted / fl.incident) / (
                            fl.transmitted / fl.incident)
            worst_i = max(worst_i, rel_i)
            worst_t = max(worst_t, rel_t)
            print("    %-3s %7.0f eV: I0=%.15f A (rel err %.2e), "
                  "T rel err %.2e" % (gas, E, res["I0_A"][0], rel_i, rel_t))

    check("b current vs ionchamber_fluxes (10 pts)", worst_i < 1e-9,
          "worst=%.2e (<1e-9)" % worst_i)
    check("b transmitted fraction vs ionchamber_fluxes", worst_t < 1e-9,
          "worst=%.2e (<1e-9)" % worst_t)


# ---------------------------------------------------------------------------
# (c) Realistic Fe K-edge demo: SNR vs dwell
# ---------------------------------------------------------------------------
def test_c_fe_demo():
    print("\n=== (c) Fe K-edge demo: dwell 0.1 s vs 1.0 s ===")
    E = np.arange(7000.0, 7300.0 + 0.25, 0.5)  # 601 pts
    mu_t = 0.3 + 1.0 / (1.0 + np.exp(-(E - 7112.0) / 1.5))  # step 0.3 -> 1.3
    flux = 1.0e11
    cfg0 = {"gas": "N2", "length_cm": 10.0, "pressure_atm": 1.0,
            "air_before_cm": 5.0, "air_after_cm": 2.0}
    cfg1 = {"gas": "N2", "length_cm": 10.0, "pressure_atm": 1.0,
            "air_path_cm": 10.0}

    ideal = run_ic_chain(E, mu_t, flux, dwell_s=None, i0=cfg0, i1=cfg1,
                         seed=None)
    edge_jump = ideal["mu_obs_ideal"][-1] - ideal["mu_obs_ideal"][0]

    rows = []
    snr = {}
    for dwell in (0.1, 1.0):
        res = run_ic_chain(E, mu_t, flux, dwell_s=dwell, i0=cfg0, i1=cfg1,
                           seed=42)
        resid = res["mu_obs"] - ideal["mu_obs_ideal"]
        sigma = float(np.std(resid))
        snr[dwell] = edge_jump / sigma
        rows.append((dwell,
                     res["I0_A"].min() * 1e6, res["I0_A"].max() * 1e6,
                     res["I1_A"].min() * 1e6, res["I1_A"].max() * 1e6,
                     sigma, snr[dwell]))

    print("    dwell[s]  I0[uA] min..max   I1[uA] min..max   "
          "sigma(mu)    SNR(jump=%.3f)" % edge_jump)
    for d, i0lo, i0hi, i1lo, i1hi, sg, sn in rows:
        print("    %7.1f   %.3f..%.3f      %.3f..%.3f       %.3e   %9.0f"
              % (d, i0lo, i0hi, i1lo, i1hi, sg, sn))

    ratio = snr[1.0] / snr[0.1]
    expected = np.sqrt(10.0)
    dev = abs(ratio / expected - 1.0)
    print("    SNR ratio (1.0s / 0.1s) = %.3f, sqrt(10) = %.3f, dev = %.1f%%"
          % (ratio, expected, dev * 100))
    check("c SNR improves ~sqrt(10) with 10x dwell", dev < 0.10,
          "ratio=%.3f vs %.3f (+-10%%)" % (ratio, expected))

    # sanity: noiseless edge jump in mu_obs matches the mu_t step (+ smooth
    # gas-term drift across the window, which is small but nonzero)
    check("c edge jump close to mu_t step 1.0", abs(edge_jump - 1.0) < 0.05,
          "jump=%.4f" % edge_jump)


if __name__ == "__main__":
    if not ic_chain.XRAYDB_OK:
        print("FATAL: xraydb not available")
        sys.exit(1)
    test_a_identity()
    test_b_xraydb_crosscheck()
    test_c_fe_demo()
    print()
    if FAILURES:
        print("RESULT: FAIL (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("RESULT: ALL PASS")
    sys.exit(0)
