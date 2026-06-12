'use strict';
// ===== bluesky/07_server_history.js — Server Scan History =====
// @module bluesky/07_server_history
// @exports SERVER_HISTORY, _handleH5Download, _handleHistoryResponse, _handleScanDataResponse, _histApplyFilter, _histDownloadH5, _histNext, _histPrev, _histRefresh, _histRowClick, _installHistorySection, _renderServerHistory, fetchScanHistory
// Extracted from 14_v435_final.js (DDD Phase 5f)
// Provides: SERVER_HISTORY state, fetchScanHistory, renderBlueskyTab wrapper (history section),
//   connectScan wrapper (history response handler)

(function() {

var SERVER_HISTORY = {
  items: [],
  total: 0,
  loaded: false,
  offset: 0,
  limit: 20,
  planFilter: ''
};
window.SERVER_HISTORY = SERVER_HISTORY;

/* -- Request scan history from server -- */
window.fetchScanHistory = function(limit, offset, planFilter) {
  var ws = typeof EPICS_STATE !== 'undefined' ? EPICS_STATE.scanWs : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    log('warn', 'Scan WS not connected \u2014 cannot fetch history');
    return;
  }
  var msg = { action: 'list_history', limit: limit || 50, offset: offset || 0 };
  if (planFilter) msg.plan_filter = planFilter;
  ws.send(JSON.stringify(msg));
};

/* -- Handle history response -- */
function _handleHistoryResponse(msg) {
  if (msg.type !== 'scan_history') return;
  SERVER_HISTORY.items = msg.history || [];
  SERVER_HISTORY.total = msg.total || 0;
  SERVER_HISTORY.loaded = true;
  _renderServerHistory();
}

/* -- Render server history in Bluesky tab -- */
function _renderServerHistory() {
  var container = document.getElementById('bsServerHistory');
  if (!container) return;

  if (!SERVER_HISTORY.loaded || SERVER_HISTORY.items.length === 0) {
    container.innerHTML = '<div style="font-size:9px;color:var(--t3);padding:8px;text-align:center">' +
      (SERVER_HISTORY.loaded ? 'No scans saved on server.' : 'Loading server history...') + '</div>';
    return;
  }

  var h = '';

  /* -- Header: filter + pagination -- */
  h += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;flex-wrap:wrap">';
  h += '<span style="font-size:8px;color:var(--t3)">History (' + SERVER_HISTORY.total + ')</span>';

  /* Plan type filter */
  h += '<select id="bsHistFilter" style="font-size:8px;padding:1px 4px;background:var(--s2);color:var(--t1);border:1px solid var(--b0);border-radius:3px" onchange="window._histApplyFilter(this.value)">';
  h += '<option value="">All plans</option>';
  var planTypes = ['energy_scan', 'xafs_scan', 'xanes_scan', 'raster_scan', 'alignment_scan',
                   'beam_check', 'fly_scan', 'line_scan', 'fermat_scan', 'rel_raster_scan'];
  planTypes.forEach(function(p) {
    var sel = SERVER_HISTORY.planFilter === p ? ' selected' : '';
    h += '<option value="' + p + '"' + sel + '>' + p + '</option>';
  });
  h += '</select>';

  /* Refresh button */
  h += '<button class="sb" style="font-size:8px;padding:1px 6px" onclick="window._histRefresh()">Refresh</button>';

  /* Pagination */
  h += '<span style="flex:1"></span>';
  var hasPrev = SERVER_HISTORY.offset > 0;
  var hasNext = (SERVER_HISTORY.offset + SERVER_HISTORY.limit) < SERVER_HISTORY.total;
  h += '<button class="sb" style="font-size:8px;padding:1px 4px' + (hasPrev ? '' : ';opacity:0.3') + '"'
    + (hasPrev ? ' onclick="window._histPrev()"' : ' disabled') + '>&lt;</button>';
  var pageStart = SERVER_HISTORY.offset + 1;
  var pageEnd = Math.min(SERVER_HISTORY.offset + SERVER_HISTORY.items.length, SERVER_HISTORY.total);
  h += '<span style="font-size:7px;color:var(--t3);font-family:var(--mn)">' + pageStart + '-' + pageEnd + '</span>';
  h += '<button class="sb" style="font-size:8px;padding:1px 4px' + (hasNext ? '' : ';opacity:0.3') + '"'
    + (hasNext ? ' onclick="window._histNext()"' : ' disabled') + '>&gt;</button>';
  h += '</div>';

  /* -- Scan rows -- */
  SERVER_HISTORY.items.forEach(function(scan, idx) {
    var isOk = scan.status === 'success';
    var icon = isOk ? '\u2713' : '\u2717';
    var color = isOk ? 'var(--gn)' : 'var(--rd)';
    var time = scan.start_time ? scan.start_time.split('T')[0] + ' ' + (scan.start_time.split('T')[1] || '').slice(0, 5) : '';
    var energy = scan.energy_keV ? scan.energy_keV.toFixed(1) + 'keV' : '';
    var uid = scan.uid || '';

    h += '<div class="bsHistRow" style="display:flex;align-items:center;gap:4px;padding:3px 2px;border-bottom:1px solid var(--b0);cursor:pointer" '
      + 'onclick="window._histRowClick(\'' + uid + '\')" '
      + 'onmouseover="this.style.background=\'var(--s2)\'" onmouseout="this.style.background=\'\'">';
    h += '<span style="color:' + color + ';font-size:9px;min-width:12px">' + icon + '</span>';
    h += '<span style="font-size:9px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + (scan.plan_name || '?') + '</span>';
    h += '<span style="font-size:8px;font-family:var(--mn);color:var(--t3)">' + (scan.num_points || 0) + 'pts</span>';
    if (energy) {
      h += '<span style="font-size:8px;font-family:var(--mn);color:var(--ac)">' + energy + '</span>';
    }
    h += '<span style="font-size:7px;font-family:var(--mn);color:var(--t3)">' + time + '</span>';
    if (scan.h5_file) {
      h += '<button class="sb" style="font-size:7px;padding:0 4px;color:var(--ac)" '
        + 'onclick="event.stopPropagation();window._histDownloadH5(\'' + uid + '\',\'' + scan.h5_file + '\')" '
        + 'title="Download ' + scan.h5_file + '">H5</button>';
    }
    h += '</div>';
  });

  container.innerHTML = h;
}

/* -- History pagination and filter controls -- */
window._histApplyFilter = function(val) {
  SERVER_HISTORY.planFilter = val;
  SERVER_HISTORY.offset = 0;
  fetchScanHistory(SERVER_HISTORY.limit, 0, val || undefined);
};

window._histRefresh = function() {
  fetchScanHistory(SERVER_HISTORY.limit, SERVER_HISTORY.offset,
                   SERVER_HISTORY.planFilter || undefined);
};

window._histPrev = function() {
  var newOff = Math.max(0, SERVER_HISTORY.offset - SERVER_HISTORY.limit);
  SERVER_HISTORY.offset = newOff;
  fetchScanHistory(SERVER_HISTORY.limit, newOff, SERVER_HISTORY.planFilter || undefined);
};

window._histNext = function() {
  var newOff = SERVER_HISTORY.offset + SERVER_HISTORY.limit;
  if (newOff < SERVER_HISTORY.total) {
    SERVER_HISTORY.offset = newOff;
    fetchScanHistory(SERVER_HISTORY.limit, newOff, SERVER_HISTORY.planFilter || undefined);
  }
};

/* -- Row click: request scan data from server -- */
window._histRowClick = function(uid) {
  if (!uid) return;
  var ws = typeof EPICS_STATE !== 'undefined' ? EPICS_STATE.scanWs : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    log('warn', 'Scan WS not connected');
    return;
  }
  ws.send(JSON.stringify({ action: 'get_scan_data', uid: uid }));
  log('info', 'Requesting scan data: ' + uid.slice(0, 8) + '...');
};

/* -- Handle scan data response -- */
function _handleScanDataResponse(msg) {
  if (msg.type !== 'scan_data') return;
  if (!msg.data || !msg.data.columns) {
    log('warn', 'No data in scan response');
    return;
  }
  /* Display in live scan popup using existing renderer */
  var points = [];
  var cols = msg.data.columns;
  var nPts = msg.data.n_points || 0;
  for (var i = 0; i < nPts; i++) {
    var pt = {};
    for (var c = 0; c < cols.length; c++) {
      var arr = msg.data.values[cols[c]];
      if (arr && arr.length > i) pt[cols[c]] = arr[i];
    }
    points.push(pt);
  }
  if (typeof updateBsLiveChart === 'function') {
    updateBsLiveChart(points, msg.plan_name || 'History');
  }
  log('info', 'Loaded scan data: ' + nPts + ' pts');
}

/* -- H5 download request -- */
window._histDownloadH5 = function(uid, filename) {
  var ws = typeof EPICS_STATE !== 'undefined' ? EPICS_STATE.scanWs : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    log('warn', 'Scan WS not connected');
    return;
  }
  ws.send(JSON.stringify({ action: 'download_h5', uid: uid, filename: filename }));
  log('info', 'Requesting H5 download: ' + filename);
};

/* -- Handle H5 download response (base64 encoded) -- */
function _handleH5Download(msg) {
  if (msg.type !== 'h5_download') return;
  if (!msg.data || !msg.filename) {
    log('warn', 'H5 download failed: ' + (msg.error || 'no data'));
    return;
  }
  /* Decode base64 and trigger browser download */
  var byteChars = atob(msg.data);
  var byteArr = new Uint8Array(byteChars.length);
  for (var i = 0; i < byteChars.length; i++) {
    byteArr[i] = byteChars.charCodeAt(i);
  }
  var blob = new Blob([byteArr], { type: 'application/x-hdf5' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = msg.filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  log('info', 'Downloaded: ' + msg.filename);
}

/* -- Install server history section into Bluesky tab -- */
function _installHistorySection() {
  /* Expose message handlers for scan WS dispatch */
  window._handleHistoryResponse = _handleHistoryResponse;
  window._handleScanDataResponse = _handleScanDataResponse;
  window._handleH5Download = _handleH5Download;
  log('info', '[' + APP_VTAG + '] Server scan history integration installed');
}

if (document.readyState === 'complete' || document.readyState === 'interactive') {
  setTimeout(_installHistorySection, 300);
} else {
  document.addEventListener('DOMContentLoaded', function() {
    setTimeout(_installHistorySection, 300);
  });
}

console.log('[' + APP_VTAG + '] Server history module loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof SERVER_HISTORY!=="undefined")globalThis.SERVER_HISTORY=SERVER_HISTORY;
if(typeof _handleH5Download!=="undefined")globalThis._handleH5Download=_handleH5Download;
if(typeof _handleHistoryResponse!=="undefined")globalThis._handleHistoryResponse=_handleHistoryResponse;
if(typeof _handleScanDataResponse!=="undefined")globalThis._handleScanDataResponse=_handleScanDataResponse;
if(typeof _histApplyFilter!=="undefined")globalThis._histApplyFilter=_histApplyFilter;
if(typeof _histDownloadH5!=="undefined")globalThis._histDownloadH5=_histDownloadH5;
if(typeof _histNext!=="undefined")globalThis._histNext=_histNext;
if(typeof _histPrev!=="undefined")globalThis._histPrev=_histPrev;
if(typeof _histRefresh!=="undefined")globalThis._histRefresh=_histRefresh;
if(typeof _histRowClick!=="undefined")globalThis._histRowClick=_histRowClick;
if(typeof _installHistorySection!=="undefined")globalThis._installHistorySection=_installHistorySection;
if(typeof _renderServerHistory!=="undefined")globalThis._renderServerHistory=_renderServerHistory;
if(typeof fetchScanHistory!=="undefined")globalThis.fetchScanHistory=fetchScanHistory;
