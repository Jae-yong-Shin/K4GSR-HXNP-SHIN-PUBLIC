'use strict';
// ===== optics/divergence_lookup.js — Effective Divergence Precompute Table =====
// @module optics/divergence_lookup
// @exports fluxDivergenceLookup, fluxDivergenceLookupReady, _falDiv
//
// Companion to 04_flux_acceptance_lookup.js. This module serves a precomputed
// SPECTRA-style effective angular divergence (sigma_x', sigma_y') at a slit
// downstream of the undulator source, indexed by (K, n, Z):
//   { metadata: { K_min, K_max, K_step, n_values: [1,3,...,15],
//                 Z_values: [<floats, m>], ... },
//     data:     { "<K>": { "<n>": { "<Z>": [Sxp_urad, Syp_urad], ... }, ... }, ... } }
//
// Same lazy-fetch / pending-resolver pattern as _falState. Returns null on
// any miss so the caller can fall back to the analytic stub in
// optics/04_source.js: effectiveDivergence().
//
// Interpolation: trilinear in (K, n, Z) — except n is DISCRETE-ODD and the
// closest tabulated harmonic is selected (no n interpolation). K and Z are
// linearly interpolated.
//
// ES5-strict (var/function only, no arrow/const/let/template literals) to
// match the repo coding rules in CLAUDE.md.
//
// JSON path is configurable via window._FLUX_DIV_LOOKUP_URL for tests;
// default is served by server.py under /js/data/.

var _falDiv = {
  url: null,
  loading: false,
  loaded: false,
  failed: false,
  error: null,
  table: null,                // parsed data block: K -> n -> Z -> [Sxp, Syp]
  K_min: 0,
  K_max: 0,
  K_step: 0,
  n_set: null,                // hash {1:true, 3:true, ...} for fast lookup
  n_values: null,             // sorted asc array [1,3,5,...]
  Z_set: null,                // sorted asc array of tabulated Z (m)
  _pendingResolvers: null
};


function _falDivResolveUrl() {
  if (typeof window !== 'undefined' && window._FLUX_DIV_LOOKUP_URL) {
    return window._FLUX_DIV_LOOKUP_URL;
  }
  return 'js/data/divergence_lookup_default.json';
}


function _falDivIngestTable(payload) {
  var md = payload && payload.metadata;
  var data = payload && payload.data;
  if (!md || !data) {
    _falDiv.failed = true;
    _falDiv.error = 'divergence lookup JSON missing metadata/data';
    return;
  }
  _falDiv.table = data;
  _falDiv.K_min = parseFloat(md.K_min);
  _falDiv.K_max = parseFloat(md.K_max);
  _falDiv.K_step = parseFloat(md.K_step);
  var ns = {};
  var nArr = md.n_values || [1, 3, 5, 7, 9, 11, 13, 15];
  var nSorted = [];
  for (var i = 0; i < nArr.length; i++) {
    var nv = nArr[i] | 0;
    ns[nv] = true;
    nSorted.push(nv);
  }
  nSorted.sort(function (a, b) { return a - b; });
  _falDiv.n_set = ns;
  _falDiv.n_values = nSorted;
  var zArr = md.Z_values || [];
  var zSorted = [];
  for (var j = 0; j < zArr.length; j++) zSorted.push(parseFloat(zArr[j]));
  zSorted.sort(function (a, b) { return a - b; });
  _falDiv.Z_set = zSorted;
  _falDiv.loaded = true;
}


function _falDivStartLoad() {
  if (_falDiv.loaded || _falDiv.loading || _falDiv.failed) return;
  _falDiv.loading = true;
  _falDiv.url = _falDivResolveUrl();
  if (typeof fetch !== 'function') {
    _falDiv.failed = true;
    _falDiv.error = 'fetch unavailable';
    _falDiv.loading = false;
    _falDivFlushPending();
    return;
  }
  fetch(_falDiv.url, { cache: 'force-cache' }).then(function (r) {
    if (!r.ok) {
      _falDiv.failed = true;
      _falDiv.error = 'HTTP ' + r.status + ' on ' + _falDiv.url;
      _falDiv.loading = false;
      _falDivFlushPending();
      return;
    }
    return r.json().then(function (j) {
      _falDivIngestTable(j);
      _falDiv.loading = false;
      _falDivFlushPending();
    });
  }).catch(function (err) {
    _falDiv.failed = true;
    _falDiv.error = (err && err.message) ? err.message : String(err);
    _falDiv.loading = false;
    _falDivFlushPending();
  });
}


function _falDivFlushPending() {
  var arr = _falDiv._pendingResolvers;
  _falDiv._pendingResolvers = null;
  if (!arr) return;
  for (var i = 0; i < arr.length; i++) {
    try { arr[i](_falDiv.loaded); } catch (e) { /* swallow */ }
  }
}


// Returns a Promise that resolves true once the divergence lookup is loaded,
// false on terminal failure. Mirrors fluxAcceptanceLookupReady().
function fluxDivergenceLookupReady() {
  if (_falDiv.loaded) return Promise.resolve(true);
  if (_falDiv.failed) return Promise.resolve(false);
  if (!_falDiv.loading) _falDivStartLoad();
  return new Promise(function (resolve) {
    if (!_falDiv._pendingResolvers) _falDiv._pendingResolvers = [];
    _falDiv._pendingResolvers.push(resolve);
  });
}


// Pick the tabulated odd harmonic closest to the requested n. Ties (rare,
// since the table is odd-only) prefer the smaller n for stability.
function _falDivPickN(n) {
  var arr = _falDiv.n_values;
  if (!arr || arr.length === 0) return null;
  var nInt = n | 0;
  if (_falDiv.n_set && _falDiv.n_set[nInt]) return nInt;
  var best = arr[0];
  var bestD = Math.abs(arr[0] - nInt);
  for (var i = 1; i < arr.length; i++) {
    var d = Math.abs(arr[i] - nInt);
    if (d < bestD) { best = arr[i]; bestD = d; }
  }
  return best;
}


// Locate the K bracket [kLo, kHi] given a query K. Returns null on miss.
function _falDivKBracket(K) {
  var step = _falDiv.K_step;
  if (step <= 0) return null;
  var idx = (K - _falDiv.K_min) / step;
  var lo = Math.floor(idx);
  var nSteps = Math.round((_falDiv.K_max - _falDiv.K_min) / step);
  if (lo < 0) lo = 0;
  if (lo >= nSteps) lo = nSteps - 1;
  var hi = lo + 1;
  var K_lo = _falDiv.K_min + lo * step;
  var K_hi = _falDiv.K_min + hi * step;
  var frac = (K - K_lo) / step;
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;
  return { K_lo: K_lo, K_hi: K_hi, frac: frac };
}


// Locate the Z bracket [zLo, zHi] in the (possibly non-uniform) Z_set.
// Returns null on out-of-range miss.
function _falDivZBracket(Z) {
  var zArr = _falDiv.Z_set;
  if (!zArr || zArr.length === 0) return null;
  if (zArr.length === 1) {
    if (Math.abs(Z - zArr[0]) < 1e-9) {
      return { Z_lo: zArr[0], Z_hi: zArr[0], frac: 0 };
    }
    return null;
  }
  if (Z < zArr[0] - 1e-9) return null;
  if (Z > zArr[zArr.length - 1] + 1e-9) return null;
  for (var i = 0; i < zArr.length - 1; i++) {
    if (Z >= zArr[i] - 1e-9 && Z <= zArr[i + 1] + 1e-9) {
      var span = zArr[i + 1] - zArr[i];
      var frac = (span > 0) ? (Z - zArr[i]) / span : 0;
      if (frac < 0) frac = 0;
      if (frac > 1) frac = 1;
      return { Z_lo: zArr[i], Z_hi: zArr[i + 1], frac: frac };
    }
  }
  return null;
}


function _falDivFetchCell(K_key, n_key, Z_key) {
  var row = _falDiv.table[K_key];
  if (!row) return null;
  var nrow = row[n_key];
  if (!nrow) return null;
  var cell = nrow[Z_key];
  if (!cell) return null;
  var sxp, syp;
  if (cell.length !== undefined) { sxp = cell[0]; syp = cell[1]; }
  else { sxp = cell.Sxp_urad; syp = cell.Syp_urad; }
  if (typeof sxp !== 'number' || typeof syp !== 'number') return null;
  if (!isFinite(sxp) || !isFinite(syp)) return null;
  return { Sxp_urad: sxp, Syp_urad: syp };
}


// Format K / Z grid coordinates to the same string keys used at build time.
// Tables are written with K to 2 decimals (step 0.05) and Z to 2 decimals
// (typical 5 / 10 / 30 / 58 m). Adjust if the precompute script changes.
function _falDivFmtK(K) { return K.toFixed(2); }
function _falDivFmtZ(Z) { return Z.toFixed(2); }


// Trilinear lookup of (Sxp_urad, Syp_urad) at (K, n, Z) — n is selected by
// nearest tabulated harmonic; K and Z are linearly interpolated. Returns
// null on table-not-loaded, n-set-empty, or K/Z out of range. Side effect:
// lazily kicks off the JSON fetch on the first call.
function fluxDivergenceLookup(K, n, Z) {
  if (!_falDiv.loaded) {
    if (!_falDiv.loading && !_falDiv.failed) _falDivStartLoad();
    return null;
  }
  if (K < _falDiv.K_min - 1e-9 || K > _falDiv.K_max + 1e-9) return null;
  var nPick = _falDivPickN(n);
  if (nPick === null) return null;
  var kBr = _falDivKBracket(K);
  if (!kBr) return null;
  var zBr = _falDivZBracket(Z);
  if (!zBr) return null;
  var nKey = String(nPick);
  var kLoKey = _falDivFmtK(kBr.K_lo);
  var kHiKey = _falDivFmtK(kBr.K_hi);
  var zLoKey = _falDivFmtZ(zBr.Z_lo);
  var zHiKey = _falDivFmtZ(zBr.Z_hi);
  var c00 = _falDivFetchCell(kLoKey, nKey, zLoKey);
  var c01 = _falDivFetchCell(kLoKey, nKey, zHiKey);
  var c10 = _falDivFetchCell(kHiKey, nKey, zLoKey);
  var c11 = _falDivFetchCell(kHiKey, nKey, zHiKey);
  if (!c00 || !c01 || !c10 || !c11) return null;
  var fK = kBr.frac, fZ = zBr.frac;
  var sxp = (1 - fK) * ((1 - fZ) * c00.Sxp_urad + fZ * c01.Sxp_urad)
         +      fK   * ((1 - fZ) * c10.Sxp_urad + fZ * c11.Sxp_urad);
  var syp = (1 - fK) * ((1 - fZ) * c00.Syp_urad + fZ * c01.Syp_urad)
         +      fK   * ((1 - fZ) * c10.Syp_urad + fZ * c11.Syp_urad);
  return { Sxp_urad: sxp, Syp_urad: syp };
}


// Kick off the fetch as soon as the module loads, so the table is ready by
// the time effectiveDivergence() is called on initial render.
if (typeof window !== 'undefined') {
  try { _falDivStartLoad(); } catch (e) { /* swallow */ }
}


// ESM bridge: expose module-scoped functions to globalThis.
if (typeof fluxDivergenceLookup !== 'undefined') globalThis.fluxDivergenceLookup = fluxDivergenceLookup;
if (typeof fluxDivergenceLookupReady !== 'undefined') globalThis.fluxDivergenceLookupReady = fluxDivergenceLookupReady;
if (typeof _falDiv !== 'undefined') globalThis._falDiv = _falDiv;
