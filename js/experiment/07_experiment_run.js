'use strict';
// ===== experiment/07_experiment_run.js — Experiment Execution Engine (popup-based) =====
// @module experiment/07_experiment_run
// @exports _COLORMAPS, _attachChartTooltip, _chartTooltipData, _drawHeatmap2D, _drawSpectrumChart, _drawXRDMapResult, _drawXRFMultiElResult, _drawXRFResult, _handleChartTooltip, _previewPtychoObject, _renderPtychoWithRetry, _runExptOnSimServer, _runPtychoExpt, _runPtychoServerMode, startExperiment, ...

// ── Render ptycho with retry (canvas may not have layout dimensions yet) ──
function _renderPtychoWithRetry(canvasId, info, maxRetries) {
  var cvs = document.getElementById(canvasId);
  if (!cvs) { console.warn('[Ptycho retry] Canvas not found: ' + canvasId); return; }
  // Ensure canvas buffer matches layout — only reassign if size actually changed
  // (canvas.width= ALWAYS clears buffer per HTML5 spec, so avoid unnecessary clears)
  if (cvs.clientWidth > 0 &&
      (cvs.width !== cvs.clientWidth || cvs.height !== cvs.clientHeight)) {
    cvs.width = cvs.clientWidth;
    cvs.height = cvs.clientHeight;
  }
  // Fallback: if canvas has no layout size, try parent dimensions
  if (cvs.width < 10 || cvs.height < 10) {
    var par = cvs.parentNode;
    if (par && par.clientWidth > 10 && par.clientHeight > 10) {
      cvs.width = par.clientWidth;
      cvs.height = par.clientHeight;
    }
  }
  if (cvs.width >= 10 && cvs.height >= 10) {
    console.log('[Ptycho render] canvas ' + cvs.width + 'x' + cvs.height +
      ', rawObj=' + !!_ptychoRawData.object + ', rawProbe=' + !!_ptychoRawData.probe);
    try {
      renderPtychoFromServer(cvs, info);
    } catch(e) {
      console.error('[Ptycho render] Error:', e);
    }
    return;
  }
  // Canvas not laid out yet — retry after a short delay
  if (maxRetries > 0) {
    setTimeout(function() { _renderPtychoWithRetry(canvasId, info, maxRetries - 1); }, 100);
  } else {
    console.warn('[Ptycho retry] Exhausted retries, canvas still not ready');
  }
}

// ── Start experiment ──
// @mode virtual: routes to simulation server (port 8002) for physics-based computation
// @mode real: will route to Bluesky RunEngine + real EPICS motors + real detectors
//   Switching point: check EPICS_STATE.mode — 'sim' uses _simSendRun, 'real' uses executeServerPlan
window.startExperiment = async function() {
  if (_exptState.running) return;
  _readExptParams();
  _exptState.running = true;
  _exptState.progress = 0;

  var mode = _exptState.mode;

  // Ptycho: dedicated K4GSR-PTYCHO server (port 8765)
  if (mode === 'ptycho') {
    _updateExptProgress(0, _tf('expt_starting_fmt', 'Ptychography'));
    _runPtychoExpt();
    return;
  }

  // All other modes: simulation server (port 8002) required
  if (typeof _simWsConnected !== 'undefined' && _simWsConnected) {
    _updateExptProgress(0, _tf('expt_starting_fmt', mode.toUpperCase()));

    // ── Resolve target energy for any mode that implies an element edge ──
    var _targetE_keV = 0;
    if (mode === 'xafs') {
      var _xafsP = _exptState.xafs || {};
      if (typeof XRAY_ELEMENTS !== 'undefined' && XRAY_ELEMENTS[_xafsP.absorber]) {
        var _e0 = XRAY_ELEMENTS[_xafsP.absorber][_xafsP.edge] || 0;
        if (_e0 > 0) _targetE_keV = _e0 / 1000;
      }
    } else if (mode === 'xrf2d') {
      // XRF needs energy above the highest element edge in formula
      var _xrfP = _exptState.xrf2d || {};
      if (_xrfP.presetKey && typeof XRF_SAMPLE_PRESETS !== 'undefined') {
        var _preset = XRF_SAMPLE_PRESETS[_xrfP.presetKey];
        if (_preset && _preset.elements && typeof XRAY_ELEMENTS !== 'undefined') {
          for (var _ei = 0; _ei < _preset.elements.length; _ei++) {
            var _elName = _preset.elements[_ei];
            var _elEdge = (XRAY_ELEMENTS[_elName] || {}).K || 0;
            if (_elEdge / 1000 > _targetE_keV) _targetE_keV = _elEdge / 1000;
          }
          // Add 0.5 keV margin above highest edge
          if (_targetE_keV > 0) _targetE_keV += 0.5;
        }
      }
    }

    // ── Set energy and auto-align if dE >= 1 keV ──
    if (_targetE_keV > 0) {
      var _prevE = state.energy || 10;
      if (typeof setTargetEnergy === 'function') setTargetEnergy(_targetE_keV);
      if (typeof updateLiveBeamInfo === 'function') try { updateLiveBeamInfo(); } catch(e) {}
      if (Math.abs(_targetE_keV - _prevE) >= 1.0 && typeof runFullAlignment === 'function') {
        window._alignFullAuto = true;
        _updateExptProgress(0, 'Aligning for ' + _targetE_keV.toFixed(3) + ' keV...');
        await runFullAlignment();
        _updateExptProgress(0, 'Alignment done. Starting experiment...');
      }
    }

    _runExptOnSimServer(mode);
    return;
  }

  // Simulation server not connected -- show error
  _exptState.running = false;
  _updateExptProgress(0, _t('expt_server_not_connected'));
};

// ── Run experiment on simulation server (port 8002) ──
function _runExptOnSimServer(mode) {
  var params = {};
  if (mode === 'xafs') {
    params = {
      formula: _exptState.xafs.formula,
      absorber: _exptState.xafs.absorber,
      edge: _exptState.xafs.edge,
      eStart: _exptState.xafs.eStart,
      eEnd: _exptState.xafs.eEnd,
      eStep: _exptState.xafs.eStep,
      ppm: _exptState.xafs.ppm,
      sampleType: _exptState.xafs.sampleType
    };
    if (typeof _exptServerXAFSData !== 'undefined') {
      _exptServerXAFSData.length = 0;
    }
    // Energy + alignment now handled in startExperiment() before this call
    var E0 = 0;
    if (typeof XRAY_ELEMENTS !== 'undefined' && XRAY_ELEMENTS[params.absorber]) {
      E0 = XRAY_ELEMENTS[params.absorber][params.edge] || 0;
    }

    // Beamline energy range check (K4GSR ID10: 5-30 keV)
    var _blWarning = '';
    var _E0_keV2 = E0 / 1000;
    if (E0 > 0 && _E0_keV2 < 5.0) {
      _blWarning = ' [OUTSIDE BEAMLINE RANGE: ' + _E0_keV2.toFixed(3) + ' keV < 5 keV]';
    } else if (E0 > 0 && (E0 + params.eEnd) / 1000 > 30.0) {
      _blWarning = ' [SCAN EXCEEDS 30 keV]';
    }
    _openExptPopup('xafs', 'XAFS: ' + params.formula + ' ' + params.absorber +
      ' ' + params.edge + '-edge (E0=' + E0 + ' eV)' + _blWarning, 700, 450);
  } else if (mode === 'xrd2d') {
    params = {
      crystal: _exptState.xrd2d.crystal,
      detDist: _exptState.xrd2d.detDist,
      detector: _exptState.xrd2d.detector
    };
    _openExptPopup('xrd2d', '2D XRD: ' + params.crystal, 600, 600);
  } else if (mode === 'xrf2d') {
    params = {
      formula: _exptState.xrf2d.formula,
      ppm: _exptState.xrf2d.ppm,
      scanLx: _exptState.xrf2d.scanLx,
      scanLy: _exptState.xrf2d.scanLy,
      step: _exptState.xrf2d.step,
      dwell: _exptState.xrf2d.dwell,
      sampleType: _exptState.xrf2d.sampleType,
      thickness_um: _exptState.xrf2d.thickness_um,
      matDensity: _exptState.xrf2d.matDensity,
      presetKey: _exptState.xrf2d.presetKey
    };
    _openExptPopup('xrf2d', '2D-XRF: ' + params.formula, 750, 600);
  } else if (mode === 'xrdmap') {
    params = {
      crystals: _exptState.xrdmap.crystals,
      scanLx: _exptState.xrdmap.scanLx,
      scanLy: _exptState.xrdmap.scanLy,
      step: _exptState.xrdmap.step,
      detDist: _exptState.xrdmap.detDist,
      detector: _exptState.xrdmap.detector
    };
    _openExptPopup('xrdmap', 'XRD Map: ' + params.crystals[0], 750, 600);
  }

  // Send to simulation server
  if (typeof _simSendRun === 'function') {
    return _simSendRun(mode, params);
  }
  return false;
}

// ── Stop experiment ──
window.stopExperiment = function() {
  _exptState.running = false;
  if (_exptState.timer) { clearTimeout(_exptState.timer); _exptState.timer = null; }
  // Cancel simulation server experiment if running
  if (typeof _simSendCancel === 'function') {
    try { _simSendCancel(); } catch(e) {}
  }
  // Cancel server reconstruction if running (Ptycho)
  if (typeof _ptychoRunning !== 'undefined' && _ptychoRunning) {
    try { ptychoCancelReconstruction(); } catch(e) {}
  }
  _updateExptProgress(_exptState.progress, 'Stopped');
};

// ── XRF Result: Multi-element heatmap tabs + Spectrum ──
function _drawXRFMultiElResult(cvs, allMapData, elList, activeEl, xP, yP,
                                formula, ppm, E_eV, flux, dwell, thickness_um, matDensity) {
  var ctx = cvs.getContext('2d');
  var W = cvs.width, H = cvs.height;
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, W, H);

  var splitX = Math.floor(W * 0.55);
  var tabH = 20;

  // Draw element tabs at top
  var tabW = Math.min(60, Math.floor(splitX / Math.max(1, elList.length)));
  for (var ti = 0; ti < elList.length; ti++) {
    var isActive = (elList[ti] === activeEl);
    ctx.fillStyle = isActive ? '#4db8ff' : '#2a2d35';
    ctx.fillRect(ti * tabW, 0, tabW - 1, tabH);
    ctx.fillStyle = isActive ? '#1a1d23' : '#a0a4ab';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(elList[ti], ti * tabW + tabW / 2, 14);
  }

  // Draw heatmap below tabs
  var mapData = allMapData[activeEl];
  if (mapData) {
    _drawHeatmap2D(cvs, mapData, {
      x: xP, y: yP, xLabel: 'X (\u03bcm)', yLabel: 'Y (\u03bcm)',
      title: 'XRF: ' + activeEl, colormap: 'hot',
      region: {x: 0, y: tabH, w: splitX, h: H - tabH}
    });
  }

  // Spectrum rendering removed — JS simXRFSpectrum deleted.
  // Server experiment engine provides spectrum data via expt_result message.
}

// Legacy wrapper for backward compatibility
function _drawXRFResult(cvs, mapData, xP, yP, formula, ppm, E_eV, flux, dwell, thickness_um, matDensity) {
  var allMaps = {};
  allMaps[formula] = mapData;
  _drawXRFMultiElResult(cvs, allMaps, [formula], formula, xP, yP, formula, ppm, E_eV, flux, dwell, thickness_um, matDensity);
}

// ── XRD Map Result: Phase map + representative pattern ──
function _drawXRDMapResult(cvs, phaseMap, intMap1, intMap2, xP, yP,
                            cryst1, cryst2, pattern1, pattern2, lambda, detDist, detKey) {
  var ctx = cvs.getContext('2d');
  var W = cvs.width, H = cvs.height;
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, W, H);

  // Layout: left = phase map (50%), right top = pattern1 (25%), right bottom = pattern2/info
  var splitX = Math.floor(W * 0.5);
  var halfH = Math.floor(H * 0.5);

  // Phase map
  _drawHeatmap2D(cvs, phaseMap, {
    x: xP, y: yP, xLabel: 'X (\u03bcm)', yLabel: 'Y (\u03bcm)',
    title: 'Phase Map: ' + cryst1 + (cryst2 ? '/' + cryst2 : ''),
    colormap: 'viridis',
    region: {x: 0, y: 0, w: splitX, h: H}
  });

  // Legend for phase map
  ctx.font = '8px monospace';
  ctx.fillStyle = '#40d89a';
  ctx.textAlign = 'left';
  ctx.fillText(cryst1 + ' (0)', 5, H - 10);
  if (cryst2) {
    ctx.fillStyle = '#ffb340';
    ctx.fillText(cryst2 + ' (1)', 5 + cryst1.length * 7 + 30, H - 10);
  }

  // Representative XRD pattern (phase 1) on right-top
  if (pattern1 && typeof renderXRD2D === 'function') {
    // Create a temporary offscreen canvas for the pattern
    var pCvs = document.createElement('canvas');
    var pW = W - splitX - 5;
    var pH = cryst2 ? halfH - 2 : H - 4;
    pCvs.width = pW;
    pCvs.height = pH;
    renderXRD2D(pCvs, pattern1, {logScale: true, showLabels: true});
    ctx.drawImage(pCvs, splitX + 5, 2, pW, pH);
    // Label
    ctx.font = '9px monospace';
    ctx.fillStyle = '#4db8ff';
    ctx.textAlign = 'center';
    ctx.fillText(cryst1 + ' pattern', splitX + 5 + pW / 2, 14);
  }

  // Representative XRD pattern (phase 2) on right-bottom
  if (cryst2 && pattern2 && typeof renderXRD2D === 'function') {
    var p2Cvs = document.createElement('canvas');
    var p2W = W - splitX - 5;
    var p2H = H - halfH - 4;
    p2Cvs.width = p2W;
    p2Cvs.height = p2H;
    renderXRD2D(p2Cvs, pattern2, {logScale: true, showLabels: true});
    ctx.drawImage(p2Cvs, splitX + 5, halfH + 2, p2W, p2H);
    ctx.font = '9px monospace';
    ctx.fillStyle = '#ffb340';
    ctx.textAlign = 'center';
    ctx.fillText(cryst2 + ' pattern', splitX + 5 + p2W / 2, halfH + 14);
  }
}

// ── Ptychography experiment (server or offline) ──
function _runPtychoExpt() {
  var pp = _exptState.ptycho;
  var energy_keV = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  // asize is set by user in UI (detector-dependent crop size: 128/256/512/1024)

  // Check if K4GSR-PTYCHO server is connected
  if (typeof _ptychoConnected !== 'undefined' && _ptychoConnected) {
    _runPtychoServerMode(pp, energy_keV);
  } else {
    // Auto-connect: use WebSocket onopen callback (no polling)
    _updateExptProgress(0.02, 'Ptycho: connecting to K4GSR-PTYCHO server...');
    var _connectTimeout = setTimeout(function() {
      window._ptychoOnConnect = null;
      _exptState.running = false;
      _updateExptProgress(0, 'K4GSR-PTYCHO server not available');
      var _wsUrl = (typeof PTYCHO_WS_URL !== 'undefined') ? PTYCHO_WS_URL : 'ws://localhost:8765';
      var infoEl = document.getElementById('exptInfo');
      if (infoEl) {
        infoEl.innerHTML = '<span style="color:#e05050">K4GSR-PTYCHO server (' + _wsUrl + ') not connected.</span><br>' +
          '<span style="color:var(--t2)">Start the server: <code>python server/ptycho_server.py</code> in K4GSR-PTYCHO project directory,<br>' +
          'or start the beamline server (<code>python server/server.py</code>) which auto-starts K4GSR-PTYCHO.</span>';
      }
    }, 3000);
    window._ptychoOnConnect = function() {
      clearTimeout(_connectTimeout);
      _runPtychoServerMode(pp, energy_keV);
    };
    if (typeof ptychoConnect === 'function') ptychoConnect();
  }
}

// ── Ptycho: Server mode (WebSocket to K4GSR-PTYCHO) ──
function _runPtychoServerMode(pp, energy_keV) {
  _updateExptProgress(0.05, 'Ptycho: connecting to K4GSR-PTYCHO server...');

  var popup = _openExptPopup('ptycho',
    'Ptychography: ' + pp.material + ' ' + pp.objheight_um + '\u03bcm @ ' + energy_keV.toFixed(1) + 'keV',
    600, 600);
  var canvasId = 'exptPopup_ptycho_canvas';
  // Hide popup info bar — progress info shown in right panel instead
  var _pInfoBar = document.getElementById('exptPopup_ptycho_info');
  if (_pInfoBar) _pInfoBar.style.display = 'none';

  // Build synthParams (K4GSR-PTYCHO format)
  var synthParams = _buildSynthParams(pp);

  // Cache num_positions from server (preview/data_loaded) for iteration/complete display
  var _cachedNumPositions = null;

  // Helper: build rendering info object
  function _mkRenderInfo(msgInfo) {
    var ri = msgInfo || {};
    ri.material = synthParams.material;
    ri.energy_keV = synthParams.energy_keV;
    ri.objheight = synthParams.objheight;
    ri.asize = synthParams.asize;
    ri.scan_step_um = synthParams.scan_step_um;
    ri.N_photons = synthParams.N_photons;
    ri.z_m = synthParams.z_m;
    ri.detector = pp.ptychoDetector || 'EIGER2_1M';
    // Use cached num_positions if not provided
    if (ri.num_positions == null || ri.num_positions === '?') {
      if (_cachedNumPositions) ri.num_positions = _cachedNumPositions;
    }
    return ri;
  }

  // ── Step 1: Quick preview (object + probe + positions, no fmag) ──
  _ptychoOnPreviewReady = function(msg) {
    console.log('[Ptycho] onPreviewReady: msg.preview=' + !!msg.preview +
      ', rawObj=' + !!_ptychoRawData.object +
      ', rawObjLen=' + (_ptychoRawData.object ? _ptychoRawData.object.length : 0) +
      ', rawProbe=' + !!_ptychoRawData.probe +
      ', shape=' + JSON.stringify(_ptychoRawData.objectShape));
    _updateExptProgress(0, 'Ptycho: preview ready, generating diffraction data...');
    // Cache num_positions from server for later iteration/complete display
    if (msg.info && msg.info.num_positions) _cachedNumPositions = msg.info.num_positions;

    var _prvInfo = _mkRenderInfo(msg.info);
    _renderPtychoWithRetry(canvasId, _prvInfo, 5);
    _registerExptRenderer('ptycho', function(cvs2) {
      renderPtychoFromServer(cvs2, _prvInfo);
    });

    // Auto-start full fmag generation
    console.log('[Ptycho] Step1 done, sending generate_synthetic');
    ptychoGenerateSynthetic(synthParams);
  };

  // ── Step 2: fmag generated → auto-start reconstruction ──
  _ptychoOnDataLoaded = function(msg) {
    console.log('[Ptycho] Step2: data_loaded received!');
    if (msg.info && msg.info.num_positions) _cachedNumPositions = msg.info.num_positions;
    _updateExptProgress(0, 'Ptycho: data ready, starting ' + pp.reconEngine + '...');

    // Auto-start reconstruction
    var _reconCoh = null;
    try { _reconCoh = _ptychoCoherentFraction(pp.energy_keV || 10); } catch(e) {}
    var _reconParams = {
      engine: pp.reconEngine || 'DM_LSQML',
      use_gpu: (typeof _ptychoGpuAvailable !== 'undefined') ? _ptychoGpuAvailable : false,
      probe_modes: (_reconCoh && _reconCoh.N_modes > 1) ? _reconCoh.N_modes : 1
    };
    // Set pipeline tracking for progress display
    _ptychoPipelineInfo = { engine: '', stage1Name: '', stage2Name: '', stage1Total: 0, stage2Total: 0, stage: 0 };
    if (pp.reconEngine === 'DM_ML' || pp.reconEngine === 'DM_LSQML') {
      _reconParams.dm_iterations = pp.dmIterations || 300;
      _reconParams.ml_iterations = pp.mlIterations || 30;
      _reconParams.lsqml_iterations = pp.mlIterations || 30;
      var _s2Name = pp.reconEngine === 'DM_LSQML' ? 'LSQML' : 'ML';
      _ptychoPipelineInfo = { engine: pp.reconEngine, stage1Name: 'DM', stage2Name: _s2Name,
        stage1Total: pp.dmIterations || 300, stage2Total: pp.mlIterations || 30, stage: 1 };
    } else if (pp.reconEngine === 'ePIE_ML' || pp.reconEngine === 'ePIE_LSQML') {
      _reconParams.epie_iterations = pp.dmIterations || 50;
      _reconParams.ml_iterations = pp.mlIterations || 30;
      _reconParams.lsqml_iterations = pp.mlIterations || 30;
      var _s2NameE = pp.reconEngine === 'ePIE_LSQML' ? 'LSQML' : 'ML';
      _ptychoPipelineInfo = { engine: pp.reconEngine, stage1Name: 'ePIE', stage2Name: _s2NameE,
        stage1Total: pp.dmIterations || 50, stage2Total: pp.mlIterations || 30, stage: 1 };
    } else if (pp.reconEngine === 'ePIE') {
      _reconParams.number_iterations = pp.dmIterations || 200;
    } else {
      _reconParams.number_iterations = pp.dmIterations || 300;
    }
    console.log('[Ptycho] Step2: starting reconstruction', JSON.stringify(_reconParams));
    ptychoStartReconstruction(_reconParams);
  };

  // ── Step 3: Iteration updates (progress already updated in 05_ptycho_sim.js) ──
  _ptychoOnIterUpdate = function(msg) {
    // Canvas rendering only — progress bar updated in 05_ptycho_sim.js for every iteration
    var _iterInfo = _mkRenderInfo({});
    _renderPtychoWithRetry(canvasId, _iterInfo, 3);
    _registerExptRenderer('ptycho', function(cvs2) {
      renderPtychoFromServer(cvs2, _iterInfo);
    });
  };

  // ── Step 4: Reconstruction complete ──
  _ptychoOnComplete = function(msg) {
    _exptState.running = false;
    var _complInfo = _mkRenderInfo({});
    _renderPtychoWithRetry(canvasId, _complInfo, 5);
    _registerExptRenderer('ptycho', function(cvs2) {
      renderPtychoFromServer(cvs2, _complInfo);
    });
    _updateExptProgress(1, 'Ptycho reconstruction complete');
  };

  _ptychoOnError = function(msg) {
    _exptState.running = false;
    _updateExptProgress(0, 'ERROR: ' + (msg.error || 'unknown'));
  };

  // Start with quick preview (object + probe, no FFT, < 2s)
  _updateExptProgress(0.05, 'Ptycho: loading preview...');
  console.log('[Ptycho] Sending preview_synthetic, connected=' + _ptychoConnected +
    ', ws readyState=' + (_ptychoWs ? _ptychoWs.readyState : 'null'));
  ptychoPreviewSynthetic(synthParams);
}

// ── Ptycho: Preview object only (no reconstruction) ──
window._previewPtychoObject = function() {
  _readPtychoParams();
  var pp = _exptState.ptycho;
  var energy_keV = (typeof state !== 'undefined' && state.energy) ? state.energy : 10;
  // asize is set by user in UI (detector-dependent crop size)

  // Requires K4GSR-PTYCHO server
  if (typeof _ptychoConnected === 'undefined' || !_ptychoConnected) {
    // Auto-connect attempt
    if (typeof ptychoConnect === 'function') ptychoConnect();
    var _wsUrl = (typeof PTYCHO_WS_URL !== 'undefined') ? PTYCHO_WS_URL : 'ws://localhost:8765';
    var infoEl = document.getElementById('exptInfo');
    if (infoEl) {
      infoEl.innerHTML = '<span style="color:#e05050">K4GSR-PTYCHO server (' + _wsUrl + ') not connected.</span><br>' +
        '<span style="color:var(--t2)">Connecting... If server is running, try again in a few seconds.</span>';
    }
    return;
  }

  // Server: generate synthetic only (no reconstruction)
  var popup = _openExptPopup('ptycho',
    'Ptychography [Preview]: ' + pp.material + ' ' + pp.objheight_um + '\u03bcm @ ' + energy_keV.toFixed(1) + 'keV',
    600, 600);
  var canvasId = 'exptPopup_ptycho_canvas';
  var synthParams = _buildSynthParams(pp);
  // Hide popup info bar — info shown in right panel
  var _pInfoBar2 = document.getElementById('exptPopup_ptycho_info');
  if (_pInfoBar2) _pInfoBar2.style.display = 'none';

  _ptychoOnPreviewReady = function(msg) {
    _updateExptProgress(1, 'Preview ready');

    var _srvInfo = msg.info || {};
    _srvInfo.material = synthParams.material;
    _srvInfo.energy_keV = synthParams.energy_keV;
    _srvInfo.objheight = synthParams.objheight;
    _srvInfo.asize = synthParams.asize;
    _srvInfo.scan_step_um = synthParams.scan_step_um;
    _srvInfo.N_photons = synthParams.N_photons;
    _srvInfo.z_m = synthParams.z_m;
    _srvInfo.detector = pp.ptychoDetector || 'EIGER2_1M';

    _renderPtychoWithRetry(canvasId, _srvInfo, 5);
    _registerExptRenderer('ptycho', function(cvs2) {
      renderPtychoFromServer(cvs2, _srvInfo);
    });
  };
  _ptychoOnDataLoaded = null;
  _ptychoOnIterUpdate = null;
  _ptychoOnComplete = null;
  _ptychoOnError = function(msg) {
    _updateExptProgress(0, 'Error: ' + (msg.error || 'unknown'));
  };

  _updateExptProgress(0.1, 'Preview: loading...');
  ptychoPreviewSynthetic(synthParams);
};

// NOTE: _drawChart1D and _drawXRDPeakLabels removed to avoid
// function-hoisting conflict with window._drawChart1D in 02_chart_stub.js
// Use window._drawChart1D(cv, data, opts) from chart_stub instead.

// ══════════════════════════════════════════════════════════════════
//  Chart Tooltip System (XAFS / XRD precision analysis)
// ══════════════════════════════════════════════════════════════════

// Stored chart data for tooltip lookup, keyed by canvasId
var _chartTooltipData = {};

// ── Attach tooltip to a completed 1D chart canvas ──
function _attachChartTooltip(canvasId, data, xLabel, yLabel, E0) {
  var cvs = document.getElementById(canvasId);
  if (!cvs || !data || data.length < 2) return;

  // Store chart info for this canvas
  _chartTooltipData[canvasId] = {
    data: data, xLabel: xLabel, yLabel: yLabel, E0: E0 || 0
  };

  // Create tooltip overlay div (if not exists)
  var tipId = canvasId + '_tooltip';
  var existing = document.getElementById(tipId);
  if (existing) existing.parentNode.removeChild(existing);

  var tip = document.createElement('div');
  tip.id = tipId;
  tip.style.cssText = 'position:absolute;display:none;pointer-events:none;' +
    'background:rgba(26,29,35,0.92);border:1px solid var(--ac,#4db8ff);border-radius:3px;' +
    'padding:4px 8px;font:9px monospace;color:var(--t1,#e8eaed);' +
    'white-space:nowrap;z-index:1010;box-shadow:0 2px 8px rgba(0,0,0,0.4)';
  // Insert into popup body (canvas parent)
  var parent = cvs.parentNode;
  if (parent) {
    parent.style.position = 'relative';
    parent.appendChild(tip);
  }

  // Crosshair overlay canvas
  var overlayId = canvasId + '_overlay';
  var existingOverlay = document.getElementById(overlayId);
  if (existingOverlay) existingOverlay.parentNode.removeChild(existingOverlay);

  var overlay = document.createElement('canvas');
  overlay.id = overlayId;
  overlay.setAttribute('data-overlay', '1');
  overlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none';
  if (parent) parent.appendChild(overlay);

  // Remove old listener if any
  if (cvs._tooltipMove) cvs.removeEventListener('mousemove', cvs._tooltipMove);
  if (cvs._tooltipLeave) cvs.removeEventListener('mouseleave', cvs._tooltipLeave);

  cvs._tooltipMove = function(e) {
    _handleChartTooltip(canvasId, e);
  };
  cvs._tooltipLeave = function() {
    var t = document.getElementById(tipId);
    if (t) t.style.display = 'none';
    var ov = document.getElementById(overlayId);
    if (ov) {
      var octx = ov.getContext('2d');
      octx.clearRect(0, 0, ov.width, ov.height);
    }
  };
  cvs.addEventListener('mousemove', cvs._tooltipMove);
  cvs.addEventListener('mouseleave', cvs._tooltipLeave);
}

// ── Handle mousemove on chart canvas ──
function _handleChartTooltip(canvasId, e) {
  var info = _chartTooltipData[canvasId];
  if (!info) return;
  var cvs = document.getElementById(canvasId);
  if (!cvs) return;

  var rect = cvs.getBoundingClientRect();
  // Work in CSS pixel space (not buffer pixels)
  var mx = e.clientX - rect.left;
  var my = e.clientY - rect.top;

  // Use stored chart layout if available (from _drawChart1D_canvas)
  var L = cvs._chartLayout;
  var margin, pw, ph2, W, H, dpr;
  var data = info.data;
  var xMin, xMax, yMin, yMax, xRange, yRange;

  if (L) {
    margin = L.pad; pw = L.pw; ph2 = L.ph;
    W = L.w; H = L.h; dpr = L.dpr;
    xMin = L.xMin; xMax = L.xMax; yMin = L.yMin; yMax = L.yMax;
    xRange = L.xRng; yRange = L.yRng;
  } else {
    // Fallback: estimate from CSS display size
    W = rect.width; H = rect.height; dpr = 1;
    var _fs2 = Math.max(10, Math.min(14, Math.round(Math.min(W, H) / 38)));
    margin = {t: _fs2 * 2 + 4, r: _fs2 + 4, b: _fs2 * 3 + 4, l: _fs2 * 5 + 4};
    pw = W - margin.l - margin.r;
    ph2 = H - margin.t - margin.b;
    xMin = data[0].x; xMax = data[0].x; yMin = data[0].y; yMax = data[0].y;
    for (var i = 1; i < data.length; i++) {
      if (data[i].x < xMin) xMin = data[i].x;
      if (data[i].x > xMax) xMax = data[i].x;
      if (data[i].y < yMin) yMin = data[i].y;
      if (data[i].y > yMax) yMax = data[i].y;
    }
    xRange = xMax - xMin; if (xRange < 1e-10) xRange = 1;
    yRange = yMax - yMin; if (yRange < 1e-10) yRange = 1;
    yMin -= yRange * 0.05; yMax += yRange * 0.05; yRange = yMax - yMin;
  }

  // Check if within plot area (CSS pixel space)
  if (mx < margin.l || mx > W - margin.r || my < margin.t || my > H - margin.b) {
    var tip = document.getElementById(canvasId + '_tooltip');
    if (tip) tip.style.display = 'none';
    var ov = document.getElementById(canvasId + '_overlay');
    if (ov) {
      var octx = ov.getContext('2d');
      octx.clearRect(0, 0, ov.width, ov.height);
    }
    return;
  }

  // Convert CSS pixel to data coordinates
  var dataX = xMin + (mx - margin.l) / pw * xRange;

  // Find nearest data point
  var nearIdx = 0;
  var bestDist = Infinity;
  for (var i = 0; i < data.length; i++) {
    var dist = Math.abs(data[i].x - dataX);
    if (dist < bestDist) { bestDist = dist; nearIdx = i; }
  }
  var pt = data[nearIdx];

  // Data point screen position (CSS pixel space)
  var ptCssX = margin.l + (pt.x - xMin) / xRange * pw;
  var ptCssY = margin.t + (1 - (pt.y - yMin) / yRange) * ph2;

  // Draw crosshair overlay (buffer pixel space = CSS * dpr)
  var ov = document.getElementById(canvasId + '_overlay');
  if (ov) {
    var ovDpr = dpr || 1;
    var bufW = Math.round(W * ovDpr), bufH = Math.round(H * ovDpr);
    if (ov.width !== bufW || ov.height !== bufH) {
      ov.width = bufW;
      ov.height = bufH;
    }
    var octx = ov.getContext('2d');
    octx.clearRect(0, 0, ov.width, ov.height);
    octx.save();
    octx.scale(ovDpr, ovDpr);

    // Vertical line
    octx.strokeStyle = 'rgba(77,184,255,0.4)';
    octx.lineWidth = 1;
    octx.setLineDash([4, 3]);
    octx.beginPath();
    octx.moveTo(ptCssX, margin.t);
    octx.lineTo(ptCssX, H - margin.b);
    octx.stroke();

    // Horizontal line
    octx.beginPath();
    octx.moveTo(margin.l, ptCssY);
    octx.lineTo(W - margin.r, ptCssY);
    octx.stroke();
    octx.setLineDash([]);

    // Data point marker
    octx.fillStyle = '#4db8ff';
    octx.beginPath();
    octx.arc(ptCssX, ptCssY, 4, 0, 2 * Math.PI);
    octx.fill();
    octx.strokeStyle = '#fff';
    octx.lineWidth = 1;
    octx.stroke();
    octx.restore();
  }

  // Position tooltip
  var tip = document.getElementById(canvasId + '_tooltip');
  if (tip) {
    var absE = info.E0 > 0 ? (info.E0 + pt.x) : 0;
    var html = '<div style="color:var(--ac,#4db8ff);font-weight:700;margin-bottom:2px">Point #' + (nearIdx + 1) + '/' + data.length + '</div>';
    html += '<div>' + info.xLabel + ': <span style="color:#fff">' + pt.x.toFixed(3) + '</span></div>';
    html += '<div>' + info.yLabel + ': <span style="color:#fff">' + pt.y.toFixed(6) + '</span></div>';
    if (absE > 0) {
      html += '<div>E (abs): <span style="color:var(--gn,#40d89a)">' + absE.toFixed(2) + ' eV</span></div>';
    }
    // Show derivative for XAFS
    if (info.E0 > 0 && nearIdx > 0 && nearIdx < data.length - 1) {
      var dydx = (data[nearIdx + 1].y - data[nearIdx - 1].y) / (data[nearIdx + 1].x - data[nearIdx - 1].x);
      html += '<div>dmu/dE: <span style="color:var(--am,#ffb340)">' + dydx.toExponential(3) + '</span></div>';
    }
    tip.innerHTML = html;
    tip.style.display = 'block';

    // Position: offset from mouse, keep within canvas bounds
    var tipX = mx + 15;
    var tipY = my - 10;
    // Keep tooltip within parent bounds
    var tipW = tip.offsetWidth || 140;
    var tipH = tip.offsetHeight || 60;
    if (tipX + tipW > rect.width - 5) tipX = mx - tipW - 10;
    if (tipY + tipH > rect.height - 5) tipY = rect.height - tipH - 5;
    if (tipY < 5) tipY = 5;
    tip.style.left = tipX + 'px';
    tip.style.top = tipY + 'px';
  }
}

// ══════════════════════════════════════════════════════════════════
//  2D Heatmap Renderer
// ══════════════════════════════════════════════════════════════════

// Colormap lookup tables
var _COLORMAPS = {
  hot: function(t) {
    t = Math.max(0, Math.min(1, t));
    var r = Math.min(255, Math.floor(t * 3 * 255));
    var g = Math.min(255, Math.max(0, Math.floor((t - 0.333) * 3 * 255)));
    var b = Math.min(255, Math.max(0, Math.floor((t - 0.667) * 3 * 255)));
    return [r, g, b];
  },
  viridis: function(t) {
    t = Math.max(0, Math.min(1, t));
    // Simplified viridis approximation
    var r = Math.floor(255 * (0.267 + t * (0.004 + t * (-1.429 + t * 1.573))));
    var g = Math.floor(255 * (0.004 + t * (1.384 + t * (-1.392 + t * 0.517))));
    var b = Math.floor(255 * (0.329 + t * (1.442 + t * (-3.048 + t * 1.613))));
    return [Math.max(0, Math.min(255, r)), Math.max(0, Math.min(255, g)), Math.max(0, Math.min(255, b))];
  },
  inferno: function(t) {
    t = Math.max(0, Math.min(1, t));
    var r = Math.floor(255 * Math.min(1, t * 3.2 - 0.15));
    var g = Math.floor(255 * Math.max(0, Math.min(1, t * 2.5 - 0.5)));
    var b = Math.floor(255 * Math.max(0, Math.min(1, 0.8 - Math.abs(t - 0.4) * 2.5)));
    return [Math.max(0, r), Math.max(0, g), Math.max(0, b)];
  }
};

// _drawHeatmap2D: render a 2D array as a colormap on canvas
// mapData[row][col] = value, opts = {x[], y[], xLabel, yLabel, title, colormap, region}
// region: {x, y, w, h} to draw in a sub-area of the canvas
window._drawHeatmap2D = function(cvs, mapData, opts) {
  if (!cvs || !mapData || mapData.length === 0) return;
  var ctx = cvs.getContext('2d');
  var nY = mapData.length, nX = mapData[0].length;

  // Drawing region
  var reg = opts.region || {x: 0, y: 0, w: cvs.width, h: cvs.height};
  var RX = reg.x, RY = reg.y, RW = reg.w, RH = reg.h;

  // Clear region
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(RX, RY, RW, RH);

  // Margins
  var margin = {t: 24, r: 50, b: 28, l: 44};
  var pw = RW - margin.l - margin.r;
  var ph = RH - margin.t - margin.b;
  if (pw < 20 || ph < 20) return;

  // Find data range
  var vMin = Infinity, vMax = -Infinity;
  for (var yi = 0; yi < nY; yi++) {
    for (var xi = 0; xi < nX; xi++) {
      var v = mapData[yi][xi];
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
  }
  if (vMin === vMax) { vMin = 0; vMax = vMin + 1; }
  var vRange = vMax - vMin;

  // Colormap function
  var cmapFn = _COLORMAPS[opts.colormap || 'hot'] || _COLORMAPS.hot;

  // Render as ImageData for performance
  var cellW = pw / nX;
  var cellH = ph / nY;
  var imgW = Math.ceil(pw);
  var imgH = Math.ceil(ph);
  var imgData = ctx.createImageData(imgW, imgH);
  var data = imgData.data;

  for (var py = 0; py < imgH; py++) {
    var rowIdx = Math.min(nY - 1, Math.floor(py / cellH));
    for (var px = 0; px < imgW; px++) {
      var colIdx = Math.min(nX - 1, Math.floor(px / cellW));
      var val = mapData[rowIdx][colIdx];
      var t = (val - vMin) / vRange;
      var rgb = cmapFn(t);
      var off = (py * imgW + px) * 4;
      data[off] = rgb[0];
      data[off + 1] = rgb[1];
      data[off + 2] = rgb[2];
      data[off + 3] = 255;
    }
  }
  ctx.putImageData(imgData, RX + margin.l, RY + margin.t);

  // Title
  ctx.font = '10px monospace';
  ctx.fillStyle = '#e8eaed';
  ctx.textAlign = 'center';
  ctx.fillText(opts.title || 'Heatmap', RX + margin.l + pw / 2, RY + 14);

  // Axis labels
  ctx.fillStyle = '#6b7280';
  ctx.font = '9px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(opts.xLabel || 'X', RX + margin.l + pw / 2, RY + RH - 4);

  ctx.save();
  ctx.translate(RX + 10, RY + margin.t + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(opts.yLabel || 'Y', 0, 0);
  ctx.restore();

  // Axis tick labels
  var xArr = opts.x || [];
  var yArr = opts.y || [];
  ctx.font = '8px monospace';
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'center';
  for (var ti = 0; ti <= 4; ti++) {
    var xIdx = Math.floor(ti * (nX - 1) / 4);
    var xVal = xArr.length > xIdx ? xArr[xIdx] : xIdx;
    ctx.fillText(typeof xVal === 'number' ? xVal.toFixed(1) : String(xVal),
      RX + margin.l + (xIdx + 0.5) * cellW, RY + margin.t + ph + 14);
  }
  ctx.textAlign = 'right';
  for (var ti2 = 0; ti2 <= 4; ti2++) {
    var yIdx = Math.floor(ti2 * (nY - 1) / 4);
    var yVal = yArr.length > yIdx ? yArr[yIdx] : yIdx;
    ctx.fillText(typeof yVal === 'number' ? yVal.toFixed(1) : String(yVal),
      RX + margin.l - 3, RY + margin.t + (yIdx + 0.5) * cellH + 3);
  }

  // Color bar (right side)
  var cbX = RX + margin.l + pw + 8;
  var cbW = 12;
  var cbH = ph;
  for (var cby = 0; cby < cbH; cby++) {
    var ct = 1 - cby / cbH;
    var cRgb = cmapFn(ct);
    ctx.fillStyle = 'rgb(' + cRgb[0] + ',' + cRgb[1] + ',' + cRgb[2] + ')';
    ctx.fillRect(cbX, RY + margin.t + cby, cbW, 1);
  }
  ctx.strokeStyle = '#3d5068';
  ctx.strokeRect(cbX, RY + margin.t, cbW, cbH);

  // Color bar labels
  ctx.font = '8px monospace';
  ctx.fillStyle = '#a0a4ab';
  ctx.textAlign = 'left';
  ctx.fillText(vMax > 1000 ? vMax.toExponential(1) : vMax.toFixed(1), cbX + cbW + 3, RY + margin.t + 8);
  ctx.fillText(vMin > 1000 ? vMin.toExponential(1) : vMin.toFixed(1), cbX + cbW + 3, RY + margin.t + cbH);
  var vMid = (vMin + vMax) / 2;
  ctx.fillText(vMid > 1000 ? vMid.toExponential(1) : vMid.toFixed(1), cbX + cbW + 3, RY + margin.t + cbH / 2 + 3);
};

// ══════════════════════════════════════════════════════════════════
//  XRF Spectrum Chart (log-scale)
// ══════════════════════════════════════════════════════════════════

function _drawSpectrumChart(ctx, spec, reg) {
  var RX = reg.x, RY = reg.y, RW = reg.w, RH = reg.h;
  var margin = {t: 24, r: 8, b: 28, l: 42};
  var pw = RW - margin.l - margin.r;
  var ph = RH - margin.t - margin.b;
  if (pw < 40 || ph < 40) return;

  // Background
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(RX, RY, RW, RH);

  // Data: log scale
  var ch = spec.channels;
  var nCh = spec.nCh;
  var ePerCh = spec.ePerCh;
  var maxE = 20000; // show up to 20 keV
  var maxCh = Math.min(nCh, Math.floor(maxE / ePerCh));

  // Find max for Y axis
  var yMax = 1;
  for (var i = 10; i < maxCh; i++) {
    if (ch[i] > yMax) yMax = ch[i];
  }
  var logMax = Math.log10(Math.max(1, yMax)) + 0.3;
  var logMin = -0.5;
  var logRange = logMax - logMin;

  // Grid lines
  ctx.strokeStyle = '#2a2d35';
  ctx.lineWidth = 0.5;
  for (var g = 0; g <= 5; g++) {
    var gy = RY + margin.t + ph * g / 5;
    ctx.beginPath(); ctx.moveTo(RX + margin.l, gy); ctx.lineTo(RX + margin.l + pw, gy); ctx.stroke();
  }

  // Spectrum fill
  ctx.fillStyle = 'rgba(77,184,255,0.15)';
  ctx.beginPath();
  ctx.moveTo(RX + margin.l, RY + margin.t + ph);
  for (var si = 0; si < maxCh; si++) {
    var sx = RX + margin.l + (si / maxCh) * pw;
    var val = Math.max(0.1, ch[si]);
    var logVal = Math.log10(val);
    var sy = RY + margin.t + ph * (1 - (logVal - logMin) / logRange);
    sy = Math.max(RY + margin.t, Math.min(RY + margin.t + ph, sy));
    ctx.lineTo(sx, sy);
  }
  ctx.lineTo(RX + margin.l + pw, RY + margin.t + ph);
  ctx.closePath();
  ctx.fill();

  // Spectrum line
  ctx.strokeStyle = '#4db8ff';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (var si2 = 0; si2 < maxCh; si2++) {
    var sx2 = RX + margin.l + (si2 / maxCh) * pw;
    var val2 = Math.max(0.1, ch[si2]);
    var logVal2 = Math.log10(val2);
    var sy2 = RY + margin.t + ph * (1 - (logVal2 - logMin) / logRange);
    sy2 = Math.max(RY + margin.t, Math.min(RY + margin.t + ph, sy2));
    if (si2 === 0) ctx.moveTo(sx2, sy2); else ctx.lineTo(sx2, sy2);
  }
  ctx.stroke();

  // Peak labels
  if (spec.peaks) {
    ctx.font = '7px monospace';
    ctx.textAlign = 'center';
    var shown = 0;
    // Sort peaks by counts descending
    var sortedPeaks = spec.peaks.slice().sort(function(a, b) { return b.counts - a.counts; });
    for (var pi = 0; pi < sortedPeaks.length && shown < 10; pi++) {
      var pk = sortedPeaks[pi];
      if (pk.E <= 0 || pk.E >= maxE || pk.counts < 1) continue;
      var pkX = RX + margin.l + (pk.E / ePerCh / maxCh) * pw;
      var pkLogY = Math.log10(Math.max(1, pk.counts));
      var pkY = RY + margin.t + ph * (1 - (pkLogY - logMin) / logRange) - 6;
      pkY = Math.max(RY + margin.t + 10, pkY);

      ctx.fillStyle = '#40d89a';
      ctx.fillText(pk.el + ' ' + pk.line, pkX, pkY - (shown % 2) * 8);
      shown++;
    }
  }

  // Compton / elastic labels
  if (spec.E_compton && spec.E_compton < maxE) {
    var compX = RX + margin.l + (spec.E_compton / ePerCh / maxCh) * pw;
    ctx.fillStyle = '#ffb340';
    ctx.font = '7px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Compton', compX, RY + margin.t + 14);
  }
  if (spec.E_elastic && spec.E_elastic < maxE) {
    var elasX = RX + margin.l + (spec.E_elastic / ePerCh / maxCh) * pw;
    ctx.fillStyle = '#ff6060';
    ctx.font = '7px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Elastic', elasX, RY + margin.t + 22);
  }

  // Title
  ctx.font = '10px monospace';
  ctx.fillStyle = '#e8eaed';
  ctx.textAlign = 'center';
  ctx.fillText('XRF Spectrum (log)', RX + margin.l + pw / 2, RY + 14);

  // X axis labels (keV)
  ctx.font = '8px monospace';
  ctx.fillStyle = '#6b7280';
  ctx.textAlign = 'center';
  for (var xi = 0; xi <= 4; xi++) {
    var eVal = (xi / 4) * maxE / 1000;
    ctx.fillText(eVal.toFixed(0) + ' keV', RX + margin.l + (xi / 4) * pw, RY + margin.t + ph + 14);
  }

  // Y axis labels (log counts)
  ctx.textAlign = 'right';
  for (var yi = 0; yi <= 4; yi++) {
    var logTick = logMin + (4 - yi) * logRange / 4;
    var tickLabel = Math.pow(10, logTick);
    ctx.fillText(tickLabel >= 100 ? tickLabel.toExponential(0) : tickLabel.toFixed(1),
      RX + margin.l - 3, RY + margin.t + yi * ph / 4 + 3);
  }

  // Axis label
  ctx.textAlign = 'center';
  ctx.fillText('Energy (keV)', RX + margin.l + pw / 2, RY + RH - 4);
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _COLORMAPS!=="undefined")globalThis._COLORMAPS=_COLORMAPS;
if(typeof _attachChartTooltip!=="undefined")globalThis._attachChartTooltip=_attachChartTooltip;
if(typeof _chartTooltipData!=="undefined")globalThis._chartTooltipData=_chartTooltipData;
if(typeof _drawHeatmap2D!=="undefined")globalThis._drawHeatmap2D=_drawHeatmap2D;
if(typeof _drawSpectrumChart!=="undefined")globalThis._drawSpectrumChart=_drawSpectrumChart;
if(typeof _drawXRDMapResult!=="undefined")globalThis._drawXRDMapResult=_drawXRDMapResult;
if(typeof _drawXRFMultiElResult!=="undefined")globalThis._drawXRFMultiElResult=_drawXRFMultiElResult;
if(typeof _drawXRFResult!=="undefined")globalThis._drawXRFResult=_drawXRFResult;
if(typeof _handleChartTooltip!=="undefined")globalThis._handleChartTooltip=_handleChartTooltip;
if(typeof _previewPtychoObject!=="undefined")globalThis._previewPtychoObject=_previewPtychoObject;
if(typeof _renderPtychoWithRetry!=="undefined")globalThis._renderPtychoWithRetry=_renderPtychoWithRetry;
if(typeof _runExptOnSimServer!=="undefined")globalThis._runExptOnSimServer=_runExptOnSimServer;
if(typeof _runPtychoExpt!=="undefined")globalThis._runPtychoExpt=_runPtychoExpt;
if(typeof _runPtychoServerMode!=="undefined")globalThis._runPtychoServerMode=_runPtychoServerMode;
if(typeof startExperiment!=="undefined")globalThis.startExperiment=startExperiment;
if(typeof stopExperiment!=="undefined")globalThis.stopExperiment=stopExperiment;
