'use strict';
// ===== ui/07_meas_chart.js — MEAS Tab Canvas Chart =====
// @module ui/07_meas_chart
// @exports _handleMeasServerMessage, _measHandleDone, _measHandleError, _measHandleProgress, _measHandleResult, _measHandleXAFSBatch, _measHandleXRD2DResult, _measHandleXRF2DResult, _measHandleXRFSpectrumResult, updChart
// Extracted from 11_v433_fixes.js (DDD Phase 4)
// Canvas-direct rendering (no Chart.js dependency)

function updChart(tp) {
  var cv = document.getElementById('measChart');
  if (!cv) return;
  // Legacy Chart.js cleanup removed — now using Plotly / canvas-direct
  var ctx = cv.getContext('2d');
  var w = cv.parentElement ? cv.parentElement.clientWidth - 16 : 400;
  var h = 170;
  cv.width = w; cv.height = h;

  // 2D map mode
  if (tp === 'map2d' && state.map2D) {
    if (typeof _drawHeatmap2D === 'function') {
      var d = state.map2D;
      _drawHeatmap2D(cv, d.d, {
        x: d.xP, y: d.yP,
        xLabel: 'X (um)', yLabel: 'Y (um)',
        title: d.xP.length + 'x' + d.yP.length,
        width: w, height: h,
        showColorbar: true
      });
    }
    return;
  }

  // 1D chart mode — delegate to _drawChart1D
  var data = state.scanData;
  if (!data || data.length < 2) return;
  if (typeof _drawChart1D === 'function') {
    var colors = { xanes: '#4db8ff', xrf: '#e870a0' };
    var xlabels = { xanes: 'E (eV)', xrf: 'E (keV)' };
    var ylabels = { xanes: '\u00b5(E)', xrf: 'Counts' };
    _drawChart1D(cv, data, {
      color: colors[tp] || '#4db8ff',
      xlabel: xlabels[tp] || 'X',
      ylabel: ylabels[tp] || 'Y',
      barMode: tp === 'xrf',
      nTicksX: 6, nTicksY: 5,
      title: data.length + ' pts',
      width: w, height: h,
      xFmt: function(v) { return tp === 'xanes' ? v.toFixed(0) : v.toFixed(1); }
    });
  }

  // [DDD inline merged from detector/02_sdd.js] Update live popup canvas
  var measLiveCv = document.getElementById('measLiveCanvas');
  if (measLiveCv) {
    if (tp === 'map2d' && state.map2D) {
      if (typeof renderLiveMap2D === 'function') renderLiveMap2D(measLiveCv, state.map2D);
    } else if (state.scanData && state.scanData.length > 1) {
      if (typeof renderScan1DPopup === 'function') renderScan1DPopup(measLiveCv, state.scanData, tp);
    }
    // Update info + progress
    var measInfo = document.getElementById('measLiveInfo');
    if (measInfo) {
      var nPts = state.scanData ? state.scanData.length : 0;
      measInfo.textContent = state.scanning ? nPts + ' points...' : 'Done -- ' + nPts + ' points';
      measInfo.style.color = state.scanning ? 'var(--am)' : 'var(--gn)';
    }
    var measProg = document.getElementById('measLiveProg');
    var origProg2 = document.getElementById('scanProg');
    if (measProg && origProg2) measProg.style.width = origProg2.style.width;
  }
}


// ============================================================
//  Server-side Meas scan handlers
//  Routes: _handleExptServerMessage -> _handleMeasServerMessage
//  when _measScanActive === true
// ============================================================

function _handleMeasServerMessage(msg) {
  var type = msg.type;

  if (type === 'expt_progress') {
    _measHandleProgress(msg);
  } else if (type === 'expt_data') {
    // Streaming batch (XAFS)
    if (msg.mode === 'xafs' && msg.batch) {
      _measHandleXAFSBatch(msg);
    }
  } else if (type === 'expt_result') {
    _measHandleResult(msg);
  } else if (type === 'expt_done') {
    _measHandleDone(msg);
  } else if (type === 'expt_error') {
    _measHandleError(msg);
  } else if (type === 'expt_cancelled') {
    _measScanActive = false;
    _measScanTechnique = '';
    state.scanning = false;
    var el = document.getElementById('scanStatus');
    if (el) { el.textContent = 'CANCELLED'; el.style.color = 'var(--rd)'; }
  }
}

// -- Progress --
function _measHandleProgress(msg) {
  var frac = msg.fraction || 0;
  var pct = (frac * 100).toFixed(0) + '%';
  var el = document.getElementById('scanProg');
  if (el) el.style.width = pct;
  var lp = document.getElementById('measLiveProg');
  if (lp) lp.style.width = pct;
  var info = document.getElementById('measLiveInfo');
  if (info && msg.msg) {
    info.textContent = msg.msg;
    info.style.color = 'var(--am)';
  }
}

// -- XAFS streaming batch -> state.scanData --
function _measHandleXAFSBatch(msg) {
  var batch = msg.batch;
  for (var i = 0; i < batch.length; i++) {
    state.scanData.push(batch[i]);
  }
  var pct = ((msg.progress || 0) * 100).toFixed(0) + '%';
  var el = document.getElementById('scanProg');
  if (el) el.style.width = pct;
  if (state.scanData.length > 2) updChart('xanes');
}

// -- Result dispatcher --
function _measHandleResult(msg) {
  var mode = msg.mode;
  var tech = _measScanTechnique;

  if (mode === 'xafs') {
    // Final data may come in result or was already streamed
    var data = msg.data || state.scanData;
    if (data && data.length > 0 && data !== state.scanData) {
      state.scanData = data;
    }
    updChart('xanes');
  } else if (mode === 'xrd2d') {
    _measHandleXRD2DResult(msg);
  } else if (mode === 'xrf2d') {
    if (tech === 'xrf') {
      _measHandleXRFSpectrumResult(msg);
    } else {
      _measHandleXRF2DResult(msg);
    }
  }
}

// -- XRF 1D spectrum (from xrf2d 1x1 grid) --
function _measHandleXRFSpectrumResult(msg) {
  state.scanData = [];
  if (msg.spectrum && msg.spectrum.channels) {
    var chs = msg.spectrum.channels;
    var ePerCh = msg.spectrum.ePerCh || 10;
    for (var i = 0; i < chs.length; i++) {
      state.scanData.push({x: i * ePerCh / 1000, y: chs[i]});
    }
  }
  updChart('xrf');
}

// -- XRF 2D map --
function _measHandleXRF2DResult(msg) {
  var elements = msg.elements || [];
  var maps = msg.maps || {};
  var info = msg.info || {};
  var nx = info.nx || 0;
  var ny = info.ny || 0;

  // Pick first element with data for the 2D map
  var elKey = '';
  for (var ei = 0; ei < elements.length; ei++) {
    if (maps[elements[ei]]) { elKey = elements[ei]; break; }
  }

  if (elKey && maps[elKey] && nx > 0 && ny > 0) {
    // Rebuild position arrays from info
    var xP = [], yP = [];
    var xStart = info.x_start || 0;
    var yStart = info.y_start || 0;
    var step = info.step_um || 1;
    for (var xi = 0; xi < nx; xi++) xP.push(xStart + xi * step);
    for (var yi = 0; yi < ny; yi++) yP.push(yStart + yi * step);

    state.map2D = { xP: xP, yP: yP, d: maps[elKey] };
    state.scanData = [];
    for (var sy = 0; sy < ny; sy++) {
      for (var sx = 0; sx < nx; sx++) {
        state.scanData.push({x: xP[sx], y: yP[sy], val: maps[elKey][sy][sx]});
      }
    }
  }

  // Also extract spectrum if available
  if (msg.spectrum && msg.spectrum.channels) {
    var chs2 = msg.spectrum.channels;
    var ePerCh2 = msg.spectrum.ePerCh || 10;
    state._xrfSpectrum = [];
    for (var si = 0; si < chs2.length; si++) {
      state._xrfSpectrum.push({x: si * ePerCh2 / 1000, y: chs2[si]});
    }
  }
  updChart('map2d');
}

// -- XRD 2D: Debye-Scherrer -> 1D pattern --
function _measHandleXRD2DResult(msg) {
  var rings = msg.rings || [];
  state.scanData = [];
  if (rings.length > 0) {
    var tthMin = 0, tthMax = 90, nPts = 900;
    for (var ti = 0; ti < nPts; ti++) {
      var tth = tthMin + (tthMax - tthMin) * ti / (nPts - 1);
      var yVal = 0;
      for (var ri = 0; ri < rings.length; ri++) {
        var pk = rings[ri];
        var dt = tth - pk.twoTheta;
        var sig = (pk.fwhm || 0.15) / 2.355;
        yVal += (pk.I || 0) * Math.exp(-0.5 * dt * dt / (sig * sig));
      }
      state.scanData.push({x: tth, y: yVal});
    }
  }
  updChart('xrd2d');
}

// -- Done --
function _measHandleDone(msg) {
  _measScanActive = false;
  state.scanning = false;
  var elapsed = msg.elapsed_sec || 0;
  var statusEl = document.getElementById('scanStatus');
  if (statusEl) {
    statusEl.textContent = 'DONE';
    statusEl.style.color = 'var(--gn)';
  }
  var progEl = document.getElementById('scanProg');
  if (progEl) progEl.style.width = '100%';
  log('info', 'Scan done (server): ' + state.scanData.length + ' pts' +
    (elapsed > 0 ? ' in ' + elapsed.toFixed(2) + 's' : ''));
  // Update live popup
  var info = document.getElementById('measLiveInfo');
  if (info) {
    info.textContent = 'Complete: ' + state.scanData.length + ' points' +
      (elapsed > 0 ? ' (' + elapsed.toFixed(2) + 's)' : '');
    info.style.color = 'var(--gn)';
  }
  var lp = document.getElementById('measLiveProg');
  if (lp) lp.style.width = '100%';
}

// -- Error --
function _measHandleError(msg) {
  _measScanActive = false;
  _measScanTechnique = '';
  state.scanning = false;
  var errMsg = msg.message || 'unknown error';
  var statusEl = document.getElementById('scanStatus');
  if (statusEl) {
    statusEl.textContent = 'ERROR';
    statusEl.style.color = 'var(--rd)';
  }
  log('err', 'Scan error: ' + errMsg);
  var info = document.getElementById('measLiveInfo');
  if (info) {
    info.textContent = 'Error: ' + errMsg;
    info.style.color = 'var(--rd)';
  }
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof updChart!=="undefined")globalThis.updChart=updChart;
if(typeof _handleMeasServerMessage!=="undefined")globalThis._handleMeasServerMessage=_handleMeasServerMessage;
if(typeof _measHandleDone!=="undefined")globalThis._measHandleDone=_measHandleDone;
if(typeof _measHandleError!=="undefined")globalThis._measHandleError=_measHandleError;
if(typeof _measHandleProgress!=="undefined")globalThis._measHandleProgress=_measHandleProgress;
if(typeof _measHandleResult!=="undefined")globalThis._measHandleResult=_measHandleResult;
if(typeof _measHandleXAFSBatch!=="undefined")globalThis._measHandleXAFSBatch=_measHandleXAFSBatch;
if(typeof _measHandleXRD2DResult!=="undefined")globalThis._measHandleXRD2DResult=_measHandleXRD2DResult;
if(typeof _measHandleXRF2DResult!=="undefined")globalThis._measHandleXRF2DResult=_measHandleXRF2DResult;
if(typeof _measHandleXRFSpectrumResult!=="undefined")globalThis._measHandleXRFSpectrumResult=_measHandleXRFSpectrumResult;
