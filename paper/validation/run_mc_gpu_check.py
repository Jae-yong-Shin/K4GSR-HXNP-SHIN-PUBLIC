"""A1 (Phase-1) validation: WebGPU MC ray-trace vs CPU MC ray-trace.

Loads the DEV html (virtual_beamline_nanoprobe_V4_38.html) via file:// with
Playwright chromium (headed, --enable-unsafe-webgpu) and compares the CPU
engine (mcRayTrace) against the opt-in WebGPU engine (mcRayTraceGPU) at the
sample plane.

Modes
-----
  python run_mc_gpu_check.py --baseline
      CPU-only capture (run BEFORE the mcRayTrace refactor to freeze a true
      pre-refactor reference). Writes data/mc_gpu_cpu_baseline_pre_refactor.json.

  python run_mc_gpu_check.py
      Full check at energies {5, 10, 20} keV, production settings
      (setTargetEnergy -> harmonic/gap/DCM sync + documented defaultSourceBW):
        * KB-conic f32 precision gate (phase 2): GPU pole-frame conic vs CPU
          f64 _kbConicAngle on identical inputs, RMS sample-plane position
          error < 1 nm per mirror (vs the ~50 nm focal spot)
        * CPU vs GPU at 80k rays x N80 repeats (task-spec comparison)
        * CPU vs GPU at 1M rays x N1M repeats (high-statistics gate)
        * element-level T_cum parity on the 1M means (<=2%)
        * GPU-1M vs GPU-80k consistency
        * GPU 4M-ray demo gate (completes + sigma/flux consistent with 1M;
          tol 6 % for sigma because the engine's sigma estimator is
          N-dependent — the CPU itself shifts -6..-9 % from 80k to 1M)
        * full-mode assertion: sample-plane GPU runs must use the phase-2
          GPU-resident chain (mode 'full'), not the hybrid fallback
        * post-refactor CPU vs frozen pre-refactor CPU baseline
        * wall-clock + per-stage timing breakdown (phase-2 stages)
      Writes data/mc_gpu_check_results.json. Exit 0=PASS, 1=FAIL, 2=env.

STATISTICAL GATING. GPU/CPU agreement is statistical (counter-based PCG RNG
on the GPU vs Math.random on the CPU), and the sample-plane sigma is a
heavy-tailed second moment (diffraction tails): measured per-run scatter at
80k rays is ~8-11% for sigma/FWHM (see the frozen baseline JSON). A raw 2%
gate on an 80k single run would therefore fail on noise alone. Each
comparison below is made on repeat-run means and PASSES if
    |dev(meanGPU, meanCPU)| <= tol                            (true deviation)
or |dev| <= Z_STAT * sigma_diff                               (consistent with
                                                              zero at the
                                                              available stats)
with sigma_diff = sqrt(sd_a^2/n_a + sd_b^2/n_b) and Z_STAT = 2.5. At 1M rays
x N1M repeats sigma_diff shrinks to <1% for sigma so the tol term dominates;
both the deviation and its statistical error are reported for every gate.
"""

import argparse
import json
import os
import statistics
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
DEV_HTML = os.path.join(WORKTREE, "virtual_beamline_nanoprobe_V4_38.html")
DATA_DIR = os.path.join(HERE, "data")
BASELINE_JSON = os.path.join(DATA_DIR, "mc_gpu_cpu_baseline_pre_refactor.json")
RESULTS_JSON = os.path.join(DATA_DIR, "mc_gpu_check_results.json")

ENERGIES = [5.0, 10.0, 20.0]
N_RAYS = 80000          # task-spec comparison count
N_RAYS_BIG = 1000000    # high-statistics comparison + "must complete" run
N_RAYS_4M = 4000000     # phase-2 large-N demo gate
N80 = 10                # repeats per side at 80k
N1M = 12                # repeats per side at 1M
N4M = 3                 # GPU repeats at 4M

TOL_SIGMA = 0.02        # sigma + flux-ratio tolerance
TOL_FWHM = 0.03         # FWHM tolerance
TOL_TCUM = 0.02         # element-level T_cum parity
TOL_4M_SIG = 0.06       # 4M-vs-1M sigma (N-dependent estimator; see docstring)
CONIC_RMS_NM = 1.0      # KB conic precision gate (RMS sample-plane error, nm)
Z_STAT = 2.5            # statistical-consistency fallback (see module docstring)

METRICS = ["sigH", "sigV", "fwhmH", "fwhmV", "fluxRatio"]

JS_SET_ENERGY = """(E) => {
  setTargetEnergy(E);
  try { autoStripeForEnergy(state.energy); } catch (e) {}
  // setTargetEnergy assigns state.energy BEFORE updateEnergy, so the
  // energyChanged guard never fires through this path and sourceBW_eV stays
  // unset. Apply the documented production default explicitly
  // (docs/knowledge/02_physics_overview.md section 2.6.1).
  if (typeof defaultSourceBW === 'function') {
    state.sourceBW_eV = defaultSourceBW(state.energy);
  }
  return {
    energy: state.energy, gap: state.gap, harmonic: state.harmonic,
    crystal: state.crystal, sourceBW_eV: state.sourceBW_eV,
    dcmTheta: (typeof MOTORS !== 'undefined' && MOTORS.dcm && MOTORS.dcm.theta)
      ? MOTORS.dcm.theta.value : null
  };
}"""

JS_PICK = """
  function _pick(mc, ms) {
    return {
      ms: ms,
      gpu: mc._gpu || null,
      sigH: mc.sigH, sigV: mc.sigV,
      fwhmH: mc.fwhmH, fwhmV: mc.fwhmV,
      fluxRatio: mc.wSumFocused / mc.nTotal,
      nSurvived: mc.nSurvived, nTotal: mc.nTotal,
      nFocused: mc.nBeams ? mc.nBeams.focused : null,
      elementTrace: (mc.elementTrace || []).map(function (e) {
        return { id: e.id, dist: e.dist, T_cum: e.T_cum, sigH: e.sigH, sigV: e.sigV };
      })
    };
  }
"""

JS_CONIC = "async (n) => await _mcGpuConicTest(n)"

STAGE_KEYS = ["p1", "wf1", "p2", "wf2", "p3", "host3", "p4", "assemble", "total"]

JS_CPU_RUN = "(nR) => {" + JS_PICK + """
  var td = pos('sample');
  var t0 = performance.now();
  var mc = mcRayTrace(td, nR);
  return _pick(mc, performance.now() - t0);
}"""

JS_GPU_RUN = "async (nR) => {" + JS_PICK + """
  var td = pos('sample');
  var t0 = performance.now();
  var mc = await mcRayTraceGPU(td, nR);
  return _pick(mc, performance.now() - t0);
}"""


def mean(vals):
    return sum(vals) / len(vals)


def rel_dev(a, b):
    if b == 0:
        return 0.0 if a == 0 else float("inf")
    return (a - b) / b


def launch_page(p, need_gpu, html=None):
    # The backgrounding flags matter: occluded/backgrounded windows throttle
    # the WebGPU mapAsync polling (observed: 0.5-3.5 s stalls with growing
    # backoff on an otherwise ~5 ms dispatch).
    args = ["--enable-unsafe-webgpu", "--enable-features=Vulkan",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling"]
    browser = p.chromium.launch(headless=not need_gpu, args=args)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///" + (html or DEV_HTML).replace("\\", "/"))
    page.wait_for_function(
        "typeof mcRayTrace === 'function' && typeof setTargetEnergy === 'function'"
        " && typeof pos === 'function'",
        timeout=60000,
    )
    return browser, page, errors


def probe_gpu(page):
    return page.evaluate(
        """async () => {
          if (typeof detectWebGPU !== 'function') return { supported: false, error: 'detectWebGPU missing' };
          var r = await detectWebGPU();
          return { supported: r.supported, adapter: r.adapter_info, error: r.error };
        }"""
    )


def run_repeats(page, js, n_rays, reps, label, verbose=True, expect_full=False):
    out = []
    for i in range(reps):
        r = page.evaluate(js, n_rays)
        if r.get("gpu") and r["gpu"].get("fallback"):
            raise RuntimeError("GPU run fell back to CPU: " + str(r["gpu"].get("reason")))
        if expect_full and (not r.get("gpu") or r["gpu"].get("mode") != "full"):
            raise RuntimeError(
                "sample-plane GPU run did not use the phase-2 full chain: mode=%s fullFallback=%s"
                % (r.get("gpu", {}).get("mode"), r.get("gpu", {}).get("fullFallback")))
        out.append(r)
        if verbose:
            print("    %s %2d/%d: %6.0f ms  sigH=%8.3f sigV=%8.3f fwhmH=%7.2f "
                  "fwhmV=%7.2f [nm] flux=%.4e" % (
                      label, i + 1, reps, r["ms"], r["sigH"] * 1e9, r["sigV"] * 1e9,
                      r["fwhmH"] * 1e9, r["fwhmV"] * 1e9, r["fluxRatio"]))
    return out


def summarize(runs):
    s = {}
    for m in METRICS:
        vals = [r[m] for r in runs]
        s[m] = {"mean": mean(vals),
                "sd": statistics.stdev(vals) if len(vals) > 1 else 0.0,
                "n": len(vals)}
    s["ms"] = {"mean": mean([r["ms"] for r in runs]),
               "min": min(r["ms"] for r in runs)}
    return s


def do_baseline(html=None, reps=20):
    with sync_playwright() as p:
        browser, page, errors = launch_page(p, need_gpu=False, html=html)
        print("[baseline] CPU-only pre-refactor capture, %d rays x %d (html=%s)"
              % (N_RAYS, reps, html or DEV_HTML))
        res = {}
        for E in ENERGIES:
            info = page.evaluate(JS_SET_ENERGY, E)
            print("  E=%.1f keV (gap=%.2f mm, n=%d, srcBW=%.1f eV)"
                  % (E, info["gap"], info["harmonic"], info["sourceBW_eV"]))
            runs = run_repeats(page, JS_CPU_RUN, N_RAYS, reps, "CPU")
            res["%g" % E] = {"settings": info, "runs": runs, "summary": summarize(runs)}
        browser.close()
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {"mode": "cpu_baseline_pre_refactor", "nRays": N_RAYS, "nRep": reps,
               "html": html or DEV_HTML,
               "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "results": res,
               "pageErrors": errors}
    with open(BASELINE_JSON, "w") as f:
        json.dump(payload, f, indent=1)
    print("[baseline] wrote %s" % BASELINE_JSON)
    return 0


class Gate(object):
    def __init__(self):
        self.fails = []
        self.rows = []

    def check(self, name, a_mean, a_sd, a_n, b_mean, b_sd, b_n, tol):
        """a = GPU/test side, b = CPU/reference side."""
        dev = rel_dev(a_mean, b_mean)
        sig = 0.0
        if b_mean != 0:
            sig = ((a_sd ** 2 / max(a_n, 1)) + (b_sd ** 2 / max(b_n, 1))) ** 0.5 / abs(b_mean)
        within_tol = abs(dev) <= tol
        within_stat = sig > 0 and abs(dev) <= Z_STAT * sig
        ok = within_tol or within_stat
        verdict = "PASS" if within_tol else ("PASS(stat)" if within_stat else "FAIL")
        print("      %-34s dev=%+7.2f %%  (tol %.0f %%, stat-sd %.2f %%)  %s"
              % (name, dev * 100, tol * 100, sig * 100, verdict))
        row = {"name": name, "dev": dev, "tol": tol, "stat_sd": sig, "verdict": verdict}
        self.rows.append(row)
        if not ok:
            self.fails.append("%s dev=%+.2f%% (tol %.0f%%, stat-sd %.2f%%)"
                              % (name, dev * 100, tol * 100, sig * 100))
        return ok


def do_full():
    gate = Gate()
    report = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
              "nRays": N_RAYS, "nRaysBig": N_RAYS_BIG, "nRays4M": N_RAYS_4M,
              "n80": N80, "n1M": N1M, "n4M": N4M,
              "zStat": Z_STAT,
              "tolerances": {"sigma": TOL_SIGMA, "fwhm": TOL_FWHM, "tcum": TOL_TCUM,
                             "sig4M": TOL_4M_SIG, "conic_rms_nm": CONIC_RMS_NM},
              "energies": {}}

    with sync_playwright() as p:
        browser, page, errors = launch_page(p, need_gpu=True)
        gpu = probe_gpu(page)
        print("[gpu] supported=%s adapter=%s error=%s"
              % (gpu.get("supported"), gpu.get("adapter"), gpu.get("error")))
        report["adapter"] = gpu
        if not gpu.get("supported"):
            print("[gpu] no WebGPU adapter available -- cannot validate GPU path")
            browser.close()
            return 2

        # --- phase-2 KB-conic precision gate (energy-independent geometry) ---
        page.evaluate(JS_SET_ENERGY, 10.0)
        conic = page.evaluate(JS_CONIC, 8192)
        report["conic"] = conic
        print("[conic] %s" % json.dumps(conic))
        per = conic.get("perMirror") or {}
        if not per:
            gate.fails.append("conic precision gate did not run: %s" % json.dumps(conic))
        for mid in sorted(per.keys()):
            rms = per[mid]["rms_nm"]
            ok = rms < CONIC_RMS_NM
            verdict = "PASS" if ok else "FAIL"
            print("      %-34s rms=%6.3f nm (max %6.3f nm, gate < %.1f nm)  %s"
                  % ("conic precision [%s]" % mid, rms, per[mid]["max_nm"],
                     CONIC_RMS_NM, verdict))
            gate.rows.append({"name": "conic precision [%s]" % mid,
                              "rms_nm": rms, "max_nm": per[mid]["max_nm"],
                              "tol_nm": CONIC_RMS_NM, "verdict": verdict})
            if not ok:
                gate.fails.append("conic RMS %s = %.3f nm >= %.1f nm"
                                  % (mid, rms, CONIC_RMS_NM))

        for E in ENERGIES:
            key = "%g" % E
            info = page.evaluate(JS_SET_ENERGY, E)
            print("\n=== E = %.1f keV (gap=%.2f mm, n=%d, srcBW=%.1f eV) ==="
                  % (E, info["gap"], info["harmonic"], info["sourceBW_eV"]))
            erec = {"settings": info}

            print("  CPU 80k x %d:" % N80)
            cpu80 = run_repeats(page, JS_CPU_RUN, N_RAYS, N80, "CPU-80k")
            print("  GPU 80k x %d (run 1 includes pipeline warmup):" % N80)
            gpu80 = run_repeats(page, JS_GPU_RUN, N_RAYS, N80, "GPU-80k", expect_full=True)
            print("  CPU 1M x %d:" % N1M)
            cpu1m = run_repeats(page, JS_CPU_RUN, N_RAYS_BIG, N1M, "CPU-1M")
            print("  GPU 1M x %d:" % N1M)
            gpu1m = run_repeats(page, JS_GPU_RUN, N_RAYS_BIG, N1M, "GPU-1M", expect_full=True)
            print("  GPU 4M x %d (phase-2 demo gate):" % N4M)
            gpu4m = run_repeats(page, JS_GPU_RUN, N_RAYS_4M, N4M, "GPU-4M", expect_full=True)

            c80, g80 = summarize(cpu80), summarize(gpu80)
            c1m, g1m = summarize(cpu1m), summarize(gpu1m)
            g4m = summarize(gpu4m)
            erec["cpu80k"] = {"runs": cpu80, "summary": c80}
            erec["gpu80k"] = {"runs": gpu80, "summary": g80}
            erec["cpu1M"] = {"runs": cpu1m, "summary": c1m}
            erec["gpu1M"] = {"runs": gpu1m, "summary": g1m}
            erec["gpu4M"] = {"runs": gpu4m, "summary": g4m}

            print("  -- 80k means: GPU vs CPU (task-spec comparison) --")
            for m in METRICS:
                tol = TOL_FWHM if m.startswith("fwhm") else TOL_SIGMA
                gate.check("80k %s @%gkeV" % (m, E),
                           g80[m]["mean"], g80[m]["sd"], g80[m]["n"],
                           c80[m]["mean"], c80[m]["sd"], c80[m]["n"], tol)
            print("  -- 1M means: GPU vs CPU (high-statistics gate) --")
            for m in METRICS:
                tol = TOL_FWHM if m.startswith("fwhm") else TOL_SIGMA
                gate.check("1M %s @%gkeV" % (m, E),
                           g1m[m]["mean"], g1m[m]["sd"], g1m[m]["n"],
                           c1m[m]["mean"], c1m[m]["sd"], c1m[m]["n"], tol)
            # 1M-vs-80k consistency. The engine's sample-plane sigma estimator
            # is intrinsically N-dependent (heavy diffraction tails + the
            # hybrid's footprint-extent dependence): the REFERENCE CPU engine
            # itself shifts by -5..-9 % between 80k and 1M. The correct
            # N-invariant is therefore the DOUBLE RATIO
            # (GPU 1M/80k) / (CPU 1M/80k): the GPU must show the same
            # N-dependence as the CPU. Raw shifts are reported alongside.
            print("  -- 1M-vs-80k consistency (double ratio GPU shift vs CPU shift) --")
            shifts = {}
            for m in ["sigH", "sigV", "fluxRatio"]:
                gshift = g1m[m]["mean"] / g80[m]["mean"]
                cshift = c1m[m]["mean"] / c80[m]["mean"]
                def relsem(s):
                    return s[m]["sd"] / (abs(s[m]["mean"]) * (s[m]["n"] ** 0.5))
                gsd = gshift * (relsem(g1m) ** 2 + relsem(g80) ** 2) ** 0.5
                csd = cshift * (relsem(c1m) ** 2 + relsem(c80) ** 2) ** 0.5
                shifts[m] = {"gpu_1M_over_80k": gshift - 1, "cpu_1M_over_80k": cshift - 1}
                print("        raw N-shift %s: GPU %+.2f %%, CPU %+.2f %%"
                      % (m, (gshift - 1) * 100, (cshift - 1) * 100))
                gate.check("Nshift-ratio %s @%gkeV" % (m, E),
                           gshift, gsd, 1, cshift, csd, 1, TOL_SIGMA)
            erec["nShift"] = shifts

            # Phase-2 4M demo gate: must complete (run_repeats raised
            # otherwise) + sigma/flux consistent with GPU-1M. Sigma tolerance
            # is 6 % because the engine's sample-plane sigma estimator is
            # N-dependent (heavy tails + hybrid footprint extent; the CPU
            # itself drifts -6..-9 % from 80k to 1M); the raw 1M->4M shift is
            # recorded in the JSON.
            print("  -- 4M demo gate (GPU 4M vs GPU 1M) --")
            for m in ["sigH", "sigV"]:
                gate.check("4M %s @%gkeV" % (m, E),
                           g4m[m]["mean"], g4m[m]["sd"], g4m[m]["n"],
                           g1m[m]["mean"], g1m[m]["sd"], g1m[m]["n"], TOL_4M_SIG)
            gate.check("4M fluxRatio @%gkeV" % E,
                       g4m["fluxRatio"]["mean"], g4m["fluxRatio"]["sd"], g4m["fluxRatio"]["n"],
                       g1m["fluxRatio"]["mean"], g1m["fluxRatio"]["sd"], g1m["fluxRatio"]["n"],
                       TOL_SIGMA)

            # Element-level T_cum parity on the 1M means.
            print("  -- per-element T_cum parity (1M means) --")
            ids = [e["id"] for e in cpu1m[0]["elementTrace"]]

            def tvals(runs, eid):
                out = []
                for r in runs:
                    for e in r["elementTrace"]:
                        if e["id"] == eid:
                            out.append(e["T_cum"])
                            break
                return out
            elem_par = {}
            for eid in ids:
                cv, gv = tvals(cpu1m, eid), tvals(gpu1m, eid)
                if not gv:
                    gate.fails.append("element %s missing in GPU trace" % eid)
                    continue
                gate.check("T_cum[%s] @%gkeV" % (eid, E),
                           mean(gv), statistics.stdev(gv) if len(gv) > 1 else 0.0, len(gv),
                           mean(cv), statistics.stdev(cv) if len(cv) > 1 else 0.0, len(cv),
                           TOL_TCUM)
                elem_par[eid] = {"cpu": mean(cv), "gpu": mean(gv),
                                 "dev": rel_dev(mean(gv), mean(cv))}
            erec["elementParity"] = elem_par

            erec["timing_ms"] = {
                "cpu80k_mean": c80["ms"]["mean"],
                "gpu80k_mean": g80["ms"]["mean"],
                "gpu80k_warm": mean([r["ms"] for r in gpu80[1:]]) if len(gpu80) > 1 else gpu80[0]["ms"],
                "cpu1M_mean": c1m["ms"]["mean"],
                "gpu1M_mean": g1m["ms"]["mean"],
                "gpu1M_passes_mean": mean([r["gpu"]["gpuMs"] for r in gpu1m if r.get("gpu")]),
                "gpu1M_host_mean": mean([r["gpu"]["contMs"] for r in gpu1m if r.get("gpu")]),
                "gpu4M_mean": g4m["ms"]["mean"],
            }
            # per-stage breakdown of the phase-2 chain (GPU-1M runs, warm:
            # skip run 0 which can include shader-module compilation)
            stage_rows = [r["gpu"]["stages"] for r in gpu1m[1:]
                          if r.get("gpu") and r["gpu"].get("stages")]
            if stage_rows:
                erec["timing_ms"]["stages_1M_mean"] = dict(
                    (k, mean([s.get(k, 0.0) for s in stage_rows])) for k in STAGE_KEYS)
            t = erec["timing_ms"]
            print("  timing: CPU-80k %.0f ms | GPU-80k warm %.0f ms | CPU-1M %.0f ms | "
                  "GPU-1M %.0f ms (passes %.0f + host %.0f) | GPU-4M %.0f ms"
                  % (t["cpu80k_mean"], t["gpu80k_warm"], t["cpu1M_mean"],
                     t["gpu1M_mean"], t["gpu1M_passes_mean"], t["gpu1M_host_mean"],
                     t["gpu4M_mean"]))
            if stage_rows:
                s = t["stages_1M_mean"]
                print("  stages 1M (warm mean): " + "  ".join(
                    "%s %.1f" % (k, s[k]) for k in STAGE_KEYS))
            report["energies"][key] = erec

        browser.close()

    # Post-refactor CPU vs frozen pre-refactor CPU baseline.
    if os.path.exists(BASELINE_JSON):
        with open(BASELINE_JSON) as f:
            base = json.load(f)
        print("\n=== post-refactor CPU vs pre-refactor CPU baseline (80k means) ===")
        for key, erec in report["energies"].items():
            b = base["results"].get(key)
            if not b:
                continue
            for m in METRICS:
                tol = TOL_FWHM if m.startswith("fwhm") else TOL_SIGMA
                gate.check("refactor %s @%skeV" % (m, key),
                           erec["cpu80k"]["summary"][m]["mean"],
                           erec["cpu80k"]["summary"][m]["sd"], N80,
                           b["summary"][m]["mean"], b["summary"][m]["sd"],
                           b["summary"][m]["n"], tol)
    else:
        print("[warn] no pre-refactor baseline found at %s" % BASELINE_JSON)

    report["pageErrors"] = errors
    report["gates"] = gate.rows
    report["fails"] = gate.fails
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RESULTS_JSON, "w") as f:
        json.dump(report, f, indent=1)
    print("\nwrote %s" % RESULTS_JSON)
    n_stat = len([r for r in gate.rows if r["verdict"] == "PASS(stat)"])
    print("gates: %d total, %d PASS, %d PASS(stat), %d FAIL"
          % (len(gate.rows),
             len([r for r in gate.rows if r["verdict"] == "PASS"]),
             n_stat, len(gate.fails)))
    if gate.fails:
        print("\nRESULT: FAIL (%d)" % len(gate.fails))
        for x in gate.fails:
            print("  - " + x)
        return 1
    print("\nRESULT: PASS")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true",
                    help="CPU-only pre-refactor baseline capture")
    ap.add_argument("--html", default=None,
                    help="override dev html (e.g. a detached pre-refactor worktree)")
    a = ap.parse_args()
    if not os.path.exists(a.html or DEV_HTML):
        print("dev html not found: %s" % (a.html or DEV_HTML))
        return 2
    return do_baseline(a.html) if a.baseline else do_full()


if __name__ == "__main__":
    sys.exit(main())
