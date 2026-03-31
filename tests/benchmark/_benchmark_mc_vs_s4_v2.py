"""
MC vs S4 Benchmark v2: Instrumented to capture KB footprint diagnostics.
"""
import json, time, os, math
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

NRAYS = 500000
N_REPEATS = 5
SRC_BW_EV = 1.0  # Source bandwidth in eV (0 = monochromatic)


def load_s4_results():
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


def main():
    s4 = load_s4_results()
    print(f"MC vs S4 Benchmark v2 (with KB footprint diagnostics)")
    print(f"nRays = {NRAYS}, repeats = {N_REPEATS}, sourceBW = {SRC_BW_EV} eV")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Loading bundle...")
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.\n")

        # Print harmonic selection for each energy
        print("Harmonic selection:")
        for E in sorted(set(c['energy'] for c in CONDITIONS)):
            info = page.evaluate(f"""(() => {{
                var b = selectBest({E});
                return b ? {{n: b.n, gap: b.gap.toFixed(2)}} : null;
            }})()""")
            if info:
                print(f"  {E} keV -> n={info['n']}, gap={info['gap']} mm")
        print()

        # ---- Run benchmarks (no instrumentation wrapper) ----
        print("=" * 90)
        print(f"{'Condition':<16s} {'MC H':>7s} {'MC V':>7s} {'S4 H':>7s} {'S4 V':>7s}"
              f" {'dH%':>7s} {'dV%':>7s} {'rays':>8s} {'thrput':>7s}")
        print("-" * 90)

        for cond in CONDITIONS:
            fh, fv, rays_l = [], [], []
            diag_last = None

            for rep in range(N_REPEATS):
                # Set state: selectBest finds correct harmonic for each energy
                page.evaluate(f"""(() => {{
                    state.sourceBW_eV = {SRC_BW_EV};
                    state.ssaH = {cond['ssaH']};
                    state.ssaV = {cond['ssaV']};
                    state.energy = {cond['energy']};
                    var best = selectBest({cond['energy']});
                    if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
                    if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({cond['energy']});
                    if (typeof updateEnergy === 'function') updateEnergy({cond['energy']});
                    if (typeof updateOptics === 'function') updateOptics();
                }})()""")

                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{
                        fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived, nTotal: mc.nTotal,
                        nBeams: mc.nBeams || null
                    }};
                }})()""")

                fh.append(result['fwhmH'] * 1e9)
                fv.append(result['fwhmV'] * 1e9)
                rays_l.append(result['nSurvived'])
                if result.get('nBeams') and rep == 0:
                    nb = result['nBeams']
                    diag_last = f"  nBeams: focused={nb.get('focused',0)}, direct={nb.get('direct',0)}, vOnly={nb.get('vOnly',0)}, hOnly={nb.get('hOnly',0)}"

            mc_h = sum(fh) / len(fh)
            mc_v = sum(fv) / len(fv)
            mc_rays = sum(rays_l) / len(rays_l)

            s4r = s4.get(cond['name'], {})
            s4_h = s4r.get('fwhm_h_nm', 0)
            s4_v = s4r.get('fwhm_v_nm', 0)
            dh = (mc_h - s4_h) / s4_h * 100 if s4_h > 0 else 0
            dv = (mc_v - s4_v) / s4_v * 100 if s4_v > 0 else 0
            thrput = mc_rays / NRAYS * 100

            print(f"{cond['name']:<16s} {mc_h:7.1f} {mc_v:7.1f} {s4_h:7.1f} {s4_v:7.1f}"
                  f" {dh:+6.1f}% {dv:+6.1f}% {mc_rays:8.0f} {thrput:6.2f}%")
            if diag_last:
                print(diag_last)

        print()

        # ---- Geometric-only (no hybrid) ----
        print("=" * 100)
        print("GEOMETRIC ONLY (hybrid disabled)")
        print(f"{'Condition':<16s} {'Geo H':>7s} {'Geo V':>7s} {'rays':>6s}")
        print("-" * 50)

        # Disable hybrid
        page.evaluate("""(() => {
            window._hybridBk1 = window._applyHybridFresnel;
            window._hybridBk2 = window._applySSAHybrid;
            window._applyHybridFresnel = function() {};
            window._applySSAHybrid = function() {};
        })()""")

        for cond in CONDITIONS:
            fh, fv, rays_l = [], [], []
            for rep in range(N_REPEATS):
                page.evaluate(f"""(() => {{
                    state.sourceBW_eV = {SRC_BW_EV};
                    state.ssaH = {cond['ssaH']};
                    state.ssaV = {cond['ssaV']};
                    state.energy = {cond['energy']};
                    var best = selectBest({cond['energy']});
                    if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
                    if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({cond['energy']});
                    if (typeof updateEnergy === 'function') updateEnergy({cond['energy']});
                    if (typeof updateOptics === 'function') updateOptics();
                }})()""")

                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{ fwhmH: mc.fwhmH, fwhmV: mc.fwhmV, nSurvived: mc.nSurvived }};
                }})()""")
                fh.append(result['fwhmH'] * 1e9)
                fv.append(result['fwhmV'] * 1e9)
                rays_l.append(result['nSurvived'])

            geo_h = sum(fh) / len(fh)
            geo_v = sum(fv) / len(fv)
            geo_rays = sum(rays_l) / len(rays_l)
            print(f"{cond['name']:<16s} {geo_h:7.1f} {geo_v:7.1f} {geo_rays:6.0f}")

        # Restore
        page.evaluate("""(() => {
            window._applyHybridFresnel = window._hybridBk1;
            window._applySSAHybrid = window._hybridBk2;
        })()""")

        browser.close()

    print("\nDone.")


if __name__ == '__main__':
    main()
