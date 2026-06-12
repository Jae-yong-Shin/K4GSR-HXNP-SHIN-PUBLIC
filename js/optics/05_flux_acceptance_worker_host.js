'use strict';
// ===== optics/05_flux_acceptance_worker_host.js — Phase 4 / Layer 3 host =====
// @module optics/05_flux_acceptance_worker_host
// @exports fluxAcceptanceWorker, fluxAcceptanceWorkerHarmonics, _fawState
//
// Companion to 05_flux_acceptance_worker.js. Spawns a dedicated Web Worker on
// first use and routes compute requests through it so the main thread is not
// blocked by the ~5-30 s CPU integral. The worker is kept alive for the page
// lifetime (reused across calls); concurrent calls are serialised via a
// per-call message id and a pending-promise map.
//
// Public API (returns Promises):
//   fluxAcceptanceWorker(K, n, halfH, halfV)
//       -> Promise<number>   peak partial flux at the requested point.
//   fluxAcceptanceWorkerHarmonics([{K,n}, ...], halfH, halfV)
//       -> Promise<Array<{K,n,flux}>>   batched form; computes all entries
//       in one worker postMessage round-trip.
//
// Timeout: each call rejects after 30 s if the worker has not responded
// (e.g. stuck on a pathological grid). The timeout does NOT terminate the
// worker; subsequent calls continue to use the same worker instance.
//
// ES5-strict (var/function only, no arrow/const/let/template literals).

var _fawState = {
  worker: null,       // Worker instance (lazy)
  workerUrl: null,    // resolved URL for the worker script
  pending: {},        // {id: {resolve, reject, timeoutHandle}}
  _nextId: 1,
  _failed: false,     // hard fault — no further attempts
  _failError: null,
  _initSent: false    // whether we have synced storage-ring constants to the worker
};


function _fawResolveWorkerUrl() {
  // Allow tests to override; otherwise serve from the static /js/ route.
  if (typeof window !== 'undefined' && window._FLUX_WORKER_URL) {
    return window._FLUX_WORKER_URL;
  }
  return 'js/optics/05_flux_acceptance_worker.js';
}


function _fawSpawn() {
  if (_fawState.worker) return _fawState.worker;
  if (_fawState._failed) return null;
  if (typeof Worker !== 'function') {
    _fawState._failed = true;
    _fawState._failError = 'Worker API unavailable in this runtime';
    return null;
  }
  _fawState.workerUrl = _fawResolveWorkerUrl();
  try {
    var w = new Worker(_fawState.workerUrl);
    _fawState.worker = w;
  } catch (e) {
    _fawState._failed = true;
    _fawState._failError = (e && e.message) ? e.message : String(e);
    return null;
  }
  _fawState.worker.onmessage = _fawOnMessage;
  _fawState.worker.onerror = _fawOnError;
  // Sync the user-editable storage-ring constants on first spawn so the
  // worker output mirrors the live UI state instead of the worker's own
  // module-default constants.
  _fawSendConstants();
  return _fawState.worker;
}


function _fawSendConstants() {
  if (_fawState._initSent) return;
  if (!_fawState.worker) return;
  var msg = { id: 0, type: 'set_constants' };
  // Best-effort pull from globals; if any are missing we just leave the
  // worker's defaults in place.
  if (typeof E_RING === 'number') msg.E_RING = E_RING;
  if (typeof I_RING === 'number') msg.I_RING = I_RING;
  if (typeof EMIT_X === 'number') msg.EMIT_X = EMIT_X;
  if (typeof EMIT_Y === 'number') msg.EMIT_Y = EMIT_Y;
  if (typeof BETA_X === 'number') msg.BETA_X = BETA_X;
  if (typeof BETA_Y === 'number') msg.BETA_Y = BETA_Y;
  if (typeof E_SPREAD === 'number') msg.E_SPREAD = E_SPREAD;
  try { _fawState.worker.postMessage(msg); _fawState._initSent = true; }
  catch (e) { /* swallow; we will retry on next call */ }
}


function _fawOnMessage(ev) {
  var msg = ev.data || {};
  var id = msg.id;
  if (id === 0 || id === undefined) return;  // ack from set_constants
  var slot = _fawState.pending[id];
  if (!slot) return;
  delete _fawState.pending[id];
  if (slot.timeoutHandle) {
    clearTimeout(slot.timeoutHandle);
  }
  if (msg.type === 'result') {
    if (msg.flux !== undefined) {
      slot.resolve(msg.flux);
    } else if (msg.results !== undefined) {
      slot.resolve(msg.results);
    } else {
      slot.reject(new Error('worker returned result with no payload'));
    }
  } else if (msg.type === 'error') {
    slot.reject(new Error(msg.message || 'worker error'));
  } else {
    slot.reject(new Error('worker returned unknown message type ' + msg.type));
  }
}


function _fawOnError(ev) {
  // Worker raised an uncaught error. Reject ALL pending calls so the caller
  // can fall back; mark the worker as failed so subsequent spawns fail fast.
  var keys = Object.keys(_fawState.pending);
  var errMsg = ev && ev.message ? ev.message : 'worker uncaught error';
  for (var i = 0; i < keys.length; i++) {
    var slot = _fawState.pending[keys[i]];
    if (slot.timeoutHandle) clearTimeout(slot.timeoutHandle);
    try { slot.reject(new Error(errMsg)); } catch (e) { /* swallow */ }
  }
  _fawState.pending = {};
  _fawState._failed = true;
  _fawState._failError = errMsg;
  try { _fawState.worker.terminate(); } catch (e) { /* swallow */ }
  _fawState.worker = null;
}


function _fawIssue(msg, timeoutMs) {
  if (_fawState._failed) {
    return Promise.reject(new Error('worker unavailable: ' + (_fawState._failError || 'unknown')));
  }
  var w = _fawSpawn();
  if (!w) {
    return Promise.reject(new Error('worker spawn failed: ' + (_fawState._failError || 'unknown')));
  }
  // Ensure constants are synced (no-op after first call).
  _fawSendConstants();
  var id = _fawState._nextId++;
  msg.id = id;
  return new Promise(function (resolve, reject) {
    var slot = { resolve: resolve, reject: reject, timeoutHandle: null };
    if (timeoutMs && timeoutMs > 0) {
      slot.timeoutHandle = setTimeout(function () {
        // Stale slot: drop it from the pending map so a late reply is ignored
        // but do NOT terminate the worker (other inflight calls are valid).
        delete _fawState.pending[id];
        reject(new Error('worker timeout after ' + timeoutMs + ' ms'));
      }, timeoutMs);
    }
    _fawState.pending[id] = slot;
    try {
      w.postMessage(msg);
    } catch (e) {
      delete _fawState.pending[id];
      if (slot.timeoutHandle) clearTimeout(slot.timeoutHandle);
      reject(new Error('worker postMessage failed: ' + ((e && e.message) ? e.message : String(e))));
    }
  });
}


// Compute one (K, n, halfH, halfV) point. 30 s default timeout.
function fluxAcceptanceWorker(K, n, halfH, halfV) {
  if (halfH === undefined) halfH = 20;
  if (halfV === undefined) halfV = halfH;
  return _fawIssue({
    type: 'compute',
    K: K, n: n, halfH: halfH, halfV: halfV
  }, 30000);
}


// Batched: compute many harmonics in one round-trip. Useful for the
// findHarmonicsAsync Layer-3 path (8 harmonics in a single message).
function fluxAcceptanceWorkerHarmonics(harms, halfH, halfV) {
  if (halfH === undefined) halfH = 20;
  if (halfV === undefined) halfV = halfH;
  if (!harms || !harms.length) return Promise.resolve([]);
  // Generous timeout: 8 harmonics worst-case ~30 s/each on cold cache.
  var timeoutMs = Math.max(60000, harms.length * 30000);
  return _fawIssue({
    type: 'compute_harmonics',
    harmonics: harms,
    halfH: halfH,
    halfV: halfV
  }, timeoutMs);
}


// ESM bridge: expose to globalThis.
if (typeof fluxAcceptanceWorker !== 'undefined') globalThis.fluxAcceptanceWorker = fluxAcceptanceWorker;
if (typeof fluxAcceptanceWorkerHarmonics !== 'undefined') globalThis.fluxAcceptanceWorkerHarmonics = fluxAcceptanceWorkerHarmonics;
if (typeof _fawState !== 'undefined') globalThis._fawState = _fawState;
