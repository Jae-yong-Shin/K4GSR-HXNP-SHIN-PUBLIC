"""
DCM Divergence Filtering Diagnostic (weight-based version):
Measure source vs post-DCM angular divergence for different sourceBW values.
Uses the same internal functions as mcRayTrace (photonSrc, applyMirrorMC, applyDCM_MC).

After Guigay DCM port: applyDCM_MC now uses weight-based reflectivity
(rays[o+5] *= R) instead of stochastic accept/reject. So divergence
is measured using weight-weighted statistics.
"""
import json, time, os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(__file__),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')
NRAYS = 200000

DIAG_JS = """(E_keV, bw_eV, nR) => {
    // Set state
    state.energy = E_keV;
    state.sourceBW_eV = bw_eV;
    var best = selectBest(E_keV);
    if (best) { state.harmonic = best.n; state.gap = best.gap; }
    if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy(E_keV);
    if (typeof updateEnergy === 'function') updateEnergy(E_keV);
    if (typeof updateOptics === 'function') updateOptics();

    var E = E_keV;
    var ps = photonSrc(E);
    var srcSigVx = ps.Sxp;
    var srcSigVy = ps.Syp;

    // Generate rays
    var E_eV_center = E * 1000;
    var srcBW = (bw_eV > 0 && E_eV_center > 0) ? bw_eV / E_eV_center : 0;
    var rays = new Float64Array(nR * RS);
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        rays[o]   = gaussRand() * ps.Sx;
        rays[o+1] = gaussRand() * ps.Sy;
        rays[o+2] = gaussRand() * ps.Sxp;
        rays[o+3] = gaussRand() * ps.Syp;
        rayUpdateVz(rays, o);
        rays[o+5] = 1;
        rays[o+6] = (srcBW > 0) ? E_eV_center * (1 + gaussRand() * srcBW * 0.5) : E_eV_center;
        rays[o+7] = 0;
    }

    // Helper: weight-based divergence stats
    function wStats(rays, nR, RS) {
        var sumW = 0, sumWvx2 = 0, sumWvy2 = 0, nAlive = 0;
        for (var i = 0; i < nR; i++) {
            var o = i * RS;
            var w = rays[o+5];
            if (w <= 0) continue;
            nAlive++;
            sumW += w;
            sumWvx2 += w * rays[o+2] * rays[o+2];
            sumWvy2 += w * rays[o+3] * rays[o+3];
        }
        return {
            nAlive: nAlive,
            sumW: sumW,
            sigVx: (sumW > 0) ? Math.sqrt(sumWvx2 / sumW) : 0,
            sigVy: (sumW > 0) ? Math.sqrt(sumWvy2 / sumW) : 0
        };
    }

    // Source stats (all weights = 1)
    var src = wStats(rays, nR, RS);

    // Drift to M1
    var L = pos('m1');
    for (var i = 0; i < nR; i++) {
        var o = i * RS; if (rays[o+5] <= 0) continue;
        var ivz = 1 / rays[o+4];
        rays[o] += rays[o+2] * ivz * L;
        rays[o+1] += rays[o+3] * ivz * L;
    }
    applyMirrorMC(rays, nR, 'm1', E);

    // Drift M1 -> M2
    L = pos('m2') - pos('m1');
    for (var i = 0; i < nR; i++) {
        var o = i * RS; if (rays[o+5] <= 0) continue;
        var ivz = 1 / rays[o+4];
        rays[o] += rays[o+2] * ivz * L;
        rays[o+1] += rays[o+3] * ivz * L;
    }
    applyMirrorMC(rays, nR, 'm2', E);

    // Pre-DCM stats (weighted)
    var pre = wStats(rays, nR, RS);

    // Drift M2 -> DCM
    L = pos('dcm') - pos('m2');
    for (var i = 0; i < nR; i++) {
        var o = i * RS; if (rays[o+5] <= 0) continue;
        var ivz = 1 / rays[o+4];
        rays[o] += rays[o+2] * ivz * L;
        rays[o+1] += rays[o+3] * ivz * L;
    }
    applyDCM_MC(rays, nR, E);

    // Post-DCM stats (weighted)
    var post = wStats(rays, nR, RS);

    // Mean energy of surviving rays
    var sumWE = 0;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] > 0) sumWE += rays[o+5] * rays[o+6];
    }
    var meanE_post = (post.sumW > 0) ? sumWE / post.sumW : E_eV_center;

    // Darwin width
    var dw_asec = (typeof darwinW === 'function') ? darwinW(E) : 0;
    var dw_urad = dw_asec / 206265 * 1e6;

    return {
        energy_keV: E,
        sourceBW_eV: bw_eV,
        // Source
        src_sigVx_urad: src.sigVx * 1e6,
        src_sigVy_urad: src.sigVy * 1e6,
        // Pre-DCM (weighted)
        preDCM_sigVx_urad: pre.sigVx * 1e6,
        preDCM_sigVy_urad: pre.sigVy * 1e6,
        preDCM_nAlive: pre.nAlive,
        preDCM_sumW: pre.sumW,
        // Post-DCM (weighted)
        postDCM_sigVx_urad: post.sigVx * 1e6,
        postDCM_sigVy_urad: post.sigVy * 1e6,
        postDCM_nAlive: post.nAlive,
        postDCM_sumW: post.sumW,
        postDCM_meanE_eV: meanE_post,
        // Ratios (weight-based throughput)
        dcm_weight_throughput_pct: (pre.sumW > 0) ? (post.sumW / pre.sumW * 100) : 0,
        dcm_ray_throughput_pct: (pre.nAlive > 0) ? (post.nAlive / pre.nAlive * 100) : 0,
        total_throughput_pct: (post.sumW / nR * 100),
        // Divergence ratio (post/pre, weight-based)
        vx_ratio: (pre.sigVx > 0) ? post.sigVx / pre.sigVx : 0,
        vy_ratio: (pre.sigVy > 0) ? post.sigVy / pre.sigVy : 0,
        // Reference
        darwin_fwhm_urad: dw_urad
    };
}"""


def main():
    print("DCM Divergence Filtering Diagnostic (Weight-Based Guigay)")
    print(f"nRays = {NRAYS:,}")
    print()

    energies = [5.0, 10.0, 20.0]
    bw_values = [0, 1.0, 5.0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Loading bundle...")
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.\n")

        results = []
        for E in energies:
            print(f"=== {E} keV ===")
            print(f"{'BW(eV)':>7s} | {'pre sigVx':>10s} {'post sigVx':>10s} {'vx_ratio':>9s}"
                  f" | {'pre sigVy':>10s} {'post sigVy':>10s} {'vy_ratio':>9s}"
                  f" | {'wt_thru':>8s} {'ray_thru':>9s}"
                  f" | {'Darwin':>8s}")
            print("-" * 115)

            for bw in bw_values:
                r = page.evaluate(f"({DIAG_JS})({E}, {bw}, {NRAYS})")
                results.append(r)
                print(f"{bw:7.1f} | "
                      f"{r['preDCM_sigVx_urad']:8.2f}ur {r['postDCM_sigVx_urad']:8.2f}ur {r['vx_ratio']:8.4f}x"
                      f" | {r['preDCM_sigVy_urad']:8.2f}ur {r['postDCM_sigVy_urad']:8.2f}ur {r['vy_ratio']:8.4f}x"
                      f" | {r['dcm_weight_throughput_pct']:6.2f}%  {r['dcm_ray_throughput_pct']:7.2f}%"
                      f" | {r['darwin_fwhm_urad']:6.2f}ur")

            print()

        browser.close()

    # Summary analysis
    print("=" * 70)
    print("ANALYSIS: Does weight-based Guigay DCM preserve divergence?")
    print("=" * 70)
    for r in results:
        E = r['energy_keV']
        bw = r['sourceBW_eV']
        vx = r['vx_ratio']
        vy = r['vy_ratio']
        # With weight-based, ratios should be ~1.0 (no angular filtering)
        vx_ok = abs(vx - 1.0) < 0.05  # within 5% of unity
        vy_ok = abs(vy - 1.0) < 0.05
        status = "PASS" if (vx_ok and vy_ok) else "CHECK"
        print(f"  {E:5.1f}keV BW={bw:4.1f}eV: "
              f"vx_ratio={vx:.4f} ({'OK' if vx_ok else 'FILTERED'}), "
              f"vy_ratio={vy:.4f} ({'OK' if vy_ok else 'FILTERED'}) "
              f"-> {status}")
    print()


if __name__ == '__main__':
    main()
