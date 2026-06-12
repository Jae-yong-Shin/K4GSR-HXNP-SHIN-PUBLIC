'use strict';
// ===== optics/04_source.js — Photon Source Size & Flux =====
// @module optics/04_source
// @exports _wbMode, erf_a, photonFlux, photonSrc, sourceFlux
// Extracted from 02_physics.js (DDD Phase 2)

// === Photon source size (Elleaume + Tanaka-Kitamura) ===
function erf_a(x){var a1=.254829592,a2=-.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=.3275911;var sg=x<0?-1:1;x=Math.abs(x);var t=1/(1+p*x);return sg*(1-((((a5*t+a4)*t+a3)*t+a2)*t+a1)*t*Math.exp(-x*x));}
// V4.36 C-2: White beam divergence model (inline merged from 12_v435_physics.js)
var _wbMode = false;
/** Photon source size/divergence (Tanaka-Kitamura). @param {number} E - keV @returns {{Sx:number,Sy:number,Sxp:number,Syp:number,sr:number,srp:number}} sizes in m, div in rad */
function photonSrc(E) {
  var lm = (HC / E) * 1e-10;
  // Diffraction-limited single-electron photon source (Kim convention).
  // sigma_r  = sqrt(2*lm*L_UND)/(4pi)      (natural source-plane RMS size)
  // sigma_r' = sqrt(lm/(2*L_UND))          (natural source-plane RMS divergence)
  // Product: sigma_r * sigma_r' = lm/(4pi)  (diffraction limit, single-mode lower bound).
  // Validated vs SPECTRA natural_usrc (zero-emittance, zero-spread) to <1%.
  // sigma_r prime is the SOURCE-PLANE single-electron RMS. For slit-plane SPECTRA-style divergence, see effectiveDivergence() (v4.37.26).
  var srp = Math.sqrt(lm / (2 * L_UND));              // sigma_r'  (rad)
  var sr = Math.sqrt(2 * lm * L_UND) / (4 * Math.PI); // sigma_r   (m)
  // Energy-spread broadening of the SOURCE size/divergence (Tanaka-Kitamura Qa,Qs) is
  // negligible for the K4GSR beam (sigma_delta=1.2e-3): measured Qa,Qs ~ 1 vs SPECTRA.
  // The energy-spread + emittance effect on the FLUX SPECTRUM is handled by the joint
  // phase-space convolution in undulatorSpectrum() (js/optics/01_undulator.js).
  var rpc = srp, rc = sr;
  var r = {
    Sx: Math.sqrt(SIG_EX * SIG_EX + rc * rc),
    Sy: Math.sqrt(SIG_EY * SIG_EY + rc * rc),
    Sxp: Math.sqrt(SIG_EXP * SIG_EXP + rpc * rpc),
    Syp: Math.sqrt(SIG_EYP * SIG_EYP + rpc * rpc),
    sr: rc, srp: rpc, tier: 'closed-form'
  };
  // === SPECTRA-accurate source size & divergence (embedded lookup, optics/06_source_optics_table.js) ===
  // The Kim closed form above (rc, rpc + electron-beam quadrature) is the natural single-electron
  // diffraction term and the off-grid fallback. When the (K, n) lookup is available it REPLACES
  // Sx/Sy/Sxp/Syp with the SPECTRA matched-window values (Kim 1989 single-electron + the
  // f_LinearFxy far-field amplitude + numerical phase-space convolution, second moment over
  // SPECTRA's own srcpoint/sprof and far/spatial/fdensa mesh extent), validated vs the SPECTRA
  // solver to sigma_x 0.4% / sigma_y 0.5% / sigma'_x 0.7% / sigma'_y 1.0% (mean abs dev,
  // K = 1.0-2.5, n = 3-11; matches manuscript Section 3 and Suppl. Tables S12/S13). photonSrc is
  // the single source of truth consumed by both the MC ray
  // seeding (raytrace/01_mc_engine.js) and the analytic propagateBeam (raytrace/02_propagation.js),
  // so this one override makes the whole engine SPECTRA-accurate upstream of the optics.
  if (typeof sourceOpticsLookup === 'function' && typeof calcK === 'function'
      && typeof calcB0 === 'function' && typeof state !== 'undefined' && state) {
    var Klu = calcK(calcB0(state.gap));
    var lc = LAMBDA_U / 10;
    var E1lu = 0.9498 * E_RING * E_RING / (lc * (1 + Klu * Klu / 2)); // keV; matches findHarmonics()
    var nlu = (E1lu > 0) ? Math.round(E / E1lu) : 1;
    if (nlu < 1) nlu = 1;
    if (nlu % 2 === 0) nlu += 1;        // planar undulator radiates odd harmonics on axis
    if (nlu > 15) nlu = 15;
    var lk = sourceOpticsLookup(Klu, nlu);
    if (lk && isFinite(lk.Sx) && isFinite(lk.Sy) && isFinite(lk.Sxp) && isFinite(lk.Syp)
        && lk.Sx > 0 && lk.Sy > 0 && lk.Sxp > 0 && lk.Syp > 0) {
      r.Sx = lk.Sx; r.Sy = lk.Sy; r.Sxp = lk.Sxp; r.Syp = lk.Syp;
      r.tier = 'spectra-lookup'; r.harmonic = nlu; r.Klookup = Klu;
    }
  }
  // --- White beam mode: enhanced divergence (from 12_v435_physics.js C-2) ---
  if (_wbMode) {
    var K = calcK(calcB0(state.gap));
    // White beam total divergence >> single harmonic
    // sigma'_H ~ K/gamma (~244 urad), sigma'_V ~ 1/gamma (~128 urad)
    r.Sxp = Math.max(r.Sxp, K / GAMMA_E);
    r.Syp = Math.max(r.Syp, 1.0 / GAMMA_E);
  }
  return r;
}

// === Effective divergence at a downstream slit (SPECTRA-style) — FALLBACK_LAYER (v4.37.26) ===
// STATUS: Analytic stub. NOT used by production photonSrc/photonFlux paths. Provided as a
// SPECTRA-style API surface for downstream callers (DCM/KB acceptance scaling, paper Suppl
// S3.5). Closed-form residual vs SPECTRA `far/spatial/fdensa` is significant (X: 24% mean,
// Y: 10% mean, at n>=11; up to 100% at n=1 where the sinc HWHM dominates and the (1+K^2/2)
// scaling overshoots). For SPECTRA <=1% matching, callers must perform the full slit-
// integrated 2nd-moment via spatial/fdensa direct sampling — see
// `docs/tasks/WORKORDER_FULL_SPATIAL_PORT.md` (pattern: fluxAcceptance lookup background
// precompute). Do not use this function in the propagateBeam / photonFlux path.
//
// Formula (Kim 1989 single-electron + Twiss drift, dimensionally corrected):
//   sigma_natural'  = (1/gamma) * sqrt((1 + K^2/2) / (n * N_PERIODS))   [rad, planar]
//   beta(Z)         = beta_0 + Z^2/beta_0          (alpha_0 ~ 0 at K4GSR straight)
//   sigma_proj'(Z)  = sqrt(beta(Z) * emit) / Z
//   Sxp_eff         = sqrt(sigma_proj_x'^2 + sigma_natural'^2)
//
// Previous v4.37.25 form `sigma_natural' = 0.5 * sqrt((1+K^2/2)/(nN))` was dimensionally
// wrong (returned ~0.023 rad, ~10^5x SPECTRA) — that is the SPECTRA normalized line half-
// width in (delta E)/E1 units, not an angle. Fixed by including the (1/gamma) factor so
// the result has units of rad. Validation: `paper/validation/test_effective_divergence.js`,
// result `paper/validation/data/test_effective_divergence_result.json`.
// Internal helper: analytic stub (Kim 1989 + Twiss drift). Synchronous.
function _effDivFast(K, n, Z) {
  var sigma_natural_prime = (1.0 / GAMMA_E) * Math.sqrt((1 + K * K / 2) / (n * N_PERIODS));
  var gx0 = 1.0 / BETA_X, gy0 = 1.0 / BETA_Y;
  var betaz_x = BETA_X + gx0 * Z * Z;
  var betaz_y = BETA_Y + gy0 * Z * Z;
  var sigma_proj_x = Math.sqrt(betaz_x * EMIT_X);
  var sigma_proj_y = Math.sqrt(betaz_y * EMIT_Y);
  var sigma_proj_x_prime = sigma_proj_x / Z;
  var sigma_proj_y_prime = sigma_proj_y / Z;
  var Sxp_eff = Math.sqrt(sigma_proj_x_prime * sigma_proj_x_prime + sigma_natural_prime * sigma_natural_prime);
  var Syp_eff = Math.sqrt(sigma_proj_y_prime * sigma_proj_y_prime + sigma_natural_prime * sigma_natural_prime);
  return {
    Sxp_eff: Sxp_eff,
    Syp_eff: Syp_eff,
    sigma_natural_prime: sigma_natural_prime,
    betaz_x: betaz_x,
    betaz_y: betaz_y,
    sigma_proj_x_prime: sigma_proj_x_prime,
    sigma_proj_y_prime: sigma_proj_y_prime,
    tier: '[fast]'
  };
}

// Internal helper: precomputed SPECTRA lookup table. Synchronous, returns null on miss.
function _effDivLookup(K, n, Z) {
  if (typeof fluxDivergenceLookup !== 'function') return null;
  if (typeof _falDiv === 'undefined' || !_falDiv || !_falDiv.loaded) return null;
  var lk = null;
  try { lk = fluxDivergenceLookup(K, n, Z); } catch (e) { lk = null; }
  if (!lk || typeof lk.Sxp_urad !== 'number' || typeof lk.Syp_urad !== 'number') return null;
  return {
    Sxp_eff: lk.Sxp_urad * 1e-6,
    Syp_eff: lk.Syp_urad * 1e-6,
    sigma_natural_prime: NaN,
    betaz_x: NaN,
    betaz_y: NaN,
    sigma_proj_x_prime: NaN,
    sigma_proj_y_prime: NaN,
    tier: '[lookup]'
  };
}

/**
 * Effective divergence at slit Z. 4-tier dispatch.
 *
 *   opts.tier === 'fast'   -> sync, analytic stub (immediate, no GPU/lookup)
 *   opts.tier === 'lookup' -> sync, lookup only (returns analytic on miss)
 *   opts.tier === 'worker' -> async (Promise), CPU worker STUB — currently
 *                             falls back to lookup -> fast. Reserved for a
 *                             future port mirroring 05_flux_acceptance_worker.
 *   opts.tier === 'auto' / 'gpu' (DEFAULT for async use) -> async (Promise):
 *     1. Try divergenceGPU(K, n, Z) if WebGPU device is available.
 *        Success -> tier='[gpu]'.
 *     2. On GPU fail / unavailable -> lookup. Hit -> tier='[lookup]'.
 *     3. On lookup miss -> analytic stub. tier='[fast]'.
 *
 * Backwards compatible call: omitting opts (or opts={}) returns the
 * synchronous lookup-then-fast result, preserving the v4.37.27 contract for
 * existing callers. Pass opts.tier='auto' (or 'gpu') to opt into the GPU
 * Promise chain.
 *
 * @param {number} E keV
 * @param {number} K
 * @param {number} n harmonic
 * @param {number} [Z=30] slit distance (m)
 * @param {{tier?:string}} [opts]
 */
function effectiveDivergence(E, K, n, Z, opts) {
  if (Z === undefined || Z === null || isNaN(Z)) Z = 30.0;
  if (!opts) opts = {};
  var tierReq = opts.tier || 'sync';   // 'sync' = legacy sync default (lookup -> fast)

  // --- Synchronous tiers (legacy + opt-in) ---
  if (tierReq === 'fast') {
    return _effDivFast(K, n, Z);
  }
  if (tierReq === 'lookup') {
    var lkOnly = _effDivLookup(K, n, Z);
    if (lkOnly) return lkOnly;
    return _effDivFast(K, n, Z);
  }
  if (tierReq === 'sync') {
    // Legacy default: lookup if loaded, else analytic. Synchronous.
    var lkSync = _effDivLookup(K, n, Z);
    if (lkSync) return lkSync;
    return _effDivFast(K, n, Z);
  }

  // --- Asynchronous tiers (Promise return) ---
  // Worker tier: STUB. Not yet ported (see 05_flux_acceptance_worker.js for
  // template). Falls back to lookup -> fast wrapped in Promise.resolve.
  if (tierReq === 'worker') {
    var wRes = _effDivLookup(K, n, Z) || _effDivFast(K, n, Z);
    return Promise.resolve(wRes);
  }

  // auto / gpu : GPU first, then lookup, then fast.
  var hasGPU = (typeof divergenceGPU === 'function')
            && (typeof window !== 'undefined')
            && window._GPU && window._GPU.supported && window._GPU.device;
  // If GPU not yet probed but detectable, defer to async probe.
  var canTryGPU = (typeof divergenceGPU === 'function')
               && (typeof window !== 'undefined')
               && window._GPU
               && !(window._GPU._probed && !window._GPU.supported);
  if (!canTryGPU) {
    var fallback = _effDivLookup(K, n, Z) || _effDivFast(K, n, Z);
    return Promise.resolve(fallback);
  }
  return divergenceGPU(K, n, Z).then(function (g) {
    if (g && typeof g.Sxp_urad === 'number' && typeof g.Syp_urad === 'number'
        && isFinite(g.Sxp_urad) && isFinite(g.Syp_urad)) {
      return {
        Sxp_eff: g.Sxp_urad * 1e-6,
        Syp_eff: g.Syp_urad * 1e-6,
        sigma_natural_prime: NaN,
        betaz_x: NaN,
        betaz_y: NaN,
        sigma_proj_x_prime: NaN,
        sigma_proj_y_prime: NaN,
        tier: '[gpu]'
      };
    }
    return _effDivLookup(K, n, Z) || _effDivFast(K, n, Z);
  }, function (_err) {
    return _effDivLookup(K, n, Z) || _effDivFast(K, n, Z);
  });
}

// === Undulator source flux (on-axis, DCM BW scaled, no optical losses) ===
// Returns ph/s at source position after DCM monochromatization.
// Finds all reachable harmonics via findHarmonics(), picks the one with
// maximum on-axis flux (not necessarily the lowest n — at high energies,
// higher harmonics with larger K give stronger coupling).
// At energies outside undulator/DCM range, returns 0.
function sourceFlux(E) {
  if (E === undefined || E === null || isNaN(E)) E = state.energy || 10;
  var harmonics = (typeof findHarmonics === 'function') ? findHarmonics(E) : [];
  if (harmonics.length === 0) return 0;
  // DCM bandwidth at this energy
  var dbw = (typeof dcmBandwidth === 'function') ? dcmBandwidth(E) : 0;
  if (dbw <= 0) return 0; // DCM cannot reach this energy
  // Pick the harmonic with highest on-axis flux
  var best = harmonics[0];
  for (var i = 1; i < harmonics.length; i++) {
    if (harmonics[i].flux > best.flux) best = harmonics[i];
  }
  // Effective BW = min(DCM bandwidth, undulator natural bandwidth)
  var ubw = 1 / (best.n * N_PERIODS);
  var eff = Math.min(dbw, ubw);
  return Math.max(0, best.flux * (eff / 0.001));
}

// === DCM band double-count correction factor (2026-06-10, flux decomposition) ===
// sourceFlux(E) is already restricted to the Si(111) Darwin band
// (eff = min(dcmBandwidth, undulator natural BW)). The MC additionally
// samples per-ray energies as Gaussian sigma = state.sourceBW_eV/2 and the
// Guigay DCM weight rejects the tails outside the Darwin band, so the band
// acceptance would be counted twice. The MC survival ratio must be divided
// by the analytic in-band probability
//   P = erf( (Darwin_FW/2) / (sigma*sqrt(2)) )
// (Gaussian-vs-top-hat overlap; standard importance-sampling reweighting,
// NOT a physical chain element — the net DCM-stage factor stays < 1:
// measured 0.73 x 1.242 = 0.906 < peak R 0.95). Measured 0.766 vs model
// 0.806 at 10 keV / srcBW=1 eV; the ~5% residual is the soft rocking-curve
// edge. Returns 1 when sourceBW_eV = 0 (monochromatic: no tails, no
// double count). Shared by photonFlux and the MC-synced Propagation Log.
function _dcmBandFix(E) {
  var fix = 1;
  try {
    var bwEv = (typeof state.sourceBW_eV === 'number') ? state.sourceBW_eV : 1.0;
    if (bwEv > 0 && typeof dcmBandwidth === 'function' && typeof erf_a === 'function') {
      var dwHalfEv = dcmBandwidth(E) * E * 1000 * 0.5; // Darwin half-width [eV]
      var sigEv = bwEv * 0.5;                           // mc_engine: sigma = BW*0.5
      if (sigEv > 0 && dwHalfEv > 0) {
        var pIn = erf_a(dwHalfEv / (sigEv * Math.SQRT2));
        if (pIn > 0.05 && pIn < 1) fix = 1 / pIn;
      }
    }
  } catch (e) {}
  return fix;
}

// === Photon flux at sample ===
// AUTHORITATIVE sample-plane flux calculator (user decision 2026-06-10):
//   the MC ray-trace chain is the physical model — it captures the M1/M2
//   secondary-source focusing at the SSA (~86% passage) and the small KB
//   angular acceptance (~9%), both of which the analytic propagateBeam
//   chain gets wrong (no mirror focusing -> ~300x over-clip at the SSA).
//   Seed flux comes from sourceFlux (SPECTRA acceptance lookup when the
//   table is loaded; Kim filament fallback otherwise) and the MC survival
//   ratio is band-corrected (see bandFix below).
//   UI display sites must NOT call this directly — call sampleFlux()
//   (js/raytrace/02_propagation.js), the single sample-flux API, which
//   routes here.
// Fallback: analytical loss model when the MC cache is unavailable
//   (cold start before the first ray trace).
function photonFlux(E) {
  if (E === undefined || E === null || isNaN(E)) E = state.energy || 10;
  var fl = sourceFlux(E);
  // MC-based: source flux x MC weight-based survival ratio
  // Guigay DCM applies weight multiplication (not kill), so count-based survival
  // over-estimates flux. Use sum-of-weights / nTotal instead.
  if (typeof _mcSampleCache !== 'undefined' && _mcSampleCache && _mcSampleCache.nTotal > 0) {
    var _bandFix = _dcmBandFix(E);
    // When KB is active with focused rays, use focused-only weight (tag=3)
    // to exclude unfocused pass-through beam from flux count
    if (_mcSampleCache.nBeams && _mcSampleCache.nBeams.focused > 10
        && typeof _mcSampleCache.wSumFocused === 'number' && _mcSampleCache.wSumFocused > 0) {
      return Math.max(0, fl * _bandFix * (_mcSampleCache.wSumFocused / _mcSampleCache.nTotal));
    }
    var wMeanMC = (typeof _mcSampleCache.wMean === 'number') ? _mcSampleCache.wMean : 1;
    return Math.max(0, fl * _bandFix * (wMeanMC * _mcSampleCache.nSurvived / _mcSampleCache.nTotal));
  }
  // Fallback: analytical optical losses (less accurate, used before first MC run)
  var gm = function(g, id, fb) {
    return (typeof MOTORS !== 'undefined' && MOTORS[g]) ? getMotorVal(g, id, fb) : fb;
  };
  // WB slit clipping
  var b1 = beamAt(pos('wbslit'));
  fl *= Math.min(1, gm('wbslit', 'wbslit_hgap', state.wbH) * 1000 / Math.max(1, b1.h));
  fl *= Math.min(1, gm('wbslit', 'wbslit_vgap', state.wbV) * 1000 / Math.max(1, b1.v));
  // Mask clipping
  if (typeof maskTransmission === 'function') {
    var bf = beamAt(pos('fmask'));
    fl *= maskTransmission('fmask', bf.h / 1000, bf.v / 1000);
    var bm = beamAt(pos('mmask'));
    fl *= maskTransmission('mmask', bm.h / 1000, bm.v / 1000);
  }
  // Mirror + DCM reflectivity
  fl *= mirrorR(E, gm('m1', 'm1_pitch', state.m1pitch), RH);
  fl *= dcmThru(E);
  fl *= mirrorR(E, gm('m2', 'm2_pitch', state.m2pitch), RH);
  // SSA clipping
  var b2 = beamAt(pos('ssa'));
  fl *= Math.min(1, gm('ssa', 'ssa_hgap', state.ssaH) / Math.max(1, b2.h));
  fl *= Math.min(1, gm('ssa', 'ssa_vgap', state.ssaV) / Math.max(1, b2.v));
  // KB upstream slit clipping
  var b3 = beamAt(pos('kbslit') || 149.19);
  fl *= Math.min(1, (state.kbslitH || 5000) / Math.max(1, b3.h));
  fl *= Math.min(1, (state.kbslitV || 5000) / Math.max(1, b3.v));
  // KB mirrors (Pt coating, dynamic pitch) + air absorption
  var kbvP = gm('kbv', 'kbv_pitch', state.kbvpitch);
  var kbhP = gm('kbh', 'kbh_pitch', state.kbhpitch);
  fl *= mirrorR(E, kbvP, PT) * mirrorR(E, kbhP, PT) * Math.exp(-0.2 * Math.pow(10 / E, 3));
  return Math.max(0, fl);
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof erf_a!=="undefined")globalThis.erf_a=erf_a;
if(typeof _dcmBandFix!=="undefined")globalThis._dcmBandFix=_dcmBandFix;
if(typeof photonFlux!=="undefined")globalThis.photonFlux=photonFlux;
if(typeof photonSrc!=="undefined")globalThis.photonSrc=photonSrc;
if(typeof effectiveDivergence!=="undefined")globalThis.effectiveDivergence=effectiveDivergence;
if(typeof sourceFlux!=="undefined")globalThis.sourceFlux=sourceFlux;
if(typeof _wbMode!=="undefined")globalThis._wbMode=_wbMode;
