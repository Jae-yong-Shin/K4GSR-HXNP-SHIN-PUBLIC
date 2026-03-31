'use strict';
// ===== bluesky/06_live_scan.js — Live Scan Visualization =====
// @module bluesky/06_live_scan
// @exports LIVE_SCAN, _addElementSelector, _enhancedScanEventHandler, _fmtTime, _installLiveScanEnhancement, _serverPlanResolve, _updateLiveProgress, _updateScanCtrlUI, bsScanAbort, bsScanPause, bsScanResume
// Extracted from 14_v435_final.js (DDD Phase 5f)
// Provides: LIVE_SCAN state, bsScanPause/Resume/Abort, _enhancedScanEventHandler
// Wraps connectScan + PlanExecutor.prototype.updateProgress for bottom-panel updates

(function() {

/* -- Live scan state -- */
var LIVE_SCAN = {
  running: false,
  planName: '',
  numPoints: 0,
  eventCount: 0,
  startTime: 0,
  data: [],
  rasterXRF: {},
  paused: false
};
window.LIVE_SCAN = LIVE_SCAN;

/* -- Scan control functions (used by bottom panel buttons) -- */
window.bsScanPause = function() {
  if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.scanWs &&
      EPICS_STATE.scanWs.readyState === WebSocket.OPEN) {
    EPICS_STATE.scanWs.send(JSON.stringify({ action: 'pause' }));
  }
  if (typeof QUEUE !== 'undefined' && QUEUE.running && QUEUE.running._executor) {
    QUEUE.running._executor.paused = true;
  }
  LIVE_SCAN.paused = true;
  _updateScanCtrlUI('paused');
  log('info', 'Scan paused');
};

window.bsScanResume = function() {
  if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.scanWs &&
      EPICS_STATE.scanWs.readyState === WebSocket.OPEN) {
    EPICS_STATE.scanWs.send(JSON.stringify({ action: 'resume' }));
  }
  if (typeof QUEUE !== 'undefined' && QUEUE.running && QUEUE.running._executor) {
    QUEUE.running._executor.paused = false;
    QUEUE.running._executor.resume();
  }
  LIVE_SCAN.paused = false;
  _updateScanCtrlUI('running');
  log('info', 'Scan resumed');
};

window.bsScanAbort = function() {
  if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.scanWs &&
      EPICS_STATE.scanWs.readyState === WebSocket.OPEN) {
    EPICS_STATE.scanWs.send(JSON.stringify({ action: 'abort', reason: 'User abort' }));
  }
  if (typeof QUEUE !== 'undefined' && QUEUE.running && QUEUE.running._executor) {
    QUEUE.running._executor.abort();
  }
  LIVE_SCAN.running = false;
  _updateScanCtrlUI('idle');
  log('warn', 'Scan aborted by user');
};

/* -- Update control button visibility -- */
function _updateScanCtrlUI(st) {
  var ctrl = document.getElementById('bsScanCtrl');
  var pauseBtn = document.getElementById('bsPauseBtn');
  var resumeBtn = document.getElementById('bsResumeBtn');
  var abortBtn = document.getElementById('bsAbortBtn');
  if (!ctrl) return;

  if (st === 'running') {
    ctrl.style.display = 'flex';
    if (pauseBtn) pauseBtn.style.display = '';
    if (resumeBtn) resumeBtn.style.display = 'none';
    if (abortBtn) abortBtn.style.display = '';
  } else if (st === 'paused') {
    ctrl.style.display = 'flex';
    if (pauseBtn) pauseBtn.style.display = 'none';
    if (resumeBtn) resumeBtn.style.display = '';
    if (abortBtn) abortBtn.style.display = '';
  } else {
    ctrl.style.display = 'none';
  }
}

/* -- Format time -- */
function _fmtTime(sec) {
  if (!sec || sec <= 0) return '--:--';
  var m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return (m > 0 ? m + 'm ' : '') + s + 's';
}

/* -- Update progress display -- */
function _updateLiveProgress(count, total, elapsed) {
  var progEl = document.getElementById('bsLiveProgress');
  var ptsEl = document.getElementById('bsLivePts');
  var etaEl = document.getElementById('bsLiveEta');

  var pct = total > 0 ? Math.min(100, (count / total) * 100) : 0;

  if (progEl) progEl.style.width = pct.toFixed(1) + '%';
  if (ptsEl) ptsEl.textContent = count + (total > 0 ? ' / ' + total + ' pts' : ' pts');

  if (etaEl) {
    if (count > 0 && total > 0 && elapsed > 0) {
      var rate = count / elapsed;
      var remaining = (total - count) / rate;
      etaEl.textContent = _fmtTime(elapsed) + ' / ETA ' + _fmtTime(remaining);
    } else if (elapsed > 0) {
      etaEl.textContent = _fmtTime(elapsed);
    } else {
      etaEl.textContent = '\u2014';
    }
  }

  var bsProg = document.getElementById('bsPlanProgress');
  var bsPct = document.getElementById('bsPlanPct');
  if (bsProg) bsProg.style.width = pct.toFixed(1) + '%';
  if (bsPct) bsPct.textContent = (total > 0 ? pct.toFixed(0) + '%' : count + ' pts');
}

/* -- Enhanced scan event handler -- */
function _enhancedScanEventHandler(msg) {
  if (msg.type !== 'scan_event') return;
  var docType = msg.doc_type;
  var doc = msg.doc || {};

  /* -- START -- */
  if (docType === 'start') {
    LIVE_SCAN.running = true;
    LIVE_SCAN.paused = false;
    LIVE_SCAN.planName = msg.plan || doc.plan_name || '';
    LIVE_SCAN.numPoints = doc.num_points || 0;
    LIVE_SCAN.eventCount = 0;
    LIVE_SCAN.startTime = Date.now();
    LIVE_SCAN.data = [];
    LIVE_SCAN.rasterXRF = {};

    var panel = document.getElementById('bsPanel');
    if (panel) panel.style.display = 'flex';

    var statusEl = document.getElementById('bsLiveStatus');
    if (statusEl) {
      statusEl.textContent = LIVE_SCAN.planName;
      statusEl.style.color = 'var(--gn)';
    }

    _updateScanCtrlUI('running');
    _updateLiveProgress(0, LIVE_SCAN.numPoints, 0);
    log('info', 'Live scan started: ' + LIVE_SCAN.planName +
        (LIVE_SCAN.numPoints > 0 ? ' (' + LIVE_SCAN.numPoints + ' pts)' : ''));
  }

  /* -- EVENT -- */
  if (docType === 'event') {
    LIVE_SCAN.eventCount++;
    var data = doc.data || {};

    var point = null;
    if (typeof _extractDataPoint === 'function') {
      point = _extractDataPoint(data, LIVE_SCAN.planName, LIVE_SCAN.eventCount);
    }
    if (point) {
      LIVE_SCAN.data.push(point);

      if (point.val !== undefined) {
        var keys = Object.keys(data);
        keys.forEach(function(k) {
          if (k !== 'sample_sx' && k !== 'sample_sy' && k !== 'ic1_current') {
            if (!LIVE_SCAN.rasterXRF[k]) LIVE_SCAN.rasterXRF[k] = [];
            LIVE_SCAN.rasterXRF[k].push({ x: point.x, y: point.y, val: data[k] || 0 });
          }
        });
      }

      /* Throttle live chart updates to ~5fps to prevent browser freeze on large scans */
      var _now = Date.now();
      if (_now - (LIVE_SCAN._lastChartUpdate || 0) > 200) {
        LIVE_SCAN._lastChartUpdate = _now;
        if (typeof updateBsLiveChart === 'function') {
          updateBsLiveChart(LIVE_SCAN.data, LIVE_SCAN.planName);
        }
      }
    }

    var elapsed = (Date.now() - LIVE_SCAN.startTime) / 1000;
    _updateLiveProgress(LIVE_SCAN.eventCount, LIVE_SCAN.numPoints, elapsed);
  }

  /* -- STOP -- */
  if (docType === 'stop') {
    LIVE_SCAN.running = false;
    var success = doc.exit_status === 'success';
    var elapsedStop = (Date.now() - LIVE_SCAN.startTime) / 1000;

    /* Final chart update (flush throttled data) */
    if (LIVE_SCAN.data.length > 0 && typeof updateBsLiveChart === 'function') {
      updateBsLiveChart(LIVE_SCAN.data, LIVE_SCAN.planName);
    }

    _updateLiveProgress(LIVE_SCAN.eventCount, LIVE_SCAN.eventCount, elapsedStop);

    var statusElStop = document.getElementById('bsLiveStatus');
    if (statusElStop) {
      statusElStop.textContent = LIVE_SCAN.planName + (success ? ' DONE' : ' FAILED');
      statusElStop.style.color = success ? 'var(--gn)' : 'var(--rd)';
    }

    _updateScanCtrlUI('idle');

    var etaEl2 = document.getElementById('bsLiveEta');
    if (etaEl2) etaEl2.textContent = _fmtTime(elapsedStop) + ' total';

    log(success ? 'info' : 'err',
        'Scan ' + (success ? 'done' : 'failed') + ': ' +
        LIVE_SCAN.eventCount + ' pts in ' + _fmtTime(elapsedStop));

    if (Object.keys(LIVE_SCAN.rasterXRF).length > 1) {
      _addElementSelector();
    }

    if (typeof window._serverPlanResolve === 'function') {
      window._serverPlanResolve({
        success: success,
        msg: (success ? 'Completed' : 'Failed') + ': ' + LIVE_SCAN.eventCount + ' points',
        data: LIVE_SCAN.data
      });
      window._serverPlanResolve = null;
    }
  }
}

/* -- Element selector for raster scan 2D maps -- */
function _addElementSelector() {
  var body = document.getElementById('bsPanelBody');
  if (!body) return;

  var existing = document.getElementById('bsElemSelect');
  if (existing) existing.parentElement.removeChild(existing);

  var keys = Object.keys(LIVE_SCAN.rasterXRF);
  if (keys.length === 0) return;

  var sel = document.createElement('div');
  sel.id = 'bsElemSelect';
  sel.style.cssText = 'display:flex;gap:2px;flex-wrap:wrap;padding:4px 2px;border-top:1px solid var(--b0)';

  keys.forEach(function(k) {
    var btn = document.createElement('button');
    btn.className = 'sb';
    btn.style.cssText = 'font-size:8px;padding:2px 6px';
    btn.textContent = k;
    btn.onclick = function() {
      var mapData = LIVE_SCAN.rasterXRF[k];
      if (mapData && typeof updateBsLiveChart === 'function') {
        updateBsLiveChart(mapData, k + ' map');
      }
      sel.querySelectorAll('button').forEach(function(b) { b.style.fontWeight = ''; });
      btn.style.fontWeight = '600';
    };
    sel.appendChild(btn);
  });

  body.insertBefore(sel, body.firstChild);
}

/* -- Install enhanced handler -- */
// connectScan wrapper removed: _enhancedScanEventHandler is now called
// directly from the canonical connectScan in control/02_epics.js
function _installLiveScanEnhancement() {
  // Patch local PlanExecutor to also update bottom panel
  if (typeof PlanExecutor !== 'undefined' && PlanExecutor.prototype) {
    var origPEUpdate = PlanExecutor.prototype.updateProgress;
    PlanExecutor.prototype.updateProgress = function(pct) {
      origPEUpdate.call(this, pct);
      var panel2 = document.getElementById('bsPanel');
      if (panel2) panel2.style.display = 'flex';

      var statusEl2 = document.getElementById('bsLiveStatus');
      if (statusEl2 && this.item) statusEl2.textContent = this.item.name || 'Local scan';

      var count = Math.round(pct);
      var elapsed2 = (Date.now() - this.startTime) / 1000;
      _updateLiveProgress(count, 100, elapsed2);

      if (!LIVE_SCAN.running) {
        LIVE_SCAN.running = true;
        LIVE_SCAN.startTime = this.startTime;
        LIVE_SCAN.planName = this.item ? this.item.name : '';
        _updateScanCtrlUI('running');
      }
    };
  }

  log('info', '[V4.36] Live scan visualization enhanced');
}

// Auto-install
if (document.readyState === 'complete' || document.readyState === 'interactive') {
  setTimeout(_installLiveScanEnhancement, 200);
} else {
  document.addEventListener('DOMContentLoaded', function() {
    setTimeout(_installLiveScanEnhancement, 200);
  });
}

console.log('[V4.36] Live scan module loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof LIVE_SCAN!=="undefined")globalThis.LIVE_SCAN=LIVE_SCAN;
if(typeof _addElementSelector!=="undefined")globalThis._addElementSelector=_addElementSelector;
if(typeof _enhancedScanEventHandler!=="undefined")globalThis._enhancedScanEventHandler=_enhancedScanEventHandler;
if(typeof _fmtTime!=="undefined")globalThis._fmtTime=_fmtTime;
if(typeof _installLiveScanEnhancement!=="undefined")globalThis._installLiveScanEnhancement=_installLiveScanEnhancement;
if(typeof _serverPlanResolve!=="undefined")globalThis._serverPlanResolve=_serverPlanResolve;
if(typeof _updateLiveProgress!=="undefined")globalThis._updateLiveProgress=_updateLiveProgress;
if(typeof _updateScanCtrlUI!=="undefined")globalThis._updateScanCtrlUI=_updateScanCtrlUI;
if(typeof bsScanAbort!=="undefined")globalThis.bsScanAbort=bsScanAbort;
if(typeof bsScanPause!=="undefined")globalThis.bsScanPause=bsScanPause;
if(typeof bsScanResume!=="undefined")globalThis.bsScanResume=bsScanResume;
