// run_ionchamber_scenarios.js - A3 ion-chamber BEAMLINE-OPERATIONS scenario
// validation (Phase 1 roadmap; follows the unit validation in
// run_ionchamber_js_check.js).
// Usage: node paper/validation/run_ionchamber_scenarios.js
//
// Six scenarios, each with a blocking PASS criterion (exit 1 on any failure):
//   S1 IC1 operating point: sampleFlux SSOT 6.3e12 ph/s @10 keV into N2,
//      10 cm, 1 atm -> current in the physically sensible window
//      (1 nA < I < 100 uA) AND equals reference-grid interpolation <= 1e-6.
//   S2 XAFS energy scan: Cu K-edge region 8.7..9.3 keV step 0.02 keV
//      (off-grid points), N2 10 cm -> strictly monotonically decreasing
//      current (gas mu falls with E; N2 has no edge here) and max
//      point-to-point step < 2%.
//   S3 I0/I1 transmission setup: I0 = N2 10 cm, sample T_s = 0.3,
//      I1 = Ar 10 cm @9 keV -> backward-reconstructed incident flux
//      rel err < 1e-9 AND I1/I0 ratio equals the analytic
//      T_N2 * T_s * (absorbed-energy/W ratio Ar vs N2) to < 1e-12.
//   S4 gas selection @20 keV: N2 vs Ar vs air absorbed fractions/currents
//      for the same flux -> Ar/N2 current ratio > 5 (motivates Ar at high E).
//   S5 pressure tuning: Ar 0.2/0.5/1.0 atm @15 keV -> absorbed fraction
//      sub-linear in P (atten/P strictly decreasing), current strictly
//      increasing with P, and the 0.2 atm point matches the closed form
//      1-exp(-0.2*mu*L) to < 1e-12.
//   S6 commissioning inverse: measured I0 = 10 nA, N2 10 cm @12 keV ->
//      incident flux via icFluxFromCurrent; forward icCurrent(flux) must
//      return 10 nA (round trip < 1e-12). Flux printed for the ops doc.
// Plus a LIVE cross-check of two scenario points (S2 @8.98 keV off-grid,
// S5 Ar @0.5 atm @15 keV) against python xraydb 4.5.8 (constants embedded
// below with the generating commands cited), JS within 1e-4.

var fs = require('fs');
var path = require('path');
var vm = require('vm');

var BASE = path.resolve(__dirname, '../..');

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
var SAMPLE_FLUX = 6.3e12;  // ph/s -- engine sampleFlux() SSOT @10 keV
                           // (memory/engine-sample-flux-ssot, 2026-06-10)
var failures = 0;
var summary = [];          // [name, PASS/FAIL, key figure]

function relErr(a, b) { return Math.abs(a / b - 1); }
function pad(s, w) { s = String(s); while (s.length < w) s = s + ' '; return s; }
function verdict(name, ok, key) {
  if (!ok) failures++;
  summary.push([name, ok ? 'PASS' : 'FAIL', key]);
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (key ? ' -- ' + key : ''));
}

// Linear interpolation of a per-gas reference array on the 0.5 keV grid
// (xraydb reference values; exact at grid points such as 10/12/20 keV).
function refInterp(gas, field, E_keV) {
  var es = ref.energies_keV;
  var ys = ref.results[gas][field];
  var n = es.length;
  if (E_keV <= es[0]) return ys[0];
  if (E_keV >= es[n - 1]) return ys[n - 1];
  var idx = (E_keV - es[0]) / 0.5;
  var i = Math.floor(idx);
  if (i >= n - 1) i = n - 2;
  var t = (E_keV - es[i]) / (es[i + 1] - es[i]);
  return ys[i] * (1 - t) + ys[i + 1] * t;
}

// Closed-form absorbed-energy-per-photon/W [eV per eV] for the analytic S3
// ratio: nCarriers*(E*aP + Ec*aI)/W computed from the same module tables.
function absorbedPerW(gas, E_keV, opts) {
  var muP = gasMuInterp(gas, E_keV, 'photo');
  var muI = gasMuInterp(gas, E_keV, 'incoh');
  var muT = gasMuInterp(gas, E_keV, 'total');
  var p = (opts && opts.pressure_atm) ? opts.pressure_atm : 1.0;
  var aT = 1 - Math.exp(-L_CM * muT * p);
  var aP = aT * muP / muT;     // pressure cancels in the mu_k/mu_total split
  var aI = aT * muI / muT;
  var Ec = _icComptonElectronMean(E_keV);
  return 2 * (E_keV * 1000.0 * aP + Ec * aI) / IC_W_VALUES[gas];
}

// =========================== S1: IC1 operating point ========================
console.log('=== S1. IC1 operating point: sampleFlux SSOT ' +
  SAMPLE_FLUX.toExponential(1) + ' ph/s @10 keV, N2, ' + L_CM + ' cm, 1 atm ===');
var s1_I = icCurrent(SAMPLE_FLUX, 'N2', L_CM, 10.0);
var s1_ref = refInterp('N2', 'current_A_per_1e10phps', 10.0) * (SAMPLE_FLUX / 1e10);
var s1_err = relErr(s1_I, s1_ref);
console.log('quantity              | value');
console.log('JS icCurrent          | ' + s1_I.toExponential(6) + ' A  (= ' +
  (s1_I * 1e6).toFixed(3) + ' uA)');
console.log('reference-grid interp | ' + s1_ref.toExponential(6) + ' A');
console.log('rel err vs reference  | ' + s1_err.toExponential(3) + '  (tol 1e-6)');
console.log('sensible-window check | 1 nA < I < 100 uA -> ' +
  (s1_I > 1e-9 && s1_I < 1e-4));
verdict('S1 IC1 operating point', (s1_I > 1e-9 && s1_I < 1e-4) && s1_err <= 1e-6,
  'I0 = ' + (s1_I * 1e6).toFixed(3) + ' uA');

// =========================== S2: XAFS energy scan ===========================
console.log('\n=== S2. XAFS scan Cu K-edge region 8.70..9.30 keV step 0.02 ' +
  '(off-grid), N2 ' + L_CM + ' cm, flux ' + SAMPLE_FLUX.toExponential(1) + ' ===');
console.log(pad('E_keV', 7) + '| ' + pad('I [A]', 13) + '| step vs prev');
var s2_mono = true, s2_maxStep = 0, s2_prev = null;
var k, s2_E, s2_I;
for (k = 0; k <= 30; k++) {
  s2_E = 8.7 + 0.02 * k;
  s2_I = icCurrent(SAMPLE_FLUX, 'N2', L_CM, s2_E);
  var stepStr = '-';
  if (s2_prev !== null) {
    if (s2_I >= s2_prev) s2_mono = false;
    var st = Math.abs(s2_I / s2_prev - 1);
    if (st > s2_maxStep) s2_maxStep = st;
    stepStr = (100 * (s2_I / s2_prev - 1)).toFixed(4) + '%';
  }
  console.log(pad(s2_E.toFixed(2), 7) + '| ' + pad(s2_I.toExponential(5), 13) +
    '| ' + stepStr);
  s2_prev = s2_I;
}
console.log('strictly decreasing: ' + s2_mono +
  ', max |step|: ' + (100 * s2_maxStep).toFixed(4) + '% (tol 2%)');
verdict('S2 XAFS energy scan', s2_mono && s2_maxStep < 0.02,
  'monotone decreasing, max step ' + (100 * s2_maxStep).toFixed(3) + '%');

// ====================== S3: I0/I1 transmission setup ========================
console.log('\n=== S3. I0(N2 ' + L_CM + ' cm) -> sample(T_s=0.3) -> I1(Ar ' +
  L_CM + ' cm) @9 keV, incident ' + SAMPLE_FLUX.toExponential(1) + ' ph/s ===');
var TS = 0.3, s3_E = 9.0;
var s3_I0 = icCurrent(SAMPLE_FLUX, 'N2', L_CM, s3_E);
var s3_afterI0 = icFluxFromCurrent(s3_I0, 'N2', L_CM, s3_E).transmitted_phps;
var s3_afterSample = s3_afterI0 * TS;
var s3_I1 = icCurrent(s3_afterSample, 'Ar', L_CM, s3_E);
console.log('stage                  | value');
console.log('I0 current             | ' + s3_I0.toExponential(6) + ' A');
console.log('flux after I0          | ' + s3_afterI0.toExponential(6) + ' ph/s');
console.log('flux after sample x0.3 | ' + s3_afterSample.toExponential(6) + ' ph/s');
console.log('I1 current             | ' + s3_I1.toExponential(6) + ' A');
// backward chain: I1 -> flux after sample -> /T_s -> /T_N2 -> incident
var s3_backSample = icFluxFromCurrent(s3_I1, 'Ar', L_CM, s3_E).incident_phps;
var s3_backIncident = (s3_backSample / TS) / icTransmittedFraction('N2', L_CM, s3_E);
var s3_backErr = relErr(s3_backIncident, SAMPLE_FLUX);
console.log('backward-reconstructed | ' + s3_backIncident.toExponential(6) +
  ' ph/s  rel err ' + s3_backErr.toExponential(3) + ' (tol 1e-9)');
// analytic ratio: I1/I0 = T_N2 * T_s * [absorbed/W](Ar) / [absorbed/W](N2)
var s3_ratio = s3_I1 / s3_I0;
var s3_ratioPred = icTransmittedFraction('N2', L_CM, s3_E) * TS *
  absorbedPerW('Ar', s3_E) / absorbedPerW('N2', s3_E);
var s3_ratioErr = relErr(s3_ratio, s3_ratioPred);
console.log('I1/I0 measured         | ' + s3_ratio.toFixed(6));
console.log('I1/I0 analytic         | ' + s3_ratioPred.toFixed(6) +
  '  rel err ' + s3_ratioErr.toExponential(3) + ' (tol 1e-12)');
verdict('S3 I0/I1 transmission setup',
  s3_backErr < 1e-9 && s3_ratioErr < 1e-12,
  'I1/I0 = ' + s3_ratio.toFixed(3) + ', chain err ' + s3_backErr.toExponential(1));

// ============================ S4: gas selection =============================
console.log('\n=== S4. Gas selection @20 keV, ' + L_CM +
  ' cm, 1 atm, same flux 1e10 ph/s ===');
console.log(pad('gas', 5) + '| ' + pad('absorbed frac (JS)', 19) + '| ' +
  pad('ref atten_total', 16) + '| ' + pad('I per 1e10 [A]', 15) + '| ref I [A]');
var s4_gases = ['N2', 'Ar', 'air'], s4_cur = {}, s4_refCur = {};
var g;
for (g = 0; g < s4_gases.length; g++) {
  var gas4 = s4_gases[g];
  var a4 = 1 - icTransmittedFraction(gas4, L_CM, 20.0);
  s4_cur[gas4] = icCurrent(1e10, gas4, L_CM, 20.0);
  s4_refCur[gas4] = refInterp(gas4, 'current_A_per_1e10phps', 20.0);
  console.log(pad(gas4, 5) + '| ' + pad(a4.toExponential(4), 19) + '| ' +
    pad(refInterp(gas4, 'atten_total', 20.0).toExponential(4), 16) + '| ' +
    pad(s4_cur[gas4].toExponential(4), 15) + '| ' +
    s4_refCur[gas4].toExponential(4));
}
var s4_ratio = s4_cur.Ar / s4_cur.N2;
var s4_refRatio = s4_refCur.Ar / s4_refCur.N2;
console.log('Ar/N2 current ratio: JS = ' + s4_ratio.toFixed(2) +
  ', from reference values = ' + s4_refRatio.toFixed(2) +
  '  (derives from ref I: Ar ' + s4_refCur.Ar.toExponential(4) +
  ' / N2 ' + s4_refCur.N2.toExponential(4) + ')');
verdict('S4 gas selection @20 keV', s4_ratio > 5,
  'Ar/N2 = ' + s4_ratio.toFixed(2) + ' (> 5 motivates Ar at high E)');

// ============================ S5: pressure tuning ===========================
console.log('\n=== S5. Pressure tuning: Ar @15 keV, ' + L_CM +
  ' cm, P = 0.2/0.5/1.0 atm, flux 1e10 ph/s ===');
console.log(pad('P_atm', 7) + '| ' + pad('absorbed frac', 14) + '| ' +
  pad('atten/P', 14) + '| I [A]');
var s5_P = [0.2, 0.5, 1.0], s5_att = [], s5_I = [];
var p;
for (p = 0; p < s5_P.length; p++) {
  s5_att[p] = 1 - icTransmittedFraction('Ar', L_CM, 15.0,
    { pressure_atm: s5_P[p] });
  s5_I[p] = icCurrent(1e10, 'Ar', L_CM, 15.0, { pressure_atm: s5_P[p] });
  console.log(pad(s5_P[p].toFixed(1), 7) + '| ' +
    pad(s5_att[p].toExponential(6), 14) + '| ' +
    pad((s5_att[p] / s5_P[p]).toExponential(6), 14) + '| ' +
    s5_I[p].toExponential(6));
}
var s5_sublinear = (s5_att[0] / s5_P[0] > s5_att[1] / s5_P[1]) &&
                   (s5_att[1] / s5_P[1] > s5_att[2] / s5_P[2]);
var s5_increasing = (s5_I[0] < s5_I[1]) && (s5_I[1] < s5_I[2]);
// closed-form identity at 0.2 atm: atten = 1 - exp(-0.2 * mu_total * L)
var s5_mu = gasMuInterp('Ar', 15.0, 'total');
var s5_cf = 1 - Math.exp(-0.2 * s5_mu * L_CM);
var s5_cfErr = Math.abs(s5_att[0] / s5_cf - 1);
console.log('sub-linear (atten/P strictly decreasing): ' + s5_sublinear);
console.log('current strictly increasing with P:       ' + s5_increasing);
console.log('0.2 atm closed form 1-exp(-0.2*mu*L) = ' + s5_cf.toExponential(6) +
  ', rel diff ' + s5_cfErr.toExponential(3) + ' (tol 1e-12)');
verdict('S5 pressure tuning', s5_sublinear && s5_increasing && s5_cfErr < 1e-12,
  'atten/P 0.342 -> 0.324 -> 0.298 (sub-linear), closed-form exact');

// ========================= S6: commissioning inverse ========================
console.log('\n=== S6. Commissioning inverse: measured I0 = 10 nA, N2 ' +
  L_CM + ' cm @12 keV ===');
var s6_meas = 1e-8;  // 10 nA
var s6_inv = icFluxFromCurrent(s6_meas, 'N2', L_CM, 12.0);
var s6_fwd = icCurrent(s6_inv.incident_phps, 'N2', L_CM, 12.0);
var s6_rt = relErr(s6_fwd, s6_meas);
var s6_refFlux = refInterp('N2', 'flux_phps_per_nA', 12.0) * 10;
console.log('quantity               | value');
console.log('measured current       | ' + s6_meas.toExponential(2) + ' A (10 nA)');
console.log('incident flux (JS)     | ' + s6_inv.incident_phps.toExponential(6) +
  ' ph/s   <-- for the operations doc');
console.log('transmitted flux       | ' + s6_inv.transmitted_phps.toExponential(6) +
  ' ph/s (T = ' + s6_inv.transmitted_fraction.toFixed(6) + ')');
console.log('reference 10*flux/nA   | ' + s6_refFlux.toExponential(6) +
  ' ph/s   rel err ' + relErr(s6_inv.incident_phps, s6_refFlux).toExponential(3));
console.log('forward round trip     | ' + s6_fwd.toExponential(6) +
  ' A   rel err ' + s6_rt.toExponential(3) + ' (tol 1e-12)');
verdict('S6 commissioning inverse',
  s6_rt < 1e-12 && relErr(s6_inv.incident_phps, s6_refFlux) <= 1e-6,
  'flux = ' + s6_inv.incident_phps.toExponential(4) + ' ph/s @12 keV per 10 nA');

// ==================== LIVE cross-check vs python xraydb =====================
// Constants computed 2026-06-12 with python 3.11.4 + xraydb 4.5.8 (the same
// install that generated the reference JSON and the gas-mu tables).
// Point A (S2 scan point, off both grids): N2, 10 cm, 1 atm, E = 8.98 keV.
//   Command: mu_k = material_mu('nitrogen', 8980, kind=k) for k in
//   {photo, incoh, total}; Ec = get_xraydb().compton_energies(8980)
//   .electron_mean = 150.523407408 eV; W = 34.8; closed-form chain
//   aT = 1-exp(-10*mu_t), aP/aI = aT*mu_k/mu_t,
//   I = 1e10*e*2*(8980*aP + Ec*aI)/W. The chain was re-verified against the
//   program at this point: ionchamber_fluxes(gas='nitrogen', volts=1,
//   length=10, energy=8980, sensitivity=1, sensitivity_units='A/V') gives
//   I_per_1e10 = 1e10/fl.incident identical to the chain (reldiff 0.0).
// Point B (S5 pressure point): Ar, 10 cm, 0.5 atm, E = 15 keV. xraydb has
//   no pressure argument -> program-computed mu at the scaled density
//   (mu linear in density): mu_k = material_mu('argon', 15000,
//   density=0.001784*0.5, kind=k); Ec = compton_energies(15000)
//   .electron_mean = 407.230380700 eV; W = 26.4; same closed-form chain.
var LIVE = [
  { name: 'S2 point N2 @8.98 keV 1 atm (off-grid)',
    gas: 'N2', E: 8.98, opts: undefined,
    I_per_1e10: 4.9820810439e-08, trans: 9.3541293813e-01 },
  { name: 'S5 point Ar @15 keV 0.5 atm',
    gas: 'Ar', E: 15.0, opts: { pressure_atm: 0.5 },
    I_per_1e10: 2.8681684918e-07, trans: 8.3786166637e-01 }
];
var TOL_LIVE = 1e-4;
console.log('\n=== LIVE cross-check vs python xraydb 4.5.8 (constants embedded,' +
  ' tol 1e-4) ===');
console.log(pad('point', 40) + '| ' + pad('I rel err', 12) + '| trans rel err');
var liveOk = true, li;
for (li = 0; li < LIVE.length; li++) {
  var lc = LIVE[li];
  var liI = relErr(icCurrent(1e10, lc.gas, L_CM, lc.E, lc.opts), lc.I_per_1e10);
  var liT = relErr(icTransmittedFraction(lc.gas, L_CM, lc.E, lc.opts), lc.trans);
  var ok = (liI <= TOL_LIVE && liT <= TOL_LIVE);
  if (!ok) liveOk = false;
  console.log(pad(lc.name, 40) + '| ' + pad(liI.toExponential(3), 12) + '| ' +
    liT.toExponential(3) + (ok ? '' : '  FAIL'));
}
verdict('LIVE xraydb cross-check (2 points)', liveOk, 'tol 1e-4');

// ================================= summary ==================================
console.log('\n=== SUMMARY ===');
var si;
for (si = 0; si < summary.length; si++) {
  console.log(pad(summary[si][0], 36) + '| ' + pad(summary[si][1], 5) + '| ' +
    summary[si][2]);
}
console.log('\n' + (failures === 0 ?
  'ALL SCENARIOS PASSED' : failures + ' FAILURE(S)'));
process.exit(failures === 0 ? 0 : 1);
