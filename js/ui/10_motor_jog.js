'use strict';
// ===== ui/10_motor_jog.js — Generic Motor Sliders + Motor Jog UI + Live Beam Monitor =====
// @module ui/10_motor_jog
// @exports _applyMotorDetails, _showMotorDetailsPopup, motorJog, motorUpdate, showMotorGroup, updateLiveBeamInfo
// Extracted from 14_v435_final.js (DDD Phase 5g)
// Provides: motorUpdate, showComp override (Advanced Motors injection),
//   showMotorGroup override (jog-button UI), motorJog override, updateLiveBeamInfo

// === Generic motor sliders for all axes + MC-linked updates ===
(function(){

// 1. Generic motor update: set MOTORS value + refresh beam
window.motorUpdate=function(devId,axKey,val){
  val=parseFloat(val);
  if(!MOTORS[devId]||!MOTORS[devId][axKey])return;
  MOTORS[devId][axKey].value=val;
  MOTORS[devId][axKey].target=val;
  // Sync special state keys
  var ax=MOTORS[devId][axKey];
  if(ax.sync&&ax.sync.stateKey&&typeof state!=='undefined'){
    state[ax.sync.stateKey]=val;
    var el=ax.sync.uiId?document.getElementById(ax.sync.uiId):null;
    if(el)el.value=val;
  }
  // Slit center sync
  if(devId==='wbslit'&&(axKey==='hcenter'||axKey==='vcenter')){
    if(axKey==='hcenter')state.wbCX=val;
    if(axKey==='vcenter')state.wbCY=val;
  }
  if(devId==='ssa'&&(axKey==='hcen'||axKey==='vcen')){
    if(axKey==='hcen')state.ssaCX=val;
    if(axKey==='vcen')state.ssaCY=val;
  }
  // Blade pseudo-motor recalc
  if(devId==='wbslit'&&typeof slitGapCenterToBlades==='function'){
    slitGapCenterToBlades('wbslit',state.wbH,state.wbV,state.wbCX,state.wbCY);
  }
  _mcSampleCache=null;
  try{if(typeof updateOptics==='function')updateOptics();}catch(e){}
  try{if(typeof renderLayout==='function')renderLayout();}catch(e){}
  if(typeof refreshBeamOnly==='function')refreshBeamOnly(devId);
};

// NOTE: Motor controls in popup removed — motor positioning is handled by the right-side motor tab only

console.log('[V4.36] Generic motor sliders ready');
})();

// === Motor UI overrides + Live Beam Monitor ===
(function(){

  // --- Override showMotorGroup (08_ui_core.js) with unified jog-button UI ---
  var _origShowMotorGroup = typeof showMotorGroup === 'function' ? showMotorGroup : null;

  window.showMotorGroup = function(groupId) {
    var panel = document.getElementById('motorGroupPanel');
    if (!panel) return;
    if (!MOTORS[groupId]) {
      panel.innerHTML = '<div style="color:var(--t3);font-size:9px">No motors for ' + groupId + '</div>';
      return;
    }
    var grp = MOTORS[groupId];
    var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x){ return x && x.id; });
    var h = '';
    // HW/SIM badge in hybrid mode
    var dev = (typeof DEVICE_REGISTRY !== 'undefined') ? DEVICE_REGISTRY[groupId] : null;
    if (dev && typeof EPICS_STATE !== 'undefined' && EPICS_STATE.hwGroups && EPICS_STATE.hwGroups.length > 0) {
      var pfx = dev.pvPrefix || '';
      var grpName = pfx.replace(/^BL10:/, '');
      var isHw = false;
      for (var gi = 0; gi < EPICS_STATE.hwGroups.length; gi++) {
        if (grpName === EPICS_STATE.hwGroups[gi]) { isHw = true; break; }
      }
      var badge = isHw
        ? '<span style="background:var(--gn);color:#000;font-size:7px;font-weight:700;padding:1px 4px;border-radius:2px;margin-left:4px">HW</span>'
        : '<span style="background:var(--s2);color:var(--t3);font-size:7px;padding:1px 4px;border-radius:2px;margin-left:4px">SIM</span>';
      h += '<div style="display:flex;align-items:center;margin-bottom:4px">' +
        '<span style="font-size:9px;color:var(--t2)">' + dev.label + '</span>' + badge + '</div>';
    }
    motors.forEach(function(m) {
      var mid = 'mot_' + groupId + '_' + m.id;
      var st = m.step || 0.001;
      var _llm = typeof m.llm === 'number' ? m.llm : m.min;
      var _hlm = typeof m.hlm === 'number' ? m.hlm : m.max;
      h += '<div class="ax-ctrl">' +
        '<div class="ax-r1">' +
        '<span class="ax-name" onclick="_showMotorDetailsPopup(\'' + groupId + '\',\'' + m.id + '\')" ' +
        'style="cursor:pointer" title="Click for motor details">' +
        m.name + ' <span class="ax-unit">(' + (m.unit||'') + ')</span></span>' +
        '<span id="mlim_' + m.id + '" style="font-size:7px;color:var(--t3);margin-left:auto;white-space:nowrap">' +
        _llm.toFixed(2) + '~' + _hlm.toFixed(2) + ' ' + (m.unit||'') + '</span>' +
        '<span class="ctrl-val ax-pos" id="mval_' + m.id + '">' + m.value.toFixed(3) + '</span>' +
        '</div>' +
        '<div class="ax-r2">' +
        '<button class="jog-btn jog-neg" onclick="motorJog(\'' + groupId + '\',\'' + m.id + '\',-10)">&#x25C4;&#x25C4;</button>' +
        '<button class="jog-btn jog-neg" onclick="motorJog(\'' + groupId + '\',\'' + m.id + '\',-1)">&#x25C4;</button>' +
        '<input type="number" value="' + st + '" step="' + (st/10) + '" min="0" class="ax-step" id="' + mid + 'st" title="Jog step"/>' +
        '<button class="jog-btn jog-pos" onclick="motorJog(\'' + groupId + '\',\'' + m.id + '\',1)">&#x25BA;</button>' +
        '<button class="jog-btn jog-pos" onclick="motorJog(\'' + groupId + '\',\'' + m.id + '\',10)">&#x25BA;&#x25BA;</button>' +
        '<span style="font-size:7px;color:var(--t3);margin-left:auto;white-space:nowrap">res:' + (m.resolution||'\u2014') + '</span>' +
        '</div>' +
        '<div class="ax-r3" style="display:flex;align-items:center;gap:4px;margin-top:2px">' +
        '<span style="font-size:7px;color:var(--t2);white-space:nowrap">Abs:</span>' +
        '<input type="number" value="' + m.value.toFixed(4) + '" step="' + st + '" class="ax-abs" id="' + mid + 'abs" ' +
        'title="Absolute position" style="width:90px;font-size:8px;background:var(--s2);color:var(--t1);border:1px solid var(--b1);border-radius:2px;padding:2px 4px;text-align:right" ' +
        'onchange="motorSetUI(\'' + groupId + '\',\'' + m.id + '\',parseFloat(this.value));' +
        'var _p=document.getElementById(\'mval_' + m.id + '\');if(_p)_p.textContent=parseFloat(this.value).toFixed(3);' +
        'var _sl=document.getElementById(\'' + mid + 's\');if(_sl)_sl.value=parseFloat(this.value)"/>' +
        '<span style="font-size:7px;color:var(--t3)">' + (m.unit||'') + '</span>' +
        '</div></div>';
    });
    panel.innerHTML = h;
  };

  // --- Override motorJog to use step input instead of fixed m.step ---
  window.motorJog = function(gid, mid, multiplier) {
    var grp = MOTORS[gid];
    if (!grp) return;
    var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x){ return x && x.id; });
    var m = null;
    for (var i = 0; i < motors.length; i++) { if (motors[i].id === mid) { m = motors[i]; break; } }
    if (!m) return;
    var stepEl = document.getElementById('mot_' + gid + '_' + mid + 'st');
    var step = stepEl ? parseFloat(stepEl.value) : m.step;
    if (isNaN(step) || step <= 0) step = m.step;
    var newVal = m.value + step * multiplier;
    newVal = Math.max(m.min, Math.min(m.max, newVal));
    m.value = newVal; m.target = newVal;
    var posEl = document.getElementById('mval_' + mid);
    if (posEl) posEl.textContent = newVal.toFixed(3);
    var absEl = document.getElementById('mot_' + gid + '_' + mid + 'abs');
    if (absEl) absEl.value = newVal.toFixed(4);
    if (typeof syncMotorToState === 'function') syncMotorToState(gid, mid, newVal);
    if (typeof log === 'function') log('info', m.name + ' \u2192 ' + newVal.toFixed(3) + ' ' + m.unit);
    if (m.pv && typeof epicsPut === 'function' && typeof EPICS_STATE !== 'undefined' && EPICS_STATE.mode !== 'disconnected') epicsPut(m.pv, newVal);
  };

  // --- Define updateLiveBeamInfo ---
  window.updateLiveBeamInfo = function() {
    var E = state.energy || 10;
    var flux = 0;

    try { flux = typeof photonFlux === 'function' ? photonFlux(E) : 0; } catch(e){}

    // MC-based focal spot (consistent with beam profile display)
    var mcSpot = null;
    try { if (typeof focalSpot === 'function') mcSpot = focalSpot(); } catch(e){}

    var eEl = document.getElementById('lm_e');
    var fEl = document.getElementById('lm_flux');
    var shEl = document.getElementById('lm_sh');

    if (eEl) eEl.textContent = E.toFixed(2) + ' keV';
    if (fEl) fEl.textContent = flux > 0 ? flux.toExponential(2) : '\u2014';
    if (mcSpot && shEl) {
      shEl.textContent = mcSpot.h.toFixed(0) + '\u00d7' + mcSpot.v.toFixed(0) + ' nm';
    }

    var liveE = document.getElementById('liveE');
    var liveFlux = document.getElementById('liveFlux');
    var liveSpot = document.getElementById('liveSpot');
    if (liveE) liveE.textContent = E.toFixed(2);
    if (liveFlux) liveFlux.textContent = flux > 0 ? flux.toExponential(2) : '\u2014';
    if (mcSpot && liveSpot) {
      liveSpot.textContent = mcSpot.h.toFixed(0) + '\u00d7' + mcSpot.v.toFixed(0) + ' nm';
    }

    // FM/MM/WBS/SSA/Sample beam size readbacks removed from bottom panel
  };

  window.addEventListener('load', function() {
    setTimeout(function() {
      if (typeof updateLiveBeamInfo === 'function') updateLiveBeamInfo();
    }, 500);
  });

  // --- Motor Details Popup (click on motor name) ---
  window._showMotorDetailsPopup = function(groupId, motorId) {
    var existing = document.getElementById('motorDetailsOverlay');
    if (existing) existing.remove();

    var grp = MOTORS[groupId];
    if (!grp) return;
    var motors = Array.isArray(grp) ? grp : Object.values(grp).filter(function(x){ return x && x.id; });
    var m = null;
    for (var i = 0; i < motors.length; i++) { if (motors[i].id === motorId) { m = motors[i]; break; } }
    if (!m) return;

    var reg = (typeof PV_REGISTRY !== 'undefined' && m.pv) ? PV_REGISTRY[m.pv] : null;
    var motor = reg ? reg.motor : m;
    var llm  = (motor && typeof motor.llm  === 'number') ? motor.llm  : m.min;
    var hlm  = (motor && typeof motor.hlm  === 'number') ? motor.hlm  : m.max;
    var velo = (motor && typeof motor.velo === 'number') ? motor.velo : (m.speed || 1.0);
    var dllm = (motor && typeof motor.dllm === 'number') ? motor.dllm : llm;
    var dhlm = (motor && typeof motor.dhlm === 'number') ? motor.dhlm : hlm;
    var lls  = (motor && typeof motor.lls  === 'number') ? motor.lls  : 0;
    var hls  = (motor && typeof motor.hls  === 'number') ? motor.hls  : 0;
    var pos  = m.value;
    var pvLabel = m.pv ? m.pv.replace('BL10:', '') : '(no PV)';
    var isHw = reg && reg.source === 'hardware';
    var srcBadge = isHw
      ? '<span style="background:var(--gn);color:#000;font-size:11px;font-weight:700;padding:2px 7px;border-radius:2px">HW</span>'
      : '<span style="background:var(--s2);color:var(--t1);font-size:11px;padding:2px 7px;border-radius:2px;border:1px solid var(--b1)">SIM</span>';

    // Travel bar: DLLM .. LLM .. pos .. HLM .. DHLM
    var dRange = dhlm - dllm;
    if (dRange <= 0) dRange = (hlm - llm) > 0 ? (hlm - llm) * 1.2 : 10;
    var llmPct = Math.max(0, Math.min(100, (llm  - dllm) / dRange * 100));
    var hlmPct = Math.max(0, Math.min(100, (hlm  - dllm) / dRange * 100));
    var posPct = Math.max(0, Math.min(100, (pos  - dllm) / dRange * 100));
    var softW  = hlmPct - llmPct;
    var toLlm  = pos - llm;
    var toHlm  = hlm - pos;
    var toLlmStr = (toLlm >= 0 ? '+' : '') + toLlm.toFixed(3) + ' ' + (m.unit||'');
    var toHlmStr = (toHlm >= 0 ? '+' : '') + toHlm.toFixed(3) + ' ' + (m.unit||'');

    var llsColor = lls ? 'var(--rd,#f87171)' : 'var(--t1)';
    var hlsColor = hls ? 'var(--rd,#f87171)' : 'var(--t1)';
    var llsLabel = lls ? 'ON' : 'off';
    var hlsLabel = hls ? 'ON' : 'off';

    // Build content HTML for non-modal popup
    var _mdpContentHtml =
      // Header (drag handle)
      '<div id="motorDetailsTitleBar" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
        '<div style="display:flex;align-items:center;gap:10px">' +
          '<span style="font-size:22px;font-weight:700;color:var(--gn)">' + m.name + '</span>' +
          srcBadge +
        '</div>' +
        '<button onclick="var _p=document.getElementById(\'motor_' + motorId + '\');if(_p&&_p._popupAPI)_p._popupAPI.close();else{var _o=document.getElementById(\'motorDetailsOverlay\');if(_o)_o.remove();}" ' +
        'style="background:none;border:none;color:var(--t1);font-size:28px;cursor:pointer;line-height:1;padding:0 4px;opacity:0.7">&times;</button>' +
      '</div>' +
      '<div style="font-size:14px;color:var(--t1);margin-bottom:14px">' + pvLabel + '</div>' +
      // Position + MRES
      '<div style="background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:12px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center">' +
        '<div>' +
          '<div style="font-size:14px;color:var(--t1);margin-bottom:3px">Current Position</div>' +
          '<div style="font-size:26px;font-weight:700;color:var(--gn)" id="mdp_pos">' + pos.toFixed(4) +
            ' <span style="font-size:16px;color:var(--t1)">' + (m.unit||'') + '</span></div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="font-size:14px;color:var(--t1);margin-bottom:3px">MRES</div>' +
          '<div style="font-size:18px;color:var(--t1)">' + (m.resolution || '\u2014') + ' ' + (m.unit||'') + '</div>' +
        '</div>' +
      '</div>' +
      // Travel bar
      '<div style="margin-bottom:14px">' +
        '<div style="font-size:14px;color:var(--t1);margin-bottom:6px;font-weight:600;letter-spacing:0.5px">TRAVEL RANGE</div>' +
        '<div style="position:relative;height:24px;background:var(--s2);border-radius:3px;overflow:hidden;border:1px solid var(--b1,#333)">' +
          '<div style="position:absolute;left:0;top:0;width:' + llmPct.toFixed(1) + '%;height:100%;background:rgba(255,179,64,0.22)"></div>' +
          '<div style="position:absolute;left:' + llmPct.toFixed(1) + '%;top:0;width:' + softW.toFixed(1) + '%;height:100%;background:rgba(64,216,154,0.15)"></div>' +
          '<div style="position:absolute;left:' + hlmPct.toFixed(1) + '%;top:0;right:0;height:100%;background:rgba(255,179,64,0.22)"></div>' +
          '<div style="position:absolute;left:' + llmPct.toFixed(1) + '%;top:0;width:1px;height:100%;background:var(--am);opacity:0.8"></div>' +
          '<div style="position:absolute;left:' + hlmPct.toFixed(1) + '%;top:0;width:1px;height:100%;background:var(--am);opacity:0.8"></div>' +
          '<div style="position:absolute;left:' + posPct.toFixed(1) + '%;top:3px;width:4px;height:18px;background:var(--gn);border-radius:1px;transform:translateX(-50%);box-shadow:0 0 5px var(--gn)"></div>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;font-size:13px;color:var(--t1);margin-top:4px">' +
          '<span>' + dllm.toFixed(3) + '</span>' +
          '<span>' + pos.toFixed(3) + ' ' + (m.unit||'') + '</span>' +
          '<span>' + dhlm.toFixed(3) + '</span>' +
        '</div>' +
      '</div>' +
      // Hard limits + Limit switch
      '<div style="display:flex;gap:10px;margin-bottom:14px">' +
        '<div style="flex:1;background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:11px">' +
          '<div style="font-size:14px;color:var(--t1);margin-bottom:7px">Hard Limits (Dial) \u2014 Read Only</div>' +
          '<div style="display:flex;justify-content:space-between;font-size:18px">' +
            '<span style="color:var(--am)">DLLM <span style="color:var(--t1);font-weight:600">' + dllm.toFixed(3) + '</span></span>' +
            '<span style="color:var(--am)">DHLM <span style="color:var(--t1);font-weight:600">' + dhlm.toFixed(3) + '</span></span>' +
          '</div>' +
        '</div>' +
        '<div style="background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:11px;min-width:130px;text-align:center">' +
          '<div style="font-size:14px;color:var(--t1);margin-bottom:7px">Limit Switch</div>' +
          '<div style="display:flex;justify-content:space-around;font-size:18px">' +
            '<span>LLS<br><span style="color:' + llsColor + ';font-weight:700">' + llsLabel + '</span></span>' +
            '<span>HLS<br><span style="color:' + hlsColor + ';font-weight:700">' + hlsLabel + '</span></span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      // Soft limit settings (editable)
      '<div style="background:var(--s2);border:1px solid var(--b1,#333);border-radius:4px;padding:12px;margin-bottom:16px">' +
        '<div style="font-size:14px;color:var(--t1);margin-bottom:10px;font-weight:600;letter-spacing:0.5px">SOFT LIMITS (Editable)</div>' +
        '<div style="display:flex;flex-direction:column;gap:9px">' +
          '<div style="display:flex;align-items:center;gap:8px">' +
            '<label style="font-size:16px;color:var(--t1);width:160px;flex-shrink:0">Speed (VELO)</label>' +
            '<input type="number" id="mdp_velo" value="' + velo.toFixed(4) + '" step="0.001" min="0.001" ' +
            'style="flex:1;font-size:16px;background:var(--bg);color:var(--t1);border:1px solid var(--b1,#333);border-radius:3px;padding:5px 10px"/>' +
            '<span style="font-size:14px;color:var(--t1);flex-shrink:0;width:65px">' + (m.unit||'') + '/s</span>' +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:8px">' +
            '<label style="font-size:16px;color:var(--t1);width:160px;flex-shrink:0">Low Limit (LLM)</label>' +
            '<input type="number" id="mdp_llm" value="' + llm.toFixed(4) + '" ' +
            'style="flex:1;font-size:16px;background:var(--bg);color:var(--t1);border:1px solid var(--b1,#333);border-radius:3px;padding:5px 10px"/>' +
            '<span style="font-size:14px;color:var(--t1);flex-shrink:0;width:65px">' + (m.unit||'') + '</span>' +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:8px">' +
            '<label style="font-size:16px;color:var(--t1);width:160px;flex-shrink:0">High Limit (HLM)</label>' +
            '<input type="number" id="mdp_hlm" value="' + hlm.toFixed(4) + '" ' +
            'style="flex:1;font-size:16px;background:var(--bg);color:var(--t1);border:1px solid var(--b1,#333);border-radius:3px;padding:5px 10px"/>' +
            '<span style="font-size:14px;color:var(--t1);flex-shrink:0;width:65px">' + (m.unit||'') + '</span>' +
          '</div>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;margin-top:10px;font-size:14px;color:var(--t1)">' +
          '<span>To LLM: <span style="color:var(--am)">' + toLlmStr + '</span></span>' +
          '<span>To HLM: <span style="color:var(--am)">' + toHlmStr + '</span></span>' +
        '</div>' +
      '</div>' +
      // Buttons
      '<div style="display:flex;gap:8px;justify-content:flex-end">' +
        '<button onclick="var _p=document.getElementById(\'motor_' + motorId + '\');if(_p&&_p._popupAPI)_p._popupAPI.close();else{var _o=document.getElementById(\'motorDetailsOverlay\');if(_o)_o.remove();}" ' +
        'style="background:var(--s2);border:1px solid var(--b1,#444);color:var(--t1);font-size:16px;padding:8px 24px;border-radius:4px;cursor:pointer">Close</button>' +
        (m.pv
          ? '<button onclick="_applyMotorDetails(\'' + m.pv.replace(/'/g, "\\'") + '\',\'' + motorId + '\')" ' +
            'style="background:var(--ac);border:none;color:#000;font-size:16px;font-weight:700;padding:8px 24px;border-radius:4px;cursor:pointer">Apply</button>'
          : '') +
      '</div>';

    if (typeof _openPopup === 'function') {
      _openPopup({
        id: 'motor_' + motorId,
        title: m.name + ' — ' + pvLabel,
        width: 380, height: 600,
        content: _mdpContentHtml,
        resizable: true, minWidth: 480, minHeight: 380,
        headerColor: 'var(--gn)'
      });
    } else {
      // Fallback: legacy overlay
      var overlay = document.createElement('div');
      overlay.id = 'motorDetailsOverlay';
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.55);z-index:10002';
      overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
      var dlg = document.createElement('div');
      dlg.id = 'motorDetailsDlg';
      dlg.style.cssText = 'position:fixed;top:50px;left:50px;background:var(--s1);border:1px solid var(--b1);border-radius:8px;padding:22px;width:560px;z-index:10003';
      dlg.innerHTML = _mdpContentHtml;
      overlay.appendChild(dlg);
      document.body.appendChild(overlay);
    }
  };

  window._applyMotorDetails = function(pvName, motorId) {
    var veloEl = document.getElementById('mdp_velo');
    var llmEl = document.getElementById('mdp_llm');
    var hlmEl = document.getElementById('mdp_hlm');
    if (!veloEl || !llmEl || !hlmEl) return;

    var velo = parseFloat(veloEl.value);
    var llm  = parseFloat(llmEl.value);
    var hlm  = parseFloat(hlmEl.value);

    if (isNaN(velo) || velo <= 0) { if (typeof log === 'function') log('err', 'Invalid speed value'); return; }
    if (isNaN(llm) || isNaN(hlm)) { if (typeof log === 'function') log('err', 'Invalid limit value'); return; }
    if (llm >= hlm) { if (typeof log === 'function') log('err', 'Low limit must be < high limit'); return; }

    if (typeof epicsPut === 'function') {
      epicsPut(pvName + '.VELO', velo);
      epicsPut(pvName + '.LLM', llm);
      epicsPut(pvName + '.HLM', hlm);
      if (typeof log === 'function') log('info', pvName.replace('BL10:','') + ': VELO=' + velo + ', LLM=' + llm + ', HLM=' + hlm);
    }

    // Update local motor object so jog clamping and display are consistent
    var reg = (typeof PV_REGISTRY !== 'undefined') ? PV_REGISTRY[pvName] : null;
    if (reg && reg.motor) {
      reg.motor.velo = velo;
      reg.motor.llm  = llm;
      reg.motor.hlm  = hlm;
      reg.motor.min  = llm;
      reg.motor.max  = hlm;
      if (typeof _updateMotorLimitDisplay === 'function') _updateMotorLimitDisplay(pvName);
    }

    // Close popup (try _openPopup API first, then legacy overlay)
    var _mpList = typeof _popupManager !== 'undefined' ? _popupManager.list : [];
    for (var _mi = 0; _mi < _mpList.length; _mi++) {
      if (_mpList[_mi].id && _mpList[_mi].id.indexOf('motor_') === 0 && _mpList[_mi]._popupAPI) {
        _mpList[_mi]._popupAPI.close(); break;
      }
    }
    var _mOvl = document.getElementById('motorDetailsOverlay');
    if (_mOvl) _mOvl.remove();
  };

  console.log('[V4.36] Motor jog UI + Live beam monitor loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _applyMotorDetails!=="undefined")globalThis._applyMotorDetails=_applyMotorDetails;
if(typeof _showMotorDetailsPopup!=="undefined")globalThis._showMotorDetailsPopup=_showMotorDetailsPopup;
if(typeof motorJog!=="undefined")globalThis.motorJog=motorJog;
if(typeof motorUpdate!=="undefined")globalThis.motorUpdate=motorUpdate;
if(typeof showMotorGroup!=="undefined")globalThis.showMotorGroup=showMotorGroup;
if(typeof updateLiveBeamInfo!=="undefined")globalThis.updateLiveBeamInfo=updateLiveBeamInfo;
