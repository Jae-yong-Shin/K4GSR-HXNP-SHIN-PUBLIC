'use strict';
// ===== raytrace/02_propagation.js — Gaussian Beam Propagation Engine =====
// @module raytrace/02_propagation
// @exports propagateBeam
// Provides: propagateBeam (element-by-element analytical Gaussian beam tracking)
// Used by Propagation Log to show beam state at each optical element

// === Beta values recalculation ===
(function(){
  BETA_X = 6.334; BETA_Y = 2.841;
  SIG_EX = Math.sqrt(EMIT_X * BETA_X);
  SIG_EXP = Math.sqrt(EMIT_X / BETA_X);
  SIG_EY = Math.sqrt(EMIT_Y * BETA_Y);
  SIG_EYP = Math.sqrt(EMIT_Y / BETA_Y);
  console.log('[' + APP_VTAG + '] Beta=' + BETA_X.toFixed(3) + '/' +
    BETA_Y.toFixed(3) + ' sigX=' +
    (SIG_EX*1e6).toFixed(1) + 'um sigY=' +
    (SIG_EY*1e6).toFixed(1) + 'um');
})();

// === propagateBeam: Gaussian beam through optical elements ===
// ROLE (updated 2026-06-10):
//   propagateBeam() is the fast ANALYTIC per-element estimator used by the
//   Propagation Log (element-by-element sigma/flux table). It is NOT the
//   authoritative sample-plane flux: this chain applies mirror reflectivity
//   only (case 'hmirror') and does not model the M1 sagittal / M2 tangential
//   focusing onto the SSA (= secondary source at 58 m), so it over-clips at
//   the SSA by ~300x (flux decomposition 2026-06-10). Sample-position flux
//   for ANY display/simulation must come from the single API
//     window.sampleFlux()   (defined below; routes to the MC chain).
//   getElementFlux(name) remains available for upstream-element estimates
//   (WB/M1/DCM/M2: analytic chain is reasonable there) and the log popup.
function propagateBeam(targetDist) {
  var E = state.energy;
  var lambda_nm = 12.3984 / E * 0.1; // nm
  var ps = photonSrc(E);

  var beam = {
    sigH: ps.Sx, sigV: ps.Sy,
    sigHp: ps.Sxp, sigVp: ps.Syp,
    flux: typeof sourceFlux === 'function' ? sourceFlux(E) : onAxisFlux(calcK(calcB0(state.gap)), state.harmonic),
    cohH: lambda_nm * 1e-9 / (2 * ps.Sxp),
    cohV: lambda_nm * 1e-9 / (2 * ps.Syp),
    E: E, lastDist: 0, elements: []
  };

  var sorted = CD.map(function(c) {
    return { id: c.id, tp: c.tp, name: c.name, p: pos(c.id) };
  }).sort(function(a, b) { return a.p - b.p; });

  for (var ci = 0; ci < sorted.length; ci++) {
    var comp = sorted[ci];
    if (comp.p > targetDist) break;
    if (comp.p <= 0) continue;

    var drift = comp.p - beam.lastDist;
    if (drift > 0) {
      beam.sigH = Math.sqrt(beam.sigH * beam.sigH + Math.pow(beam.sigHp * drift, 2));
      beam.sigV = Math.sqrt(beam.sigV * beam.sigV + Math.pow(beam.sigVp * drift, 2));
    }

    var effect = 'drift';
    switch (comp.tp) {
      case 'slit': {
        var isWB = comp.id === 'wbslit';
        var isKB = comp.id === 'kbslit';
        var slitH, slitV;
        if (isWB) { slitH = state.wbH * 0.5e-3; slitV = state.wbV * 0.5e-3; }
        else if (isKB) { slitH = (state.kbslitH || 5000) * 0.5e-6; slitV = (state.kbslitV || 5000) * 0.5e-6; }
        else { slitH = state.ssaH * 0.5e-6; slitV = state.ssaV * 0.5e-6; }
        if (slitH < beam.sigH * 2.355) {
          beam.flux *= Math.min(1, slitH * 2 / (beam.sigH * 2.355 * 2));
          beam.sigH = Math.min(beam.sigH, slitH / 2.355);
          var diffDivH = lambda_nm * 1e-9 / (2 * Math.PI * slitH);
          beam.sigHp = Math.sqrt(Math.pow(beam.sigHp, 2) + Math.pow(diffDivH, 2));
        }
        if (slitV < beam.sigV * 2.355) {
          beam.flux *= Math.min(1, slitV * 2 / (beam.sigV * 2.355 * 2));
          beam.sigV = Math.min(beam.sigV, slitV / 2.355);
          var diffDivV = lambda_nm * 1e-9 / (2 * Math.PI * slitV);
          beam.sigVp = Math.sqrt(Math.pow(beam.sigVp, 2) + Math.pow(diffDivV, 2));
        }
        effect = isWB ? 'WB slit clip' : (isKB ? 'KB slit clip' : 'SSA clip');
        break;
      }
      case 'hmirror': {
        var pitch = comp.id === 'm1' ? state.m1pitch : state.m2pitch;
        var R = mirrorR(E, pitch, RH);
        beam.flux *= R;
        effect = 'H-mirror R=' + (R * 100).toFixed(1) + '%';
        break;
      }
      case 'dcm': {
        var T = dcmThru(E);
        beam.flux *= T;
        var dw = darwinW(E) / 206265;
        beam.sigVp = Math.sqrt(Math.pow(beam.sigVp, 2) + Math.pow(dw * 0.1, 2));
        effect = 'DCM T=' + (T * 100).toFixed(1) + '%';
        break;
      }
      case 'kbv': {
        var pV = comp.p - pos('ssa');
        var qV = pos('sample') - comp.p;
        var MV = qV / pV;
        beam.sigV = beam.sigV * MV;
        beam.sigVp = beam.sigVp / MV;
        var kbvPitch = state.kbvpitch || 3;
        beam.flux *= mirrorR(E, kbvPitch, PT);
        effect = 'KB-V M=' + (1 / MV).toFixed(0) + 'x';
        break;
      }
      case 'kbh': {
        var pH = comp.p - pos('ssa');
        var qH = pos('sample') - comp.p;
        var MH = qH / pH;
        beam.sigH = beam.sigH * MH;
        beam.sigHp = beam.sigHp / MH;
        var kbhPitch = state.kbhpitch || 3;
        beam.flux *= mirrorR(E, kbhPitch, PT);
        effect = 'KB-H M=' + (1 / MH).toFixed(0) + 'x';
        break;
      }
      case 'atten': {
        var T_att = typeof attenTransmission === 'function' ? attenTransmission(E) : 1;
        beam.flux *= T_att;
        effect = 'Atten T=' + (T_att * 100).toFixed(1) + '%';
        break;
      }
      case 'sample': {
        // KB focal spot correction: use proper imaging formula instead of
        // broken drift-from-demag model (which explodes due to sigHp/MH)
        var kbPs2 = photonSrc(E);
        var kbEH2 = Math.min(kbPs2.Sx * M1_DM, state.ssaH * 0.5e-6);
        var kbEV2 = Math.min(kbPs2.Sy * M2_DM, state.ssaV * 0.5e-6);
        var kbPV2 = pos('kbv') - pos('ssa'), kbQV2 = pos('sample') - pos('kbv');
        var kbPH2 = pos('kbh') - pos('ssa'), kbQH2 = pos('sample') - pos('kbh');
        var dl2 = kbDiffLimit();
        var kbSV2 = kbEV2 * (kbQV2 / kbPV2), kbSH2 = kbEH2 * (kbQH2 / kbPH2);
        beam.sigV = Math.sqrt(kbSV2 * kbSV2 + dl2.sigV * dl2.sigV);
        beam.sigH = Math.sqrt(kbSH2 * kbSH2 + dl2.sigH * dl2.sigH);
        // Post-focus divergence (NA-limited)
        var sinG2 = Math.sin((state.kbvpitch || 3) * 1e-3);
        beam.sigVp = 0.300 * sinG2 / (2 * kbQV2) / 2.355;
        beam.sigHp = 0.100 * sinG2 / (2 * kbQH2) / 2.355;
        var spotH2 = beam.sigH * 2.355e9, spotV2 = beam.sigV * 2.355e9;
        effect = 'KB focus ' + spotH2.toFixed(0) + 'x' + spotV2.toFixed(0) + ' nm';
        break;
      }
      default:
        break;
    }

    beam.lastDist = comp.p;
    beam.elements.push({
      id: comp.id, name: comp.name, dist: comp.p, effect: effect,
      sigH: beam.sigH, sigV: beam.sigV, flux: beam.flux
    });
  }

  var finalDrift = targetDist - beam.lastDist;
  if (finalDrift > 0) {
    beam.sigH = Math.sqrt(Math.pow(beam.sigH, 2) + Math.pow(beam.sigHp * finalDrift, 2));
    beam.sigV = Math.sqrt(beam.sigV * beam.sigV + Math.pow(beam.sigVp * finalDrift, 2));
  }

  var fwhmH_um = beam.sigH * 2.355e6;
  var fwhmV_um = beam.sigV * 2.355e6;
  beam.cohFracH = Math.min(1, beam.cohH / (beam.sigH * 2.355));
  beam.cohFracV = Math.min(1, beam.cohV / (beam.sigV * 2.355));
  beam.fwhmH_um = fwhmH_um;
  beam.fwhmV_um = fwhmV_um;
  beam.fwhmH_nm = fwhmH_um * 1000;
  beam.fwhmV_nm = fwhmV_um * 1000;

  // KB focal spot correction
  if (targetDist >= pos('ssa') - 0.1) {
    var kbPs = photonSrc(state.energy);
    var kbEH = Math.min(kbPs.Sx * M1_DM, state.ssaH * 0.5e-6);
    var kbEV = Math.min(kbPs.Sy * M2_DM, state.ssaV * 0.5e-6);
    if (targetDist >= pos('sample') - 0.5) {
      var kbPV = pos('kbv') - pos('ssa'), kbQV = pos('sample') - pos('kbv');
      var kbPH = pos('kbh') - pos('ssa'), kbQH = pos('sample') - pos('kbh');
      var dl = kbDiffLimit();
      var kbSV = kbEV * (kbQV / kbPV), kbSH = kbEH * (kbQH / kbPH);
      // SSA is at KB conjugate plane (B≈0 in ABCD matrix):
      // SSA diffraction angular spread does NOT broaden the image — only affects flux.
      // Spot = quadrature(geometric demag, KB aperture diffraction)
      beam.sigV = Math.sqrt(kbSV * kbSV + dl.sigV * dl.sigV);
      beam.sigH = Math.sqrt(kbSH * kbSH + dl.sigH * dl.sigH);
      beam.fwhmV_um = beam.sigV * 2.355e6; beam.fwhmH_um = beam.sigH * 2.355e6;
      beam.fwhmV_nm = beam.fwhmV_um * 1000; beam.fwhmH_nm = beam.fwhmH_um * 1000;
    }
  }

  beam.dist = targetDist;

  // === Flux SSOT cache (see contract comment above) ===
  // Store the computed elements[] so UI builders can read flux by element name
  // without recomputing. Refreshed on every propagateBeam() call.
  try {
    window._lastPropagationResult = {
      elements: beam.elements.slice(),
      E: E,
      targetDist: targetDist,
      ts: Date.now()
    };
  } catch (_e) {}

  return beam;
}

// === getElementFlux: SSOT read API for UI ===
// Returns the cached post-propagation flux for the named element. Names are
// case-insensitive and matched against the element id ('sample', 'detector'/'det',
// 'kbh', 'kbv', 'ssa', 'dcm', 'm1', 'm2', ...). Returns null when the cache is
// stale (i.e., propagateBeam() has not yet been called for the current physics).
// Lazy recompute: when no cache exists, warm MC via focalSpot() and run
// propagateBeam() to the detector plane so 'sample' and 'detector' both populate.
window.getElementFlux = function(name) {
  if (!name) return null;
  var key = String(name).toLowerCase();
  // Alias: detector popup uses 'det' as the component id.
  if (key === 'detector') key = 'det';

  function _lookup() {
    var cache = window._lastPropagationResult;
    if (!cache || !cache.elements) return null;
    for (var i = 0; i < cache.elements.length; i++) {
      var el = cache.elements[i];
      var elKey = String(el.id || el.name || '').toLowerCase();
      if (elKey === key) return (typeof el.flux === 'number') ? el.flux : null;
    }
    return null;
  }

  var hit = _lookup();
  if (hit !== null) return hit;

  // Lazy warm: ensure MC is current, then propagate to the detector plane so
  // all downstream elements are populated.
  try {
    if (typeof focalSpot === 'function') focalSpot();
    if (typeof propagateBeam === 'function') {
      var detP = (typeof pos === 'function') ? pos('det') : null;
      if (!detP || isNaN(detP)) detP = (typeof pos === 'function') ? pos('sample') : 150;
      propagateBeam(detP);
    }
  } catch (_e) {}

  return _lookup();
};

// === sampleFlux: THE single sample-plane flux API (2026-06-10) ===
// User directive: every status window / experiment tab / simulator that needs
// the photon flux at the SAMPLE position must call this ONE function — do not
// scatter getElementFlux/photonFlux combinations across call sites.
//
// Authoritative model = MC ray-trace chain via photonFlux(state.energy)
// (user decision 2026-06-10): the MC correctly models the M1/M2 secondary-
// source focusing at the SSA and the small KB angular acceptance (~9%);
// the analytic propagateBeam chain lacks mirror focusing and over-clips at
// the SSA by ~300x, so its 'sample' element flux must NOT be used for
// display. (propagateBeam/getElementFlux remain for the per-element
// propagation log and upstream-element estimates.)
//
// Lazy warm: runs focalSpot() once when the MC cache is cold so photonFlux
// takes the MC path instead of its coarse cold-start analytic fallback.
// Returns ph/s (Number). Returns 0 when no engine is available (headless
// stubs) so callers can apply their own last-resort default.
window.sampleFlux = function() {
  // While the SPECTRA acceptance lookup table is still fetching, return 0
  // ('—' in displays) instead of flashing the Kim filament fallback value
  // (~2.5x high, picks wrong harmonic) for the first few hundred ms after
  // page load. Once the fetch resolves (loaded OR failed), values flow
  // normally and a one-shot re-render refreshes the visible displays.
  try {
    if (typeof _falState !== 'undefined' && _falState &&
        !_falState.loaded && !_falState.failed) {
      if (typeof fluxAcceptanceLookupReady === 'function' && !window._sfReadyHooked) {
        window._sfReadyHooked = true;
        fluxAcceptanceLookupReady().then(function() {
          try { if (typeof updateLiveBeamInfo === 'function') updateLiveBeamInfo(); } catch (e) {}
          try { if (typeof _updateExptBeamlineStatus === 'function') _updateExptBeamlineStatus(); } catch (e) {}
        });
      }
      return 0;
    }
  } catch (_e0) {}
  try {
    if ((typeof _mcSampleCache === 'undefined' || !_mcSampleCache) &&
        typeof focalSpot === 'function') {
      focalSpot();
    }
  } catch (_e) {}
  try {
    if (typeof photonFlux === 'function') {
      var f = photonFlux(state.energy);
      if (f !== null && f !== undefined && isFinite(f)) return f;
    }
  } catch (_e2) {}
  return 0;
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof propagateBeam!=="undefined")globalThis.propagateBeam=propagateBeam;
if(typeof window!=="undefined"&&window.getElementFlux)globalThis.getElementFlux=window.getElementFlux;
if(typeof window!=="undefined"&&window.sampleFlux)globalThis.sampleFlux=window.sampleFlux;
