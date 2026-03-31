import os, json
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        
        # Set 10keV SSA50
        page.evaluate("""(() => {
            state.energy = 10.0;
            state.ssaH = 50;
            state.ssaV = 50;
            if (typeof updateEnergy === 'function') updateEnergy(10.0);
            if (typeof updateOptics === 'function') updateOptics();
        })()""")
        
        # Instrument _applyHybridFresnel to capture D values
        page.evaluate("""(() => {
            var _origHybrid = window._applyHybridFresnel;
            window._applyHybridFresnel = function(rays, nR, E, td) {
                // Before calling original, we need to capture the D values
                // The original function modifies rays in place
                // Let's compute what it computes internally
                var RS = 6;
                var HC = 12.3984;
                var lam = HC / E * 1e-10;
                
                var kbp = window.KB_PARAMS || {};
                var kbvP = kbp.kbv || { len: 0.300, wid: 0.030 };
                var kbhP = kbp.kbh || { len: 0.100, wid: 0.030 };
                var posKBV = pos('kbv'), posKBH = pos('kbh'), posSample = pos('sample');
                var qV = posSample - posKBV;
                var qH = posSample - posKBH;
                var sinTg = Math.sin(0.003);
                var apV = kbvP.len * sinTg;
                var apH = kbhP.len * sinTg;
                
                // Count alive rays
                var alive = [];
                for (var i = 0; i < nR; i++) {
                    if (rays[i * RS + 5] > 0) alive.push(i);
                }
                
                // Back-propagate
                var yMin = Infinity, yMax = -Infinity;
                var xMin = Infinity, xMax = -Infinity;
                for (var ai = 0; ai < alive.length; ai++) {
                    var o = alive[ai] * RS;
                    var ivz = 1 / rays[o + 4];
                    var yAtKBV = rays[o + 1] - rays[o + 3] * ivz * qV;
                    var xAtKBH = rays[o]     - rays[o + 2] * ivz * qH;
                    if (yAtKBV < yMin) yMin = yAtKBV;
                    if (yAtKBV > yMax) yMax = yAtKBV;
                    if (xAtKBH < xMin) xMin = xAtKBH;
                    if (xAtKBH > xMax) xMax = xAtKBH;
                }
                
                // Also check _kbFootprintArr
                var fpV = window._kbFootprintArr && window._kbFootprintArr['kbv'];
                var fpH = window._kbFootprintArr && window._kbFootprintArr['kbh'];
                var fpYmin = Infinity, fpYmax = -Infinity;
                var fpXmin = Infinity, fpXmax = -Infinity;
                if (fpV && fpH) {
                    for (var ai = 0; ai < alive.length; ai++) {
                        var ri = alive[ai];
                        if (fpV[ri] !== 0) {
                            if (fpV[ri] < fpYmin) fpYmin = fpV[ri];
                            if (fpV[ri] > fpYmax) fpYmax = fpV[ri];
                        }
                        if (fpH[ri] !== 0) {
                            if (fpH[ri] < fpXmin) fpXmin = fpH[ri];
                            if (fpH[ri] > fpXmax) fpXmax = fpH[ri];
                        }
                    }
                }
                
                window._hybridDiag = {
                    nAlive: alive.length,
                    yMin_um: yMin * 1e6,
                    yMax_um: yMax * 1e6,
                    DV_um: (yMax - yMin) * 1e6,
                    xMin_um: xMin * 1e6,
                    xMax_um: xMax * 1e6,
                    DH_um: (xMax - xMin) * 1e6,
                    apV_um: apV * 1e6,
                    apH_um: apH * 1e6,
                    fpV_min_um: fpYmin * 1e6,
                    fpV_max_um: fpYmax * 1e6,
                    fpV_D_um: (fpYmax - fpYmin) * 1e6,
                    fpH_min_um: fpXmin * 1e6,
                    fpH_max_um: fpXmax * 1e6,
                    fpH_D_um: (fpXmax - fpXmin) * 1e6,
                };
                
                // Call original
                _origHybrid(rays, nR, E, td);
            };
        })()""")
        
        # Run MC
        result = page.evaluate("""(() => {
            var mc = mcRayTrace(pos('sample') || 150.0, 200000);
            return {
                fwhmH: mc.fwhmH * 1e9,
                fwhmV: mc.fwhmV * 1e9,
                nSurvived: mc.nSurvived,
                diag: window._hybridDiag || {}
            };
        })()""")
        
        print("=== MC D-value Diagnostic (10keV SSA50) ===")
        print(f"MC FWHM: H={result['fwhmH']:.1f}nm, V={result['fwhmV']:.1f}nm")
        print(f"Survived: {result['nSurvived']} rays")
        print()
        
        diag = result.get('diag', {})
        print("Back-propagated positions (yAtKBV, xAtKBH):")
        print(f"  yAtKBV: min={diag.get('yMin_um', 0):.1f}um, max={diag.get('yMax_um', 0):.1f}um, DV={diag.get('DV_um', 0):.1f}um")
        print(f"  xAtKBH: min={diag.get('xMin_um', 0):.1f}um, max={diag.get('xMax_um', 0):.1f}um, DH={diag.get('DH_um', 0):.1f}um")
        print()
        print("Physical projected apertures:")
        print(f"  apV = {diag.get('apV_um', 0):.1f}um (KB-V: 300mm * sin(3mrad))")
        print(f"  apH = {diag.get('apH_um', 0):.1f}um (KB-H: 100mm * sin(3mrad))")
        print()
        print("Stored footprint (_kbFootprintArr, pre z-offset correction):")
        print(f"  fpV: min={diag.get('fpV_min_um', 0):.1f}um, max={diag.get('fpV_max_um', 0):.1f}um, D={diag.get('fpV_D_um', 0):.1f}um")
        print(f"  fpH: min={diag.get('fpH_min_um', 0):.1f}um, max={diag.get('fpH_max_um', 0):.1f}um, D={diag.get('fpH_D_um', 0):.1f}um")
        print()
        print("Comparison with S4:")
        print(f"  S4 KB-V D = 1061.8 um, MC DV = {diag.get('DV_um', 0):.1f}um, ratio = {diag.get('DV_um', 0)/1061.8:.3f}")
        print(f"  S4 KB-H D = 1695.5 um, MC DH = {diag.get('DH_um', 0):.1f}um, ratio = {diag.get('DH_um', 0)/1695.5:.3f}")
        
        browser.close()

if __name__ == '__main__':
    main()
