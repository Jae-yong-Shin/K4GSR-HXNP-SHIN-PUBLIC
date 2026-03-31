// ===== bluesky/03_bluesky_ui.js — Bluesky Tab UI Rendering =====
// Extracted from 10_features.js (DDD Phase 3)
// @module bluesky/03_bluesky_ui
// @exports bsLiveChart, collectPlanParams, draw2DMap, fetchScanHistory, heatColor, hideBsBottomPanel, renderBlueskyTab, renderBsBottomPanel, renderPlanParams, renderResultCanvas, submitAndRun, submitSelectedPlan, toggleBsPanel, updateBsLiveChart, updateBsProgressOnly
// Merged: v415 execution guard, v420 history result buttons (from 11_v433_fixes.js, DDD Phase 4)
'use strict';

var bsLiveChart = null;

// ============================================================
//  MAIN TAB RENDERER
// ============================================================

function renderBlueskyTab() {
  var el = document.getElementById('tab-bluesky');
  if (!el) return;

  // [DDD merged from 11:67 installBlueskyFix] Skip DOM rebuild during active execution
  if (QUEUE.running && QUEUE.running._executor && QUEUE.running._executor.progress > 0 && QUEUE.running._executor.progress < 100) {
    updateBsProgressOnly();
    return;
  }

  var qs = QUEUE;
  var statusColors = { idle: 'var(--t2)', running: 'var(--gn)', paused: 'var(--am)', error: 'var(--rd)' };
  var statusIcons = { idle: 'o', running: '*', paused: '||', error: 'X' };

  var h = '';

  // --- Status Bar ---
  h += '<div class="ctrl-group" style="display:flex;justify-content:space-between;align-items:center;margin:0 0 6px 0">' +
    '<div style="display:flex;align-items:center;gap:6px">' +
      '<span style="color:' + statusColors[qs.status] + ';font-size:12px">' + statusIcons[qs.status] + '</span>' +
      '<span style="font-size:10px;font-family:var(--mn);color:' + statusColors[qs.status] + '">' + _t('status_' + qs.status).toUpperCase() + '</span>' +
      '<span style="font-size:8px;font-family:var(--mn);color:var(--t3)">' + (QS_CONFIG.simMode ? 'SIM' : 'LIVE') + '</span>' +
    '</div>' +
    '<div style="display:flex;gap:2px">' +
      '<button class="sb" onclick="queueStart()" style="font-size:8px;padding:2px 6px" ' + (qs.status==='running'?'disabled':'') + '>></button>' +
      '<button class="sb" onclick="queuePause()" style="font-size:8px;padding:2px 6px;background:var(--am);color:#000" ' + (qs.status!=='running'?'disabled':'') + '>||</button>' +
      '<button class="sb" onclick="queueResume()" style="font-size:8px;padding:2px 6px;background:var(--gn);color:#000" ' + (qs.status!=='paused'?'disabled':'') + '>>></button>' +
      '<button class="sb stop" onclick="queueAbort()" style="font-size:8px;padding:2px 6px" ' + (!qs.running?'disabled':'') + '>X</button>' +
    '</div>' +
  '</div>';

  // --- Running Plan ---
  if (qs.running) {
    var exec = qs.running._executor;
    var pct = exec ? exec.progress.toFixed(0) : 0;
    h += '<div class="ctrl-group" style="border-left:3px solid var(--gn);margin:0 0 6px 0">' +
      '<div class="ctrl-label" style="color:var(--gn);font-weight:600">> ' + qs.running.name + '</div>' +
      '<div style="font-size:8px;font-family:var(--mn);color:var(--t3)">' + qs.running.item_uid.slice(-8) + '</div>' +
      '<div class="prog-bar" style="margin-top:4px"><div class="prog-fill" id="bsPlanProgress" style="width:' + pct + '%"></div></div>' +
      '<div style="font-size:8px;font-family:var(--mn);color:var(--ac);text-align:right;margin-top:2px" id="bsPlanPct">' + pct + '%</div>' +
    '</div>';
  }

  // --- Submit Plan ---
  var planOptions = '';
  var planKeys = Object.keys(PLAN_LIBRARY);
  for (var pi = 0; pi < planKeys.length; pi++) {
    var pl = PLAN_LIBRARY[planKeys[pi]];
    planOptions += '<option value="' + pl.name + '">' + pl.label + ' (' + pl.category + ')</option>';
  }
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px" data-i18n="bs_submit_plan">' + _t('bs_submit_plan') + '</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<select id="bsPlanSelect" style="margin-bottom:4px" onchange="renderPlanParams()">' +
      planOptions +
    '</select>' +
    '<div id="bsPlanParams"></div>' +
    '<div style="display:flex;gap:4px;margin-top:6px">' +
      '<button class="sb act" onclick="submitSelectedPlan()" style="flex:1" data-i18n="bs_add_queue">' + _t('bs_add_queue') + '</button>' +
      '<button class="sb go act" onclick="submitAndRun()" style="flex:1" data-i18n="bs_run_now">' + _t('bs_run_now') + '</button>' +
    '</div>' +
  '</div></div>';

  // --- Queue ---
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px;display:flex;justify-content:space-between">' +
      '<span>' + _tf('bs_queue_fmt', qs.items.length) + '</span>' +
      '<span style="cursor:pointer;color:var(--rd);font-size:8px;font-weight:400" onclick="queueClear()" data-i18n="bs_clear">' + _t('bs_clear') + '</span>' +
    '</h4>' +
    '<div class="ctrl-group" style="margin:0">';
  if (qs.items.length === 0) {
    h += '<div style="font-size:9px;color:var(--t3);padding:8px;text-align:center" data-i18n="bs_queue_empty">' + _t('bs_queue_empty') + '</div>';
  } else {
    for (var qi = 0; qi < qs.items.length; qi++) {
      var item = qs.items[qi];
      var idx = qi;
      h += '<div style="display:flex;align-items:center;gap:4px;padding:3px 0;border-bottom:1px solid var(--b0)">' +
        '<span style="font-size:8px;color:var(--t3);min-width:14px">' + (idx + 1) + '</span>' +
        '<span style="font-size:9px;flex:1">' + item.name + '</span>' +
        '<button onclick="queueMoveUp(\'' + item.item_uid + '\')" style="font-size:8px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:2px;cursor:pointer;padding:1px 3px">^</button>' +
        '<button onclick="queueMoveDown(\'' + item.item_uid + '\')" style="font-size:8px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:2px;cursor:pointer;padding:1px 3px">v</button>' +
        '<button onclick="queueRemove(\'' + item.item_uid + '\')" style="font-size:8px;background:var(--s2);border:1px solid var(--b1);color:var(--rd);border-radius:2px;cursor:pointer;padding:1px 3px">X</button>' +
      '</div>';
    }
  }
  h += '</div></div>';

  // --- History ---
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">' + _tf('bs_run_history_fmt', qs.history.length) + '</h4>' +
    '<div class="ctrl-group" style="margin:0">';
  var histSlice = qs.history.slice(0, 8);
  for (var hi2 = 0; hi2 < histSlice.length; hi2++) {
    var hitem = histSlice[hi2];
    var color = hitem.status === 'completed' ? 'var(--gn)' : hitem.status === 'aborted' ? 'var(--am)' : 'var(--rd)';
    var icon = hitem.status === 'completed' ? 'OK' : hitem.status === 'aborted' ? '--' : 'X';
    var resultMsg = (hitem.result && hitem.result.msg) ? hitem.result.msg : '';
    h += '<div style="display:flex;align-items:center;gap:4px;padding:2px 0;border-bottom:1px solid var(--b0)">' +
      '<span style="color:' + color + ';font-size:9px">' + icon + '</span>' +
      '<span style="font-size:9px;flex:1">' + hitem.name + '</span>' +
      '<span style="font-size:8px;font-family:var(--mn);color:var(--t3)">' + resultMsg + '</span>' +
    '</div>';
  }
  h += '</div></div>';

  // --- Quick Actions ---
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px" data-i18n="bs_quick_run">' + _t('bs_quick_run') + '</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div style="display:flex;flex-wrap:wrap;gap:3px">' +
      '<button class="sb" onclick="quickEnergyScan(state.energy-2,state.energy+2,50);queueStart()" style="font-size:8px;padding:2px 6px">> E-Scan</button>' +
      '<button class="sb" onclick="quickXafs(document.getElementById(\'material\')?.value||\'Cu\');queueStart()" style="font-size:8px;padding:2px 6px">> XANES</button>' +
      '<button class="sb" onclick="quickAlign(\'m1_pitch\');queueStart()" style="font-size:8px;padding:2px 6px">> M1 Align</button>' +
      '<button class="sb" onclick="queuePlan(\'auto_align\',{});queueStart()" style="font-size:8px;padding:2px 6px">> Auto Align</button>' +
      '<button class="sb" onclick="quickRaster(5,5,21);queueStart()" style="font-size:8px;padding:2px 6px">> Raster</button>' +
      '<button class="sb" onclick="queuePlan(\'gap_optimize\',{});queueStart()" style="font-size:8px;padding:2px 6px">> Gap Opt.</button>' +
      '<button class="sb" onclick="quickAutoTune(\'m1\',\'pitch\');queueStart()" style="font-size:8px;padding:2px 6px">> AutoTune</button>' +
      '<button class="sb" onclick="quickAdaptiveScan(state.energy-0.1,state.energy+0.1);queueStart()" style="font-size:8px;padding:2px 6px">> Adaptive</button>' +
      '<button class="sb" onclick="quickRelAlign(\'m1\',\'pitch\',0.2);queueStart()" style="font-size:8px;padding:2px 6px">> Rel.Align</button>' +
      '<button class="sb" onclick="quickFermat(10,10,0.5);queueStart()" style="font-size:8px;padding:2px 6px">> Fermat</button>' +
      '<button class="sb" onclick="quickRelRaster(10,10,21,21);queueStart()" style="font-size:8px;padding:2px 6px">> Rel.Raster</button>' +
    '</div>' +
  '</div></div>';

  // --- QS Connection ---
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px" data-i18n="bs_qs_connection">' + _t('bs_qs_connection') + '</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div style="display:flex;gap:4px">' +
      '<input type="text" id="bsQsUrl" value="' + QS_CONFIG.url + '" style="flex:1;font-size:8px" placeholder="http://host:60610"/>' +
      '<button class="sb" onclick="connectRealQS(document.getElementById(\'bsQsUrl\').value)" style="font-size:8px;padding:2px 6px" data-i18n="bs_connect">' + _t('bs_connect') + '</button>' +
    '</div>' +
    '<div style="font-size:8px;font-family:var(--mn);color:var(--t3);margin-top:2px">' +
      (QS_CONFIG.connected ? _t('bs_connected') : _t('bs_sim_mode')) +
    '</div>' +
  '</div></div>';

  // [DDD inline merged from bluesky/07_server_history.js] Server Scan History section
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px;display:flex;justify-content:space-between">' +
      '<span data-i18n="bs_server_history">' + _t('bs_server_history') + '</span>' +
      '<span style="cursor:pointer;color:var(--ac);font-size:8px;font-weight:400" onclick="window.fetchScanHistory()">Refresh</span>' +
    '</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div id="bsServerHistory"><div style="font-size:9px;color:var(--t3);padding:8px;text-align:center">' +
      _t('bs_click_refresh') + '</div></div>' +
  '</div></div>';

  el.innerHTML = h;

  // Auto-fetch server history if WS is connected
  if (typeof SERVER_HISTORY !== 'undefined' && !SERVER_HISTORY.loaded &&
      typeof EPICS_STATE !== 'undefined' && EPICS_STATE.scanWs &&
      EPICS_STATE.scanWs.readyState === 1 /* WebSocket.OPEN */) {
    if (typeof window.fetchScanHistory === 'function') window.fetchScanHistory();
  }

  // Render initial plan params
  setTimeout(renderPlanParams, 10);

  // [DDD merged from 11:2367 fixBSHistoryButtons] Inject result view buttons
  setTimeout(function() {
    if (typeof QUEUE === 'undefined' || !QUEUE.history) return;
    QUEUE.history.forEach(function(item) {
      if (item.status !== 'completed' || !item.result || !item.result.data || item.result.data.length < 2) return;
      var divs = el.querySelectorAll('div');
      for (var di = 0; di < divs.length; di++) {
        var dv = divs[di];
        if (dv.style.borderBottom && dv.textContent.indexOf(item.name) >= 0 && !dv.querySelector('.v420rb')) {
          var btn = document.createElement('button');
          btn.className = 'sb v420rb';
          btn.style.cssText = 'font-size:8px;padding:1px 5px;background:var(--pr);color:#fff;margin-left:2px';
          btn.textContent = 'Result';
          (function(itm) { btn.onclick = function(ev) { ev.stopPropagation(); if (typeof v420ShowResult === 'function') v420ShowResult(itm); }; })(item);
          dv.appendChild(btn); break;
        }
      }
    });
  }, 80);
}

// [DDD merged from 11:84] Lightweight progress-only update (no DOM rebuild)
function updateBsProgressOnly() {
  var pctEl = document.getElementById('bsPlanPct');
  var progEl = document.getElementById('bsPlanProgress');
  if (QUEUE.running && QUEUE.running._executor) {
    var pct = QUEUE.running._executor.progress;
    if (pctEl) pctEl.textContent = pct.toFixed(0) + '%';
    if (progEl) progEl.style.width = pct.toFixed(0) + '%';
  }
}

// ============================================================
//  PLAN PARAMETER FORM
// ============================================================

function renderPlanParams() {
  var sel = document.getElementById('bsPlanSelect');
  var container = document.getElementById('bsPlanParams');
  if (!sel || !container) return;

  var plan = PLAN_LIBRARY[sel.value];
  if (!plan) { container.innerHTML = ''; return; }

  var h = '<div style="font-size:8px;color:var(--t3);margin-bottom:4px">' + plan.description + '</div>';
  var paramKeys = Object.keys(plan.params);
  for (var ki = 0; ki < paramKeys.length; ki++) {
    var key = paramKeys[ki];
    var cfg = plan.params[key];
    var id = 'bsP_' + key;
    if (cfg.type === 'select') {
      var opts = '';
      for (var oi = 0; oi < cfg.options.length; oi++) {
        var o = cfg.options[oi];
        opts += '<option value="' + o + '" ' + (o === cfg.default ? 'selected' : '') + '>' + o + '</option>';
      }
      h += '<div class="mc-row" style="margin-bottom:3px">' +
        '<label style="min-width:70px;font-size:9px">' + cfg.label + '</label>' +
        '<select id="' + id + '" style="flex:1;font-size:9px">' +
          opts +
        '</select>' +
      '</div>';
    } else {
      h += '<div class="mc-row" style="margin-bottom:3px">' +
        '<label style="min-width:70px;font-size:9px">' + cfg.label + '</label>' +
        '<input type="number" id="' + id + '" value="' + cfg.default + '" step="any" style="flex:1;font-size:9px"/>' +
        '<span style="font-size:8px;color:var(--t3);min-width:25px">' + (cfg.unit || '') + '</span>' +
      '</div>';
    }
  }
  container.innerHTML = h;
}

function collectPlanParams() {
  var sel = document.getElementById('bsPlanSelect');
  if (!sel) return {};
  var plan = PLAN_LIBRARY[sel.value];
  if (!plan) return {};
  var params = {};
  var paramKeys = Object.keys(plan.params);
  for (var ki = 0; ki < paramKeys.length; ki++) {
    var key = paramKeys[ki];
    var cfg = plan.params[key];
    var el = document.getElementById('bsP_' + key);
    if (!el) continue;
    if (cfg.type === 'select') params[key] = el.value;
    else params[key] = parseFloat(el.value);
  }
  return params;
}

function submitSelectedPlan() {
  var sel = document.getElementById('bsPlanSelect');
  if (!sel) return;
  var params = collectPlanParams();
  queuePlan(sel.value, params);
}

function submitAndRun() {
  submitSelectedPlan();
  queueStart();
}

// ============================================================
//  LIVE CHART (in bottom panel)
// ============================================================

// [DDD merged from 11:290 fixBsBottomPanel] Canvas-direct rendering (no Chart.js)
function updateBsLiveChart(data, planName) {
  // When suppressPanel is active (virtual experiment popup), skip bottom panel
  if (typeof QUEUE !== 'undefined' && QUEUE._suppressPanel) return;
  // Ensure panel is visible
  var panel = document.getElementById('bsPanel');
  if (panel) panel.style.display = 'flex';
  var status = document.getElementById('bsLiveStatus');
  if (status) status.textContent = planName || 'Running...';

  var cv = document.getElementById('bsLiveCanvas');
  if (!cv) {
    // Canvas was destroyed by DOM rebuild -- recreate it
    var body = document.getElementById('bsPanelBody');
    if (body) {
      body.innerHTML = '<canvas id="bsLiveCanvas" height="150"></canvas>';
      cv = document.getElementById('bsLiveCanvas');
    }
  }
  if (!cv) return;

  // Check if this is 2D map data
  if (data.length > 0 && data[0].val !== undefined) {
    draw2DMap(cv, data);
    return;
  }

  // Use canvas-direct rendering (no Chart.js dependency)
  if (typeof renderResultCanvas === 'function') {
    renderResultCanvas(cv, data, planName || '');
  }
}

// === renderResultCanvas: delegates to _drawChart1D (Plotly-based) ===
function renderResultCanvas(cv, data, planName) {
  if (!data || data.length === 0) return;
  if (data[0] && data[0].val !== undefined) {
    if (typeof draw2DMap === 'function') draw2DMap(cv, data);
    return;
  }
  var xlabel = data[0].xlabel || 'X';
  var ylabel = data[0].ylabel || 'Y';
  if (typeof _drawChart1D === 'function') {
    _drawChart1D(cv, data, {
      color: '#4db8ff',
      xlabel: xlabel,
      ylabel: ylabel,
      title: planName || '',
      nTicksX: 5, nTicksY: 4,
      height: 120
    });
  }
}

function draw2DMap(cv, data) {
  var xSet = {}, ySet = {};
  var di;
  for (di = 0; di < data.length; di++) { xSet[data[di].x] = true; ySet[data[di].y] = true; }
  var xs = Object.keys(xSet).map(Number).sort(function(a, b) { return a - b; });
  var ys = Object.keys(ySet).map(Number).sort(function(a, b) { return a - b; });
  var nx = xs.length, ny = ys.length;

  var lookup = {};
  for (di = 0; di < data.length; di++) { lookup[data[di].x + ',' + data[di].y] = data[di].val; }

  var z = [];
  for (var j = 0; j < ny; j++) {
    var row = [];
    for (var i = 0; i < nx; i++) {
      var v = lookup[xs[i] + ',' + ys[j]];
      row.push(v !== undefined ? v : 0);
    }
    z.push(row);
  }

  if (typeof _drawHeatmap2D === 'function') {
    var w = cv.parentElement ? cv.parentElement.clientWidth - 16 : 300;
    _drawHeatmap2D(cv, z, {
      x: xs, y: ys,
      xLabel: 'X (μm)', yLabel: 'Y (μm)',
      title: nx + 'x' + ny,
      width: w, height: 150,
      colorscale: [
        [0, 'rgb(0,0,128)'], [0.25, 'rgb(0,255,255)'],
        [0.5, 'rgb(0,255,0)'], [0.75, 'rgb(255,255,0)'], [1, 'rgb(255,0,0)']
      ]
    });
  }
}

function heatColor(t) {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.25) return 'rgb(0,' + (t / 0.25 * 255 | 0) + ',' + (128 + t / 0.25 * 127 | 0) + ')';
  if (t < 0.5) return 'rgb(0,255,' + (255 - (t - 0.25) / 0.25 * 128 | 0) + ')';
  if (t < 0.75) return 'rgb(' + ((t - 0.5) / 0.25 * 255 | 0) + ',255,0)';
  return 'rgb(255,' + (255 - (t - 0.75) / 0.25 * 255 | 0) + ',0)';
}

// ============================================================
//  BOTTOM PANEL — Bluesky Live Data
// ============================================================

function renderBsBottomPanel() {
  var panel = document.getElementById('bsPanel');
  if (!panel) return;
  panel.style.display = 'flex';
  var body = document.getElementById('bsPanelBody');
  if (!body) return;
  body.innerHTML = '<canvas id="bsLiveCanvas" height="150"></canvas>';
}

function hideBsBottomPanel() {
  var panel = document.getElementById('bsPanel');
  if (panel) panel.style.display = 'none';
}


// === Bluesky bottom panel toggle ===
function toggleBsPanel(show) {
  var p = document.getElementById('bsPanel');
  if (p) p.style.display = show ? 'flex' : 'none';
  var st = document.getElementById('bsLiveStatus');
  if (st && QUEUE.running) st.textContent = QUEUE.running.name;
  else if (st) st.textContent = '--';
}

// [DDD] _origProcessNext and _origQueueStart wrappers merged into bluesky/01_queue.js
// [DDD] renderBlueskyTab v415 guard + v420 history buttons merged inline
// [DDD] updateBsLiveChart v415 canvas-direct merged inline (no Chart.js)

// ESM bridge: expose module-scoped vars to globalThis
if(typeof bsLiveChart!=="undefined")globalThis.bsLiveChart=bsLiveChart;
if(typeof collectPlanParams!=="undefined")globalThis.collectPlanParams=collectPlanParams;
if(typeof draw2DMap!=="undefined")globalThis.draw2DMap=draw2DMap;
if(typeof heatColor!=="undefined")globalThis.heatColor=heatColor;
if(typeof hideBsBottomPanel!=="undefined")globalThis.hideBsBottomPanel=hideBsBottomPanel;
if(typeof renderBlueskyTab!=="undefined")globalThis.renderBlueskyTab=renderBlueskyTab;
if(typeof renderBsBottomPanel!=="undefined")globalThis.renderBsBottomPanel=renderBsBottomPanel;
if(typeof renderPlanParams!=="undefined")globalThis.renderPlanParams=renderPlanParams;
if(typeof renderResultCanvas!=="undefined")globalThis.renderResultCanvas=renderResultCanvas;
if(typeof submitAndRun!=="undefined")globalThis.submitAndRun=submitAndRun;
if(typeof submitSelectedPlan!=="undefined")globalThis.submitSelectedPlan=submitSelectedPlan;
if(typeof toggleBsPanel!=="undefined")globalThis.toggleBsPanel=toggleBsPanel;
if(typeof updateBsLiveChart!=="undefined")globalThis.updateBsLiveChart=updateBsLiveChart;
if(typeof updateBsProgressOnly!=="undefined")globalThis.updateBsProgressOnly=updateBsProgressOnly;
if(typeof fetchScanHistory!=="undefined")globalThis.fetchScanHistory=fetchScanHistory;
