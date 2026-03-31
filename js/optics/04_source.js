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
  var lm = (HC / E) * 1e-10, n = state.harmonic || 1;
  var srp = 0.69 * Math.sqrt(lm / (2 * n * L_UND));
  var sr = 2.740 / (4 * Math.PI) * Math.sqrt(2 * lm * L_UND / n);
  var se = 2 * Math.PI * n * N_PERIODS * E_SPREAD;
  var Qa_v = Math.sqrt(Math.max(0, 2 * se * se - 1 + Math.exp(-2 * se * se) + Math.sqrt(2 * Math.PI) * se * erf_a(Math.sqrt(2) * se)));
  var Qa = Math.max(1, Qa_v);
  var se4 = se / 4;
  var Qa4 = Math.sqrt(Math.max(0, 2 * se4 * se4 - 1 + Math.exp(-2 * se4 * se4) + Math.sqrt(2 * Math.PI) * se4 * erf_a(Math.sqrt(2) * se4)));
  var Qs = (Qa4 > 0.01) ? Math.max(1, Math.pow(Qa4, 2 / 3)) : 1;
  var rpc = srp * Qa, rc = sr * Qs;
  var r = {
    Sx: Math.sqrt(SIG_EX * SIG_EX + rc * rc),
    Sy: Math.sqrt(SIG_EY * SIG_EY + rc * rc),
    Sxp: Math.sqrt(SIG_EXP * SIG_EXP + rpc * rpc),
    Syp: Math.sqrt(SIG_EYP * SIG_EYP + rpc * rpc),
    sr: rc, srp: rpc
  };
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

// === Photon flux at sample — MC-consistent ===
// Uses MC ray trace survival ratio for optical losses (physically accurate).
// Fallback: analytical loss model when MC cache unavailable.
function photonFlux(E) {
  if (E === undefined || E === null || isNaN(E)) E = state.energy || 10;
  var fl = sourceFlux(E);
  // MC-based: source flux x MC weight-based survival ratio
  // Guigay DCM applies weight multiplication (not kill), so count-based survival
  // over-estimates flux. Use sum-of-weights / nTotal instead.
  if (typeof _mcSampleCache !== 'undefined' && _mcSampleCache && _mcSampleCache.nTotal > 0) {
    // When KB is active with focused rays, use focused-only weight (tag=3)
    // to exclude unfocused pass-through beam from flux count
    if (_mcSampleCache.nBeams && _mcSampleCache.nBeams.focused > 10
        && typeof _mcSampleCache.wSumFocused === 'number' && _mcSampleCache.wSumFocused > 0) {
      return Math.max(0, fl * (_mcSampleCache.wSumFocused / _mcSampleCache.nTotal));
    }
    var wMeanMC = (typeof _mcSampleCache.wMean === 'number') ? _mcSampleCache.wMean : 1;
    return Math.max(0, fl * (wMeanMC * _mcSampleCache.nSurvived / _mcSampleCache.nTotal));
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
if(typeof photonFlux!=="undefined")globalThis.photonFlux=photonFlux;
if(typeof photonSrc!=="undefined")globalThis.photonSrc=photonSrc;
if(typeof sourceFlux!=="undefined")globalThis.sourceFlux=sourceFlux;
if(typeof _wbMode!=="undefined")globalThis._wbMode=_wbMode;
