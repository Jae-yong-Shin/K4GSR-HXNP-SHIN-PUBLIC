'use strict';
// ===== optics/02_crystal.js — Bragg / DCM Functions =====
// @module optics/02_crystal
// @exports braggAngle, darwinW, dcmGap, dcmRes, dcmThru, extDepth, siChi, siFf, siFh
// Extracted from 02_physics.js (DDD Phase 2)

/** Bragg angle for Si crystal. @param {number} E - energy (keV) @returns {number} angle (rad) or NaN */
function braggAngle(E){var d=D_SI[state.crystal];var s=HC/(2*d*E);return Math.abs(s)<=1?Math.asin(s):NaN;}
/** DCM crystal gap. @param {number} th - Bragg angle (rad) @returns {number} gap (mm) */
function dcmGap(th){return FIXED_EXIT/(2*Math.cos(th));}
/** DCM energy resolution dE/E. @param {number} E - energy (keV) @returns {number} */
function dcmRes(E){var th=braggAngle(E);return isNaN(th)?0:1/(N_PERIODS*Math.tan(th)*Math.PI)*0.8;}
function siFf(s){var s2=s*s;return 6.2915*Math.exp(-2.4386*s2)+3.0353*Math.exp(-32.334*s2)+1.9891*Math.exp(-0.6785*s2)+1.5410*Math.exp(-81.694*s2)+1.1407;}
function siFh(E){var th=braggAngle(E);if(isNaN(th))return 0;var s=Math.sin(th)/(HC/E);return 4*Math.SQRT2*siFf(s)*Math.exp(-0.4632*s*s);}
function siChi(E){var l=HC/E;return R_E_A*l*l*siFh(E)/(Math.PI*V_SI);}
function darwinW(E){var th=braggAngle(E);if(isNaN(th))return 0;return 2*siChi(E)/Math.sin(2*th)*206265;}
function extDepth(E){var th=braggAngle(E),Fh=siFh(E),l=HC/E;if(isNaN(th)||Fh<1e-6)return 0;return V_SI*Math.sin(th)/(R_E_A*l*Fh)*1e-4;}
// V4.36 C-3: Darwin width angular acceptance model (inline merged from 12_v435_physics.js)
function dcmThru(E) {
  var dw = darwinW(E);
  if (dw <= 0) return 0;
  var dw_rad = dw / 206265;
  var ps = photonSrc(E);
  var beamDiv = ps.Syp;    // vertical source divergence [rad]
  var R2 = 0.95;           // two-crystal peak reflectivity
  var accept = Math.min(1, dw_rad / (beamDiv + 1e-30));
  return Math.min(0.99, R2 * accept);
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof braggAngle!=="undefined")globalThis.braggAngle=braggAngle;
if(typeof darwinW!=="undefined")globalThis.darwinW=darwinW;
if(typeof dcmGap!=="undefined")globalThis.dcmGap=dcmGap;
if(typeof dcmRes!=="undefined")globalThis.dcmRes=dcmRes;
if(typeof dcmThru!=="undefined")globalThis.dcmThru=dcmThru;
if(typeof extDepth!=="undefined")globalThis.extDepth=extDepth;
if(typeof siChi!=="undefined")globalThis.siChi=siChi;
if(typeof siFf!=="undefined")globalThis.siFf=siFf;
if(typeof siFh!=="undefined")globalThis.siFh=siFh;
