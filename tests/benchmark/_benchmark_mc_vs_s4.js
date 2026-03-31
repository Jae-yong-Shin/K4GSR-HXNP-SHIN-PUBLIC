/**
 * _benchmark_mc_vs_s4.js
 * Full MC ray tracer benchmark: run mcRayTrace from Node.js for 5 conditions
 * and compare FWHM with Shadow4 reference.
 *
 * Usage:
 *   node _benchmark_mc_vs_s4.js
 *
 * Loads all required JS modules in dependency order with minimal DOM stubs.
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
      tagName: tag,
      style: {},
      classList: { add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; } },
      appendChild: function(){},
      removeChild: function(){},
      addEventListener: function(){},
      setAttribute: function(){},
      getAttribute: function(){ return null; },
      getContext: function() {
        return {
          fillRect: function(){}, clearRect: function(){}, beginPath: function(){},
          moveTo: function(){}, lineTo: function(){}, stroke: function(){},
          fillText: function(){}, measureText: function(){ return {width:0}; },
          arc: function(){}, fill: function(){}, save: function(){}, restore: function(){},
          scale: function(){}, translate: function(){}, createLinearGradient: function(){
            return { addColorStop: function(){} };
          },
          drawImage: function(){}, getImageData: function(){ return {data: new Uint8ClampedArray(4)}; },
          putImageData: function(){}, createImageData: function(w,h){ return {data: new Uint8ClampedArray(w*h*4), width:w, height:h}; }
        };
      },
      width: 100, height: 100, clientWidth: 100, clientHeight: 100,
      innerHTML: '', textContent: '', value: '',
      children: [], childNodes: [],
      parentNode: null, parentElement: null
    };
  },
  body: { appendChild: function(){}, style: {} },
  head: { appendChild: function(){} },
  createTextNode: function(){ return {}; },
  documentElement: { style: {} }
};
global.location = { search: '', href: '', hostname: 'localhost' };
try { global.navigator = { userAgent: 'node' }; } catch(e) { /* read-only in Node 22+ */ }
global.localStorage = { getItem: function(){ return null; }, setItem: function(){} };
global.sessionStorage = { getItem: function(){ return null; }, setItem: function(){} };
global.requestAnimationFrame = function(cb) { setTimeout(cb, 0); };
global.cancelAnimationFrame = function(){};
global.getComputedStyle = function(){ return { getPropertyValue: function(){ return ''; } }; };
global.alert = function(){};
global.console = global.console || { log: function(){}, warn: function(){}, error: function(){} };
global.setTimeout = global.setTimeout;
global.clearTimeout = global.clearTimeout;
global.URLSearchParams = function(){ this.get = function(){ return null; }; };
global.WebSocket = function(){ this.send = function(){}; this.close = function(){}; this.addEventListener = function(){}; };
global.fetch = function(){ return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({}); } }); };
global.Image = function(){ this.onload = null; this.src = ''; };
global.Audio = function(){ this.play = function(){}; };
global.speechSynthesis = { speak: function(){}, cancel: function(){} };
global.SpeechSynthesisUtterance = function(){};

// Suppress log noise
var _origLog = console.log;
var _logEnabled = false;
console.log = function() { if (_logEnabled) _origLog.apply(console, arguments); };
console.warn = function() {};

// ===== Load JS modules in dependency order =====
var fs = require('fs');
var path = require('path');
var vm = require('vm');
var baseDir = __dirname;

function loadJS(relPath) {
  var fullPath = path.join(baseDir, relPath);
  var code = fs.readFileSync(fullPath, 'utf8');
  // Remove 'use strict' to avoid issues with eval in global scope
  code = code.replace(/^'use strict';\s*/m, '');
  try {
    // Use vm.runInThisContext to execute in global scope (var/function declarations become global)
    vm.runInThisContext(code, { filename: relPath });
  } catch(e) {
    _origLog('[LOAD ERROR] ' + relPath + ': ' + e.message);
    throw e;
  }
}

// Pre-define KB_PARAMS before loading MC engine (normally from alignment/03_runners.js)
window.KB_PARAMS = {
  kbv: { type:'elliptical', len:0.300, wid:0.030, thick:0.020, rough:4.0 },
  kbh: { type:'elliptical', len:0.100, wid:0.030, thick:0.020, rough:4.0 }
};

_origLog('Loading JS modules...');

// 1. Core constants and state
loadJS('js/shared/01_constants.js');

// 2. Optical constants tables (DABAX)
loadJS('js/optics/00_optconst_tables.js');

// 3. Undulator physics
loadJS('js/optics/01_undulator.js');

// 4. Crystal physics (Bragg, Darwin)
loadJS('js/optics/02_crystal.js');

// 5. Reflectivity
loadJS('js/optics/03_reflectivity.js');

// 6. Motors (DEVICE_CONFIGS + MOTORS)
loadJS('js/control/01_motors.js');

// 7. Source
loadJS('js/optics/04_source.js');

// 8. MC engine (mcRayTrace, applyMirrorMC, applyDCM_MC, applyKBMC, hybrid)
loadJS('js/raytrace/01_mc_engine.js');

// 9. Beam profile (MC_GRID)
loadJS('js/raytrace/03_beam_profile.js');

_origLog('All modules loaded.\n');

// ===== Verify critical functions exist =====
var missing = [];
['mcRayTrace', 'photonSrc', 'braggAngle', 'darwinW', 'mirrorR', 'calcK', 'calcB0', 'calcE1', 'pos', 'mVal'].forEach(function(fn) {
  if (typeof global[fn] !== 'function') missing.push(fn);
});
if (missing.length > 0) {
  _origLog('FATAL: Missing functions: ' + missing.join(', '));
  process.exit(1);
}
_origLog('All critical functions verified.\n');

// ===== S4 Reference FWHM (500K rays, latest run) =====
var S4_REF = {
  '5keV_ssa50':  { h: 63.0, v: 71.8 },
  '10keV_ssa50': { h: 43.9, v: 43.6 },
  '20keV_ssa50': { h: 36.5, v: 32.6 },
  '10keV_ssa10': { h: 29.2, v: 31.2 },
  '10keV_ssa200':{ h: 49.3, v: 42.6 }
};

// ===== Benchmark conditions =====
var CONDITIONS = [
  { name: '10keV_ssa50',  energy: 10.0, ssaH: 50,  ssaV: 50  },
  { name: '5keV_ssa50',   energy: 5.0,  ssaH: 50,  ssaV: 50  },
  { name: '20keV_ssa50',  energy: 20.0, ssaH: 50,  ssaV: 50  },
  { name: '10keV_ssa10',  energy: 10.0, ssaH: 10,  ssaV: 10  },
  { name: '10keV_ssa200', energy: 10.0, ssaH: 200, ssaV: 200 }
];

// ===== Run benchmark =====
var NRAYS = 200000;
var NRUNS = 3;  // Average over multiple runs for stability

_origLog('========================================');
_origLog('  MC vs S4 Benchmark (' + NRAYS + ' rays x ' + NRUNS + ' runs)');
_origLog('========================================\n');

// ===== Diagnostics =====
_origLog('--- Diagnostics ---');
_origLog('MOTORS keys: ' + Object.keys(MOTORS).join(', '));
_origLog('MOTORS.m1: ' + (MOTORS.m1 ? Object.keys(MOTORS.m1).join(',') : 'MISSING'));
_origLog('MOTORS.kbv: ' + (MOTORS.kbv ? Object.keys(MOTORS.kbv).join(',') : 'MISSING'));
_origLog('MOTORS.kbh: ' + (MOTORS.kbh ? Object.keys(MOTORS.kbh).join(',') : 'MISSING'));
if (MOTORS.m1 && MOTORS.m1.pitch) _origLog('MOTORS.m1.pitch.value = ' + MOTORS.m1.pitch.value);
if (MOTORS.kbv && MOTORS.kbv.pitch) _origLog('MOTORS.kbv.pitch.value = ' + MOTORS.kbv.pitch.value);
if (MOTORS.kbh && MOTORS.kbh.pitch) _origLog('MOTORS.kbh.pitch.value = ' + MOTORS.kbh.pitch.value);

// Test gap tuning
[5, 10, 20].forEach(function(e) {
  for (var g = 5.0; g < 30.0; g += 0.01) {
    var e1 = calcE1(calcK(calcB0(g)));
    if (e1 >= e) {
      _origLog('E=' + e + 'keV -> gap=' + g.toFixed(2) + 'mm, E1=' + e1.toFixed(2) + 'keV, K=' + calcK(calcB0(g)).toFixed(3));
      break;
    }
  }
});

// Test photonSrc
state.energy = 10.0;
var ps = photonSrc(10.0);
_origLog('photonSrc(10): Sx=' + (ps.Sx*1e6).toFixed(2) + 'um, Sy=' + (ps.Sy*1e6).toFixed(2) + 'um, Sxp=' + (ps.Sxp*1e6).toFixed(2) + 'urad, Syp=' + (ps.Syp*1e6).toFixed(2) + 'urad');

// Test pos
_origLog('pos: m1=' + pos('m1') + ', dcm=' + pos('dcm') + ', m2=' + pos('m2') + ', ssa=' + pos('ssa') + ', kbv=' + pos('kbv') + ', kbh=' + pos('kbh') + ', sample=' + pos('sample'));

// Test mirrorR
_origLog('mirrorR(10, 3.0, RH) = ' + mirrorR(10.0, 3.0, RH).toFixed(4));
_origLog('mirrorR(10, 3.0, PT) = ' + mirrorR(10.0, 3.0, PT).toFixed(4));
_origLog('braggAngle(10) = ' + (braggAngle(10.0)*1000).toFixed(4) + ' mrad');
_origLog('');

// ===== Single-ray trace diagnostic =====
_origLog('--- Single-ray trace at 10keV SSA50 ---');
state.energy = 10.0; state.ssaH = 50; state.ssaV = 50; state.crystal = '111';
state.m1pitch = 3.0; state.m2pitch = 3.0; state.kbvpitch = 3.0; state.kbhpitch = 3.0;
var best10 = selectBest(10.0);
state.gap = best10.gap; state.harmonic = best10.n;
autoStripeForEnergy(10.0);
_origLog('  Coating: M1=' + state.m1stripe + ', M2=' + state.m2stripe);
try { MOTORS.m1.pitch.value = 3.0; MOTORS.m2.pitch.value = 3.0; } catch(e){}
try { MOTORS.kbv.pitch.value = 3.0; MOTORS.kbh.pitch.value = 3.0; } catch(e){}
var thB10 = braggAngle(10.0);
try { MOTORS.dcm.theta.value = thB10 * 180 / Math.PI; } catch(e){}

// Run with 100 rays and capture intermediate positions
_origLog('  KB_PARAMS defined: ' + (typeof KB_PARAMS !== 'undefined' && KB_PARAMS !== null));
_origLog('  _applyHybridFresnel: ' + (typeof _applyHybridFresnel));
_origLog('  _applySSAHybrid: ' + (typeof _applySSAHybrid));
_origLog('  bendToFocal: ' + (typeof bendToFocal));
_origLog('  getStripeMaterial: ' + (typeof getStripeMaterial));

_origLog('  KB_PARAMS: kbv.len=' + KB_PARAMS.kbv.len + ', kbh.len=' + KB_PARAMS.kbh.len);

// Quick test: run MC with 10000 rays and check beam at intermediate positions
var testMC = mcRayTrace(150.0, 10000);
_origLog('  Test MC: survived=' + testMC.nSurvived + ', sigH=' + (testMC.sigH*1e9).toFixed(1) + 'nm, sigV=' + (testMC.sigV*1e9).toFixed(1) + 'nm');
_origLog('  fwhmH=' + (testMC.fwhmH*1e9).toFixed(1) + 'nm, fwhmV=' + (testMC.fwhmV*1e9).toFixed(1) + 'nm');
_origLog('');

// Also test at SSA position (58m) to verify M1/M2 focusing
var testSSA = mcRayTrace(58.0, 10000);
_origLog('  At SSA: survived=' + testSSA.nSurvived + ', sigH=' + (testSSA.sigH*1e6).toFixed(1) + 'um, sigV=' + (testSSA.sigV*1e6).toFixed(1) + 'um');
_origLog('  fwhmH=' + (testSSA.fwhmH*1e6).toFixed(1) + 'um, fwhmV=' + (testSSA.fwhmV*1e6).toFixed(1) + 'um');
_origLog('');

var results = [];

CONDITIONS.forEach(function(cond) {
  // Set beamline state
  state.energy = cond.energy;
  state.ssaH = cond.ssaH;
  state.ssaV = cond.ssaV;
  state.crystal = '111';
  state.gap = 7.0;
  state.wbH = 2.0;
  state.wbV = 1.0;
  state.m1pitch = 3.0;
  state.m2pitch = 3.0;
  state.kbvpitch = 3.0;
  state.kbhpitch = 3.0;
  state.harmonic = 1;

  // Auto-select harmonic and gap for energy
  var best = selectBest(cond.energy);
  if (best) {
    state.gap = best.gap;
    state.harmonic = best.n;
    _origLog('  [Setup] E=' + cond.energy + 'keV -> n=' + best.n + ', gap=' + best.gap.toFixed(2) + 'mm, K=' + best.K.toFixed(3) + ', E1=' + best.E1.toFixed(2) + 'keV');
  } else {
    _origLog('  [WARN] No harmonic found for E=' + cond.energy + 'keV');
  }

  // Auto-select mirror coating for energy
  // M1: always Pt | M2: Rh(5-23keV), Si(<5keV), Pt(23+keV) | KB: always Pt
  var m2coat = autoStripeForEnergy(cond.energy);
  _origLog('  [Coating] M1=' + state.m1stripe + ', M2=' + state.m2stripe + ' (auto for ' + cond.energy + 'keV)');

  // Verify coating by checking getStripeMaterial
  var m1mat = getStripeMaterial('m1');
  var m2mat = getStripeMaterial('m2');
  var kbvmat = getStripeMaterial('kbv');
  var kbhmat = getStripeMaterial('kbh');
  _origLog('  [Verify] M1=' + m1mat.name + '(Z=' + m1mat.mat.Z + '), M2=' + m2mat.name + '(Z=' + m2mat.mat.Z + '), KBV=' + kbvmat.name + ', KBH=' + kbhmat.name);

  // Sync motor values with state
  try { MOTORS.m1.pitch.value = state.m1pitch; } catch(e){}
  try { MOTORS.m2.pitch.value = state.m2pitch; } catch(e){}
  try { MOTORS.kbv.pitch.value = state.kbvpitch; } catch(e){}
  try { MOTORS.kbh.pitch.value = state.kbhpitch; } catch(e){}
  // Sync DCM theta
  var thB = braggAngle(cond.energy);
  if (!isNaN(thB) && MOTORS.dcm && MOTORS.dcm.theta) {
    MOTORS.dcm.theta.value = thB * 180 / Math.PI;
  }

  var fwhmH_arr = [], fwhmV_arr = [], surv_arr = [];
  var nRaysThis = NRAYS;

  for (var r = 0; r < NRUNS; r++) {
    var mc = mcRayTrace(150.0, nRaysThis);
    fwhmH_arr.push(mc.fwhmH * 1e9);
    fwhmV_arr.push(mc.fwhmV * 1e9);
    surv_arr.push(mc.nSurvived);
    if (r === 0) {
      _origLog('  [Diag] survived=' + mc.nSurvived + '/' + nRaysThis + ' (' + (mc.nSurvived/nRaysThis*100).toFixed(1) + '%), sigH=' + (mc.sigH*1e9).toFixed(1) + 'nm, sigV=' + (mc.sigV*1e9).toFixed(1) + 'nm');
    }
  }

  // Compute mean and std
  var meanH = fwhmH_arr.reduce(function(a,b){return a+b;}, 0) / NRUNS;
  var meanV = fwhmV_arr.reduce(function(a,b){return a+b;}, 0) / NRUNS;
  var meanSurv = surv_arr.reduce(function(a,b){return a+b;}, 0) / NRUNS;
  var stdH = Math.sqrt(fwhmH_arr.reduce(function(a,b){return a+(b-meanH)*(b-meanH);}, 0) / NRUNS);
  var stdV = Math.sqrt(fwhmV_arr.reduce(function(a,b){return a+(b-meanV)*(b-meanV);}, 0) / NRUNS);

  var s4 = S4_REF[cond.name];
  var devH = ((meanH - s4.h) / s4.h * 100);
  var devV = ((meanV - s4.v) / s4.v * 100);

  results.push({
    name: cond.name, energy: cond.energy, ssa: cond.ssaH,
    mcH: meanH, mcV: meanV, stdH: stdH, stdV: stdV,
    s4H: s4.h, s4V: s4.v, devH: devH, devV: devV,
    survived: meanSurv
  });

  _origLog(cond.name + ':');
  _origLog('  MC  H = ' + meanH.toFixed(1) + ' +/- ' + stdH.toFixed(1) + ' nm');
  _origLog('  MC  V = ' + meanV.toFixed(1) + ' +/- ' + stdV.toFixed(1) + ' nm');
  _origLog('  S4  H = ' + s4.h.toFixed(1) + ' nm,  S4 V = ' + s4.v.toFixed(1) + ' nm');
  _origLog('  Dev H = ' + (devH >= 0 ? '+' : '') + devH.toFixed(1) + '%,  Dev V = ' + (devV >= 0 ? '+' : '') + devV.toFixed(1) + '%');
  _origLog('  Survived: ' + Math.round(meanSurv) + '/' + NRAYS + ' (' + (meanSurv/NRAYS*100).toFixed(1) + '%)');
  _origLog('');
});

// ===== Summary Table =====
_origLog('\n========================================');
_origLog('  SUMMARY: New MC vs S4 (500K rays)');
_origLog('========================================');
_origLog('');
_origLog('Condition     | MC H(nm) | S4 H(nm) | Dev H  | MC V(nm) | S4 V(nm) | Dev V  | Surv%');
_origLog('--------------|----------|----------|--------|----------|----------|--------|------');

var totalAbsDevH = 0, totalAbsDevV = 0;
results.forEach(function(r) {
  var line = r.name.padEnd(14) + '| ' +
    r.mcH.toFixed(1).padStart(8) + ' | ' +
    r.s4H.toFixed(1).padStart(8) + ' | ' +
    ((r.devH >= 0 ? '+' : '') + r.devH.toFixed(1) + '%').padStart(6) + ' | ' +
    r.mcV.toFixed(1).padStart(8) + ' | ' +
    r.s4V.toFixed(1).padStart(8) + ' | ' +
    ((r.devV >= 0 ? '+' : '') + r.devV.toFixed(1) + '%').padStart(6) + ' | ' +
    (r.survived / NRAYS * 100).toFixed(1).padStart(5);
  _origLog(line);
  totalAbsDevH += Math.abs(r.devH);
  totalAbsDevV += Math.abs(r.devV);
});

_origLog('');
_origLog('Mean |Dev H| = ' + (totalAbsDevH / results.length).toFixed(1) + '%');
_origLog('Mean |Dev V| = ' + (totalAbsDevV / results.length).toFixed(1) + '%');
_origLog('Mean |Dev|   = ' + ((totalAbsDevH + totalAbsDevV) / (results.length * 2)).toFixed(1) + '%');
_origLog('');

// Compare with OLD MC
_origLog('--- Comparison with OLD MC (before hybrid fix) ---');
var OLD_MC = {
  '5keV_ssa50':  { h: 72.9, v: 91.4 },
  '10keV_ssa50': { h: 50.9, v: 49.7 },
  '20keV_ssa50': { h: 42.3, v: 42.1 },
  '10keV_ssa10': { h: 34.7, v: 35.4 },
  '10keV_ssa200':{ h: 60.1, v: 50.8 }
};

_origLog('Condition     | Old Dev H | New Dev H | Old Dev V | New Dev V | Improved?');
_origLog('--------------|-----------|-----------|-----------|-----------|----------');
results.forEach(function(r) {
  var old = OLD_MC[r.name];
  var oldDevH = (old.h - r.s4H) / r.s4H * 100;
  var oldDevV = (old.v - r.s4V) / r.s4V * 100;
  var betterH = Math.abs(r.devH) < Math.abs(oldDevH) ? 'YES' : 'NO';
  var betterV = Math.abs(r.devV) < Math.abs(oldDevV) ? 'YES' : 'NO';
  _origLog(r.name.padEnd(14) + '| ' +
    ((oldDevH >= 0 ? '+' : '') + oldDevH.toFixed(1) + '%').padStart(9) + ' | ' +
    ((r.devH >= 0 ? '+' : '') + r.devH.toFixed(1) + '%').padStart(9) + ' | ' +
    ((oldDevV >= 0 ? '+' : '') + oldDevV.toFixed(1) + '%').padStart(9) + ' | ' +
    ((r.devV >= 0 ? '+' : '') + r.devV.toFixed(1) + '%').padStart(9) + ' | ' +
    (betterH + '/' + betterV).padStart(9)
  );
});

// ===== Hybrid contribution decomposition (10keV SSA50) =====
_origLog('\n========================================');
_origLog('  HYBRID DECOMPOSITION (10keV SSA50, 200K rays x 5 runs)');
_origLog('========================================\n');

function _setupState10() {
  state.energy = 10.0; state.ssaH = 50; state.ssaV = 50; state.crystal = '111';
  state.m1pitch = 3.0; state.m2pitch = 3.0; state.kbvpitch = 3.0; state.kbhpitch = 3.0;
  var b10 = selectBest(10.0);
  state.gap = b10.gap; state.harmonic = b10.n;
  autoStripeForEnergy(10.0);
  try { MOTORS.m1.pitch.value = 3.0; MOTORS.m2.pitch.value = 3.0; } catch(e){}
  try { MOTORS.kbv.pitch.value = 3.0; MOTORS.kbh.pitch.value = 3.0; } catch(e){}
  var thB10 = braggAngle(10.0);
  try { MOTORS.dcm.theta.value = thB10 * 180 / Math.PI; } catch(e){}
}

var _savedHybFresnel = _applyHybridFresnel;
var _savedSSAHybrid = _applySSAHybrid;
var NR5 = 5;
var decomp = {};

// 1. Both ON
_setupState10();
var hh = [], vv = [];
for (var r = 0; r < NR5; r++) { var mc = mcRayTrace(150.0, NRAYS); hh.push(mc.fwhmH*1e9); vv.push(mc.fwhmV*1e9); }
decomp.bothOn = { h: hh.reduce(function(a,b){return a+b;},0)/NR5, v: vv.reduce(function(a,b){return a+b;},0)/NR5 };

// 2. Both OFF
window._applyHybridFresnel = null; window._applySSAHybrid = null;
_setupState10();
hh = []; vv = [];
for (var r = 0; r < NR5; r++) { var mc = mcRayTrace(150.0, NRAYS); hh.push(mc.fwhmH*1e9); vv.push(mc.fwhmV*1e9); }
decomp.bothOff = { h: hh.reduce(function(a,b){return a+b;},0)/NR5, v: vv.reduce(function(a,b){return a+b;},0)/NR5 };

// 3. SSA ON, KB OFF
window._applySSAHybrid = _savedSSAHybrid; window._applyHybridFresnel = null;
_setupState10();
hh = []; vv = [];
for (var r = 0; r < NR5; r++) { var mc = mcRayTrace(150.0, NRAYS); hh.push(mc.fwhmH*1e9); vv.push(mc.fwhmV*1e9); }
decomp.ssaOnly = { h: hh.reduce(function(a,b){return a+b;},0)/NR5, v: vv.reduce(function(a,b){return a+b;},0)/NR5 };

// 4. KB ON, SSA OFF
window._applySSAHybrid = null; window._applyHybridFresnel = _savedHybFresnel;
_setupState10();
hh = []; vv = [];
for (var r = 0; r < NR5; r++) { var mc = mcRayTrace(150.0, NRAYS); hh.push(mc.fwhmH*1e9); vv.push(mc.fwhmV*1e9); }
decomp.kbOnly = { h: hh.reduce(function(a,b){return a+b;},0)/NR5, v: vv.reduce(function(a,b){return a+b;},0)/NR5 };

// Restore
window._applyHybridFresnel = _savedHybFresnel; window._applySSAHybrid = _savedSSAHybrid;

// S4 reference: geometric=33.6/33.5, hybrid=43.0/44.8
_origLog('Mode            | MC H(nm) | MC V(nm) | S4 H(nm) | S4 V(nm)');
_origLog('----------------|----------|----------|----------|--------');
_origLog('Both OFF (geom) | ' + decomp.bothOff.h.toFixed(1).padStart(8) + ' | ' + decomp.bothOff.v.toFixed(1).padStart(8) + ' |     33.6 |     33.5');
_origLog('SSA only        | ' + decomp.ssaOnly.h.toFixed(1).padStart(8) + ' | ' + decomp.ssaOnly.v.toFixed(1).padStart(8) + ' |      n/a |      n/a');
_origLog('KB only         | ' + decomp.kbOnly.h.toFixed(1).padStart(8) + ' | ' + decomp.kbOnly.v.toFixed(1).padStart(8) + ' |      n/a |      n/a');
_origLog('Both ON         | ' + decomp.bothOn.h.toFixed(1).padStart(8) + ' | ' + decomp.bothOn.v.toFixed(1).padStart(8) + ' |     43.0 |     44.8');
_origLog('');
_origLog('Contributions:');
_origLog('  SSA effect = SSA_only - geom: H=' + (decomp.ssaOnly.h-decomp.bothOff.h).toFixed(1) + ', V=' + (decomp.ssaOnly.v-decomp.bothOff.v).toFixed(1));
_origLog('  KB  effect = KB_only  - geom: H=' + (decomp.kbOnly.h-decomp.bothOff.h).toFixed(1) + ', V=' + (decomp.kbOnly.v-decomp.bothOff.v).toFixed(1));
_origLog('  Total      = both_on  - geom: H=' + (decomp.bothOn.h-decomp.bothOff.h).toFixed(1) + ', V=' + (decomp.bothOn.v-decomp.bothOff.v).toFixed(1));
_origLog('  S4 total   = S4_hyb - S4_geo: H=' + (43.0-33.6).toFixed(1) + ', V=' + (44.8-33.5).toFixed(1));

// ===== HYBRID DIAGNOSTICS: wrap _applyHybridFresnel to capture D, angular kicks =====
_origLog('\n========================================');
_origLog('  HYBRID DIAGNOSTICS (10keV SSA50)');
_origLog('========================================\n');

_setupState10();
var diagData = {};
var RS = 6; // ray stride: x,y,vx,vy,vz,alive

// Wrap _applyHybridFresnel: capture before/after ray state
var _origApplyHybFr2 = _savedHybFresnel;
window._applyHybridFresnel = function(rays, nR, E, td) {
  var alive = [];
  for (var i = 0; i < nR; i++) {
    if (rays[i * RS + 5] > 0) alive.push(i);
  }

  // Get footprint from stored arrays
  var fpV = window._kbFootprintArr && window._kbFootprintArr['kbv'];
  var fpH = window._kbFootprintArr && window._kbFootprintArr['kbh'];

  // Compute footprint D (same logic as _applyHybridFresnel)
  if (fpV && fpH && alive.length > 10) {
    var yvMin = Infinity, yvMax = -Infinity;
    var xhMin = Infinity, xhMax = -Infinity;
    var yvSum = 0, yvSum2 = 0, xhSum = 0, xhSum2 = 0;
    for (var ai = 0; ai < alive.length; ai++) {
      var ri = alive[ai];
      var yv = fpV[ri], xh = fpH[ri];
      if (yv < yvMin) yvMin = yv; if (yv > yvMax) yvMax = yv;
      if (xh < xhMin) xhMin = xh; if (xh > xhMax) xhMax = xh;
      yvSum += yv; yvSum2 += yv*yv;
      xhSum += xh; xhSum2 += xh*xh;
    }
    var yvMean = yvSum/alive.length, xhMean = xhSum/alive.length;
    var yvSig = Math.sqrt(yvSum2/alive.length - yvMean*yvMean);
    var xhSig = Math.sqrt(xhSum2/alive.length - xhMean*xhMean);
    var DV = yvMax - yvMin;
    var DH = xhMax - xhMin;
    var apV = 0.300 * Math.sin(0.003);
    var apH = 0.100 * Math.sin(0.003);
    if (DV > apV) DV = apV;
    if (DH > apH) DH = apH;
    diagData.footprint = {
      kbv_range_um: (yvMax-yvMin)*1e6, kbv_D_um: DV*1e6,
      kbv_sigma_um: yvSig*1e6, kbv_fwhm_um: yvSig*2.355*1e6,
      kbh_range_um: (xhMax-xhMin)*1e6, kbh_D_um: DH*1e6,
      kbh_sigma_um: xhSig*1e6, kbh_fwhm_um: xhSig*2.355*1e6,
      nAlive: alive.length
    };
  }

  // Record ray positions BEFORE hybrid
  var posBeforeH = new Float64Array(alive.length);
  var posBeforeV = new Float64Array(alive.length);
  for (var ai = 0; ai < alive.length; ai++) {
    var o = alive[ai] * RS;
    posBeforeH[ai] = rays[o];
    posBeforeV[ai] = rays[o + 1];
  }

  // Call the real hybrid function
  _origApplyHybFr2(rays, nR, E, td);

  // Record ray positions AFTER hybrid
  var posAfterH = new Float64Array(alive.length);
  var posAfterV = new Float64Array(alive.length);
  for (var ai = 0; ai < alive.length; ai++) {
    var o = alive[ai] * RS;
    posAfterH[ai] = rays[o];
    posAfterV[ai] = rays[o + 1];
  }

  // Compute position shift (at sample) = angular_kick * q
  var qV = 150.0 - 149.69; // 0.31m
  var qH = 150.0 - 149.90; // 0.10m
  var dxSum = 0, dxSum2 = 0, dySum = 0, dySum2 = 0;
  for (var ai = 0; ai < alive.length; ai++) {
    var dx = posAfterH[ai] - posBeforeH[ai];
    var dy = posAfterV[ai] - posBeforeV[ai];
    dxSum += dx; dxSum2 += dx*dx;
    dySum += dy; dySum2 += dy*dy;
  }
  var n = alive.length;
  var dxMean = dxSum/n, dyMean = dySum/n;
  var dxStd = Math.sqrt(dxSum2/n - dxMean*dxMean);
  var dyStd = Math.sqrt(dySum2/n - dyMean*dyMean);

  // FWHM of position shifts
  function computeFwhm(arr, n) {
    var nB = 200;
    var vMin = arr[0], vMax = arr[0];
    for (var i = 1; i < n; i++) { if (arr[i]<vMin)vMin=arr[i]; if(arr[i]>vMax)vMax=arr[i]; }
    var bw = (vMax-vMin)/nB;
    if (bw < 1e-20) return 0;
    var h = new Float64Array(nB);
    for (var i = 0; i < n; i++) { var bi=Math.floor((arr[i]-vMin)/bw); if(bi>=0&&bi<nB) h[bi]++; }
    var pk = 0; for (var i=0;i<nB;i++) if(h[i]>pk) pk=h[i];
    var hm = pk*0.5;
    var iL=0,iR=nB-1;
    for (var i=0;i<nB;i++) { if(h[i]>=hm){iL=i;break;} }
    for (var i=nB-1;i>=0;i--) { if(h[i]>=hm){iR=i;break;} }
    return (iR-iL)*bw;
  }

  // Position shift arrays
  var dxArr = new Float64Array(n), dyArr = new Float64Array(n);
  for (var ai = 0; ai < n; ai++) {
    dxArr[ai] = posAfterH[ai] - posBeforeH[ai];
    dyArr[ai] = posAfterV[ai] - posBeforeV[ai];
  }
  var dxFwhm = computeFwhm(dxArr, n);
  var dyFwhm = computeFwhm(dyArr, n);

  diagData.kicks = {
    dx_mean_nm: dxMean*1e9, dy_mean_nm: dyMean*1e9,
    dx_std_nm: dxStd*1e9, dy_std_nm: dyStd*1e9,
    dx_fwhm_nm: dxFwhm*1e9, dy_fwhm_nm: dyFwhm*1e9,
    angH_fwhm_urad: (dxFwhm/qH)*1e6, angV_fwhm_urad: (dyFwhm/qV)*1e6,
    nAlive: n
  };
};

// Restore SSA hybrid for full run
window._applySSAHybrid = _savedSSAHybrid;

// Run one trace with instrumented hybrid
var mcDiag = mcRayTrace(150.0, NRAYS);

// Restore original
window._applyHybridFresnel = _savedHybFresnel;

// Print diagnostics
var lambda10 = 12.398 / 10.0 * 1e-10;
_origLog('lambda = ' + (lambda10*1e10).toFixed(4) + ' A = ' + (lambda10*1e9).toFixed(4) + ' nm');
_origLog('');

if (diagData.footprint) {
  var fp = diagData.footprint;
  _origLog('Footprint on KB mirrors (alive=' + fp.nAlive + '):');
  _origLog('  KB-V: range=' + fp.kbv_range_um.toFixed(1) + 'um, D(clamped)=' + fp.kbv_D_um.toFixed(1) + 'um, sigma=' + fp.kbv_sigma_um.toFixed(1) + 'um, FWHM=' + fp.kbv_fwhm_um.toFixed(1) + 'um');
  _origLog('  KB-H: range=' + fp.kbh_range_um.toFixed(1) + 'um, D(clamped)=' + fp.kbh_D_um.toFixed(1) + 'um, sigma=' + fp.kbh_sigma_um.toFixed(1) + 'um, FWHM=' + fp.kbh_fwhm_um.toFixed(1) + 'um');
  _origLog('  KB-V aperture: ' + (0.300 * Math.sin(0.003) * 1e6).toFixed(0) + 'um (300mm x sin3mrad)');
  _origLog('  KB-H aperture: ' + (0.100 * Math.sin(0.003) * 1e6).toFixed(0) + 'um (100mm x sin3mrad)');

  // Airy FWHM for each D
  var airyV = 0.88 * lambda10 / (fp.kbv_D_um * 1e-6);
  var airyH = 0.88 * lambda10 / (fp.kbh_D_um * 1e-6);
  _origLog('  Airy(D_V): ' + (airyV*1e6).toFixed(3) + ' urad -> ' + (airyV*0.31*1e9).toFixed(1) + ' nm at sample');
  _origLog('  Airy(D_H): ' + (airyH*1e6).toFixed(3) + ' urad -> ' + (airyH*0.10*1e9).toFixed(1) + ' nm at sample');
  _origLog('');
}

if (diagData.kicks) {
  var k = diagData.kicks;
  _origLog('Hybrid kicks (position shift at sample, n=' + k.nAlive + '):');
  _origLog('  H: mean=' + k.dx_mean_nm.toFixed(1) + 'nm, std=' + k.dx_std_nm.toFixed(1) + 'nm, FWHM=' + k.dx_fwhm_nm.toFixed(1) + 'nm');
  _origLog('  V: mean=' + k.dy_mean_nm.toFixed(1) + 'nm, std=' + k.dy_std_nm.toFixed(1) + 'nm, FWHM=' + k.dy_fwhm_nm.toFixed(1) + 'nm');
  _origLog('  Angular FWHM: H=' + k.angH_fwhm_urad.toFixed(3) + ' urad, V=' + k.angV_fwhm_urad.toFixed(3) + ' urad');
  _origLog('');
}

// Compare with S4 expected broadening
var s4GeomH = 33.6, s4GeomV = 33.5, s4HybH = 43.0, s4HybV = 44.8;
var s4DiffH = Math.sqrt(s4HybH*s4HybH - s4GeomH*s4GeomH);
var s4DiffV = Math.sqrt(s4HybV*s4HybV - s4GeomV*s4GeomV);
_origLog('S4 diffraction FWHM (quadrature): H=' + s4DiffH.toFixed(1) + 'nm, V=' + s4DiffV.toFixed(1) + 'nm');
var mcGeomH = decomp.bothOff.h, mcGeomV = decomp.bothOff.v;
var mcHybH = mcDiag.fwhmH * 1e9, mcHybV = mcDiag.fwhmV * 1e9;
_origLog('MC hybrid spot: H=' + mcHybH.toFixed(1) + 'nm, V=' + mcHybV.toFixed(1) + 'nm');
var mcDiffH = Math.sqrt(Math.max(0, mcHybH*mcHybH - mcGeomH*mcGeomH));
var mcDiffV = Math.sqrt(Math.max(0, mcHybV*mcHybV - mcGeomV*mcGeomV));
_origLog('MC diffraction FWHM (quadrature): H=' + mcDiffH.toFixed(1) + 'nm, V=' + mcDiffV.toFixed(1) + 'nm');
if (s4DiffH > 0 && s4DiffV > 0) {
  _origLog('MC/S4 ratio: H=' + (mcDiffH/s4DiffH).toFixed(3) + ', V=' + (mcDiffV/s4DiffV).toFixed(3));
}

// What D S4 would need for its broadening (assuming uniform aperture Airy)
var s4AngH = s4DiffH * 1e-9 / 0.10;
var s4AngV = s4DiffV * 1e-9 / 0.31;
var s4DeffH = 0.88 * lambda10 / s4AngH;
var s4DeffV = 0.88 * lambda10 / s4AngV;
_origLog('');
_origLog('S4 effective D (back-calculated from broadening):');
_origLog('  H: ' + (s4DeffH*1e6).toFixed(0) + 'um (MC uses ' + (diagData.footprint ? diagData.footprint.kbh_D_um.toFixed(0) : '?') + 'um)');
_origLog('  V: ' + (s4DeffV*1e6).toFixed(0) + 'um (MC uses ' + (diagData.footprint ? diagData.footprint.kbv_D_um.toFixed(0) : '?') + 'um)');
