'use strict';
// ===== optics/04_flux_acceptance_lookup.js — Phase 4 / Layer 1 =====
// @module optics/04_flux_acceptance_lookup
// @exports fluxAcceptanceLookup, fluxAcceptanceLookupReady, _falState
//
// Layer 1 of the 3-layer fallback for the harmonic partial-flux integral
// (precompute -> WebGPU -> Web Worker). The lookup table is a build-time
// product of Scripts/build_flux_acceptance_lookup.py and lives at
//   js/data/flux_acceptance_lookup_default_wb.json
// Structure:
//   { metadata: { halfH_urad, halfV_urad, K_min, K_max, K_step,
//                 n_values: [1,3,...,15], ... },
//     data:     { "0.50": {"1": <flux>, "3": ..., ...}, "0.55": {...}, ... } }
//
// Behaviour:
//   - The module fetches the JSON once at first use. fetch is launched lazily
//     on the first fluxAcceptanceLookup() call so module load does not block.
//   - fluxAcceptanceLookup(K, n, halfH_urad, halfV_urad) returns a number if
//     all four conditions hold:
//       (a) the table is loaded,
//       (b) halfH and halfV are within +/-2% of the table's halfH_urad /
//           halfV_urad (i.e. the caller is using the manuscript-default WB),
//       (c) n is one of the tabulated harmonics (1,3,5,7,9,11,13,15),
//       (d) K is inside [K_min, K_max].
//     Otherwise it returns null and the caller falls through to Layer 2/3.
//   - K interpolation is linear between adjacent grid points (step 0.05).
//
// ES5-strict (var/function only, no arrow/const/let/template literals) to match
// the repo coding rules in CLAUDE.md.
//
// JSON path is configurable via window._FLUX_LOOKUP_URL for tests; default is
// served by server.py under /js/data/ (Phase 3 static routing).

var _falState = {
  url: null,                  // resolved URL once load starts
  loading: false,             // fetch in-flight
  loaded: false,              // fetch resolved successfully
  failed: false,              // fetch rejected; no further retries
  error: null,
  table: null,                // parsed JSON payload
  K_min: 0,
  K_max: 0,
  K_step: 0,
  n_set: null,                // object hash {1:true, 3:true, ...}
  halfH_urad: 0,
  halfV_urad: 0,
  _pendingResolvers: null     // [resolveFn,...] called once the fetch finishes
};


// Return the lookup-table JSON URL: window._FLUX_LOOKUP_URL override if set, else 'js/data/flux_acceptance_lookup_default_wb.json'.
function _falResolveUrl() {
  // Browser: relative URL works against the page origin (server.py serves /js/).
  // Node/jsdom tests can override via window._FLUX_LOOKUP_URL.
  if (typeof window !== 'undefined' && window._FLUX_LOOKUP_URL) {
    return window._FLUX_LOOKUP_URL;
  }
  return 'js/data/flux_acceptance_lookup_default_wb.json';
}


// Parse fetched payload into _falState: store data rows, K_min/K_max/K_step, halfH/halfV_urad, harmonic n_set hash; set loaded or failed.
function _falIngestTable(payload) {
  var md = payload && payload.metadata;
  var data = payload && payload.data;
  if (!md || !data) {
    _falState.failed = true;
    _falState.error = 'lookup JSON missing metadata/data';
    return;
  }
  _falState.table = data;
  _falState.K_min = parseFloat(md.K_min);
  _falState.K_max = parseFloat(md.K_max);
  _falState.K_step = parseFloat(md.K_step);
  _falState.halfH_urad = parseFloat(md.halfH_urad);
  _falState.halfV_urad = parseFloat(md.halfV_urad);
  var ns = {};
  var arr = md.n_values || [1, 3, 5, 7, 9, 11, 13, 15];
  for (var i = 0; i < arr.length; i++) ns[arr[i] | 0] = true;
  _falState.n_set = ns;
  _falState.loaded = true;
}


// Once-only lazy fetch of the lookup JSON (force-cache); on resolve calls _falIngestTable, then flushes pending readiness resolvers; sets failed if fetch missing or errors.
function _falStartLoad() {
  if (_falState.loaded || _falState.loading || _falState.failed) return;
  _falState.loading = true;
  _falState.url = _falResolveUrl();
  if (typeof fetch !== 'function') {
    _falState.failed = true;
    _falState.error = 'fetch unavailable';
    _falState.loading = false;
    _falFlushPending();
    return;
  }
  fetch(_falState.url, { cache: 'force-cache' }).then(function (r) {
    if (!r.ok) {
      _falState.failed = true;
      _falState.error = 'HTTP ' + r.status + ' on ' + _falState.url;
      _falState.loading = false;
      _falFlushPending();
      return;
    }
    return r.json().then(function (j) {
      _falIngestTable(j);
      _falState.loading = false;
      _falFlushPending();
    });
  }).catch(function (err) {
    _falState.failed = true;
    _falState.error = (err && err.message) ? err.message : String(err);
    _falState.loading = false;
    _falFlushPending();
  });
}


// Drain _falState._pendingResolvers, invoking each queued readiness promise resolver with the loaded boolean (errors swallowed).
function _falFlushPending() {
  var arr = _falState._pendingResolvers;
  _falState._pendingResolvers = null;
  if (!arr) return;
  for (var i = 0; i < arr.length; i++) {
    try { arr[i](_falState.loaded); } catch (e) { /* swallow */ }
  }
}


// Returns a Promise that resolves true once the lookup table is loaded
// (or false if loading failed). Callers can use this to gate their first
// fluxAcceptanceLookup pass; fluxAcceptanceLookup() itself never throws and
// just returns null on a cold cache, so awaiting is optional.
function fluxAcceptanceLookupReady() {
  if (_falState.loaded) return Promise.resolve(true);
  if (_falState.failed) return Promise.resolve(false);
  if (!_falState.loading) _falStartLoad();
  return new Promise(function (resolve) {
    if (!_falState._pendingResolvers) _falState._pendingResolvers = [];
    _falState._pendingResolvers.push(resolve);
  });
}


// Returns the partial flux at (K, n, halfH, halfV) from the precomputed
// table, or null if the requested point cannot be served (table not yet
// loaded, n out of set, halfH/halfV not the manuscript default, or K out
// of [K_min, K_max]). Side effect: kicks off a lazy fetch on the first
// call so subsequent calls succeed once the JSON arrives.
function fluxAcceptanceLookup(K, n, halfH_urad, halfV_urad) {
  if (!_falState.loaded) {
    if (!_falState.loading && !_falState.failed) _falStartLoad();
    return null;
  }
  if (halfH_urad === undefined) halfH_urad = _falState.halfH_urad;
  if (halfV_urad === undefined) halfV_urad = halfH_urad;
  // (b) WB half-angle must be within +/-2% of the tabulated default.
  var tolH = Math.abs(_falState.halfH_urad) * 0.02;
  var tolV = Math.abs(_falState.halfV_urad) * 0.02;
  if (tolH < 1e-6) tolH = 1e-6;
  if (tolV < 1e-6) tolV = 1e-6;
  if (Math.abs(halfH_urad - _falState.halfH_urad) > tolH) return null;
  if (Math.abs(halfV_urad - _falState.halfV_urad) > tolV) return null;
  // (c) n must be in the tabulated set.
  var nInt = n | 0;
  if (!_falState.n_set || !_falState.n_set[nInt]) return null;
  // (d) K must be inside [K_min, K_max].
  if (K < _falState.K_min - 1e-9 || K > _falState.K_max + 1e-9) return null;
  // Linear interpolation between bracketing K grid nodes.
  var step = _falState.K_step;
  if (step <= 0) return null;
  // Index of left grid point (0-based). Saturate so kHi exists.
  var kIdxF = (K - _falState.K_min) / step;
  var kLo = Math.floor(kIdxF);
  var nSteps = Math.round((_falState.K_max - _falState.K_min) / step);
  if (kLo < 0) kLo = 0;
  if (kLo >= nSteps) kLo = nSteps - 1;
  var kHi = kLo + 1;
  var K_lo = _falState.K_min + kLo * step;
  var K_hi = _falState.K_min + kHi * step;
  var keyLo = K_lo.toFixed(2);
  var keyHi = K_hi.toFixed(2);
  var rowLo = _falState.table[keyLo];
  var rowHi = _falState.table[keyHi];
  if (!rowLo || !rowHi) return null;
  var nKey = String(nInt);
  var vLo = rowLo[nKey];
  var vHi = rowHi[nKey];
  if (typeof vLo !== 'number' || typeof vHi !== 'number') return null;
  if (!isFinite(vLo) || !isFinite(vHi)) return null;
  var frac = (K - K_lo) / step;
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;
  return vLo * (1 - frac) + vHi * frac;
}


// Kick off the fetch as soon as the module loads, so the table is ready by
// the time updateHarmPanel runs on initial render. Safe even if fetch is
// missing (no-op fallthrough).
if (typeof window !== 'undefined') {
  try { _falStartLoad(); } catch (e) { /* swallow */ }
}


// ESM bridge: expose module-scoped functions to globalThis.
if (typeof fluxAcceptanceLookup !== 'undefined') globalThis.fluxAcceptanceLookup = fluxAcceptanceLookup;
if (typeof fluxAcceptanceLookupReady !== 'undefined') globalThis.fluxAcceptanceLookupReady = fluxAcceptanceLookupReady;
if (typeof _falState !== 'undefined') globalThis._falState = _falState;
