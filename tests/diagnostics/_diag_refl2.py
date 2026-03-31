"""Diagnose MC reflectivity and throughput at each energy."""
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

        # Get reflectivity at each mirror for different energies
        for energy in [5.0, 10.0, 15.0, 20.0, 25.0]:
            result = page.evaluate(f"""(() => {{
                var E = {energy};
                if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy(E);
                
                var theta = 3.0;  // mrad for mirrorR
                var rough = 2.0;  // Angstrom RMS roughness
                
                var m1mat = getStripeMaterial('m1');
                var m2mat = getStripeMaterial('m2');
                var kbvmat = getStripeMaterial('kbv');
                var kbhmat = getStripeMaterial('kbh');
                
                var R_m1 = mirrorR(E, theta, m1mat.mat, rough);
                var R_m2 = mirrorR(E, theta, m2mat.mat, rough);
                var R_kbv = mirrorR(E, theta, kbvmat.mat, rough);
                var R_kbh = mirrorR(E, theta, kbhmat.mat, rough);
                var R_4bounce = R_m1 * R_m2 * R_kbv * R_kbh;
                
                return {{
                    m1: {{ name: m1mat.name, R: R_m1 }},
                    m2: {{ name: m2mat.name, R: R_m2 }},
                    kbv: {{ name: kbvmat.name, R: R_kbv }},
                    kbh: {{ name: kbhmat.name, R: R_kbh }},
                    R_4bounce: R_4bounce
                }};
            }})()""")
            
            print(f"E={energy:5.1f}keV  "
                  f"M1({result['m1']['name']})={result['m1']['R']:.4f}  "
                  f"M2({result['m2']['name']})={result['m2']['R']:.4f}  "
                  f"KBV({result['kbv']['name']})={result['kbv']['R']:.4f}  "
                  f"KBH({result['kbh']['name']})={result['kbh']['R']:.4f}  "
                  f"4-bounce={result['R_4bounce']:.6f}")
        
        # Now check: what if M2 uses Pt at 20 keV instead of Rh?
        print()
        print("=== What if M2 = Pt at 20 keV? ===")
        result_pt = page.evaluate("""(() => {
            var E = 20.0;
            var theta = 3.0;
            var rough = 2.0;
            var MAT_PT = {Z:78, A:195.1, rho:21.45e6};
            var MAT_RH = {Z:45, A:102.9, rho:12.41e6};
            
            var R_m1_pt = mirrorR(E, theta, MAT_PT, rough);
            var R_m2_rh = mirrorR(E, theta, MAT_RH, rough);
            var R_m2_pt = mirrorR(E, theta, MAT_PT, rough);
            var R_kbv_pt = mirrorR(E, theta, MAT_PT, rough);
            var R_kbh_pt = mirrorR(E, theta, MAT_PT, rough);
            
            return {
                R_m2_rh: R_m2_rh, R_m2_pt: R_m2_pt,
                R4_with_rh: R_m1_pt * R_m2_rh * R_kbv_pt * R_kbh_pt,
                R4_with_pt: R_m1_pt * R_m2_pt * R_kbv_pt * R_kbh_pt
            };
        })()""")
        print(f"  M2=Rh: R={result_pt['R_m2_rh']:.6f}, 4-bounce={result_pt['R4_with_rh']:.6f}")
        print(f"  M2=Pt: R={result_pt['R_m2_pt']:.6f}, 4-bounce={result_pt['R4_with_pt']:.6f}")
        
        # Also compute critical angle for each material at 20 keV
        print()
        print("=== Critical angles at 20 keV ===")
        result_crit = page.evaluate("""(() => {
            var E = 20.0;
            var MAT_PT = {Z:78, A:195.1, rho:21.45e6};
            var MAT_RH = {Z:45, A:102.9, rho:12.41e6};
            var oc_pt = optConst(E, MAT_PT);
            var oc_rh = optConst(E, MAT_RH);
            return {
                pt_delta: oc_pt.delta, pt_beta: oc_pt.beta,
                pt_thetaC_mrad: Math.sqrt(2 * oc_pt.delta) * 1000,
                rh_delta: oc_rh.delta, rh_beta: oc_rh.beta,
                rh_thetaC_mrad: Math.sqrt(2 * oc_rh.delta) * 1000
            };
        })()""")
        print(f"  Pt: thetaC = {result_crit['pt_thetaC_mrad']:.3f} mrad (operating: 3.0 mrad)")
        print(f"  Rh: thetaC = {result_crit['rh_thetaC_mrad']:.3f} mrad (operating: 3.0 mrad)")
        
        # MC run: per-element survival diagnostic
        print()
        print("=== MC per-element ray count at 20 keV (200k rays) ===")
        surv = page.evaluate("""(() => {
            state.energy = 20.0;
            state.ssaH = 50;
            state.ssaV = 50;
            if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy(20.0);
            if (typeof updateEnergy === 'function') updateEnergy(20.0);
            if (typeof updateOptics === 'function') updateOptics();
            
            // Instrument applyMirrorMC to count per-element
            var _origMirrorMC = window.applyMirrorMC;
            var mirrorCounts = {};
            window.applyMirrorMC = function(rays, nR, devId, E) {
                var RS = 6;
                var before = 0;
                for (var i = 0; i < nR; i++) if (rays[i*RS+5] > 0) before++;
                _origMirrorMC(rays, nR, devId, E);
                var after = 0;
                for (var i = 0; i < nR; i++) if (rays[i*RS+5] > 0) after++;
                mirrorCounts[devId] = {before: before, after: after};
                return;
            };
            
            var mc = mcRayTrace(pos('sample') || 150.0, 200000);
            
            // Restore
            window.applyMirrorMC = _origMirrorMC;
            
            return {
                mirrors: mirrorCounts,
                final: mc.nSurvived,
                total: mc.nTotal
            };
        })()""")
        
        print(f"  Total input: {surv.get('total', 'N/A')}")
        for mid in ['m1', 'm2', 'kbv', 'kbh']:
            d = surv.get('mirrors', {}).get(mid, {})
            if d:
                print(f"  {mid}: {d.get('before',0)} -> {d.get('after',0)} "
                      f"(survival: {d.get('after',0)/max(d.get('before',1),1)*100:.1f}%)")
        print(f"  Final survived: {surv.get('final', 'N/A')}")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
