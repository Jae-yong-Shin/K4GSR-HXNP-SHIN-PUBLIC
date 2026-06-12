// run_ionchamber_js_check.js - validate JS ion-chamber port vs xraydb reference
// Usage: node paper/validation/run_ionchamber_js_check.js
//
// Checks (all blocking; process exits 1 on any failure):
//   1. icCurrent over the full reference grid (4 gases x 41 energies,
//      L=10 cm, 1 atm) vs current_A_per_1e10phps from
//      data/ionchamber_reference.json  -> relative error <= 1%
//   2. icFluxFromCurrent round-trip (flux -> current -> flux) <= 0.1%,
//      and transmitted fraction vs reference atten_total <= 1%
//   3. One gas-mixture and one pressure case (+ one off-grid pure-gas case)
//      vs fresh python xraydb 4.5.8 calls (constants embedded below) <= 1%
//   4. both_carriers=false halves the current exactly

var fs = require('fs');
var path = require('path');
var vm = require('vm');

var BASE = path.resolve(__dirname, '../..');
var TOL_GRID = 0.01;       // 1% vs reference grid
var TOL_ROUNDTRIP = 0.001; // 0.1% flux -> current -> flux
var TOL_SPOT = 0.01;       // 1% vs fresh python xraydb spot checks

// ======= Load JS modules (vm.runInThisContext pattern, as run_js_mc.js) =======
function loadJS(relPath) {
  var fullPath = path.join(BASE, relPath);
  var code = fs.readFileSync(fullPath, 'utf8');
  vm.runInThisContext(code, { filename: relPath });
}
loadJS('js/optics/00_gasmu_tables.js');
loadJS('js/optics/07_ion_chamber.js');

var ref = JSON.parse(fs.readFileSync(
  path.join(__dirname, 'data', 'ionchamber_reference.json'), 'utf8'));

var L_CM = ref.metadata.settings.length_cm;   // 10 cm
var energies = ref.energies_keV;              // 41 points, 5..25 keV
var gases = ['N2', 'He', 'Ar', 'air'];
var failures = 0;

function relErr(a, b) { return Math.abs(a / b - 1); }

// ======= 1. Full grid: icCurrent vs reference =======
console.log('=== 1. icCurrent vs xraydb reference grid (L=' + L_CM +
  ' cm, 1 atm, 1e10 ph/s) ===');
console.log('gas  | n  | max rel err | mean rel err | @E_keV');
var g, i;
for (g = 0; g < gases.length; g++) {
  var gas = gases[g];
  var refCur = ref.results[gas].current_A_per_1e10phps;
  var maxErr = 0, sumErr = 0, maxAt = 0;
  for (i = 0; i < energies.length; i++) {
    var cur = icCurrent(1e10, gas, L_CM, energies[i]);
    var err = relErr(cur, refCur[i]);
    sumErr += err;
    if (err > maxErr) { maxErr = err; maxAt = energies[i]; }
    if (err > TOL_GRID) {
      console.log('  FAIL ' + gas + ' @' + energies[i] + ' keV: js=' + cur +
        ' ref=' + refCur[i] + ' rel=' + err.toExponential(3));
      failures++;
    }
  }
  console.log(gas + (gas.length < 3 ? '  ' : ' ') + ' | ' + energies.length +
    ' | ' + maxErr.toExponential(3) + '   | ' +
    (sumErr / energies.length).toExponential(3) + '    | ' + maxAt);
}

// ======= 2. Round-trip + transmitted fraction =======
console.log('\n=== 2. icFluxFromCurrent round-trip + transmitted fraction ===');
var rtMax = 0, tfMax = 0;
for (g = 0; g < gases.length; g++) {
  for (i = 0; i < energies.length; i++) {
    var flux0 = 3.7e11;
    var cA = icCurrent(flux0, gases[g], L_CM, energies[i]);
    var back = icFluxFromCurrent(cA, gases[g], L_CM, energies[i]);
    var rt = relErr(back.incident_phps, flux0);
    if (rt > rtMax) rtMax = rt;
    if (rt > TOL_ROUNDTRIP) {
      console.log('  FAIL round-trip ' + gases[g] + ' @' + energies[i] +
        ' keV: rel=' + rt.toExponential(3));
      failures++;
    }
    // transmitted fraction vs reference (1 - atten_total)
    var tfRef = 1 - ref.results[gases[g]].atten_total[i];
    var tf = relErr(back.transmitted_fraction, tfRef);
    if (tf > tfMax) tfMax = tf;
    if (tf > TOL_GRID) {
      console.log('  FAIL transmitted ' + gases[g] + ' @' + energies[i] +
        ' keV: js=' + back.transmitted_fraction + ' ref=' + tfRef);
      failures++;
    }
    // icTransmittedFraction must agree with the struct field
    var tf2 = icTransmittedFraction(gases[g], L_CM, energies[i]);
    if (Math.abs(tf2 - back.transmitted_fraction) > 1e-15) {
      console.log('  FAIL icTransmittedFraction mismatch ' + gases[g]);
      failures++;
    }
  }
}
console.log('round-trip max rel err:       ' + rtMax.toExponential(3) +
  ' (tol ' + TOL_ROUNDTRIP + ')');
console.log('transmitted-frac max rel err: ' + tfMax.toExponential(3) +
  ' (tol ' + TOL_GRID + ')');

// ======= 3. Spot checks vs fresh python xraydb 4.5.8 calls =======
// Constants computed 2026-06-12 with python 3.11.4 + xraydb 4.5.8
// (same install that generated the tables), commands:
//   MIX : ionchamber_fluxes(gas={'nitrogen':0.7,'argon':0.3}, volts=1,
//           length=10, energy=10000, sensitivity=1, sensitivity_units='A/V')
//           -> I_per_1e10 = 1e10/fl.incident; trans = fl.transmitted/fl.incident
//   OFFG: ionchamber_fluxes(gas='nitrogen', ..., energy=7770) (off-grid E)
//   PRES: xraydb has no pressure argument -> closed-form chain (verified
//           <1e-12 vs the program by run_ionchamber_reference.py) with
//           mu_k = material_mu('argon', 12340, density=0.001784*0.2, kind=k)
//           (program-computed mu at the scaled density; mu linear in density),
//           Ec = compton_energies(12340).electron_mean = 279.706658 eV, W=26.4
var SPOT = [
  { name: 'mixture N2:0.7+Ar:0.3 @10 keV',
    gas: { N2: 0.7, Ar: 0.3 }, E: 10.0, opts: undefined,
    I_per_1e10: 3.0221865199e-07, trans: 6.8939435107e-01 },
  { name: 'off-grid pure N2 @7.77 keV',
    gas: 'N2', E: 7.77, opts: undefined,
    I_per_1e10: 6.6759220250e-08, trans: 9.0196049799e-01 },
  { name: 'pressure Ar 0.2 atm @12.34 keV',
    gas: 'Ar', E: 12.34, opts: { pressure_atm: 0.2 },
    I_per_1e10: 1.7117835808e-07, trans: 8.8341649456e-01 }
];
console.log('\n=== 3. Spot checks vs fresh python xraydb calls ===');
var s;
for (s = 0; s < SPOT.length; s++) {
  var sc = SPOT[s];
  var iJs = icCurrent(1e10, sc.gas, L_CM, sc.E, sc.opts);
  var tJs = icTransmittedFraction(sc.gas, L_CM, sc.E, sc.opts);
  var eI = relErr(iJs, sc.I_per_1e10);
  var eT = relErr(tJs, sc.trans);
  var ok = (eI <= TOL_SPOT && eT <= TOL_SPOT);
  if (!ok) failures++;
  console.log((ok ? 'PASS ' : 'FAIL ') + sc.name +
    ': I rel=' + eI.toExponential(3) + ', trans rel=' + eT.toExponential(3));
}

// ======= 4. both_carriers switch =======
console.log('\n=== 4. both_carriers switch ===');
var i2 = icCurrent(1e10, 'N2', L_CM, 10.0);
var i1 = icCurrent(1e10, 'N2', L_CM, 10.0, { both_carriers: false });
if (Math.abs(i1 / i2 - 0.5) < 1e-12) {
  console.log('PASS both_carriers=false -> exactly half current (N=1 vs N=2)');
} else {
  console.log('FAIL both_carriers ratio = ' + (i1 / i2));
  failures++;
}

console.log('\n' + (failures === 0 ?
  'ALL CHECKS PASSED' : failures + ' FAILURE(S)'));
process.exit(failures === 0 ? 0 : 1);
