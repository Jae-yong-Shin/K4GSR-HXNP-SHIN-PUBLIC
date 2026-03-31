'use strict';
// ===== ui/04_dynamic_tabs.js — Dynamic Optics/DCM/IVU Tab Renderer =====
// @module ui/04_dynamic_tabs
// @exports _eJog, axCtrl, dynJog, dynMoveRel, dynSet, renderDynTabs
// Extracted from 14_v435_final.js (DDD Phase 5d)
// Provides: renderDynTabs, dynSet, dynJog, dynMoveRel, axCtrl (global)

(function(){
  var TAB_LAYOUT = {
    undulator: {
      devices: ['ivu'],
      derived: function() {
        var eVals = typeof state !== 'undefined' ? state : {};
        var B0val = typeof calcB0 === 'function' ? calcB0(eVals.gap || 7) : 0;
        var Kval = typeof calcK === 'function' ? calcK(B0val) : 0;
        var E1val = typeof calcE1 === 'function' ? calcE1(Kval) : 0;
        var Pval = typeof calcPtotal === 'function' ? calcPtotal(B0val) : 0;
        var Brtval = typeof calcBrt === 'function' ? calcBrt(Kval) : 0;
        var h = '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">RING / e-BEAM</h4>' +
          '<div class="ctrl-group" style="margin:0">' +
          '<div class="row"><div><div class="ctrl-label">E (GeV)</div>' +
          '<input type="number" value="4.0" step="0.1" min="1" max="8" style="width:100%" onchange="updateEbeamParam(\'E_RING\',this.value)"/></div>' +
          '<div><div class="ctrl-label">I (mA)</div>' +
          '<input type="number" value="400" step="10" min="10" max="500" style="width:100%" onchange="updateEbeamParam(\'I_RING\',this.value)"/></div></div>' +
          '<div class="row" style="margin-top:3px"><div><div class="ctrl-label">&epsilon;<sub>x</sub> (pm)</div>' +
          '<input type="number" value="62" step="1" min="1" max="500" style="width:100%" onchange="updateEbeamParam(\'EMIT_X\',this.value)"/></div>' +
          '<div><div class="ctrl-label">&epsilon;<sub>y</sub> (pm)</div>' +
          '<input type="number" value="6.2" step="0.1" min="0.1" max="100" style="width:100%" onchange="updateEbeamParam(\'EMIT_Y\',this.value)"/></div></div>' +
          '<div class="row" style="margin-top:3px"><div><div class="ctrl-label">&beta;<sub>x</sub> (m)</div>' +
          '<input type="number" value="6.334" step="0.1" min="0.5" max="30" style="width:100%" onchange="updateEbeamParam(\'BETA_X\',this.value)"/></div>' +
          '<div><div class="ctrl-label">&beta;<sub>y</sub> (m)</div>' +
          '<input type="number" value="2.841" step="0.1" min="0.5" max="30" style="width:100%" onchange="updateEbeamParam(\'BETA_Y\',this.value)"/></div></div>' +
          '<div class="row" style="margin-top:3px"><div><div class="ctrl-label">&sigma;<sub>E</sub> (10<sup>-4</sup>)</div>' +
          '<input type="number" value="12.0" step="0.1" min="0.01" max="50" style="width:100%" onchange="updateEbeamParam(\'E_SPREAD\',this.value)"/></div>' +
          '<div><div class="ctrl-label">Period/N</div><span class="ctrl-val" style="font-size:9px">24mm / 123</span></div></div>' +
          '<div class="ctrl-label" style="margin-top:3px">Derived<span class="ctrl-val" id="vEbeamInfo" style="font-size:8px">&sigma;<sub>x</sub>=20.0\u03BCm, &sigma;<sub>y</sub>=4.17\u03BCm, &gamma;=7827</span></div></div></div>';
        h += '<div class="ctrl-group" style="margin:0 0 6px 0">' +
          '<div class="ctrl-label">B\u2080<span class="ctrl-val" id="vB0">' + B0val.toFixed(4) + ' T</span></div>' +
          '<div class="ctrl-label">K<span class="ctrl-val" id="vK">' + Kval.toFixed(3) + '</span></div>' +
          '<div class="ctrl-label">E\u2081<span class="ctrl-val" id="vE1">' + E1val.toFixed(2) + ' keV</span></div>' +
          '<div class="ctrl-label">Harmonic<span class="ctrl-val" id="vHarm">n=' + (eVals.harmonic || 1) + '</span></div>' +
          '<div class="ctrl-label">Total Power<span class="ctrl-val" id="vPow">' + (Pval / 1000).toFixed(2) + ' kW</span></div>' +
          '<div class="ctrl-label">Brightness<span class="ctrl-val" id="vBrt">' + Brtval.toExponential(1) + '</span></div></div>';
        var srcBW = (typeof state.sourceBW_eV === 'number') ? state.sourceBW_eV : 1.0;
        h += '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">SOURCE BANDWIDTH</h4>' +
          '<div class="ctrl-group" style="margin:0">' +
          '<div class="ctrl-label">dE (eV)' +
          '<input type="number" value="' + srcBW + '" step="0.1" min="0" max="50" ' +
          'style="width:55px;float:right;text-align:right" id="srcBWInput" ' +
          'onchange="state.sourceBW_eV=parseFloat(this.value);_mcSampleCache=null;' +
          'try{updateOptics();}catch(e){}"/></div>' +
          '<div class="ctrl-label" style="font-size:8px;color:var(--t3)">MC ray energy spread around DCM center</div></div></div>';
        return h;
      }
    },
    dcm: {
      devices: ['dcm'],
      header: function() {
        return '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">CRYSTAL</h4>' +
          '<div class="ctrl-group" style="margin:0">' +
          '<select id="crystalSel" onchange="setCrystal(this.value)" style="width:100%">' +
          '<option value="111">Si(111)</option><option value="311">Si(311)</option></select></div></div>' +
          '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">MONO ENERGY</h4>' +
          '<div class="ctrl-group" style="margin:0"><div class="ax-ctrl">' +
          '<div class="ax-r1"><span class="ax-name">Energy <span class="ax-unit">(keV)</span></span>' +
          '<span class="ctrl-val ax-pos" id="vEnergy">10.000</span></div>' +
          '<input type="hidden" id="energySlider" value="10"/>' +
          '<div class="ax-r2">' +
          '<button class="jog-btn jog-neg" onclick="_eJog(-10)">&#x25C4;&#x25C4;</button>' +
          '<button class="jog-btn jog-neg" onclick="_eJog(-1)">&#x25C4;</button>' +
          '<input type="number" value="0.01" step="0.001" min="0" class="ax-step" id="eJogStep"/>' +
          '<button class="jog-btn jog-pos" onclick="_eJog(1)">&#x25BA;</button>' +
          '<button class="jog-btn jog-pos" onclick="_eJog(10)">&#x25BA;&#x25BA;</button>' +
          '</div></div></div></div>';
      },
      derived: function() {
        return '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">' +
          'DCM: Horizontal Bragg diffraction (fixed-exit)</h4>' +
          '<div class="ctrl-group" style="margin:0">' +
          '<div class="ctrl-label">Theta_B<span class="ctrl-val" id="vBragg">--</span></div>' +
          '<div class="ctrl-label">d<span class="ctrl-val" id="vDspacing">3.1356 A Si(111)</span></div>' +
          '<div class="ctrl-label">Fixed Exit<span class="ctrl-val" id="vOffset">' + FIXED_EXIT.toFixed(1) + ' mm</span></div>' +
          '<div class="ctrl-label">Crystal Gap<span class="ctrl-val" id="vGapDCM">--</span></div>' +
          '<div class="ctrl-label">Darwin W.<span class="ctrl-val" id="vDarwin">--</span></div>' +
          '<div class="ctrl-label">dE/E<span class="ctrl-val" id="vRes">--</span></div>' +
          '<div class="ctrl-label">Throughput<span class="ctrl-val" id="vThru">--</span></div></div></div>';
      }
    },
    optics: {
      devices: ['wbslit','m1','m2','ssa','kbv','kbh','zp'],
      derived: function() {
        return '<div style="margin-bottom:6px">' +
          '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">FOCUSING OPTICS</h4>' +
          '<div class="ctrl-group" style="margin:0">' +
          '<div style="display:flex;gap:2px;margin-bottom:6px">' +
          '<button class="mode-btn active" id="fBtn-kb" onclick="setFocusMode(\'kb\')">KB</button>' +
          '<button class="mode-btn" id="fBtn-zp" onclick="setFocusMode(\'zp\')">ZP</button>' +
          '<button class="mode-btn" id="fBtn-crl" onclick="setFocusMode(\'crl\')">CRL</button></div>' +
          '<div class="ctrl-label">Focus HxV<span class="ctrl-val" id="vSpot">--</span></div>' +
          '<div class="ctrl-label">Demag<span class="ctrl-val" id="vDemag">--</span></div>' +
          '<div id="focPosCtrl"></div></div></div>';
      }
    }
  };

  function _stripeLabel(mid) {
    if (typeof getStripeMaterial !== 'function') return '';
    var st = getStripeMaterial(mid);
    var name = st ? st.name : '?';
    var col = name==='Pt'?'#e8c840':name==='Rh'?'#60c0ff':name==='Si'?'#90d890':'#999';
    return '<div class="ctrl-label">Coating<span class="ctrl-val" id="v'+mid+'coat" style="color:'+col+'">' + name + '</span></div>';
  }
  var DEV_DERIVED = {
    m1: function(grp) {
      var p = grp.pitch ? grp.pitch.value : 3.0;
      var st = typeof getStripeMaterial==='function' ? getStripeMaterial('m1') : null;
      var mat = st ? st.mat : RH;
      return '<div class="ctrl-label">Deflection<span class="ctrl-val" id="vM1defl">' +
        (p*2).toFixed(1) + ' mrad</span></div>' +
        '<div class="ctrl-label">Cut-off<span class="ctrl-val" id="vM1cut">' +
        (typeof mirrorCut==='function' ? mirrorCut(p,mat).toFixed(1) : '--') + ' keV</span></div>' +
        _stripeLabel('m1');
    },
    m2: function(grp) { return _stripeLabel('m2'); },
    kbv: function(grp) { return _stripeLabel('kbv'); },
    kbh: function(grp) { return _stripeLabel('kbh'); }
  };

  // --- Generalized sync function routing ---
  // Returns oninput handler string for slider; handles all registered sync functions
  function _syncOninput(syncFn, devId, axKey, readbackId) {
    var rb = ";var _rv=document.getElementById('" + readbackId + "');if(_rv)_rv.textContent=parseFloat(this.value).toFixed(3)";
    if (syncFn && typeof window[syncFn] === 'function') {
      return syncFn + '(this.value)' + rb;
    }
    // dynSet already updates readback
    return "dynSet('" + devId + "','" + axKey + "',parseFloat(this.value))";
  }

  function axCtrl(devId, axKey, ax, motor) {
    var id = 'dyn_' + devId + '_' + axKey;
    var val = motor ? motor.value : (ax.value || 0);
    var mn = ax.min != null ? ax.min : -1e6;
    var mx = ax.max != null ? ax.max : 1e6;
    var st = ax.step || 0.001;
    var syncFn = ax.sync && ax.sync.fn;
    var sliderId = (ax.sync && ax.sync.slider) ? ax.sync.slider : (id + 's');
    var readbackId = id + 'v';
    var oninput = _syncOninput(syncFn, devId, axKey, readbackId);
    return '<div class="ax-ctrl">' +
      '<div class="ax-r1">' +
      '<span class="ax-name">' + ax.name + ' <span class="ax-unit">(' + (ax.unit||'') + ')</span></span>' +
      '<span class="ctrl-val ax-pos" id="' + readbackId + '">' + val.toFixed(3) + '</span>' +
      '</div>' +
      '<input type="range" min="' + mn + '" max="' + mx + '" step="' + st +
      '" value="' + val + '" class="ax-slider" id="' + sliderId + '" oninput="' + oninput + '"/>' +
      '<div class="ax-r2">' +
      '<button class="jog-btn jog-neg" onclick="dynJog(\'' + devId + '\',\'' + axKey + '\',-10)">&#x25C4;&#x25C4;</button>' +
      '<button class="jog-btn jog-neg" onclick="dynJog(\'' + devId + '\',\'' + axKey + '\',-1)">&#x25C4;</button>' +
      '<input type="number" value="' + st + '" step="' + (st/10) + '" min="0" class="ax-step" id="' + id + 'st" title="Jog step size"/>' +
      '<button class="jog-btn jog-pos" onclick="dynJog(\'' + devId + '\',\'' + axKey + '\',1)">&#x25BA;</button>' +
      '<button class="jog-btn jog-pos" onclick="dynJog(\'' + devId + '\',\'' + axKey + '\',10)">&#x25BA;&#x25BA;</button>' +
      '</div></div>';
  }
  // Expose globally for mask panel, SVG popup, etc.
  window.axCtrl = function(devId, axKey, ax, motor) { return axCtrl(devId, axKey, ax, motor); };

  window.dynJog = function(devId, axKey, multiplier) {
    var id = 'dyn_' + devId + '_' + axKey;
    var stepInput = document.getElementById(id + 'st');
    var ax = DEVICE_REGISTRY[devId] && DEVICE_REGISTRY[devId].axes[axKey];
    var defaultStep = ax ? (ax.step || 0.001) : 0.001;
    var step = stepInput ? parseFloat(stepInput.value) : defaultStep;
    if (isNaN(step) || step <= 0) step = defaultStep;
    var m = MOTORS[devId] && MOTORS[devId][axKey];
    if (!m) return;
    var dist = step * multiplier;
    var newPos = m.value + dist;
    var mn = ax ? (ax.min != null ? ax.min : -1e6) : -1e6;
    var mx = ax ? (ax.max != null ? ax.max : 1e6) : 1e6;
    newPos = Math.max(mn, Math.min(mx, newPos));
    var syncFn = ax && ax.sync && ax.sync.fn;
    if (syncFn && typeof window[syncFn] === 'function') {
      window[syncFn](newPos);
    } else {
      window.dynSet(devId, axKey, newPos);
    }
    // Update slider position
    var sliderId = (ax && ax.sync && ax.sync.slider) ? ax.sync.slider : (id + 's');
    var sl = document.getElementById(sliderId);
    if (sl) sl.value = newPos;
    // Update readback display
    var rv = document.getElementById(id + 'v');
    if (rv) rv.textContent = newPos.toFixed(3);
    // Propagate optics for sync function path (dynSet already does this)
    if (syncFn && typeof window[syncFn] === 'function') {
      if (typeof updateOptics === 'function') updateOptics();
    }
  };

  // Energy jog: same pattern as dynJog but for mono energy
  window._eJog = function(mult) {
    var stepEl = document.getElementById('eJogStep');
    var step = stepEl ? parseFloat(stepEl.value) : 0.01;
    if (isNaN(step) || step <= 0) step = 0.01;
    var curE = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
    var newE = Math.max(4, Math.min(40, curE + step * mult));
    if (typeof updateEnergy === 'function') updateEnergy(newE);
    var rv = document.getElementById('vEnergy');
    if (rv) rv.textContent = newE.toFixed(3);
    var es = document.getElementById('energySlider');
    if (es) es.value = newE;
  };

  window.dynMoveRel = function(devId, axKey, inputId) {
    var m = MOTORS[devId] && MOTORS[devId][axKey];
    if (!m) return;
    var inp = document.getElementById(inputId);
    if (!inp) return;
    var dist = parseFloat(inp.value);
    if (isNaN(dist) || dist === 0) return;
    window.dynJog(devId, axKey, dist / (DEVICE_REGISTRY[devId].axes[axKey].step || 0.001));
    inp.value = '0';
  };

  function buildDevGroup(devId) {
    var dev = DEVICE_REGISTRY[devId];
    if (!dev) return '';
    var grp = MOTORS[devId];
    if (!grp) return '';
    var _hwBadge = '';
    if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.hwGroups && EPICS_STATE.hwGroups.length > 0) {
      var _gn = (dev.pvPrefix || '').replace(/^BL10:/, '');
      var _isHw = EPICS_STATE.hwGroups.indexOf(_gn) >= 0;
      _hwBadge = _isHw
        ? ' <span style="background:var(--gn);color:#000;font-size:7px;font-weight:700;padding:0 3px;border-radius:2px">HW</span>'
        : ' <span style="color:var(--t3);font-size:7px">SIM</span>';
    }
    var h = '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">' +
      dev.label + _hwBadge + '</h4>' +
      '<div class="ctrl-group" style="margin:0">';
    Object.keys(dev.axes).forEach(function(axKey) {
      var ax = dev.axes[axKey];
      h += axCtrl(devId, axKey, ax, grp[axKey]);
    });
    if (DEV_DERIVED[devId]) h += DEV_DERIVED[devId](grp);
    h += '</div></div>';
    return h;
  }

  window.dynSet = function(devId, axKey, val) {
    var m = MOTORS[devId] && MOTORS[devId][axKey];
    if (!m) return;
    var ax = DEVICE_REGISTRY[devId] && DEVICE_REGISTRY[devId].axes[axKey];
    var mn = ax ? (ax.min != null ? ax.min : -1e6) : -1e6;
    var mx = ax ? (ax.max != null ? ax.max : 1e6) : 1e6;
    val = Math.max(mn, Math.min(mx, val));
    m.value = val; m.target = val;
    var id = 'dyn_' + devId + '_' + axKey;
    var sv = document.getElementById(id+'v');
    var ss = document.getElementById(id+'s');
    var sn = document.getElementById(id+'n');
    if (sv) sv.textContent = val.toFixed(3);
    if (ss) ss.value = val;
    if (sn) sn.value = val;
    if (typeof syncMotorToState==='function') syncMotorToState(devId, m.id, val);
    if (typeof updateOptics==='function') updateOptics();
    if (typeof renderLayout==='function') renderLayout();
  };

  function renderDynTabs() {
    Object.keys(TAB_LAYOUT).forEach(function(tabKey) {
      var lay = TAB_LAYOUT[tabKey];
      var el = document.getElementById('tab-' + tabKey);
      if (!el) return;
      var h = '';
      if (lay.header) h += lay.header();
      lay.devices.forEach(function(devId) { h += buildDevGroup(devId); });
      if (lay.derived) h += lay.derived();
      el.innerHTML = h;
    });
    if (typeof updateEnergy==='function') {
      var es = document.getElementById('energySlider');
      if (es) updateEnergy(es.value);
    }
    // Trigger IVU display update
    if (typeof updateUnd === 'function' && typeof state !== 'undefined') {
      updateUnd(state.gap || 7);
    }
  }

  window.renderDynTabs = renderDynTabs;

  if (document.readyState==='loading') {
    document.addEventListener('DOMContentLoaded', renderDynTabs);
  } else {
    renderDynTabs();
  }
  console.log('[V4.36] Dynamic tab renderer loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _eJog!=="undefined")globalThis._eJog=_eJog;
if(typeof axCtrl!=="undefined")globalThis.axCtrl=axCtrl;
if(typeof dynJog!=="undefined")globalThis.dynJog=dynJog;
if(typeof dynMoveRel!=="undefined")globalThis.dynMoveRel=dynMoveRel;
if(typeof dynSet!=="undefined")globalThis.dynSet=dynSet;
if(typeof renderDynTabs!=="undefined")globalThis.renderDynTabs=renderDynTabs;
