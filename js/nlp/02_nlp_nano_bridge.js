'use strict';
// ===== nlp/02_nlp_nano_bridge.js -- NLP → Nano Scanner Bridge =====
// @module nlp/02_nlp_nano_bridge
// @exports _nanoAxisCh, _nanoBridgeReady, nanoJog, nanoMoveTo, nanoScanAbort, nanoScanFly1D, nanoScanSpiral, nanoScanStep2D, nanoStatus, queryHardwareStatus
// Translates NLP action calls (window[fn](...args)) into nano_* WebSocket
// messages via _nanoSend() defined in ui/13_scanner_panel.js.
//
// Unit convention: NLP/user speaks µm, hardware speaks nm.
// Axis mapping: 'x'→0, 'y'→1, 'z'→2 (accepts both string and int).

// ===== Axis Helper =====
function _nanoAxisCh(axis) {
  if (typeof axis === 'number') return Math.max(0, Math.min(2, axis));
  var map = { x: 0, y: 1, z: 2 };
  return map[String(axis).toLowerCase()] !== undefined ? map[String(axis).toLowerCase()] : 0;
}

function _nanoBridgeReady() {
  if (typeof _nanoSend !== 'function') {
    if (typeof log === 'function') log('err', 'NanoBridge: _nanoSend not available');
    return false;
  }
  return true;
}

// ===== Scan Functions =====

// 2D step scan (raster) on nano scanner
// xRange_um, yRange_um: scan range in µm (symmetric around current pos)
// nx, ny: number of points per axis
// dwell_s: dwell time per point (seconds)
window.nanoScanStep2D = function(xRange_um, yRange_um, nx, ny, dwell_s) {
  if (!_nanoBridgeReady()) return;
  var xR = (xRange_um || 10) * 1000;  // µm → nm
  var yR = (yRange_um || 10) * 1000;
  _nanoSend({
    action: 'nano_scan_start',
    scan_type: 'step_2d',
    params: {
      fast_axis: 0,
      slow_axis: 1,
      fast_start: -xR / 2,
      fast_stop: xR / 2,
      n_fast: nx || 101,
      slow_start: -yR / 2,
      slow_stop: yR / 2,
      n_slow: ny || 101,
      dwell_s: dwell_s || 0.01
    }
  });
  if (typeof log === 'function') log('info', 'NanoBridge: step2D ' + xRange_um + 'x' + yRange_um + ' um, ' + nx + 'x' + ny + ' pts');
};

// 1D fly scan (continuous motion) on nano scanner
// axis: 'x','y','z' or 0,1,2
// range_um: scan range in µm (symmetric)
// nPoints: number of data points
// velocity: scan speed in µm/s
window.nanoScanFly1D = function(axis, range_um, nPoints, velocity) {
  if (!_nanoBridgeReady()) return;
  var ch = _nanoAxisCh(axis);
  var halfR = (range_um || 10) * 500;  // µm → nm half-range
  _nanoSend({
    action: 'nano_scan_start',
    scan_type: 'fly_1d',
    params: {
      axis: ch,
      start_nm: -halfR,
      stop_nm: halfR,
      n_points: nPoints || 200,
      velocity_nm_s: (velocity || 5) * 1000,  // µm/s → nm/s
      stream_rate_hz: 10000
    }
  });
  if (typeof log === 'function') log('info', 'NanoBridge: fly1D axis=' + ch + ' ' + range_um + ' um');
};

// Fermat spiral scan on nano scanner
// radius_um: max radius in µm
// dr_um: radial step in µm
// dwell_s: dwell time per point (seconds)
window.nanoScanSpiral = function(radius_um, dr_um, dwell_s) {
  if (!_nanoBridgeReady()) return;
  _nanoSend({
    action: 'nano_scan_start',
    scan_type: 'spiral',
    params: {
      x_axis: 0,
      y_axis: 1,
      x_center: 0.0,
      y_center: 0.0,
      radius_nm: (radius_um || 5) * 1000,
      dr_nm: (dr_um || 0.05) * 1000,
      dwell_s: dwell_s || 0.01
    }
  });
  if (typeof log === 'function') log('info', 'NanoBridge: spiral R=' + radius_um + ' um, dr=' + dr_um + ' um');
};

// ===== Move Functions =====

// Relative move (jog) on nano scanner
// axis: 'x','y','z' or 0,1,2
// delta_um: move distance in µm (positive = + direction)
window.nanoJog = function(axis, delta_um) {
  if (!_nanoBridgeReady()) return;
  var ch = _nanoAxisCh(axis);
  _nanoSend({
    action: 'nano_jog',
    ch: ch,
    delta_nm: (delta_um || 0) * 1000
  });
  if (typeof log === 'function') log('info', 'NanoBridge: jog ch=' + ch + ' delta=' + delta_um + ' um');
};

// Absolute move on nano scanner
// axis: 'x','y','z' or 0,1,2
// pos_um: target position in µm
window.nanoMoveTo = function(axis, pos_um) {
  if (!_nanoBridgeReady()) return;
  var ch = _nanoAxisCh(axis);
  _nanoSend({
    action: 'nano_move',
    ch: ch,
    pos_nm: (pos_um || 0) * 1000
  });
  if (typeof log === 'function') log('info', 'NanoBridge: moveTo ch=' + ch + ' pos=' + pos_um + ' um');
};

// ===== Status & Control =====

// Query nano scanner hardware status
window.nanoStatus = function() {
  if (!_nanoBridgeReady()) return;
  _nanoSend({ action: 'nano_status' });
  // Also display in chat if available
  if (typeof addChatMessage === 'function') {
    var s = NANO_SCANNER;
    var msg = '[Nano Scanner Status]\n';
    msg += 'Connected: ' + (s.connected ? 'Yes' : 'No') + '\n';
    msg += 'MCS2: ' + (s.mcs2_ok ? 'OK' : 'Disconnected') + '\n';
    msg += 'PicoScale: ' + (s.ps_ok ? 'OK' : 'Disconnected') + '\n';
    if (s.connected) {
      msg += 'Position (PicoScale): X=' + s.positions[0].toFixed(1) + ' nm, Y=' + s.positions[1].toFixed(1) + ' nm, Z=' + s.positions[2].toFixed(1) + ' nm\n';
      msg += 'Scanning: ' + (s.scanning ? 'Yes (' + s.scanProgress + '/' + s.scanTotal + ')' : 'No');
    }
    addChatMessage('system', msg);
  }
  if (typeof log === 'function') log('info', 'NanoBridge: status requested');
};

// Abort current nano scan
window.nanoScanAbort = function() {
  if (!_nanoBridgeReady()) return;
  _nanoSend({ action: 'nano_scan_abort' });
  if (typeof log === 'function') log('info', 'NanoBridge: scan abort requested');
};

// ===== Hardware Status Query =====
// Reads cached PV values and displays in chat.
// group: 'scanner'|'xbpm'|'kohzu'|'ring'|'all'
window.queryHardwareStatus = function(group) {
  group = (group || 'all').toLowerCase();
  var lines = [];

  // Scanner status
  if (group === 'scanner' || group === 'all') {
    var s = (typeof NANO_SCANNER !== 'undefined') ? NANO_SCANNER : null;
    lines.push('[Nano Scanner]');
    if (s) {
      lines.push('  Connected: ' + (s.connected ? 'Yes' : 'No'));
      lines.push('  MCS2: ' + (s.mcs2_ok ? 'OK' : 'Disconnected'));
      lines.push('  PicoScale: ' + (s.ps_ok ? 'OK' : 'Disconnected'));
      if (s.connected) {
        lines.push('  PicoScale X: ' + s.positions[0].toFixed(1) + ' nm');
        lines.push('  PicoScale Y: ' + s.positions[1].toFixed(1) + ' nm');
        lines.push('  PicoScale Z: ' + s.positions[2].toFixed(1) + ' nm');
        lines.push('  Scanning: ' + (s.scanning ? 'Yes (' + s.scanProgress + '/' + s.scanTotal + ')' : 'No'));
      }
    } else {
      lines.push('  Not available');
    }
  }

  // XBPM status
  if (group === 'xbpm' || group === 'all') {
    lines.push('[XBPM]');
    var _pvVal = function(pv) {
      if (typeof PV_REGISTRY !== 'undefined' && PV_REGISTRY[pv]) return PV_REGISTRY[pv].value;
      if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs[pv]) return EPICS_STATE.simIOC.pvs[pv].value;
      return null;
    };
    var x1 = _pvVal('BL10:XBPM1:X'), y1 = _pvVal('BL10:XBPM1:Y');
    var px = _pvVal('BL10:XBPM2:PosX:MeanValue_RBV'), py = _pvVal('BL10:XBPM2:PosY:MeanValue_RBV');
    var sum = _pvVal('BL10:XBPM2:SumAll:MeanValue_RBV');
    lines.push('  XBPM1: X=' + (x1 !== null ? x1.toFixed(4) : 'N/A') + ', Y=' + (y1 !== null ? y1.toFixed(4) : 'N/A'));
    lines.push('  XBPM2 Pos: X=' + (px !== null ? px.toExponential(2) : 'N/A') + ', Y=' + (py !== null ? py.toExponential(2) : 'N/A'));
    lines.push('  XBPM2 Sum: ' + (sum !== null ? sum.toExponential(2) : 'N/A'));
  }

  // KOHZU stage status
  if (group === 'kohzu' || group === 'all') {
    lines.push('[KOHZU Stage]');
    var _mVal = function(gid, mid) {
      if (typeof MOTORS !== 'undefined' && MOTORS[gid]) {
        var arr = Array.isArray(MOTORS[gid]) ? MOTORS[gid] : Object.values(MOTORS[gid]);
        for (var i = 0; i < arr.length; i++) {
          if (arr[i] && arr[i].id === mid) return arr[i].value;
        }
      }
      return null;
    };
    var cx = _mVal('sample', 'sample_cx'), cy = _mVal('sample', 'sample_cy'), cz = _mVal('sample', 'sample_cz');
    lines.push('  CX: ' + (cx !== null ? cx.toFixed(4) + ' mm' : 'N/A'));
    lines.push('  CY: ' + (cy !== null ? cy.toFixed(4) + ' mm' : 'N/A'));
    lines.push('  CZ: ' + (cz !== null ? cz.toFixed(4) + ' mm' : 'N/A'));
  }

  // Ring status
  if (group === 'ring' || group === 'all') {
    lines.push('[Storage Ring]');
    var _pvVal2 = function(pv) {
      if (typeof PV_REGISTRY !== 'undefined' && PV_REGISTRY[pv]) return PV_REGISTRY[pv].value;
      if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs[pv]) return EPICS_STATE.simIOC.pvs[pv].value;
      return null;
    };
    var cur = _pvVal2('BL10:RING:Current'), eng = _pvVal2('BL10:RING:Energy'), lt = _pvVal2('BL10:RING:Lifetime');
    lines.push('  Current: ' + (cur !== null ? cur.toFixed(1) + ' mA' : 'N/A'));
    lines.push('  Energy: ' + (eng !== null ? eng.toFixed(1) + ' GeV' : 'N/A'));
    lines.push('  Lifetime: ' + (lt !== null ? lt.toFixed(1) + ' h' : 'N/A'));
  }

  if (typeof addChatMessage === 'function') {
    addChatMessage('system', lines.join('\n'));
  }
  if (typeof log === 'function') log('info', 'NanoBridge: queryHardwareStatus(' + group + ')');
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _nanoAxisCh!=="undefined")globalThis._nanoAxisCh=_nanoAxisCh;
if(typeof _nanoBridgeReady!=="undefined")globalThis._nanoBridgeReady=_nanoBridgeReady;
if(typeof nanoJog!=="undefined")globalThis.nanoJog=nanoJog;
if(typeof nanoMoveTo!=="undefined")globalThis.nanoMoveTo=nanoMoveTo;
if(typeof nanoScanAbort!=="undefined")globalThis.nanoScanAbort=nanoScanAbort;
if(typeof nanoScanFly1D!=="undefined")globalThis.nanoScanFly1D=nanoScanFly1D;
if(typeof nanoScanSpiral!=="undefined")globalThis.nanoScanSpiral=nanoScanSpiral;
if(typeof nanoScanStep2D!=="undefined")globalThis.nanoScanStep2D=nanoScanStep2D;
if(typeof nanoStatus!=="undefined")globalThis.nanoStatus=nanoStatus;
if(typeof queryHardwareStatus!=="undefined")globalThis.queryHardwareStatus=queryHardwareStatus;
