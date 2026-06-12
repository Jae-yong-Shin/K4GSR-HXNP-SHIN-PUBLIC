"""Phase-2 pre-work: measure WHERE the GPU-run CPU continuation time goes.

Wraps the continuation sub-functions (_applySSAHybrid, applyKBMC,
_applyHybridFresnel, _hybridFF1D is internal so measured via its callers) with
accumulating timers, runs mcRayTraceGPU at 1M rays a few times, and reports
the per-stage breakdown. Also micro-benchmarks the Float32->Float64 buffer
conversion. Read-only profiling: no engine behavior change (wrappers call the
originals).
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
DEV_HTML = os.path.join(WORKTREE, "virtual_beamline_nanoprobe_V4_38.html")

JS_INSTRUMENT = """() => {
  window._prof = { ssa: 0, kb: 0, fresnel: 0, calls: {} };
  function wrap(name) {
    var orig = window[name];
    if (typeof orig !== 'function') return;
    window['_orig_' + name] = orig;
    window[name] = function () {
      var t0 = performance.now();
      var r = orig.apply(this, arguments);
      var dt = performance.now() - t0;
      var key = name === 'applyKBMC' ? 'kb' :
                name === '_applySSAHybrid' ? 'ssa' : 'fresnel';
      window._prof[key] += dt;
      window._prof.calls[name] = (window._prof.calls[name] || 0) + 1;
      return r;
    };
  }
  wrap('_applySSAHybrid');
  wrap('applyKBMC');
  wrap('_applyHybridFresnel');
  return true;
}"""

JS_RUN = """async (nR) => {
  window._prof.ssa = 0; window._prof.kb = 0; window._prof.fresnel = 0;
  var td = pos('sample');
  var t0 = performance.now();
  var mc = await mcRayTraceGPU(td, nR);
  var total = performance.now() - t0;
  return {
    total: total,
    gpuMs: mc._gpu ? mc._gpu.gpuMs : null,
    contMs: mc._gpu ? mc._gpu.contMs : null,
    fallback: mc._gpu ? !!mc._gpu.fallback : null,
    reason: mc._gpu ? mc._gpu.reason || null : null,
    ssa: window._prof.ssa, kb: window._prof.kb, fresnel: window._prof.fresnel,
    nSurvived: mc.nSurvived
  };
}"""

JS_RUN_CPU = """(nR) => {
  window._prof.ssa = 0; window._prof.kb = 0; window._prof.fresnel = 0;
  var td = pos('sample');
  var t0 = performance.now();
  var mc = mcRayTrace(td, nR);
  var total = performance.now() - t0;
  return { total: total,
    ssa: window._prof.ssa, kb: window._prof.kb, fresnel: window._prof.fresnel,
    nSurvived: mc.nSurvived };
}"""

JS_CONVERT_BENCH = """(nR) => {
  var f32 = new Float32Array(nR * 8);
  for (var i = 0; i < f32.length; i++) f32[i] = i * 1e-7;
  var t0 = performance.now();
  var f64 = new Float64Array(f32);
  var t1 = performance.now();
  var s = 0; for (var j = 0; j < 8; j++) s += f64[j];
  return { convertMs: t1 - t0, s: s };
}"""


def main():
    n = 1000000
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--enable-unsafe-webgpu", "--enable-features=Vulkan",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling"])
        page = browser.new_page()
        page.goto("file:///" + DEV_HTML.replace("\\", "/"))
        page.wait_for_function(
            "typeof mcRayTraceGPU === 'function' && typeof pos === 'function'",
            timeout=60000)
        page.evaluate("(E) => { setTargetEnergy(E); "
                      "if (typeof defaultSourceBW==='function') "
                      "state.sourceBW_eV = defaultSourceBW(state.energy); }", 10.0)
        page.evaluate(JS_INSTRUMENT)

        conv = page.evaluate(JS_CONVERT_BENCH, n)
        print("Float32->Float64 convert (1M x 8): %.1f ms" % conv["convertMs"])

        print("\nGPU 1M runs (kernel+readback = gpuMs; continuation = contMs):")
        rows = []
        for i in range(5):
            r = page.evaluate(JS_RUN, n)
            if r["fallback"]:
                print("FALLBACK: %s" % r["reason"])
                return 1
            rest = r["contMs"] - r["ssa"] - r["kb"] - r["fresnel"]
            rows.append(r)
            print(" run %d: total %6.0f | gpu(kernel+rb) %5.0f | cont %5.0f "
                  "= ssa %5.1f + kb %5.1f + fresnel %5.1f + loop/stats/convert %6.1f"
                  % (i, r["total"], r["gpuMs"], r["contMs"],
                     r["ssa"], r["kb"], r["fresnel"], rest))

        print("\nCPU 1M run (same wrappers):")
        for i in range(2):
            r = page.evaluate(JS_RUN_CPU, n)
            rest = r["total"] - r["ssa"] - r["kb"] - r["fresnel"]
            print(" run %d: total %6.0f = ssa %5.1f + kb %5.1f + fresnel %5.1f "
                  "+ source/elements/stats %6.1f" % (i, r["total"], r["ssa"],
                                                     r["kb"], r["fresnel"], rest))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
