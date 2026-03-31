// ===== epics.js =====
'use strict';
// ===== epics.js -- EPICS Integration Layer for Korea-4GSR ID10 NanoProbe =====
// @module control/02_epics
// @exports EPICS_STATE, PV_ARCHIVE, PV_MONITOR_GROUPS, PV_REGISTRY, SimIOC, _discoveredPVs, _findMotorByPV, _handlePVDiscovered, _pvDiscoverClose, _pvDiscoverIgnore, _pvDiscoverPlace, _pvLatencyLog, _pvLimitStatus, _showMoveConfirmDialog, _showPVDetailPopup, ...
// Phase 1: SimIOC (offline testing) + WebSocket bridge (ophyd-websocket ready)

// ===== PV Registry -- maps every motor to an EPICS PV name =====
var PV_REGISTRY = {};  // Built dynamically from MOTORS

function buildPVRegistry() {
  if (typeof MOTORS === 'undefined') return;
  Object.keys(MOTORS).forEach(function(grp) {
    var group = MOTORS[grp];
    var motors = Array.isArray(group) ? group : Object.values(group).filter(function(m) { return m && m.id; });
    motors.forEach(function(m) {
      if (m.pv) {
        PV_REGISTRY[m.pv] = {
          groupId: grp,
          motorId: m.id,
          motor: m,
          value: m.value,
          severity: 0,       // 0=NO_ALARM, 1=MINOR, 2=MAJOR, 3=INVALID
          timestamp: Date.now() / 1000,
          connected: false,
          callbacks: []
        };
      }
    });
  });
  // Status PVs (no motor object -- ring, BPM, IC)
  var STATUS_PVS = {
    'BL10:RING:Current':  400.0,
    'BL10:RING:Energy':   4.0,
    'BL10:RING:Lifetime': 12.5,
    'BL10:FE:Shutter':    1,
    'BL10:XBPM1:X': 0, 'BL10:XBPM1:Y': 0,
    'BL10:XBPM2:Current1:MeanValue_RBV': 0, 'BL10:XBPM2:Current2:MeanValue_RBV': 0,
    'BL10:XBPM2:Current3:MeanValue_RBV': 0, 'BL10:XBPM2:Current4:MeanValue_RBV': 0,
    'BL10:XBPM2:SumAll:MeanValue_RBV': 0,
    'BL10:XBPM2:PosX:MeanValue_RBV': 0, 'BL10:XBPM2:PosY:MeanValue_RBV': 0,
    'BL10:XBPM2:Range': 2, 'BL10:XBPM2:BiasPEn': 0,
    'BL10:XBPM2:SampleFreq': 10000, 'BL10:XBPM2:Acquire': 0,
    'BL10:IC1:Current':   1e-9
  };
  Object.keys(STATUS_PVS).forEach(function(pv) {
    PV_REGISTRY[pv] = {
      groupId: '_status', motorId: pv, motor: null,
      value: STATUS_PVS[pv], severity: 0,
      timestamp: Date.now() / 1000, connected: false, callbacks: []
    };
  });
  log('info', 'PV Registry: ' + Object.keys(PV_REGISTRY).length + ' PVs mapped (incl. ' + Object.keys(STATUS_PVS).length + ' status)');
}

// ===== EPICS Connection State =====
var _svHost = (typeof SERVER_HOST !== 'undefined') ? SERVER_HOST : 'localhost';
var _svPort = (typeof SERVER_WS_PORT !== 'undefined') ? SERVER_WS_PORT : 8001;
var EPICS_STATE = {
  mode: 'disconnected',   // disconnected | sim | real
  wsUrl: 'ws://' + _svHost + ':' + _svPort + '/ws/pv',
  ws: null,
  simIOC: null,
  connected: false,
  reconnectTimer: null,
  reconnectAttempts: 0,
  maxReconnect: 5,
  // Scan WebSocket (Bluesky)
  scanWsUrl: 'ws://' + _svHost + ':' + _svPort + '/ws/scan',
  scanWs: null,
  scanConnected: false,
  stats: {
    pvCount: 0,
    connectedPVs: 0,
    messagesSent: 0,
    messagesRecv: 0,
    errors: 0,
    lastUpdate: null,
    latencyMs: 0
  }
};

// ===== SimIOC -- In-Browser Simulated IOC for Offline Testing =====
function SimIOC() {
  this.pvs = {};
  this.running = false;
  this.scanRate = 100;  // ms
  this.noiseLevel = 0.001;
  this.timer = null;
}

SimIOC.prototype.start = function() {
  var self = this;
  self.running = true;
  // Initialize all PVs from registry
  Object.keys(PV_REGISTRY).forEach(function(pv) {
    self.pvs[pv] = {
      value: PV_REGISTRY[pv].value,
      setpoint: PV_REGISTRY[pv].value,
      moving: false,
      speed: PV_REGISTRY[pv].motor ? PV_REGISTRY[pv].motor.speed || 1.0 : 1.0,
      severity: 0
    };
  });

  // Add virtual readback PVs (ring current, BPM readings, etc.)
  self.pvs['BL10:RING:Current'] = { value: 400.0, setpoint: 400.0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:RING:Energy'] = { value: 4.0, setpoint: 4.0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:RING:Lifetime'] = { value: 12.5, setpoint: 12.5, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:FE:Shutter'] = { value: 1, setpoint: 1, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM1:X'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM1:Y'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  // XBPM2 quadEM PVs (Sydor SI-DBPM-M403V + T4U) — names match real IOC
  self.pvs['BL10:XBPM2:Current1:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:Current2:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:Current3:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:Current4:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:SumAll:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:PosX:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:PosY:MeanValue_RBV'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:Range'] = { value: 2, setpoint: 2, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:BiasPEn'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:SampleFreq'] = { value: 10000, setpoint: 10000, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:XBPM2:Acquire'] = { value: 0, setpoint: 0, moving: false, speed: 0, severity: 0 };
  self.pvs['BL10:IC1:Current'] = { value: 1e-9, setpoint: 1e-9, moving: false, speed: 0, severity: 0 };

  // Start scan loop
  self.timer = setInterval(function() { self.scan(); }, self.scanRate);
  log('info', 'SimIOC started: ' + Object.keys(self.pvs).length + ' PVs @ ' + self.scanRate + 'ms');
};

SimIOC.prototype.stop = function() {
  this.running = false;
  if (this.timer) { clearInterval(this.timer); this.timer = null; }
  log('info', 'SimIOC stopped');
};

SimIOC.prototype.scan = function() {
  var self = this;
  if (!self.running) return;
  var now = Date.now() / 1000;

  Object.keys(self.pvs).forEach(function(pvName) {
    var pv = self.pvs[pvName];
    var changed = false;

    // Motor simulation: move toward setpoint
    if (pv.moving && pv.speed > 0) {
      var diff = pv.setpoint - pv.value;
      var step = pv.speed * (self.scanRate / 1000);
      if (Math.abs(diff) < step) {
        pv.value = pv.setpoint;
        pv.moving = false;
        changed = true;
      } else {
        pv.value += Math.sign(diff) * step;
        changed = true;
      }
    }

    // Add readback noise for realism
    if (pvName.indexOf('XBPM') >= 0 || pvName.indexOf('IC1') >= 0) {
      pv.value = pv.setpoint + (Math.random() - 0.5) * self.noiseLevel * 10;
      changed = true;
    }
    if (pvName === 'BL10:RING:Current') {
      pv.value = 400.0 + (Math.random() - 0.5) * 0.1;
      changed = true;
    }
    if (pvName === 'BL10:RING:Lifetime') {
      pv.value = 12.5 + Math.sin(now * 0.01) * 0.3;
      changed = true;
    }

    // Check alarm limits
    var reg = PV_REGISTRY[pvName];
    if (reg && reg.motor) {
      var m = reg.motor;
      if (pv.value < m.min || pv.value > m.max) pv.severity = 2;
      else if (pv.value < m.min * 1.05 || pv.value > m.max * 0.95) pv.severity = 1;
      else pv.severity = 0;
    }

    // Notify subscribers
    if (changed && reg) {
      reg.value = pv.value;
      reg.severity = pv.severity;
      reg.timestamp = now;
      reg.connected = true;
      // Sync motor position from ramped value
      if (reg.motor) {
        reg.motor.value = pv.value;
        if (typeof syncMotorToState === 'function') {
          syncMotorToState(reg.groupId, reg.motorId, pv.value);
        }
      }
      reg.callbacks.forEach(function(cb) { cb(pvName, pv.value, pv.severity, now); });
    }
  });

  // Update BPM readings based on actual beam position
  if (typeof beamAt === 'function' && typeof state !== 'undefined') {
    var xbpm1 = beamAt(32.6);
    self.pvs['BL10:XBPM1:X'].value = (Math.random() - 0.5) * xbpm1.h * 0.001;
    self.pvs['BL10:XBPM1:Y'].value = (Math.random() - 0.5) * xbpm1.v * 0.001;
    // XBPM2 quadEM simulation: 4-channel currents + computed position
    var xbpm2 = beamAt(57);
    var xb2Base = 1.0;  // ~1 nA base current
    var xb2Noise = 0.01;
    self.pvs['BL10:XBPM2:Current1:MeanValue_RBV'].value = xb2Base + (Math.random() - 0.5) * xb2Noise;
    self.pvs['BL10:XBPM2:Current2:MeanValue_RBV'].value = xb2Base + (Math.random() - 0.5) * xb2Noise;
    self.pvs['BL10:XBPM2:Current3:MeanValue_RBV'].value = xb2Base + (Math.random() - 0.5) * xb2Noise;
    self.pvs['BL10:XBPM2:Current4:MeanValue_RBV'].value = xb2Base + (Math.random() - 0.5) * xb2Noise;
    var cA = self.pvs['BL10:XBPM2:Current1:MeanValue_RBV'].value;
    var cB = self.pvs['BL10:XBPM2:Current2:MeanValue_RBV'].value;
    var cC = self.pvs['BL10:XBPM2:Current3:MeanValue_RBV'].value;
    var cD = self.pvs['BL10:XBPM2:Current4:MeanValue_RBV'].value;
    var cSum = cA + cB + cC + cD;
    self.pvs['BL10:XBPM2:SumAll:MeanValue_RBV'].value = cSum;
    self.pvs['BL10:XBPM2:PosX:MeanValue_RBV'].value = cSum > 0 ? ((cA+cD)-(cB+cC))/cSum : 0;
    self.pvs['BL10:XBPM2:PosY:MeanValue_RBV'].value = cSum > 0 ? ((cA+cB)-(cC+cD))/cSum : 0;
    // Ion chamber current proportional to flux
    self.pvs['BL10:IC1:Current'].value = photonFlux(state.energy) * 1.6e-19 * (1 + (Math.random() - 0.5) * 0.02);
  }
};

SimIOC.prototype.caput = function(pvName, value) {
  var pv = this.pvs[pvName];
  if (!pv) { log('warn', 'SimIOC: Unknown PV ' + pvName); return false; }
  pv.setpoint = value;
  if (pv.speed > 0) {
    pv.moving = true;
  } else {
    pv.value = value;
  }
  EPICS_STATE.stats.messagesSent++;
  log('info', 'caput ' + pvName + ' = ' + value);

  // For ramping motors, scan() will gradually sync; for instant PVs, sync now
  var reg = PV_REGISTRY[pvName];
  if (reg && reg.motor && pv.speed <= 0) {
    reg.motor.value = value;
    if (typeof syncMotorToState === 'function') {
      syncMotorToState(reg.groupId, reg.motorId, value);
    }
  }
  return true;
};

SimIOC.prototype.caget = function(pvName) {
  var pv = this.pvs[pvName];
  if (!pv) return null;
  EPICS_STATE.stats.messagesRecv++;
  return { value: pv.value, severity: pv.severity, timestamp: Date.now() / 1000 };
};

SimIOC.prototype.isMoving = function(pvName) {
  var pv = this.pvs[pvName];
  return pv ? pv.moving : false;
};

// ===== WebSocket Client for ophyd-websocket =====
function connectEPICS(url) {
  if (EPICS_STATE.ws) { EPICS_STATE.ws.close(); }
  EPICS_STATE.wsUrl = url || EPICS_STATE.wsUrl;

  try {
    EPICS_STATE.ws = new WebSocket(EPICS_STATE.wsUrl);

    EPICS_STATE.ws.onopen = function() {
      EPICS_STATE.connected = true;
      EPICS_STATE.reconnectAttempts = 0;
      log('info', 'WebSocket connected: ' + EPICS_STATE.wsUrl);
      updateEpicsUI();

      // CRITICAL: Save Virtual mode motor values NOW, before server
      // defaults arrive via subscribe callbacks and overwrite them.
      // These saved values act as a GUARD: handlePVUpdate checks
      // EPICS_STATE._initialValues and uses saved values instead of
      // server defaults for .RBV responses. This works regardless of
      // network latency (SSH tunnel can delay responses 200-1000ms+).
      var _savedValues = {};
      Object.keys(PV_REGISTRY).forEach(function(pv) {
        var reg = PV_REGISTRY[pv];
        // Only guard motors that have speed > 0 (server subscribes .RBV for these).
        // PVs without speed (e.g. TargetE, Chi2F) have no .RBV → guard never clears.
        if (reg && reg.motor && typeof reg.motor.value === 'number' && reg.motor.speed > 0) {
          _savedValues[pv] = reg.motor.value;
        }
      });
      // Expose to handlePVUpdate as a guard
      EPICS_STATE._initialValues = _savedValues;

      // Subscribe to all registered PVs + .RBV variants for motors
      Object.keys(PV_REGISTRY).forEach(function(pv) {
        EPICS_STATE.ws.send(JSON.stringify({ action: 'subscribe', pv: pv }));
        EPICS_STATE.stats.messagesSent++;
        // Motor PVs: also subscribe to readback (motor record .RBV field)
        if (PV_REGISTRY[pv].motor) {
          EPICS_STATE.ws.send(JSON.stringify({ action: 'subscribe', pv: pv + '.RBV' }));
          EPICS_STATE.stats.messagesSent++;
        }
      });

      // Auto-connect scan WebSocket when PV connection succeeds
      connectScan();

      // Push saved Virtual mode values to server soft_ioc.
      // Server defaults (e.g. gap=7mm) need to be replaced with
      // calculated values from Virtual mode.
      // IMPORTANT: First set motor velocities to very high so the soft_ioc
      // motor record reaches target near-instantly (avoids slow ramp that
      // leaks intermediate .RBV values after the guard expires).
      setTimeout(function() {
        if (!EPICS_STATE.ws || EPICS_STATE.ws.readyState !== WebSocket.OPEN) return;
        var count = 0;
        // Phase 1: Set high velocity for all motors
        Object.keys(_savedValues).forEach(function(pv) {
          EPICS_STATE.ws.send(JSON.stringify({
            action: 'put', pv: pv + '.VELO', value: 9999
          }));
        });
        // Phase 2: Push saved values (motor will ramp at 9999 speed = near instant)
        Object.keys(_savedValues).forEach(function(pv) {
          EPICS_STATE.ws.send(JSON.stringify({
            action: 'put', pv: pv, value: _savedValues[pv]
          }));
          count++;
        });
        log('info', 'Pushed ' + count + ' motor values to server (high-velocity mode)');
        // Phase 3: Restore original velocities after 2 seconds
        setTimeout(function() {
          if (!EPICS_STATE.ws || EPICS_STATE.ws.readyState !== WebSocket.OPEN) return;
          Object.keys(_savedValues).forEach(function(pv) {
            var reg = PV_REGISTRY[pv];
            if (reg && reg.motor && reg.motor.speed > 0) {
              EPICS_STATE.ws.send(JSON.stringify({
                action: 'put', pv: pv + '.VELO', value: reg.motor.speed
              }));
            }
          });
          log('info', 'Restored original motor velocities');
        }, 2000);
      }, 200);

      // Guard clearance: per-PV convergence-based (see handlePVUpdate).
      // Also runs active polling every 3s to check if values already match
      // (handles race conditions where subscribe response arrives before
      // guard is set, or server doesn't send .RBV for some PV types).
      var _guardPollId = setInterval(function() {
        if (!EPICS_STATE._initialValues) { clearInterval(_guardPollId); return; }
        var pvList = Object.keys(EPICS_STATE._initialValues);
        pvList.forEach(function(pv) {
          var reg = PV_REGISTRY[pv];
          if (!reg) return;
          var saved = EPICS_STATE._initialValues[pv];
          var cur = reg.value;
          var tol = Math.max(0.05, Math.abs(saved) * 0.002);
          if (Math.abs(cur - saved) < tol) {
            delete EPICS_STATE._initialValues[pv];
          }
        });
        if (Object.keys(EPICS_STATE._initialValues).length === 0) {
          EPICS_STATE._initialValues = null;
          clearInterval(_guardPollId);
          log('info', 'All initial value guards cleared (poll)');
        }
      }, 3000);
      // Safety fallback: force clear after 30s
      setTimeout(function() {
        clearInterval(_guardPollId);
        if (EPICS_STATE._initialValues) {
          var remaining = Object.keys(EPICS_STATE._initialValues).length;
          if (remaining > 0) {
            log('warn', 'Guard timeout: ' + remaining + ' PVs still protected, clearing');
          }
          EPICS_STATE._initialValues = null;
        }
      }, 30000);

      // Re-fetch HW motor RBVs after 400ms so poll_loop has time to populate
      // fresh values from KOHZU IOC (initial subscribe response may be stale 0)
      setTimeout(function() {
        if (!EPICS_STATE.ws || EPICS_STATE.ws.readyState !== WebSocket.OPEN) return;
        Object.keys(PV_REGISTRY).forEach(function(pv) {
          var reg = PV_REGISTRY[pv];
          if (reg.motor && reg.source === 'hardware') {
            EPICS_STATE.ws.send(JSON.stringify({ action: 'get', pv: pv + '.RBV' }));
          }
        });
      }, 400);

      // Fetch motor limits and speeds once (LLM/HLM/VELO/DLLM/DHLM/LLS/HLS)
      setTimeout(function() {
        if (!EPICS_STATE.ws || EPICS_STATE.ws.readyState !== WebSocket.OPEN) return;
        Object.keys(PV_REGISTRY).forEach(function(pv) {
          var reg = PV_REGISTRY[pv];
          if (reg.motor) {
            var fields = ['.LLM', '.HLM', '.VELO', '.DLLM', '.DHLM', '.LLS', '.HLS'];
            for (var _fi = 0; _fi < fields.length; _fi++) {
              EPICS_STATE.ws.send(JSON.stringify({ action: 'get', pv: pv + fields[_fi] }));
            }
          }
        });
      }, 700);
    };

    EPICS_STATE.ws.onmessage = function(e) {
      EPICS_STATE.stats.messagesRecv++;
      EPICS_STATE.stats.lastUpdate = Date.now();
      try {
        var msg = JSON.parse(e.data);
        // D7: batch PV updates — server sends JSON array of PV messages
        if (Array.isArray(msg)) {
          for (var bi = 0; bi < msg.length; bi++) {
            var bm = msg[bi];
            handlePVUpdate(bm.pv || bm.name, bm.value, bm.severity || 0, bm.timestamp);
          }
          return;
        }
        // PV latency measurement
        if (msg._ts_pv_send && window._pvLatencyLog) {
          var recvTs = Date.now() / 1000;
          var latency = (recvTs - msg._ts_pv_send) * 1000;
          window._pvLatencyLog.push({
            pv: msg.pv || msg.name,
            ts_poll: msg.timestamp,
            ts_send: msg._ts_pv_send,
            ts_recv: recvTs,
            latency_send_to_recv_ms: latency
          });
        }
        // Handle pv_sources message (hybrid mode source info)
        if (msg.action === 'pv_sources' && msg.sources) {
          EPICS_STATE.pvSources = msg.sources;
          EPICS_STATE.hwGroups = msg.hw_groups || [];
          Object.keys(msg.sources).forEach(function(pvName) {
            var reg = PV_REGISTRY[pvName];
            if (reg) reg.source = msg.sources[pvName];
          });
          if (typeof updateEpicsUI === 'function') updateEpicsUI();
          log('info', 'PV sources: ' + (msg.hw_groups || []).join(',') + ' = hardware');
        } else if (msg.action === 'pv_discovered' && msg.pvs) {
          // PV Auto-Discovery: new PVs found from hardware IOC
          log('info', 'PV Discovery: ' + msg.pvs.length + ' new PV(s) found');
          if (typeof _handlePVDiscovered === 'function') _handlePVDiscovered(msg.pvs);
        } else if (msg.action === 'safety_reject') {
          // Safety layer rejected a move
          if (msg.code === 'CONFIRM_REQUIRED') {
            _showMoveConfirmDialog(msg.pv, msg.current, msg.target);
          } else if (msg.code === 'SOFT_LIMIT') {
            log('err', 'SAFETY: ' + msg.reason);
          } else {
            log('warn', 'Safety reject: ' + (msg.reason || 'unknown'));
          }
        } else {
          handlePVUpdate(msg.pv || msg.name, msg.value, msg.severity || 0, msg.timestamp);
        }
      } catch (err) {
        EPICS_STATE.stats.errors++;
      }
    };

    EPICS_STATE.ws.onclose = function() {
      EPICS_STATE.connected = false;
      log('warn', 'WebSocket disconnected');
      updateEpicsUI();
      // Auto-reconnect
      if (EPICS_STATE.mode === 'real') {
        scheduleReconnect();
      }
    };

    EPICS_STATE.ws.onerror = function(err) {
      EPICS_STATE.stats.errors++;
      log('err', 'WebSocket error');
    };

  } catch (e) {
    log('err', 'WebSocket failed: ' + e.message);
    EPICS_STATE.stats.errors++;
  }
}

function scheduleReconnect() {
  if (EPICS_STATE.reconnectAttempts >= EPICS_STATE.maxReconnect) {
    log('err', 'Max reconnect attempts reached');
    return;
  }
  var delay = Math.min(1000 * Math.pow(2, EPICS_STATE.reconnectAttempts), 30000);
  EPICS_STATE.reconnectAttempts++;
  log('warn', 'Reconnecting in ' + (delay/1000).toFixed(0) + 's (attempt ' + EPICS_STATE.reconnectAttempts + ')');
  EPICS_STATE.reconnectTimer = setTimeout(function() { connectEPICS(); }, delay);
}

function disconnectEPICS() {
  if (EPICS_STATE.ws) { EPICS_STATE.ws.close(); EPICS_STATE.ws = null; }
  if (EPICS_STATE.reconnectTimer) { clearTimeout(EPICS_STATE.reconnectTimer); }
  EPICS_STATE.connected = false;
  EPICS_STATE.reconnectAttempts = 0;
  disconnectScan();
  updateEpicsUI();
}

// ===== Scan WebSocket (Bluesky RunEngine) =====
function connectScan(url) {
  if (EPICS_STATE.scanWs) { EPICS_STATE.scanWs.close(); }
  EPICS_STATE.scanWsUrl = url || EPICS_STATE.scanWsUrl;

  try {
    EPICS_STATE.scanWs = new WebSocket(EPICS_STATE.scanWsUrl);

    EPICS_STATE.scanWs.onopen = function() {
      EPICS_STATE.scanConnected = true;
      log('info', 'Scan WebSocket connected: ' + EPICS_STATE.scanWsUrl);
      updateEpicsUI();
      // Request plan library from server to sync with PLAN_LIBRARY
      try {
        EPICS_STATE.scanWs.send(JSON.stringify({ action: 'list_plans' }));
      } catch (e) { /* ignore */ }
    };

    EPICS_STATE.scanWs.onmessage = function(e) {
      try {
        var msg = JSON.parse(e.data);
        // Latency measurement: record browser receive time
        if (msg.type === 'scan_event') {
          msg._ts_browser_recv = Date.now() / 1000;  // seconds (match Python time.time())
        }
        // Sync server plan library into PLAN_LIBRARY
        if (msg.type === 'scan_plans' && msg.plans && typeof PLAN_LIBRARY !== 'undefined') {
          var added = 0;
          msg.plans.forEach(function(p) {
            if (!PLAN_LIBRARY[p.name]) {
              PLAN_LIBRARY[p.name] = {
                name: p.name,
                label: p.desc || p.name,
                description: p.desc || '',
                category: 'server',
                params: {},
                detectors: [],
                motors: [],
                serverOnly: true
              };
              added++;
            }
          });
          if (added > 0) {
            log('info', 'Plan library synced: +' + added + ' server plans (total ' + Object.keys(PLAN_LIBRARY).length + ')');
            if (typeof renderBlueskyTab === 'function') renderBlueskyTab();
          }
        }
        // [DDD inline merged] Base: dispatch scan events
        if (msg.type === 'scan_event' && typeof window.handleScanEvent === 'function') {
          window.handleScanEvent(msg);
        }
        // [DDD inline merged from bluesky/06_live_scan.js] Enhanced live scan handler
        if (typeof _enhancedScanEventHandler === 'function') {
          try { _enhancedScanEventHandler(msg); } catch(e2) {}
        }
        // [DDD inline merged from bluesky/07_server_history.js] History response handler
        if (typeof _handleHistoryResponse === 'function') {
          try { _handleHistoryResponse(msg); } catch(e3) {}
        }
        // Scan data response (history row click)
        if (typeof _handleScanDataResponse === 'function') {
          try { _handleScanDataResponse(msg); } catch(e4) {}
        }
        // H5 download response
        if (typeof _handleH5Download === 'function') {
          try { _handleH5Download(msg); } catch(e5) {}
        }
      } catch (err) {
        log('err', 'Scan WS parse error');
      }
    };

    EPICS_STATE.scanWs.onclose = function() {
      EPICS_STATE.scanConnected = false;
      log('warn', 'Scan WebSocket disconnected');
      updateEpicsUI();
    };

    EPICS_STATE.scanWs.onerror = function() {
      // onclose will follow
    };
  } catch (e) {
    log('err', 'Scan WS connect failed: ' + e.message);
  }
}

function disconnectScan() {
  if (EPICS_STATE.scanWs) { EPICS_STATE.scanWs.close(); EPICS_STATE.scanWs = null; }
  EPICS_STATE.scanConnected = false;
}

function handlePVUpdate(pvName, value, severity, timestamp) {
  var reg = PV_REGISTRY[pvName];
  var basePV = pvName;
  var isRBV = false;
  // Handle .RBV suffix from server -> find base motor PV
  if (!reg && pvName.indexOf('.RBV') === pvName.length - 4) {
    basePV = pvName.slice(0, -4);
    reg = PV_REGISTRY[basePV];
    isRBV = true;
  }
  // Handle motor configuration fields: .LLM/.HLM/.VELO/.DLLM/.DHLM/.LLS/.HLS
  if (!reg && !isRBV) {
    var _cfgMap = { '.LLM': 'llm', '.HLM': 'hlm', '.VELO': 'velo', '.DLLM': 'dllm', '.DHLM': 'dhlm', '.LLS': 'lls', '.HLS': 'hls' };
    var _cfgKeys = ['.DLLM', '.DHLM', '.LLS', '.HLS', '.LLM', '.HLM', '.VELO'];
    for (var _ci = 0; _ci < _cfgKeys.length; _ci++) {
      var _suf = _cfgKeys[_ci];
      if (pvName.length > _suf.length && pvName.slice(-_suf.length) === _suf) {
        var _cfgBase = pvName.slice(0, -_suf.length);
        var _cfgReg = PV_REGISTRY[_cfgBase];
        if (_cfgReg && _cfgReg.motor) {
          _cfgReg.motor[_cfgMap[_suf]] = value;
          if (typeof _updateMotorLimitDisplay === 'function') _updateMotorLimitDisplay(_cfgBase);
        }
        return;
      }
    }
  }
  if (reg) {
    reg.timestamp = timestamp || Date.now() / 1000;
    reg.connected = true;
    // Guard: during initial sync after Virtual->Real mode switch, protect
    // motor values from being overwritten by server defaults or intermediate
    // ramp positions. Checks both .RBV and base PV updates (some PVs
    // may not have .RBV in the server PVStore).
    if (EPICS_STATE._initialValues && EPICS_STATE._initialValues[basePV] !== undefined) {
      var _guardVal = EPICS_STATE._initialValues[basePV];
      var _guardTol = Math.max(0.05, Math.abs(_guardVal) * 0.002);
      if (Math.abs(value - _guardVal) < _guardTol) {
        // Server value converged to saved value -- clear guard for this PV
        delete EPICS_STATE._initialValues[basePV];
        if (Object.keys(EPICS_STATE._initialValues).length === 0) {
          EPICS_STATE._initialValues = null;
          log('info', 'All initial value guards cleared');
        }
        // Use server value (matches saved value)
      } else {
        // Motor still ramping or server default -- use saved value
        value = _guardVal;
      }
    }
    if (isRBV) {
      // Server readback -> actual motor position
      reg.value = value;
      reg.severity = severity;
      if (reg.motor) {
        reg.motor.value = value;
        // Update motor jog panel DOM directly (static HTML, not re-rendered on value change)
        var _posEl = document.getElementById('mval_' + reg.motorId);
        if (_posEl) _posEl.textContent = value.toFixed(3);
        var _absEl = document.getElementById('mot_' + reg.groupId + '_' + reg.motorId + 'abs');
        if (_absEl && document.activeElement !== _absEl) _absEl.value = value.toFixed(4);
        if (typeof syncMotorToState === 'function')
          syncMotorToState(reg.groupId, reg.motorId, value);
      }
    } else if (reg.motor && EPICS_STATE.mode === 'real') {
      // Setpoint PV in real mode -> update target only, wait for .RBV
      reg.severity = severity;
      reg.motor.target = value;
    } else {
      // Sim mode or status PV (motor===null) -> direct update
      reg.value = value;
      reg.severity = severity;
      if (reg.motor) {
        reg.motor.value = value;
        if (typeof syncMotorToState === 'function')
          syncMotorToState(reg.groupId, reg.motorId, value);
      }
    }
    // Notify callbacks (pass original pvName so listeners distinguish setpoint vs RBV)
    reg.callbacks.forEach(function(cb) { cb(pvName, value, severity, timestamp); });
  }
  updatePVMonitorRow(basePV, reg ? reg.value : value, severity);
}

// ===== EPICS caput via active connection =====
function epicsPut(pvName, value, opts) {
  opts = opts || {};
  if (EPICS_STATE.mode === 'sim' && EPICS_STATE.simIOC) {
    return EPICS_STATE.simIOC.caput(pvName, value);
  }
  if (EPICS_STATE.ws && EPICS_STATE.connected) {
    var msg = { action: 'put', pv: pvName, value: value };
    if (opts.confirmed) msg.confirmed = true;
    EPICS_STATE.ws.send(JSON.stringify(msg));
    EPICS_STATE.stats.messagesSent++;
    return true;
  }
  log('warn', 'epicsPut failed: not connected (' + pvName + ')');
  return false;
}

function epicsGet(pvName) {
  if (EPICS_STATE.mode === 'sim' && EPICS_STATE.simIOC) {
    return EPICS_STATE.simIOC.caget(pvName);
  }
  var reg = PV_REGISTRY[pvName];
  return reg ? { value: reg.value, severity: reg.severity, timestamp: reg.timestamp } : null;
}

// ===== Subscribe/Unsubscribe to PV updates =====
function pvSubscribe(pvName, callback) {
  var reg = PV_REGISTRY[pvName];
  if (reg) { reg.callbacks.push(callback); return true; }
  return false;
}

function pvUnsubscribe(pvName, callback) {
  var reg = PV_REGISTRY[pvName];
  if (reg) { reg.callbacks = reg.callbacks.filter(function(cb) { return cb !== callback; }); }
}

// ===== EPICS Mode Switching =====
function setEpicsMode(mode) {
  // Stop existing connections
  if (EPICS_STATE.simIOC) { EPICS_STATE.simIOC.stop(); EPICS_STATE.simIOC = null; }
  disconnectEPICS();

  EPICS_STATE.mode = mode;
  log('info', 'EPICS mode -> ' + mode.toUpperCase());

  switch (mode) {
    case 'sim':
      EPICS_STATE.simIOC = new SimIOC();
      EPICS_STATE.simIOC.start();
      // Mark all PVs connected + clear HW source badges from previous real mode
      Object.values(PV_REGISTRY).forEach(function(r) { r.connected = true; r.source = 'simulation'; });
      EPICS_STATE.stats.connectedPVs = Object.keys(PV_REGISTRY).length;
      EPICS_STATE.pvSources = {};
      EPICS_STATE.hwGroups = [];
      break;
    case 'real':
      connectEPICS();
      break;
    case 'hybrid':
      // Redirect to real mode: server CA Bridge handles HW/SIM routing
      setEpicsMode('real');
      return;
    case 'disconnected':
      Object.values(PV_REGISTRY).forEach(function(r) { r.connected = false; delete r.source; });
      EPICS_STATE.stats.connectedPVs = 0;
      EPICS_STATE.pvSources = {};
      EPICS_STATE.hwGroups = [];
      break;
  }
  updateEpicsUI();

  // Trigger MC ray trace after mode switch so beam profile updates immediately
  setTimeout(function() {
    if (typeof _invalidateMCCache === 'function') _invalidateMCCache();
    if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
  }, 300);
}

// ===== PV Monitor UI =====
var PV_MONITOR_GROUPS = [
  { name: 'Ring Status', pvs: ['BL10:RING:Current', 'BL10:RING:Energy', 'BL10:RING:Lifetime', 'BL10:FE:Shutter'] },
  { name: 'IVU', pvs: ['BL10:IVU:Gap'] },
  { name: 'DCM', pvs: ['BL10:DCM:Theta', 'BL10:DCM:Chi1', 'BL10:DCM:Y2', 'BL10:DCM:Z2'] },
  { name: 'Mirrors', pvs: ['BL10:M1:Pitch', 'BL10:M1:PitchF', 'BL10:M2:Pitch', 'BL10:M2:PitchF'] },
  { name: 'Slits', pvs: ['BL10:WBS:Hgap', 'BL10:WBS:Vgap', 'BL10:SSA:Hgap', 'BL10:SSA:Vgap'] },
  { name: 'KB', pvs: ['BL10:KBV:Pitch', 'BL10:KBH:Pitch'] },
  { name: 'Sample', pvs: ['BL10:SAM:CX', 'BL10:SAM:CY', 'BL10:SAM:CZ', 'BL10:SAM:FX', 'BL10:SAM:FY', 'BL10:SAM:FZ', 'BL10:SAM:Theta', 'BL10:SAM:Phi'] },
  { name: 'BPM', pvs: ['BL10:XBPM1:X', 'BL10:XBPM1:Y', 'BL10:XBPM2:PosX:MeanValue_RBV', 'BL10:XBPM2:PosY:MeanValue_RBV', 'BL10:XBPM2:SumAll:MeanValue_RBV'] },
  { name: 'Diagnostics', pvs: ['BL10:IC1:Current'] }
];

// Find motor object by PV name
function _findMotorByPV(pvName) {
  if (typeof MOTORS === 'undefined') return null;
  for (var grpId in MOTORS) {
    var grp = MOTORS[grpId];
    if (!grp || typeof grp !== 'object') continue;
    for (var key in grp) {
      var m = grp[key];
      if (m && m.pv === pvName) return { groupId: grpId, motorId: m.id, motor: m };
    }
  }
  return null;
}

// Limit status: 'ok' | 'near' | 'at' | null (not a motor)
function _pvLimitStatus(pvName) {
  var info = _findMotorByPV(pvName);
  if (!info) return null;
  var m = info.motor;
  var val = m.value;
  if (typeof val !== 'number') return null;
  var reg = (typeof PV_REGISTRY !== 'undefined' && m.pv) ? PV_REGISTRY[m.pv] : null;
  var motor = reg ? reg.motor : m;
  var llm = (motor && typeof motor.llm === 'number') ? motor.llm : m.min;
  var hlm = (motor && typeof motor.hlm === 'number') ? motor.hlm : m.max;
  if (typeof llm !== 'number' || typeof hlm !== 'number') return null;
  var range = hlm - llm;
  if (range <= 0) return null;
  var margin = range * 0.05;
  // Check hard limit switches
  var lls = (motor && motor.lls) ? 1 : 0;
  var hls = (motor && motor.hls) ? 1 : 0;
  if (lls || hls) return 'at';
  if (val <= llm || val >= hlm) return 'at';
  if (val <= llm + margin || val >= hlm - margin) return 'near';
  return 'ok';
}

function renderPVMonitor() {
  var el = document.getElementById('pvMonitorBody');
  if (!el) return;
  var h = '';
  PV_MONITOR_GROUPS.forEach(function(grp) {
    h += '<div style="font-size:8px;color:var(--pr);margin:6px 0 2px;letter-spacing:1px;font-weight:600">' + grp.name + '</div>';
    grp.pvs.forEach(function(pv) {
      var reg = PV_REGISTRY[pv];
      var simPV = EPICS_STATE.simIOC ? EPICS_STATE.simIOC.pvs[pv] : null;
      var val = reg ? reg.value : (simPV ? simPV.value : '--');
      var sev = reg ? reg.severity : 0;
      var conn = reg ? reg.connected : (simPV ? true : false);
      var sevCls = sev === 0 ? 'var(--gn)' : sev === 1 ? 'var(--am)' : 'var(--rd)';
      var connDot = conn ? '<span style="color:var(--gn)">&#9679;</span>' : '<span style="color:var(--rd)">&#9675;</span>';
      var shortPV = pv.replace('BL10:', '');
      var fmtVal = typeof val === 'number' ? (Math.abs(val) < 0.001 && val !== 0 ? val.toExponential(2) : val.toFixed(4)) : val;
      var moving = (EPICS_STATE.simIOC && EPICS_STATE.simIOC.isMoving(pv)) ? '<span style="color:var(--am);font-size:8px"> &#9654;</span>' : '';
      var srcBadge = '';
      if (reg && reg.source === 'hardware') {
        srcBadge = '<span style="color:var(--gn);font-size:7px;font-weight:700;margin-left:2px">HW</span>';
      } else if (reg && reg.source === 'simulation') {
        srcBadge = '<span style="color:var(--t3);font-size:7px;margin-left:2px">SIM</span>';
      }
      // Limit status indicator for motor PVs
      var limStatus = _pvLimitStatus(pv);
      var limIcon = '';
      if (limStatus === 'at') {
        limIcon = '<span title="At limit" style="color:var(--rd);font-size:7px;margin-left:1px">&#9632;</span>';
      } else if (limStatus === 'near') {
        limIcon = '<span title="Near limit" style="color:var(--am);font-size:7px;margin-left:1px">&#9650;</span>';
      }
      // Click handler: motor PV -> motor detail popup, other -> PV detail popup
      var mInfo = _findMotorByPV(pv);
      var clickAttr = '';
      if (mInfo) {
        clickAttr = ' onclick="_showMotorDetailsPopup(\'' + mInfo.groupId + '\',\'' + mInfo.motorId + '\')" style="display:flex;justify-content:space-between;align-items:center;padding:1px 4px;border-bottom:1px solid rgba(80,160,255,.03);cursor:pointer"';
      } else {
        clickAttr = ' onclick="_showPVDetailPopup(\'' + pv.replace(/'/g, "\\'") + '\')" style="display:flex;justify-content:space-between;align-items:center;padding:1px 4px;border-bottom:1px solid rgba(80,160,255,.03);cursor:pointer"';
      }
      h += '<div class="pv-row" id="pvr_' + pv.replace(/[:.]/g,'_') + '"' + clickAttr + '>' +
        '<span style="display:flex;align-items:center;gap:3px">' + connDot + '<span style="color:var(--t2);font-size:8px">' + shortPV + '</span>' + srcBadge + moving + limIcon + '</span>' +
        '<span style="color:' + sevCls + ';font-size:9px;font-weight:500">' + fmtVal + '</span>' +
      '</div>';
    });
  });
  el.innerHTML = h;
}

// ===== PV Detail Popup (non-motor PVs) =====
window._showPVDetailPopup = function(pvName) {
  var existing = document.getElementById('pvDetailOverlay');
  if (existing) existing.remove();

  var reg = PV_REGISTRY[pvName];
  var simPV = EPICS_STATE.simIOC ? EPICS_STATE.simIOC.pvs[pvName] : null;
  var val = reg ? reg.value : (simPV ? simPV.value : '--');
  var conn = reg ? reg.connected : (simPV ? true : false);
  var sev = reg ? reg.severity : 0;
  var src = reg ? (reg.source || 'unknown') : 'simulation';
  var shortPV = pvName.replace('BL10:', '');

  var isHw = src === 'hardware';
  var srcBadge = isHw
    ? '<span style="background:var(--gn);color:#000;font-size:11px;font-weight:700;padding:2px 7px;border-radius:2px">HW</span>'
    : '<span style="background:var(--s2);color:var(--t1);font-size:11px;padding:2px 7px;border-radius:2px;border:1px solid var(--b1)">SIM</span>';
  var connBadge = conn
    ? '<span style="color:var(--gn);font-size:11px">Connected</span>'
    : '<span style="color:var(--rd);font-size:11px">Disconnected</span>';
  var sevLabel = sev === 0 ? 'NO_ALARM' : sev === 1 ? 'MINOR' : 'MAJOR';
  var sevColor = sev === 0 ? 'var(--gn)' : sev === 1 ? 'var(--am)' : 'var(--rd)';

  var fmtVal = typeof val === 'number' ? val.toFixed(6) : String(val);

  var _pvdContent =
    '<div style="font-size:12px;color:var(--t2);margin-bottom:14px">' + shortPV + ' ' + srcBadge + '<br>' + pvName + '</div>' +
    // Value
    '<div style="background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:12px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center">' +
      '<div>' +
        '<div style="font-size:12px;color:var(--t2);margin-bottom:3px">Current Value</div>' +
        '<div style="font-size:24px;font-weight:700;color:var(--gn)" id="pvd_val">' + fmtVal + '</div>' +
      '</div>' +
      '<div style="text-align:right">' +
        '<div style="font-size:12px;color:var(--t2);margin-bottom:3px">Severity</div>' +
        '<div style="font-size:14px;color:' + sevColor + '">' + sevLabel + '</div>' +
      '</div>' +
    '</div>' +
    // Status
    '<div style="display:flex;gap:10px;margin-bottom:14px">' +
      '<div style="flex:1;background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:10px">' +
        '<div style="font-size:11px;color:var(--t2);margin-bottom:4px">Connection</div>' +
        '<div>' + connBadge + '</div>' +
      '</div>' +
      '<div style="flex:1;background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:10px">' +
        '<div style="font-size:11px;color:var(--t2);margin-bottom:4px">Source</div>' +
        '<div style="font-size:12px">' + src + '</div>' +
      '</div>' +
    '</div>' +
    // Mini trend chart
    '<div style="background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:10px;margin-bottom:14px">' +
      '<div style="font-size:11px;color:var(--t2);margin-bottom:6px">Trend (last 5 min)</div>' +
      '<div id="pvd_trend" style="width:100%;height:120px"></div>' +
    '</div>' +
    // Actions
    '<div style="display:flex;gap:8px;justify-content:flex-end">' +
      '<button onclick="setTrendPV(\'' + pvName.replace(/'/g, "\\'") + '\');toggleTrendPopup();var _pp=document.getElementById(\'pv_'+pvName.replace(/[:.]/g,'_')+'\');if(_pp&&_pp._popupAPI)_pp._popupAPI.close()" ' +
      'style="background:var(--s2);border:1px solid var(--ac);color:var(--ac);font-size:13px;padding:6px 16px;border-radius:4px;cursor:pointer">Open in Trend</button>' +
      '<button onclick="var _pp=document.getElementById(\'pv_'+pvName.replace(/[:.]/g,'_')+'\');if(_pp&&_pp._popupAPI)_pp._popupAPI.close()" ' +
      'style="background:var(--s2);border:1px solid var(--b1,#444);color:var(--t1);font-size:13px;padding:6px 16px;border-radius:4px;cursor:pointer">Close</button>' +
    '</div>';

  var _pvdId = 'pv_' + pvName.replace(/[:.]/g, '_');
  if (typeof _openPopup === 'function') {
    _openPopup({
      id: _pvdId,
      title: shortPV,
      width: 320, height: 440,
      content: _pvdContent,
      resizable: true, minWidth: 360, minHeight: 300,
      headerColor: isHw ? 'var(--gn)' : 'var(--ac)'
    });
  }

  // Helper: render mini trend chart into pvd_trend div
  function _renderPvdTrend() {
    var trendDiv = document.getElementById('pvd_trend');
    if (!trendDiv || typeof _drawChart1D !== 'function') return;
    var trace = PV_ARCHIVE.traces[pvName];
    if (!trace || trace.length < 2) {
      trendDiv.innerHTML = '<div style="color:var(--t3);font-size:10px;text-align:center;padding-top:40px">No trend data</div>';
      return;
    }
    // Clear previous chart content before re-render
    trendDiv.innerHTML = '';
    var data = [];
    var t0 = trace[0].t;
    for (var i = 0; i < trace.length; i++) {
      data.push({ x: (trace[i].t - t0) / 1000, y: trace[i].v });
    }
    function tFmt(v) {
      var s = Math.round(v); var m = Math.floor(s / 60); s = s % 60;
      return m + ':' + (s < 10 ? '0' : '') + s;
    }
    var tw = trendDiv.clientWidth || 400;
    var th = trendDiv.clientHeight || 120;
    _drawChart1D(trendDiv, data, {
      color: '#4db8ff', xlabel: '', ylabel: '', title: '',
      nTicksX: 5, nTicksY: 4, xFmt: tFmt, useCanvas: true,
      width: tw, height: th
    });
  }

  // Draggable + resizable with re-render callback
  var titleEl = document.getElementById('pvDetailTitleBar');
  if (typeof _makePopupResizable === 'function') {
    _makePopupResizable(dlg, {
      dragEl: titleEl, minWidth: 380, minHeight: 300,
      onResize: function() {
        // onMove passes (w,h) args — skip during drag (CSS handles stretching)
        if (arguments.length > 0) return;
        // onUp (no args) — re-render the trend chart
        _renderPvdTrend();
      }
    });
  }

  // Initial render
  setTimeout(_renderPvdTrend, 100);

  // Live update timer
  var _pvdTimer = setInterval(function() {
    if (!document.getElementById('pvDetailOverlay')) { clearInterval(_pvdTimer); return; }
    var r = PV_REGISTRY[pvName];
    var s = EPICS_STATE.simIOC ? EPICS_STATE.simIOC.pvs[pvName] : null;
    var v = r ? r.value : (s ? s.value : '--');
    var vEl = document.getElementById('pvd_val');
    if (vEl) vEl.textContent = typeof v === 'number' ? v.toFixed(6) : String(v);
  }, 1000);
};

function updatePVMonitorRow(pvName, value, severity) {
  var rowId = 'pvr_' + pvName.replace(/[:.]/g, '_');
  var row = document.getElementById(rowId);
  if (!row) return;
  var spans = row.querySelectorAll('span');
  if (spans.length >= 4) {
    var sevCls = severity === 0 ? 'var(--gn)' : severity === 1 ? 'var(--am)' : 'var(--rd)';
    var fmtVal = typeof value === 'number' ? (Math.abs(value) < 0.001 && value !== 0 ? value.toExponential(2) : value.toFixed(4)) : value;
    spans[spans.length - 1].style.color = sevCls;
    spans[spans.length - 1].textContent = fmtVal;
  }
}

// ===== EPICS Tab UI =====
function updateEpicsUI() {
  // Connection status
  var stEl = document.getElementById('epicsStatus');
  if (stEl) {
    var m = EPICS_STATE.mode;
    var labels = { disconnected: 'DISCONNECTED', sim: 'SimIOC ACTIVE', real: 'REAL EPICS' };
    var colors = { disconnected: 'var(--t3)', sim: 'var(--gn)', real: 'var(--ac)' };
    stEl.innerHTML = '<span style="color:' + colors[m] + '">' + labels[m] + '</span>';
  }

  // Stats
  var statsEl = document.getElementById('epicsStats');
  if (statsEl) {
    var s = EPICS_STATE.stats;
    var pvCount = Object.keys(PV_REGISTRY).length;
    var connPVs = Object.values(PV_REGISTRY).filter(function(r) { return r.connected; }).length;
    var simPVs = EPICS_STATE.simIOC ? Object.keys(EPICS_STATE.simIOC.pvs).length : 0;
    var scanStatus = EPICS_STATE.scanConnected ? '<span style="color:var(--gn)">READY</span>' : '<span style="color:var(--t3)">OFF</span>';
    statsEl.innerHTML =
      '<div class="ctrl-label">Motor PVs<span class="ctrl-val">' + pvCount + '</span></div>' +
      '<div class="ctrl-label">Connected<span class="ctrl-val" style="color:' + (connPVs > 0 ? 'var(--gn)' : 'var(--rd)') + '">' + connPVs + '/' + pvCount + '</span></div>' +
      '<div class="ctrl-label">SimIOC PVs<span class="ctrl-val">' + simPVs + '</span></div>' +
      '<div class="ctrl-label">Bluesky<span class="ctrl-val">' + scanStatus + '</span></div>';
  }

  // Render PV monitor
  renderPVMonitor();

  // Update top bar LED
  var led = document.querySelector('.led');
  if (led) {
    if (EPICS_STATE.mode === 'sim') { led.style.background = 'var(--gn)'; led.style.boxShadow = '0 0 6px var(--gn)'; }
    else if (EPICS_STATE.mode === 'real') { led.style.background = 'var(--ac)'; led.style.boxShadow = '0 0 6px var(--ac)'; }
    else { led.style.background = '#666'; led.style.boxShadow = 'none'; }
  }
}

// ===== PV Caput from UI =====
function pvPutFromUI(pvName, inputId) {
  var el = document.getElementById(inputId);
  if (!el) return;
  var val = parseFloat(el.value);
  if (isNaN(val)) { log('warn', 'Invalid value'); return; }
  epicsPut(pvName, val);
}

// ===== Initialize EPICS subsystem =====
function initEPICS() {
  buildPVRegistry();
  EPICS_STATE.stats.pvCount = Object.keys(PV_REGISTRY).length;
  log('info', 'EPICS init: ' + EPICS_STATE.stats.pvCount + ' PVs registered');

  // Auto-start SimIOC in virtual mode
  setEpicsMode('sim');

  // Periodic PV monitor refresh (every 500ms) -- individual row updates, no innerHTML flicker
  setInterval(function() {
    if (EPICS_STATE.mode !== 'disconnected') {
      PV_MONITOR_GROUPS.forEach(function(grp) {
        grp.pvs.forEach(function(pv) {
          var reg = PV_REGISTRY[pv];
          var simPV = EPICS_STATE.simIOC ? EPICS_STATE.simIOC.pvs[pv] : null;
          var val = reg ? reg.value : (simPV ? simPV.value : '--');
          var sev = reg ? reg.severity : 0;
          updatePVMonitorRow(pv, val, sev);
        });
      });
      updateEpicsStatsBar();
    }
  }, 500);
}

// ===== Live stats in bottom bar =====
function updateEpicsStatsBar() {
  var el = document.getElementById('epicsLiveStats');
  if (!el) return;
  var m = EPICS_STATE.mode;
  var pvC = Object.keys(PV_REGISTRY).length;
  var connC = Object.values(PV_REGISTRY).filter(function(r) { return r.connected; }).length;
  var col = { disconnected: '#666', sim: 'var(--gn)', real: 'var(--ac)', hybrid: 'var(--am)' };
  // Use textContent to avoid flicker (runs every 500ms)
  if (!el.querySelector('.epics-dot')) {
    el.innerHTML = '<span class="epics-dot" style="color:#666">\u2B24</span> <span class="epics-txt"></span>';
  }
  var dot = el.querySelector('.epics-dot');
  var txt = el.querySelector('.epics-txt');
  if (dot) dot.style.color = col[m] || '#666';
  if (txt) txt.textContent = 'EPICS:' + m.toUpperCase() + ' ' + connC + '/' + pvC + 'PV';
}

// ===== PV Archiver -- In-Memory Time-Series History =====
var PV_ARCHIVE = {
  maxPoints: 300,      // ~5min @ 1Hz
  interval: 1000,      // 1s sampling
  timer: null,
  traces: {},          // pvName -> [{t, v}]
  watching: []         // PVs currently being archived
};

function pvArchiveStart() {
  // Default watch list: key operational PVs
  PV_ARCHIVE.watching = [
    'BL10:RING:Current', 'BL10:RING:Lifetime',
    'BL10:IVU:Gap', 'BL10:DCM:Theta',
    'BL10:XBPM1:X', 'BL10:XBPM1:Y',
    'BL10:XBPM2:PosX:MeanValue_RBV', 'BL10:XBPM2:PosY:MeanValue_RBV',
    'BL10:IC1:Current',
    'BL10:M1:Pitch', 'BL10:M2:Pitch',
    'BL10:WBS:Hgap', 'BL10:WBS:Vgap',
    'BL10:SSA:Hgap', 'BL10:SSA:Vgap'
  ];
  PV_ARCHIVE.watching.forEach(function(pv) { PV_ARCHIVE.traces[pv] = []; });

  PV_ARCHIVE.timer = setInterval(function() {
    var now = Date.now();
    PV_ARCHIVE.watching.forEach(function(pv) {
      var result = epicsGet(pv);
      if (!result) return;
      var trace = PV_ARCHIVE.traces[pv];
      trace.push({ t: now, v: result.value });
      while (trace.length > PV_ARCHIVE.maxPoints) trace.shift();
    });
  }, PV_ARCHIVE.interval);
  log('info', 'PV Archiver: tracking ' + PV_ARCHIVE.watching.length + ' PVs @ 1Hz');
}

function pvArchiveStop() {
  if (PV_ARCHIVE.timer) { clearInterval(PV_ARCHIVE.timer); PV_ARCHIVE.timer = null; }
}

function pvArchiveExport(pvName) {
  var trace = PV_ARCHIVE.traces[pvName];
  if (!trace || !trace.length) { log('warn', 'No archive data for ' + pvName); return; }
  var csv = 'Timestamp,Value\n';
  trace.forEach(function(p) {
    csv += new Date(p.t).toISOString() + ',' + p.v + '\n';
  });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'}));
  a.download = pvName.replace(/:/g, '_') + '_archive.csv';
  a.click();
  log('info', 'Exported ' + pvName + ' archive (' + trace.length + ' pts)');
}

// ===== P3-4: Network Latency Measurement =====
function measureLatency() {
  if (!EPICS_STATE.ws || !EPICS_STATE.connected) {
    EPICS_STATE.stats.latencyMs = -1;
    return;
  }
  var t0 = performance.now();
  // Send a lightweight read request
  EPICS_STATE.ws.send(JSON.stringify({ action: 'get', pv: 'BL10:RING:Current' }));
  var origHandler = EPICS_STATE.ws.onmessage;
  EPICS_STATE.ws.onmessage = function(e) {
    EPICS_STATE.stats.latencyMs = (performance.now() - t0).toFixed(1);
    EPICS_STATE.ws.onmessage = origHandler;
    if (origHandler) origHandler(e);
  };
  // Timeout fallback
  setTimeout(function() {
    if (EPICS_STATE.stats.latencyMs === -1) {
      EPICS_STATE.stats.latencyMs = 'timeout';
    }
  }, 5000);
}

// Periodic latency check (every 10s when connected to real)
setInterval(function() {
  if (EPICS_STATE.mode === 'real') {
    measureLatency();
  }
}, 10000);

// ===== PV Latency Measurement Utilities =====
// Usage from browser console:
//   startPVLatencyLog()   -- start collecting PV update latencies
//   stopPVLatencyLog()    -- stop and print summary
//   window._pvLatencyLog  -- raw data array
window.startPVLatencyLog = function() {
  window._pvLatencyLog = [];
  console.log('[PV Latency] Logging started. Move some motors, then call stopPVLatencyLog()');
};
window.stopPVLatencyLog = function() {
  if (!window._pvLatencyLog || window._pvLatencyLog.length === 0) {
    console.log('[PV Latency] No data collected.');
    return;
  }
  var data = window._pvLatencyLog;
  var vals = data.map(function(e) { return e.latency_send_to_recv_ms; }).sort(function(a,b){return a-b;});
  var sum = vals.reduce(function(a,b){return a+b;}, 0);
  var median = vals[Math.floor(vals.length/2)];
  var p10 = vals[Math.floor(vals.length*0.1)];
  var p90 = vals[Math.floor(vals.length*0.9)];
  console.log('========== PV LATENCY SUMMARY ==========');
  console.log('PV updates measured: ' + vals.length);
  console.log('Server-send to browser-recv: median=' + median.toFixed(1) + 'ms, mean=' + (sum/vals.length).toFixed(1) + 'ms');
  console.log('  min=' + vals[0].toFixed(1) + 'ms, max=' + vals[vals.length-1].toFixed(1) + 'ms');
  console.log('  P10=' + p10.toFixed(1) + 'ms, P90=' + p90.toFixed(1) + 'ms');
  console.log('Note: Add ~100ms polling interval (server-side) for total IOC-to-browser latency');
  console.log('Raw data: JSON.stringify(window._pvLatencyLog)');
  console.log('=========================================');
  window._pvLatencyLog = null;
};

// ===== PV Auto-Discovery Handler =====
function _handlePVDiscovered(pvs) {
  if (!pvs || pvs.length === 0) return;

  // Show toast notification
  pvs.forEach(function(pv) {
    log('info', 'New HW PV: ' + pv.name + ' = ' + pv.value);
  });

  // Build placement dialog
  var overlay = document.createElement('div');
  overlay.id = 'pvDiscoverOverlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center';

  var dialog = document.createElement('div');
  dialog.style.cssText = 'background:var(--s1);border:1px solid var(--ac);border-radius:8px;padding:16px;max-width:420px;width:90%;color:var(--t1);font-family:var(--mn);box-shadow:0 8px 32px rgba(0,0,0,0.5)';

  var h = '<h3 style="margin:0 0 8px;font-size:12px;color:var(--gn)">New Hardware PV(s) Detected</h3>';
  h += '<div style="font-size:9px;color:var(--t3);margin-bottom:12px">' + pvs.length + ' PV(s) found from hardware IOC</div>';

  // List each discovered PV with placement options
  pvs.forEach(function(pv, idx) {
    var shortName = pv.name.replace('BL10:', '');
    h += '<div style="border:1px solid var(--b1);border-radius:4px;padding:8px;margin-bottom:8px;background:var(--s2)">';
    h += '<div style="display:flex;justify-content:space-between;align-items:center">';
    h += '<span style="font-size:10px;font-weight:700;color:var(--gn)">' + shortName + '</span>';
    h += '<span style="font-size:8px;color:var(--t3)">val=' + (typeof pv.value === 'number' ? pv.value.toFixed(3) : pv.value) + '</span>';
    h += '</div>';
    h += '<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">';

    // Device group options
    var devices = typeof DEVICE_CONFIGS !== 'undefined' ? DEVICE_CONFIGS : [];
    devices.forEach(function(dev) {
      h += '<button class="sb" style="font-size:8px;padding:2px 6px" onclick="_pvDiscoverPlace(' + idx + ',\'' + dev.id + '\')">' + dev.label + '</button>';
    });
    h += '<button class="sb" style="font-size:8px;padding:2px 6px;color:var(--t3)" onclick="_pvDiscoverIgnore(' + idx + ')">Ignore</button>';
    h += '</div></div>';
  });

  h += '<div style="text-align:right;margin-top:8px">';
  h += '<button class="sb" style="font-size:9px;padding:4px 12px" onclick="_pvDiscoverClose()">Close</button>';
  h += '</div>';

  dialog.innerHTML = h;
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  // Store discovered PVs for placement actions
  window._discoveredPVs = pvs;
}

function _pvDiscoverPlace(pvIdx, deviceId) {
  var pvs = window._discoveredPVs;
  if (!pvs || !pvs[pvIdx]) return;
  var pv = pvs[pvIdx];

  // Extract axis key from PV name (e.g. BL10:SAM:RX -> rx)
  var parts = pv.name.split(':');
  var axSuffix = parts[parts.length - 1];
  var axKey = axSuffix.toLowerCase();

  var dev = typeof DEVICE_REGISTRY !== 'undefined' ? DEVICE_REGISTRY[deviceId] : null;
  if (!dev) { log('err', 'Device not found: ' + deviceId); return; }

  var axisCfg = {
    pvSuffix: axSuffix,
    name: axSuffix,
    unit: pv.unit || 'mm',
    min: pv.limits ? pv.limits[0] : -100,
    max: pv.limits ? pv.limits[1] : 100,
    step: 0.01,
    init: pv.value || 0,
    resolution: 0.001,
    speed: 1
  };

  if (typeof addMotorAxis === 'function') {
    var ok = addMotorAxis(deviceId, axKey, axisCfg);
    if (ok) {
      log('info', 'Added ' + pv.name + ' to ' + dev.label + ' as ' + axKey);
      // Subscribe to new PV
      if (typeof epicsSubscribe === 'function') epicsSubscribe(pv.name);
    }
  }

  // Mark as placed in UI
  var btn = document.querySelector('#pvDiscoverOverlay');
  if (btn) {
    pvs[pvIdx]._placed = true;
    // Check if all placed/ignored
    var allDone = pvs.every(function(p) { return p._placed || p._ignored; });
    if (allDone) _pvDiscoverClose();
  }
}

function _pvDiscoverIgnore(pvIdx) {
  var pvs = window._discoveredPVs;
  if (!pvs || !pvs[pvIdx]) return;
  pvs[pvIdx]._ignored = true;
  log('info', 'Ignored discovered PV: ' + pvs[pvIdx].name);
  var allDone = pvs.every(function(p) { return p._placed || p._ignored; });
  if (allDone) _pvDiscoverClose();
}

function _pvDiscoverClose() {
  var el = document.getElementById('pvDiscoverOverlay');
  if (el) el.remove();
  window._discoveredPVs = null;
}

// ===== Motor Limit Display Update =====
// Called from handlePVUpdate when .LLM/.HLM/.VELO arrives
window._updateMotorLimitDisplay = function(basePV) {
  var reg = PV_REGISTRY[basePV];
  if (!reg || !reg.motor) return;
  var m = reg.motor;
  var limEl = document.getElementById('mlim_' + reg.motorId);
  if (!limEl) return;
  var llm = typeof m.llm === 'number' ? m.llm : m.min;
  var hlm = typeof m.hlm === 'number' ? m.hlm : m.max;
  limEl.textContent = llm.toFixed(2) + '~' + hlm.toFixed(2) + ' ' + (m.unit || '');
};

// ===== Safety Confirmation Dialog for Hardware Motor Moves =====
function _showMoveConfirmDialog(pvName, current, target) {
  // Remove existing dialog if any
  var existing = document.getElementById('safetyConfirmOverlay');
  if (existing) existing.remove();

  var shortPV = pvName.replace('BL10:', '');
  var reg = PV_REGISTRY[pvName];
  var unit = (reg && reg.motor) ? (reg.motor.unit || '') : '';
  var distance = (typeof current === 'number' && typeof target === 'number')
    ? Math.abs(target - current).toFixed(4) : '?';
  var speed = (reg && reg.motor && reg.motor.speed) ? reg.motor.speed : '?';

  var overlay = document.createElement('div');
  overlay.id = 'safetyConfirmOverlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:10001;display:flex;align-items:center;justify-content:center';

  var dialog = document.createElement('div');
  dialog.style.cssText = 'background:var(--s1);border:2px solid var(--am);border-radius:8px;padding:16px;max-width:380px;width:90%;color:var(--t1);font-family:var(--mn);box-shadow:0 8px 32px rgba(0,0,0,0.6)';

  dialog.innerHTML =
    '<h3 style="margin:0 0 8px;font-size:12px;color:var(--am)">Hardware Motor Move Confirmation</h3>' +
    '<div style="border:1px solid var(--b1);border-radius:4px;padding:8px;background:var(--s2);margin-bottom:12px">' +
    '<div style="font-size:10px;font-weight:700;color:var(--gn)">' + shortPV + ' <span style="font-size:8px;color:var(--t3)">' + unit + '</span></div>' +
    '<div style="display:flex;justify-content:space-between;margin-top:6px;font-size:9px">' +
    '<span style="color:var(--t3)">Current: <span style="color:var(--t1)">' + (typeof current === 'number' ? current.toFixed(4) : '?') + '</span></span>' +
    '<span style="color:var(--am)">Target: <span style="color:var(--t1);font-weight:700">' + (typeof target === 'number' ? target.toFixed(4) : '?') + '</span></span>' +
    '</div>' +
    '<div style="font-size:8px;color:var(--t3);margin-top:4px">Distance: ' + distance + ' ' + unit + ' | Speed: ' + speed + ' ' + unit + '/s</div>' +
    '</div>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end">' +
    '<button class="sb sec act" onclick="document.getElementById(\'safetyConfirmOverlay\').remove()">Cancel</button>' +
    '<button class="sb act" style="background:var(--am);color:#000;font-weight:700" ' +
    'onclick="epicsPut(\'' + pvName.replace(/'/g, "\\'") + '\',' + target + ',{confirmed:true});document.getElementById(\'safetyConfirmOverlay\').remove()">Move</button>' +
    '</div>';

  overlay.appendChild(dialog);
  document.body.appendChild(overlay);
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof EPICS_STATE!=="undefined")globalThis.EPICS_STATE=EPICS_STATE;
if(typeof PV_ARCHIVE!=="undefined")globalThis.PV_ARCHIVE=PV_ARCHIVE;
if(typeof PV_MONITOR_GROUPS!=="undefined")globalThis.PV_MONITOR_GROUPS=PV_MONITOR_GROUPS;
if(typeof PV_REGISTRY!=="undefined")globalThis.PV_REGISTRY=PV_REGISTRY;
if(typeof SimIOC!=="undefined")globalThis.SimIOC=SimIOC;
if(typeof buildPVRegistry!=="undefined")globalThis.buildPVRegistry=buildPVRegistry;
if(typeof connectEPICS!=="undefined")globalThis.connectEPICS=connectEPICS;
if(typeof connectScan!=="undefined")globalThis.connectScan=connectScan;
if(typeof disconnectEPICS!=="undefined")globalThis.disconnectEPICS=disconnectEPICS;
if(typeof disconnectScan!=="undefined")globalThis.disconnectScan=disconnectScan;
if(typeof epicsGet!=="undefined")globalThis.epicsGet=epicsGet;
if(typeof epicsPut!=="undefined")globalThis.epicsPut=epicsPut;
if(typeof handlePVUpdate!=="undefined")globalThis.handlePVUpdate=handlePVUpdate;
if(typeof initEPICS!=="undefined")globalThis.initEPICS=initEPICS;
if(typeof measureLatency!=="undefined")globalThis.measureLatency=measureLatency;
if(typeof pvArchiveExport!=="undefined")globalThis.pvArchiveExport=pvArchiveExport;
if(typeof pvArchiveStart!=="undefined")globalThis.pvArchiveStart=pvArchiveStart;
if(typeof pvArchiveStop!=="undefined")globalThis.pvArchiveStop=pvArchiveStop;
if(typeof pvPutFromUI!=="undefined")globalThis.pvPutFromUI=pvPutFromUI;
if(typeof pvSubscribe!=="undefined")globalThis.pvSubscribe=pvSubscribe;
if(typeof pvUnsubscribe!=="undefined")globalThis.pvUnsubscribe=pvUnsubscribe;
if(typeof renderPVMonitor!=="undefined")globalThis.renderPVMonitor=renderPVMonitor;
if(typeof scheduleReconnect!=="undefined")globalThis.scheduleReconnect=scheduleReconnect;
if(typeof setEpicsMode!=="undefined")globalThis.setEpicsMode=setEpicsMode;
if(typeof updateEpicsStatsBar!=="undefined")globalThis.updateEpicsStatsBar=updateEpicsStatsBar;
if(typeof updateEpicsUI!=="undefined")globalThis.updateEpicsUI=updateEpicsUI;
if(typeof updatePVMonitorRow!=="undefined")globalThis.updatePVMonitorRow=updatePVMonitorRow;
if(typeof _discoveredPVs!=="undefined")globalThis._discoveredPVs=_discoveredPVs;
if(typeof _findMotorByPV!=="undefined")globalThis._findMotorByPV=_findMotorByPV;
if(typeof _handlePVDiscovered!=="undefined")globalThis._handlePVDiscovered=_handlePVDiscovered;
if(typeof _pvDiscoverClose!=="undefined")globalThis._pvDiscoverClose=_pvDiscoverClose;
if(typeof _pvDiscoverIgnore!=="undefined")globalThis._pvDiscoverIgnore=_pvDiscoverIgnore;
if(typeof _pvDiscoverPlace!=="undefined")globalThis._pvDiscoverPlace=_pvDiscoverPlace;
if(typeof _pvLatencyLog!=="undefined")globalThis._pvLatencyLog=_pvLatencyLog;
if(typeof _pvLimitStatus!=="undefined")globalThis._pvLimitStatus=_pvLimitStatus;
if(typeof _showMoveConfirmDialog!=="undefined")globalThis._showMoveConfirmDialog=_showMoveConfirmDialog;
if(typeof _showPVDetailPopup!=="undefined")globalThis._showPVDetailPopup=_showPVDetailPopup;
if(typeof _svHost!=="undefined")globalThis._svHost=_svHost;
if(typeof _svPort!=="undefined")globalThis._svPort=_svPort;
if(typeof _updateMotorLimitDisplay!=="undefined")globalThis._updateMotorLimitDisplay=_updateMotorLimitDisplay;
if(typeof handleScanEvent!=="undefined")globalThis.handleScanEvent=handleScanEvent;
if(typeof startPVLatencyLog!=="undefined")globalThis.startPVLatencyLog=startPVLatencyLog;
if(typeof stopPVLatencyLog!=="undefined")globalThis.stopPVLatencyLog=stopPVLatencyLog;
