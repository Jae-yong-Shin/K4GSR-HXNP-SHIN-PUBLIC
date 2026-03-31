"""
MC vs S4 Benchmark: Run MC ray trace in headless browser via Playwright.
Measures FWHM for multiple energy/SSA conditions, with and without hybrid.
Compares against stored S4 results.
"""
import json, time, os, sys
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(__file__),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')
S4_DATA = os.path.join(os.path.dirname(__file__), 'paper', 'validation', 'data')

CONDITIONS = [
    {'name': '10keV SSA50',  'energy': 10.0, 'ssaH': 50,  'ssaV': 50},
    {'name': '5keV SSA50',   'energy': 5.0,  'ssaH': 50,  'ssaV': 50},
    {'name': '20keV SSA50',  'energy': 20.0, 'ssaH': 50,  'ssaV': 50},
    {'name': '10keV SSA10',  'energy': 10.0, 'ssaH': 10,  'ssaV': 10},
    {'name': '10keV SSA200', 'energy': 10.0, 'ssaH': 200, 'ssaV': 200},
]

NRAYS = 200000  # high stats for accurate FWHM
N_REPEATS = 3   # average over repeats


def load_s4_results():
    """Load pre-computed S4 results."""
    s4 = {}
    files = {
        '10keV SSA50':  's4_10keV_ssa50.json',
        '5keV SSA50':   's4_5keV_ssa50.json',
        '20keV SSA50':  's4_20keV_ssa50.json',
        '10keV SSA10':  's4_10keV_ssa10.json',
        '10keV SSA200': 's4_10keV_ssa200.json',
    }
    for name, fname in files.items():
        path = os.path.join(S4_DATA, fname)
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            s4[name] = {
                'fwhm_h_nm': d.get('fine_fwhm_h_mean_m',
                                   d.get('fine_fwhm_h_m', 0)) * 1e9,
                'fwhm_v_nm': d.get('fine_fwhm_v_mean_m',
                                   d.get('fine_fwhm_v_m', 0)) * 1e9,
                'nrays': d.get('nrays_good_mean',
                               d.get('nrays_good', 0)),
            }
    return s4


def run_mc(page, energy, ssaH, ssaV, nrays, hybrid=True):
    """Run MC ray trace and return FWHM results."""
    # Set state
    page.evaluate(f"""(() => {{
        state.energy = {energy};
        state.ssaH = {ssaH};
        state.ssaV = {ssaV};
        // Update optics for new energy
        if (typeof updateEnergy === 'function') updateEnergy({energy});
        if (typeof updateOptics === 'function') updateOptics();
    }})()""")

    # Disable or enable hybrid
    if not hybrid:
        page.evaluate("""(() => {
            window._hybridBackup_fresnel = window._applyHybridFresnel;
            window._hybridBackup_ssa = window._applySSAHybrid;
            window._applyHybridFresnel = function() {};
            window._applySSAHybrid = function() {};
        })()""")
    else:
        # Restore if previously disabled
        page.evaluate("""(() => {
            if (window._hybridBackup_fresnel) {
                window._applyHybridFresnel = window._hybridBackup_fresnel;
            }
            if (window._hybridBackup_ssa) {
                window._applySSAHybrid = window._hybridBackup_ssa;
            }
        })()""")

    # Run MC
    result = page.evaluate(f"""(() => {{
        var samplePos = pos('sample') || 150.0;
        var mc = mcRayTrace(samplePos, {nrays});
        return {{
            fwhmH: mc.fwhmH,
            fwhmV: mc.fwhmV,
            sigH: mc.sigH,
            sigV: mc.sigV,
            nSurvived: mc.nSurvived,
            nTotal: mc.nTotal
        }};
    }})()""")
    return result


def main():
    s4 = load_s4_results()

    print(f"MC vs S4 Benchmark")
    print(f"nRays = {NRAYS}, repeats = {N_REPEATS}")
    print(f"Bundle: {os.path.basename(BUNDLE)}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Load bundle
        print("Loading bundle HTML...")
        t0 = time.time()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        # Wait for JS to initialize
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print(f"Loaded in {time.time()-t0:.1f}s")
        print()

        # Check initial state
        init = page.evaluate("({e: state.energy, ssa: state.ssaH})")
        print(f"Initial state: E={init['e']} keV, SSA={init['ssa']} um")
        print()

        # ==== Benchmark: WITH hybrid ====
        print("=" * 90)
        print("WITH HYBRID (full physics)")
        print("=" * 90)
        hdr = f"{'Condition':<16s} {'MC H(nm)':>10s} {'MC V(nm)':>10s}"
        hdr += f" {'S4 H(nm)':>10s} {'S4 V(nm)':>10s}"
        hdr += f" {'dH%':>7s} {'dV%':>7s} {'rays':>8s}"
        print(hdr)
        print("-" * 90)

        mc_hybrid = {}
        for cond in CONDITIONS:
            fwhm_h_list, fwhm_v_list, rays_list = [], [], []
            for rep in range(N_REPEATS):
                r = run_mc(page, cond['energy'], cond['ssaH'], cond['ssaV'],
                          NRAYS, hybrid=True)
                fwhm_h_list.append(r['fwhmH'] * 1e9)
                fwhm_v_list.append(r['fwhmV'] * 1e9)
                rays_list.append(r['nSurvived'])

            mc_h = sum(fwhm_h_list) / len(fwhm_h_list)
            mc_v = sum(fwhm_v_list) / len(fwhm_v_list)
            mc_rays = sum(rays_list) / len(rays_list)

            s4r = s4.get(cond['name'], {})
            s4_h = s4r.get('fwhm_h_nm', 0)
            s4_v = s4r.get('fwhm_v_nm', 0)

            dh = (mc_h - s4_h) / s4_h * 100 if s4_h > 0 else 0
            dv = (mc_v - s4_v) / s4_v * 100 if s4_v > 0 else 0

            mc_hybrid[cond['name']] = {'h': mc_h, 'v': mc_v, 'rays': mc_rays}

            line = f"{cond['name']:<16s} {mc_h:10.1f} {mc_v:10.1f}"
            line += f" {s4_h:10.1f} {s4_v:10.1f}"
            line += f" {dh:+6.1f}% {dv:+6.1f}% {mc_rays:8.0f}"
            print(line)

        print()

        # ==== Benchmark: WITHOUT hybrid (geometric only) ====
        print("=" * 90)
        print("WITHOUT HYBRID (geometric only)")
        print("=" * 90)
        hdr2 = f"{'Condition':<16s} {'Geo H(nm)':>10s} {'Geo V(nm)':>10s}"
        hdr2 += f" {'Hyb H(nm)':>10s} {'Hyb V(nm)':>10s}"
        hdr2 += f" {'Quad H':>10s} {'Quad V':>10s}"
        print(hdr2)
        print("-" * 90)

        for cond in CONDITIONS:
            fwhm_h_list, fwhm_v_list = [], []
            for rep in range(N_REPEATS):
                r = run_mc(page, cond['energy'], cond['ssaH'], cond['ssaV'],
                          NRAYS, hybrid=False)
                fwhm_h_list.append(r['fwhmH'] * 1e9)
                fwhm_v_list.append(r['fwhmV'] * 1e9)

            geo_h = sum(fwhm_h_list) / len(fwhm_h_list)
            geo_v = sum(fwhm_v_list) / len(fwhm_v_list)

            hyb = mc_hybrid.get(cond['name'], {})
            hyb_h = hyb.get('h', 0)
            hyb_v = hyb.get('v', 0)

            # Quadrature: sqrt(geo^2 + (hyb^2 - geo^2)) should equal hyb
            # But let's compute: diffraction contribution = sqrt(hyb^2 - geo^2)
            import math
            diff_h = math.sqrt(max(0, hyb_h**2 - geo_h**2))
            diff_v = math.sqrt(max(0, hyb_v**2 - geo_v**2))
            quad_h = math.sqrt(geo_h**2 + diff_h**2)
            quad_v = math.sqrt(geo_v**2 + diff_v**2)

            line = f"{cond['name']:<16s} {geo_h:10.1f} {geo_v:10.1f}"
            line += f" {hyb_h:10.1f} {hyb_v:10.1f}"
            line += f" {quad_h:10.1f} {quad_v:10.1f}"
            print(line)

        # Restore hybrid
        page.evaluate("""(() => {
            if (window._hybridBackup_fresnel) {
                window._applyHybridFresnel = window._hybridBackup_fresnel;
            }
            if (window._hybridBackup_ssa) {
                window._applySSAHybrid = window._hybridBackup_ssa;
            }
        })()""")

        print()

        # ==== Summary ====
        print("=" * 90)
        print("SUMMARY: MC vs S4 deviation")
        print("=" * 90)
        total_dev = []
        for cond in CONDITIONS:
            hyb = mc_hybrid.get(cond['name'], {})
            s4r = s4.get(cond['name'], {})
            mc_h = hyb.get('h', 0)
            mc_v = hyb.get('v', 0)
            s4_h = s4r.get('fwhm_h_nm', 0)
            s4_v = s4r.get('fwhm_v_nm', 0)
            if s4_h > 0 and s4_v > 0:
                dh = abs(mc_h - s4_h) / s4_h * 100
                dv = abs(mc_v - s4_v) / s4_v * 100
                total_dev.extend([dh, dv])
                print(f"  {cond['name']:<16s}  |dH|={dh:.1f}%  |dV|={dv:.1f}%")

        if total_dev:
            avg = sum(total_dev) / len(total_dev)
            mx = max(total_dev)
            print(f"\n  Average |deviation| = {avg:.1f}%")
            print(f"  Max |deviation|     = {mx:.1f}%")
            print(f"  Target: < 5%")

        browser.close()


if __name__ == '__main__':
    main()
