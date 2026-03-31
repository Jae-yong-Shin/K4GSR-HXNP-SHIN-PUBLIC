'use strict';
// ===== measurement/01_scan_control.js — Scan Control (start/stop/finish, colormap, CSV export) =====
// @module measurement/01_scan_control
// @exports cmpChart, exportCSV, hc, measChart, scanTimer, stopScan, trendChart, trendPV
// Extracted from 09_scan_init.js (DDD Phase)
// NOTE: updChart(tp) lives in ui/07_meas_chart.js — do NOT duplicate here

var scanTimer = null;
var measChart = null;
var cmpChart = null;
var trendPV = 'BL10:IVU:Gap';
var trendChart = null;

// startScan: canonical definition in detector/02_sdd.js (v419 with live popup)

function stopScan() {
  state.scanning = false;
  if (scanTimer) { clearTimeout(scanTimer); scanTimer = null; }
  // Cancel server-side scan if running
  if (_measScanActive) {
    if (typeof _simSendCancel === 'function') {
      try { _simSendCancel(); } catch(e) {}
    }
    _measScanActive = false;
    _measScanTechnique = '';
  }
  document.getElementById('scanStatus').textContent = 'STOPPED';
  document.getElementById('scanStatus').style.color = 'var(--rd)';
}

// finishScan: canonical definition in detector/02_sdd.js (v420 with live popup update)

// Colormap helper: maps t in [0,1] to an RGB string
function hc(t) {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.25) {
    var s = t / 0.25;
    return 'rgb(0,' + (s * 255 | 0) + ',' + (128 + s * 127 | 0) + ')';
  }
  if (t < 0.5) {
    var s2 = (t - 0.25) / 0.25;
    return 'rgb(0,255,' + (255 - s2 * 128 | 0) + ')';
  }
  if (t < 0.75) {
    var s3 = (t - 0.5) / 0.25;
    return 'rgb(' + (s3 * 255 | 0) + ',255,0)';
  }
  var s4 = (t - 0.75) / 0.25;
  return 'rgb(255,' + (255 - s4 * 255 | 0) + ',0)';
}

// CSV Export
function exportCSV() {
  if (!state.scanData.length) { log('warn', 'No data'); return; }
  var t = document.getElementById('technique').value;
  var csv = '';
  if (t === 'xrd2d') {
    csv = 'X,Y,I\n';
    state.scanData.forEach(function(d) { csv += d.x + ',' + d.y + ',' + d.val + '\n'; });
  } else {
    var headers = { xanes: 'E_eV,mu', xrd: '2Theta,I', xrf: 'E_keV,Cts' };
    csv = (headers[t] || 'X,Y') + '\n';
    state.scanData.forEach(function(d) { csv += d.x + ',' + d.y + '\n'; });
  }
  var a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = '4GSR_ID10_' + t + '.csv';
  a.click();
  log('info', 'Exported ' + t + ' CSV');
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof cmpChart!=="undefined")globalThis.cmpChart=cmpChart;
if(typeof exportCSV!=="undefined")globalThis.exportCSV=exportCSV;
if(typeof hc!=="undefined")globalThis.hc=hc;
if(typeof measChart!=="undefined")globalThis.measChart=measChart;
if(typeof scanTimer!=="undefined")globalThis.scanTimer=scanTimer;
if(typeof stopScan!=="undefined")globalThis.stopScan=stopScan;
if(typeof trendChart!=="undefined")globalThis.trendChart=trendChart;
if(typeof trendPV!=="undefined")globalThis.trendPV=trendPV;
