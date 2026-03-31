'use strict';
// ===== JS Physics Unit Tests — A2 Action Item =====
// Pure math/physics functions extracted from the beamline codebase.
// Run: node tests/js/test_physics.js
// No browser/DOM dependencies. No external packages required.

// ───────────────────────────────────────────────────
// Test harness (minimal, zero-dependency)
// ───────────────────────────────────────────────────
var _passed = 0, _failed = 0, _errors = [];
function assert(cond, msg) {
  if (cond) { _passed++; }
  else { _failed++; _errors.push('FAIL: ' + msg); }
}
function assertClose(actual, expected, tol, msg) {
  var diff = Math.abs(actual - expected);
  var ok = diff <= tol;
  if (ok) { _passed++; }
  else {
    _failed++;
    _errors.push('FAIL: ' + msg + ' | expected=' + expected + ' actual=' + actual + ' diff=' + diff + ' tol=' + tol);
  }
}
function section(name) { process.stdout.write('  ' + name + ' ... '); }
function sectionEnd() { process.stdout.write('OK\n'); }

// ───────────────────────────────────────────────────
// Extract constants (from shared/01_constants.js)
// ───────────────────────────────────────────────────
var HC = 12.3984;          // keV*A
var D_SI = { '111': 3.13560, '311': 1.63751 }; // A
var FIXED_EXIT = 12.0;     // mm
var R_E_A = 2.8179e-5;
var NA = 6.022e23;
var V_SI = 160.18;
var RH = { Z: 45, A: 102.9, rho: 12.41e6 };
var PT = { Z: 78, A: 195.08, rho: 21.45e6 };
var N_PERIODS = 123;
var LAMBDA_U = 24;             // mm
var LAMBDA_U_M = 0.024;        // m
var L_UND = N_PERIODS * LAMBDA_U_M;
var HALB_A = 3.3, HALB_B = -5.08, HALB_C = 1.54;
var E_RING = 4.0;
var I_RING = 400;
var GAMMA_E = E_RING * 1e3 / 0.511;
var EMIT_X = 62e-12, EMIT_Y = 6.2e-12;
var BETA_X = 6.334, BETA_Y = 2.841;
var E_SPREAD = 1.20e-3;
var SIG_EX = Math.sqrt(EMIT_X * BETA_X);
var SIG_EXP = Math.sqrt(EMIT_X / BETA_X);
var SIG_EY = Math.sqrt(EMIT_Y * BETA_Y);
var SIG_EYP = Math.sqrt(EMIT_Y / BETA_Y);

// Minimal state mock
var state = { crystal: '111', energy: 10.0, harmonic: 1, gap: 7.0,
  m1pitch: 2.5, m2pitch: 2.5, kbvpitch: 3.0, kbhpitch: 3.0,
  positions: {} };

// ───────────────────────────────────────────────────
// 1. gaussRand — Box-Muller Gaussian RNG
// ───────────────────────────────────────────────────
function gaussRand() {
  var u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// ───────────────────────────────────────────────────
// 2. braggAngle — Si crystal Bragg angle
// ───────────────────────────────────────────────────
function braggAngle(E) {
  var d = D_SI[state.crystal];
  var s = HC / (2 * d * E);
  return Math.abs(s) <= 1 ? Math.asin(s) : NaN;
}
function dcmGap(th) { return FIXED_EXIT / (2 * Math.cos(th)); }

// ───────────────────────────────────────────────────
// 3. mirrorR — Born & Wolf + Debye-Waller (fallback optConst)
// ───────────────────────────────────────────────────
function optConst(E, mat) {
  // Fallback: piecewise power-law (legacy path, no OPTCONST_TABLES)
  var Ne = mat.rho / 1e6 * 1e6 * NA * mat.Z / mat.A;
  var lm = HC / E * 1e-10;
  var delta = Ne * 2.8179e-15 * lm * lm / (2 * Math.PI);
  var mu_rho;
  if (mat.Z === 45) { // Rh
    if (E > 23.22) mu_rho = 120 * Math.pow(23.22 / E, 2.8);
    else if (E > 3.004) mu_rho = 30 * Math.pow(10 / E, 2.75);
    else mu_rho = 250 * Math.pow(3.0 / E, 2.75);
  } else if (mat.Z === 78) { // Pt
    if (E > 13.88) mu_rho = 220 * Math.pow(15 / E, 2.8);
    else if (E > 11.56) mu_rho = 450 * Math.pow(11.56 / E, 2.7);
    else if (E > 3.3) mu_rho = 115 * Math.pow(10 / E, 2.8);
    else mu_rho = 600 * Math.pow(3.3 / E, 2.75);
  } else { // Si
    if (E > 1.839) mu_rho = 20 * Math.pow(10 / E, 2.8);
    else mu_rho = 5000 * Math.pow(1.839 / E, 2.8);
  }
  var beta = mu_rho * mat.rho / 1e6 * 100 * lm / (4 * Math.PI);
  return { delta: delta, beta: beta };
}

function mirrorR(E, th_mrad, mat, roughness_A) {
  var oc = optConst(E, mat), th = th_mrad * 1e-3;
  var sth = (th > 0.05) ? Math.sin(th) : th;
  var p = sth * sth - 2 * oc.delta;
  var qi = 2 * oc.beta;
  var mag = Math.sqrt(p * p + qi * qi);
  var A = Math.sqrt(Math.max(0, (p + mag) * 0.5));
  var B = Math.sqrt(Math.max(0, (-p + mag) * 0.5));
  var num = (sth - A) * (sth - A) + B * B;
  var den = (sth + A) * (sth + A) + B * B;
  var R = (den > 1e-30) ? num / den : 0.99;
  if (roughness_A > 0) {
    var lam_A = HC / E;
    R *= Math.exp(-Math.pow(4 * Math.PI * sth * roughness_A / lam_A, 2));
  }
  return Math.min(0.99, Math.max(0, R));
}

// ───────────────────────────────────────────────────
// 4. photonSrc — source size/divergence
// ───────────────────────────────────────────────────
function erf_a(x) {
  var a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741,
      a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  var sg = x < 0 ? -1 : 1;
  x = Math.abs(x);
  var t = 1 / (1 + p * x);
  return sg * (1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-x * x));
}

function photonSrc(E) {
  var lm = (HC / E) * 1e-10, n = state.harmonic || 1;
  var srp = 0.69 * Math.sqrt(lm / (2 * n * L_UND));
  var sr = 2.740 / (4 * Math.PI) * Math.sqrt(2 * lm * L_UND / n);
  var se = 2 * Math.PI * n * N_PERIODS * E_SPREAD;
  var Qa_v = Math.sqrt(Math.max(0, 2 * se * se - 1 + Math.exp(-2 * se * se) +
    Math.sqrt(2 * Math.PI) * se * erf_a(Math.sqrt(2) * se)));
  var Qa = Math.max(1, Qa_v);
  var se4 = se / 4;
  var Qa4 = Math.sqrt(Math.max(0, 2 * se4 * se4 - 1 + Math.exp(-2 * se4 * se4) +
    Math.sqrt(2 * Math.PI) * se4 * erf_a(Math.sqrt(2) * se4)));
  var Qs = (Qa4 > 0.01) ? Math.max(1, Math.pow(Qa4, 2 / 3)) : 1;
  var rpc = srp * Qa, rc = sr * Qs;
  return {
    Sx: Math.sqrt(SIG_EX * SIG_EX + rc * rc),
    Sy: Math.sqrt(SIG_EY * SIG_EY + rc * rc),
    Sxp: Math.sqrt(SIG_EXP * SIG_EXP + rpc * rpc),
    Syp: Math.sqrt(SIG_EYP * SIG_EYP + rpc * rpc),
    sr: rc, srp: rpc
  };
}

// ───────────────────────────────────────────────────
// 5. _nomBeamX — nominal beam position
// ───────────────────────────────────────────────────
var _m1Pos = 29.0, _m2Pos = 32.0;
var _m1Pitch = 2.5e-3; // rad
var _m1Defl = 2 * _m1Pitch;

function _nomBeamX(compPos) {
  if (compPos <= _m1Pos) return 0;
  if (compPos <= _m2Pos) return _m1Defl * (compPos - _m1Pos);
  return _m1Defl * (_m2Pos - _m1Pos);
}

// ───────────────────────────────────────────────────
// 6. Si form factor (siFf) and related crystal functions
// ───────────────────────────────────────────────────
function siFf(s) {
  var s2 = s * s;
  return 6.2915 * Math.exp(-2.4386 * s2) + 3.0353 * Math.exp(-32.334 * s2) +
    1.9891 * Math.exp(-0.6785 * s2) + 1.5410 * Math.exp(-81.694 * s2) + 1.1407;
}
function siFh(E) {
  var th = braggAngle(E);
  if (isNaN(th)) return 0;
  var s = Math.sin(th) / (HC / E);
  return 4 * Math.SQRT2 * siFf(s) * Math.exp(-0.4632 * s * s);
}
function siChi(E) {
  var l = HC / E;
  return R_E_A * l * l * siFh(E) / (Math.PI * V_SI);
}
function darwinW(E) {
  var th = braggAngle(E);
  if (isNaN(th)) return 0;
  return 2 * siChi(E) / Math.sin(2 * th) * 206265;
}

// ───────────────────────────────────────────────────
// 7. Undulator physics (from optics/01_undulator.js)
// ───────────────────────────────────────────────────
function calcB0(g) { var r = g / LAMBDA_U; return HALB_A * Math.exp(HALB_B * r + HALB_C * r * r); }
function calcK(B0) { return 0.9341 * B0 * (LAMBDA_U / 10); }
function calcE1(K) { return 0.9498 * E_RING * E_RING / ((LAMBDA_U / 10) * (1 + K * K / 2)); }
function besselJ(n, x) {
  if (Math.abs(x) < 1e-10) return n === 0 ? 1 : 0;
  var s = 0, fM = 1, fN = 1;
  for (var i = 1; i <= n; i++) fN *= i;
  for (var m = 0; m < 30; m++) {
    if (m > 0) { fM *= m; fN *= (m + n); }
    var t = Math.pow(-1, m) / fM / fN * Math.pow(x / 2, 2 * m + n);
    s += t;
    if (Math.abs(t) < 1e-15 * Math.abs(s || 1)) break;
  }
  return s;
}
function coupFn(K, n) {
  var xi = K * K / (4 + 2 * K * K);
  var j1 = besselJ(Math.floor((n - 1) / 2), n * xi);
  var j2 = besselJ(Math.floor((n + 1) / 2), n * xi);
  var JJ = j1 - j2;
  return n * n * K * K * JJ * JJ / Math.pow(1 + K * K / 2, 2);
}
function onAxisFlux(K, n) { return 1.431e14 * N_PERIODS * I_RING_A * coupFn(K, n); }
var I_RING_A = I_RING / 1000;
function solveGap(B0t) {
  var lo = 4, hi = 30;
  for (var i = 0; i < 50; i++) { var m = (lo + hi) / 2; calcB0(m) > B0t ? lo = m : hi = m; }
  return (lo + hi) / 2;
}
function findHarmonics(Et) {
  var res = [], lc = LAMBDA_U / 10;
  for (var n = 1; n <= 15; n += 2) {
    var E1n = Et / n, K2 = 2 * (0.9498 * E_RING * E_RING / (lc * E1n) - 1);
    if (K2 < 0.01 || K2 > 25) continue;
    var K = Math.sqrt(K2), B0 = K / (0.9341 * lc), gap = solveGap(B0);
    if (gap < 4.5 || gap > 30) continue;
    res.push({ n: n, K: K, B0: B0, gap: gap, E1: E1n, flux: onAxisFlux(K, n), Fn: coupFn(K, n) });
  }
  return res.sort(function(a, b) { return a.n - b.n; });
}

// ───────────────────────────────────────────────────
// 8. DCM bandwidth & source flux (from raytrace/01_mc_engine.js, optics/04_source.js)
// ───────────────────────────────────────────────────
function dcmBandwidth(E) {
  var th = braggAngle(E);
  if (isNaN(th)) return 0;
  var dw_rad = darwinW(E) / 206265;
  return dw_rad / Math.tan(th);
}

function sourceFlux(E) {
  if (E === undefined || E === null || isNaN(E)) E = state.energy || 10;
  var harmonics = findHarmonics(E);
  if (harmonics.length === 0) return 0;
  var dbw = dcmBandwidth(E);
  if (dbw <= 0) return 0;
  var best = harmonics[0];
  for (var i = 1; i < harmonics.length; i++) {
    if (harmonics[i].flux > best.flux) best = harmonics[i];
  }
  var ubw = 1 / (best.n * N_PERIODS);
  var eff = Math.min(dbw, ubw);
  return Math.max(0, best.flux * (eff / 0.001));
}

// ═══════════════════════════════════════════════════
//   TEST SUITES
// ═══════════════════════════════════════════════════
console.log('K4GSR-Beamline Physics Unit Tests');
console.log('=================================');

// ─── T1: gaussRand ───────────────────────────────
section('T1: gaussRand — mean~0, stddev~1 (N=5000)');
(function() {
  var N = 5000, sum = 0, sum2 = 0;
  for (var i = 0; i < N; i++) {
    var g = gaussRand();
    sum += g; sum2 += g * g;
  }
  var mean = sum / N;
  var std = Math.sqrt(sum2 / N - mean * mean);
  assertClose(mean, 0, 0.08, 'gaussRand mean ~ 0');
  assertClose(std, 1, 0.08, 'gaussRand stddev ~ 1');
  assert(typeof gaussRand() === 'number', 'gaussRand returns number');
  assert(!isNaN(gaussRand()), 'gaussRand not NaN');
})();
sectionEnd();

// ─── T2: braggAngle ─────────────────────────────
section('T2: braggAngle — Si(111) & Si(311)');
(function() {
  // Si(111) @ 10 keV: theta = asin(HC/(2*3.1356*10)) = asin(0.19772) = 11.40 deg
  state.crystal = '111';
  var th10 = braggAngle(10);
  var deg10 = th10 * 180 / Math.PI;
  assertClose(deg10, 11.40, 0.05, 'Si(111) 10keV -> ~11.40 deg');

  // Si(111) @ 20 keV
  var th20 = braggAngle(20);
  var deg20 = th20 * 180 / Math.PI;
  assertClose(deg20, 5.69, 0.05, 'Si(111) 20keV -> ~5.69 deg');

  // Si(311) @ 10 keV
  state.crystal = '311';
  var th311 = braggAngle(10);
  var deg311 = th311 * 180 / Math.PI;
  assertClose(deg311, 22.34, 0.1, 'Si(311) 10keV -> ~22.34 deg');

  // Energy too low -> NaN
  state.crystal = '111';
  var thLow = braggAngle(1.5);
  assert(isNaN(thLow), 'Si(111) 1.5keV -> NaN (below cutoff)');

  state.crystal = '111'; // restore
})();
sectionEnd();

// ─── T3: dcmGap ─────────────────────────────────
section('T3: dcmGap — fixed exit offset');
(function() {
  var th = braggAngle(10);
  var gap = dcmGap(th);
  // gap = 12 / (2*cos(11.4 deg)) = 12 / (2*0.9803) = 6.12 mm
  assertClose(gap, 6.12, 0.05, 'dcmGap @ 10keV ~ 6.12 mm');
  // At 0 angle, gap = 6 mm (min)
  assertClose(dcmGap(0), 6.0, 1e-6, 'dcmGap @ theta=0 -> 6.0 mm');
})();
sectionEnd();

// ─── T4: mirrorR — reflectivity ─────────────────
section('T4: mirrorR — Pt/Rh reflectivity');
(function() {
  // Pt @ 10 keV, 2.5 mrad -> high R (below critical angle)
  var rPt = mirrorR(10, 2.5, PT, 0);
  assert(rPt > 0.85, 'Pt 2.5mrad 10keV R > 0.85 (got ' + rPt.toFixed(4) + ')');
  assert(rPt <= 0.99, 'Pt R clamped <= 0.99');

  // Rh @ 10 keV, 2.5 mrad -> high R
  var rRh = mirrorR(10, 2.5, RH, 0);
  assert(rRh > 0.85, 'Rh 2.5mrad 10keV R > 0.85 (got ' + rRh.toFixed(4) + ')');

  // Pt @ 10 keV, 20 mrad -> low R (above critical angle)
  var rHigh = mirrorR(10, 20, PT, 0);
  assert(rHigh < 0.5, 'Pt 20mrad 10keV R < 0.5 (above Ec, got ' + rHigh.toFixed(4) + ')');

  // Roughness reduces R
  var rSmooth = mirrorR(10, 2.5, PT, 0);
  var rRough = mirrorR(10, 2.5, PT, 5);
  assert(rRough < rSmooth, 'Roughness(5A) reduces R: ' + rRough.toFixed(4) + ' < ' + rSmooth.toFixed(4));

  // R always in [0, 0.99]
  for (var e = 5; e <= 25; e += 5) {
    for (var th = 1; th <= 10; th += 3) {
      var r = mirrorR(e, th, PT, 0);
      assert(r >= 0 && r <= 0.99, 'R in [0,0.99] @ ' + e + 'keV ' + th + 'mrad');
    }
  }
})();
sectionEnd();

// ─── T5: photonSrc — source size/divergence ─────
section('T5: photonSrc — source size & divergence');
(function() {
  state.harmonic = 1;
  var ps = photonSrc(10);

  // Source size: Sx ~ tens of um, Sy ~ few um
  assert(ps.Sx > 1e-6 && ps.Sx < 1e-3, 'Sx in um range: ' + (ps.Sx * 1e6).toFixed(1) + ' um');
  assert(ps.Sy > 1e-7 && ps.Sy < 1e-4, 'Sy in um range: ' + (ps.Sy * 1e6).toFixed(2) + ' um');

  // Divergence: Sxp, Syp ~ urad range
  assert(ps.Sxp > 1e-7 && ps.Sxp < 1e-4, 'Sxp in urad range: ' + (ps.Sxp * 1e6).toFixed(1) + ' urad');
  assert(ps.Syp > 1e-7 && ps.Syp < 1e-4, 'Syp in urad range: ' + (ps.Syp * 1e6).toFixed(1) + ' urad');

  // Sx > Sy (horizontal emittance >> vertical)
  assert(ps.Sx > ps.Sy, 'Sx > Sy (horizontal > vertical)');

  // Energy dependence: higher E -> smaller photon source contribution
  var ps5 = photonSrc(5);
  var ps20 = photonSrc(20);
  assert(ps5.sr > ps20.sr, 'sr(5keV) > sr(20keV): photon source shrinks with E');
  assert(ps5.srp > ps20.srp, 'srp(5keV) > srp(20keV): divergence shrinks with E');

  // All values positive
  assert(ps.Sx > 0 && ps.Sy > 0 && ps.Sxp > 0 && ps.Syp > 0, 'All source params > 0');
})();
sectionEnd();

// ─── T6: _nomBeamX — beam position ──────────────
section('T6: _nomBeamX — nominal beam position');
(function() {
  // Before M1 (29m): always 0
  assertClose(_nomBeamX(0), 0, 1e-12, 'nomBeamX(0m) = 0');
  assertClose(_nomBeamX(28), 0, 1e-12, 'nomBeamX(28m) = 0');
  assertClose(_nomBeamX(29), 0, 1e-12, 'nomBeamX(29m) = 0 (at M1)');

  // Between M1 and M2: linear ramp
  // defl = 2 * 2.5e-3 = 5e-3 rad
  // at 30.4m (DCM): 5e-3 * (30.4-29) = 5e-3 * 1.4 = 7.0 mm
  assertClose(_nomBeamX(30.4) * 1e3, 7.0, 0.01, 'nomBeamX(30.4m) = 7.0 mm (DCM)');

  // At M2 (32m): 5e-3 * (32-29) = 15 mm
  assertClose(_nomBeamX(32) * 1e3, 15.0, 0.01, 'nomBeamX(32m) = 15.0 mm (M2)');

  // After M2: constant 15 mm
  assertClose(_nomBeamX(58) * 1e3, 15.0, 0.01, 'nomBeamX(58m) = 15.0 mm (SSA)');
  assertClose(_nomBeamX(150) * 1e3, 15.0, 0.01, 'nomBeamX(150m) = 15.0 mm (sample)');
})();
sectionEnd();

// ─── T7: Si form factor & Darwin width ──────────
section('T7: siFf, siFh, darwinW');
(function() {
  // siFf at s=0: sum of all coefficients
  var ff0 = siFf(0);
  assertClose(ff0, 14.0016, 0.01, 'siFf(0) ~ 14.00 (Si Z=14)');

  // siFh at 10 keV: should be positive
  state.crystal = '111';
  var fh10 = siFh(10);
  assert(fh10 > 0 && fh10 < 100, 'siFh(10keV) in range: ' + fh10.toFixed(2));

  // Darwin width at 10 keV: should be few arcsec
  var dw10 = darwinW(10);
  assert(dw10 > 1 && dw10 < 30, 'darwinW(10keV) in [1,30] arcsec: ' + dw10.toFixed(2) + '"');

  // Darwin width decreases with energy (higher E -> narrower rocking curve)
  var dw5 = darwinW(5);
  var dw20 = darwinW(20);
  assert(dw5 > dw20, 'darwinW(5keV) > darwinW(20keV): ' + dw5.toFixed(2) + ' > ' + dw20.toFixed(2));
})();
sectionEnd();

// ─── T8: erf_a — error function approximation ───
section('T8: erf_a — error function');
(function() {
  // erf(0) = 0
  assertClose(erf_a(0), 0, 1e-6, 'erf(0) = 0');
  // erf(inf) -> 1
  assertClose(erf_a(5), 1.0, 1e-6, 'erf(5) ~ 1');
  // erf(-x) = -erf(x)
  assertClose(erf_a(-1), -erf_a(1), 1e-6, 'erf(-1) = -erf(1)');
  // erf(1) ~ 0.8427
  assertClose(erf_a(1), 0.8427, 0.001, 'erf(1) ~ 0.8427');
})();
sectionEnd();

// ─── T9: optConst — optical constants (fallback) ─
section('T9: optConst — delta/beta (legacy fallback)');
(function() {
  // delta should be positive, beta should be positive
  var ocPt = optConst(10, PT);
  assert(ocPt.delta > 0, 'Pt delta > 0 at 10keV');
  assert(ocPt.beta > 0, 'Pt beta > 0 at 10keV');
  assert(ocPt.delta > ocPt.beta, 'delta > beta for metals at 10keV');

  var ocRh = optConst(10, RH);
  assert(ocRh.delta > 0, 'Rh delta > 0 at 10keV');
  assert(ocRh.beta > 0, 'Rh beta > 0 at 10keV');

  // delta ~ 1/E^2 (approximately)
  var oc5 = optConst(5, PT);
  var oc20 = optConst(20, PT);
  assert(oc5.delta > oc20.delta, 'Pt delta(5keV) > delta(20keV)');
})();
sectionEnd();

// ─── T10: cross-checks ─────────────────────────
section('T10: cross-consistency checks');
(function() {
  // Critical angle ~ sqrt(2*delta) should be in mrad range for metals
  var oc = optConst(10, PT);
  var thc = Math.sqrt(2 * oc.delta) * 1e3; // mrad
  assert(thc > 1 && thc < 10, 'Pt critical angle @ 10keV ~ ' + thc.toFixed(1) + ' mrad');

  // Mirror R should be high below critical angle, low above
  var rBelow = mirrorR(10, thc * 0.5, PT, 0);
  var rAbove = mirrorR(10, thc * 2, PT, 0);
  assert(rBelow > rAbove, 'R(below Ec) > R(above Ec)');

  // Bragg angle monotonically decreases with energy
  state.crystal = '111';
  var prev = braggAngle(5);
  for (var e = 6; e <= 25; e++) {
    var curr = braggAngle(e);
    if (!isNaN(curr) && !isNaN(prev)) {
      assert(curr < prev, 'bragg(' + e + 'keV) < bragg(' + (e - 1) + 'keV)');
      prev = curr;
    }
  }
})();
sectionEnd();

// ─── T11: undulator physics ──────────────────────
section('T11: calcB0, calcK, calcE1, findHarmonics');
(function() {
  // calcB0: magnetic field from gap (Halbach model)
  var B0_7 = calcB0(7.0);
  assert(B0_7 > 0.3 && B0_7 < 2.0, 'calcB0(7mm) in [0.3, 2.0] T: ' + B0_7.toFixed(3) + ' T');
  // Field decreases with gap
  var B0_10 = calcB0(10.0);
  assert(B0_7 > B0_10, 'B0(7mm) > B0(10mm)');
  var B0_20 = calcB0(20.0);
  assert(B0_10 > B0_20, 'B0(10mm) > B0(20mm)');

  // calcK: K-parameter
  var K7 = calcK(B0_7);
  assert(K7 > 0.5 && K7 < 5, 'K(7mm gap) in [0.5, 5]: ' + K7.toFixed(2));
  assert(calcK(B0_10) < K7, 'K decreases with gap');
  assertClose(calcK(0), 0, 1e-10, 'K(B0=0) = 0');

  // calcE1: fundamental energy
  var E1 = calcE1(K7);
  assert(E1 > 2 && E1 < 30, 'E1(K@7mm) in [2,30] keV: ' + E1.toFixed(2) + ' keV');
  // Higher K -> lower E1
  assert(calcE1(2.0) < calcE1(1.0), 'E1(K=2) < E1(K=1)');

  // solveGap: round-trip consistency
  var gapRT = solveGap(B0_7);
  assertClose(gapRT, 7.0, 0.1, 'solveGap(B0(7)) ~ 7.0 mm: ' + gapRT.toFixed(2));
  var gapRT2 = solveGap(calcB0(15.0));
  assertClose(gapRT2, 15.0, 0.1, 'solveGap(B0(15)) ~ 15.0 mm');

  // findHarmonics: standard energy
  state.crystal = '111';
  var h10 = findHarmonics(10);
  assert(Array.isArray(h10), 'findHarmonics(10) returns array');
  assert(h10.length > 0, 'findHarmonics(10) has at least 1 harmonic');
  // Check first harmonic structure
  var h1 = h10[0];
  assert(typeof h1.n === 'number', 'harmonic has n');
  assert(typeof h1.K === 'number', 'harmonic has K');
  assert(typeof h1.B0 === 'number', 'harmonic has B0');
  assert(typeof h1.gap === 'number', 'harmonic has gap');
  assert(typeof h1.flux === 'number', 'harmonic has flux');
  assert(typeof h1.Fn === 'number', 'harmonic has Fn');
  // Gap in valid range
  for (var i = 0; i < h10.length; i++) {
    assert(h10[i].gap >= 4.5 && h10[i].gap <= 30, 'harmonic gap in [4.5, 30]: ' + h10[i].gap.toFixed(1));
    assert(h10[i].n % 2 === 1, 'harmonic n is odd: ' + h10[i].n);
    assert(h10[i].flux > 0, 'harmonic flux > 0');
  }
  // 10 keV requires n>=3 (IVU24 @ 4GeV: n=1 max ~6keV)
  var hasN3 = h10.some(function(h) { return h.n === 3; });
  assert(hasN3, 'n=3 harmonic exists for 10keV');
  // n=1 at 5 keV should be reachable
  var h5 = findHarmonics(5);
  var hasN1at5 = h5.some(function(h) { return h.n === 1; });
  assert(hasN1at5, 'n=1 harmonic exists for 5keV');

  // High energy: 25 keV should still find harmonics
  var h25 = findHarmonics(25);
  assert(h25.length > 0, 'findHarmonics(25) has harmonics');

  // Very low energy: 2 keV may have no valid gaps
  var h2 = findHarmonics(2);
  assert(Array.isArray(h2), 'findHarmonics(2) returns array');

  // Very high energy: 40 keV beyond range
  var h40 = findHarmonics(40);
  assert(Array.isArray(h40), 'findHarmonics(40) returns array (may be empty)');
})();
sectionEnd();

// ─── T12: flux chain ────────────────────────────
section('T12: dcmBandwidth, sourceFlux');
(function() {
  state.crystal = '111';

  // dcmBandwidth: fractional energy resolution
  var bw10 = dcmBandwidth(10);
  assert(bw10 > 0, 'dcmBandwidth(10) > 0');
  assert(bw10 < 0.01, 'dcmBandwidth(10) < 1% (fractional): ' + bw10.toExponential(2));
  // Si(111) BW ~ 1.3e-4 at 10 keV (typical)
  assert(bw10 > 1e-5 && bw10 < 1e-3, 'dcmBandwidth(10) in [1e-5, 1e-3]: ' + bw10.toExponential(2));

  // BW at different energies
  var bw5 = dcmBandwidth(5);
  var bw20 = dcmBandwidth(20);
  assert(bw5 > 0, 'dcmBandwidth(5) > 0');
  assert(bw20 > 0, 'dcmBandwidth(20) > 0');

  // Below crystal cutoff -> 0
  var bwLow = dcmBandwidth(1.5);
  assertClose(bwLow, 0, 1e-10, 'dcmBandwidth(1.5keV) = 0 (below cutoff)');

  // Si(311): switch crystal
  state.crystal = '311';
  var bw311 = dcmBandwidth(10);
  assert(bw311 > 0, 'Si(311) dcmBandwidth(10) > 0');
  // Si(311) has narrower BW than Si(111)
  assert(bw311 < bw10, 'Si(311) BW < Si(111) BW at 10keV');
  state.crystal = '111'; // restore

  // sourceFlux: photons/s at source after DCM
  var fl10 = sourceFlux(10);
  assert(fl10 > 0, 'sourceFlux(10) > 0');
  // IVU24 @ 4GeV 400mA: expect > 1e10 ph/s in 0.1%BW equivalent
  assert(fl10 > 1e8, 'sourceFlux(10) > 1e8 ph/s: ' + fl10.toExponential(2));

  // Flux decreases at high energy (fewer photons)
  var fl25 = sourceFlux(25);
  assert(fl25 >= 0, 'sourceFlux(25) >= 0');

  // Flux at 5 keV
  var fl5 = sourceFlux(5);
  assert(fl5 > 0, 'sourceFlux(5) > 0');

  // NaN/undefined safety
  var flNaN = sourceFlux(NaN);
  assert(!isNaN(flNaN), 'sourceFlux(NaN) does not return NaN');
  assert(flNaN >= 0, 'sourceFlux(NaN) >= 0');
})();
sectionEnd();

// ─── T13: coupFn, onAxisFlux, besselJ ───────────
section('T13: coupFn, onAxisFlux, besselJ');
(function() {
  // besselJ: J0(0)=1, J1(0)=0
  assertClose(besselJ(0, 0), 1.0, 1e-10, 'J0(0) = 1');
  assertClose(besselJ(1, 0), 0.0, 1e-10, 'J1(0) = 0');
  // J0(pi) ~ -0.3042
  assertClose(besselJ(0, Math.PI), -0.3042, 0.001, 'J0(pi) ~ -0.3042');
  // J1(pi) ~ 0.2849 (approx, not used in coupling but good validation)

  // coupFn: coupling function for harmonics
  // At K=1, n=1: xi = 1/(4+2) = 1/6, F1 = 1*K^2*JJ^2/(1+K^2/2)^2
  var F1_K1 = coupFn(1, 1);
  assert(F1_K1 > 0, 'coupFn(K=1, n=1) > 0: ' + F1_K1.toFixed(4));
  assert(F1_K1 < 1, 'coupFn(K=1, n=1) < 1');

  // Higher harmonics have lower coupling (generally)
  var F3_K1 = coupFn(1, 3);
  assert(F3_K1 >= 0, 'coupFn(K=1, n=3) >= 0');

  // K=0: no radiation
  var F1_K0 = coupFn(0.01, 1);
  assert(F1_K0 >= 0, 'coupFn(K~0, n=1) >= 0');

  // onAxisFlux: on-axis flux in ph/s/0.1%BW
  var flux_K1_n1 = onAxisFlux(1, 1);
  assert(flux_K1_n1 > 0, 'onAxisFlux(K=1, n=1) > 0');
  // Expected range for IVU24: 1e13-1e15 ph/s/0.1%BW
  assert(flux_K1_n1 > 1e12 && flux_K1_n1 < 1e16, 'onAxisFlux in [1e12, 1e16]: ' + flux_K1_n1.toExponential(2));

  // Flux scales with K^2*Fn (at fixed n=1)
  var flux_K2_n1 = onAxisFlux(2, 1);
  assert(flux_K2_n1 > 0, 'onAxisFlux(K=2, n=1) > 0');
})();
sectionEnd();

// ═══════════════════════════════════════════════════
//   RESULTS
// ═══════════════════════════════════════════════════
console.log('');
console.log('---------------------------------');
if (_failed === 0) {
  console.log('ALL PASS: ' + _passed + '/' + _passed + ' tests passed');
  process.exit(0);
} else {
  console.log('FAILED: ' + _failed + '/' + (_passed + _failed) + ' tests failed');
  _errors.forEach(function(e) { console.log('  ' + e); });
  process.exit(1);
}
