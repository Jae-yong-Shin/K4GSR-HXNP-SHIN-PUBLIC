// run_xafs_ic_params_check.js -- headless contract check for the XAFS IC
// measurement toggle (stage 3 of TASK_XANES_IC_SIM): loads the experiment
// runner with browser stubs, assembles params.ic via _buildXafsICParams, and
// writes the JSON for the matching server-side check
// (run_xafs_ic_params_check.py) to consume. ES5, node only.
'use strict';
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var ROOT = path.join(__dirname, '..', '..');

// -- Browser stubs (same minimal pattern as run_layout_export_check.js) --
var sandbox = {
  console: console,
  window: {},
  document: {
    getElementById: function () { return null; },
    createElement: function () { return { style: {}, setAttribute: function () {} }; },
    addEventListener: function () {}
  },
  location: { hostname: 'localhost', port: '' },
  WebSocket: function () { this.readyState = 3; },
  setTimeout: function () { return 0; },
  clearTimeout: function () {},
  // state mirrors the IC1 popup + detector IC tab settings under test
  state: {
    energy: 8.979,
    ic1Gas: 'N2', ic1LenCm: 10, ic1PressAtm: 1.0,
    ic1AirBeforeCm: 5, ic1AirAfterCm: 2,
    det_icGas: 'Ar', det_icLenCm: 15
  },
  icLiveChain: function () { return { ratioPreFocus: 12.34 }; }
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

var src = fs.readFileSync(
  path.join(ROOT, 'js', 'experiment', '07_experiment_run.js'), 'utf8');
vm.runInContext(src, sandbox, { filename: '07_experiment_run.js' });

var fails = [];
function check(name, cond, detail) {
  console.log('  ' + (cond ? 'PASS' : 'FAIL') + '  ' + name +
    (detail ? '  ' + detail : ''));
  if (!cond) fails.push(name);
}

var build = vm.runInContext('typeof _buildXafsICParams', sandbox);
check('builder defined', build === 'function', build);

var ic = vm.runInContext('_buildXafsICParams(0.5)', sandbox);
check('enabled', ic.enabled === true);
check('dwell', ic.dwell_s === 0.5, String(ic.dwell_s));
check('i0 from IC1 popup state',
  ic.i0 && ic.i0.gas === 'N2' && ic.i0.length_cm === 10 &&
  ic.i0.pressure_atm === 1.0 && ic.i0.air_before_cm === 5 &&
  ic.i0.air_after_cm === 2, JSON.stringify(ic.i0));
check('i1 from det IC tab state',
  ic.i1 && ic.i1.gas === 'Ar' && ic.i1.length_cm === 15 &&
  ic.i1.air_path_cm === 0, JSON.stringify(ic.i1));
check('ratio_prefocus from icLiveChain',
  Math.abs(ic.ratio_prefocus - 12.34) < 1e-12, String(ic.ratio_prefocus));

// dwell fallback + missing-state robustness
var icDef = vm.runInContext('_buildXafsICParams(0)', sandbox);
check('dwell fallback 1.0', icDef.dwell_s === 1.0, String(icDef.dwell_s));
vm.runInContext('state = undefined; icLiveChain = undefined;', sandbox);
var icBare = vm.runInContext('_buildXafsICParams(1.0)', sandbox);
check('robust without state/icLiveChain',
  icBare.enabled === true && icBare.dwell_s === 1.0,
  JSON.stringify(icBare));

// JSON round-trip artifact for the python-side contract check
var out = path.join(__dirname, 'data', 'xafs_ic_params_sample.json');
fs.writeFileSync(out, JSON.stringify(ic, null, 1));
console.log('saved: ' + out);

console.log(fails.length ? 'RESULT: FAIL ' + JSON.stringify(fails)
                         : 'RESULT: ALL PASS');
process.exit(fails.length ? 1 : 0);
