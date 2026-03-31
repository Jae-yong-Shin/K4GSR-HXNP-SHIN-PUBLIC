"""
Comprehensive MC vs S4 Benchmark:
  Test 1: MC monochromatic (sourceBW=0) vs S4
  Test 2: MC polychromatic (sourceBW=default) vs S4
  Test 3: SSA-to-Sample isolation (ideal Gaussian at SSA -> KB -> Sample)
"""
import json, time, os, statistics
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')
S4_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'paper', 'validation', 'data')

CONDITIONS = [
    {'name': '10keV SSA50', 'energy': 10.0, 'ssaH': 50, 'ssaV': 50},
    {'name': '20keV SSA50', 'energy': 20.0, 'ssaH': 50, 'ssaV': 50},
]

NRAYS = 500000
N_REPEATS = 5


def load_s4():
    s4 = {}
    for name, fname in [('10keV SSA50', 's4_10keV_ssa50.json'),
                         ('20keV SSA50', 's4_20keV_ssa50.json')]:
        path = os.path.join(S4_DATA, fname)
        if os.path.exists(path):
            d = json.load(open(path))
            s4[name] = {
                'fwhm_h_nm': d.get('fine_fwhm_h_mean_m',
                                   d.get('fwhm_h_m', 0)) * 1e9,
                'fwhm_v_nm': d.get('fine_fwhm_v_mean_m',
                                   d.get('fwhm_v_m', 0)) * 1e9,
                'nrays': d.get('nrays_good_mean',
                               d.get('nrays_good', 0)),
            }
    return s4


def run_mc(page, cond, src_bw, n_repeats=N_REPEATS):
    """Run MC and return mean/std FWHM."""
    fh, fv, rays_l, nb_first = [], [], [], None
    for rep in range(n_repeats):
        page.evaluate(f"""(() => {{
            state.sourceBW_eV = {src_bw};
            state.ssaH = {cond['ssaH']}; state.ssaV = {cond['ssaV']};
            state.energy = {cond['energy']};
            var best = selectBest({cond['energy']});
            if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
            autoStripeForEnergy({cond['energy']});
            if (typeof updateOptics === 'function') updateOptics();
            _mcSampleCache = null;
        }})()""")
        t0 = time.time()
        result = page.evaluate(f"""(() => {{
            var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
            return {{
                fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                nSurvived: mc.nSurvived, nTotal: mc.nTotal,
                nBeams: mc.nBeams || null
            }};
        }})()""")
        dt = time.time() - t0
        fh.append(result['fwhmH'] * 1e9)
        fv.append(result['fwhmV'] * 1e9)
        rays_l.append(result['nSurvived'])
        nb_str = ''
        if result.get('nBeams') and rep == 0:
            nb = result['nBeams']
            nb_first = nb
            nb_str = (f"  [foc={nb.get('focused',0)} dir={nb.get('direct',0)}"
                      f" vO={nb.get('vOnly',0)} hO={nb.get('hOnly',0)}]")
        print(f"  rep{rep+1}: H={fh[-1]:.1f} V={fv[-1]:.1f}"
              f" rays={rays_l[-1]:,} ({dt:.1f}s){nb_str}")

    return {
        'mc_h': statistics.mean(fh),
        'mc_v': statistics.mean(fv),
        'mc_h_std': statistics.stdev(fh) if len(fh) > 1 else 0,
        'mc_v_std': statistics.stdev(fv) if len(fv) > 1 else 0,
        'mc_rays': statistics.mean(rays_l),
        'thrput': statistics.mean(rays_l) / NRAYS * 100,
        'nBeams': nb_first,
    }


# SSA isolation: generate rays at SSA, trace through KB only
SSA_ISOLATION_JS = """(E_keV, ssaH, ssaV, nR) => {
    var E = E_keV;
    var ps = photonSrc(E);
    // M1 sagittal V-focus (DM=M1_Q/M1_P), M2 tangential H-focus (DM=M2_Q/M2_P)
    var sigH_ssa = ps.Sx * M2_DM;
    var sigV_ssa = ps.Sy * M1_DM;
    var effH = Math.min(sigH_ssa, ssaH * 0.5e-6);
    var effV = Math.min(sigV_ssa, ssaV * 0.5e-6);
    var divH = ps.Sxp / M2_DM;
    var divV = ps.Syp / M1_DM;

    // Detect RS from existing code
    var testMc = mcRayTrace(pos('sample'), 100);
    var RS = 8;  // current engine uses RS=8

    var ssaPos = pos('ssa');
    var rays = new Float64Array(nR * RS);
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        rays[o]   = gaussRand() * effH;
        rays[o+1] = gaussRand() * effV;
        rays[o+2] = gaussRand() * divH;
        rays[o+3] = gaussRand() * divV;
        rays[o+4] = 1.0;
        rays[o+5] = 1.0;
        if (RS >= 7) rays[o+6] = E * 1000;
        if (RS >= 8) rays[o+7] = 0;
    }

    // Propagate to KBV
    var kbvPos = pos('kbv');
    var dz1 = kbvPos - ssaPos;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        rays[o]   += rays[o+2] * dz1;
        rays[o+1] += rays[o+3] * dz1;
    }
    applyKBMC(rays, nR, 'kbv', E);
    if (typeof _applyHybridFresnel === 'function')
        _applyHybridFresnel(rays, nR, 'kbv', E);

    // Propagate to KBH
    var kbhPos = pos('kbh');
    var dz2 = kbhPos - kbvPos;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        rays[o]   += rays[o+2] * dz2;
        rays[o+1] += rays[o+3] * dz2;
    }
    applyKBMC(rays, nR, 'kbh', E);
    if (typeof _applyHybridFresnel === 'function')
        _applyHybridFresnel(rays, nR, 'kbh', E);

    // Propagate to sample
    var samplePos = pos('sample');
    var dz3 = samplePos - kbhPos;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        rays[o]   += rays[o+2] * dz3;
        rays[o+1] += rays[o+3] * dz3;
    }

    // Collect focused rays (tag=3)
    var xs = [], ys = [];
    var tagCounts = [0, 0, 0, 0];
    var totalAlive = 0;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        totalAlive++;
        var tag = (RS >= 8) ? (rays[o+7] | 0) : 3;
        if (tag < 4) tagCounts[tag]++;
        if (tag === 3) {
            xs.push(rays[o]);
            ys.push(rays[o+1]);
        }
    }

    // FWHM from histogram
    function fwhm1d(arr) {
        if (arr.length < 10) return 0;
        arr.sort(function(a, b) { return a - b; });
        var n = arr.length;
        var nbins = 201;
        var lo = arr[Math.floor(n * 0.005)];
        var hi = arr[Math.floor(n * 0.995)];
        var bw = (hi - lo) / nbins;
        if (bw <= 0) return 0;
        var hist = new Array(nbins).fill(0);
        for (var i = 0; i < n; i++) {
            var bi = Math.floor((arr[i] - lo) / bw);
            if (bi >= 0 && bi < nbins) hist[bi]++;
        }
        var peak = 0;
        for (var i = 0; i < nbins; i++) if (hist[i] > peak) peak = hist[i];
        var hm = peak * 0.5;
        var left = 0, right = nbins - 1;
        for (var i = 0; i < nbins; i++) if (hist[i] >= hm) { left = i; break; }
        for (var i = nbins - 1; i >= 0; i--) if (hist[i] >= hm) { right = i; break; }
        return (right - left) * bw;
    }

    return {
        fwhmH_nm: fwhm1d(xs) * 1e9,
        fwhmV_nm: fwhm1d(ys) * 1e9,
        nFocused: tagCounts[3],
        nDirect: tagCounts[0],
        nVonly: tagCounts[1],
        nHonly: tagCounts[2],
        totalAlive: totalAlive,
        effH_um: effH * 1e6,
        effV_um: effV * 1e6,
        sigH_ssa_um: sigH_ssa * 1e6,
        sigV_ssa_um: sigV_ssa * 1e6,
        divH_urad: divH * 1e6,
        divV_urad: divV * 1e6
    };
}"""


def main():
    s4 = load_s4()
    print("S4 reference:")
    for k, v in s4.items():
        print(f"  {k}: H={v['fwhm_h_nm']:.1f}nm V={v['fwhm_v_nm']:.1f}nm"
              f" rays={v['nrays']:.0f}")
    print()

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    all_results = {'timestamp': ts, 'nrays': NRAYS, 'n_repeats': N_REPEATS}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Loading bundle...")
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.\n")

        # Check setup
        for E in [10, 20]:
            bw = page.evaluate(f"defaultSourceBW({E})")
            page.evaluate(f"autoStripeForEnergy({E})")
            coat = page.evaluate('getStripeMaterial("m2").name')
            info = page.evaluate(f"""(() => {{
                var b = selectBest({E});
                return b ? {{n: b.n, gap: b.gap.toFixed(2)}} : null;
            }})()""")
            print(f"  {E}keV: dE_default={bw}eV, M2={coat},"
                  f" n={info['n']}, gap={info['gap']}mm")
        print()

        # ======== TEST 1: MC mono (sourceBW=0) ========
        print("=" * 110)
        print("TEST 1: MC monochromatic (sourceBW=0) vs S4 monochromatic")
        print("=" * 110)
        test1 = {}
        for cond in CONDITIONS:
            print(f"--- {cond['name']} (dE=0) ---")
            r = run_mc(page, cond, src_bw=0)
            s4r = s4[cond['name']]
            dh = (r['mc_h'] - s4r['fwhm_h_nm']) / s4r['fwhm_h_nm'] * 100
            dv = (r['mc_v'] - s4r['fwhm_v_nm']) / s4r['fwhm_v_nm'] * 100
            print(f"  >> MC H={r['mc_h']:.1f}+/-{r['mc_h_std']:.1f}"
                  f"  V={r['mc_v']:.1f}+/-{r['mc_v_std']:.1f}"
                  f"  S4 H={s4r['fwhm_h_nm']:.1f} V={s4r['fwhm_v_nm']:.1f}"
                  f"  dH={dh:+.1f}% dV={dv:+.1f}% thrput={r['thrput']:.1f}%")
            test1[cond['name']] = {**r, 'dh': dh, 'dv': dv, 'src_bw': 0}
            print()
        all_results['test1_mono'] = test1

        # ======== TEST 2: MC poly (sourceBW=default) ========
        print("=" * 110)
        print("TEST 2: MC polychromatic (sourceBW=default) vs S4 monochromatic")
        print("=" * 110)
        test2 = {}
        for cond in CONDITIONS:
            src_bw = page.evaluate(f"defaultSourceBW({cond['energy']})")
            print(f"--- {cond['name']} (dE={src_bw}eV) ---")
            r = run_mc(page, cond, src_bw=src_bw)
            s4r = s4[cond['name']]
            dh = (r['mc_h'] - s4r['fwhm_h_nm']) / s4r['fwhm_h_nm'] * 100
            dv = (r['mc_v'] - s4r['fwhm_v_nm']) / s4r['fwhm_v_nm'] * 100
            print(f"  >> MC H={r['mc_h']:.1f}+/-{r['mc_h_std']:.1f}"
                  f"  V={r['mc_v']:.1f}+/-{r['mc_v_std']:.1f}"
                  f"  S4 H={s4r['fwhm_h_nm']:.1f} V={s4r['fwhm_v_nm']:.1f}"
                  f"  dH={dh:+.1f}% dV={dv:+.1f}% thrput={r['thrput']:.1f}%")
            test2[cond['name']] = {**r, 'dh': dh, 'dv': dv, 'src_bw': src_bw}
            print()
        all_results['test2_poly'] = test2

        # ======== TEST 3: SSA isolation ========
        print("=" * 110)
        print("TEST 3: SSA-to-Sample isolation")
        print("=" * 110)
        test3 = {}
        for cond in CONDITIONS:
            # Set state first
            page.evaluate(f"""(() => {{
                state.sourceBW_eV = 0;
                state.ssaH = {cond['ssaH']}; state.ssaV = {cond['ssaV']};
                state.energy = {cond['energy']};
                var best = selectBest({cond['energy']});
                if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
                autoStripeForEnergy({cond['energy']});
                if (typeof updateOptics === 'function') updateOptics();
            }})()""")

            print(f"--- {cond['name']} (SSA isolation) ---")
            # Run 3 repeats for statistics
            iso_fh, iso_fv = [], []
            for rep in range(3):
                result = page.evaluate(
                    f"({SSA_ISOLATION_JS})({cond['energy']}, "
                    f"{cond['ssaH']}, {cond['ssaV']}, {NRAYS})")
                iso_fh.append(result['fwhmH_nm'])
                iso_fv.append(result['fwhmV_nm'])
                if rep == 0:
                    print(f"  SSA beam: sigH={result['sigH_ssa_um']:.2f}um"
                          f" sigV={result['sigV_ssa_um']:.2f}um")
                    print(f"  SSA eff:  effH={result['effH_um']:.2f}um"
                          f" effV={result['effV_um']:.2f}um")
                    print(f"  SSA div:  divH={result['divH_urad']:.2f}urad"
                          f" divV={result['divV_urad']:.2f}urad")
                    print(f"  nBeams: foc={result['nFocused']}"
                          f" dir={result['nDirect']}"
                          f" vO={result['nVonly']} hO={result['nHonly']}"
                          f" alive={result['totalAlive']}")
                print(f"  rep{rep+1}: H={result['fwhmH_nm']:.1f}nm"
                      f" V={result['fwhmV_nm']:.1f}nm")

            avg_h = statistics.mean(iso_fh)
            avg_v = statistics.mean(iso_fv)
            s4r = s4[cond['name']]
            dh = (avg_h - s4r['fwhm_h_nm']) / s4r['fwhm_h_nm'] * 100
            dv = (avg_v - s4r['fwhm_v_nm']) / s4r['fwhm_v_nm'] * 100
            print(f"  >> Iso H={avg_h:.1f}nm  V={avg_v:.1f}nm"
                  f"  S4 H={s4r['fwhm_h_nm']:.1f} V={s4r['fwhm_v_nm']:.1f}"
                  f"  dH={dh:+.1f}% dV={dv:+.1f}%")
            test3[cond['name']] = {
                'iso_h': avg_h, 'iso_v': avg_v,
                'dh': dh, 'dv': dv, **result
            }
            print()
        all_results['test3_ssa_iso'] = test3

        browser.close()

    # ======== SUMMARY ========
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print(f"{'Condition':<16s} {'Test':>12s}  {'MC H':>7s} {'MC V':>7s}"
          f"  {'S4 H':>7s} {'S4 V':>7s}  {'dH%':>7s} {'dV%':>7s}")
    print("-" * 90)
    for cond in CONDITIONS:
        name = cond['name']
        s4r = s4[name]
        t1 = test1[name]
        t2 = test2[name]
        t3 = test3[name]
        print(f"{name:<16s} {'mono(dE=0)':<12s}"
              f"  {t1['mc_h']:7.1f} {t1['mc_v']:7.1f}"
              f"  {s4r['fwhm_h_nm']:7.1f} {s4r['fwhm_v_nm']:7.1f}"
              f"  {t1['dh']:+6.1f}% {t1['dv']:+6.1f}%")
        print(f"{'':16s} {'poly(dE=def)':<12s}"
              f"  {t2['mc_h']:7.1f} {t2['mc_v']:7.1f}"
              f"  {s4r['fwhm_h_nm']:7.1f} {s4r['fwhm_v_nm']:7.1f}"
              f"  {t2['dh']:+6.1f}% {t2['dv']:+6.1f}%")
        print(f"{'':16s} {'SSA-iso':<12s}"
              f"  {t3['iso_h']:7.1f} {t3['iso_v']:7.1f}"
              f"  {s4r['fwhm_h_nm']:7.1f} {s4r['fwhm_v_nm']:7.1f}"
              f"  {t3['dh']:+6.1f}% {t3['dv']:+6.1f}%")
        print()

    print("Done.")


if __name__ == '__main__':
    main()
