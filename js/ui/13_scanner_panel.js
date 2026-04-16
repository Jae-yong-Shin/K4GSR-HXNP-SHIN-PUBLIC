'use strict';
// ===== ui/13_scanner_panel.js -- Nano Scanner Control Panel =====
// @module ui/13_scanner_panel
// @exports NANO_SCANNER, _NANO_AXES, _STREAM_CH_COLORS, _handleNanoMessage, _nanoConnect, _nanoDisconnect, _nanoIFMPulseTimer, _nanoJog, _nanoMoveAbs, _nanoScanAbort, _nanoScanStart, _nanoSend, _nanoSendWarnTime, _nanoSetPollRate, _nanoStartPoll, ...
// SmarAct MCS2 + PicoScale nano-positioner control via /ws/scan WebSocket.
// Follows motor jog pattern (.ax-ctrl/.jog-btn) from 10_motor_jog.js
// and UI component standard (26_ui_component_standard.md).

// ===== Global State =====
var NANO_SCANNER = {
  connected: false,
  mcs2_ok: false,
  ps_ok: false,
  mcs2_mode: '',
  ps_mode: '',
  positions: { 0: 0, 1: 0, 2: 0 },      // PicoScale readback (nm)
  mcs2_pos: { 0: 0, 1: 0, 2: 0 },        // MCS2 position (nm)
  scanning: false,
  scanProgress: 0,
  scanTotal: 0,
  scanEta: 0,
  pollTimer: null,
  pollRate: 2,                             // polling rate (Hz), user-selectable
  stepSizes: { 0: 100, 1: 100, 2: 100 }  // per-axis jog step (nm)
};

var _NANO_AXES = [
  { ch: 0, label: 'X', color: 'var(--ac)' },
  { ch: 1, label: 'Y', color: 'var(--gn)' },
  { ch: 2, label: 'Z', color: 'var(--am)' }
];

// ===== WebSocket Send Helper =====
var _nanoSendWarnTime = 0;
function _nanoSend(msg) {
  var ws = (typeof EPICS_STATE !== 'undefined') ? EPICS_STATE.scanWs : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    // Rate-limit "WS not connected" to once per 10s (avoid log spam in Virtual mode)
    var now = Date.now();
    if (now - _nanoSendWarnTime > 10000) {
      _nanoSendWarnTime = now;
      if (typeof log === 'function') log('warn', 'Nano: scan WS not connected');
    }
    var errEl = document.getElementById('nano_ws_status');
    if (errEl) {
      errEl.textContent = 'WS not connected';
      errEl.style.color = 'var(--rd)';
    }
    // Stop polling if WS is gone (e.g., switched to Virtual mode)
    if (NANO_SCANNER.pollTimer && msg && msg.action === 'nano_get_pos') {
      _nanoStopPoll();
      NANO_SCANNER.connected = false;
      _nanoUpdateStatusUI();
    }
    return false;
  }
  try {
    ws.send(JSON.stringify(msg));
    return true;
  } catch (e) {
    if (typeof log === 'function') log('err', 'Nano send error: ' + e.message);
    return false;
  }
}

// ===== Connect / Disconnect =====
function _nanoConnect() {
  // Virtual mode: use frontend mock (no server connection)
  if (typeof state !== 'undefined' && state.mode === 'virtual') {
    NANO_SCANNER.connected = true;
    NANO_SCANNER.mcs2_ok = true;
    NANO_SCANNER.ps_ok = true;
    NANO_SCANNER._mock = true;
    _nanoUpdateStatusUI();
    if (typeof log === 'function') log('info', 'Nano: connected (mock — Virtual mode)');
    // Start mock position polling
    if (!NANO_SCANNER._mockPollId) {
      NANO_SCANNER._mockPollId = setInterval(function() {
        _nanoUpdatePositionUI();
      }, 500);
    }
    return;
  }
  // Real mode: connect via scan WebSocket to server
  var ws = (typeof EPICS_STATE !== 'undefined') ? EPICS_STATE.scanWs : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    var errEl = document.getElementById('nano_ws_status');
    if (errEl) {
      errEl.textContent = 'Scan WS not open. Switch to Real mode or connect to server.';
      errEl.style.color = 'var(--rd)';
    }
    return;
  }
  _nanoSend({ action: 'nano_connect' });
}

function _nanoDisconnect() {
  _nanoStopPoll();
  // Mock mode cleanup
  if (NANO_SCANNER._mock) {
    if (NANO_SCANNER._mockPollId) { clearInterval(NANO_SCANNER._mockPollId); NANO_SCANNER._mockPollId = null; }
    NANO_SCANNER._mock = false;
  } else {
    _nanoSend({ action: 'nano_disconnect' });
  }
  NANO_SCANNER.connected = false;
  NANO_SCANNER.mcs2_ok = false;
  NANO_SCANNER.ps_ok = false;
  _nanoUpdateStatusUI();
  _nanoUpdatePositionUI();
}

// ===== Position Polling =====
function _nanoStartPoll() {
  _nanoStopPoll();
  var interval = Math.round(1000 / (NANO_SCANNER.pollRate || 2));
  NANO_SCANNER.pollTimer = setInterval(function() {
    if (NANO_SCANNER.connected) {
      _nanoSend({ action: 'nano_get_pos' });
    }
  }, interval);
}

function _nanoSetPollRate(hz) {
  NANO_SCANNER.pollRate = hz;
  // Update button styles
  var rates = [1, 2, 5, 10];
  for (var i = 0; i < rates.length; i++) {
    var btn = document.getElementById('nano_rate_' + rates[i]);
    if (btn) {
      btn.style.borderBottom = (rates[i] === hz) ? '2px solid var(--ac)' : '2px solid transparent';
      btn.style.color = (rates[i] === hz) ? 'var(--ac)' : 'var(--t3)';
    }
  }
  // Restart polling with new rate
  if (NANO_SCANNER.pollTimer) _nanoStartPoll();
  // Reset rate counter for immediate display update
  NANO_SCANNER._ifmRateCounter = 0;
  NANO_SCANNER._ifmRateTime = Date.now();
}

function _nanoStopPoll() {
  if (NANO_SCANNER.pollTimer) {
    clearInterval(NANO_SCANNER.pollTimer);
    NANO_SCANNER.pollTimer = null;
  }
}

// ===== Jog =====
function _nanoJog(ch, multiplier) {
  var stepEl = document.getElementById('nano_step_' + ch);
  var step = stepEl ? parseFloat(stepEl.value) : (NANO_SCANNER.stepSizes[ch] || 100);
  NANO_SCANNER.stepSizes[ch] = step;
  var delta = multiplier * step;
  // Mock mode: update position locally
  if (NANO_SCANNER._mock) {
    if (!NANO_SCANNER._mockPos) NANO_SCANNER._mockPos = [0, 0, 0];
    NANO_SCANNER._mockPos[ch] = (NANO_SCANNER._mockPos[ch] || 0) + delta;
    NANO_SCANNER.positions[ch] = { ps: NANO_SCANNER._mockPos[ch], mcs2: NANO_SCANNER._mockPos[ch], err: 0 };
    _nanoUpdatePositionUI();
    return;
  }
  _nanoSend({ action: 'nano_jog', ch: ch, delta_nm: delta });
}

// ===== Absolute Move =====
function _nanoMoveAbs(ch) {
  var inputEl = document.getElementById('nano_abs_' + ch);
  if (!inputEl) return;
  var pos = parseFloat(inputEl.value);
  if (isNaN(pos)) return;
  // Mock mode
  if (NANO_SCANNER._mock) {
    if (!NANO_SCANNER._mockPos) NANO_SCANNER._mockPos = [0, 0, 0];
    NANO_SCANNER._mockPos[ch] = pos;
    NANO_SCANNER.positions[ch] = { ps: pos, mcs2: pos, err: 0 };
    _nanoUpdatePositionUI();
    return;
  }
  _nanoSend({ action: 'nano_move', ch: ch, pos_nm: pos });
}

// ===== Stop =====
function _nanoStop(ch) {
  _nanoSend({ action: 'nano_stop', ch: ch });
}

function _nanoStopAll() {
  for (var i = 0; i < 3; i++) {
    _nanoSend({ action: 'nano_stop', ch: i });
  }
}

// ===== Scan Start / Abort =====
function _nanoScanStart() {
  var el = function(id) { return document.getElementById(id); };
  var fastAxis = parseInt((el('nano_scan_fast_axis') || {}).value, 10);
  var slowAxis = parseInt((el('nano_scan_slow_axis') || {}).value, 10);
  var fastStart = parseFloat((el('nano_scan_fast_start') || {}).value);
  var fastStop = parseFloat((el('nano_scan_fast_stop') || {}).value);
  var nFast = parseInt((el('nano_scan_n_fast') || {}).value, 10);
  var slowStart = parseFloat((el('nano_scan_slow_start') || {}).value);
  var slowStop = parseFloat((el('nano_scan_slow_stop') || {}).value);
  var nSlow = parseInt((el('nano_scan_n_slow') || {}).value, 10);
  var dwell = parseFloat((el('nano_scan_dwell') || {}).value);

  if (isNaN(fastStart) || isNaN(fastStop) || isNaN(nFast) ||
      isNaN(slowStart) || isNaN(slowStop) || isNaN(nSlow) || isNaN(dwell)) {
    if (typeof log === 'function') log('warn', 'Nano scan: invalid parameters');
    return;
  }

  NANO_SCANNER.scanning = true;
  NANO_SCANNER.scanProgress = 0;
  NANO_SCANNER.scanTotal = nFast * nSlow;
  NANO_SCANNER.scanEta = 0;
  _nanoUpdateScanUI();

  _nanoSend({
    action: 'nano_scan_start',
    params: {
      fast_axis: fastAxis, slow_axis: slowAxis,
      fast_start: fastStart, fast_stop: fastStop, n_fast: nFast,
      slow_start: slowStart, slow_stop: slowStop, n_slow: nSlow,
      dwell_s: dwell
    }
  });
}

function _nanoScanAbort() {
  _nanoSend({ action: 'nano_scan_abort' });
  NANO_SCANNER.scanning = false;
  _nanoUpdateScanUI();
}

// ===== WebSocket Message Handler =====
function _handleNanoMessage(msg) {
  if (!msg || !msg.type) return;

  // Show server errors in WS status area
  if (msg.type === 'error' || msg.type === 'nano_error') {
    var errEl = document.getElementById('nano_ws_status');
    if (errEl) {
      errEl.textContent = msg.message || msg.error || 'Server error';
      errEl.style.color = 'var(--rd)';
    }
    if (typeof log === 'function') log('warn', 'Nano: ' + (msg.message || msg.error));
    return;
  }

  if (msg.type === 'nano_status') {
    NANO_SCANNER.connected = !!msg.ok;
    NANO_SCANNER.mcs2_ok = !!msg.mcs2_connected;
    NANO_SCANNER.ps_ok = !!msg.ps_connected;
    if (msg.mcs2_mode) NANO_SCANNER.mcs2_mode = msg.mcs2_mode;
    if (msg.picoscale_mode) NANO_SCANNER.ps_mode = msg.picoscale_mode;
    if (msg.msg === 'disconnected') {
      NANO_SCANNER.connected = false;
      NANO_SCANNER.mcs2_ok = false;
      NANO_SCANNER.ps_ok = false;
      _nanoStopPoll();
    } else if (msg.ok) {
      _nanoStartPoll();
    }
    _nanoUpdateStatusUI();
    return;
  }

  if (msg.type === 'nano_positions') {
    if (msg.picoscale_nm) {
      for (var k in msg.picoscale_nm) {
        if (msg.picoscale_nm.hasOwnProperty(k)) {
          NANO_SCANNER.positions[parseInt(k, 10)] = msg.picoscale_nm[k];
        }
      }
    }
    if (msg.mcs2_nm) {
      for (var m in msg.mcs2_nm) {
        if (msg.mcs2_nm.hasOwnProperty(m)) {
          NANO_SCANNER.mcs2_pos[parseInt(m, 10)] = msg.mcs2_nm[m];
        }
      }
    }
    _nanoUpdatePositionUI();
    return;
  }

  if (msg.type === 'nano_move') {
    if (typeof msg.ch === 'number' && typeof msg.pos_nm === 'number') {
      NANO_SCANNER.positions[msg.ch] = msg.pos_nm;
    }
    _nanoUpdatePositionUI();
    return;
  }

  if (msg.type === 'nano_scan_progress') {
    NANO_SCANNER.scanProgress = msg.current || 0;
    NANO_SCANNER.scanTotal = msg.total || NANO_SCANNER.scanTotal;
    NANO_SCANNER.scanEta = msg.eta_s || 0;
    if (msg.done) NANO_SCANNER.scanning = false;
    _nanoUpdateScanUI();
    return;
  }

  // Streaming messages
  if (msg.type === 'nano_stream_data' || msg.type === 'nano_stream_batch') {
    _nanoStreamOnData(msg);
    return;
  }
  if (msg.type === 'nano_stream_started' || msg.type === 'nano_stream_stopped' ||
      msg.type === 'nano_stream_error') {
    _nanoStreamOnStatus(msg);
    return;
  }
}

// ===== UI Update: Status Indicators =====
function _nanoUpdateStatusUI() {
  var mcs2Dot = document.getElementById('nano_mcs2_dot');
  var psDot = document.getElementById('nano_ps_dot');
  var connBtn = document.getElementById('nano_connect_btn');
  var discBtn = document.getElementById('nano_disconnect_btn');
  var wsStatus = document.getElementById('nano_ws_status');

  if (mcs2Dot) {
    mcs2Dot.innerHTML = NANO_SCANNER.mcs2_ok ? '&#9679;' : '&#9675;';
    mcs2Dot.style.color = NANO_SCANNER.mcs2_ok ? 'var(--gn)' : 'var(--t3)';
  }
  var mcs2Mode = document.getElementById('nano_mcs2_mode');
  if (mcs2Mode && NANO_SCANNER.mcs2_mode) {
    mcs2Mode.textContent = '(' + NANO_SCANNER.mcs2_mode + ')';
    mcs2Mode.style.color = NANO_SCANNER.mcs2_mode === 'mock' ? 'var(--am)' : 'var(--t3)';
  }
  if (psDot) {
    psDot.innerHTML = NANO_SCANNER.ps_ok ? '&#9679;' : '&#9675;';
    psDot.style.color = NANO_SCANNER.ps_ok ? 'var(--gn)' : 'var(--t3)';
  }
  var psMode = document.getElementById('nano_ps_mode');
  if (psMode && NANO_SCANNER.ps_mode) {
    psMode.textContent = '(' + NANO_SCANNER.ps_mode + ')';
    psMode.style.color = NANO_SCANNER.ps_mode === 'mock' ? 'var(--am)' : 'var(--t3)';
  }
  if (connBtn) {
    connBtn.disabled = NANO_SCANNER.connected;
    connBtn.style.opacity = NANO_SCANNER.connected ? '0.4' : '1';
  }
  if (discBtn) {
    discBtn.disabled = !NANO_SCANNER.connected;
    discBtn.style.opacity = NANO_SCANNER.connected ? '1' : '0.4';
  }
  // Clear error on successful status
  if (wsStatus && NANO_SCANNER.connected) {
    wsStatus.textContent = '';
  }
}

// ===== UI Update: Position Display =====
var _nanoIFMPulseTimer = null;

function _nanoUpdatePositionUI() {
  var isConn = NANO_SCANNER.connected;
  for (var i = 0; i < 3; i++) {
    var posEl = document.getElementById('nano_pos_' + i);
    var psVal = NANO_SCANNER.positions[i];
    var mcVal = NANO_SCANNER.mcs2_pos[i];
    if (posEl) {
      posEl.textContent = (typeof psVal === 'number') ? psVal.toFixed(3) : '--';
      posEl.style.color = isConn ? 'var(--gn)' : 'var(--t3)';
    }
    // Update abs input with current position (if not focused)
    var absEl = document.getElementById('nano_abs_' + i);
    if (absEl && document.activeElement !== absEl && isConn) {
      absEl.value = psVal.toFixed(1);
    }
    // Update interferometer table
    var ifmPs = document.getElementById('nano_ifm_ps_' + i);
    var ifmMc = document.getElementById('nano_ifm_mc_' + i);
    var ifmErr = document.getElementById('nano_ifm_err_' + i);
    if (ifmPs) {
      ifmPs.textContent = isConn && typeof psVal === 'number' ? psVal.toFixed(3) : '--';
      ifmPs.style.color = isConn ? 'var(--t1)' : 'var(--t3)';
    }
    if (ifmMc) {
      ifmMc.textContent = isConn && typeof mcVal === 'number' ? mcVal.toFixed(3) : '--';
    }
    if (ifmErr) {
      if (isConn && typeof psVal === 'number' && typeof mcVal === 'number') {
        var err = psVal - mcVal;
        ifmErr.textContent = err.toFixed(3);
        var absErr = Math.abs(err);
        ifmErr.style.color = absErr < 1 ? 'var(--gn)' : absErr < 10 ? 'var(--am)' : 'var(--rd)';
      } else {
        ifmErr.textContent = '--';
        ifmErr.style.color = 'var(--t3)';
      }
    }
  }
  // Pulse indicator (blink green briefly)
  if (isConn) {
    var pulse = document.getElementById('nano_ifm_pulse');
    if (pulse) {
      pulse.style.background = 'var(--gn)';
      clearTimeout(_nanoIFMPulseTimer);
      _nanoIFMPulseTimer = setTimeout(function() {
        if (pulse) pulse.style.background = 'var(--t3)';
      }, 200);
    }
    // Update rate display
    if (!NANO_SCANNER._ifmRateCounter) NANO_SCANNER._ifmRateCounter = 0;
    if (!NANO_SCANNER._ifmRateTime) NANO_SCANNER._ifmRateTime = Date.now();
    NANO_SCANNER._ifmRateCounter++;
    var elapsed = (Date.now() - NANO_SCANNER._ifmRateTime) / 1000;
    if (elapsed >= 2) {
      var rate = NANO_SCANNER._ifmRateCounter / elapsed;
      var rateEl = document.getElementById('nano_ifm_rate');
      if (rateEl) rateEl.textContent = rate.toFixed(1) + ' Hz';
      NANO_SCANNER._ifmRateCounter = 0;
      NANO_SCANNER._ifmRateTime = Date.now();
    }
  }
}

// ===== UI Update: Scan Progress =====
function _nanoUpdateScanUI() {
  var barFill = document.getElementById('nano_scan_bar_fill');
  var barText = document.getElementById('nano_scan_bar_text');
  var startBtn = document.getElementById('nano_scan_start_btn');
  var abortBtn = document.getElementById('nano_scan_abort_btn');

  var pct = 0;
  if (NANO_SCANNER.scanTotal > 0) {
    pct = Math.min(100, Math.round(100 * NANO_SCANNER.scanProgress / NANO_SCANNER.scanTotal));
  }

  if (barFill) barFill.style.width = pct + '%';
  if (barText) {
    if (NANO_SCANNER.scanning) {
      var etaStr = NANO_SCANNER.scanEta > 0 ? ('  ETA: ' + NANO_SCANNER.scanEta.toFixed(1) + 's') : '';
      barText.textContent = pct + '% (' + NANO_SCANNER.scanProgress + '/' + NANO_SCANNER.scanTotal + ')' + etaStr;
      barText.style.color = 'var(--ac)';
    } else if (NANO_SCANNER.scanProgress > 0 && NANO_SCANNER.scanProgress >= NANO_SCANNER.scanTotal) {
      barText.textContent = 'Complete (' + NANO_SCANNER.scanTotal + ' pts)';
      barText.style.color = 'var(--gn)';
    } else if (!NANO_SCANNER.scanning && NANO_SCANNER.scanProgress > 0) {
      barText.textContent = 'Aborted at ' + NANO_SCANNER.scanProgress + '/' + NANO_SCANNER.scanTotal;
      barText.style.color = 'var(--am)';
    } else {
      barText.textContent = 'Idle';
      barText.style.color = 'var(--t3)';
    }
  }
  if (startBtn) {
    startBtn.disabled = NANO_SCANNER.scanning || !NANO_SCANNER.connected;
    startBtn.style.opacity = (NANO_SCANNER.scanning || !NANO_SCANNER.connected) ? '0.4' : '1';
  }
  if (abortBtn) {
    abortBtn.disabled = !NANO_SCANNER.scanning;
    abortBtn.style.opacity = NANO_SCANNER.scanning ? '1' : '0.4';
  }
}

// ===== Render Scanner Tab =====
// Uses .ax-ctrl / .jog-btn / .jog-neg / .jog-pos classes from main CSS
// and standard component patterns from 26_ui_component_standard.md
function renderScannerTab() {
  var pane = document.getElementById('tab-scanner');
  if (!pane) return;
  pane.style.overflow = 'hidden';

  var h = '';

  // Inject style to hide number input spinners (cross-browser)
  h += '<style>' +
    '#tab-scanner input[type=number]{-moz-appearance:textfield}' +
    '#tab-scanner input[type=number]::-webkit-outer-spin-button,' +
    '#tab-scanner input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}' +
    '#tab-scanner select,#tab-scanner input{min-width:0;box-sizing:border-box}' +
    '</style>';

  // --- Connection Header (two rows: buttons + status) ---
  h += '<div style="padding:3px 0;margin-bottom:6px;border-bottom:1px solid var(--b0)">';

  // Row 1: buttons + status dots on same line
  h += '<div style="display:flex;align-items:center;gap:4px">';
  var _btnH = 'height:22px;line-height:14px;white-space:nowrap;';
  h += '<button id="nano_connect_btn" class="sb go" onclick="_nanoConnect()" ' +
    'style="padding:4px 10px;' + _btnH + '">Connect</button>';
  h += '<button id="nano_disconnect_btn" class="sb sec" onclick="_nanoDisconnect()" ' +
    'style="padding:4px 10px;border:1px solid var(--b1);color:var(--t1);' + _btnH + '">Disconnect</button>';
  h += '<button class="sb stop" onclick="_nanoStopAll()" ' +
    'style="padding:4px 10px;' + _btnH + '">STOP ALL</button>';
  h += '</div>';

  // Row 2: status dots (full width, never truncated)
  h += '<div style="display:flex;align-items:center;gap:8px;font-size:8px;font-family:var(--mn);margin-top:4px">';
  h += '<span style="display:flex;align-items:center;gap:2px">' +
    '<span id="nano_mcs2_dot" style="color:var(--t3);font-size:8px">&#9675;</span>' +
    '<span style="color:var(--t2)">MCS2</span>' +
    '<span id="nano_mcs2_mode" style="color:var(--t3);font-size:7px"></span></span>';
  h += '<span style="display:flex;align-items:center;gap:2px">' +
    '<span id="nano_ps_dot" style="color:var(--t3);font-size:8px">&#9675;</span>' +
    '<span style="color:var(--t2)">PicoScale</span>' +
    '<span id="nano_ps_mode" style="color:var(--t3);font-size:7px"></span></span>';
  h += '</div>';
  h += '</div>';

  // WS status message area
  h += '<div id="nano_ws_status" style="font-size:8px;color:var(--t3);margin-bottom:4px"></div>';

  // --- Section: Laser Interferometer Monitor ---
  h += '<div style="font-size:10px;color:var(--t1);margin-bottom:4px;' +
    'font-weight:600;letter-spacing:0.5px;display:flex;align-items:center;gap:6px">' +
    'LASER INTERFEROMETER' +
    '<span id="nano_ifm_pulse" style="display:inline-block;width:5px;height:5px;' +
    'border-radius:50%;background:var(--t3);transition:background 0.15s"></span>' +
    '<span id="nano_ifm_rate" style="font-size:7px;color:var(--t3);font-weight:400"></span>';

  // Polling rate selector buttons (right-aligned)
  var _pollRates = [1, 2, 5, 10];
  h += '<span style="margin-left:auto;display:flex;align-items:center;gap:2px;font-weight:400">';
  for (var _pi = 0; _pi < _pollRates.length; _pi++) {
    var _pr = _pollRates[_pi];
    var _isActive = _pr === (NANO_SCANNER.pollRate || 2);
    h += '<button id="nano_rate_' + _pr + '" class="sb" onclick="_nanoSetPollRate(' + _pr + ')" ' +
      'style="background:transparent;color:' + (_isActive ? 'var(--ac)' : 'var(--t3)') + ';' +
      'font-size:8px;font-family:var(--mn);padding:1px 4px;border:none;' +
      'border-bottom:2px solid ' + (_isActive ? 'var(--ac)' : 'transparent') + ';' +
      'border-radius:0;cursor:pointer;min-width:18px;text-align:center">' + _pr + '</button>';
  }
  h += '<span style="font-size:7px;color:var(--t3)">Hz</span>';
  h += '</span>';
  h += '</div>';

  // Interferometer position table
  h += '<div style="background:var(--s2);border:1px solid var(--b1);border-radius:4px;' +
    'padding:6px 8px;margin-bottom:8px;font-family:var(--mn)">';

  // Table header
  h += '<div style="display:grid;grid-template-columns:24px 1fr 1fr 1fr;gap:4px;' +
    'font-size:7px;color:var(--t3);margin-bottom:3px;padding-bottom:3px;border-bottom:1px solid var(--b0)">';
  h += '<span>CH</span>';
  h += '<span style="text-align:right">PicoScale (nm)</span>';
  h += '<span style="text-align:right">MCS2 (nm)</span>';
  h += '<span style="text-align:right">Error (nm)</span>';
  h += '</div>';

  // Table rows (X/Y/Z)
  for (var _ri = 0; _ri < _NANO_AXES.length; _ri++) {
    var _rax = _NANO_AXES[_ri];
    h += '<div style="display:grid;grid-template-columns:24px 1fr 1fr 1fr;gap:4px;' +
      'font-size:10px;line-height:18px">';
    h += '<span style="color:' + _rax.color + ';font-weight:600;font-size:9px">' + _rax.label + '</span>';
    h += '<span id="nano_ifm_ps_' + _rax.ch + '" style="text-align:right;color:var(--t1)">--</span>';
    h += '<span id="nano_ifm_mc_' + _rax.ch + '" style="text-align:right;color:var(--t2)">--</span>';
    h += '<span id="nano_ifm_err_' + _rax.ch + '" style="text-align:right;color:var(--t3)">--</span>';
    h += '</div>';
  }
  h += '</div>';  // end interferometer table

  // --- Section: Position + Jog (uses .ax-ctrl pattern) ---
  h += '<div style="font-size:10px;color:var(--t1);margin-bottom:4px;' +
    'font-weight:600;letter-spacing:0.5px">JOG CONTROL</div>';

  h += '<div style="background:var(--s2);border:1px solid var(--b1);' +
    'border-radius:4px;padding:6px 8px;margin-bottom:8px">';

  for (var i = 0; i < _NANO_AXES.length; i++) {
    var ax = _NANO_AXES[i];
    var ch = ax.ch;
    var posVal = NANO_SCANNER.positions[ch];
    var posStr = (typeof posVal === 'number') ? posVal.toFixed(3) : '--';
    var stepVal = NANO_SCANNER.stepSizes[ch] || 100;

    // Use standard .ax-ctrl structure: r1 (name+value), r2 (jog), r3 (abs)
    h += '<div class="ax-ctrl">';

    // Row 1: axis name + position readback (same as motor panel .ax-r1)
    h += '<div class="ax-r1">';
    h += '<span class="ax-name" style="color:' + ax.color + ';font-weight:600">' +
      ax.label + ' <span class="ax-unit">(nm)</span></span>';
    h += '<span style="font-size:7px;color:var(--t3);margin-left:auto;white-space:nowrap">' +
      '-15000~15000 nm</span>';
    h += '<span class="ctrl-val ax-pos" id="nano_pos_' + ch + '" style="color:' +
      (NANO_SCANNER.connected ? 'var(--gn)' : 'var(--t3)') + '">' + posStr + '</span>';
    h += '</div>';

    // Row 2: jog buttons + step input (same as motor panel .ax-r2)
    h += '<div class="ax-r2">';
    h += '<button class="jog-btn jog-neg" onclick="_nanoJog(' + ch + ',-10)">&#x25C4;&#x25C4;</button>';
    h += '<button class="jog-btn jog-neg" onclick="_nanoJog(' + ch + ',-1)">&#x25C4;</button>';
    h += '<input type="number" value="' + stepVal + '" step="10" min="1" ' +
      'class="ax-step" id="nano_step_' + ch + '" title="Jog step (nm)"/>';
    h += '<button class="jog-btn jog-pos" onclick="_nanoJog(' + ch + ',1)">&#x25BA;</button>';
    h += '<button class="jog-btn jog-pos" onclick="_nanoJog(' + ch + ',10)">&#x25BA;&#x25BA;</button>';
    h += '<button class="sb" onclick="_nanoStop(' + ch + ')" ' +
      'style="background:var(--rd);color:#fff;font-size:8px;font-weight:600;' +
      'padding:2px 6px;border:none;border-radius:3px;cursor:pointer;margin-left:auto">STP</button>';
    h += '</div>';

    // Row 3: absolute position input (same as motor panel .ax-r3)
    h += '<div class="ax-r3" style="display:flex;align-items:center;gap:4px;margin-top:2px">';
    h += '<span style="font-size:7px;color:var(--t2);white-space:nowrap">Abs:</span>';
    h += '<input type="number" id="nano_abs_' + ch + '" value="' + posVal.toFixed(1) + '" step="10" ' +
      'style="width:90px;font-size:8px;background:var(--s2);color:var(--t1);' +
      'border:1px solid var(--b1);border-radius:2px;padding:2px 4px;text-align:right;' +
      'font-family:var(--mn)" ' +
      'onchange="_nanoMoveAbs(' + ch + ')"/>';
    h += '<span style="font-size:7px;color:var(--t3)">nm</span>';
    h += '</div>';

    h += '</div>';  // end .ax-ctrl
  }
  h += '</div>';  // end JOG CONTROL gray box

  // --- Section: 2D Step Scan ---
  h += '<div style="font-size:10px;color:var(--t1);margin-bottom:4px;margin-top:8px;' +
    'font-weight:600;letter-spacing:0.5px">2D STEP SCAN</div>';

  h += '<div style="background:var(--s2);border:1px solid var(--b1);' +
    'border-radius:4px;padding:6px 8px;margin-bottom:8px">';

  // Shared scan input style (compact for narrow sidebar)
  var _scanInp = 'background:var(--bg);color:var(--t1);border:1px solid var(--b1);' +
    'border-radius:3px;font-size:8px;font-family:var(--mn);padding:2px 3px;' +
    'height:20px;box-sizing:border-box;text-align:center;width:100%;min-width:0';
  var _scanSel = 'background:var(--bg);color:var(--t1);border:1px solid var(--b1);' +
    'border-radius:3px;font-size:8px;font-family:var(--mn);padding:2px 2px;' +
    'height:20px;box-sizing:border-box;width:100%;min-width:0';
  var _scanGrid = 'display:grid;grid-template-columns:30px 36px 1fr 1fr 32px;' +
    'gap:3px;align-items:center;margin-bottom:3px';

  // Scan type selector
  h += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">';
  h += '<label style="font-size:8px;color:var(--t2);flex-shrink:0">Type:</label>';
  h += '<select id="nano_scan_type" onchange="_nanoScanTypeChanged()" style="' + _scanSel + '">' +
    '<option value="step2d" selected>Step 2D</option>' +
    '<option value="fly1d">Fly 1D</option>' +
    '<option value="fermat">Fermat Spiral</option></select>';
  h += '</div>';

  // Column headers (CSS grid aligned)
  h += '<div id="nano_scan_grid_hdr" style="' + _scanGrid + ';margin-bottom:2px">';
  h += '<span></span><span style="font-size:7px;color:var(--t3);text-align:center">Axis</span>';
  h += '<span style="font-size:7px;color:var(--t3);text-align:center">Start</span>';
  h += '<span style="font-size:7px;color:var(--t3);text-align:center">Stop</span>';
  h += '<span style="font-size:7px;color:var(--t3);text-align:center">N</span>';
  h += '</div>';

  // Fast axis row (CSS grid aligned)
  h += '<div style="' + _scanGrid + '">';
  h += '<label style="font-size:8px;color:var(--t2)">Fast:</label>';
  h += '<select id="nano_scan_fast_axis" style="' + _scanSel + '">' +
    '<option value="0" selected>X</option><option value="1">Y</option><option value="2">Z</option></select>';
  h += '<input type="number" id="nano_scan_fast_start" value="-1000" step="100" style="' + _scanInp + '"/>';
  h += '<input type="number" id="nano_scan_fast_stop" value="1000" step="100" style="' + _scanInp + '"/>';
  h += '<input type="number" id="nano_scan_n_fast" value="21" step="1" min="2" style="' + _scanInp + '"/>';
  h += '</div>';

  // Slow axis row (CSS grid aligned)
  h += '<div style="' + _scanGrid + '">';
  h += '<label style="font-size:8px;color:var(--t2)">Slow:</label>';
  h += '<select id="nano_scan_slow_axis" style="' + _scanSel + '">' +
    '<option value="0">X</option><option value="1" selected>Y</option><option value="2">Z</option></select>';
  h += '<input type="number" id="nano_scan_slow_start" value="-1000" step="100" style="' + _scanInp + '"/>';
  h += '<input type="number" id="nano_scan_slow_stop" value="1000" step="100" style="' + _scanInp + '"/>';
  h += '<input type="number" id="nano_scan_n_slow" value="21" step="1" min="2" style="' + _scanInp + '"/>';
  h += '</div>';

  // Dwell + info row
  h += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:6px">';
  h += '<label style="font-size:8px;color:var(--t2);flex-shrink:0">Dwell:</label>';
  h += '<input type="number" id="nano_scan_dwell" value="0.01" step="0.001" min="0.001" ' +
    'style="' + _scanInp + ';width:56px"/>';
  h += '<span style="font-size:7px;color:var(--t3)">s</span>';
  h += '<span id="nano_scan_total_info" style="font-size:7px;color:var(--t3);margin-left:auto;white-space:nowrap"></span>';
  h += '</div>';

  // Buttons (standard: Secondary first, Primary last -- but here Start=Primary, Abort=Danger)
  h += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">';
  h += '<button id="nano_scan_start_btn" class="sb go act" onclick="_nanoScanStart()">Start Scan</button>';
  h += '<button id="nano_scan_abort_btn" class="sb stop act" onclick="_nanoScanAbort()" ' +
    'style="opacity:0.4" disabled>Abort</button>';
  h += '</div>';

  // Progress bar (standard from 26_ui_component_standard 8)
  h += '<div style="height:6px;background:var(--s2);border-radius:3px;overflow:hidden;margin-top:4px">';
  h += '<div id="nano_scan_bar_fill" style="width:0%;height:100%;background:var(--ac);' +
    'transition:width 0.2s"></div>';
  h += '</div>';
  h += '<div id="nano_scan_bar_text" style="font-size:8px;color:var(--t3);' +
    'text-align:right;margin-top:2px">Idle</div>';

  // 2D scan heatmap canvas
  h += '<div id="nano_scan_heatmap_wrap" style="margin-top:6px;display:none">';
  h += '<div style="font-size:8px;color:var(--t2);margin-bottom:2px">Scan Result</div>';
  h += '<div style="position:relative;width:100%;aspect-ratio:1;background:var(--bg);' +
    'border:1px solid var(--b1);border-radius:3px;overflow:hidden">';
  h += '<canvas id="nano_scan_heatmap" style="width:100%;height:100%"></canvas>';
  h += '</div>';
  h += '<div style="display:flex;justify-content:space-between;font-size:7px;color:var(--t3);margin-top:2px">';
  h += '<span id="nano_hm_min">0</span>';
  h += '<span id="nano_hm_label">Intensity (a.u.)</span>';
  h += '<span id="nano_hm_max">1</span>';
  h += '</div>';
  h += '</div>';

  h += '</div>';  // end scan section

  // --- Section: Position Streaming ---
  h += '<div style="font-size:10px;color:var(--t1);margin-bottom:4px;margin-top:8px;' +
    'font-weight:600;letter-spacing:0.5px">POSITION STREAMING</div>';

  h += '<div style="background:var(--s2);border:1px solid var(--b1);' +
    'border-radius:4px;padding:6px 8px;margin-bottom:8px">';

  // Row 1: Rate + Window + Y-range (grid for alignment)
  h += '<div style="display:grid;grid-template-columns:auto 1fr auto 1fr auto 1fr;' +
    'gap:3px;align-items:center;margin-bottom:4px">';
  h += '<span style="font-size:8px;color:var(--t2)">Rate:</span>';
  h += '<select id="nano_stream_rate" style="' + _scanSel + ';font-size:8px">' +
    '<option value="100">100 Hz</option>' +
    '<option value="500">500 Hz</option>' +
    '<option value="1000" selected>1 kHz</option>' +
    '<option value="5000">5 kHz</option>' +
    '<option value="10000">10 kHz</option></select>';
  h += '<span style="font-size:8px;color:var(--t2)">Win:</span>';
  h += '<select id="nano_stream_window" style="' + _scanSel + ';font-size:8px">' +
    '<option value="1">1 s</option><option value="2">2 s</option>' +
    '<option value="5" selected>5 s</option><option value="10">10 s</option>' +
    '<option value="30">30 s</option></select>';
  h += '<span style="font-size:8px;color:var(--t2)">Y:</span>';
  h += '<select id="nano_stream_yrange" onchange="_nanoStreamSetYRange(this.value)" ' +
    'style="' + _scanSel + ';font-size:8px">' +
    '<option value="0" selected>Auto</option>' +
    '<option value="10">10 nm</option>' +
    '<option value="50">50 nm</option>' +
    '<option value="100">100 nm</option>' +
    '<option value="500">500 nm</option>' +
    '<option value="1000">1 um</option></select>';
  h += '</div>';

  // Row 2: Channels + Start / Stop
  h += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">';
  var _chColors = ['var(--ac)', 'var(--gn)', 'var(--am)'];
  var _chLabels = ['X', 'Y', 'Z'];
  for (var _ci = 0; _ci < 3; _ci++) {
    h += '<label style="display:flex;align-items:center;gap:2px;font-size:8px;color:' +
      _chColors[_ci] + ';cursor:pointer">' +
      '<input type="checkbox" id="nano_stream_ch_' + _ci + '" checked ' +
      'style="width:10px;height:10px;margin:0">' + _chLabels[_ci] + '</label>';
  }
  h += '<button id="nano_stream_start_btn" class="sb go" onclick="_nanoStreamStart()" ' +
    'style="padding:3px 12px;margin-left:auto;height:22px;white-space:nowrap">Start</button>';
  h += '<button id="nano_stream_stop_btn" class="sb stop" onclick="_nanoStreamStop()" ' +
    'style="padding:3px 12px;height:22px;white-space:nowrap;opacity:0.4" disabled>Stop</button>';
  h += '</div>';

  // Canvas chart
  h += '<div style="position:relative;width:100%;height:150px;background:#fff;' +
    'border:1px solid var(--b1);border-radius:3px;overflow:hidden">';
  h += '<canvas id="nano_stream_canvas" style="width:100%;height:100%"></canvas>';
  h += '</div>';

  // Status line
  h += '<div style="display:flex;align-items:center;justify-content:space-between;' +
    'margin-top:3px;font-size:7px;color:var(--t3)">';
  h += '<span id="nano_stream_status">Idle</span>';
  h += '<span id="nano_stream_mode"></span>';
  h += '<span id="nano_stream_stats"></span>';
  h += '</div>';

  h += '</div>';  // end streaming section

  // --- Hardware Info (small text) ---
  h += '<div style="font-size:8px;color:var(--t3);line-height:1.5">' +
    'MCS2: 3ch piezo (X=ch0, Y=ch1, Z=ch2) via TCP bridge | ' +
    'PicoScale V2: 3ch laser interferometer | Range: +/-15 um</div>';

  pane.innerHTML = h;

  // Post-render updates
  _nanoUpdateStatusUI();
  _nanoUpdatePositionUI();
  _nanoUpdateScanUI();
  _nanoUpdateScanTotalInfo();
  _nanoStreamInitCanvas();

  // Attach scan input listeners
  var ids = ['nano_scan_n_fast', 'nano_scan_n_slow', 'nano_scan_dwell',
    'nano_scan_fast_start', 'nano_scan_fast_stop',
    'nano_scan_slow_start', 'nano_scan_slow_stop'];
  for (var j = 0; j < ids.length; j++) {
    var inp = document.getElementById(ids[j]);
    if (inp) inp.addEventListener('input', _nanoUpdateScanTotalInfo);
  }
}

// ===== Update scan total/time info =====
function _nanoUpdateScanTotalInfo() {
  var nFastEl = document.getElementById('nano_scan_n_fast');
  var nSlowEl = document.getElementById('nano_scan_n_slow');
  var dwellEl = document.getElementById('nano_scan_dwell');
  var infoEl = document.getElementById('nano_scan_total_info');
  if (!nFastEl || !nSlowEl || !dwellEl || !infoEl) return;

  var total = (parseInt(nFastEl.value, 10) || 0) * (parseInt(nSlowEl.value, 10) || 0);
  var estTime = total * (parseFloat(dwellEl.value) || 0);
  var timeStr = estTime >= 60 ? (estTime / 60).toFixed(1) + ' min' : estTime.toFixed(1) + ' s';
  infoEl.textContent = total + ' pts, ~' + timeStr + ' (dwell only)';
}

// ===== Streaming State & Ring Buffer =====
var _nanoStream = {
  active: false,
  rateHz: 1000,
  windowS: 5,
  channels: [0, 1, 2],
  yRangeNm: 0,   // 0=auto, else fixed range in nm (e.g. 50, 100, 500)
  // Ring buffer per channel: Float64Array, write pointer, count
  bufs: {},       // ch -> Float64Array
  bufSize: 0,
  writePtr: 0,
  sampleCount: 0,
  // Render
  rafId: null,
  lastRender: 0,
  canvasCtx: null,
  canvasW: 0,
  canvasH: 0
};

var _STREAM_CH_COLORS = ['#4db8ff', '#40d89a', '#ffb340'];

function _nanoStreamSetYRange(val) {
  _nanoStream.yRangeNm = parseInt(val, 10) || 0;
}

function _nanoStreamStart() {
  var rateEl = document.getElementById('nano_stream_rate');
  var winEl = document.getElementById('nano_stream_window');
  var rate = rateEl ? parseInt(rateEl.value, 10) : 1000;
  var win = winEl ? parseInt(winEl.value, 10) : 5;

  // Collect enabled channels
  var channels = [];
  for (var i = 0; i < 3; i++) {
    var cb = document.getElementById('nano_stream_ch_' + i);
    if (cb && cb.checked) channels.push(i);
  }
  if (channels.length === 0) channels = [0, 1, 2];

  _nanoStream.rateHz = rate;
  _nanoStream.windowS = win;
  _nanoStream.channels = channels;

  // Allocate ring buffers
  var bufSize = rate * win;
  if (bufSize > 300000) bufSize = 300000;
  _nanoStream.bufSize = bufSize;
  _nanoStream.writePtr = 0;
  _nanoStream.sampleCount = 0;
  _nanoStream.bufs = {};
  for (var c = 0; c < channels.length; c++) {
    _nanoStream.bufs[channels[c]] = new Float64Array(bufSize);
  }

  _nanoSend({
    action: 'nano_stream_start',
    rate_hz: rate,
    channels: channels
  });
}

function _nanoStreamStop() {
  _nanoSend({ action: 'nano_stream_stop' });
}

function _nanoStreamInitCanvas() {
  var canvas = document.getElementById('nano_stream_canvas');
  if (!canvas) return;

  // Use clientWidth (not getBoundingClientRect — UI guide 4-1, double-zoom prevention)
  var cw = canvas.parentElement.clientWidth || 400;
  var ch = canvas.parentElement.clientHeight || 100;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(cw * dpr);
  canvas.height = Math.round(ch * dpr);
  _nanoStream.canvasW = cw;
  _nanoStream.canvasH = ch;
  _nanoStream.canvasCtx = canvas.getContext('2d');
  _nanoStream.canvasCtx.scale(dpr, dpr);

  // Draw empty state
  _nanoStreamDrawEmpty();
}

function _nanoStreamDrawEmpty() {
  var ctx = _nanoStream.canvasCtx;
  if (!ctx) return;
  var w = _nanoStream.canvasW;
  var h = _nanoStream.canvasH;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = '#999';
  ctx.font = '9px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('No streaming data', w / 2, h / 2);
}

function _nanoStreamOnData(msg) {
  // Handle both direct and batch messages
  if (!_nanoStream.active) return;

  var channels = _nanoStream.channels;
  var bufSize = _nanoStream.bufSize;

  if (msg.type === 'nano_stream_data') {
    // Direct: single sample
    for (var c = 0; c < channels.length; c++) {
      var ch = channels[c];
      var buf = _nanoStream.bufs[ch];
      if (!buf) continue;
      var val = msg['ch' + ch];
      if (typeof val === 'number') {
        buf[_nanoStream.writePtr % bufSize] = val;
      }
    }
    _nanoStream.writePtr++;
    _nanoStream.sampleCount++;
  } else if (msg.type === 'nano_stream_batch') {
    // Batch: array of samples
    for (var c2 = 0; c2 < channels.length; c2++) {
      var ch2 = channels[c2];
      var buf2 = _nanoStream.bufs[ch2];
      if (!buf2) continue;
      var arr = msg['ch' + ch2];
      if (!arr || !arr.length) continue;
      for (var s = 0; s < arr.length; s++) {
        buf2[(_nanoStream.writePtr + s) % bufSize] = arr[s];
      }
    }
    var n = msg.n || 0;
    _nanoStream.writePtr += n;
    _nanoStream.sampleCount += n;
  }

  // Update stats
  var statsEl = document.getElementById('nano_stream_stats');
  if (statsEl) {
    var cnt = _nanoStream.sampleCount;
    var txt = cnt >= 1000 ? (cnt / 1000).toFixed(1) + 'k' : cnt;
    statsEl.textContent = 'Samples: ' + txt;
  }
}

function _nanoStreamOnStatus(msg) {
  var statusEl = document.getElementById('nano_stream_status');
  var modeEl = document.getElementById('nano_stream_mode');
  var startBtn = document.getElementById('nano_stream_start_btn');
  var stopBtn = document.getElementById('nano_stream_stop_btn');

  if (msg.type === 'nano_stream_started') {
    _nanoStream.active = true;
    if (statusEl) {
      statusEl.textContent = 'Streaming ' + msg.rate_hz + ' Hz';
      statusEl.style.color = 'var(--gn)';
    }
    if (modeEl) {
      modeEl.textContent = '(' + (msg.mode || 'direct') + ')';
    }
    if (startBtn) { startBtn.disabled = true; startBtn.style.opacity = '0.4'; }
    if (stopBtn) { stopBtn.disabled = false; stopBtn.style.opacity = '1'; }
    // Start render loop
    _nanoStreamStartRender();
  } else if (msg.type === 'nano_stream_stopped') {
    _nanoStream.active = false;
    if (statusEl) {
      statusEl.textContent = 'Stopped';
      statusEl.style.color = 'var(--t3)';
    }
    if (modeEl) modeEl.textContent = '';
    if (startBtn) { startBtn.disabled = false; startBtn.style.opacity = '1'; }
    if (stopBtn) { stopBtn.disabled = true; stopBtn.style.opacity = '0.4'; }
    // Stop render loop
    if (_nanoStream.rafId) {
      cancelAnimationFrame(_nanoStream.rafId);
      _nanoStream.rafId = null;
    }
  } else if (msg.type === 'nano_stream_error') {
    _nanoStream.active = false;
    if (statusEl) {
      statusEl.textContent = msg.error || 'Error';
      statusEl.style.color = 'var(--rd)';
    }
    if (startBtn) { startBtn.disabled = false; startBtn.style.opacity = '1'; }
    if (stopBtn) { stopBtn.disabled = true; stopBtn.style.opacity = '0.4'; }
  }
}

function _nanoStreamStartRender() {
  if (_nanoStream.rafId) cancelAnimationFrame(_nanoStream.rafId);

  function frame(ts) {
    if (!_nanoStream.active) return;
    // Throttle to ~30fps
    if (ts - _nanoStream.lastRender < 33) {
      _nanoStream.rafId = requestAnimationFrame(frame);
      return;
    }
    _nanoStream.lastRender = ts;
    _nanoStreamRender();
    _nanoStream.rafId = requestAnimationFrame(frame);
  }
  _nanoStream.rafId = requestAnimationFrame(frame);
}

// Nice tick step: returns a "round" step size for axis labels
function _niceStep(rawStep) {
  var exp = Math.floor(Math.log10(rawStep));
  var frac = rawStep / Math.pow(10, exp);
  var nice;
  if (frac <= 1.5) nice = 1;
  else if (frac <= 3.5) nice = 2;
  else if (frac <= 7.5) nice = 5;
  else nice = 10;
  return nice * Math.pow(10, exp);
}

function _nanoStreamRender() {
  var ctx = _nanoStream.canvasCtx;
  if (!ctx) return;
  var w = _nanoStream.canvasW;
  var h = _nanoStream.canvasH;
  var channels = _nanoStream.channels;
  var bufSize = _nanoStream.bufSize;
  var wp = _nanoStream.writePtr;
  var count = Math.min(wp, bufSize);

  // White background
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);

  // Plot area with margins for axis labels
  var pad = { t: 12, r: 12, b: 20, l: 56 };
  var pw = w - pad.l - pad.r;
  var ph = h - pad.t - pad.b;

  if (count < 2 || pw < 10 || ph < 10) return;

  // Find data Y range across all visible channels
  var dataMin = Infinity, dataMax = -Infinity;
  for (var c = 0; c < channels.length; c++) {
    var buf = _nanoStream.bufs[channels[c]];
    if (!buf) continue;
    for (var i = 0; i < count; i++) {
      var idx = (wp - count + i) % bufSize;
      if (idx < 0) idx += bufSize;
      var v = buf[idx];
      if (v < dataMin) dataMin = v;
      if (v > dataMax) dataMax = v;
    }
  }
  if (dataMin === dataMax) { dataMin -= 1; dataMax += 1; }

  // Determine Y axis range
  var yMin, yMax;
  var fixedRange = _nanoStream.yRangeNm;
  if (fixedRange > 0) {
    // Fixed range: center around data mean
    var mid = (dataMin + dataMax) / 2;
    yMin = mid - fixedRange / 2;
    yMax = mid + fixedRange / 2;
  } else {
    // Auto: 10% margin, snap to nice round numbers
    var rawRange = dataMax - dataMin;
    var margin = rawRange * 0.15;
    yMin = dataMin - margin;
    yMax = dataMax + margin;
  }
  var yRange = yMax - yMin;

  // Compute nice Y tick step
  var nTicksTarget = 5;
  var rawTickStep = yRange / nTicksTarget;
  var tickStep = _niceStep(rawTickStep);
  var tickStart = Math.ceil(yMin / tickStep) * tickStep;

  // Draw grid lines at nice tick positions
  ctx.strokeStyle = '#e0e0e0';
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  for (var tv = tickStart; tv <= yMax + tickStep * 0.01; tv += tickStep) {
    var gy = Math.round(pad.t + ph - ((tv - yMin) / yRange) * ph) + 0.5;
    if (gy < pad.t || gy > pad.t + ph) continue;
    ctx.moveTo(pad.l, gy);
    ctx.lineTo(pad.l + pw, gy);
  }
  ctx.stroke();

  // Plot border
  ctx.strokeStyle = '#bbb';
  ctx.lineWidth = 1;
  ctx.strokeRect(pad.l + 0.5, pad.t + 0.5, pw, ph);

  // Y-axis labels (integer where possible)
  ctx.fillStyle = '#333';
  ctx.font = '8px monospace';
  ctx.textAlign = 'right';
  for (var tv2 = tickStart; tv2 <= yMax + tickStep * 0.01; tv2 += tickStep) {
    var yPx = Math.round(pad.t + ph - ((tv2 - yMin) / yRange) * ph);
    if (yPx < pad.t - 2 || yPx > pad.t + ph + 2) continue;
    // Integer if tick step >= 1, else 1 decimal
    var label = (tickStep >= 1) ? Math.round(tv2).toString() : tv2.toFixed(1);
    ctx.fillText(label, pad.l - 4, yPx + 3);
  }

  // X-axis: time labels
  ctx.fillStyle = '#555';
  ctx.font = '8px monospace';
  ctx.textAlign = 'center';
  var totalTimeS = count / _nanoStream.rateHz;
  ctx.fillText('0', pad.l, pad.t + ph + 13);
  ctx.fillText(totalTimeS.toFixed(1) + 's', pad.l + pw, pad.t + ph + 13);
  if (pw > 140) {
    ctx.fillText((totalTimeS / 2).toFixed(1), pad.l + pw / 2, pad.t + ph + 13);
  }

  // Y-axis unit label
  ctx.save();
  ctx.fillStyle = '#888';
  ctx.font = '8px monospace';
  ctx.translate(8, pad.t + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillText('nm', 0, 0);
  ctx.restore();

  // Draw each channel line (1.5px for clarity)
  var step = Math.max(1, Math.floor(count / pw));

  for (var ch = 0; ch < channels.length; ch++) {
    var chIdx = channels[ch];
    var chBuf = _nanoStream.bufs[chIdx];
    if (!chBuf) continue;

    ctx.strokeStyle = _STREAM_CH_COLORS[chIdx] || '#333';
    ctx.lineWidth = 1.5;
    ctx.beginPath();

    var first = true;
    for (var si = 0; si < count; si += step) {
      var bIdx = (wp - count + si) % bufSize;
      if (bIdx < 0) bIdx += bufSize;
      var val = chBuf[bIdx];
      var px = pad.l + (si / count) * pw;
      var py = pad.t + ph - ((val - yMin) / yRange) * ph;
      // Clamp to plot area
      if (py < pad.t) py = pad.t;
      if (py > pad.t + ph) py = pad.t + ph;
      if (first) { ctx.moveTo(px, py); first = false; }
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // Legend (top-right inside plot area, with last value)
  ctx.font = '9px monospace';
  ctx.textAlign = 'right';
  for (var li = 0; li < channels.length; li++) {
    var lch = channels[li];
    var lx = pad.l + pw - 4;
    var ly = pad.t + 10 + li * 13;
    // Get last value for this channel
    var lastVal = 0;
    var lBuf = _nanoStream.bufs[lch];
    if (lBuf && wp > 0) {
      var lIdx = (wp - 1) % bufSize;
      if (lIdx < 0) lIdx += bufSize;
      lastVal = lBuf[lIdx];
    }
    var ltxt = _NANO_AXES[lch].label + ' ' + Math.round(lastVal);
    var lm = ctx.measureText(ltxt);
    // Background box
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.fillRect(lx - lm.width - 3, ly - 9, lm.width + 6, 13);
    ctx.fillStyle = _STREAM_CH_COLORS[lch] || '#333';
    ctx.fillText(ltxt, lx, ly);
  }
}

// ===== Register handler in scanWs onmessage chain =====
(function() {
  var _hookAttempts = 0;
  var _hookTimer = setInterval(function() {
    _hookAttempts++;
    if (_hookAttempts > 60) { clearInterval(_hookTimer); return; }
    if (typeof EPICS_STATE === 'undefined') return;
    if (!EPICS_STATE.scanWs) return;

    // Hook onmessage to route nano messages
    function _nanoHookWs(ws) {
      if (!ws || (ws.onmessage && ws.onmessage._nanoHooked)) return;
      var prev = ws.onmessage;
      var hooked = function(e) {
        if (typeof prev === 'function') {
          try { prev.call(ws, e); } catch (err) { /* */ }
        }
        try {
          var msg = JSON.parse(e.data);
          _handleNanoMessage(msg);
        } catch (err2) { /* */ }
      };
      hooked._nanoHooked = true;
      ws.onmessage = hooked;
    }
    _nanoHookWs(EPICS_STATE.scanWs);
    clearInterval(_hookTimer);

    // Watch for WS reconnections — re-hook if needed
    var _watchTimer = setInterval(function() {
      if (!EPICS_STATE.scanWs) return;
      // Clear stale "WS not connected" message when scan WS is open
      if (EPICS_STATE.scanWs.readyState === WebSocket.OPEN) {
        var _wsEl = document.getElementById('nano_ws_status');
        if (_wsEl && _wsEl.textContent.indexOf('not connected') >= 0) _wsEl.textContent = '';
      }
      _nanoHookWs(EPICS_STATE.scanWs);
    }, 3000);
  }, 500);
})();

// ===== Register with switchTab =====
(function() {
  var _origSwitchTab = typeof switchTab === 'function' ? switchTab : null;
  window.switchTab = function(id) {
    if (typeof _origSwitchTab === 'function') {
      try { _origSwitchTab(id); } catch (e) { /* */ }
    }
    if (id === 'scanner' && typeof renderScannerTab === 'function') {
      renderScannerTab();
    }
  };
})();

// ===== Scan Type Switcher =====
window._nanoScanTypeChanged = function() {
  var sel = document.getElementById('nano_scan_type');
  var type = sel ? sel.value : 'step2d';
  var slowRow = document.getElementById('nano_scan_slow_axis') ?
    document.getElementById('nano_scan_slow_axis').parentElement : null;
  var hdr = document.getElementById('nano_scan_grid_hdr');
  // Show/hide slow axis row for 1D scans
  if (slowRow) slowRow.style.display = (type === 'fly1d') ? 'none' : '';
  // Update labels for Fermat
  var fastLabel = slowRow ? slowRow.previousElementSibling : null;
  if (fastLabel && fastLabel.querySelector && fastLabel.querySelector('label')) {
    fastLabel.querySelector('label').textContent = (type === 'fermat') ? 'Range:' : 'Fast:';
  }
};

// ===== 2D Scan Heatmap Rendering =====
var _nanoHeatmapData = null;

window._nanoHeatmapUpdate = function(data, nFast, nSlow) {
  var wrap = document.getElementById('nano_scan_heatmap_wrap');
  var canvas = document.getElementById('nano_scan_heatmap');
  if (!wrap || !canvas) return;
  wrap.style.display = '';
  _nanoHeatmapData = { values: data, nFast: nFast, nSlow: nSlow };
  var ctx = canvas.getContext('2d');
  var w = canvas.parentElement.clientWidth;
  var h = canvas.parentElement.clientHeight || w;
  canvas.width = w; canvas.height = h;
  var min = Infinity, max = -Infinity;
  for (var i = 0; i < data.length; i++) {
    if (data[i] < min) min = data[i];
    if (data[i] > max) max = data[i];
  }
  var range = max - min || 1;
  var cw = w / nFast, ch = h / nSlow;
  for (var sy = 0; sy < nSlow; sy++) {
    for (var sx = 0; sx < nFast; sx++) {
      var idx = sy * nFast + sx;
      var v = (idx < data.length) ? (data[idx] - min) / range : 0;
      // Viridis-like: dark purple → blue → green → yellow
      var r = Math.round(255 * Math.min(1, Math.max(0, 1.5 * v - 0.5)));
      var g = Math.round(255 * Math.min(1, Math.max(0, v < 0.5 ? 2 * v : 1)));
      var b = Math.round(255 * Math.min(1, Math.max(0, v < 0.5 ? 0.5 + v : 1.5 - v)));
      ctx.fillStyle = 'rgb(' + r + ',' + g + ',' + b + ')';
      ctx.fillRect(sx * cw, sy * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }
  var minEl = document.getElementById('nano_hm_min');
  var maxEl = document.getElementById('nano_hm_max');
  if (minEl) minEl.textContent = min.toFixed(1);
  if (maxEl) maxEl.textContent = max.toFixed(1);
};

// Hook scan progress to update heatmap incrementally
var _origNanoUpdateScanUI = _nanoUpdateScanUI;
_nanoUpdateScanUI = function() {
  _origNanoUpdateScanUI();
  // Show heatmap wrap when scanning starts
  var wrap = document.getElementById('nano_scan_heatmap_wrap');
  if (wrap && NANO_SCANNER.scanning) wrap.style.display = '';
};

// ===== Mock Scan Mode (for when hardware is disconnected) =====
window._nanoMockScan = function() {
  var el = function(id) { return document.getElementById(id); };
  var nFast = parseInt((el('nano_scan_n_fast') || {}).value, 10) || 21;
  var nSlow = parseInt((el('nano_scan_n_slow') || {}).value, 10) || 21;
  var total = nFast * nSlow;
  var data = [];
  // Generate mock Gaussian peak data
  var cx = nFast / 2, cy = nSlow / 2;
  var sx = nFast / 5, sy = nSlow / 5;
  for (var iy = 0; iy < nSlow; iy++) {
    for (var ix = 0; ix < nFast; ix++) {
      var dx = (ix - cx) / sx, dy = (iy - cy) / sy;
      data.push(1000 * Math.exp(-0.5 * (dx * dx + dy * dy)) + 50 * Math.random());
    }
  }
  // Simulate progressive scan
  NANO_SCANNER.scanning = true;
  NANO_SCANNER.scanProgress = 0;
  NANO_SCANNER.scanTotal = total;
  _nanoUpdateScanUI();
  var step = 0;
  var partialData = [];
  var mockTimer = setInterval(function() {
    var batch = Math.min(nFast, total - step);
    for (var b = 0; b < batch; b++) {
      partialData.push(data[step + b]);
    }
    step += batch;
    NANO_SCANNER.scanProgress = step;
    _nanoUpdateScanUI();
    _nanoHeatmapUpdate(partialData, nFast, Math.ceil(step / nFast));
    if (step >= total) {
      clearInterval(mockTimer);
      NANO_SCANNER.scanning = false;
      _nanoUpdateScanUI();
      _nanoHeatmapUpdate(data, nFast, nSlow);
    }
  }, 50);
};

// Override _nanoScanStart to fall back to mock when disconnected
var _origNanoScanStart = _nanoScanStart;
_nanoScanStart = function() {
  if (NANO_SCANNER.connected) {
    _origNanoScanStart();
  } else {
    // Mock mode: simulate scan locally
    if (typeof log === 'function') log('info', 'Nano: starting mock scan (hardware not connected)');
    _nanoMockScan();
  }
};

// Enable Start button even when disconnected (mock mode)
var _origNanoUpdateScanUI2 = _nanoUpdateScanUI;
_nanoUpdateScanUI = function() {
  _origNanoUpdateScanUI2();
  var startBtn = document.getElementById('nano_scan_start_btn');
  if (startBtn && !NANO_SCANNER.scanning) {
    startBtn.disabled = false;
    startBtn.style.opacity = '1';
    if (!NANO_SCANNER.connected) {
      startBtn.textContent = 'Mock Scan';
    } else {
      startBtn.textContent = 'Start Scan';
    }
  }
};

console.log('[V4.36] Nano scanner panel ready (with scan heatmap + mock mode)');

// ESM bridge: expose module-scoped vars to globalThis
if(typeof NANO_SCANNER!=="undefined")globalThis.NANO_SCANNER=NANO_SCANNER;
if(typeof _NANO_AXES!=="undefined")globalThis._NANO_AXES=_NANO_AXES;
if(typeof _STREAM_CH_COLORS!=="undefined")globalThis._STREAM_CH_COLORS=_STREAM_CH_COLORS;
if(typeof renderScannerTab!=="undefined")globalThis.renderScannerTab=renderScannerTab;
if(typeof _handleNanoMessage!=="undefined")globalThis._handleNanoMessage=_handleNanoMessage;
if(typeof _nanoConnect!=="undefined")globalThis._nanoConnect=_nanoConnect;
if(typeof _nanoDisconnect!=="undefined")globalThis._nanoDisconnect=_nanoDisconnect;
if(typeof _nanoIFMPulseTimer!=="undefined")globalThis._nanoIFMPulseTimer=_nanoIFMPulseTimer;
if(typeof _nanoJog!=="undefined")globalThis._nanoJog=_nanoJog;
if(typeof _nanoMoveAbs!=="undefined")globalThis._nanoMoveAbs=_nanoMoveAbs;
if(typeof _nanoScanAbort!=="undefined")globalThis._nanoScanAbort=_nanoScanAbort;
if(typeof _nanoScanStart!=="undefined")globalThis._nanoScanStart=_nanoScanStart;
if(typeof _nanoScanTypeChanged!=="undefined")globalThis._nanoScanTypeChanged=_nanoScanTypeChanged;
if(typeof _nanoHeatmapUpdate!=="undefined")globalThis._nanoHeatmapUpdate=_nanoHeatmapUpdate;
if(typeof _nanoMockScan!=="undefined")globalThis._nanoMockScan=_nanoMockScan;
if(typeof _nanoSend!=="undefined")globalThis._nanoSend=_nanoSend;
if(typeof _nanoSendWarnTime!=="undefined")globalThis._nanoSendWarnTime=_nanoSendWarnTime;
if(typeof _nanoSetPollRate!=="undefined")globalThis._nanoSetPollRate=_nanoSetPollRate;
if(typeof _nanoStartPoll!=="undefined")globalThis._nanoStartPoll=_nanoStartPoll;
if(typeof _nanoStop!=="undefined")globalThis._nanoStop=_nanoStop;
if(typeof _nanoStopAll!=="undefined")globalThis._nanoStopAll=_nanoStopAll;
if(typeof _nanoStopPoll!=="undefined")globalThis._nanoStopPoll=_nanoStopPoll;
if(typeof _nanoStream!=="undefined")globalThis._nanoStream=_nanoStream;
if(typeof _nanoStreamDrawEmpty!=="undefined")globalThis._nanoStreamDrawEmpty=_nanoStreamDrawEmpty;
if(typeof _nanoStreamInitCanvas!=="undefined")globalThis._nanoStreamInitCanvas=_nanoStreamInitCanvas;
if(typeof _nanoStreamOnData!=="undefined")globalThis._nanoStreamOnData=_nanoStreamOnData;
if(typeof _nanoStreamOnStatus!=="undefined")globalThis._nanoStreamOnStatus=_nanoStreamOnStatus;
if(typeof _nanoStreamRender!=="undefined")globalThis._nanoStreamRender=_nanoStreamRender;
if(typeof _nanoStreamSetYRange!=="undefined")globalThis._nanoStreamSetYRange=_nanoStreamSetYRange;
if(typeof _nanoStreamStart!=="undefined")globalThis._nanoStreamStart=_nanoStreamStart;
if(typeof _nanoStreamStartRender!=="undefined")globalThis._nanoStreamStartRender=_nanoStreamStartRender;
if(typeof _nanoStreamStop!=="undefined")globalThis._nanoStreamStop=_nanoStreamStop;
if(typeof _nanoUpdatePositionUI!=="undefined")globalThis._nanoUpdatePositionUI=_nanoUpdatePositionUI;
if(typeof _nanoUpdateScanTotalInfo!=="undefined")globalThis._nanoUpdateScanTotalInfo=_nanoUpdateScanTotalInfo;
if(typeof _nanoUpdateScanUI!=="undefined")globalThis._nanoUpdateScanUI=_nanoUpdateScanUI;
if(typeof _nanoUpdateStatusUI!=="undefined")globalThis._nanoUpdateStatusUI=_nanoUpdateStatusUI;
if(typeof _niceStep!=="undefined")globalThis._niceStep=_niceStep;
if(typeof switchTab!=="undefined")globalThis.switchTab=switchTab;
