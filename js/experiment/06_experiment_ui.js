'use strict';
// ===== experiment/06_experiment_ui.js — Expt Tab (launcher) + Popup UI =====
// @module experiment/06_experiment_ui
// @exports SIM_WS_PORT, _absorberOptions, _btnSmallSty, _buildBeamlineContext, _buildExptControls, _buildPtychoControls, _crystalOptions, _ensureCanvasAndRender, _exptBeamlineCache, _exptPopupRenderers, _exptSendCancel, _exptSendRun, _exptServerXAFSData, _exptState, _exptWs, ...

// ── Beamline cache (always updated, even when experiment tab is not visible) ──
var _exptBeamlineCache = { energy: 10, flux: 0, spotH: 50, spotV: 50 };

// ── State ──
var _exptState = {
  mode: 'xafs',
  running: false,
  timer: null,
  progress: 0,
  xafs: { formula: 'Cu', absorber: 'Cu', edge: 'K', eStart: -50, eEnd: 300, eStep: 0.5, ppm: 10000, sampleType: 'solid', icMode: false, icDwell: 1.0 },
  xrd2d: { crystal: 'Cu', detDist: 0.05, detector: 'EIGER2_1M', presetKey: '' },
  xrf2d: { formula: 'Cu', ppm: 1000, scanLx: 10, scanLy: 10, step: 0.5, dwell: 0.1,
           thickness_um: 1.0, matDensity: 8.96, sampleType: 'solid', presetKey: '' },
  xrdmap: { crystals: ['Cu','Fe2O3'], scanLx: 10, scanLy: 10, step: 0.5,
            detDist: 0.3, detector: 'EIGER2_1M' },
  ptycho: {
    // K4GSR-PTYCHO synthParams format
    dataset_id: 6,        // 1:Mona Lisa, 5:USAF-1951, 6:Mandrill, 7:Chip Phantom, 8:Snellen Chart
    material: 'Au',
    objheight_um: 1.0,
    scan_step_um: 0,       // 0 = auto from beam size (beam * 0.4 for ~60% overlap)
    scan_lx_um: 3,
    scan_ly_um: 3,
    z_m: 0.5,
    N_photons: 1000,
    noise_sigma: 0.0,
    dwellTime: 0.01,
    // Offline fallback params
    scanType: 'fermat',
    objectType: 'siemens',
    addNoise: true,
    // Detector
    ptychoDetector: 'EIGER2_1M',
    asize: 512,           // Diffraction pattern crop size (detector-dependent, user-adjustable)
    // Reconstruction params (engine names: ePIE, ePIE_ML, ePIE_LSQML, DM, ML, DM_ML, DM_LSQML)
    reconEngine: 'DM_LSQML',
    dmIterations: 300,
    mlIterations: 30
  }
};

// ── Render Expt Tab (launcher) ──
window.renderExptTab = function() {
  var pane = document.getElementById('tab-expt');
  if (!pane) return;

  var h = '';
  // Sub-tab bar
  h += '<div style="display:flex;gap:2px;padding:4px 6px;background:var(--s1);border-bottom:1px solid var(--s2)">';
  var modes = [{id:'xafs',label:'XAFS'},{id:'xrd2d',label:'2D-XRD'},{id:'xrf2d',label:'2D-XRF'},{id:'xrdmap',label:'XRD Map'},{id:'ptycho',label:'Ptycho'}];
  for (var i = 0; i < modes.length; i++) {
    var m = modes[i];
    var act = _exptState.mode === m.id ? 'background:var(--ac);color:#000;font-weight:700' : 'background:var(--s2);color:var(--t2)';
    h += '<button onclick="switchExptMode(\'' + m.id + '\')" style="' + act + ';border:none;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:10px;font-family:var(--mn)">' + m.label + '</button>';
  }
  h += '</div>';

  // Beamline status (live-updated by _updateExptBeamlineStatus)
  h += '<div id="exptBeamlineBar" style="padding:4px 8px;background:var(--s1);border-bottom:1px solid var(--s2);font:9px var(--mn);color:var(--t3)">';
  h += '<span id="exptBL_label">' + _t('expt_beamline_status') + '</span>: ';
  h += 'E=<span id="exptBL_energy">--</span> keV  ';
  h += 'Flux=<span id="exptBL_flux">--</span> ph/s  ';
  h += 'Spot=<span id="exptBL_spot">--</span> nm';
  h += '</div>';

  // Controls
  h += '<div id="exptControls" style="padding:6px 8px;font-family:var(--mn);font-size:10px;overflow-y:auto;flex:0 0 auto">';
  h += _buildExptControls(_exptState.mode);
  h += '</div>';

  // Action bar — two rows so a narrow pane never overflows horizontally:
  // (1) result controls (Show / Save / T(E) / Compare), (2) run controls
  // (Start / Stop / progress / %). flex:1 progress gets min-width:0 so it can
  // shrink instead of forcing a horizontal scrollbar.
  var _btnSec = 'background:var(--s2);color:var(--t1);border:1px solid var(--b1,#3d5068);padding:4px 8px;border-radius:3px;cursor:pointer;font-size:10px;font-family:var(--mn)';
  h += '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:4px 8px;align-items:center;border-top:1px solid var(--s2)">';
  h += '<button onclick="_reopenExptPopup()" style="' + _btnSec + '" data-i18n="expt_show">' + _t('expt_show') + '</button>';
  h += '<button onclick="_savePtychoResult()" style="' + _btnSec + '" data-i18n="expt_save">' + _t('expt_save') + '</button>';
  h += '<button onclick="showTransmissionPopup()" style="' + _btnSec + '" title="Sample transmission T(E) calculator">T(E)</button>';
  h += '<button id="exptCompareBtn" onclick="window._exptCompareMode=!window._exptCompareMode;this.style.background=window._exptCompareMode?\'var(--ac)\':\'var(--s2)\';this.style.color=window._exptCompareMode?\'#000\':\'var(--t1)\';this.style.fontWeight=window._exptCompareMode?\'700\':\'400\'" style="background:' + (window._exptCompareMode ? 'var(--ac)' : 'var(--s2)') + ';color:' + (window._exptCompareMode ? '#000' : 'var(--t1)') + ';font-weight:' + (window._exptCompareMode ? '700' : '400') + ';border:1px solid var(--b1,#3d5068);padding:4px 8px;border-radius:3px;cursor:pointer;font-size:10px;font-family:var(--mn)" title="Compare: ON keeps the previous result beside the new one; OFF replaces it in place">Compare</button>';
  h += '</div>';
  h += '<div style="display:flex;gap:6px;padding:0 8px 4px;align-items:center">';
  h += '<button id="exptStartBtn" onclick="startExperiment()" style="background:var(--gn);color:#000;border:none;padding:4px 14px;border-radius:3px;cursor:pointer;font-size:10px;font-weight:700;font-family:var(--mn)" data-i18n="expt_start">' + _t('expt_start') + '</button>';
  h += '<button onclick="stopExperiment()" style="background:#e05050;color:#fff;border:none;padding:4px 10px;border-radius:3px;cursor:pointer;font-size:10px;font-family:var(--mn)" data-i18n="expt_stop">' + _t('expt_stop') + '</button>';
  h += '<div style="flex:1;min-width:0;background:var(--s2);height:18px;border-radius:5px;overflow:hidden"><div id="exptProgBar" style="width:0%;height:100%;background:var(--ac);transition:width 0.2s"></div></div>';
  h += '<span id="exptProgText" style="color:var(--t1);font-size:12px;font-weight:bold;min-width:36px;text-align:right;flex:0 0 auto">0%</span>';
  h += '</div>';

  // Info
  h += '<div id="exptInfo" style="padding:4px 8px;font-size:12px;color:var(--t2);font-family:var(--mn);border-top:1px solid var(--s2)" data-i18n="expt_ready_msg">' + _t('expt_ready_msg') + '</div>';

  pane.innerHTML = h;
  // Populate beamline status bar from cache immediately (synchronous — no setTimeout race)
  try {
    var _eEl = document.getElementById('exptBL_energy');
    var _fEl = document.getElementById('exptBL_flux');
    var _sEl = document.getElementById('exptBL_spot');
    if (_eEl) _eEl.textContent = _exptBeamlineCache.energy.toFixed(2);
    if (_fEl) _fEl.textContent = _exptBeamlineCache.flux > 0 ? _exptBeamlineCache.flux.toExponential(2) : 'N/A';
    if (_sEl) _sEl.textContent = _exptBeamlineCache.spotH.toFixed(0) + 'x' + _exptBeamlineCache.spotV.toFixed(0);
  } catch(e) {}
  // Populate per-mode beam/flux info from cache
  setTimeout(function() {
    try { _refreshExptModeInfo(); } catch(e) {}
  }, 0);
};

// ── Live-update beamline status in Experiment panel ──
// Called from focalSpot() on MC completion + updateEnergy().
// ALWAYS writes to _exptBeamlineCache (even when tab is hidden),
// then updates DOM if the experiment panel is currently visible.
window._updateExptBeamlineStatus = function() {
  var eKev = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  // Sample-plane flux: single API (sampleFlux) shared by every display.
  var fl = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
  // Read spot from MC cache (no re-run — just read cached result)
  var spH = 50, spV = 50;
  try {
    if (typeof _mcSampleCache !== 'undefined' && _mcSampleCache && _mcSampleCache.fwhmH) {
      spH = Math.max(15, _mcSampleCache.fwhmH * 1e9);
      spV = Math.max(15, _mcSampleCache.fwhmV * 1e9);
    }
  } catch(e) {}
  // Always update cache (survives tab switches)
  _exptBeamlineCache.energy = eKev;
  _exptBeamlineCache.flux = fl;
  _exptBeamlineCache.spotH = spH;
  _exptBeamlineCache.spotV = spV;
  // Update DOM if experiment tab is visible
  var eEl = document.getElementById('exptBL_energy');
  if (!eEl) return;
  eEl.textContent = eKev.toFixed(2);
  var fEl = document.getElementById('exptBL_flux');
  if (fEl) fEl.textContent = fl > 0 ? fl.toExponential(2) : 'N/A';
  var sEl = document.getElementById('exptBL_spot');
  if (sEl) sEl.textContent = spH.toFixed(0) + 'x' + spV.toFixed(0);
  // Also refresh per-mode beam/flux displays
  try { _refreshExptModeInfo(); } catch(e) {}
};

// ── Refresh per-mode beam/flux info (called from _updateExptBeamlineStatus) ──
function _refreshExptModeInfo() {
  var eKev = _exptBeamlineCache.energy;
  var fl = _exptBeamlineCache.flux;
  var spH = _exptBeamlineCache.spotH;
  var spV = _exptBeamlineCache.spotV;
  var mode = _exptState.mode;

  // Common info div (XRF, XRD 2D, XRD Map share the same ID)
  var infoEl = document.getElementById('exptModeBeamInfo');

  if (mode === 'xrf2d' && infoEl) {
    var stepEl = document.getElementById('exptXrf2dStep');
    var lxEl = document.getElementById('exptXrf2dLx');
    var lyEl = document.getElementById('exptXrf2dLy');
    var step = stepEl ? (parseFloat(stepEl.value) || 0.5) : 0.5;
    var lx = lxEl ? (parseFloat(lxEl.value) || 10) : 10;
    var ly = lyEl ? (parseFloat(lyEl.value) || 10) : 10;
    var nPtsX = Math.ceil(lx / step), nPtsY = Math.ceil(ly / step);
    infoEl.innerHTML = 'Beam: ' + spH.toFixed(0) + 'x' + spV.toFixed(0) + ' nm | ' +
      'Grid: ' + nPtsX + 'x' + nPtsY + '=' + (nPtsX * nPtsY) + ' pts | ' +
      'Flux: ' + (fl > 0 ? fl.toExponential(2) : 'N/A') + ' ph/s';

  } else if (mode === 'xrd2d' && infoEl) {
    infoEl.innerHTML = 'E=' + eKev.toFixed(2) + ' keV | ' +
      'Beam: ' + spH.toFixed(0) + 'x' + spV.toFixed(0) + ' nm | ' +
      'Flux: ' + (fl > 0 ? fl.toExponential(2) : 'N/A') + ' ph/s';

  } else if (mode === 'xrdmap' && infoEl) {
    var stepElM = document.getElementById('exptXrdMapStep');
    var lxElM = document.getElementById('exptXrdMapLx');
    var lyElM = document.getElementById('exptXrdMapLy');
    var stepM = stepElM ? (parseFloat(stepElM.value) || 0.5) : 0.5;
    var lxM = lxElM ? (parseFloat(lxElM.value) || 10) : 10;
    var lyM = lyElM ? (parseFloat(lyElM.value) || 10) : 10;
    var nPtsXM = Math.ceil(lxM / stepM), nPtsYM = Math.ceil(lyM / stepM);
    infoEl.innerHTML = 'Beam: ' + spH.toFixed(0) + 'x' + spV.toFixed(0) + ' nm | ' +
      'Grid: ' + nPtsXM + 'x' + nPtsYM + '=' + (nPtsXM * nPtsYM) + ' pts | ' +
      'Flux: ' + (fl > 0 ? fl.toExponential(2) : 'N/A') + ' ph/s';
  }

  // XAFS: re-compute edge info with current flux
  if (mode === 'xafs') {
    try { if (typeof _updateXafsEdgeInfo === 'function') _updateXafsEdgeInfo(); } catch(e) {}
  }

  // Ptycho: update probe display + N_photons placeholder
  if (mode === 'ptycho') {
    var probeEl = document.getElementById('exptPtychoProbeDisplay');
    if (probeEl) {
      probeEl.innerHTML = (spH / 1000).toFixed(3) + ' x ' + (spV / 1000).toFixed(3) + ' \u03bcm';
    }
    // Update auto step placeholder + overlap
    var beamMaxNm = Math.max(spH, spV);
    var autoStepUm = parseFloat((beamMaxNm * 0.4 / 1000).toFixed(4));
    var stepInput = document.getElementById('exptPtychoStepUm');
    if (stepInput) stepInput.placeholder = 'auto ' + autoStepUm;
    var effectiveStep = (stepInput && parseFloat(stepInput.value) > 0) ? parseFloat(stepInput.value) : autoStepUm;
    var overlapPct = Math.round((1 - effectiveStep / (beamMaxNm / 1000)) * 100);
    var ovColor = overlapPct >= 50 ? 'var(--gn)' : (overlapPct >= 20 ? 'var(--am)' : '#e05050');
    var ovSpan = document.getElementById('ptychoOverlapSpan');
    if (ovSpan) {
      ovSpan.style.color = ovColor;
      ovSpan.textContent = overlapPct + '% overlap';
    }
    // Update N_photons placeholder (flux * dwell)
    try { if (typeof _updatePtychoDwellEstimate === 'function') _updatePtychoDwellEstimate(); } catch(e) {}
  }
}

// ── Build controls per mode ──
function _buildExptControls(mode) {
  var h = '';
  if (mode === 'xafs') {
    h += _row(_t('expt_formula'), '<input id="exptXafsFormula" value="' + _exptState.xafs.formula + '" style="' + _inputSty + 'width:80px" onchange="_exptXafsFormulaChanged()">');
    h += _row(_t('expt_absorber'), '<select id="exptXafsAbsorber" onchange="_updateXafsEdgeInfo()" style="' + _selectSty + '">' + _absorberOptions(_exptState.xafs.formula, _exptState.xafs.absorber) + '</select>');
    h += _row(_t('expt_edge'), '<select id="exptXafsEdge" onchange="_updateXafsEdgeInfo()" style="' + _selectSty + '"><option value="K"' + (_exptState.xafs.edge === 'K' ? ' selected' : '') + '>K</option><option value="L3"' + (_exptState.xafs.edge === 'L3' ? ' selected' : '') + '>L3</option></select>');
    h += '<div id="xafsEdgeInfo" style="padding:2px 8px;font:9px var(--mn)"></div>';
    h += _row(_t('expt_e_range'), '<input id="exptXafsEStart" type="number" value="' + _exptState.xafs.eStart + '" style="' + _inputSty + 'width:50px"> ~ <input id="exptXafsEEnd" type="number" value="' + _exptState.xafs.eEnd + '" style="' + _inputSty + 'width:50px">');
    h += _row(_t('expt_e_step'), '<input id="exptXafsEStep" type="number" value="' + _exptState.xafs.eStep + '" step="0.1" style="' + _inputSty + 'width:50px"> eV');
    h += _row(_t('expt_presets'), '<select onchange="if(this.value){document.getElementById(\'exptXafsFormula\').value=this.value;_exptXafsFormulaChanged()}" style="' + _selectSty + '"><option value="">--</option><option>Cu</option><option>Cu2O</option><option>CuO</option><option>Fe</option><option>Fe2O3</option><option>NiO</option><option>SrTiO3</option></select>');
    h += _row(_t('expt_sample'), '<select id="exptXafsSampleType" style="' + _selectSty + '"><option value="solid"' + (_exptState.xafs.sampleType === 'solid' ? ' selected' : '') + '>Solid</option><option value="powder"' + (_exptState.xafs.sampleType === 'powder' ? ' selected' : '') + '>Powder (dilute)</option></select>');
    h += _row(_t('expt_conc'), '<input id="exptXafsPPM" type="number" value="' + _exptState.xafs.ppm + '" step="100" style="' + _inputSty + 'width:70px">');
    // IC measurement mode (opt-in): mu_obs = ln(I0/I1) through the I0/I1
    // chamber chain (server ic_chain.py) instead of synthetic noise.
    // I0 config = IC1 popup (SVG icon), I1 config = detector popup IC tab.
    h += _row('IC I0/I1',
      '<label style="font-size:10px;cursor:pointer"><input type="checkbox" id="exptXafsIC"' +
      (_exptState.xafs.icMode ? ' checked' : '') +
      '> ln(I0/I1)</label> &nbsp;dwell <input id="exptXafsICDwell" type="number" value="' +
      (_exptState.xafs.icDwell || 1.0) +
      '" min="0.01" step="0.1" style="' + _inputSty + 'width:45px"> s');
  } else if (mode === 'xrd2d') {
    // Preset selector
    var xrdPresetOpts = '<option value="">-- Custom --</option>';
    if (typeof XRD_SAMPLE_PRESETS !== 'undefined') {
      var xrdPKeys = Object.keys(XRD_SAMPLE_PRESETS);
      for (var xpi = 0; xpi < xrdPKeys.length; xpi++) {
        var xrp = XRD_SAMPLE_PRESETS[xrdPKeys[xpi]];
        xrdPresetOpts += '<option value="' + xrdPKeys[xpi] + '"' + (xrdPKeys[xpi] === _exptState.xrd2d.presetKey ? ' selected' : '') + '>' + xrp.name + '</option>';
      }
    }
    h += _row('Preset', '<select id="exptXrd2dPreset" onchange="_xrd2dPresetChanged()" style="' + _selectSty + 'width:180px">' + xrdPresetOpts + '</select>');
    h += _row('Material', '<input id="exptXrd2dCrystal" list="xrd2dCrystalList" value="' + (_exptState.xrd2d.crystal || 'Cu') + '" placeholder="e.g. Cu, NaCl, Fe2O3" style="' + _inputSty + 'width:120px">' +
      '<datalist id="xrd2dCrystalList">' + _crystalOptions(_exptState.xrd2d.crystal) + '</datalist>' +
      '<span style="font-size:8px;color:var(--t3);margin-left:4px">or type formula</span>');
    h += _row('Detector', '<select id="exptXrd2dDet" style="' + _selectSty + '">' +
      '<option value="EIGER2_1M"' + (_exptState.xrd2d.detector === 'EIGER2_1M' ? ' selected' : '') + '>EIGER2 X 1M (1028x1062, 75\u03bcm)</option>' +
      '<option value="EIGER2_4M"' + (_exptState.xrd2d.detector === 'EIGER2_4M' ? ' selected' : '') + '>EIGER2 X 4M (2068x2162, 75\u03bcm)</option>' +
      '</select>');
    h += _row('Det dist', '<input id="exptXrd2dDist" type="number" value="' + _exptState.xrd2d.detDist + '" step="0.01" style="' + _inputSty + 'width:60px"> m');
    // Show detector info
    var _det = (typeof EIGER_DETECTORS !== 'undefined') ? EIGER_DETECTORS[_exptState.xrd2d.detector] : null;
    if (_det) {
      h += '<div style="font-size:8px;color:var(--t3);margin-top:2px;padding:2px 4px;background:var(--s1);border-radius:2px">' +
        _det.name + ': ' + _det.pixelsH + 'x' + _det.pixelsV + ' px, ' +
        (_det.activeAreaH * 1000).toFixed(1) + 'x' + (_det.activeAreaV * 1000).toFixed(1) + ' mm, ' +
        _det.modules + ' modules, gap=' + _det.moduleGapV + 'px (V)' +
        (_det.moduleGapH > 0 ? ' ' + _det.moduleGapH + 'px (H)' : '') +
        '</div>';
    }
    // Beam/Flux info (live-updated by _refreshExptModeInfo)
    h += '<div id="exptModeBeamInfo" style="font-size:8px;color:var(--t3);margin-top:3px;padding:2px 4px;background:var(--s1);border-radius:2px"></div>';
  } else if (mode === 'xrf2d') {
    var xf = _exptState.xrf2d;
    // Sample preset
    h += '<div style="color:var(--ac);font-weight:700;margin-bottom:3px">Sample</div>';
    var presetOpts = '<option value="">-- Custom --</option>';
    if (typeof XRF_SAMPLE_PRESETS !== 'undefined') {
      var spKeys = Object.keys(XRF_SAMPLE_PRESETS);
      for (var spi = 0; spi < spKeys.length; spi++) {
        var sp = XRF_SAMPLE_PRESETS[spKeys[spi]];
        presetOpts += '<option value="' + spKeys[spi] + '"' + (spKeys[spi] === xf.presetKey ? ' selected' : '') + '>' + sp.name + '</option>';
      }
    }
    h += _row('Preset', '<select id="exptXrf2dPreset" onchange="_xrf2dPresetChanged()" style="' + _selectSty + 'width:180px">' + presetOpts + '</select>');
    h += _row('Formula', '<input id="exptXrf2dFormula" value="' + xf.formula + '" style="' + _inputSty + 'width:120px">');
    h += _row('Conc (ppm)', '<input id="exptXrf2dPPM" type="number" value="' + xf.ppm + '" step="100" style="' + _inputSty + 'width:70px">');
    h += _row('Thickness', '<input id="exptXrf2dThickness" type="number" value="' + xf.thickness_um + '" step="0.1" style="' + _inputSty + 'width:60px"> \u03bcm');
    h += _row('Density', '<input id="exptXrf2dDensity" type="number" value="' + xf.matDensity + '" step="0.1" style="' + _inputSty + 'width:60px"> g/cm3');
    h += _row('Type', '<select id="exptXrf2dSampleType" style="' + _selectSty + '">' +
      '<option value="solid"' + (xf.sampleType === 'solid' ? ' selected' : '') + '>Solid / thin film</option>' +
      '<option value="powder"' + (xf.sampleType === 'powder' ? ' selected' : '') + '>Powder (dilute)</option>' +
      '<option value="particle"' + (xf.sampleType === 'particle' ? ' selected' : '') + '>Single microparticle</option>' +
      '</select>');
    // Scan section
    h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Scan</div>';
    h += _row('Scan area', '<input id="exptXrf2dLx" type="number" value="' + xf.scanLx + '" step="1" style="' + _inputSty + 'width:40px"> x <input id="exptXrf2dLy" type="number" value="' + xf.scanLy + '" step="1" style="' + _inputSty + 'width:40px"> \u03bcm');
    h += _row('Step', '<input id="exptXrf2dStep" type="number" value="' + xf.step + '" step="0.1" style="' + _inputSty + 'width:50px"> \u03bcm');
    h += _row('Dwell', '<input id="exptXrf2dDwell" type="number" value="' + xf.dwell + '" step="0.01" style="' + _inputSty + 'width:50px"> s');
    // Info (live-updated by _refreshExptModeInfo)
    h += '<div id="exptModeBeamInfo" style="font-size:8px;color:var(--t3);margin-top:3px;padding:2px 4px;background:var(--s1);border-radius:2px"></div>';
    // Detector info
    if (typeof SDD_SPEC !== 'undefined') {
      h += '<div style="font-size:8px;color:var(--t3);padding:2px 4px;background:var(--s1);border-radius:2px;margin-top:1px">' +
        'Det: ' + SDD_SPEC.name + ' | FWHM=' + SDD_SPEC.fwhm_MnKa_eV + 'eV@MnKa | ' +
        'Omega=' + (SDD_SPEC.totalSolidAngle_sr * 1000).toFixed(2) + ' msr' +
        '</div>';
    }
  } else if (mode === 'xrdmap') {
    var xm = _exptState.xrdmap;
    h += '<div style="color:var(--ac);font-weight:700;margin-bottom:3px">Sample Phases</div>';
    // Phase 1
    h += _row('Phase 1', '<input id="exptXrdMapCryst1" list="xrdMapCryst1List" value="' + (xm.crystals[0] || 'Cu') + '" placeholder="e.g. Cu" style="' + _inputSty + 'width:100px">' +
      '<datalist id="xrdMapCryst1List">' + _crystalOptions(xm.crystals[0] || 'Cu') + '</datalist>');
    // Phase 2
    h += _row('Phase 2', '<input id="exptXrdMapCryst2" list="xrdMapCryst2List" value="' + (xm.crystals[1] || 'Fe2O3') + '" placeholder="none or formula" style="' + _inputSty + 'width:100px">' +
      '<datalist id="xrdMapCryst2List"><option value="">-- none --</option>' + _crystalOptions(xm.crystals[1] || 'Fe2O3') + '</datalist>');
    h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Detector</div>';
    h += _row('Detector', '<select id="exptXrdMapDet" style="' + _selectSty + '">' +
      '<option value="EIGER2_1M"' + (xm.detector === 'EIGER2_1M' ? ' selected' : '') + '>EIGER2 X 1M</option>' +
      '<option value="EIGER2_4M"' + (xm.detector === 'EIGER2_4M' ? ' selected' : '') + '>EIGER2 X 4M</option>' +
      '</select>');
    h += _row('Det dist', '<input id="exptXrdMapDist" type="number" value="' + xm.detDist + '" step="0.01" style="' + _inputSty + 'width:60px"> m');
    h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Scan</div>';
    h += _row('Scan area', '<input id="exptXrdMapLx" type="number" value="' + xm.scanLx + '" step="1" style="' + _inputSty + 'width:40px"> x <input id="exptXrdMapLy" type="number" value="' + xm.scanLy + '" step="1" style="' + _inputSty + 'width:40px"> \u03bcm');
    h += _row('Step', '<input id="exptXrdMapStep" type="number" value="' + xm.step + '" step="0.1" style="' + _inputSty + 'width:50px"> \u03bcm');
    // Info (live-updated by _refreshExptModeInfo)
    h += '<div id="exptModeBeamInfo" style="font-size:8px;color:var(--t3);margin-top:3px;padding:2px 4px;background:var(--s1);border-radius:2px"></div>';
  } else if (mode === 'ptycho') {
    h += _buildPtychoControls();
  }
  return h;
}

// ── Ptycho controls (K4GSR-PTYCHO synthParams aligned) ──
function _buildPtychoControls() {
  var pp = _exptState.ptycho;
  var h = '';

  // Server connection status (uses common bar at top; Ptycho-specific info here)
  var isConn = (typeof _exptWsConnected !== 'undefined') && _exptWsConnected;
  var isPtyConn = (typeof _ptychoConnected !== 'undefined') && _ptychoConnected;
  var ptyStat = isPtyConn ? 'K4GSR-PTYCHO (ws://' + (typeof PTYCHO_WS_URL !== 'undefined' ? PTYCHO_WS_URL.replace('ws://','') : 'localhost:8765') + ')' : 'Offline (auto-connect on Start)';
  h += '<div style="font-size:8px;color:var(--t3);margin-bottom:3px">';
  h += 'Recon server: <span style="color:' + (isPtyConn ? 'var(--gn)' : 'var(--am)') + '">' + ptyStat + '</span>';
  if (!isPtyConn) {
    h += ' <button onclick="ptychoConnect()" style="' + _btnSmallSty + 'font-size:8px;padding:1px 6px">Connect</button>';
  }
  h += '</div>';

  // Sample section
  h += '<div style="color:var(--ac);font-weight:700;margin-bottom:3px">Sample</div>';
  h += _row('Dataset', '<select id="exptPtychoDataset" style="' + _selectSty + '">' +
    '<option value="1"' + (pp.dataset_id === 1 ? ' selected' : '') + '>Mona Lisa</option>' +
    '<option value="5"' + (pp.dataset_id === 5 ? ' selected' : '') + '>USAF-1951</option>' +
    '<option value="6"' + (pp.dataset_id === 6 ? ' selected' : '') + '>Mandrill</option>' +
    '<option value="7"' + (pp.dataset_id === 7 ? ' selected' : '') + '>Chip Phantom</option>' +
    '<option value="8"' + (pp.dataset_id === 8 ? ' selected' : '') + '>Snellen Chart</option>' +
    '</select>');
  h += _row('Material', '<select id="exptPtychoMat" style="' + _selectSty + '">' +
    '<option value="Au"' + (pp.material === 'Au' ? ' selected' : '') + '>Au (Gold)</option>' +
    '<option value="Cu"' + (pp.material === 'Cu' ? ' selected' : '') + '>Cu (Copper)</option>' +
    '<option value="W"' + (pp.material === 'W' ? ' selected' : '') + '>W (Tungsten)</option>' +
    '<option value="Pt"' + (pp.material === 'Pt' ? ' selected' : '') + '>Pt (Platinum)</option>' +
    '<option value="Si"' + (pp.material === 'Si' ? ' selected' : '') + '>Si (Silicon)</option>' +
    '<option value="SiO2"' + (pp.material === 'SiO2' ? ' selected' : '') + '>SiO2 (Quartz)</option>' +
    '</select>');
  h += _row('Thickness', '<input id="exptPtychoH" type="number" value="' + pp.objheight_um + '" step="0.1" min="0.01" max="100" style="' + _inputSty + 'width:60px"> \u03bcm');

  // Scan section
  h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Scan</div>';
  var _bsz = {h:50,v:50}; try { if (typeof focalSpot === 'function') _bsz = focalSpot(); } catch(e) {}
  var probeUmH = (_bsz.h / 1000).toFixed(3);
  var probeUmV = (_bsz.v / 1000).toFixed(3);
  var beamMaxNm = Math.max(_bsz.h, _bsz.v);
  // Auto step: beam * 0.4 for ~60% overlap, in um
  var autoStepUm = parseFloat((beamMaxNm * 0.4 / 1000).toFixed(4));
  var effectiveStep = pp.scan_step_um > 0 ? pp.scan_step_um : autoStepUm;
  // Overlap: 1 - step/probe
  var overlapPct = Math.round((1 - effectiveStep / (beamMaxNm / 1000)) * 100);
  var ovColor = overlapPct >= 50 ? 'var(--gn)' : (overlapPct >= 20 ? 'var(--am)' : '#e05050');
  h += _row('Probe', '<span id="exptPtychoProbeDisplay" style="color:var(--t1)">' + probeUmH + ' x ' + probeUmV + ' \u03bcm</span> <span style="color:var(--t3);font-size:8px">(from beamline)</span>');
  var stepDisplayVal = pp.scan_step_um > 0 ? pp.scan_step_um : '';
  h += _row('Step', '<input id="exptPtychoStepUm" type="number" value="' + stepDisplayVal + '" step="0.001" min="0" placeholder="auto ' + autoStepUm + '" style="' + _inputSty + 'width:70px" oninput="_updatePtychoScanEstimate()" onchange="_refreshPtychoCoherence()"> \u03bcm' +
    ' <span id="ptychoOverlapSpan" style="color:' + ovColor + ';font-size:8px;font-weight:700">' + overlapPct + '% overlap</span>');
  h += _row('Scan area', '<input id="exptPtychoLxUm" type="number" value="' + pp.scan_lx_um + '" step="0.5" min="0.1" style="' + _inputSty + 'width:40px" oninput="_updatePtychoScanEstimate()"> x <input id="exptPtychoLyUm" type="number" value="' + pp.scan_ly_um + '" step="0.5" min="0.1" style="' + _inputSty + 'width:40px" oninput="_updatePtychoScanEstimate()"> \u03bcm');
  // Detector section
  h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Detector</div>';
  h += _row('Detector', '<select id="exptPtychoDet" style="' + _selectSty + '" onchange="_refreshPtychoCoherence()">' +
    '<option value="EIGER2_1M"' + (pp.ptychoDetector === 'EIGER2_1M' ? ' selected' : '') + '>EIGER2 X 1M</option>' +
    '<option value="EIGER2_4M"' + (pp.ptychoDetector === 'EIGER2_4M' ? ' selected' : '') + '>EIGER2 X 4M</option>' +
    '</select>');
  h += _row('Det dist (z)', '<input id="exptPtychoZ" type="number" value="' + pp.z_m + '" step="0.5" style="' + _inputSty + 'width:50px" onchange="_refreshPtychoCoherence()"> m');
  // Crop size (asize): determined by detector, adjustable by user (SNR, compute cost)
  var _asizeOpts = [128, 256, 512, 1024];
  var _asizeHtml = '';
  for (var _ai = 0; _ai < _asizeOpts.length; _ai++) {
    _asizeHtml += '<option value="' + _asizeOpts[_ai] + '"' + (pp.asize === _asizeOpts[_ai] ? ' selected' : '') + '>' + _asizeOpts[_ai] + '</option>';
  }
  h += _row('Crop (asize)', '<select id="exptPtychoAsize" style="' + _selectSty + '" onchange="_updatePtychoScanEstimate();_refreshPtychoCoherence()">' + _asizeHtml + '</select>' +
    ' <span style="color:var(--t3);font-size:8px">det crop size</span>');
  // Show detector geometry info using user-selected asize
  var _pEkev = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  var _pGeom = null;
  try { _pGeom = _ptychoDetectorGeometry(_pEkev, pp.z_m, pp.ptychoDetector); } catch(e) {}
  if (_pGeom) {
    var _probeNm = Math.max(_bsz.h, _bsz.v);
    var _userAsize = pp.asize || 512;
    var _dxAtAs = _pGeom.lambda_m * (pp.z_m || 2.0) / (_userAsize * _pGeom.pixelSize) * 1e9; // nm
    var _probePx = _probeNm / _dxAtAs;
    var _oversampling = _pGeom.lambda_m * (pp.z_m || 2.0) / (_pGeom.pixelSize * _probeNm * 1e-9);
    h += '<div style="font-size:8px;color:var(--t3);margin:2px 0;padding:2px 4px;background:var(--s1);border-radius:2px">' +
      _pGeom.detName + ': ' + _pGeom.pixelsH + 'x' + _pGeom.pixelsV + ' px, ' +
      (_pGeom.pixelSize * 1e6).toFixed(0) + '\u03bcm/px' +
      ' | dx=' + _dxAtAs.toFixed(1) + ' nm' +
      ' | probe=' + _probePx.toFixed(1) + ' px' +
      ' | O=' + _oversampling.toFixed(0) +
      '</div>';
  }
  // Scan estimate: Npos + memory
  var _estLx = pp.scan_lx_um || 3;
  var _estLy = pp.scan_ly_um || 3;
  var _estAs = pp.asize || 512;
  var _estNpos = Math.round(Math.PI * (_estLx * _estLy) / (effectiveStep * effectiveStep) * 0.25);
  var _estMemGB = (_estAs * _estAs * _estNpos * 4) / 1e9;
  var _memColor = _estMemGB < 2 ? 'var(--gn)' : (_estMemGB < 4 ? 'var(--am)' : '#e05050');
  // Estimated simulation time (2-pass FFT model)
  // Empirical per-FFT time (ms) on typical CPU (numpy): asize=128:0.1, 256:0.3, 512:1.0
  var _fftMs = _estAs <= 128 ? 0.1 : (_estAs <= 256 ? 0.3 : (_estAs <= 512 ? 1.0 : 2.5));
  var _estTimeSec = (2 * _estNpos * _fftMs) / 1000;  // 2 passes x Npos FFTs
  var _timeStr;
  if (_estTimeSec < 60) { _timeStr = Math.round(_estTimeSec) + 's'; }
  else if (_estTimeSec < 3600) { _timeStr = Math.round(_estTimeSec / 60) + 'm ' + Math.round(_estTimeSec % 60) + 's'; }
  else { _timeStr = Math.round(_estTimeSec / 3600) + 'h ' + Math.round((_estTimeSec % 3600) / 60) + 'm'; }
  h += '<div id="ptychoScanEstimate" style="font-size:8px;color:var(--t3);margin:2px 0;padding:2px 4px;background:var(--s1);border-radius:2px;border-left:2px solid ' + _memColor + '">' +
    'Scan: ~' + _estNpos + ' positions (Fermat) | fmag: ' + _estMemGB.toFixed(2) + ' GB | ~' + _timeStr +
    (_estMemGB >= 4 ? ' <span style="color:#e05050;font-weight:700">scan area will be reduced (overlap preserved)</span>' : '') +
    '</div>';

  // Coherence + Quality Check + SSA Recommendation (live-updated block)
  h += '<div id="ptychoCoherenceBlock">';
  h += _renderPtychoCoherenceBlock(_pEkev, pp);
  h += '</div>';

  // Signal section
  h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Signal</div>';
  h += _row('Dwell time', '<input id="exptPtychoDwell" type="number" value="' + pp.dwellTime + '" step="0.01" min="0.001" style="' + _inputSty + 'width:60px" oninput="_updatePtychoDwellEstimate()" onchange="_refreshPtychoCoherence()"> s');
  // Auto-compute N_photons from flux * dwell
  var _autoPhotons = 0;
  try { _autoPhotons = _fluxToPhotons((typeof state !== 'undefined' && state.energy) || 10, pp.dwellTime); } catch(e) {}
  var _nphDisplay = (pp.N_photons > 0 && pp.N_photons !== 1000) ? pp.N_photons : '';
  h += _row('N_photons', '<input id="exptPtychoNph" type="number" value="' + _nphDisplay + '" placeholder="auto ' + _autoPhotons.toExponential(1) + '" style="' + _inputSty + 'width:90px"> <span id="ptychoNphAuto" style="color:var(--t3);font-size:8px">' + (_nphDisplay ? 'manual' : 'auto: flux*dwell') + '</span>');
  h += _row('Noise sigma', '<input id="exptPtychoNoiseSigma" type="number" value="' + pp.noise_sigma + '" step="0.01" min="0" style="' + _inputSty + 'width:50px">');

  // Reconstruction section (for server mode)
  h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Reconstruction</div>';
  h += _row('Engine', '<select id="exptPtychoEngine" style="' + _selectSty + '">' +
    '<option value="DM_LSQML"' + (pp.reconEngine === 'DM_LSQML' ? ' selected' : '') + '>DM + LSQML (GPU)</option>' +
    '<option value="DM_ML"' + (pp.reconEngine === 'DM_ML' ? ' selected' : '') + '>DM + ML</option>' +
    '<option value="DM"' + (pp.reconEngine === 'DM' ? ' selected' : '') + '>DM only</option>' +
    '<option value="LSQML"' + (pp.reconEngine === 'LSQML' ? ' selected' : '') + '>LSQML (GPU)</option>' +
    '<option value="ML"' + (pp.reconEngine === 'ML' ? ' selected' : '') + '>ML only</option>' +
    '<option value="ePIE"' + (pp.reconEngine === 'ePIE' ? ' selected' : '') + '>ePIE</option>' +
    '<option value="ePIE_ML"' + (pp.reconEngine === 'ePIE_ML' ? ' selected' : '') + '>ePIE + ML</option>' +
    '<option value="ePIE_LSQML"' + (pp.reconEngine === 'ePIE_LSQML' ? ' selected' : '') + '>ePIE + LSQML (GPU)</option>' +
    '</select>');
  h += _row('DM iter', '<input id="exptPtychoDMIter" type="number" value="' + pp.dmIterations + '" step="10" min="1" max="1000" style="' + _inputSty + 'width:60px">');
  h += _row('ML iter', '<input id="exptPtychoMLIter" type="number" value="' + pp.mlIterations + '" step="5" min="1" max="500" style="' + _inputSty + 'width:60px">');

  // Preview button: synthetic data only (no reconstruction)
  h += '<div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--s2)">';
  h += '<button onclick="_previewPtychoObject()" style="' + _btnSmallSty + 'background:var(--ac);color:#000;font-weight:700" title="Preview synthetic object without reconstruction">Preview</button>';
  h += ' <span style="color:var(--t3);font-size:8px">Synthetic data preview (object check)</span>';
  h += '</div>';

  return h;
}

// ── Render coherence + quality check + SSA recommendation block ──
// Extracted so it can be refreshed independently when SSA changes.
function _renderPtychoCoherenceBlock(eKev, pp) {
  var h = '';

  // Coherence section
  h += '<div style="color:var(--ac);font-weight:700;margin:4px 0 3px">Coherence</div>';
  var _cohInfo = null;
  try { _cohInfo = _ptychoCoherentFraction(eKev); } catch(e) {}
  if (_cohInfo) {
    var _fCohPct = (_cohInfo.coherent_fraction * 100).toFixed(1);
    var _cohColor = _cohInfo.coherent_fraction > 0.5 ? 'var(--gn)' : (_cohInfo.coherent_fraction > 0.1 ? 'var(--am)' : '#e05050');
    var _nModes = _cohInfo.N_modes || 1;
    h += '<div style="font-size:9px;color:var(--t3);margin-bottom:2px;padding:3px 5px;background:var(--s1);border-radius:2px;border-left:3px solid ' + _cohColor + '">';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>Coherent fraction:</span>';
    h += '<span style="color:' + _cohColor + ';font-weight:700">' + _fCohPct + '% (' + _nModes + ' modes)</span>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>Mode count (H x V):</span>';
    h += '<span style="color:var(--t1)">M=' + (_cohInfo.M_H || 1).toFixed(1) + ' x ' + (_cohInfo.M_V || 1).toFixed(1) + '</span>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>sigma_coh (H x V):</span>';
    h += '<span style="color:var(--t2)">' + (_cohInfo.sigma_coh_h_um || 0).toFixed(1) + ' x ' + (_cohInfo.sigma_coh_v_um || 0).toFixed(1) + ' \u03BCm</span>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>sigma_eff (H x V):</span>';
    h += '<span style="color:var(--t2)">' + (_cohInfo.sigma_eff_h_um || 0).toFixed(1) + ' x ' + (_cohInfo.sigma_eff_v_um || 0).toFixed(1) + ' \u03BCm</span>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>KB aperture (H x V):</span>';
    h += '<span style="color:var(--t2)">' + (_cohInfo.A_KB_H_mm || 0.3).toFixed(2) + ' x ' + (_cohInfo.A_KB_V_mm || 0.9).toFixed(2) + ' mm</span>';
    h += '</div>';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:1px">';
    h += '<span>SSA (H x V):</span>';
    h += '<span style="color:var(--t2)">' + (_cohInfo.ssa_h_um || 50) + ' x ' + (_cohInfo.ssa_v_um || 50) + ' \u03BCm</span>';
    h += '</div>';
    var _cohLabel = _cohInfo.coherent_fraction > 0.8 ? 'Highly coherent' :
      (_cohInfo.coherent_fraction > 0.3 ? 'Partially coherent' :
      (_cohInfo.coherent_fraction > 0.05 ? 'Low coherence' : 'Incoherent'));
    h += '<div style="color:' + _cohColor + ';font-size:8px;text-align:center;margin-top:2px">' + _cohLabel + '</div>';
    h += '</div>';
  } else {
    h += '<div style="font-size:8px;color:var(--t3)">Coherence data unavailable</div>';
  }

  // Quality Check: Pre-flight screening
  h += '<div style="color:var(--ac);font-weight:700;margin:6px 0 3px">Quality Check</div>';
  h += '<div style="font-size:9px;color:var(--t3);padding:4px;background:var(--s1);border-radius:3px">';
  var _pfResult = null;
  try { _pfResult = _ptychoPreflightCheck(pp); } catch(e) {}
  if (_pfResult) {
    for (var _qi = 0; _qi < _pfResult.checks.length; _qi++) {
      var _chk = _pfResult.checks[_qi];
      var _chkColor = _chk.status === 'pass' ? 'var(--gn)' : (_chk.status === 'warn' ? 'var(--am)' : '#e05050');
      var _chkIcon = _chk.status === 'pass' ? 'PASS' : (_chk.status === 'warn' ? 'WARN' : 'FAIL');
      h += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:2px">';
      h += '<span style="color:' + _chkColor + ';font-weight:700;min-width:32px;font-size:8px">' + _chkIcon + '</span>';
      h += '<span style="min-width:65px">' + _chk.name + '</span>';
      h += '<span style="color:var(--t2);flex:1">' + _chk.message + '</span>';
      h += '</div>';
    }
    if (_pfResult.recommendations.length > 0) {
      h += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid var(--s2);color:var(--am)">';
      for (var _ri = 0; _ri < _pfResult.recommendations.length; _ri++) {
        h += '<div style="font-size:8px;margin-bottom:1px">* ' + _pfResult.recommendations[_ri] + '</div>';
      }
      h += '</div>';
    }
  } else {
    h += '<div>Quality check unavailable</div>';
  }
  h += '</div>';

  // SSA Recommendation
  var _ssaRec = null;
  try { _ssaRec = _ptychoSSARecommendation(eKev); } catch(e) {}
  if (_ssaRec) {
    h += '<div style="font-size:8px;color:var(--t3);margin-top:3px;padding:3px 5px;background:var(--s1);border-radius:2px;border-left:2px solid var(--ac)">';
    h += '<div style="color:var(--ac);font-weight:700;margin-bottom:1px">SSA Trade-off</div>';
    h += '<div>' + _ssaRec.recommendation + '</div>';
    h += '</div>';
  }

  return h;
}

// ── Refresh coherence block when SSA, energy, or detector params change ──
window._refreshPtychoCoherence = function() {
  var block = document.getElementById('ptychoCoherenceBlock');
  if (!block) return;
  // Read latest values from UI inputs into _exptState.ptycho
  try { _readPtychoParams(); } catch(e) {}
  var eKev = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  var pp = _exptState.ptycho;
  block.innerHTML = _renderPtychoCoherenceBlock(eKev, pp);
};

// ── Dwell time change → update N_photons auto estimate ──
window._updatePtychoDwellEstimate = function() {
  var dwellEl = document.getElementById('exptPtychoDwell');
  var nphEl = document.getElementById('exptPtychoNph');
  var nphAutoEl = document.getElementById('ptychoNphAuto');
  if (!dwellEl) return;
  var dwell = parseFloat(dwellEl.value) || 0.1;
  var energy_keV = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  var autoNph = 0;
  try { autoNph = _fluxToPhotons(energy_keV, dwell); } catch(e) {}
  // Update placeholder with auto value
  if (nphEl) nphEl.placeholder = 'auto ' + autoNph.toExponential(1);
  // If manual value is empty, show auto label
  if (nphAutoEl) {
    nphAutoEl.textContent = (nphEl && nphEl.value) ? 'manual' : 'auto: flux*dwell';
  }
  // Also update quality check
  _updatePtychoQualityCheck();
};

// ── Update Quality Check display ──
window._updatePtychoQualityCheck = function() {
  var el = document.getElementById('ptychoQualityCheck');
  if (!el) return;
  // Quick read current params from UI
  _readPtychoParams();
  var pp = _exptState.ptycho;
  var result = null;
  try { result = _ptychoPreflightCheck(pp); } catch(e) {}
  if (!result) return;
  var h = '';
  for (var i = 0; i < result.checks.length; i++) {
    var chk = result.checks[i];
    var clr = chk.status === 'pass' ? 'var(--gn)' : (chk.status === 'warn' ? 'var(--am)' : '#e05050');
    var icon = chk.status === 'pass' ? 'PASS' : (chk.status === 'warn' ? 'WARN' : 'FAIL');
    h += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:2px">';
    h += '<span style="color:' + clr + ';font-weight:700;min-width:32px;font-size:8px">' + icon + '</span>';
    h += '<span style="min-width:65px">' + chk.name + '</span>';
    h += '<span style="color:var(--t2);flex:1">' + chk.message + '</span>';
    h += '</div>';
  }
  if (result.recommendations.length > 0) {
    h += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid var(--s2);color:var(--am)">';
    for (var j = 0; j < result.recommendations.length; j++) {
      h += '<div style="font-size:8px;margin-bottom:1px">* ' + result.recommendations[j] + '</div>';
    }
    h += '</div>';
  }
  el.innerHTML = h;
};

// ── Live scan estimate update ──
window._updatePtychoScanEstimate = function() {
  var el = document.getElementById('ptychoScanEstimate');
  if (!el) return;
  var lxEl = document.getElementById('exptPtychoLxUm');
  var lyEl = document.getElementById('exptPtychoLyUm');
  var stepEl = document.getElementById('exptPtychoStepUm');
  var asizeEl = document.getElementById('exptPtychoAsize');
  var ovSpan = document.getElementById('ptychoOverlapSpan');
  var lx = lxEl ? (parseFloat(lxEl.value) || 3) : 3;
  var ly = lyEl ? (parseFloat(lyEl.value) || 3) : 3;
  var asize = asizeEl ? (parseInt(asizeEl.value, 10) || 512) : 512;
  // beam size for auto step
  var _bsz = {h:50,v:50}; try { if (typeof focalSpot === 'function') _bsz = focalSpot(); } catch(e) {}
  var beamMaxNm = Math.max(_bsz.h, _bsz.v);
  var autoStepUm = parseFloat((beamMaxNm * 0.4 / 1000).toFixed(4));
  var stepVal = stepEl ? parseFloat(stepEl.value) : 0;
  var effectiveStep = (stepVal > 0) ? stepVal : autoStepUm;
  // Npos
  var npos = Math.max(1, Math.round(Math.PI * (lx * ly) / (effectiveStep * effectiveStep) * 0.25));
  // Memory
  var memGB = (asize * asize * npos * 4) / 1e9;
  var memColor = memGB < 2 ? 'var(--gn)' : (memGB < 4 ? 'var(--am)' : '#e05050');
  // Time
  var fftMs = asize <= 128 ? 0.1 : (asize <= 256 ? 0.3 : (asize <= 512 ? 1.0 : 2.5));
  var timeSec = (2 * npos * fftMs) / 1000;
  var timeStr;
  if (timeSec < 60) { timeStr = Math.round(timeSec) + 's'; }
  else if (timeSec < 3600) { timeStr = Math.round(timeSec / 60) + 'm ' + Math.round(timeSec % 60) + 's'; }
  else { timeStr = Math.round(timeSec / 3600) + 'h ' + Math.round((timeSec % 3600) / 60) + 'm'; }
  el.style.borderLeftColor = memColor;
  el.innerHTML = 'Scan: ~' + npos + ' positions (Fermat) | fmag: ' + memGB.toFixed(2) + ' GB | ~' + timeStr +
    (memGB >= 4 ? ' <span style="color:#e05050;font-weight:700">scan area will be reduced (overlap preserved)</span>' : '');
  // Update overlap display
  if (ovSpan) {
    var overlapPct = Math.round((1 - effectiveStep / (beamMaxNm / 1000)) * 100);
    var ovColor = overlapPct >= 50 ? 'var(--gn)' : (overlapPct >= 20 ? 'var(--am)' : '#e05050');
    ovSpan.style.color = ovColor;
    ovSpan.textContent = overlapPct + '% overlap';
  }
  // Also update quality check display
  _updatePtychoQualityCheck();
};

// ── Styles ──
var _inputSty = 'background:var(--s2);color:var(--t1);border:1px solid var(--s2);padding:2px 4px;border-radius:2px;font-size:10px;font-family:var(--mn);';
var _selectSty = 'background:var(--s2);color:var(--t1);border:1px solid var(--s2);padding:2px 4px;border-radius:2px;font-size:10px;font-family:var(--mn);';
// Inline CSS string for small secondary buttons (s2 background, 2x8px padding, 9px monospace, pointer cursor).
var _btnSmallSty = 'background:var(--s2);color:var(--t2);border:1px solid var(--s2);padding:2px 8px;border-radius:2px;font-size:9px;font-family:var(--mn);cursor:pointer;';

// Builds one flex form-row HTML: a label span (min-width 65px) plus the supplied control markup, used across all mode panels.
function _row(label, ctrl) {
  return '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px"><span style="color:var(--t3);min-width:65px;font-size:9px">' + label + ':</span><span style="font-size:10px">' + ctrl + '</span></div>';
}

// Returns <option> HTML for every key in the CRYSTALS table, marking the passed value selected; falls back to a single Cu option.
function _crystalOptions(selected) {
  if (typeof CRYSTALS === 'undefined') return '<option>Cu</option>';
  var h = '', keys = Object.keys(CRYSTALS);
  for (var i = 0; i < keys.length; i++) {
    h += '<option value="' + keys[i] + '"' + (keys[i] === selected ? ' selected' : '') + '>' + keys[i] + '</option>';
  }
  return h;
}

// Returns <option> HTML of the element symbols from parseFormula(formula), marking the given absorber selected for the XAFS edge picker.
function _absorberOptions(formula, selected) {
  var h = '';
  if (typeof parseFormula === 'function') {
    var parsed = parseFormula(formula);
    var keys = Object.keys(parsed);
    for (var i = 0; i < keys.length; i++) {
      h += '<option value="' + keys[i] + '"' + (keys[i] === selected ? ' selected' : '') + '>' + keys[i] + '</option>';
    }
  } else {
    h += '<option value="' + selected + '" selected>' + selected + '</option>';
  }
  return h;
}

// On XAFS formula input change, stores it in state, rebuilds the absorber dropdown from its parsed elements, and refreshes edge info.
window._exptXafsFormulaChanged = function() {
  var el = document.getElementById('exptXafsFormula');
  if (!el) return;
  _exptState.xafs.formula = el.value.trim();
  var absSel = document.getElementById('exptXafsAbsorber');
  if (absSel && typeof parseFormula === 'function') {
    var parsed = parseFormula(_exptState.xafs.formula);
    var keys = Object.keys(parsed), h2 = '';
    for (var i = 0; i < keys.length; i++) h2 += '<option value="' + keys[i] + '">' + keys[i] + '</option>';
    absSel.innerHTML = h2;
    if (keys.length > 0) _exptState.xafs.absorber = keys[0];
  }
  _updateXafsEdgeInfo();
};

// ── XAFS Edge Energy Info + Beamline Range Warning ──
// Stubbed 2026-06-10: per user request, the edge/flux/range banner is no longer
// surfaced in the XAFS panel. Function kept as a no-op clear so existing inline
// onchange handlers (#exptXafsAbsorber, #exptXafsEdge), the tail call from
// _exptXafsFormulaChanged, the mode-refresh helper, and the globalThis export
// shim all continue to resolve without ReferenceError. The #xafsEdgeInfo div is
// retained but will simply be cleared on every call.
window._updateXafsEdgeInfo = function() {
  var infoEl = document.getElementById('xafsEdgeInfo');
  if (!infoEl) return;
  infoEl.innerHTML = '';
};

// ── XRF 2D Preset Change Handler ──
window._xrf2dPresetChanged = function() {
  var sel = document.getElementById('exptXrf2dPreset');
  if (!sel || !sel.value) return;
  var key = sel.value;
  var preset = (typeof XRF_SAMPLE_PRESETS !== 'undefined') ? XRF_SAMPLE_PRESETS[key] : null;
  if (!preset) return;
  _exptState.xrf2d.presetKey = key;
  _exptState.xrf2d.formula = preset.formula || 'Cu';
  _exptState.xrf2d.thickness_um = preset.thickness_um || 1.0;
  _exptState.xrf2d.matDensity = preset.matrixDensity || 2.0;
  _exptState.xrf2d.sampleType = preset.sampleType || 'solid';
  // Set ppm to 10000 (full concentration for preset-based multi-element)
  _exptState.xrf2d.ppm = 1000000;
  renderExptTab();
};

// ── XRD 2D Preset Change Handler ──
window._xrd2dPresetChanged = function() {
  var sel = document.getElementById('exptXrd2dPreset');
  if (!sel || !sel.value) { _exptState.xrd2d.presetKey = ''; return; }
  var key = sel.value;
  var preset = (typeof XRD_SAMPLE_PRESETS !== 'undefined') ? XRD_SAMPLE_PRESETS[key] : null;
  if (!preset) return;
  _exptState.xrd2d.presetKey = key;
  _exptState.xrd2d.crystal = preset.crystal || 'Cu';
  _exptState.xrd2d.detDist = preset.detDist || 0.05;
  _exptState.xrd2d.detector = preset.detector || 'EIGER2_1M';
  renderExptTab();
};

// Sets the active experiment mode (xafs/xrd2d/xrf2d/xrdmap/ptycho), re-renders the tab, and auto-connects the ptycho server when entered.
window.switchExptMode = function(mode) {
  _exptState.mode = mode;
  renderExptTab();
  // Auto-connect to K4GSR-PTYCHO server when switching to ptycho mode
  if (mode === 'ptycho' && typeof ptychoConnect === 'function') {
    if (!_ptychoConnected) ptychoConnect();
  }
};

// ── Read params from UI ──
function _readExptParams() {
  var mode = _exptState.mode;
  // Programmatic callers (NLP/quick* set _exptState directly) must NOT have their
  // values overwritten by stale Expt-tab DOM inputs. Honor _skipDomRead for ALL
  // modes (previously only xafs did, so quickRaster's xrf2d geometry was clobbered
  // by the tab's default 10x10/0.5 inputs), then consume the flag.
  if (_exptState._skipDomRead) { _exptState._skipDomRead = false; return; }
  if (mode === 'xafs') {
    // Skip DOM read if _exptState was set programmatically (NLP/quickXanes)
    // — DOM may contain stale values from previous Expt tab interaction
    if (!_exptState._skipDomRead) {
      var f = document.getElementById('exptXafsFormula');
      var a = document.getElementById('exptXafsAbsorber');
      var e = document.getElementById('exptXafsEdge');
      var es = document.getElementById('exptXafsEStart');
      var ee = document.getElementById('exptXafsEEnd');
      var est = document.getElementById('exptXafsEStep');
      if (f && f.value) _exptState.xafs.formula = f.value.trim();
      if (a && a.value) _exptState.xafs.absorber = a.value;
      if (e && e.value) _exptState.xafs.edge = e.value;
      if (es) _exptState.xafs.eStart = parseFloat(es.value) || _exptState.xafs.eStart || -50;
      if (ee) _exptState.xafs.eEnd = parseFloat(ee.value) || _exptState.xafs.eEnd || 300;
      if (est) _exptState.xafs.eStep = parseFloat(est.value) || _exptState.xafs.eStep || 0.5;
      var ppmEl = document.getElementById('exptXafsPPM');
      var stEl = document.getElementById('exptXafsSampleType');
      if (ppmEl) _exptState.xafs.ppm = parseFloat(ppmEl.value) || _exptState.xafs.ppm || 10000;
      if (stEl && stEl.value) _exptState.xafs.sampleType = stEl.value;
      var icEl = document.getElementById('exptXafsIC');
      var icDwEl = document.getElementById('exptXafsICDwell');
      if (icEl) _exptState.xafs.icMode = !!icEl.checked;
      if (icDwEl) _exptState.xafs.icDwell = parseFloat(icDwEl.value) || _exptState.xafs.icDwell || 1.0;
    }
    _exptState._skipDomRead = false; // reset after use
  } else if (mode === 'xrd2d') {
    var c2 = document.getElementById('exptXrd2dCrystal');
    var dd = document.getElementById('exptXrd2dDist');
    var detSel = document.getElementById('exptXrd2dDet');
    if (c2) _exptState.xrd2d.crystal = c2.value;
    if (dd) _exptState.xrd2d.detDist = parseFloat(dd.value) || 0.05;
    if (detSel) _exptState.xrd2d.detector = detSel.value;
  } else if (mode === 'xrf2d') {
    // Only read from DOM if Expt tab is rendered; otherwise keep _exptState values
    // (NLP sets _exptState directly without rendering the tab)
    var xfEl;
    xfEl = document.getElementById('exptXrf2dPreset');    if (xfEl && xfEl.value) _exptState.xrf2d.presetKey = xfEl.value;
    xfEl = document.getElementById('exptXrf2dFormula');   if (xfEl && xfEl.value) _exptState.xrf2d.formula = xfEl.value.trim();
    xfEl = document.getElementById('exptXrf2dPPM');       if (xfEl) _exptState.xrf2d.ppm = parseFloat(xfEl.value) || _exptState.xrf2d.ppm || 1000;
    xfEl = document.getElementById('exptXrf2dThickness'); if (xfEl) _exptState.xrf2d.thickness_um = parseFloat(xfEl.value) || _exptState.xrf2d.thickness_um || 1.0;
    xfEl = document.getElementById('exptXrf2dDensity');   if (xfEl) _exptState.xrf2d.matDensity = parseFloat(xfEl.value) || _exptState.xrf2d.matDensity || 2.0;
    xfEl = document.getElementById('exptXrf2dSampleType');if (xfEl && xfEl.value) _exptState.xrf2d.sampleType = xfEl.value;
    xfEl = document.getElementById('exptXrf2dLx');        if (xfEl) _exptState.xrf2d.scanLx = parseFloat(xfEl.value) || _exptState.xrf2d.scanLx || 10;
    xfEl = document.getElementById('exptXrf2dLy');        if (xfEl) _exptState.xrf2d.scanLy = parseFloat(xfEl.value) || _exptState.xrf2d.scanLy || 10;
    xfEl = document.getElementById('exptXrf2dStep');      if (xfEl) _exptState.xrf2d.step = parseFloat(xfEl.value) || _exptState.xrf2d.step || 0.5;
    xfEl = document.getElementById('exptXrf2dDwell');     if (xfEl) _exptState.xrf2d.dwell = parseFloat(xfEl.value) || _exptState.xrf2d.dwell || 0.1;
  } else if (mode === 'xrdmap') {
    var xmEl;
    var xm2 = _exptState.xrdmap;
    xmEl = document.getElementById('exptXrdMapCryst1'); if (xmEl) xm2.crystals[0] = xmEl.value;
    xmEl = document.getElementById('exptXrdMapCryst2'); if (xmEl) xm2.crystals[1] = xmEl.value || '';
    xmEl = document.getElementById('exptXrdMapDet');    if (xmEl) xm2.detector = xmEl.value;
    xmEl = document.getElementById('exptXrdMapDist');   if (xmEl) xm2.detDist = parseFloat(xmEl.value) || 0.3;
    xmEl = document.getElementById('exptXrdMapLx');     if (xmEl) xm2.scanLx = parseFloat(xmEl.value) || 10;
    xmEl = document.getElementById('exptXrdMapLy');     if (xmEl) xm2.scanLy = parseFloat(xmEl.value) || 10;
    xmEl = document.getElementById('exptXrdMapStep');   if (xmEl) xm2.step = parseFloat(xmEl.value) || 0.5;
  } else if (mode === 'ptycho') {
    _readPtychoParams();
  }
}

// Reads ptycho UI inputs (dataset, material, thickness um, step/scan um, z m, dwell s, N_photons, asize, engine, iters) into state.
function _readPtychoParams() {
  var pp = _exptState.ptycho;
  var el;
  el = document.getElementById('exptPtychoDataset'); if (el) pp.dataset_id = parseInt(el.value) || 6;
  el = document.getElementById('exptPtychoMat');     if (el) pp.material = el.value;
  el = document.getElementById('exptPtychoH');       if (el) pp.objheight_um = parseFloat(el.value) || 1.0;
  el = document.getElementById('exptPtychoStepUm');  if (el) pp.scan_step_um = parseFloat(el.value) || 0;
  el = document.getElementById('exptPtychoLxUm');    if (el) pp.scan_lx_um = parseFloat(el.value) || 3;
  el = document.getElementById('exptPtychoLyUm');    if (el) pp.scan_ly_um = parseFloat(el.value) || 3;
  el = document.getElementById('exptPtychoZ');       if (el) pp.z_m = parseFloat(el.value) || 0.5;
  el = document.getElementById('exptPtychoDwell');   if (el) pp.dwellTime = parseFloat(el.value) || 0.1;
  el = document.getElementById('exptPtychoNph');     if (el) pp.N_photons = parseInt(el.value) || 0;  // 0 = auto (flux*dwell)
  el = document.getElementById('exptPtychoNoiseSigma'); if (el) pp.noise_sigma = parseFloat(el.value) || 0.0;
  el = document.getElementById('exptPtychoDet');     if (el) pp.ptychoDetector = el.value;
  el = document.getElementById('exptPtychoAsize');   if (el) pp.asize = parseInt(el.value) || 512;
  el = document.getElementById('exptPtychoEngine');   if (el) pp.reconEngine = el.value || 'DM_ML';
  el = document.getElementById('exptPtychoDMIter');   if (el) pp.dmIterations = parseInt(el.value) || 300;
  el = document.getElementById('exptPtychoMLIter');   if (el) pp.mlIterations = parseInt(el.value) || 30;
}

// ── Save reconstruction result as PNG ──
window._savePtychoResult = function() {
  var cvs = document.getElementById('exptPopup_ptycho_canvas');
  if (!cvs || cvs.width < 10) {
    var infoEl = document.getElementById('exptInfo');
    if (infoEl) infoEl.textContent = 'No result to save';
    return;
  }
  var ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  var link = document.createElement('a');
  link.download = 'ptycho_result_' + ts + '.png';
  link.href = cvs.toDataURL('image/png');
  link.click();
  var infoEl2 = document.getElementById('exptInfo');
  if (infoEl2) infoEl2.textContent = 'Saved: ' + link.download;
};

// ── Progress bar ──
window._updateExptProgress = function(frac, msg) {
  var bar = document.getElementById('exptProgBar');
  var txt = document.getElementById('exptProgText');
  var info = document.getElementById('exptInfo');
  var pct = Math.round(frac * 100);
  if (bar) bar.style.width = pct + '%';
  if (txt) txt.textContent = pct + '%';
  if (info && msg) info.textContent = msg;
};

// ── Popup re-render registry ──
// Each experiment registers a re-render function after completion.
// When popup is resized, onResize calls this to redraw the canvas.
var _exptPopupRenderers = {};  // {mode: function(canvas){...}}

// Stores a per-mode canvas redraw function in _exptPopupRenderers so popup resize/reopen can re-render that mode's result.
window._registerExptRenderer = function(mode, fn) {
  _exptPopupRenderers[mode] = fn;
};

// ── Re-open closed experiment popup ──
window._reopenExptPopup = function() {
  var mode = (typeof _exptState !== 'undefined') ? _exptState.mode : '';
  if (!mode) return;
  var popupId = 'exptPopup_' + mode;
  var el = document.getElementById(popupId);
  if (el) {
    el.style.display = 'flex';
    // Re-init canvas size after flex layout recomputes
    setTimeout(function() {
      var cvs = document.getElementById(popupId + '_canvas');
      if (cvs && cvs.clientWidth > 0) {
        cvs.width = cvs.clientWidth;
        cvs.height = cvs.clientHeight;
        if (_exptPopupRenderers[mode]) {
          try { _exptPopupRenderers[mode](cvs); } catch(e) {}
        }
      }
    }, 50);
  }
};

// ── Popup creation (reusable for all experiment types) ──
window._openExptPopup = function(mode, title, width, height) {
  var popupId = 'exptPopup_' + mode;
  var existing = document.getElementById(popupId);
  if (existing) {
    // If this popup already shows a COMPLETED result, freeze it into a static
    // side-by-side snapshot first so the NEW run's result can be compared
    // instead of replacing it (user request). _freezeExptResultPopup snapshots
    // the rendered canvas, builds a standalone snapshot window, removes this
    // live popup, and returns true -> fall through to create a fresh popup.
    // If there is no rendered result yet (still computing/blank) it returns
    // false and we reuse the popup as before.
    // Opt-in: only freeze the previous result into a side-by-side snapshot when
    // the user enabled Compare mode. Default (off) reuses the popup in place, so
    // re-running a scan replaces the previous result instead of stacking windows.
    if (window._exptCompareMode &&
        typeof _freezeExptResultPopup === 'function' && _freezeExptResultPopup(mode)) {
      existing = null;   // froze + removed -> create a fresh popup below
    }
  }
  if (existing) {
    existing.style.display = 'flex';
    // Dynamically update popup title (fixes stale title on parameter change)
    var _hdrSpan = existing.querySelector('#' + popupId + '_hdr span');
    if (_hdrSpan && title) _hdrSpan.textContent = title;
    // Re-init canvas size + re-render (defer to allow flex layout to compute)
    // Per UI guide: canvas.width= always clears buffer → must re-render after
    setTimeout(function() {
      var cvs = document.getElementById(popupId + '_canvas');
      if (cvs && cvs.clientWidth > 0) {
        cvs.width = cvs.clientWidth;
        cvs.height = cvs.clientHeight;
        // Re-render to avoid blank canvas after buffer clear
        if (_exptPopupRenderers[mode]) {
          try { _exptPopupRenderers[mode](cvs); } catch(e) {
            console.warn('[Expt] re-open render error:', e);
          }
        }
      }
    }, 30);
    return existing;
  }

  width = width || 650;
  height = height || 520;

  var div = document.createElement('div');
  div.id = popupId;
  div.style.cssText = 'position:fixed;left:80px;top:50px;width:' + width + 'px;height:' + height + 'px;' +
    'background:var(--bg);border:1px solid var(--b1,#3d5068);border-radius:4px;' +
    'box-shadow:0 4px 16px rgba(0,0,0,0.5);z-index:1000;display:flex;flex-direction:column';

  // Header
  var hdr = document.createElement('div');
  hdr.id = popupId + '_hdr';
  hdr.style.cssText = 'flex:0 0 auto;background:var(--s1);padding:6px 10px;display:flex;justify-content:space-between;align-items:center;cursor:move;user-select:none;border-radius:4px 4px 0 0';
  hdr.innerHTML = '<span style="color:var(--ac);font:bold 11px var(--mn)">' + (title || mode.toUpperCase() + ' Simulation') + '</span>' +
    '<button onclick="document.getElementById(\'' + popupId + '\').style.display=\'none\'" style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:13px;padding:0 4px">X</button>';

  // Canvas body
  var body = document.createElement('div');
  body.style.cssText = 'flex:1;position:relative;overflow:hidden;min-height:0';
  var cvs = document.createElement('canvas');
  cvs.id = popupId + '_canvas';
  cvs.style.cssText = 'width:100%;height:100%;display:block';
  body.appendChild(cvs);

  // Info bar
  var infoBar = document.createElement('div');
  infoBar.id = popupId + '_info';
  infoBar.style.cssText = 'flex:0 0 auto;padding:5px 10px;font:12px var(--mn);color:var(--t2);border-top:1px solid var(--s2);background:var(--s1);border-radius:0 0 4px 4px';
  infoBar.textContent = 'Computing...';

  div.appendChild(hdr);
  div.appendChild(body);
  div.appendChild(infoBar);
  document.body.appendChild(div);

  // Make resizable + draggable
  if (typeof _makePopupResizable === 'function') {
    _makePopupResizable(div, {
      dragEl: hdr,
      minWidth: 400,
      minHeight: 320,
      onResize: function() {
        // onMove passes (width, height) during drag; onUp passes no args.
        // Skip re-render during drag -- CSS width:100%;height:100% on
        // canvas stretches content visually. Re-render only on mouse-up
        // to avoid expensive uPlot destroy/create cycles and canvas
        // clearing that causes white screen.
        if (arguments.length > 0) return;

        var c = document.getElementById(popupId + '_canvas');
        if (!c) return;

        // uPlot mode: canvas is display:none, uPlot div renders instead
        var isHidden = (c.style.display === 'none' || c.offsetWidth === 0);
        if (isHidden) {
          if (_exptPopupRenderers[mode]) {
            try { _exptPopupRenderers[mode](c); } catch(e) {
              console.warn('[Expt] re-render error:', e);
            }
          }
          return;
        }

        // Canvas mode: resize buffer then re-render
        if (c.clientWidth > 0) {
          c.width = c.clientWidth;
          c.height = c.clientHeight;
          if (_exptPopupRenderers[mode]) {
            try { _exptPopupRenderers[mode](c); } catch(e) {
              console.warn('[Expt] re-render error:', e);
            }
          }
          var ov = document.getElementById(popupId + '_canvas_overlay');
          if (ov) {
            var ovCtx = ov.getContext('2d');
            if (ovCtx) ovCtx.clearRect(0, 0, ov.width, ov.height);
          }
        }
      }
    });
  }

  // Init canvas dimensions (multiple attempts for flex layout timing)
  // After setting canvas.width (which clears buffer), re-render if a
  // renderer was already registered (fixes race with fast experiment results).
  function _initCanvasSize(attempt) {
    var c = document.getElementById(popupId + '_canvas');
    if (!c) return;
    var cw = 0, ch = 0;
    if (c.clientWidth > 10 && c.clientHeight > 10) {
      cw = c.clientWidth; ch = c.clientHeight;
    } else {
      var par = c.parentNode;
      if (par && par.clientWidth > 10 && par.clientHeight > 10) {
        cw = par.clientWidth; ch = par.clientHeight;
      }
    }
    if (cw > 10 && ch > 10) {
      c.width = cw;
      c.height = ch;
      // Re-render: buffer was just cleared, restore content if renderer exists
      if (_exptPopupRenderers[mode]) {
        try { _exptPopupRenderers[mode](c); } catch(e) {}
      }
      return;
    }
    if (attempt < 5) {
      setTimeout(function() { _initCanvasSize(attempt + 1); }, 50);
    }
  }
  setTimeout(function() { _initCanvasSize(0); }, 30);

  return div;
};

// Freeze the CURRENT result popup for a mode into its OWN standalone window so
// the NEXT scan's result can be shown alongside it for comparison (instead of
// replacing it). Captures this result's RENDERER closure (which closes over the
// result data) so the frozen window is a real, re-renderable figure -- it
// redraws crisply at any size on resize, not a stretched bitmap. Returns true
// if a window was created (then the caller creates a fresh popup for the new
// result). Renderer closures are per-mode in _exptPopupRenderers; capture it
// here BEFORE the new scan overwrites it.
window._freezeExptResultPopup = function(mode) {
  var id = 'exptPopup_' + mode;
  var prev = document.getElementById(id);
  if (!prev) return false;
  var cvs = document.getElementById(id + '_canvas');
  if (!cvs || !(cvs.width > 1)) return false;   // nothing rendered yet -> reuse
  // This result's renderer (closes over its own maps/data); kept so the frozen
  // window can redraw itself independently of later scans.
  var renderer = (typeof _exptPopupRenderers !== 'undefined') ? _exptPopupRenderers[mode] : null;
  var snapUrl = null;
  if (!renderer) { try { snapUrl = cvs.toDataURL('image/png'); } catch (e) { return false; } }

  var info = document.getElementById(id + '_info');
  var hdrSpan = prev.querySelector('span');
  var titleTxt = hdrSpan ? hdrSpan.textContent : mode;
  var infoTxt = info ? info.textContent : '';
  var r = prev.getBoundingClientRect();
  var seq = (window._exptFrozenSeq = (window._exptFrozenSeq || 0) + 1);
  var fid = id + '_frozen' + seq;

  // Place beside the spot where the NEW result popup will spawn (left:80) so the
  // two results sit side by side for comparison, not stacked.
  var vw = window.innerWidth || 1400;
  var fw = Math.round(r.width) || 700, fh = Math.round(r.height) || 500;
  var fx = Math.min(96 + fw + (seq - 1) * 30, Math.max(120, vw - fw - 20));
  var fy = 50 + (seq - 1) * 30;
  var sd = document.createElement('div');
  sd.id = fid;
  sd.style.cssText = 'position:fixed;left:' + fx + 'px;top:' + fy + 'px;width:' + fw +
    'px;height:' + fh + 'px;background:var(--bg);border:1px solid var(--b1,#3d5068);' +
    'border-radius:4px;box-shadow:0 4px 16px rgba(0,0,0,0.5);z-index:999;display:flex;flex-direction:column';

  var sh = document.createElement('div');
  sh.id = fid + '_hdr';
  sh.style.cssText = 'flex:0 0 auto;background:var(--s1);padding:6px 10px;display:flex;justify-content:space-between;align-items:center;cursor:move;user-select:none;border-radius:4px 4px 0 0';
  sh.innerHTML = '<span style="color:var(--am);font:bold 11px var(--mn)">&#10063; ' +
    titleTxt + '</span><button title="Close this snapshot" style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:13px;padding:0 4px">X</button>';

  var sb = document.createElement('div');
  sb.style.cssText = 'flex:1;position:relative;overflow:hidden;min-height:0';
  var fcanvas = null;
  if (renderer) {
    fcanvas = document.createElement('canvas');
    fcanvas.id = fid + '_canvas';
    fcanvas.style.cssText = 'width:100%;height:100%;display:block';
    sb.appendChild(fcanvas);
  } else {
    var img = document.createElement('img');
    img.src = snapUrl;
    img.style.cssText = 'width:100%;height:100%;display:block;object-fit:contain;background:var(--bg)';
    sb.appendChild(img);
  }

  var si = document.createElement('div');
  si.style.cssText = 'flex:0 0 auto;padding:5px 10px;font:12px var(--mn);color:var(--t2);border-top:1px solid var(--s2);background:var(--s1);border-radius:0 0 4px 4px';
  si.textContent = infoTxt;

  sd.appendChild(sh); sd.appendChild(sb); sd.appendChild(si);
  document.body.appendChild(sd);
  sh.querySelector('button').onclick = function() { sd.remove(); };

  // Re-render THIS result's figure at the canvas's current size (crisp, not a
  // stretched image), using the captured renderer. The experiment popups size
  // the canvas buffer to clientWidth/Height (no devicePixelRatio), so match that.
  function _renderFrozen() {
    if (!renderer || !fcanvas || fcanvas.clientWidth < 2) return;
    fcanvas.width = fcanvas.clientWidth;
    fcanvas.height = fcanvas.clientHeight;
    try { renderer(fcanvas); } catch (e) { console.warn('[Expt] frozen re-render error:', e); }
  }
  if (typeof _makePopupResizable === 'function') {
    _makePopupResizable(sd, {
      dragEl: sh, minWidth: 320, minHeight: 260,
      onResize: function() { if (arguments.length > 0) return; _renderFrozen(); }
    });
  }
  if (renderer) setTimeout(_renderFrozen, 30);   // initial draw after layout settles
  prev.remove();   // remove the old live popup; a fresh one is created next
  return true;
};


// ======================================================================
//  Simulation Server WebSocket Client (port 8002, high-fidelity)
// ======================================================================

var _simWs = null;
var _simWsConnected = false;
var _simWsReconnectTimer = null;
// Auto-detect: main port + 1 (e.g., 8081 → 8082, 8001 → 8002)
var _simAutoPort = (typeof location !== 'undefined' && location.port) ? (parseInt(location.port) + 1) : 8002;
// Port for the simulation server WebSocket, defaulting to main port+1 (e.g. 8001->8002), overridable via the ?simport= URL param.
var SIM_WS_PORT = _simAutoPort || 8002;

// Parse ?simport= URL parameter (override)
try {
  var _urlParams = new URLSearchParams(window.location.search);
  var _simPortParam = _urlParams.get('simport');
  if (_simPortParam) SIM_WS_PORT = parseInt(_simPortParam, 10) || SIM_WS_PORT;
} catch(e) {}

// -- Connect to simulation server --
// Tries SERVER_HOST first, then falls back to localhost if connection fails.
var _simFallbackToLocal = false;
// Opens the WebSocket to the high-fidelity sim server (/ws/sim on SIM_WS_PORT), with SERVER_HOST-to-localhost fallback and 5s reconnect.
window.simServerConnect = function(url) {
  if (!url) {
    var _simHost = 'localhost';
    if (!_simFallbackToLocal) {
      try { if (typeof SERVER_HOST !== 'undefined' && SERVER_HOST) _simHost = SERVER_HOST; } catch(e) {}
    }
    url = 'ws://' + _simHost + ':' + SIM_WS_PORT + '/ws/sim';
  }
  if (_simWs && _simWs.readyState <= 1) return;

  try {
    _simWs = new WebSocket(url);
  } catch(e) {
    _simWsConnected = false;
    _updateSimConnectionUI(false);
    return;
  }

  _simWs.onopen = function() {
    _simWsConnected = true;
    _updateSimConnectionUI(true);
    console.log('[Sim] Connected: ' + url);
    try {
      _simWs.send(JSON.stringify({action: 'list_modes'}));
    } catch(e2) {}
  };

  _simWs.onclose = function() {
    _simWsConnected = false;
    _updateSimConnectionUI(false);
    console.log('[Sim] Disconnected');
    clearTimeout(_simWsReconnectTimer);
    _simWsReconnectTimer = setTimeout(function() {
      simServerConnect(url);
    }, 5000);
  };

  _simWs.onerror = function() {
    _simWsConnected = false;
    _updateSimConnectionUI(false);
    // If remote SERVER_HOST failed, try localhost fallback
    if (!_simFallbackToLocal) {
      _simFallbackToLocal = true;
      console.log('[Sim] Remote failed, trying localhost fallback...');
      setTimeout(function() { simServerConnect(); }, 500);
    }
  };

  _simWs.onmessage = function(ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch(err) { return; }
    // Reuse the same handler -- protocol is identical
    try { _handleExptServerMessage(msg); } catch(err) {
      console.error('[Sim] message handler error:', err);
    }
  };
};

// -- Disconnect --
window.simServerDisconnect = function() {
  clearTimeout(_simWsReconnectTimer);
  _simWsReconnectTimer = null;
  if (_simWs) {
    _simWs.onclose = null;
    _simWs.close();
    _simWs = null;
  }
  _simWsConnected = false;
  _updateSimConnectionUI(false);
};

// -- Send experiment run to simulation server --
window._simSendRun = function(mode, params) {
  if (!_simWs || _simWs.readyState !== 1) return false;
  var msg = {
    action: 'run',
    mode: mode,
    params: params
  };
  msg.params.beamline = _buildBeamlineContext();
  try {
    _simWs.send(JSON.stringify(msg));
    return true;
  } catch(e) {
    console.error('[Sim] send error:', e);
    return false;
  }
};

// -- Cancel running simulation --
window._simSendCancel = function() {
  if (_simWs && _simWs.readyState === 1) {
    try {
      _simWs.send(JSON.stringify({action: 'cancel'}));
    } catch(e) {}
  }
};

// -- Update simulation server connection UI --
function _updateSimConnectionUI(connected) {
  var led = document.getElementById('simConnLed');
  var txt = document.getElementById('simConnText');
  if (led) {
    led.style.background = connected ? 'var(--gn)' : '#555';
    led.style.boxShadow = connected ? '0 0 6px var(--gn)' : 'none';
  }
  if (txt) {
    txt.textContent = connected ? 'Sim server (port ' + SIM_WS_PORT + ')' : 'Sim offline';
  }
}


// ======================================================================
//  Common Experiment WebSocket Client (/ws/expt)
// ======================================================================

var _exptWs = null;
var _exptWsConnected = false;
var _exptWsReconnectTimer = null;

// ── Build beamline context from current MC state ──
// Called at experiment start to package beamline parameters for the server.
// Order matters: focalSpot() FIRST so the MC cache is fresh, THEN read the
// sample-plane flux via sampleFlux() — the single API used by every
// sample-flux display (modal, motor jog, Expt beamline bar, attenuator,
// detector simulators, IC1 sim). Do not inline a different flux calculator
// here; one API keeps every surfaced number identical.
function _buildBeamlineContext() {
  var eKev = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  // 1) focalSpot triggers MC re-run if cache is dirty (slit/optics changed)
  var sp = {h: 50, v: 50};
  try { if (typeof focalSpot === 'function') sp = focalSpot(); } catch(e) {}
  // 2) Sample-plane flux: single API (sampleFlux) shared by every display.
  var fl = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
  if (!fl) fl = 1e10;
  var ssaH = (typeof state !== 'undefined' && state.ssaH) ? state.ssaH : 50;
  var ssaV = (typeof state !== 'undefined' && state.ssaV) ? state.ssaV : 50;
  console.log('[Beamline] context: E=' + eKev.toFixed(3) + 'keV, flux=' +
    fl.toExponential(2) + ', spot=' + sp.h.toFixed(0) + 'x' + sp.v.toFixed(0) +
    'nm, SSA=' + ssaH + 'x' + ssaV + 'um');
  return {
    energy_keV: eKev,
    spot_h_nm: sp.h,
    spot_v_nm: sp.v,
    flux: fl,
    ssaH: ssaH,
    ssaV: ssaV
  };
}

// ── Connect to experiment server ──
window.exptServerConnect = function(url) {
  if (!url) {
    url = 'ws://' + (location.hostname || 'localhost') + ':8001/ws/expt';
  }
  if (_exptWs && _exptWs.readyState <= 1) return;

  try {
    _exptWs = new WebSocket(url);
  } catch(e) {
    _exptWsConnected = false;
    _updateExptConnectionUI(false);
    return;
  }

  _exptWs.onopen = function() {
    _exptWsConnected = true;
    _updateExptConnectionUI(true);
    console.log('[Expt] Connected: ' + url);
    // Request available modes
    try {
      _exptWs.send(JSON.stringify({action: 'list_modes'}));
    } catch(e2) {}
  };

  _exptWs.onclose = function() {
    _exptWsConnected = false;
    _updateExptConnectionUI(false);
    console.log('[Expt] Disconnected');
    // Auto-reconnect after 5s
    clearTimeout(_exptWsReconnectTimer);
    _exptWsReconnectTimer = setTimeout(function() {
      exptServerConnect(url);
    }, 5000);
  };

  _exptWs.onerror = function() {
    _exptWsConnected = false;
    _updateExptConnectionUI(false);
  };

  _exptWs.onmessage = function(ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch(err) { return; }
    try { _handleExptServerMessage(msg); } catch(err) {
      console.error('[Expt] message handler error:', err);
    }
  };
};

// ── Disconnect ──
window.exptServerDisconnect = function() {
  clearTimeout(_exptWsReconnectTimer);
  _exptWsReconnectTimer = null;
  if (_exptWs) {
    _exptWs.onclose = null;
    _exptWs.close();
    _exptWs = null;
  }
  _exptWsConnected = false;
  _updateExptConnectionUI(false);
};

// ── Send experiment run request ──
window._exptSendRun = function(mode, params) {
  if (!_exptWs || _exptWs.readyState !== 1) return false;
  var msg = {
    action: 'run',
    mode: mode,
    params: params
  };
  // Attach beamline context
  msg.params.beamline = _buildBeamlineContext();
  try {
    _exptWs.send(JSON.stringify(msg));
    return true;
  } catch(e) {
    console.error('[Expt] send error:', e);
    return false;
  }
};

// ── Cancel running experiment ──
window._exptSendCancel = function() {
  if (_exptWs && _exptWs.readyState === 1) {
    try {
      _exptWs.send(JSON.stringify({action: 'cancel'}));
    } catch(e) {}
  }
};

// ── Meas scan routing flag ──
// When true, server messages are routed to Meas tab handlers instead of Expt popup
var _measScanActive = false;
var _measScanTechnique = '';

// ── Handle server messages ──
function _handleExptServerMessage(msg) {
  // Route to Bluesky Queue if queue sim is active
  if (typeof _queueSimActive !== 'undefined' && _queueSimActive && typeof _handleQueueSimResponse === 'function') {
    _handleQueueSimResponse(msg);
    return;
  }
  // Route to Meas tab if Meas scan is active
  if (_measScanActive && typeof _handleMeasServerMessage === 'function') {
    _handleMeasServerMessage(msg);
    return;
  }

  var type = msg.type;

  if (type === 'expt_progress') {
    _updateExptProgress(msg.fraction || 0, msg.msg || '');
  } else if (type === 'expt_data') {
    // Streaming data batch (XAFS)
    if (msg.mode === 'xafs' && msg.batch) {
      _handleExptXAFSBatch(msg);
    }
  } else if (type === 'expt_result') {
    // IC measurement mode: keep the chamber-current summary for the
    // completion line (expt_done arrives right after and owns the text).
    _exptState._lastIC = (msg.ic && msg.ic.i0_A_range) ? msg.ic : null;
    if (_exptState._lastIC) {
      try {
        console.log('[Expt] IC chain: I0=' + msg.ic.i0_A_range[1].toExponential(2) +
          ' A, I1=' + msg.ic.i1_A_range[1].toExponential(2) +
          ' A, dwell=' + msg.ic.dwell_s + ' s, ratio_prefocus=' +
          msg.ic.ratio_prefocus);
      } catch (e) {}
    }
    _handleExptResult(msg);
  } else if (type === 'expt_done') {
    _exptState.running = false;
    var elapsed = msg.elapsed_sec || 0;
    if (elapsed > 0) {
      var _icNote = '';
      if (_exptState._lastIC) {
        try {
          _icNote = ' | IC I0 ' + (_exptState._lastIC.i0_A_range[1] * 1e6).toFixed(2) +
            ' uA / I1 ' + (_exptState._lastIC.i1_A_range[1] * 1e6).toFixed(2) + ' uA';
        } catch (e) { _icNote = ''; }
        _exptState._lastIC = null;
      }
      _updateExptProgress(1, 'Complete (' + elapsed.toFixed(2) + 's, server)' + _icNote);
    }
    // Notify waiters immediately (no polling needed)
    if (typeof _exptState._onDone === 'function') {
      _exptState._onDone({ success: true });
      _exptState._onDone = null;
    }
  } else if (type === 'expt_error') {
    _exptState.running = false;
    _updateExptProgress(0, 'Error: ' + (msg.message || 'unknown'));
    if (typeof _exptState._onDone === 'function') {
      _exptState._onDone({ success: false, error: msg.message });
      _exptState._onDone = null;
    }
  } else if (type === 'expt_modes') {
    console.log('[Expt] Server modes:', msg.modes);
  } else if (type === 'expt_cancelled') {
    _exptState.running = false;
    _updateExptProgress(0, 'Cancelled');
    if (typeof _exptState._onDone === 'function') {
      _exptState._onDone({ success: false, cancelled: true });
      _exptState._onDone = null;
    }
  }
}

// ── XAFS streaming batch handler ──
var _exptServerXAFSData = [];
// Appends a streamed batch of XAFS points to _exptServerXAFSData, updates progress, and live-redraws the mu(E) vs E-E0 chart.
function _handleExptXAFSBatch(msg) {
  var batch = msg.batch;
  for (var i = 0; i < batch.length; i++) {
    _exptServerXAFSData.push(batch[i]);
  }
  _updateExptProgress(msg.progress || 0,
    'XAFS: ' + _exptServerXAFSData.length + ' points (server)');

  // Live chart update
  var cvs = document.getElementById('exptPopup_xafs_canvas');
  if (cvs && _exptServerXAFSData.length > 2) {
    var par = cvs.parentNode;
    var pw = par ? par.clientWidth : 0;
    var ph = par ? par.clientHeight : 0;
    if (pw < 10 || ph < 10) return;  // layout not ready yet
    var p = _exptState.xafs;
    _drawChart1D(cvs, _exptServerXAFSData, {
      title: p.absorber + ' ' + p.edge + '-edge (' + p.formula + ') [server]',
      xlabel: 'E - E0 (eV)', ylabel: 'µ(E)', color: '#4db8ff',
      width: pw, height: ph, useCanvas: true
    });
  }
}

// ── Canvas retry: ensure canvas has FINAL layout dimensions before rendering ──
// Fixes white-screen bug: canvas.width assignment clears the pixel buffer (HTML5 spec).
// If we render on the default 300x150 canvas, _initCanvasSize will later clear it
// by setting canvas.width = clientWidth. So we wait until clientWidth is ready,
// then sync buffer and render in one atomic step.
function _ensureCanvasAndRender(canvasId, mode, renderFn, maxRetries) {
  maxRetries = (maxRetries != null) ? maxRetries : 15;
  var c = document.getElementById(canvasId);
  if (!c) return;

  var cw = c.clientWidth, ch = c.clientHeight;

  // Wait until flex layout has computed (clientWidth > 10)
  if (cw < 10 || ch < 10) {
    // Try parent as fallback
    var par = c.parentNode;
    if (par && par.clientWidth > 10 && par.clientHeight > 10) {
      cw = par.clientWidth;
      ch = par.clientHeight;
    }
  }

  // Only render when layout is ready — sync buffer + render atomically
  if (cw > 10 && ch > 10) {
    c.width = cw;
    c.height = ch;
    try { renderFn(c); } catch(e) {
      console.warn('[Expt] render error (' + mode + '):', e);
    }
    return;
  }

  // Retry — layout not ready yet
  if (maxRetries > 0) {
    setTimeout(function() {
      _ensureCanvasAndRender(canvasId, mode, renderFn, maxRetries - 1);
    }, 50);
  } else {
    console.warn('[Expt] canvas still not ready after retries (' + mode + ')');
  }
}

// ── XRF result advisory (deterministic; posts to NLP chat) ──
// Reports the actual measured (excited) elements vs. those that could NOT be
// excited at the current incident energy, the experiment conditions, and a
// text suggestion to raise the energy. Physics, not LLM: an element fluoresces
// only when E_incident exceeds its absorption edge.
function _xrfBuildAdvisory(msg) {
  if (typeof XRAY_ELEMENTS === 'undefined') return '';
  var info = msg.info || {};
  var measured = msg.elements || [];
  var energy_keV = info.energy_keV ||
    ((typeof state !== 'undefined' && state.energy) ? state.energy : 0) || 0;
  if (energy_keV <= 0) return '';
  var energy_eV = energy_keV * 1000;
  var E_MAX_keV = 25.0;  // beamline max (matches server BEAMLINE_E_MAX)

  // Sample name + full candidate element list (preset preferred, else formula)
  var xf = (typeof _exptState !== 'undefined' && _exptState.xrf2d) ? _exptState.xrf2d : {};
  var presetKey = xf.presetKey || '';
  var sampleName = presetKey;
  var candidates = [];
  if (presetKey && typeof XRF_SAMPLE_PRESETS !== 'undefined' && XRF_SAMPLE_PRESETS[presetKey]) {
    var preset = XRF_SAMPLE_PRESETS[presetKey];
    sampleName = preset.name || presetKey;
    if (preset.elements) candidates = Object.keys(preset.elements);
  }
  if (!candidates.length && info.formula && typeof parseFormula === 'function') {
    try { candidates = Object.keys(parseFormula(info.formula)); } catch (e) {}
  }
  if (!candidates.length) candidates = measured.slice();

  // Lowest absorption edge within beamline range for an element (eV), or null
  function _lowestReachableEdge(sym) {
    var el = XRAY_ELEMENTS[sym];
    if (!el) return null;
    var best = null;
    var edges = [['K', el.K], ['L3', el.L3]];
    for (var i = 0; i < edges.length; i++) {
      var name = edges[i][0], e = edges[i][1];
      if (e && e <= E_MAX_keV * 1000) {
        if (best === null || e < best.e) best = { edge: name, e: e };
      }
    }
    return best;
  }

  // Edge actually excited at this energy (for the "measured" list labels)
  function _excitedEdgeLabel(sym) {
    var el = XRAY_ELEMENTS[sym];
    if (!el) return '';
    if (el.K && energy_eV > el.K) return 'K ' + (el.K / 1000).toFixed(2) + ' keV';
    if (el.L3 && energy_eV > el.L3) return 'L3 ' + (el.L3 / 1000).toFixed(2) + ' keV';
    return '';
  }

  // Partition: missing = in sample, not in measured, and its lowest reachable
  // edge is above the current energy (i.e. could be captured by raising E).
  var measuredSet = {};
  for (var m = 0; m < measured.length; m++) measuredSet[measured[m]] = true;
  var missing = [];     // {sym, edge, e_keV}
  var unreachable = []; // sym (no edge within beamline range at all)
  for (var c = 0; c < candidates.length; c++) {
    var sym = candidates[c];
    if (measuredSet[sym]) continue;
    var le = _lowestReachableEdge(sym);
    if (le === null) { unreachable.push(sym); continue; }
    if (le.e > energy_eV) missing.push({ sym: sym, edge: le.edge, e_keV: le.e / 1000 });
  }

  var isKo = (typeof UI_LANG !== 'undefined' && UI_LANG === 'ko');

  // Conditions line
  var Lx = (xf.scanLx != null) ? xf.scanLx : 0;
  var Ly = (xf.scanLy != null) ? xf.scanLy : Lx;
  var nx = info.nx || 0, ny = info.ny || 0;
  var step = info.step_um || 0;

  var measLabels = [];
  for (var k = 0; k < measured.length; k++) {
    var lab = _excitedEdgeLabel(measured[k]);
    measLabels.push(measured[k] + (lab ? ' (' + lab + ')' : ''));
  }

  // Recommended energy: cover the highest-edge missing element (+0.5 keV margin)
  var recE = 0, recSym = '';
  for (var g = 0; g < missing.length; g++) {
    if (missing[g].e_keV > recE) { recE = missing[g].e_keV; recSym = missing[g].sym; }
  }
  var recTarget = recE > 0 ? Math.min(E_MAX_keV, recE + 0.5) : 0;

  var lines = [];
  if (isKo) {
    lines.push('XRF 2D 매핑 완료 — ' + sampleName);
    lines.push('조건: FOV ' + Lx + '×' + Ly + ' µm, ' + nx + '×' + ny + ' pts, step ' +
               step + ' µm, E=' + energy_keV.toFixed(2) + ' keV, KB 나노빔(~50 nm)');
    lines.push('측정된 원소(여기됨): ' + (measLabels.length ? measLabels.join(', ') : '없음'));
    if (missing.length) {
      var mtxt = [];
      for (var i2 = 0; i2 < missing.length; i2++) {
        mtxt.push(missing[i2].sym + ' (' + missing[i2].edge + ' ' +
                  missing[i2].e_keV.toFixed(2) + ' keV)');
      }
      lines.push('현재 에너지(' + energy_keV.toFixed(2) +
                 ' keV)에서 여기되지 않은 원소: ' + mtxt.join(', '));
      lines.push('이 시료의 주성분 ' + recSym + '를 매핑하려면 입사 에너지를 ' +
                 recE.toFixed(2) + ' keV 위로 올려야 합니다.');
      lines.push('원하시면 "' + recTarget.toFixed(1) +
                 ' keV로 재스캔"이라고 말씀해 주세요. 에너지를 변경하고 정렬 후 다시 측정하겠습니다.');
    }
    if (unreachable.length) {
      lines.push('빔라인 범위(5–25 keV) 내 흡수단이 없어 측정 불가: ' + unreachable.join(', '));
    }
  } else {
    lines.push('XRF 2D map complete — ' + sampleName);
    lines.push('Conditions: FOV ' + Lx + '×' + Ly + ' µm, ' + nx + '×' + ny + ' pts, step ' +
               step + ' µm, E=' + energy_keV.toFixed(2) + ' keV, KB nanobeam (~50 nm)');
    lines.push('Measured (excited): ' + (measLabels.length ? measLabels.join(', ') : 'none'));
    if (missing.length) {
      var mtxt2 = [];
      for (var i3 = 0; i3 < missing.length; i3++) {
        mtxt2.push(missing[i3].sym + ' (' + missing[i3].edge + ' ' +
                   missing[i3].e_keV.toFixed(2) + ' keV)');
      }
      lines.push('Not excited at ' + energy_keV.toFixed(2) + ' keV: ' + mtxt2.join(', '));
      lines.push('To map this sample’s main element ' + recSym +
                 ', the incident energy must exceed ' + recE.toFixed(2) + ' keV.');
      lines.push('If you’d like, say "rescan at ' + recTarget.toFixed(1) +
                 ' keV" and I’ll change the energy, re-align, and measure again.');
    }
    if (unreachable.length) {
      lines.push('No absorption edge within the beamline range (5–25 keV), cannot measure: ' +
                 unreachable.join(', '));
    }
  }
  return lines.join('\n');
}

// ── Result handler ──
function _handleExptResult(msg) {
  var mode = msg.mode;

  if (mode === 'xafs') {
    var data = msg.data || _exptServerXAFSData;
    var info = msg.info || {};
    var p = _exptState.xafs;

    // Final chart render (with retry for headless/fast-popup timing)
    var _xafsRenderFn = function(c) {
      _drawChart1D(c, data, {
        title: p.absorber + ' ' + p.edge + '-edge (' + p.formula + ') [' + (info.engine || 'server') + ']',
        xlabel: 'E - E0 (eV)', ylabel: 'µ(E)', color: '#4db8ff',
        useCanvas: true
      });
    };
    if (data.length > 0) {
      _ensureCanvasAndRender('exptPopup_xafs_canvas', 'xafs', _xafsRenderFn, 10);
    }
    // Re-render registration
    _registerExptRenderer('xafs', _xafsRenderFn);
    // Tooltip
    if (typeof _attachChartTooltip === 'function') {
      _attachChartTooltip('exptPopup_xafs_canvas', data, 'E - E0 (eV)', 'µ(E)', info.E0_eV || 0);
    }
    // Info line
    var infoEl = document.getElementById('exptPopup_xafs_info');
    if (infoEl) {
      infoEl.textContent = 'XAFS [' + (info.engine || 'server') + ']: ' +
        p.formula + ' ' + p.absorber + ' ' + p.edge + '-edge, E0=' +
        (info.E0_eV || 0) + ' eV, ' + (info.n_points || data.length) + ' points';
    }
  }
  else if (mode === 'xrd2d') {
    // Decode base64 Float32 image -> renderXRD2D
    var info3 = msg.info || {};
    if (msg.image_b64) {
      var binStr = atob(msg.image_b64);
      var bytes = new Uint8Array(binStr.length);
      for (var bi = 0; bi < binStr.length; bi++) bytes[bi] = binStr.charCodeAt(bi);
      var imgArr = new Float32Array(bytes.buffer);
      var xrdRings = msg.rings || [];
      var xrdResult = {
        data: imgArr,
        width: msg.width || 1024,
        height: msg.height || 1024,
        rings: xrdRings
      };
      // Build 1D pattern data from rings for chart display
      var xrd1dData = [];
      if (xrdRings.length > 0) {
        // Generate broadened peaks
        var tthMin = 0, tthMax = 90, nPts = 900;
        for (var ti = 0; ti < nPts; ti++) {
          var tth = tthMin + (tthMax - tthMin) * ti / (nPts - 1);
          var yVal = 0;
          for (var ri = 0; ri < xrdRings.length; ri++) {
            var pk = xrdRings[ri];
            var dt = tth - pk.twoTheta;
            var sig = (pk.fwhm || 0.15) / 2.355;
            yVal += (pk.I || 0) * Math.exp(-0.5 * dt * dt / (sig * sig));
          }
          xrd1dData.push({x: tth, y: yVal});
        }
      }
      // Render: 2D image (top) + 1D pattern (bottom)
      var _renderXrd2d = function(c) {
        var cw6 = c.width, ch6 = c.height;
        var ctx6 = c.getContext('2d');
        ctx6.fillStyle = '#1a1d23'; ctx6.fillRect(0, 0, cw6, ch6);
        var patH = Math.min(120, Math.floor(ch6 * 0.22));
        var imgH = ch6 - patH;
        // 2D detector image on temp canvas, then draw to top region
        if (typeof renderXRD2D === 'function') {
          var tmpCvs = document.createElement('canvas');
          tmpCvs.width = cw6; tmpCvs.height = imgH;
          renderXRD2D(tmpCvs, xrdResult, {logScale: true, showLabels: true});
          ctx6.drawImage(tmpCvs, 0, 0);
        }
        // 1D diffraction pattern at bottom
        if (xrd1dData.length > 0 && typeof _drawChart1D === 'function') {
          var patCvs = document.createElement('canvas');
          patCvs.width = cw6; patCvs.height = patH;
          _drawChart1D(patCvs, xrd1dData, {
            title: 'XRD Pattern', xlabel: '2-theta (deg)', ylabel: 'Intensity',
            color: '#4db8ff', width: cw6, height: patH
          });
          ctx6.drawImage(patCvs, 0, imgH);
        }
      };
      _ensureCanvasAndRender('exptPopup_xrd2d_canvas', 'xrd2d', _renderXrd2d, 10);
      _registerExptRenderer('xrd2d', _renderXrd2d);
    }
    var infoEl3 = document.getElementById('exptPopup_xrd2d_info');
    if (infoEl3) {
      infoEl3.textContent = '2D XRD [' + (info3.engine || 'server') + ']: ' +
        (info3.crystal || '') + ' | ' + (info3.n_rings || 0) + ' rings' +
        ' | d=' + (info3.detDist_m || 0) + 'm | E=' + (info3.energy_keV || 0).toFixed(1) + 'keV';
    }
  }
  else if (mode === 'xrf2d') {
    // Render XRF element maps + spectrum
    var cvs4 = document.getElementById('exptPopup_xrf2d_canvas');
    var info4 = msg.info || {};
    var elements = msg.elements || [];
    var maps = msg.maps || {};
    // Build specData from spectrum channels (outside renderer so it's available for both)
    var specData = [];
    if (msg.spectrum && msg.spectrum.channels) {
      var chs = msg.spectrum.channels;
      var ePerCh = msg.spectrum.ePerCh || 10;
      for (var si = 0; si < chs.length; si++) {
        specData.push({x: si * ePerCh / 1000, y: chs[si]});
      }
    }
    var nEl = elements.length;
    var cols = Math.min(nEl, 3);
    var rows = Math.ceil(nEl / cols);

    if (nEl > 0 && typeof _drawHeatmap2D === 'function') {
      var _renderXrf2d = function(c) {
        var cw = c.width, ch = c.height;
        var ctx = c.getContext('2d');
        ctx.fillStyle = '#1a1d23'; ctx.fillRect(0, 0, cw, ch);
        var specH = 120;
        var mapH = ch - specH;
        var pW = Math.floor(cw / cols);
        var pH = Math.floor(mapH / rows);
        for (var ei = 0; ei < nEl; ei++) {
          var mapArr = maps[elements[ei]];
          if (!mapArr) continue;
          _drawHeatmap2D(c, mapArr, {
            title: elements[ei], colormap: 'hot',
            region: {x: (ei % cols) * pW, y: Math.floor(ei / cols) * pH, w: pW, h: pH}
          });
        }
        if (specData.length > 0 && typeof _drawChart1D === 'function') {
          var sCvs = document.createElement('canvas');
          sCvs.width = cw; sCvs.height = specH;
          _drawChart1D(sCvs, specData, {
            title: 'XRF Spectrum', xlabel: 'Energy (keV)', ylabel: 'Counts',
            color: '#40d89a', width: cw, height: specH
          });
          ctx.drawImage(sCvs, 0, mapH);
        }
      };
      _ensureCanvasAndRender('exptPopup_xrf2d_canvas', 'xrf2d', _renderXrf2d, 10);
      _registerExptRenderer('xrf2d', _renderXrf2d);
    }
    var infoEl4 = document.getElementById('exptPopup_xrf2d_info');
    if (infoEl4) {
      infoEl4.textContent = '2D XRF [' + (info4.engine || 'server') + ']: ' +
        (info4.formula || '') + ' | ' + elements.join(', ') +
        ' | ' + (info4.nx || 0) + 'x' + (info4.ny || 0) + ' pts' +
        ' | step=' + (info4.step_um || 0) + '\u03bcm | E=' + (info4.energy_keV || 0).toFixed(1) + 'keV';
    }
    // Post deterministic advisory to NLP chat (one-shot; set by quickRaster).
    if (typeof _exptState !== 'undefined' && _exptState._chatAdvisory &&
        typeof addChatMessage === 'function') {
      _exptState._chatAdvisory = false;
      try {
        var _adv = _xrfBuildAdvisory(msg);
        if (_adv) addChatMessage('assistant', _adv);
      } catch (e) { console.warn('[XRF advisory]', e); }
    }
  }
  else if (mode === 'xrdmap') {
    // Render phase map + XRD patterns
    var cvs5 = document.getElementById('exptPopup_xrdmap_canvas');
    var info5 = msg.info || {};
    var phaseMap = msg.phase_map;
    if (phaseMap && typeof _drawHeatmap2D === 'function') {
      // Build pattern data outside renderer
      var p1Data = [], p2Data = [];
      if (msg.pattern1 && typeof _drawChart1D === 'function') {
        var p1 = msg.pattern1;
        var p1Y = p1.intensity || p1.ints || [];
        if (p1.tth && p1Y.length > 0) {
          for (var pi = 0; pi < p1.tth.length; pi++) {
            p1Data.push({x: p1.tth[pi], y: p1Y[pi] || 0});
          }
        }
        if (msg.pattern2 && info5.cryst2) {
          var p2 = msg.pattern2;
          var p2Y = p2.intensity || p2.ints || [];
          if (p2.tth && p2Y.length > 0) {
            for (var pi2 = 0; pi2 < p2.tth.length; pi2++) {
              p2Data.push({x: p2.tth[pi2], y: p2Y[pi2] || 0});
            }
          }
        }
      }
      var _renderXrdMap = function(c) {
        var cw = c.width, ch = c.height;
        var halfW = Math.floor(cw * 0.5);
        _drawHeatmap2D(c, phaseMap, {
          title: (info5.cryst1 || '') + ' / ' + (info5.cryst2 || ''),
          colormap: 'viridis',
          region: {x: 0, y: 0, w: halfW, h: ch}
        });
        if (p1Data.length > 0 && typeof _drawChart1D === 'function') {
          var pCvs = document.createElement('canvas');
          pCvs.width = cw - halfW; pCvs.height = Math.floor(ch / 2);
          _drawChart1D(pCvs, p1Data, {title: info5.cryst1 || 'Phase 1', xlabel: '2theta (deg)', ylabel: 'I', color: '#4db8ff'});
          c.getContext('2d').drawImage(pCvs, halfW, 0);
        }
        if (p2Data.length > 0 && typeof _drawChart1D === 'function') {
          var p2Cvs = document.createElement('canvas');
          p2Cvs.width = cw - halfW; p2Cvs.height = ch - Math.floor(ch / 2);
          _drawChart1D(p2Cvs, p2Data, {title: info5.cryst2 || 'Phase 2', xlabel: '2theta (deg)', ylabel: 'I', color: '#ffb340'});
          c.getContext('2d').drawImage(p2Cvs, halfW, Math.floor(ch / 2));
        }
      };
      _ensureCanvasAndRender('exptPopup_xrdmap_canvas', 'xrdmap', _renderXrdMap, 10);
      _registerExptRenderer('xrdmap', _renderXrdMap);
    }
    var infoEl5 = document.getElementById('exptPopup_xrdmap_info');
    if (infoEl5) {
      infoEl5.textContent = 'XRD Map [' + (info5.engine || 'server') + ']: ' +
        (info5.cryst1 || '') + (info5.cryst2 ? ' + ' + info5.cryst2 : '') +
        ' | ' + (info5.nx || 0) + 'x' + (info5.ny || 0) + ' pts' +
        ' | E=' + (info5.energy_keV || 0).toFixed(1) + 'keV';
    }
  }
  else {
    console.log('[Expt] Server result for ' + mode + ':', Object.keys(msg));
  }
}

// ── Update connection UI (LED + text) ──
function _updateExptConnectionUI(connected) {
  var led = document.getElementById('exptConnLed');
  var txt = document.getElementById('exptConnText');
  if (led) {
    led.style.background = connected ? 'var(--gn)' : '#e05050';
    led.style.boxShadow = '0 0 6px ' + (connected ? 'var(--gn)' : '#e05050');
  }
  if (txt) {
    txt.textContent = connected ? 'Server connected' : 'Offline';
  }
}

// ── Auto-connect to simulation server on page load ──
// Delay slightly so DOM/URL params are fully parsed
setTimeout(function() {
  try { simServerConnect(); } catch(e) {}
}, 1500);

// ESM bridge: expose module-scoped vars to globalThis
if(typeof SIM_WS_PORT!=="undefined")globalThis.SIM_WS_PORT=SIM_WS_PORT;
if(typeof _absorberOptions!=="undefined")globalThis._absorberOptions=_absorberOptions;
if(typeof _btnSmallSty!=="undefined")globalThis._btnSmallSty=_btnSmallSty;
if(typeof _buildBeamlineContext!=="undefined")globalThis._buildBeamlineContext=_buildBeamlineContext;
if(typeof _buildExptControls!=="undefined")globalThis._buildExptControls=_buildExptControls;
if(typeof _buildPtychoControls!=="undefined")globalThis._buildPtychoControls=_buildPtychoControls;
if(typeof _crystalOptions!=="undefined")globalThis._crystalOptions=_crystalOptions;
if(typeof _ensureCanvasAndRender!=="undefined")globalThis._ensureCanvasAndRender=_ensureCanvasAndRender;
if(typeof _exptBeamlineCache!=="undefined")globalThis._exptBeamlineCache=_exptBeamlineCache;
if(typeof _exptPopupRenderers!=="undefined")globalThis._exptPopupRenderers=_exptPopupRenderers;
if(typeof _exptSendCancel!=="undefined")globalThis._exptSendCancel=_exptSendCancel;
if(typeof _exptSendRun!=="undefined")globalThis._exptSendRun=_exptSendRun;
if(typeof _exptServerXAFSData!=="undefined")globalThis._exptServerXAFSData=_exptServerXAFSData;
if(typeof _exptState!=="undefined")globalThis._exptState=_exptState;
if(typeof _exptWs!=="undefined")globalThis._exptWs=_exptWs;
if(typeof _exptWsConnected!=="undefined")globalThis._exptWsConnected=_exptWsConnected;
if(typeof _exptWsReconnectTimer!=="undefined")globalThis._exptWsReconnectTimer=_exptWsReconnectTimer;
if(typeof _exptXafsFormulaChanged!=="undefined")globalThis._exptXafsFormulaChanged=_exptXafsFormulaChanged;
if(typeof _handleExptResult!=="undefined")globalThis._handleExptResult=_handleExptResult;
if(typeof _handleExptServerMessage!=="undefined")globalThis._handleExptServerMessage=_handleExptServerMessage;
if(typeof _handleExptXAFSBatch!=="undefined")globalThis._handleExptXAFSBatch=_handleExptXAFSBatch;
if(typeof _inputSty!=="undefined")globalThis._inputSty=_inputSty;
if(typeof _measScanActive!=="undefined")globalThis._measScanActive=_measScanActive;
if(typeof _measScanTechnique!=="undefined")globalThis._measScanTechnique=_measScanTechnique;
if(typeof _openExptPopup!=="undefined")globalThis._openExptPopup=_openExptPopup;
if(typeof _readExptParams!=="undefined")globalThis._readExptParams=_readExptParams;
if(typeof _readPtychoParams!=="undefined")globalThis._readPtychoParams=_readPtychoParams;
if(typeof _refreshExptModeInfo!=="undefined")globalThis._refreshExptModeInfo=_refreshExptModeInfo;
if(typeof _refreshPtychoCoherence!=="undefined")globalThis._refreshPtychoCoherence=_refreshPtychoCoherence;
if(typeof _registerExptRenderer!=="undefined")globalThis._registerExptRenderer=_registerExptRenderer;
if(typeof _renderPtychoCoherenceBlock!=="undefined")globalThis._renderPtychoCoherenceBlock=_renderPtychoCoherenceBlock;
if(typeof _reopenExptPopup!=="undefined")globalThis._reopenExptPopup=_reopenExptPopup;
if(typeof _row!=="undefined")globalThis._row=_row;
if(typeof _savePtychoResult!=="undefined")globalThis._savePtychoResult=_savePtychoResult;
if(typeof _selectSty!=="undefined")globalThis._selectSty=_selectSty;
if(typeof _simAutoPort!=="undefined")globalThis._simAutoPort=_simAutoPort;
if(typeof _simFallbackToLocal!=="undefined")globalThis._simFallbackToLocal=_simFallbackToLocal;
if(typeof _simSendCancel!=="undefined")globalThis._simSendCancel=_simSendCancel;
if(typeof _simSendRun!=="undefined")globalThis._simSendRun=_simSendRun;
if(typeof _simWs!=="undefined")globalThis._simWs=_simWs;
if(typeof _simWsConnected!=="undefined")globalThis._simWsConnected=_simWsConnected;
if(typeof _simWsReconnectTimer!=="undefined")globalThis._simWsReconnectTimer=_simWsReconnectTimer;
if(typeof _updateExptBeamlineStatus!=="undefined")globalThis._updateExptBeamlineStatus=_updateExptBeamlineStatus;
if(typeof _updateExptConnectionUI!=="undefined")globalThis._updateExptConnectionUI=_updateExptConnectionUI;
if(typeof _updateExptProgress!=="undefined")globalThis._updateExptProgress=_updateExptProgress;
if(typeof _updatePtychoDwellEstimate!=="undefined")globalThis._updatePtychoDwellEstimate=_updatePtychoDwellEstimate;
if(typeof _updatePtychoQualityCheck!=="undefined")globalThis._updatePtychoQualityCheck=_updatePtychoQualityCheck;
if(typeof _updatePtychoScanEstimate!=="undefined")globalThis._updatePtychoScanEstimate=_updatePtychoScanEstimate;
if(typeof _updateSimConnectionUI!=="undefined")globalThis._updateSimConnectionUI=_updateSimConnectionUI;
if(typeof _updateXafsEdgeInfo!=="undefined")globalThis._updateXafsEdgeInfo=_updateXafsEdgeInfo;
if(typeof _xrd2dPresetChanged!=="undefined")globalThis._xrd2dPresetChanged=_xrd2dPresetChanged;
if(typeof _xrf2dPresetChanged!=="undefined")globalThis._xrf2dPresetChanged=_xrf2dPresetChanged;
if(typeof exptServerConnect!=="undefined")globalThis.exptServerConnect=exptServerConnect;
if(typeof exptServerDisconnect!=="undefined")globalThis.exptServerDisconnect=exptServerDisconnect;
if(typeof renderExptTab!=="undefined")globalThis.renderExptTab=renderExptTab;
if(typeof simServerConnect!=="undefined")globalThis.simServerConnect=simServerConnect;
if(typeof simServerDisconnect!=="undefined")globalThis.simServerDisconnect=simServerDisconnect;
if(typeof switchExptMode!=="undefined")globalThis.switchExptMode=switchExptMode;
