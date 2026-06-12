#!/usr/bin/env python3
"""Ion-chamber response reference generator (Phase 1 / A3).

Ground truth program: xraydb.ionchamber_fluxes (Matt Newville's xraydb),
the same physics as the XAFSmass flux calculator cited in the JSR
manuscript par.49 (Klementiev & Chernikov 2016, J. Synchrotron Rad. 23).

Program-based working principle (NO formula guessing): every number in the
output JSON is computed by CALLING xraydb.ionchamber_fluxes directly.
The closed-form chain documented below was extracted by reading the xraydb
SOURCE (site-packages/xraydb/xray.py, ionchamber_fluxes, lines 1048-1188 in
xraydb 4.5.8) and is verified here against the program output to machine
precision (assert reldiff < 1e-12) at every grid point.

Extracted formula chain (xraydb/xray.py::ionchamber_fluxes):
    mu_k        = material_mu(gas, E, kind=k)     k in {photo, incoh, total, coh}
                  (linear coefficient [1/cm] = density * sum_elem(frac*mass*
                   mu_elam(elem,E,k)) / mass_total; Elam tables, materials.py:75-125)
    atten_total = 1 - exp(-L * mu_total)
    atten_photo = atten_total * mu_photo / mu_total
    atten_incoh = atten_total * mu_incoh / mu_total
    E_compton   = ComptonEnergies(E).electron_mean   (tabulated Klein-Nishina
                  integration, linear interp; xraydb.py:394-408)
    W           = ionization_potential(gas)          (eV/ion-pair, Knoll Table 5-1
                  + ICRU 31; xray.py:632-672)
    N_carriers  = 2 (both electron and ion collected; default both_carriers=True)
    I [A]       = flux_in [ph/s] * e * N_carriers
                  * (E*atten_photo + E_compton*atten_incoh) / W
    (xraydb solves the inverse: flux_in = V*sens*W / (e * absorbed_energy))

Gas densities are the xraydb materials-DB defaults (approx. 1 atm):
N2 1.25e-3, He 1.786e-4, Ar 1.784e-3, air 1.225e-3 g/cm^3.
mu scales linearly with density, so pressure scaling is mu *= P/P0.

Output: paper/validation/data/ionchamber_reference.json
Usage:  python paper/validation/run_ionchamber_reference.py
"""
import json
import os
import sys
import datetime

import scipy.constants as spc
import xraydb
from xraydb import ionchamber_fluxes, ionization_potential, get_material
from xraydb.xray import get_xraydb

QCHARGE = spc.e          # 1.602176634e-19 C (same constant xraydb uses)
LENGTH_CM = 10.0         # typical ion-chamber active length
NCARRIERS = 2            # xraydb default (both_carriers=True)
E_KEV = [5.0 + 0.5 * i for i in range(41)]   # 5..25 keV step 0.5

# label -> name passed to xraydb (ionchamber_fluxes maps N2->nitrogen internally)
GASES = [
    ('N2', 'N2'),
    ('He', 'helium'),
    ('Ar', 'argon'),
    ('air', 'air'),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, 'data', 'ionchamber_reference.json')

    xdb = get_xraydb()

    gas_meta = {}
    for label, xname in GASES:
        formula, density = get_material('nitrogen' if xname == 'N2' else xname)
        gas_meta[label] = {
            'xraydb_name': xname,
            'formula': formula,
            'density_g_cm3': density,
            'W_eV': ionization_potential(xname),
        }

    e_compton = [float(xdb.compton_energies(e * 1000.0).electron_mean)
                 for e in E_KEV]

    results = {}
    for label, xname in GASES:
        att_tot, att_pho, att_inc = [], [], []
        cur_per_1e10, flux_per_na = [], []
        for i, ekev in enumerate(E_KEV):
            e_ev = ekev * 1000.0
            # current = volts*sensitivity = 1 A  ->  fl.incident = flux per 1 A
            fl = ionchamber_fluxes(gas=xname, volts=1.0, length=LENGTH_CM,
                                   energy=e_ev, sensitivity=1.0,
                                   sensitivity_units='A/V')
            a_tot = 1.0 - fl.transmitted / fl.incident
            a_pho = fl.photo / fl.incident
            a_inc = fl.incoherent / fl.incident
            i_per_1e10 = 1e10 / fl.incident           # [A] per 1e10 ph/s
            f_per_na = fl.incident * 1e-9             # [ph/s] per 1 nA

            # verify the extracted closed-form chain against the program
            w_ev = gas_meta[label]['W_eV']
            i_closed = 1e10 * QCHARGE * NCARRIERS * \
                (e_ev * a_pho + e_compton[i] * a_inc) / w_ev
            rel = abs(i_closed / i_per_1e10 - 1.0)
            assert rel < 1e-12, \
                'closed-form mismatch %s %.1f keV: %.3e' % (label, ekev, rel)

            att_tot.append(a_tot)
            att_pho.append(a_pho)
            att_inc.append(a_inc)
            cur_per_1e10.append(i_per_1e10)
            flux_per_na.append(f_per_na)

        results[label] = {
            'atten_total': att_tot,
            'atten_photo': att_pho,
            'atten_incoh': att_inc,
            'current_A_per_1e10phps': cur_per_1e10,
            'flux_phps_per_nA': flux_per_na,
        }

    out = {
        'metadata': {
            'generated': datetime.date.today().isoformat(),
            'generator': 'paper/validation/run_ionchamber_reference.py',
            'ground_truth': ('xraydb.ionchamber_fluxes '
                             '(xraydb/xray.py lines 1048-1188, called directly; '
                             'closed-form chain verified to <1e-12 at every point)'),
            'xraydb_version': xraydb.__version__,
            'python_version': sys.version.split()[0],
            'formula_notes': [
                'I[A] = flux*e*N_carriers*(E*atten_photo + Ec*atten_incoh)/W',
                'atten_total = 1-exp(-L*mu_total); atten_k = atten_total*mu_k/mu_total',
                'mu_k = material_mu(gas,E,kind=k) [1/cm], Elam tables at DB density',
                'Ec = Compton electron mean energy (tabulated Klein-Nishina, interp)',
                'W = effective ionization potential eV/ion-pair (Knoll/ICRU 31)',
                'N_carriers = 2 (both electron and ion collected)',
                'pressure scaling: mu linear in density (DB densities ~ 1 atm)',
            ],
            'settings': {
                'length_cm': LENGTH_CM,
                'with_compton': True,
                'both_carriers': True,
                'n_carriers': NCARRIERS,
                'qcharge_C': QCHARGE,
            },
            'gases': gas_meta,
        },
        'energies_keV': E_KEV,
        'compton_electron_mean_eV': e_compton,
        'results': results,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=1)
    print('wrote %s' % out_path)
    print('xraydb %s | L=%g cm | N_carriers=%d | gases: %s' %
          (xraydb.__version__, LENGTH_CM, NCARRIERS,
           ', '.join('%s (W=%.1f eV, rho=%g g/cm3)' %
                     (lab, gas_meta[lab]['W_eV'], gas_meta[lab]['density_g_cm3'])
                     for lab, _ in GASES)))
    print()

    hdr = '%6s |' % 'E_keV'
    for label, _ in GASES:
        hdr += ' %s abs_frac  I/1e10[A] |' % ('%-3s' % label)
    print(hdr)
    print('-' * len(hdr))
    for i, ekev in enumerate(E_KEV):
        row = '%6.1f |' % ekev
        for label, _ in GASES:
            r = results[label]
            row += ' %12.4e %10.3e |' % (r['atten_total'][i],
                                         r['current_A_per_1e10phps'][i])
        print(row)


if __name__ == '__main__':
    main()
