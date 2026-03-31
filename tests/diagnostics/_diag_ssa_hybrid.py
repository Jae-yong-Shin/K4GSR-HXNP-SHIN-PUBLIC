"""Compare MC results with SSA hybrid ON vs OFF."""
import os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join('c:/Projects/K4GSR-Beamline',
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')

CONDITIONS = [
    {'name': '10keV SSA50',  'energy': 10.0, 'ssaH': 50,  'ssaV': 50},
    {'name': '5keV SSA50',   'energy': 5.0,  'ssaH': 50,  'ssaV': 50},
    {'name': '10keV SSA10',  'energy': 10.0, 'ssaH': 10,  'ssaV': 10},
    {'name': '10keV SSA200', 'energy': 10.0, 'ssaH': 200, 'ssaV': 200},
]
S4_REF = {
    '10keV SSA50':  (40.8, 45.2),
    '5keV SSA50':   (66.2, 70.8),
    '10keV SSA10':  (26.2, 35.7),
    '10keV SSA200': (50.4, 46.0),
}

NRAYS = 500000
N_REP = 5

def run_conditions(page, label):
    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"{'Cond':<16} {'MC H':>7} {'MC V':>7} {'S4 H':>7} {'S4 V':>7} {'dH%':>7} {'dV%':>7} {'rays':>6}")
    print(f"{'-'*80}")
    
    for c in CONDITIONS:
        fh, fv, rl = [], [], []
        for _ in range(N_REP):
            page.evaluate(f"""(() => {{
                state.energy = {c['energy']};
                state.ssaH = {c['ssaH']};
                state.ssaV = {c['ssaV']};
                if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({c['energy']});
                if (typeof updateEnergy === 'function') updateEnergy({c['energy']});
                if (typeof updateOptics === 'function') updateOptics();
            }})()""")
            
            r = page.evaluate(f"""(() => {{
                var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                return {{ h: mc.fwhmH*1e9, v: mc.fwhmV*1e9, n: mc.nSurvived }};
            }})()""")
            fh.append(r['h']); fv.append(r['v']); rl.append(r['n'])
        
        mh = sum(fh)/len(fh)
        mv = sum(fv)/len(fv)
        mr = sum(rl)/len(rl)
        s4h, s4v = S4_REF.get(c['name'], (0,0))
        dh = (mh-s4h)/s4h*100 if s4h else 0
        dv = (mv-s4v)/s4v*100 if s4v else 0
        print(f"{c['name']:<16} {mh:7.1f} {mv:7.1f} {s4h:7.1f} {s4v:7.1f} {dh:+6.1f}% {dv:+6.1f}% {mr:6.0f}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.")
        
        # 1. SSA hybrid ON (current code: _applySSAHybrid is called)
        run_conditions(page, "SSA HYBRID ON (full hybrid)")
        
        # 2. SSA hybrid OFF (disable _applySSAHybrid)
        page.evaluate("""(() => {
            window._ssaHybridBk = window._applySSAHybrid;
            window._applySSAHybrid = undefined;
        })()""")
        run_conditions(page, "SSA HYBRID OFF (KB hybrid only, SSA falls back to sincSqRand)")
        
        # 3. Both SSA and KB hybrid OFF (geometric only)
        page.evaluate("""(() => {
            window._applySSAHybrid = undefined;
            window._kbHybridBk = window._applyHybridFresnel;
            window._applyHybridFresnel = function() {};
        })()""")
        run_conditions(page, "ALL HYBRID OFF (geometric only)")
        
        # Restore
        page.evaluate("""(() => {
            window._applySSAHybrid = window._ssaHybridBk;
            window._applyHybridFresnel = window._kbHybridBk;
        })()""")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
