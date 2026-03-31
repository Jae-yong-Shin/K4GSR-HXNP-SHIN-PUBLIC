'use strict';
// ===== alignment/01_signals.js -- MC Alignment Signal Helpers =====
// @module alignment/01_signals
// @exports ALIGN_CONFIG, mcBeamSizeAt, mcFluxAt, mcSignalAt
// Extracted from 14_v435_final.js (DDD Phase 5e)
// MC-based alignment signals: quick helpers for scan routines
// Dependencies: mcRayTrace (from optics/), beamAt, pos (from physics/)

// === Add XBPMs to DEVICE_CONFIGS (from 13_alignment.js) ===
(function() {
  var newBPMs = [
    {id:'xbpm_wb', name:'XBPM-WB', tp:'bpm', dp:28.6, optics:{fov:5e-3}},  // WB: low mag, ±5mm
    {id:'xbpm_m1', name:'XBPM-M1', tp:'bpm', dp:29.7, optics:{fov:5e-3}},  // WB: before M1, ±5mm
    {id:'xbpm_m2', name:'XBPM-M2', tp:'bpm', dp:35,   optics:{fov:5e-3}},  // M2 alignment: ±5mm (same as M1)
    {id:'xbpm_ssa',name:'XBPM-SSA',tp:'bpm', dp:59,   optics:{fov:1e-3}}   // Mono: after SSA, ±1mm
  ];
  newBPMs.forEach(function(b) {
    if (!state.positions[b.id]) {
      CD.push(b);
      state.positions[b.id] = b.dp;
    }
  });
  CD.sort(function(a,b) { return a.dp - b.dp; });
})();

// === Alignment config — user-adjustable parameters per step ===
var ALIGN_CONFIG = {
  wbslit:   { motor:'wbslit_hcen', detector:'xbpm_wb', range:[-5,5],   nPts:41, algo:'centroid',  label:'WB Slit H-Centering', unit:'mm', scanGap:null },
  wbslit_v: { motor:'wbslit_vcen',detector:'xbpm_wb', range:[-5,5],   nPts:41, algo:'centroid',  label:'WB Slit V-Centering', unit:'mm', scanGap:null },
  m1pitch:  { motor:'m1_pitch',    detector:'xbpm_m1', range:[-0.5,0.5], nPts:41, algo:'gaussian', label:'M1 Pitch Optimize',   unit:'mrad' },
  dcmDTheta2:   { motor:'dcm_dTheta2',    detector:'xbpm1',   range:[-3,3],   nPts:51, algo:'rocking',   label:'DCM Chi2 Rocking',    unit:'arcsec' },
  m2pitch:  { motor:'m2_pitch',    detector:'xbpm_m2', range:[-0.5,0.5], nPts:41, algo:'gaussian', label:'M2 Pitch Optimize',   unit:'mrad' },
  ssacenter:  { motor:'ssa_hcen',    detector:'xbpm_ssa',range:[-300,300], nPts:121, algo:'gaussian',  label:'SSA H-Centering',      unit:'μm', scanGap:null },
  ssacenter_v:{ motor:'ssa_vcen',    detector:'xbpm_ssa',range:[-300,300], nPts:121, algo:'gaussian',  label:'SSA V-Centering',      unit:'μm', scanGap:null },
  kbalign:  { motor:'kbv_pitch',   detector:'det',     range:[-0.3,0.3], nPts:31, algo:'gaussian', label:'KB Focus Alignment',  unit:'mrad', ssaGapH:100, ssaGapV:100 }
};

(function(){
// MC alignment signal: weight-based photon intensity at detector position
// Uses wMean * nSurvived to capture Guigay DCM weight attenuation.
// For mirror alignment, wMean ~ 1, so this ~ nSurvived (no change).
window.mcSignalAt=function(detDist,nR){
  nR=nR||((typeof MC_NRAYS!=='undefined')?MC_NRAYS:80000);
  try{
    var mc=mcRayTrace(detDist,nR);
    return (mc.wMean||1)*(mc.nSurvived||0);
  }catch(e){return 0;}
};

// MC flux ratio signal (normalized 0-1, weight-based)
window.mcFluxAt=function(detDist,nR){
  nR=nR||((typeof MC_NRAYS!=='undefined')?MC_NRAYS:80000);
  try{
    var mc=mcRayTrace(detDist,nR);
    return mc.nTotal>0?((mc.wMean||1)*mc.nSurvived/mc.nTotal):0;
  }catch(e){return 0;}
};

// MC beam size at position (returns {h,v} in um)
window.mcBeamSizeAt=function(detDist,nR){
  nR=nR||((typeof MC_NRAYS!=='undefined')?MC_NRAYS:80000);
  try{
    var mc=mcRayTrace(detDist,nR);
    return{h:mc.fwhmH*1e6,v:mc.fwhmV*1e6};
  }catch(e){return{h:999,v:999};}
};

console.log('[alignment/01_signals] MC alignment signal helpers ready');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof ALIGN_CONFIG!=="undefined")globalThis.ALIGN_CONFIG=ALIGN_CONFIG;
if(typeof mcBeamSizeAt!=="undefined")globalThis.mcBeamSizeAt=mcBeamSizeAt;
if(typeof mcFluxAt!=="undefined")globalThis.mcFluxAt=mcFluxAt;
if(typeof mcSignalAt!=="undefined")globalThis.mcSignalAt=mcSignalAt;
