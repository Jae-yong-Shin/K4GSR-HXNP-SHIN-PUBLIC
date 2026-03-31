"""
MC vs S4 Benchmark: NRAYS sweep to test if over-broadening depends on ray count.
Hypothesis: MC's lower throughput -> fewer surviving rays -> noisier histogram -> broader FWHM.
Test: run with 200k, 500k, 1M input rays and compare FWHM.
"""
import json, time, os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(__file__),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')
S4_DATA = os.path.join(os.path.dirname(__file__), 'paper', 'validation', 'data')

NRAYS_LIST = [100000, 200000, 500000]
N_REPEATS = 3
ENERGY = 10.0
SSA_H = 50
SSA_V = 50


def load_s4():
    path = os.path.join(S4_DATA, 's4_10keV_ssa50.json')
    if os.path.exists(path):
        with open(path) as f:
            d = json.load(f)
        return {
            'fwhm_h_nm': d.get('fine_fwhm_h_mean_m',
                               d.get('fwhm_h_m', 0)) * 1e9,
            'fwhm_v_nm': d.get('fine_fwhm_v_mean_m',
                               d.get('fwhm_v_m', 0)) * 1e9,
            'nrays': d.get('nrays_good_mean',
                           d.get('nrays_good', 0)),
        }
    return {}


def main():
    s4 = load_s4()
    s4_h = s4.get('fwhm_h_nm', 40.8)
    s4_v = s4.get('fwhm_v_nm', 45.2)
    s4_rays = s4.get('nrays', 11205)

    print(f"NRAYS Sweep Benchmark: 10keV SSA50")
    print(f"S4 reference: H={s4_h:.1f}nm, V={s4_v:.1f}nm, rays={s4_rays}")
    print(f"Repeats per condition: {N_REPEATS}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Loading bundle...")
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.\n")

        # Set state once
        page.evaluate(f"""(() => {{
            state.energy = {ENERGY};
            state.ssaH = {SSA_H};
            state.ssaV = {SSA_V};
            if (typeof updateEnergy === 'function') updateEnergy({ENERGY});
            if (typeof updateOptics === 'function') updateOptics();
        }})()""")

        # === WITH HYBRID ===
        print("=" * 90)
        print("WITH HYBRID")
        print(f"{'NRAYS':>10s} {'MC H':>8s} {'MC V':>8s} {'dH%':>7s} {'dV%':>7s}"
              f" {'rays':>8s} {'rays/NR':>8s} {'time':>6s}")
        print("-" * 90)

        hybrid_results = {}
        for nrays in NRAYS_LIST:
            fh, fv, rl = [], [], []
            t0 = time.time()
            for rep in range(N_REPEATS):
                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {nrays});
                    return {{
                        fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived
                    }};
                }})()""")
                fh.append(result['fwhmH'] * 1e9)
                fv.append(result['fwhmV'] * 1e9)
                rl.append(result['nSurvived'])

            dt = time.time() - t0
            mc_h = sum(fh) / len(fh)
            mc_v = sum(fv) / len(fv)
            mc_rays = sum(rl) / len(rl)
            dh = (mc_h - s4_h) / s4_h * 100
            dv = (mc_v - s4_v) / s4_v * 100
            hybrid_results[nrays] = {'h': mc_h, 'v': mc_v, 'rays': mc_rays}

            print(f"{nrays:10d} {mc_h:8.1f} {mc_v:8.1f} {dh:+6.1f}% {dv:+6.1f}%"
                  f" {mc_rays:8.0f} {mc_rays/nrays*100:7.2f}% {dt:5.1f}s")

        print()

        # === GEOMETRIC ONLY ===
        print("=" * 90)
        print("GEOMETRIC ONLY (hybrid disabled)")
        page.evaluate("""(() => {
            window._hybridBk1 = window._applyHybridFresnel;
            window._hybridBk2 = window._applySSAHybrid;
            window._applyHybridFresnel = function() {};
            window._applySSAHybrid = function() {};
        })()""")

        print(f"{'NRAYS':>10s} {'Geo H':>8s} {'Geo V':>8s} {'rays':>8s}")
        print("-" * 50)

        for nrays in NRAYS_LIST:
            fh, fv, rl = [], [], []
            for rep in range(N_REPEATS):
                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {nrays});
                    return {{
                        fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived
                    }};
                }})()""")
                fh.append(result['fwhmH'] * 1e9)
                fv.append(result['fwhmV'] * 1e9)
                rl.append(result['nSurvived'])

            geo_h = sum(fh) / len(fh)
            geo_v = sum(fv) / len(fv)
            geo_rays = sum(rl) / len(rl)
            print(f"{nrays:10d} {geo_h:8.1f} {geo_v:8.1f} {geo_rays:8.0f}")

        # Restore hybrid
        page.evaluate("""(() => {
            window._applyHybridFresnel = window._hybridBk1;
            window._applySSAHybrid = window._hybridBk2;
        })()""")

        print()

        # === DIFFRACTION KICK DIAGNOSTICS ===
        # Capture kick distributions at different nrays
        print("=" * 90)
        print("DIFFRACTION KICK DIAGNOSTICS (from _hybridFF1D)")

        # Instrument to capture kick FWHM
        page.evaluate("""(() => {
            window._kickDiag = {};
            var _origHybrid = window._applyHybridFresnel;

            // Patch _hybridFF1D to capture kick stats (via wrapper)
            window._applyHybridFresnel = function(rays, nR, E, td) {
                // Before calling original, patch _hybridFF1D to capture kicks
                // We do this by hooking the angV/angH arrays after they're computed
                // Actually, let's just compute kick stats from the ray changes
                var RS = 6;
                var alive = [];
                for (var i = 0; i < nR; i++) {
                    if (rays[i * RS + 5] > 0) alive.push(i);
                }
                // Save geometric positions
                var yGeo = new Float64Array(alive.length);
                var xGeo = new Float64Array(alive.length);
                for (var ai = 0; ai < alive.length; ai++) {
                    var o = alive[ai] * RS;
                    yGeo[ai] = rays[o + 1];
                    xGeo[ai] = rays[o];
                }

                // Call original
                _origHybrid(rays, nR, E, td);

                // Compute kick = new_pos - old_pos
                var kicksV = new Float64Array(alive.length);
                var kicksH = new Float64Array(alive.length);
                for (var ai = 0; ai < alive.length; ai++) {
                    var o = alive[ai] * RS;
                    kicksV[ai] = rays[o + 1] - yGeo[ai];
                    kicksH[ai] = rays[o] - xGeo[ai];
                }

                // Measure FWHM of kick distributions
                function histFwhm(vals, n) {
                    var mn = vals[0], mx = vals[0];
                    for (var i = 1; i < n; i++) {
                        if (vals[i] < mn) mn = vals[i];
                        if (vals[i] > mx) mx = vals[i];
                    }
                    var nB = 501, range = mx - mn;
                    if (range < 1e-20) return 0;
                    var dx = range / nB;
                    var hist = new Float64Array(nB);
                    for (var i = 0; i < n; i++) {
                        var b = Math.floor((vals[i] - mn) / dx);
                        if (b >= 0 && b < nB) hist[b]++;
                    }
                    var pk = 0;
                    for (var i = 0; i < nB; i++) if (hist[i] > pk) pk = hist[i];
                    if (pk <= 0) return 0;
                    var hm = pk * 0.5, x0 = -1, x1 = -1;
                    for (var i = 1; i < nB; i++) {
                        if (hist[i-1] < hm && hist[i] >= hm && x0 < 0)
                            x0 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
                        if (hist[i-1] >= hm && hist[i] < hm)
                            x1 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
                    }
                    if (x0 < 0 || x1 < 0) return 0;
                    return (x1 - x0) * dx;
                }

                window._kickDiag = {
                    nAlive: alive.length,
                    kickV_fwhm_nm: histFwhm(kicksV, alive.length) * 1e9,
                    kickH_fwhm_nm: histFwhm(kicksH, alive.length) * 1e9,
                };
            };
        })()""")

        print(f"{'NRAYS':>10s} {'nAlive':>8s} {'kickH':>10s} {'kickV':>10s}"
              f" {'Airy H':>10s} {'Airy V':>10s} {'ratioH':>8s} {'ratioV':>8s}")
        print("-" * 90)

        # Theoretical Airy FWHM at sample
        lam = 12.3984 / ENERGY * 1e-10
        airy_h = 0.886 * lam / 300e-6 * 0.10 * 1e9  # nm
        airy_v = 0.886 * lam / 900e-6 * 0.31 * 1e9   # nm

        for nrays in NRAYS_LIST:
            kick_h_list, kick_v_list, alive_list = [], [], []
            for rep in range(N_REPEATS):
                page.evaluate(f"""(() => {{
                    state.energy = {ENERGY};
                    state.ssaH = {SSA_H};
                    state.ssaV = {SSA_V};
                    if (typeof updateEnergy === 'function') updateEnergy({ENERGY});
                    if (typeof updateOptics === 'function') updateOptics();
                }})()""")

                result = page.evaluate(f"""(() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {nrays});
                    return window._kickDiag || {{}};
                }})()""")
                kick_h_list.append(result.get('kickH_fwhm_nm', 0))
                kick_v_list.append(result.get('kickV_fwhm_nm', 0))
                alive_list.append(result.get('nAlive', 0))

            avg_kh = sum(kick_h_list) / len(kick_h_list)
            avg_kv = sum(kick_v_list) / len(kick_v_list)
            avg_alive = sum(alive_list) / len(alive_list)
            rh = avg_kh / airy_h if airy_h > 0 else 0
            rv = avg_kv / airy_v if airy_v > 0 else 0

            print(f"{nrays:10d} {avg_alive:8.0f} {avg_kh:9.1f}nm {avg_kv:9.1f}nm"
                  f" {airy_h:9.1f}nm {airy_v:9.1f}nm {rh:8.3f} {rv:8.3f}")

        # Restore original
        page.evaluate("""(() => {
            if (window._hybridBk1) window._applyHybridFresnel = window._hybridBk1;
            if (window._hybridBk2) window._applySSAHybrid = window._hybridBk2;
        })()""")

        browser.close()

    print("\nDone.")


if __name__ == '__main__':
    main()
