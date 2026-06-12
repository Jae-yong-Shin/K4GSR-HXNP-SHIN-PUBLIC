"""
Benchmark: Hybrid Decomposition Test
=====================================
Tests 4 configurations to isolate the sequential effect of SSA hybrid on KB hybrid.

Hypothesis: S4 applies SSA hybrid BEFORE KB, modifying the angular distribution
of rays entering KB. This changes the KB footprint and diffraction pattern.
If disabling SSA hybrid significantly changes the KB FWHM, it confirms the
sequential effect.

Configurations:
  1. FULL hybrid   (SSA + KB both enabled)  -- baseline
  2. KB-only       (SSA hybrid disabled, KB hybrid enabled)
  3. SSA-only      (SSA hybrid enabled, KB hybrid disabled)
  4. NO hybrid     (both disabled)           -- geometric baseline

Parameters: 10 keV, SSA 50x50 um, NRAYS=200000, 3 repeats
"""

import sys
import time
import statistics
from pathlib import Path
from playwright.sync_api import sync_playwright

BUNDLE = Path(__file__).resolve().parents[2] / "virtual_beamline_nanoprobe_V4_36_bundle.html"
NRAYS = 200000
N_REPEATS = 3
ENERGY_KEV = 10.0
SSA_H = 50  # um
SSA_V = 50  # um

# Configuration definitions: (name, disable_ssa_hybrid, disable_kb_hybrid)
CONFIGS = [
    ("FULL hybrid (SSA+KB)",  False, False),
    ("KB-only hybrid",        True,  False),
    ("SSA-only hybrid",       False, True),
    ("NO hybrid (geometric)", True,  True),
]


def run_benchmark():
    url = BUNDLE.as_uri()
    print(f"Bundle: {BUNDLE}")
    print(f"URL:    {url}")
    print(f"NRAYS={NRAYS}, N_REPEATS={N_REPEATS}, E={ENERGY_KEV} keV, SSA={SSA_H}x{SSA_V} um")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        # Load the bundle
        print("Loading bundle HTML...")
        page.goto(url, wait_until="load", timeout=60000)

        # Wait for mcRayTrace to be defined
        print("Waiting for mcRayTrace to be available...")
        page.wait_for_function("typeof mcRayTrace === 'function'", timeout=30000)
        print("mcRayTrace is available.")

        # Also verify hybrid functions exist
        has_ssa = page.evaluate("typeof _applySSAHybrid === 'function'")
        has_kb = page.evaluate("typeof _applyHybridFresnel === 'function'")
        print(f"_applySSAHybrid  exists: {has_ssa}")
        print(f"_applyHybridFresnel exists: {has_kb}")
        if not has_ssa or not has_kb:
            print("ERROR: Hybrid functions not found. Aborting.")
            browser.close()
            return
        print()

        # Store original function references on the window object
        page.evaluate("""() => {
            window.__orig_applySSAHybrid = window._applySSAHybrid;
            window.__orig_applyHybridFresnel = window._applyHybridFresnel;
        }""")

        results = {}  # config_name -> list of {fwhmH, fwhmV, nSurvived, time_ms}

        for cfg_name, disable_ssa, disable_kb in CONFIGS:
            print(f"--- Config: {cfg_name} ---")
            runs = []

            for rep in range(N_REPEATS):
                # Restore originals first
                page.evaluate("""() => {
                    window._applySSAHybrid = window.__orig_applySSAHybrid;
                    window._applyHybridFresnel = window.__orig_applyHybridFresnel;
                }""")

                # Apply disabling as needed
                if disable_ssa:
                    page.evaluate("window._applySSAHybrid = function() {};")
                if disable_kb:
                    page.evaluate("window._applyHybridFresnel = function() {};")

                # Set state
                page.evaluate(f"""() => {{
                    state.energy = {ENERGY_KEV};
                    state.ssaH = {SSA_H};
                    state.ssaV = {SSA_V};
                    if (typeof updateEnergy === 'function') updateEnergy({ENERGY_KEV});
                    if (typeof updateOptics === 'function') updateOptics();
                }}""")

                # Run MC ray trace
                t0 = time.perf_counter()
                result = page.evaluate(f"""() => {{
                    var mc = mcRayTrace(pos('sample') || 150.0, {NRAYS});
                    return {{
                        fwhmH: mc.fwhmH,
                        fwhmV: mc.fwhmV,
                        nSurvived: mc.nSurvived
                    }};
                }}""")
                elapsed_ms = (time.perf_counter() - t0) * 1000

                fwhmH_nm = result["fwhmH"] * 1e9
                fwhmV_nm = result["fwhmV"] * 1e9
                ns = result["nSurvived"]

                runs.append({
                    "fwhmH_nm": fwhmH_nm,
                    "fwhmV_nm": fwhmV_nm,
                    "nSurvived": ns,
                    "time_ms": elapsed_ms,
                })
                print(f"  Rep {rep+1}: FWHM H={fwhmH_nm:8.2f} nm  V={fwhmV_nm:8.2f} nm  "
                      f"survived={ns:6d}/{NRAYS}  time={elapsed_ms:.0f} ms")

            results[cfg_name] = runs
            print()

        # Restore originals before closing
        page.evaluate("""() => {
            window._applySSAHybrid = window.__orig_applySSAHybrid;
            window._applyHybridFresnel = window.__orig_applyHybridFresnel;
        }""")

        browser.close()

    # === Print summary table ===
    print("=" * 100)
    print("BENCHMARK RESULTS: Hybrid Decomposition")
    print(f"Parameters: E={ENERGY_KEV} keV, SSA={SSA_H}x{SSA_V} um, NRAYS={NRAYS}, repeats={N_REPEATS}")
    print("=" * 100)
    print()

    hdr = (f"{'Configuration':<28} | {'FWHM-H (nm)':>14} | {'FWHM-V (nm)':>14} | "
           f"{'Survived':>10} | {'Time (ms)':>10} | {'SSA hyb':>8} | {'KB hyb':>8}")
    print(hdr)
    print("-" * len(hdr))

    summary = {}
    for cfg_name, disable_ssa, disable_kb in CONFIGS:
        runs = results[cfg_name]
        fwhmH_vals = [r["fwhmH_nm"] for r in runs]
        fwhmV_vals = [r["fwhmV_nm"] for r in runs]
        surv_vals = [r["nSurvived"] for r in runs]
        time_vals = [r["time_ms"] for r in runs]

        avgH = statistics.mean(fwhmH_vals)
        avgV = statistics.mean(fwhmV_vals)
        stdH = statistics.stdev(fwhmH_vals) if len(fwhmH_vals) > 1 else 0
        stdV = statistics.stdev(fwhmV_vals) if len(fwhmV_vals) > 1 else 0
        avgS = statistics.mean(surv_vals)
        avgT = statistics.mean(time_vals)
        ssa_status = "OFF" if disable_ssa else "ON"
        kb_status = "OFF" if disable_kb else "ON"

        summary[cfg_name] = {"avgH": avgH, "avgV": avgV, "stdH": stdH, "stdV": stdV,
                             "avgS": avgS, "avgT": avgT}

        print(f"{cfg_name:<28} | {avgH:7.2f} +/- {stdH:4.2f} | {avgV:7.2f} +/- {stdV:4.2f} | "
              f"{avgS:10.0f} | {avgT:10.0f} | {ssa_status:>8} | {kb_status:>8}")

    print()

    # === Analysis ===
    print("=" * 100)
    print("ANALYSIS: Sequential SSA -> KB effect")
    print("=" * 100)
    print()

    full = summary["FULL hybrid (SSA+KB)"]
    kb_only = summary["KB-only hybrid"]
    ssa_only = summary["SSA-only hybrid"]
    no_hyb = summary["NO hybrid (geometric)"]

    # Effect of SSA hybrid on KB output (compare FULL vs KB-only)
    dH_ssa_on_kb = full["avgH"] - kb_only["avgH"]
    dV_ssa_on_kb = full["avgV"] - kb_only["avgV"]
    pctH = (dH_ssa_on_kb / kb_only["avgH"] * 100) if kb_only["avgH"] > 0 else 0
    pctV = (dV_ssa_on_kb / kb_only["avgV"] * 100) if kb_only["avgV"] > 0 else 0

    print("1. SSA hybrid effect on KB-focused beam (FULL vs KB-only):")
    print(f"   Delta FWHM-H = {dH_ssa_on_kb:+.2f} nm ({pctH:+.1f}%)")
    print(f"   Delta FWHM-V = {dV_ssa_on_kb:+.2f} nm ({pctV:+.1f}%)")
    print(f"   -> {'SIGNIFICANT' if abs(pctH) > 2 or abs(pctV) > 2 else 'NEGLIGIBLE'} sequential coupling")
    print()

    # Pure KB diffraction effect (compare KB-only vs NO hybrid)
    dH_kb = kb_only["avgH"] - no_hyb["avgH"]
    dV_kb = kb_only["avgV"] - no_hyb["avgV"]
    pctH_kb = (dH_kb / no_hyb["avgH"] * 100) if no_hyb["avgH"] > 0 else 0
    pctV_kb = (dV_kb / no_hyb["avgV"] * 100) if no_hyb["avgV"] > 0 else 0

    print("2. Pure KB hybrid effect (KB-only vs NO hybrid):")
    print(f"   Delta FWHM-H = {dH_kb:+.2f} nm ({pctH_kb:+.1f}%)")
    print(f"   Delta FWHM-V = {dV_kb:+.2f} nm ({pctV_kb:+.1f}%)")
    print()

    # Pure SSA diffraction effect (compare SSA-only vs NO hybrid)
    dH_ssa = ssa_only["avgH"] - no_hyb["avgH"]
    dV_ssa = ssa_only["avgV"] - no_hyb["avgV"]
    pctH_ssa = (dH_ssa / no_hyb["avgH"] * 100) if no_hyb["avgH"] > 0 else 0
    pctV_ssa = (dV_ssa / no_hyb["avgV"] * 100) if no_hyb["avgV"] > 0 else 0

    print("3. Pure SSA hybrid effect at sample (SSA-only vs NO hybrid):")
    print(f"   Delta FWHM-H = {dH_ssa:+.2f} nm ({pctH_ssa:+.1f}%)")
    print(f"   Delta FWHM-V = {dV_ssa:+.2f} nm ({pctV_ssa:+.1f}%)")
    print()

    # Additivity check: does FULL ~ KB-only + SSA-only - NO hybrid?
    predictH = kb_only["avgH"] + ssa_only["avgH"] - no_hyb["avgH"]
    predictV = kb_only["avgV"] + ssa_only["avgV"] - no_hyb["avgV"]
    residH = full["avgH"] - predictH
    residV = full["avgV"] - predictV

    print("4. Additivity check: FULL vs (KB-only + SSA-only - NO hybrid):")
    print(f"   Predicted FWHM-H = {predictH:.2f} nm,  Actual = {full['avgH']:.2f} nm,  Residual = {residH:+.2f} nm")
    print(f"   Predicted FWHM-V = {predictV:.2f} nm,  Actual = {full['avgV']:.2f} nm,  Residual = {residV:+.2f} nm")
    print(f"   -> {'NON-LINEAR coupling' if abs(residH) > 1 or abs(residV) > 1 else 'Approximately additive'}")
    print()

    # Survived rays comparison
    print("5. Survived rays (should be identical -- hybrid doesn't kill rays):")
    for cfg_name, _, _ in CONFIGS:
        s = summary[cfg_name]
        print(f"   {cfg_name:<28}: {s['avgS']:.0f}")
    print()

    print("Done.")


if __name__ == "__main__":
    run_benchmark()
