'use strict';
// ===== measurement/03_init.js — Main Initialization =====
// @module measurement/03_init
// @exports init
// Extracted from 09_scan_init.js (DDD Phase)

function init() {
  log('info', 'Korea-4GSR ID10 NanoProbe v4.36');
  log('info', 'IVU24: \u03bb=' + LAMBDA_U + 'mm N=' + N_PERIODS + ' Halbach');
  log('info', 'Ring: ' + E_RING + 'GeV ' + I_RING + 'mA \u03b5=' + (EMIT_X * 1e12).toFixed(0) + 'pm');
  log('info', 'Motors: 8-axis sample + all optics');
  log('info', 'Corrections: LUT + polynomial + energy-coupling');
  log('info', 'Auto-align: centroid/gaussian/halfbeam/rocking/spiral');

  var defl1 = document.getElementById('vM1defl');
  if (defl1) defl1.textContent = (state.m1pitch * 2).toFixed(1) + ' mrad';

  // Initialize motor system
  if (typeof initMotors === 'function') initMotors();
  if (typeof initMaskMotors === 'function') initMaskMotors();

  setTargetEnergy(state.targetEnergy);
  updateOptics();

  // Build alignment steps panel
  if (typeof buildAlignPanel === 'function') buildAlignPanel();

  // Show default motor group
  if (typeof showMotorGroup === 'function') showMotorGroup('sample');

  // Update mask panel
  if (typeof updateMaskSidePanel === 'function') updateMaskSidePanel();

  if (typeof updateLiveBeamInfo === 'function') updateLiveBeamInfo();

  // Initialize EPICS subsystem (SimIOC auto-start)
  if (typeof initEPICS === 'function') initEPICS();
  if (typeof pvArchiveStart === 'function') pvArchiveStart();
  if (typeof startEpicsPeriodicUpdates === 'function') startEpicsPeriodicUpdates();

  // Initialize Bluesky Queue Server (Sim mode)
  if (typeof renderBlueskyTab === 'function') {
    log('info', 'Bluesky QS initialized (sim mode)');
    log('info', 'Plans: energy_scan, xanes_scan, align_motor, auto_align, raster_scan, fly_scan, gap_optimize');
  }

  // Phase 4/5 init
  if (typeof renderGuideTab === 'function') renderGuideTab();
  log('info', 'Detectors: Eiger2X 500K (CdTe) + Vortex ME-4 SDD (90\u00b0)');
  log('info', 'Ray-tracing: Monte Carlo beam profile + coherence');
  log('info', 'Virtual Expts: Cu-XANES, XRF-map, Powder-XRD, nano-XRF');
  log('info', 'Beam profiles: Monte Carlo ray tracing at all optical components');
  log('info', 'System ready (v4.36)');
}

window.addEventListener('DOMContentLoaded', init);

// ESM bridge: expose module-scoped vars to globalThis
if(typeof init!=="undefined")globalThis.init=init;
