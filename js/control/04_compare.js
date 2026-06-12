// ===== compare.js -- Phase 2: V/R Comparison Engine =====
// ===== compare.js -- Phase 2: Real/Virtual Live Comparison Engine =====
// @module control/04_compare
// @exports COMPARISON, DEFAULT_TOLERANCES, SEV_BAD, SEV_GOOD, SEV_WARN, VIRTUAL_STATE, autoCalibrateTolerance, captureVirtualState, clearComparisonOverlay, comparisonTimer, renderComparisonPanel, runComparison, setDeviceTolerance, setTolerance, severityColor, ...
// Captures virtual (predicted) state, compares with real (EPICS) readbacks,
// generates discrepancy reports, color-codes SVG diagram, auto-suggests fixes.
// =====================================================================

// ========================================================================
// Virtual State Snapshot -- predicted values from physics model
// ========================================================================
var VIRTUAL_STATE = {
  motors: {},      // motorId -> {predicted, unit, tolerance}
  beam: {},        // beam parameters at each component
  timestamp: 0,
  energy: 0
};

// Live virtual-vs-real comparison state: per-motor results, beam results, suggestions, tolerances, score, enabled flag.
var COMPARISON = {
  enabled: false,
  results: {},     // motorId -> {virtual, real, diff, pctDiff, status, severity}
  beamResults: {}, // componentId -> {vH, vV, rH, rV, status}
  overallScore: 100,
  suggestions: [],
  tolerances: {},  // motorId -> absolute tolerance (auto or manual)
  lastUpdate: 0
};

// Default tolerances by unit type
var DEFAULT_TOLERANCES = {
  'mm':     0.005,
  'um':     0.5,
  'mrad':   0.005,
  'deg':    0.002,
  'arcsec': 0.5,
  'Nm':     0.5,
  'keV':    0.01,
  '#':      0.5
};

// Severity thresholds (multiples of tolerance)
var SEV_GOOD = 1.0;     // < 1x tolerance -> green
var SEV_WARN = 3.0;     // 1-3x tolerance -> yellow
var SEV_BAD  = 10.0;    // 3-10x -> orange, >10x -> red

/**
 * Capture virtual state snapshot.
 * Reads all motor values + computes expected beam at each component.
 */
function captureVirtualState(){
  VIRTUAL_STATE.timestamp = Date.now();
  VIRTUAL_STATE.energy = state.energy;
  VIRTUAL_STATE.motors = {};

  // Snapshot all motors
  Object.keys(MOTORS).forEach(function(devId) {
    var dev = MOTORS[devId];
    Object.keys(dev).forEach(function(axKey) {
      var m = dev[axKey];
      if(!m || !m.id) return;
      VIRTUAL_STATE.motors[m.id] = {
        predicted: m.value,
        unit: m.unit,
        pv: m.pv,
        deviceId: devId,
        axisKey: axKey,
        tolerance: COMPARISON.tolerances[m.id] || DEFAULT_TOLERANCES[m.unit] || 0.01
      };
    });
  });

  // Snapshot beam parameters at key positions
  VIRTUAL_STATE.beam = {};
  ['wbslit','m1','dcm','m2','ssa','kbv','kbh','sample'].forEach(function(compId) {
    var comp = CD.find(function(c) { return c.id === compId; });
    if(!comp) return;
    var d = state.positions[compId] || comp.dp;
    var bs = beamAt(d);
    VIRTUAL_STATE.beam[compId] = { h: bs.h, v: bs.v, dist: d };
  });

  // Focal spot
  var sp = focalSpot();
  VIRTUAL_STATE.beam._spot = { h: sp.h, v: sp.v };
  VIRTUAL_STATE.beam._flux = (typeof sampleFlux === 'function') ? sampleFlux() : 0;

  return VIRTUAL_STATE;
}

/**
 * Compare virtual state with real (EPICS) readback values.
 * Returns comparison results with severity grading.
 */
function runComparison(){
  if(EPICS_STATE.mode === 'disconnected') return null;

  captureVirtualState();
  COMPARISON.results = {};
  COMPARISON.suggestions = [];
  var totalScore = 0, nMotors = 0;

  Object.keys(VIRTUAL_STATE.motors).forEach(function(mId) {
    var vs = VIRTUAL_STATE.motors[mId];
    if(!vs.pv) return;

    // Get real value from EPICS
    var pvEntry = PV_REGISTRY[vs.pv];
    var realVal = pvEntry ? pvEntry.value : null;

    if(realVal === null || realVal === undefined){
      COMPARISON.results[mId] = {
        virtual: vs.predicted, real: null,
        diff: null, pctDiff: null,
        status: 'disconnected', severity: 0,
        unit: vs.unit, pv: vs.pv,
        deviceId: vs.deviceId, axisKey: vs.axisKey
      };
      return;
    }

    var diff = Math.abs(realVal - vs.predicted);
    var tol = vs.tolerance;
    var ratio = diff / (tol || 0.001);
    var pctDiff = vs.predicted !== 0 ? (diff / Math.abs(vs.predicted)) * 100 : (diff > 0 ? 100 : 0);

    var status, severity;
    if(ratio < SEV_GOOD)      { status = 'good';    severity = 0; }
    else if(ratio < SEV_WARN) { status = 'warning'; severity = 1; }
    else if(ratio < SEV_BAD)  { status = 'alarm';   severity = 2; }
    else                      { status = 'critical'; severity = 3; }

    COMPARISON.results[mId] = {
      virtual: vs.predicted, real: realVal,
      diff: diff, pctDiff: pctDiff, ratio: ratio,
      status: status, severity: severity, unit: vs.unit, pv: vs.pv,
      tolerance: tol, deviceId: vs.deviceId, axisKey: vs.axisKey
    };

    // Score (100 = perfect, 0 = all critical)
    var mScore = Math.max(0, 100 - ratio * 10);
    totalScore += mScore;
    nMotors++;

    // Generate suggestions for significant discrepancies
    if(severity >= 2){
      var sign = realVal > vs.predicted ? '+' : '';
      COMPARISON.suggestions.push({
        severity: severity,
        motorId: mId,
        pv: vs.pv,
        message: vs.pv + ': d=' + sign + (realVal - vs.predicted).toFixed(4) + ' ' + vs.unit + ' (' + ratio.toFixed(1) + 'x tol)',
        action: 'caput ' + vs.pv + ' ' + vs.predicted.toFixed(6),
        priority: ratio
      });
    }
  });

  COMPARISON.overallScore = nMotors > 0 ? (totalScore / nMotors).toFixed(0) : 100;
  COMPARISON.suggestions.sort(function(a, b) { return b.priority - a.priority; });
  COMPARISON.lastUpdate = Date.now();
  COMPARISON.enabled = true;

  return COMPARISON;
}

/**
 * Get color for severity level.
 */
function severityColor(severity){
  switch(severity){
    case 0: return 'var(--gn)';    // green
    case 1: return 'var(--am)';    // amber
    case 2: return '#ff8040';      // orange
    case 3: return 'var(--rd)';    // red
    default: return 'var(--t3)';   // gray (disconnected)
  }
}

// Map a status string (good/warning/alarm/critical/disconnected) to a short text icon (OK/!/!!/X/o).
function severityLabel(status){
  var labels = { good:'OK', warning:'!', alarm:'!!', critical:'X', disconnected:'o' };
  return labels[status] || '?';
}

// ========================================================================
// SVG Overlay -- Color-code beamline components by comparison severity
// ========================================================================
function updateComparisonOverlay(){
  if(!COMPARISON.enabled) return;

  // Group results by device
  var deviceWorst = {};
  Object.values(COMPARISON.results).forEach(function(r) {
    var dev = r.deviceId;
    if(!deviceWorst[dev] || r.severity > deviceWorst[dev])
      deviceWorst[dev] = r.severity;
  });

  // Apply colors to SVG component groups
  document.querySelectorAll('.comp-g').forEach(function(g) {
    var onclickAttr = g.getAttribute('onclick');
    var match = onclickAttr ? onclickAttr.match(/showComp\('([^']+)'\)/) : null;
    var compId = match ? match[1] : null;
    if(!compId) return;

    // Find matching device
    var comp = CD.find(function(c) { return c.id === compId; });
    if(!comp) return;

    // Map component to device (some are same id, some need mapping)
    var devId = compId; // In most cases, component id = device id
    var sev = deviceWorst[devId];

    if(sev !== undefined && sev >= 1){
      var color = severityColor(sev);
      // Add pulsing ring around component
      var nameEl = g.querySelector('.comp-name');
      if(nameEl) nameEl.style.fill = color;

      // Add comparison indicator dot
      var existingDot = g.querySelector('.cmp-dot');
      if(existingDot) existingDot.remove();

      var bbox = g.getBBox();
      var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', bbox.x + bbox.width - 2);
      dot.setAttribute('cy', bbox.y + 2);
      dot.setAttribute('r', '3');
      dot.setAttribute('fill', color);
      dot.setAttribute('class', 'cmp-dot');
      if(sev >= 2) dot.setAttribute('opacity', '0.8');
      g.appendChild(dot);
    }
  });
}

// Remove all SVG comparison indicator dots and reset component-name fill colors, undoing the severity overlay.
function clearComparisonOverlay(){
  document.querySelectorAll('.cmp-dot').forEach(function(d) { d.remove(); });
  document.querySelectorAll('.comp-name').forEach(function(n) { n.style.fill = ''; });
}

// ========================================================================
// Comparison Panel Rendering
// ========================================================================
function renderComparisonPanel(){
  var panel = document.getElementById('compareBody');
  if(!panel) return;

  if(!COMPARISON.enabled || EPICS_STATE.mode === 'disconnected'){
    panel.innerHTML = '<div style="color:var(--t3);font-size:9px;text-align:center;padding:20px">Enable Sim or Real mode in EPICS tab to compare</div>';
    return;
  }

  runComparison();

  // Overall score bar
  var score = parseInt(COMPARISON.overallScore);
  var scoreColor = score > 90 ? 'var(--gn)' : score > 70 ? 'var(--am)' : 'var(--rd)';

  var h = '<div class="ctrl-group" style="text-align:center;margin:0 0 6px 0">' +
    '<div style="font-size:20px;font-weight:700;color:' + scoreColor + '">' + score + '%</div>' +
    '<div style="font-size:8px;color:var(--t3)">V/R Agreement Score</div>' +
    '<div class="prog-bar" style="margin-top:4px"><div class="prog-fill" style="width:' + score + '%;background:' + scoreColor + '"></div></div>' +
  '</div>';

  // Group by device
  var byDevice = {};
  var resultKeys = Object.keys(COMPARISON.results);
  for(var _ri = 0; _ri < resultKeys.length; _ri++){
    var mId = resultKeys[_ri];
    var r = COMPARISON.results[mId];
    if(!byDevice[r.deviceId]) byDevice[r.deviceId] = [];
    var entry = { mId: mId };
    var rKeys = Object.keys(r);
    for(var _rk = 0; _rk < rKeys.length; _rk++) entry[rKeys[_rk]] = r[rKeys[_rk]];
    byDevice[r.deviceId].push(entry);
  }

  var devIds = Object.keys(byDevice);
  for(var _di = 0; _di < devIds.length; _di++){
    var devId = devIds[_di];
    var motors = byDevice[devId];
    var dev = DEVICE_REGISTRY[devId];
    var label = dev ? dev.label : devId;
    var worstSev = 0;
    for(var _mi = 0; _mi < motors.length; _mi++){
      if(motors[_mi].severity > worstSev) worstSev = motors[_mi].severity;
    }
    var devColor = severityColor(worstSev);

    h += '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">' + label + '</h4>' +
      '<div class="ctrl-group" style="margin:0;border-left:2px solid ' + devColor + '">';

    for(var _mi = 0; _mi < motors.length; _mi++){
      var m = motors[_mi];
      var sColor = severityColor(m.severity);
      var icon = severityLabel(m.status);
      var diffStr = m.diff !== null ? m.diff.toFixed(4) : '--';
      var realStr = m.real !== null ? m.real.toFixed(4) : '--';

      h += '<div style="display:flex;align-items:center;gap:4px;font-size:8px;font-family:var(--mn);padding:1px 0;border-bottom:1px solid var(--b0)">' +
        '<span style="color:' + sColor + ';width:10px;text-align:center">' + icon + '</span>' +
        '<span style="color:var(--t2);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">' + m.axisKey + '</span>' +
        '<span style="color:var(--ac);width:52px;text-align:right">' + m.virtual.toFixed(3) + '</span>' +
        '<span style="color:var(--t3);width:8px;text-align:center">|</span>' +
        '<span style="color:' + sColor + ';width:52px;text-align:right">' + realStr + '</span>' +
        '<span style="color:' + sColor + ';width:40px;text-align:right;font-size:8px">' + (m.status === 'disconnected' ? '' : 'd' + diffStr) + '</span>' +
      '</div>';
    }
    h += '</div></div>';
  }

  // Suggestions
  if(COMPARISON.suggestions.length > 0){
    h += '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">SUGGESTIONS</h4>' +
      '<div class="ctrl-group" style="margin:0;border-left:2px solid var(--am)">';
    var sugSlice = COMPARISON.suggestions.slice(0, 5);
    for(var _si = 0; _si < sugSlice.length; _si++){
      var s = sugSlice[_si];
      h += '<div class="sug" style="font-size:8px;padding:3px 6px;margin:2px 0">' +
        '<div style="color:' + severityColor(s.severity) + '">' + s.message + '</div>' +
        '<div style="color:var(--t3);margin-top:1px;cursor:pointer" onclick="navigator.clipboard.writeText(\'' + s.action + '\')">-> ' + s.action + ' <span style="font-size:8px;opacity:.5">(click to copy)</span></div>' +
      '</div>';
    }
    h += '</div></div>';
  }

  // Legend
  h += '<div style="display:flex;gap:6px;font-size:8px;color:var(--t3-bright);padding:4px;justify-content:center">' +
    '<span>OK Good</span> <span style="color:var(--am)">! Warn</span>' +
    '<span style="color:#ff8040">!! Alarm</span> <span style="color:var(--rd)">X Critical</span>' +
  '</div>';

  panel.innerHTML = h;
  updateComparisonOverlay();
}

// ========================================================================
// Tolerance Configuration
// ========================================================================

/**
 * Set custom tolerance for a motor.
 * Example: setTolerance('m1_pitch', 0.001)  -- 1 urad tolerance
 */
function setTolerance(motorId, tolerance){
  COMPARISON.tolerances[motorId] = tolerance;
  log('info', 'Tolerance ' + motorId + ' -> ' + tolerance);
}

/**
 * Set tolerance for all axes of a device.
 */
function setDeviceTolerance(deviceId, tolerance){
  var grp = MOTORS[deviceId];
  if(!grp) return;
  Object.values(grp).forEach(function(m) {
    if(m && m.id) COMPARISON.tolerances[m.id] = tolerance;
  });
  log('info', 'Device tolerance ' + deviceId + ' -> ' + tolerance);
}

/**
 * Auto-compute tolerances from noise floor (requires data).
 * Reads current jitter from SimIOC or real readback.
 */
function autoCalibrateTolerance(nSamples){
  if(nSamples === undefined) nSamples = 20;
  if(EPICS_STATE.mode === 'disconnected'){ log('warn','Connect EPICS first'); return; }

  log('info', 'Auto-calibrating tolerances (' + nSamples + ' samples)...');
  var samples = {};

  var count = 0;
  var timer = setInterval(function() {
    Object.keys(VIRTUAL_STATE.motors).forEach(function(mId) {
      var vs = VIRTUAL_STATE.motors[mId];
      if(!vs.pv) return;
      var pvEntry = PV_REGISTRY[vs.pv];
      if(!pvEntry) return;
      if(!samples[mId]) samples[mId] = [];
      samples[mId].push(pvEntry.value);
    });
    count++;
    if(count >= nSamples){
      clearInterval(timer);
      // Compute std dev -> tolerance = 3sigma
      var sKeys = Object.keys(samples);
      for(var _sk = 0; _sk < sKeys.length; _sk++){
        var mId = sKeys[_sk];
        var vals = samples[mId];
        if(vals.length < 5) continue;
        var mean = vals.reduce(function(a,b) { return a+b; }, 0) / vals.length;
        var variance = vals.reduce(function(a,b) { return a + Math.pow((b-mean), 2); }, 0) / vals.length;
        var std = Math.sqrt(variance);
        var vsMotor = VIRTUAL_STATE.motors[mId];
        var tol = Math.max(std * 3, DEFAULT_TOLERANCES[vsMotor ? vsMotor.unit : ''] || 0.001);
        COMPARISON.tolerances[mId] = tol;
      }
      log('info', 'Tolerances calibrated for ' + Object.keys(samples).length + ' motors');
    }
  }, 200);
}

// ========================================================================
// Comparison mode switching (integrated with EPICS modes)
// ========================================================================

/**
 * Enable/disable live comparison.
 */
var comparisonTimer = null;

// Enable comparison, capture virtual state, and start a 2s timer that re-runs the diff and re-renders the panel.
function startComparison(){
  COMPARISON.enabled = true;
  captureVirtualState();
  comparisonTimer = setInterval(function() {
    runComparison();
    var panel = document.getElementById('compareBody');
    if(panel && panel.offsetParent !== null) requestAnimationFrame(function(){ renderComparisonPanel(); });
  }, 2000);
  log('info', 'V/R comparison started (2s interval)');
}

// Disable comparison, clear the 2s interval timer, and remove the SVG severity overlay.
function stopComparison(){
  COMPARISON.enabled = false;
  if(comparisonTimer){ clearInterval(comparisonTimer); comparisonTimer = null; }
  clearComparisonOverlay();
  log('info', 'V/R comparison stopped');
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof COMPARISON!=="undefined")globalThis.COMPARISON=COMPARISON;
if(typeof DEFAULT_TOLERANCES!=="undefined")globalThis.DEFAULT_TOLERANCES=DEFAULT_TOLERANCES;
if(typeof SEV_BAD!=="undefined")globalThis.SEV_BAD=SEV_BAD;
if(typeof SEV_GOOD!=="undefined")globalThis.SEV_GOOD=SEV_GOOD;
if(typeof SEV_WARN!=="undefined")globalThis.SEV_WARN=SEV_WARN;
if(typeof VIRTUAL_STATE!=="undefined")globalThis.VIRTUAL_STATE=VIRTUAL_STATE;
if(typeof autoCalibrateTolerance!=="undefined")globalThis.autoCalibrateTolerance=autoCalibrateTolerance;
if(typeof captureVirtualState!=="undefined")globalThis.captureVirtualState=captureVirtualState;
if(typeof clearComparisonOverlay!=="undefined")globalThis.clearComparisonOverlay=clearComparisonOverlay;
if(typeof comparisonTimer!=="undefined")globalThis.comparisonTimer=comparisonTimer;
if(typeof renderComparisonPanel!=="undefined")globalThis.renderComparisonPanel=renderComparisonPanel;
if(typeof runComparison!=="undefined")globalThis.runComparison=runComparison;
if(typeof setDeviceTolerance!=="undefined")globalThis.setDeviceTolerance=setDeviceTolerance;
if(typeof setTolerance!=="undefined")globalThis.setTolerance=setTolerance;
if(typeof severityColor!=="undefined")globalThis.severityColor=severityColor;
if(typeof severityLabel!=="undefined")globalThis.severityLabel=severityLabel;
if(typeof startComparison!=="undefined")globalThis.startComparison=startComparison;
if(typeof stopComparison!=="undefined")globalThis.stopComparison=stopComparison;
if(typeof updateComparisonOverlay!=="undefined")globalThis.updateComparisonOverlay=updateComparisonOverlay;
