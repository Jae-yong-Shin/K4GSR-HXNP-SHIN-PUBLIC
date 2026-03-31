"""Check state.gap, state.harmonic, and undulator envelope effect."""
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

        # 1. Check default state
        defaults = page.evaluate("""(() => {
            return {
                gap: state.gap,
                harmonic: state.harmonic,
                energy: state.energy,
                gapType: typeof state.gap,
                harmonicType: typeof state.harmonic
            };
        })()""")
        print("=== Default state ===")
        print(f"  gap = {defaults['gap']} (type: {defaults['gapType']})")
        print(f"  harmonic = {defaults['harmonic']} (type: {defaults['harmonicType']})")
        print(f"  energy = {defaults['energy']}")
        
        # 2. Check E1 from default gap
        und = page.evaluate("""(() => {
            var gap = state.gap;
            var B0 = (typeof calcB0 === 'function') ? calcB0(gap) : NaN;
            var K = (typeof calcK === 'function') ? calcK(B0) : NaN;
            var E1 = (typeof calcE1 === 'function') ? calcE1(K) : NaN;
            var n = state.harmonic || 1;
            return { gap: gap, B0: B0, K: K, E1: E1, n: n, En: n * E1 };
        })()""")
        print(f"\n=== Undulator calc from default gap ===")
        print(f"  gap={und['gap']}, B0={und['B0']}, K={und['K']}, E1={und['E1']}keV")
        print(f"  harmonic n={und['n']}, En={und['En']}keV")
        
        # 3. Check what selectBest gives for different energies
        for energy in [5.0, 10.0, 20.0]:
            best = page.evaluate(f"""(() => {{
                var b = (typeof selectBest === 'function') ? selectBest({energy}) : null;
                return b ? {{ n: b.n, gap: b.gap, E_peak: b.E || 0 }} : null;
            }})()""")
            print(f"\n  selectBest({energy}keV): {best}")
        
        # 4. Test undulator envelope for ray at E=20keV with default gap
        env_test = page.evaluate("""(() => {
            var E = 20.0;
            var gap = state.gap;
            var B0 = (typeof calcB0 === 'function') ? calcB0(gap) : NaN;
            var K_ea = (typeof calcK === 'function') ? calcK(B0) : NaN;
            var E1_ea = (typeof calcE1 === 'function') ? calcE1(K_ea) : NaN;
            var n_ea = state.harmonic || 1;
            var En_ea = n_ea * E1_ea;
            var Kfac = 1 + K_ea * K_ea / 2;
            var N_PERIODS = (typeof N_PERIODS !== 'undefined') ? N_PERIODS : 70;
            
            // On-axis ray (theta=0)
            var Eres = En_ea;
            var xa = Math.PI * N_PERIODS * (E / Eres - 1);
            var weight = (Math.abs(xa) < 1e-10) ? 1.0 : Math.pow(Math.sin(xa) / xa, 2);
            
            return {
                gap: gap, B0: B0, K: K_ea, E1: E1_ea, n: n_ea, En: En_ea,
                xa: xa, weight: weight,
                xa_isNaN: isNaN(xa), weight_isNaN: isNaN(weight),
                N_PERIODS: N_PERIODS
            };
        })()""")
        print(f"\n=== Und envelope at E=20keV, default gap ===")
        print(f"  E1={env_test['E1']}, En={env_test['En']}, N={env_test['N_PERIODS']}")
        print(f"  xa={env_test['xa']}, weight={env_test['weight']}")
        print(f"  xa isNaN: {env_test['xa_isNaN']}, weight isNaN: {env_test['weight_isNaN']}")
        
        # 5. Compare: properly set gap for 20keV
        page.evaluate("""(() => {
            if (typeof setTargetEnergy === 'function') setTargetEnergy(20.0);
        })()""")
        
        proper = page.evaluate("""(() => {
            var E = 20.0;
            var gap = state.gap;
            var B0 = calcB0(gap);
            var K_ea = calcK(B0);
            var E1_ea = calcE1(K_ea);
            var n_ea = state.harmonic || 1;
            var En_ea = n_ea * E1_ea;
            var N_PERIODS = (typeof N_PERIODS !== 'undefined') ? N_PERIODS : 70;
            var xa = Math.PI * N_PERIODS * (E / En_ea - 1);
            var weight = (Math.abs(xa) < 1e-10) ? 1.0 : Math.pow(Math.sin(xa) / xa, 2);
            
            return {
                gap: gap, harmonic: n_ea, E1: E1_ea, En: En_ea,
                xa: xa, weight: weight
            };
        })()""")
        print(f"\n=== After setTargetEnergy(20.0) ===")
        print(f"  gap={proper['gap']:.1f}mm, harmonic={proper['harmonic']}")
        print(f"  E1={proper['E1']:.3f}keV, En={proper['En']:.3f}keV")
        print(f"  xa={proper['xa']:.4f}, weight={proper['weight']:.6f}")
        
        # 6. Run MC with proper gap at 20keV
        result_proper = page.evaluate("""(() => {
            var mc = mcRayTrace(pos('sample') || 150.0, 200000);
            return { fwhmH: mc.fwhmH * 1e9, fwhmV: mc.fwhmV * 1e9, 
                     nSurvived: mc.nSurvived, nTotal: mc.nTotal };
        })()""")
        print(f"\n  MC with proper gap: H={result_proper['fwhmH']:.1f}nm, V={result_proper['fwhmV']:.1f}nm, "
              f"rays={result_proper['nSurvived']}/{result_proper['nTotal']}")
        
        # 7. Also check: what does NaN weight do to ray survival?
        nan_test = page.evaluate("""(() => {
            var nanVal = NaN;
            return {
                nan_leq_0: nanVal <= 0,
                nan_gt_0: nanVal > 0,
                nan_times_1: 1.0 * nanVal,
                nan_times_1_isNaN: isNaN(1.0 * nanVal)
            };
        })()""")
        print(f"\n=== NaN behavior ===")
        print(f"  NaN <= 0: {nan_test['nan_leq_0']}")
        print(f"  NaN > 0: {nan_test['nan_gt_0']}")
        print(f"  1.0 * NaN = {nan_test['nan_times_1']} (isNaN: {nan_test['nan_times_1_isNaN']})")
        
        browser.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
