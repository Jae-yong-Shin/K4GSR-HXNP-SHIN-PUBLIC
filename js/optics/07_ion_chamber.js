'use strict';
// ===== optics/07_ion_chamber.js - ion-chamber response model (Phase 1 / A3) =====
// Port of xraydb.ionchamber_fluxes (xraydb 4.5.8, xraydb/xray.py lines
// 1048-1188) -- the same physics as the XAFSmass flux calculator
// (Klementiev & Chernikov 2016, J. Synchrotron Rad. 23).
// Porting recipe: docs/tasks/TASK_A3_IONCHAMBER.md
// Validation:     paper/validation/run_ionchamber_js_check.js
//                 (vs paper/validation/data/ionchamber_reference.json,
//                  all 4 gases x 41 energies within <=1%)
//
// Formula chain (extracted from the xraydb SOURCE, verified to <1e-12
// against the program at every reference grid point by
// paper/validation/run_ionchamber_reference.py):
//   mu_k        = gas linear attenuation coefficient [1/cm] at the xraydb
//                 materials-DB default density (~1 atm); k in {photo, incoh,
//                 total}; tables in js/optics/00_gasmu_tables.js
//   atten_total = 1 - exp(-L_cm * mu_total)
//   atten_k     = atten_total * mu_k / mu_total      (k = photo, incoh)
//   I [A]       = flux [ph/s] * e * N_carriers
//                 * (E_eV*atten_photo + Ec_eV*atten_incoh) / W
// Coherent scattering attenuates the beam (it is inside mu_total) but
// creates NO current (only photo + incoherent terms ionize the gas).
// Gas mixtures: mu_k and W are weight-fraction-weighted averages of the
// pure-gas values (fractions normalized to their sum), per xraydb.
// Pressure: mu is linear in density, so opts.pressure_atm scales all mu_k.
//
// SimIOC wiring point (do NOT wire here -- 02_epics.js has pending changes
// on another branch; wiring happens in the merge session):
//   js/control/02_epics.js  BL10:IC1:Current placeholder
//   (currently photonFlux(state.energy)*1.6e-19)  becomes
//   icCurrent(sampleFlux(), 'N2', 10, state.energy)
//   (sampleFlux = sample-flux SSOT; keep the cold-start '-' gating).

// Effective ionization potential W [eV per ion pair].
// Source: G. F. Knoll, Radiation Detection and Measurement, Table 5-1, and
// ICRU Report 31 (1979) -- identical to xraydb ionization_potential().
var IC_W_VALUES = {
  N2: 34.8,   // nitrogen
  He: 41.3,   // helium
  Ar: 26.4,   // argon
  air: 33.8   // dry air
};

// Elementary charge [C] (exact, SI 2019 -- same constant xraydb uses)
var IC_QCHARGE = 1.602176634e-19;

// Mean energy of the Compton-scattered electron [eV] vs incident E [keV].
// 41-point table copied verbatim from paper/validation/data/
// ionchamber_reference.json (compton_electron_mean_eV), itself
// xraydb compton_energies().electron_mean = pre-tabulated integration over
// the Klein-Nishina cross-section (xraydb native grid: 200-500 eV spacing
// in this range). Linear interpolation with end clamping -- xraydb uses
// np.interp, which is also linear + clamped.
var IC_COMPTON_E_KEV = [
  5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5,
  13, 13.5, 14, 14.5, 15, 15.5, 16, 16.5, 17, 17.5, 18, 18.5, 19, 19.5,
  20, 20.5, 21, 21.5, 22, 22.5, 23, 23.5, 24, 24.5, 25
];
var IC_COMPTON_ELECTRON_MEAN_EV = [
  47.639032, 57.491892, 68.240869, 79.878902, 92.399002, 105.79425,
  120.05778, 135.1828, 151.1626, 167.99051, 185.65993, 204.57858,
  223.49724, 244.06012, 264.62301, 286.80485, 308.98669, 332.76269,
  356.5387, 381.88454, 407.23038, 434.1222, 461.01401, 489.42838,
  517.84275, 547.7567, 577.67064, 609.06162, 640.4526, 673.29848,
  706.14436, 741.12937, 776.11438, 811.09939, 846.0844, 883.85154,
  921.61867, 959.3858, 997.15294, 1036.9556, 1076.7582
];

/** Compton electron mean energy [eV] at incident E [keV] (linear interp, clamped). */
function _icComptonElectronMean(E_keV) {
  var ex = IC_COMPTON_E_KEV, ey = IC_COMPTON_ELECTRON_MEAN_EV;
  var n = ex.length;
  if (E_keV <= ex[0]) return ey[0];
  if (E_keV >= ex[n - 1]) return ey[n - 1];
  // uniform 0.5 keV grid -> direct index
  var idx = (E_keV - ex[0]) / 0.5;
  var i = Math.floor(idx);
  if (i >= n - 1) i = n - 2;
  var t = (E_keV - ex[i]) / (ex[i + 1] - ex[i]);
  return ey[i] * (1 - t) + ey[i + 1] * t;
}

/** Canonicalize a gas name to a GASMU_TABLES / IC_W_VALUES key (or null). */
function _icGasKey(name) {
  if (typeof name !== 'string') return null;
  var s = name.toLowerCase();
  if (s === 'n2' || s === 'nitrogen') return 'N2';
  if (s === 'he' || s === 'helium') return 'He';
  if (s === 'ar' || s === 'argon') return 'Ar';
  if (s === 'air') return 'air';
  return null;
}

/**
 * Resolve gas spec -> weighted mu values [1/cm] and W [eV/pair].
 * @param {string|Object} gas - 'N2'|'He'|'Ar'|'air' or weight-fraction map
 *        e.g. {N2:0.7, Ar:0.3} (fractions normalized to their sum, per xraydb)
 * @param {number} E_keV
 * @param {Object} [opts] - {pressure_atm:1} scales mu linearly (mu ~ density)
 * @returns {{muPhoto:number, muIncoh:number, muTotal:number, W:number}|null}
 */
function _icResolveGas(gas, E_keV, opts) {
  var spec = gas;
  if (typeof spec === 'string') {
    var k0 = _icGasKey(spec);
    if (k0 === null) return null;
    spec = {};
    spec[k0] = 1.0;
  }
  if (!spec || typeof spec !== 'object') return null;
  var total = 0, comps = [], name, key, frac;
  for (name in spec) {
    if (!Object.prototype.hasOwnProperty.call(spec, name)) continue;
    key = _icGasKey(name);
    frac = spec[name];
    if (key === null || !(frac > 0)) return null;
    total += frac;
    comps.push([key, frac]);
  }
  if (!(total > 0) || comps.length === 0) return null;
  var muP = 0, muI = 0, muT = 0, W = 0, i, w;
  for (i = 0; i < comps.length; i++) {
    key = comps[i][0];
    w = comps[i][1] / total;
    muP += w * gasMuInterp(key, E_keV, 'photo');
    muI += w * gasMuInterp(key, E_keV, 'incoh');
    muT += w * gasMuInterp(key, E_keV, 'total');
    W += w * IC_W_VALUES[key];
  }
  var p = 1.0;
  if (opts && typeof opts.pressure_atm === 'number' && opts.pressure_atm > 0) {
    p = opts.pressure_atm;
  }
  return { muPhoto: muP * p, muIncoh: muI * p, muTotal: muT * p, W: W };
}

/**
 * Attenuation split for a gas column.
 * @returns {{attenTotal:number, attenPhoto:number, attenIncoh:number, W:number}|null}
 */
function _icAtten(gas, length_cm, E_keV, opts) {
  var r = _icResolveGas(gas, E_keV, opts);
  if (r === null || !(length_cm > 0) || !(r.muTotal > 0)) return null;
  var aT = 1 - Math.exp(-length_cm * r.muTotal);
  return {
    attenTotal: aT,
    attenPhoto: aT * r.muPhoto / r.muTotal,
    attenIncoh: aT * r.muIncoh / r.muTotal,
    W: r.W
  };
}

/** Absorbed (current-generating) energy per incident photon [eV]. */
function _icAbsorbedEnergy(att, E_keV, opts) {
  var nCarriers = (opts && opts.both_carriers === false) ? 1 : 2;
  var withCompton = !(opts && opts.with_compton === false);
  var Ec = withCompton ? _icComptonElectronMean(E_keV) : 0;
  return nCarriers * (E_keV * 1000.0 * att.attenPhoto + Ec * att.attenIncoh);
}

/**
 * Fraction of the incident flux transmitted through the gas column
 * (coherent + incoherent + photo all attenuate the beam).
 * @param {string|Object} gas - 'N2'|'He'|'Ar'|'air' or {name: weightFraction}
 * @param {number} length_cm - active length [cm]
 * @param {number} E_keV - photon energy [keV] (engine range 5-25)
 * @param {Object} [opts] - {pressure_atm:1}
 * @returns {number} transmitted fraction in (0,1], or NaN on bad input
 */
function icTransmittedFraction(gas, length_cm, E_keV, opts) {
  var att = _icAtten(gas, length_cm, E_keV, opts);
  if (att === null) return NaN;
  return 1 - att.attenTotal;
}

/**
 * Ion-chamber current [A] from incident flux.
 * @param {number} flux_phps - incident flux [photons/s]
 * @param {string|Object} gas - 'N2'|'He'|'Ar'|'air' or {name: weightFraction}
 * @param {number} length_cm - active length [cm]
 * @param {number} E_keV - photon energy [keV]
 * @param {Object} [opts] - {pressure_atm:1, both_carriers:true (N=2; false->1),
 *        with_compton:true}
 * @returns {number} current [A], or NaN on bad input
 */
function icCurrent(flux_phps, gas, length_cm, E_keV, opts) {
  var att = _icAtten(gas, length_cm, E_keV, opts);
  if (att === null || !(flux_phps >= 0)) return NaN;
  var absEv = _icAbsorbedEnergy(att, E_keV, opts);
  return flux_phps * IC_QCHARGE * absEv / att.W;
}

/**
 * Inverse: incident + transmitted flux from a measured ion-chamber current.
 * @param {number} current_A - measured current [A]
 * @param {string|Object} gas / @param {number} length_cm / @param {number} E_keV
 * @param {Object} [opts] - same as icCurrent
 * @returns {{incident_phps:number, transmitted_phps:number,
 *            transmitted_fraction:number}|null}
 */
function icFluxFromCurrent(current_A, gas, length_cm, E_keV, opts) {
  var att = _icAtten(gas, length_cm, E_keV, opts);
  if (att === null || !(current_A >= 0)) return null;
  var absEv = _icAbsorbedEnergy(att, E_keV, opts);
  if (!(absEv > 0)) return null;
  var incident = current_A * att.W / (IC_QCHARGE * absEv);
  return {
    incident_phps: incident,
    transmitted_phps: incident * (1 - att.attenTotal),
    transmitted_fraction: 1 - att.attenTotal
  };
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof IC_W_VALUES!=="undefined")globalThis.IC_W_VALUES=IC_W_VALUES;
if(typeof icCurrent!=="undefined")globalThis.icCurrent=icCurrent;
if(typeof icFluxFromCurrent!=="undefined")globalThis.icFluxFromCurrent=icFluxFromCurrent;
if(typeof icTransmittedFraction!=="undefined")globalThis.icTransmittedFraction=icTransmittedFraction;
