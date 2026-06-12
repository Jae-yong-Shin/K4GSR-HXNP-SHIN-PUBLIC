'use strict';
// ===== bluesky/08_scan_results.js — BS Scan Results & PlanExecutor v420 =====
// @module bluesky/08_scan_results
// @exports _bsLiveResult, _bsLiveTechType, _getSavePrefix, _v420RenderToCanvas, v420DoneLive, v420FallbackChart, v420OpenLive, v420SaveAs, v420SaveCSV, v420SaveJSON, v420SavePNG, v420SaveResult, v420ShowResult, v420UpdateLive
// Resizable live popups for all plan types (no openModal),
// result viewing, save (PNG/JSON), PLAN_LIBRARY management

// Global state for live popup
var _bsLiveResult = null;    // last result data for save
var _bsLiveTechType = null;  // last tech type for re-render
// Each scan opens its OWN popup so results can be compared side by side instead
// of the previous one being replaced. _bsLivePopupId is the id of the popup that
// is currently receiving live updates; per-popup result data is stored on each
// popup element (._bsResult / ._bsTechType) so resize/save use that popup's own
// data, not the latest scan's.
var _bsLivePopupId = null;
var _bsPopupSeq = 0;

// Unified PlanExecutor — all plan types with live popups
(function() {
  var _chainedExec = PlanExecutor.prototype.execute;
  PlanExecutor.prototype.execute = async function() {
    var name = this.item.name, p = this.item.kwargs || {};
    var techType = 'generic';
    if (name === 'xrd_scan') techType = 'xrd';
    else if (name === 'xrf_scan') techType = 'xrf';
    else if (name === 'xrd_2d_map' || name === 'raster_scan' || name === 'rel_raster_scan' || name === 'fermat_scan') techType = 'xrd2d';
    else if (name === 'xanes_scan' || name === 'energy_scan' || name === 'adaptive_energy_scan') techType = 'xanes';
    else if (name === 'align_motor' || name === 'rel_alignment_scan' || name === 'auto_tune') techType = 'align';
    else if (name === 'fly_scan') techType = 'fly';
    else if (name === 'gap_optimize') techType = 'gap';
    else if (name === 'count') techType = 'count';

    var labels = {xanes:'XANES', xrd:'XRD', xrf:'XRF', xrd2d:'2D Map', align:'Alignment', fly:'Fly Scan', gap:'Gap Optimize', count:'Count', generic:'Scan'};
    v420OpenLive(name, techType, (labels[techType] || techType) + ' -- ' + name);

    var self = this, _origEmit = this.emitPoint.bind(this), _ec = 0;
    this.emitPoint = function(pt) { _origEmit(pt); _ec++;
      if (_ec % 15 === 0 || _ec < 5) v420UpdateLive(self.liveData, techType, _ec);
    };
    var _origProg = this.updateProgress.bind(this);
    this.updateProgress = function(pct) { _origProg(pct);
      var pg = document.getElementById(_bsLivePopupId + '_prog');
      if (pg) pg.style.width = pct.toFixed(0) + '%';
      var pc = document.getElementById(_bsLivePopupId + '_pct');
      if (pc) pc.textContent = pct.toFixed(0) + '%';
    };

    try {
      // All plans go through the chained executor (server engine or local MC alignment)
      // No local synthetic fallback — measurement plans require simulation server
      var result = await _chainedExec.call(this);
      v420DoneLive(self.liveData, techType, result);
      return result;
    } catch (e) {
      var info = document.getElementById(_bsLivePopupId + '_info');
      if (info) { info.textContent = 'ERROR: ' + e.message; info.style.color = 'var(--rd)'; }
      return { success: false, msg: e.message };
    }
  };
})();

// ============================================================
//  LIVE POPUP — _openExptPopup style (resizable, draggable)
// ============================================================

function v420OpenLive(planName, techType, title) {
  _bsLiveTechType = techType;
  _bsLiveResult = null;

  var popupId = 'bsLivePopup_' + (++_bsPopupSeq);
  _bsLivePopupId = popupId;
  // Previous popups are intentionally NOT removed -- each scan gets its own
  // window so two results can be compared side by side. Close via the X button.

  var is2D = (techType === 'xrd2d');
  var initW = is2D ? 520 : 580;
  var initH = is2D ? 500 : 420;

  // Cascade the position so a new popup does not perfectly cover the previous.
  var _casc = ((_bsPopupSeq - 1) % 8) * 28;
  var div = document.createElement('div');
  div.id = popupId;
  div._bsTechType = techType;   // per-popup data (resize/save use the popup's own)
  div._bsResult = null;
  div.style.cssText = 'position:fixed;left:' + (90 + _casc) + 'px;top:' + (50 + _casc) + 'px;width:' + initW + 'px;height:' + initH + 'px;' +
    'background:var(--bg);border:1px solid var(--b1,#3d5068);border-radius:4px;' +
    'box-shadow:0 4px 16px rgba(0,0,0,0.5);z-index:1000;display:flex;flex-direction:column';

  // Header (draggable)
  var hdr = document.createElement('div');
  hdr.id = popupId + '_hdr';
  hdr.style.cssText = 'flex:0 0 auto;background:var(--s1);padding:6px 10px;display:flex;justify-content:space-between;align-items:center;cursor:move;user-select:none;border-radius:4px 4px 0 0';
  hdr.innerHTML = '<span style="color:var(--ac);font:bold 11px var(--mn)">' + (title || 'Scan') + '</span>' +
    '<div style="display:flex;gap:4px;align-items:center">' +
      '<select id="' + popupId + '_saveSel" onchange="v420SaveAs(this.value,\'' + popupId + '\');this.selectedIndex=0" style="background:var(--s2);border:1px solid var(--b1);color:var(--t2);padding:2px 4px;border-radius:3px;cursor:pointer;font-size:9px;font-family:var(--mn)">' +
        '<option value="">Save...</option>' +
        '<option value="png">PNG Image</option>' +
        '<option value="csv">CSV Data</option>' +
        '<option value="json">JSON Data</option>' +
      '</select>' +
      '<button onclick="var _p=document.getElementById(\'' + popupId + '\');if(_p)_p.remove()" title="Close this result" style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:13px;padding:0 4px">X</button>' +
    '</div>';

  // Canvas body (flex fill)
  var body = document.createElement('div');
  body.style.cssText = 'flex:1;position:relative;overflow:hidden;min-height:0';
  var cvs = document.createElement('canvas');
  cvs.id = popupId + '_canvas';
  cvs.style.cssText = 'width:100%;height:100%;display:block';
  body.appendChild(cvs);

  // Footer (progress + info)
  var foot = document.createElement('div');
  foot.id = popupId + '_foot';
  foot.style.cssText = 'flex:0 0 auto;padding:5px 10px;border-top:1px solid var(--s2);background:var(--s1);border-radius:0 0 4px 4px';
  foot.innerHTML =
    '<div id="' + popupId + '_info" style="font-size:10px;color:var(--am);font-family:var(--mn);margin-bottom:4px">Scanning...</div>' +
    '<div style="display:flex;gap:6px;align-items:center">' +
      '<span id="' + popupId + '_pct" style="font-size:9px;font-family:var(--mn);color:var(--ac);min-width:30px">0%</span>' +
      '<div style="flex:1"><div class="prog-bar"><div class="prog-fill" id="' + popupId + '_prog"></div></div></div>' +
    '</div>';

  div.appendChild(hdr);
  div.appendChild(body);
  div.appendChild(foot);
  document.body.appendChild(div);

  // Make resizable + draggable
  if (typeof _makePopupResizable === 'function') {
    _makePopupResizable(div, {
      dragEl: hdr,
      minWidth: 380,
      minHeight: 300,
      onResize: function() {
        // During drag: arguments.length > 0 -> skip re-render (CSS stretches)
        // On mouseUp: arguments.length === 0 -> re-render at new size
        if (arguments.length > 0) return;
        var c = document.getElementById(popupId + '_canvas');
        if (!c || c.clientWidth === 0) return;
        var _dpr = window.devicePixelRatio || 1;
        c.width = Math.round(c.clientWidth * _dpr);
        c.height = Math.round(c.clientHeight * _dpr);
        var _ctx = c.getContext('2d');
        if (_ctx) _ctx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
        // Re-render with THIS popup's own data (not the latest scan's).
        if (div._bsResult) {
          _v420RenderToCanvas(c, div._bsResult.data, div._bsTechType, div._bsResult.mapData);
        }
      }
    });
  }
}

// ============================================================
//  UNIFIED RENDERER — handles 1D and 2D on any canvas
// ============================================================

function _v420RenderToCanvas(cv, data, techType, mapData) {
  if (!cv || cv.clientWidth === 0) return;
  // Set canvas buffer to CSS size × devicePixelRatio for HiDPI sharpness
  var dpr = window.devicePixelRatio || 1;
  var cw = cv.clientWidth, ch = cv.clientHeight;
  if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) {
    cv.width = Math.round(cw * dpr);
    cv.height = Math.round(ch * dpr);
    var ctx = cv.getContext('2d');
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  if (techType === 'xrd2d' && mapData && mapData.d && mapData.d.length > 0) {
    // 2D heatmap — use full canvas size
    if (typeof _drawHeatmap2D === 'function') {
      _drawHeatmap2D(cv, mapData.d, {
        x: mapData.xP, y: mapData.yP,
        xLabel: 'X (um)', yLabel: 'Y (um)',
        title: mapData.xP.length + 'x' + mapData.d.length + '/' + mapData.yP.length,
        width: cv.clientWidth, height: cv.clientHeight,
        showColorbar: true
      });
    }
  } else if (data && data.length > 1) {
    // 1D chart
    if (typeof renderScan1DPopup === 'function') {
      renderScan1DPopup(cv, data, techType);
    } else {
      v420FallbackChart(cv, data, techType);
    }
  }
}

// ============================================================
//  LIVE UPDATE + DONE + FALLBACK
// ============================================================

function v420UpdateLive(data, techType, count) {
  var cv = document.getElementById(_bsLivePopupId + '_canvas');
  if (!cv || !data || data.length < 2) return;
  // For 2D maps, row-level rendering is handled in v420Xrd2dMap directly
  if (techType === 'xrd2d') return;
  _v420RenderToCanvas(cv, data, techType, null);
  var info = document.getElementById(_bsLivePopupId + '_info');
  if (info) info.textContent = 'Scanning... ' + count + ' pts';
}

function v420DoneLive(data, techType, result) {
  // Store result for save + re-render on resize (globals kept for back-compat).
  _bsLiveResult = result || {};
  if (data) _bsLiveResult.data = data;
  _bsLiveTechType = techType;

  var popupId = _bsLivePopupId;
  // Freeze this scan's result ON its own popup so later resize/save use it, not
  // the next scan's data (each popup stays an independent, comparable result).
  var dv = document.getElementById(popupId);
  if (dv) { dv._bsResult = _bsLiveResult; dv._bsTechType = techType; }

  var cv = document.getElementById(popupId + '_canvas');
  if (cv) _v420RenderToCanvas(cv, data, techType, result ? result.mapData : null);

  var info = document.getElementById(popupId + '_info');
  if (info) {
    if (result && result.success) { info.textContent = 'Complete: ' + (result.msg || data.length + ' pts'); info.style.color = 'var(--gn)'; }
    else { info.textContent = 'Failed: ' + (result ? result.msg : '?'); info.style.color = 'var(--rd)'; }
  }
  var pg = document.getElementById(popupId + '_prog'); if (pg) pg.style.width = '100%';
  var pc = document.getElementById(popupId + '_pct'); if (pc) pc.textContent = result && result.success ? 'Done' : 'Fail';
}

function v420FallbackChart(cv, data, type) {
  if (!data || data.length < 2) return;
  var colors = {xanes:'#4db8ff', xrd:'#a08cff', xrf:'#e870a0'};
  if (typeof _drawChart1D === 'function') {
    _drawChart1D(cv, data, {
      color: colors[type] || '#4db8ff',
      barMode: type === 'xrf',
      title: data.length + ' pts'
    });
  }
}

// ============================================================
//  SAVE — PNG + JSON download
// ============================================================

/* Save dispatcher for dropdown (popupId identifies WHICH result window). */
function v420SaveAs(fmt, popupId) {
  if (!fmt) return;
  if (fmt === 'png') v420SavePNG(popupId);
  else if (fmt === 'csv') v420SaveCSV(popupId);
  else if (fmt === 'json') v420SaveJSON(popupId);
}
window.v420SaveAs = v420SaveAs;

/* Resolve a popup's OWN stored result/tech; fall back to the live popup/globals. */
function _bsResolve(popupId) {
  var d = popupId && document.getElementById(popupId);
  if (d && d._bsResult) return { id: popupId, result: d._bsResult, tech: d._bsTechType };
  var lp = _bsLivePopupId && document.getElementById(_bsLivePopupId);
  return { id: _bsLivePopupId || popupId,
           result: (lp && lp._bsResult) || _bsLiveResult,
           tech: (lp && lp._bsTechType) || _bsLiveTechType };
}

/* Legacy: save PNG + JSON */
function v420SaveResult() { v420SavePNG(); v420SaveJSON(); }

function _getSavePrefix(tech) {
  var ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return 'scan_' + (tech || _bsLiveTechType || 'result') + '_' + ts;
}

function v420SavePNG(popupId) {
  var r = _bsResolve(popupId);
  var cv = document.getElementById(r.id + '_canvas');
  if (!cv) return;
  try {
    var link = document.createElement('a');
    link.download = _getSavePrefix(r.tech) + '.png';
    link.href = cv.toDataURL('image/png');
    link.click();
  } catch (e) {
    console.warn('[v420] PNG save error:', e);
  }
}

function v420SaveJSON(popupId) {
  var r = _bsResolve(popupId);
  if (!r.result) return;
  try {
    var jsonData = {
      techType: r.tech,
      timestamp: _getSavePrefix(r.tech),
      msg: r.result.msg || '',
      data: r.result.data || [],
      mapData: r.result.mapData || null
    };
    var blob = new Blob([JSON.stringify(jsonData, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var link2 = document.createElement('a');
    link2.download = _getSavePrefix(r.tech) + '.json';
    link2.href = url;
    link2.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.warn('[v420] JSON save error:', e);
  }
}

function v420SaveCSV(popupId) {
  /* Export this popup's scan data (or LIVE_SCAN.data) as CSV */
  var _r = _bsResolve(popupId);
  var data = (_r.result && _r.result.data) ? _r.result.data : null;
  if (!data && typeof LIVE_SCAN !== 'undefined' && LIVE_SCAN.data.length > 0) {
    data = LIVE_SCAN.data;
  }
  if (!data || data.length === 0) {
    if (typeof log === 'function') log('warn', 'No data to export as CSV');
    return;
  }

  /* Collect all column keys from first row */
  var keys = [];
  var first = data[0];
  for (var k in first) {
    if (first.hasOwnProperty(k) && typeof first[k] === 'number') {
      keys.push(k);
    }
  }
  if (keys.length === 0) return;

  /* Build CSV string */
  var lines = [keys.join(',')];
  for (var i = 0; i < data.length; i++) {
    var row = [];
    for (var j = 0; j < keys.length; j++) {
      var val = data[i][keys[j]];
      row.push(val != null ? String(val) : '');
    }
    lines.push(row.join(','));
  }

  var csv = lines.join('\n');
  var blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  var url = URL.createObjectURL(blob);
  var link3 = document.createElement('a');
  link3.download = _getSavePrefix(_r.tech) + '.csv';
  link3.href = url;
  link3.click();
  URL.revokeObjectURL(url);

  if (typeof log === 'function') log('info', 'CSV exported: ' + data.length + ' rows');
}

// ============================================================
//  RESULT VIEWER — reopen popup for history items
// ============================================================

function v420ShowResult(item) {
  if (!item || !item.result) return;
  var data = item.result.data;
  if (!data || data.length < 2) {
    if (typeof openModal === 'function') openModal('Result: ' + item.name, '<div style="color:var(--t2);padding:20px;text-align:center">No data</div>');
    return;
  }
  var techType = 'xanes';
  if (item.name.indexOf('xrd_2d') >= 0 || item.name === 'raster_scan') techType = 'xrd2d';
  else if (item.name.indexOf('xrd') >= 0) techType = 'xrd';
  else if (item.name.indexOf('xrf') >= 0) techType = 'xrf';

  var labels = {xanes:'XANES', xrd:'XRD', xrf:'XRF', xrd2d:'2D Map'};
  v420OpenLive(item.name, techType, (labels[techType] || techType) + ' -- ' + item.name + ' (Result)');

  // Store for save (globals + on the popup element for per-popup save/resize)
  var pid = _bsLivePopupId;
  _bsLiveResult = item.result;
  _bsLiveTechType = techType;
  var _dv = document.getElementById(pid);
  if (_dv) { _dv._bsResult = item.result; _dv._bsTechType = techType; }

  // Render after layout settles
  setTimeout(function() {
    var cv = document.getElementById(pid + '_canvas');
    if (!cv) return;
    _v420RenderToCanvas(cv, data, techType, item.result.mapData);
    var info = document.getElementById(pid + '_info');
    if (info) {
      info.textContent = (item.result.msg || 'Complete') + ' | ' + (item.startTime ? item.startTime.slice(11, 19) : '') + ' | ' + data.length + ' pts';
      info.style.color = 'var(--gn)';
    }
    var pg = document.getElementById(pid + '_prog'); if (pg) pg.style.width = '100%';
    var pc = document.getElementById(pid + '_pct'); if (pc) pc.textContent = 'Done';
  }, 50);
}

// ============================================================
//  PLAN LIBRARY EXTENSION — ensure XRD/XRF/2DMap plans exist
// ============================================================

// ESM bridge: expose module-scoped vars to globalThis
if(typeof v420DoneLive!=="undefined")globalThis.v420DoneLive=v420DoneLive;
if(typeof v420FallbackChart!=="undefined")globalThis.v420FallbackChart=v420FallbackChart;
if(typeof v420OpenLive!=="undefined")globalThis.v420OpenLive=v420OpenLive;
if(typeof v420SaveCSV!=="undefined")globalThis.v420SaveCSV=v420SaveCSV;
if(typeof v420SaveJSON!=="undefined")globalThis.v420SaveJSON=v420SaveJSON;
if(typeof v420SavePNG!=="undefined")globalThis.v420SavePNG=v420SavePNG;
if(typeof v420SaveResult!=="undefined")globalThis.v420SaveResult=v420SaveResult;
if(typeof v420ShowResult!=="undefined")globalThis.v420ShowResult=v420ShowResult;
if(typeof v420UpdateLive!=="undefined")globalThis.v420UpdateLive=v420UpdateLive;
if(typeof _bsLiveResult!=="undefined")globalThis._bsLiveResult=_bsLiveResult;
if(typeof _bsLiveTechType!=="undefined")globalThis._bsLiveTechType=_bsLiveTechType;
if(typeof _getSavePrefix!=="undefined")globalThis._getSavePrefix=_getSavePrefix;
if(typeof _v420RenderToCanvas!=="undefined")globalThis._v420RenderToCanvas=_v420RenderToCanvas;
if(typeof v420SaveAs!=="undefined")globalThis.v420SaveAs=v420SaveAs;
