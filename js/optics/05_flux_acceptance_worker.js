'use strict';
// ===== optics/05_flux_acceptance_worker.js — Phase 4 / Layer 3 =====
//
// Dedicated Web Worker that runs the CPU fluxAcceptance() implementation off
// the main thread. The host (05_flux_acceptance_worker_host.js) spawns a single
// instance of this worker on first use, sends compute requests over postMessage,
// and resolves a Promise when the worker posts back the result.
//
// IMPORTANT: this file is fetched directly as a Worker script (not bundled into
// the page <script>). It must be SELF-CONTAINED — we cannot rely on globals
// that live on the page's window. We re-declare the small handful of physics
// constants and the besselJ / fLinFxy2 / fluxAcceptance routines we need.
// The math is line-for-line identical to js/optics/01_undulator.js so a
// later refactor that consolidates the source would not change numerics.
//
// ES5-strict (var/function only, no arrow/const/let/template literals).

// ---- Ring + undulator physics constants (mirror js/shared/01_constants.js) ----
var E_RING = 4.0;
var I_RING = 400;
var I_RING_A = I_RING / 1000;
var GAMMA_E = E_RING * 1e3 / 0.511;

var EMIT_X = 62e-12;
var EMIT_Y = 6.2e-12;
var BETA_X = 6.334;
var BETA_Y = 2.841;
var E_SPREAD = 1.20e-3;

var SIG_EXP = Math.sqrt(EMIT_X / BETA_X);
var SIG_EYP = Math.sqrt(EMIT_Y / BETA_Y);

var LAMBDA_U = 24;
var LAMBDA_U_M = 0.024;
var N_PERIODS = 123;
var L_UND = N_PERIODS * LAMBDA_U_M;
var HC = 12.3984;

// Optional dynamic refresh: the host can send `{type:'set_constants', E_RING,
// I_RING, EMIT_X, ...}` if the user has edited the storage-ring parameters in
// the UI; we recompute the derived sigmas. This keeps the worker output
// consistent with the live state instead of frozen at worker-creation time.
function _setConstants(c) {
  if (typeof c.E_RING === 'number') E_RING = c.E_RING;
  if (typeof c.I_RING === 'number') { I_RING = c.I_RING; I_RING_A = I_RING / 1000; }
  if (typeof c.EMIT_X === 'number') EMIT_X = c.EMIT_X;
  if (typeof c.EMIT_Y === 'number') EMIT_Y = c.EMIT_Y;
  if (typeof c.BETA_X === 'number') BETA_X = c.BETA_X;
  if (typeof c.BETA_Y === 'number') BETA_Y = c.BETA_Y;
  if (typeof c.E_SPREAD === 'number') E_SPREAD = c.E_SPREAD;
  GAMMA_E = E_RING * 1e3 / 0.511;
  SIG_EXP = Math.sqrt(EMIT_X / BETA_X);
  SIG_EYP = Math.sqrt(EMIT_Y / BETA_Y);
}


// ---- Undulator helpers (mirror js/optics/01_undulator.js, identical math) ----
function calcE1(K) {
  return 0.9498 * E_RING * E_RING / ((LAMBDA_U / 10) * (1 + K * K / 2));
}

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

function _cdiv(a, b) {
  var q = Math.floor(Math.abs(a) / Math.abs(b));
  return ((a < 0) !== (b < 0)) ? -q : q;
}

function _jnS(m, x) {
  return m >= 0 ? besselJ(m, x) : (((-m) % 2 === 0 ? 1 : -1) * besselJ(-m, x));
}

function coupFn(K, n) {
  var xi = K * K / (4 + 2 * K * K);
  var j1 = besselJ(Math.floor((n - 1) / 2), n * xi);
  var j2 = besselJ(Math.floor((n + 1) / 2), n * xi);
  var JJ = j1 - j2;
  return n * n * K * K * JJ * JJ / Math.pow(1 + K * K / 2, 2);
}

function fLinFxy2(K, nh, gt, phi) {
  var gsi = nh / (1 + K * K / 2 + gt * gt), z = K * K * gsi / 4;
  var u = Math.cos(phi), v = Math.sin(phi);
  var x = 2 * gt * K * gsi * u;
  var INF = 1e-30, fx0, fy0, s1, s2, m, ia, ib, nn, bjx, bjz1, bjz2, ds1, ds2, ssum, dssum, fds, ds1a;
  if (Math.abs(x) > 1e-3) {
    s1 = INF; s2 = INF; ssum = INF; ds1a = s1; m = 1;
    while (m < 200) {
      ia = _cdiv(2 * m - 1 - nh, 2); ib = _cdiv(-2 * m + 1 - nh, 2);
      bjz1 = _jnS(ia, z); bjz2 = _jnS(ib, z); nn = 2 * m - 1; bjx = _jnS(nn, x);
      ds1 = bjx * (bjz1 - bjz2); ds2 = bjx * (ia * bjz1 - ib * bjz2);
      s1 += ds1; s2 += ds2;
      dssum = Math.abs(bjx) + Math.abs(bjz1) + Math.abs(bjz2); ssum += Math.abs(dssum);
      fds = (dssum + ds1a) / ssum; ds1a = dssum;
      fds = Math.max(fds, Math.abs(ds1 / (s1 + INF)), Math.abs(ds2 / (s2 + INF))); m++;
      if (fds <= 1e-9) break;
    }
    fx0 = -(nh * s1 + 2 * s2) / gt / u + 2 * gt * gsi * s1 * u;
    fy0 = 2 * s1 * gt * v * gsi;
  } else {
    var naa = _cdiv(-nh - 1, 2), nbb = _cdiv(-nh + 1, 2);
    s1 = _jnS(1, x) * (_jnS(nbb, z) - _jnS(naa, z)); s2 = _jnS(naa, z) + _jnS(nbb, z);
    fx0 = gsi * (2 * s1 * gt * u - K * s2); fy0 = 2 * gsi * s1 * gt * v;
  }
  return fx0 * fx0 + fy0 * fy0;
}

function _undGrids(K, n) {
  var s0 = Math.sqrt((HC / (n * calcE1(K))) * 1e-10 / (2 * L_UND));
  var thmax = 5 * Math.max(SIG_EXP, SIG_EYP) / (2 * s0);
  return {
    nA: Math.min(81, Math.max(41, Math.ceil(12 * thmax) | 1)),
    nE: Math.max(31, Math.ceil(80 * n * N_PERIODS * E_SPREAD) | 1)
  };
}


// ---- fluxAcceptance: peak partial-flux integrator (mirrors 01_undulator.js) ----
function fluxAcceptance(K, n, halfH_urad, halfV_urad) {
  if (halfH_urad === undefined) halfH_urad = 20;
  if (halfV_urad === undefined) halfV_urad = halfH_urad;
  var E1 = calcE1(K), En0 = n * E1;
  var H = 1 + K * K / 2, g2 = GAMMA_E * GAMMA_E;
  var N = N_PERIODS, sd = E_SPREAD, piNn = Math.PI * n * N;
  var bw = 7.0 / (n * N);
  var COEF = 1.744e14 * N * N * E_RING * E_RING * I_RING_A;
  function _grid(sig, m) {
    var v = [], w = [], s = 0, j, x, ww;
    for (j = 0; j < m; j++) { x = (-5 + 10 * j / (m - 1)) * sig; ww = Math.exp(-x * x / (2 * sig * sig)); v.push(x); w.push(ww); s += ww; }
    for (j = 0; j < m; j++) w[j] /= s;
    return { v: v, w: w };
  }
  var gr = _undGrids(K, n);
  var gd = _grid(sd, gr.nE);
  var gx = _grid(SIG_EXP, gr.nA);
  var gy = _grid(SIG_EYP, gr.nA);
  var halfRadH = halfH_urad * 1e-6;
  var halfRadV = halfV_urad * 1e-6;
  var nObs = 21;
  var dObsH = (2 * halfRadH) / (nObs - 1);
  var dObsV = (2 * halfRadV) / (nObs - 1);
  var dOmegaMrad2 = (dObsH * 1e3) * (dObsV * 1e3);
  var nEgrid = 41;
  var Elo = En0 * (1 - bw * 2.0), Ehi = En0 * (1 + bw * 0.5);
  var Egrid = new Array(nEgrid), dE = (Ehi - Elo) / (nEgrid - 1), ig;
  for (ig = 0; ig < nEgrid; ig++) Egrid[ig] = Elo + ig * dE;
  var pflux = new Array(nEgrid); for (ig = 0; ig < nEgrid; ig++) pflux[ig] = 0;
  var ox, oy, a, b, id, Ox, Oy, thx, thy, psix, psiy, psi2, gt, redA, amp, wab, En, wgt, xs, sc2;
  for (ox = 0; ox < nObs; ox++) {
    Ox = -halfRadH + ox * dObsH;
    for (oy = 0; oy < nObs; oy++) {
      Oy = -halfRadV + oy * dObsV;
      for (a = 0; a < gx.v.length; a++) {
        thx = gx.v[a];
        for (b = 0; b < gy.v.length; b++) {
          thy = gy.v[b];
          psix = Ox - thx; psiy = Oy - thy; psi2 = psix * psix + psiy * psiy;
          gt = GAMMA_E * Math.sqrt(psi2);
          redA = 1 / (1 + g2 * psi2 / H);
          amp = COEF * fLinFxy2(K, n, gt, Math.atan2(psiy, psix));
          wab = gx.w[a] * gy.w[b] * dOmegaMrad2;
          for (id = 0; id < gd.v.length; id++) {
            En = En0 * (1 + gd.v[id]) * (1 + gd.v[id]) * redA;
            wgt = amp * wab * gd.w[id];
            for (ig = 0; ig < nEgrid; ig++) {
              xs = piNn * (Egrid[ig] / En - 1);
              sc2 = (xs > -1e-10 && xs < 1e-10) ? 1 : Math.pow(Math.sin(xs) / xs, 2);
              pflux[ig] += wgt * sc2;
            }
          }
        }
      }
    }
  }
  var peak = 0, k; for (k = 0; k < nEgrid; k++) if (pflux[k] > peak) peak = pflux[k];
  return peak;
}


// ---- Message router ----
// Inbound messages:
//   {id, type:'set_constants', ...constants}
//       Updates the worker's E_RING/I_RING/... state.
//   {id, type:'compute', K, n, halfH, halfV}
//       Posts back {id, type:'result', flux} (or {id, type:'error', message}).
//   {id, type:'compute_harmonics', harmonics:[{K,n}, ...], halfH, halfV}
//       Iterates over the request list and posts back {id, type:'result',
//       results:[{K, n, flux}, ...]}. Useful for the findHarmonicsAsync
//       Layer-3 path that needs all 8 harmonics; consolidating into one
//       postMessage avoids 8 round-trips.
self.onmessage = function (ev) {
  var msg = ev.data || {};
  var id = msg.id;
  try {
    if (msg.type === 'set_constants') {
      _setConstants(msg);
      self.postMessage({ id: id, type: 'ack' });
      return;
    }
    if (msg.type === 'compute') {
      var flux = fluxAcceptance(msg.K, msg.n, msg.halfH, msg.halfV);
      self.postMessage({ id: id, type: 'result', flux: flux });
      return;
    }
    if (msg.type === 'compute_harmonics') {
      var arr = msg.harmonics || [];
      var out = [];
      for (var i = 0; i < arr.length; i++) {
        var item = arr[i];
        var f = fluxAcceptance(item.K, item.n, msg.halfH, msg.halfV);
        out.push({ K: item.K, n: item.n, flux: f });
      }
      self.postMessage({ id: id, type: 'result', results: out });
      return;
    }
    self.postMessage({ id: id, type: 'error', message: 'unknown message type ' + msg.type });
  } catch (e) {
    self.postMessage({ id: id, type: 'error', message: (e && e.message) ? e.message : String(e) });
  }
};
