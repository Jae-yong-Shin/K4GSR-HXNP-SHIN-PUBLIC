# run_xafsmass_crosscheck.py -- cross-validate the project's xraydb-ported
# ion-chamber response model (A3, server/sim_engines/ic_chain.py +
# js/optics/07_ion_chamber.js) against the program the manuscript cites as
# the example reference implementation: XAFSmass (Klementiev & Chernikov
# 2016), function XAFSmassCalc.calculate_flux ("flux for 1 uA of ion
# current").
#
# The two programs use different, equally documented conventions:
#   XAFSmass : I = flux * att * (E/W) * e        single carrier, no Compton
#              split, Chantler-f2 absorption, W = pairEnergy (N2 36, Ar 26),
#              pressure in torr, T = 295 K
#   xraydb   : I = flux * e * 2 * (E*att_photo + Ec*att_incoh) / W
#              both carriers, Compton electron mean, Elam tables,
#              W = ionization_potential (N2 34.8, Ar 26.4)
# After reconciling those conventions algebraically (column "recon" =
# raw ratio / predicted convention ratio), the residual is the
# Chantler-vs-Elam table difference only.
#
# Run: python -X utf8 paper/validation/run_xafsmass_crosscheck.py
# Requires: pip install XAFSmass xraydb
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "server"))

import XAFSmass.XAFSmassCalc as C  # noqa: E402
import xraydb  # noqa: E402
from sim_engines.ic_chain import compton_electron_mean  # noqa: E402

LENGTH_CM = 10.0
P_TORR = 760.0  # 1 atm; XAFSmass pressure unit is torr
                # (empirically confirmed: att(N2,760,10cm,8979eV)=0.0406
                #  matches the Elam photo attenuation 0.0395 within tables)

CASES = [("N2", 7112.0), ("N2", 8979.0), ("N2", 12000.0),
         ("Ar", 8979.0), ("Ar", 15000.0)]

TOL_RECON = 0.02  # reconciled agreement gate: 2 % (table-difference level)

rows = []
fails = []
print("%-4s %-8s | %-12s %-12s %-7s %-7s" %
      ("gas", "E[eV]", "fluxXM/uA", "fluxXDB/uA", "raw", "recon"))
for gas, E in CASES:
    fxm, att_xm = C.calculate_flux([(gas, P_TORR)], E, LENGTH_CM)

    res = xraydb.ionchamber_fluxes(gas=gas, volts=1.0, energy=E,
                                   length=LENGTH_CM, sensitivity=1.0)
    fxdb = res.incident * 1e-6  # flux per 1 uA

    name = "nitrogen" if gas == "N2" else gas
    mu_t = xraydb.material_mu(name, E, kind="total")
    mu_p = xraydb.material_mu(name, E, kind="photo")
    att_tot = 1.0 - np.exp(-mu_t * LENGTH_CM)
    att_pho = 1.0 - np.exp(-mu_p * LENGTH_CM)
    att_inc = att_tot - att_pho
    Ec = float(compton_electron_mean(np.array([E]))[0])

    W_xm = C.pairEnergy["N₂" if gas == "N2" else gas]
    W_xdb = xraydb.ionization_potential(name)

    pred = (W_xm / (E * att_xm)) / (W_xdb / (2.0 * (E * att_pho
                                                    + Ec * att_inc)))
    raw = fxm / fxdb
    recon = raw / pred
    ok = abs(recon - 1.0) <= TOL_RECON
    if not ok:
        fails.append((gas, E, recon))
    rows.append({"gas": gas, "energy_eV": E, "flux_per_uA_xafsmass": fxm,
                 "flux_per_uA_xraydb": fxdb, "raw_ratio": raw,
                 "reconciled_ratio": recon,
                 "W_xafsmass": W_xm, "W_xraydb": W_xdb})
    print("%-4s %-8.0f | %-12.3e %-12.3e %-7.3f %-7.3f %s"
          % (gas, E, fxm, fxdb, raw, recon, "PASS" if ok else "FAIL"))

out = {"date": "2026-06-12", "length_cm": LENGTH_CM, "pressure_torr": P_TORR,
       "tolerance_reconciled": TOL_RECON,
       "conventions": {
           "xafsmass": "single carrier, total-absorption energy deposit, "
                       "Chantler tables, pairEnergy W",
           "xraydb_ported": "both carriers, E*att_photo + Ec*att_incoh, "
                            "Elam tables, ionization_potential W"},
       "rows": rows}
path = os.path.join(os.path.dirname(__file__), "data",
                    "xafsmass_crosscheck.json")
with open(path, "w") as f:
    json.dump(out, f, indent=1)
print("wrote", path)
print("RESULT:", "FAIL %s" % fails if fails else
      "ALL PASS (reconciled agreement within %.0f%%)" % (TOL_RECON * 100))
sys.exit(1 if fails else 0)
