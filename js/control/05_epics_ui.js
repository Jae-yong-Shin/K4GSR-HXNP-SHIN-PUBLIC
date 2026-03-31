'use strict';
// ===== control/05_epics_ui.js — EPICS Tab UI & Ring Status =====
// @module control/05_epics_ui
// @exports caputSelectChanged, executeCaput, motorMoveWithEpics, populateCaputSelect, populateTrendSelect, renderEpicsTab, renderEpicsTab_ORIG, renderTrendChart, renderTrendChart_ORIG, setTrendPV, startEpicsPeriodicUpdates, switchTabV2, updateRingStatus
// Extracted from 08_ui_core.js (DDD Phase 6)

/**
 * Build caput PV dropdown from PV_MONITOR_GROUPS.
 */
window.populateCaputSelect = function() {
  var sel = document.getElementById('caputPvSelect');
  if (!sel) return;
  var h = '<option value="">-- Select PV --</option>';
  PV_MONITOR_GROUPS.forEach(function(grp) {
    h += '<optgroup label="' + grp.name + '">';
    grp.pvs.forEach(function(pv) {
      var shortName = pv.replace('BL10:', '');
      h += '<option value="' + pv + '">' + shortName + '</option>';
    });
    h += '</optgroup>';
  });
  sel.innerHTML = h;
};

/**
 * Prefill current value on caput PV select change.
 */
window.caputSelectChanged = function() {
  var pv = document.getElementById('caputPvSelect').value;
  var inp = document.getElementById('caputValue');
  if (!pv || !inp) return;
  var result = epicsGet(pv);
  if (result) inp.value = result.value.toFixed(4);
};

/**
 * Execute caput with history logging.
 */
window.executeCaput = function() {
  var pv = document.getElementById('caputPvSelect').value;
  var val = parseFloat(document.getElementById('caputValue').value);
  if (!pv) { log('warn', 'Select a PV first'); return; }
  if (isNaN(val)) { log('warn', 'Enter a valid number'); return; }
  var ok = epicsPut(pv, val);
  if (ok) {
    var hist = document.getElementById('caputHistory');
    if (hist) {
      var t = new Date().toLocaleTimeString('en-US', {hour12: false});
      hist.innerHTML = '<div><span style="color:var(--t3)">' + t +
        '</span> <span style="color:var(--gn)">OK</span> ' +
        pv.replace('BL10:', '') + ' = ' + val + '</div>' + hist.innerHTML;
      while (hist.children.length > 10) hist.removeChild(hist.lastChild);
    }
  }
};

/**
 * Update ring current / lifetime / shutter status bar.
 */
window.updateRingStatus = function() {
  var el = document.getElementById('ringStatusBar');
  if (!el) return;
  if (EPICS_STATE.mode === 'disconnected') { el.innerHTML = ''; return; }

  var getCurrent = function() {
    if (EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs['BL10:RING:Current']) {
      return EPICS_STATE.simIOC.pvs['BL10:RING:Current'].value;
    }
    return 400.0;
  };
  var getLifetime = function() {
    if (EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs['BL10:RING:Lifetime']) {
      return EPICS_STATE.simIOC.pvs['BL10:RING:Lifetime'].value;
    }
    return 12.5;
  };
  var getShutter = function() {
    if (EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs['BL10:FE:Shutter']) {
      return EPICS_STATE.simIOC.pvs['BL10:FE:Shutter'].value;
    }
    return 1;
  };

  var cur = getCurrent();
  var life = getLifetime();
  var shut = getShutter();
  var shutColor = shut ? 'var(--gn)' : 'var(--rd)';
  var shutText = shut ? 'OPEN' : 'CLOSED';

  el.innerHTML = '<span style="color:var(--t3)">Ring:</span> ' +
    '<span style="color:var(--ac)">' + cur.toFixed(1) + 'mA</span> ' +
    '<span style="color:var(--t3)">t:</span> ' +
    '<span style="color:var(--ac)">' + life.toFixed(1) + 'h</span> ' +
    '<span style="color:' + shutColor + '">FE:' + shutText + '</span>';
};

/**
 * Motor move + EPICS caput. Syncs motor state and writes to EPICS PV.
 * @param {string} groupId - Motor group identifier.
 * @param {string} motorId - Motor identifier within the group.
 * @param {number} value   - Target value to set.
 */
window.motorMoveWithEpics = function(groupId, motorId, value) {
  if (typeof syncMotorToState === 'function') {
    syncMotorToState(groupId, motorId, value);
  }
  if (EPICS_STATE.mode !== 'disconnected') {
    Object.keys(PV_REGISTRY).forEach(function(pv) {
      var reg = PV_REGISTRY[pv];
      if (reg.groupId === groupId && reg.motorId === motorId) {
        epicsPut(pv, value);
      }
    });
  }
};

/**
 * Enhanced tab switch for EPICS. Activates the specified tab pane.
 * @param {string} id - Tab identifier to activate.
 */
window.switchTabV2 = function(id) {
  var ns = [
    'undulator', 'mask', 'dcm', 'optics', 'atten',
    'motors', 'measure', 'align', 'compare', 'epics'
  ];
  document.querySelectorAll('.tab').forEach(function(t, i) {
    if (i < ns.length) t.classList.toggle('active', ns[i] === id);
  });
  document.querySelectorAll('.tabpane').forEach(function(p) {
    p.classList.remove('active');
  });
  var el = document.getElementById('tab-' + id);
  if (el) el.classList.add('active');
  if (id === 'epics') renderEpicsTab();
};

/**
 * Render trend chart. Delegates to V2 implementation if available.
 */
window.renderTrendChart = function() {
  if (typeof renderTrendChartV2 === 'function') { renderTrendChartV2(); return; }
  renderTrendChart_ORIG();
};

/**
 * Original trend chart stub (V2 active).
 */
window.renderTrendChart_ORIG = function() { /* V2 active, stub */ };

/**
 * Set trend PV and refresh the trend chart.
 * @param {string} pv - PV name to monitor in the trend chart.
 */
window.setTrendPV = function(pv) {
  trendPV = pv;
  var lbl = document.getElementById('trendPopupPVLabel');
  if (lbl) lbl.textContent = pv.replace('BL10:', '');
  renderTrendChart();
};

/**
 * Render EPICS tab. Delegates to V2 implementation if available.
 */
window.renderEpicsTab = function() {
  if (typeof renderEpicsTabV2 === 'function') { renderEpicsTabV2(); return; }
  renderEpicsTab_ORIG();
};

/**
 * Original EPICS tab render stub (V2 active).
 */
window.renderEpicsTab_ORIG = function() { /* V2 active, stub */ };

/**
 * Populate trend PV selector dropdown from PV_ARCHIVE.watching.
 */
window.populateTrendSelect = function() {
  var sel = document.getElementById('trendPopupPvSelect');
  if (!sel) return;
  var h = '';
  PV_ARCHIVE.watching.forEach(function(pv) {
    var short = pv.replace('BL10:', '');
    h += '<option value="' + pv + '"' +
      (pv === trendPV ? ' selected' : '') +
      '>' + short + '</option>';
  });
  sel.innerHTML = h;
};

/**
 * Start periodic EPICS updates with 2-second interval.
 * Updates ring status, stats bar, and (if EPICS tab is active) the UI and trend chart.
 */
window.startEpicsPeriodicUpdates = function() {
  setInterval(function() {
    updateRingStatus();
    updateEpicsStatsBar();
    var epicsPane = document.getElementById('tab-epics');
    if (epicsPane && epicsPane.classList.contains('active')) {
      updateEpicsUI();
      renderTrendChart();
    }
  }, 2000);
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof caputSelectChanged!=="undefined")globalThis.caputSelectChanged=caputSelectChanged;
if(typeof executeCaput!=="undefined")globalThis.executeCaput=executeCaput;
if(typeof motorMoveWithEpics!=="undefined")globalThis.motorMoveWithEpics=motorMoveWithEpics;
if(typeof populateCaputSelect!=="undefined")globalThis.populateCaputSelect=populateCaputSelect;
if(typeof populateTrendSelect!=="undefined")globalThis.populateTrendSelect=populateTrendSelect;
if(typeof renderEpicsTab!=="undefined")globalThis.renderEpicsTab=renderEpicsTab;
if(typeof renderEpicsTab_ORIG!=="undefined")globalThis.renderEpicsTab_ORIG=renderEpicsTab_ORIG;
if(typeof renderTrendChart!=="undefined")globalThis.renderTrendChart=renderTrendChart;
if(typeof renderTrendChart_ORIG!=="undefined")globalThis.renderTrendChart_ORIG=renderTrendChart_ORIG;
if(typeof setTrendPV!=="undefined")globalThis.setTrendPV=setTrendPV;
if(typeof startEpicsPeriodicUpdates!=="undefined")globalThis.startEpicsPeriodicUpdates=startEpicsPeriodicUpdates;
if(typeof switchTabV2!=="undefined")globalThis.switchTabV2=switchTabV2;
if(typeof updateRingStatus!=="undefined")globalThis.updateRingStatus=updateRingStatus;
