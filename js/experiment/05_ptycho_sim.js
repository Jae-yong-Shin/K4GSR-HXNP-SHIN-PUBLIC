'use strict';
// ===== experiment/05_ptycho_sim.js — Ptychography (K4GSR-PTYCHO WebSocket Integration) =====
// @module experiment/05_ptycho_sim
// @exports PTYCHO_WS_PORT, PTYCHO_WS_URL, _REF_INDEX, _addPoissonNoise, _buildSynthParams, _cmapCache, _createComplexObject, _createFresnelSincProbe, _decodeRawComplex, _fermatSpiral, _fft1d, _fft2d, _fftshift, _fluxToPhotons, _genResolutionChartThickness, ...
// Primary: WebSocket client to K4GSR-PTYCHO server (ws://localhost:8765)
// Fallback: JS forward model for offline use

// ══════════════════════════════════════════════════════════════════
//  Section 1: WebSocket Client (K4GSR-PTYCHO ptycho_server.py)
// ══════════════════════════════════════════════════════════════════

var _ptychoWs = null;
var _ptychoConnected = false;
var _ptychoReconnectTimer = null;
var _ptychoDataLoaded = false;
var _ptychoRunning = false;
var _ptychoGpuAvailable = false;

// Raw data from server (interleaved float32 complex)
var _ptychoRawData = {
  object: null, objectShape: null,
  probe: null,  probeShape: null
};

// Iteration tracking
var _ptychoIteration = 0;
var _ptychoTotalIterations = 0;
var _ptychoErrorHistory = [];
var _ptychoCurrentJobId = null;

// Pipeline tracking — for "DM 50/300 + LSQML 30" style progress
var _ptychoPipelineInfo = { engine: '', stage1Name: '', stage2Name: '', stage1Total: 0, stage2Total: 0, stage: 0 };

// Pending preview (deferred rendering — matches K4GSR-PTYCHO 02_ws.js pattern)
var _ptychoPendingPreview = null;
var _ptychoPreviewRafPending = false;

// Callback for rendering — set by 07_experiment_run.js
var _ptychoOnPreviewReady = null; // function(msg) — quick preview (no fmag)
var _ptychoOnDataLoaded = null;   // function(msg) — full data with fmag
var _ptychoOnIterUpdate = null;   // function(msg) — called with preview data for canvas render
var _ptychoOnComplete = null;     // function(msg)
var _ptychoOnError = null;        // function(msg)
var _ptychoCurrentEngine = '';    // current engine name (DM, ML, etc.)

// Ptycho server URL: follows SERVER_HOST for future workstation migration
// Local: ws://localhost:8765, Workstation: ws://{SERVER_HOST}:8765
var PTYCHO_WS_PORT = 8765;
var PTYCHO_WS_URL = 'ws://' +
  ((typeof SERVER_HOST !== 'undefined' && SERVER_HOST !== 'localhost' && SERVER_HOST !== '127.0.0.1')
    ? 'localhost' : 'localhost') + ':' + PTYCHO_WS_PORT;
// Override via URL param: ?ptycho_host=141.223.48.182
(function() {
  var _qp2 = (typeof location !== 'undefined' && location.search) ? new URLSearchParams(location.search) : null;
  if (_qp2 && _qp2.get('ptycho_host')) PTYCHO_WS_URL = 'ws://' + _qp2.get('ptycho_host') + ':' + PTYCHO_WS_PORT;
  if (_qp2 && _qp2.get('ptycho_port')) {
    PTYCHO_WS_PORT = parseInt(_qp2.get('ptycho_port'));
    PTYCHO_WS_URL = PTYCHO_WS_URL.replace(/:\d+$/, ':' + PTYCHO_WS_PORT);
  }
})();

// ── Connect to K4GSR-PTYCHO server ──
window.ptychoConnect = function(url) {
  url = url || PTYCHO_WS_URL;
  if (_ptychoWs && _ptychoWs.readyState <= 1) return;

  try {
    _ptychoWs = new WebSocket(url);
  } catch(e) {
    _ptychoConnected = false;
    _updatePtychoConnectionUI(false);
    return;
  }

  _ptychoWs.onopen = function() {
    _ptychoConnected = true;
    _updatePtychoConnectionUI(true);
    console.log('[Ptycho] Connected: ' + url);
    // Ping to get GPU status
    _ptychoSend({type: 'ping'});
    // Notify waiters (event-driven, no polling needed)
    if (typeof _ptychoOnConnect === 'function') {
      _ptychoOnConnect();
      _ptychoOnConnect = null;
    }
  };

  _ptychoWs.onclose = function() {
    _ptychoConnected = false;
    _updatePtychoConnectionUI(false);
    console.log('[Ptycho] Disconnected');
    clearTimeout(_ptychoReconnectTimer);
    _ptychoReconnectTimer = setTimeout(function() { ptychoConnect(url); }, 5000);
  };

  _ptychoWs.onerror = function() {
    _ptychoConnected = false;
    _updatePtychoConnectionUI(false);
  };

  _ptychoWs.onmessage = function(e) {
    var msg;
    try { msg = JSON.parse(e.data); } catch(err) {
      console.error('[Ptycho] JSON parse error, data len=' + (e.data ? e.data.length : 0));
      return;
    }
    var _mType = msg.type || '?';
    console.log('[Ptycho] Received: type=' + _mType +
      ', data len=' + (e.data ? e.data.length : 0));
    // Debug: show message flow in info bar
    var _dbgEl = document.getElementById('exptPopup_ptycho_info');
    if (_dbgEl && _mType !== 'log') {
      _dbgEl.textContent = '[WS] ' + _mType +
        (_mType === 'error' ? ': ' + (msg.error || '') : '') +
        (_mType === 'iteration_update' ? ' iter=' + msg.iteration : '');
    }
    try { _ptychoHandleMessage(msg); } catch(err) {
      console.error('[Ptycho] handleMessage error:', err, err.stack);
      if (_dbgEl) _dbgEl.textContent = '[ERROR] ' + err.message;
    }
  };
};

// ── Disconnect ──
window.ptychoDisconnect = function() {
  clearTimeout(_ptychoReconnectTimer);
  _ptychoReconnectTimer = null;
  if (_ptychoWs) {
    _ptychoWs.onclose = null; // prevent reconnect
    _ptychoWs.close();
    _ptychoWs = null;
  }
  _ptychoConnected = false;
  _updatePtychoConnectionUI(false);
};

// ── Send message ──
function _ptychoSend(obj) {
  if (_ptychoWs && _ptychoWs.readyState === 1) {
    _ptychoWs.send(JSON.stringify(obj));
  } else {
    console.warn('[Ptycho] Not connected');
  }
}

// ── Handle incoming messages (matches ptycho_server.py protocol) ──
function _ptychoHandleMessage(msg) {
  switch (msg.type) {
    case 'pong':
      _ptychoGpuAvailable = msg.gpu_available || false;
      console.log('[Ptycho] GPU: ' + (_ptychoGpuAvailable ? 'ON' : 'OFF') +
        '  v' + (msg.version || '?'));
      break;

    case 'preview_ready':
      // Quick preview: object + probe + positions (no fmag)
      console.log('[Ptycho] preview_ready msg keys:', Object.keys(msg),
        ', has preview:', !!msg.preview,
        ', preview keys:', msg.preview ? Object.keys(msg.preview) : 'none');
      if (msg.preview) {
        if (msg.preview.raw_object) {
          _ptychoRawData.object = _decodeRawComplex(msg.preview.raw_object);
          _ptychoRawData.objectShape = msg.preview.raw_object_shape;
          console.log('[Ptycho] Decoded object: len=' + _ptychoRawData.object.length +
            ', shape=' + JSON.stringify(_ptychoRawData.objectShape));
        } else {
          console.warn('[Ptycho] preview_ready: no raw_object in preview');
        }
        if (msg.preview.raw_probe) {
          _ptychoRawData.probe = _decodeRawComplex(msg.preview.raw_probe);
          _ptychoRawData.probeShape = msg.preview.raw_probe_shape;
          console.log('[Ptycho] Decoded probe: len=' + _ptychoRawData.probe.length +
            ', shape=' + JSON.stringify(_ptychoRawData.probeShape));
        } else {
          console.warn('[Ptycho] preview_ready: no raw_probe in preview');
        }
      } else {
        console.warn('[Ptycho] preview_ready: no preview data in message');
      }
      console.log('[Ptycho] Preview ready: ' + (msg.info ? msg.info.num_positions + ' positions' : 'ok') +
        ', callback=' + (typeof _ptychoOnPreviewReady));
      if (typeof _ptychoOnPreviewReady === 'function') _ptychoOnPreviewReady(msg);
      break;

    case 'data_loaded':
      _ptychoDataLoaded = true;
      // Update raw data if previews included (reconstruction updates)
      if (msg.preview) {
        if (msg.preview.raw_object) {
          _ptychoRawData.object = _decodeRawComplex(msg.preview.raw_object);
          _ptychoRawData.objectShape = msg.preview.raw_object_shape;
        }
        if (msg.preview.raw_probe) {
          _ptychoRawData.probe = _decodeRawComplex(msg.preview.raw_probe);
          _ptychoRawData.probeShape = msg.preview.raw_probe_shape;
        }
      }
      console.log('[Ptycho] Data loaded: ' + (msg.info ? msg.info.num_positions + ' positions' : 'ok'));
      if (typeof _ptychoOnDataLoaded === 'function') _ptychoOnDataLoaded(msg);
      break;

    case 'data_load_error':
      _ptychoDataLoaded = false;
      console.error('[Ptycho] Data load failed: ' + msg.error);
      if (typeof _ptychoOnError === 'function') _ptychoOnError(msg);
      break;

    case 'reconstruction_started':
      _ptychoRunning = true;
      _ptychoCurrentJobId = msg.job_id;
      _ptychoTotalIterations = msg.total_iterations;
      _ptychoIteration = 0;
      _ptychoErrorHistory = [];
      _ptychoCurrentEngine = (msg.engine || '').split('_')[0];
      // Build pipeline progress label: "DM 0/300 + LSQML 30"
      var _rsLabel = msg.engine + (msg.use_gpu ? ' [GPU]' : ' [CPU]');
      if (_ptychoPipelineInfo.stage > 0) {
        _rsLabel += ': ' + _ptychoPipelineInfo.stage1Name + ' 0/' + _ptychoPipelineInfo.stage1Total +
          ' + ' + _ptychoPipelineInfo.stage2Name + ' ' + _ptychoPipelineInfo.stage2Total;
      } else {
        _rsLabel += ' 0/' + msg.total_iterations;
      }
      console.log('[Ptycho] ' + msg.engine + (msg.use_gpu ? ' [GPU]' : ' [CPU]') +
        ' started (' + msg.total_iterations + ' iter)');
      if (typeof _updateExptProgress === 'function') {
        _updateExptProgress(0, _rsLabel);
      }
      break;

    case 'iteration_update':
      _ptychoIteration = msg.iteration;
      if (typeof msg.error === 'number') {
        _ptychoErrorHistory.push(msg.error);
      }
      // Always update progress bar (every iteration, not just when preview data arrives)
      if (typeof _updateExptProgress === 'function') {
        var _iEng = msg.engine || _ptychoCurrentEngine || '';
        var _iErr = (typeof msg.error === 'number') ? '  err=' + msg.error.toExponential(2) : '';
        var _iFrac, _iText;
        if (_ptychoPipelineInfo.stage > 0) {
          // Pipeline mode: overall progress across both stages
          var _iDone = (_ptychoPipelineInfo.stage === 1) ? msg.iteration :
            _ptychoPipelineInfo.stage1Total + msg.iteration;
          var _iGrandTotal = _ptychoPipelineInfo.stage1Total + _ptychoPipelineInfo.stage2Total;
          _iFrac = _iDone / Math.max(_iGrandTotal, 1);
          if (_ptychoPipelineInfo.stage === 1) {
            _iText = _iEng + ' ' + msg.iteration + '/' + _ptychoPipelineInfo.stage1Total +
              ' + ' + _ptychoPipelineInfo.stage2Name + ' ' + _ptychoPipelineInfo.stage2Total + _iErr;
          } else {
            _iText = _iEng + ' ' + msg.iteration + '/' + _ptychoTotalIterations +
              ' (' + _ptychoPipelineInfo.stage1Name + ' ' + _ptychoPipelineInfo.stage1Total + ' done)' + _iErr;
          }
        } else {
          // Single engine mode
          _iFrac = msg.iteration / Math.max(_ptychoTotalIterations, 1);
          _iText = _iEng + ' ' + msg.iteration + '/' + _ptychoTotalIterations + _iErr;
        }
        _updateExptProgress(_iFrac, _iText);
      }
      // Deferred rendering — only keep latest, drop intermediate (K4GSR-PTYCHO pattern)
      if (msg.raw_object || msg.raw_probe) {
        _ptychoPendingPreview = msg;
        if (!_ptychoPreviewRafPending) {
          _ptychoPreviewRafPending = true;
          setTimeout(function() {
            _ptychoPreviewRafPending = false;
            var m = _ptychoPendingPreview;
            _ptychoPendingPreview = null;
            if (m) {
              if (m.raw_object) {
                _ptychoRawData.object = _decodeRawComplex(m.raw_object);
                _ptychoRawData.objectShape = m.raw_object_shape;
              }
              if (m.raw_probe) {
                _ptychoRawData.probe = _decodeRawComplex(m.raw_probe);
                _ptychoRawData.probeShape = m.raw_probe_shape;
              }
              if (typeof _ptychoOnIterUpdate === 'function') _ptychoOnIterUpdate(m);
            }
          }, 20);
        }
      }
      break;

    case 'pipeline_stage_change':
      _ptychoTotalIterations = msg.total_iterations;
      _ptychoIteration = 0;
      _ptychoCurrentEngine = msg.engine || '';
      // Update pipeline tracking
      if (_ptychoPipelineInfo.stage > 0) {
        _ptychoPipelineInfo.stage = 2;
        _ptychoPipelineInfo.stage2Total = msg.total_iterations;
        _ptychoPipelineInfo.stage2Name = msg.engine || _ptychoPipelineInfo.stage2Name;
      }
      console.log('[Ptycho] Stage ' + msg.stage + ': ' + msg.engine + ' (' + msg.total_iterations + ' iter)');
      if (typeof _updateExptProgress === 'function') {
        var _scFrac = _ptychoPipelineInfo.stage1Total /
          Math.max(_ptychoPipelineInfo.stage1Total + _ptychoPipelineInfo.stage2Total, 1);
        _updateExptProgress(_scFrac,
          msg.engine + ' 0/' + msg.total_iterations +
          ' (' + _ptychoPipelineInfo.stage1Name + ' ' + _ptychoPipelineInfo.stage1Total + ' done)');
      }
      break;

    case 'reconstruction_complete':
      _ptychoRunning = false;
      _ptychoPendingPreview = null;
      _ptychoPreviewRafPending = false;
      if (msg.error_history && msg.error_history.length) {
        _ptychoErrorHistory = msg.error_history;
      }
      // Store final preview data
      if (msg.raw_object) {
        _ptychoRawData.object = _decodeRawComplex(msg.raw_object);
        _ptychoRawData.objectShape = msg.raw_object_shape;
      }
      if (msg.raw_probe) {
        _ptychoRawData.probe = _decodeRawComplex(msg.raw_probe);
        _ptychoRawData.probeShape = msg.raw_probe_shape;
      }
      console.log('[Ptycho] Complete: ' + (msg.total_time_sec || 0).toFixed(1) + 's');
      if (typeof _ptychoOnComplete === 'function') _ptychoOnComplete(msg);
      break;

    case 'reconstruction_error':
      _ptychoRunning = false;
      console.error('[Ptycho] Error: ' + msg.error);
      if (typeof _ptychoOnError === 'function') _ptychoOnError(msg);
      break;

    case 'reconstruction_cancelled':
      _ptychoRunning = false;
      _ptychoPendingPreview = null;
      _ptychoPreviewRafPending = false;
      console.warn('[Ptycho] Cancelled — server memory freed');
      if (typeof _exptState !== 'undefined') _exptState.running = false;
      if (typeof _updateExptProgress === 'function') _updateExptProgress(0, 'Cancelled (memory freed)');
      try {
        var _cancelEl = document.getElementById('ptychoSynthStatus');
        if (_cancelEl) _cancelEl.textContent = 'Cancelled (memory freed)';
      } catch(e) {}
      if (typeof _ptychoOnError === 'function') _ptychoOnError({error: 'Cancelled by user'});
      break;

    case 'reconstruction_warning':
      console.warn('[Ptycho] WARNING: ' + (msg.warning || ''));
      try {
        var _warnEl = document.getElementById('ptychoSynthStatus');
        if (_warnEl) _warnEl.textContent = msg.warning || 'Warning';
        if (typeof _ptychoOnIterUpdate === 'function') {
          _ptychoOnIterUpdate({warning: msg.warning, batched: msg.batched});
        }
      } catch(e) {}
      break;

    case 'synth_progress':
      console.log('[Ptycho] Progress: ' + (msg.msg || '') +
        ' (' + ((msg.fraction || 0) * 100).toFixed(0) + '%)');
      // Update status line in experiment panel if available
      var _spEl = document.getElementById('ptychoSynthStatus');
      if (_spEl) _spEl.textContent = msg.msg || 'Generating...';
      break;

    case 'log':
      // Server log messages — silent unless debug
      break;

    case 'error':
      console.error('[Ptycho] Server error: ' + msg.error);
      if (typeof _ptychoOnError === 'function') _ptychoOnError(msg);
      break;
  }
}

// ── Quick preview: object + probe + positions, no fmag (< 1s) ──
window.ptychoPreviewSynthetic = function(params) {
  _ptychoSend({type: 'preview_synthetic', params: params});
};

// ── Full generate: fmag computation (slow, needed for reconstruction) ──
window.ptychoGenerateSynthetic = function(params) {
  _ptychoSend({type: 'generate_synthetic', params: params});
};

// ── Start reconstruction on server ──
window.ptychoStartReconstruction = function(params) {
  params = params || {};
  var sendParams = {
    engine: params.engine || 'ePIE',
    use_gpu: params.use_gpu !== undefined ? params.use_gpu : _ptychoGpuAvailable
  };
  // Pipeline engines: separate iteration counts per stage
  if (sendParams.engine === 'DM_ML' || sendParams.engine === 'DM_LSQML') {
    sendParams.dm_iterations = params.dm_iterations || 300;
    sendParams.ml_iterations = params.ml_iterations || 30;
    sendParams.lsqml_iterations = params.lsqml_iterations || 20;
  } else if (sendParams.engine === 'ePIE_ML' || sendParams.engine === 'ePIE_LSQML') {
    sendParams.epie_iterations = params.epie_iterations || params.dm_iterations || 50;
    sendParams.ml_iterations = params.ml_iterations || 30;
    sendParams.lsqml_iterations = params.lsqml_iterations || 20;
  } else if (sendParams.engine === 'ePIE') {
    sendParams.number_iterations = params.number_iterations || params.dm_iterations || 200;
  } else {
    sendParams.number_iterations = params.number_iterations || 300;
  }
  // Pass through any extra params
  var keys = Object.keys(params);
  for (var i = 0; i < keys.length; i++) {
    if (sendParams[keys[i]] === undefined) sendParams[keys[i]] = params[keys[i]];
  }
  _ptychoSend({ type: 'start_reconstruction', params: sendParams });
};

// ── Cancel reconstruction ──
window.ptychoCancelReconstruction = function() {
  _ptychoSend({type: 'cancel_reconstruction'});
};

// ── Connection UI updater ──
function _updatePtychoConnectionUI(connected) {
  // Re-render ptycho tab to update connection status display
  if (_exptState && _exptState.mode === 'ptycho' && typeof renderExptTab === 'function') {
    try { renderExptTab(); } catch(e) {}
  }
}

// ══════════════════════════════════════════════════════════════════
//  Section 2: Raw Complex Data Decoder + Colormap Renderer
//  (Ported from K4GSR-PTYCHO colormaps.js)
// ══════════════════════════════════════════════════════════════════

// Decode interleaved float32 base64 → Float32Array [re0, im0, re1, im1, ...]
window._decodeRawComplex = function(b64) {
  var raw = Uint8Array.from(atob(b64), function(c) { return c.charCodeAt(0); });
  return new Float32Array(raw.buffer);
};

// ── Colormap LUT builder (K4GSR-PTYCHO colormaps.js port) ──
var _cmapCache = {};

function _getCmapLUT(name) {
  if (_cmapCache[name]) return _cmapCache[name];
  var lut = new Uint8Array(256 * 3);
  for (var i = 0; i < 256; i++) {
    var t = i / 255;
    var r, g, b;
    if (name === 'viridis') {
      // Simplified viridis
      if (t < 0.25) { r = 68+t*4*(49-68); g = 1+t*4*(104-1); b = 84+t*4*(142-84); }
      else if (t < 0.5) { var s=(t-0.25)*4; r = 49+s*(53-49); g = 104+s*(183-104); b = 142+s*(121-142); }
      else if (t < 0.75) { var s=(t-0.5)*4; r = 53+s*(187-53); g = 183+s*(223-183); b = 121+s*(39-121); }
      else { var s=(t-0.75)*4; r = 187+s*(253-187); g = 223+s*(231-223); b = 39+s*(37-39); }
    } else if (name === 'hot') {
      r = Math.min(1, t*3)*255; g = Math.max(0, Math.min(1, t*3-1))*255; b = Math.max(0, Math.min(1, t*3-2))*255;
    } else if (name === 'hsv') {
      var h = t * 6, hi = Math.floor(h), f = h - hi, q = 1 - f;
      if (hi === 0 || hi === 6) { r = 255; g = f*255; b = 0; }
      else if (hi === 1) { r = q*255; g = 255; b = 0; }
      else if (hi === 2) { r = 0; g = 255; b = f*255; }
      else if (hi === 3) { r = 0; g = q*255; b = 255; }
      else if (hi === 4) { r = f*255; g = 0; b = 255; }
      else { r = 255; g = 0; b = q*255; }
    } else if (name === 'gray') {
      r = g = b = t * 255;
    } else if (name === 'inferno') {
      if (t < 0.25) { r = t*4*95; g = 0; b = t*4*83+5; }
      else if (t < 0.5) { var s=(t-0.25)*4; r = 95+s*(180-95); g = s*32; b = 83+s*(50-83); }
      else if (t < 0.75) { var s=(t-0.5)*4; r = 180+s*(246-180); g = 32+s*(136-32); b = 50+s*(5-50); }
      else { var s=(t-0.75)*4; r = 246+s*(252-246); g = 136+s*(255-136); b = 5+s*(164-5); }
    } else {
      // Default gray
      r = g = b = t * 255;
    }
    lut[i*3]   = Math.max(0, Math.min(255, Math.round(r)));
    lut[i*3+1] = Math.max(0, Math.min(255, Math.round(g)));
    lut[i*3+2] = Math.max(0, Math.min(255, Math.round(b)));
  }
  _cmapCache[name] = lut;
  return lut;
}

// ── Render raw complex data to canvas (from server) ──
// Renders 4 panels: OBJ AMP, OBJ PHASE, PROBE AMP, DIFFRACTION (placeholder)
window.renderPtychoFromServer = function(canvas, info) {
  if (!canvas) { console.warn('[Ptycho render] No canvas'); return; }
  // Ensure canvas buffer matches layout size (CSS flex may give 0 initially)
  if (canvas.width < 10 && canvas.clientWidth > 0) {
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;
  }
  var cw = canvas.width;
  var ch = canvas.height;
  if (cw < 10 || ch < 10) {
    console.warn('[Ptycho render] Canvas too small: ' + cw + 'x' + ch);
    return;
  }
  var ctx = canvas.getContext('2d');
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, cw, ch);

  var gridH = ch;
  var pw = Math.floor(cw / 2), ph = Math.floor(gridH / 2);

  // 3 image panels + 1 error chart panel
  var imgPanels = [
    {title: 'Object Amplitude',  x: 0,  y: 0,  w: pw,        h: ph,         key: 'object', mode: 'amp',   cmap: 'jet'},
    {title: 'Object Phase',      x: pw, y: 0,  w: cw - pw,   h: ph,         key: 'object', mode: 'phase', cmap: 'hsv'},
    {title: 'Probe Amplitude',   x: 0,  y: ph, w: pw,        h: gridH - ph, key: 'probe',  mode: 'amp',   cmap: 'jet'}
  ];

  for (var pi = 0; pi < imgPanels.length; pi++) {
    var pnl = imgPanels[pi];
    var complex = _ptychoRawData[pnl.key];
    var shape = _ptychoRawData[pnl.key + 'Shape'];
    if (!complex || !shape) {
      ctx.fillStyle = '#22252b';
      ctx.fillRect(pnl.x, pnl.y, pnl.w, pnl.h);
      ctx.font = '10px monospace';
      ctx.fillStyle = '#6b7280';
      ctx.textAlign = 'center';
      ctx.fillText('No data', pnl.x + pnl.w / 2, pnl.y + pnl.h / 2);
      ctx.textAlign = 'left';
      continue;
    }

    var imgH = shape[0], imgW = shape[1];
    var n = imgH * imgW;

    var data = new Float32Array(n);
    if (pnl.mode === 'phase') {
      for (var i = 0; i < n; i++) {
        data[i] = Math.atan2(complex[2 * i + 1], complex[2 * i]);
      }
    } else {
      for (var i = 0; i < n; i++) {
        var re = complex[2 * i], im = complex[2 * i + 1];
        data[i] = Math.sqrt(re * re + im * im);
      }
    }

    // Robust scale
    var sorted = Float32Array.from(data);
    sorted.sort();
    var vmin, vmax;
    if (pnl.key === 'probe' && pnl.mode === 'amp') {
      var nzStart = 0;
      for (var zi = 0; zi < n; zi++) { if (sorted[zi] > 1e-12) { nzStart = zi; break; } }
      var nzCount = n - nzStart;
      if (nzCount > 1) {
        vmin = sorted[nzStart + Math.floor(0.005 * (nzCount - 1))];
        vmax = sorted[nzStart + Math.floor(0.995 * (nzCount - 1))];
      } else {
        vmin = sorted[0]; vmax = sorted[n - 1];
      }
    } else {
      vmin = sorted[Math.floor(0.005 * (n - 1))];
      vmax = sorted[Math.floor(0.995 * (n - 1))];
    }
    if (vmax - vmin < 1e-12) vmax = vmin + 1;

    var lut = _getCmapLUT(pnl.cmap);
    var inv = 255 / (vmax - vmin);
    var id = ctx.createImageData(pnl.w, pnl.h);
    var px = id.data;

    for (var y = 0; y < pnl.h; y++) {
      for (var x = 0; x < pnl.w; x++) {
        var sy = Math.floor(y * imgH / pnl.h);
        var sx = Math.floor(x * imgW / pnl.w);
        var v = data[sy * imgW + sx];
        var idx = (v - vmin) * inv;
        idx = idx < 0 ? 0 : (idx > 255 ? 255 : (idx + 0.5) | 0);
        var off = (y * pnl.w + x) * 4;
        px[off]     = lut[idx * 3];
        px[off + 1] = lut[idx * 3 + 1];
        px[off + 2] = lut[idx * 3 + 2];
        px[off + 3] = 255;
      }
    }
    ctx.putImageData(id, pnl.x, pnl.y);
  }

  // ── Bottom-right: Error convergence chart ──
  var errX = pw, errY = ph, errW = cw - pw, errH = gridH - ph;
  ctx.fillStyle = '#22252b';
  ctx.fillRect(errX, errY, errW, errH);
  if (_ptychoErrorHistory.length >= 2) {
    var eData = _ptychoErrorHistory;
    var eN = eData.length;
    var ePad = {l: 40, r: 8, t: 18, b: 18};
    var ePW = errW - ePad.l - ePad.r;
    var ePH = errH - ePad.t - ePad.b;
    if (ePW > 10 && ePH > 10) {
      var logArr = [];
      for (var ei = 0; ei < eN; ei++) {
        logArr.push(eData[ei] > 0 ? Math.log10(eData[ei]) : -10);
      }
      var eYMin = logArr[0], eYMax = logArr[0];
      for (var ei = 1; ei < eN; ei++) {
        if (logArr[ei] < eYMin) eYMin = logArr[ei];
        if (logArr[ei] > eYMax) eYMax = logArr[ei];
      }
      if (eYMax - eYMin < 0.1) { eYMin -= 0.5; eYMax += 0.5; }
      // Grid lines
      ctx.strokeStyle = 'rgba(80,160,255,0.08)';
      ctx.lineWidth = 0.5;
      ctx.font = '7px monospace';
      ctx.fillStyle = '#6b7280';
      ctx.textAlign = 'right';
      for (var gi = Math.ceil(eYMin); gi <= Math.floor(eYMax); gi++) {
        var gy = errY + ePad.t + ePH * (1 - (gi - eYMin) / (eYMax - eYMin));
        ctx.beginPath(); ctx.moveTo(errX + ePad.l, gy); ctx.lineTo(errX + ePad.l + ePW, gy); ctx.stroke();
        ctx.fillText('1e' + gi, errX + ePad.l - 3, gy + 3);
      }
      // Data line
      ctx.beginPath();
      ctx.strokeStyle = '#4db8ff';
      ctx.lineWidth = 1.5;
      for (var ej = 0; ej < eN; ej++) {
        var ex = errX + ePad.l + (ej / Math.max(eN - 1, 1)) * ePW;
        var ey = errY + ePad.t + ePH * (1 - (logArr[ej] - eYMin) / (eYMax - eYMin));
        if (ej === 0) ctx.moveTo(ex, ey); else ctx.lineTo(ex, ey);
      }
      ctx.stroke();
      // Axis labels
      ctx.fillStyle = '#6b7280';
      ctx.textAlign = 'center';
      ctx.font = '7px monospace';
      ctx.fillText('1', errX + ePad.l, errY + errH - 3);
      ctx.fillText('' + eN, errX + ePad.l + ePW, errY + errH - 3);
    }
  } else {
    ctx.font = '10px monospace';
    ctx.fillStyle = '#6b7280';
    ctx.textAlign = 'center';
    ctx.fillText('Error chart', errX + errW / 2, errY + errH / 2);
    ctx.textAlign = 'left';
  }

  // Panel labels
  ctx.font = '10px monospace';
  ctx.fillStyle = '#4db8ff';
  ctx.textAlign = 'left';
  for (var i = 0; i < imgPanels.length; i++) {
    ctx.fillText(imgPanels[i].title, imgPanels[i].x + 4, imgPanels[i].y + 13);
  }
  ctx.fillText('Error Convergence', errX + 4, errY + 13);

  // Grid lines
  ctx.strokeStyle = '#3d5068';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pw, 0); ctx.lineTo(pw, gridH);
  ctx.moveTo(0, ph); ctx.lineTo(cw, ph);
  ctx.stroke();

};

// ── Render error convergence plot ──
window.renderPtychoErrorPlot = function(canvas) {
  if (!canvas || _ptychoErrorHistory.length < 2) return;
  var ctx = canvas.getContext('2d');
  var w = canvas.width, h = canvas.height;
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, w, h);

  var data = _ptychoErrorHistory;
  var n = data.length;
  var pad = {l: 50, r: 10, t: 15, b: 25};
  var pw2 = w - pad.l - pad.r;
  var ph2 = h - pad.t - pad.b;

  // Log scale
  var logData = [];
  for (var i = 0; i < n; i++) {
    logData.push(data[i] > 0 ? Math.log10(data[i]) : -10);
  }
  var yMin = logData[0], yMax = logData[0];
  for (var i = 1; i < n; i++) {
    if (logData[i] < yMin) yMin = logData[i];
    if (logData[i] > yMax) yMax = logData[i];
  }
  if (yMax - yMin < 0.1) { yMin -= 0.5; yMax += 0.5; }

  // Grid
  ctx.strokeStyle = 'rgba(80,160,255,0.08)';
  ctx.lineWidth = 0.5;
  ctx.font = '8px monospace';
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'right';
  for (var i = Math.ceil(yMin); i <= Math.floor(yMax); i++) {
    var gy = pad.t + ph2 * (1 - (i - yMin) / (yMax - yMin));
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw2, gy); ctx.stroke();
    ctx.fillText('1e' + i, pad.l - 4, gy + 3);
  }

  // Data line
  ctx.beginPath();
  ctx.strokeStyle = '#4db8ff';
  ctx.lineWidth = 1.5;
  for (var j = 0; j < n; j++) {
    var x = pad.l + (j / (n - 1)) * pw2;
    var y = pad.t + ph2 * (1 - (logData[j] - yMin) / (yMax - yMin));
    if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Labels
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'center';
  ctx.fillText('Iteration', pad.l + pw2 / 2, h - 4);
  ctx.fillText('1', pad.l, h - 4);
  ctx.fillText('' + n, pad.l + pw2, h - 4);

  ctx.fillStyle = '#4db8ff';
  ctx.fillText('Error Convergence', w / 2, 10);
};


// ══════════════════════════════════════════════════════════════════
//  Section 3: Beamline Integration (Flux / Focal Spot)
// ══════════════════════════════════════════════════════════════════

// Flux to photons conversion
window._fluxToPhotons = function(energy_keV, dwellTime_s) {
  var flux = 1e10; // default
  try {
    if (typeof photonFlux === 'function') flux = photonFlux(energy_keV);
  } catch(e) {}
  return Math.round(flux * dwellTime_s);
};

// Get beamline info for display
window._getBeamlineInfo = function(energy_keV) {
  var info = {flux: 0, spotH: 50, spotV: 50, energy: energy_keV};
  try {
    if (typeof photonFlux === 'function') info.flux = photonFlux(energy_keV);
    if (typeof focalSpot === 'function') {
      var sp = focalSpot();
      info.spotH = sp.h;
      info.spotV = sp.v;
    }
  } catch(e) {}
  return info;
};

// ── Ptychography detector geometry calculator ──
// Real-space pixel size: dx = lambda * z / (N * det_pixel)
// Oversampling ratio: O = lambda * z / (det_pixel * probe_FWHM)
//   probe_FWHM is independent physical quantity (focused beam size)
//   NOT related to asize -- asize is the crop/computation window size
window._ptychoDetectorGeometry = function(energy_keV, z_m, detKey) {
  var det = (typeof EIGER_DETECTORS !== 'undefined' && EIGER_DETECTORS[detKey]) ?
    EIGER_DETECTORS[detKey] : null;
  var pixelSize = det ? det.pixelSize : 75e-6;   // 75 um default
  var pixelsH = det ? det.pixelsH : 1028;
  var pixelsV = det ? det.pixelsV : 1062;
  var detName = det ? det.name : 'EIGER2 X 1M';

  var lambda_m = 1239.842e-9 / (energy_keV * 1000);  // wavelength
  // Use smaller dimension for square cropped diffraction pattern (common practice)
  var N_det = Math.min(pixelsH, pixelsV);
  // Real-space pixel size at sample plane
  var dx_m = lambda_m * z_m / (N_det * pixelSize);
  var dx_nm = dx_m * 1e9;

  return {
    detector: detKey || 'EIGER2_1M',
    detName: detName,
    pixelSize: pixelSize,
    pixelsH: pixelsH,
    pixelsV: pixelsV,
    N_det: N_det,
    lambda_m: lambda_m,
    z_m: z_m,
    dx_m: dx_m,
    dx_nm: dx_nm
  };
};

// Compute oversampling ratio for given detector + probe size
window._ptychoOversampling = function(geom, asize) {
  // Oversampling = N_det / asize (for ptychography, the probe sets the Nyquist)
  // In real terms: O = lambda * z / (det_pixel * probe_real_size)
  //   probe_real_size = asize * dx = asize * lambda * z / (N_det * det_pixel)
  //   O = lambda * z / (det_pixel * asize * lambda * z / (N_det * det_pixel)) = N_det / asize
  return geom.N_det / asize;
};

// Build synthParams from UI state + beamline (K4GSR-PTYCHO format)
// Sends KB Fresnel probe params (rectangular aperture -> sinc beam)
window._buildSynthParams = function(ptyState) {
  var energy_keV = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  var N_photons = 1000;
  try { N_photons = _fluxToPhotons(energy_keV, ptyState.dwellTime || 0.1); } catch(e) {}

  var detKey = ptyState.ptychoDetector || 'EIGER2_1M';
  var z_m = ptyState.z_m || 2.0;
  var geom = _ptychoDetectorGeometry(energy_keV, z_m, detKey);

  // Auto step: beam * 0.4 for ~60% overlap if scan_step_um == 0
  var _sspBsz = {h:50,v:50}; try { if (typeof focalSpot === 'function') _sspBsz = focalSpot(); } catch(e) {}
  var _sspBeamMax = Math.max(_sspBsz.h, _sspBsz.v);
  var _sspStep = ptyState.scan_step_um > 0 ? ptyState.scan_step_um : (_sspBeamMax * 0.4 / 1000);

  // asize from UI (detector-dependent, user-adjustable)
  var _asize = ptyState.asize || 512;

  // ── Memory guard: estimate Npos and enforce fmag memory limit ──
  // fmag = (asize, asize, Npos) float32.  Server memory limit default: 4 GB.
  //
  // CRITICAL CONSTRAINT — Ptychography Overlap Requirement:
  //   Reconstruction algorithms (DM, ePIE, ML, LSQML) REQUIRE probe overlap
  //   ratio >= 60% for convergence.  overlap = 1 - step/beam_diameter.
  //   NEVER increase step to reduce Npos — it would violate this fundamental
  //   requirement and make reconstruction impossible.
  //
  // Instead of adjusting step, the memory guard reduces scan area to fit the
  // memory budget while preserving the step size (and thus overlap ratio).
  var _fmagLimitGB = 4;
  var _maxNpos = Math.floor(_fmagLimitGB * 1e9 / (_asize * _asize * 4));
  var _lx = ptyState.scan_lx_um || 3;
  var _ly = ptyState.scan_ly_um || 3;
  // Quick Npos estimate: pi * (scan_area / step^2) for Fermat spiral
  var _estNpos = Math.round(Math.PI * (_lx * _ly) / (_sspStep * _sspStep) * 0.25);
  if (_estNpos > _maxNpos && _maxNpos > 0) {
    // Strategy: shrink scan area proportionally (preserves step & overlap)
    var _areaRatio = _maxNpos / _estNpos;    // < 1
    var _sideRatio = Math.sqrt(_areaRatio);  // shrink each side equally
    var _newLx = _lx * _sideRatio;
    var _newLy = _ly * _sideRatio;
    var _overlapPct = Math.round((1 - _sspStep / (_sspBeamMax / 1000)) * 100);
    console.warn('[Ptycho] Memory guard: ' + _lx.toFixed(1) + 'x' + _ly.toFixed(1)
      + ' \u03bcm scan would create ~' + _estNpos + ' positions (fmag ~'
      + (_estNpos * _asize * _asize * 4 / 1e9).toFixed(1) + ' GB, limit ' + _fmagLimitGB + ' GB).'
      + ' Scan area reduced to ' + _newLx.toFixed(2) + 'x' + _newLy.toFixed(2) + ' \u03bcm'
      + ' (~' + _maxNpos + ' positions). Overlap ' + _overlapPct + '% preserved.');
    _lx = _newLx;
    _ly = _newLy;
    _estNpos = _maxNpos;
  }
  // dx = lambda*z / (asize * det_pixel)
  var _dxNm = geom.lambda_m * z_m / (_asize * geom.pixelSize) * 1e9;

  // KB Fresnel probe parameters (sinc beam from rectangular aperture)
  // Uses beam FWHM at sample from focalSpot() + KB mirror focal length
  var _mcProbe = null;
  try {
    var _samplePos = 150.0;
    var _kbvPos = 149.69;
    var _kbhPos = 149.90;
    if (typeof CD !== 'undefined' && Array.isArray(CD)) {
      for (var ci = 0; ci < CD.length; ci++) {
        if (CD[ci].id === 'sample') _samplePos = CD[ci].dp;
        if (CD[ci].id === 'kbv') _kbvPos = CD[ci].dp;
        if (CD[ci].id === 'kbh') _kbhPos = CD[ci].dp;
      }
    }
    // KB focal length = average of KBV and KBH image distances to sample
    var _kbFocalV = _samplePos - _kbvPos;   // ~0.31 m
    var _kbFocalH = _samplePos - _kbhPos;   // ~0.10 m
    var _kbFocal = (_kbFocalV + _kbFocalH) / 2.0;
    _mcProbe = {
      fwhm_h_m: _sspBsz.h * 1e-9,    // focalSpot() returns nm
      fwhm_v_m: _sspBsz.v * 1e-9,
      focal_length_m: _kbFocal,
      defocus_m: 0.0
    };
  } catch(e) {}

  // Estimated simulation time (2-pass FFT: 2 * Npos FFTs)
  var _fftMs = _asize <= 128 ? 0.1 : (_asize <= 256 ? 0.3 : (_asize <= 512 ? 1.0 : 2.5));
  var _estTimeSec = (2 * _estNpos * _fftMs) / 1000;
  var _estMemGB = (_asize * _asize * _estNpos * 4) / 1e9;
  console.log('[Ptycho] Estimate: ~' + _estNpos + ' positions, fmag ~'
    + _estMemGB.toFixed(2) + ' GB, ~' + _estTimeSec.toFixed(1) + 's simulation time');

  // ── Coherence parameters (NanoMAX criterion) ──
  var _cohInfo = null;
  try { _cohInfo = _ptychoCoherentFraction(energy_keV); } catch(e) {}
  var _fCoh = _cohInfo ? _cohInfo.coherent_fraction : 1.0;
  var _nModes = _cohInfo ? _cohInfo.N_modes : 1;

  return {
    dataset_id: ptyState.dataset_id || 6,
    material: ptyState.material || 'Au',
    energy_keV: energy_keV,
    objheight: (ptyState.objheight_um || 1.0) * 1e-6,
    asize: _asize,
    scan_step_um: _sspStep,
    scan_lx_um: _lx,
    scan_ly_um: _ly,
    z_m: z_m,
    N_photons: ptyState.N_photons || N_photons,
    noise_sigma: ptyState.noise_sigma || 0.0,
    rng_seed: 42,
    // KB Fresnel probe params (sinc beam from rectangular aperture)
    mc_probe: _mcProbe,
    probe_fwhm_nm: _sspBeamMax,
    dx_nm: _dxNm,
    // Detector geometry for server
    det_pixel_m: geom.pixelSize,
    det_pixels_h: geom.pixelsH,
    det_pixels_v: geom.pixelsV,
    N_det: geom.N_det,
    // Coherence (NanoMAX criterion)
    coherent_fraction: _fCoh,
    N_modes: _nModes,
    // Estimates for UI
    est_npos: _estNpos,
    est_mem_gb: _estMemGB,
    est_time_sec: _estTimeSec
  };
};


// ══════════════════════════════════════════════════════════════════
//  Section 3b: Coherence Model (Degree of Coherence at Sample)
// ══════════════════════════════════════════════════════════════════

// Transverse coherence length at sample plane via Van Cittert-Zernike theorem
// Two contributions:
// 1) Source-limited:  xi_src  = lambda * R_sample / (2*pi*sigma_source)
// 2) SSA-limited:     xi_ssa  = lambda * L_ssa2sample / (2*pi*sigma_ssa)
//    SSA acts as virtual source with sigma = halfgap/2.355
// Effective coherence = min(xi_src, xi_ssa) per axis (bottleneck)
window._ptychoCoherenceLength = function(energy_keV) {
  var lambda_m = 1239.842e-9 / (energy_keV * 1000);
  // Total photon source size from photonSrc (includes undulator diffraction)
  var ps = null;
  try { if (typeof photonSrc === 'function') ps = photonSrc(energy_keV); } catch(e) {}
  var sigH = ps ? ps.Sx : ((typeof SIG_EX !== 'undefined') ? SIG_EX : Math.sqrt(62e-12 * 6.334));
  var sigV = ps ? ps.Sy : ((typeof SIG_EY !== 'undefined') ? SIG_EY : Math.sqrt(6.2e-12 * 2.841));

  // Distances
  var R_ssa = 58;    // source -> SSA (m)
  var R_sample = 150; // source -> sample (m)
  try {
    if (typeof CD !== 'undefined' && Array.isArray(CD)) {
      for (var ci = 0; ci < CD.length; ci++) {
        if (CD[ci].id === 'ssa')    R_ssa = CD[ci].dp;
        if (CD[ci].id === 'sample') R_sample = CD[ci].dp;
      }
    }
  } catch(e) {}
  var L_ssa2sample = R_sample - R_ssa; // SSA -> sample distance (92 m)

  // 1) Source-limited coherence at sample
  var xi_src_h = lambda_m * R_sample / (2 * Math.PI * sigH);
  var xi_src_v = lambda_m * R_sample / (2 * Math.PI * sigV);

  // 2) SSA-limited coherence at sample (SSA = virtual source)
  var ssaH_um = 50, ssaV_um = 50;
  try { if (typeof state !== 'undefined') { ssaH_um = state.ssaH || 50; ssaV_um = state.ssaV || 50; } } catch(e) {}
  // Rectangular aperture RMS: sigma = full_width / (2*sqrt(3))
  var ssaSigH = ssaH_um * 1e-6 / (2 * Math.sqrt(3));
  var ssaSigV = ssaV_um * 1e-6 / (2 * Math.sqrt(3));
  var xi_ssa_h = lambda_m * L_ssa2sample / (2 * Math.PI * ssaSigH);
  var xi_ssa_v = lambda_m * L_ssa2sample / (2 * Math.PI * ssaSigV);

  // Effective = min of source-limited and SSA-limited (bottleneck)
  var xi_h = Math.min(xi_src_h, xi_ssa_h);
  var xi_v = Math.min(xi_src_v, xi_ssa_v);

  return {
    xi_h_nm: xi_h * 1e9,
    xi_v_nm: xi_v * 1e9,
    xi_h_m: xi_h,
    xi_v_m: xi_v,
    xi_src_h_nm: xi_src_h * 1e9,
    xi_src_v_nm: xi_src_v * 1e9,
    xi_ssa_h_nm: xi_ssa_h * 1e9,
    xi_ssa_v_nm: xi_ssa_v * 1e9,
    sigma_h_um: sigH * 1e6,
    sigma_v_um: sigV * 1e6,
    ssa_sig_h_um: ssaSigH * 1e6,
    ssa_sig_v_um: ssaSigV * 1e6,
    R_sample_m: R_sample,
    L_ssa2sample_m: L_ssa2sample,
    lambda_m: lambda_m
  };
};

// Coherent fraction using NanoMAX criterion
// (Bjorling et al., OE 28, 5069, 2020)
//
// Mode count is determined by two apertures:
//   1. SSA (position space): sigma_eff = min(sigma_beam_at_SSA, sigma_SSA)
//   2. KB mirror acceptance (angular space): A_KB = L_KB * sin(theta_graze)
//
// sigma_coh = lambda * L_SSA_to_KB / (2*pi*A_KB)
//   -> max source sigma for single-mode KB illumination
//
// M_per_axis = max(1, sigma_eff / sigma_coh)
// M_total = M_H * M_V
// f_coh = 1 / M_total
//
// SSA is rectangular -> sigma_SSA = full_width / (2*sqrt(3))  [uniform RMS]
//
// IMPORTANT: f_coh is a phase-space invariant (Liouville theorem).
// Do NOT use focused beam size. Evaluate at SSA plane.
window._ptychoCoherentFraction = function(energy_keV) {
  var coh = _ptychoCoherenceLength(energy_keV);
  var lambda_m = coh.lambda_m;
  var R_ssa = 58.0;

  // Source parameters
  var sigSrcH = coh.sigma_h_um * 1e-6;   // source sigma (m)
  var sigSrcV = coh.sigma_v_um * 1e-6;

  // Source divergence from emittance
  var emit_x = 58e-12, emit_y = 5.8e-12;
  var sigDivH = emit_x / Math.max(sigSrcH, 1e-9);
  var sigDivV = emit_y / Math.max(sigSrcV, 1e-9);

  // Beam sigma at SSA (propagated from source)
  var sigBeamH = Math.sqrt(sigSrcH * sigSrcH + Math.pow(sigDivH * R_ssa, 2));
  var sigBeamV = Math.sqrt(sigSrcV * sigSrcV + Math.pow(sigDivV * R_ssa, 2));

  // ── KB mirror parameters ──
  var kbhLen = 0.100;  // KBH mirror length (m)
  var kbvLen = 0.300;  // KBV mirror length (m)
  var graze = 3e-3;    // grazing angle (rad)
  try {
    if (typeof KB_V_LEN !== 'undefined') kbvLen = KB_V_LEN;
    if (typeof KB_H_LEN !== 'undefined') kbhLen = KB_H_LEN;
  } catch(e) {}

  // KB projected apertures (m)
  var A_KB_H = kbhLen * Math.sin(graze);  // 0.300 mm
  var A_KB_V = kbvLen * Math.sin(graze);  // 0.900 mm

  // SSA -> KB distances
  var kbhPos = 149.90, kbvPos = 149.69;
  try {
    if (typeof CD !== 'undefined' && Array.isArray(CD)) {
      for (var ci = 0; ci < CD.length; ci++) {
        if (CD[ci].id === 'ssa') R_ssa = CD[ci].dp;
        if (CD[ci].id === 'kbh') kbhPos = CD[ci].dp;
        if (CD[ci].id === 'kbv') kbvPos = CD[ci].dp;
      }
    }
  } catch(e) {}
  var L_SSA_to_KBH = kbhPos - R_ssa;  // ~91.9 m
  var L_SSA_to_KBV = kbvPos - R_ssa;  // ~91.69 m

  // ── Coherent source sigma (NanoMAX criterion) ──
  // sigma_coh = lambda * L_SSA_to_KB / (2*pi*A_KB)
  var sigCohH = lambda_m * L_SSA_to_KBH / (2 * Math.PI * A_KB_H);
  var sigCohV = lambda_m * L_SSA_to_KBV / (2 * Math.PI * A_KB_V);

  // ── SSA size → effective source sigma ──
  var ssaH_um = 50, ssaV_um = 50;
  try { if (typeof state !== 'undefined') { ssaH_um = state.ssaH || 50; ssaV_um = state.ssaV || 50; } } catch(e) {}

  // Rectangular aperture RMS: sigma = full_width / (2*sqrt(3))
  var sqrt3 = Math.sqrt(3);
  var ssaSigH = ssaH_um * 1e-6 / (2 * sqrt3);
  var ssaSigV = ssaV_um * 1e-6 / (2 * sqrt3);
  var sigEffH = Math.min(sigBeamH, ssaSigH);
  var sigEffV = Math.min(sigBeamV, ssaSigV);

  // ── Mode count per axis ──
  var M_H = Math.max(1.0, sigEffH / sigCohH);
  var M_V = Math.max(1.0, sigEffV / sigCohV);
  var M_total = M_H * M_V;
  var N_modes = Math.ceil(M_total);
  var f_coh = Math.min(1.0, 1.0 / M_total);

  // Focused beam size for display
  var spot = {h: 50, v: 50};
  try { if (typeof focalSpot === 'function') spot = focalSpot(); } catch(e) {}

  return {
    coherent_fraction: f_coh,
    M_H: M_H,
    M_V: M_V,
    M_total: M_total,
    N_modes: N_modes,
    f_h: 1.0 / M_H,
    f_v: 1.0 / M_V,
    sigma_coh_h_um: sigCohH * 1e6,
    sigma_coh_v_um: sigCohV * 1e6,
    sigma_eff_h_um: sigEffH * 1e6,
    sigma_eff_v_um: sigEffV * 1e6,
    sigma_beam_at_ssa_h_um: sigBeamH * 1e6,
    sigma_beam_at_ssa_v_um: sigBeamV * 1e6,
    sigma_source_h_um: coh.sigma_h_um,
    sigma_source_v_um: coh.sigma_v_um,
    A_KB_H_mm: A_KB_H * 1e3,
    A_KB_V_mm: A_KB_V * 1e3,
    L_SSA_to_KBH_m: L_SSA_to_KBH,
    L_SSA_to_KBV_m: L_SSA_to_KBV,
    ssa_h_um: ssaH_um,
    ssa_v_um: ssaV_um,
    beam_h_nm: spot.h,
    beam_v_nm: spot.v,
    R_sample_m: coh.R_sample_m,
    L_ssa2sample_m: coh.L_ssa2sample_m,
    lambda_nm: coh.lambda_m * 1e9
  };
};

// Number of coherent modes from NanoMAX criterion (M_total from _ptychoCoherentFraction)
// Each mode is a shifted version of the coherent probe
// Mode weights decay geometrically: w_k ~ (1 - f_coh)^k
window._ptychoCoherenceModes = function(energy_keV) {
  var cf = _ptychoCoherentFraction(energy_keV);
  var f = cf.coherent_fraction;
  var N_modes = Math.max(1, Math.min(10, cf.N_modes || Math.ceil(cf.M_total || 1)));
  // Mode weights: geometric decay. The k-th eigenvalue ~ (1-f)^k
  // Normalized so sum = 1
  var weights = new Float64Array(N_modes);
  var sumW = 0;
  for (var k = 0; k < N_modes; k++) {
    weights[k] = Math.pow(1 - f, k);
    sumW += weights[k];
  }
  for (var k2 = 0; k2 < N_modes; k2++) {
    weights[k2] /= sumW;
  }
  return {
    N_modes: N_modes,
    weights: weights,
    coherent_fraction: f,
    M_H: cf.M_H,
    M_V: cf.M_V,
    M_total: cf.M_total,
    f_h: cf.f_h,
    f_v: cf.f_v,
    sigma_coh_h_um: cf.sigma_coh_h_um,
    sigma_coh_v_um: cf.sigma_coh_v_um,
    sigma_eff_h_um: cf.sigma_eff_h_um,
    sigma_eff_v_um: cf.sigma_eff_v_um,
    beam_h_nm: cf.beam_h_nm,
    beam_v_nm: cf.beam_v_nm
  };
};

// Generate incoherent probe modes from a base probe
// Each mode is shifted in position according to the incoherent spread.
// Physical model: shift ~ beam_sigma * sqrt(1 - f_coh) per axis
// mode_k probe(x,y) = probe_0(x - dx_k, y - dy_k)
window._generateProbeModes = function(probeRe, probeIm, asize, energy_keV, dx_m) {
  var modes = _ptychoCoherenceModes(energy_keV);
  var N_modes = modes.N_modes;
  var cohFraction = modes.coherent_fraction;
  var result = [];

  // Incoherent spread in pixels (per axis)
  // beam sigma in pixels ~ asize/6 (matches probe generation)
  var probeSigPx = asize / 6;
  var spreadH_px = probeSigPx * Math.sqrt(Math.max(0, 1 - (modes.f_h || cohFraction)));
  var spreadV_px = probeSigPx * Math.sqrt(Math.max(0, 1 - (modes.f_v || cohFraction)));

  for (var k = 0; k < N_modes; k++) {
    var modeRe = new Float64Array(asize * asize);
    var modeIm = new Float64Array(asize * asize);
    if (k === 0) {
      // First mode = original probe
      for (var i = 0; i < asize * asize; i++) {
        modeRe[i] = probeRe[i];
        modeIm[i] = probeIm[i];
      }
    } else {
      // Higher modes: shifted probe. Shift ~ sqrt(k) * incoherent_spread
      var angle = k * 2.3999632; // golden angle in radians
      var dxPx = Math.sqrt(k) * Math.cos(angle) * spreadH_px;
      var dyPx = Math.sqrt(k) * Math.sin(angle) * spreadV_px;
      // Sub-pixel shift via bilinear interpolation
      var idx0 = Math.floor(dxPx), idy0 = Math.floor(dyPx);
      var fx = dxPx - idx0, fy = dyPx - idy0;
      for (var y = 0; y < asize; y++) {
        for (var x = 0; x < asize; x++) {
          var sx = x - idx0, sy = y - idy0;
          // Bilinear interpolation with boundary check
          if (sx >= 0 && sx < asize - 1 && sy >= 0 && sy < asize - 1) {
            var i00 = sy * asize + sx;
            var i10 = sy * asize + sx + 1;
            var i01 = (sy + 1) * asize + sx;
            var i11 = (sy + 1) * asize + sx + 1;
            modeRe[y * asize + x] = (1 - fx) * (1 - fy) * probeRe[i00] +
              fx * (1 - fy) * probeRe[i10] +
              (1 - fx) * fy * probeRe[i01] +
              fx * fy * probeRe[i11];
            modeIm[y * asize + x] = (1 - fx) * (1 - fy) * probeIm[i00] +
              fx * (1 - fy) * probeIm[i10] +
              (1 - fx) * fy * probeIm[i01] +
              fx * fy * probeIm[i11];
          }
          // Outside boundary: zero (probe falls off)
        }
      }
    }
    result.push({re: modeRe, im: modeIm, weight: modes.weights[k]});
  }

  return {
    modes: result,
    N_modes: N_modes,
    weights: modes.weights,
    coherent_fraction: cohFraction,
    xi_h_nm: modes.xi_h_nm,
    xi_v_nm: modes.xi_v_nm
  };
};


// ══════════════════════════════════════════════════════════════════
//  Section 3c: Pre-flight Check & SSA Recommendation
// ══════════════════════════════════════════════════════════════════

// Pre-flight screening: check if current parameters will produce good reconstruction
// Returns: {pass: bool, checks: [{name, status, value, threshold, message}], recommendations: [str]}
window._ptychoPreflightCheck = function(ptyState) {
  var energy_keV = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  var checks = [];
  var recommendations = [];

  // Beam info
  var bsz = {h: 50, v: 50};
  try { if (typeof focalSpot === 'function') bsz = focalSpot(); } catch(e) {}
  var beamMaxNm = Math.max(bsz.h, bsz.v);

  // Detector geometry
  var detKey = ptyState.ptychoDetector || 'EIGER2_1M';
  var z_m = ptyState.z_m || 2.0;
  var asize = ptyState.asize || 256;
  var geom = _ptychoDetectorGeometry(energy_keV, z_m, detKey);

  // Pixel size
  var dx_nm = geom.lambda_m * z_m / (asize * geom.pixelSize) * 1e9;

  // ── Check 1: Oversampling ──
  // Physical oversampling: O = lambda * z / (det_pixel * probe_FWHM)
  // This depends on energy, detector distance, pixel size, and actual beam size
  var probeMaxM = beamMaxNm * 1e-9;
  var O_ratio = (probeMaxM > 0) ? geom.lambda_m * z_m / (geom.pixelSize * probeMaxM) : 0;
  var osStatus = O_ratio >= 4 ? 'pass' : (O_ratio >= 2 ? 'warn' : 'fail');
  checks.push({
    name: 'Oversampling',
    status: osStatus,
    value: O_ratio,
    threshold: 'O >= 4 (pass), >= 2 (warn)',
    message: 'O = ' + O_ratio.toFixed(1) + ' (lam=' + (geom.lambda_m*1e10).toFixed(3) + 'A, z=' + z_m.toFixed(1) + 'm, px=' + (geom.pixelSize*1e6).toFixed(0) + 'um, probe=' + beamMaxNm.toFixed(0) + 'nm)'
  });
  if (O_ratio < 2) {
    // Suggest increasing z_m or decreasing probe
    var z_need = 2.0 * geom.pixelSize * probeMaxM / geom.lambda_m;
    recommendations.push('Oversampling too low (O=' + O_ratio.toFixed(1) + '). Try z >= ' + z_need.toFixed(1) + ' m or reduce probe size.');
  }

  // ── Check 2: Probe extent (FWHM in pixels) ──
  // For hard X-ray nanoprobe ptychography with focused beam,
  // probe FWHM is typically 1-5 px (beam << pixel size).
  // Thresholds: >= 3px good, >= 1px workable, < 1px fail
  var probePx = beamMaxNm / dx_nm;
  var probeStatus = probePx >= 3 ? 'pass' : (probePx >= 1 ? 'warn' : 'fail');
  checks.push({
    name: 'Probe extent',
    status: probeStatus,
    value: probePx,
    threshold: '>= 3 px (pass), >= 1 px (warn)',
    message: 'Probe FWHM = ' + probePx.toFixed(1) + ' px (' + beamMaxNm.toFixed(0) + ' nm / ' + dx_nm.toFixed(1) + ' nm/px)'
  });
  if (probePx < 1) {
    // Suggest smaller asize to increase dx_nm
    var targetDx = beamMaxNm / 3; // 3 px target
    var recAsize = Math.round(geom.lambda_m * z_m / (targetDx * 1e-9 * geom.pixelSize));
    recAsize = Math.pow(2, Math.floor(Math.log2(recAsize)));
    recAsize = Math.max(64, Math.min(1024, recAsize));
    recommendations.push('Probe is only ' + probePx.toFixed(1) + ' px. Try asize=' + recAsize + ' (probe=' + (beamMaxNm / (geom.lambda_m * z_m / (recAsize * geom.pixelSize) * 1e9)).toFixed(0) + ' px).');
  }

  // ── Check 3: Overlap ──
  var autoStep = beamMaxNm * 0.4 / 1000; // um
  var effectiveStep = (ptyState.scan_step_um > 0) ? ptyState.scan_step_um : autoStep;
  var probeUm = beamMaxNm / 1000;
  var overlapPct = (1 - effectiveStep / probeUm) * 100;
  var ovStatus = overlapPct >= 70 ? 'pass' : (overlapPct >= 50 ? 'warn' : 'fail');
  checks.push({
    name: 'Overlap',
    status: ovStatus,
    value: overlapPct,
    threshold: '>= 70% (pass), >= 50% (warn)',
    message: 'Overlap = ' + overlapPct.toFixed(0) + '% (step=' + (effectiveStep * 1000).toFixed(0) + ' nm, probe=' + beamMaxNm.toFixed(0) + ' nm)'
  });
  if (overlapPct < 50) {
    recommendations.push('Overlap ' + overlapPct.toFixed(0) + '% is too low. Reduce scan step or set to 0 (auto = 60%).');
  }

  // ── Check 4: Coherent fraction (NanoMAX criterion) ──
  var cohInfo = null;
  try { cohInfo = _ptychoCoherentFraction(energy_keV); } catch(e) {}
  var fCoh = cohInfo ? cohInfo.coherent_fraction : 1.0;
  var nModes = cohInfo ? cohInfo.N_modes : 1;
  var cohStatus = fCoh > 0.5 ? 'pass' : (fCoh > 0.1 ? 'warn' : 'fail');
  checks.push({
    name: 'Coherence',
    status: cohStatus,
    value: fCoh,
    threshold: '> 0.5 (pass), > 0.1 (warn)',
    message: 'f=' + (fCoh * 100).toFixed(0) + '% (' + nModes + ' modes) SSA ' + (cohInfo ? cohInfo.ssa_h_um : '?') + 'x' + (cohInfo ? cohInfo.ssa_v_um : '?') + ' um'
      + (cohInfo ? ' | M_H=' + cohInfo.M_H.toFixed(1) + ' M_V=' + cohInfo.M_V.toFixed(1) : '')
  });
  if (fCoh <= 0.1) {
    recommendations.push('f=' + (fCoh * 100).toFixed(0) + '% (' + nModes + ' modes) is very low. Close SSA to improve coherence.');
  } else if (fCoh <= 0.3) {
    recommendations.push('f=' + (fCoh * 100).toFixed(0) + '% (' + nModes + ' modes) is marginal. Consider closing SSA for better reconstruction.');
  }

  // ── Check 5: Photon count ──
  // N_photons=0 means auto (flux*dwell), N_photons=1000 is legacy default — treat as auto
  var N_photons = ptyState.N_photons || 0;
  var _nphAuto = false;
  if (N_photons <= 0 || N_photons === 1000) {
    try { N_photons = _fluxToPhotons(energy_keV, ptyState.dwellTime || 0.1); } catch(e) { N_photons = 1e8; }
    _nphAuto = true;
  }
  var phStatus = N_photons >= 1e6 ? 'pass' : (N_photons >= 1e4 ? 'warn' : 'fail');
  checks.push({
    name: 'Photons',
    status: phStatus,
    value: N_photons,
    threshold: '>= 1e6 (pass), >= 1e4 (warn)',
    message: 'N_photons = ' + N_photons.toExponential(1) + ' (' + (_nphAuto ? 'auto: flux*' : 'dwell=') + (ptyState.dwellTime || 0.1) + 's)'
  });
  if (N_photons < 1e4) {
    recommendations.push('Only ' + N_photons.toExponential(1) + ' photons. Increase dwell time or open SSA for more flux.');
  }

  // Overall pass
  var allPass = true;
  for (var i = 0; i < checks.length; i++) {
    if (checks[i].status === 'fail') allPass = false;
  }

  return {
    pass: allPass,
    checks: checks,
    recommendations: recommendations,
    energy_keV: energy_keV,
    dx_nm: dx_nm,
    probePx: probePx,
    overlapPct: overlapPct,
    N_photons: N_photons,
    f_coh: fCoh
  };
};

// SSA recommendation engine: find optimal SSA for flux-coherence trade-off
// Uses NanoMAX criterion (Bjorling et al., OE 28, 5069, 2020):
//   sigma_coh = lambda * L_SSA_to_KB / (2*pi*A_KB)
//   M = sigma_eff / sigma_coh per axis
// Sweeps SSA from 5 to 500 um and finds optimal/maximum SSA
window._ptychoSSARecommendation = function(energy_keV) {
  var lambda_m = 1239.842e-9 / (energy_keV * 1000);

  // Source size
  var ps = null;
  try { if (typeof photonSrc === 'function') ps = photonSrc(energy_keV); } catch(e) {}
  var sigSrcH = ps ? ps.Sx : ((typeof SIG_EX !== 'undefined') ? SIG_EX : Math.sqrt(62e-12 * 6.334));
  var sigSrcV = ps ? ps.Sy : ((typeof SIG_EY !== 'undefined') ? SIG_EY : Math.sqrt(6.2e-12 * 2.841));

  // Source divergence from emittance
  var emit_x = 58e-12, emit_y = 5.8e-12;
  var sigDivH = emit_x / Math.max(sigSrcH, 1e-9);
  var sigDivV = emit_y / Math.max(sigSrcV, 1e-9);

  // Distances
  var R_ssa = 58, kbhPos = 149.90, kbvPos = 149.69;
  try {
    if (typeof CD !== 'undefined' && Array.isArray(CD)) {
      for (var ci = 0; ci < CD.length; ci++) {
        if (CD[ci].id === 'ssa') R_ssa = CD[ci].dp;
        if (CD[ci].id === 'kbh') kbhPos = CD[ci].dp;
        if (CD[ci].id === 'kbv') kbvPos = CD[ci].dp;
      }
    }
  } catch(e) {}
  var L_SSA_to_KBH = kbhPos - R_ssa;
  var L_SSA_to_KBV = kbvPos - R_ssa;

  // Beam sigma at SSA (SSA-plane, NOT focused beam)
  var sigBeamH = Math.sqrt(sigSrcH * sigSrcH + Math.pow(sigDivH * R_ssa, 2));
  var sigBeamV = Math.sqrt(sigSrcV * sigSrcV + Math.pow(sigDivV * R_ssa, 2));

  // KB mirror projected apertures
  var kbhLen = 0.100, kbvLen = 0.300, graze = 3e-3;
  try {
    if (typeof KB_V_LEN !== 'undefined') kbvLen = KB_V_LEN;
    if (typeof KB_H_LEN !== 'undefined') kbhLen = KB_H_LEN;
  } catch(e) {}
  var A_KB_H = kbhLen * Math.sin(graze);
  var A_KB_V = kbvLen * Math.sin(graze);

  // Coherent source sigma (NanoMAX criterion)
  var sigCohH = lambda_m * L_SSA_to_KBH / (2 * Math.PI * A_KB_H);
  var sigCohV = lambda_m * L_SSA_to_KBV / (2 * Math.PI * A_KB_V);

  // Current SSA
  var ssaH = 50, ssaV = 50;
  try { if (typeof state !== 'undefined') { ssaH = state.ssaH || 50; ssaV = state.ssaV || 50; } } catch(e) {}

  // Helper: compute f_coh for given symmetric SSA (NanoMAX criterion)
  var sqrt3 = Math.sqrt(3);
  function _fCohForSSA(ssa_um) {
    var ssaSig = ssa_um * 1e-6 / (2 * sqrt3);  // rectangular RMS
    var sH = Math.min(sigBeamH, ssaSig);
    var sV = Math.min(sigBeamV, ssaSig);
    var mH = Math.max(1, sH / sigCohH);
    var mV = Math.max(1, sV / sigCohV);
    return Math.min(1.0, 1.0 / (mH * mV));
  }

  // Current f_coh (with actual asymmetric SSA)
  var current_f_coh = 0;
  var current_N_modes = 1;
  try {
    var cf = _ptychoCoherentFraction(energy_keV);
    current_f_coh = cf.coherent_fraction;
    current_N_modes = cf.N_modes;
  } catch(e) {}

  // Sweep SSA to build trade-off curve
  var sweepSSA = [];
  for (var s = 5; s <= 500; s += 5) {
    var fc = _fCohForSSA(s);
    sweepSSA.push({ssa: s, f_coh: fc, N_modes: Math.ceil(1.0 / Math.max(fc, 0.01))});
  }

  // Find optimal (f_coh closest to 0.5) and maximum (f_coh closest to 0.3)
  var optimal = {ssa: 50, f_coh: 0.5, N_modes: 2};
  var maximum = {ssa: 100, f_coh: 0.3, N_modes: 3};
  var bestOptDiff = 999, bestMaxDiff = 999;
  for (var i = 0; i < sweepSSA.length; i++) {
    var d05 = Math.abs(sweepSSA[i].f_coh - 0.5);
    var d03 = Math.abs(sweepSSA[i].f_coh - 0.3);
    if (d05 < bestOptDiff) { bestOptDiff = d05; optimal = sweepSSA[i]; }
    if (d03 < bestMaxDiff) { bestMaxDiff = d03; maximum = sweepSSA[i]; }
  }

  // Flux gain: proportional to SSA area
  var refSSA = optimal.ssa;
  var fluxGainAtMax = Math.pow(maximum.ssa / refSSA, 2);

  // Build recommendation text
  var rec = '';
  if (Math.max(ssaH, ssaV) > maximum.ssa) {
    rec = 'SSA ' + ssaH + 'x' + ssaV + ' um is too open (f=' + (current_f_coh * 100).toFixed(0) + '%, ' + current_N_modes + ' modes). ' +
      'Reduce to ' + maximum.ssa + 'x' + maximum.ssa + ' um (' + maximum.N_modes + ' modes, ' + fluxGainAtMax.toFixed(1) + 'x flux vs optimal) ' +
      'or ' + optimal.ssa + 'x' + optimal.ssa + ' um (' + optimal.N_modes + ' modes, best quality).';
  } else if (Math.max(ssaH, ssaV) > optimal.ssa) {
    rec = 'SSA ' + ssaH + 'x' + ssaV + ' um is acceptable (f=' + (current_f_coh * 100).toFixed(0) + '%, ' + current_N_modes + ' modes). ' +
      'For best quality: ' + optimal.ssa + 'x' + optimal.ssa + ' um (' + optimal.N_modes + ' modes). ' +
      'Max flux: ' + maximum.ssa + 'x' + maximum.ssa + ' um (' + maximum.N_modes + ' modes, ' + fluxGainAtMax.toFixed(1) + 'x flux).';
  } else {
    rec = 'SSA ' + ssaH + 'x' + ssaV + ' um is optimal for ptychography (f=' + (current_f_coh * 100).toFixed(0) + '%, ' + current_N_modes + ' modes). ' +
      'If you need more flux: up to ' + maximum.ssa + 'x' + maximum.ssa + ' um (' + maximum.N_modes + ' modes, ' + fluxGainAtMax.toFixed(1) + 'x flux).';
  }

  return {
    current_ssa: {h: ssaH, v: ssaV},
    current_f_coh: current_f_coh,
    current_N_modes: current_N_modes,
    optimal_ssa: optimal.ssa,
    optimal_f_coh: optimal.f_coh,
    optimal_N_modes: optimal.N_modes,
    max_ssa: maximum.ssa,
    max_f_coh: maximum.f_coh,
    max_N_modes: maximum.N_modes,
    flux_gain_at_max: fluxGainAtMax,
    sweep: sweepSSA,
    recommendation: rec,
    sigma_coh_h_um: sigCohH * 1e6,
    sigma_coh_v_um: sigCohV * 1e6,
    sigma_beam_at_ssa_h_um: sigBeamH * 1e6,
    sigma_beam_at_ssa_v_um: sigBeamV * 1e6
  };
};


// ══════════════════════════════════════════════════════════════════
//  Section 4: JS Offline Fallback (simplified forward model)
// ══════════════════════════════════════════════════════════════════

// ── Simple 2D FFT (Radix-2 Cooley-Tukey) ──
function _fft1d(re, im, N, inverse) {
  var j = 0;
  for (var i = 0; i < N - 1; i++) {
    if (i < j) {
      var tr = re[i]; re[i] = re[j]; re[j] = tr;
      var ti = im[i]; im[i] = im[j]; im[j] = ti;
    }
    var m = N >> 1;
    while (m >= 1 && j >= m) { j -= m; m >>= 1; }
    j += m;
  }
  var sign = inverse ? -1 : 1;
  for (var step = 2; step <= N; step <<= 1) {
    var half = step >> 1;
    var angle = sign * Math.PI / half;
    var wRe = Math.cos(angle), wIm = Math.sin(angle);
    for (var g = 0; g < N; g += step) {
      var curRe = 1, curIm = 0;
      for (var k = 0; k < half; k++) {
        var a = g + k, b = a + half;
        var tRe = curRe * re[b] - curIm * im[b];
        var tIm = curRe * im[b] + curIm * re[b];
        re[b] = re[a] - tRe;
        im[b] = im[a] - tIm;
        re[a] += tRe;
        im[a] += tIm;
        var nRe = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = nRe;
      }
    }
  }
  if (inverse) {
    for (var i = 0; i < N; i++) { re[i] /= N; im[i] /= N; }
  }
}

function _fft2d(re, im, N, inverse) {
  var row_re = new Float64Array(N), row_im = new Float64Array(N);
  for (var y = 0; y < N; y++) {
    var off = y * N;
    for (var x = 0; x < N; x++) { row_re[x] = re[off + x]; row_im[x] = im[off + x]; }
    _fft1d(row_re, row_im, N, inverse);
    for (var x = 0; x < N; x++) { re[off + x] = row_re[x]; im[off + x] = row_im[x]; }
  }
  var col_re = new Float64Array(N), col_im = new Float64Array(N);
  for (var x = 0; x < N; x++) {
    for (var y = 0; y < N; y++) { col_re[y] = re[y * N + x]; col_im[y] = im[y * N + x]; }
    _fft1d(col_re, col_im, N, inverse);
    for (var y = 0; y < N; y++) { re[y * N + x] = col_re[y]; im[y * N + x] = col_im[y]; }
  }
}

function _fftshift(arr, N) {
  var half = N >> 1;
  var tmp = new Float64Array(N * N);
  for (var y = 0; y < N; y++) {
    for (var x = 0; x < N; x++) {
      tmp[((y + half) % N) * N + (x + half) % N] = arr[y * N + x];
    }
  }
  for (var i = 0; i < N * N; i++) arr[i] = tmp[i];
}

// ── Far-field Fresnel propagation (port of cSAXS utils.prop_free_ff) ──
function _propFreeFf(wRe, wIm, N, lambda_m, z, pixsize) {
  var z_n = z / pixsize;
  var lam_n = lambda_m / pixsize;
  var half = N >> 1;
  // Source quadratic phase: exp(i*pi*r2/(lam_n*z_n))
  // Multiply w by src_phase, then fftshift, then FFT, then ifftshift
  // Then multiply by obs_phase = exp(i*pi*lam_n*z_n*r2/N^2)
  // Final factor: -i
  var srcRe = new Float64Array(N * N);
  var srcIm = new Float64Array(N * N);
  for (var y = 0; y < N; y++) {
    var yy = y - half;
    for (var x = 0; x < N; x++) {
      var xx = x - half;
      var r2 = xx * xx + yy * yy;
      var ang = Math.PI * r2 / (lam_n * z_n);
      var cA = Math.cos(ang), sA = Math.sin(ang);
      var idx = y * N + x;
      // w * src_phase
      srcRe[idx] = wRe[idx] * cA - wIm[idx] * sA;
      srcIm[idx] = wRe[idx] * sA + wIm[idx] * cA;
    }
  }
  // fftshift
  _fftshift(srcRe, N);
  _fftshift(srcIm, N);
  // FFT (forward)
  _fft2d(srcRe, srcIm, N, false);
  // ifftshift
  _fftshift(srcRe, N);
  _fftshift(srcIm, N);
  // obs_phase * (-i) * ft
  var outRe = new Float64Array(N * N);
  var outIm = new Float64Array(N * N);
  for (var y = 0; y < N; y++) {
    var yy = y - half;
    for (var x = 0; x < N; x++) {
      var xx = x - half;
      var r2 = xx * xx + yy * yy;
      var ang = Math.PI * lam_n * z_n * r2 / (N * N);
      var oRe = Math.cos(ang), oIm = Math.sin(ang);
      var idx = y * N + x;
      // obs * ft
      var tRe = oRe * srcRe[idx] - oIm * srcIm[idx];
      var tIm = oRe * srcIm[idx] + oIm * srcRe[idx];
      // multiply by -i: -i*(a+bi) = b - ai
      outRe[idx] = tIm;
      outIm[idx] = -tRe;
    }
  }
  return {re: outRe, im: outIm};
}

// ── KB Fresnel sinc probe (rectangular aperture + thin lens + propagation) ──
window._createFresnelSincProbe = function(asize, lambda_m, dx_spec, focalLength, fwhm_h_m, fwhm_v_m) {
  var f = focalLength;
  var upsample = 2; // Use 2x to keep JS fast (vs 4x in Python)
  var N = upsample * asize;
  // Ensure N is power of 2 for FFT
  var Npow = 1;
  while (Npow < N) Npow <<= 1;
  N = Npow;

  var dx_pupil = f * lambda_m / (N * dx_spec);
  var aperture_h = 0.886 * lambda_m * f / fwhm_h_m;
  var aperture_v = 0.886 * lambda_m * f / fwhm_v_m;
  var hw_h = aperture_h / (2.0 * dx_pupil);
  var hw_v = aperture_v / (2.0 * dx_pupil);

  var half = N >> 1;

  // Build 1D apertures with Hanning edge
  var edge_h = Math.max(3, Math.floor(hw_h * 0.02) + 1);
  var edge_v = Math.max(3, Math.floor(hw_v * 0.02) + 1);
  var wh_1d = new Float64Array(N);
  var wv_1d = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    var ax = Math.abs(i - half);
    // Horizontal
    if (ax <= hw_h - edge_h) wh_1d[i] = 1.0;
    else if (ax < hw_h + edge_h) wh_1d[i] = 0.5 * (1.0 + Math.cos(Math.PI * (ax - (hw_h - edge_h)) / (2 * edge_h)));
    // Vertical
    if (ax <= hw_v - edge_v) wv_1d[i] = 1.0;
    else if (ax < hw_v + edge_v) wv_1d[i] = 0.5 * (1.0 + Math.cos(Math.PI * (ax - (hw_v - edge_v)) / (2 * edge_v)));
  }

  // Build 2D pupil = wv * wh, apply thin lens phase
  var pupilRe = new Float64Array(N * N);
  var pupilIm = new Float64Array(N * N);
  for (var y = 0; y < N; y++) {
    var yy = y - half;
    for (var x = 0; x < N; x++) {
      var xx = x - half;
      var w = wv_1d[y] * wh_1d[x];
      if (w < 1e-12) continue;
      var r2 = xx * xx + yy * yy;
      // Thin lens phase: exp(-i*pi*r2*dx^2/(lambda*f))
      var ang = -Math.PI * r2 * dx_pupil * dx_pupil / (lambda_m * f);
      var idx = y * N + x;
      pupilRe[idx] = w * Math.cos(ang);
      pupilIm[idx] = w * Math.sin(ang);
    }
  }

  // Fresnel propagation
  var result = _propFreeFf(pupilRe, pupilIm, N, lambda_m, f, dx_pupil);

  // Center crop to asize
  var probeRe = new Float64Array(asize * asize);
  var probeIm = new Float64Array(asize * asize);
  var c = N >> 1;
  var h = asize >> 1;
  for (var y = 0; y < asize; y++) {
    for (var x = 0; x < asize; x++) {
      var srcIdx = (c - h + y) * N + (c - h + x);
      probeRe[y * asize + x] = result.re[srcIdx];
      probeIm[y * asize + x] = result.im[srcIdx];
    }
  }

  // Radial apodization
  var cx2 = asize / 2.0;
  var edgeStart = asize * 0.42, edgeEnd = asize * 0.50;
  for (var y = 0; y < asize; y++) {
    for (var x = 0; x < asize; x++) {
      var ar = Math.sqrt((x - cx2) * (x - cx2) + (y - cx2) * (y - cx2));
      if (ar > edgeStart) {
        var taper = Math.max(0, Math.min(1, (edgeEnd - ar) / (edgeEnd - edgeStart)));
        var idx = y * asize + x;
        probeRe[idx] *= taper;
        probeIm[idx] *= taper;
      }
    }
  }

  // Normalize: sum(|P|^2) = asize^2
  var power = 0;
  for (var i = 0; i < asize * asize; i++) {
    power += probeRe[i] * probeRe[i] + probeIm[i] * probeIm[i];
  }
  if (power > 0) {
    var sc = asize / Math.sqrt(power);
    for (var i = 0; i < asize * asize; i++) {
      probeRe[i] *= sc;
      probeIm[i] *= sc;
    }
  }
  return {re: probeRe, im: probeIm};
};

// ── Refractive index table (Henke CXRO, from K4GSR-PTYCHO synth_ptycho.py) ──
var _REF_INDEX = {
  Au:  {6.2:[4.6596e-5,5.2813e-6], 8:[2.82e-5,3.6927e-6], 10:[1.81e-5,2.257e-6], 12.4:[1.18e-5,1.38e-6]},
  Cu:  {6.2:[2.34e-5,3.067e-6], 8:[1.41e-5,2.138e-6], 8.97:[1.12e-5,5.16e-6], 10:[9.047e-6,5.731e-7], 12.4:[5.878e-6,2.981e-7]},
  W:   {6.2:[5.176e-5,7.117e-6], 8:[3.12e-5,4.118e-6], 10:[2.0e-5,5.215e-6], 12.4:[1.299e-5,2.67e-6]},
  Pt:  {6.2:[5.33e-5,5.196e-6], 8:[3.21e-5,3.61e-6], 10:[2.058e-5,4.128e-6], 12.4:[1.336e-5,2.164e-6]},
  Si:  {6.2:[5.489e-6,7.724e-8], 8:[3.308e-6,1.751e-7], 10:[2.119e-6,4.727e-8], 12.4:[1.376e-6,2.009e-8]},
  SiO2:{6.2:[6.723e-6,8.228e-8], 8:[4.05e-6,1.501e-7], 10:[2.592e-6,4.754e-8], 12.4:[1.684e-6,2.09e-8]}
};

window._getRefIndex = function(material, energy_keV) {
  var table = _REF_INDEX[material];
  if (!table) return [1e-5, 1e-6];
  var energies = [];
  for (var e in table) { if (table.hasOwnProperty(e)) energies.push(parseFloat(e)); }
  energies.sort(function(a, b) { return a - b; });
  if (table[energy_keV]) return table[energy_keV];
  if (energy_keV <= energies[0]) return table[energies[0]];
  if (energy_keV >= energies[energies.length - 1]) return table[energies[energies.length - 1]];
  for (var i = 0; i < energies.length - 1; i++) {
    if (energies[i] <= energy_keV && energy_keV <= energies[i + 1]) {
      var e0 = energies[i], e1 = energies[i + 1];
      var d0 = table[e0][0], b0 = table[e0][1];
      var d1 = table[e1][0], b1 = table[e1][1];
      var t = (energy_keV - e0) / (e1 - e0);
      var delta = Math.exp(Math.log(d0) * (1 - t) + Math.log(d1) * t);
      var beta = Math.exp(Math.log(Math.max(b0, 1e-15)) * (1 - t) + Math.log(Math.max(b1, 1e-15)) * t);
      return [delta, beta];
    }
  }
  return [1e-5, 1e-6];
};

window._createComplexObject = function(thickMap, N, energy_keV, material, objheight_m) {
  var ref = _getRefIndex(material, energy_keV);
  var delta = ref[0], beta = ref[1];
  var lambda_m = 1239.842e-9 / (energy_keV * 1000);
  var k = 2 * Math.PI / lambda_m;
  var objRe = new Float64Array(N * N);
  var objIm = new Float64Array(N * N);
  var amp = new Float64Array(N * N);
  var phase = new Float64Array(N * N);
  for (var i = 0; i < N * N; i++) {
    var t = 1 - thickMap[i];
    var phReal = -k * delta * t * objheight_m;
    var absorption = k * beta * t * objheight_m;
    var atten = Math.exp(-absorption);
    objRe[i] = atten * Math.cos(phReal);
    objIm[i] = atten * Math.sin(phReal);
    amp[i] = atten;
    phase[i] = phReal;
  }
  return {re: objRe, im: objIm, amp: amp, phase: phase, size: N};
};

window._addPoissonNoise = function(dp, N_photons) {
  var mx = 0;
  for (var i = 0; i < dp.length; i++) { if (dp[i] > mx) mx = dp[i]; }
  if (mx < 1e-20) return dp;
  var scale = N_photons / mx;
  var noisy = new Float64Array(dp.length);
  for (var i = 0; i < dp.length; i++) {
    var lam = dp[i] * scale;
    if (lam > 20) {
      var u1 = Math.random(), u2 = Math.random();
      var z = Math.sqrt(-2 * Math.log(Math.max(u1, 1e-30))) * Math.cos(2 * Math.PI * u2);
      noisy[i] = Math.max(0, lam + z * Math.sqrt(lam));
    } else if (lam > 0) {
      var L = Math.exp(-lam), kk = 0, p = 1;
      do { kk++; p *= Math.random(); } while (p > L);
      noisy[i] = kk - 1;
    } else {
      noisy[i] = 0;
    }
  }
  return noisy;
};

// ── Thickness map generators ──
function _genSiemensStarThickness(N, nSpokes) {
  nSpokes = nSpokes || 16;
  var t = new Float64Array(N * N);
  var cx = N / 2, cy = N / 2;
  for (var y = 0; y < N; y++) {
    for (var x = 0; x < N; x++) {
      var dx = x - cx, dy = y - cy;
      var r = Math.sqrt(dx * dx + dy * dy);
      var theta = Math.atan2(dy, dx);
      var spoke = Math.cos(nSpokes * theta);
      t[y * N + x] = r < cx * 0.9 ? (spoke > 0 ? 1.0 : 0.0) : 0.0;
    }
  }
  return t;
}

function _genResolutionChartThickness(N) {
  var t = new Float64Array(N * N);
  for (var y = 0; y < N; y++) {
    for (var x = 0; x < N; x++) {
      var block = Math.floor(x / (N / 8));
      var freq = block + 1;
      var stripe = Math.sin(2 * Math.PI * freq * y / N);
      t[y * N + x] = stripe > 0 ? 1.0 : 0.0;
    }
  }
  return t;
}

// ── Scan position generators ──
window._fermatSpiral = function(N, stepSize, asize) {
  var c = stepSize * 0.5;
  var positions = [];
  var golden = 137.508 * Math.PI / 180;
  for (var i = 0; i < N; i++) {
    var r = c * Math.sqrt(i);
    var theta = i * golden;
    positions.push({x: r * Math.cos(theta), y: r * Math.sin(theta)});
  }
  return positions;
};

window._rasterScan = function(Nx, Ny, stepX, stepY, snake) {
  var positions = [];
  for (var j = 0; j < Ny; j++) {
    if (snake && j % 2 === 1) {
      for (var i = Nx - 1; i >= 0; i--) {
        positions.push({x: i * stepX, y: j * stepY});
      }
    } else {
      for (var i = 0; i < Nx; i++) {
        positions.push({x: i * stepX, y: j * stepY});
      }
    }
  }
  return positions;
};

// ── Offline forward model (used when server unavailable) ──
// Diffraction pattern size is determined by actual EIGER detector specs.
// Oversampling ratio O = N_det / asize determines how many detector pixels
// per probe pixel in reciprocal space.
// Real-space resolution dx = lambda * z / (N_det * det_pixel_size)
window.simPtycho = function(opts) {
  opts = opts || {};
  var asize = opts.asize || 64;
  var objSize = opts.objSize || 256;
  var scanType = opts.scanType || 'fermat';
  var objectType = opts.objectType || 'siemens';
  var stepSize = opts.stepSize || Math.max(1, Math.round(asize * 0.4));
  var Nx = opts.Nx || 12, Ny = opts.Ny || 12;
  var nPositions = opts.nPositions || (Nx * Ny);
  var material = opts.material || 'Au';
  var objheight_m = opts.objheight_m || 1e-6;
  var energy_keV = opts.energy_keV || ((typeof state !== 'undefined' && state.energy) ? state.energy : 10);
  var N_photons = opts.N_photons || 1000;
  var addNoise = opts.addNoise !== undefined ? opts.addNoise : false;
  var dwellTime = opts.dwellTime || 0.1;
  var detKey = opts.ptychoDetector || 'EIGER2_1M';
  var z_m = opts.z_m || 0.5;

  if (!opts.N_photons && typeof photonFlux === 'function') {
    try { N_photons = _fluxToPhotons(energy_keV, dwellTime); } catch(e) {}
  }

  // Detector geometry
  var geom = _ptychoDetectorGeometry(energy_keV, z_m, detKey);
  var N_det = geom.N_det;           // square crop of detector
  var det_pixel_m = geom.pixelSize; // 75 um
  var lambda_m = geom.lambda_m;
  var oversampling = _ptychoOversampling(geom, asize);  // O = N_det / asize

  // Real-space pixel size: dx = lambda * z / (N_det * det_pixel)
  var dx_m = geom.dx_m;
  var dx_nm = geom.dx_nm;

  // asize must be power of 2 for FFT and <= N_det
  // The diffraction pattern on detector has N_det pixels but we simulate
  // with zero-padded FFT of size N_det for correct oversampling
  // For efficiency, use nearest power of 2 >= asize
  var N_fft = asize;
  // If oversampling > 1, the exit wave (asize x asize) is zero-padded to N_det
  // for the FFT, then we crop the central N_det pixels as the diffraction pattern
  // For offline mode, we use a practical FFT size that captures the oversampling
  var N_pad = 1;
  while (N_pad < asize) N_pad *= 2;
  // Apply oversampling: pad exit wave so diffraction has correct # of pixels
  // Use min(N_det, 512) to keep offline simulation fast
  var N_sim = Math.min(N_det, 512);
  // Round up to power of 2
  var N_fft_use = 1;
  while (N_fft_use < N_sim) N_fft_use *= 2;
  // Ensure N_fft_use >= asize
  if (N_fft_use < asize) N_fft_use = asize;

  // Effective oversampling in simulation
  var O_sim = N_fft_use / asize;

  // Generate probe (KB Fresnel sinc — rectangular aperture)
  // Get KB focal length and beam FWHM from opts or beamline state
  var kbFocal = opts.focalLength || 0.2;   // default ~average of KBV(0.31) + KBH(0.10)
  var fwhm_h_m = opts.fwhm_h_m || 50e-9;
  var fwhm_v_m = opts.fwhm_v_m || 50e-9;
  try {
    if (typeof CD !== 'undefined' && Array.isArray(CD)) {
      var _sp = 150.0, _kv = 149.69, _kh = 149.90;
      for (var ci = 0; ci < CD.length; ci++) {
        if (CD[ci].id === 'sample') _sp = CD[ci].dp;
        if (CD[ci].id === 'kbv') _kv = CD[ci].dp;
        if (CD[ci].id === 'kbh') _kh = CD[ci].dp;
      }
      if (!opts.focalLength) kbFocal = ((_sp - _kv) + (_sp - _kh)) / 2.0;
    }
    if (!opts.fwhm_h_m && typeof focalSpot === 'function') {
      var _bsz = focalSpot();
      if (_bsz && _bsz.h > 0 && _bsz.v > 0) {
        fwhm_h_m = _bsz.h * 1e-9;
        fwhm_v_m = _bsz.v * 1e-9;
      }
    }
  } catch(e) {}
  var sincProbe = _createFresnelSincProbe(asize, lambda_m, dx_m, kbFocal, fwhm_h_m, fwhm_v_m);
  var probeRe = sincProbe.re;
  var probeIm = sincProbe.im;

  // Coherence: generate incoherent probe modes for partial coherence
  var cohInfo = _ptychoCoherentFraction(energy_keV);
  var probeModes = null;
  if (cohInfo.coherent_fraction < 0.99) {
    probeModes = _generateProbeModes(probeRe, probeIm, asize, energy_keV, dx_m);
  }

  // Generate object
  var thickMap;
  if (objectType === 'resolution') thickMap = _genResolutionChartThickness(objSize);
  else thickMap = _genSiemensStarThickness(objSize, 16);

  var obj = _createComplexObject(thickMap, objSize, energy_keV, material, objheight_m);

  // Scan positions
  var positions;
  if (scanType === 'raster' || scanType === 'raster-snake') {
    positions = _rasterScan(Nx, Ny, stepSize, stepSize, scanType === 'raster-snake');
  } else {
    positions = _fermatSpiral(nPositions, stepSize, asize);
  }

  // Center positions on object
  var objCx = objSize / 2 - asize / 2;
  var objCy = objSize / 2 - asize / 2;
  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (var i = 0; i < positions.length; i++) {
    if (positions[i].x < minX) minX = positions[i].x;
    if (positions[i].x > maxX) maxX = positions[i].x;
    if (positions[i].y < minY) minY = positions[i].y;
    if (positions[i].y > maxY) maxY = positions[i].y;
  }
  var offX = objCx - (minX + maxX) / 2;
  var offY = objCy - (minY + maxY) / 2;
  for (var i = 0; i < positions.length; i++) {
    positions[i].x += offX;
    positions[i].y += offY;
  }

  // Compute diffraction patterns with zero-padding for oversampling
  // Exit wave (asize x asize) -> zero-pad to (N_fft_use x N_fft_use) -> FFT -> |F|^2
  // For partial coherence: sum weighted |F_k|^2 over probe modes
  var patterns = [];
  var nShow = Math.min(positions.length, 4);
  var padOff = Math.floor((N_fft_use - asize) / 2);  // centering offset
  var useMultiMode = probeModes && probeModes.N_modes > 1;
  var nModes = useMultiMode ? probeModes.N_modes : 1;

  // Helper: compute single-mode diffraction pattern
  function _computeDP(pRArr, pIArr, ppx, ppy) {
    var exitRe = new Float64Array(N_fft_use * N_fft_use);
    var exitIm = new Float64Array(N_fft_use * N_fft_use);
    for (var y = 0; y < asize; y++) {
      for (var x = 0; x < asize; x++) {
        var oy = ppy + y, ox = ppx + x;
        if (oy < 0 || oy >= objSize || ox < 0 || ox >= objSize) continue;
        var objIdx = oy * objSize + ox;
        var oRe = obj.re[objIdx], oIm = obj.im[objIdx];
        var pR = pRArr[y * asize + x], pI = pIArr[y * asize + x];
        var padY = y + padOff, padX = x + padOff;
        exitRe[padY * N_fft_use + padX] = pR * oRe - pI * oIm;
        exitIm[padY * N_fft_use + padX] = pR * oIm + pI * oRe;
      }
    }
    _fft2d(exitRe, exitIm, N_fft_use, false);
    var intensity = new Float64Array(N_fft_use * N_fft_use);
    for (var i = 0; i < N_fft_use * N_fft_use; i++) {
      intensity[i] = exitRe[i] * exitRe[i] + exitIm[i] * exitIm[i];
    }
    return intensity;
  }

  for (var pi = 0; pi < nShow; pi++) {
    var ppx = Math.round(positions[pi].x);
    var ppy = Math.round(positions[pi].y);

    var dp;
    if (useMultiMode) {
      // Partial coherence: weighted sum of diffraction patterns from each mode
      dp = new Float64Array(N_fft_use * N_fft_use);
      for (var mk = 0; mk < nModes; mk++) {
        var mode = probeModes.modes[mk];
        var dpk = _computeDP(mode.re, mode.im, ppx, ppy);
        _fftshift(dpk, N_fft_use);
        var wk = mode.weight;
        for (var i = 0; i < N_fft_use * N_fft_use; i++) {
          dp[i] += wk * dpk[i];
        }
      }
    } else {
      // Fully coherent: single mode
      dp = _computeDP(probeRe, probeIm, ppx, ppy);
      _fftshift(dp, N_fft_use);
    }

    if (addNoise && N_photons > 0) {
      dp = _addPoissonNoise(dp, N_photons);
    }
    patterns.push(dp);
  }

  var blInfo = _getBeamlineInfo(energy_keV);

  // Coherence summary for display
  var cohSummary = {
    coherent_fraction: cohInfo.coherent_fraction,
    xi_h_nm: cohInfo.xi_h_nm,
    xi_v_nm: cohInfo.xi_v_nm,
    ssa_h_um: cohInfo.ssa_h_um,
    ssa_v_um: cohInfo.ssa_v_um,
    beam_h_nm: cohInfo.beam_h_nm,
    beam_v_nm: cohInfo.beam_v_nm,
    N_modes: useMultiMode ? nModes : 1
  };

  return {
    probe: {re: probeRe, im: probeIm, size: asize},
    probeModes: probeModes,   // multi-mode info (null if fully coherent)
    object: {re: obj.re, im: obj.im, amp: obj.amp, phase: obj.phase, size: objSize},
    positions: positions,
    patterns: patterns,
    asize: asize,
    dpSize: N_fft_use,          // diffraction pattern size (pixels)
    scanType: scanType,
    material: material,
    objheight_m: objheight_m,
    energy_keV: energy_keV,
    N_photons: N_photons,
    pixel_size_nm: dx_nm,        // real-space resolution from detector geometry
    detector: geom,              // full detector geometry info
    oversampling: oversampling,  // actual O = N_det/asize
    oversampling_sim: O_sim,     // simulated O = N_fft_use/asize
    z_m: z_m,
    beamline: blInfo,
    coherence: cohSummary,       // degree of coherence info
    scan_step_um: opts.scan_step_um || 0,
    scan_lx_um: opts.scan_lx_um || 0,
    scan_ly_um: opts.scan_ly_um || 0
  };
};

// ── Offline fallback renderer (6-panel) ──
window.renderPtychoPanel = function(canvas, result) {
  if (!canvas || !result) return;
  var cw = canvas.width || 600;
  var ch = canvas.height || 500;
  var ctx = canvas.getContext('2d');
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, cw, ch);

  var gridH = ch;
  var pw = Math.floor(cw / 3), ph = Math.floor(gridH / 2);
  var panels = [
    {title: 'OBJ Amplitude', x: 0, y: 0, w: pw, h: ph, cmap: 'viridis'},
    {title: 'OBJ Phase', x: pw, y: 0, w: pw, h: ph, cmap: 'hsv'},
    {title: 'Probe', x: pw * 2, y: 0, w: cw - pw * 2, h: ph, cmap: 'hot'},
    {title: 'Scan Positions', x: 0, y: ph, w: pw, h: gridH - ph, cmap: 'none'},
    {title: 'Exit Wave', x: pw, y: ph, w: pw, h: gridH - ph, cmap: 'hot'},
    {title: 'Diffraction (log)', x: pw * 2, y: ph, w: cw - pw * 2, h: gridH - ph, cmap: 'viridis'}
  ];

  function _renderArr(arr, N, px, py, pw2, ph2, logScale, cmap) {
    var lut = _getCmapLUT(cmap);
    var mn = Infinity, mx = -Infinity;
    for (var i = 0; i < arr.length; i++) {
      var v = logScale ? Math.log(Math.max(arr[i], 1e-10)) : arr[i];
      if (v < mn) mn = v; if (v > mx) mx = v;
    }
    var range = mx - mn; if (range < 1e-10) range = 1;
    var inv = 255 / range;
    var id = ctx.createImageData(pw2, ph2);
    var d = id.data;
    for (var y = 0; y < ph2; y++) {
      for (var x = 0; x < pw2; x++) {
        var sy = Math.floor(y * N / ph2), sx = Math.floor(x * N / pw2);
        var raw = arr[sy * N + sx];
        var v = logScale ? Math.log(Math.max(raw, 1e-10)) : raw;
        var idx = ((v - mn) * inv + 0.5) | 0;
        if (idx < 0) idx = 0; if (idx > 255) idx = 255;
        var off = (y * pw2 + x) * 4;
        d[off]     = lut[idx * 3];
        d[off + 1] = lut[idx * 3 + 1];
        d[off + 2] = lut[idx * 3 + 2];
        d[off + 3] = 255;
      }
    }
    ctx.putImageData(id, px, py);
  }

  // Panel 0: Object amplitude
  _renderArr(result.object.amp, result.object.size, panels[0].x, panels[0].y, panels[0].w, panels[0].h, false, 'viridis');
  // Panel 1: Object phase
  _renderArr(result.object.phase, result.object.size, panels[1].x, panels[1].y, panels[1].w, panels[1].h, false, 'hsv');
  // Panel 2: Probe amplitude
  var probeAmp = new Float64Array(result.asize * result.asize);
  for (var i = 0; i < probeAmp.length; i++) {
    probeAmp[i] = Math.sqrt(result.probe.re[i] * result.probe.re[i] + result.probe.im[i] * result.probe.im[i]);
  }
  _renderArr(probeAmp, result.asize, panels[2].x, panels[2].y, panels[2].w, panels[2].h, false, 'hot');
  // Panel 3: Scan positions
  _renderArr(result.object.amp, result.object.size, panels[3].x, panels[3].y, panels[3].w, panels[3].h, false, 'viridis');
  var oSize = result.object.size;
  var scX = panels[3].w / oSize, scY = panels[3].h / oSize;
  ctx.fillStyle = 'rgba(77,184,255,0.7)';
  for (var i = 0; i < result.positions.length; i++) {
    var p = result.positions[i];
    var sx = panels[3].x + (p.x + result.asize / 2) * scX;
    var sy = panels[3].y + (p.y + result.asize / 2) * scY;
    ctx.fillRect(sx - 1, sy - 1, 3, 3);
  }
  // Panel 4: Exit wave
  var dpN = result.dpSize || result.asize;  // diffraction pattern dimension
  if (result.patterns.length > 0) {
    var ew = new Float64Array(result.patterns[0].length);
    for (var i = 0; i < ew.length; i++) ew[i] = Math.sqrt(Math.max(result.patterns[0][i], 0));
    _renderArr(ew, dpN, panels[4].x, panels[4].y, panels[4].w, panels[4].h, false, 'hot');
  }
  // Panel 5: Diffraction pattern (log)
  if (result.patterns.length > 0) {
    _renderArr(result.patterns[0], dpN, panels[5].x, panels[5].y, panels[5].w, panels[5].h, true, 'viridis');
  }

  // Labels
  ctx.font = '9px monospace';
  ctx.fillStyle = '#4db8ff';
  for (var i = 0; i < panels.length; i++) {
    ctx.fillText(panels[i].title, panels[i].x + 3, panels[i].y + 10);
  }
  ctx.strokeStyle = '#333';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (var c = 1; c < 3; c++) { ctx.moveTo(pw * c, 0); ctx.lineTo(pw * c, gridH); }
  ctx.moveTo(0, ph); ctx.lineTo(cw, ph);
  ctx.stroke();

};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof PTYCHO_WS_PORT!=="undefined")globalThis.PTYCHO_WS_PORT=PTYCHO_WS_PORT;
if(typeof PTYCHO_WS_URL!=="undefined")globalThis.PTYCHO_WS_URL=PTYCHO_WS_URL;
if(typeof _REF_INDEX!=="undefined")globalThis._REF_INDEX=_REF_INDEX;
if(typeof ML!=="undefined")globalThis.ML=ML;
if(typeof _addPoissonNoise!=="undefined")globalThis._addPoissonNoise=_addPoissonNoise;
if(typeof _buildSynthParams!=="undefined")globalThis._buildSynthParams=_buildSynthParams;
if(typeof _cmapCache!=="undefined")globalThis._cmapCache=_cmapCache;
if(typeof _createComplexObject!=="undefined")globalThis._createComplexObject=_createComplexObject;
if(typeof _createFresnelSincProbe!=="undefined")globalThis._createFresnelSincProbe=_createFresnelSincProbe;
if(typeof _decodeRawComplex!=="undefined")globalThis._decodeRawComplex=_decodeRawComplex;
if(typeof _fermatSpiral!=="undefined")globalThis._fermatSpiral=_fermatSpiral;
if(typeof _fft1d!=="undefined")globalThis._fft1d=_fft1d;
if(typeof _fft2d!=="undefined")globalThis._fft2d=_fft2d;
if(typeof _fftshift!=="undefined")globalThis._fftshift=_fftshift;
if(typeof _fluxToPhotons!=="undefined")globalThis._fluxToPhotons=_fluxToPhotons;
if(typeof _genResolutionChartThickness!=="undefined")globalThis._genResolutionChartThickness=_genResolutionChartThickness;
if(typeof _genSiemensStarThickness!=="undefined")globalThis._genSiemensStarThickness=_genSiemensStarThickness;
if(typeof _generateProbeModes!=="undefined")globalThis._generateProbeModes=_generateProbeModes;
if(typeof _getBeamlineInfo!=="undefined")globalThis._getBeamlineInfo=_getBeamlineInfo;
if(typeof _getCmapLUT!=="undefined")globalThis._getCmapLUT=_getCmapLUT;
if(typeof _getRefIndex!=="undefined")globalThis._getRefIndex=_getRefIndex;
if(typeof _propFreeFf!=="undefined")globalThis._propFreeFf=_propFreeFf;
if(typeof _ptychoCoherenceLength!=="undefined")globalThis._ptychoCoherenceLength=_ptychoCoherenceLength;
if(typeof _ptychoCoherenceModes!=="undefined")globalThis._ptychoCoherenceModes=_ptychoCoherenceModes;
if(typeof _ptychoCoherentFraction!=="undefined")globalThis._ptychoCoherentFraction=_ptychoCoherentFraction;
if(typeof _ptychoConnected!=="undefined")globalThis._ptychoConnected=_ptychoConnected;
if(typeof _ptychoCurrentEngine!=="undefined")globalThis._ptychoCurrentEngine=_ptychoCurrentEngine;
if(typeof _ptychoCurrentJobId!=="undefined")globalThis._ptychoCurrentJobId=_ptychoCurrentJobId;
if(typeof _ptychoDataLoaded!=="undefined")globalThis._ptychoDataLoaded=_ptychoDataLoaded;
if(typeof _ptychoDetectorGeometry!=="undefined")globalThis._ptychoDetectorGeometry=_ptychoDetectorGeometry;
if(typeof _ptychoErrorHistory!=="undefined")globalThis._ptychoErrorHistory=_ptychoErrorHistory;
if(typeof _ptychoGpuAvailable!=="undefined")globalThis._ptychoGpuAvailable=_ptychoGpuAvailable;
if(typeof _ptychoHandleMessage!=="undefined")globalThis._ptychoHandleMessage=_ptychoHandleMessage;
if(typeof _ptychoIteration!=="undefined")globalThis._ptychoIteration=_ptychoIteration;
if(typeof _ptychoOnComplete!=="undefined")globalThis._ptychoOnComplete=_ptychoOnComplete;
if(typeof _ptychoOnDataLoaded!=="undefined")globalThis._ptychoOnDataLoaded=_ptychoOnDataLoaded;
if(typeof _ptychoOnError!=="undefined")globalThis._ptychoOnError=_ptychoOnError;
if(typeof _ptychoOnIterUpdate!=="undefined")globalThis._ptychoOnIterUpdate=_ptychoOnIterUpdate;
if(typeof _ptychoOnPreviewReady!=="undefined")globalThis._ptychoOnPreviewReady=_ptychoOnPreviewReady;
if(typeof _ptychoOversampling!=="undefined")globalThis._ptychoOversampling=_ptychoOversampling;
if(typeof _ptychoPendingPreview!=="undefined")globalThis._ptychoPendingPreview=_ptychoPendingPreview;
if(typeof _ptychoPipelineInfo!=="undefined")globalThis._ptychoPipelineInfo=_ptychoPipelineInfo;
if(typeof _ptychoPreflightCheck!=="undefined")globalThis._ptychoPreflightCheck=_ptychoPreflightCheck;
if(typeof _ptychoPreviewRafPending!=="undefined")globalThis._ptychoPreviewRafPending=_ptychoPreviewRafPending;
if(typeof _ptychoRawData!=="undefined")globalThis._ptychoRawData=_ptychoRawData;
if(typeof _ptychoReconnectTimer!=="undefined")globalThis._ptychoReconnectTimer=_ptychoReconnectTimer;
if(typeof _ptychoRunning!=="undefined")globalThis._ptychoRunning=_ptychoRunning;
if(typeof _ptychoSSARecommendation!=="undefined")globalThis._ptychoSSARecommendation=_ptychoSSARecommendation;
if(typeof _ptychoSend!=="undefined")globalThis._ptychoSend=_ptychoSend;
if(typeof _ptychoTotalIterations!=="undefined")globalThis._ptychoTotalIterations=_ptychoTotalIterations;
if(typeof _ptychoWs!=="undefined")globalThis._ptychoWs=_ptychoWs;
if(typeof _rasterScan!=="undefined")globalThis._rasterScan=_rasterScan;
if(typeof _updatePtychoConnectionUI!=="undefined")globalThis._updatePtychoConnectionUI=_updatePtychoConnectionUI;
if(typeof ptychoCancelReconstruction!=="undefined")globalThis.ptychoCancelReconstruction=ptychoCancelReconstruction;
if(typeof ptychoConnect!=="undefined")globalThis.ptychoConnect=ptychoConnect;
if(typeof ptychoDisconnect!=="undefined")globalThis.ptychoDisconnect=ptychoDisconnect;
if(typeof ptychoGenerateSynthetic!=="undefined")globalThis.ptychoGenerateSynthetic=ptychoGenerateSynthetic;
if(typeof ptychoPreviewSynthetic!=="undefined")globalThis.ptychoPreviewSynthetic=ptychoPreviewSynthetic;
if(typeof ptychoStartReconstruction!=="undefined")globalThis.ptychoStartReconstruction=ptychoStartReconstruction;
if(typeof renderPtychoErrorPlot!=="undefined")globalThis.renderPtychoErrorPlot=renderPtychoErrorPlot;
if(typeof renderPtychoFromServer!=="undefined")globalThis.renderPtychoFromServer=renderPtychoFromServer;
if(typeof renderPtychoPanel!=="undefined")globalThis.renderPtychoPanel=renderPtychoPanel;
if(typeof simPtycho!=="undefined")globalThis.simPtycho=simPtycho;
