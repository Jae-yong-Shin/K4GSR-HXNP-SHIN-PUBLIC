"""Diagnose MC reflectivity at each optical element for different energies."""
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

        for energy in [5.0, 10.0, 20.0]:
            print(f"\n{'='*80}")
            print(f"Energy = {energy} keV, SSA 50x50 um")
            print(f"{'='*80}")
            
            # Check auto stripe selection
            m2stripe = page.evaluate(f"""(() => {{
                state.energy = {energy};
                state.ssaH = 50;
                state.ssaV = 50;
                if (typeof updateEnergy === 'function') updateEnergy({energy});
                if (typeof updateOptics === 'function') updateOptics();
                if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({energy});
                return {{
                    m1stripe: state.m1stripe,
                    m2stripe: state.m2stripe
                }};
            }})()""")
            print(f"  M1 stripe: {m2stripe['m1stripe']}")
            print(f"  M2 stripe: {m2stripe['m2stripe']}")
            
            # Get reflectivity values at this energy
            refl = page.evaluate(f"""(() => {{
                var E = {energy};
                var theta = 3.0e-3;  // 3 mrad grazing angle
                var results = {{}};
                
                // Check what material is used for each mirror
                var mats = {{}};
                ['m1', 'm2', 'kbv', 'kbh'].forEach(function(mid) {{
                    var s = getStripeMaterial(mid);
                    mats[mid] = s ? s.name || s.mat || 'unknown' : 'unknown';
                }});
                results.materials = mats;
                
                // Compute reflectivity if optConst is available
                if (typeof optConst === 'function') {{
                    ['m1', 'm2', 'kbv', 'kbh'].forEach(function(mid) {{
                        var s = getStripeMaterial(mid);
                        if (s && s.mat !== undefined) {{
                            var oc = optConst(s.mat, E);
                            // Fresnel reflectivity
                            var delta = oc.delta || 0;
                            var beta = oc.beta || 0;
                            // Critical angle
                            var thetaC = Math.sqrt(2 * delta);
                            // Simplified reflectivity
                            var ratio = theta / thetaC;
                            var R;
                            if (ratio < 1) {{
                                R = 1.0;  // below critical angle - total external reflection
                            }} else {{
                                // Above critical angle - approximate
                                R = Math.pow(thetaC / (2 * theta), 4);
                            }}
                            results[mid] = {{
                                delta: delta, beta: beta, thetaC_mrad: thetaC * 1000,
                                R_approx: R
                            }};
                        }}
                    }});
                }}
                
                // Also check actual reflectivity function if available
                if (typeof mirrorReflectivity === 'function') {{
                    ['m1', 'm2', 'kbv', 'kbh'].forEach(function(mid) {{
                        var R = mirrorReflectivity(mid, E, theta);
                        results[mid + '_actual_R'] = R;
                    }});
                }}
                
                return results;
            }})()""")
            
            print(f"\n  Materials: {refl.get('materials', {})}")
            for mid in ['m1', 'm2', 'kbv', 'kbh']:
                data = refl.get(mid, {})
                actual_R = refl.get(mid + '_actual_R', 'N/A')
                if data:
                    print(f"  {mid}: delta={data.get('delta',0):.3e}, beta={data.get('beta',0):.3e}, "
                          f"thetaC={data.get('thetaC_mrad',0):.3f}mrad, "
                          f"R_approx={data.get('R_approx',0):.6f}, "
                          f"actual_R={actual_R}")
                else:
                    print(f"  {mid}: actual_R={actual_R}")
            
            # Run MC with instrumented per-element ray count
            result = page.evaluate(f"""(() => {{
                var nR = 200000;
                var RS = 6;
                var rays = new Float64Array(nR * RS);
                
                // Generate source
                var src = typeof generateSource === 'function' ? 
                    generateSource(nR, {energy}) : null;
                if (!src) return {{'error': 'generateSource not found'}};
                
                for (var i = 0; i < nR * RS; i++) rays[i] = src.rays[i];
                var nAlive0 = 0;
                for (var i = 0; i < nR; i++) if (rays[i*RS+5] > 0) nAlive0++;
                
                // Process each element and count survivors
                var counts = {{'source': nAlive0}};
                var elements = beamlineElements ? beamlineElements() : [];
                
                for (var ei = 0; ei < elements.length; ei++) {{
                    var c = elements[ei];
                    // Simple count after MC processes
                    // We can't easily separate, so just run full MC and count
                }}
                
                // Just run full MC and return final count
                var mc = mcRayTrace(pos('sample') || 150.0, nR);
                counts.final = mc.nSurvived;
                counts.total = mc.nTotal;
                
                return counts;
            }})()""")
            
            print(f"\n  Source rays: {result.get('source', 'N/A')}")
            print(f"  Survived: {result.get('final', 'N/A')} / {result.get('total', 'N/A')}")
            print(f"  Throughput: {result.get('final',0)/result.get('total',1)*100:.3f}%")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
