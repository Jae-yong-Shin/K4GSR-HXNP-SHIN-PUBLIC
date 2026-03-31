"""
Analytical vs MC Benchmark: Compare quadratic beam size calculation with MC 500K x 5.
Conditions: 3 energies (5, 10, 20 keV) x 2 SSA settings (50x50, 20x10 um)
"""
import json, time, os, math, statistics
from playwright.sync_api import sync_playwright

BUNDLE = os.path.join(os.path.dirname(__file__),
                      'virtual_beamline_nanoprobe_V4_36_bundle.html')

CONDITIONS = [
    {'name': '5keV SSA50x50',   'energy': 5.0,  'ssaH': 50,  'ssaV': 50},
    {'name': '10keV SSA50x50',  'energy': 10.0, 'ssaH': 50,  'ssaV': 50},
    {'name': '20keV SSA50x50',  'energy': 20.0, 'ssaH': 50,  'ssaV': 50},
    {'name': '5keV SSA20x10',   'energy': 5.0,  'ssaH': 20,  'ssaV': 10},
    {'name': '10keV SSA20x10',  'energy': 10.0, 'ssaH': 20,  'ssaV': 10},
    {'name': '20keV SSA20x10',  'energy': 20.0, 'ssaH': 20,  'ssaV': 10},
]

NRAYS = 500000
N_REPEATS = 5
SRC_BW_EV = 1.0  # Source bandwidth in eV (0 = monochromatic)

# Analytical beam size calculation (runs in browser JS context)
ANALYTICAL_JS = """(E, ssaH_um, ssaV_um) => {
    var HC = 12.39842;  // keV*Angstrom
    var lambda = HC / E * 1e-10;  // meters
    var ps = photonSrc(E);

    // Source RMS sizes (meters)
    var sigX = ps.Sx, sigY = ps.Sy;
    var sigXp = ps.Sxp, sigYp = ps.Syp;  // divergence RMS (rad)

    // M1 sagittal -> V focus, M2 tangential -> H focus
    // M1_DM = M1_Q/M1_P (V), M2_DM = M2_Q/M2_P (H)
    var sigH_ssa = sigX * M2_DM;   // RMS beam H at SSA (M2 tangential)
    var sigV_ssa = sigY * M1_DM;   // RMS beam V at SSA (M1 sagittal)
    var fwhm_beam_H_ssa = sigH_ssa * 2.355e6;  // FWHM in um
    var fwhm_beam_V_ssa = sigV_ssa * 2.355e6;

    // SSA effective source (half-width, meters)
    var effH = Math.min(sigH_ssa, ssaH_um * 0.5e-6);
    var effV = Math.min(sigV_ssa, ssaV_um * 0.5e-6);

    // KB geometry
    var pV = pos('kbv') - pos('ssa');   // SSA -> KB-V distance
    var qV = pos('sample') - pos('kbv');  // KB-V -> sample
    var pH = pos('kbh') - pos('ssa');
    var qH = pos('sample') - pos('kbh');
    var MV = qV / pV;  // KB-V demag
    var MH = qH / pH;  // KB-H demag

    // Geometric FWHM at sample (nm)
    var fwhm_geo_H = 2.355 * effH * MH * 1e9;
    var fwhm_geo_V = 2.355 * effV * MV * 1e9;

    // Beam size at KB (diverging from SSA intermediate focus)
    // Divergence at SSA = source_div / M_demag (magnified)
    var divH_ssa = sigXp / M2_DM;
    var divV_ssa = sigYp / M1_DM;

    // Beam FWHM at KB position (Gaussian propagation from SSA waist)
    var beam_H_at_KBH = Math.sqrt(effH * effH + Math.pow(divH_ssa * pH, 2));
    var beam_V_at_KBV = Math.sqrt(effV * effV + Math.pow(divV_ssa * pV, 2));

    // KB acceptance (projected aperture)
    var theta = 3.0e-3;  // rad (nominal pitch)
    var kbp = window.KB_PARAMS || {};
    var kbvLen = kbp.kbv ? kbp.kbv.len : 0.300;
    var kbhLen = kbp.kbh ? kbp.kbh.len : 0.100;
    var accept_V = kbvLen * Math.sin(theta);  // projected V aperture
    var accept_H = kbhLen * Math.sin(theta);  // projected H aperture

    // Effective aperture D = min(mirror acceptance, 2*beam_rms at KB)
    // Using 2*sigma ~ FWHM/1.18 for Gaussian fill
    var D_V = Math.min(accept_V, 2 * beam_V_at_KBV);
    var D_H = Math.min(accept_H, 2 * beam_H_at_KBH);

    // Diffraction FWHM at sample (Airy: 0.886 * lambda * q / D)
    var fwhm_diff_H = 0.886 * lambda * qH / D_H * 1e9;  // nm
    var fwhm_diff_V = 0.886 * lambda * qV / D_V * 1e9;  // nm

    // Total FWHM (quadrature sum)
    var fwhm_H = Math.sqrt(fwhm_geo_H * fwhm_geo_H + fwhm_diff_H * fwhm_diff_H);
    var fwhm_V = Math.sqrt(fwhm_geo_V * fwhm_geo_V + fwhm_diff_V * fwhm_diff_V);

    return {
        fwhm_H: fwhm_H, fwhm_V: fwhm_V,
        geo_H: fwhm_geo_H, geo_V: fwhm_geo_V,
        diff_H: fwhm_diff_H, diff_V: fwhm_diff_V,
        beam_ssa_H_um: fwhm_beam_H_ssa, beam_ssa_V_um: fwhm_beam_V_ssa,
        ssa_H_um: ssaH_um, ssa_V_um: ssaV_um,
        D_H_um: D_H * 1e6, D_V_um: D_V * 1e6,
        accept_H_um: accept_H * 1e6, accept_V_um: accept_V * 1e6,
        MH: MH, MV: MV,
        lambda_nm: lambda * 1e9
    };
}"""


def main():
    print(f"Analytical vs MC Benchmark")
    print(f"MC: nRays = {NRAYS:,}, repeats = {N_REPEATS}, sourceBW = {SRC_BW_EV} eV")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Loading bundle...")
        page.goto(f'file:///{BUNDLE.replace(os.sep, "/")}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("Loaded.\n")

        # Print harmonic selection for each energy
        print("Undulator setup:")
        for E in sorted(set(c['energy'] for c in CONDITIONS)):
            info = page.evaluate(f"""(() => {{
                var b = selectBest({E});
                return b ? {{n: b.n, gap: b.gap.toFixed(2)}} : null;
            }})()""")
            if info:
                print(f"  {E} keV -> harmonic n={info['n']}, gap={info['gap']} mm")
        print()

        results = []

        for cond in CONDITIONS:
            print(f"--- {cond['name']} ---")

            # Set state with undulator
            page.evaluate(f"""(() => {{
                state.sourceBW_eV = {SRC_BW_EV};
                state.ssaH = {cond['ssaH']};
                state.ssaV = {cond['ssaV']};
                state.energy = {cond['energy']};
                var best = selectBest({cond['energy']});
                if (best) {{ state.harmonic = best.n; state.gap = best.gap; }}
                if (typeof autoStripeForEnergy === 'function') autoStripeForEnergy({cond['energy']});
                if (typeof updateEnergy === 'function') updateEnergy({cond['energy']});
                if (typeof updateOptics === 'function') updateOptics();
                _mcSampleCache = null;
            }})()""")

            # Analytical calculation
            ana = page.evaluate(f"({ANALYTICAL_JS})({cond['energy']}, {cond['ssaH']}, {cond['ssaV']})")
            print(f"  Analytical: H={ana['fwhm_H']:.1f}nm  V={ana['fwhm_V']:.1f}nm")
            print(f"    geo:  H={ana['geo_H']:.1f}nm  V={ana['geo_V']:.1f}nm")
            print(f"    diff: H={ana['diff_H']:.1f}nm  V={ana['diff_V']:.1f}nm")
            print(f"    D_eff: H={ana['D_H_um']:.0f}um  V={ana['D_V_um']:.0f}um"
                  f"  (accept: H={ana['accept_H_um']:.0f}um V={ana['accept_V_um']:.0f}um)")

            # MC runs
            fh_list, fv_list, rays_list = [], [], []
            for rep in range(N_REPEATS):
                t0 = time.time()
                result = page.evaluate(f"""(() => {{
                    _mcSampleCache = null;
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{
                        fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived, nTotal: mc.nTotal,
                        nBeams: mc.nBeams || null
                    }};
                }})()""")
                dt = time.time() - t0
                fh_nm = result['fwhmH'] * 1e9
                fv_nm = result['fwhmV'] * 1e9
                fh_list.append(fh_nm)
                fv_list.append(fv_nm)
                rays_list.append(result['nSurvived'])
                nb_str = ""
                if result.get('nBeams') and rep == 0:
                    nb = result['nBeams']
                    nb_str = f"  [focused={nb.get('focused',0)} direct={nb.get('direct',0)} vOnly={nb.get('vOnly',0)} hOnly={nb.get('hOnly',0)}]"
                print(f"  MC rep{rep+1}: H={fh_nm:.1f}nm  V={fv_nm:.1f}nm  "
                      f"rays={result['nSurvived']:,}  ({dt:.1f}s){nb_str}")

            mc_h = statistics.mean(fh_list)
            mc_v = statistics.mean(fv_list)
            mc_h_std = statistics.stdev(fh_list) if len(fh_list) > 1 else 0
            mc_v_std = statistics.stdev(fv_list) if len(fv_list) > 1 else 0
            mc_rays = statistics.mean(rays_list)
            thrput = mc_rays / NRAYS * 100

            dh = (mc_h - ana['fwhm_H']) / ana['fwhm_H'] * 100 if ana['fwhm_H'] > 0 else 0
            dv = (mc_v - ana['fwhm_V']) / ana['fwhm_V'] * 100 if ana['fwhm_V'] > 0 else 0

            print(f"  MC avg: H={mc_h:.1f}+/-{mc_h_std:.1f}nm  V={mc_v:.1f}+/-{mc_v_std:.1f}nm"
                  f"  rays={mc_rays:,.0f} ({thrput:.2f}%)")
            print(f"  MC vs Analytical: dH={dh:+.1f}%  dV={dv:+.1f}%")
            print()

            results.append({
                'name': cond['name'],
                'ana_H': ana['fwhm_H'], 'ana_V': ana['fwhm_V'],
                'geo_H': ana['geo_H'], 'geo_V': ana['geo_V'],
                'diff_H': ana['diff_H'], 'diff_V': ana['diff_V'],
                'mc_H': mc_h, 'mc_V': mc_v,
                'mc_H_std': mc_h_std, 'mc_V_std': mc_v_std,
                'mc_rays': mc_rays, 'thrput': thrput,
                'dH': dh, 'dV': dv,
            })

        browser.close()

    # Summary table
    print("=" * 100)
    print("SUMMARY: Analytical vs MC (500K x 5)")
    print(f"{'Condition':<18s} {'Ana H':>7s} {'Ana V':>7s}  "
          f"{'MC H':>7s} {'(std)':>6s} {'MC V':>7s} {'(std)':>6s}  "
          f"{'dH%':>6s} {'dV%':>6s} {'rays':>8s} {'thrpt':>6s}")
    print("-" * 100)
    for r in results:
        print(f"{r['name']:<18s} {r['ana_H']:7.1f} {r['ana_V']:7.1f}  "
              f"{r['mc_H']:7.1f} {r['mc_H_std']:5.1f}  {r['mc_V']:7.1f} {r['mc_V_std']:5.1f}  "
              f"{r['dH']:+5.1f}% {r['dV']:+5.1f}% {r['mc_rays']:8,.0f} {r['thrput']:5.2f}%")
    print("=" * 100)

    # Breakdown table
    print()
    print("BREAKDOWN: Geometric vs Diffraction contribution (nm)")
    print(f"{'Condition':<18s} {'Geo H':>7s} {'Diff H':>7s} {'Total H':>8s}  "
          f"{'Geo V':>7s} {'Diff V':>7s} {'Total V':>8s}")
    print("-" * 80)
    for r in results:
        print(f"{r['name']:<18s} {r['geo_H']:7.1f} {r['diff_H']:7.1f} {r['ana_H']:8.1f}  "
              f"{r['geo_V']:7.1f} {r['diff_V']:7.1f} {r['ana_V']:8.1f}")

    print("\nDone.")


if __name__ == '__main__':
    main()
