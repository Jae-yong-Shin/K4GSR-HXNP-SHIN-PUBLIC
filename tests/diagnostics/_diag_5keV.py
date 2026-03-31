import json, os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join('c:/Projects/K4GSR-Beamline',
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)

        # Test 5keV with more repeats to get stable stats
        NRAYS = 500000
        N_REPEATS = 5
        
        for energy in [5.0, 10.0]:
            print(f"\n=== {energy} keV, SSA50, NRAYS={NRAYS}, {N_REPEATS} repeats ===")
            fh_list, fv_list, rays_list = [], [], []
            
            for rep in range(N_REPEATS):
                page.evaluate(f"""(() => {{
                    state.energy = {energy};
                    state.ssaH = 50;
                    state.ssaV = 50;
                    if (typeof updateEnergy === 'function') updateEnergy({energy});
                    if (typeof updateOptics === 'function') updateOptics();
                }})()""")
                
                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{
                        fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived, nTotal: mc.nTotal
                    }};
                }})()""")
                
                fh_list.append(result['fwhmH'] * 1e9)
                fv_list.append(result['fwhmV'] * 1e9)
                rays_list.append(result['nSurvived'])
            
            avg_h = sum(fh_list) / len(fh_list)
            avg_v = sum(fv_list) / len(fv_list)
            avg_rays = sum(rays_list) / len(rays_list)
            std_h = (sum((x - avg_h)**2 for x in fh_list) / len(fh_list))**0.5
            std_v = (sum((x - avg_v)**2 for x in fv_list) / len(fv_list))**0.5
            
            print(f"  H: {avg_h:.1f} +/- {std_h:.1f} nm")
            print(f"  V: {avg_v:.1f} +/- {std_v:.1f} nm")
            print(f"  Rays: {avg_rays:.0f}")
            print(f"  Individual H: {[f'{x:.1f}' for x in fh_list]}")
            print(f"  Individual V: {[f'{x:.1f}' for x in fv_list]}")
        
        # Also test: 5keV with SSA hybrid disabled to see contribution
        print(f"\n=== 5keV SSA50, SSA hybrid DISABLED (geometric SSA) ===")
        page.evaluate("""(() => {
            window._ssaHybridBk = window._applySSAHybrid;
            window._applySSAHybrid = undefined;
        })()""")
        
        fh_list, fv_list = [], []
        for rep in range(N_REPEATS):
            page.evaluate("""(() => {
                state.energy = 5.0;
                state.ssaH = 50;
                state.ssaV = 50;
                if (typeof updateEnergy === 'function') updateEnergy(5.0);
                if (typeof updateOptics === 'function') updateOptics();
            })()""")
            
            result = page.evaluate(f"""(() => {{
                var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                return {{ fwhmH: mc.fwhmH, fwhmV: mc.fwhmV, nSurvived: mc.nSurvived }};
            }})()""")
            fh_list.append(result['fwhmH'] * 1e9)
            fv_list.append(result['fwhmV'] * 1e9)
        
        avg_h = sum(fh_list) / len(fh_list)
        avg_v = sum(fv_list) / len(fv_list)
        print(f"  H: {avg_h:.1f} nm (S4: 66.2)")
        print(f"  V: {avg_v:.1f} nm (S4: 70.8)")
        
        # Restore
        page.evaluate("window._applySSAHybrid = window._ssaHybridBk;")
        
        # Also test: 5keV with KB hybrid disabled (SSA hybrid only)
        print(f"\n=== 5keV SSA50, KB hybrid DISABLED (SSA hybrid only) ===")
        page.evaluate("""(() => {
            window._kbHybridBk = window._applyHybridFresnel;
            window._applyHybridFresnel = function() {};
        })()""")
        
        fh_list, fv_list = [], []
        for rep in range(N_REPEATS):
            page.evaluate("""(() => {
                state.energy = 5.0;
                state.ssaH = 50;
                state.ssaV = 50;
                if (typeof updateEnergy === 'function') updateEnergy(5.0);
                if (typeof updateOptics === 'function') updateOptics();
            })()""")
            
            result = page.evaluate(f"""(() => {{
                var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                return {{ fwhmH: mc.fwhmH, fwhmV: mc.fwhmV, nSurvived: mc.nSurvived }};
            }})()""")
            fh_list.append(result['fwhmH'] * 1e9)
            fv_list.append(result['fwhmV'] * 1e9)
        
        avg_h = sum(fh_list) / len(fh_list)
        avg_v = sum(fv_list) / len(fv_list)
        print(f"  H: {avg_h:.1f} nm (S4: 66.2)")
        print(f"  V: {avg_v:.1f} nm (S4: 70.8)")
        
        page.evaluate("window._applyHybridFresnel = window._kbHybridBk;")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
