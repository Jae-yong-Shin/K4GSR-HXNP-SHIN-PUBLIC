// ===== PHASE 3: Bluesky Queue Server & Plan Execution =====
// ===== bluesky.js — Bluesky Queue Server & Plan Execution Engine =====
// @module bluesky/01_queue
// @exports PLAN_LIBRARY, PlanExecutor, QS_CONFIG, QUEUE, _LOCAL_ONLY_PLANS, _SIM_PLAN_MAP, _buildSimParams, _extractDataPoint, _handleQueueSimResponse, _handleQueueSimResult, _latencyLog, _mapPlanParams, _queueSimActive, _queueSimLiveData, _queueSimMapData, ...
// Korea-4GSR ID10 NanoProbe v4.36 — Phase 3
'use strict';

// ============================================================
//  1. QUEUE SERVER CLIENT (SimQS / Real QS via REST)
// ============================================================

var QS_CONFIG = {
  url: 'http://localhost:60610',   // bluesky-queueserver default
  pollInterval: 1000,              // ms
  connected: false,
  simMode: true                    // true = browser-simulated QS
};

var QUEUE = {
  items: [],          // queued plans
  running: null,      // currently executing plan
  history: [],        // completed plans
  status: 'idle',     // idle | running | paused | error
  autostart: false,
  workerState: 'idle', // idle | executing_plan | paused
  _suppressPanel: false // when true, skip Bluesky bottom panel + tab switch
};

var qsPollTimer = null;

// --- Queue Operations ---
function queuePlan(planName, params, meta) {
  if (params === undefined) params = {};
  if (meta === undefined) meta = {};
  var metaCopy = {};
  var mk;
  for (mk in meta) { if (meta.hasOwnProperty(mk)) metaCopy[mk] = meta[mk]; }
  metaCopy.submitted = new Date().toISOString();
  metaCopy.source = 'virtual_bl';
  var item = {
    item_uid: 'plan_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
    name: planName,
    kwargs: params,
    meta: metaCopy,
    status: 'queued'
  };
  QUEUE.items.push(item);
  log('info', 'Plan queued: ' + planName + ' [' + item.item_uid.slice(-6) + ']');
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
  return item;
}

function queueRemove(uid) {
  var idx = -1;
  for (var i = 0; i < QUEUE.items.length; i++) { if (QUEUE.items[i].item_uid === uid) { idx = i; break; } }
  if (idx >= 0) {
    var removed = QUEUE.items.splice(idx, 1)[0];
    log('info', 'Plan removed: ' + removed.name);
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
    return true;
  }
  return false;
}

function queueMoveUp(uid) {
  var idx = -1;
  for (var i = 0; i < QUEUE.items.length; i++) { if (QUEUE.items[i].item_uid === uid) { idx = i; break; } }
  if (idx > 0) { var tmp = QUEUE.items[idx - 1]; QUEUE.items[idx - 1] = QUEUE.items[idx]; QUEUE.items[idx] = tmp; }
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
}

function queueMoveDown(uid) {
  var idx = -1;
  for (var i = 0; i < QUEUE.items.length; i++) { if (QUEUE.items[i].item_uid === uid) { idx = i; break; } }
  if (idx >= 0 && idx < QUEUE.items.length - 1) { var tmp = QUEUE.items[idx]; QUEUE.items[idx] = QUEUE.items[idx + 1]; QUEUE.items[idx + 1] = tmp; }
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
}

function queueClear() {
  QUEUE.items = [];
  log('info', 'Queue cleared');
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
}

// --- Queue Execution Control ---
// [DDD merged from 11:1912-1925 fixBSQueue — v419 canonical, supersedes Phase 3 base]
function queueStart() {
  // Skip if startExperiment() already running (NLP sends redundant queueStart)
  if (QUEUE._exptRunning) { QUEUE._exptRunning = false; return; }
  if (!QUEUE._suppressPanel && typeof toggleBsPanel === 'function') toggleBsPanel(true);
  QUEUE.autostart = true;
  // FIX: If not currently running a plan, always start processing
  if (!QUEUE.running) {
    QUEUE.status = 'running';
    log('info', 'Queue started');
    processNextPlan();
  } else {
    QUEUE.status = 'running';
    log('info', 'Queue: already running a plan');
  }
}

function queueStop() {
  QUEUE.autostart = false;
  if (QUEUE.status === 'running' && !QUEUE.running) QUEUE.status = 'idle';
  log('info', 'Queue stopped — autostart OFF');
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
}

function queuePause() {
  if (QUEUE.running && QUEUE.running._executor) {
    QUEUE.status = 'paused';
    QUEUE.workerState = 'paused';
    log('warn', 'Queue paused');
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
  }
}

function queueResume() {
  if (QUEUE.status === 'paused') {
    QUEUE.status = 'running';
    QUEUE.workerState = 'executing_plan';
    log('info', 'Queue resumed');
    if (QUEUE.running && QUEUE.running._executor) QUEUE.running._executor.resume();
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
  }
}

function queueAbort() {
  if (QUEUE.running && QUEUE.running._executor) {
    QUEUE.running._executor.abort();
    QUEUE.running.status = 'aborted';
    QUEUE.history.push(QUEUE.running);
    QUEUE.running = null;
    QUEUE.status = QUEUE.autostart ? 'running' : 'idle';
    QUEUE.workerState = 'idle';
    QUEUE._suppressPanel = false;
    log('err', 'Plan aborted');
    if (QUEUE.autostart) processNextPlan();
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
  }
}

// [DDD merged from 11:1869-1910 fixBSQueue — v419 canonical with queue-empty fix]
function processNextPlan() {
  if (!QUEUE._suppressPanel && typeof toggleBsPanel === 'function') toggleBsPanel(true);
  if (QUEUE.items.length === 0) {
    // FIX: Always set idle when no items, regardless of autostart
    QUEUE.status = 'idle';
    QUEUE.workerState = 'idle';
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
    return;
  }
  if (!QUEUE.autostart) {
    QUEUE.status = 'idle';
    QUEUE.workerState = 'idle';
    if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
    return;
  }

  var item = QUEUE.items.shift();
  QUEUE.running = item;
  item.status = 'running';
  item.startTime = new Date().toISOString();
  QUEUE.workerState = 'executing_plan';
  if (typeof renderBlueskyTab === 'function') renderBlueskyTab();

  executePlan(item).then(function(result) {
    item.status = result.success ? 'completed' : 'failed';
    item.endTime = new Date().toISOString();
    item.result = result;
    QUEUE.history.unshift(item);
    if (QUEUE.history.length > 50) QUEUE.history.pop();
    QUEUE.running = null;
    QUEUE.workerState = 'idle';
    QUEUE._suppressPanel = false;
    log(result.success ? 'info' : 'err', 'Plan ' + item.name + ': ' + item.status);

    if (QUEUE.autostart && QUEUE.items.length > 0) {
      setTimeout(processNextPlan, 200);
    } else {
      QUEUE.status = 'idle';
      if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
    }
  });
}

// ============================================================
//  2. PLAN LIBRARY — Virtual Beamline Plans
// ============================================================

var PLAN_LIBRARY = {
  // --- Energy Scan (count at each energy) ---
  energy_scan: {
    name: 'energy_scan',
    label: 'Energy Scan',
    description: 'Scan DCM energy and measure flux at each point',
    category: 'scan',
    params: {
      start: { type: 'number', default: 8, unit: 'keV', label: 'Start Energy' },
      stop:  { type: 'number', default: 12, unit: 'keV', label: 'Stop Energy' },
      num:   { type: 'number', default: 50, unit: 'pts', label: 'Num Points' },
      dwell: { type: 'number', default: 0.5, unit: 's', label: 'Dwell Time' }
    },
    detectors: ['ion_chamber', 'sdd'],
    motors: ['dcm_theta']
  },

  // --- XANES Scan ---
  xanes_scan: {
    name: 'xanes_scan',
    label: 'XANES Scan',
    description: 'Energy scan around absorption edge (pre-edge, edge, EXANES)',
    category: 'scan',
    params: {
      element: { type: 'select', options: ['Fe','Cu','Ni','Ti','Au','Pt'], default: 'Cu', label: 'Element' },
      edge:    { type: 'select', options: ['K','L3'], default: 'K', label: 'Edge' },
      pre_start: { type: 'number', default: -150, unit: 'eV', label: 'Pre-edge Start' },
      pre_stop:  { type: 'number', default: -30, unit: 'eV', label: 'Pre-edge Stop' },
      pre_step:  { type: 'number', default: 5, unit: 'eV', label: 'Pre-edge Step' },
      edge_step: { type: 'number', default: 0.5, unit: 'eV', label: 'Edge Step' },
      k_max:     { type: 'number', default: 12, unit: 'A-1', label: 'k_max' },
      k_step:    { type: 'number', default: 0.05, unit: 'A-1', label: 'k Step' }
    },
    detectors: ['ion_chamber', 'sdd'],
    motors: ['dcm_theta']
  },

  // --- Alignment Scan ---
  align_motor: {
    name: 'align_motor',
    label: 'Motor Alignment Scan',
    description: 'Scan specified motor to find optimal position (Gaussian fitting)',
    category: 'alignment',
    params: {
      motor:  { type: 'select', options: ['m1_pitch','m2_pitch','kbv_pitch','kbh_pitch','dcm_chi1'], default: 'm1_pitch', label: 'Motor' },
      start:  { type: 'number', default: -0.1, unit: 'rel', label: 'Rel. Start' },
      stop:   { type: 'number', default: 0.1, unit: 'rel', label: 'Rel. Stop' },
      num:    { type: 'number', default: 31, unit: 'pts', label: 'Num Points' }
    },
    detectors: ['ion_chamber'],
    motors: ['$motor']  // dynamic
  },

  // --- Auto-Alignment (beam path order: M1->DCM->M2->SSA->KB) ---
  auto_align: {
    name: 'auto_align',
    label: 'Auto Alignment',
    description: 'Sequential optics alignment along beam path (M1->DCM->M2->SSA->KB)',
    category: 'alignment',
    params: {},
    detectors: ['xbpm_m1', 'xbpm1', 'xbpm_m2', 'xbpm_ssa', 'xbpm3'],
    motors: ['m1_pitch', 'dcm_dTheta2', 'm2_pitch', 'ssa_hcen', 'kbv_pitch']
  },

  // --- Sample Raster Scan ---
  raster_scan: {
    name: 'raster_scan',
    label: 'Raster Map',
    description: 'X-Y raster scan of sample for fluorescence/diffraction mapping',
    category: 'imaging',
    params: {
      x_start: { type: 'number', default: -5, unit: 'um', label: 'X Start' },
      x_stop:  { type: 'number', default: 5, unit: 'um', label: 'X Stop' },
      x_num:   { type: 'number', default: 21, unit: 'pts', label: 'X Points' },
      y_start: { type: 'number', default: -5, unit: 'um', label: 'Y Start' },
      y_stop:  { type: 'number', default: 5, unit: 'um', label: 'Y Stop' },
      y_num:   { type: 'number', default: 21, unit: 'pts', label: 'Y Points' },
      dwell:   { type: 'number', default: 0.1, unit: 's', label: 'Dwell Time' }
    },
    detectors: ['sdd', 'ccd'],
    motors: ['sample_x', 'sample_y']
  },

  // --- Count (single shot) ---
  count: {
    name: 'count',
    label: 'Single Measurement',
    description: 'Measure at current position for specified duration',
    category: 'utility',
    params: {
      num:   { type: 'number', default: 1, unit: '', label: 'Num Counts' },
      dwell: { type: 'number', default: 1, unit: 's', label: 'Dwell Time' }
    },
    detectors: ['ion_chamber', 'sdd'],
    motors: []
  },

  // --- Fly Scan (continuous motion) ---
  fly_scan: {
    name: 'fly_scan',
    label: 'Continuous Scan (Fly)',
    description: 'Continuous motor motion with high-speed data acquisition',
    category: 'scan',
    params: {
      motor: { type: 'select', options: ['sample_x','sample_y','dcm_theta'], default: 'sample_x', label: 'Motor' },
      start: { type: 'number', default: -10, unit: '', label: 'Start' },
      stop:  { type: 'number', default: 10, unit: '', label: 'Stop' },
      speed: { type: 'number', default: 1, unit: '/s', label: 'Speed' }
    },
    detectors: ['sdd'],
    motors: ['$motor']
  },

  // --- Undulator Gap Optimization ---
  gap_optimize: {
    name: 'gap_optimize',
    label: 'Gap Optimization',
    description: 'Fine-tune IVU gap at current energy to maximize flux',
    category: 'optimization',
    params: {
      range: { type: 'number', default: 0.5, unit: 'mm', label: 'Search Range' },
      num:   { type: 'number', default: 21, unit: 'pts', label: 'Num Points' }
    },
    detectors: ['ion_chamber'],
    motors: ['ivu_gap']
  },

  // --- Auto-Tune (iterative centroid alignment) ---
  auto_tune: {
    name: 'auto_tune',
    label: 'Auto Tuning',
    description: 'Iterative centroid alignment -- auto-track peak and narrow range',
    category: 'alignment',
    params: {
      device: { type: 'select', options: ['m1','m2','kbv','kbh','dcm'], default: 'm1', label: 'Device' },
      axis:   { type: 'select', options: ['pitch','roll','y','x','theta','chi2'], default: 'pitch', label: 'Axis' },
      start:  { type: 'number', default: -0.1, unit: '', label: 'Start (abs)' },
      stop:   { type: 'number', default: 0.1, unit: '', label: 'Stop (abs)' },
      min_step: { type: 'number', default: 0.001, unit: '', label: 'Min Step' },
      num:    { type: 'number', default: 21, unit: 'pts', label: 'Num Points' }
    },
    detectors: ['ion_chamber'],
    motors: ['$device.$axis']
  },

  // --- Adaptive Energy Scan ---
  adaptive_energy_scan: {
    name: 'adaptive_energy_scan',
    label: 'Adaptive Energy Scan',
    description: 'Adaptive step size near absorption edge -- rate-of-change based',
    category: 'scan',
    params: {
      e_start:     { type: 'number', default: 8.9, unit: 'keV', label: 'Start Energy' },
      e_stop:      { type: 'number', default: 9.1, unit: 'keV', label: 'Stop Energy' },
      min_step_eV: { type: 'number', default: 0.1, unit: 'eV', label: 'Min Step' },
      max_step_eV: { type: 'number', default: 5.0, unit: 'eV', label: 'Max Step' },
      target_delta:{ type: 'number', default: 0.2, unit: '', label: 'Target Delta' }
    },
    detectors: ['ion_chamber'],
    motors: ['dcm_theta']
  },

  // --- Relative Alignment Scan ---
  rel_alignment_scan: {
    name: 'rel_alignment_scan',
    label: 'Relative Alignment Scan',
    description: 'Alignment scan within +/-width/2 of current position (no absolute coords needed)',
    category: 'alignment',
    params: {
      device: { type: 'select', options: ['m1','m2','kbv','kbh','dcm'], default: 'm1', label: 'Device' },
      axis:   { type: 'select', options: ['pitch','roll','y','x','theta','chi2'], default: 'pitch', label: 'Axis' },
      width:  { type: 'number', default: 0.2, unit: '', label: 'Scan Width' },
      num:    { type: 'number', default: 21, unit: 'pts', label: 'Num Points' }
    },
    detectors: ['ion_chamber'],
    motors: ['$device.$axis']
  },

  // --- Fermat Spiral Scan ---
  fermat_scan: {
    name: 'fermat_scan',
    label: 'Fermat Spiral Scan',
    description: 'Efficient 2D mapping -- uniform coverage via Fermat spiral',
    category: 'imaging',
    params: {
      x_range: { type: 'number', default: 10, unit: 'um', label: 'X Range' },
      y_range: { type: 'number', default: 10, unit: 'um', label: 'Y Range' },
      dr:      { type: 'number', default: 0.5, unit: 'um', label: 'Radial Step (dr)' },
      factor:  { type: 'number', default: 1.0, unit: '', label: 'Density Factor' }
    },
    detectors: ['sdd', 'ion_chamber'],
    motors: ['sample_x', 'sample_y']
  },

  // --- Relative Raster Scan ---
  rel_raster_scan: {
    name: 'rel_raster_scan',
    label: 'Relative Raster Scan',
    description: 'Raster map within +/-dx/2, +/-dy/2 of current position',
    category: 'imaging',
    params: {
      dx:  { type: 'number', default: 10, unit: 'um', label: 'X Full Width' },
      dy:  { type: 'number', default: 10, unit: 'um', label: 'Y Full Width' },
      nx:  { type: 'number', default: 21, unit: 'pts', label: 'X Points' },
      ny:  { type: 'number', default: 21, unit: 'pts', label: 'Y Points' }
    },
    detectors: ['sdd', 'ccd'],
    motors: ['sample_x', 'sample_y']
  }
};

// ============================================================
//  3. PLAN EXECUTOR — Browser-Side Simulation Engine
// ============================================================

function PlanExecutor(item) {
  this.item = item;
  this.plan = PLAN_LIBRARY[item.name];
  var planParams = (this.plan && this.plan.params) ? this.plan.params : {};
  var kwParams = item.kwargs || {};
  this.params = {};
  var pk;
  for (pk in planParams) { if (planParams.hasOwnProperty(pk)) this.params[pk] = planParams[pk]; }
  for (pk in kwParams) { if (kwParams.hasOwnProperty(pk)) this.params[pk] = kwParams[pk]; }
  this.aborted = false;
  this.paused = false;
  this.progress = 0;
  this.data = [];          // collected data points
  this.liveData = [];      // for real-time chart
  this.startTime = Date.now();
  this._resolveWait = null;
}

PlanExecutor.prototype.abort = function() { this.aborted = true; if (this._resolveWait) this._resolveWait(); };
PlanExecutor.prototype.resume = function() { this.paused = false; if (this._resolveWait) this._resolveWait(); };

PlanExecutor.prototype.wait = function(ms) {
  var self = this;
  if (self.aborted) return Promise.resolve();
  function waitForUnpause() {
    if (!self.paused || self.aborted) return Promise.resolve();
    return new Promise(function(r) { self._resolveWait = r; setTimeout(r, 200); }).then(function() {
      if (self.paused && !self.aborted) return waitForUnpause();
      return Promise.resolve();
    });
  }
  return waitForUnpause().then(function() {
    if (self.aborted) return Promise.resolve();
    return new Promise(function(r) { self._resolveWait = r; setTimeout(r, ms); });
  });
};

PlanExecutor.prototype.updateProgress = function(pct) {
  this.progress = pct;
  var progEl = document.getElementById('bsPlanProgress');
  if (progEl) progEl.style.width = pct.toFixed(0) + '%';
  var pctEl = document.getElementById('bsPlanPct');
  if (pctEl) pctEl.textContent = pct.toFixed(0) + '%';
};

PlanExecutor.prototype.emitPoint = function(point) {
  this.data.push(point);
  this.liveData.push(point);
  // Update live chart
  if (typeof updateBsLiveChart === 'function') updateBsLiveChart(this.liveData, this.item.name);
};

PlanExecutor.prototype.execute = function() {
  var self = this;
  var p = self.item.kwargs || {};
  try {
    // Only LOCAL_ONLY plans reach PlanExecutor — measurement plans are routed
    // to simulation server via executeSimPlan() and never arrive here.
    // @mode virtual: alignment uses MC ray tracing (mcSig)
    // @mode real: alignment will use actual BPM/ion chamber readback via EPICS
    switch (self.item.name) {
      case 'align_motor':        return self.runAlignScan(p);
      case 'auto_align':         return self.runAutoAlign(p);
      case 'count':              return self.runCount(p);
      case 'gap_optimize':       return self.runGapOptimize(p);
      case 'auto_tune':          return self.runAutoTune(p);
      case 'rel_alignment_scan': return self.runRelAlignScan(p);
      default:
        return Promise.resolve({ success: false, msg: 'Unknown plan: ' + self.item.name + '. Measurement plans require simulation server.' });
    }
  } catch (e) {
    return Promise.resolve({ success: false, msg: e.message });
  }
};

// --- Alignment Motor Scan ---
PlanExecutor.prototype.runAlignScan = function(p) {
  var self = this;
  var motorId = p.motor || 'm1_pitch';
  var relStart = p.start || -0.1, relStop = p.stop || 0.1;
  var num = p.num || 31;
  var motorMap = { 'm1_pitch': 'm1pitch', 'm2_pitch': 'm2pitch', 'kbv_pitch': 'kbvPitch', 'kbh_pitch': 'kbhPitch' };
  var stKey = motorMap[motorId] || 'm1pitch';
  var _nomPitchMap = { 'm1pitch': 2.5, 'm2pitch': 2.5, 'kbvPitch': 3.0, 'kbhPitch': 3.0 };
  var center = state[stKey] || _nomPitchMap[stKey] || 2.5;
  var step = (relStop - relStart) / (num - 1);
  var bestVal = center, bestSignal = -Infinity;
  var idx = 0;
  // MC detector position: map motor to downstream BPM/detector
  var _detMap = { 'm1pitch': 'xbpm_m1', 'm2pitch': 'xbpm_m2', 'kbvPitch': 'det', 'kbhPitch': 'det' };
  var _detId = _detMap[stKey] || 'det';
  var _detDist = (typeof pos === 'function') ? pos(_detId) : 150;

  function doStep() {
    if (idx >= num) {
      state[stKey] = bestVal;
      log('info', 'Align ' + motorId + ': best = ' + bestVal.toFixed(4));
      return Promise.resolve({ success: true, msg: 'Optimum: ' + bestVal.toFixed(4), data: self.data, bestVal: bestVal });
    }
    if (self.aborted) return Promise.resolve({ success: false, msg: 'Aborted' });
    var scanPos = center + relStart + idx * step;
    state[stKey] = scanPos;
    if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
    return self.wait(6).then(function() {
      var signal = (typeof mcSig === 'function') ? mcSig(_detDist) : 0;
      if (signal > bestSignal) { bestSignal = signal; bestVal = scanPos; }
      self.emitPoint({ x: scanPos, y: signal, xlabel: motorId, ylabel: 'MC Flux' });
      self.updateProgress(((idx + 1) / num) * 100);
      idx++;
      return doStep();
    });
  }
  return doStep();
};

// --- Auto-Alignment: delegate to unified runFullAlignment orchestrator ---
PlanExecutor.prototype.runAutoAlign = function(p) {
  var self = this;
  log('info', 'Auto-Align: delegating to runFullAlignment()');
  self.updateProgress(10);
  try {
    var result = runFullAlignment();
    if (result && typeof result.then === 'function') {
      return result.then(function() {
        self.updateProgress(100);
        return { success: true, msg: 'Auto-align complete (full sequence)' };
      });
    }
    self.updateProgress(100);
    return Promise.resolve({ success: true, msg: 'Auto-align complete (full sequence)' });
  } catch (e) {
    log('err', 'Auto-Align failed: ' + e.message);
    return Promise.resolve({ success: false, msg: 'Auto-align error: ' + e.message });
  }
};

// --- Count ---
PlanExecutor.prototype.runCount = function(p) {
  var self = this;
  var num = p.num || 1, dwell = p.dwell || 1;
  var i = 0;

  function doStep() {
    if (i >= num) return Promise.resolve({ success: true, msg: num + ' counts done', data: self.data });
    if (self.aborted) return Promise.resolve({ success: false, msg: 'Aborted' });
    return self.wait(dwell * 100).then(function() {
      var ct = (typeof mcSig === 'function') ? mcSig((typeof pos === 'function') ? pos('det') : 150) : 0;
      ct = ct * dwell;
      self.emitPoint({ x: i + 1, y: ct, xlabel: 'Count #', ylabel: 'MC Counts' });
      self.updateProgress(((i + 1) / num) * 100);
      i++;
      return doStep();
    });
  }
  return doStep();
};

// --- Gap Optimize ---
PlanExecutor.prototype.runGapOptimize = function(p) {
  var self = this;
  var range = p.range || 0.5, num = p.num || 21;
  var center = state.gap || 7.0;
  var step = (2 * range) / (num - 1);
  var bestGap = center, bestFlux = -Infinity;
  var i = 0;

  function doStep() {
    if (i >= num) {
      state.gap = bestGap;
      if (typeof updateUnd === 'function') updateUnd(bestGap);
      var el = document.getElementById('gapSlider');
      if (el) el.value = bestGap;
      log('info', 'Gap optimized: ' + bestGap.toFixed(3) + ' mm');
      return Promise.resolve({ success: true, msg: 'Optimal gap: ' + bestGap.toFixed(3) + ' mm', data: self.data, bestGap: bestGap });
    }
    if (self.aborted) return Promise.resolve({ success: false, msg: 'Aborted' });
    var gap = center - range + i * step;
    state.gap = gap;
    if (typeof updateUnd === 'function') updateUnd(gap);
    return self.wait(10).then(function() {
      if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
      var flux = (typeof mcSig === 'function') ? mcSig((typeof pos === 'function') ? pos('det') : 150) : 0;
      if (flux > bestFlux) { bestFlux = flux; bestGap = gap; }
      self.emitPoint({ x: gap, y: flux, xlabel: 'Gap (mm)', ylabel: 'MC Flux' });
      self.updateProgress(((i + 1) / num) * 100);
      i++;
      return doStep();
    });
  }
  return doStep();
};

// --- Auto-Tune (iterative centroid, MC-based) ---
PlanExecutor.prototype.runAutoTune = function(p) {
  var self = this;
  var device = p.device || 'm1', axis = p.axis || 'pitch';
  var motorMap = { 'm1_pitch': 'm1pitch', 'm2_pitch': 'm2pitch', 'kbv_pitch': 'kbvPitch', 'kbh_pitch': 'kbhPitch' };
  var stKey = motorMap[device + '_' + axis] || 'm1pitch';
  var _nomPitchMap2 = { 'm1pitch': 2.5, 'm2pitch': 2.5, 'kbvPitch': 3.0, 'kbhPitch': 3.0 };
  var center = state[stKey] || _nomPitchMap2[stKey] || 2.5;
  var lo = p.start != null ? p.start : center - 0.1;
  var hi = p.stop != null ? p.stop : center + 0.1;
  var minStep = p.min_step || 0.001;
  var num = p.num || 21;
  var iteration = 0;
  // MC detector position
  var _detMap2 = { 'm1pitch': 'xbpm_m1', 'm2pitch': 'xbpm_m2', 'kbvPitch': 'det', 'kbhPitch': 'det' };
  var _detId2 = _detMap2[stKey] || 'det';
  var _detDist2 = (typeof pos === 'function') ? pos(_detId2) : 150;

  function doIteration() {
    if (!((hi - lo) > minStep * 2 && iteration < 5)) {
      state[stKey] = (lo + hi) / 2;
      if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
      log('info', 'AutoTune ' + device + ':' + axis + ': ' + state[stKey].toFixed(4) + ' (' + iteration + ' iters)');
      return Promise.resolve({ success: true, msg: 'Tuned to ' + state[stKey].toFixed(4) + ' (' + iteration + ' iters)', data: self.data });
    }
    iteration++;
    var step = (hi - lo) / (num - 1);
    var bestPos = lo, bestSig = -Infinity;
    var i = 0;

    function doStep() {
      if (i >= num) {
        var halfW = (hi - lo) / 6;
        lo = bestPos - halfW;
        hi = bestPos + halfW;
        self.updateProgress(iteration * 20);
        return doIteration();
      }
      if (self.aborted) return Promise.resolve({ success: false, msg: 'Aborted' });
      var scanPos = lo + i * step;
      state[stKey] = scanPos;
      if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
      var signal = (typeof mcSig === 'function') ? mcSig(_detDist2) : 0;
      if (signal > bestSig) { bestSig = signal; bestPos = scanPos; }
      self.emitPoint({ x: scanPos, y: signal, xlabel: device + ':' + axis + ' iter' + iteration, ylabel: 'MC Flux' });
      i++;
      return self.wait(3).then(doStep);
    }
    return doStep();
  }
  return doIteration();
};

// --- Relative Alignment Scan (MC-based) ---
PlanExecutor.prototype.runRelAlignScan = function(p) {
  var self = this;
  var device = p.device || 'm1', axis = p.axis || 'pitch';
  var motorMap = { 'm1_pitch': 'm1pitch', 'm2_pitch': 'm2pitch', 'kbv_pitch': 'kbvPitch', 'kbh_pitch': 'kbhPitch' };
  var stKey = motorMap[device + '_' + axis] || 'm1pitch';
  var _nomPitchMap3 = { 'm1pitch': 2.5, 'm2pitch': 2.5, 'kbvPitch': 3.0, 'kbhPitch': 3.0 };
  var center = state[stKey] || _nomPitchMap3[stKey] || 2.5;
  var half = (p.width || 0.2) / 2;
  var num = p.num || 21;
  var step = (2 * half) / (num - 1);
  var bestPos = center, bestSig = -Infinity;
  var i = 0;
  // MC detector position
  var _detMap3 = { 'm1pitch': 'xbpm_m1', 'm2pitch': 'xbpm_m2', 'kbvPitch': 'det', 'kbhPitch': 'det' };
  var _detId3 = _detMap3[stKey] || 'det';
  var _detDist3 = (typeof pos === 'function') ? pos(_detId3) : 150;

  function doStep() {
    if (i >= num) {
      state[stKey] = bestPos;
      if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
      return Promise.resolve({ success: true, msg: 'Rel-align: best=' + bestPos.toFixed(4), data: self.data });
    }
    if (self.aborted) return Promise.resolve({ success: false, msg: 'Aborted' });
    var scanPos = center - half + i * step;
    state[stKey] = scanPos;
    if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
    return self.wait(5).then(function() {
      var signal = (typeof mcSig === 'function') ? mcSig(_detDist3) : 0;
      if (signal > bestSig) { bestSig = signal; bestPos = scanPos; }
      self.emitPoint({ x: scanPos, y: signal, xlabel: device + ':' + axis, ylabel: 'MC Flux' });
      self.updateProgress(((i + 1) / num) * 100);
      i++;
      return doStep();
    });
  }
  return doStep();
};

// --- Main executor ---
// Measurement plans (scans, XANES, raster, etc.) MUST use the server engine.
// Only alignment/utility plans can run locally via PlanExecutor.
var _LOCAL_ONLY_PLANS = {
  'align_motor': true, 'auto_align': true, 'gap_optimize': true,
  'auto_tune': true, 'rel_alignment_scan': true
};

// Measurement plan → simulation engine mode mapping
// @mode virtual: all measurement plans route to simulation server (port 8002)
// @mode real: will route to Bluesky RunEngine + real ophyd devices + real detectors
var _SIM_PLAN_MAP = {
  'xanes_scan': 'xafs',
  'energy_scan': 'xafs',
  'adaptive_energy_scan': 'xafs',
  'raster_scan': 'xrf2d',
  'rel_raster_scan': 'xrf2d',
  'fermat_scan': 'xrf2d',
  'fly_scan': 'xrf2d',
  'count': '_count'
};

function executePlan(item) {
  // 1. Alignment/utility plans → Bluesky server or local
  if (_LOCAL_ONLY_PLANS[item.name]) {
    if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.scanConnected) {
      return executeServerPlan(item);
    }
    return new Promise(function(resolve) {
      var executor = new PlanExecutor(item);
      item._executor = executor;
      executor.execute().then(function(result) { resolve(result); });
    });
  }
  // 2. Measurement plans → simulation server engine
  if (_SIM_PLAN_MAP[item.name]) {
    return executeSimPlan(item);
  }
  // 3. Unknown plan → error
  log('err', 'Unknown plan: ' + item.name);
  return Promise.resolve({ success: false, msg: 'Unknown plan: ' + item.name });
}

// ============================================================
//  Simulation Engine Execution (port 8002)
// ============================================================
var _queueSimActive = false;
var _queueSimResolve = null;
var _queueSimLiveData = [];
var _queueSimMapData = null;
var _queueSimPlanName = '';

function executeSimPlan(item) {
  return new Promise(function(resolve) {
    // Check simulation server connection
    if (typeof _simWsConnected === 'undefined' || !_simWsConnected) {
      var simPort = (typeof SIM_WS_PORT !== 'undefined') ? SIM_WS_PORT : 8002;
      log('err', 'Simulation server (port ' + simPort + ') not connected');
      resolve({ success: false, msg: 'Simulation server not connected (port ' + simPort + ')' });
      return;
    }

    var p = item.kwargs || {};
    var simMode = _SIM_PLAN_MAP[item.name];

    // Special case: count (no server needed)
    if (simMode === '_count') {
      var flux = typeof photonFlux === 'function' ? photonFlux(state.energy) : 1e10;
      var ct = flux * (p.dwell || 1) * (0.98 + Math.random() * 0.04);
      resolve({ success: true, msg: 'Count: ' + ct.toExponential(2) + ' photons', data: [{ x: 1, y: ct }] });
      return;
    }

    // Build params for simulation engine
    var simParams = _buildSimParams(item.name, p);

    // Set up response routing
    _queueSimActive = true;
    _queueSimResolve = resolve;
    _queueSimLiveData = [];
    _queueSimMapData = null;
    _queueSimPlanName = item.name;

    // Provide abort interface
    item._executor = {
      abort: function() {
        if (typeof _simSendCancel === 'function') _simSendCancel();
        _queueSimActive = false;
        if (_queueSimResolve) {
          _queueSimResolve({ success: false, msg: 'Aborted', data: _queueSimLiveData });
          _queueSimResolve = null;
        }
      }
    };

    log('info', 'Sim plan: ' + simMode + '(' + JSON.stringify(simParams).substring(0, 200) + ')');

    // Send to simulation server
    if (!_simSendRun(simMode, simParams)) {
      _queueSimActive = false;
      _queueSimResolve = null;
      resolve({ success: false, msg: 'Failed to send to simulation server' });
      return;
    }

    // Timeout fallback: 5 minutes
    setTimeout(function() {
      if (_queueSimResolve) {
        _queueSimActive = false;
        _queueSimResolve({ success: false, msg: 'Timeout (300s)', data: _queueSimLiveData });
        _queueSimResolve = null;
      }
    }, 300000);
  });
}

// Build simulation engine params from Bluesky plan params
function _buildSimParams(planName, p) {
  switch (planName) {
    case 'xanes_scan':
      return {
        formula: p.element || 'Cu',
        absorber: p.element || 'Cu',
        edge: p.edge || 'K',
        eStart: -50,
        eEnd: 300,
        eStep: 0.5,
        ppm: 10000,
        sampleType: 'solid'
      };
    case 'energy_scan':
      return {
        formula: 'Cu',
        absorber: 'Cu',
        edge: 'K',
        eStart: ((p.start || 8) - 8.979) * 1000,
        eEnd: ((p.stop || 12) - 8.979) * 1000,
        eStep: ((p.stop || 12) - (p.start || 8)) / (p.num || 50) * 1000,
        ppm: 10000,
        sampleType: 'solid'
      };
    case 'adaptive_energy_scan':
      return {
        formula: p.element || 'Cu',
        absorber: p.element || 'Cu',
        edge: p.edge || 'K',
        eStart: ((p.e_start || 8.9) - 8.979) * 1000,
        eEnd: ((p.e_stop || 9.1) - 8.979) * 1000,
        eStep: (p.min_step_eV || 0.5),
        ppm: 10000,
        sampleType: 'solid'
      };
    case 'raster_scan':
      return {
        formula: 'Cu',
        ppm: 1000,
        scanLx: Math.abs((p.x_stop || 5) - (p.x_start || -5)),
        scanLy: Math.abs((p.y_stop || 5) - (p.y_start || -5)),
        step: Math.abs((p.x_stop || 5) - (p.x_start || -5)) / ((p.x_num || 21) - 1),
        dwell: p.dwell || 0.1,
        sampleType: 'solid'
      };
    case 'rel_raster_scan':
      return {
        formula: 'Cu',
        ppm: 1000,
        scanLx: p.dx || 10,
        scanLy: p.dy || 10,
        step: (p.dx || 10) / ((p.nx || 21) - 1),
        dwell: 0.1,
        sampleType: 'solid'
      };
    case 'fermat_scan':
      return {
        formula: 'Cu',
        ppm: 1000,
        scanLx: (p.x_range || 10),
        scanLy: (p.y_range || 10),
        step: p.dr || 0.5,
        dwell: 0.1,
        sampleType: 'solid'
      };
    case 'fly_scan':
      return {
        formula: 'Cu',
        ppm: 1000,
        scanLx: Math.abs((p.stop || 10) - (p.start || -10)),
        scanLy: 0.001,
        step: Math.abs((p.stop || 10) - (p.start || -10)) / ((p.n_points || 101) - 1),
        dwell: 0.1,
        sampleType: 'solid'
      };
    default:
      return p;
  }
}

// Handle simulation server responses for Queue plans
function _handleQueueSimResponse(msg) {
  var type = msg.type;

  if (type === 'expt_progress') {
    var pct = (msg.fraction || 0) * 100;
    var progEl = document.getElementById('bsPlanProgress');
    if (progEl) progEl.style.width = pct.toFixed(0) + '%';
    var pctEl = document.getElementById('bsPlanPct');
    if (pctEl) pctEl.textContent = pct.toFixed(0) + '%';
  } else if (type === 'expt_data') {
    // XAFS streaming batch
    if (msg.mode === 'xafs' && msg.batch) {
      for (var i = 0; i < msg.batch.length; i++) {
        var pt = msg.batch[i];
        _queueSimLiveData.push({ x: pt.x, y: pt.y, xlabel: 'E - E0 (eV)', ylabel: 'mu(E)' });
      }
      if (typeof updateBsLiveChart === 'function') {
        updateBsLiveChart(_queueSimLiveData, _queueSimPlanName);
      }
    }
  } else if (type === 'expt_result') {
    // Open Expt popup FIRST (creates canvas), then render results
    if (typeof _openExptPopup === 'function' && msg.mode) {
      var _modeLabel = {xafs:'XAFS',xrf2d:'XRF 2D Map',xrd2d:'2D XRD',xrdmap:'XRD Map'};
      try { _openExptPopup(msg.mode, _modeLabel[msg.mode] || msg.mode, 700, 500); } catch(e) {}
    }
    if (typeof _handleExptResult === 'function') {
      // Defer to allow popup canvas to initialize
      setTimeout(function() { try { _handleExptResult(msg); } catch(e) {} }, 200);
    }
  } else if (type === 'expt_done') {
    log('info', 'Sim plan complete (' + (_queueSimLiveData.length) + ' pts, ' + (msg.elapsed_sec || 0).toFixed(1) + 's)');
    _queueSimActive = false;
    if (_queueSimResolve) {
      _queueSimResolve({
        success: true,
        msg: _queueSimLiveData.length + ' points',
        data: _queueSimLiveData,
        mapData: _queueSimMapData
      });
      _queueSimResolve = null;
    }
  } else if (type === 'expt_error') {
    log('err', 'Sim plan error: ' + (msg.error || msg.msg || 'unknown'));
    _queueSimActive = false;
    if (_queueSimResolve) {
      _queueSimResolve({ success: false, msg: msg.error || msg.msg || 'Simulation error' });
      _queueSimResolve = null;
    }
  } else if (type === 'expt_cancelled') {
    _queueSimActive = false;
    if (_queueSimResolve) {
      _queueSimResolve({ success: false, msg: 'Cancelled' });
      _queueSimResolve = null;
    }
  }
}

// Process simulation result into Queue live data
function _handleQueueSimResult(msg) {
  var mode = msg.mode;

  if (mode === 'xafs') {
    // XAFS: data array already in liveData from streaming, or in msg.data
    var data = msg.data || [];
    if (data.length > 0 && _queueSimLiveData.length === 0) {
      for (var i = 0; i < data.length; i++) {
        _queueSimLiveData.push({ x: data[i].x, y: data[i].y, xlabel: 'E - E0 (eV)', ylabel: 'mu(E)' });
      }
    }
  } else if (mode === 'xrf2d') {
    // XRF 2D map: extract maps and spectrum
    if (msg.maps) {
      var elements = Object.keys(msg.maps);
      var firstEl = elements[0];
      if (firstEl && msg.maps[firstEl]) {
        var mapArr = msg.maps[firstEl];
        var ny = mapArr.length, nx = (mapArr[0] || []).length;
        // Convert to flat liveData for chart
        var scanLx = (msg.info && msg.info.scan_range_um) ? msg.info.scan_range_um[0] : 10;
        var scanLy = (msg.info && msg.info.scan_range_um) ? msg.info.scan_range_um[1] : 10;
        _queueSimMapData = { xP: [], yP: [], d: [] };
        for (var ix = 0; ix < nx; ix++) _queueSimMapData.xP.push(-scanLx / 2 + ix * scanLx / (nx - 1 || 1));
        for (var iy = 0; iy < ny; iy++) _queueSimMapData.yP.push(-scanLy / 2 + iy * scanLy / (ny - 1 || 1));
        for (var jy = 0; jy < ny; jy++) {
          var row = [];
          for (var jx = 0; jx < nx; jx++) {
            var val = mapArr[jy][jx] || 0;
            row.push(val);
            _queueSimLiveData.push({ x: _queueSimMapData.xP[jx], y: _queueSimMapData.yP[jy], val: val });
          }
          _queueSimMapData.d.push(row);
        }
      }
    }
    // Also store spectrum if available
    if (msg.spectrum && msg.spectrum.channels) {
      var chs = msg.spectrum.channels;
      var eStep = (msg.spectrum.e_max || 20) / chs.length;
      for (var k = 0; k < chs.length; k++) {
        if (chs[k] > 0) {
          _queueSimLiveData.push({ x: k * eStep, y: chs[k], xlabel: 'Energy (keV)', ylabel: 'Counts' });
        }
      }
    }
  } else if (mode === 'xrd2d') {
    // XRD: rings data
    if (msg.rings) {
      for (var r = 0; r < msg.rings.length; r++) {
        var ring = msg.rings[r];
        _queueSimLiveData.push({ x: ring.tth || ring.two_theta || 0, y: ring.I || ring.intensity || 0, xlabel: '2theta (deg)', ylabel: 'Intensity' });
      }
    }
  }

  if (typeof updateBsLiveChart === 'function') {
    updateBsLiveChart(_queueSimLiveData, _queueSimPlanName);
  }
}

// --- Server-side plan execution via /ws/scan WebSocket ---
function executeServerPlan(item) {
  return new Promise(function(resolve) {
    var ws = EPICS_STATE.scanWs;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      // Alignment plans can fall back to local; measurement plans must fail
      if (_LOCAL_ONLY_PLANS[item.name]) {
        log('warn', 'Scan WS not connected, running alignment plan locally');
        var executor = new PlanExecutor(item);
        item._executor = executor;
        executor.execute().then(function(result) { resolve(result); });
        return;
      }
      log('err', 'Scan WS not connected — plan "' + item.name + '" requires server');
      resolve({ success: false, msg: 'Server not connected. Measurement plans require simulation server.' });
      return;
    }

    // Map JS plan names to server plan names if needed
    var planNameMap = {
      'energy_scan': 'energy_scan',
      'xanes_scan': 'xanes_scan',
      'raster_scan': 'raster_scan',
      'align_motor': 'alignment_scan',
      'count': 'beam_check',
      'auto_align': 'alignment_scan',
      'gap_optimize': 'energy_scan',
      'auto_tune': 'auto_tune',
      'adaptive_energy_scan': 'adaptive_energy_scan',
      'rel_alignment_scan': 'rel_alignment_scan',
      'fermat_scan': 'fermat_scan',
      'rel_raster_scan': 'rel_raster_scan'
    };
    var serverPlanName = planNameMap[item.name] || item.name;

    // Map JS params to server params
    var serverParams = _mapPlanParams(item.name, item.kwargs || {});

    log('info', 'Server plan submit: ' + serverPlanName + '(' + JSON.stringify(serverParams) + ')');

    // Set up scan event handler for this execution
    var liveData = [];
    var eventCount = 0;

    window._serverPlanResolve = function(result) {
      window._serverPlanResolve = null;
      resolve(result);
    };

    // Latency measurement storage
    window._latencyLog = window._latencyLog || [];

    window.handleScanEvent = function(msg) {
      if (msg.type !== 'scan_event') return;
      var docType = msg.doc_type;
      var doc = msg.doc || {};

      // Latency measurement: log all timestamps for each event
      if (msg._ts_callback && msg._ts_browser_recv) {
        var entry = {
          doc_type: docType,
          event_num: msg.event_count || 0,
          ts_callback: msg._ts_callback,
          ts_send: msg._ts_send,
          ts_ws_send: msg._ts_ws_send,
          ts_browser_recv: msg._ts_browser_recv,
          ts_handler: Date.now() / 1000,
          latency_callback_to_send_ms: (msg._ts_send - msg._ts_callback) * 1000,
          latency_send_to_ws_ms: (msg._ts_ws_send - msg._ts_send) * 1000,
          latency_ws_to_browser_ms: (msg._ts_browser_recv - msg._ts_ws_send) * 1000,
          latency_total_ms: (msg._ts_browser_recv - msg._ts_callback) * 1000
        };
        window._latencyLog.push(entry);
        if (docType === 'event') {
          console.log('[Latency] event #' + entry.event_num +
            ' | callback->send: ' + entry.latency_callback_to_send_ms.toFixed(1) + 'ms' +
            ' | send->ws: ' + entry.latency_send_to_ws_ms.toFixed(1) + 'ms' +
            ' | ws->browser: ' + entry.latency_ws_to_browser_ms.toFixed(1) + 'ms' +
            ' | TOTAL: ' + entry.latency_total_ms.toFixed(1) + 'ms');
        }
      }

      if (docType === 'start') {
        log('info', 'Server scan started: ' + (msg.plan || serverPlanName));
        window._latencyLog = [];  // Reset for new scan
        liveData = [];
        eventCount = 0;
        var progEl = document.getElementById('bsPlanProgress');
        if (progEl) progEl.style.width = '0%';
      }

      if (docType === 'event') {
        eventCount++;
        // Extract data point from Bluesky event document
        var data = doc.data || {};
        var point = _extractDataPoint(data, item.name, eventCount);
        if (point) {
          liveData.push(point);
          if (typeof updateBsLiveChart === 'function') updateBsLiveChart(liveData, item.name);
        }
        // Update progress (estimate from event_count if total not known)
        var total = msg.event_count || eventCount;
        var pctEl = document.getElementById('bsPlanPct');
        if (pctEl) pctEl.textContent = eventCount + ' pts';
      }

      if (docType === 'stop') {
        var success = doc.exit_status === 'success';
        log(success ? 'info' : 'err', 'Server scan finished: ' + (doc.exit_status || 'unknown'));
        var progEl = document.getElementById('bsPlanProgress');
        if (progEl) progEl.style.width = '100%';
        var pctEl = document.getElementById('bsPlanPct');
        if (pctEl) pctEl.textContent = '100%';

        // Latency measurement: print summary statistics on scan completion
        if (window._latencyLog && window._latencyLog.length > 0) {
          var events = window._latencyLog.filter(function(e) { return e.doc_type === 'event'; });
          if (events.length > 0) {
            var totals = events.map(function(e) { return e.latency_total_ms; }).sort(function(a,b){return a-b;});
            var sum = totals.reduce(function(a,b){return a+b;}, 0);
            var median = totals[Math.floor(totals.length/2)];
            var p10 = totals[Math.floor(totals.length*0.1)];
            var p90 = totals[Math.floor(totals.length*0.9)];
            var min = totals[0];
            var max = totals[totals.length-1];
            console.log('========== LATENCY SUMMARY ==========');
            console.log('Events measured: ' + events.length);
            console.log('Total (callback->browser): median=' + median.toFixed(1) + 'ms, mean=' + (sum/totals.length).toFixed(1) + 'ms');
            console.log('  min=' + min.toFixed(1) + 'ms, max=' + max.toFixed(1) + 'ms');
            console.log('  P10=' + p10.toFixed(1) + 'ms, P90=' + p90.toFixed(1) + 'ms');
            // Breakdown averages
            var avgCb = events.reduce(function(a,e){return a+e.latency_callback_to_send_ms;},0)/events.length;
            var avgSend = events.reduce(function(a,e){return a+e.latency_send_to_ws_ms;},0)/events.length;
            var avgWs = events.reduce(function(a,e){return a+e.latency_ws_to_browser_ms;},0)/events.length;
            console.log('Breakdown (mean): callback->send=' + avgCb.toFixed(1) + 'ms, send->ws_send=' + avgSend.toFixed(1) + 'ms, ws_send->browser=' + avgWs.toFixed(1) + 'ms');
            console.log('Raw data: JSON.stringify(window._latencyLog)');
            console.log('======================================');
          }
        }

        if (window._serverPlanResolve) {
          window._serverPlanResolve({
            success: success,
            msg: (success ? 'Completed' : 'Failed') + ': ' + eventCount + ' points',
            data: liveData
          });
        }
      }
    };

    // Submit to server
    ws.send(JSON.stringify({
      action: 'submit',
      plan_name: serverPlanName,
      params: serverParams
    }));

    // Provide abort/pause/resume via item._executor interface
    item._executor = {
      abort: function() {
        ws.send(JSON.stringify({ action: 'abort', reason: 'User abort' }));
      },
      resume: function() {
        ws.send(JSON.stringify({ action: 'resume' }));
      }
    };

    // Timeout fallback: resolve after 5 minutes if no stop event
    setTimeout(function() {
      if (window._serverPlanResolve) {
        window._serverPlanResolve({ success: false, msg: 'Timeout (300s)', data: liveData });
      }
    }, 300000);
  });
}

// --- Map JS plan params to server plan params ---
function _mapPlanParams(planName, params) {
  switch (planName) {
    case 'energy_scan':
      return {
        e_start: params.start || 8,
        e_stop: params.stop || 12,
        n_points: params.num || 50
      };
    case 'xanes_scan':
      return {
        element: params.element || 'Cu',
        edge: params.edge || 'K'
      };
    case 'raster_scan':
      return {
        x_range: [params.x_start || -5, params.x_stop || 5],
        y_range: [params.y_start || -5, params.y_stop || 5],
        nx: params.x_num || 21,
        ny: params.y_num || 21
      };
    case 'align_motor': {
      var motorMap = { 'm1_pitch': ['m1','pitch'], 'm2_pitch': ['m2','pitch'],
                       'kbv_pitch': ['kbv','pitch'], 'kbh_pitch': ['kbh','pitch'] };
      var mapped = motorMap[params.motor] || ['m1','pitch'];
      var _defCenter = (mapped[0]==='m1'||mapped[0]==='m2') ? 2.5 : 3.0;
      return { device_name: mapped[0], axis_name: mapped[1],
               center: params.center || _defCenter, width: params.width || 0.2 };
    }
    case 'count':
      return { n_readings: params.num || 1, delay: params.dwell || 1 };
    default:
      return params;
  }
}

// --- Extract a data point from Bluesky event document ---
function _extractDataPoint(data, planName, idx) {
  // Bluesky event docs have data keys like 'dcm_theta', 'ic1_current', etc.
  var keys = Object.keys(data);
  if (keys.length === 0) return null;

  // For energy scans: x = theta (convert to energy), y = detector
  if (planName === 'energy_scan' || planName === 'xanes_scan') {
    var theta = data['dcm_theta'] || data[keys[0]];
    var signal = data['ic1_current'] || data[keys[keys.length > 1 ? 1 : 0]];
    return { x: theta, y: signal || 0, xlabel: 'DCM Theta (deg)', ylabel: 'Signal' };
  }

  // For raster scans: x, y, val
  if (planName === 'raster_scan') {
    var sx = data['sample_sx'] || data[keys[0]] || 0;
    var sy = data['sample_sy'] || data[keys.length > 1 ? keys[1] : keys[0]] || 0;
    var val = data['ic1_current'] || data[keys[keys.length > 1 ? keys.length - 1 : 0]] || 0;
    return { x: sx, y: sy, val: val };
  }

  // Generic: first key = x, second key = y
  return { x: data[keys[0]] || idx, y: data[keys.length > 1 ? keys[1] : keys[0]] || 0,
           xlabel: keys[0] || 'X', ylabel: keys.length > 1 ? keys[1] : 'Y' };
}

// ============================================================
//  4. REAL QUEUE SERVER REST API CLIENT
// ============================================================

function qsApiCall(endpoint, method, body) {
  if (method === undefined) method = 'GET';
  if (body === undefined) body = null;
  if (QS_CONFIG.simMode) {
    log('warn', 'QS in sim mode -- use simulated queue');
    return Promise.resolve({ success: false, msg: 'Sim mode' });
  }
  var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  return fetch(QS_CONFIG.url + '/api/' + endpoint, opts).then(function(r) {
    return r.json();
  }).catch(function(e) {
    log('err', 'QS API error: ' + e.message);
    return { success: false, msg: e.message };
  });
}

function connectRealQS(url) {
  QS_CONFIG.url = url || QS_CONFIG.url;
  QS_CONFIG.simMode = false;
  return qsApiCall('status').then(function(status) {
    if (status.worker_environment_exists !== undefined) {
      QS_CONFIG.connected = true;
      log('info', 'Connected to Queue Server at ' + QS_CONFIG.url);
      return true;
    }
    QS_CONFIG.simMode = true;
    QS_CONFIG.connected = false;
    return false;
  }).catch(function(e) {
    log('err', 'QS connection failed: ' + e.message);
    QS_CONFIG.simMode = true;
    QS_CONFIG.connected = false;
    return false;
  });
}

// ============================================================
//  5. CONVENIENCE — Quick plan submission helpers
// ============================================================

// @mode virtual: routes to simulation server (port 8002) via _SIM_PLAN_MAP
// @mode real: will route to Bluesky RunEngine + real DCM + real ion chamber
function quickEnergyScan(start, stop, num) {
  return queuePlan('energy_scan', { start: start, stop: stop, num: num || 50 });
}

/**
 * Wait for experiment completion via WebSocket event (no polling).
 * _exptState._onDone is called by 06_experiment_ui.js on expt_done/error/cancelled.
 * Fallback timeout at 600s to prevent infinite hang.
 */
function _waitExptDone() {
  return new Promise(function(resolve) {
    var timeout = setTimeout(function() {
      _exptState._onDone = null;
      resolve({ success: false, timeout: true });
    }, 600000);
    _exptState._onDone = function(result) {
      clearTimeout(timeout);
      resolve(result);
    };
  });
}

// @mode virtual: routes to simulation server (port 8002) via startExperiment()
// @mode real: will route to Bluesky RunEngine + real DCM + real XRF detector
async function quickXafs(element, edge) {
  if (typeof _exptState !== 'undefined' && typeof startExperiment === 'function') {
    var el = element || 'Cu';
    var ed = edge || 'K';
    _exptState.mode = 'xafs';
    if (!_exptState.xafs) _exptState.xafs = {};
    _exptState.xafs.absorber = el;
    _exptState.xafs.edge = ed;
    _exptState.xafs.formula = el;
    if (!_exptState.xafs.eStart) _exptState.xafs.eStart = -150;
    if (!_exptState.xafs.eEnd) _exptState.xafs.eEnd = 800;
    if (!_exptState.xafs.eStep) _exptState.xafs.eStep = 1.0;
    _exptState.xafs.sampleType = 'solid';
    _exptState.xafs.ppm = 1000000;
    _exptState._skipDomRead = true;
    await startExperiment();
    QUEUE._exptRunning = true;
    await _waitExptDone();
    return { success: true };
  }
  return queuePlan('xanes_scan', { element: element, edge: edge || 'K' });
}

function quickAlign(motor) {
  return queuePlan('align_motor', { motor: motor });
}

// @mode virtual: routes to simulation server (port 8002) via startExperiment()
// @mode real: will route to Bluesky RunEngine + real nano-scanner + real XRF detector
async function quickRaster(xRange, yRange, numPts, presetKey) {
  var r = xRange || 5, n = numPts || 21;
  if (typeof _exptState !== 'undefined' && typeof startExperiment === 'function') {
    _exptState.mode = 'xrf2d';
    if (!_exptState.xrf2d) _exptState.xrf2d = {};
    _exptState.xrf2d.scanLx = r * 2;
    _exptState.xrf2d.scanLy = (yRange || r) * 2;
    _exptState.xrf2d.step = (r * 2) / Math.max(1, n - 1);
    // Apply preset: use provided key, or default to semiconductor_ic
    var defKey = presetKey || 'semiconductor_ic';
    if (typeof XRF_SAMPLE_PRESETS !== 'undefined') {
      var preset = XRF_SAMPLE_PRESETS[defKey];
      if (preset) {
        _exptState.xrf2d.presetKey = defKey;
        _exptState.xrf2d.formula = preset.formula || 'Cu';
        _exptState.xrf2d.thickness_um = preset.thickness_um || 1.0;
        _exptState.xrf2d.matDensity = preset.matrixDensity || 2.0;
        _exptState.xrf2d.sampleType = preset.sampleType || 'solid';
        _exptState.xrf2d.ppm = 1000000;
      }
    }
    _exptState._skipDomRead = true;
    await startExperiment();
    QUEUE._exptRunning = true;
    await _waitExptDone();
    return { success: true };
  }
  // Fallback: queue
  return queuePlan('raster_scan', {
    x_start: -r, x_stop: r, x_num: n,
    y_start: -(yRange || r), y_stop: (yRange || r), y_num: n
  });
}

function quickCount(num, dwell) {
  return queuePlan('count', { num: num || 1, dwell: dwell || 1 });
}

// @mode virtual: routes to simulation server (port 8002) via startExperiment()
// @mode real: will route to Bluesky RunEngine + real DCM + real XRF detector
async function quickXanes(element, edge) {
  if (typeof _exptState !== 'undefined' && typeof startExperiment === 'function') {
    var el = element || 'Cu';
    var ed = edge || 'K';
    _exptState.mode = 'xafs';
    if (!_exptState.xafs) _exptState.xafs = {};
    _exptState.xafs.absorber = el;
    _exptState.xafs.edge = ed;
    _exptState.xafs.formula = el;
    // Default scan range: -50 to +200 eV relative to edge, 0.5 eV step
    if (!_exptState.xafs.eStart) _exptState.xafs.eStart = -50;
    if (!_exptState.xafs.eEnd) _exptState.xafs.eEnd = 200;
    if (!_exptState.xafs.eStep) _exptState.xafs.eStep = 0.5;
    _exptState.xafs.sampleType = 'solid';
    _exptState.xafs.ppm = 1000000;
    _exptState._skipDomRead = true;
    await startExperiment();  // waits for alignment to complete
    // Wait for experiment via WebSocket event (no polling)
    QUEUE._exptRunning = true;
    await _waitExptDone();
    return { success: true };
  }
  return queuePlan('xanes_scan', { element: element, edge: edge || 'K' });
}

function quickFlyScan(motorName, axisName, start, stop, nPoints) {
  return queuePlan('fly_scan', {
    motor_name: motorName, axis_name: axisName,
    start: start, stop: stop, n_points: nPoints || 101
  });
}

// @mode virtual: pitch requests route to runMirrorAlignUI (MC centroid-based)
// @mode real: will route to actual BPM centroid feedback
function quickAutoTune(deviceName, axisName, start, stop, targetField) {
  // Mirror pitch tuning: intensity is plateau-shaped, max search is meaningless.
  // Route to runMirrorAlignUI which uses centroid drift (rotation center) instead.
  var dev = (deviceName || '').toLowerCase();
  var axis = (axisName || '').toLowerCase();
  if (axis === 'pitch' && typeof runMirrorAlignUI === 'function') {
    var mirrorMap = {'m1':'m1', 'm2':'m2', 'kbv':'kbv', 'kbh':'kbh', 'kb-v':'kbv', 'kb-h':'kbh', 'kb_v':'kbv', 'kb_h':'kbh'};
    var mid = mirrorMap[dev];
    if (mid) {
      log('info', 'quickAutoTune: pitch request -> routing to runMirrorAlignUI(' + mid + ')');
      return runMirrorAlignUI(mid, {skipGuard: false});
    }
  }
  // Non-pitch axes: use iterative max search (appropriate for gap, slit position, etc.)
  return queuePlan('auto_tune', {
    device_name: deviceName, axis_name: axisName,
    start: start, stop: stop,
    target_field: targetField || 'ic1_current'
  });
}

function quickAdaptiveScan(eStart, eStop, minStepEV, maxStepEV) {
  return queuePlan('adaptive_energy_scan', {
    e_start: eStart, e_stop: eStop,
    min_step_eV: minStepEV || 0.1, max_step_eV: maxStepEV || 5.0
  });
}

function quickRelAlign(deviceName, axisName, width, nPoints) {
  return queuePlan('rel_alignment_scan', {
    device_name: deviceName, axis_name: axisName,
    width: width, n_points: nPoints || 21
  });
}

function quickFermat(xRange, yRange, dr) {
  return queuePlan('fermat_scan', {
    x_range: xRange || 10, y_range: yRange || 10, dr: dr || 0.5
  });
}

function quickRelRaster(dx, dy, nx, ny) {
  return queuePlan('rel_raster_scan', {
    dx: dx || 10, dy: dy || 10, nx: nx || 21, ny: ny || 21
  });
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof PLAN_LIBRARY!=="undefined")globalThis.PLAN_LIBRARY=PLAN_LIBRARY;
if(typeof PlanExecutor!=="undefined")globalThis.PlanExecutor=PlanExecutor;
if(typeof QS_CONFIG!=="undefined")globalThis.QS_CONFIG=QS_CONFIG;
if(typeof QUEUE!=="undefined")globalThis.QUEUE=QUEUE;
if(typeof _LOCAL_ONLY_PLANS!=="undefined")globalThis._LOCAL_ONLY_PLANS=_LOCAL_ONLY_PLANS;
if(typeof _SIM_PLAN_MAP!=="undefined")globalThis._SIM_PLAN_MAP=_SIM_PLAN_MAP;
if(typeof connectRealQS!=="undefined")globalThis.connectRealQS=connectRealQS;
if(typeof executePlan!=="undefined")globalThis.executePlan=executePlan;
if(typeof executeServerPlan!=="undefined")globalThis.executeServerPlan=executeServerPlan;
if(typeof executeSimPlan!=="undefined")globalThis.executeSimPlan=executeSimPlan;
if(typeof processNextPlan!=="undefined")globalThis.processNextPlan=processNextPlan;
if(typeof qsApiCall!=="undefined")globalThis.qsApiCall=qsApiCall;
if(typeof qsPollTimer!=="undefined")globalThis.qsPollTimer=qsPollTimer;
if(typeof queueAbort!=="undefined")globalThis.queueAbort=queueAbort;
if(typeof queueClear!=="undefined")globalThis.queueClear=queueClear;
if(typeof queueMoveDown!=="undefined")globalThis.queueMoveDown=queueMoveDown;
if(typeof queueMoveUp!=="undefined")globalThis.queueMoveUp=queueMoveUp;
if(typeof queuePause!=="undefined")globalThis.queuePause=queuePause;
if(typeof queuePlan!=="undefined")globalThis.queuePlan=queuePlan;
if(typeof queueRemove!=="undefined")globalThis.queueRemove=queueRemove;
if(typeof queueResume!=="undefined")globalThis.queueResume=queueResume;
if(typeof queueStart!=="undefined")globalThis.queueStart=queueStart;
if(typeof queueStop!=="undefined")globalThis.queueStop=queueStop;
if(typeof quickAdaptiveScan!=="undefined")globalThis.quickAdaptiveScan=quickAdaptiveScan;
if(typeof quickAlign!=="undefined")globalThis.quickAlign=quickAlign;
if(typeof quickAutoTune!=="undefined")globalThis.quickAutoTune=quickAutoTune;
if(typeof quickCount!=="undefined")globalThis.quickCount=quickCount;
if(typeof quickEnergyScan!=="undefined")globalThis.quickEnergyScan=quickEnergyScan;
if(typeof quickFermat!=="undefined")globalThis.quickFermat=quickFermat;
if(typeof quickFlyScan!=="undefined")globalThis.quickFlyScan=quickFlyScan;
if(typeof quickRaster!=="undefined")globalThis.quickRaster=quickRaster;
if(typeof quickRelAlign!=="undefined")globalThis.quickRelAlign=quickRelAlign;
if(typeof quickRelRaster!=="undefined")globalThis.quickRelRaster=quickRelRaster;
if(typeof quickXafs!=="undefined")globalThis.quickXafs=quickXafs;
if(typeof quickXanes!=="undefined")globalThis.quickXanes=quickXanes;
if(typeof _buildSimParams!=="undefined")globalThis._buildSimParams=_buildSimParams;
if(typeof _extractDataPoint!=="undefined")globalThis._extractDataPoint=_extractDataPoint;
if(typeof _handleQueueSimResponse!=="undefined")globalThis._handleQueueSimResponse=_handleQueueSimResponse;
if(typeof _handleQueueSimResult!=="undefined")globalThis._handleQueueSimResult=_handleQueueSimResult;
if(typeof _latencyLog!=="undefined")globalThis._latencyLog=_latencyLog;
if(typeof _mapPlanParams!=="undefined")globalThis._mapPlanParams=_mapPlanParams;
if(typeof _queueSimActive!=="undefined")globalThis._queueSimActive=_queueSimActive;
if(typeof _queueSimLiveData!=="undefined")globalThis._queueSimLiveData=_queueSimLiveData;
if(typeof _queueSimMapData!=="undefined")globalThis._queueSimMapData=_queueSimMapData;
if(typeof _queueSimPlanName!=="undefined")globalThis._queueSimPlanName=_queueSimPlanName;
if(typeof _queueSimResolve!=="undefined")globalThis._queueSimResolve=_queueSimResolve;
if(typeof _serverPlanResolve!=="undefined")globalThis._serverPlanResolve=_serverPlanResolve;
if(typeof handleScanEvent!=="undefined")globalThis.handleScanEvent=handleScanEvent;
