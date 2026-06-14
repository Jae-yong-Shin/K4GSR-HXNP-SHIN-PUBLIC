'use strict';
// ===== shared/01_constants.js ??Ring, IVU, Crystal, Material Constants + State =====
// @module shared/01_constants
// @exports APP_VERSION, APP_VTAG
// @exports E_RING, I_RING, EMIT_X, EMIT_Y, BETA_X, BETA_Y, E_SPREAD, GAMMA_E
// @exports SIG_EX, SIG_EXP, SIG_EY, SIG_EYP, N_PERIODS, LAMBDA_U, LAMBDA_U_M, L_UND
// @exports HC, FIXED_EXIT, D_SI, R_E_A, NA, V_SI, RH, PT
// @exports state, CD, pos, gaussRand, xbpmZone, recalcElectronBeam, log
// Extracted from 02_physics.js (DDD Phase 2)

// ===== Application version (single source of truth) =====
// Bump per CHANGELOG.md / Versioning Policy. ALL log/console output that needs to
// mention the app version must reference APP_VERSION / APP_VTAG here, never a
// hard-coded literal. preflight_deploy.py enforces this (no "v4.NN"/"V4.NN" literals
// allowed under js/ outside this file). MINOR+ bump procedure (CLAUDE.md "踰꾩쟾 愿由?):
// change this line, rename bundle pair, run preflight, commit, deploy.
var APP_VERSION = '4.38.11';
var APP_VTAG = 'v' + APP_VERSION;  // for log prefixes like '[v4.37.4]'

// ===== Server Connection Config =====
// Auto-detect: when loaded from server, use same host. Override with ?server=xxx.
// Local file (file://) falls back to localhost.
var _qp = (typeof location !== 'undefined' && location.search) ? new URLSearchParams(location.search) : null;
var _autoHost = (typeof location !== 'undefined' && location.hostname) ? location.hostname : 'localhost';
var SERVER_HOST = (_qp && _qp.get('server')) || _autoHost;
var _autoPort = (typeof location !== 'undefined' && location.port) ? parseInt(location.port) : 8001;
var SERVER_WS_PORT = (_qp && _qp.get('wsport')) ? parseInt(_qp.get('wsport')) : (_autoPort || 8001);

// Ring & IVU constants
var E_RING=4.0, I_RING=400, I_RING_A=0.4, GAMMA_E=E_RING*1e3/0.511;
var EMIT_X=62e-12, EMIT_Y=6.2e-12, BETA_X=6.334, BETA_Y=2.841, E_SPREAD=1.20e-3;
var SIG_EX=Math.sqrt(EMIT_X*BETA_X), SIG_EXP=Math.sqrt(EMIT_X/BETA_X);
var SIG_EY=Math.sqrt(EMIT_Y*BETA_Y), SIG_EYP=Math.sqrt(EMIT_Y/BETA_Y);
// Recompute derived e-beam values from current ring params: I_RING_A=I_RING/1000, GAMMA_E, and beam sigmas sqrt(EMIT*BETA) / sqrt(EMIT/BETA).
function recalcElectronBeam(){
  I_RING_A=I_RING/1000; GAMMA_E=E_RING*1e3/0.511;
  SIG_EX=Math.sqrt(EMIT_X*BETA_X); SIG_EXP=Math.sqrt(EMIT_X/BETA_X);
  SIG_EY=Math.sqrt(EMIT_Y*BETA_Y); SIG_EYP=Math.sqrt(EMIT_Y/BETA_Y);
}
// Parse a value, assign it to one ring param (EMIT in pm, E_SPREAD in 1e-4), recalc, refresh the sigma/gamma readout, then re-run undulator/energy/optics.
function updateEbeamParam(param,val){
  val=parseFloat(val);if(isNaN(val))return;
  if(param==='E_RING'){E_RING=val;}
  else if(param==='I_RING'){I_RING=val;}
  else if(param==='EMIT_X'){EMIT_X=val*1e-12;}
  else if(param==='EMIT_Y'){EMIT_Y=val*1e-12;}
  else if(param==='BETA_X'){BETA_X=val;}
  else if(param==='BETA_Y'){BETA_Y=val;}
  else if(param==='E_SPREAD'){E_SPREAD=val*1e-4;}
  recalcElectronBeam();
  // Update display
  var d=document.getElementById('vEbeamInfo');
  if(d) d.innerHTML='\u03c3<sub>x</sub>='+(SIG_EX*1e6).toFixed(1)+'\u00b5m, \u03c3<sub>y</sub>='+(SIG_EY*1e6).toFixed(2)+'\u00b5m, \u03b3='+GAMMA_E.toFixed(0);
  updateUnd(state.gap); updateEnergy(state.energy); updateOptics();
}
var LAMBDA_U=24, LAMBDA_U_M=0.024, N_PERIODS=123, L_UND=N_PERIODS*LAMBDA_U_M;
var HC=12.3984;
var FIXED_EXIT=12.0; // mm, XDS Oxford HDCM-HCCM horizontal fixed-exit offset
// Si crystal d-spacings in Angstrom by Miller index for DCM Bragg: '111'=3.13560, '311'=1.63751.
var D_SI={'111':3.13560,'311':1.63751};
var HALB_A=3.3, HALB_B=-5.08, HALB_C=1.54;
var R_E_A=2.8179e-5, NA=6.022e23, V_SI=160.18;
// Rhodium mirror-coating constants {Z:45, A:102.9, rho:12.41e6} fed to mirrorR() for M1/M2 reflectivity vs energy and pitch.
var RH={Z:45,A:102.9,rho:12.41e6};
// Platinum mirror-coating constants {Z:78, A:195.08, rho:21.45e6} fed to mirrorR() for KB-V/KB-H reflectivity vs energy and pitch.
var PT={Z:78,A:195.08,rho:21.45e6};

// Component definitions: 16 elements
// optics: beam physics metadata for generic SVG beam path
// svg: rendering hints for generic SVG layout
var CD=[
  {id:'ivu',   name:'IVU24',      tp:'source',  dp:0,
    optics:{beamState:'white'}, svg:{showDist:true}},
  {id:'fmask', name:'FxMask',     tp:'mask',    dp:17,
    svg:{showDist:true}},
  {id:'mmask', name:'MvMask',     tp:'mask',    dp:22,
    svg:{}},
  {id:'wbslit',name:'WBSlit',     tp:'slit',    dp:27.8,
    optics:{aperture:true}, svg:{showDist:true}},
  {id:'atten', name:'Attenuator', tp:'atten',   dp:28.3,
    svg:{showDist:true}},
  {id:'m1',    name:'M1',         tp:'hmirror', dp:29,
    optics:{deflView:'top',pitchKey:'m1pitch',deflFactor:2},
    svg:{showDist:true}},
  {id:'dcm',   name:'DCM',        tp:'dcm',     dp:30.4,
    optics:{monochromatize:true,fixedExit:true,c1OffsetPx:-8,deflView:'top'},
    svg:{showDist:true}},
  {id:'m2',    name:'M2',         tp:'hmirror', dp:32,
    optics:{deflView:'top',pitchKey:'m2pitch',deflFactor:-2},
    svg:{showDist:true}},
  {id:'xbpm1', name:'XBPM1',      tp:'bpm', bpmType:'generic', dp:31.2,
    optics:{fov:1e-3}, svg:{}},
  {id:'xbpm2', name:'XBPM2',      tp:'bpm', bpmType:'dbpm',    dp:57,
    optics:{fov:1e-3}, svg:{}},
  {id:'ssa',   name:'SSA',        tp:'slit',    dp:58,
    optics:{aperture:true}, svg:{showDist:true,colorOverride:'var(--pr)'}},
  {id:'xbpm3', name:'XBPM3',      tp:'bpm', bpmType:'generic', dp:140,
    optics:{fov:1e-3}, svg:{}},
  {id:'kbslit',name:'KB Slit',    tp:'slit',    dp:149.19,
    optics:{aperture:true}, svg:{showDist:true}},
  {id:'kbv',   name:'KB-V',       tp:'kbv',     dp:149.69,
    optics:{focus:true,focusPlane:'v',deflView:'side',pitchKey:'kbvpitch',deflFactor:2}, svg:{showDist:true}},
  {id:'kbh',   name:'KB-H',       tp:'kbh',     dp:149.9,
    optics:{focus:true,focusPlane:'h',deflView:'top',pitchKey:'kbhpitch',deflFactor:2}, svg:{showDist:true}},
  {id:'ic1',   name:'IC1',        tp:'ic',      dp:149.45,
    svg:{}},
  {id:'sample',name:'Sample',     tp:'sample',  dp:150,
    svg:{showDist:true}},
  {id:'det',   name:'Detector',   tp:'det',     dp:154.5,
    svg:{showDist:true}}
];

// State
var state={mode:'virtual',gap:7.0,energy:10.0,targetEnergy:10.0,crystal:'111',
  wbH:1.2,wbV:1.2,m1pitch:2.5,m2pitch:2.5,kbvpitch:3.0,kbhpitch:3.0,ssaH:50,ssaV:50,kbslitH:5000,kbslitV:5000,
  focusMode:'kb',visualSx:{},
  // IC1 ion chamber (A3): gas fill, active length, pressure, and the air
  // path the beam crosses BEFORE the chamber entrance (KB exit window ->
  // IC1) and AFTER it (IC1 -> sample). Air attenuation matters: the
  // current is generated from the flux that REACHES the chamber.
  ic1Gas:'N2',ic1LenCm:10,ic1PressAtm:1.0,ic1AirBeforeCm:5,ic1AirAfterCm:2,
  scanning:false,scanData:[],map2D:null,harmonic:1,positions:{},epicsConnected:false,
  attenFilters:[{material:'None',thickness:0},{material:'None',thickness:0},{material:'None',thickness:0},{material:'None',thickness:0}]};
CD.forEach(function(c){state.positions[c.id]=c.dp;});
// Return the longitudinal position (m) of a device id from state.positions, the user-editable distance map seeded from CD.
function pos(id){return state.positions[id];}

// Box-Muller Gaussian random number generator (shared utility)
// Used by MC ray tracing, detector simulation, noise models
function gaussRand() {
  var u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// === Zone auto-detection: WB if upstream of DCM, else MONO/SSA/KB ===
function xbpmZone(id) {
  var p = pos(id);
  if (p === undefined) return '?';
  var dcmP = pos('dcm');
  if (dcmP !== undefined && p < dcmP) return 'WB';
  var ssaP = pos('ssa');
  if (ssaP !== undefined && p < ssaP) return 'MONO';
  var kbvP = pos('kbv');
  if (kbvP !== undefined && p < kbvP) return 'SSA';
  return 'KB';
}

// Build XBPM list dynamically from CD (all tp:'bpm' entries).
// Positions come from state.positions (user-editable like any device).
// Zone is auto-detected from DCM position ??no hardcoding.
window.getXbpmList = function() {
  var list = [];
  for (var i = 0; i < CD.length; i++) {
    if (CD[i].tp === 'bpm') {
      list.push({id:CD[i].id, name:CD[i].name, dist:pos(CD[i].id), zone:xbpmZone(CD[i].id), bpmType:CD[i].bpmType || 'generic'});
    }
  }
  list.sort(function(a,b){return a.dist - b.dist;});
  return list;
};

// Materials database
var MATERIALS={
  Fe:{Z:26,K:7112,L3:706,lines:{Ka:6404,Kb:7058},xrd:[44.67,65.02,82.33]},
  Cu:{Z:29,K:8979,L3:932,lines:{Ka:8048,Kb:8905},xrd:[43.30,50.43,74.13]},
  Ni:{Z:28,K:8333,L3:855,lines:{Ka:7478,Kb:8265},xrd:[44.51,51.85,76.37]},
  Ti:{Z:22,K:4966,L3:454,lines:{Ka:4510,Kb:4932},xrd:[35.09,38.42,40.17]},
  Au:{Z:79,K:80725,L3:11919,lines:{La:9713,Lb:11443},xrd:[38.19,44.39,64.58]},
  Pt:{Z:78,K:78395,L3:11564,lines:{La:9442,Lb:11071},xrd:[39.76,46.24,67.45]},
  Si:{Z:14,K:1839,L3:99,lines:{Ka:1740},xrd:[28.44,47.30,56.12,69.13,76.38]},
  SrTiO3:{Z:38,K:16105,L3:1940,lines:{TiKa:4510,SrKa:14165},xrd:[22.75,32.40,39.95,46.47,52.35]}
};

// === Global log utility (must load before all other modules) ===
function log(lv, msg) {
  var b = document.getElementById('logBox');
  if (!b) return;
  var t = new Date().toLocaleTimeString('en-US', { hour12: false });
  b.innerHTML = '<div><span class="ltime">' + t + '</span> <span class="l' + lv +
    '">[' + lv.toUpperCase() + ']</span> ' + msg + '</div>' + b.innerHTML;
  while (b.children.length > 80) b.removeChild(b.lastChild);
}

// Empty the on-screen log panel by clearing the #logBox element's innerHTML; wired to the LOG panel Clr button.
function clearLog() {
  var el = document.getElementById('logBox');
  if (el) el.innerHTML = '';
}

// Helper: get motor value or fallback
function getMotorVal(group,motorId,fallback){
  if(typeof MOTORS==='undefined'||!MOTORS[group])return fallback;
  var grp=MOTORS[group];
  var motors=Array.isArray(grp)?grp:Object.values(grp).filter(function(x){return x&&x.id;});
  var m=null;for(var i=0;i<motors.length;i++){if(motors[i].id===motorId){m=motors[i];break;}}
  return m?m.value:fallback;
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof A!=="undefined")globalThis.A=A;
if(typeof BETA_X!=="undefined")globalThis.BETA_X=BETA_X;
if(typeof BETA_Y!=="undefined")globalThis.BETA_Y=BETA_Y;
if(typeof CD!=="undefined")globalThis.CD=CD;
if(typeof D_SI!=="undefined")globalThis.D_SI=D_SI;
if(typeof EMIT_X!=="undefined")globalThis.EMIT_X=EMIT_X;
if(typeof EMIT_Y!=="undefined")globalThis.EMIT_Y=EMIT_Y;
if(typeof E_RING!=="undefined")globalThis.E_RING=E_RING;
if(typeof E_SPREAD!=="undefined")globalThis.E_SPREAD=E_SPREAD;
if(typeof FIXED_EXIT!=="undefined")globalThis.FIXED_EXIT=FIXED_EXIT;
if(typeof GAMMA_E!=="undefined")globalThis.GAMMA_E=GAMMA_E;
if(typeof HALB_A!=="undefined")globalThis.HALB_A=HALB_A;
if(typeof HALB_B!=="undefined")globalThis.HALB_B=HALB_B;
if(typeof HALB_C!=="undefined")globalThis.HALB_C=HALB_C;
if(typeof HC!=="undefined")globalThis.HC=HC;
if(typeof I_RING!=="undefined")globalThis.I_RING=I_RING;
if(typeof I_RING_A!=="undefined")globalThis.I_RING_A=I_RING_A;
if(typeof LAMBDA_U!=="undefined")globalThis.LAMBDA_U=LAMBDA_U;
if(typeof LAMBDA_U_M!=="undefined")globalThis.LAMBDA_U_M=LAMBDA_U_M;
if(typeof L_UND!=="undefined")globalThis.L_UND=L_UND;
if(typeof MATERIALS!=="undefined")globalThis.MATERIALS=MATERIALS;
if(typeof NA!=="undefined")globalThis.NA=NA;
if(typeof N_PERIODS!=="undefined")globalThis.N_PERIODS=N_PERIODS;
if(typeof PT!=="undefined")globalThis.PT=PT;
if(typeof RH!=="undefined")globalThis.RH=RH;
if(typeof R_E_A!=="undefined")globalThis.R_E_A=R_E_A;
if(typeof SERVER_HOST!=="undefined")globalThis.SERVER_HOST=SERVER_HOST;
if(typeof SERVER_WS_PORT!=="undefined")globalThis.SERVER_WS_PORT=SERVER_WS_PORT;
if(typeof SIG_EX!=="undefined")globalThis.SIG_EX=SIG_EX;
if(typeof SIG_EXP!=="undefined")globalThis.SIG_EXP=SIG_EXP;
if(typeof SIG_EY!=="undefined")globalThis.SIG_EY=SIG_EY;
if(typeof SIG_EYP!=="undefined")globalThis.SIG_EYP=SIG_EYP;
if(typeof V_SI!=="undefined")globalThis.V_SI=V_SI;
if(typeof XDS!=="undefined")globalThis.XDS=XDS;
if(typeof clearLog!=="undefined")globalThis.clearLog=clearLog;
if(typeof crystal!=="undefined")globalThis.crystal=crystal;
if(typeof energy!=="undefined")globalThis.energy=energy;
if(typeof gap!=="undefined")globalThis.gap=gap;
if(typeof gaussRand!=="undefined")globalThis.gaussRand=gaussRand;
if(typeof getMotorVal!=="undefined")globalThis.getMotorVal=getMotorVal;
if(typeof getXbpmList!=="undefined")globalThis.getXbpmList=getXbpmList;
if(typeof log!=="undefined")globalThis.log=log;
if(typeof pos!=="undefined")globalThis.pos=pos;
if(typeof recalcElectronBeam!=="undefined")globalThis.recalcElectronBeam=recalcElectronBeam;
if(typeof rho!=="undefined")globalThis.rho=rho;
if(typeof state!=="undefined")globalThis.state=state;
if(typeof targetEnergy!=="undefined")globalThis.targetEnergy=targetEnergy;
if(typeof updateEbeamParam!=="undefined")globalThis.updateEbeamParam=updateEbeamParam;
if(typeof xbpmZone!=="undefined")globalThis.xbpmZone=xbpmZone;
if(typeof _autoHost!=="undefined")globalThis._autoHost=_autoHost;
if(typeof _autoPort!=="undefined")globalThis._autoPort=_autoPort;
if(typeof _qp!=="undefined")globalThis._qp=_qp;
