/**
 * _diag_mc_divergence.js
 * Extract MC ray tracer divergence at INTERMEDIATE positions vs S4.
 * Identifies WHERE the divergence mismatch develops (source? M1? DCM? M2? SSA?).
 *
 * Usage:  node _diag_mc_divergence.js
 */
'use strict';

// ===== Node.js stubs for browser globals =====
var window = global;
global.window = window;
global.document = {
  getElementById: function() { return null; },
  querySelector: function() { return null; },
  querySelectorAll: function() { return []; },
  createElement: function(tag) {
    return {
      tagName: tag, style: {}, classList: { add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; } },
      appendChild: function(){}, removeChild: function(){}, addEventListener: function(){}, setAttribute: function(){}, getAttribute: function(){ return null; },
      getContext: function() {
        return { fillRect: function(){}, clearRect: function(){}, beginPath: function(){}, moveTo: function(){}, lineTo: function(){}, stroke: function(){},
          fillText: function(){}, measureText: function(){ return {width:0}; }, arc: function(){}, fill: function(){}, save: function(){}, restore: function(){},
          scale: function(){}, translate: function(){}, createLinearGradient: function(){ return { addColorStop: function(){} }; },
          drawImage: function(){}, getImageData: function(){ return {data: new Uint8ClampedArray(4)}; },
          putImageData: function(){}, createImageData: function(w,h){ return {data: new Uint8ClampedArray(w*h*4), width:w, height:h}; }
        };
      },
      width: 100, height: 100, clientWidth: 100, clientHeight: 100,
      innerHTML: '', textContent: '', value: '', children: [], childNodes: [], parentNode: null, parentElement: null
    };
  },
  body: { appendChild: function(){}, style: {} },
  head: { appendChild: function(){} },
  createTextNode: function(){ return {}; },
  documentElement: { style: {} }
};
global.location = { search: '', href: '', hostname: 'localhost' };
try { global.navigator = { userAgent: 'node' }; } catch(e) {}
global.localStorage = { getItem: function(){ return null; }, setItem: function(){} };
global.sessionStorage = { getItem: function(){ return null; }, setItem: function(){} };
global.requestAnimationFrame = function(cb) { setTimeout(cb, 0); };
global.cancelAnimationFrame = function(){};
global.getComputedStyle = function(){ return { getPropertyValue: function(){ return ''; } }; };
global.alert = function(){};
global.setTimeout = global.setTimeout;
global.clearTimeout = global.clearTimeout;
global.URLSearchParams = function(){ this.get = function(){ return null; }; };
global.WebSocket = function(){ this.send = function(){}; this.close = function(){}; this.addEventListener = function(){}; };
global.fetch = function(){ return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({}); } }); };
global.Image = function(){ this.onload = null; this.src = ''; };
global.Audio = function(){ this.play = function(){}; };
global.speechSynthesis = { speak: function(){}, cancel: function(){} };
global.SpeechSynthesisUtterance = function(){};

var _origLog = console.log;
var _logEnabled = false;
console.log = function() { if (_logEnabled) _origLog.apply(console, arguments); };
console.warn = function() {};

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var baseDir = __dirname;

function loadJS(relPath) {
  var code = fs.readFileSync(path.join(baseDir, relPath), 'utf8');
  code = code.replace(/^'use strict';\s*/m, '');
  vm.runInThisContext(code, { filename: relPath });
}

window.KB_PARAMS = {
  kbv: { type:'elliptical', len:0.300, wid:0.030, thick:0.020, rough:4.0 },
  kbh: { type:'elliptical', len:0.100, wid:0.030, thick:0.020, rough:4.0 }
};

_origLog('Loading JS modules...');
loadJS('js/shared/01_constants.js');
loadJS('js/optics/00_optconst_tables.js');
loadJS('js/optics/01_undulator.js');
loadJS('js/optics/02_crystal.js');
loadJS('js/optics/02b_crystal_psi_tables.js');
loadJS('js/optics/03_reflectivity.js');
loadJS('js/control/01_motors.js');
loadJS('js/optics/04_source.js');
loadJS('js/raytrace/01_mc_engine.js');
loadJS('js/raytrace/03_beam_profile.js');
_origLog('All modules loaded.\n');

// Force non-WB mode for clean intermediate diagnostics
global._forceNonWB = true;
// Disable SSA diffraction (hybrid + fallback sinc^2) to match S4 geometric-only SSA
global._noSSADiffraction = true;
// Disable mirror reflectivity to match S4 f_reflec=0
global._noMirrorReflectivity = true;

// ===== S4 reference from s4_intermediate.json =====
var s4Data = JSON.parse(fs.readFileSync(path.join(baseDir, 'paper/validation/data/s4_intermediate.json'), 'utf8'));

// ===== Intermediate positions to trace =====
// MC positions chosen to match S4 intermediate checkpoints
// MC element positions: m1=29, dcm=30.4, xbpm1=31.2, m2=32
var POSITIONS = [
  { label: 'source',    td: 0.5 },    // near source (before any optics)
  { label: 'after_M1',  td: 30.0 },   // after M1(29) but BEFORE DCM(30.4)
  { label: 'after_DCM', td: 31.0 },   // after DCM(30.4) but before M2(32)
  { label: 'after_M2',  td: 33.0 },   // after M2(32)
  { label: 'at_SSA',    td: 58.0 }    // at SSA(58)
];

var CONDITIONS = [
  { name: '5keV_ssa50',  energy: 5.0,  ssaH: 50,  ssaV: 50 }
];

var NRAYS = 200000;
var NRUNS = 3;

_origLog('=============================================================');
_origLog('  MC Intermediate Divergence vs S4 (200K rays x 3 runs)');
_origLog('  Mirror reflectivity: DISABLED (_noMirrorReflectivity=true)');
_origLog('=============================================================\n');

_logEnabled = false;

CONDITIONS.forEach(function(cond) {
  state.energy = cond.energy;
  state.ssaH = cond.ssaH;
  state.ssaV = cond.ssaV;
  state.crystal = '111';
  state.m1pitch = 3.0;
  state.m2pitch = 3.0;
  state.kbvpitch = 3.0;
  state.kbhpitch = 3.0;

  var best = selectBest(cond.energy);
  if (best) { state.gap = best.gap; state.harmonic = best.n; }
  autoStripeForEnergy(cond.energy);
  var n_harm = state.harmonic || 1;
  // Use monochromatic source (like S4) for fair comparison
  state.sourceBW_eV = 0;
  // Open WB slit wide to match S4 (which has no WB slit)
  state.wbH = 100; state.wbV = 100;  // mm, effectively infinite
  try { MOTORS.m1.pitch.value = 3.0; MOTORS.m2.pitch.value = 3.0; } catch(e){}
  try { MOTORS.kbv.pitch.value = 3.0; MOTORS.kbh.pitch.value = 3.0; } catch(e){}
  var thB = braggAngle(cond.energy);
  try { MOTORS.dcm.theta.value = thB * 180 / Math.PI; } catch(e){}

  _origLog('=== ' + cond.name + ' (n=' + n_harm + ', BW=' + state.sourceBW_eV.toFixed(1) + 'eV) ===\n');
  _origLog('  Source params: Sxp=' + (photonSrc(cond.energy).Sxp*1e6).toFixed(2) + ' urad, Syp=' + (photonSrc(cond.energy).Syp*1e6).toFixed(2) + ' urad\n');

  // Header - compare weighted vs unweighted vs S4 (with _swap_xz correction)
  _origLog('  Position      |  MC(wt)  MC(uw)    S4    wt_dev  uw_dev |  MC(wt)  MC(uw)    S4    wt_dev  uw_dev |  n_surv');
  _origLog('                |        phys H divergence (urad)          |        phys V divergence (urad)          |');
  _origLog('  --------------|------------------------------------------|------------------------------------------|--------');

  POSITIONS.forEach(function(p) {
    var sumDivH = 0, sumDivV = 0, sumUDivH = 0, sumUDivV = 0, sumN = 0;
    var lastWMin=0, lastWMax=0, lastWMean=0;
    for (var r = 0; r < NRUNS; r++) {
      var mc = mcRayTrace(p.td, NRAYS);
      sumDivH += mc.sigDivH;
      sumDivV += mc.sigDivV;
      sumUDivH += mc.usigDivH;
      sumUDivV += mc.usigDivV;
      sumN += mc.nSurvived;
      lastWMin = mc.wMin; lastWMax = mc.wMax; lastWMean = mc.wMean;
    }
    var mcDivH = sumDivH / NRUNS;
    var mcDivV = sumDivV / NRUNS;
    var mcUDivH = sumUDivH / NRUNS;
    var mcUDivV = sumUDivV / NRUNS;
    var mcN = Math.round(sumN / NRUNS);

    // Weight distribution diagnostic (last run)
    var wMin=1e30,wMax=-1e30,wSum=0,wCnt=0;
    // Note: mc object from last run still has rays data in closure, use sigDivH instead
    // We need to check weight distribution separately

    var s4 = s4Data[cond.name];
    var s4pos = s4 ? s4[p.label] : null;
    // _swap_xz correction: at intermediate positions (after_M1..after_M2),
    // S4 sig_xp = physical V, sig_zp = physical H (swapped!)
    // At source and at_SSA, swap is not active.
    var isSwapped = (p.label === 'after_M1' || p.label === 'after_DCM' || p.label === 'after_M2');
    var s4DivH = s4pos ? (isSwapped ? s4pos.sig_zp : s4pos.sig_xp) : 0;
    var s4DivV = s4pos ? (isSwapped ? s4pos.sig_xp : s4pos.sig_zp) : 0;
    var s4N = s4pos ? s4pos.n : 0;

    _origLog('  ' + p.label.padEnd(14) + '|'
      + (mcDivH*1e6).toFixed(2).padStart(7)
      + (mcUDivH*1e6).toFixed(2).padStart(7)
      + (s4DivH*1e6).toFixed(2).padStart(7)
      + pctDev(mcDivH, s4DivH).padStart(8)
      + pctDev(mcUDivH, s4DivH).padStart(8) + ' |'
      + (mcDivV*1e6).toFixed(2).padStart(7)
      + (mcUDivV*1e6).toFixed(2).padStart(7)
      + (s4DivV*1e6).toFixed(2).padStart(7)
      + pctDev(mcDivV, s4DivV).padStart(8)
      + pctDev(mcUDivV, s4DivV).padStart(8) + ' |'
      + String(mcN).padStart(7)
      + '  w=[' + lastWMin.toFixed(4) + ',' + lastWMean.toFixed(4) + ',' + lastWMax.toFixed(4) + ']');
  });
  _origLog('');
});

// Also run 10keV and 20keV for at_SSA only (quick summary)
_origLog('\n=== Quick SSA summary for all energies (SSA diffraction OFF) ===\n');
_origLog('  Energy        |  MC(wt)  MC(uw)    S4    wt_dev  uw_dev |  MC(wt)  MC(uw)    S4    wt_dev  uw_dev |  n_surv');
_origLog('                |           sig_xp (urad)                  |           sig_zp (urad)                  |');
_origLog('  --------------|------------------------------------------|------------------------------------------|--------');

[
  { name: '5keV_ssa50',  energy: 5.0,  ssaH: 50,  ssaV: 50 },
  { name: '10keV_ssa50', energy: 10.0, ssaH: 50,  ssaV: 50 },
  { name: '20keV_ssa50', energy: 20.0, ssaH: 50,  ssaV: 50 }
].forEach(function(cond) {
  state.energy = cond.energy;
  state.ssaH = cond.ssaH;
  state.ssaV = cond.ssaV;
  state.crystal = '111';
  state.m1pitch = 3.0; state.m2pitch = 3.0;
  state.kbvpitch = 3.0; state.kbhpitch = 3.0;
  var best = selectBest(cond.energy);
  if (best) { state.gap = best.gap; state.harmonic = best.n; }
  autoStripeForEnergy(cond.energy);
  var n_harm = state.harmonic || 1;
  state.sourceBW_eV = 0;  // monochromatic for fair S4 comparison
  state.wbH = 100; state.wbV = 100;  // mm, wide open to match S4
  try { MOTORS.m1.pitch.value = 3.0; MOTORS.m2.pitch.value = 3.0; } catch(e){}
  try { MOTORS.kbv.pitch.value = 3.0; MOTORS.kbh.pitch.value = 3.0; } catch(e){}
  try { MOTORS.dcm.theta.value = braggAngle(cond.energy) * 180 / Math.PI; } catch(e){}

  var sumDivH = 0, sumDivV = 0, sumUDivH = 0, sumUDivV = 0, sumN = 0;
  for (var r = 0; r < NRUNS; r++) {
    var mc = mcRayTrace(58.0, NRAYS);
    sumDivH += mc.sigDivH;
    sumDivV += mc.sigDivV;
    sumUDivH += mc.usigDivH;
    sumUDivV += mc.usigDivV;
    sumN += mc.nSurvived;
  }
  var mcDivH = sumDivH / NRUNS;
  var mcDivV = sumDivV / NRUNS;
  var mcUDivH = sumUDivH / NRUNS;
  var mcUDivV = sumUDivV / NRUNS;
  var mcN = Math.round(sumN / NRUNS);

  var s4 = s4Data[cond.name];
  var s4DivH = s4 && s4.at_SSA ? s4.at_SSA.sig_xp : 0;
  var s4DivV = s4 && s4.at_SSA ? s4.at_SSA.sig_zp : 0;
  var s4N = s4 && s4.at_SSA ? s4.at_SSA.n : 0;

  _origLog('  ' + cond.name.padEnd(14) + '|'
    + (mcDivH*1e6).toFixed(2).padStart(7) + (mcUDivH*1e6).toFixed(2).padStart(7)
    + (s4DivH*1e6).toFixed(2).padStart(7)
    + pctDev(mcDivH, s4DivH).padStart(8) + pctDev(mcUDivH, s4DivH).padStart(8) + ' |'
    + (mcDivV*1e6).toFixed(2).padStart(7) + (mcUDivV*1e6).toFixed(2).padStart(7)
    + (s4DivV*1e6).toFixed(2).padStart(7)
    + pctDev(mcDivV, s4DivV).padStart(8) + pctDev(mcUDivV, s4DivV).padStart(8) + ' |'
    + String(mcN).padStart(7));
});

function pad(n, w) { var s = String(n); while(s.length < w) s = ' ' + s; return s; }
function pctDev(mc, s4) {
  if (s4 === 0) return '  N/A';
  var d = (mc - s4) / s4 * 100;
  return (d >= 0 ? '+' : '') + d.toFixed(1) + '%';
}
