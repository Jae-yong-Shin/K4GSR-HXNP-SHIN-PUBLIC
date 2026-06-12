'use strict';
// ===== control/03_energy_sync.js — Energy Sync + Slider Handlers + Slit Pseudo-Motors =====
// @module control/03_energy_sync
// @exports compSliderUpdate, defaultSourceBW, kbslitSliderUpdate, refreshBeamOnly, refreshInfoOnly, slitBladesToGapCenter, slitGapCenterToBlades, ssaSliderUpdate, updateEnergy
// Extracted from 14_v435_final.js (DDD Phase 5d)
// Provides: compSliderUpdate, ssaSliderUpdate, refreshInfoOnly, refreshBeamOnly,
//   updateEnergy wrapper (_syncDCMToEnergy), slitBladesToGapCenter, slitGapCenterToBlades

// === SSA + WB + RT slider ===
(function(){
  // SSA center offset state + motors
  state.ssaCX=0; state.ssaCY=0;
  if(typeof MOTORS!=='undefined'&&MOTORS.ssa){
    MOTORS.ssa.hcenter={value:0,target:0,unit:'um',min:-100,max:100,step:1,label:'H Center'};
    MOTORS.ssa.vcenter={value:0,target:0,unit:'um',min:-100,max:100,step:1,label:'V Center'};
  }

  // --- Unified slider handlers ---
  window.compSliderUpdate=function(compId,param,val){
    val=parseFloat(val);
    if(compId==='ivu'){state.gap=val;var ge=document.getElementById('gapSlider');if(ge)ge.value=val;try{updateUnd(val);}catch(e){}}
    else if(compId==='wbslit'){
      if(param==='h'){state.wbH=val;var e=document.getElementById('wbH');if(e)e.value=val;if(MOTORS.wbslit&&MOTORS.wbslit.hgap){MOTORS.wbslit.hgap.value=val;MOTORS.wbslit.hgap.target=val;}}
      else{state.wbV=val;var e2=document.getElementById('wbV');if(e2)e2.value=val;if(MOTORS.wbslit&&MOTORS.wbslit.vgap){MOTORS.wbslit.vgap.value=val;MOTORS.wbslit.vgap.target=val;}}
      if(typeof updateHarmPanel==='function')updateHarmPanel();
    }
    else if(compId==='m1'){var s=document.getElementById('m1Slider');if(s)s.value=val;try{updateM1(val);}catch(e){}}
    else if(compId==='m2'){var s2=document.getElementById('m2Slider');if(s2)s2.value=val;try{updateM2(val);}catch(e){}}
    else if(compId==='kbv'){state.kbvpitch=val;if(MOTORS.kbv&&MOTORS.kbv.pitch){MOTORS.kbv.pitch.value=val;MOTORS.kbv.pitch.target=val;}if(typeof syncMotorToState==='function')syncMotorToState('kbv','kbv_pitch',val);}
    else if(compId==='kbh'){state.kbhpitch=val;if(MOTORS.kbh&&MOTORS.kbh.pitch){MOTORS.kbh.pitch.value=val;MOTORS.kbh.pitch.target=val;}if(typeof syncMotorToState==='function')syncMotorToState('kbh','kbh_pitch',val);}
    else if(compId==='dcm'){var es=document.getElementById('energySlider');if(es)es.value=val;try{updateEnergy(val);}catch(e){}try{refreshInfoOnly('dcm');}catch(e){}}
    _mcSampleCache=null;
    try{updateOptics();}catch(e){}
    _doBeamRefresh(compId);
  };

  window.ssaSliderUpdate=function(axis,val){
    val=parseFloat(val);
    if(axis==='h'){state.ssaH=val;var _e=document.getElementById('ssaH');if(_e)_e.value=val;if(MOTORS.ssa&&MOTORS.ssa.hgap){MOTORS.ssa.hgap.value=val;MOTORS.ssa.hgap.target=val;}}
    else if(axis==='v'){state.ssaV=val;var _e2=document.getElementById('ssaV');if(_e2)_e2.value=val;if(MOTORS.ssa&&MOTORS.ssa.vgap){MOTORS.ssa.vgap.value=val;MOTORS.ssa.vgap.target=val;}}
    else if(axis==='cx'){state.ssaCX=val;if(MOTORS.ssa&&MOTORS.ssa.hcenter)MOTORS.ssa.hcenter.value=val;}
    else if(axis==='cy'){state.ssaCY=val;if(MOTORS.ssa&&MOTORS.ssa.vcenter)MOTORS.ssa.vcenter.value=val;}
    _mcSampleCache=null;
    try{updateOptics();}catch(e){}
    _doBeamRefresh('ssa');
    try{if(typeof _refreshPtychoCoherence==='function')_refreshPtychoCoherence();}catch(e){}
  };

  window.kbslitSliderUpdate=function(axis,val){
    val=parseFloat(val);
    if(axis==='h'){state.kbslitH=val;var _e=document.getElementById('kbslitH');if(_e)_e.value=val;if(MOTORS.kbslit&&MOTORS.kbslit.hgap){MOTORS.kbslit.hgap.value=val;MOTORS.kbslit.hgap.target=val;}}
    else if(axis==='v'){state.kbslitV=val;var _e2=document.getElementById('kbslitV');if(_e2)_e2.value=val;if(MOTORS.kbslit&&MOTORS.kbslit.vgap){MOTORS.kbslit.vgap.value=val;MOTORS.kbslit.vgap.target=val;}}
    else if(axis==='cx'){state.kbslitCX=val;if(MOTORS.kbslit&&MOTORS.kbslit.hcenter)MOTORS.kbslit.hcenter.value=val;}
    else if(axis==='cy'){state.kbslitCY=val;if(MOTORS.kbslit&&MOTORS.kbslit.vcenter)MOTORS.kbslit.vcenter.value=val;}
    _mcSampleCache=null;
    try{updateOptics();}catch(e){}
    _doBeamRefresh('kbslit');
  };

  function _doBeamRefresh(compId){
    var bp=document.getElementById('beamProfile_'+compId);
    if(!bp)return;
    renderBeamProfileAt('beamProfile_'+compId, pos(compId));
  }

  window.refreshInfoOnly=function(cid){
    if(curModal!==cid)return;
    var ig=document.querySelector('#modalBody .info-grid');
    if(!ig)return;
    if(cid==='dcm'){
      var th=braggAngle(state.energy),td=isNaN(th)?0:th*180/Math.PI;
      var d=D_SI[state.crystal];
      var vals=ig.querySelectorAll('.info-item .val');
      if(vals.length>=9){
        vals[0].textContent='Si('+state.crystal+')';
        vals[1].textContent=d.toFixed(4)+' \u00c5';
        vals[2].textContent=td.toFixed(3)+'\u00b0';
        vals[3].textContent=(isNaN(th)?'-':dcmGap(th).toFixed(2))+' mm';
        vals[4].textContent=darwinW(state.energy).toFixed(2)+' arcsec';
        vals[5].textContent=dcmRes(state.energy).toExponential(2);
        vals[6].textContent=extDepth(state.energy).toFixed(2)+' \u00b5m';
        vals[7].textContent='n='+state.harmonic+' @'+state.energy.toFixed(2)+' keV';
      }
    }
  };
  window.refreshBeamOnly=function(cid){_doBeamRefresh(cid);};

  // === updateEnergy — INLINE MERGED (base from 08_ui_core.js + DCM sync) ===
  // Base: sidebar Bragg/Darwin/d-spacing updates + renderLayout
  // Addition: DCM theta/z2 motor auto-sync
  // Default source energy bandwidth (eV) as a function of energy.
  // These values represent the effective DCM-filtered bandwidth for MC ray tracing.
  // User can override via the IVU tab UI control.
  window.defaultSourceBW = function(E_keV) {
    // Piecewise linear interpolation: 5keV=1eV, 10keV=1eV, 20keV=5eV, 25keV=7eV
    if (E_keV <= 5) return 1.0;
    if (E_keV <= 10) return 1.0;
    if (E_keV <= 20) return 1.0 + (E_keV - 10) * (5.0 - 1.0) / (20 - 10);
    if (E_keV <= 25) return 5.0 + (E_keV - 20) * (7.0 - 5.0) / (25 - 20);
    return 7.0;
  };

  window.updateEnergy = function(v) {
    // --- base logic (from 08_ui_core.js) ---
    var newE = parseFloat(v);
    var energyChanged = (Math.abs(newE - state.energy) > 1e-6);
    state.energy = newE;
    // Auto-set source bandwidth ONLY when energy actually changes
    // (preserves user's custom sourceBW_eV set via UI)
    if (energyChanged) {
      state.sourceBW_eV = defaultSourceBW(state.energy);
    }
    var _s = function(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
    _s('liveE', state.energy.toFixed(2));
    var th = braggAngle(state.energy);
    if (!isNaN(th)) {
      var d = D_SI[state.crystal];
      _s('vEnergy', state.energy.toFixed(3));
      _s('vBragg', (th * 180 / Math.PI).toFixed(3) + '\u00b0');
      _s('vGapDCM', dcmGap(th).toFixed(2) + ' mm');
      _s('vDarwin', darwinW(state.energy).toFixed(2) + ' arcsec');
      _s('vRes', dcmRes(state.energy).toExponential(1));
      _s('vThru', (dcmThru(state.energy) * 100).toFixed(1) + '%');
      _s('vDspacing', d.toFixed(4) + ' \u00c5 Si(' + state.crystal + ')');
      try { renderLayout(); } catch (e) {}
      if (typeof updateCompare === 'function') try { updateCompare(); } catch (e) {}
    }
    // --- DCM motor sync (from 14_v435_final.js) ---
    _syncDCMToEnergy();
    try{if(typeof _refreshPtychoCoherence==='function')_refreshPtychoCoherence();}catch(e){}
    // Live-update experiment panel beamline status
    try{if(typeof _updateExptBeamlineStatus==='function')_updateExptBeamlineStatus();}catch(e){}
  };

  function _syncDCMToEnergy() {
    if (typeof MOTORS === 'undefined' || !MOTORS.dcm) return;
    var thB = braggAngle(state.energy);
    if (isNaN(thB)) return;
    var thDeg = thB * 180 / Math.PI;
    if (MOTORS.dcm.theta) {
      MOTORS.dcm.theta.value = thDeg;
      MOTORS.dcm.theta.target = thDeg;
    }
    var gap = FIXED_EXIT / (2 * Math.cos(thB));
    if (MOTORS.dcm.z2) {
      MOTORS.dcm.z2.value = gap;
      MOTORS.dcm.z2.target = gap;
    }
    var ids = [['theta', thDeg], ['z2', gap]];
    ids.forEach(function(pair) {
      var k = pair[0], val = pair[1];
      var r = document.getElementById('adv_dcm_' + k + 'r');
      var n = document.getElementById('adv_dcm_' + k + 'n');
      if (r) r.value = val;
      if (n) n.value = val.toFixed(4);
    });
  }

  if (document.readyState === 'complete') setTimeout(_syncDCMToEnergy, 200);
  else window.addEventListener('load', function() { setTimeout(_syncDCMToEnergy, 500); });

  console.log('[' + APP_VTAG + '] Slider RT refresh + DCM energy sync ready');
})();

// === WBSlit center offset + slit blade pseudo-motors ===
(function(){
  state.wbCX=0; state.wbCY=0;

  var wbDev=null;
  if(typeof DEVICE_CONFIGS!=='undefined'){
    for(var i=0;i<DEVICE_CONFIGS.length;i++){
      if(DEVICE_CONFIGS[i].id==='wbslit'){wbDev=DEVICE_CONFIGS[i];break;}
    }
    if(wbDev&&!wbDev.axes.hcenter){
      wbDev.axes.hcenter={name:'H-Center',pvSuffix:'Hcen',unit:'mm',value:0,min:-5,max:5,step:0.01,resolution:0.001};
      wbDev.axes.vcenter={name:'V-Center',pvSuffix:'Vcen',unit:'mm',value:0,min:-5,max:5,step:0.01,resolution:0.001};
    }
    if(typeof buildMotorsFromConfig==='function')buildMotorsFromConfig();
  }

  window.slitBladesToGapCenter=function(devId){
    if(!MOTORS[devId])return null;
    var t=MOTORS[devId].top,b=MOTORS[devId].bottom,ib=MOTORS[devId].inboard,ob=MOTORS[devId].outboard;
    if(!t||!b||!ib||!ob)return null;
    return{hgap:ob.value-ib.value,vgap:t.value-b.value,
      hcenter:(ob.value+ib.value)/2,vcenter:(t.value+b.value)/2};
  };
  window.slitGapCenterToBlades=function(devId,hgap,vgap,hcen,vcen){
    if(!MOTORS[devId])return;
    var m=MOTORS[devId];
    if(m.top)m.top.value=vcen+vgap/2;
    if(m.bottom)m.bottom.value=vcen-vgap/2;
    if(m.outboard)m.outboard.value=hcen+hgap/2;
    if(m.inboard)m.inboard.value=hcen-hgap/2;
  };

  console.log('[' + APP_VTAG + '] WBSlit center + blade pseudo-motors ready');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof compSliderUpdate!=="undefined")globalThis.compSliderUpdate=compSliderUpdate;
if(typeof defaultSourceBW!=="undefined")globalThis.defaultSourceBW=defaultSourceBW;
if(typeof kbslitSliderUpdate!=="undefined")globalThis.kbslitSliderUpdate=kbslitSliderUpdate;
if(typeof refreshBeamOnly!=="undefined")globalThis.refreshBeamOnly=refreshBeamOnly;
if(typeof refreshInfoOnly!=="undefined")globalThis.refreshInfoOnly=refreshInfoOnly;
if(typeof slitBladesToGapCenter!=="undefined")globalThis.slitBladesToGapCenter=slitBladesToGapCenter;
if(typeof slitGapCenterToBlades!=="undefined")globalThis.slitGapCenterToBlades=slitGapCenterToBlades;
if(typeof ssaSliderUpdate!=="undefined")globalThis.ssaSliderUpdate=ssaSliderUpdate;
if(typeof updateEnergy!=="undefined")globalThis.updateEnergy=updateEnergy;
