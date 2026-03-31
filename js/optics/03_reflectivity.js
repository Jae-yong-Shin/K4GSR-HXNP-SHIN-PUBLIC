'use strict';
// ===== optics/03_reflectivity.js — Mirror Reflectivity (Shadow4 PreRefl / Born & Wolf) =====
// @module optics/03_reflectivity
// @exports mirrorCut, mirrorR, optConst
// Extracted from 02_physics.js (DDD Phase 2)
// Ref: shadow4/physical_models/prerefl/prerefl.py
//   reflectivity_amplitudes_fresnel (Born & Wolf 6th ed. p.40)
//   Debye-Waller roughness factor

/** Optical constants (delta, beta). @param {number} E - keV @param {{Z:number,A:number,rho:number}} mat @returns {{delta:number,beta:number}} */
function optConst(E,mat){
  // DABAX-equivalent lookup from pre-computed xraylib tables (00_optconst_tables.js)
  // ZF1 = 2*delta, ZF2 = 2*beta at 10 eV steps from 3-30 keV
  if(typeof OPTCONST_TABLES!=='undefined'){
    var key=null;
    if(mat.Z===45)key='Rh';else if(mat.Z===78)key='Pt';else if(mat.Z===14)key='Si';
    if(key&&OPTCONST_TABLES[key]){
      var tbl=OPTCONST_TABLES[key];
      var idx=(E-OPTCONST_TABLES.E_min_keV)/OPTCONST_TABLES.E_step_keV;
      var i=Math.floor(idx);
      if(i<0)i=0;
      if(i>=OPTCONST_TABLES.N-1)i=OPTCONST_TABLES.N-2;
      var frac=idx-i;
      if(frac<0)frac=0;if(frac>1)frac=1;
      var zf1=tbl.ZF1[i]*(1-frac)+tbl.ZF1[i+1]*frac;
      var zf2=tbl.ZF2[i]*(1-frac)+tbl.ZF2[i+1]*frac;
      return{delta:zf1/2,beta:zf2/2};
    }
  }
  // Fallback: piecewise power-law (legacy, for materials not in tables)
  var Ne=mat.rho/1e6*1e6*NA*mat.Z/mat.A;
  var lm=HC/E*1e-10;
  var delta=Ne*2.8179e-15*lm*lm/(2*Math.PI);
  var mu_rho;
  if(mat.Z===45){
    if(E>23.22)mu_rho=120*Math.pow(23.22/E,2.8);
    else if(E>3.004)mu_rho=30*Math.pow(10/E,2.75);
    else mu_rho=250*Math.pow(3.0/E,2.75);
  }else if(mat.Z===78){
    if(E>13.88)mu_rho=220*Math.pow(15/E,2.8);
    else if(E>11.56)mu_rho=450*Math.pow(11.56/E,2.7);
    else if(E>3.3)mu_rho=115*Math.pow(10/E,2.8);
    else mu_rho=600*Math.pow(3.3/E,2.75);
  }else{
    if(E>1.839)mu_rho=20*Math.pow(10/E,2.8);
    else mu_rho=5000*Math.pow(1.839/E,2.8);
  }
  var beta=mu_rho*mat.rho/1e6*100*lm/(4*Math.PI);
  return{delta:delta,beta:beta};
}
// Born & Wolf complex Fresnel reflectivity + Debye-Waller roughness
// Shadow4: PreRefl.reflectivity_amplitudes_fresnel (method=0)
//   Rs = |(sin(th) - sqrt(sin^2(th) - 2delta + 2i*beta))/(sin(th) + sqrt(sin^2(th) - 2delta + 2i*beta))|^2
//   DW = exp(-(4pi sin(th) sigma/lambda)^2)  [sigma=RMS roughness in A, lambda in A]
/** Mirror reflectivity (Born & Wolf + Debye-Waller). @param {number} E - keV @param {number} th_mrad - grazing angle (mrad) @param {{Z:number,A:number,rho:number}} mat @param {number} [roughness_A=0] - RMS roughness (Angstrom) @returns {number} R in [0, 0.99] */
function mirrorR(E,th_mrad,mat,roughness_A){
  var oc=optConst(E,mat),th=th_mrad*1e-3;
  // Grazing angle -> sin(th) (exact for all angles)
  var sth=(th>0.05)?Math.sin(th):th; // small-angle approx OK below 50 mrad
  // Complex argument: sin^2(th) - 2delta + 2i*beta
  var p=sth*sth-2*oc.delta; // real part
  var qi=2*oc.beta;          // imaginary part
  var mag=Math.sqrt(p*p+qi*qi); // modulus
  // Complex square root: A + iB = sqrt(p + i*qi)
  var A=Math.sqrt(Math.max(0,(p+mag)*0.5));
  var B=Math.sqrt(Math.max(0,(-p+mag)*0.5));
  // |rs|^2 = ((sin(th) - A)^2 + B^2) / ((sin(th) + A)^2 + B^2)
  var num=(sth-A)*(sth-A)+B*B;
  var den=(sth+A)*(sth+A)+B*B;
  var R=(den>1e-30)?num/den:0.99;
  // Debye-Waller roughness damping (Shadow4 PreRefl convention)
  if(roughness_A>0){
    var lam_A=HC/E; // wavelength in A (HC=12.3984 keV*A)
    R*=Math.exp(-Math.pow(4*Math.PI*sth*roughness_A/lam_A,2));
  }
  return Math.min(.99,Math.max(0,R));
}
function mirrorCut(th_mrad,mat){for(var e=3;e<60;e+=.5)if(mirrorR(e,th_mrad,mat)<.5)return e;return 60;}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof mirrorCut!=="undefined")globalThis.mirrorCut=mirrorCut;
if(typeof mirrorR!=="undefined")globalThis.mirrorR=mirrorR;
if(typeof optConst!=="undefined")globalThis.optConst=optConst;
