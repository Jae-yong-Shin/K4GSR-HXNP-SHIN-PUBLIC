import json, time, os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')

CONDITIONS = [
    {'name': '10keV SSA50',  'energy': 10.0, 'ssaH': 50,  'ssaV': 50,  's4_h': 40.8, 's4_v': 45.2},
    {'name': '5keV SSA50',   'energy': 5.0,  'ssaH': 50,  'ssaV': 50,  's4_h': 66.2, 's4_v': 70.8},
    {'name': '10keV SSA200', 'energy': 10.0, 'ssaH': 200, 'ssaV': 200, 's4_h': 50.4, 's4_v': 46.0},
]

NRAYS = 500000
N_REPEATS = 5

def main():
    print(f"MC vs S4 Benchmark (HIGH STATS)")
    print(f"nRays = {NRAYS}, repeats = {N_REPEATS}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Bundle loaded.\n")

        print(f"{'Condition':<16s} {'MC H':>7s} {'MC V':>7s} {'S4 H':>7s} {'S4 V':>7s}"
              f" {'dH%':>7s} {'dV%':>7s} {'rays':>8s} {'time':>6s}")
        print("-" * 80)

        for cond in CONDITIONS:
            fh, fv, rl = [], [], []
            t0 = time.time()
            for rep in range(N_REPEATS):
                page.evaluate(f"""(() => {{
                    state.energy = {cond['energy']};
                    state.ssaH = {cond['ssaH']};
                    state.ssaV = {cond['ssaV']};
                    if (typeof updateEnergy === 'function') updateEnergy({cond['energy']});
                    if (typeof updateOptics === 'function') updateOptics();
                }})()""")

                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{ fwhmH: mc.fwhmH, fwhmV: mc.fwhmV, nSurvived: mc.nSurvived }};
                }})()""")
                fh.append(result['fwhmH'] * 1e9)
                fv.append(result['fwhmV'] * 1e9)
                rl.append(result['nSurvived'])

            dt = time.time() - t0
            mc_h = sum(fh) / len(fh)
            mc_v = sum(fv) / len(fv)
            mc_rays = sum(rl) / len(rl)
            dh = (mc_h - cond['s4_h']) / cond['s4_h'] * 100
            dv = (mc_v - cond['s4_v']) / cond['s4_v'] * 100

            # Also print individual runs for variance
            h_std = (sum((x-mc_h)**2 for x in fh) / len(fh)) ** 0.5
            v_std = (sum((x-mc_v)**2 for x in fv) / len(fv)) ** 0.5

            print(f"{cond['name']:<16s} {mc_h:7.1f} {mc_v:7.1f} {cond['s4_h']:7.1f} {cond['s4_v']:7.1f}"
                  f" {dh:+6.1f}% {dv:+6.1f}% {mc_rays:8.0f} {dt:5.1f}s")
            print(f"{'':16s} std: H={h_std:.1f}nm V={v_std:.1f}nm  per-run: {[f'{x:.1f}' for x in fh]}")

        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
