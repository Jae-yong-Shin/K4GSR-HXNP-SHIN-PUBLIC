// run_layout_export_check.js — headless validation of exportBeamlineLayout()
// (Phase 1 / A2, docs/tasks/TASK_A2_XRT_EXPORT.md)
//
// Loads the engine constants + the layout-export module with browser stubs
// (vm.runInThisContext pattern from run_js_mc.js), configures a known state,
// calls exportBeamlineLayout() and asserts:
//   1. schema/version present
//   2. all CD component ids present, positions finite & non-negative
//      (source at 0, everything downstream strictly positive, monotonic info)
//   3. beam block matches state (energy/crystal/gap/harmonic)
//   4. slit gaps/centers match state
//   5. mirror pitches/coatings and KB p/q geometry are consistent
//   6. source params match engine variables
//   7. document JSON round-trips losslessly
//   8. headless {download:true} does not throw
// Also writes the exported default layout to
//   paper/validation/data/layout_default.json (input for layout_to_xrt.py).
//
// Usage: node paper/validation/run_layout_export_check.js

var fs = require('fs');
var path = require('path');
var vm = require('vm');

var BASE = path.resolve(__dirname, '../..');

// ======= Browser API stubs (run_js_mc.js pattern) =======
global.window = global;
global.document = undefined; // headless: exportBeamlineLayout must not need DOM
global.location = { search: '' };
global.localStorage = { getItem: function () { return null; }, setItem: function () {} };

// Motor system stubs (needed by 01_mc_engine.js for M1_P/M2_P + getStripeMaterial)
global.DEVICE_CONFIGS = [];
global.MOTORS = {
  m2: { y: { id: 'm2_y', value: -2, target: -2 } }  // Rh stripe (center=+2, yTarget=-2)
};
global.buildMotorsFromConfig = function () {};
global.KB_PARAMS = {
  kbv: { type: 'elliptical', len: 0.300, wid: 0.030, thick: 0.020, rough: 4.0 },
  kbh: { type: 'elliptical', len: 0.100, wid: 0.030, thick: 0.020, rough: 4.0 }
};
global.MC_GRID = 51;

function loadJS(relPath) {
  var code = fs.readFileSync(path.join(BASE, relPath), 'utf8');
  vm.runInThisContext(code, { filename: relPath });
}

console.log('Loading JS modules...');
loadJS('js/shared/01_constants.js');
loadJS('js/optics/00_optconst_tables.js');
loadJS('js/optics/01_undulator.js');
loadJS('js/optics/02_crystal.js');
loadJS('js/optics/02b_crystal_psi_tables.js');
loadJS('js/optics/03_reflectivity.js');
loadJS('js/optics/04_source.js');
loadJS('js/raytrace/01_mc_engine.js');   // M1_P/M2_P/M_PARAMS + getStripeMaterial
loadJS('js/optics/08_layout_export.js'); // module under test

// ======= Configure a known live state =======
state.energy = 10.0;
state.targetEnergy = 10.0;
state.crystal = '111';
state.ssaH = 50; state.ssaV = 50;       // um
state.ssaCX = 0; state.ssaCY = 0;       // um
state.wbH = 1.2; state.wbV = 1.2;       // mm
state.wbCX = 0; state.wbCY = 0;         // mm
state.m1pitch = 2.5; state.m2pitch = 2.5;   // mrad
state.kbvpitch = 3.0; state.kbhpitch = 3.0; // mrad
state.kbslitH = 5000; state.kbslitV = 5000; // um
state.kbslitCX = 0; state.kbslitCY = 0;
// Auto harmonic & gap for 10 keV (browser behavior, run_js_mc.js pattern)
var best = selectBest(state.energy);
if (best) {
  state.harmonic = best.n;
  state.gap = best.gap;
  console.log('Auto harmonic: n=' + best.n + ' gap=' + best.gap.toFixed(3) +
    ' K=' + best.K.toFixed(3) + ' E1=' + best.E1.toFixed(3) + 'keV');
} else {
  state.harmonic = 1; state.gap = 7.0;
}

// ======= Run export =======
var layout = exportBeamlineLayout();

// ======= Assertions =======
var nPass = 0, nFail = 0;
function check(name, cond, detail) {
  if (cond) { nPass++; console.log('  PASS  ' + name); }
  else { nFail++; console.log('  FAIL  ' + name + (detail ? '  [' + detail + ']' : '')); }
}

console.log('\n=== 1. schema ===');
check('schema id', layout.schema === 'hanbit.beamline.layout', String(layout.schema));
check('schemaVersion = 1', layout.schemaVersion === 1, String(layout.schemaVersion));
check('exportedAt ISO', typeof layout.exportedAt === 'string' && !isNaN(Date.parse(layout.exportedAt)));
check('engineVersion = APP_VERSION', layout.engineVersion === APP_VERSION,
  layout.engineVersion + ' vs ' + APP_VERSION);

console.log('\n=== 2. components (CD ids + positions) ===');
check('component count = CD.length (' + CD.length + ')', layout.components.length === CD.length,
  String(layout.components.length));
var ids = {};
layout.components.forEach(function (c) { ids[c.id] = c; });
var allPresent = true, allFinite = true, allNonNeg = true, downstreamPos = true;
CD.forEach(function (c) {
  var e = ids[c.id];
  if (!e) { allPresent = false; return; }
  if (typeof e.position_m !== 'number' || !isFinite(e.position_m)) allFinite = false;
  if (e.position_m < 0) allNonNeg = false;
  if (c.id !== 'ivu' && !(e.position_m > 0)) downstreamPos = false;
  if (e.position_m !== pos(c.id)) allFinite = false; // must equal live pos()
});
check('all ' + CD.length + ' CD ids present', allPresent);
check('positions finite and equal pos(id)', allFinite);
check('source at >= 0, downstream strictly positive', allNonNeg && downstreamPos);

console.log('\n=== 3. beam state ===');
check('energy_keV', layout.beam.energy_keV === state.energy);
check('targetEnergy_keV', layout.beam.targetEnergy_keV === state.targetEnergy);
check('crystal', layout.beam.crystal === state.crystal);
check('gap_mm', layout.beam.gap_mm === state.gap);
check('harmonic', layout.beam.harmonic === state.harmonic);

console.log('\n=== 4. slits ===');
check('wb gaps', layout.slits.wb.hGap_mm === state.wbH && layout.slits.wb.vGap_mm === state.wbV);
check('wb centers', layout.slits.wb.hCenter_mm === 0 && layout.slits.wb.vCenter_mm === 0);
check('ssa gaps', layout.slits.ssa.hGap_um === state.ssaH && layout.slits.ssa.vGap_um === state.ssaV);
check('ssa centers', layout.slits.ssa.hCenter_um === 0 && layout.slits.ssa.vCenter_um === 0);
check('kbslit gaps', layout.slits.kbslit.hGap_um === state.kbslitH &&
  layout.slits.kbslit.vGap_um === state.kbslitV);

console.log('\n=== 5. mirrors ===');
check('m1 pitch', layout.mirrors.m1.pitch_mrad === state.m1pitch);
check('m2 pitch', layout.mirrors.m2.pitch_mrad === state.m2pitch);
check('kb pitches', layout.mirrors.kbv.pitch_mrad === state.kbvpitch &&
  layout.mirrors.kbh.pitch_mrad === state.kbhpitch);
check('m1 coating Pt', layout.mirrors.m1.coating === 'Pt', layout.mirrors.m1.coating);
check('m2 coating Rh (y=-2 stripe)', layout.mirrors.m2.coating === 'Rh', layout.mirrors.m2.coating);
check('kb coating Pt', layout.mirrors.kbv.coating === 'Pt' && layout.mirrors.kbh.coating === 'Pt');
check('m1 p/q = 29/29', layout.mirrors.m1.p_m === M1_P && layout.mirrors.m1.q_m === M1_Q);
check('m2 p/q = 32/26', layout.mirrors.m2.p_m === M2_P && layout.mirrors.m2.q_m === M2_Q);
var pV = pos('kbv') - pos('ssa'), qV = pos('sample') - pos('kbv');
var pH = pos('kbh') - pos('ssa'), qH = pos('sample') - pos('kbh');
check('kbv p/q from positions (' + pV.toFixed(2) + '/' + qV.toFixed(2) + ')',
  Math.abs(layout.mirrors.kbv.p_m - pV) < 1e-12 && Math.abs(layout.mirrors.kbv.q_m - qV) < 1e-12);
check('kbh p/q from positions (' + pH.toFixed(2) + '/' + qH.toFixed(2) + ')',
  Math.abs(layout.mirrors.kbh.p_m - pH) < 1e-12 && Math.abs(layout.mirrors.kbh.q_m - qH) < 1e-12);
check('kb lengths 0.300/0.100', layout.mirrors.kbv.length_m === 0.300 &&
  layout.mirrors.kbh.length_m === 0.100);

console.log('\n=== 6. source params ===');
check('E_GeV', layout.source.E_GeV === E_RING);
check('I_mA', layout.source.I_mA === I_RING);
check('emitX/emitY', layout.source.emitX_m_rad === EMIT_X && layout.source.emitY_m_rad === EMIT_Y);
check('betaX/betaY', layout.source.betaX_m === BETA_X && layout.source.betaY_m === BETA_Y);
check('eSpread', layout.source.eSpread === E_SPREAD);
check('lambdaU/nPeriods', layout.source.lambdaU_mm === LAMBDA_U && layout.source.nPeriods === N_PERIODS);

console.log('\n=== 7. JSON round-trip ===');
var txt = JSON.stringify(layout);
var back = JSON.parse(txt);
check('round-trip deep-equal', JSON.stringify(back) === txt);
check('no undefined leaked', txt.indexOf('undefined') === -1);
check('dcm dSpacing present', back.dcm.dSpacing_A === D_SI[state.crystal], String(back.dcm.dSpacing_A));

console.log('\n=== 8. headless download guard ===');
var threw = false;
try { exportBeamlineLayout({ download: true }); } catch (e) { threw = true; }
check('{download:true} headless does not throw', !threw);

// ======= Save default layout for layout_to_xrt.py =======
var outPath = path.join(BASE, 'paper/validation/data/layout_default.json');
fs.writeFileSync(outPath, JSON.stringify(layout, null, 1));
console.log('\nSaved default layout: ' + outPath);

console.log('\n==========================================');
console.log('TOTAL: ' + nPass + ' passed, ' + nFail + ' failed');
console.log(nFail === 0 ? 'RESULT: PASS' : 'RESULT: FAIL');
process.exit(nFail === 0 ? 0 : 1);
