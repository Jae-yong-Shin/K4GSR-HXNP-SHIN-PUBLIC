'use strict';
// ===== ui/03_panels.js -- Sidebar Controls, Mode, Harmonic Panel, Utilities =====
// @module ui/03_panels
// @exports _maskAperJog, applyHarm, axCtrl, emergencyStop, homeMotor, logAllMotorPositions, maskAperUpdate, motorMoveRelUI, motorSetUI, openMaskFullAnalysis, openMaskModal, selectMask, selectedMask, setCrystal, setFocusMode, ...
// Extracted from 08_ui_core.js (DDD Phase 6)

// === Sidebar Updates ===
function updateUnd(v) {
  state.gap = parseFloat(v);
  var B0 = calcB0(state.gap), K = calcK(B0), E1 = calcE1(K), P = calcPtotal(B0);
  var _s = function(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
  _s('vGap', state.gap.toFixed(1));
  _s('vB0', B0.toFixed(4) + ' T');
  _s('vK', K.toFixed(3));
  _s('vE1', E1.toFixed(2) + ' keV');
  _s('vHarm', 'n=' + state.harmonic);
  _s('vPow', (P / 1000).toFixed(2) + ' kW');
  _s('vBrt', calcBrt(K).toExponential(1));
  // Sync dynamic tab readback
  _s('dyn_ivu_gapv', state.gap.toFixed(3));
  // Sync MOTORS registry
  if (typeof MOTORS !== 'undefined' && MOTORS.ivu && MOTORS.ivu.gap) {
    MOTORS.ivu.gap.value = state.gap; MOTORS.ivu.gap.target = state.gap;
  }
  renderLayout();
}

function setCrystal(v) {
  state.crystal = v;
  var e1 = document.getElementById('crystalSel'); if (e1) e1.value = v;
  var e2 = document.getElementById('vDspacing'); if (e2) e2.textContent = D_SI[v].toFixed(4) + ' A Si(' + v + ')';
  updateEnergy(state.energy);
  updateHarmPanel();
  log('info', 'Crystal -> Si(' + v + ') d=' + D_SI[v].toFixed(4) + 'A');
}

function updateM1(v) {
  state.m1pitch = parseFloat(v);
  var _s = function(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
  _s('vM1p', state.m1pitch.toFixed(2));
  _s('vM1defl', (state.m1pitch * 2).toFixed(1) + ' mrad');
  var _st1 = (typeof getStripeMaterial === 'function') ? getStripeMaterial('m1') : null;
  var _m1mat = (_st1 && _st1.mat) ? _st1.mat : PT;
  _s('vM1cut', mirrorCut(state.m1pitch, _m1mat).toFixed(1) + ' keV');
  if (MOTORS.m1 && MOTORS.m1.pitch) { MOTORS.m1.pitch.value = state.m1pitch; MOTORS.m1.pitch.target = state.m1pitch; }
  renderLayout();
}

function updateM2(v) {
  state.m2pitch = parseFloat(v);
  var e = document.getElementById('vM2p'); if (e) e.textContent = state.m2pitch.toFixed(2);
  if (MOTORS.m2 && MOTORS.m2.pitch) { MOTORS.m2.pitch.value = state.m2pitch; MOTORS.m2.pitch.target = state.m2pitch; }
  renderLayout();
}

function updateKBV(v) {
  state.kbvpitch = parseFloat(v);
  if (MOTORS.kbv && MOTORS.kbv.pitch) { MOTORS.kbv.pitch.value = state.kbvpitch; MOTORS.kbv.pitch.target = state.kbvpitch; }
  if (typeof _mcSampleCache !== 'undefined') _mcSampleCache = null;
  try { updateOptics(); } catch(e) {}
}

function updateKBH(v) {
  state.kbhpitch = parseFloat(v);
  if (MOTORS.kbh && MOTORS.kbh.pitch) { MOTORS.kbh.pitch.value = state.kbhpitch; MOTORS.kbh.pitch.target = state.kbhpitch; }
  if (typeof _mcSampleCache !== 'undefined') _mcSampleCache = null;
  try { updateOptics(); } catch(e) {}
}

function setFocusMode(m) {
  state.focusMode = m;
  ['kb', 'zp', 'crl'].forEach(function(id) {
    var b = document.getElementById('fBtn-' + id);
    if (b) b.classList.toggle('active', id === m);
  });
  var pc = document.getElementById('focPosCtrl'); if (!pc) return;
  if (m === 'kb') {
    pc.innerHTML = '<div class="ctrl-label" style="margin-top:4px">KB-V pos(m)</div>' +
      '<input type="number" value="' + pos('kbv') + '" step="0.1" style="width:100%" ' +
      'onchange="state.positions.kbv=parseFloat(this.value);renderLayout();updateOptics()"/>' +
      '<div class="ctrl-label">KB-H pos(m)</div>' +
      '<input type="number" value="' + pos('kbh') + '" step="0.1" style="width:100%" ' +
      'onchange="state.positions.kbh=parseFloat(this.value);renderLayout();updateOptics()"/>';
  } else {
    var lbl = m === 'zp' ? 'Zone Plate' : 'CRL';
    pc.innerHTML = '<div class="ctrl-label" style="margin-top:4px">' + lbl + ' pos(m)</div>' +
      '<input type="number" value="' + pos('kbv') + '" step="0.1" style="width:100%" ' +
      'onchange="state.positions.kbv=parseFloat(this.value);renderLayout();updateOptics()"/>';
  }
  renderLayout(); updateOptics(); log('info', 'Focus->' + m.toUpperCase());
}

// === Harmonic Panel ===
function updateHarmPanel() {
  var p = document.getElementById('harmPanel');
  var hs = findHarmonics(state.targetEnergy);
  var B0 = calcB0(state.gap), K = calcK(B0), E1 = calcE1(K);
  var Ptot = calcPtotal(B0);
  var h = '<div style="margin-bottom:4px;color:var(--t2)">Target: <b style="color:var(--ac)">' +
    state.targetEnergy.toFixed(2) + 'keV</b> E1=' + E1.toFixed(2) + '</div>';
  h += '<div style="margin-bottom:4px;font-size:8px;color:var(--t3)">Current gap: P<sub>total</sub>=<b style="color:var(--am)">' +
    (Ptot / 1000).toFixed(2) + ' kW</b></div>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:2px;margin-bottom:6px">';
  hs.forEach(function(x) {
    h += '<span class="harm-badge ' + (x.n === state.harmonic ? 'active' : 'avail') +
      '" onclick="applyHarm(' + x.n + ',' + x.gap.toFixed(2) + ')" title="gap=' +
      x.gap.toFixed(1) + ' K=' + x.K.toFixed(2) + '">n=' + x.n + '</span>';
  });
  h += '</div><table style="width:100%;font-size:8px"><tr style="color:var(--t3)"><td>n</td><td>Gap</td><td>K</td><td>E1</td><td>Flux</td><td>P<sub>tot</sub></td></tr>';
  hs.forEach(function(x) {
    var s = x.n === state.harmonic ? 'color:var(--gn);font-weight:600' : '';
    var Px = (calcPtotal(x.B0) / 1000).toFixed(2);
    h += '<tr style="' + s + '"><td>' + x.n + '</td><td>' + x.gap.toFixed(1) +
      '</td><td>' + x.K.toFixed(2) + '</td><td>' + x.E1.toFixed(2) +
      '</td><td>' + x.flux.toExponential(1) + '</td><td>' + Px + 'kW</td></tr>';
  });
  h += '</table>';
  p.innerHTML = h;
  var harmInfo = document.getElementById('harmInfo');
  if (harmInfo) harmInfo.textContent = 'n=' + state.harmonic;
}

function applyHarm(n, gap) {
  state.harmonic = n;
  state.gap = gap;
  var slider = document.getElementById('gapSlider');
  if (slider) slider.value = gap;
  if (typeof MOTORS !== 'undefined' && MOTORS.ivu && MOTORS.ivu.harmonic) {
    MOTORS.ivu.harmonic.value = n; MOTORS.ivu.harmonic.target = n;
  }
  updateUnd(gap);
  updateHarmPanel();
  // Propagate flux change through optics to sample
  if (typeof updateOptics === 'function') updateOptics();
  log('info', 'Harmonic->n=' + n + ' gap=' + gap.toFixed(1) + 'mm');
}

function setTargetEnergy(v) {
  state.targetEnergy = parseFloat(v);
  state.energy = state.targetEnergy;
  var _s = function(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
  _s('vTargetE', state.targetEnergy.toFixed(3));
  _s('dyn_ivu_targetEnergyv', state.targetEnergy.toFixed(3));
  var el2 = document.getElementById('energySlider');
  if (el2) el2.value = state.targetEnergy;
  // Sync MOTORS registry
  if (typeof MOTORS !== 'undefined' && MOTORS.ivu && MOTORS.ivu.targetEnergy) {
    MOTORS.ivu.targetEnergy.value = state.targetEnergy; MOTORS.ivu.targetEnergy.target = state.targetEnergy;
  }
  var b = selectBest(state.targetEnergy);
  if (b) {
    state.harmonic = b.n;
    state.gap = b.gap;
    var gs = document.getElementById('gapSlider');
    if (gs) gs.value = b.gap;
    // Sync harmonic to MOTORS so guard saves correct value on mode switch
    if (typeof MOTORS !== 'undefined' && MOTORS.ivu && MOTORS.ivu.harmonic) {
      MOTORS.ivu.harmonic.value = b.n; MOTORS.ivu.harmonic.target = b.n;
    }
    updateUnd(b.gap);
  }
  updateEnergy(state.energy);
  updateHarmPanel();
}

// === Mode Switching ===
function setMode(m) {
  state.mode = m;
  document.querySelectorAll('.mode-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('.mode-btn').forEach(function(b) {
    if (b.textContent.toLowerCase() === m) b.classList.add('active');
  });
  var lb = { virtual: 'VIRTUAL MODE', real: 'REAL MODE', dual: 'DUAL COMPARE' };
  var modeEl = document.getElementById('modeStatus');
  if (modeEl) modeEl.textContent = lb[m];
  var cmpEl = document.getElementById('comparePanel');
  if (cmpEl) cmpEl.style.display = m === 'dual' ? 'flex' : 'none';
  // Show Bluesky live panel when queue is running
  var bsEl = document.getElementById('bsPanel');
  if (bsEl) bsEl.style.display = 'none';
  if (m === 'dual') {
    if (typeof startComparison === 'function') startComparison();
  } else {
    if (typeof stopComparison === 'function') stopComparison();
  }
  log('info', 'Mode->' + lb[m]);
  if (m === 'real') setEpicsMode('real');
  else if (m === 'virtual') { setEpicsMode('sim'); }
}

// === Technique UI ===
function updateTechUI() {
  var t = document.getElementById('technique');
  var tv = t ? t.value : '';
  ['xanes', 'xrd2d', 'xrf', 'xrf2d'].forEach(function(id) {
    var e = document.getElementById(id + 'Params');
    if (e) e.style.display = tv === id ? 'block' : 'none';
  });
}

// === Compare Mode ===
function updateCompare() {
  if (typeof COMPARISON === 'undefined' || !COMPARISON.enabled) return;
  // Update bottom panel compact view
  var body = document.getElementById('comparePanelBody');
  if (!body) return;
  var score = parseInt(COMPARISON.overallScore || 100);
  var sc = severityColor(score > 90 ? 0 : score > 70 ? 1 : score > 50 ? 2 : 3);
  var el = document.getElementById('cmpScoreBar');
  if (el) { el.textContent = score + '%'; el.style.color = sc; }
  // Compact summary
  var h = '';
  var devSummary = {};
  Object.values(COMPARISON.results).forEach(function(r) {
    if (!devSummary[r.deviceId]) devSummary[r.deviceId] = { worst: 0, count: 0, bad: 0 };
    devSummary[r.deviceId].count++;
    if (r.severity > devSummary[r.deviceId].worst) devSummary[r.deviceId].worst = r.severity;
    if (r.severity >= 2) devSummary[r.deviceId].bad++;
  });
  Object.keys(devSummary).forEach(function(devId) {
    var s = devSummary[devId];
    var dev = DEVICE_REGISTRY[devId];
    var c = severityColor(s.worst);
    h += '<div style="display:flex;font-size:8px;font-family:var(--mn);gap:4px;padding:1px 0">' +
      '<span style="color:' + c + '">' + severityLabel(['good', 'warning', 'alarm', 'critical'][s.worst]) + '</span>' +
      '<span style="color:var(--t2);flex:1">' + (dev ? dev.label : devId) + '</span>' +
      '<span style="color:' + c + '">' + (s.bad > 0 ? s.bad + '/' + s.count + ' WARN' : s.count + ' OK') + '</span></div>';
  });
  if (COMPARISON.suggestions.length > 0) {
    h += '<div style="margin-top:4px;border-top:1px solid var(--b0);padding-top:2px">';
    COMPARISON.suggestions.slice(0, 3).forEach(function(s) {
      h += '<div style="font-size:8px;color:' + severityColor(s.severity) + ';padding:1px 0">' + s.message + '</div>';
    });
    h += '</div>';
  }
  body.innerHTML = h;
}

// === Utility ===
// log() and clearLog() moved to shared/01_constants.js (must load before all modules)

function emergencyStop() {
  stopScan();
  if (typeof MOTORS !== 'undefined') {
    Object.keys(MOTORS).forEach(function(grp) {
      var dev = MOTORS[grp];
      Object.keys(dev).forEach(function(ax) {
        if (dev[ax] && dev[ax].moving && typeof dev[ax].stop === 'function') dev[ax].stop();
      });
    });
  }
  state.aligning = false;
  state._alignAborted = true;
  /* Send estop to server (real hardware) */
  try {
    var ws = typeof EPICS_STATE !== 'undefined' ? EPICS_STATE.ws : null;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'estop' }));
    }
  } catch (e) { /* ignore */ }
  log('err', 'E-STOP: all motors halted');
  var el = document.getElementById('scanStatus');
  if (el) { el.textContent = 'E-STOP'; el.style.color = 'var(--rd)'; }
}

/* Home a motor via EPICS .HOMF field (KOHZU stages) */
function homeMotor(groupId, motorId) {
  /* Build PV name from motor group/id mapping */
  var pvMap = {
    'sample_cx': 'BL10:SAM:CX', 'sample_cy': 'BL10:SAM:CY', 'sample_cz': 'BL10:SAM:CZ',
    'sample_theta': 'BL10:SAM:Theta', 'sample_phi': 'BL10:SAM:Phi',
    'sample_fx': 'BL10:SAM:FX', 'sample_fy': 'BL10:SAM:FY', 'sample_fz': 'BL10:SAM:FZ',
    'sample_sx': 'BL10:SAM:SX', 'sample_sy': 'BL10:SAM:SY'
  };
  var pvName = pvMap[motorId];
  if (!pvName) {
    log('warn', 'homeMotor: unknown motor ' + motorId);
    return;
  }
  var ws = typeof EPICS_STATE !== 'undefined' ? EPICS_STATE.ws : null;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    log('warn', 'homeMotor: PV WebSocket not connected');
    return;
  }
  ws.send(JSON.stringify({ action: 'home', pv: pvName, direction: 'forward' }));
  log('info', 'Homing: ' + pvName);
}

// === Mask Full Analysis (high-res 101x101) ===
function openMaskFullAnalysis(maskId) {
  closeModal();
  var res = renderMaskResult(maskId);
  var html = res.html;
  var result = res.result;
  var title = (maskId === 'fmask' ? 'Fixed' : 'Movable') + ' Mask -- Full Analysis (101x101)';
  openModal(title, html);
  setTimeout(function() { drawMaskSpecChart(result); drawMaskProfile(result); }, 100);
}

// === Mask aperture update from modal slider ===
function maskAperUpdate(msId, axis, val) {
  val = parseFloat(val);
  if (axis === 'h') maskState[msId].aperH = val;
  else maskState[msId].aperV = val;
  // Sync to motor
  var gid = msId;
  var mid = msId + '_' + (axis === 'h' ? 'hgap' : 'vgap');
  if (MOTORS[gid]) {
    var grp = MOTORS[gid];
    var key = axis === 'h' ? 'hgap' : 'vgap';
    if (grp[key]) { grp[key].value = val; grp[key].target = val; }
  }
  if (typeof syncMotorToState === 'function') syncMotorToState(gid, mid, val);
  // Update display value spans in side panel
  var panel = document.getElementById('maskSidePanel');
  if (panel && msId === selectedMask) {
    var spans = panel.querySelectorAll('.ctrl-val');
    // First ctrl-val = Aperture H, second = Aperture V
    if (axis === 'h' && spans.length > 0) spans[0].textContent = val.toFixed(1);
    if (axis === 'v' && spans.length > 1) spans[1].textContent = val.toFixed(1);
  }
  if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
  if (typeof renderLayout === 'function') try { renderLayout(); } catch(e) {}
}

// === Mask aperture jog (motor-panel style) ===
function _maskAperJog(msId, axis, multiplier) {
  var idPfx = 'maskAper_' + msId + '_' + axis;
  var stepEl = document.getElementById(idPfx + 'st');
  var step = stepEl ? parseFloat(stepEl.value) : 0.1;
  if (isNaN(step) || step <= 0) step = 0.1;
  var cur = axis === 'h' ? maskState[msId].aperH : maskState[msId].aperV;
  var nv = Math.max(0.5, Math.min(10, cur + step * multiplier));
  maskAperUpdate(msId, axis, nv);
  var sl = document.getElementById(idPfx + 's');
  if (sl) sl.value = nv;
  var rv = document.getElementById(idPfx + 'v');
  if (rv) rv.textContent = nv.toFixed(3);
}

// === Mask Side Panel ===
var selectedMask = 'fmask';

function selectMask(id) {
  selectedMask = id;
  document.querySelectorAll('[id^="maskBtn-"]').forEach(function(b) { b.classList.remove('active'); });
  var btn = document.getElementById('maskBtn-' + id);
  if (btn) btn.classList.add('active');
  updateMaskSidePanel();
}

function updateMaskSidePanel() {
  var panel = document.getElementById('maskSidePanel'); if (!panel) return;
  var ms = maskState[selectedMask];
  var r = calcMaskHeatLoad(selectedMask);
  var _msk = selectedMask;
  var _hId = 'maskAper_' + _msk + '_h';
  var _vId = 'maskAper_' + _msk + '_v';
  var _hStep = 0.1;
  var _vStep = 0.1;
  var h = '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">APERTURE</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div class="ax-ctrl">' +
    '<div class="ax-r1">' +
    '<span class="ax-name">H-Gap <span class="ax-unit">(mm)</span></span>' +
    '<span class="ctrl-val ax-pos" id="' + _hId + 'v">' + ms.aperH.toFixed(3) + '</span></div>' +
    '<input type="range" min="0.5" max="10" step="' + _hStep + '" value="' + ms.aperH +
    '" class="ax-slider" id="' + _hId + 's" oninput="maskAperUpdate(\'' + _msk + '\',\'h\',this.value);' +
    'var _rv=document.getElementById(\'' + _hId + 'v\');if(_rv)_rv.textContent=parseFloat(this.value).toFixed(3)"/>' +
    '<div class="ax-r2">' +
    '<button class="jog-btn jog-neg" onclick="_maskAperJog(\'' + _msk + '\',\'h\',-10)">&#x25C4;&#x25C4;</button>' +
    '<button class="jog-btn jog-neg" onclick="_maskAperJog(\'' + _msk + '\',\'h\',-1)">&#x25C4;</button>' +
    '<input type="number" value="' + _hStep + '" step="0.01" min="0" class="ax-step" id="' + _hId + 'st" title="Jog step size"/>' +
    '<button class="jog-btn jog-pos" onclick="_maskAperJog(\'' + _msk + '\',\'h\',1)">&#x25BA;</button>' +
    '<button class="jog-btn jog-pos" onclick="_maskAperJog(\'' + _msk + '\',\'h\',10)">&#x25BA;&#x25BA;</button>' +
    '</div></div>' +
    '<div class="ax-ctrl">' +
    '<div class="ax-r1">' +
    '<span class="ax-name">V-Gap <span class="ax-unit">(mm)</span></span>' +
    '<span class="ctrl-val ax-pos" id="' + _vId + 'v">' + ms.aperV.toFixed(3) + '</span></div>' +
    '<input type="range" min="0.5" max="10" step="' + _vStep + '" value="' + ms.aperV +
    '" class="ax-slider" id="' + _vId + 's" oninput="maskAperUpdate(\'' + _msk + '\',\'v\',this.value);' +
    'var _rv=document.getElementById(\'' + _vId + 'v\');if(_rv)_rv.textContent=parseFloat(this.value).toFixed(3)"/>' +
    '<div class="ax-r2">' +
    '<button class="jog-btn jog-neg" onclick="_maskAperJog(\'' + _msk + '\',\'v\',-10)">&#x25C4;&#x25C4;</button>' +
    '<button class="jog-btn jog-neg" onclick="_maskAperJog(\'' + _msk + '\',\'v\',-1)">&#x25C4;</button>' +
    '<input type="number" value="' + _vStep + '" step="0.01" min="0" class="ax-step" id="' + _vId + 'st" title="Jog step size"/>' +
    '<button class="jog-btn jog-pos" onclick="_maskAperJog(\'' + _msk + '\',\'v\',1)">&#x25BA;</button>' +
    '<button class="jog-btn jog-pos" onclick="_maskAperJog(\'' + _msk + '\',\'v\',10)">&#x25BA;&#x25BA;</button>' +
    '</div></div></div></div>';
  // Mask motor controls (X, Y, H-Gap, V-Gap) using unified axCtrl layout
  var dev = null;
  if (typeof DEVICE_REGISTRY !== 'undefined') dev = DEVICE_REGISTRY[selectedMask];
  var grp = MOTORS[selectedMask];
  if (dev && dev.axes && grp) {
    var axKeys = Object.keys(dev.axes).filter(function(k) {
      return k !== 'hgap' && k !== 'vgap'; // aperture already rendered above
    });
    if (axKeys.length > 0) {
      h += '<div style="margin-bottom:6px">' +
        '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">POSITION MOTORS</h4>' +
        '<div class="ctrl-group" style="margin:0">';
      axKeys.forEach(function(k) {
        var ax = dev.axes[k];
        var motor = grp[k] || null;
        if (typeof window.axCtrl === 'function') {
          h += window.axCtrl(selectedMask, k, ax, motor);
        }
      });
      h += '</div></div>';
    }
  }
  h += '<div style="margin-bottom:6px">' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div class="ctrl-label">Total Power<span class="ctrl-val">' + r.P_total.toFixed(0) + ' W</span></div>' +
    '<div class="ctrl-label">Aperture Power<span class="ctrl-val">' + r.P_aper.toFixed(1) + ' W</span></div>' +
    '<div class="ctrl-label">After Atten.<span class="ctrl-val" style="color:' +
    (r.finalP > 500 ? 'var(--rd)' : 'var(--gn)') + '">' + r.finalP.toFixed(1) + ' W</span></div>' +
    '<div class="ctrl-label">Absorbed<span class="ctrl-val" style="color:var(--am)">' + r.totalAbs.toFixed(1) + ' W</span></div>' +
    '<div class="ctrl-label">Peak W/mm2<span class="ctrl-val">' + r.profile.peakDens.toFixed(3) + '</span></div>' +
    '</div></div>';
  // Attenuator quick add
  var ports = ms.attPorts || [];
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Attenuators (' + ports.length + ')</h4>' +
    '<div class="ctrl-group" style="margin:0">';
  ports.forEach(function(p, i) {
    h += '<div style="display:flex;gap:2px;margin-top:2px;align-items:center;font-size:8px">' +
      '<select style="flex:1;font-size:8px;background:var(--s2);border:1px solid var(--b1);color:var(--t0);padding:2px;border-radius:2px" ' +
      'onchange="maskState.' + selectedMask + '.attPorts[' + i + '].material=this.value;updateMaskSidePanel()">';
    MASK_MATERIALS.forEach(function(mat) {
      h += '<option value="' + mat + '"' + (p.material === mat ? ' selected' : '') + '>' + mat + '</option>';
    });
    h += '</select>' +
      '<input type="number" value="' + p.thickness + '" step="0.5" min="0" style="width:35px;font-size:8px" ' +
      'onchange="maskState.' + selectedMask + '.attPorts[' + i + '].thickness=parseFloat(this.value)||0;updateMaskSidePanel()"/>' +
      '<span style="color:var(--t3)">mm</span>' +
      '</div>';
  });
  h += '<button onclick="maskState.' + selectedMask + '.attPorts.push({material:\'Carbon\',thickness:1});updateMaskSidePanel()" ' +
    'style="font-size:8px;margin-top:3px;padding:2px 6px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:2px;cursor:pointer">+ Port</button></div></div>';
  panel.innerHTML = h;
}

function openMaskModal() {
  var res = renderMaskResult(selectedMask);
  var html = res.html;
  var result = res.result;
  var title = (selectedMask === 'fmask' ? 'Fixed' : 'Movable') + ' Mask Analysis';
  openModal(title, html);
  setTimeout(function() { drawMaskSpecChart(result); drawMaskProfile(result); }, 80);
}

// === Tab Switch — INLINE MERGED (base from 08_ui_core.js + attenuator from 11_beam_monitor.js) ===
function switchTab(id) {
  document.querySelectorAll('.tabpane').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  var pane = document.getElementById('tab-' + id);
  if (pane) pane.classList.add('active');
  // Match tab by current i18n label OR English fallback (for pre-refresh state)
  var EN_MAP = {undulator:'IVU',dcm:'DCM',optics:'Optics',motors:'Motors',mask:'Mask',
    measure:'Meas',align:'Align',compare:'V/R',epics:'EPICS',bluesky:'BS',
    guide:'Guide',chat:'Chat',expt:'Expt',scanner:'Scan'};
  var label = (typeof _t === 'function') ? _t('tab_' + id) : (EN_MAP[id] || id);
  var enLabel = EN_MAP[id] || id;
  document.querySelectorAll('.tab').forEach(function(t) {
    var txt = t.textContent.trim();
    if (txt === label || txt === enLabel) t.classList.add('active');
  });
  if (id === 'epics' && typeof renderEpicsTab === 'function') renderEpicsTab();
  if (id === 'compare' && typeof renderComparisonPanel === 'function') renderComparisonPanel();
  if (id === 'bluesky' && typeof renderBlueskyTab === 'function') renderBlueskyTab();
  if (id === 'guide' && typeof renderGuideTab === 'function') renderGuideTab();
  if (id === 'chat' && typeof renderChatTab === 'function') renderChatTab();
  if (id === 'expt' && typeof renderExptTab === 'function') renderExptTab();
  // --- attenuator tab auto-render (from ui/11_beam_monitor.js) ---
  if (id === 'atten') {
    if (typeof renderAttenUI === 'function') renderAttenUI();
    if (typeof _renderAttenMotors === 'function') try { _renderAttenMotors(); } catch(e) {}
  }
}

// === Motor UI base functions (from 08_ui_core.js) ===
function motorSetUI(gid, mid, val) {
  var grp = MOTORS[gid]; if (!grp) return;
  var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x) { return x && x.id; });
  var m = null;
  for (var i = 0; i < motors.length; i++) { if (motors[i].id === mid) { m = motors[i]; break; } }
  if (!m) return;
  val = Math.max(m.min, Math.min(m.max, val));
  m.value = val; m.target = val;
  var el = document.getElementById('mval_' + mid);
  if (el) el.textContent = val.toFixed(4) + ' ' + m.unit;
  log('info', m.name + ' \u2192 ' + val.toFixed(4) + ' ' + m.unit);
  if (typeof syncMotorToState === 'function') syncMotorToState(gid, mid, val);
  if (m.pv && typeof epicsPut === 'function' && typeof EPICS_STATE !== 'undefined' && EPICS_STATE.mode !== 'disconnected') epicsPut(m.pv, val);
}
function motorMoveRelUI(gid, mid, delta) {
  var grp = MOTORS[gid]; if (!grp) return;
  var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x) { return x && x.id; });
  var m = null;
  for (var i = 0; i < motors.length; i++) { if (motors[i].id === mid) { m = motors[i]; break; } }
  if (!m) return;
  motorSetUI(gid, mid, m.value + delta);
}
function logAllMotorPositions() {
  log('info', '=== Motor Positions ===');
  var gids = Object.keys(MOTORS);
  for (var g = 0; g < gids.length; g++) {
    var gid = gids[g], grp = MOTORS[gid];
    var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x) { return x && x.id; });
    for (var j = 0; j < motors.length; j++) {
      log('info', '  ' + gid + '.' + motors[j].name + ': ' + motors[j].value.toFixed(4) + ' ' + motors[j].unit);
    }
  }
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof applyHarm!=="undefined")globalThis.applyHarm=applyHarm;
if(typeof emergencyStop!=="undefined")globalThis.emergencyStop=emergencyStop;
if(typeof homeMotor!=="undefined")globalThis.homeMotor=homeMotor;
if(typeof logAllMotorPositions!=="undefined")globalThis.logAllMotorPositions=logAllMotorPositions;
if(typeof maskAperUpdate!=="undefined")globalThis.maskAperUpdate=maskAperUpdate;
if(typeof motorMoveRelUI!=="undefined")globalThis.motorMoveRelUI=motorMoveRelUI;
if(typeof motorSetUI!=="undefined")globalThis.motorSetUI=motorSetUI;
if(typeof openMaskFullAnalysis!=="undefined")globalThis.openMaskFullAnalysis=openMaskFullAnalysis;
if(typeof openMaskModal!=="undefined")globalThis.openMaskModal=openMaskModal;
if(typeof selectMask!=="undefined")globalThis.selectMask=selectMask;
if(typeof selectedMask!=="undefined")globalThis.selectedMask=selectedMask;
if(typeof setCrystal!=="undefined")globalThis.setCrystal=setCrystal;
if(typeof setFocusMode!=="undefined")globalThis.setFocusMode=setFocusMode;
if(typeof setMode!=="undefined")globalThis.setMode=setMode;
if(typeof setTargetEnergy!=="undefined")globalThis.setTargetEnergy=setTargetEnergy;
if(typeof switchTab!=="undefined")globalThis.switchTab=switchTab;
if(typeof updateCompare!=="undefined")globalThis.updateCompare=updateCompare;
if(typeof updateHarmPanel!=="undefined")globalThis.updateHarmPanel=updateHarmPanel;
if(typeof updateKBH!=="undefined")globalThis.updateKBH=updateKBH;
if(typeof updateKBV!=="undefined")globalThis.updateKBV=updateKBV;
if(typeof updateM1!=="undefined")globalThis.updateM1=updateM1;
if(typeof updateM2!=="undefined")globalThis.updateM2=updateM2;
if(typeof updateMaskSidePanel!=="undefined")globalThis.updateMaskSidePanel=updateMaskSidePanel;
if(typeof updateTechUI!=="undefined")globalThis.updateTechUI=updateTechUI;
if(typeof updateUnd!=="undefined")globalThis.updateUnd=updateUnd;
if(typeof _maskAperJog!=="undefined")globalThis._maskAperJog=_maskAperJog;
if(typeof axCtrl!=="undefined")globalThis.axCtrl=axCtrl;
