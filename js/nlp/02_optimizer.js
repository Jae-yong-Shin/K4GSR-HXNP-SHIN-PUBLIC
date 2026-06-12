'use strict';
// ===== nlp/02_optimizer.js — Beamline Optimizer (AGR Sweep) =====
// @module nlp/02_optimizer
// @exports OPTICAL_CONSTRAINTS, _SSA_SWEEP, _buildExplanation, _optRestoreState, _optSaveState, _optSetEnergy, _pad, _pendingOptimization, _renderOptimizationResult, applyOptimization, cancelOptimization, estimateSignal, optimizeBeamline, sweepEnergy, sweepSSA
// Adaptive Grid Refinement: findHarmonics() -> fine sweep -> quadratic polish
// Provides: optimizeBeamline, sweepEnergy, sweepSSA, estimateSignal, applyOptimization

// === Constraints ===
var OPTICAL_CONSTRAINTS = {
  crystal: 'Si111',
  energyRange: {eMin: 4.0, eMax: 25.0},
  ptL3_avoid: {min: 11.514, max: 11.614},
  ssaRange: {min: 5, max: 200},
  pitchRange: {min: 2.0, max: 5.0},
  gapMin: 5.0
};

// Fixed grid of secondary-source-aperture sizes in micrometers (5-200) iterated over by the SSA Pareto sweep.
var _SSA_SWEEP = [5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200];

// === State save/restore ===
function _optSaveState() {
  return {
    energy: state.energy,
    targetEnergy: state.targetEnergy,
    gap: state.gap,
    harmonic: state.harmonic,
    ssaH: state.ssaH,
    ssaV: state.ssaV,
    m1pitch: state.m1pitch,
    m2pitch: state.m2pitch,
    kbvpitch: state.kbvpitch,
    kbhpitch: state.kbhpitch
  };
}

// Write a saved snapshot back into state: energy, targetEnergy, gap, harmonic, ssaH/V, M1/M2 and KB-V/H pitches.
function _optRestoreState(saved) {
  state.energy = saved.energy;
  state.targetEnergy = saved.targetEnergy;
  state.gap = saved.gap;
  state.harmonic = saved.harmonic;
  state.ssaH = saved.ssaH;
  state.ssaV = saved.ssaV;
  state.m1pitch = saved.m1pitch;
  state.m2pitch = saved.m2pitch;
  state.kbvpitch = saved.kbvpitch;
  state.kbhpitch = saved.kbhpitch;
}

// === Helper: set energy state for evaluation ===
function _optSetEnergy(E_keV, harmInfo) {
  state.energy = E_keV;
  state.targetEnergy = E_keV;
  if (harmInfo) {
    state.harmonic = harmInfo.n;
    state.gap = harmInfo.gap;
  }
}

// === AGR Energy Sweep ===
window.sweepEnergy = function(element, edge, technique) {
  var elData = XRAY_ELEMENTS[element];
  if (!elData) return {error: 'Unknown element: ' + element};

  var edgeKey = edge || 'K';
  var E0_eV = elData[edgeKey];
  if (!E0_eV) return {error: element + ' ' + edgeKey + ' edge not found'};
  var E0 = E0_eV / 1000; // keV

  // Energy search range by technique
  var eMin, eMax;
  if (technique === 'xanes') {
    eMin = E0 - 0.1;
    eMax = E0 + 0.1;
  } else if (technique === 'xrf' || technique === 'xrf2d') {
    eMin = E0 + 0.5;
    eMax = E0 + 5.0;
  } else {
    eMin = E0 + 0.5;
    eMax = E0 + 10.0;
  }

  // Clamp to beamline range
  eMin = Math.max(eMin, OPTICAL_CONSTRAINTS.energyRange.eMin);
  eMax = Math.min(eMax, OPTICAL_CONSTRAINTS.energyRange.eMax);
  if (eMin >= eMax) return {error: 'Energy range out of Si(111) DCM limits (4-25 keV)'};

  var saved = _optSaveState();
  var curve = [];
  var peaks = [];

  try {
    // Phase 1: Analytical harmonic peaks
    var nSamples = 5;
    var allHarmonics = {};
    for (var si = 0; si <= nSamples; si++) {
      var Et = eMin + (eMax - eMin) * si / nSamples;
      var harms = findHarmonics(Et);
      for (var hi = 0; hi < harms.length; hi++) {
        var h = harms[hi];
        if (h.gap < OPTICAL_CONSTRAINTS.gapMin) continue;
        var peakE = h.n * h.E1;
        if (peakE < eMin - 1 || peakE > eMax + 1) continue;
        var key = 'n' + h.n;
        if (!allHarmonics[key] || h.flux > allHarmonics[key].flux) {
          allHarmonics[key] = {n: h.n, peakE: peakE, gap: h.gap, K: h.K, flux: h.flux};
        }
      }
    }

    var harmonicKeys = Object.keys(allHarmonics);
    if (harmonicKeys.length === 0) {
      _optRestoreState(saved);
      return {error: 'No feasible harmonics in ' + eMin.toFixed(1) + '-' + eMax.toFixed(1) + ' keV'};
    }

    // Phase 2: Fine sweep around each harmonic peak
    for (var ki = 0; ki < harmonicKeys.length; ki++) {
      var harm = allHarmonics[harmonicKeys[ki]];
      var dbw = 0;
      try { dbw = dcmBandwidth(harm.peakE); } catch(e) { dbw = 1e-4; }
      var window_keV = Math.max(0.5, dbw * harm.peakE * 5);
      var sweepMin = Math.max(eMin, harm.peakE - window_keV);
      var sweepMax = Math.min(eMax, harm.peakE + window_keV);
      var stepE = 0.001; // 1 eV = 0.001 keV

      for (var E = sweepMin; E <= sweepMax; E += stepE) {
        var hForE = selectBest(E);
        if (!hForE || hForE.gap < OPTICAL_CONSTRAINTS.gapMin) continue;

        _optSetEnergy(E, hForE);
        var fl = 0;
        try { fl = photonFlux(E); } catch(e) { continue; }
        if (fl <= 0) continue;

        // Mirror check
        var rhOk = true, ptOk = true;
        try {
          if (mirrorR(E, 3, RH) < 0.05) rhOk = false;
          if (mirrorR(E, 3, PT) < 0.05) ptOk = false;
        } catch(e) { /* skip check */ }

        var ptL3Warn = (E >= OPTICAL_CONSTRAINTS.ptL3_avoid.min &&
                        E <= OPTICAL_CONSTRAINTS.ptL3_avoid.max);

        curve.push({
          E: E, flux: fl, harmonic: hForE.n, gap: hForE.gap,
          rhOk: rhOk, ptOk: ptOk, ptL3Warn: ptL3Warn
        });
      }
    }

    if (curve.length === 0) {
      _optRestoreState(saved);
      return {error: 'No valid flux points found in sweep'};
    }

    // Phase 3: Find top-3 and quadratic polish
    curve.sort(function(a, b) { return b.flux - a.flux; });
    var top3 = curve.slice(0, Math.min(3, curve.length));

    for (var ti = 0; ti < top3.length; ti++) {
      var p = top3[ti];
      // Find points for quadratic fit
      var eL = p.E - stepE, eR = p.E + stepE;
      var hL = selectBest(eL), hR = selectBest(eR);
      if (hL && hR && hL.gap >= OPTICAL_CONSTRAINTS.gapMin && hR.gap >= OPTICAL_CONSTRAINTS.gapMin) {
        _optSetEnergy(eL, hL);
        var fL = 0; try { fL = photonFlux(eL); } catch(e) {}
        _optSetEnergy(eR, hR);
        var fR = 0; try { fR = photonFlux(eR); } catch(e) {}

        if (fL > 0 && fR > 0) {
          // Quadratic: f = a*x^2 + b*x + c, vertex at x = -b/(2a)
          var a = (fL + fR - 2 * p.flux) / (stepE * stepE);
          if (a < -1e-10) {
            var eOpt = p.E + stepE * (fL - fR) / (2 * (fL + fR - 2 * p.flux));
            var hOpt = selectBest(eOpt);
            if (hOpt && hOpt.gap >= OPTICAL_CONSTRAINTS.gapMin) {
              _optSetEnergy(eOpt, hOpt);
              var fOpt = 0; try { fOpt = photonFlux(eOpt); } catch(e) {}
              if (fOpt > p.flux) {
                p.E = eOpt; p.flux = fOpt; p.gap = hOpt.gap; p.harmonic = hOpt.n;
              }
            }
          }
        }
      }

      peaks.push({
        E: p.E, flux: p.flux, harmonic: p.harmonic, gap: p.gap,
        ptL3Warn: p.ptL3Warn || false
      });
    }

    _optRestoreState(saved);

    // Sort curve by energy for display
    curve.sort(function(a, b) { return a.E - b.E; });

    return {
      bestEnergy: peaks[0].E,
      bestFlux: peaks[0].flux,
      bestHarmonic: peaks[0].harmonic,
      bestGap: peaks[0].gap,
      curve: curve,
      peaks: peaks,
      E0_keV: E0,
      element: element,
      edge: edgeKey
    };
  } catch(err) {
    _optRestoreState(saved);
    return {error: 'Sweep error: ' + err.message};
  }
};

// === SSA Pareto Sweep ===
window.sweepSSA = function(energy, priority) {
  var saved = _optSaveState();
  var pareto = [];
  priority = priority || 'balanced';

  try {
    var hForE = selectBest(energy);
    if (!hForE || hForE.gap < OPTICAL_CONSTRAINTS.gapMin) {
      _optRestoreState(saved);
      return {error: 'No valid harmonic at ' + energy.toFixed(3) + ' keV'};
    }

    _optSetEnergy(energy, hForE);
    var sampleDist = pos('sample');
    var dl = kbDiffLimit();

    for (var si = 0; si < _SSA_SWEEP.length; si++) {
      var ssa = _SSA_SWEEP[si];
      state.ssaH = ssa;
      state.ssaV = ssa;

      var beam = propagateBeam(sampleDist);
      var cohFH = beam.cohFracH || 0;
      var cohFV = beam.cohFracV || 0;
      var degCoh = cohFH * cohFV;
      var cohFlux = beam.flux * degCoh;

      var fwhmH = beam.sigH * 2.355;
      var fwhmV = beam.sigV * 2.355;
      var spotH_nm = Math.sqrt(fwhmH * fwhmH + dl.fwhmH * dl.fwhmH) * 1e9;
      var spotV_nm = Math.sqrt(fwhmV * fwhmV + dl.fwhmV * dl.fwhmV) * 1e9;

      pareto.push({
        ssaH: ssa,
        flux: beam.flux,
        cohFlux: cohFlux,
        cohFracH: cohFH,
        cohFracV: cohFV,
        degCoh: degCoh,
        spotH_nm: spotH_nm,
        spotV_nm: spotV_nm
      });
    }

    _optRestoreState(saved);

    // Select recommended point by priority
    var recommended = null;
    if (priority === 'resolution') {
      // Min spot with flux > 1e8
      var best = null;
      for (var ri = 0; ri < pareto.length; ri++) {
        if (pareto[ri].flux > 1e8) {
          var spot = Math.max(pareto[ri].spotH_nm, pareto[ri].spotV_nm);
          if (!best || spot < best.spot) {
            best = {idx: ri, spot: spot};
          }
        }
      }
      recommended = best ? pareto[best.idx] : pareto[0];
    } else if (priority === 'flux') {
      // Max flux with spot < 500nm
      var bestF = null;
      for (var fi = 0; fi < pareto.length; fi++) {
        var spotMax = Math.max(pareto[fi].spotH_nm, pareto[fi].spotV_nm);
        if (spotMax < 500) {
          if (!bestF || pareto[fi].flux > bestF.flux) {
            bestF = {idx: fi, flux: pareto[fi].flux};
          }
        }
      }
      recommended = bestF ? pareto[bestF.idx] : pareto[pareto.length - 1];
    } else if (priority === 'coherence') {
      // Max cohFlux with degCoh > 0.3
      var bestC = null;
      for (var ci = 0; ci < pareto.length; ci++) {
        if (pareto[ci].degCoh > 0.3) {
          if (!bestC || pareto[ci].cohFlux > bestC.cohFlux) {
            bestC = {idx: ci, cohFlux: pareto[ci].cohFlux};
          }
        }
      }
      if (!bestC) {
        // Fallback: highest degCoh
        for (var cf = 0; cf < pareto.length; cf++) {
          if (!bestC || pareto[cf].degCoh > bestC.degCoh) {
            bestC = {idx: cf, degCoh: pareto[cf].degCoh};
          }
        }
      }
      recommended = bestC ? pareto[bestC.idx] : pareto[0];
    } else {
      // Balanced: flux / spotH^2
      var bestB = null;
      for (var bi = 0; bi < pareto.length; bi++) {
        var score = pareto[bi].flux / Math.pow(pareto[bi].spotH_nm, 2);
        if (!bestB || score > bestB.score) {
          bestB = {idx: bi, score: score};
        }
      }
      recommended = bestB ? pareto[bestB.idx] : pareto[0];
    }

    return {pareto: pareto, recommended: recommended, energy: energy, priority: priority};
  } catch(err) {
    _optRestoreState(saved);
    return {error: 'SSA sweep error: ' + err.message};
  }
};

// === Signal Estimation ===
window.estimateSignal = function(technique, element, ppm, flux, beamSize_nm, thickness_um) {
  var elData = XRAY_ELEMENTS[element];
  if (!elData) return {error: 'Unknown element: ' + element};
  var Z = elData.Z;

  // Use current state if not provided
  if (!flux || flux <= 0) {
    flux = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
    if (!flux) flux = 1e10;
  }
  if (!beamSize_nm || beamSize_nm <= 0) beamSize_nm = 100;
  if (!thickness_um || thickness_um <= 0) thickness_um = 10;
  if (!ppm || ppm <= 0) ppm = 10000;

  var wt_frac = ppm / 1e6;
  var thickness_cm = thickness_um * 1e-4;
  var dwell = 1.0; // 1 second reference

  if (technique === 'xrf' || technique === 'xrf2d') {
    // Use existing xrfSignal if available
    var matDensity = 2.5; // generic matrix
    try {
      var sig = xrfSignal(flux, state.energy * 1000, element, wt_frac, thickness_cm, matDensity, dwell);
      return {
        technique: technique,
        element: element,
        signal: sig.total,
        signalUnit: 'counts/s',
        details: {
          Ka: sig.counts_Ka / dwell,
          Kb: sig.counts_Kb / dwell,
          La: sig.counts_La / dwell,
          Lb: sig.counts_Lb / dwell,
          total: sig.total / dwell
        },
        flux: flux,
        ppm: ppm,
        beamSize_nm: beamSize_nm,
        dwell_s: dwell
      };
    } catch(e) {
      // Fallback simple model
      var yld = XRF_YIELDS[element];
      var omega = (yld && yld.omega_K) ? yld.omega_K : (0.015 * Z - 0.1);
      omega = Math.max(0.01, Math.min(1, omega));
      var rate = flux * wt_frac * omega * 0.001 * 0.01;
      return {
        technique: technique, element: element,
        signal: rate, signalUnit: 'counts/s',
        flux: flux, ppm: ppm, beamSize_nm: beamSize_nm, dwell_s: dwell
      };
    }
  } else if (technique === 'xanes') {
    // Edge jump estimation
    var delta_mu = 200 * Math.pow(Z / 26, 3); // cm^2/g approx
    var rho = 2.5;
    var edgeJump = delta_mu * wt_frac * rho * thickness_cm;
    var transI0 = flux * Math.exp(-50 * rho * thickness_cm); // rough total absorption
    return {
      technique: 'xanes', element: element,
      signal: edgeJump,
      signalUnit: 'delta_mu*t',
      details: {
        edgeJump: edgeJump,
        transmittedFlux: transI0,
        estimatedSNR: edgeJump * Math.sqrt(transI0 * dwell)
      },
      flux: flux, ppm: ppm, beamSize_nm: beamSize_nm, dwell_s: dwell
    };
  } else if (technique === 'ptycho') {
    // Coherent flux estimation
    var beam = null;
    try { beam = propagateBeam(pos('sample')); } catch(e) {}
    var cohFH = (beam && beam.cohFracH) ? beam.cohFracH : 0.3;
    var cohFV = (beam && beam.cohFracV) ? beam.cohFracV : 0.5;
    var degCoh = cohFH * cohFV;
    var cohFlux = flux * degCoh;
    return {
      technique: 'ptycho', element: element,
      signal: cohFlux,
      signalUnit: 'coh.ph/s',
      details: {
        totalFlux: flux,
        cohFracH: cohFH,
        cohFracV: cohFV,
        degCoh: degCoh,
        coherentFlux: cohFlux,
        sufficient: degCoh > 0.3
      },
      flux: flux, ppm: ppm, beamSize_nm: beamSize_nm, dwell_s: dwell
    };
  } else if (technique === 'xrd2d') {
    // Simple order-of-magnitude
    var illVol = Math.pow(beamSize_nm * 1e-7, 2) * thickness_cm;
    var intensity = flux * illVol * 1e8;
    return {
      technique: 'xrd2d', element: element,
      signal: intensity,
      signalUnit: 'counts/s (est)',
      flux: flux, ppm: ppm, beamSize_nm: beamSize_nm, dwell_s: dwell
    };
  }

  return {error: 'Unknown technique: ' + technique};
};

// === Main Optimizer ===
window.optimizeBeamline = function(opts) {
  if (!opts) return {error: 'No options provided'};
  var technique = opts.technique || 'xrf';
  var element = opts.element;
  var edge = opts.edge || 'K';
  var ppm = opts.ppm || 10000;
  var sampleType = opts.sampleType || 'powder';
  var thickness_um = opts.thickness_um || 10;
  var priority = opts.priority;

  // Auto-set priority for ptycho
  if (technique === 'ptycho' && !priority) priority = 'coherence';
  if (!priority) priority = 'balanced';

  if (!element) return {error: 'Element required'};
  var elData = XRAY_ELEMENTS[element];
  if (!elData) return {error: 'Unknown element: ' + element};

  var edgeE_eV = elData[edge];
  if (!edgeE_eV) return {error: element + ' ' + edge + ' edge not found in database'};
  var E0_keV = edgeE_eV / 1000;

  // Step 1-2: Energy range validation
  if (E0_keV > OPTICAL_CONSTRAINTS.energyRange.eMax) {
    var altMsg = '';
    if (elData.L3 && elData.L3 / 1000 <= OPTICAL_CONSTRAINTS.energyRange.eMax &&
        elData.L3 / 1000 >= OPTICAL_CONSTRAINTS.energyRange.eMin) {
      altMsg = '. Alternative: use ' + element + ' L3-edge (' + (elData.L3 / 1000).toFixed(3) + ' keV)';
    }
    return {
      error: element + ' ' + edge + '-edge (' + E0_keV.toFixed(2) + ' keV) exceeds Si(111) DCM limit (25 keV)' + altMsg,
      warnings: ['Si(311) CCM required for K-edge at this energy range']
    };
  }
  // Check if edge energy is below beamline minimum
  if (E0_keV < OPTICAL_CONSTRAINTS.energyRange.eMin) {
    return {
      error: element + ' ' + edge + '-edge (' + (E0_keV * 1000).toFixed(0) + ' eV) is below beamline minimum (4 keV). This edge is not accessible with the Si(111) DCM.',
      warnings: []
    };
  }

  var saved = _optSaveState();
  var warnings = [];
  var t0 = Date.now();

  try {
    // Step 3-5: AGR Energy Sweep
    var eSweep = sweepEnergy(element, edge, technique);
    if (eSweep.error) {
      _optRestoreState(saved);
      return {error: eSweep.error};
    }

    var bestE = eSweep.bestEnergy;
    var bestFlux = eSweep.bestFlux;

    // Check warnings from peaks
    var isPtL3Target = (element === 'Pt' && edge === 'L3');
    for (var pi = 0; pi < eSweep.peaks.length; pi++) {
      if (eSweep.peaks[pi].ptL3Warn && !isPtL3Target) {
        warnings.push('Pt L3 edge (11.564 keV) proximity: KB mirror reflectivity may vary');
      }
    }
    if (isPtL3Target) {
      warnings.push('KB mirrors use Pt coating: Pt L3 edge (11.564 keV) causes reflectivity anomaly. Flux estimate may differ from actual.');
    }

    // XANES: fix energy to edge
    if (technique === 'xanes') {
      bestE = E0_keV;
      var hXanes = selectBest(bestE);
      if (!hXanes || hXanes.gap < OPTICAL_CONSTRAINTS.gapMin) {
        _optRestoreState(saved);
        return {error: element + ' ' + edge + '-edge (' + E0_keV.toFixed(3) + ' keV) cannot be reached: no valid undulator harmonic at this energy', warnings: warnings};
      }
      _optSetEnergy(bestE, hXanes);
      try { bestFlux = photonFlux(bestE); } catch(e) {}
    }

    // Step 6: SSA Pareto Sweep
    var ssaSweep = sweepSSA(bestE, priority);
    if (ssaSweep.error) {
      _optRestoreState(saved);
      return {error: ssaSweep.error, warnings: warnings};
    }

    var rec = ssaSweep.recommended;
    if (!rec) {
      _optRestoreState(saved);
      return {error: 'No recommended SSA point found', warnings: warnings};
    }

    // Get harmonic info for recommended energy
    var bestH = selectBest(bestE);

    // Step 7: Signal estimation
    var sigEst = estimateSignal(technique, element, ppm, rec.flux, rec.spotH_nm, thickness_um);

    // Air absorption warning
    if (bestE < 6) {
      warnings.push('Low energy (' + bestE.toFixed(2) + ' keV): significant air absorption');
    }

    // Coherence warning for ptycho
    if (technique === 'ptycho' && rec.degCoh < 0.3) {
      warnings.push('Low coherence (degCoh=' + rec.degCoh.toFixed(2) + '): consider smaller SSA');
    }

    var elapsed = Date.now() - t0;

    // Build result
    var result = {
      recommended: {
        energy: bestE,
        harmonic: bestH ? bestH.n : 1,
        gap: bestH ? bestH.gap : state.gap,
        crystal: 'Si111',
        ssaH: rec.ssaH,
        ssaV: rec.ssaH,
        m1pitch: state.m1pitch || 2.5,
        m2pitch: state.m2pitch || 2.5
      },
      predicted: {
        flux: rec.flux,
        cohFlux: rec.cohFlux,
        spotH_nm: rec.spotH_nm,
        spotV_nm: rec.spotV_nm,
        cohFracH: rec.cohFracH,
        cohFracV: rec.cohFracV,
        degCoh: rec.degCoh,
        signal: sigEst.signal || 0,
        signalUnit: sigEst.signalUnit || '',
        resolution_nm: Math.max(rec.spotH_nm, rec.spotV_nm)
      },
      explanation: _buildExplanation(opts, bestE, E0_keV, rec, sigEst, eSweep),
      warnings: warnings,
      tradeoff: ssaSweep.pareto,
      energyCurve: eSweep.curve,
      energyPeaks: eSweep.peaks,
      elapsed_ms: elapsed,
      technique: technique,
      element: element,
      edge: edge,
      priority: priority
    };

    _optRestoreState(saved);

    // Store for apply/cancel
    window._pendingOptimization = result;

    // Render in chat
    _renderOptimizationResult(result);

    return result;
  } catch(err) {
    _optRestoreState(saved);
    return {error: 'Optimization error: ' + err.message, warnings: warnings};
  }
};

// === Build Korean explanation ===
function _buildExplanation(opts, bestE, E0_keV, rec, sigEst, eSweep) {
  var el = opts.element;
  var edge = opts.edge || 'K';
  var tech = opts.technique;
  var lines = [];

  lines.push(el + ' ' + edge + '-edge (' + (E0_keV * 1000).toFixed(0) + ' eV) ' +
    (tech === 'xrf' ? 'XRF' : tech === 'xanes' ? 'XANES' : tech === 'ptycho' ? 'Ptychography' : 'XRD') +
    ' optimization');

  lines.push('Recommended energy: ' + bestE.toFixed(3) + ' keV (harmonic ' + eSweep.bestHarmonic + ')');
  lines.push('Flux at sample: ' + rec.flux.toExponential(2) + ' ph/s');
  lines.push('Beam size: ' + rec.spotH_nm.toFixed(0) + ' x ' + rec.spotV_nm.toFixed(0) + ' nm');
  lines.push('SSA: ' + rec.ssaH + ' \u03BCm');

  if (rec.degCoh > 0) {
    lines.push('Coherence: ' + (rec.degCoh * 100).toFixed(1) + '% (H:' +
      (rec.cohFracH * 100).toFixed(0) + '% V:' + (rec.cohFracV * 100).toFixed(0) + '%)');
  }

  if (tech === 'ptycho') {
    lines.push('Coherent flux: ' + rec.cohFlux.toExponential(2) + ' coh.ph/s');
  }

  if (sigEst && sigEst.signal > 0) {
    lines.push('Estimated signal: ' + sigEst.signal.toExponential(2) + ' ' + sigEst.signalUnit);
  }

  if (opts.ppm) lines.push('Sample: ' + opts.ppm + ' ppm ' + el + ', ' + (opts.thickness_um || 10) + ' μm thick');

  return lines.join('\n');
}

// === Result Renderer ===
function _renderOptimizationResult(result) {
  if (typeof addChatMessage !== 'function') return;

  var lines = [];
  lines.push('=== Beamline Optimization Result ===');
  lines.push('');
  lines.push(result.explanation);
  lines.push('');

  // Warnings
  if (result.warnings && result.warnings.length > 0) {
    lines.push('[Warnings]');
    for (var wi = 0; wi < result.warnings.length; wi++) {
      lines.push('  ! ' + result.warnings[wi]);
    }
    lines.push('');
  }

  // Pareto table header
  lines.push('[SSA Trade-off Table]');
  lines.push('SSA(μm) | Flux(ph/s)  | CohFlux     | DegCoh | Spot H(nm) | Spot V(nm)');
  lines.push('--------|-------------|-------------|--------|------------|----------');

  var tradeoff = result.tradeoff || [];
  for (var ti = 0; ti < tradeoff.length; ti++) {
    var t = tradeoff[ti];
    var marker = (t.ssaH === result.recommended.ssaH) ? ' *' : '';
    lines.push(
      _pad(t.ssaH, 7) + ' | ' +
      _pad(t.flux.toExponential(2), 11) + ' | ' +
      _pad(t.cohFlux.toExponential(2), 11) + ' | ' +
      _pad((t.degCoh * 100).toFixed(1) + '%', 6) + ' | ' +
      _pad(t.spotH_nm.toFixed(0), 10) + ' | ' +
      t.spotV_nm.toFixed(0) + marker
    );
  }

  lines.push('');
  lines.push('(* = recommended)');
  lines.push('Elapsed: ' + result.elapsed_ms + ' ms');

  try {
    addChatMessage('assistant', lines.join('\n'), null, false);
  } catch(e) {
    console.log('[Optimizer] Render error:', e);
  }

  // Add Apply/Cancel message
  try {
    var btnMsg = {
      role: 'assistant',
      text: 'Apply this configuration?',
      actions: [
        {fn: 'applyOptimization', args: []}
      ],
      needConfirm: true,
      _optimizerButtons: true
    };
    if (typeof NLP_STATE !== 'undefined' && NLP_STATE.messages) {
      NLP_STATE.messages.push(btnMsg);
      NLP_STATE.pendingActions = btnMsg.actions;
      if (typeof renderChatMessages === 'function') renderChatMessages();
    }
  } catch(e) {
    console.log('[Optimizer] Button render error:', e);
  }
}

// Left-pad a value's string form with spaces to width n for fixed-column alignment in the trade-off table.
function _pad(v, n) {
  var s = String(v);
  while (s.length < n) s = ' ' + s;
  return s;
}

// === Apply / Cancel ===
window._pendingOptimization = null;

// Commit the pending recommendation to state and UI: set target energy, SSA H/V, sync sliders, call updateOptics.
window.applyOptimization = function() {
  var r = window._pendingOptimization;
  if (!r || !r.recommended) {
    return {error: 'No pending optimization to apply'};
  }

  try {
    // Apply energy (triggers gap/harmonic/DCM sync)
    if (typeof setTargetEnergy === 'function') {
      setTargetEnergy(r.recommended.energy);
    } else {
      state.energy = r.recommended.energy;
      state.targetEnergy = r.recommended.energy;
    }

    // Apply SSA
    state.ssaH = r.recommended.ssaH;
    state.ssaV = r.recommended.ssaV;

    // Sync UI sliders
    var ssaHEl = document.getElementById('ssaH');
    if (ssaHEl) ssaHEl.value = r.recommended.ssaH;
    var ssaVEl = document.getElementById('ssaV');
    if (ssaVEl) ssaVEl.value = r.recommended.ssaV;

    // Trigger optics update
    if (typeof updateOptics === 'function') {
      try { updateOptics(); } catch(e) {}
    }

    window._pendingOptimization = null;

    if (typeof addChatMessage === 'function') {
      addChatMessage('assistant',
        'Configuration applied: E=' + r.recommended.energy.toFixed(3) + ' keV, SSA=' +
        r.recommended.ssaH + ' \u03BCm', null, false);
    }

    return {success: true, applied: r.recommended};
  } catch(err) {
    return {error: 'Apply failed: ' + err.message};
  }
};

// Clear the pending optimization result and post an 'Optimization cancelled' chat message.
window.cancelOptimization = function() {
  window._pendingOptimization = null;
  if (typeof addChatMessage === 'function') {
    addChatMessage('assistant', 'Optimization cancelled.', null, false);
  }
  return {success: true, cancelled: true};
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof OPTICAL_CONSTRAINTS!=="undefined")globalThis.OPTICAL_CONSTRAINTS=OPTICAL_CONSTRAINTS;
if(typeof _SSA_SWEEP!=="undefined")globalThis._SSA_SWEEP=_SSA_SWEEP;
if(typeof _buildExplanation!=="undefined")globalThis._buildExplanation=_buildExplanation;
if(typeof _optRestoreState!=="undefined")globalThis._optRestoreState=_optRestoreState;
if(typeof _optSaveState!=="undefined")globalThis._optSaveState=_optSaveState;
if(typeof _optSetEnergy!=="undefined")globalThis._optSetEnergy=_optSetEnergy;
if(typeof _pad!=="undefined")globalThis._pad=_pad;
if(typeof _pendingOptimization!=="undefined")globalThis._pendingOptimization=_pendingOptimization;
if(typeof _renderOptimizationResult!=="undefined")globalThis._renderOptimizationResult=_renderOptimizationResult;
if(typeof applyOptimization!=="undefined")globalThis.applyOptimization=applyOptimization;
if(typeof cancelOptimization!=="undefined")globalThis.cancelOptimization=cancelOptimization;
if(typeof estimateSignal!=="undefined")globalThis.estimateSignal=estimateSignal;
if(typeof optimizeBeamline!=="undefined")globalThis.optimizeBeamline=optimizeBeamline;
if(typeof sweepEnergy!=="undefined")globalThis.sweepEnergy=sweepEnergy;
if(typeof sweepSSA!=="undefined")globalThis.sweepSSA=sweepSSA;
