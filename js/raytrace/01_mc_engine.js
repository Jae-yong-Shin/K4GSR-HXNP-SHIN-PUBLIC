'use strict';
// ===== raytrace/01_mc_engine.js — Shadow4-like MC Ray Trace Engine =====
// @module raytrace/01_mc_engine
// @exports ALIGN_MC_RAYS, M1_DM, M1_F, M1_P, M2_DM, M2_F, MC_NRAYS, MIRROR_STRIPES, M_PARAMS, PROFILE_MC_RAYS, RS, _alignBpmCenter, _applyHybridFresnel, _applySSAHybrid, _invalidateMCCache, ...
// Extracted from 14_v435_final.js + 12_v435_physics.js (DDD Phase 5c/6)
// Contains: constants, gaussRand, rayUpdateVz, kbDiffLimit, dcmBandwidth,
//   mVal, M_PARAMS, applyMirrorMC (unified), applyKBMC, applyDCM_MC (3D Bragg),
//   mcRayTrace, physics helpers (bendToFocal, getStripeMaterial, thermalSlopeError, 3D),
//   MC-based alignment signals (mirrorHalfCutSignal, mirrorRockingSignal, mcBeamWithPitch,
//   dcmRockingSignal, dcmY2Signal, mcBeamWithDCM, ALIGN_MC_RAYS, PROFILE_MC_RAYS)

// === Mirror geometry constants (extracted from 12_v435_physics.js) ===
var M1_P = 29.0, M1_Q = 29.0, M2_P = 32.0, M2_Q = 26.0;
var M1_F = 1 / (1 / M1_P + 1 / M1_Q); // sagittal -> H focus
var M2_F = 1 / (1 / M2_P + 1 / M2_Q); // tangential -> V focus
var M1_DM = M1_Q / M1_P;               // H demag 0.908
var M2_DM = M2_Q / M2_P;               // V demag 0.758
var _mcSampleCache = null, _mcSampleDirty = true;

// Invalidate MC sample cache — call when physics state changes.
// focalSpot() will re-run mcRayTrace on next call.
// Pure UI operations (tab switch, layout) should NOT call this.
// A1 (GPU): also bump the physics revision counter consumed by the opt-in
// WebGPU path (raytrace/05_mc_gpu.js) so stored GPU results are discarded
// whenever the physics state changes.
window._mcPhysicsRev = 0;
window._invalidateMCCache = function() {
  _mcSampleDirty = true;
  window._mcPhysicsRev = (window._mcPhysicsRev | 0) + 1;
};

// A1 (GPU): install an externally produced MC result (same object shape as
// mcRayTrace's return) as the focalSpot sample cache. Used by the opt-in
// WebGPU path when an async GPU run for the sample plane completes.
window._mcSetSampleCache = function(mc) {
  if (!mc) return;
  _mcSampleCache = mc;
  _mcSampleDirty = false;
};

// Ray stride: [x, y, vx, vy, vz, w, E_eV, kbTag] per ray
// E_eV: per-ray photon energy in eV (undulator bandwidth sampling)
// kbTag: bit flag — bit0(1)=KB-V reflected, bit1(2)=KB-H reflected
//   0=direct(unfocused), 1=V-only, 2=H-only, 3=V+H(focused)
var RS = 8;

// gaussRand() now defined in shared/01_constants.js

// === sincSqRand: sample from [sin(x)/x]^2 distribution (rejection method) ===
// Returns x drawn from sinc^2(x) — slit diffraction angular pattern.
// Range [-Npi, Npi] captures central peak + N-1 side lobes on each side.
function sincSqRand() {
  var R = 4 * Math.PI; // capture central + 3 side lobes
  for (var tries = 0; tries < 200; tries++) {
    var x = (Math.random() * 2 - 1) * R;
    if (Math.abs(x) < 1e-10) return x;
    var s = Math.sin(x) / x;
    if (Math.random() < s * s) return x;
  }
  return 0; // fallback (extremely rare)
}

// === rayUpdateVz: maintain unit vector constraint ===
function rayUpdateVz(rays, o) {
  var s = rays[o + 2] * rays[o + 2] + rays[o + 3] * rays[o + 3];
  rays[o + 4] = (s < 1) ? Math.sqrt(1 - s) : 1e-10;
}

// === kbDiffLimit: KB diffraction limits [m, RMS sigma] ===
function kbDiffLimit() {
  var ln = HC / state.energy * 1e-10; // wavelength [m]
  var sinG = Math.sin(0.003);          // grazing 3 mrad
  var qV = pos('sample') - pos('kbv');
  var qH = pos('sample') - pos('kbh');
  var NA_V = 0.300 * sinG / (2 * qV);
  var NA_H = 0.100 * sinG / (2 * qH);
  return {
    sigV: 0.44 * ln / NA_V / 2.355,   // RMS [m]
    sigH: 0.44 * ln / NA_H / 2.355,
    fwhmV: 0.44 * ln / NA_V,           // FWHM [m]
    fwhmH: 0.44 * ln / NA_H
  };
}

// === dcmBandwidth: DCM energy resolution dE/E ===
function dcmBandwidth(E) {
  var th = braggAngle(E);
  if (isNaN(th)) return 0;
  var dw_rad = darwinW(E) / 206265;
  return dw_rad / Math.tan(th);
}

// === Motor value reader (safe access to MOTORS[dev][axis].value) ===
window.mVal = function(devId, axis, fb) {
  try { var d = MOTORS[devId]; return (d && d[axis] && d[axis].value !== undefined) ? d[axis].value : fb; }
  catch(e) { return fb; }
};

// === Mirror physical constants (Shadow4 ElementCoordinates equivalent) ===
var M_PARAMS = {
  m1: { type:'spherical_fixed', len:0.60, wid:0.060, thick:0.050, nomP:2.5, fp:'v', F:M1_F, rough:3.0, deflAxis:'x' },
  m2: { type:'spherical', len:0.60, wid:0.060, thick:0.050, nomP:2.5, fp:'h', F:M2_F, rough:3.0, deflAxis:'x' }
};

// === Undulator spectral envelope (importance sampling weight) ===
// Physics: Kim (1989) sinc^2 convolved with Gaussian(2*E_SPREAD)
// E_res(eps) = E_res0 * (1 + 2*eps), eps ~ N(0, E_SPREAD)
// Factor 2: E_res proportional to gamma^2 proportional to E_e^2
// Used as importance sampling weight: rays generated at DCM energy,
// weighted by undulator spectral intensity at that energy.
function _undulatorEnvelope(E_ray_keV, E_res0_keV) {
  if (E_res0_keV < 1) return 1;
  if (E_SPREAD < 1e-8) return undulatorSinc2(E_ray_keV, E_res0_keV);
  // 5-point Gaussian quadrature at eps = k * E_SPREAD, k = -2..+2
  var S = 0, W = 0;
  for (var k = -2; k <= 2; k++) {
    var gw = Math.exp(-0.5 * k * k);   // Gaussian weight (unnormalized)
    var E_res_k = E_res0_keV * (1 + 2 * k * E_SPREAD);
    S += gw * undulatorSinc2(E_ray_keV, E_res_k);
    W += gw;
  }
  return S / W;
}

// === Physics helpers ===
(function(){
  // Add missing axes to DEVICE_CONFIGS
  var dc = typeof DEVICE_CONFIGS !== 'undefined' ? DEVICE_CONFIGS : [];
  dc.forEach(function(d){
    if(d.id==='dcm'){
      if(!d.axes.chi2F) d.axes.chi2F={name:'Chi2 Piezo',pvSuffix:'Chi2F',unit:'\u03BCrad',value:0,min:-50,max:50,step:0.01,resolution:0.05};
      if(!d.axes.roll2F) d.axes.roll2F={name:'Roll2 Piezo',pvSuffix:'Roll2F',unit:'\u03BCrad',value:0,min:-50,max:50,step:0.01,resolution:0.05};
    }
  });
  if(typeof buildMotorsFromConfig==='function') buildMotorsFromConfig();

  // === Bender -> focal length ===
  // M1: fixed curvature (no bender), M2: bendable
  var BEND_P={
    m2:{nomR:2*M2_F/(2.5e-3),EI:411e9*0.06*Math.pow(0.04,3)/12}
  };
  window.bendToFocal=function(mid,pitch_mrad){
    if(mid==='m1') return M1_F; // M1 is fixed mirror — no bender
    var bp=BEND_P[mid]; if(!bp) return mid==='m2'?M2_F:M1_F;
    var bu=mVal(mid,'bend_u',0),bd=mVal(mid,'bend_d',0);
    var dC=(bu+bd)*0.5/bp.EI;
    var tC=1.0/bp.nomR+dC;
    if(Math.abs(tC)<1e-12) return 1e6;
    var R=1.0/tC,th=pitch_mrad*1e-3;
    return R*Math.sin(th)/2.0;
  };

  // === Stripe selection (y-motor based, center-to-center 2mm, stripe width 1mm) ===
  var MAT_PT = {Z:78, A:195.1, rho:21.45e6};
  var MAT_RH = {Z:45, A:102.9, rho:12.41e6};
  var MAT_SI = {Z:14, A:28.09, rho:2.33e6};
  // Coating-stripe geometry: single Pt stripe and the M2 triple Rh/Si/Pt stripes (center mm, half-width, material) for stripe selection.
  var MIRROR_STRIPES = {
    single_pt: [ {center:0, hw:15, mat:MAT_PT, name:'Pt'} ],
    triple: [
      {center:+2, hw:0.5, mat:MAT_RH, name:'Rh'},
      {center: 0, hw:0.5, mat:MAT_SI, name:'Si'},
      {center:-2, hw:0.5, mat:MAT_PT, name:'Pt'}
    ]
  };
  window.MIRROR_STRIPES = MIRROR_STRIPES;
  window.getStripeMaterial=function(mid){
    // KB-V/KB-H: Pt single coating (JTEC KB mirrors)
    if (mid === 'kbv' || mid === 'kbh') {
      return MIRROR_STRIPES.single_pt[0];
    }
    // M1: Pt single coating (always)
    if (mid === 'm1') {
      return MIRROR_STRIPES.single_pt[0];
    }
    // M2: triple stripe (Rh/Si/Pt), energy-dependent
    // M2: y-motor position determines which stripe the beam hits
    if (mid === 'm2') {
      var stripes = MIRROR_STRIPES.triple;
      var yOff = mVal(mid, 'y', 0);
      var beamOnMirror = -yOff;
      for (var i = 0; i < stripes.length; i++) {
        if (Math.abs(beamOnMirror - stripes[i].center) <= stripes[i].hw)
          return stripes[i];
      }
      return {center:0, hw:100, mat:MAT_SI, name:'Si(substrate)'};
    }
    return MIRROR_STRIPES.single_pt[0];
  };

  // === Auto stripe selection by energy ===
  // M1: always Pt (single coating)
  // M2: triple stripe (Pt/Rh/Si), energy-dependent selection:
  //   'Rh': 5-23 keV  -- standard harmonic rejection
  //   'Si': <5 keV    -- low-energy, high reflectivity
  //   'Pt': 23+ keV   -- high-energy, above Rh K-edge
  window.autoStripeForEnergy = function(E_keV) {
    state.m1stripe = 'Pt';  // M1 is always Pt
    var m2name;
    if (E_keV >= 23) m2name = 'Pt';
    else if (E_keV >= 5) m2name = 'Rh';
    else m2name = 'Si';
    // Move M2 y-motor to the corresponding stripe center position
    var stripes = MIRROR_STRIPES.triple;
    for (var i = 0; i < stripes.length; i++) {
      if (stripes[i].name === m2name) {
        var yTarget = -stripes[i].center;  // beamOnMirror = -yOff
        if (typeof MOTORS !== 'undefined' && MOTORS.m2 && MOTORS.m2.y) {
          MOTORS.m2.y.value = yTarget;
          MOTORS.m2.y.target = yTarget;
        }
        break;
      }
    }
    return m2name;
  };

  // === Thermal slope error ===
  // Thermal slope error DISABLED (all coefficients 0). The interactive engine does
  // not model mirror thermal slope errors (consistent with Manuscript Section 3,
  // which states the engine "does not model thermal deformation, mirror slope errors").
  // thermalSlopeError() therefore returns 0 and adds no angular blur at M1/M2/DCM/KB.
  var TH_K={m1:0,m2:0,dcm:0,kbv:0,kbh:0};
  window.thermalSlopeError=function(devId,E){
    var k=TH_K[devId]; if(!k) return 0;
    var bf=typeof propagateBeam==='function'?propagateBeam(pos(devId)):null;
    var pA=bf?Math.min(bf.flux*E*1.602e-19,500):0;
    return k*pA;
  };

  // === 3D helpers ===
  function rotX(a){var c=Math.cos(a),s=Math.sin(a);return[1,0,0,0,c,-s,0,s,c];}
  function rotY(a){var c=Math.cos(a),s=Math.sin(a);return[c,0,s,0,1,0,-s,0,c];}
  function rotZ(a){var c=Math.cos(a),s=Math.sin(a);return[c,-s,0,s,c,0,0,0,1];}
  function mv(m,v){return[m[0]*v[0]+m[1]*v[1]+m[2]*v[2],m[3]*v[0]+m[4]*v[1]+m[5]*v[2],m[6]*v[0]+m[7]*v[1]+m[8]*v[2]];}
  window.reflect3D=function(v,n){var d=2*(v[0]*n[0]+v[1]*n[1]+v[2]*n[2]);return[v[0]-d*n[0],v[1]-d*n[1],v[2]-d*n[2]];};
  window.labToMirror=function(p,d,th,rl,yw){
    var r1=mv(rotY(-yw),p),d1=mv(rotY(-yw),d);
    var r2=mv(rotX(-(Math.PI/2-th)),r1),d2=mv(rotX(-(Math.PI/2-th)),d1);
    return{pos:mv(rotZ(-rl),r2),dir:mv(rotZ(-rl),d2)};
  };
  window.mirrorToLab=function(p,d,th,rl,yw){
    var r1=mv(rotZ(rl),p),d1=mv(rotZ(rl),d);
    var r2=mv(rotX(Math.PI/2-th),r1),d2=mv(rotX(Math.PI/2-th),d1);
    return{pos:mv(rotY(yw),r2),dir:mv(rotY(yw),d2)};
  };
  console.log('[' + APP_VTAG + '] Helpers + axes loaded');
})();

// === Unified applyMirrorMC — Shadow4 S4SphereMirror ===
// Integrates: piezo, bender, stripe, slope error, paraxial physics
// Ref: shadow4/beamline/optical_elements/mirrors/s4_sphere_mirror.py
// Note: thin-lens kick -y/F is exact for R >> beam_size (M1/M2 R ~10km >> ~20um)
(function(){
  window.applyMirrorMC = function(rays, nR, mid, E) {
    var mp = M_PARAMS[mid]; if (!mp) return;
    var pitch = (mid==='m1') ? state.m1pitch : state.m2pitch;
    pitch += mVal(mid,'pitch_fine',0) * 1e-3;
    var F = (typeof bendToFocal==='function') ? bendToFocal(mid, pitch) : mp.F;
    var sMat = RH;
    if (typeof getStripeMaterial==='function') {
      var st = getStripeMaterial(mid);
      if (st && st.mat) sMat = st.mat;
    }
    var roll = mVal(mid,'roll',0)*1e-3;
    var yaw = mVal(mid,'yaw',0)*1e-3;
    var txOff = mVal(mid,'x',0)*1e-3;
    var tyOff = mVal(mid,'y',0)*1e-3;
    var zBeam = mVal(mid,'z',0)*1e-3;
    var tg = pitch * 1e-3;
    var dP = (pitch - mp.nomP) * 1e-3;
    var rough = mp.rough || 0;
    var sig = (typeof thermalSlopeError==='function') ? thermalSlopeError(mid,E) : 0;
    var isDeflX = (mp.deflAxis === 'x');
    var deflIdx = isDeflX ? 2 : 3;
    var crossIdx = isDeflX ? 3 : 2;
    var sinTg = Math.sin(Math.abs(tg));
    for (var i=0; i<nR; i++) {
      var o = i*RS;
      if (rays[o+5] <= 0) continue;
      var xr = rays[o]-txOff, yr = rays[o+1]-tyOff;
      var bodyPos = isDeflX ? xr : yr;
      var widthPos = isDeflX ? yr : xr;
      if (Math.abs(widthPos) > mp.wid*0.5) continue;
      if (tg > 0.5e-3) {
        var surfY = bodyPos / sinTg;
        if (Math.abs(zBeam) > 1e-7) surfY -= zBeam;
        if (Math.abs(surfY) > mp.len * 0.5) { rays[o+5]=0; continue; }
      } else {
        if (bodyPos < 0 || bodyPos > mp.thick) continue;
        if (tg <= 1e-7) { rays[o+5]=0; continue; }
        if (bodyPos > mp.len * sinTg) { rays[o+5]=0; continue; }
      }
      var lth = Math.abs(tg - rays[o+deflIdx]);
      var E_ray_keV = rays[o+6] * 0.001;
      if (typeof _noMirrorReflectivity === 'undefined' || !_noMirrorReflectivity) {
        var R = mirrorR(E_ray_keV, lth*1e3, sMat, rough);
        if (Math.random() > R) { rays[o+5]=0; continue; }
      }
      rays[o+deflIdx] += 2*dP;
      rays[o+crossIdx] += 2*tg*roll;
      rays[o+crossIdx] += 2*yaw;
      var yFoc = (mp.fp==='h') ? rays[o] : rays[o+1];
      var kick = -yFoc/F;
      if (mp.fp==='h') rays[o+2] += kick;
      else rays[o+3] += kick;
      if (sig > 1e-12) {
        if (mp.fp==='h') rays[o+2] += gaussRand()*sig;
        else rays[o+3] += gaussRand()*sig;
      }
      // M1/M2 diffraction: aperture >> beam -> negligible (R~10km >> 20um)
      rayUpdateVz(rays,o);
    }
  };

  // === Guigay Thick Bragg Reflectivity (crystalpy LINE-BY-LINE port) ===
  // Reference: crystalpy/diffraction/PerfectCrystalDiffraction.py
  //   calculateDiffractionGuigay(), is_thick=1
  // Paper: Guigay & Sanchez del Rio, J. Synchrotron Rad. (2022)
  //
  // Returns {R_s, R_p}: sigma and pi intensity reflectivities (|amplitude|^2)
  // for a single thick Bragg crystal.
  //
  // Inputs:
  //   vdn  - v_hat . n_hat (dot product of ray direction with crystal inward normal)
  //          This equals gamma_0 in S4 convention.
  //   E_keV - ray energy in keV
  //   thB  - per-ray Bragg angle [rad]
  //   psi  - {psi0_re, psi0_im, psiH_re, psiH_im, psiHb_re, psiHb_im} from crystalPsi()
  //   sig  - thermal slope error [rad], 0 if none
  //
  function _guigayThickBragg(vdn, E_keV, thB, psi, sig) {
    // --- S4 PerfectCrystalDiffraction.py line 524-527: alpha ---
    // alpha = -k^{-2} * (|H|^2 + 2 * k0.H)
    // For symmetric Bragg, H = -|H| * n_hat_inward (H points outward)
    // => k0.H = -k * |H| * vdn
    // => alpha = -(|H|/k)^2 + 2*(|H|/k)*vdn = g*(2*vdn - g)
    // where g = lambda/d = |H|/k
    var d_m = D_SI[state.crystal] * 1e-10;  // d-spacing [m]
    var lam_m = HC / E_keV * 1e-10;  // wavelength [m]
    var g = lam_m / d_m;  // = |H|/k
    var alpha = g * (2 * vdn - g);

    // --- S4 line 552-569: guigay_b = gamma_0 / gamma_H ---
    // gamma_0 = vdn (ray direction . inward normal)
    // K_H = K_0 + H; for symmetric: H = -|H|*n_hat
    // K_H . n_hat = k*vdn - |H| = k*(vdn - g)
    // |K_H|: K_H = k*v - |H|*n => |K_H|^2 = k^2 - 2k|H|vdn + |H|^2
    //       = k^2*(1 - 2g*vdn + g^2)
    // gamma_H = (K_H.n_hat)/|K_H| = (k*(vdn-g))/(k*sqrt(1-2gvdn+g^2))
    //         = (vdn - g)/sqrt(1 - 2g*vdn + g^2)
    var KH_norm_sq = 1 - 2*g*vdn + g*g;
    var KH_norm = Math.sqrt(Math.abs(KH_norm_sq));
    var gamma_H = (KH_norm > 1e-15) ? (vdn - g) / KH_norm : -vdn;
    var guigay_b = (Math.abs(gamma_H) > 1e-15) ? vdn / gamma_H : -1.0;

    // --- S4 line 1028: effective_psi_0 = conj(psi_0) ---
    // Note: S4 convention uses conj() for the effective susceptibilities
    var ep0_re = psi.psi0_re;    // Re(conj(psi0)) = Re(psi0)
    var ep0_im = -psi.psi0_im;   // Im(conj(psi0)) = -Im(psi0)

    // --- S4 line 1030: w = b * alpha/2 + eff_psi0 * (b-1)/2 ---
    // w is complex: w = b*alpha/2 + ep0*(b-1)/2
    // alpha is real, b is real, ep0 is complex
    var bAlphaHalf = guigay_b * alpha * 0.5;
    var bm1half = (guigay_b - 1) * 0.5;
    var w_re = bAlphaHalf + bm1half * ep0_re;
    var w_im = bm1half * ep0_im;

    // --- S4 line 1031: omega = pi/lambda * w ---
    var piOverLam = Math.PI / lam_m;
    var omega_re = piOverLam * w_re;
    var omega_im = piOverLam * w_im;

    // === Compute for SIGMA polarization ===
    // --- S4 line 1038-1039: effective_psi_h = conj(psiH), eff_psi_h_bar = conj(psiHbar) ---
    var eph_re = psi.psiH_re;
    var eph_im = -psi.psiH_im;
    var ephb_re = psi.psiHb_re;
    var ephb_im = -psi.psiHb_im;

    // --- S4 line 1041: uh_bar = eff_psi_h_bar * pi/lambda ---
    var uhb_re = ephb_re * piOverLam;
    var uhb_im = ephb_im * piOverLam;

    // --- S4 line 1067: asquared = (pi/lam)^2 * (b * eph * ephb + w^2) ---
    // b * eph * ephb: complex multiply
    var prod_re = eph_re * ephb_re - eph_im * ephb_im;
    var prod_im = eph_re * ephb_im + eph_im * ephb_re;
    var bprod_re = guigay_b * prod_re;
    var bprod_im = guigay_b * prod_im;
    // w^2: complex square
    var w2_re = w_re * w_re - w_im * w_im;
    var w2_im = 2 * w_re * w_im;
    // sum
    var sum_re = bprod_re + w2_re;
    var sum_im = bprod_im + w2_im;
    // asquared = (pi/lam)^2 * sum
    var piOL2 = piOverLam * piOverLam;
    var asq_re = piOL2 * sum_re;
    var asq_im = piOL2 * sum_im;

    // --- S4 line 1068-1069: aa = 1/sqrt(2) * (Im(asq)/sqrt(|asq|-Re(asq)) + i*sqrt(|asq|-Re(asq))) ---
    var asq_abs = Math.sqrt(asq_re * asq_re + asq_im * asq_im);
    var q = asq_abs - asq_re;  // |asquared| - Re(asquared)
    if (q < 1e-40) q = 1e-40;  // guard against division by zero
    var sqrtQ = Math.sqrt(q);
    var invSqrt2 = 0.7071067811865476;  // 1/sqrt(2)
    var aa_re = invSqrt2 * asq_im / sqrtQ;
    var aa_im = invSqrt2 * sqrtQ;

    // --- S4 line 1072: complex_amplitude_s = (aa + omega) / uh_bar ---
    var num_re = aa_re + omega_re;
    var num_im = aa_im + omega_im;
    // complex division: (a+bi)/(c+di) = ((ac+bd)+(bc-ad)i)/(c^2+d^2)
    var denom = uhb_re * uhb_re + uhb_im * uhb_im;
    var R_s;
    if (denom > 1e-60) {
      var cs_re = (num_re * uhb_re + num_im * uhb_im) / denom;
      var cs_im = (num_im * uhb_re - num_re * uhb_im) / denom;
      R_s = cs_re * cs_re + cs_im * cs_im;  // |amplitude|^2
    } else {
      R_s = 0;
    }

    // === Compute for PI polarization ===
    // --- S4 line 1075-1076: eff_psi_h *= cos(2*thB), eff_psi_h_bar *= cos(2*thB) ---
    var cos2thB = Math.cos(2 * thB);
    var eph_p_re = eph_re * cos2thB;
    var eph_p_im = eph_im * cos2thB;
    var ephb_p_re = ephb_re * cos2thB;
    var ephb_p_im = ephb_im * cos2thB;

    // uh_bar for pi
    var uhb_p_re = ephb_p_re * piOverLam;
    var uhb_p_im = ephb_p_im * piOverLam;

    // b * eph_p * ephb_p
    var prod_p_re = eph_p_re * ephb_p_re - eph_p_im * ephb_p_im;
    var prod_p_im = eph_p_re * ephb_p_im + eph_p_im * ephb_p_re;
    var bprod_p_re = guigay_b * prod_p_re;
    var bprod_p_im = guigay_b * prod_p_im;
    // asquared for pi (w^2 same, only b*eph*ephb changes)
    var sum_p_re = bprod_p_re + w2_re;
    var sum_p_im = bprod_p_im + w2_im;
    var asq_p_re = piOL2 * sum_p_re;
    var asq_p_im = piOL2 * sum_p_im;

    // aa for pi
    var asq_p_abs = Math.sqrt(asq_p_re * asq_p_re + asq_p_im * asq_p_im);
    var q_p = asq_p_abs - asq_p_re;
    if (q_p < 1e-40) q_p = 1e-40;
    var sqrtQp = Math.sqrt(q_p);
    var aa_p_re = invSqrt2 * asq_p_im / sqrtQp;
    var aa_p_im = invSqrt2 * sqrtQp;

    // complex_amplitude_p = (aa_p + omega) / uhb_p
    var num_p_re = aa_p_re + omega_re;
    var num_p_im = aa_p_im + omega_im;
    var denom_p = uhb_p_re * uhb_p_re + uhb_p_im * uhb_p_im;
    var R_p;
    if (denom_p > 1e-60) {
      var cp_re = (num_p_re * uhb_p_re + num_p_im * uhb_p_im) / denom_p;
      var cp_im = (num_p_im * uhb_p_re - num_p_re * uhb_p_im) / denom_p;
      R_p = cp_re * cp_re + cp_im * cp_im;
    } else {
      R_p = 0;
    }

    // Clamp to physical range [0, 1]
    if (R_s > 1) R_s = 1; if (R_s < 0) R_s = 0;
    if (R_p > 1) R_p = 1; if (R_p < 0) R_p = 0;

    return {R_s: R_s, R_p: R_p};
  }

  // === Two-Crystal HORIZONTAL DCM -- Guigay Thick Bragg (S4 line-by-line port) ===
  // Shadow4: S4Compound + crystalpy PerfectCrystalDiffraction (Guigay is_thick=1)
  // Key difference from previous version:
  //   - Uses S4's Guigay thick Bragg complex amplitude reflectivity
  //   - Weight-based (S4 style): rays[o+5] *= R, NOT stochastic accept/reject
  //   - This preserves divergence angular distribution (no non-physical filtering)
  window.applyDCM_MC = function(rays, nR, E) {
    var thB_center = braggAngle(E);
    if (isNaN(thB_center)) return;
    var cosThB_center = Math.cos(thB_center);
    var d_spacing = D_SI[state.crystal];  // d-spacing in Angstrom

    // Pre-fetch crystal susceptibility table for center energy
    var psi_center = (typeof crystalPsi === 'function') ? crystalPsi(E, state.crystal) : null;

    // Refraction correction: dynamical Bragg angle = kinematic + dth_refrac
    // dth = -Re(psi_0) / sin(2*thB)  (standard dynamical diffraction theory)
    // This shifts the crystal to the rocking curve peak.
    // Without this, the crystal sits on the rocking curve tail and gives ~0 throughput.
    var dth_refrac = 0;
    if (psi_center) {
      var sin2thB = Math.sin(2 * thB_center);
      if (Math.abs(sin2thB) > 1e-10) {
        dth_refrac = -psi_center.psi0_re / sin2thB;
      }
    }
    // Apply refraction correction AFTER reading motor angle.
    // updateEnergy() sets the motor to the kinematic Bragg angle;
    // the refraction correction adjusts the effective crystal orientation.
    var actualTheta = mVal('dcm','theta', thB_center*180/Math.PI) * Math.PI / 180;
    actualTheta += dth_refrac;
    var cosThA = Math.cos(actualTheta), sinThA = Math.sin(actualTheta);
    var dTh2 = (mVal('dcm','dTheta2',0) + mVal('dcm','dTheta2F',0)*0.2063) * 4.848e-6;
    var chi1 = mVal('dcm','chi1',0) * 4.848e-6;
    var y1_x = mVal('dcm','y1',0) * 1e-3;
    var roll2 = mVal('dcm','roll2',0) * 4.848e-6;
    var OFFSET_M = FIXED_EXIT * 1e-3;
    var d_perp = OFFSET_M / (2 * cosThB_center);
    var gap_m = mVal('dcm','z2', d_perp * 1000) * 1e-3;
    var cW = 0.060;
    var cThick = 0.010;
    var sig = (typeof thermalSlopeError === 'function') ? thermalSlopeError('dcm', E) : 0;

    // theta ~ 0: DCM disengaged (half-cut mode) -- pure body blocking
    if (Math.abs(actualTheta) < 1e-4) {
      for (var i = 0; i < nR; i++) {
        var o = i * RS;
        if (rays[o+5] <= 0) continue;
        if (Math.abs(rays[o+1]) > cW * 0.5) continue;
        var xr1 = rays[o] - y1_x;
        if (xr1 >= 0 && xr1 <= cThick) rays[o+5] = 0;
      }
      return;
    }

    var n1x = cosThA, n1y = chi1 * cosThA, n1z = sinThA;
    var th2 = actualTheta + dTh2;
    var costh2 = Math.cos(th2), sinth2 = Math.sin(th2);
    var n2x = -costh2, n2y = -roll2 * costh2, n2z = -sinth2;
    var h_nominal = 2 * gap_m * cosThA;

    for (var i = 0; i < nR; i++) {
      var o = i * RS;
      if (rays[o+5] <= 0) continue;
      if (Math.abs(rays[o+1]) > cW * 0.5) continue;
      var xr1 = rays[o] - y1_x;
      if (xr1 < -cThick*0.5 || xr1 > cThick*0.5) continue;
      // Per-ray Bragg angle from per-ray energy
      var E_ray_keV = rays[o+6] * 0.001;
      var sinThB_ray = HC / (2 * d_spacing * E_ray_keV);
      if (sinThB_ray >= 1 || sinThB_ray <= 0) { rays[o+5] = 0; continue; }
      var thB_ray = Math.asin(sinThB_ray);
      var cosThB_ray = Math.cos(thB_ray);

      // Per-ray susceptibilities (lookup from DABAX table)
      var psi_ray = (typeof crystalPsi === 'function') ? crystalPsi(E_ray_keV, state.crystal) : psi_center;

      // Crystal 1: dot product of ray direction with crystal inward normal
      var vdn1 = rays[o+2]*n1x + rays[o+3]*n1y + rays[o+4]*n1z;
      // Add thermal slope error to effective incidence
      var vdn1_eff = vdn1;
      if (sig > 1e-12) vdn1_eff += gaussRand() * sig;
      // Guigay reflectivity for crystal 1
      var ref1 = _guigayThickBragg(vdn1_eff, E_ray_keV, thB_ray, psi_ray, sig);
      // S4 style: weight *= R (average of sigma and pi)
      var R1 = (ref1.R_s + ref1.R_p) * 0.5;
      rays[o+5] *= R1;
      if (rays[o+5] < 1e-12) { rays[o+5] = 0; continue; }

      // Specular reflection off crystal 1
      var twovdn1 = 2 * vdn1;
      var vx1 = rays[o+2] - twovdn1*n1x;
      var vy1 = rays[o+3] - twovdn1*n1y;
      var vz1 = rays[o+4] - twovdn1*n1z;
      if (Math.abs(vdn1) < 1e-10) { rays[o+5] = 0; continue; }
      // Propagate to crystal 2
      var t12 = gap_m / Math.abs(vdn1);
      if (t12 > 10.0) { rays[o+5] = 0; continue; }
      rays[o]   += vx1 * t12;
      rays[o+1] += vy1 * t12;
      if (Math.abs(rays[o+1]) > cW * 0.5) { rays[o+5] = 0; continue; }

      // Crystal 2: same per-ray energy and susceptibilities
      var vdn2 = vx1*n2x + vy1*n2y + vz1*n2z;
      var vdn2_eff = vdn2;
      if (sig > 1e-12) vdn2_eff += gaussRand() * sig;
      var ref2 = _guigayThickBragg(vdn2_eff, E_ray_keV, thB_ray, psi_ray, sig);
      var R2 = (ref2.R_s + ref2.R_p) * 0.5;
      rays[o+5] *= R2;
      if (rays[o+5] < 1e-12) { rays[o+5] = 0; continue; }

      // Specular reflection off crystal 2
      var twovdn2 = 2 * vdn2;
      rays[o+2] = vx1 - twovdn2*n2x;
      rays[o+3] = vy1 - twovdn2*n2y;
      rays[o+4] = vz1 - twovdn2*n2z;
      rays[o] += h_nominal;
    }
  };
  console.log('[' + APP_VTAG + '] Sphere mirror + Guigay DCM (S4 crystalpy port) loaded');
})();

// === Elliptical KB Mirror MC — Shadow4 S4EllipsoidMirror ===
// Exact-surface ellipsoid conic ray-trace (ccc + intersect + normal + reflect + image
// frame), ported from Shadow4 s4_conic.py / s4_mirror.py. Replaces the thin-lens -y/F
// kick: it traces the real ellipsoid surface, reproducing the S4EllipsoidMirror
// geometric focus. At the matched secondary source the engine geom V is ~40 nm
// (thin-lens gave 46.7 nm; S4 element gives 39.5 nm), validated standalone vs S4Conic.
// 4-beam support: rays missing the mirror pass through alive (no deflection).
// kbTag bit flag: bit0(1)=KB-V reflected, bit1(2)=KB-H reflected.
// _kbConicAngle: 1D meridional ellipsoid reflection (cylinder is flat in the sagittal
// axis, so V and H decouple). Returns the straightened-frame reflected angle with the
// pole-plane position folded in, so the engine keeps its paraxial position convention.
// Reduces to -srcPos/F in the small-footprint (thin-lens) limit.
function _kbConicAngle(srcPos, angIn, posKb, cc1, cc2, cc4, cc8, sK, cK, pf, qf){
  var vzc=Math.sqrt(Math.max(1-angIn*angIn,0));
  var PY=srcPos*sK - pf*cK, PZ=srcPos*cK + pf*sK;       // rotate(graz,axisX) + translate
  var VY=vzc*cK+angIn*sK, VZ=-vzc*sK+angIn*cK;
  var AA=cc1*VY*VY+cc2*VZ*VZ+cc4*VY*VZ;
  var BB=2*(cc1*PY*VY+cc2*PZ*VZ)+cc4*(PZ*VY+PY*VZ)+cc8*VZ;
  var CC=cc1*PY*PY+cc2*PZ*PZ+cc4*PY*PZ+cc8*PZ;
  var disc=BB*BB-4*AA*CC; if(disc<0)disc=0; var sq=Math.sqrt(disc);
  var ta=(-BB+sq)/(2*AA), tb=(-BB-sq)/(2*AA);
  var IYa=PY+VY*ta, IYb=PY+VY*tb;
  var tt=(Math.abs(IYb)<Math.abs(IYa))?tb:ta;            // pole-nearest intersection
  var IY=PY+VY*tt, IZ=PZ+VZ*tt;
  var n1=2*cc1*IY+cc4*IZ, n2=2*cc2*IZ+cc4*IY+cc8;        // conic-gradient normal
  var nm=Math.sqrt(n1*n1+n2*n2); n1/=nm; n2/=nm;
  var vdn=VY*n1+VZ*n2, RY=VY-2*vdn*n1, RZ=VZ-2*vdn*n2;   // specular reflection
  var vyi=-RY*sK+RZ*cK, vzi=RY*cK+RZ*sK;                 // image frame (VZIM=[0,-s,c])
  var yim=-IY*sK+IZ*cK, zim=IY*cK+IZ*sK;
  var yp=yim-vyi*zim/vzi;                                // back-propagate to pole plane
  return vyi + (yp - posKb)/qf;
}
// Trace one KB mirror (kbv/kbh): exact Shadow4 ellipsoid-conic focus at 3 mrad grazing, reflectivity cull, set kbTag bit.
window.applyKBMC = function(rays, nR, kbId, E) {
  var pitch=mVal(kbId,'pitch',3.0), roll=mVal(kbId,'roll',0)*1e-3;
  var yaw=mVal(kbId,'yaw',0)*1e-3;
  var tyOff=mVal(kbId,'y',0)*1e-3, txOff=mVal(kbId,'x',0)*1e-3;
  var zBeam=mVal(kbId,'z',0)*1e-3;
  var tg=pitch*1e-3, dP=(pitch-3.0)*1e-3;
  var isV=(kbId==='kbv');
  var kbBit = isV ? 1 : 2;  // V=bit0, H=bit1
  var kbp=window.KB_PARAMS&&window.KB_PARAMS[kbId];
  var kbLen=kbp?kbp.len:0.200, kbWid=kbp?kbp.wid:0.030;
  var rough=kbp?kbp.rough||0:0;
  var sinTg=Math.sin(Math.abs(tg));
  var pDist=pos(kbId)-pos('ssa'), qDist=pos('sample')-pos(kbId);
  var F=(pDist>0&&qDist>0)?pDist*qDist/(pDist+qDist):0.3;
  // Exact ellipsoid conic coefficients (Shadow4 method=0, cylindrical/meridional) for this KB
  var cKB=Math.cos(Math.abs(tg)), _pqK=pDist+qDist;
  var useConic=(pDist>0&&qDist>0);
  var cc1=sinTg*sinTg;
  var cc2=useConic?1-Math.pow(sinTg*(pDist-qDist)/_pqK,2):1.0;
  var cc4=useConic?-2*sinTg*cKB*(qDist-pDist)/_pqK:0.0;
  var cc8=useConic?-4*sinTg*pDist*qDist/_pqK:0.0;
  var sMat=RH;
  if(typeof getStripeMaterial==='function'){
    var st=getStripeMaterial(kbId); if(st&&st.mat) sMat=st.mat;
  }
  var sig=(typeof thermalSlopeError==='function')?thermalSlopeError(kbId,E):0;
  // Store original footprint for hybrid diffraction computation
  if(!window._kbFootprintArr) window._kbFootprintArr = {};
  window._kbFootprintArr[kbId] = new Float64Array(nR);
  // Coordinate system follows reflected beam path. Non-reflected rays need
  // a -2*theta kick so they separate from the reflected beam at the detector
  // (see: "Complete alignment of a KB-mirror system guided by ptychography").
  var passIdx = isV ? 3 : 2;  // angle index for deflection plane
  var passKick = -2*tg;       // -2*theta coordinate correction
  for(var i=0;i<nR;i++){var o=i*RS;
    if(rays[o+5]<=0)continue;
    var xr=rays[o]-txOff, yr=rays[o+1]-tyOff;
    var kbThick=kbp?kbp.thick:0.050;
    // Width check: outside lateral width -> pass through (no interaction)
    if(isV){if(Math.abs(xr)>kbWid*0.5){rays[o+passIdx]+=passKick;rayUpdateVz(rays,o);continue;}}
    else{if(Math.abs(yr)>kbWid*0.5){rays[o+passIdx]+=passKick;rayUpdateVz(rays,o);continue;}}
    var kbDeflPos=isV?yr:xr;
    var hitMirror = true;
    if(tg > 0.5e-3){
      var surfY=kbDeflPos/sinTg;
      if(Math.abs(zBeam)>1e-7) surfY-=zBeam;
      if(Math.abs(surfY)>kbLen*0.5) hitMirror = false;  // pass through
    }else{
      if(kbDeflPos<0||kbDeflPos>kbThick){rays[o+passIdx]+=passKick;rayUpdateVz(rays,o);continue;}
      // Ray is inside mirror body (0 <= kbDeflPos <= kbThick)
      if(tg<=1e-7){rays[o+5]=0;continue;} // pitch=0: mirror body blocks ray
      if(kbDeflPos>kbLen*sinTg) hitMirror = false;
    }
    if(!hitMirror){
      // Substrate(50mm) + motor/holder blocks ALL rays below the reflective surface.
      // Only rays above the footprint (+side) pass through as direct beam.
      if(tg>0.5e-3){
        var fpHalf=kbLen*sinTg*0.5;
        if(kbDeflPos<-fpHalf){rays[o+5]=0;continue;}
      }
      rays[o+passIdx]+=passKick;rayUpdateVz(rays,o);
      continue;
    }
    var lth=Math.abs(tg-(isV?rays[o+3]:rays[o+2]));
    var E_ray_keV=rays[o+6]*0.001;
    if(Math.random()>mirrorR(E_ray_keV,lth*1e3,sMat,rough)){rays[o+5]=0;continue;}  // absorbed by mirror
    // Ray successfully reflected by this KB mirror
    window._kbFootprintArr[kbId][i] = kbDeflPos;
    rays[o+7] = (rays[o+7] | 0) | kbBit;  // set KB tag bit
    // Misalignment kicks + exact ellipsoid conic focus (Shadow4 S4EllipsoidMirror)
    if(isV){
      if(useConic) rays[o+3]=_kbConicAngle(rays[o+1]-rays[o+3]*pDist, rays[o+3], rays[o+1], cc1,cc2,cc4,cc8, sinTg,cKB, pDist,qDist)+2*dP;
      else rays[o+3]+=2*dP-rays[o+1]/F;
      rays[o+2]+=2*tg*roll+2*yaw;
      if(sig>1e-12) rays[o+3]+=gaussRand()*sig;
    }else{
      if(useConic) rays[o+2]=_kbConicAngle(rays[o]-rays[o+2]*pDist, rays[o+2], rays[o], cc1,cc2,cc4,cc8, sinTg,cKB, pDist,qDist)+2*dP;
      else rays[o+2]+=2*dP-rays[o]/F;
      rays[o+3]+=2*tg*roll+2*yaw;
      if(sig>1e-12) rays[o+2]+=gaussRand()*sig;
    }
    rayUpdateVz(rays,o);
  }
};

// === Shadow4 Hybrid: FFT-based Fresnel wave propagation ===
// Replaces per-ray sinc^2 diffraction kicks with coherent wavefront propagation.
// Ref: wofryimpl/propagator/propagators1D/fresnel.py (Transfer Function method)
// Ref: hybrid_methods/coherence/hybrid_screen.py (_propagate_wavefront_tangentially)
// Algorithm: rays -> histogram on optic -> sqrt(I) wavefront -> thin-lens phase
//   -> Fresnel FFT propagation -> intensity at image -> inverse CDF resampling of rays

(function(){
  // --- Radix-2 Cooley-Tukey FFT (in-place, iterative) ---
  // re/im: Float64Array of length N (must be power of 2)
  // inv: false=forward FFT, true=inverse FFT
  function _fft(re, im, inv) {
    var N = re.length;
    // Bit-reversal permutation
    for (var i = 1, j = 0; i < N; i++) {
      var bit = N >> 1;
      while (j & bit) { j ^= bit; bit >>= 1; }
      j ^= bit;
      if (i < j) {
        var t = re[i]; re[i] = re[j]; re[j] = t;
        t = im[i]; im[i] = im[j]; im[j] = t;
      }
    }
    // FFT butterfly
    var sign = inv ? 1 : -1;
    for (var len = 2; len <= N; len <<= 1) {
      var ang = sign * 2 * Math.PI / len;
      var wRe = Math.cos(ang), wIm = Math.sin(ang);
      for (var i = 0; i < N; i += len) {
        var curRe = 1, curIm = 0;
        for (var j = 0; j < (len >> 1); j++) {
          var a = i + j, b = i + j + (len >> 1);
          var tRe = curRe * re[b] - curIm * im[b];
          var tIm = curRe * im[b] + curIm * re[b];
          re[b] = re[a] - tRe;
          im[b] = im[a] - tIm;
          re[a] += tRe;
          im[a] += tIm;
          var tmpR = curRe * wRe - curIm * wIm;
          curIm = curRe * wIm + curIm * wRe;
          curRe = tmpR;
        }
      }
    }
    if (inv) { for (var i = 0; i < N; i++) { re[i] /= N; im[i] /= N; } }
  }

  // Next power of 2 >= n
  function _nextPow2(n) { var p = 1; while (p < n) p <<= 1; return p; }

  // --- 1D Fresnel propagation (Transfer Function method) ---
  // Input: amplitude array amp[0..nPts-1] on grid [xMin, xMax]
  // Output: intensity |U(x)|^2 at image plane after propagation distance z
  // lambda: wavelength [m], z: propagation distance [m]
  // focalLen: thin-lens focal length [m] (applied before propagation)
  // Returns: {intensity: Float64Array, xMin, xMax, dx}
  function _fresnelProp1D(amp, nPts, xMin, xMax, lambda, z, focalLen) {
    var dx = (xMax - xMin) / (nPts - 1);
    var k = 2 * Math.PI / lambda;
    // Pad to power of 2
    var N = _nextPow2(nPts * 2); // 2x oversampling for anti-aliasing
    var re = new Float64Array(N);
    var im = new Float64Array(N);
    // Fill amplitude with thin-lens phase: exp(-i*k*x^2/(2*f))
    for (var i = 0; i < nPts; i++) {
      var x = xMin + i * dx;
      var phi = -k * x * x / (2 * focalLen);
      re[i] = amp[i] * Math.cos(phi);
      im[i] = amp[i] * Math.sin(phi);
    }
    // Forward FFT
    _fft(re, im, false);
    // Apply Fresnel transfer function: H(f) = exp(-i*pi*lambda*z*f^2)
    // Frequency grid: f_j = j/(N*dx) for j=0..N/2, then (j-N)/(N*dx) for j=N/2+1..N-1
    var coeff = -Math.PI * lambda * z;
    for (var j = 0; j < N; j++) {
      var fj = (j <= N / 2) ? j / (N * dx) : (j - N) / (N * dx);
      var phase = coeff * fj * fj;
      var cP = Math.cos(phase), sP = Math.sin(phase);
      var tRe = re[j] * cP - im[j] * sP;
      var tIm = re[j] * sP + im[j] * cP;
      re[j] = tRe;
      im[j] = tIm;
    }
    // Inverse FFT
    _fft(re, im, true);
    // Extract intensity
    var intensity = new Float64Array(nPts);
    for (var i = 0; i < nPts; i++) {
      intensity[i] = re[i] * re[i] + im[i] * im[i];
    }
    // Output grid: same as input grid (TF method preserves grid)
    return { intensity: intensity, xMin: xMin, xMax: xMax, dx: dx, nPts: nPts };
  }

  // --- CDF construction (Shadow4 Sampler1D exact port; A1 GPU split) ---
  // Extracted from _inverseCdfSample as a PURE CODE MOTION so the opt-in
  // WebGPU path (raytrace/05_mc_gpu.js) can build the very same CDF table on
  // the host and upload it for in-shader inverse-CDF sampling.
  // CDF: cumsum(pdf), subtract first value, normalize to [0,1].
  // Returns {ok:false} when the CDF is degenerate (S4 falls back to uniform).
  function _cdfBuild(pdf, n) {
    var cdf = new Float64Array(n);
    cdf[0] = pdf[0];
    for (var i = 1; i < n; i++) cdf[i] = cdf[i - 1] + pdf[i];
    var cdf0 = cdf[0];
    for (var i = 0; i < n; i++) cdf[i] -= cdf0;
    var cdfMax = cdf[n - 1];
    if (cdfMax <= 0) return { ok: false, cdf: null };
    for (var i = 0; i < n; i++) cdf[i] /= cdfMax;
    return { ok: true, cdf: cdf };
  }
  window._cdfBuild = _cdfBuild;

  // --- Inverse CDF sampler (Shadow4 Sampler1D exact port) ---
  // Ref: srxraylib/util/inverse_method_sampler.py class Sampler1D
  // CDF: cumsum(pdf), subtract first value, normalize to [0,1]
  // Sampling: binary search + linear interpolation within bin
  function _inverseCdfSample(pdf, n, xMin, xMax, nSamples) {
    var dx = (xMax - xMin) / (n - 1);
    // Build CDF (S4: cumsum, subtract cdf[0], normalize)
    var built = _cdfBuild(pdf, n);
    if (!built.ok) {
      var samples = new Float64Array(nSamples);
      for (var i = 0; i < nSamples; i++) samples[i] = xMin + Math.random() * (xMax - xMin);
      return samples;
    }
    var cdf = built.cdf;
    // Sample (S4: _get_index finds first cdf >= u, then ix-=1, linear interp)
    var samples = new Float64Array(nSamples);
    for (var s = 0; s < nSamples; s++) {
      var u = Math.random();
      // Binary search: find first index where cdf >= u
      var lo = 0, hi = n - 1;
      while (lo < hi) {
        var mid = (lo + hi) >> 1;
        if (cdf[mid] < u) lo = mid + 1;
        else hi = mid;
      }
      // S4: if ix > 0: ix -= 1
      var ix = lo;
      if (ix > 0) ix--;
      // Linear interpolation within [ix, ix+1]
      var delta_val = 0;
      if (ix < n - 1) {
        var pendent = cdf[ix + 1] - cdf[ix];
        if (pendent > 0) delta_val = (u - cdf[ix]) / pendent;
      }
      samples[s] = xMin + (ix + delta_val) * dx;
    }
    return samples;
  }

  // --- Shadow4 Hybrid: line-by-line port of S4 hybrid_screen.py ---
  // Ref: hybrid_methods/coherence/hybrid_screen.py
  //   _propagate_wavefront_tangentially (lines 1059-1184)
  //   _convolve_wavefront_with_rays (lines 1365-1407)
  //   _calculate_focal_length_ff_1D (lines 1350-1352)
  //   _calculate_fft_size (lines 1358-1360)
  // Ref: wofryimpl/propagator/propagators1D/fresnel.py (lines 30-39)
  // Ref: srxraylib/util/data_structures.py ScaledArray.interpolate_value
  // Ref: srxraylib/util/inverse_method_sampler.py Sampler1D
  //
  // Algorithm (S4 exact):
  //   1. Histogram footprint with n_bins = min(200, nAlive/20)
  //   2. ScaledArray: map histogram to [zMin, zMax] grid
  //   3. Create wavefront: N points from zMin to zMax
  //   4. Interpolate histogram onto wavefront grid -> sqrt -> amplitude
  //   5. Thin-lens phase: phi(z) = -k * z^2 / (2 * f_ff)
  //   6. Fresnel TF propagation over distance f_ff
  //   7. Extract image: interpolate at centered grid, |U|^2
  //   8. Convert scale to angles (position / f_ff)
  //   9. CDF sample -> angular kicks
  //  10. ADD kicks to geometric ray directions

  // --- Wavefront profile core (A1 GPU split: PURE CODE MOTION) ---
  // Everything in _hybridFF1D after the footprint histogram and before the
  // inverse-CDF sampling, extracted unchanged so the opt-in WebGPU path
  // (raytrace/05_mc_gpu.js) can run the SAME collective wavefront physics on
  // a GPU-built histogram (the FFT stays on the CPU; only the per-ray
  // sampling moves into the shader). Inputs: histogram (counts), nBins,
  // zMin/zMax (footprint range), D (footprint width), lambda [m].
  // Returns {intensity, nPts, angMin, angMax} or null (degenerate).
  function _hybridProfile1D(hist, nBins, zMin, zMax, D, lambda) {
    if (D < 1e-12) return null;
    if (zMax - zMin < 1e-15) return null;

    var n_peaks = 20;
    var k = 2 * Math.PI / lambda;

    // S4: _calculate_focal_length_ff_1D (line 1352)
    // f_ff = (z_max - z_min)^2 / n_peaks / 2 / 0.88 / wavelength
    var f_ff = D * D / (n_peaks * 2 * 0.88 * lambda);

    // S4: ScaledArray.initialize_from_range(histogram, bins[0], bins[-1])
    // Maps nBins values to scale from zMin to zMax
    // hist_delta = (zMax - zMin) / (nBins - 1)
    var hist_delta = (nBins > 1) ? (zMax - zMin) / (nBins - 1) : 1e-15;

    // --- Step 2: FFT size (S4 convention) ---
    // S4: _calculate_fft_size (line 1360)
    // fft_size = int(min(factor * D^2 / (lam * f_ff * 0.88), fft_n_pts))
    // factor=100, fft_n_pts=1e6
    var fft_size_raw = Math.round(100 * D * D / (lambda * f_ff * 0.88));
    if (fft_size_raw > 1000000) fft_size_raw = 1000000;
    if (fft_size_raw < nBins * 2) fft_size_raw = nBins * 2;
    // Round up to power of 2 for Cooley-Tukey FFT
    var N = _nextPow2(fft_size_raw);
    if (N > 131072) N = 131072;

    // --- Step 3: Create wavefront on grid [zMin, zMax] with N points ---
    // S4: initialize_wavefront_from_range(x_min=zMin, x_max=zMax, number_of_points=N)
    // delta = (zMax - zMin) / (N - 1)
    var delta = (zMax - zMin) / (N - 1);
    var re = new Float64Array(N);
    var im = new Float64Array(N);

    // --- Step 4: Interpolate histogram onto wavefront grid ---
    // S4: sqrt(wIray_z.interpolate_values(wavefront.get_abscissas()))
    // Then add thin-lens phase: -k * z^2 / (2 * f_ff)
    // S4 interpolation: ScaledArray.interpolate_value (data_structures.py:681-713)
    //   - Clamp to first/last value outside range
    //   - Linear interpolation within range
    for (var j = 0; j < N; j++) {
      var z = zMin + j * delta;
      // Linear interpolation of histogram ScaledArray
      var frac_idx = (z - zMin) / hist_delta;
      var idx0 = Math.floor(frac_idx);
      var idx1 = idx0 + 1;
      // S4 clamp: out-of-bounds returns first/last value
      if (idx0 < 0) { idx0 = 0; idx1 = 0; }
      if (idx1 >= nBins) { idx1 = nBins - 1; if (idx0 >= nBins) idx0 = nBins - 1; }
      var interp_val;
      if (idx0 === idx1) {
        interp_val = hist[idx0];
      } else {
        var frac = frac_idx - idx0;
        interp_val = hist[idx0] + (hist[idx1] - hist[idx0]) * frac;
      }
      // S4: amplitude = sqrt(interpolated_intensity)
      var amp = Math.sqrt(Math.max(0, interp_val));
      // S4: _add_ideal_lens_phase_shift_1D (line 1305)
      // phase = -k * z^2 / (2 * f_ff)
      // Note: z is PHYSICAL position on mirror (S4 uses wavefront.get_abscissas())
      var phi = -k * z * z / (2 * f_ff);
      re[j] = amp * Math.cos(phi);
      im[j] = amp * Math.sin(phi);
    }

    // --- Step 5: Fresnel TF propagation (S4: fresnel.py lines 30-39) ---
    // fft_scale = fftfreq(N) / delta
    // fft *= exp(-i * pi * lambda * f_ff * fft_scale^2)
    _fft(re, im, false);
    var coeff = -Math.PI * lambda * f_ff;
    for (var j = 0; j < N; j++) {
      // S4: numpy.fft.fftfreq(N) = [0,1/N,...,(N/2-1)/N,-N/2/N,...,-1/N]
      var freq_idx = (j < N / 2) ? j : (j - N);
      var fj = freq_idx / (N * delta);
      var phase = coeff * fj * fj;
      var cP = Math.cos(phase), sP = Math.sin(phase);
      var tRe = re[j] * cP - im[j] * sP;
      var tIm = re[j] * sP + im[j] * cP;
      re[j] = tRe;
      im[j] = tIm;
    }
    _fft(re, im, true);

    // --- Step 6: Extract image intensity (S4: lines 1112-1127) ---
    // image_size = min(2*min(|zMax|,|zMin|), n_peaks*2*0.88*lam*f_ff/D)
    var image_size = Math.min(Math.abs(zMax), Math.abs(zMin)) * 2;
    image_size = Math.min(image_size,
        n_peaks * 2 * 0.88 * lambda * f_ff / Math.abs(zMax - zMin));

    // S4: image_n_pts = round(image_size / delta / 2) * 2 + 1
    var image_n_pts = Math.round(image_size / delta / 2) * 2 + 1;
    if (image_n_pts < 3) image_n_pts = 3;
    if (image_n_pts > N) image_n_pts = N;

    // S4: dif_zp grid centered at 0, spacing = delta
    // Positions: [-(image_n_pts-1)/2 * delta, ..., (image_n_pts-1)/2 * delta]
    // Interpolate propagated wavefront at these positions, take |amplitude|^2
    var half_pts = (image_n_pts - 1) / 2;
    var intensity = new Float64Array(image_n_pts);
    for (var ip = 0; ip < image_n_pts; ip++) {
      var pos = (ip - half_pts) * delta;
      // Map to wavefront index: (pos - zMin) / delta
      var wf_frac = (pos - zMin) / delta;
      var i0 = Math.floor(wf_frac);
      var i1 = i0 + 1;
      if (i0 < 0 || i1 >= N) { intensity[ip] = 0; continue; }
      var frac = wf_frac - i0;
      var re_i = re[i0] + (re[i1] - re[i0]) * frac;
      var im_i = im[i0] + (im[i1] - im[i0]) * frac;
      intensity[ip] = re_i * re_i + im_i * im_i;
    }

    // S4: dif_zp.set_scale_from_range (line 1126-1127)
    // Convert scale to angular coordinates: divide positions by f_ff
    var angMin = -half_pts * delta / f_ff;
    var angMax = half_pts * delta / f_ff;

    return { intensity: intensity, nPts: image_n_pts, angMin: angMin, angMax: angMax };
  }
  window._hybridProfile1D = _hybridProfile1D;

  // Core 1D hybrid diffraction: footprint array -> angular kick samples.
  // (A1 GPU split: footprint histogram here, collective wavefront physics in
  // _hybridProfile1D, per-ray sampling in _inverseCdfSample — behavior
  // identical to the original single function.)
  function _hybridFF1D(footArr, nAlive, D, lambda, nSamples, focalLen) {
    if (D < 1e-12 || nAlive < 3) return new Float64Array(nSamples);

    // --- Step 1: Histogram footprint (S4 convention) ---
    // S4: n_bins_z = min(200, round(nAlive/20)), capped at >= 10
    var nBins = Math.min(200, Math.round(nAlive / 20));
    if (nBins < 10) nBins = 10;

    var zMin = footArr[0], zMax = footArr[0];
    for (var i = 1; i < nAlive; i++) {
      if (footArr[i] < zMin) zMin = footArr[i];
      if (footArr[i] > zMax) zMax = footArr[i];
    }
    if (zMax - zMin < 1e-15) return new Float64Array(nSamples);

    // S4: numpy.histogram(zz_screen, bins=nBins) -> hist, bin_edges
    var dz_hist = (zMax - zMin) / nBins;
    var hist = new Float64Array(nBins);
    for (var i = 0; i < nAlive; i++) {
      var bin = Math.floor((footArr[i] - zMin) / dz_hist);
      if (bin >= nBins) bin = nBins - 1;
      if (bin >= 0) hist[bin]++;
    }

    var prof = _hybridProfile1D(hist, nBins, zMin, zMax, D, lambda);
    if (!prof) return new Float64Array(nSamples);

    // --- Step 7: CDF sampling (S4: Sampler1D) ---
    return _inverseCdfSample(prof.intensity, prof.nPts, prof.angMin, prof.angMax, nSamples);
  }

  // SSA Hybrid: S4-style diffraction for secondary source aperture.
  // Replaces per-ray sincSqRand() with coherent wavefront propagation.
  // Called from mcRayTrace slit case for SSA (not wbslit).
  // rays: ray array, nR: total rays, slitId: 'ssa', E: energy keV
  // hH, hV: half-widths [m], cxO, cyO: center offsets [m]
  window._applySSAHybrid = function(rays, nR, E, hH, hV, cxO, cyO) {
    // Use mean energy of alive rays for collective wavefront computation
    var alive = [];
    var E_sum = 0;
    for (var i = 0; i < nR; i++) {
      if (rays[i * RS + 5] > 0) { alive.push(i); E_sum += rays[i * RS + 6]; }
    }
    var E_mean_keV = alive.length > 0 ? (E_sum / alive.length) * 0.001 : E;
    var lam = HC / E_mean_keV * 1e-10;
    if (lam <= 0) return;
    if (alive.length < 10) return;

    // Collect ray positions within the slit
    var xPos = new Float64Array(alive.length);
    var yPos = new Float64Array(alive.length);
    for (var ai = 0; ai < alive.length; ai++) {
      var o = alive[ai] * RS;
      xPos[ai] = rays[o] - cxO;     // H position relative to slit center
      yPos[ai] = rays[o + 1] - cyO; // V position relative to slit center
    }

    // Footprint width: actual ray distribution within slit
    var xMin = xPos[0], xMax = xPos[0], yMin = yPos[0], yMax = yPos[0];
    for (var ai = 1; ai < alive.length; ai++) {
      if (xPos[ai] < xMin) xMin = xPos[ai];
      if (xPos[ai] > xMax) xMax = xPos[ai];
      if (yPos[ai] < yMin) yMin = yPos[ai];
      if (yPos[ai] > yMax) yMax = yPos[ai];
    }
    var DH = xMax - xMin;
    var DV = yMax - yMin;
    // Clamp to slit aperture
    if (DH > 2 * hH) DH = 2 * hH;
    if (DV > 2 * hV) DV = 2 * hV;

    // Angular kicks from hybrid diffraction
    var angH = (DH > 1e-10) ? _hybridFF1D(xPos, alive.length, DH, lam, alive.length) : null;
    var angV = (DV > 1e-10) ? _hybridFF1D(yPos, alive.length, DV, lam, alive.length) : null;

    // Add angular kicks to ray directions
    for (var ai = 0; ai < alive.length; ai++) {
      var o = alive[ai] * RS;
      if (angH) rays[o + 2] += angH[ai];
      if (angV) rays[o + 3] += angV[ai];
      if (angH || angV) rayUpdateVz(rays, o);
    }
  };

  // After sample drift (td>148m), apply Shadow4-hybrid Fresnel diffraction to KB-V/KB-H reflected rays by back-propagating to mirror footprint and re-adding geometric plus diffraction angular kicks.
  window._applyHybridFresnel = function(rays, nR, E, td) {
    if (td < 148) return;

    // Collect alive rays with KB tags, compute mean energy
    var alive = [], alive_V = [], alive_H = [];
    var E_sum = 0;
    for (var i = 0; i < nR; i++) {
      if (rays[i * RS + 5] > 0) {
        var tag = rays[i * RS + 7] | 0;
        alive.push(i);
        E_sum += rays[i * RS + 6];
        if (tag & 1) alive_V.push(i);  // reflected by KB-V
        if (tag & 2) alive_H.push(i);  // reflected by KB-H
      }
    }
    if (alive.length < 10) return;
    var E_mean_keV = (E_sum / alive.length) * 0.001;
    var lam = HC / E_mean_keV * 1e-10;
    if (lam <= 0) return;

    var kbp = window.KB_PARAMS || {};
    var kbvP = kbp.kbv || { len: 0.300, wid: 0.030 };
    var kbhP = kbp.kbh || { len: 0.100, wid: 0.030 };

    var posKBV = pos('kbv'), posKBH = pos('kbh'), posSSA = pos('ssa'), posSample = pos('sample');
    var qV = posSample - posKBV;
    var qH = posSample - posKBH;
    var sinTg = Math.sin(0.003);
    var apV = kbvP.len * sinTg;
    var apH = kbhP.len * sinTg;
    // H1 fix: compute KB focal lengths for geometric kick removal
    var pV = posKBV - posSSA, pH = posKBH - posSSA;
    var F_kbv = (pV > 0 && qV > 0) ? pV * qV / (pV + qV) : 0.3;
    var F_kbh = (pH > 0 && qH > 0) ? pH * qH / (pH + qH) : 0.1;

    // KB-V hybrid: back-propagate V-reflected rays, compute diffraction kicks
    // H1 fix: remove geometric kick before back-propagation to avoid double-counting
    if (alive_V.length >= 10) {
      var yAtKBV = new Float64Array(alive_V.length);
      var vyAtKBV = new Float64Array(alive_V.length);
      for (var ai = 0; ai < alive_V.length; ai++) {
        var o = alive_V[ai] * RS;
        var ivz = 1 / rays[o + 4];
        // Subtract geometric kick: applyKBMC added vy += -y_mirror/F to rays[o+3]
        // We need the pre-kick angle to recover the correct mirror footprint
        var vy_with_kick = rays[o + 3] * ivz;  // current vy/vz (includes geo kick)
        var y_at_sample = rays[o + 1];
        // Back-propagate with current (kicked) angle to get mirror position
        var y_mirror = y_at_sample - vy_with_kick * qV;
        // Remove the geometric kick to get original angle before KB
        var geo_kick = -y_mirror / F_kbv;  // this is what applyKBMC added
        var vy_orig = vy_with_kick - geo_kick;  // angle before geometric focusing
        yAtKBV[ai] = y_mirror;
        vyAtKBV[ai] = vy_orig;
      }
      var yMin = yAtKBV[0], yMax = yAtKBV[0];
      for (var ai = 1; ai < alive_V.length; ai++) {
        if (yAtKBV[ai] < yMin) yMin = yAtKBV[ai];
        if (yAtKBV[ai] > yMax) yMax = yAtKBV[ai];
      }
      var DV = yMax - yMin;
      // hybridFF1D computes diffraction angular kicks from footprint
      var angV = _hybridFF1D(yAtKBV, alive_V.length, DV, lam, alive_V.length, Infinity);
      for (var ai = 0; ai < alive_V.length; ai++) {
        var o = alive_V[ai] * RS;
        // Reconstruct: original angle + geo kick + diffraction kick
        var vy_total = vyAtKBV[ai] + (-yAtKBV[ai] / F_kbv) + angV[ai];
        rays[o + 1] = yAtKBV[ai] + vy_total * qV;
        rays[o + 3] = vy_total * rays[o + 4];
      }
    }

    // KB-H hybrid: back-propagate H-reflected rays, compute diffraction kicks
    // H1 fix: same geometric kick removal as KB-V
    if (alive_H.length >= 10) {
      var xAtKBH = new Float64Array(alive_H.length);
      var vxAtKBH = new Float64Array(alive_H.length);
      for (var ai = 0; ai < alive_H.length; ai++) {
        var o = alive_H[ai] * RS;
        var ivz = 1 / rays[o + 4];
        var vx_with_kick = rays[o + 2] * ivz;
        var x_at_sample = rays[o];
        var x_mirror = x_at_sample - vx_with_kick * qH;
        var geo_kick_h = -x_mirror / F_kbh;
        var vx_orig = vx_with_kick - geo_kick_h;
        xAtKBH[ai] = x_mirror;
        vxAtKBH[ai] = vx_orig;
      }
      var xMin = xAtKBH[0], xMax = xAtKBH[0];
      for (var ai = 1; ai < alive_H.length; ai++) {
        if (xAtKBH[ai] < xMin) xMin = xAtKBH[ai];
        if (xAtKBH[ai] > xMax) xMax = xAtKBH[ai];
      }
      var DH = xMax - xMin;
      var angH = _hybridFF1D(xAtKBH, alive_H.length, DH, lam, alive_H.length, Infinity);
      for (var ai = 0; ai < alive_H.length; ai++) {
        var o = alive_H[ai] * RS;
        var vx_total = vxAtKBH[ai] + (-xAtKBH[ai] / F_kbh) + angH[ai];
        rays[o] = xAtKBH[ai] + vx_total * qH;
        rays[o + 2] = vx_total * rays[o + 4];
      }
    }
  };
})();

// === Histogram FWHM: sub-pixel interpolation on marginal ===
// Measures FWHM directly from marginal histogram, accurate for any distribution
// (sinc², Gaussian, etc.) unlike sigma*2.355 which assumes Gaussian.
function _margFwhm(marg, G, halfFov) {
  var mx = 0;
  for (var i = 0; i < G; i++) { if (marg[i] > mx) mx = marg[i]; }
  if (mx <= 0) return 0;
  var hm = mx * 0.5;
  var x0 = -1, x1 = -1;
  for (var i = 1; i < G; i++) {
    if (marg[i - 1] < hm && marg[i] >= hm && x0 < 0) {
      x0 = (i - 1) + (hm - marg[i - 1]) / (marg[i] - marg[i - 1] + 1e-30);
    }
    if (marg[i - 1] >= hm && marg[i] < hm) {
      x1 = (i - 1) + (hm - marg[i - 1]) / (marg[i] - marg[i - 1] - 1e-30);
    }
  }
  if (x0 < 0 || x1 < 0) return 0;
  return (x1 - x0) * (2 * halfFov / G);
}

// === MC Ray Trace — Shadow4 3D vector model ===
var MC_NRAYS = 100000;

// Run the full MC ray trace from undulator source to target distance td; returns 2D/marginal histograms, FWHM, sigma, divergence, beam counts.
window.mcRayTrace = function(td, nR) {
  nR=nR||MC_NRAYS;
  // === A1 WebGPU opt-in hook (default OFF; raytrace/05_mc_gpu.js) ===
  // When state.mcGpuEnabled is true and the async GPU pipeline holds a
  // completed result whose physics fingerprint matches the CURRENT state for
  // this exact (td, nR), consume it here so existing sync callers benefit
  // transparently. Otherwise the hook returns null (and may schedule a
  // background GPU run for the sample plane) and the CPU chain below runs
  // unchanged. GPU vs CPU agreement is statistical (independent RNG streams),
  // validated in paper/validation/run_mc_gpu_check.py.
  if (typeof state !== 'undefined' && state.mcGpuEnabled &&
      typeof window._mcGpuSyncHook === 'function') {
    try { var _g = window._mcGpuSyncHook(td, nR); if (_g) return _g; } catch (e) {}
  }
  var E=state.energy, ps=photonSrc(E);
  var sX=ps.Sx,sY=ps.Sy,sXp=ps.Sxp,sYp=ps.Syp;
  var dcmTh=(typeof MOTORS!=='undefined'&&MOTORS.dcm&&MOTORS.dcm.theta)?MOTORS.dcm.theta.value:null;
  var isWB=(typeof _forceNonWB==='undefined'||!_forceNonWB)&&(td<(pos('dcm')||32)||(dcmTh!==null&&Math.abs(dcmTh)<0.1));
  var wbUniform=false, wbHalfAngH=0, wbHalfAngV=0;
  if(isWB){
    var wbDist=pos('wbslit')||27.8;
    wbHalfAngH=(state.wbH*0.5e-3+3*sX)/wbDist;
    wbHalfAngV=(state.wbV*0.5e-3+3*sY)/wbDist;
    wbUniform=true;
  }
  // Per-ray energy: Gaussian sampling around DCM center energy.
  // state.sourceBW_eV controls the energy spread (FWHM-like, in eV).
  // Each ray gets a slightly different energy, enabling per-ray Bragg matching.
  var E_eV_center = E * 1000;
  var srcBW_eV = (typeof state.sourceBW_eV === 'number') ? state.sourceBW_eV : 1.0;
  var srcBW = (srcBW_eV > 0 && E_eV_center > 0) ? srcBW_eV / E_eV_center : 0;
  var rays=new Float64Array(nR*RS);
  for(var i=0;i<nR;i++){var o=i*RS;
    rays[o]=gaussRand()*sX;rays[o+1]=gaussRand()*sY;
    if(wbUniform){
      rays[o+2]=(Math.random()*2-1)*wbHalfAngH;
      rays[o+3]=(Math.random()*2-1)*wbHalfAngV;
    }else{
      rays[o+2]=gaussRand()*sXp;rays[o+3]=gaussRand()*sYp;
    }
    rayUpdateVz(rays,o); rays[o+5]=1;
    rays[o+6] = (srcBW > 0) ? E_eV_center * (1 + gaussRand() * srcBW * 0.5) : E_eV_center;
    rays[o+7] = 0;
  }
  // Undulator spectral envelope (importance sampling weight correction)
  // E_und from gap+harmonic, independent of DCM state.energy.
  // In normal operation (E_DCM = E_und), envelope ~ 1.0 (no effect).
  // When DCM is detuned from undulator, envelope -> 0 (beam vanishes).
  var _und_n = state.harmonic || 1;
  var _und_E1 = calcE1(calcK(calcB0(state.gap)));
  var _und_Epeak = _und_n * _und_E1;
  if (_und_Epeak > 1) {
    for (var i = 0; i < nR; i++) {
      var o = i * RS;
      if (rays[o+5] <= 0) continue;
      rays[o+5] *= _undulatorEnvelope(rays[o+6] * 0.001, _und_Epeak);
    }
  }
  return _mcTraceFromRays(rays, nR, td, null);
};

// === _mcTraceFromRays — element-chain + statistics core (A1 GPU split) ===
// PURE CODE MOTION from mcRayTrace (2026-06-12, validated vs the frozen
// pre-refactor CPU baseline in paper/validation/run_mc_gpu_check.py):
// traces an EXISTING ray buffer through the optical-element chain and
// computes the full result object. mcRayTrace generates the source rays and
// delegates here with opts=null (identical behavior to the original
// single-function engine). The opt-in WebGPU path (raytrace/05_mc_gpu.js)
// runs the source->M2 per-ray segment on the GPU and delegates the
// SSA/KB/statistics continuation here with:
//   opts.ld0          = plane (m) the rays currently sit at — elements with
//                       p <= ld0 are skipped (already applied upstream)
//   opts.elementTrace = pre-seeded per-element snapshots from the GPU segment
window._mcTraceFromRays = function(rays, nR, td, opts) {
  opts = opts || {};
  var ld0 = opts.ld0 || 0;
  var E = state.energy;
  var sorted=CD.map(function(c){return{id:c.id,tp:c.tp,name:c.name,p:pos(c.id)};})
    .filter(function(c){return c.p>0&&c.p<=td;}).sort(function(a,b){return a.p-b.p;});
  var dcmTh=(typeof MOTORS!=='undefined'&&MOTORS.dcm&&MOTORS.dcm.theta)?MOTORS.dcm.theta.value:null;
  var isWB=(typeof _forceNonWB==='undefined'||!_forceNonWB)&&(td<(pos('dcm')||32)||(dcmTh!==null&&Math.abs(dcmTh)<0.1));
  var lam_m=HC/E*1e-10; // wavelength [m] for slit diffraction

  // === Nominal beam path: compute physical beam X at each component ===
  // Girder positions follow the nominal beam path (2*M1_pitch after M1, etc.)
  // Used to offset aperture checks and BPM centers to girder-local coordinates.
  var _m1Pos=pos('m1')||29, _m2Pos=pos('m2')||32, _dcmPos=pos('dcm')||30.4;
  var _m1Pitch=(state.m1pitch||2.5)*1e-3, _m2Pitch=(state.m2pitch||2.5)*1e-3;
  var _m1Defl=2*_m1Pitch; // beam angle after M1
  var _fixedExit=(typeof FIXED_EXIT!=='undefined'?FIXED_EXIT:12)*1e-3; // DCM fixed exit [m]
  // After M2, beam is parallel to axis again. Offset = M1 deflection * (M2-M1 distance)
  // DCM beam-frame transform means DCM doesn't add extra x offset.
  var _m2ChicaneX=_m1Defl*(_m2Pos-_m1Pos);
  // nomBeamX: nominal beam X at each position in the lab frame.
  // With beam-frame DCM transform, DCM internally doesn't change x significantly
  // (vx≈0 in beam frame → internal propagation cancels exit offset).
  // So beam x simply follows M1 deflection angle throughout.
  function _nomBeamX(compPos){
    if(compPos<=_m1Pos) return 0; // before M1: on optical axis
    if(compPos<=_m2Pos) return _m1Defl*(compPos-_m1Pos); // M1 to M2: beam at angle 2*M1_pitch
    // After M2: beam direction ≈ 0, fixed offset = M1 deflection * (M2-M1 distance)
    return _m1Defl*(_m2Pos-_m1Pos); // ~15mm
  }
  window._nomBeamX=_nomBeamX; // expose for applyMirrorMC/applyKBMC

  var ld=ld0;
  // Per-element cumulative snapshots for the Propagation Log (MC-synced,
  // 2026-06-10): after each optical element is applied, record the weighted
  // transmission (sum w / nR) and the weighted beam RMS at that plane.
  // One extra O(nR) pass per element — negligible vs the trace itself.
  var elementTrace=opts.elementTrace||[];
  for(var ci=0;ci<sorted.length;ci++){
    var c=sorted[ci];
    if(c.p<=ld0)continue; // resume support: element already applied upstream (GPU segment)
    var L=c.p-ld;
    if(L>0)for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
      var ivz=1/rays[o+4];rays[o]+=rays[o+2]*ivz*L;rays[o+1]+=rays[o+3]*ivz*L;}
    switch(c.tp){
    case 'slit':{
      var wb=c.id==='wbslit',hH,hV,cxO,cyO;
      if(wb){hH=state.wbH*.5e-3;hV=state.wbV*.5e-3;cxO=(state.wbCX||0)*1e-3;cyO=(state.wbCY||0)*1e-3;}
      else if(c.id==='kbslit'){hH=(state.kbslitH||5000)*.5e-6;hV=(state.kbslitV||5000)*.5e-6;cxO=(state.kbslitCX||0)*1e-6;cyO=(state.kbslitCY||0)*1e-6;}
      else{hH=state.ssaH*.5e-6;hV=state.ssaV*.5e-6;cxO=(state.ssaCX||0)*1e-6;cyO=(state.ssaCY||0)*1e-6;}
      // Clip rays outside slit aperture
      for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
        if(Math.abs(rays[o]-cxO)>hH||Math.abs(rays[o+1]-cyO)>hV){rays[o+5]=0;}}
      if(typeof _noSSADiffraction==='undefined'||!_noSSADiffraction){
        if(!wb && c.id==='ssa' && typeof _applySSAHybrid==='function'){
          _applySSAHybrid(rays, nR, E, hH, hV, cxO, cyO);
        } else if(!wb){
          // Fallback: Fraunhofer sinc^2 per-ray kicks
          var dfH=(hH>1e-10)?lam_m/(Math.PI*2*hH):0;
          var dfV=(hV>1e-10)?lam_m/(Math.PI*2*hV):0;
          for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
            if(dfH>1e-12){rays[o+2]+=sincSqRand()*dfH;}
            if(dfV>1e-12){rays[o+3]+=sincSqRand()*dfV;}
            if(dfH>1e-12||dfV>1e-12)rayUpdateVz(rays,o);}
        }
      }
      break;}
    case 'hmirror': applyMirrorMC(rays,nR,c.id,E); break;
    case 'dcm': applyDCM_MC(rays,nR,E); break;
    case 'kbv': applyKBMC(rays,nR,'kbv',E); break;
    case 'kbh': applyKBMC(rays,nR,'kbh',E); break;
    }
    ld=c.p;
    // Element-plane snapshot: cumulative weighted transmission + beam moments
    {var _tw=0,_tmx=0,_tmy=0;
     for(var i=0;i<nR;i++){var o=i*RS;var _w=rays[o+5];if(_w<=0)continue;
       _tw+=_w;_tmx+=rays[o]*_w;_tmy+=rays[o+1]*_w;}
     var _tsx=0,_tsy=0;
     if(_tw>0){_tmx/=_tw;_tmy/=_tw;
       for(var i=0;i<nR;i++){var o=i*RS;var _w=rays[o+5];if(_w<=0)continue;
         var _dx=rays[o]-_tmx,_dy=rays[o+1]-_tmy;_tsx+=_dx*_dx*_w;_tsy+=_dy*_dy*_w;}
       _tsx=Math.sqrt(_tsx/_tw);_tsy=Math.sqrt(_tsy/_tw);}
     elementTrace.push({id:c.id,name:c.name||c.id,tp:c.tp,dist:c.p,
       T_cum:_tw/nR,sigH:_tsx,sigV:_tsy});}
  }
  // Final free-space drift to target distance
  var fL=td-ld;
  if(fL>0)for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
    var ivz=1/rays[o+4];rays[o]+=rays[o+2]*ivz*fL;rays[o+1]+=rays[o+3]*ivz*fL;}
  // Hybrid Fresnel wave propagation for KB mirrors
  // Applied AFTER all drifts (rays at sample). Adds Fresnel diffraction correction.
  var hasKB = sorted.some(function(c){ return c.tp === 'kbv' || c.tp === 'kbh'; });
  if (hasKB && td > 149 && typeof _applyHybridFresnel === 'function') {
    _applyHybridFresnel(rays, nR, E, td);
  }
  var al=[],sw=0,mx=0,my=0;
  var tagCounts = [0, 0, 0, 0];  // [direct, V-only, H-only, focused]
  for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]>0){
    var tag = rays[o+7] | 0;
    if (tag >= 0 && tag < 4) tagCounts[tag]++;
    al.push({x:rays[o],y:rays[o+1],w:rays[o+5],tag:tag});sw+=rays[o+5];mx+=rays[o]*rays[o+5];my+=rays[o+1]*rays[o+5];}}
  if(al.length<10)return{hist2d:null,margH:null,margV:null,grid:MC_GRID,
    nSurvived:0,nTotal:nR,sigH:1e-6,sigV:1e-6,fwhmH:2.355e-6,fwhmV:2.355e-6,fovH:1e-5,fovV:1e-5,
    nBeams:{direct:0,vOnly:0,hOnly:0,focused:0},elementTrace:elementTrace};
  mx/=sw;my/=sw;
  // For FWHM/sigma: use focused rays (tag=3) when KB is active
  var al_fwhm = al, mx_f = mx, my_f = my, sw_f = sw;
  if (hasKB && tagCounts[3] > 10) {
    al_fwhm = []; sw_f = 0; mx_f = 0; my_f = 0;
    for (var i = 0; i < nR; i++) {
      var o = i * RS;
      if (rays[o+5] > 0 && (rays[o+7] | 0) === 3) {
        al_fwhm.push({x:rays[o], y:rays[o+1], w:rays[o+5]});
        sw_f += rays[o+5]; mx_f += rays[o] * rays[o+5]; my_f += rays[o+1] * rays[o+5];
      }
    }
    mx_f /= sw_f; my_f /= sw_f;
  }
  var vx2=0,vy2=0;
  for(var i=0;i<al_fwhm.length;i++){vx2+=al_fwhm[i].w*Math.pow(al_fwhm[i].x-mx_f,2);vy2+=al_fwhm[i].w*Math.pow(al_fwhm[i].y-my_f,2);}
  var sH=Math.sqrt(vx2/sw_f),sV=Math.sqrt(vy2/sw_f);
  var screenFov;
  var samplePos = pos('sample') || 150;
  if (isWB) { screenFov = 5e-3; }
  else if (td > samplePos + 0.01) {
    // Post-sample (>10mm): auto-FOV from ALL rays (shows all 4 beams)
    var maxExt = 0;
    for (var i = 0; i < al.length; i++) {
      var ax = Math.abs(al[i].x), ay = Math.abs(al[i].y);
      if (ax > maxExt) maxExt = ax;
      if (ay > maxExt) maxExt = ay;
    }
    screenFov = Math.max(maxExt * 1.5, 1e-3);  // 1.5x margin, min 1mm
  }
  else if (td > samplePos - 0.05) {
    // Fixed 300nm square FOV for sample plane.
    screenFov = 0.15e-6;  // +/-150nm = 300nm total
  }
  else if (td > (pos('kbv')||149.69) - 0.01) { screenFov = 0.5e-3; }  // KB-V/KB-H: 1mm total FOV
  else if (td > (pos('kbv')||149.69) - 1) { screenFov = 2.5e-3; }  // KB slit region: 5mm total FOV
  else if (td > (pos('xbpm3')||140) - 1) { screenFov = 5e-3; }
  else if (td > 50) { screenFov = 0.075e-3; }
  else { screenFov = 1.5e-3; }
  var fH=screenFov, fV=screenFov;
  // Override with fixed BPM FOV if this position matches a BPM with optics.fov
  var _bpmFixedFov = null;
  if (typeof CD !== 'undefined') {
    for (var _ci = 0; _ci < CD.length; _ci++) {
      if (CD[_ci].tp === 'bpm' && CD[_ci].optics && CD[_ci].optics.fov) {
        var _bpmPos = (typeof pos === 'function') ? pos(CD[_ci].id) : CD[_ci].dp;
        if (Math.abs(_bpmPos - td) < 0.5) { _bpmFixedFov = CD[_ci].optics.fov; break; }
      }
    }
  }
  if (_bpmFixedFov) { fH = _bpmFixedFov; fV = _bpmFixedFov; }
  // Histogram center: default = main beam (x=0 in beam frame).
  // During alignment, _alignBpmCenter can override to pan to reflected beam.
  var cxS=(typeof window._alignBpmCenter==='number')?window._alignBpmCenter:0;
  var cyS=0;
  var G=MC_GRID,h2=new Float64Array(G*G),mH2=new Float64Array(G),mV2=new Float64Array(G);
  for(var i=0;i<al.length;i++){var xi=Math.floor((al[i].x-cxS+fH)/(2*fH)*G),yi=Math.floor((al[i].y-cyS+fV)/(2*fV)*G);
    if(xi>=0&&xi<G&&yi>=0&&yi<G){h2[yi*G+xi]+=al[i].w;mH2[xi]+=al[i].w;mV2[yi]+=al[i].w;}}
  // FWHM: use fine 1D histogram (fixed 300nm FOV) for sample-plane accuracy
  var fwH, fwV, fmH = null, fmV = null, fFH = 0, fFV = 0, GF = 201;
  if (td > samplePos - 0.05 && td < samplePos + 0.5 && al.length > 50) {
    fFH = 0.15e-6;  // +/-150nm = 300nm total
    fFV = 0.15e-6;
    fmH = new Float64Array(GF); fmV = new Float64Array(GF);
    for (var i = 0; i < al_fwhm.length; i++) {
      var xi = Math.floor((al_fwhm[i].x - mx_f + fFH) / (2 * fFH) * GF);
      var yi = Math.floor((al_fwhm[i].y - my_f + fFV) / (2 * fFV) * GF);
      if (xi >= 0 && xi < GF) fmH[xi] += al_fwhm[i].w;
      if (yi >= 0 && yi < GF) fmV[yi] += al_fwhm[i].w;
    }
    fwH = _margFwhm(fmH, GF, fFH);
    fwV = _margFwhm(fmV, GF, fFV);
  } else {
    fwH = _margFwhm(mH2, G, fH);
    fwV = _margFwhm(mV2, G, fV);
  }
  // Divergence statistics: both weighted and unweighted (S4-compatible)
  var divH2=0,divV2=0,divSw=0,divHm=0,divVm=0;
  var udivH2=0,udivV2=0,udivN=0,udivHm=0,udivVm=0;
  for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
    var w=rays[o+5];var ivz=1/rays[o+4];var dh=rays[o+2]*ivz,dv=rays[o+3]*ivz;
    divHm+=w*dh;divVm+=w*dv;divSw+=w;
    udivHm+=dh;udivVm+=dv;udivN++;}
  if(divSw>0){divHm/=divSw;divVm/=divSw;}
  if(udivN>0){udivHm/=udivN;udivVm/=udivN;}
  for(var i=0;i<nR;i++){var o=i*RS;if(rays[o+5]<=0)continue;
    var w=rays[o+5];var ivz=1/rays[o+4];var dh=rays[o+2]*ivz,dv=rays[o+3]*ivz;
    divH2+=w*(dh-divHm)*(dh-divHm);divV2+=w*(dv-divVm)*(dv-divVm);
    udivH2+=(dh-udivHm)*(dh-udivHm);udivV2+=(dv-udivVm)*(dv-udivVm);}
  var sigDivH=divSw>0?Math.sqrt(divH2/divSw):0, sigDivV=divSw>0?Math.sqrt(divV2/divSw):0;
  var usigDivH=udivN>1?Math.sqrt(udivH2/udivN):0, usigDivV=udivN>1?Math.sqrt(udivV2/udivN):0;
  // Weight statistics for diagnostics
  var wMin=Infinity,wMax=-Infinity,wMean=0;
  for(var i=0;i<al.length;i++){var w=al[i].w;if(w<wMin)wMin=w;if(w>wMax)wMax=w;wMean+=w;}
  wMean=al.length>0?wMean/al.length:0;
  // Focused-only weight sum (tag=3: both KB-V and KB-H reflected)
  var wSumFocused=0;
  if(hasKB&&tagCounts[3]>0){for(var i=0;i<al.length;i++){if((al[i].tag|0)===3)wSumFocused+=al[i].w;}}
  return{hist2d:h2,margH:mH2,margV:mV2,grid:G,nSurvived:al.length,nTotal:nR,meanH:mx_f,meanV:my_f,
    sigH:sH,sigV:sV,fwhmH:fwH,fwhmV:fwV,fovH:fH,fovV:fV,meanX:mx_f,meanY:my_f,
    sigDivH:sigDivH,sigDivV:sigDivV,usigDivH:usigDivH,usigDivV:usigDivV,
    wMin:wMin,wMax:wMax,wMean:wMean,wSumFocused:wSumFocused,
    fineMargH:fmH,fineMargV:fmV,fineFovH:fFH,fineFovV:fFV,fineGrid:GF,
    nBeams:{direct:tagCounts[0],vOnly:tagCounts[1],hOnly:tagCounts[2],focused:tagCounts[3]},
    elementTrace:elementTrace,
    _aliveRays:al};
};

// === MC-based alignment signals ===
window.mirrorHalfCutSignal = function(mirrorId, motorVal, detId, motorKey) {
  var mk = motorKey || (mirrorId==='dcm' ? 'y1' : 'z');
  var prev = mVal(mirrorId, mk, 0);
  try { MOTORS[mirrorId][mk].value = motorVal; } catch(e) {}
  var pitch = (mirrorId==='m1') ? state.m1pitch : (mirrorId==='m2') ? state.m2pitch : 0;
  console.log('[HalfCut] ' + mirrorId + ' ' + mk + '=' + motorVal.toFixed(2) +
    ' pitch=' + pitch + ' det=' + detId + ' detPos=' + pos(detId));
  var mc = mcRayTrace(pos(detId), 40000);
  console.log('[HalfCut] survived=' + mc.nSurvived + '/' + mc.nTotal +
    ' ratio=' + (mc.nSurvived/mc.nTotal*100).toFixed(1) + '%');
  try { MOTORS[mirrorId][mk].value = prev; } catch(e) {}
  return (mc.wMean||1) * mc.nSurvived / mc.nTotal * 1e12 * (0.97 + 0.06 * Math.random());
};

// Set M1/M2 pitch (mrad), trace 40k rays to a detector, return vertical centroid drift (mm) and survival flux for rotation-center scans.
window.mirrorRockingSignal = function(mirrorId, pitch_mrad, detId) {
  var k=(mirrorId==='m1')?'m1pitch':'m2pitch', prev=state[k];
  state[k]=pitch_mrad;
  var mc=mcRayTrace(pos(detId),40000);
  state[k]=prev;
  var posV=mc.meanY?mc.meanY*1000:0;
  return{posV:posV,posH:0,flux:mc.nSurvived/mc.nTotal*1e12};
};

// === DCM MC-based alignment signals ===
window.dcmRockingSignal = function(dTheta2_arcsec, detId) {
  var prev = mVal('dcm','dTheta2',0);
  try { MOTORS.dcm.dTheta2.value = dTheta2_arcsec; } catch(e){}
  var mc = mcRayTrace(pos(detId), 40000);
  try { MOTORS.dcm.dTheta2.value = prev; } catch(e){}
  return (mc.wMean||1) * mc.nSurvived / mc.nTotal * 1e12 * (0.97 + 0.06 * Math.random());
};

// Set DCM y2 offset (mm), trace 40k rays to a detector, return weighted survival flux with small jitter for the y2 alignment scan.
window.dcmY2Signal = function(y2_mm, detId) {
  var prev = mVal('dcm','y2',0);
  try { MOTORS.dcm.y2.value = y2_mm; } catch(e){}
  var mc = mcRayTrace(pos(detId), 40000);
  try { MOTORS.dcm.y2.value = prev; } catch(e){}
  return (mc.wMean||1) * mc.nSurvived / mc.nTotal * 1e12 * (0.97 + 0.06 * Math.random());
};

// Set a DCM piezo motor (dTheta2/y2/roll2) to val, trace rays, and return the full MC result plus vertical center shift (mm) and flux.
window.mcBeamWithDCM = function(motor, val, detId, nRays) {
  var key = (motor === 'dTheta2') ? 'dTheta2' : (motor === 'y2') ? 'y2' : 'roll2';
  var prev = mVal('dcm', key, 0);
  try { MOTORS.dcm[key].value = val; } catch(e){}
  var mc = mcRayTrace(pos(detId), nRays || 40000);
  try { MOTORS.dcm[key].value = prev; } catch(e){}
  mc.centerShiftV = mc.meanY ? mc.meanY * 1000 : 0;
  mc.flux = (mc.wMean||1) * mc.nSurvived / mc.nTotal * 1e12;
  return mc;
};

// === mcBeamWithPitch (inline merged: handles both mirror + DCM) ===
// Previously: base version (mirror only) + _origMcBWP override (DCM routing)
// Now: single function with DCM check
window.mcBeamWithPitch = function(mirrorId, val, detId, nRays) {
  // DCM routing (merged from _origMcBWP override)
  if (mirrorId === 'dcm') return mcBeamWithDCM('chi2', val, detId, nRays);
  // Mirror path (original base logic)
  var k=(mirrorId==='m1')?'m1pitch':'m2pitch', prev=state[k];
  state[k]=val;
  var mc=mcRayTrace(pos(detId),nRays||40000);
  state[k]=prev;
  mc.centerShiftV=mc.meanY?mc.meanY*1000:0;
  mc.flux=(mc.wMean||1)*mc.nSurvived/mc.nTotal*1e12;
  return mc;
};

// Ray count (40000) used for the lighter MC traces driving alignment scan signals.
window.ALIGN_MC_RAYS = 40000;
// Ray count (100000) used for full-resolution beam-profile MC traces.
window.PROFILE_MC_RAYS = 100000;

console.log('[' + APP_VTAG + '] MC engine: 100k rays, true MC alignment signals');
console.log('[' + APP_VTAG + '] DCM MC signals + alignment ray optimization');

// ESM bridge: expose module-scoped vars to globalThis
if(typeof M1_DM!=="undefined")globalThis.M1_DM=M1_DM;
if(typeof M1_F!=="undefined")globalThis.M1_F=M1_F;
if(typeof M1_P!=="undefined")globalThis.M1_P=M1_P;
if(typeof M2_DM!=="undefined")globalThis.M2_DM=M2_DM;
if(typeof M2_F!=="undefined")globalThis.M2_F=M2_F;
if(typeof MC_NRAYS!=="undefined")globalThis.MC_NRAYS=MC_NRAYS;
if(typeof M_PARAMS!=="undefined")globalThis.M_PARAMS=M_PARAMS;
if(typeof RS!=="undefined")globalThis.RS=RS;
if(typeof dcmBandwidth!=="undefined")globalThis.dcmBandwidth=dcmBandwidth;
if(typeof kbDiffLimit!=="undefined")globalThis.kbDiffLimit=kbDiffLimit;
if(typeof rayUpdateVz!=="undefined")globalThis.rayUpdateVz=rayUpdateVz;
if(typeof sincSqRand!=="undefined")globalThis.sincSqRand=sincSqRand;
if(typeof ALIGN_MC_RAYS!=="undefined")globalThis.ALIGN_MC_RAYS=ALIGN_MC_RAYS;
if(typeof M1_Q!=="undefined")globalThis.M1_Q=M1_Q;
if(typeof M2_P!=="undefined")globalThis.M2_P=M2_P;
if(typeof M2_Q!=="undefined")globalThis.M2_Q=M2_Q;
if(typeof MIRROR_STRIPES!=="undefined")globalThis.MIRROR_STRIPES=MIRROR_STRIPES;
if(typeof PROFILE_MC_RAYS!=="undefined")globalThis.PROFILE_MC_RAYS=PROFILE_MC_RAYS;
if(typeof _alignBpmCenter!=="undefined")globalThis._alignBpmCenter=_alignBpmCenter;
if(typeof _applyHybridFresnel!=="undefined")globalThis._applyHybridFresnel=_applyHybridFresnel;
if(typeof _applySSAHybrid!=="undefined")globalThis._applySSAHybrid=_applySSAHybrid;
if(typeof _invalidateMCCache!=="undefined")globalThis._invalidateMCCache=_invalidateMCCache;
if(typeof _kbFootprintArr!=="undefined")globalThis._kbFootprintArr=_kbFootprintArr;
if(typeof _margFwhm!=="undefined")globalThis._margFwhm=_margFwhm;
if(typeof _mcSampleCache!=="undefined")globalThis._mcSampleCache=_mcSampleCache;
if(typeof _mcSampleDirty!=="undefined")globalThis._mcSampleDirty=_mcSampleDirty;
if(typeof _nomBeamX!=="undefined")globalThis._nomBeamX=_nomBeamX;
if(typeof _undulatorEnvelope!=="undefined")globalThis._undulatorEnvelope=_undulatorEnvelope;
if(typeof applyDCM_MC!=="undefined")globalThis.applyDCM_MC=applyDCM_MC;
if(typeof applyKBMC!=="undefined")globalThis.applyKBMC=applyKBMC;
if(typeof applyMirrorMC!=="undefined")globalThis.applyMirrorMC=applyMirrorMC;
if(typeof autoStripeForEnergy!=="undefined")globalThis.autoStripeForEnergy=autoStripeForEnergy;
if(typeof bendToFocal!=="undefined")globalThis.bendToFocal=bendToFocal;
if(typeof dcmRockingSignal!=="undefined")globalThis.dcmRockingSignal=dcmRockingSignal;
if(typeof dcmY2Signal!=="undefined")globalThis.dcmY2Signal=dcmY2Signal;
if(typeof getStripeMaterial!=="undefined")globalThis.getStripeMaterial=getStripeMaterial;
if(typeof labToMirror!=="undefined")globalThis.labToMirror=labToMirror;
if(typeof mVal!=="undefined")globalThis.mVal=mVal;
if(typeof mcBeamWithDCM!=="undefined")globalThis.mcBeamWithDCM=mcBeamWithDCM;
if(typeof mcBeamWithPitch!=="undefined")globalThis.mcBeamWithPitch=mcBeamWithPitch;
if(typeof mcRayTrace!=="undefined")globalThis.mcRayTrace=mcRayTrace;
if(typeof mirrorHalfCutSignal!=="undefined")globalThis.mirrorHalfCutSignal=mirrorHalfCutSignal;
if(typeof mirrorRockingSignal!=="undefined")globalThis.mirrorRockingSignal=mirrorRockingSignal;
if(typeof mirrorToLab!=="undefined")globalThis.mirrorToLab=mirrorToLab;
if(typeof reflect3D!=="undefined")globalThis.reflect3D=reflect3D;
if(typeof thermalSlopeError!=="undefined")globalThis.thermalSlopeError=thermalSlopeError;
