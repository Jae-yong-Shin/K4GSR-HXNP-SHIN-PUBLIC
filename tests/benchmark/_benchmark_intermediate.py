"""
MC vs S4 intermediate diagnostics: beam stats at each optic from source to SSA.
Compares sigH, sigV, FWHM_H, FWHM_V, n_survived at:
  source, after_M1, after_DCM, after_M2, at_SSA
"""
import json, time, os
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')
S4_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'paper', 'validation', 'data', 's4_intermediate.json')

NRAYS = 500000

# JS: generate rays at source, trace step-by-step, record stats at each position
MC_INTERMEDIATE_JS = """(E_keV, ssaH_um, ssaV_um, nR) => {
    var E = E_keV;
    var ps = photonSrc(E);

    // Ray stride
    var RS = 8;
    var rays = new Float64Array(nR * RS);

    // Generate source rays
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        rays[o]   = gaussRand() * ps.Sx;     // x
        rays[o+1] = gaussRand() * ps.Sy;     // y
        rays[o+2] = gaussRand() * ps.Sxp;    // vx
        rays[o+3] = gaussRand() * ps.Syp;    // vy
        rays[o+4] = 1.0;                      // vz
        rays[o+5] = 1.0;                      // alive
        rays[o+6] = E * 1000;                 // E_eV
        rays[o+7] = 0;                        // kbTag
    }

    // Stats helper
    function bstats(rays, nR, RS, label) {
        var xs = [], ys = [], vxs = [], vys = [];
        for (var i = 0; i < nR; i++) {
            var o = i * RS;
            if (rays[o+5] <= 0) continue;
            xs.push(rays[o]);
            ys.push(rays[o+1]);
            vxs.push(rays[o+2]);
            vys.push(rays[o+3]);
        }
        var n = xs.length;
        if (n < 10) return {n:n, sig_h:0, sig_v:0, sigp_h:0, sigp_v:0, fwhm_h:0, fwhm_v:0};

        function std(arr) {
            var s=0, s2=0;
            for(var i=0;i<arr.length;i++){s+=arr[i]; s2+=arr[i]*arr[i];}
            var m=s/arr.length;
            return Math.sqrt(s2/arr.length - m*m);
        }
        function fwhm(arr) {
            if(arr.length<10) return 0;
            arr.sort(function(a,b){return a-b;});
            var lo=arr[Math.floor(arr.length*0.005)], hi=arr[Math.floor(arr.length*0.995)];
            var nbins=201, bw=(hi-lo)/nbins;
            if(bw<=0) return 0;
            var hist=new Array(nbins).fill(0);
            for(var i=0;i<arr.length;i++){
                var bi=Math.floor((arr[i]-lo)/bw);
                if(bi>=0 && bi<nbins) hist[bi]++;
            }
            var peak=0;
            for(var i=0;i<nbins;i++) if(hist[i]>peak) peak=hist[i];
            var hm=peak*0.5, left=0, right=nbins-1;
            for(var i=0;i<nbins;i++) if(hist[i]>=hm){left=i;break;}
            for(var i=nbins-1;i>=0;i--) if(hist[i]>=hm){right=i;break;}
            return (right-left)*bw;
        }

        return {
            n: n,
            sig_h: std(xs), sig_v: std(ys),
            sigp_h: std(vxs), sigp_v: std(vys),
            fwhm_h: fwhm(xs.slice()), fwhm_v: fwhm(ys.slice())
        };
    }

    // Propagate helper
    function propagate(rays, nR, RS, dz) {
        for (var i = 0; i < nR; i++) {
            var o = i * RS;
            if (rays[o+5] <= 0) continue;
            rays[o]   += rays[o+2] * dz;
            rays[o+1] += rays[o+3] * dz;
        }
    }

    var results = {};

    // Source stats
    results.source = bstats(rays, nR, RS, 'source');
    results.source_params = {Sx: ps.Sx, Sy: ps.Sy, Sxp: ps.Sxp, Syp: ps.Syp};

    // Propagate to M1
    var m1Pos = pos('m1');
    propagate(rays, nR, RS, m1Pos);

    // Apply M1
    applyMirrorMC(rays, nR, 'm1', E);
    results.after_M1 = bstats(rays, nR, RS, 'after_M1');

    // Propagate to DCM (from M1 position)
    var dcmPos = pos('dcm');
    propagate(rays, nR, RS, dcmPos - m1Pos);

    // Apply DCM
    applyDCM_MC(rays, nR, E);
    results.after_DCM = bstats(rays, nR, RS, 'after_DCM');

    // Propagate to M2
    var m2Pos = pos('m2');
    propagate(rays, nR, RS, m2Pos - dcmPos);

    // Apply M2
    applyMirrorMC(rays, nR, 'm2', E);
    results.after_M2 = bstats(rays, nR, RS, 'after_M2');

    // Propagate to SSA
    var ssaPos = pos('ssa');
    propagate(rays, nR, RS, ssaPos - m2Pos);

    // Apply SSA slit (clip rays outside aperture)
    var halfH = ssaH_um * 0.5e-6;
    var halfV = ssaV_um * 0.5e-6;
    for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        if (Math.abs(rays[o]) > halfH || Math.abs(rays[o+1]) > halfV) {
            rays[o+5] = 0;
        }
    }
    results.at_SSA = bstats(rays, nR, RS, 'at_SSA');

    // Also record positions used
    results.positions = {
        m1: m1Pos, dcm: dcmPos, m2: m2Pos, ssa: ssaPos
    };

    return results;
}"""


def main():
    # Load S4 intermediate
    s4_all = json.load(open(S4_DATA))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Bundle loaded.\n")

        for E, ssa, s4_key in [(10.0, 50, '10keV_ssa50'), (20.0, 50, '20keV_ssa50')]:
            # Set state
            page.evaluate(f"""(() => {{
                state.sourceBW_eV = 0;
                state.ssaH = {ssa}; state.ssaV = {ssa};
                state.energy = {E};
                var best = selectBest({E});
                if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
                autoStripeForEnergy({E});
                if (typeof updateOptics === 'function') updateOptics();
            }})()""")

            # Check M2 coating
            coat = page.evaluate('getStripeMaterial("m2").name')
            print(f"=== {E} keV, SSA {ssa}x{ssa}um, M2={coat} ===")

            # Run MC intermediate
            mc = page.evaluate(f"({MC_INTERMEDIATE_JS})({E}, {ssa}, {ssa}, {NRAYS})")
            s4 = s4_all[s4_key]

            # Print comparison table
            stages = ['source', 'after_M1', 'after_DCM', 'after_M2', 'at_SSA']
            print()
            print(f"{'Stage':<14s}  {'MC sig_h':>12s} {'S4 sig_h':>12s} {'ratio':>7s}"
                  f"  {'MC sig_v':>12s} {'S4 sig_v':>12s} {'ratio':>7s}"
                  f"  {'MC n':>8s} {'S4 n':>8s}")
            print("-" * 110)

            for stage in stages:
                mc_s = mc.get(stage, {})
                s4_s = s4.get(stage, {})
                mc_sh = mc_s.get('sig_h', 0)
                mc_sv = mc_s.get('sig_v', 0)
                s4_sh = s4_s.get('sig_h', 0)
                s4_sv = s4_s.get('sig_v', 0)
                mc_n = mc_s.get('n', 0)
                s4_n = s4_s.get('n', 0)
                rh = mc_sh / s4_sh if s4_sh > 0 else 0
                rv = mc_sv / s4_sv if s4_sv > 0 else 0

                print(f"{stage:<14s}  {mc_sh:12.4e} {s4_sh:12.4e} {rh:6.3f}x"
                      f"  {mc_sv:12.4e} {s4_sv:12.4e} {rv:6.3f}x"
                      f"  {mc_n:8d} {s4_n:8d}")

            # Also print FWHM comparison
            print()
            print(f"{'Stage':<14s}  {'MC fwhm_h':>12s} {'S4 fwhm_h':>12s} {'ratio':>7s}"
                  f"  {'MC fwhm_v':>12s} {'S4 fwhm_v':>12s} {'ratio':>7s}")
            print("-" * 90)

            for stage in stages:
                mc_s = mc.get(stage, {})
                s4_s = s4.get(stage, {})
                mc_fh = mc_s.get('fwhm_h', 0)
                mc_fv = mc_s.get('fwhm_v', 0)
                s4_fh = s4_s.get('fwhm_h', 0)
                s4_fv = s4_s.get('fwhm_v', 0)
                rfh = mc_fh / s4_fh if s4_fh > 0 else 0
                rfv = mc_fv / s4_fv if s4_fv > 0 else 0

                print(f"{stage:<14s}  {mc_fh:12.4e} {s4_fh:12.4e} {rfh:6.3f}x"
                      f"  {mc_fv:12.4e} {s4_fv:12.4e} {rfv:6.3f}x")

            # Divergence at each stage (MC only, S4 doesn't have this)
            print()
            print(f"{'Stage':<14s}  {'MC sigp_h':>12s} {'MC sigp_v':>12s}")
            print("-" * 45)
            for stage in stages:
                mc_s = mc.get(stage, {})
                print(f"{stage:<14s}  {mc_s.get('sigp_h',0):12.4e} {mc_s.get('sigp_v',0):12.4e}")

            # Source params
            sp = mc.get('source_params', {})
            s4sp = s4.get('source_params', {})
            print()
            print(f"Source params: MC Sx={sp.get('Sx',0):.4e} S4 Sx={s4sp.get('Sx',0):.4e}"
                  f"  MC Sy={sp.get('Sy',0):.4e} S4 Sy={s4sp.get('Sy',0):.4e}")
            print(f"              MC Sxp={sp.get('Sxp',0):.4e} S4 Sxp={s4sp.get('Sxp',0):.4e}"
                  f"  MC Syp={sp.get('Syp',0):.4e} S4 Syp={s4sp.get('Syp',0):.4e}")
            print()
            print()

        browser.close()
    print("Done.")


if __name__ == '__main__':
    main()
