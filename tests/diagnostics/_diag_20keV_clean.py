"""Clean test: 20keV ray survival without any instrumentation."""
import os
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
        print("Bundle loaded.\n")

        # Run each energy condition FRESH (no wrappers, no instrumentation)
        for energy in [5.0, 10.0, 20.0]:
            print(f"=== {energy} keV, SSA50 ===")
            for rep in range(3):
                result = page.evaluate(f"""(() => {{
                    state.energy = {energy};
                    state.ssaH = 50;
                    state.ssaV = 50;
                    if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({energy});
                    if (typeof updateEnergy === 'function') updateEnergy({energy});
                    if (typeof updateOptics === 'function') updateOptics();
                    
                    var mc = mcRayTrace(pos('sample') || 150.0, 200000);
                    return {{
                        fwhmH: mc.fwhmH * 1e9,
                        fwhmV: mc.fwhmV * 1e9,
                        nSurvived: mc.nSurvived,
                        nTotal: mc.nTotal
                    }};
                }})()""")
                
                print(f"  Rep {rep}: H={result['fwhmH']:.1f}nm, V={result['fwhmV']:.1f}nm, "
                      f"rays={result['nSurvived']}/{result['nTotal']}")
            print()
        
        # NOW try the same but WITHOUT autoStripeForEnergy 
        # (to see if benchmark misses this call)
        print("=== 20 keV WITHOUT autoStripeForEnergy ===")
        for rep in range(3):
            result = page.evaluate(f"""(() => {{
                state.energy = 20.0;
                state.ssaH = 50;
                state.ssaV = 50;
                // NO autoStripeForEnergy call - like the benchmark
                if (typeof updateEnergy === 'function') updateEnergy(20.0);
                if (typeof updateOptics === 'function') updateOptics();
                
                var mc = mcRayTrace(pos('sample') || 150.0, 200000);
                return {{
                    fwhmH: mc.fwhmH * 1e9,
                    fwhmV: mc.fwhmV * 1e9,
                    nSurvived: mc.nSurvived,
                    nTotal: mc.nTotal,
                    m2stripe: state.m2stripe
                }};
            }})()""")
            
            print(f"  Rep {rep}: H={result['fwhmH']:.1f}nm, V={result['fwhmV']:.1f}nm, "
                  f"rays={result['nSurvived']}/{result['nTotal']}, m2stripe={result.get('m2stripe','?')}")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
