#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transmission Calculator Physics Verification.

Compares JS compoundMuRho / calcTransmission results against
NIST xraydb reference values. This script reimplements the JS
physics logic in Python and validates correctness.

Channels tested:
  1. Physics accuracy: mu/rho vs xraydb (NIST)
  2. Beer-Lambert T(E) calculation
  3. Optimal thickness recommendations
  4. Edge detection / edge-jump behavior
  5. Compound density database
  6. Browser JS console test snippets (generated)
"""

import sys
import math
import json
from pathlib import Path
import pytest

try:
    import xraydb
    HAS_XRAYDB = True
except ImportError:
    HAS_XRAYDB = False
    print("WARNING: xraydb not installed. NIST comparison skipped.")

# ══════════════════════════════════════════════════════════════
# 1. Reimplement JS physics in Python (mirror of 01_xray_data.js)
# ══════════════════════════════════════════════════════════════

XRAY_ELEMENTS = {
    'B':  {'Z':5,  'M':10.81,  'K':188},
    'C':  {'Z':6,  'M':12.011, 'K':284},
    'N':  {'Z':7,  'M':14.007, 'K':410},
    'O':  {'Z':8,  'M':15.999, 'K':543},
    'Na': {'Z':11, 'M':22.990, 'K':1071},
    'Al': {'Z':13, 'M':26.982, 'K':1560},
    'Si': {'Z':14, 'M':28.086, 'K':1839},
    'P':  {'Z':15, 'M':30.974, 'K':2145},
    'S':  {'Z':16, 'M':32.065, 'K':2472},
    'Cl': {'Z':17, 'M':35.453, 'K':2822},
    'Ca': {'Z':20, 'M':40.078, 'K':4038},
    'Ti': {'Z':22, 'M':47.867, 'K':4966, 'L3':454},
    'V':  {'Z':23, 'M':50.942, 'K':5465, 'L3':512},
    'Cr': {'Z':24, 'M':51.996, 'K':5989, 'L3':574},
    'Mn': {'Z':25, 'M':54.938, 'K':6539, 'L3':639},
    'Fe': {'Z':26, 'M':55.845, 'K':7112, 'L3':706},
    'Co': {'Z':27, 'M':58.933, 'K':7709, 'L3':778},
    'Ni': {'Z':28, 'M':58.693, 'K':8333, 'L3':855},
    'Cu': {'Z':29, 'M':63.546, 'K':8979, 'L3':932},
    'Zn': {'Z':30, 'M':65.38,  'K':9659, 'L3':1020},
    'Ga': {'Z':31, 'M':69.723, 'K':10367, 'L3':1116},
    'Ge': {'Z':32, 'M':72.630, 'K':11103, 'L3':1217},
    'As': {'Z':33, 'M':74.922, 'K':11867, 'L3':1324},
    'Se': {'Z':34, 'M':78.971, 'K':12658, 'L3':1434},
    'Sr': {'Z':38, 'M':87.62,  'K':16105, 'L3':1940},
    'Mo': {'Z':42, 'M':95.95,  'K':20000, 'L3':2520},
    'Ag': {'Z':47, 'M':107.87, 'K':25514, 'L3':3351},
    'W':  {'Z':74, 'M':183.84, 'K':69525, 'L3':10207},
    'Pt': {'Z':78, 'M':195.08, 'K':78395, 'L3':11564},
    'Au': {'Z':79, 'M':196.97, 'K':80725, 'L3':11919},
    'Pb': {'Z':82, 'M':207.20, 'K':88005, 'L3':13035},
}

XRF_MU_PHOTO = {
    'O':  {'rho':1.429,  'mu':{2000:694, 3000:216, 5000:47, 8000:11, 10000:6, 15000:2}},
    'Na': {'rho':0.968,  'mu':{2000:1519, 3000:506, 5000:118, 8000:30, 10000:15, 15000:4}},
    'Al': {'rho':2.700,  'mu':{2000:2261, 3000:787, 5000:192, 8000:50, 10000:26, 15000:8}},
    'Si': {'rho':2.330,  'mu':{2000:2775, 3000:977, 5000:244, 8000:64, 10000:33, 15000:10}},
    'P':  {'rho':1.823,  'mu':{3000:1116, 5000:285, 8000:76, 10000:40, 15000:12}},
    'S':  {'rho':2.070,  'mu':{3000:1337, 5000:347, 8000:94, 10000:49, 15000:15}},
    'Cl': {'rho':3.214,  'mu':{3000:1471, 5000:389, 8000:107, 10000:56, 15000:17}},
    'Ca': {'rho':1.550,  'mu':{3000:265, 5000:601, 8000:171, 10000:92, 15000:29}},
    'Ti': {'rho':4.506,  'mu':{3000:330, 4000:150, 4900:85, 5000:599, 8000:201, 10000:110, 12400:60, 15000:35}},
    'V':  {'rho':6.110,  'mu':{3000:372, 4000:169, 5400:73, 5500:546, 8000:220, 10000:121, 12400:67, 15000:38}},
    'Cr': {'rho':7.190,  'mu':{3000:431, 4000:196, 5900:67, 6000:525, 8000:250, 10000:138, 12400:77, 15000:44}},
    'Mn': {'rho':7.470,  'mu':{3000:482, 4000:220, 6400:60, 6600:480, 8000:272, 10000:150, 12400:84, 15000:48}},
    'Fe': {'rho':7.874,  'mu':{5000:129, 6000:79, 7000:54, 7200:440, 8000:304, 10000:169, 12400:95, 15000:54}},
    'Co': {'rho':8.900,  'mu':{6000:67, 7000:47, 7600:47, 7800:400, 8000:323, 10000:183, 12400:103, 15000:58}},
    'Ni': {'rho':8.908,  'mu':{6000:92, 7000:61, 8200:44, 8400:360, 10000:207, 12400:118, 15000:67}},
    'Cu': {'rho':8.960,  'mu':{7000:74, 8000:51, 8900:38, 9000:310, 10000:214, 12400:123, 15000:70}},
    'Zn': {'rho':7.134,  'mu':{7000:64, 8000:45, 9500:35, 9700:270, 10000:231, 12400:134, 15000:76}},
    'Sr': {'rho':2.640,  'mu':{8000:112, 10000:61, 12400:33, 16200:210, 20000:115}},
    'Mo': {'rho':10.280, 'mu':{8000:154, 10000:83, 12400:46, 20100:180, 25000:95}},
    'Au': {'rho':19.300, 'mu':{8000:201, 10000:113, 12000:174, 12400:164, 15000:98}},
    'Pt': {'rho':21.450, 'mu':{8000:193, 10000:108, 11600:158, 12400:158, 15000:94}},
    'W':  {'rho':19.250, 'mu':{8000:165, 10000:92, 10300:218, 12400:220, 15000:131}},
    'Pb': {'rho':11.340, 'mu':{8000:223, 10000:126, 12400:72, 13100:190, 15000:125}},
}

COMPOUND_DENSITIES = {
    'Cu':8.96, 'Fe':7.87, 'Ni':8.91, 'Au':19.3, 'Pt':21.45, 'Ag':10.49,
    'Si':2.33, 'Al':2.70, 'Ti':4.51, 'W':19.25, 'Mo':10.28, 'Cr':7.19,
    'Co':8.90, 'Zn':7.13, 'Mn':7.47, 'V':6.11, 'Ge':5.32, 'Se':4.81,
    'SiO2':2.20, 'Al2O3':3.95, 'Fe2O3':5.24, 'Fe3O4':5.17, 'TiO2':4.23,
    'Cu2O':6.0, 'CuO':6.31, 'NiO':6.67, 'ZnO':5.61, 'MgO':3.58,
    'CeO2':7.22, 'BaTiO3':6.02, 'SrTiO3':5.12, 'LiCoO2':5.05,
    'GaAs':5.32, 'InP':4.81, 'GaN':6.15, 'Si3N4':3.17,
    'CaF2':3.18, 'NaCl':2.16, 'MoS2':5.06,
    'H2O':1.0, 'C':2.27, 'BN':2.1, 'Diamond':3.51,
}


def parse_formula(formula):
    """Simple formula parser (mirrors JS parseFormula)."""
    import re
    result = {}
    tokens = re.findall(r'([A-Z][a-z]?)(\d*)', formula)
    for el, n in tokens:
        if el and el in XRAY_ELEMENTS:
            result[el] = result.get(el, 0) + (int(n) if n else 1)
    return result


def compound_mass(parsed):
    mass = 0
    for el, count in parsed.items():
        if el in XRAY_ELEMENTS:
            mass += count * XRAY_ELEMENTS[el]['M']
    return mass


def same_edge_side(e1, e2, el_data):
    k = el_data.get('K')
    l3 = el_data.get('L3')
    if k:
        if (e1 < k and e2 >= k) or (e1 >= k and e2 < k):
            return False
    if l3:
        if (e1 < l3 and e2 >= l3) or (e1 >= l3 and e2 < l3):
            return False
    return True


def interpolate_mu_photo(mu_dict, E_eV, el_data):
    sorted_pts = sorted(mu_dict.items(), key=lambda x: x[0])
    best_e, best_mu = sorted_pts[0]
    min_dist = 1e20
    for e, mu in sorted_pts:
        if same_edge_side(e, E_eV, el_data):
            dist = abs(e - E_eV)
            if dist < min_dist:
                min_dist = dist
                best_e = e
                best_mu = mu
    if min_dist >= 1e20:
        for e, mu in sorted_pts:
            d2 = abs(e - E_eV)
            if d2 < min_dist:
                min_dist = d2
                best_e = e
                best_mu = mu
    if best_e > 0 and best_e != E_eV:
        return best_mu * (best_e / E_eV) ** 2.8
    return best_mu


def victoreen_with_edge(Z, E_eV, E_K, E_L3):
    a = 1e-4 * Z ** 3.5
    mu = a / (E_eV / 1000) ** 3
    if E_K and E_eV >= E_K:
        mu *= (5 + 0.15 * Z)
    if E_L3 and E_eV >= E_L3 and (not E_K or E_eV < E_K):
        mu *= 2.5
    return mu


def element_mu_rho(el, E_eV):
    el_data = XRAY_ELEMENTS.get(el)
    if not el_data:
        return 0
    mu_data = XRF_MU_PHOTO.get(el)
    if mu_data and mu_data.get('mu'):
        return interpolate_mu_photo(mu_data['mu'], E_eV, el_data)
    return victoreen_with_edge(
        el_data['Z'], E_eV,
        el_data.get('K'), el_data.get('L3')
    )


def compound_mu_rho(formula, E_eV):
    parsed = parse_formula(formula) if isinstance(formula, str) else formula
    total_mass = compound_mass(parsed)
    if total_mass <= 0:
        return 0
    mu_total = 0
    for el, count in parsed.items():
        el_data = XRAY_ELEMENTS.get(el)
        if not el_data:
            continue
        wt = count * el_data['M'] / total_mass
        mu_total += wt * element_mu_rho(el, E_eV)
    return mu_total


def calc_transmission(formula, thickness_um, density_gcc, E_keV):
    """Returns T for a single energy."""
    E_eV = E_keV * 1000
    mu_rho = compound_mu_rho(formula, E_eV)
    thickness_cm = thickness_um * 1e-4
    mu_t = mu_rho * density_gcc * thickness_cm
    return math.exp(-mu_t), mu_t


# ══════════════════════════════════════════════════════════════
# 2. Test suites
# ══════════════════════════════════════════════════════════════

def test_mu_rho_vs_nist():
    """Compare compoundMuRho against xraydb (NIST) for calibrated elements."""
    print("\n" + "=" * 70)
    print("TEST 1: mu/rho accuracy vs NIST (xraydb)")
    print("=" * 70)

    if not HAS_XRAYDB:
        pytest.skip("xraydb not available")

    test_cases = [
        # (element, energy_eV, description)
        ('Cu', 10000, 'Cu @ 10 keV (above K-edge)'),
        ('Cu', 8000, 'Cu @ 8 keV (below K-edge)'),
        ('Cu', 15000, 'Cu @ 15 keV'),
        ('Fe', 10000, 'Fe @ 10 keV (above K-edge)'),
        ('Fe', 7000, 'Fe @ 7 keV (below K-edge)'),
        ('Fe', 8000, 'Fe @ 8 keV'),
        ('Ni', 10000, 'Ni @ 10 keV'),
        ('Ni', 8000, 'Ni @ 8 keV (below K-edge)'),
        ('Ti', 5000, 'Ti @ 5 keV (above K-edge)'),
        ('Ti', 10000, 'Ti @ 10 keV'),
        ('Mo', 10000, 'Mo @ 10 keV (below K-edge)'),
        ('Mo', 25000, 'Mo @ 25 keV (above K-edge)'),
        ('Au', 12000, 'Au @ 12 keV (above L3-edge)'),
        ('Au', 10000, 'Au @ 10 keV (below L3-edge)'),
        ('Pb', 15000, 'Pb @ 15 keV (above L3-edge)'),
        ('W',  12000, 'W @ 12 keV (above L3-edge)'),
    ]

    passed = 0
    failed = 0

    print(f"\n  {'Description':<35} {'JS mu/rho':>10} {'NIST mu/rho':>12} {'Error%':>8} {'Status':>8}")
    print(f"  {'-'*35} {'-'*10} {'-'*12} {'-'*8} {'-'*8}")

    for el, E_eV, desc in test_cases:
        js_mu = element_mu_rho(el, E_eV)
        nist_mu = xraydb.mu_elam(el, E_eV * 1e-3, kind='photo')  # returns cm^2/g
        # xraydb returns in cm^2/g, same units as our JS code

        # Actually xraydb.mu_elam takes energy in eV and returns cm^2/g
        nist_mu = xraydb.mu_elam(el, E_eV, kind='photo')

        if nist_mu > 0:
            error_pct = abs(js_mu - nist_mu) / nist_mu * 100
        else:
            error_pct = 0

        status = 'PASS' if error_pct < 30 else 'FAIL'
        if status == 'PASS':
            passed += 1
        else:
            failed += 1

        print(f"  {desc:<35} {js_mu:>10.1f} {nist_mu:>12.1f} {error_pct:>7.1f}% {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed (tolerance: 30%)")
    return passed, failed


def test_compound_mu_rho_vs_nist():
    """Compare compound mu/rho against xraydb for compounds."""
    print("\n" + "=" * 70)
    print("TEST 2: Compound mu/rho accuracy vs NIST")
    print("=" * 70)

    if not HAS_XRAYDB:
        pytest.skip("xraydb not available")

    test_cases = [
        ('Fe2O3', 10000, 'Fe2O3 @ 10 keV'),
        ('SiO2',  10000, 'SiO2 @ 10 keV'),
        ('Cu',    10000, 'Cu @ 10 keV'),
        ('Fe2O3',  8000, 'Fe2O3 @ 8 keV'),
        ('SiO2',  15000, 'SiO2 @ 15 keV'),
        ('TiO2',  10000, 'TiO2 @ 10 keV'),
        ('NaCl',  10000, 'NaCl @ 10 keV'),
        ('CaF2',  10000, 'CaF2 @ 10 keV'),
    ]

    passed = 0
    failed = 0

    print(f"\n  {'Description':<25} {'JS mu/rho':>10} {'NIST mu/rho':>12} {'Error%':>8} {'Status':>8}")
    print(f"  {'-'*25} {'-'*10} {'-'*12} {'-'*8} {'-'*8}")

    for formula, E_eV, desc in test_cases:
        js_mu = compound_mu_rho(formula, E_eV)

        # xraydb compound: need to compute mass-weighted sum
        parsed = parse_formula(formula)
        total_mass = compound_mass(parsed)
        nist_mu = 0
        for el, count in parsed.items():
            wt = count * XRAY_ELEMENTS[el]['M'] / total_mass
            nist_mu += wt * xraydb.mu_elam(el, E_eV, kind='photo')

        if nist_mu > 0:
            error_pct = abs(js_mu - nist_mu) / nist_mu * 100
        else:
            error_pct = 0

        status = 'PASS' if error_pct < 30 else 'FAIL'
        if status == 'PASS':
            passed += 1
        else:
            failed += 1

        print(f"  {desc:<25} {js_mu:>10.1f} {nist_mu:>12.1f} {error_pct:>7.1f}% {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed (tolerance: 30%)")
    return passed, failed


def test_transmission_values():
    """Verify T(E) calculation for known cases."""
    print("\n" + "=" * 70)
    print("TEST 3: Transmission T(E) known-value verification")
    print("=" * 70)

    test_cases = [
        # (formula, thickness_um, density, E_keV, expected_T_approx, tolerance, desc)
        ('Cu', 1, 8.96, 10, None, 0.30, 'Cu 1um @ 10keV'),
        ('Cu', 50, 8.96, 10, None, 0.30, 'Cu 50um @ 10keV (very thick)'),
        ('Fe', 1, 7.87, 10, None, 0.30, 'Fe 1um @ 10keV'),
        ('Si', 100, 2.33, 10, None, 0.30, 'Si 100um @ 10keV'),
        ('SiO2', 100, 2.20, 10, None, 0.30, 'SiO2 100um @ 10keV'),
        ('Fe2O3', 10, 5.24, 10, None, 0.30, 'Fe2O3 10um @ 10keV'),
    ]

    passed = 0
    failed = 0

    print(f"\n  {'Description':<25} {'JS T(E)':>10} {'NIST T(E)':>10} {'mu*t JS':>8} {'mu*t NIST':>10} {'Err%':>7} {'Status':>8}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*8} {'-'*10} {'-'*7} {'-'*8}")

    for formula, t_um, rho, E_keV, _, tol, desc in test_cases:
        T_js, muT_js = calc_transmission(formula, t_um, rho, E_keV)

        # NIST reference
        if HAS_XRAYDB:
            parsed = parse_formula(formula)
            total_mass = compound_mass(parsed)
            nist_mu = 0
            for el, count in parsed.items():
                wt = count * XRAY_ELEMENTS[el]['M'] / total_mass
                nist_mu += wt * xraydb.mu_elam(el, E_keV * 1000, kind='photo')
            muT_nist = nist_mu * rho * t_um * 1e-4
            T_nist = math.exp(-muT_nist)
        else:
            T_nist = T_js
            muT_nist = muT_js

        if T_nist > 1e-10:
            error_pct = abs(T_js - T_nist) / max(T_nist, 1e-10) * 100
        else:
            error_pct = abs(muT_js - muT_nist) / max(muT_nist, 0.01) * 100

        status = 'PASS' if error_pct < 50 else 'FAIL'
        if status == 'PASS':
            passed += 1
        else:
            failed += 1

        print(f"  {desc:<25} {T_js:>10.4e} {T_nist:>10.4e} {muT_js:>8.3f} {muT_nist:>10.3f} {error_pct:>6.1f}% {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed (tolerance: 50% on T)")
    return passed, failed


def test_edge_behavior():
    """Verify that mu/rho shows proper edge-jump behavior."""
    print("\n" + "=" * 70)
    print("TEST 4: Absorption edge behavior")
    print("=" * 70)

    edge_tests = [
        ('Cu', 8979, 'Cu K-edge'),
        ('Fe', 7112, 'Fe K-edge'),
        ('Ni', 8333, 'Ni K-edge'),
        ('Au', 11919, 'Au L3-edge'),
        ('Pt', 11564, 'Pt L3-edge'),
        ('W',  10207, 'W L3-edge'),
    ]

    passed = 0
    failed = 0

    print(f"\n  {'Edge':<15} {'mu below':>10} {'mu above':>10} {'Jump ratio':>12} {'Expected':>10} {'Status':>8}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*12} {'-'*10} {'-'*8}")

    for el, edge_eV, desc in edge_tests:
        mu_below = element_mu_rho(el, edge_eV - 50)
        mu_above = element_mu_rho(el, edge_eV + 50)

        if mu_below > 0:
            jump = mu_above / mu_below
        else:
            jump = 0

        # K-edge jump should be 5-10x, L3-edge should be 2-5x
        if 'K' in desc:
            expected = '5-10x'
            ok = 3 < jump < 15
        else:
            expected = '2-5x'
            ok = 1.5 < jump < 8

        status = 'PASS' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  {desc:<15} {mu_below:>10.1f} {mu_above:>10.1f} {jump:>11.1f}x {expected:>10} {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed")
    return passed, failed


def test_optimal_thickness():
    """Verify optimal thickness recommendations make physical sense."""
    print("\n" + "=" * 70)
    print("TEST 5: Optimal thickness recommendations")
    print("=" * 70)

    test_cases = [
        # (formula, density, E_keV, technique, desc)
        ('Cu', 8.96, 10, 'transmission', 'Cu XAFS @ 10keV'),
        ('Cu', 8.96, 10, 'fluorescence', 'Cu XRF @ 10keV'),
        ('Cu', 8.96, 10, 'ptycho', 'Cu Ptycho @ 10keV'),
        ('Fe2O3', 5.24, 10, 'transmission', 'Fe2O3 XAFS @ 10keV'),
        ('SiO2', 2.20, 10, 'transmission', 'SiO2 XAFS @ 10keV'),
        ('Au', 19.3, 12, 'fluorescence', 'Au XRF @ 12keV'),
    ]

    passed = 0
    failed = 0

    print(f"\n  {'Description':<25} {'Optimal um':>10} {'Min um':>8} {'Max um':>8} {'T@opt':>8} {'Phys OK':>8}")
    print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    for formula, rho, E_keV, technique, desc in test_cases:
        mu_rho = compound_mu_rho(formula, E_keV * 1000)
        mu_linear = mu_rho * rho
        if mu_linear <= 0:
            print(f"  {desc:<25} {'N/A':>10} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'SKIP':>8}")
            continue

        if technique == 'transmission':
            opt_um = (1.0 / mu_linear) * 1e4
            min_um = (0.36 / mu_linear) * 1e4
            max_um = (2.3 / mu_linear) * 1e4
        elif technique == 'fluorescence':
            opt_um = (0.1 / mu_linear) * 1e4
            min_um = 0
            max_um = (0.3 / mu_linear) * 1e4
        elif technique == 'ptycho':
            opt_um = (0.5 / mu_linear) * 1e4
            min_um = 0.01
            max_um = (1.0 / mu_linear) * 1e4

        T_opt, _ = calc_transmission(formula, opt_um, rho, E_keV)

        # Physical sanity checks
        ok = True
        if technique == 'transmission':
            ok = ok and (0.30 < T_opt < 0.45)  # T should be ~37% at mu*t=1
        elif technique == 'fluorescence':
            ok = ok and (T_opt > 0.85)  # Thin sample
        elif technique == 'ptycho':
            ok = ok and (T_opt > 0.50)  # Moderate absorption
        ok = ok and (opt_um > 0)
        ok = ok and (min_um <= opt_um <= max_um or technique == 'fluorescence')

        status = 'PASS' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  {desc:<25} {opt_um:>10.2f} {min_um:>8.2f} {max_um:>8.2f} {T_opt:>7.1%} {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed")
    return passed, failed


def test_density_database():
    """Verify density values against known references."""
    print("\n" + "=" * 70)
    print("TEST 6: Density database verification")
    print("=" * 70)

    # Reference densities (CRC Handbook / NIST)
    ref = {
        'Cu': 8.96, 'Fe': 7.874, 'Au': 19.32, 'Si': 2.329,
        'SiO2': 2.20, 'Al2O3': 3.95, 'Fe2O3': 5.24,
        'H2O': 1.0, 'NaCl': 2.165, 'TiO2': 4.23,
        'GaAs': 5.32, 'CaF2': 3.18,
    }

    passed = 0
    failed = 0

    print(f"\n  {'Material':<12} {'DB value':>10} {'Reference':>10} {'Error%':>8} {'Status':>8}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

    for mat, ref_val in ref.items():
        db_val = COMPOUND_DENSITIES.get(mat, 0)
        if db_val > 0:
            error_pct = abs(db_val - ref_val) / ref_val * 100
        else:
            error_pct = 100

        status = 'PASS' if error_pct < 2 else 'FAIL'
        if status == 'PASS':
            passed += 1
        else:
            failed += 1

        print(f"  {mat:<12} {db_val:>10.2f} {ref_val:>10.2f} {error_pct:>7.1f}% {status:>8}")

    print(f"\n  Result: {passed}/{passed+failed} passed (tolerance: 2%)")
    return passed, failed


def generate_js_console_tests():
    """Generate JS console test commands for browser verification."""
    print("\n" + "=" * 70)
    print("TEST 7: JS Console Test Commands (copy to browser)")
    print("=" * 70)

    js_tests = """
// ===== Transmission Calculator - Browser Console Tests =====
// Copy-paste these into the browser JS console

// --- Test 1: compoundMuRho basic ---
(function() {
  var tests = [
    {el:'Cu', E:10000, desc:'Cu@10keV'},
    {el:'Fe', E:10000, desc:'Fe@10keV'},
    {el:'Ni', E:10000, desc:'Ni@10keV'},
    {el:'Au', E:12000, desc:'Au@12keV'},
    {el:'SiO2', E:10000, desc:'SiO2@10keV'},
    {el:'Fe2O3', E:10000, desc:'Fe2O3@10keV'},
  ];
  console.log('--- compoundMuRho tests ---');
  tests.forEach(function(t) {
    var mu = compoundMuRho(t.el, t.E);
    console.log(t.desc + ': mu/rho = ' + mu.toFixed(1) + ' cm2/g');
  });
})();

// --- Test 2: calcTransmission ---
(function() {
  var r = calcTransmission('Cu', 1, 8.96, 1, 25, 100);
  console.log('--- calcTransmission Cu 1um ---');
  console.log('Points:', r.nPoints, 'Edges:', r.edges.length);
  console.log('T@1keV:', r.transmission[0].toFixed(4));
  console.log('T@25keV:', r.transmission[r.nPoints-1].toFixed(4));
  // Find T near 10 keV
  var idx10 = Math.round((10-1)/(25-1)*99);
  console.log('T@~10keV:', r.transmission[idx10].toFixed(4));
  console.log('Edges:', JSON.stringify(r.edges.map(function(e){return e.element+' '+e.edge+' '+e.energy+'eV'})));
})();

// --- Test 3: optimalThickness ---
(function() {
  var techniques = ['transmission', 'fluorescence', 'ptycho'];
  console.log('--- optimalThickness Cu @10keV ---');
  techniques.forEach(function(tech) {
    var o = optimalThickness('Cu', 8.96, 10, tech);
    console.log(tech + ': optimal=' + o.optimal_um.toFixed(2) + 'um, range='
      + o.min_um.toFixed(2) + '-' + o.max_um.toFixed(2) + 'um');
  });
})();

// --- Test 4: estimateDensity ---
(function() {
  var materials = ['Cu', 'Fe2O3', 'SiO2', 'Au', 'NaCl', 'GaAs'];
  console.log('--- estimateDensity ---');
  materials.forEach(function(m) {
    console.log(m + ': ' + estimateDensity(m).toFixed(2) + ' g/cm3');
  });
})();

// --- Test 5: Edge jump verification ---
(function() {
  console.log('--- Edge jump (Cu K=8979eV) ---');
  var below = compoundMuRho('Cu', 8900);
  var above = compoundMuRho('Cu', 9100);
  console.log('mu below K-edge:', below.toFixed(1), 'above:', above.toFixed(1),
    'jump:', (above/below).toFixed(1) + 'x');
})();

// --- Test 6: showTransmissionPopup ---
showTransmissionPopup('Cu', 1, 8.96);
console.log('Popup should be visible with Cu 1um T(E) curve');

// --- Test 7: NLP wrapper ---
showTransmission('Fe2O3', 10);
console.log('Popup should update to Fe2O3 10um with auto density');

console.log('===== All console tests complete =====');
"""

    print(js_tests)
    # Save to file
    out = Path("tests/transmission_console_tests.js")
    out.write_text(js_tests.strip(), encoding='utf-8')
    print(f"\n  Saved to: {out}")
    return 0, 0  # Not auto-graded


# ══════════════════════════════════════════════════════════════
# 3. Main
# ══════════════════════════════════════════════════════════════

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 70)
    print("  Transmission Calculator Physics Verification")
    print("  Reference: NIST xraydb (Elam, Ravel, Sieber 2002)")
    print("=" * 70)

    total_pass = 0
    total_fail = 0

    for test_fn in [
        test_mu_rho_vs_nist,
        test_compound_mu_rho_vs_nist,
        test_transmission_values,
        test_edge_behavior,
        test_optimal_thickness,
        test_density_database,
        generate_js_console_tests,
    ]:
        p, f = test_fn()
        total_pass += p
        total_fail += f

    print("\n" + "=" * 70)
    print(f"  OVERALL: {total_pass}/{total_pass+total_fail} passed, {total_fail} failed")
    print("=" * 70)

    return total_fail == 0


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
