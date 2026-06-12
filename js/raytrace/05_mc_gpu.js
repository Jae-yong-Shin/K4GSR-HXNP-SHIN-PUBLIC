'use strict';
// ===== raytrace/05_mc_gpu.js — opt-in WebGPU MC ray-trace (Phase-1 A1 + Phase-2) =====
// @module raytrace/05_mc_gpu
// @exports mcRayTraceGPU, setMCEngine, _mcGpuSyncHook, _mcGpuStatus, _mcGpuConicTest
//
// WebGPU acceleration of mcRayTrace. Physics identical to the CPU engine —
// same formulas, same tables, NO fudge factors.
//
// PHASE 2 (2026-06-12): the CPU continuation of phase 1 (SSA hybrid + KB slit
// + KB conic + Fresnel hybrid + per-ray readback + histogram/statistics,
// ~950 ms of the ~1000 ms end-to-end at 1M rays) is collapsed into a fully
// GPU-RESIDENT multi-pass chain ("full mode", sample-plane target):
//
//   pass 1  (mc_trace)   source sampling -> WB slit -> M1 -> DCM -> M2 ->
//                        ... -> SSA aperture clip. Per-element snapshot
//                        partials + SSA footprint stats (alive count via
//                        atomics, min/max via ordered-u32 atomics, sum-E via
//                        workgroup reduction).
//   pass 1b (foot_hist)  unweighted SSA footprint histograms (u32 atomics,
//                        EXACT integer parity with the CPU histogram).
//   [CPU]                collective wavefront physics: the engine's OWN
//                        _hybridProfile1D (FFT Fresnel propagation, pure code
//                        motion out of _hybridFF1D) + _cdfBuild produce the
//                        SSA H/V angular-kick CDF tables -> uploaded.
//   pass 2  (mc_pass2)   per-ray inverse-CDF SSA kicks (same distributions,
//                        in-shader sampling), then the remaining element
//                        chain: KB slit clip + sinc^2 rejection-sampled kicks
//                        (sincSqRand port), KB-V/KB-H (footprint/body
//                        boundary, reflectivity cull, EXACT ellipsoid conic in
//                        a pole-frame small-quantity formulation — see below),
//                        final drift to the sample plane. Element snapshots +
//                        KB-footprint stats for the Fresnel hybrid.
//   pass 2b (foot_hist)  unweighted KB-footprint histograms (back-propagated
//                        mirror coordinates, u32 atomics).
//   [CPU]                _hybridProfile1D + _cdfBuild for KB-V/KB-H Fresnel
//                        kick distributions -> uploaded.
//   pass 3  (mc_pass3)   per-ray Fresnel-hybrid application (geometric-kick
//                        removal + diffraction kick + re-propagation,
//                        line-for-line port of _applyHybridFresnel), then all
//                        moment sums (weighted/unweighted, all-alive +
//                        focused-only), tag counts, weight min/max.
//   pass 4  (final_hist) weighted histograms (2D grid + marginals + fine
//                        sample-plane marginals) via fixed-point u32 atomics
//                        (scale chosen so nR * scale < 2^31: no overflow,
//                        deterministic).
//
//   Downloads are SMALL (atomics block ~3 KB, snapshot/moment partials ~1 MB
//   at 1M rays, final histograms ~43 KB) — the 32 MB per-ray readback and ALL
//   per-ray CPU loops of phase 1 are gone. The result object is assembled on
//   the host with the same statistics formulas (raw-moment form of the same
//   algebra) and the same FOV/fine-histogram decision logic as
//   _mcTraceFromRays. _aliveRays (per-ray dump, unused by sample-plane
//   consumers) is null in full-mode results — documented limitation.
//
// KB ELLIPSOID CONIC IN F32 (phase-1 limitation lifted): the direct CPU
// formulation evaluates the intersection quadratic with the ray anchored at
// the source (91.7 m away), so AA/BB/CC emerge from 3-5-decade cancellations
// that f32 cannot survive. The GPU uses an algebraically EXACT regrouping
// (no approximation):
//   * the ray anchor is shifted to the mirror-pole plane: P' = P + V*pf,
//     where PY' = srcPos*sK + pf*eY and PZ' = srcPos*cK + pf*eZ with
//     eY = (vzc-1)*cK + ang*sK, eZ = -(vzc-1)*sK + ang*cK,
//     (vzc-1) = -ang^2/(1+vzc) — all SMALL quantities, identities exact;
//   * AA is evaluated as A0*VY^2 + B1*VY*h + cc2*h^2 with h = VZ + sK*VY
//     (computed in small-quantity form) and A0 = cc1 + cc2*sK^2 - cc4*sK,
//     B1 = cc4 - 2*cc2*sK precomputed in f64 on the host (the 2-decade
//     cancellation cc1+cc2 s^2 ~ cc4 s happens ONCE in f64, not per ray);
//   * the quadratic roots use the numerically stable q-form
//     (qq = -(BB + sign(BB)*sqrt(disc))/2; t = qq/AA and CC/qq), with the
//     same pole-nearest |IY| selection as the CPU.
// GATING: full mode runs a DEDICATED precision self-test on first use per
// conic configuration (window._mcGpuConicTest): GPU conic vs the CPU f64
// _kbConicAngle on identical f32 inputs spanning the full mirror aperture;
// the verdict (RMS sample-plane position error < 1 nm — well below the
// ~50 nm focal spot) is required, else the run falls back to phase-1 hybrid
// mode and reports the reason. The validation harness asserts the gate.
//
// HYBRID MODE (phase 1) is retained unchanged for td != sample plane and as
// the automatic fallback: GPU source->M2 segment, 32 MB readback,
// _mcTraceFromRays CPU continuation.
//
// RNG note: counter-based PCG-RXS-M-XS-32 per ray per pass (fresh seed per
// pass); CPU uses Math.random(). GPU vs CPU equivalence is STATISTICAL (same
// distributions), NOT bitwise. Validation: paper/validation/run_mc_gpu_check.py.
//
// Opt-in wiring unchanged: state.mcGpuEnabled (default false), _mcGpuSyncHook
// serves fingerprint-matched sample-plane results, mcRayTraceGPU(td, nR) is
// the explicit async API, automatic CPU fallback on unsupported configs.
//
// Coding rules (CLAUDE.md): ES5-strict (var/function only). WGSL assembled
// by string concatenation. No emoji / surrogate chars.

// ===========================================================================
// Tunables / constants
// ===========================================================================
var MG_WG_SIZE = 256;          // workgroup size (1D, one thread per ray)
var MG_RAY_STRIDE = 8;         // [x,y,vx,vy,vz,w,E_eV,kbTag] — must equal RS
var MG_TBL_N = 2701;           // optconst/psi table rows (3-30 keV, 10 eV)
var MG_OP_NOOP = 0, MG_OP_SLIT = 1, MG_OP_MIRROR = 2, MG_OP_DCM = 3, MG_OP_DCM_OFF = 4;
var MG_OP_SLIT_SINC = 5, MG_OP_KB = 6;
var MG_DESC_STRIDE = 32;       // f32 per element descriptor
var MG_MAX_ELEMS = 24;         // pass-1 prefix + pass-2 chain combined
var MG_CDF_SEG = 131072;       // per-segment CDF capacity (= FFT cap of _hybridProfile1D)
var MG_FOOT_BINS = 200;        // footprint histogram capacity (CPU: nBins <= 200)
var MG_ATOM_WORDS = 20 + 4 * MG_FOOT_BINS;  // counters/minmax + 4 footprint histograms
var MG_FINE_GRID = 201;        // fine sample-plane marginal bins (CPU GF)

// Default-off opt-in flag (restored from localStorage below).
if (typeof state !== 'undefined' && state && state.mcGpuEnabled === undefined) {
  state.mcGpuEnabled = false;
}

// ===========================================================================
// Module state: pipeline/buffer caches, result store, serialization queue
// ===========================================================================
var _mgCache = {
  device: null,
  module: null,
  pipelines: null,
  bgl: null,
  bufferKey: '',
  buffers: null,
  optconstWritten: false,
  psiCrystal: ''
};
var _mgStore = { key: '', result: null };
var _mgInFlightKey = null;
var _mgChain = Promise.resolve();      // serializes GPU runs (shared buffers)
var _mgLastError = null;
var _mgConicVerdicts = {};             // conic-params-JSON -> {ok, rms_nm, max_nm}

window._mcGpuStatus = function () {
  return {
    enabled: !!(typeof state !== 'undefined' && state && state.mcGpuEnabled),
    gpu: (window._GPU && window._GPU.supported) ? (window._GPU.adapter_info || true) : false,
    storedKey: _mgStore.key ? true : false,
    inFlight: _mgInFlightKey !== null,
    lastError: _mgLastError,
    conicVerdicts: _mgConicVerdicts
  };
};

// ===========================================================================
// Host-side preparation: gather ALL physics inputs the GPU segment needs,
// build element descriptors, and a fingerprint string. Mirrors the host-side
// math of mcRayTrace/applyMirrorMC/applyDCM_MC/applyKBMC exactly (f64).
// Returns { ok:false, reason } when the current configuration has no
// GPU-equivalent implementation -> caller falls back to CPU.
//
// Output layout:
//   prep.descs    pass-1 prefix EXCLUDING any non-WB slit (phase-1 hybrid
//                 prefix — unchanged behavior for hybrid mode)
//   prep.ssaDesc  the first non-WB slit as a GPU descriptor (full mode only)
//   prep.p2Descs  every element after it up to td (full mode only)
//   prep.fullOk   true when the whole chain to td is GPU-expressible
// ===========================================================================
function _mgPrep(td, nR) {
  if (typeof state === 'undefined' || typeof CD === 'undefined' ||
      typeof pos !== 'function' || typeof photonSrc !== 'function') {
    return { ok: false, reason: 'engine globals missing' };
  }
  // Diagnostic flags force the reference CPU path (S4-comparison conditions).
  if ((typeof _noMirrorReflectivity !== 'undefined' && _noMirrorReflectivity) ||
      (typeof _noSSADiffraction !== 'undefined' && _noSSADiffraction)) {
    return { ok: false, reason: 'diagnostic flags active' };
  }
  var E = state.energy;
  var ps = photonSrc(E);

  // Same component list construction as mcRayTrace.
  var sorted = CD.map(function (c) { return { id: c.id, tp: c.tp, name: c.name, p: pos(c.id) }; })
    .filter(function (c) { return c.p > 0 && c.p <= td; })
    .sort(function (a, b) { return a.p - b.p; });

  // WB / per-ray-energy source setup (same formulas as mcRayTrace).
  var dcmTh = (typeof MOTORS !== 'undefined' && MOTORS.dcm && MOTORS.dcm.theta) ? MOTORS.dcm.theta.value : null;
  var isWB = (typeof _forceNonWB === 'undefined' || !_forceNonWB) &&
             (td < (pos('dcm') || 32) || (dcmTh !== null && Math.abs(dcmTh) < 0.1));
  var wbHalfAngH = 0, wbHalfAngV = 0;
  if (isWB) {
    var wbDist = pos('wbslit') || 27.8;
    wbHalfAngH = (state.wbH * 0.5e-3 + 3 * ps.Sx) / wbDist;
    wbHalfAngV = (state.wbV * 0.5e-3 + 3 * ps.Sy) / wbDist;
  }
  var E_eV_center = E * 1000;
  var srcBW_eV = (typeof state.sourceBW_eV === 'number') ? state.sourceBW_eV : 1.0;
  var srcBW = (srcBW_eV > 0 && E_eV_center > 0) ? srcBW_eV / E_eV_center : 0;
  var und_n = state.harmonic || 1;
  var und_E1 = (typeof calcE1 === 'function' && typeof calcK === 'function' && typeof calcB0 === 'function')
    ? calcE1(calcK(calcB0(state.gap))) : 0;
  var und_Epeak = und_n * und_E1;

  // GPU prefix: stop BEFORE the first element that needs the collective
  // physics (SSA / KB slit diffraction, KB conic) — this is the phase-1
  // hybrid prefix. The full-mode extension below continues past it.
  var descs = [];
  var gpuElems = [];
  var gpuEndP = 0;
  var i, c, splitIdx = sorted.length;
  for (i = 0; i < sorted.length; i++) {
    c = sorted[i];
    if (c.tp === 'kbv' || c.tp === 'kbh') { splitIdx = i; break; }
    if (c.tp === 'slit' && c.id !== 'wbslit') { splitIdx = i; break; }
    var d = _mgElemDesc(c, E);
    if (!d.ok) return { ok: false, reason: 'element ' + c.id + ': ' + d.reason };
    descs.push(d.desc);
    gpuElems.push(c);
    gpuEndP = c.p;
  }

  var prep = {
    ok: true,
    td: td, nR: nR,
    E: E, ps: ps,
    isWB: isWB,
    wbHalfAngH: wbHalfAngH, wbHalfAngV: wbHalfAngV,
    E_eV_center: E_eV_center, srcBW: srcBW,
    und_Epeak: und_Epeak,
    eSpread: (typeof E_SPREAD !== 'undefined') ? E_SPREAD : 0,
    nPeriods: (typeof N_PERIODS !== 'undefined') ? N_PERIODS : 123,
    crystal: state.crystal,
    descs: descs, gpuElems: gpuElems, gpuEndP: gpuEndP,
    // full-mode extension (filled below when expressible)
    fullOk: false, fullReason: '',
    ssaDesc: null, ssaElem: null, ssaInfo: null,
    p2Descs: [], p2Elems: [], kbMeta: {},
    hasKB: sorted.some(function (cc) { return cc.tp === 'kbv' || cc.tp === 'kbh'; })
  };

  // ---- full-mode chain (sample plane): express the REST of the chain ----
  var full = { ok: true, reason: '' };
  var rest = sorted.slice(splitIdx);
  var p2Descs = [], p2Elems = [], ssaDesc = null, ssaElem = null, ssaInfo = null;
  var kbMeta = {};
  var lam_m_center = HC / E * 1e-10;   // _mcTraceFromRays: slit diffraction at center E
  for (i = 0; i < rest.length && full.ok; i++) {
    c = rest[i];
    if (c.tp === 'slit') {
      var sd = _mgSlitDesc(c, lam_m_center);
      if (!sd.ok) { full = { ok: false, reason: 'slit ' + c.id + ': ' + sd.reason }; break; }
      if (i === 0 && c.id === 'ssa') {
        // first post-prefix element is the SSA: clip joins pass 1, hybrid
        // kicks are applied at the start of pass 2 (CPU order: clip -> kicks;
        // positions at the SSA plane are unaffected by the kicks).
        ssaDesc = sd.desc; ssaElem = c; ssaInfo = sd.info;
        continue;
      }
      if (c.id === 'ssa') {
        // ssa NOT first after the prefix (custom layout): the collective
        // hybrid would be misplaced in the pass-2 chain — not expressible.
        full = { ok: false, reason: 'ssa not first post-prefix element' };
        break;
      }
      p2Descs.push(sd.desc); p2Elems.push(c);
      continue;
    }
    if (c.tp === 'kbv' || c.tp === 'kbh') {
      var kd = _mgKbDesc(c, E);
      if (!kd.ok) { full = { ok: false, reason: 'kb ' + c.id + ': ' + kd.reason }; break; }
      p2Descs.push(kd.desc); p2Elems.push(c); kbMeta[c.id] = kd.meta;
      continue;
    }
    if (c.tp === 'hmirror' || c.tp === 'dcm') {
      var d2 = _mgElemDesc(c, E);
      if (!d2.ok) { full = { ok: false, reason: 'element ' + c.id + ': ' + d2.reason }; break; }
      p2Descs.push(d2.desc); p2Elems.push(c);
      continue;
    }
    // mask / atten / bpm / ic / sample / det: no interaction -> noop
    var dn = new Array(MG_DESC_STRIDE);
    for (var k0 = 0; k0 < MG_DESC_STRIDE; k0++) dn[k0] = 0;
    dn[0] = MG_OP_NOOP;
    p2Descs.push(dn); p2Elems.push(c);
  }
  var n1full = descs.length + (ssaDesc ? 1 : 0);
  if (full.ok && n1full + p2Descs.length > MG_MAX_ELEMS) {
    full = { ok: false, reason: 'too many GPU elements (' + (n1full + p2Descs.length) + ')' };
  }
  if (full.ok) {
    prep.fullOk = true;
    prep.ssaDesc = ssaDesc; prep.ssaElem = ssaElem; prep.ssaInfo = ssaInfo;
    prep.p2Descs = p2Descs; prep.p2Elems = p2Elems; prep.kbMeta = kbMeta;
  } else {
    prep.fullReason = full.reason;
  }
  if (descs.length > MG_MAX_ELEMS) {
    return { ok: false, reason: 'too many GPU elements (' + descs.length + ')' };
  }

  // Fill drift lengths (desc[1] = drift from previous plane) across the
  // CONCATENATED chain: prefix -> ssa -> pass-2 elements.
  var ld = 0;
  for (i = 0; i < descs.length; i++) { descs[i][1] = gpuElems[i].p - ld; ld = gpuElems[i].p; }
  if (prep.fullOk) {
    if (ssaDesc) { ssaDesc[1] = ssaElem.p - ld; ld = ssaElem.p; }
    for (i = 0; i < p2Descs.length; i++) { p2Descs[i][1] = p2Elems[i].p - ld; ld = p2Elems[i].p; }
    prep.finalDrift = td - ld;
    prep.fullEndP = ld;
  }

  prep.fingerprint = _mgFingerprintOf(prep);
  return prep;
}

// Slit descriptor for the pass-2 chain (ssa / kbslit / other non-WB slits).
// Mirrors the slit case of _mcTraceFromRays exactly (units differ per id).
function _mgSlitDesc(c, lam_m) {
  var d = new Array(MG_DESC_STRIDE);
  var k;
  for (k = 0; k < MG_DESC_STRIDE; k++) d[k] = 0;
  var hH, hV, cxO, cyO;
  if (c.id === 'wbslit') {
    hH = state.wbH * 0.5e-3; hV = state.wbV * 0.5e-3;
    cxO = (state.wbCX || 0) * 1e-3; cyO = (state.wbCY || 0) * 1e-3;
    d[0] = MG_OP_SLIT;            // WB slit: clip only (CPU: no kicks)
  } else if (c.id === 'kbslit') {
    hH = (state.kbslitH || 5000) * 0.5e-6; hV = (state.kbslitV || 5000) * 0.5e-6;
    cxO = (state.kbslitCX || 0) * 1e-6; cyO = (state.kbslitCY || 0) * 1e-6;
    d[0] = MG_OP_SLIT_SINC;
  } else {
    hH = state.ssaH * 0.5e-6; hV = state.ssaV * 0.5e-6;
    cxO = (state.ssaCX || 0) * 1e-6; cyO = (state.ssaCY || 0) * 1e-6;
    // ssa itself: clip op (hybrid kicks handled collectively); other ids:
    // CPU falls to the Fraunhofer sinc branch.
    d[0] = (c.id === 'ssa') ? MG_OP_SLIT : MG_OP_SLIT_SINC;
  }
  d[2] = hH; d[3] = hV; d[4] = cxO; d[5] = cyO;
  if (d[0] === MG_OP_SLIT_SINC) {
    d[6] = (hH > 1e-10) ? lam_m / (Math.PI * 2 * hH) : 0;   // dfH
    d[7] = (hV > 1e-10) ? lam_m / (Math.PI * 2 * hV) : 0;   // dfV
  }
  return { ok: true, desc: d, info: { hH: hH, hV: hV, cxO: cxO, cyO: cyO } };
}

// KB mirror descriptor (applyKBMC port). meta carries the f64 conic
// parameters for the precision self-test and the Fresnel-hybrid host math.
function _mgKbDesc(c, E) {
  var kbId = c.id;
  var sig = (typeof thermalSlopeError === 'function') ? thermalSlopeError(kbId, E) : 0;
  if (sig > 1e-12) return { ok: false, reason: 'thermal slope error active' };
  var pitch = mVal(kbId, 'pitch', 3.0);
  var roll = mVal(kbId, 'roll', 0) * 1e-3;
  var yaw = mVal(kbId, 'yaw', 0) * 1e-3;
  var tyOff = mVal(kbId, 'y', 0) * 1e-3, txOff = mVal(kbId, 'x', 0) * 1e-3;
  var zBeam = mVal(kbId, 'z', 0) * 1e-3;
  var tg = pitch * 1e-3, dP = (pitch - 3.0) * 1e-3;
  var isV = (kbId === 'kbv');
  var kbp = window.KB_PARAMS && window.KB_PARAMS[kbId];
  var kbLen = kbp ? kbp.len : 0.200, kbWid = kbp ? kbp.wid : 0.030;
  var kbThick = kbp ? kbp.thick : 0.050;
  var rough = kbp ? kbp.rough || 0 : 0;
  var sinTg = Math.sin(Math.abs(tg));
  var pDist = pos(kbId) - pos('ssa'), qDist = pos('sample') - pos(kbId);
  var F = (pDist > 0 && qDist > 0) ? pDist * qDist / (pDist + qDist) : 0.3;
  var cKB = Math.cos(Math.abs(tg)), _pqK = pDist + qDist;
  var useConic = (pDist > 0 && qDist > 0);
  var cc1 = sinTg * sinTg;
  var cc2 = useConic ? 1 - Math.pow(sinTg * (pDist - qDist) / _pqK, 2) : 1.0;
  var cc4 = useConic ? -2 * sinTg * cKB * (qDist - pDist) / _pqK : 0.0;
  var cc8 = useConic ? -4 * sinTg * pDist * qDist / _pqK : 0.0;
  var sMat = RH;
  if (typeof getStripeMaterial === 'function') {
    var st = getStripeMaterial(kbId);
    if (st && st.mat) sMat = st.mat;
  }
  var matIdx = (sMat.Z === 45) ? 0 : (sMat.Z === 78) ? 1 : (sMat.Z === 14) ? 2 : -1;
  if (matIdx < 0) return { ok: false, reason: 'coating Z=' + sMat.Z + ' not in DABAX tables' };
  if (Math.abs(F) < 1e-9) return { ok: false, reason: 'KB focal length ~0' };

  var d = new Array(MG_DESC_STRIDE);
  var k;
  for (k = 0; k < MG_DESC_STRIDE; k++) d[k] = 0;
  d[0] = MG_OP_KB;
  d[2] = isV ? 1 : 0;
  d[3] = kbWid * 0.5;              // halfWid
  d[4] = kbLen * 0.5;              // halfLen
  d[5] = kbThick;
  d[6] = tg;
  d[7] = sinTg;
  d[8] = -2 * tg;                  // passKick
  d[9] = 2 * dP;                   // twoDP
  d[10] = 2 * tg * roll + 2 * yaw; // crossKick
  d[11] = txOff;
  d[12] = tyOff;
  d[13] = zBeam;
  d[14] = matIdx * 2 * MG_TBL_N;   // matBase
  d[15] = rough;
  d[16] = useConic ? 1 : 0;
  d[17] = 1 / F;                   // invF (thin-lens fallback)
  d[18] = kbLen;
  // conic constants (f64 host values, f32-rounded on upload). A0/B1/CKm1 are
  // the cancellation-free regroupings derived in the header comment.
  d[19] = sinTg;                   // sK
  d[20] = cKB;                     // cK
  d[21] = pDist;                   // pf
  d[22] = qDist;                   // qf
  d[23] = cc1;
  d[24] = cc2;
  d[25] = cc4;
  d[26] = cc8;
  d[27] = cc1 + cc2 * sinTg * sinTg - cc4 * sinTg;   // A0 (exact, f64)
  d[28] = cc4 - 2 * cc2 * sinTg;                     // B1 (exact, f64)
  d[29] = -(sinTg * sinTg) / (1 + cKB);              // CKm1 = cK-1 (exact)
  return {
    ok: true, desc: d,
    meta: {
      kbId: kbId, isV: isV, useConic: useConic,
      cc1: cc1, cc2: cc2, cc4: cc4, cc8: cc8,
      sinTg: sinTg, cKB: cKB, pDist: pDist, qDist: qDist,
      halfLen: kbLen * 0.5, F: F, tg: tg
    }
  };
}

// Per-element descriptor (pass-1 ops; unchanged from phase 1 apart from the
// wider stride). Returns {ok,desc} or {ok:false,reason}.
function _mgElemDesc(c, E) {
  var d = new Array(MG_DESC_STRIDE);
  var k;
  for (k = 0; k < MG_DESC_STRIDE; k++) d[k] = 0;
  d[0] = MG_OP_NOOP;

  if (c.tp === 'slit' && c.id === 'wbslit') {
    d[0] = MG_OP_SLIT;
    d[2] = state.wbH * 0.5e-3;
    d[3] = state.wbV * 0.5e-3;
    d[4] = (state.wbCX || 0) * 1e-3;
    d[5] = (state.wbCY || 0) * 1e-3;
    return { ok: true, desc: d };
  }

  if (c.tp === 'hmirror') {
    var mp = (typeof M_PARAMS !== 'undefined') ? M_PARAMS[c.id] : null;
    if (!mp) return { ok: true, desc: d };           // CPU: applyMirrorMC no-ops
    if (mp.deflAxis !== 'x') return { ok: false, reason: 'deflAxis!=x not ported' };
    var sig = (typeof thermalSlopeError === 'function') ? thermalSlopeError(c.id, E) : 0;
    if (sig > 1e-12) return { ok: false, reason: 'thermal slope error active' };
    var pitch = (c.id === 'm1') ? state.m1pitch : state.m2pitch;
    pitch += mVal(c.id, 'pitch_fine', 0) * 1e-3;
    var F = (typeof bendToFocal === 'function') ? bendToFocal(c.id, pitch) : mp.F;
    if (!isFinite(F) || Math.abs(F) < 1e-6) return { ok: false, reason: 'bad focal length' };
    var sMat = RH;
    if (typeof getStripeMaterial === 'function') {
      var st = getStripeMaterial(c.id);
      if (st && st.mat) sMat = st.mat;
    }
    var matIdx = (sMat.Z === 45) ? 0 : (sMat.Z === 78) ? 1 : (sMat.Z === 14) ? 2 : -1;
    if (matIdx < 0) return { ok: false, reason: 'coating Z=' + sMat.Z + ' not in DABAX tables' };
    var roll = mVal(c.id, 'roll', 0) * 1e-3;
    var yaw = mVal(c.id, 'yaw', 0) * 1e-3;
    var tg = pitch * 1e-3;
    d[0] = MG_OP_MIRROR;
    d[2] = mp.wid * 0.5;             // halfWid
    d[3] = mp.len * 0.5;             // halfLen
    d[4] = mp.thick;                 // thick
    d[5] = tg;                       // grazing angle (rad)
    d[6] = Math.sin(Math.abs(tg));   // sinTg
    d[7] = 2 * (pitch - mp.nomP) * 1e-3;        // twoDP (defl-axis kick)
    d[8] = 2 * tg * roll + 2 * yaw;             // crossKick (cross-axis kick)
    d[9] = mVal(c.id, 'x', 0) * 1e-3;           // txOff
    d[10] = mVal(c.id, 'y', 0) * 1e-3;          // tyOff
    d[11] = mVal(c.id, 'z', 0) * 1e-3;          // zBeam
    d[12] = 1 / F;                              // invF
    d[13] = (mp.fp === 'h') ? 1 : 0;            // fpIsH
    d[14] = matIdx * 2 * MG_TBL_N;              // matBase (offset into optconst)
    d[15] = mp.rough || 0;                      // roughness (Angstrom)
    return { ok: true, desc: d };
  }

  if (c.tp === 'dcm') {
    var thB = braggAngle(E);
    if (isNaN(thB)) return { ok: true, desc: d };   // CPU: applyDCM_MC returns
    var sigD = (typeof thermalSlopeError === 'function') ? thermalSlopeError('dcm', E) : 0;
    if (sigD > 1e-12) return { ok: false, reason: 'DCM thermal slope error active' };
    if (typeof crystalPsi !== 'function') return { ok: false, reason: 'crystalPsi missing' };
    var psiC = crystalPsi(E, state.crystal);
    var dth_refrac = 0;
    var sin2thB = Math.sin(2 * thB);
    if (psiC && Math.abs(sin2thB) > 1e-10) dth_refrac = -psiC.psi0_re / sin2thB;
    var actualTheta = mVal('dcm', 'theta', thB * 180 / Math.PI) * Math.PI / 180 + dth_refrac;
    var cW = 0.060, cThick = 0.010;
    var y1_x = mVal('dcm', 'y1', 0) * 1e-3;
    if (Math.abs(actualTheta) < 1e-4) {
      d[0] = MG_OP_DCM_OFF;            // disengaged: pure body blocking
      d[8] = y1_x;
      d[10] = cW * 0.5;
      d[11] = cThick;
      return { ok: true, desc: d };
    }
    var cosThA = Math.cos(actualTheta), sinThA = Math.sin(actualTheta);
    var dTh2 = (mVal('dcm', 'dTheta2', 0) + mVal('dcm', 'dTheta2F', 0) * 0.2063) * 4.848e-6;
    var chi1 = mVal('dcm', 'chi1', 0) * 4.848e-6;
    var roll2 = mVal('dcm', 'roll2', 0) * 4.848e-6;
    var OFFSET_M = FIXED_EXIT * 1e-3;
    var d_perp = OFFSET_M / (2 * Math.cos(thB));
    var gap_m = mVal('dcm', 'z2', d_perp * 1000) * 1e-3;
    var th2 = actualTheta + dTh2;
    var n1x = cosThA, n1y = chi1 * cosThA;       // n1z = sinThA exactly
    var n2x = -Math.cos(th2), n2y = -roll2 * Math.cos(th2), n2z = -Math.sin(th2);
    var d_A = D_SI[state.crystal];
    var sinThB_c = HC / (2 * d_A * E);           // = sin(braggAngle(E)) exactly
    // f64 host constants for the cancellation-free small-quantity forms
    // (EXACT regroupings, derived in TASK_A1_MC_GPU.md):
    //   dev1 = d1 + D1 + dE_sin,  d1 = vx*n1x + vy*n1y + (vz-1)*sinThA
    //   vdn2 = V20 + dv.n2 - 2*d1*(n1.n2),  V20 = n2z - 2*sinThA*(n1.n2)
    //   dev2 = D2 + dv.n2 - 2*d1*(n1.n2) + dE_sin
    //   v2x  = vx + CX - 2*d1*n1x - 2*(vdn2 - V20)*n2x  (same for y)
    var n1n2 = n1x * n2x + n1y * n2y + sinThA * n2z;
    var V20 = n2z - 2 * sinThA * n1n2;
    d[0] = MG_OP_DCM;
    d[2] = sinThA;
    d[3] = n1x;
    d[4] = n1y;
    d[5] = n2x;
    d[6] = n2y;
    d[7] = n2z;
    d[8] = y1_x;
    d[9] = gap_m;
    d[10] = cW * 0.5;
    d[11] = cThick;
    d[12] = sinThA - sinThB_c;                   // D1
    d[13] = V20 - sinThB_c;                      // D2
    d[14] = n1n2;
    d[15] = sinThB_c;
    d[16] = d_A;
    d[17] = -2 * sinThA * n1x - 2 * V20 * n2x;   // CX
    d[18] = -2 * sinThA * n1y - 2 * V20 * n2y;   // CY
    return { ok: true, desc: d };
  }

  // mask / atten / bpm / ic / sample / det: no interaction in mcRayTrace's
  // switch -> noop (drift + snapshot only), matching the CPU engine.
  return { ok: true, desc: d };
}

// Physics fingerprint: every input the stored GPU result depends on,
// including the continuation inputs (SSA/KB state) and the global physics
// revision bumped by _invalidateMCCache. Stored results are only served when
// the fingerprint of the CURRENT state matches.
function _mgFingerprintOf(prep) {
  var motors = {};
  var ids = ['m1', 'm2', 'dcm', 'kbv', 'kbh'];
  var i, j, dev, ax;
  if (typeof MOTORS !== 'undefined') {
    for (i = 0; i < ids.length; i++) {
      dev = MOTORS[ids[i]];
      if (!dev) continue;
      var mv = {};
      for (ax in dev) {
        if (dev.hasOwnProperty(ax) && dev[ax] && dev[ax].value !== undefined) mv[ax] = dev[ax].value;
      }
      motors[ids[i]] = mv;
    }
  }
  var st = {};
  var keys = ['energy', 'gap', 'harmonic', 'crystal', 'sourceBW_eV',
    'wbH', 'wbV', 'wbCX', 'wbCY', 'ssaH', 'ssaV', 'ssaCX', 'ssaCY',
    'kbslitH', 'kbslitV', 'kbslitCX', 'kbslitCY',
    'm1pitch', 'm2pitch', 'kbvpitch', 'kbhpitch'];
  for (j = 0; j < keys.length; j++) st[keys[j]] = state[keys[j]];
  return JSON.stringify({
    rev: window._mcPhysicsRev | 0,
    td: prep.td, nR: prep.nR,
    grid: (typeof MC_GRID !== 'undefined') ? MC_GRID : 0,
    st: st, motors: motors,
    positions: state.positions,
    descs: prep.descs, ssa: prep.ssaDesc, p2: prep.p2Descs,
    src: [prep.ps.Sx, prep.ps.Sy, prep.ps.Sxp, prep.ps.Syp],
    env: [prep.und_Epeak, prep.eSpread, prep.nPeriods, prep.srcBW],
    wb: [prep.isWB ? 1 : 0, prep.wbHalfAngH, prep.wbHalfAngV]
  });
}

// ===========================================================================
// WGSL kernels (one module, six entry points, one bind group layout)
// ===========================================================================
function _mgBuildWGSL() {
  var src = [
    '// === HANBIT MC ray-trace GPU chain (phase 2: fully GPU-resident) ===',
    '// Physics ported 1:1 from raytrace/01_mc_engine.js (applyMirrorMC,',
    '// applyDCM_MC/_guigayThickBragg, applyKBMC/_kbConicAngle, sincSqRand,',
    '// _applySSAHybrid/_applyHybridFresnel per-ray parts, _mcTraceFromRays',
    '// statistics) and optics/03_reflectivity.js (optConst/mirrorR), with',
    '// exact small-quantity regroupings for f32 (DCM phase 1; KB conic',
    '// pole-frame phase 2 — see 05_mc_gpu.js header).',
    '',
    'struct Params {',
    '  Ec_eV:      f32,',
    '  srcBW:      f32,',
    '  sX:         f32,',
    '  sY:         f32,',
    '  sXp:        f32,',
    '  sYp:        f32,',
    '  wbHalfAngH: f32,',
    '  wbHalfAngV: f32,',
    '  Epeak_keV:  f32,',
    '  eSpread:    f32,',
    '  nPeriods:   f32,',
    '  _padf:      f32,',
    '  nR:         u32,',
    '  nElem:      u32,',
    '  seed:       u32,',
    '  flags:      u32,',   // bit0 = wbUniform, bit1 = useEnvelope
    '};',
    '',
    '// Pass-2/3/histogram uniforms (vec4-packed; see _mgP2U host mirror):',
    '//  u0=[seed2,seed3,e2Base,e2Count] u1=[ssaModeH,ssaModeV,frModeV,frModeH]',
    '//  u2=cdfN[4] u3=[fineEnable,fineTagOnly,grid,fineGrid]',
    '//  u4=[histMode,conicDesc,conicN,-] f0=cdfXMin[4] f1=cdfDx[4](mode2:span)',
    '//  f2=[finalDrift,qV,qH,ssaCx] f3=[Fkbv,Fkbh,ssaCy,fovH]',
    '//  f4=[fovV,cxS,cyS,fineFov] f5=[fineCx,fineCy,wScale,-]',
    'struct P2U {',
    '  u0: vec4<u32>, u1: vec4<u32>, u2: vec4<u32>, u3: vec4<u32>, u4: vec4<u32>,',
    '  f0: vec4<f32>, f1: vec4<f32>, f2: vec4<f32>, f3: vec4<f32>, f4: vec4<f32>, f5: vec4<f32>,',
    '};',
    '',
    '@group(0) @binding(0) var<uniform>             P        : Params;',
    '@group(0) @binding(1) var<storage, read>       elems    : array<f32>;',
    '@group(0) @binding(2) var<storage, read>       optconst : array<f32>;',
    '@group(0) @binding(3) var<storage, read>       psitab   : array<f32>;',
    '@group(0) @binding(4) var<storage, read_write> raysOut  : array<f32>;',
    '@group(0) @binding(5) var<storage, read_write> partials : array<f32>;',
    '@group(0) @binding(6) var<uniform>             U        : P2U;',
    '@group(0) @binding(7) var<storage, read>       cdf      : array<f32>;',
    '@group(0) @binding(8) var<storage, read_write> atom     : array<atomic<u32>>;',
    '@group(0) @binding(9) var<storage, read_write> histbuf  : array<atomic<u32>>;',
    '',
    'const HC: f32 = 12.3984;',          // keV*Angstrom (shared/01_constants.js)
    'const TBL_N: i32 = ' + MG_TBL_N + ';',
    'const DESC: u32 = ' + MG_DESC_STRIDE + 'u;',
    'const MAXE: u32 = ' + MG_MAX_ELEMS + 'u;',
    'const CDFSEG: i32 = ' + MG_CDF_SEG + ';',
    'const FOOTB: u32 = ' + MG_FOOT_BINS + 'u;',
    'const PI: f32 = 3.14159274;',
    'const INV_SQRT2: f32 = 0.70710678;',
    '',
    'var<workgroup> wgRed: array<f32, ' + MG_WG_SIZE + '>;',
    '',
    '// --- per-ray state (private so element ops can be functions) ---',
    'var<private> rx: f32;',
    'var<private> ry: f32;',
    'var<private> rvx: f32;',
    'var<private> rvy: f32;',
    'var<private> rw: f32;',
    'var<private> reps: f32;',           // E_eV - Ec_eV (per-ray energy deviation)
    'var<private> rtag: u32;',           // kb tag bits
    'var<private> rng: u32;',
    '',
    '// --- counter-based PCG-RXS-M-XS-32 (statistical equivalence only) ---',
    'fn rngNext() -> u32 {',
    '  rng = rng * 747796405u + 2891336453u;',
    '  let s = rng;',
    '  let w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;',
    '  return (w >> 22u) ^ w;',
    '}',
    'fn rand01() -> f32 {',              // [0,1)
    '  return f32(rngNext() >> 8u) * 5.9604645e-8;',
    '}',
    'fn rand01o() -> f32 {',             // (0,1) for log()
    '  return (f32(rngNext() >> 8u) + 0.5) * 5.9604645e-8;',
    '}',
    'fn gaussR() -> f32 {',              // Box-Muller (CPU gaussRand equivalent)
    '  let u = rand01o();',
    '  let v = rand01o();',
    '  return sqrt(-2.0 * log(u)) * cos(6.2831853 * v);',
    '}',
    '// sincSqRand port: rejection sampling of [sin(x)/x]^2 on [-4pi, 4pi]',
    'fn sincSqR() -> f32 {',
    '  let R = 4.0 * PI;',
    '  for (var t: i32 = 0; t < 200; t = t + 1) {',
    '    let x = (rand01() * 2.0 - 1.0) * R;',
    '    if (abs(x) < 1e-10) { return x; }',
    '    let s = sin(x) / x;',
    '    if (rand01() < s * s) { return x; }',
    '  }',
    '  return 0.0;',
    '}',
    '',
    '// --- ordered-u32 encoding for f32 atomic min/max (IEEE total order) ---',
    'fn encOrd(v: f32) -> u32 {',
    '  let u = bitcast<u32>(v);',
    '  if ((u & 0x80000000u) != 0u) { return ~u; }',
    '  return u | 0x80000000u;',
    '}',
    'fn decOrd(u: u32) -> f32 {',
    '  if ((u & 0x80000000u) != 0u) { return bitcast<f32>(u ^ 0x80000000u); }',
    '  return bitcast<f32>(~u);',
    '}',
    '',
    '// --- table interpolation, clamping identical to optConst/crystalPsi ---',
    'fn tblOpt(off: i32, E_keV: f32) -> f32 {',
    '  let idx = (E_keV - 3.0) * 100.0;',
    '  var i = i32(floor(idx));',
    '  if (i < 0) { i = 0; }',
    '  if (i >= TBL_N - 1) { i = TBL_N - 2; }',
    '  let f = clamp(idx - f32(i), 0.0, 1.0);',
    '  let a = optconst[off + i];',
    '  let b = optconst[off + i + 1];',
    '  return a + (b - a) * f;',
    '}',
    'fn tblPsi(comp: i32, E_keV: f32) -> f32 {',
    '  let idx = (E_keV - 3.0) * 100.0;',
    '  var i = i32(floor(idx));',
    '  if (i < 0) { i = 0; }',
    '  if (i >= TBL_N - 1) { i = TBL_N - 2; }',
    '  let f = clamp(idx - f32(i), 0.0, 1.0);',
    '  let off = comp * TBL_N;',
    '  let a = psitab[off + i];',
    '  let b = psitab[off + i + 1];',
    '  return a + (b - a) * f;',
    '}',
    '',
    '// --- mirrorR: Born & Wolf Fresnel + Debye-Waller (03_reflectivity.js) ---',
    'fn mirrorR_g(E_keV: f32, th: f32, matBase: i32, rough_A: f32) -> f32 {',
    '  let zf1 = tblOpt(matBase, E_keV);',
    '  let zf2 = tblOpt(matBase + TBL_N, E_keV);',
    '  let delta = zf1 * 0.5;',
    '  let beta = zf2 * 0.5;',
    '  var sth = th;',
    '  if (th > 0.05) { sth = sin(th); }',
    '  let p = sth * sth - 2.0 * delta;',
    '  let qi = 2.0 * beta;',
    '  let mag = sqrt(p * p + qi * qi);',
    '  let A = sqrt(max(0.0, (p + mag) * 0.5));',
    '  let B = sqrt(max(0.0, (-p + mag) * 0.5));',
    '  let num = (sth - A) * (sth - A) + B * B;',
    '  let den = (sth + A) * (sth + A) + B * B;',
    '  var R = 0.99;',
    '  if (den > 1e-30) { R = num / den; }',
    '  if (rough_A > 0.0) {',
    '    let lam_A = HC / E_keV;',
    '    let arg = 4.0 * PI * sth * rough_A / lam_A;',
    '    R = R * exp(-arg * arg);',
    '  }',
    '  return min(0.99, max(0.0, R));',
    '}',
    '',
    '// --- undulator spectral envelope (_undulatorEnvelope port) ---',
    'fn undSinc2(E_keV: f32, Eres: f32) -> f32 {',
    '  let x = PI * P.nPeriods * (E_keV / Eres - 1.0);',
    '  if (abs(x) < 1e-10) { return 1.0; }',
    '  let s = sin(x) / x;',
    '  return s * s;',
    '}',
    'fn envelope(E_keV: f32) -> f32 {',
    '  if (P.Epeak_keV < 1.0) { return 1.0; }',
    '  if (P.eSpread < 1e-8) { return undSinc2(E_keV, P.Epeak_keV); }',
    '  var S = 0.0;',
    '  var W = 0.0;',
    '  for (var k: i32 = -2; k <= 2; k = k + 1) {',
    '    let gw = exp(-0.5 * f32(k) * f32(k));',
    '    let Eres = P.Epeak_keV * (1.0 + 2.0 * f32(k) * P.eSpread);',
    '    S = S + gw * undSinc2(E_keV, Eres);',
    '    W = W + gw;',
    '  }',
    '  return S / W;',
    '}',
    '',
    '// --- Guigay thick-Bragg (sigma+pi)/2 reflectivity (_guigayThickBragg) ---',
    '// dev = vdn - g/2 (cancellation-free input); alpha = g*(2*vdn-g) = 2*g*dev.',
    'fn guigayR(dev: f32, vdn: f32, g: f32, lam_m: f32, cos2thB: f32,',
    '           p0re: f32, p0im: f32, pHre: f32, pHim: f32, pBre: f32, pBim: f32) -> f32 {',
    '  let alpha = 2.0 * g * dev;',
    '  let KH2 = 1.0 - 2.0 * g * vdn + g * g;',
    '  let KHn = sqrt(abs(KH2));',
    '  var gammaH = -vdn;',
    '  if (KHn > 1e-15) { gammaH = (vdn - g) / KHn; }',
    '  var b = -1.0;',
    '  if (abs(gammaH) > 1e-15) { b = vdn / gammaH; }',
    '  let ep0re = p0re;',
    '  let ep0im = -p0im;',
    '  let bAlphaHalf = b * alpha * 0.5;',
    '  let bm1half = (b - 1.0) * 0.5;',
    '  let w_re = bAlphaHalf + bm1half * ep0re;',
    '  let w_im = bm1half * ep0im;',
    '  let piOL = PI / lam_m;',
    '  let om_re = piOL * w_re;',
    '  let om_im = piOL * w_im;',
    '  let piOL2 = piOL * piOL;',
    '  let w2_re = w_re * w_re - w_im * w_im;',
    '  let w2_im = 2.0 * w_re * w_im;',
    '  var Rs = 0.0;',
    '  var Rp = 0.0;',
    '  for (var pol: i32 = 0; pol < 2; pol = pol + 1) {',
    '    var sc = 1.0;',
    '    if (pol == 1) { sc = cos2thB; }',
    '    let ehre = pHre * sc;',
    '    let ehim = -pHim * sc;',
    '    let ebre = pBre * sc;',
    '    let ebim = -pBim * sc;',
    '    let uhre = ebre * piOL;',
    '    let uhim = ebim * piOL;',
    '    let prre = ehre * ebre - ehim * ebim;',
    '    let prim = ehre * ebim + ehim * ebre;',
    '    let sre = b * prre + w2_re;',
    '    let sim = b * prim + w2_im;',
    '    let are = piOL2 * sre;',
    '    let aim = piOL2 * sim;',
    '    let aabs = sqrt(are * are + aim * aim);',
    '    // q = |asq| - Re(asq), evaluated cancellation-free when Re > 0',
    '    var q = aabs - are;',
    '    if (are > 0.0) { q = (aim * aim) / max(aabs + are, 1e-30); }',
    '    if (q < 1e-30) { q = 1e-30; }',
    '    let sq = sqrt(q);',
    '    let aare = INV_SQRT2 * aim / sq;',
    '    let aaim = INV_SQRT2 * sq;',
    '    let nre = aare + om_re;',
    '    let nim = aaim + om_im;',
    '    let dnm = uhre * uhre + uhim * uhim;',
    '    var Rpol = 0.0;',
    '    if (dnm > 1e-30) {',
    '      let cre = (nre * uhre + nim * uhim) / dnm;',
    '      let cim = (nim * uhre - nre * uhim) / dnm;',
    '      Rpol = cre * cre + cim * cim;',
    '    }',
    '    Rpol = clamp(Rpol, 0.0, 1.0);',
    '    if (pol == 0) { Rs = Rpol; } else { Rp = Rpol; }',
    '  }',
    '  return (Rs + Rp) * 0.5;',
    '}',
    '',
    '// --- KB ellipsoid conic, pole-frame small-quantity form (EXACT algebra;',
    '//     derivation in the module header). Mirrors _kbConicAngle output. ---',
    'fn kbConic(srcPos: f32, angIn: f32, posKb: f32, base: u32) -> f32 {',
    '  let sK = elems[base + 19u];',
    '  let cK = elems[base + 20u];',
    '  let pf = elems[base + 21u];',
    '  let qf = elems[base + 22u];',
    '  let cc1 = elems[base + 23u];',
    '  let cc2 = elems[base + 24u];',
    '  let cc4 = elems[base + 25u];',
    '  let cc8 = elems[base + 26u];',
    '  let A0 = elems[base + 27u];',
    '  let B1 = elems[base + 28u];',
    '  let CKm1 = elems[base + 29u];',
    '  let s2a = angIn * angIn;',
    '  var vzc = 0.0;',
    '  if (s2a < 1.0) { vzc = sqrt(1.0 - s2a); }',
    '  let vzc1 = -s2a / (1.0 + vzc);',          // vzc - 1, stable
    '  let eY = vzc1 * cK + angIn * sK;',        // VY - cK
    '  let eZ = -vzc1 * sK + angIn * cK;',       // VZ + sK
    '  let VY = cK + eY;',
    '  let VZ = -sK + eZ;',
    '  let PYp = srcPos * sK + pf * eY;',        // PY + VY*pf (exact identity)
    '  let PZp = srcPos * cK + pf * eZ;',        // PZ + VZ*pf (exact identity)
    '  let h = eZ + sK * CKm1 + sK * eY;',       // VZ + sK*VY in small terms
    '  let AA = A0 * VY * VY + B1 * VY * h + cc2 * h * h;',
    '  let BB = 2.0 * (cc1 * PYp * VY + cc2 * PZp * VZ) + cc4 * (PZp * VY + PYp * VZ) + cc8 * VZ;',
    '  let CC = cc1 * PYp * PYp + cc2 * PZp * PZp + cc4 * PYp * PZp + cc8 * PZp;',
    '  var disc = BB * BB - 4.0 * AA * CC;',
    '  if (disc < 0.0) { disc = 0.0; }',
    '  let sq = sqrt(disc);',
    '  var qq = -0.5 * (BB + sq);',
    '  if (BB < 0.0) { qq = -0.5 * (BB - sq); }',
    '  var ta = 0.0;',
    '  var tb = 0.0;',
    '  if (abs(AA) > 1e-30) { ta = qq / AA; }',
    '  if (abs(qq) > 1e-30) { tb = CC / qq; }',
    '  let IYa = PYp + VY * ta;',
    '  let IYb = PYp + VY * tb;',
    '  var tt = ta;',
    '  if (abs(IYb) < abs(IYa)) { tt = tb; }',   // pole-nearest intersection
    '  let IY = PYp + VY * tt;',
    '  let IZ = PZp + VZ * tt;',
    '  var n1 = 2.0 * cc1 * IY + cc4 * IZ;',
    '  var n2 = 2.0 * cc2 * IZ + cc4 * IY + cc8;',
    '  let nm = sqrt(n1 * n1 + n2 * n2);',
    '  n1 = n1 / nm;',
    '  n2 = n2 / nm;',
    '  let vdn = VY * n1 + VZ * n2;',
    '  let RY = VY - 2.0 * vdn * n1;',
    '  let RZ = VZ - 2.0 * vdn * n2;',
    '  let vyi = -RY * sK + RZ * cK;',
    '  let vzi = RY * cK + RZ * sK;',
    '  let yim = -IY * sK + IZ * cK;',
    '  let zim = IY * cK + IZ * sK;',
    '  let yp = yim - vyi * zim / vzi;',
    '  return vyi + (yp - posKb) / qf;',
    '}',
    '',
    '// --- inverse-CDF sampling of an uploaded table (Sampler1D port) ---',
    'fn cdfSampleSeg(seg: u32) -> f32 {',
    '  let n = i32(U.u2[seg]);',
    '  let xMin = U.f0[seg];',
    '  let dx = U.f1[seg];',
    '  let u = rand01();',
    '  let off = i32(seg) * CDFSEG;',
    '  var lo = 0;',
    '  var hi = n - 1;',
    '  loop {',
    '    if (lo >= hi) { break; }',
    '    let mid = (lo + hi) >> 1;',
    '    if (cdf[off + mid] < u) { lo = mid + 1; } else { hi = mid; }',
    '  }',
    '  var ix = lo;',
    '  if (ix > 0) { ix = ix - 1; }',
    '  var dval = 0.0;',
    '  if (ix < n - 1) {',
    '    let pend = cdf[off + ix + 1] - cdf[off + ix];',
    '    if (pend > 0.0) { dval = (u - cdf[off + ix]) / pend; }',
    '  }',
    '  return xMin + (f32(ix) + dval) * dx;',
    '}',
    '// mode: 1=CDF sample, 2=uniform (degenerate CDF; f1 slot = span),',
    '// 3=zero kick (CPU zeros array). 0 is handled by the caller (no kick).',
    'fn hybridKick(seg: u32, mode: u32) -> f32 {',
    '  if (mode == 1u) { return cdfSampleSeg(seg); }',
    '  if (mode == 2u) { return U.f0[seg] + rand01() * U.f1[seg]; }',
    '  return 0.0;',
    '}',
    '',
    '// --- element ops (return early = CPU "continue"; rw=0 = killed ray) ---',
    'fn opSlit(base: u32) {',
    '  let hH = elems[base + 2u];',
    '  let hV = elems[base + 3u];',
    '  let cx = elems[base + 4u];',
    '  let cy = elems[base + 5u];',
    '  if (abs(rx - cx) > hH || abs(ry - cy) > hV) { rw = 0.0; }',
    '}',
    '',
    '// kbslit (and any non-ssa narrow slit): clip + Fraunhofer sinc^2 kicks',
    'fn opSlitSinc(base: u32) {',
    '  let hH = elems[base + 2u];',
    '  let hV = elems[base + 3u];',
    '  let cx = elems[base + 4u];',
    '  let cy = elems[base + 5u];',
    '  if (abs(rx - cx) > hH || abs(ry - cy) > hV) { rw = 0.0; return; }',
    '  let dfH = elems[base + 6u];',
    '  let dfV = elems[base + 7u];',
    '  if (dfH > 1e-12) { rvx = rvx + sincSqR() * dfH; }',
    '  if (dfV > 1e-12) { rvy = rvy + sincSqR() * dfV; }',
    '}',
    '',
    'fn opMirror(base: u32) {',
    '  let halfWid = elems[base + 2u];',
    '  let halfLen = elems[base + 3u];',
    '  let thick = elems[base + 4u];',
    '  let tg = elems[base + 5u];',
    '  let sinTg = elems[base + 6u];',
    '  let xr = rx - elems[base + 9u];',
    '  let yr = ry - elems[base + 10u];',
    '  // deflAxis x: bodyPos = xr, widthPos = yr (host asserts deflAxis==x)',
    '  if (abs(yr) > halfWid) { return; }',
    '  if (tg > 0.5e-3) {',
    '    var surfY = xr / sinTg;',
    '    let zBeam = elems[base + 11u];',
    '    if (abs(zBeam) > 1e-7) { surfY = surfY - zBeam; }',
    '    if (abs(surfY) > halfLen) { rw = 0.0; return; }',
    '  } else {',
    '    if (xr < 0.0 || xr > thick) { return; }',
    '    if (tg <= 1e-7) { rw = 0.0; return; }',
    '    if (xr > 2.0 * halfLen * sinTg) { rw = 0.0; return; }',
    '  }',
    '  let lth = abs(tg - rvx);',
    '  let E_keV = (P.Ec_eV + reps) * 0.001;',
    '  let R = mirrorR_g(E_keV, lth, i32(elems[base + 14u]), elems[base + 15u]);',
    '  if (rand01() > R) { rw = 0.0; return; }',
    '  rvx = rvx + elems[base + 7u];',     // += 2*dP   (defl axis)
    '  rvy = rvy + elems[base + 8u];',     // += 2*tg*roll + 2*yaw (cross axis)
    '  let fpIsH = elems[base + 13u];',
    '  let invF = elems[base + 12u];',
    '  if (fpIsH > 0.5) { rvx = rvx - rx * invF; }',
    '  else             { rvy = rvy - ry * invF; }',
    '}',
    '',
    '// applyKBMC port (V/H selected by desc): boundary checks, pass-through',
    '// -2theta kick, substrate blocking, reflectivity cull, conic/thin-lens',
    'fn opKB(base: u32) {',
    '  let isV = elems[base + 2u] > 0.5;',
    '  let halfWid = elems[base + 3u];',
    '  let halfLen = elems[base + 4u];',
    '  let thick = elems[base + 5u];',
    '  let tg = elems[base + 6u];',
    '  let sinTg = elems[base + 7u];',
    '  let passKick = elems[base + 8u];',
    '  let kbLen = elems[base + 18u];',
    '  let xr = rx - elems[base + 11u];',
    '  let yr = ry - elems[base + 12u];',
    '  var widthPos = yr;',
    '  var dpos = xr;',
    '  if (isV) { widthPos = xr; dpos = yr; }',
    '  if (abs(widthPos) > halfWid) {',
    '    if (isV) { rvy = rvy + passKick; } else { rvx = rvx + passKick; }',
    '    return;',
    '  }',
    '  var hit = true;',
    '  if (tg > 0.5e-3) {',
    '    var surfY = dpos / sinTg;',
    '    let zBeam = elems[base + 13u];',
    '    if (abs(zBeam) > 1e-7) { surfY = surfY - zBeam; }',
    '    if (abs(surfY) > halfLen) { hit = false; }',
    '  } else {',
    '    if (dpos < 0.0 || dpos > thick) {',
    '      if (isV) { rvy = rvy + passKick; } else { rvx = rvx + passKick; }',
    '      return;',
    '    }',
    '    if (tg <= 1e-7) { rw = 0.0; return; }',
    '    if (dpos > kbLen * sinTg) { hit = false; }',
    '  }',
    '  if (!hit) {',
    '    if (tg > 0.5e-3) {',
    '      let fpHalf = kbLen * sinTg * 0.5;',
    '      if (dpos < -fpHalf) { rw = 0.0; return; }',
    '    }',
    '    if (isV) { rvy = rvy + passKick; } else { rvx = rvx + passKick; }',
    '    return;',
    '  }',
    '  var ang = rvx;',
    '  if (isV) { ang = rvy; }',
    '  let lth = abs(tg - ang);',
    '  let E_keV = (P.Ec_eV + reps) * 0.001;',
    '  let R = mirrorR_g(E_keV, lth, i32(elems[base + 14u]), elems[base + 15u]);',
    '  if (rand01() > R) { rw = 0.0; return; }',
    '  let twoDP = elems[base + 9u];',
    '  let crossKick = elems[base + 10u];',
    '  let useConic = elems[base + 16u] > 0.5;',
    '  let invF = elems[base + 17u];',
    '  let pf = elems[base + 21u];',
    '  if (isV) {',
    '    rtag = rtag | 1u;',
    '    if (useConic) { rvy = kbConic(ry - rvy * pf, rvy, ry, base) + twoDP; }',
    '    else { rvy = rvy + twoDP - ry * invF; }',
    '    rvx = rvx + crossKick;',
    '  } else {',
    '    rtag = rtag | 2u;',
    '    if (useConic) { rvx = kbConic(rx - rvx * pf, rvx, rx, base) + twoDP; }',
    '    else { rvx = rvx + twoDP - rx * invF; }',
    '    rvy = rvy + crossKick;',
    '  }',
    '}',
    '',
    'fn opDcmOff(base: u32) {',
    '  if (abs(ry) > elems[base + 10u]) { return; }',
    '  let xr1 = rx - elems[base + 8u];',
    '  if (xr1 >= 0.0 && xr1 <= elems[base + 11u]) { rw = 0.0; }',
    '}',
    '',
    'fn opDcm(base: u32) {',
    '  let cWhalf = elems[base + 10u];',
    '  if (abs(ry) > cWhalf) { return; }',
    '  let xr1 = rx - elems[base + 8u];',
    '  let cThick = elems[base + 11u];',
    '  if (xr1 < -cThick * 0.5 || xr1 > cThick * 0.5) { return; }',
    '  let sinThA = elems[base + 2u];',
    '  let n1x = elems[base + 3u];',
    '  let n1y = elems[base + 4u];',
    '  let n2x = elems[base + 5u];',
    '  let n2y = elems[base + 6u];',
    '  let n2z = elems[base + 7u];',
    '  let gap_m = elems[base + 9u];',
    '  let D1 = elems[base + 12u];',
    '  let D2 = elems[base + 13u];',
    '  let n1n2 = elems[base + 14u];',
    '  let sinThB_c = elems[base + 15u];',
    '  let CX = elems[base + 17u];',
    '  let CY = elems[base + 18u];',
    '  let E_eV = P.Ec_eV + reps;',
    '  let E_keV = E_eV * 0.001;',
    '  // per-ray Bragg: sinThB_ray = HC/(2*d*E_ray) = sinThB_c * Ec/E_ray',
    '  let sinThB = sinThB_c * P.Ec_eV / E_eV;',
    '  if (sinThB >= 1.0 || sinThB <= 0.0) { rw = 0.0; return; }',
    '  let thB = asin(sinThB);',
    '  let cos2thB = cos(2.0 * thB);',
    '  let g = 2.0 * sinThB;',
    '  let lam_m = HC / E_keV * 1e-10;',
    '  // psi components at E_ray (DABAX table, same clamped lerp as CPU)',
    '  let p0re = tblPsi(0, E_keV);',
    '  let p0im = tblPsi(1, E_keV);',
    '  let pHre = tblPsi(2, E_keV);',
    '  let pHim = tblPsi(3, E_keV);',
    '  let pBre = tblPsi(4, E_keV);',
    '  let pBim = tblPsi(5, E_keV);',
    '  // small-quantity geometry (EXACT regroupings; see TASK_A1_MC_GPU.md):',
    '  let s2 = rvx * rvx + rvy * rvy;',
    '  let vz = sqrt(max(1.0 - s2, 0.0));',
    '  let dvz = -s2 / (1.0 + vz);',                       // vz - 1, stable
    '  let d1 = rvx * n1x + rvy * n1y + dvz * sinThA;',    // vdn1 - sinThA
    '  let dE_sin = sinThB_c * reps / E_eV;',              // sinThB_c - sinThB_ray
    '  let dev1 = d1 + D1 + dE_sin;',                      // vdn1 - sinThB_ray
    '  let vdn1 = sinThB + dev1;',
    '  if (vdn1 <= 1e-6) { rw = 0.0; return; }',           // grazing-side guard (|vdn1|<1e-10 on CPU)
    '  let R1 = guigayR(dev1, vdn1, g, lam_m, cos2thB, p0re, p0im, pHre, pHim, pBre, pBim);',
    '  rw = rw * R1;',
    '  if (rw < 1e-12) { rw = 0.0; return; }',
    '  let t12 = gap_m / vdn1;',
    '  if (t12 > 10.0) { rw = 0.0; return; }',
    '  // crystal-1 -> crystal-2 propagation + fixed-exit return, regrouped:',
    '  //   dx = vx1*t12 + h_nominal == t12*vx   (exact; h_nominal = 2*gap*n1x)',
    '  //   dy = vy1*t12,  vy1 = vy - 2*vdn1*n1y (n1y ~ urad: no cancellation)',
    '  rx = rx + t12 * rvx;',
    '  ry = ry + (rvy - 2.0 * vdn1 * n1y) * t12;',
    '  if (abs(ry) > cWhalf) { rw = 0.0; return; }',
    '  // crystal 2: vdn2 = V20 + dv.n2 - 2*d1*(n1.n2); dev2 = vdn2 - sinThB_ray',
    '  let dvn2 = rvx * n2x + rvy * n2y + dvz * n2z;',
    '  let w2s = dvn2 - 2.0 * d1 * n1n2;',                 // vdn2 - V20
    '  let dev2 = D2 + w2s + dE_sin;',
    '  let vdn2 = sinThB + dev2;',
    '  let R2 = guigayR(dev2, vdn2, g, lam_m, cos2thB, p0re, p0im, pHre, pHim, pBre, pBim);',
    '  rw = rw * R2;',
    '  if (rw < 1e-12) { rw = 0.0; return; }',
    '  // composite two-reflection direction update, regrouped (exact):',
    '  //   v2 = v + C - 2*d1*n1 - 2*(vdn2 - V20)*n2',
    '  rvx = rvx + CX - 2.0 * d1 * n1x - 2.0 * w2s * n2x;',
    '  rvy = rvy + CY - 2.0 * d1 * n1y - 2.0 * w2s * n2y;',
    '  // vz follows from |v|=1 (reflections are norm-preserving; the CPU',
    '  // stores the explicitly reflected vz which equals sqrt(1-vx^2-vy^2)).',
    '}',
    '',
    'fn opDispatch(op: u32, base: u32) {',
    '  if (op == 1u) { opSlit(base); }',
    '  else if (op == 2u) { opMirror(base); }',
    '  else if (op == 3u) { opDcm(base); }',
    '  else if (op == 4u) { opDcmOff(base); }',
    '  else if (op == 5u) { opSlitSinc(base); }',
    '  else if (op == 6u) { opKB(base); }',
    '}',
    '',
    '// free-space drift: CPU keeps vz == sqrt(1-vx^2-vy^2) via rayUpdateVz',
    '// after every direction change, so recomputing here is equivalent.',
    'fn driftRay(L: f32) {',
    '  if (L > 0.0) {',
    '    let s2 = rvx * rvx + rvy * rvy;',
    '    var vz = 1e-10;',
    '    if (s2 < 1.0) { vz = sqrt(1.0 - s2); }',
    '    let ivzL = L / vz;',
    '    rx = rx + rvx * ivzL;',
    '    ry = ry + rvy * ivzL;',
    '  }',
    '}',
    'fn curVz() -> f32 {',
    '  let s2 = rvx * rvx + rvy * rvy;',
    '  var vz = 1e-10;',
    '  if (s2 < 1.0) { vz = sqrt(1.0 - s2); }',
    '  return vz;',
    '}',
    '',
    '// --- workgroup tree reduction (uniform control flow) ---',
    'fn wgSum(v: f32, lid: u32) -> f32 {',
    '  wgRed[lid] = v;',
    '  workgroupBarrier();',
    '  var s: u32 = ' + (MG_WG_SIZE / 2) + 'u;',
    '  loop {',
    '    if (lid < s) { wgRed[lid] = wgRed[lid] + wgRed[lid + s]; }',
    '    workgroupBarrier();',
    '    s = s >> 1u;',
    '    if (s == 0u) { break; }',
    '  }',
    '  let r = wgRed[0];',
    '  workgroupBarrier();',
    '  return r;',
    '}',
    '',
    '// partials regions (host mirrors): A = element snapshots',
    '// [(e*NW+wg)*5], B = ssa sumE [Aend+wg], C = kb sumE [Aend+NW+wg],',
    '// D = final moments [Aend+2*NW+wg*18]',
    'fn regBoff(nwg: u32) -> u32 { return MAXE * nwg * 5u; }',
    '',
    '// ======================== PASS 1: source -> SSA ========================',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn mc_trace(@builtin(global_invocation_id) gid: vec3<u32>,',
    '            @builtin(local_invocation_id) lid3: vec3<u32>,',
    '            @builtin(workgroup_id) wid3: vec3<u32>,',
    '            @builtin(num_workgroups) nwg3: vec3<u32>) {',
    '  let i = gid.x;',
    '  let lid = lid3.x;',
    '  let isAct = i < P.nR;',
    '  rw = 0.0;',
    '  rx = 0.0; ry = 0.0; rvx = 0.0; rvy = 0.0; reps = 0.0; rtag = 0u;',
    '  if (isAct) {',
    '    // counter-based per-ray RNG stream',
    '    rng = ((i + 1u) * 2654435769u) ^ P.seed;',
    '    rngNext(); rngNext();',
    '    // source phase-space sampling (mcRayTrace source block)',
    '    rx = gaussR() * P.sX;',
    '    ry = gaussR() * P.sY;',
    '    if ((P.flags & 1u) != 0u) {',
    '      rvx = (rand01() * 2.0 - 1.0) * P.wbHalfAngH;',
    '      rvy = (rand01() * 2.0 - 1.0) * P.wbHalfAngV;',
    '    } else {',
    '      rvx = gaussR() * P.sXp;',
    '      rvy = gaussR() * P.sYp;',
    '    }',
    '    rw = 1.0;',
    '    if (P.srcBW > 0.0) { reps = P.Ec_eV * gaussR() * P.srcBW * 0.5; }',
    '    if ((P.flags & 2u) != 0u) { rw = rw * envelope((P.Ec_eV + reps) * 0.001); }',
    '  }',
    '  // element chain (uniform loop; barriers only in the snapshot reduction)',
    '  for (var e: u32 = 0u; e < P.nElem; e = e + 1u) {',
    '    let base = e * DESC;',
    '    if (isAct && rw > 0.0) {',
    '      driftRay(elems[base + 1u]);',
    '      opDispatch(u32(elems[base]), base);',
    '    }',
    '    // per-element snapshot partials: [sumW, sumWX, sumWY, sumWX2, sumWY2]',
    '    var w0 = 0.0;',
    '    if (isAct && rw > 0.0) { w0 = rw; }',
    '    let sw  = wgSum(w0, lid);',
    '    let swx = wgSum(w0 * rx, lid);',
    '    let swy = wgSum(w0 * ry, lid);',
    '    let sxx = wgSum(w0 * rx * rx, lid);',
    '    let syy = wgSum(w0 * ry * ry, lid);',
    '    if (lid == 0u) {',
    '      let pb = (e * nwg3.x + wid3.x) * 5u;',
    '      partials[pb] = sw;',
    '      partials[pb + 1u] = swx;',
    '      partials[pb + 2u] = swy;',
    '      partials[pb + 3u] = sxx;',
    '      partials[pb + 4u] = syy;',
    '    }',
    '  }',
    '  // SSA-plane footprint stats for the hybrid wavefront (full mode):',
    '  // alive count + ordered min/max of slit-relative coordinates + sum E.',
    '  var wE = 0.0;',
    '  if (isAct && rw > 0.0) {',
    '    atomicAdd(&atom[0], 1u);',
    '    let relH = rx - U.f2.w;',
    '    let relV = ry - U.f3.z;',
    '    atomicMin(&atom[1], encOrd(relH));',
    '    atomicMax(&atom[2], encOrd(relH));',
    '    atomicMin(&atom[3], encOrd(relV));',
    '    atomicMax(&atom[4], encOrd(relV));',
    '    wE = P.Ec_eV + reps;',
    '  }',
    '  let sE = wgSum(wE, lid);',
    '  if (lid == 0u) { partials[regBoff(nwg3.x) + wid3.x] = sE; }',
    '  if (isAct) {',
    '    let o = i * 8u;',
    '    raysOut[o] = rx;',
    '    raysOut[o + 1u] = ry;',
    '    raysOut[o + 2u] = rvx;',
    '    raysOut[o + 3u] = rvy;',
    '    raysOut[o + 4u] = curVz();',
    '    raysOut[o + 5u] = rw;',
    '    raysOut[o + 6u] = P.Ec_eV + reps;',
    '    raysOut[o + 7u] = 0.0;',
    '  }',
    '}',
    '',
    '// =============== footprint histograms (SSA / KB modes) ===============',
    '// Unweighted integer counts — exact parity with the CPU histogram given',
    '// the same coordinates. nBins recomputed in-shader from the atomic alive',
    '// counts with the CPU formula min(200, round(n/20)), floor(x+0.5) ==',
    '// Math.round for positive x.',
    'fn footBins(n: u32) -> i32 {',
    '  var nb = i32(floor(f32(n) / 20.0 + 0.5));',
    '  if (nb > 200) { nb = 200; }',
    '  if (nb < 10) { nb = 10; }',
    '  return nb;',
    '}',
    'fn footBinAdd(v: f32, minIdx: u32, maxIdx: u32, nb: i32, histBase: u32) {',
    '  let zMin = decOrd(atomicLoad(&atom[minIdx]));',
    '  let zMax = decOrd(atomicLoad(&atom[maxIdx]));',
    '  if (zMax - zMin < 1e-15) { return; }',
    '  let dz = (zMax - zMin) / f32(nb);',
    '  var b = i32(floor((v - zMin) / dz));',
    '  if (b >= nb) { b = nb - 1; }',
    '  if (b >= 0) { atomicAdd(&atom[histBase + u32(b)], 1u); }',
    '}',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn foot_hist(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let i = gid.x;',
    '  if (i >= P.nR) { return; }',
    '  let o = i * 8u;',
    '  if (raysOut[o + 5u] <= 0.0) { return; }',
    '  if (U.u4.x == 0u) {',
    '    // SSA mode: slit-relative positions (same expression as pass 1)',
    '    let nb = footBins(atomicLoad(&atom[0]));',
    '    footBinAdd(raysOut[o] - U.f2.w, 1u, 2u, nb, 20u);',
    '    footBinAdd(raysOut[o + 1u] - U.f3.z, 3u, 4u, nb, 20u + FOOTB);',
    '  } else {',
    '    // KB mode: back-propagated mirror coordinates (CPU ivz form)',
    '    let tag = u32(raysOut[o + 7u]);',
    '    let ivz = 1.0 / raysOut[o + 4u];',
    '    if ((tag & 1u) != 0u) {',
    '      let ymir = raysOut[o + 1u] - raysOut[o + 3u] * ivz * U.f2.y;',
    '      footBinAdd(ymir, 8u, 9u, footBins(atomicLoad(&atom[6])), 20u + 2u * FOOTB);',
    '    }',
    '    if ((tag & 2u) != 0u) {',
    '      let xmir = raysOut[o] - raysOut[o + 2u] * ivz * U.f2.z;',
    '      footBinAdd(xmir, 10u, 11u, footBins(atomicLoad(&atom[7])), 20u + 3u * FOOTB);',
    '    }',
    '  }',
    '}',
    '',
    '// ======== PASS 2: SSA hybrid kicks -> remaining chain -> sample ========',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn mc_pass2(@builtin(global_invocation_id) gid: vec3<u32>,',
    '            @builtin(local_invocation_id) lid3: vec3<u32>,',
    '            @builtin(workgroup_id) wid3: vec3<u32>,',
    '            @builtin(num_workgroups) nwg3: vec3<u32>) {',
    '  let i = gid.x;',
    '  let lid = lid3.x;',
    '  let isAct = i < P.nR;',
    '  let o = i * 8u;',
    '  rw = 0.0;',
    '  rx = 0.0; ry = 0.0; rvx = 0.0; rvy = 0.0; reps = 0.0; rtag = 0u;',
    '  if (isAct) {',
    '    rng = ((i + 1u) * 2654435769u) ^ U.u0.x;',
    '    rngNext(); rngNext();',
    '    rx = raysOut[o];',
    '    ry = raysOut[o + 1u];',
    '    rvx = raysOut[o + 2u];',
    '    rvy = raysOut[o + 3u];',
    '    rw = raysOut[o + 5u];',
    '    reps = raysOut[o + 6u] - P.Ec_eV;',
    '    rtag = u32(raysOut[o + 7u]);',
    '  }',
    '  // SSA hybrid angular kicks (CPU _applySSAHybrid kick loop; the',
    '  // distributions were computed on the host from the GPU histograms via',
    '  // the engine-owned _hybridProfile1D/_cdfBuild).',
    '  if (isAct && rw > 0.0) {',
    '    if (U.u1.x != 0u) { rvx = rvx + hybridKick(0u, U.u1.x); }',
    '    if (U.u1.y != 0u) { rvy = rvy + hybridKick(1u, U.u1.y); }',
    '  }',
    '  // remaining element chain (kbslit, KB-V, KB-H, noops)',
    '  for (var e2: u32 = 0u; e2 < U.u0.w; e2 = e2 + 1u) {',
    '    let eg = U.u0.z + e2;',
    '    let base = eg * DESC;',
    '    if (isAct && rw > 0.0) {',
    '      driftRay(elems[base + 1u]);',
    '      opDispatch(u32(elems[base]), base);',
    '    }',
    '    var w0 = 0.0;',
    '    if (isAct && rw > 0.0) { w0 = rw; }',
    '    let sw  = wgSum(w0, lid);',
    '    let swx = wgSum(w0 * rx, lid);',
    '    let swy = wgSum(w0 * ry, lid);',
    '    let sxx = wgSum(w0 * rx * rx, lid);',
    '    let syy = wgSum(w0 * ry * ry, lid);',
    '    if (lid == 0u) {',
    '      let pb = (eg * nwg3.x + wid3.x) * 5u;',
    '      partials[pb] = sw;',
    '      partials[pb + 1u] = swx;',
    '      partials[pb + 2u] = swy;',
    '      partials[pb + 3u] = sxx;',
    '      partials[pb + 4u] = syy;',
    '    }',
    '  }',
    '  // final drift to the target plane',
    '  var wE = 0.0;',
    '  if (isAct && rw > 0.0) {',
    '    driftRay(U.f2.x);',
    '    // Fresnel-hybrid prep stats (CPU _applyHybridFresnel collection):',
    '    atomicAdd(&atom[5], 1u);',
    '    wE = P.Ec_eV + reps;',
    '    let vzv = curVz();',
    '    let ivz = 1.0 / vzv;',
    '    if ((rtag & 1u) != 0u) {',
    '      atomicAdd(&atom[6], 1u);',
    '      let ymir = ry - rvy * ivz * U.f2.y;',
    '      atomicMin(&atom[8], encOrd(ymir));',
    '      atomicMax(&atom[9], encOrd(ymir));',
    '    }',
    '    if ((rtag & 2u) != 0u) {',
    '      atomicAdd(&atom[7], 1u);',
    '      let xmir = rx - rvx * ivz * U.f2.z;',
    '      atomicMin(&atom[10], encOrd(xmir));',
    '      atomicMax(&atom[11], encOrd(xmir));',
    '    }',
    '  }',
    '  let sE = wgSum(wE, lid);',
    '  if (lid == 0u) { partials[regBoff(nwg3.x) + nwg3.x + wid3.x] = sE; }',
    '  if (isAct) {',
    '    raysOut[o] = rx;',
    '    raysOut[o + 1u] = ry;',
    '    raysOut[o + 2u] = rvx;',
    '    raysOut[o + 3u] = rvy;',
    '    raysOut[o + 4u] = curVz();',
    '    raysOut[o + 5u] = rw;',
    '    raysOut[o + 6u] = P.Ec_eV + reps;',
    '    raysOut[o + 7u] = f32(rtag);',
    '  }',
    '}',
    '',
    '// ========= PASS 3: Fresnel hybrid application + moment sums =========',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn mc_pass3(@builtin(global_invocation_id) gid: vec3<u32>,',
    '            @builtin(local_invocation_id) lid3: vec3<u32>,',
    '            @builtin(workgroup_id) wid3: vec3<u32>,',
    '            @builtin(num_workgroups) nwg3: vec3<u32>) {',
    '  let i = gid.x;',
    '  let lid = lid3.x;',
    '  let isAct = i < P.nR;',
    '  let o = i * 8u;',
    '  rx = 0.0; ry = 0.0; rvx = 0.0; rvy = 0.0; rw = 0.0; rtag = 0u;',
    '  var vz = 1.0;',
    '  if (isAct) {',
    '    rng = ((i + 1u) * 2654435769u) ^ U.u0.y;',
    '    rngNext(); rngNext();',
    '    rx = raysOut[o];',
    '    ry = raysOut[o + 1u];',
    '    rvx = raysOut[o + 2u];',
    '    rvy = raysOut[o + 3u];',
    '    vz = raysOut[o + 4u];',
    '    rw = raysOut[o + 5u];',
    '    rtag = u32(raysOut[o + 7u]);',
    '  }',
    '  let alive = isAct && rw > 0.0;',
    '  // _applyHybridFresnel port: vz is the STORED value and is NOT updated',
    '  // (CPU leaves it stale through and after this block).',
    '  if (alive) {',
    '    if (U.u1.z != 0u && (rtag & 1u) != 0u) {',
    '      let ivz = 1.0 / vz;',
    '      let vys = rvy * ivz;',
    '      let ymir = ry - vys * U.f2.y;',
    '      let geo = -ymir / U.f3.x;',
    '      let vyo = vys - geo;',
    '      let ang = hybridKick(2u, U.u1.z);',
    '      let vyt = vyo + (-ymir / U.f3.x) + ang;',
    '      ry = ymir + vyt * U.f2.y;',
    '      rvy = vyt * vz;',
    '    }',
    '    if (U.u1.w != 0u && (rtag & 2u) != 0u) {',
    '      let ivz = 1.0 / vz;',
    '      let vxs = rvx * ivz;',
    '      let xmir = rx - vxs * U.f2.z;',
    '      let geoh = -xmir / U.f3.y;',
    '      let vxo = vxs - geoh;',
    '      let angh = hybridKick(3u, U.u1.w);',
    '      let vxt = vxo + (-xmir / U.f3.y) + angh;',
    '      rx = xmir + vxt * U.f2.z;',
    '      rvx = vxt * vz;',
    '    }',
    '    if (isAct) {',
    '      raysOut[o] = rx;',
    '      raysOut[o + 1u] = ry;',
    '      raysOut[o + 2u] = rvx;',
    '      raysOut[o + 3u] = rvy;',
    '    }',
    '    // counters: tag distribution, alive count, weight min/max',
    '    var tc = rtag;',
    '    if (tc > 3u) { tc = 3u; }',
    '    atomicAdd(&atom[12u + tc], 1u);',
    '    atomicAdd(&atom[16], 1u);',
    '    atomicMin(&atom[17], encOrd(rw));',
    '    atomicMax(&atom[18], encOrd(rw));',
    '  }',
    '  // moment partials (raw moments; host converts to the same statistics',
    '  // _mcTraceFromRays computes two-pass — identical algebra):',
    '  var w0 = 0.0;',
    '  var u0 = 0.0;',
    '  var wf = 0.0;',
    '  if (alive) {',
    '    w0 = rw;',
    '    u0 = 1.0;',
    '    if (rtag == 3u) { wf = rw; }',
    '  }',
    '  var dh = 0.0;',
    '  var dv = 0.0;',
    '  if (alive) {',
    '    let ivz2 = 1.0 / vz;',
    '    dh = rvx * ivz2;',
    '    dv = rvy * ivz2;',
    '  }',
    '  let m0  = wgSum(w0, lid);',
    '  let m1  = wgSum(w0 * rx, lid);',
    '  let m2  = wgSum(w0 * ry, lid);',
    '  let m3  = wgSum(w0 * rx * rx, lid);',
    '  let m4  = wgSum(w0 * ry * ry, lid);',
    '  let m5  = wgSum(wf, lid);',
    '  let m6  = wgSum(wf * rx, lid);',
    '  let m7  = wgSum(wf * ry, lid);',
    '  let m8  = wgSum(wf * rx * rx, lid);',
    '  let m9  = wgSum(wf * ry * ry, lid);',
    '  let m10 = wgSum(w0 * dh, lid);',
    '  let m11 = wgSum(w0 * dv, lid);',
    '  let m12 = wgSum(w0 * dh * dh, lid);',
    '  let m13 = wgSum(w0 * dv * dv, lid);',
    '  let m14 = wgSum(u0 * dh, lid);',
    '  let m15 = wgSum(u0 * dv, lid);',
    '  let m16 = wgSum(u0 * dh * dh, lid);',
    '  let m17 = wgSum(u0 * dv * dv, lid);',
    '  if (lid == 0u) {',
    '    let db = regBoff(nwg3.x) + 2u * nwg3.x + wid3.x * 18u;',
    '    partials[db] = m0;   partials[db + 1u] = m1;   partials[db + 2u] = m2;',
    '    partials[db + 3u] = m3;   partials[db + 4u] = m4;   partials[db + 5u] = m5;',
    '    partials[db + 6u] = m6;   partials[db + 7u] = m7;   partials[db + 8u] = m8;',
    '    partials[db + 9u] = m9;   partials[db + 10u] = m10; partials[db + 11u] = m11;',
    '    partials[db + 12u] = m12; partials[db + 13u] = m13; partials[db + 14u] = m14;',
    '    partials[db + 15u] = m15; partials[db + 16u] = m16; partials[db + 17u] = m17;',
    '  }',
    '}',
    '',
    '// ===== PASS 4: weighted histograms (fixed-point u32, deterministic) =====',
    '// layout: [0, G*G) hist2d | [G*G, +G) margH | [+G, +G) margV |',
    '//         [.., +GF) fineH | [.., +GF) fineV',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn final_hist(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let i = gid.x;',
    '  if (i >= P.nR) { return; }',
    '  let o = i * 8u;',
    '  let w = raysOut[o + 5u];',
    '  if (w <= 0.0) { return; }',
    '  let x = raysOut[o];',
    '  let y = raysOut[o + 1u];',
    '  let tag = u32(raysOut[o + 7u]);',
    '  let wq = u32(w * U.f5.z + 0.5);',
    '  let G = i32(U.u3.z);',
    '  let fH = U.f3.w;',
    '  let fV = U.f4.x;',
    '  let xi = i32(floor((x - U.f4.y + fH) / (2.0 * fH) * f32(G)));',
    '  let yi = i32(floor((y - U.f4.z + fV) / (2.0 * fV) * f32(G)));',
    '  if (xi >= 0 && xi < G && yi >= 0 && yi < G) {',
    '    atomicAdd(&histbuf[u32(yi * G + xi)], wq);',
    '    atomicAdd(&histbuf[u32(G * G + xi)], wq);',
    '    atomicAdd(&histbuf[u32(G * G + G + yi)], wq);',
    '  }',
    '  if (U.u3.x != 0u) {',
    '    var sel = true;',
    '    if (U.u3.y != 0u) { sel = (tag == 3u); }',
    '    if (sel) {',
    '      let GF = i32(U.u3.w);',
    '      let fF = U.f4.w;',
    '      let fb = u32(G * G + 2 * G);',
    '      let fxi = i32(floor((x - U.f5.x + fF) / (2.0 * fF) * f32(GF)));',
    '      let fyi = i32(floor((y - U.f5.y + fF) / (2.0 * fF) * f32(GF)));',
    '      if (fxi >= 0 && fxi < GF) { atomicAdd(&histbuf[fb + u32(fxi)], wq); }',
    '      if (fyi >= 0 && fyi < GF) { atomicAdd(&histbuf[fb + u32(GF) + u32(fyi)], wq); }',
    '    }',
    '  }',
    '}',
    '',
    '// ===== conic precision self-test: rays[o]=posKb, rays[o+1]=angIn =====',
    '@compute @workgroup_size(' + MG_WG_SIZE + ', 1, 1)',
    'fn conic_test(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let i = gid.x;',
    '  if (i >= U.u4.z) { return; }',
    '  let o = i * 8u;',
    '  let posKb = raysOut[o];',
    '  let angIn = raysOut[o + 1u];',
    '  let base = U.u4.y * DESC;',
    '  let pf = elems[base + 21u];',
    '  partials[i] = kbConic(posKb - angIn * pf, angIn, posKb, base);',
    '}',
    ''
  ].join('\n');
  return src;
}

// ===========================================================================
// Pipelines / buffers
// ===========================================================================
function _mgEnsurePipeline(device) {
  if (_mgCache.device === device && _mgCache.pipelines) return;
  _mgCache.device = device;
  _mgCache.bufferKey = '';
  _mgCache.buffers = null;
  _mgCache.optconstWritten = false;
  _mgCache.psiCrystal = '';
  var mod = device.createShaderModule({ code: _mgBuildWGSL() });
  _mgCache.module = mod;
  var bgl = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 5, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 6, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      { binding: 7, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 8, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 9, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } }
    ]
  });
  _mgCache.bgl = bgl;
  var layout = device.createPipelineLayout({ bindGroupLayouts: [bgl] });
  function mk(entry) {
    return device.createComputePipeline({ layout: layout, compute: { module: mod, entryPoint: entry } });
  }
  _mgCache.pipelines = {
    trace: mk('mc_trace'),
    foot: mk('foot_hist'),
    pass2: mk('mc_pass2'),
    pass3: mk('mc_pass3'),
    fhist: mk('final_hist'),
    conic: mk('conic_test')
  };
}

function _mgHistWords(grid) {
  return grid * grid + 2 * grid + 2 * MG_FINE_GRID;
}

function _mgEnsureBuffers(device, nR, grid) {
  var numWG = Math.ceil(nR / MG_WG_SIZE);
  var key = nR + '_' + grid;
  if (_mgCache.bufferKey === key && _mgCache.buffers) return _mgCache.buffers;
  if (_mgCache.buffers) {
    var old = _mgCache.buffers;
    var names = ['params', 'p2u', 'elems', 'rays', 'partials', 'atom', 'histf',
      'rbPart', 'rbAtom', 'rbHist', 'rbRays'];
    for (var ni = 0; ni < names.length; ni++) {
      if (old[names[ni]]) { try { old[names[ni]].destroy(); } catch (e) {} }
    }
    // optconst / psi / cdf survive (content static per crystal / per run)
  }
  var raysBytes = nR * MG_RAY_STRIDE * 4;
  var partFloats = (MG_MAX_ELEMS * 5 + 2 + 18) * numWG;
  var partBytes = partFloats * 4;
  var histBytes = _mgHistWords(grid) * 4;
  var bufs = _mgCache.buffers && _mgCache.buffers.optconst ? _mgCache.buffers : {};
  bufs.params = device.createBuffer({ size: 64, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  bufs.p2u = device.createBuffer({ size: 192, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  bufs.elems = device.createBuffer({ size: MG_MAX_ELEMS * MG_DESC_STRIDE * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
  if (!bufs.optconst) {
    bufs.optconst = device.createBuffer({ size: 3 * 2 * MG_TBL_N * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
    bufs.psi = device.createBuffer({ size: 6 * MG_TBL_N * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
    bufs.cdf = device.createBuffer({ size: 4 * MG_CDF_SEG * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
  }
  bufs.rays = device.createBuffer({ size: raysBytes, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST });
  bufs.partials = device.createBuffer({ size: partBytes, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC });
  bufs.atom = device.createBuffer({ size: MG_ATOM_WORDS * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST });
  bufs.histf = device.createBuffer({ size: histBytes, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST });
  bufs.rbPart = device.createBuffer({ size: partBytes, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
  bufs.rbAtom = device.createBuffer({ size: MG_ATOM_WORDS * 4, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
  bufs.rbHist = device.createBuffer({ size: histBytes, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
  bufs.rbRays = null;            // lazily created for hybrid mode only
  bufs.numWG = numWG;
  bufs.grid = grid;
  bufs.bindGroup = device.createBindGroup({
    layout: _mgCache.bgl,
    entries: [
      { binding: 0, resource: { buffer: bufs.params } },
      { binding: 1, resource: { buffer: bufs.elems } },
      { binding: 2, resource: { buffer: bufs.optconst } },
      { binding: 3, resource: { buffer: bufs.psi } },
      { binding: 4, resource: { buffer: bufs.rays } },
      { binding: 5, resource: { buffer: bufs.partials } },
      { binding: 6, resource: { buffer: bufs.p2u } },
      { binding: 7, resource: { buffer: bufs.cdf } },
      { binding: 8, resource: { buffer: bufs.atom } },
      { binding: 9, resource: { buffer: bufs.histf } }
    ]
  });
  _mgCache.bufferKey = key;
  _mgCache.buffers = bufs;
  return bufs;
}

function _mgEnsureRaysReadback(device, bufs, nR) {
  var raysBytes = nR * MG_RAY_STRIDE * 4;
  if (bufs.rbRays && bufs.rbRaysBytes === raysBytes) return bufs.rbRays;
  if (bufs.rbRays) { try { bufs.rbRays.destroy(); } catch (e) {} }
  bufs.rbRays = device.createBuffer({ size: raysBytes, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
  bufs.rbRaysBytes = raysBytes;
  return bufs.rbRays;
}

function _mgWriteStaticTables(device, bufs, crystal) {
  if (!_mgCache.optconstWritten) {
    if (typeof OPTCONST_TABLES === 'undefined') throw new Error('OPTCONST_TABLES missing');
    var oc = new Float32Array(3 * 2 * MG_TBL_N);
    var mats = ['Rh', 'Pt', 'Si'];
    var m, k, t;
    for (m = 0; m < 3; m++) {
      t = OPTCONST_TABLES[mats[m]];
      if (!t || !t.ZF1 || t.ZF1.length !== MG_TBL_N) throw new Error('optconst table ' + mats[m] + ' shape');
      for (k = 0; k < MG_TBL_N; k++) {
        oc[(m * 2) * MG_TBL_N + k] = t.ZF1[k];
        oc[(m * 2 + 1) * MG_TBL_N + k] = t.ZF2[k];
      }
    }
    device.queue.writeBuffer(bufs.optconst, 0, oc);
    _mgCache.optconstWritten = true;
  }
  if (_mgCache.psiCrystal !== crystal) {
    var tbl = (crystal === '311') ? SI311_PSI : SI111_PSI;
    var comps = ['psi0_re', 'psi0_im', 'psiH_re', 'psiH_im', 'psiHb_re', 'psiHb_im'];
    var psi = new Float32Array(6 * MG_TBL_N);
    var ci, j, arr;
    for (ci = 0; ci < 6; ci++) {
      arr = tbl[comps[ci]];
      if (!arr || arr.length !== MG_TBL_N) throw new Error('psi table ' + comps[ci] + ' shape');
      for (j = 0; j < MG_TBL_N; j++) psi[ci * MG_TBL_N + j] = arr[j];
    }
    device.queue.writeBuffer(bufs.psi, 0, psi);
    _mgCache.psiCrystal = crystal;
  }
}

function _mgBuildUniform(prep, nElem) {
  var buf = new ArrayBuffer(64);
  var f = new Float32Array(buf, 0, 12);
  var u = new Uint32Array(buf, 48, 4);
  f[0] = prep.E_eV_center;
  f[1] = prep.srcBW;
  f[2] = prep.ps.Sx;
  f[3] = prep.ps.Sy;
  f[4] = prep.ps.Sxp;
  f[5] = prep.ps.Syp;
  f[6] = prep.wbHalfAngH;
  f[7] = prep.wbHalfAngV;
  f[8] = prep.und_Epeak;
  f[9] = prep.eSpread;
  f[10] = prep.nPeriods;
  f[11] = 0;
  u[0] = prep.nR >>> 0;
  u[1] = nElem >>> 0;
  u[2] = (Math.random() * 4294967296) >>> 0;   // fresh seed per run (independent runs, like Math.random on CPU)
  u[3] = (prep.isWB ? 1 : 0) | (prep.und_Epeak > 1 ? 2 : 0);
  return new Uint8Array(buf);
}

// Host mirror of the P2U uniform (see WGSL struct comment).
function _mgP2UNew() {
  var buf = new ArrayBuffer(192);
  return { buf: buf, u: new Uint32Array(buf, 0, 20), f: new Float32Array(buf, 80, 24) };
}
// f-index helper: f0..f5 are float vec4s starting at byte 80 -> f[seg*4+lane]

// Ordered-u32 decode (host side, matches WGSL decOrd)
var _mgDecScratchF = new Float32Array(1);
var _mgDecScratchU = new Uint32Array(_mgDecScratchF.buffer);
function _mgDecOrd(u) {
  u = u >>> 0;
  if ((u & 0x80000000) !== 0) _mgDecScratchU[0] = (u ^ 0x80000000) >>> 0;
  else _mgDecScratchU[0] = (~u) >>> 0;
  return _mgDecScratchF[0];
}

// Sum a partials region in f64 on the host.
function _mgSumRegion(arr, base, count, stride, lane) {
  var s = 0;
  for (var i = 0; i < count; i++) s += arr[base + i * stride + lane];
  return s;
}

// elementTrace entries from snapshot partials (same fields as the CPU
// per-element snapshot; raw-moment sigma — identical algebra).
function _mgTraceEntries(partF32, elems0, idx0, count, numWG, nR) {
  var out = [];
  for (var e = 0; e < count; e++) {
    var eg = idx0 + e;
    var sw = 0, swx = 0, swy = 0, sxx = 0, syy = 0;
    for (var wg = 0; wg < numWG; wg++) {
      var b = (eg * numWG + wg) * 5;
      sw += partF32[b];
      swx += partF32[b + 1];
      swy += partF32[b + 2];
      sxx += partF32[b + 3];
      syy += partF32[b + 4];
    }
    var sH = 0, sV = 0;
    if (sw > 0) {
      var mx = swx / sw, my = swy / sw;
      sH = Math.sqrt(Math.max(0, sxx / sw - mx * mx));
      sV = Math.sqrt(Math.max(0, syy / sw - my * my));
    }
    var ce = elems0[e];
    out.push({ id: ce.id, name: ce.name || ce.id, tp: ce.tp, dist: ce.p,
      T_cum: sw / nR, sigH: sH, sigV: sV });
  }
  return out;
}

// Wavefront mode decision + CDF upload prep for one axis. Mirrors the CPU
// control flow of _applySSAHybrid / _applyHybridFresnel + _hybridFF1D +
// _inverseCdfSample EXACTLY (same functions where collective).
// Returns {mode, xMin, dx, n, cdfF32}
function _mgAxisWavefront(hist, nAliveAxis, zMin, zMax, D, lam) {
  // _hybridFF1D degenerate cases -> zeros array (mode 3)
  if (!(D >= 1e-12) || nAliveAxis < 3) return { mode: 3, xMin: 0, dx: 0, n: 0, cdfF32: null };
  if (!(zMax - zMin >= 1e-15)) return { mode: 3, xMin: 0, dx: 0, n: 0, cdfF32: null };
  var nBins = Math.min(200, Math.round(nAliveAxis / 20));
  if (nBins < 10) nBins = 10;
  var prof = window._hybridProfile1D(hist, nBins, zMin, zMax, D, lam);
  if (!prof) return { mode: 3, xMin: 0, dx: 0, n: 0, cdfF32: null };
  var built = window._cdfBuild(prof.intensity, prof.nPts);
  if (!built.ok) {
    // CPU: uniform sampling over [angMin, angMax]
    return { mode: 2, xMin: prof.angMin, dx: prof.angMax - prof.angMin, n: 0, cdfF32: null };
  }
  var n = prof.nPts;
  if (n > MG_CDF_SEG) n = MG_CDF_SEG;   // cannot exceed (FFT cap 131072)
  var cdfF32 = new Float32Array(n);
  for (var i = 0; i < n; i++) cdfF32[i] = built.cdf[i];
  var dx = (n > 1) ? (prof.angMax - prof.angMin) / (prof.nPts - 1) : 0;
  return { mode: 1, xMin: prof.angMin, dx: dx, n: n, cdfF32: cdfF32 };
}

// ===========================================================================
// Conic precision self-test (gates full mode; see header). Compares the GPU
// pole-frame f32 conic against the CPU f64 _kbConicAngle on identical f32
// inputs spanning the full mirror aperture; error is expressed as
// sample-plane position error (delta-angle * q).
// ===========================================================================
function _mgConicKeyOf(prep) {
  var arr = [];
  for (var id in prep.kbMeta) {
    if (!prep.kbMeta.hasOwnProperty(id)) continue;
    var m = prep.kbMeta[id];
    if (m.useConic) arr.push([m.cc1, m.cc2, m.cc4, m.cc8, m.sinTg, m.cKB, m.pDist, m.qDist]);
  }
  return arr.length ? JSON.stringify(arr) : '';
}

function _mgRunConicTest(prep, nTest) {
  var device = window._GPU.device;
  _mgEnsurePipeline(device);
  var grid = (typeof MC_GRID !== 'undefined') ? MC_GRID : 101;
  // partials must hold nTest f32 results: (MAXE*5+20)*ceil(N/256) >= nTest
  // holds for N >= 2*nTest; use 4*nTest for margin.
  var needN = Math.max(prep.nR, 4 * nTest);
  var bufs = _mgEnsureBuffers(device, needN, grid);
  var results = {};
  var seq = Promise.resolve();
  var n1 = prep.descs.length + (prep.ssaDesc ? 1 : 0);
  // elems buffer must contain the descs (also written again by the run)
  _mgWriteElems(device, bufs, prep);

  function testOne(kbIdx, meta) {
    return function () {
      var inputs = new Float32Array(nTest * MG_RAY_STRIDE);
      var i, posKb, src, ang;
      var apHalf = meta.halfLen * meta.sinTg * 0.999;
      for (i = 0; i < nTest; i++) {
        posKb = (Math.random() * 2 - 1) * apHalf;
        src = (Math.random() * 2 - 1) * 50e-6;
        ang = (posKb - src) / meta.pDist + (Math.random() * 2 - 1) * 2e-6;
        inputs[i * MG_RAY_STRIDE] = posKb;
        inputs[i * MG_RAY_STRIDE + 1] = ang;
      }
      device.queue.writeBuffer(bufs.rays, 0, inputs);
      var p2u = _mgP2UNew();
      p2u.u[16] = 0;                       // histMode (unused)
      p2u.u[17] = kbIdx >>> 0;             // conic desc global index
      p2u.u[18] = nTest >>> 0;
      device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);
      var enc = device.createCommandEncoder();
      var pass = enc.beginComputePass();
      pass.setPipeline(_mgCache.pipelines.conic);
      pass.setBindGroup(0, bufs.bindGroup);
      pass.dispatchWorkgroups(Math.ceil(nTest / MG_WG_SIZE), 1, 1);
      pass.end();
      enc.copyBufferToBuffer(bufs.partials, 0, bufs.rbPart, 0, nTest * 4);
      device.queue.submit([enc.finish()]);
      return bufs.rbPart.mapAsync(GPUMapMode.READ).then(function () {
        var got = new Float32Array(bufs.rbPart.getMappedRange(0, nTest * 4).slice(0));
        bufs.rbPart.unmap();
        var se = 0, mx = 0, j;
        for (j = 0; j < nTest; j++) {
          var pk = inputs[j * MG_RAY_STRIDE];
          var an = inputs[j * MG_RAY_STRIDE + 1];
          var ref = _kbConicAngle(pk - an * meta.pDist, an, pk,
            meta.cc1, meta.cc2, meta.cc4, meta.cc8, meta.sinTg, meta.cKB,
            meta.pDist, meta.qDist);
          var err = (got[j] - ref) * meta.qDist;   // sample-plane position error [m]
          se += err * err;
          if (Math.abs(err) > mx) mx = Math.abs(err);
        }
        results[meta.kbId] = {
          rms_nm: Math.sqrt(se / nTest) * 1e9,
          max_nm: mx * 1e9,
          n: nTest
        };
      });
    };
  }

  for (var k = 0; k < prep.p2Descs.length; k++) {
    if (prep.p2Descs[k][0] === MG_OP_KB && prep.p2Descs[k][16] > 0.5) {
      var meta2 = prep.kbMeta[prep.p2Elems[k].id];
      seq = seq.then(testOne(n1 + k, meta2));
    }
  }
  return seq.then(function () {
    var ok = true, worst = 0;
    for (var id in results) {
      if (!results.hasOwnProperty(id)) continue;
      if (results[id].rms_nm >= 1.0) ok = false;
      if (results[id].rms_nm > worst) worst = results[id].rms_nm;
    }
    return { ok: ok, worst_rms_nm: worst, perMirror: results };
  });
}

// Public conic-test API (used by the validation harness).
window._mcGpuConicTest = function (nTest) {
  nTest = nTest || 4096;
  var run = function () {
    var prep;
    try { prep = _mgPrep(pos('sample'), nTest); } catch (e) {
      return Promise.resolve({ ok: false, reason: 'prep threw: ' + (e && e.message ? e.message : String(e)) });
    }
    if (!prep.ok) return Promise.resolve({ ok: false, reason: prep.reason });
    if (!prep.fullOk) return Promise.resolve({ ok: false, reason: prep.fullReason });
    if (!_mgConicKeyOf(prep)) return Promise.resolve({ ok: false, reason: 'no conic KB in chain' });
    if (typeof detectWebGPU !== 'function') return Promise.resolve({ ok: false, reason: 'webgpu detect missing' });
    return detectWebGPU().then(function (gi) {
      if (!gi.supported || !window._GPU.device) return { ok: false, reason: 'WebGPU unavailable' };
      return _mgRunConicTest(prep, nTest);
    });
  };
  var p = _mgChain.then(run, run);
  _mgChain = p.then(function () {}, function () {});
  return p;
};

// ===========================================================================
// Element-buffer writer: prefix descs [0..n0), ssa desc [n0], pass-2 descs
// [n1..n1+n2) — one contiguous upload; pass selection via uniforms only.
// ===========================================================================
function _mgWriteElems(device, bufs, prep) {
  var elemArr = new Float32Array(MG_MAX_ELEMS * MG_DESC_STRIDE);
  var i, k, off = 0;
  for (i = 0; i < prep.descs.length; i++) {
    for (k = 0; k < MG_DESC_STRIDE; k++) elemArr[off + k] = prep.descs[i][k];
    off += MG_DESC_STRIDE;
  }
  if (prep.fullOk && prep.ssaDesc) {
    for (k = 0; k < MG_DESC_STRIDE; k++) elemArr[off + k] = prep.ssaDesc[k];
    off += MG_DESC_STRIDE;
  }
  if (prep.fullOk) {
    for (i = 0; i < prep.p2Descs.length; i++) {
      for (k = 0; k < MG_DESC_STRIDE; k++) elemArr[off + k] = prep.p2Descs[i][k];
      off += MG_DESC_STRIDE;
    }
  }
  device.queue.writeBuffer(bufs.elems, 0, elemArr);
}

// ===========================================================================
// FULL MODE: GPU-resident chain (4 submit/readback round trips)
// ===========================================================================
function _mgRunFull(prep) {
  var device = window._GPU.device;
  var now = function () { return (typeof performance !== 'undefined') ? performance.now() : Date.now(); };
  var stages = {};
  var t0 = now();
  _mgEnsurePipeline(device);
  var grid = (typeof MC_GRID !== 'undefined') ? MC_GRID : 101;
  var GF = MG_FINE_GRID;
  var bufs = _mgEnsureBuffers(device, prep.nR, grid);
  _mgWriteStaticTables(device, bufs, prep.crystal);
  _mgWriteElems(device, bufs, prep);

  var nR = prep.nR, td = prep.td, numWG = bufs.numWG;
  var n0 = prep.descs.length;
  var n1 = n0 + (prep.ssaDesc ? 1 : 0);
  var n2 = prep.p2Descs.length;
  var regB = MG_MAX_ELEMS * numWG * 5;
  var regC = regB + numWG;
  var regD = regB + 2 * numWG;

  device.queue.writeBuffer(bufs.params, 0, _mgBuildUniform(prep, n1));

  // pass-2/3 fixed geometry (CPU _applyHybridFresnel constants)
  var posKBV = pos('kbv'), posKBH = pos('kbh'), posSSA = pos('ssa'), posSample = pos('sample');
  var qV = (posKBV !== null && posKBV !== undefined) ? posSample - posKBV : 0;
  var qH = (posKBH !== null && posKBH !== undefined) ? posSample - posKBH : 0;
  var pV = (posKBV !== null && posSSA !== null) ? posKBV - posSSA : 0;
  var pH = (posKBH !== null && posSSA !== null) ? posKBH - posSSA : 0;
  var F_kbv = (pV > 0 && qV > 0) ? pV * qV / (pV + qV) : 0.3;
  var F_kbh = (pH > 0 && qH > 0) ? pH * qH / (pH + qH) : 0.1;

  // weighted-histogram fixed-point scale: nR * scale < 2^31 (w <= 1)
  var wShift = 31, nTmp = 1;
  while (nTmp < nR) { nTmp *= 2; wShift--; }
  if (wShift > 16) wShift = 16;
  if (wShift < 1) wShift = 1;
  var wScale = Math.pow(2, wShift);

  var p2u = _mgP2UNew();
  function fset(vec, lane, v) { p2u.f[vec * 4 + lane] = v; }
  p2u.u[0] = (Math.random() * 4294967296) >>> 0;   // seed2
  p2u.u[1] = (Math.random() * 4294967296) >>> 0;   // seed3
  p2u.u[2] = n1 >>> 0;                             // e2Base
  p2u.u[3] = n2 >>> 0;                             // e2Count
  p2u.u[12] = 0; p2u.u[13] = 0;                    // fine flags (pass 4)
  p2u.u[14] = grid >>> 0; p2u.u[15] = GF >>> 0;
  p2u.u[16] = 0;                                   // histMode = SSA
  fset(2, 0, prep.finalDrift);
  fset(2, 1, qV); fset(2, 2, qH);
  fset(2, 3, prep.ssaInfo ? prep.ssaInfo.cxO : 0);
  fset(3, 0, F_kbv); fset(3, 1, F_kbh);
  fset(3, 2, prep.ssaInfo ? prep.ssaInfo.cyO : 0);
  fset(5, 2, wScale);
  device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);

  // atomics init: counters 0, min slots 0xFFFFFFFF, max slots 0
  var atomInit = new Uint32Array(MG_ATOM_WORDS);
  var minSlots = [1, 3, 8, 10, 17];
  for (var ms = 0; ms < minSlots.length; ms++) atomInit[minSlots[ms]] = 0xFFFFFFFF;
  device.queue.writeBuffer(bufs.atom, 0, atomInit);

  var ssaPresent = !!prep.ssaDesc;
  var E_center = prep.E;
  var hasKB = prep.hasKB;
  var trace1, trace2, mom, atomU;
  var ssaAlive = 0;

  // ---------- submit A: pass 1 (+ SSA footprint histogram) ----------
  var encA = device.createCommandEncoder();
  var passA = encA.beginComputePass();
  passA.setPipeline(_mgCache.pipelines.trace);
  passA.setBindGroup(0, bufs.bindGroup);
  passA.dispatchWorkgroups(numWG, 1, 1);
  if (ssaPresent) {
    passA.setPipeline(_mgCache.pipelines.foot);
    passA.dispatchWorkgroups(numWG, 1, 1);
  }
  passA.end();
  encA.copyBufferToBuffer(bufs.atom, 0, bufs.rbAtom, 0, MG_ATOM_WORDS * 4);
  encA.copyBufferToBuffer(bufs.partials, 0, bufs.rbPart, 0, n1 * numWG * 5 * 4);
  encA.copyBufferToBuffer(bufs.partials, regB * 4, bufs.rbPart, regB * 4, numWG * 4);
  device.queue.submit([encA.finish()]);

  return Promise.all([
    bufs.rbAtom.mapAsync(GPUMapMode.READ),
    bufs.rbPart.mapAsync(GPUMapMode.READ)
  ]).then(function () {
    atomU = new Uint32Array(bufs.rbAtom.getMappedRange().slice(0));
    var partA = new Float32Array(bufs.rbPart.getMappedRange().slice(0));
    bufs.rbAtom.unmap();
    bufs.rbPart.unmap();
    stages.p1 = now() - t0;
    var tW = now();

    trace1 = _mgTraceEntries(partA, prep.gpuElems.concat(prep.ssaElem ? [prep.ssaElem] : []),
      0, n1, numWG, nR);

    // ---- CPU collective wavefront: SSA hybrid (engine-owned code) ----
    var modeH = { mode: 0, xMin: 0, dx: 0, n: 0, cdfF32: null };
    var modeV = { mode: 0, xMin: 0, dx: 0, n: 0, cdfF32: null };
    ssaAlive = atomU[0] >>> 0;
    if (ssaPresent && ssaAlive >= 10) {
      var sumE = _mgSumRegion(partA, regB, numWG, 1, 0);
      var E_mean_keV = ssaAlive > 0 ? (sumE / ssaAlive) * 0.001 : E_center;
      var lam = HC / E_mean_keV * 1e-10;
      if (lam > 0) {
        var xMin = _mgDecOrd(atomU[1]), xMax = _mgDecOrd(atomU[2]);
        var yMin = _mgDecOrd(atomU[3]), yMax = _mgDecOrd(atomU[4]);
        var DH = xMax - xMin, DV = yMax - yMin;
        if (DH > 2 * prep.ssaInfo.hH) DH = 2 * prep.ssaInfo.hH;
        if (DV > 2 * prep.ssaInfo.hV) DV = 2 * prep.ssaInfo.hV;
        var nb = Math.min(200, Math.round(ssaAlive / 20));
        if (nb < 10) nb = 10;
        var histH = new Float64Array(nb), histV = new Float64Array(nb), bi;
        for (bi = 0; bi < nb; bi++) {
          histH[bi] = atomU[20 + bi];
          histV[bi] = atomU[20 + MG_FOOT_BINS + bi];
        }
        if (DH > 1e-10) modeH = _mgAxisWavefront(histH, ssaAlive, xMin, xMax, DH, lam);
        if (DV > 1e-10) modeV = _mgAxisWavefront(histV, ssaAlive, yMin, yMax, DV, lam);
      }
    }
    if (modeH.cdfF32) device.queue.writeBuffer(bufs.cdf, 0, modeH.cdfF32);
    if (modeV.cdfF32) device.queue.writeBuffer(bufs.cdf, MG_CDF_SEG * 4, modeV.cdfF32);
    p2u.u[4] = modeH.mode; p2u.u[5] = modeV.mode;
    p2u.u[8] = modeH.n >>> 0; p2u.u[9] = modeV.n >>> 0;
    fset(0, 0, modeH.xMin); fset(0, 1, modeV.xMin);
    fset(1, 0, modeH.dx); fset(1, 1, modeV.dx);
    p2u.u[16] = 1;   // histMode = KB for the pass-2b foot_hist
    device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);
    stages.wf1 = now() - tW;

    // ---------- submit B: pass 2 (+ KB footprint histograms) ----------
    var tB = now();
    var encB = device.createCommandEncoder();
    var passB = encB.beginComputePass();
    passB.setPipeline(_mgCache.pipelines.pass2);
    passB.setBindGroup(0, bufs.bindGroup);
    passB.dispatchWorkgroups(numWG, 1, 1);
    if (hasKB) {
      passB.setPipeline(_mgCache.pipelines.foot);
      passB.dispatchWorkgroups(numWG, 1, 1);
    }
    passB.end();
    encB.copyBufferToBuffer(bufs.atom, 0, bufs.rbAtom, 0, MG_ATOM_WORDS * 4);
    if (n2 > 0) {
      encB.copyBufferToBuffer(bufs.partials, n1 * numWG * 5 * 4, bufs.rbPart, n1 * numWG * 5 * 4, n2 * numWG * 5 * 4);
    }
    encB.copyBufferToBuffer(bufs.partials, regC * 4, bufs.rbPart, regC * 4, numWG * 4);
    device.queue.submit([encB.finish()]);
    return Promise.all([
      bufs.rbAtom.mapAsync(GPUMapMode.READ),
      bufs.rbPart.mapAsync(GPUMapMode.READ)
    ]).then(function () { stages.p2 = now() - tB; });
  }).then(function () {
    atomU = new Uint32Array(bufs.rbAtom.getMappedRange().slice(0));
    var partB = new Float32Array(bufs.rbPart.getMappedRange().slice(0));
    bufs.rbAtom.unmap();
    bufs.rbPart.unmap();
    var tW = now();

    trace2 = _mgTraceEntries(partB, prep.p2Elems, n1, n2, numWG, nR);

    // ---- CPU collective wavefront: KB Fresnel hybrid ----
    var frV = { mode: 0, xMin: 0, dx: 0, n: 0, cdfF32: null };
    var frH = { mode: 0, xMin: 0, dx: 0, n: 0, cdfF32: null };
    var aliveP2 = atomU[5] >>> 0;
    var aliveV = atomU[6] >>> 0;
    var aliveH = atomU[7] >>> 0;
    // CPU gating: hasKB && td > 149 && alive >= 10 (+ per-axis >= 10)
    if (hasKB && td > 149 && !(td < 148) && aliveP2 >= 10) {
      var sumE2 = _mgSumRegion(partB, regC, numWG, 1, 0);
      var E_mean2 = (sumE2 / aliveP2) * 0.001;
      var lam2 = HC / E_mean2 * 1e-10;
      if (lam2 > 0) {
        var bi2, nbV, nbH;
        if (aliveV >= 10) {
          var yMin2 = _mgDecOrd(atomU[8]), yMax2 = _mgDecOrd(atomU[9]);
          nbV = Math.min(200, Math.round(aliveV / 20));
          if (nbV < 10) nbV = 10;
          var histKV = new Float64Array(nbV);
          for (bi2 = 0; bi2 < nbV; bi2++) histKV[bi2] = atomU[20 + 2 * MG_FOOT_BINS + bi2];
          frV = _mgAxisWavefront(histKV, aliveV, yMin2, yMax2, yMax2 - yMin2, lam2);
        }
        if (aliveH >= 10) {
          var xMin2 = _mgDecOrd(atomU[10]), xMax2 = _mgDecOrd(atomU[11]);
          nbH = Math.min(200, Math.round(aliveH / 20));
          if (nbH < 10) nbH = 10;
          var histKH = new Float64Array(nbH);
          for (bi2 = 0; bi2 < nbH; bi2++) histKH[bi2] = atomU[20 + 3 * MG_FOOT_BINS + bi2];
          frH = _mgAxisWavefront(histKH, aliveH, xMin2, xMax2, xMax2 - xMin2, lam2);
        }
      }
    }
    if (frV.cdfF32) device.queue.writeBuffer(bufs.cdf, 2 * MG_CDF_SEG * 4, frV.cdfF32);
    if (frH.cdfF32) device.queue.writeBuffer(bufs.cdf, 3 * MG_CDF_SEG * 4, frH.cdfF32);
    p2u.u[6] = frV.mode; p2u.u[7] = frH.mode;
    p2u.u[10] = frV.n >>> 0; p2u.u[11] = frH.n >>> 0;
    fset(0, 2, frV.xMin); fset(0, 3, frH.xMin);
    fset(1, 2, frV.dx); fset(1, 3, frH.dx);
    device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);
    stages.wf2 = now() - tW;

    // ---------- submit C: pass 3 (Fresnel apply + moments) ----------
    var tC = now();
    var encC = device.createCommandEncoder();
    var passC = encC.beginComputePass();
    passC.setPipeline(_mgCache.pipelines.pass3);
    passC.setBindGroup(0, bufs.bindGroup);
    passC.dispatchWorkgroups(numWG, 1, 1);
    passC.end();
    encC.copyBufferToBuffer(bufs.atom, 0, bufs.rbAtom, 0, MG_ATOM_WORDS * 4);
    encC.copyBufferToBuffer(bufs.partials, regD * 4, bufs.rbPart, regD * 4, numWG * 18 * 4);
    device.queue.submit([encC.finish()]);
    return Promise.all([
      bufs.rbAtom.mapAsync(GPUMapMode.READ),
      bufs.rbPart.mapAsync(GPUMapMode.READ)
    ]).then(function () { stages.p3 = now() - tC; });
  }).then(function () {
    atomU = new Uint32Array(bufs.rbAtom.getMappedRange().slice(0));
    var partC = new Float32Array(bufs.rbPart.getMappedRange().slice(0));
    bufs.rbAtom.unmap();
    bufs.rbPart.unmap();
    var tH = now();

    var elementTrace = trace1.concat(trace2);
    var tagCounts = [atomU[12] >>> 0, atomU[13] >>> 0, atomU[14] >>> 0, atomU[15] >>> 0];
    var nSurvived = atomU[16] >>> 0;

    if (nSurvived < 10) {
      // CPU early-return shape (al.length < 10)
      stages.host3 = now() - tH;
      stages.total = now() - t0;
      return {
        hist2d: null, margH: null, margV: null, grid: grid,
        nSurvived: 0, nTotal: nR, sigH: 1e-6, sigV: 1e-6,
        fwhmH: 2.355e-6, fwhmV: 2.355e-6, fovH: 1e-5, fovV: 1e-5,
        nBeams: { direct: 0, vOnly: 0, hOnly: 0, focused: 0 },
        elementTrace: elementTrace,
        _gpu: { engine: 'webgpu', mode: 'full', stages: stages,
          gpuMs: (stages.p1 || 0) + (stages.p2 || 0) + (stages.p3 || 0),
          contMs: (stages.wf1 || 0) + (stages.wf2 || 0) + (stages.host3 || 0),
          totalMs: stages.total, adapter: window._GPU.adapter_info || null }
      };
    }

    // host f64 reduction of the 18 moment sums
    mom = new Float64Array(18);
    for (var wg = 0; wg < numWG; wg++) {
      var b = regD + wg * 18;
      for (var mi = 0; mi < 18; mi++) mom[mi] += partC[b + mi];
    }
    var sw = mom[0], mx = sw > 0 ? mom[1] / sw : 0, my = sw > 0 ? mom[2] / sw : 0;
    // focused-only set selection (CPU: hasKB && tagCounts[3] > 10)
    var useFocused = hasKB && tagCounts[3] > 10;
    var sw_f = useFocused ? mom[5] : sw;
    var mx_f = useFocused ? (sw_f > 0 ? mom[6] / sw_f : 0) : mx;
    var my_f = useFocused ? (sw_f > 0 ? mom[7] / sw_f : 0) : my;
    var ex2 = useFocused ? mom[8] : mom[3];
    var ey2 = useFocused ? mom[9] : mom[4];
    var sH = sw_f > 0 ? Math.sqrt(Math.max(0, ex2 / sw_f - mx_f * mx_f)) : 0;
    var sV = sw_f > 0 ? Math.sqrt(Math.max(0, ey2 / sw_f - my_f * my_f)) : 0;
    // divergence statistics (weighted + unweighted; same algebra raw-moment form)
    var divSw = sw, udivN = nSurvived;
    var divHm = divSw > 0 ? mom[10] / divSw : 0;
    var divVm = divSw > 0 ? mom[11] / divSw : 0;
    var sigDivH = divSw > 0 ? Math.sqrt(Math.max(0, mom[12] / divSw - divHm * divHm)) : 0;
    var sigDivV = divSw > 0 ? Math.sqrt(Math.max(0, mom[13] / divSw - divVm * divVm)) : 0;
    var udivHm = udivN > 0 ? mom[14] / udivN : 0;
    var udivVm = udivN > 0 ? mom[15] / udivN : 0;
    var usigDivH = udivN > 1 ? Math.sqrt(Math.max(0, mom[16] / udivN - udivHm * udivHm)) : 0;
    var usigDivV = udivN > 1 ? Math.sqrt(Math.max(0, mom[17] / udivN - udivVm * udivVm)) : 0;
    var wMin = _mgDecOrd(atomU[17]), wMax = _mgDecOrd(atomU[18]);
    var wMean = nSurvived > 0 ? sw / nSurvived : 0;
    var wSumFocused = (hasKB && tagCounts[3] > 0) ? mom[5] : 0;

    // FOV decision (same logic as _mcTraceFromRays; full mode is gated to
    // the sample plane so the post-sample auto-FOV branch is unreachable)
    var samplePos = pos('sample') || 150;
    var screenFov;
    if (prep.isWB) { screenFov = 5e-3; }
    else if (td > samplePos + 0.01) { screenFov = 1e-3; }
    else if (td > samplePos - 0.05) { screenFov = 0.15e-6; }
    else if (td > (pos('kbv') || 149.69) - 0.01) { screenFov = 0.5e-3; }
    else if (td > (pos('kbv') || 149.69) - 1) { screenFov = 2.5e-3; }
    else if (td > (pos('xbpm3') || 140) - 1) { screenFov = 5e-3; }
    else if (td > 50) { screenFov = 0.075e-3; }
    else { screenFov = 1.5e-3; }
    var fH = screenFov, fV = screenFov;
    var _bpmFixedFov = null;
    if (typeof CD !== 'undefined') {
      for (var _ci = 0; _ci < CD.length; _ci++) {
        if (CD[_ci].tp === 'bpm' && CD[_ci].optics && CD[_ci].optics.fov) {
          var _bpmPos = (typeof pos === 'function') ? pos(CD[_ci].id) : CD[_ci].dp;
          if (Math.abs(_bpmPos - td) < 0.5) { _bpmFixedFov = CD[_ci].optics.fov; break; }
        }
      }
    }
    if (_bpmFixedFov) { fH = _bpmFixedFov; fV = _bpmFixedFov; }
    var cxS = (typeof window._alignBpmCenter === 'number') ? window._alignBpmCenter : 0;
    var cyS = 0;
    var fineOn = (td > samplePos - 0.05 && td < samplePos + 0.5 && nSurvived > 50);
    var fFH = fineOn ? 0.15e-6 : 0;

    p2u.u[12] = fineOn ? 1 : 0;
    p2u.u[13] = useFocused ? 1 : 0;
    fset(3, 3, fH);
    fset(4, 0, fV); fset(4, 1, cxS); fset(4, 2, cyS); fset(4, 3, fFH);
    fset(5, 0, mx_f); fset(5, 1, my_f);
    device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);
    stages.host3 = now() - tH;

    // ---------- submit D: pass 4 (weighted histograms) ----------
    var tD = now();
    var encD = device.createCommandEncoder();
    encD.clearBuffer(bufs.histf);
    var passD = encD.beginComputePass();
    passD.setPipeline(_mgCache.pipelines.fhist);
    passD.setBindGroup(0, bufs.bindGroup);
    passD.dispatchWorkgroups(numWG, 1, 1);
    passD.end();
    encD.copyBufferToBuffer(bufs.histf, 0, bufs.rbHist, 0, _mgHistWords(grid) * 4);
    device.queue.submit([encD.finish()]);
    return bufs.rbHist.mapAsync(GPUMapMode.READ).then(function () {
      var histU = new Uint32Array(bufs.rbHist.getMappedRange().slice(0));
      bufs.rbHist.unmap();
      stages.p4 = now() - tD;
      var tA2 = now();

      var G = grid, inv = 1 / wScale;
      var h2 = new Float64Array(G * G), mH2 = new Float64Array(G), mV2 = new Float64Array(G);
      var i2;
      for (i2 = 0; i2 < G * G; i2++) h2[i2] = histU[i2] * inv;
      for (i2 = 0; i2 < G; i2++) {
        mH2[i2] = histU[G * G + i2] * inv;
        mV2[i2] = histU[G * G + G + i2] * inv;
      }
      var fmH = null, fmV = null;
      if (fineOn) {
        fmH = new Float64Array(GF);
        fmV = new Float64Array(GF);
        for (i2 = 0; i2 < GF; i2++) {
          fmH[i2] = histU[G * G + 2 * G + i2] * inv;
          fmV[i2] = histU[G * G + 2 * G + GF + i2] * inv;
        }
      }
      var fwH, fwV;
      if (fineOn) {
        fwH = _margFwhm(fmH, GF, fFH);
        fwV = _margFwhm(fmV, GF, fFH);
      } else {
        fwH = _margFwhm(mH2, G, fH);
        fwV = _margFwhm(mV2, G, fV);
      }
      stages.assemble = now() - tA2;
      stages.total = now() - t0;
      var gpuMs = (stages.p1 || 0) + (stages.p2 || 0) + (stages.p3 || 0) + (stages.p4 || 0);
      var contMs = (stages.wf1 || 0) + (stages.wf2 || 0) + (stages.host3 || 0) + (stages.assemble || 0);
      return {
        hist2d: h2, margH: mH2, margV: mV2, grid: G,
        nSurvived: nSurvived, nTotal: nR, meanH: mx_f, meanV: my_f,
        sigH: sH, sigV: sV, fwhmH: fwH, fwhmV: fwV, fovH: fH, fovV: fV,
        meanX: mx_f, meanY: my_f,
        sigDivH: sigDivH, sigDivV: sigDivV, usigDivH: usigDivH, usigDivV: usigDivV,
        wMin: wMin, wMax: wMax, wMean: wMean, wSumFocused: wSumFocused,
        fineMargH: fmH, fineMargV: fmV, fineFovH: fFH, fineFovV: fFH, fineGrid: GF,
        nBeams: { direct: tagCounts[0], vOnly: tagCounts[1], hOnly: tagCounts[2], focused: tagCounts[3] },
        elementTrace: elementTrace,
        _aliveRays: null,   // full mode keeps rays on the GPU (documented)
        _gpu: {
          engine: 'webgpu', mode: 'full',
          nGpuElems: n1 + n2, gpuEndP: prep.fullEndP,
          gpuMs: gpuMs, contMs: contMs, totalMs: stages.total,
          stages: stages,
          adapter: window._GPU.adapter_info || null
        }
      };
    });
  });
}

// ===========================================================================
// HYBRID MODE (phase 1): GPU source->pre-SSA segment, per-ray readback,
// CPU continuation via the engine's own _mcTraceFromRays. Used for non-
// sample-plane targets and as the fallback when full mode is unsupported.
// ===========================================================================
function _mgRunHybrid(prep) {
  var device = window._GPU.device;
  var t0 = (typeof performance !== 'undefined') ? performance.now() : Date.now();
  _mgEnsurePipeline(device);
  var grid = (typeof MC_GRID !== 'undefined') ? MC_GRID : 101;
  var bufs = _mgEnsureBuffers(device, prep.nR, grid);
  _mgWriteStaticTables(device, bufs, prep.crystal);
  _mgWriteElems(device, bufs, prep);
  var rbRays = _mgEnsureRaysReadback(device, bufs, prep.nR);

  // hybrid prefix length = prep.descs only (stops before the first non-WB slit)
  device.queue.writeBuffer(bufs.params, 0, _mgBuildUniform(prep, prep.descs.length));
  // P2U still consulted by pass-1 SSA stats — write benign values
  var p2u = _mgP2UNew();
  device.queue.writeBuffer(bufs.p2u, 0, p2u.buf);
  var atomInit = new Uint32Array(MG_ATOM_WORDS);
  atomInit[1] = 0xFFFFFFFF; atomInit[3] = 0xFFFFFFFF;
  atomInit[8] = 0xFFFFFFFF; atomInit[10] = 0xFFFFFFFF; atomInit[17] = 0xFFFFFFFF;
  device.queue.writeBuffer(bufs.atom, 0, atomInit);

  var enc = device.createCommandEncoder();
  var pass = enc.beginComputePass();
  pass.setPipeline(_mgCache.pipelines.trace);
  pass.setBindGroup(0, bufs.bindGroup);
  pass.dispatchWorkgroups(bufs.numWG, 1, 1);
  pass.end();
  enc.copyBufferToBuffer(bufs.rays, 0, rbRays, 0, prep.nR * MG_RAY_STRIDE * 4);
  var n1 = prep.descs.length;
  enc.copyBufferToBuffer(bufs.partials, 0, bufs.rbPart, 0, Math.max(1, n1) * bufs.numWG * 5 * 4);
  device.queue.submit([enc.finish()]);

  return Promise.all([
    rbRays.mapAsync(GPUMapMode.READ),
    bufs.rbPart.mapAsync(GPUMapMode.READ)
  ]).then(function () {
    var raysF32 = new Float32Array(rbRays.getMappedRange().slice(0));
    var partF32 = new Float32Array(bufs.rbPart.getMappedRange().slice(0));
    rbRays.unmap();
    bufs.rbPart.unmap();
    var t1 = (typeof performance !== 'undefined') ? performance.now() : Date.now();

    var elementTrace = _mgTraceEntries(partF32, prep.gpuElems, 0, n1, bufs.numWG, prep.nR);

    // CPU continuation: SSA + KB + statistics via the engine's own code.
    var rays64 = new Float64Array(raysF32);
    var res = window._mcTraceFromRays(rays64, prep.nR, prep.td,
      { ld0: prep.gpuEndP, elementTrace: elementTrace });
    var t2 = (typeof performance !== 'undefined') ? performance.now() : Date.now();
    res._gpu = {
      engine: 'webgpu',
      mode: 'hybrid',
      nGpuElems: n1,
      gpuEndP: prep.gpuEndP,
      gpuMs: t1 - t0,
      contMs: t2 - t1,
      totalMs: t2 - t0,
      adapter: window._GPU.adapter_info || null
    };
    return res;
  });
}

// ===========================================================================
// Public async API. Same result shape as mcRayTrace (plus ._gpu metadata).
// Falls back to the CPU engine (resolved promise, _gpu.fallback=true) when
// WebGPU or the current element configuration is unsupported. Full mode is
// used for the sample plane (after the conic precision gate passes); other
// targets use the phase-1 hybrid mode.
// ===========================================================================
window.mcRayTraceGPU = function (td, nR) {
  nR = nR || ((typeof MC_NRAYS !== 'undefined') ? MC_NRAYS : 100000);

  function cpuFallback(reason) {
    _mgLastError = reason;
    try { console.warn('[mcGPU] CPU fallback: ' + reason); } catch (e) {}
    var res = mcRayTrace(td, nR);
    res._gpu = { engine: 'cpu', fallback: true, reason: reason };
    return res;
  }

  var run = function () {
    var prep;
    try { prep = _mgPrep(td, nR); } catch (e) {
      return Promise.resolve(cpuFallback('prep threw: ' + (e && e.message ? e.message : String(e))));
    }
    if (!prep.ok) return Promise.resolve(cpuFallback(prep.reason));
    if (typeof detectWebGPU !== 'function') {
      return Promise.resolve(cpuFallback('02_webgpu_detect.js not loaded'));
    }
    return detectWebGPU().then(function (gi) {
      if (!gi.supported || !window._GPU.device) {
        return cpuFallback('WebGPU unavailable: ' + (gi.error || 'unknown'));
      }
      var lim = window._GPU.limits || {};
      var need = nR * MG_RAY_STRIDE * 4;
      if (lim.maxStorageBufferBindingSize && need > lim.maxStorageBufferBindingSize) {
        return cpuFallback('ray buffer ' + need + ' B exceeds maxStorageBufferBindingSize');
      }
      // mode selection: full GPU chain only for the sample plane
      var sp = (typeof pos === 'function') ? pos('sample') : null;
      var wantFull = prep.fullOk && sp !== null && sp !== undefined && Math.abs(td - sp) < 1e-9;
      var conicKey = wantFull ? _mgConicKeyOf(prep) : '';

      function doRun(full, fullFailReason) {
        var p = full ? _mgRunFull(prep) : _mgRunHybrid(prep);
        return p.then(function (res) {
          _mgLastError = null;
          if (!full && fullFailReason && res._gpu) res._gpu.fullFallback = fullFailReason;
          return res;
        }, function (err) {
          return cpuFallback('GPU run failed: ' + (err && err.message ? err.message : String(err)));
        });
      }

      if (!wantFull) return doRun(false, prep.fullOk ? null : prep.fullReason);
      if (!conicKey) return doRun(true, null);   // no conic in chain: nothing to gate
      var verdict = _mgConicVerdicts[conicKey];
      if (verdict) {
        if (verdict.ok) return doRun(true, null);
        return doRun(false, 'conic precision gate failed (worst RMS ' +
          verdict.worst_rms_nm.toFixed(2) + ' nm >= 1 nm)');
      }
      // first use for this conic configuration: run the precision self-test
      return _mgRunConicTest(prep, 4096).then(function (cv) {
        _mgConicVerdicts[conicKey] = cv;
        try {
          console.log('[mcGPU] conic precision self-test: ' +
            (cv.ok ? 'PASS' : 'FAIL') + ' (worst RMS ' +
            cv.worst_rms_nm.toFixed(3) + ' nm, gate < 1 nm)');
        } catch (e) {}
        if (cv.ok) return doRun(true, null);
        return doRun(false, 'conic precision gate failed (worst RMS ' +
          cv.worst_rms_nm.toFixed(2) + ' nm >= 1 nm)');
      }, function (err) {
        return doRun(false, 'conic self-test failed to run: ' +
          (err && err.message ? err.message : String(err)));
      });
    });
  };

  // Serialize runs: buffers/readbacks are shared module state.
  var p = _mgChain.then(run, run);
  _mgChain = p.then(function () {}, function () {});
  return p;
};

// ===========================================================================
// Sync hook consumed by mcRayTrace (engine entry point). Returns a stored
// GPU result ONLY when its physics fingerprint matches the current state for
// this exact (td, nR); otherwise returns null (CPU runs) and — for the
// sample-plane profile request only — schedules a background GPU run so the
// next request is served from the GPU.
// ===========================================================================
window._mcGpuSyncHook = function (td, nR) {
  if (typeof state === 'undefined' || !state.mcGpuEnabled) return null;
  if (typeof navigator === 'undefined' || !navigator.gpu) return null;
  var sp = (typeof pos === 'function') ? pos('sample') : null;
  if (sp === null || sp === undefined || Math.abs(td - sp) > 1e-9) return null;
  var prep;
  try { prep = _mgPrep(td, nR); } catch (e) { return null; }
  if (!prep.ok) return null;
  var fp = prep.fingerprint;
  if (_mgStore.result && _mgStore.key === fp) return _mgStore.result;
  if (_mgInFlightKey === fp) return null;          // already computing
  _mgInFlightKey = fp;
  window.mcRayTraceGPU(td, nR).then(function (res) {
    if (_mgInFlightKey === fp) _mgInFlightKey = null;
    if (!res || (res._gpu && res._gpu.fallback)) return;
    // Discard if physics changed while the run was in flight.
    var nowFp;
    try {
      var p2 = _mgPrep(td, nR);
      nowFp = p2.ok ? p2.fingerprint : null;
    } catch (e) { nowFp = null; }
    if (nowFp !== fp) return;
    _mgStore.key = fp;
    _mgStore.result = res;
    // Surface on the focalSpot sample cache + experiment status line.
    try { if (typeof window._mcSetSampleCache === 'function') window._mcSetSampleCache(res); } catch (e) {}
    try { if (typeof _updateExptBeamlineStatus === 'function') _updateExptBeamlineStatus(); } catch (e) {}
    try { console.log('[mcGPU] sample-plane GPU result ready (' +
      res._gpu.gpuMs.toFixed(0) + ' ms GPU + ' + res._gpu.contMs.toFixed(0) + ' ms CPU, mode=' +
      res._gpu.mode + ')'); } catch (e) {}
  }, function (err) {
    if (_mgInFlightKey === fp) _mgInFlightKey = null;
    _mgLastError = (err && err.message) ? err.message : String(err);
  });
  return null;
};

// ===========================================================================
// UI toggle (View tab "MC Engine" section calls this)
// ===========================================================================
window.setMCEngine = function (v) {
  var on = !!v;
  if (on && (typeof navigator === 'undefined' || !navigator.gpu)) {
    try { if (typeof log === 'function') log('warn', 'WebGPU not available in this browser - staying on CPU engine'); } catch (e) {}
    on = false;
  }
  state.mcGpuEnabled = on;
  _mgStore.key = ''; _mgStore.result = null;
  try { localStorage.setItem('bl10_mcgpu', on ? '1' : '0'); } catch (e) {}
  if (on && typeof detectWebGPU === 'function') { try { detectWebGPU(); } catch (e) {} }
  try { if (typeof log === 'function') log('info', 'MC engine -> ' + (on ? 'GPU (WebGPU, beta)' : 'CPU')); } catch (e) {}
  try { if (typeof renderModeMenu === 'function') renderModeMenu(); } catch (e) {}
  // Recompute through the selected engine (background GPU run is scheduled
  // by the hook on the next sample-plane request).
  try { if (typeof _invalidateMCCache === 'function') _invalidateMCCache(); } catch (e) {}
  try { if (typeof updateOptics === 'function') updateOptics(); } catch (e) {}
};

// Restore persisted preference (only meaningful when WebGPU exists).
try {
  if (typeof localStorage !== 'undefined' && localStorage.getItem('bl10_mcgpu') === '1' &&
      typeof navigator !== 'undefined' && navigator.gpu &&
      typeof state !== 'undefined' && state) {
    state.mcGpuEnabled = true;
  }
} catch (e) {}

try { console.log('[' + (typeof APP_VTAG !== 'undefined' ? APP_VTAG : 'V?') + '] MC GPU engine loaded (opt-in, default CPU; phase-2 GPU-resident chain)'); } catch (e) {}

// ESM bridge: expose module-scoped vars to globalThis
if (typeof MG_WG_SIZE !== 'undefined') globalThis.MG_WG_SIZE = MG_WG_SIZE;
if (typeof _mgBuildWGSL !== 'undefined') globalThis._mgBuildWGSL = _mgBuildWGSL;
if (typeof _mgPrep !== 'undefined') globalThis._mgPrep = _mgPrep;
