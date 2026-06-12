"""
Analytical beam size calculation using Playwright against the bundle HTML.
Loads the virtual beamline in headless Chromium, calls photonSrc(E) for each energy,
and computes geometric + diffraction-limited beam sizes at sample.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ENERGIES = [5, 7, 10, 12, 15, 18, 20, 25, 30]
SSA_CONFIGS = [
    {"label": "50x50", "ssaH": 50, "ssaV": 50},
    {"label": "20x10", "ssaH": 20, "ssaV": 10},
]

JS_CALC = r"""
(args) => {
    const E = args.E, ssaH = args.ssaH, ssaV = args.ssaV;
    try {
        state.energy = E;
        state.ssaH = ssaH;
        state.ssaV = ssaV;
        var ps = photonSrc(E);
        var hc = HC;
        var lambda_m = (hc / E) * 1e-10;
        var posSSA    = pos('ssa');
        var posKBV    = pos('kbv');
        var posKBH    = pos('kbh');
        var posSample = pos('sample');
        var pV = posKBV - posSSA;
        var qV = posSample - posKBV;
        var pH = posKBH - posSSA;
        var qH = posSample - posKBH;
        var M_kbv = qV / pV;
        var M_kbh = qH / pH;
        var m1dm = M1_DM;
        var m2dm = M2_DM;
        var sigH_ssa = ps.Sx * m1dm;
        var sigV_ssa = ps.Sy * m2dm;
        var ssaH_half = ssaH * 0.5e-6;
        var ssaV_half = ssaV * 0.5e-6;
        var effH = Math.min(sigH_ssa, ssaH_half);
        var effV = Math.min(sigV_ssa, ssaV_half);
        var kbhLen = KB_PARAMS.kbh.len;
        var kbvLen = KB_PARAMS.kbv.len;
        var D_eff_H = kbhLen;
        var D_eff_V = kbvLen;
        var geo_H = 2.355 * effH * M_kbh * 1e9;
        var geo_V = 2.355 * effV * M_kbv * 1e9;
        var diff_H = 0.886 * lambda_m * qH / D_eff_H * 1e9;
        var diff_V = 0.886 * lambda_m * qV / D_eff_V * 1e9;
        var total_H = Math.sqrt(geo_H * geo_H + diff_H * diff_H);
        var total_V = Math.sqrt(geo_V * geo_V + diff_V * diff_V);
        return {
            E: E, ssaLabel: ssaH + 'x' + ssaV,
            Sx: ps.Sx * 1e6, Sy: ps.Sy * 1e6,
            Sxp: ps.Sxp * 1e6, Syp: ps.Syp * 1e6,
            m1dm: m1dm, m2dm: m2dm,
            M_kbh: M_kbh, M_kbv: M_kbv,
            pV: pV, qV: qV, pH: pH, qH: qH,
            kbhLen: kbhLen, kbvLen: kbvLen,
            sigH_ssa: sigH_ssa * 1e6, sigV_ssa: sigV_ssa * 1e6,
            ssaH_half: ssaH_half * 1e6, ssaV_half: ssaV_half * 1e6,
            effH: effH * 1e6, effV: effV * 1e6,
            geo_H: geo_H, diff_H: diff_H, total_H: total_H,
            geo_V: geo_V, diff_V: diff_V, total_V: total_V,
            error: null
        };
    } catch(e) {
        return {E: E, error: e.message + ' | ' + e.stack};
    }
}
"""

JS_CHECK = r"""
() => ({
    HC: HC,
    GAMMA_E: GAMMA_E,
    M1_DM: M1_DM,
    M2_DM: M2_DM,
    posSSA: pos('ssa'),
    posKBV: pos('kbv'),
    posKBH: pos('kbh'),
    posSample: pos('sample'),
    kbhLen: KB_PARAMS.kbh.len,
    kbvLen: KB_PARAMS.kbv.len
})
"""

JS_WAIT = 'typeof photonSrc === "function" && typeof pos === "function" && typeof KB_PARAMS !== "undefined"'


def main():
    bundle_path = (Path(__file__).resolve().parents[2] / "virtual_beamline_nanoprobe_V4_36_bundle.html").as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"Loading bundle: {bundle_path}")
        try:
            page.goto(bundle_path, timeout=30000, wait_until="networkidle")
        except Exception as e:
            print(f"Warning during page load: {e}")
            print("Attempting to continue anyway...")

        page.wait_for_function(JS_WAIT, timeout=15000)
        print("Page loaded, key functions available.\n")

        check = page.evaluate(JS_CHECK)
        print("=== Beamline Constants ===")
        for k, v in check.items():
            print(f"  {k}: {v}")
        print()

        results = []
        for ssa in SSA_CONFIGS:
            for E in ENERGIES:
                r = page.evaluate(JS_CALC, {"E": E, "ssaH": ssa["ssaH"], "ssaV": ssa["ssaV"]})
                if r.get("error"):
                    print(f"ERROR at E={E}, SSA={ssa['label']}: {r['error']}")
                else:
                    results.append(r)

        browser.close()

    # Print results table
    print("=" * 120)
    print("ANALYTICAL BEAM SIZE AT SAMPLE (nm)")
    print("=" * 120)
    hdr = f"{'E(keV)':>8} | {'SSA':>7} | {'geo_H':>8} | {'diff_H':>8} | {'total_H':>8} | {'geo_V':>8} | {'diff_V':>8} | {'total_V':>8} | {'effH(um)':>9} | {'effV(um)':>9}"
    print(hdr)
    print("-" * 120)

    for r in results:
        print(
            f"{r['E']:8.0f} | {r['ssaLabel']:>7} | "
            f"{r['geo_H']:8.1f} | {r['diff_H']:8.1f} | {r['total_H']:8.1f} | "
            f"{r['geo_V']:8.1f} | {r['diff_V']:8.1f} | {r['total_V']:8.1f} | "
            f"{r['effH']:9.2f} | {r['effV']:9.2f}"
        )

    # Source parameters
    print()
    print("=" * 100)
    print("SOURCE PARAMETERS (from photonSrc)")
    print("=" * 100)
    hdr2 = f"{'E(keV)':>8} | {'Sx(um)':>9} | {'Sy(um)':>9} | {'Sxp(urad)':>10} | {'Syp(urad)':>10} | {'sigH@SSA(um)':>13} | {'sigV@SSA(um)':>13}"
    print(hdr2)
    print("-" * 100)
    seen = set()
    for r in results:
        key = r['E']
        if key in seen:
            continue
        seen.add(key)
        print(
            f"{r['E']:8.0f} | {r['Sx']:9.2f} | {r['Sy']:9.2f} | "
            f"{r['Sxp']:10.2f} | {r['Syp']:10.2f} | "
            f"{r['sigH_ssa']:13.2f} | {r['sigV_ssa']:13.2f}"
        )

    print()
    print("=== KB Geometry ===")
    if results:
        r0 = results[0]
        print(f"  KB-H: p={r0['pH']:.2f}m, q={r0['qH']:.2f}m, M={r0['M_kbh']:.6f}, len={r0['kbhLen']}m")
        print(f"  KB-V: p={r0['pV']:.2f}m, q={r0['qV']:.2f}m, M={r0['M_kbv']:.6f}, len={r0['kbvLen']}m")
        print(f"  M1_DM(H)={r0['m1dm']:.4f}, M2_DM(V)={r0['m2dm']:.4f}")


if __name__ == "__main__":
    main()
