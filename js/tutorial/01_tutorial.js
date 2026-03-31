// ===== PHASE 5: Tutorial + Virtual Experiments =====
// ===== tutorial.js — Interactive Tutorial + Virtual Experiment Runner =====
// @module tutorial/01_tutorial
// @exports TUTORIAL, TUTORIAL_COURSES, endTutorial, renderEnhancedSampleModal, renderExperimentPanel, renderGuideTab, renderTutorialLauncher, runEigerDemo, runSddDemo, runVirtualExperiment, sddSelectedElements, setupVirtualExperiment, showDetectorDemo, showExperimentGuide, showExperimentsOverview, ...
// Korea-4GSR ID10 NanoProbe v4.36 — Phase 5
'use strict';

// ============================================================
//  1. TUTORIAL SYSTEM — Step-by-step guided walkthrough
// ============================================================

var TUTORIAL = {
  active: false,
  currentStep: 0,
  steps: [],
  completedSteps: [],
  overlay: null
};

var TUTORIAL_COURSES = {
  // --- Beginner: Basic Usage ---
  basics: {
    id: 'basics',
    name_key: 'tut_basics_name',
    name: 'Basic Usage',
    desc_key: 'tut_basics_desc',
    description: 'Learn the basic interface and key features of the program',
    steps: [
      {
        title_key: 'tut_b1_title', content_key: 'tut_b1_content',
        title: 'Welcome!',
        content: '<p>Welcome to the Korea-4GSR ID10 NanoProbe Virtual Beamline!</p>' +
          '<p>This tutorial will guide you through the basic usage step by step.</p>' +
          '<p style="color:var(--am)">Follow the instructions at each step.</p>',
        highlight: null,
        action: null
      },
      {
        title_key: 'tut_b2_title', content_key: 'tut_b2_content',
        title: '1. Beamline Layout',
        content: '<p>The center of the screen shows <b>two views</b>:</p>' +
          '<p>* <span style="color:var(--ac)">TOP VIEW</span> -- Horizontal plane (M1/M2 mirror reflections)</p>' +
          '<p>* <span style="color:var(--ac)">SIDE VIEW</span> -- Vertical plane (DCM Bragg diffraction)</p>' +
          '<p style="color:var(--gn)">Click on any component to open its details and control panel.</p>',
        highlight: '#svgWrap',
        action: null
      },
      {
        title_key: 'tut_b3_title', content_key: 'tut_b3_content',
        title: '2. Energy Setting',
        content: '<p>Set the target energy in the <b>IVU tab</b> on the right sidebar.</p>' +
          '<p style="color:var(--am)">Try dragging the slider to set energy to 10 keV.</p>' +
          '<p>The system will automatically:</p>' +
          '<p>* Select the optimal harmonic</p>' +
          '<p>* Adjust the IVU gap</p>' +
          '<p>* Calculate the DCM Bragg angle</p>',
        highlight: '#tab-undulator',
        action: function() { switchTab('undulator'); }
      },
      {
        title_key: 'tut_b4_title', content_key: 'tut_b4_content',
        title: '3. Optical Component Adjustment',
        content: '<p>Adjust the beamline optics in the <b>Optics tab</b>:</p>' +
          '<p>* <span style="color:var(--ac)">WB Slit</span> -- White beam slit size</p>' +
          '<p>* <span style="color:var(--ac)">M1/M2</span> -- Horizontal deflection mirror angles</p>' +
          '<p>* <span style="color:var(--ac)">SSA</span> -- Secondary slit (KB virtual source)</p>' +
          '<p>* <span style="color:var(--ac)">KB</span> -- Final focusing result</p>' +
          '<p style="color:var(--am)">Try clicking the Optics tab.</p>',
        highlight: '.tabs',
        action: function() { switchTab('optics'); }
      },
      {
        title_key: 'tut_b5_title', content_key: 'tut_b5_content',
        title: '4. Status Monitoring',
        content: '<p>Check real-time beam information in the status bar at the bottom:</p>' +
          '<p>* <span style="color:var(--ac)">E</span> -- Current energy</p>' +
          '<p>* <span style="color:var(--gn)">Flux</span> -- Photon flux</p>' +
          '<p>* <span style="color:var(--pk)">Spot</span> -- Focal spot size</p>' +
          '<p>Beam sizes at each component position are also displayed.</p>',
        highlight: null,
        action: null
      },
      {
        title_key: 'tut_b6_title', content_key: 'tut_b6_content',
        title: '5. Running Measurements',
        content: '<p>You can run virtual experiments from the <b>Meas tab</b>:</p>' +
          '<p>* XANES -- Absorption spectrum</p>' +
          '<p>* XRD -- Diffraction pattern</p>' +
          '<p>* XRF -- Fluorescence spectrum</p>' +
          '<p>* 2D Map -- Spatial mapping</p>' +
          '<p style="color:var(--gn)">Press the START button to begin a scan.</p>',
        highlight: '#tab-measure',
        action: function() { switchTab('measure'); }
      },
      {
        title_key: 'tut_b7_title', content_key: 'tut_b7_content',
        title: '6. Bluesky Experiment Queue',
        content: '<p>Manage Bluesky-style experiments from the <b>BS tab</b>:</p>' +
          '<p>* Select plan and set parameters</p>' +
          '<p>* Add to queue for sequential execution</p>' +
          '<p>* Real-time progress monitoring</p>' +
          '<p style="color:var(--pr)">You can also use Quick Run buttons to start immediately.</p>',
        highlight: null,
        action: function() { switchTab('bluesky'); }
      },
      {
        title_key: 'tut_b8_title', content_key: 'tut_b8_content',
        title: '7. Mode Switching',
        content: '<p>Switch the operation mode using the mode buttons in the top bar:</p>' +
          '<p>* <span style="color:var(--gn)">Virtual</span> -- Simulation only</p>' +
          '<p>* <span style="color:var(--am)">Real</span> -- Real EPICS IOC connection</p>' +
          '<p>* <span style="color:var(--ac)">Dual</span> -- V/R comparison mode</p>' +
          '<p>For first-time use, practice in Virtual mode before switching to Real.</p>',
        highlight: '.mode-btns',
        action: null
      },
      {
        title_key: 'tut_b9_title', content_key: 'tut_b9_content',
        title: 'Basic Tutorial Complete!',
        content: '<p style="color:var(--gn)">Congratulations! You have learned the basic usage.</p>' +
          '<p>Proceed to the next steps:</p>' +
          '<p>* <b>Virtual Experiments</b> -- Simulate real experiments</p>' +
          '<p>* <b>EPICS Integration</b> -- Connect to real equipment</p>' +
          '<p>* <b>V/R Comparison</b> -- Compare simulation and reality</p>',
        highlight: null,
        action: null
      }
    ]
  },

  // --- Intermediate: Virtual Experiment Practice ---
  experiments: {
    id: 'experiments',
    name_key: 'tut_exp_name',
    name: 'Virtual Experiment Practice',
    desc_key: 'tut_exp_desc',
    description: 'Perform virtual experiments for each measurement technique',
    steps: [
      {
        title_key: 'tut_e1_title', content_key: 'tut_e1_content',
        title: 'Cu K-edge XANES Experiment',
        content: '<p>In this exercise, you will perform a <b>Cu K-edge XANES</b> measurement.</p>' +
          '<p style="color:var(--am)">Press the "Auto Setup" button below to automatically configure the experiment.</p>',
        highlight: null,
        action: function() { setupVirtualExperiment('cu_xanes'); }
      },
      {
        title_key: 'tut_e2_title', content_key: 'tut_e2_content',
        title: 'Run XANES Scan',
        content: '<p>Energy has been set to Cu K-edge (8.979 keV).</p>' +
          '<p style="color:var(--am)">In the BS tab, press the XANES button to start the scan.</p>' +
          '<p>When the scan completes, the mu(E) spectrum will be displayed in the bottom panel.</p>',
        highlight: null,
        action: function() { switchTab('bluesky'); }
      },
      {
        title_key: 'tut_e3_title', content_key: 'tut_e3_content',
        title: 'XRF Imaging Experiment',
        content: '<p>Now we will perform <b>XRF Imaging</b>.</p>' +
          '<p>The SDD detector collects fluorescence X-rays at 90 deg from the sample.</p>' +
          '<p style="color:var(--am)">After auto setup, a raster scan will generate an elemental distribution map.</p>',
        highlight: null,
        action: function() { setupVirtualExperiment('xrf_imaging'); }
      },
      {
        title_key: 'tut_e4_title', content_key: 'tut_e4_content',
        title: 'Powder XRD Experiment',
        content: '<p>Perform a <b>Powder XRD</b> measurement.</p>' +
          '<p>The Eiger 2X detector will collect Debye-Scherrer ring patterns.</p>',
        highlight: null,
        action: function() { setupVirtualExperiment('powder_xrd'); }
      }
    ]
  }
};

// --- Tutorial UI ---
function startTutorial(courseId) {
  var course = TUTORIAL_COURSES[courseId];
  if (!course) return;

  TUTORIAL.active = true;
  TUTORIAL.steps = course.steps;
  TUTORIAL.currentStep = 0;
  TUTORIAL.completedSteps = [];

  showTutorialStep(0);
  log('info', 'Tutorial started: ' + course.name);
}

function showTutorialStep(stepIdx) {
  if (stepIdx >= TUTORIAL.steps.length) {
    endTutorial();
    return;
  }

  TUTORIAL.currentStep = stepIdx;
  var step = TUTORIAL.steps[stepIdx];
  var stepTitle = step.title_key ? _t(step.title_key) : step.title;
  var stepContent = step.content_key ? _t(step.content_key) : step.content;

  // Execute action if any
  if (step.action) step.action();

  // Create/update overlay
  var overlay = document.getElementById('tutorialOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'tutorialOverlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:2000;pointer-events:none';
    document.body.appendChild(overlay);
  }

  var total = TUTORIAL.steps.length;
  var progress = ((stepIdx + 1) / total * 100).toFixed(0);

  overlay.innerHTML =
    '<div style="position:fixed;bottom:20px;left:50%;transform:translateX(-50%);width:480px;max-width:90vw;' +
      'background:var(--s0);border:1px solid var(--b2);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.7);' +
      'pointer-events:all;font-family:var(--sn);overflow:hidden">' +
      '<div style="padding:4px 12px;background:var(--s1);display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--b0)">' +
        '<span style="font-size:11px;font-weight:600;color:var(--ac)">' + stepTitle + '</span>' +
        '<span style="font-size:9px;color:var(--t3);font-family:var(--mn)">' + (stepIdx + 1) + '/' + total + '</span>' +
      '</div>' +
      '<div style="padding:12px 14px;font-size:11px;line-height:1.7;color:var(--t0)">' + stepContent + '</div>' +
      '<div style="padding:8px 14px;display:flex;justify-content:space-between;align-items:center;background:var(--s1);border-top:1px solid var(--b0)">' +
        '<div style="flex:1;height:3px;background:var(--s3);border-radius:2px;margin-right:10px">' +
          '<div style="width:' + progress + '%;height:100%;background:linear-gradient(90deg,var(--ac),var(--pr));border-radius:2px"></div>' +
        '</div>' +
        '<div style="display:flex;gap:4px">' +
          (stepIdx > 0 ? '<button onclick="showTutorialStep('+(stepIdx-1)+')" style="padding:4px 10px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:4px;font-size:10px;cursor:pointer" data-i18n="tut_prev">' + _t('tut_prev') + '</button>' : '') +
          (stepIdx < total - 1 ?
            '<button onclick="showTutorialStep('+(stepIdx+1)+')" style="padding:4px 12px;background:var(--ac);border:none;color:#000;border-radius:4px;font-size:10px;font-weight:600;cursor:pointer" data-i18n="tut_next">' + _t('tut_next') + '</button>' :
            '<button onclick="endTutorial()" style="padding:4px 12px;background:var(--gn);border:none;color:#000;border-radius:4px;font-size:10px;font-weight:600;cursor:pointer" data-i18n="tut_done">' + _t('tut_done') + '</button>') +
          '<button onclick="endTutorial()" style="padding:4px 8px;background:none;border:1px solid var(--b1);color:var(--t3);border-radius:4px;font-size:9px;cursor:pointer">X</button>' +
        '</div>' +
      '</div>' +
    '</div>';

  // Highlight element
  if (step.highlight) {
    var el = document.querySelector(step.highlight);
    if (el) {
      el.style.outline = '2px solid var(--ac)';
      el.style.outlineOffset = '2px';
      el.style.transition = 'outline 0.3s';
      // Remove highlight from previous
      setTimeout(function() {
        document.querySelectorAll('[style*="outline"]').forEach(function(e) {
          if (e !== el) { e.style.outline = ''; e.style.outlineOffset = ''; }
        });
      }, 100);
    }
  }
}

function endTutorial() {
  TUTORIAL.active = false;
  var overlay = document.getElementById('tutorialOverlay');
  if (overlay) overlay.remove();
  // Remove all highlights
  document.querySelectorAll('[style*="outline"]').forEach(function(e) {
    e.style.outline = '';
    e.style.outlineOffset = '';
  });
  log('info', 'Tutorial ended');
}

// ============================================================
//  2. VIRTUAL EXPERIMENT SETUP & RUNNER
// ============================================================

function setupVirtualExperiment(expId) {
  var exp = VIRTUAL_EXPERIMENTS.find(function(e) { return e.id === expId; });
  if (!exp) return;

  log('info', 'Setting up: ' + exp.name);

  // Apply settings
  if (exp.setup.energy) {
    state.energy = exp.setup.energy;
    state.targetEnergy = exp.setup.energy;
    if (typeof setTargetEnergy === 'function') setTargetEnergy(exp.setup.energy);
  }

  // Queue the plan
  if (exp.setup.plan && typeof queuePlan === 'function') {
    queuePlan(exp.setup.plan, exp.setup.params || {});
  }

  log('info', 'Experiment ready: ' + exp.name);
}

function runVirtualExperiment(expId) {
  if (typeof QUEUE !== 'undefined') QUEUE._suppressPanel = true;
  setupVirtualExperiment(expId);
  if (typeof queueStart === 'function') queueStart();
}

// ============================================================
//  3. EXPERIMENT PANEL IN SAMPLE MODAL
// ============================================================

function renderExperimentPanel(containerId) {
  var container = document.getElementById(containerId);
  if (!container) return;

  var h = '<div style="margin-top:10px">';
  h += '<h4 style="font-size:10px;color:var(--pr);margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px">Virtual Experiments</h4>';

  VIRTUAL_EXPERIMENTS.forEach(function(exp) {
    var catColors = {spectroscopy:'var(--ac)',imaging:'var(--pk)',diffraction:'var(--pr)'};
    h += '<div style="background:var(--s1);border:1px solid var(--b1);border-radius:6px;padding:8px 10px;margin-bottom:6px;cursor:pointer"' +
      ' onclick="runVirtualExperiment(\'' + exp.id + '\')">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<span style="font-size:10px;font-weight:600">' + exp.icon + ' ' + exp.name + '</span>' +
        '<span style="font-size:8px;color:' + (catColors[exp.category] || 'var(--t3)') + ';font-family:var(--mn)">' + exp.category + '</span>' +
      '</div>' +
      '<div style="font-size:9px;color:var(--t3);margin-top:3px">' + exp.description + '</div>' +
      '<div style="display:flex;gap:4px;margin-top:4px">' +
        '<button onclick="event.stopPropagation();showExperimentGuide(\'' + exp.id + '\')"' +
          ' style="font-size:8px;padding:2px 8px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:3px;cursor:pointer">Guide</button>' +
        '<button onclick="event.stopPropagation();runVirtualExperiment(\'' + exp.id + '\')"' +
          ' style="font-size:8px;padding:2px 8px;background:var(--ac);border:none;color:#000;border-radius:3px;cursor:pointer;font-weight:600">Run</button>' +
      '</div>' +
    '</div>';
  });

  h += '</div>';
  container.innerHTML = h;
}

function showExperimentGuide(expId) {
  var exp = VIRTUAL_EXPERIMENTS.find(function(e) { return e.id === expId; });
  if (!exp) return;

  var h = '<div style="font-size:11px;margin-bottom:10px">' + exp.description + '</div>';
  h += '<div style="background:var(--s1);border-radius:6px;padding:10px">';
  exp.guide.forEach(function(step, i) {
    h += '<div style="display:flex;gap:8px;margin-bottom:6px;font-size:10px">' +
      '<span style="color:var(--ac);font-family:var(--mn);min-width:20px">' + (i+1) + '.</span>' +
      '<span style="color:var(--t0)">' + step.replace(/^\d+\.\s*/, '') + '</span>' +
    '</div>';
  });
  h += '</div>';
  h += '<div style="margin-top:10px;text-align:center">' +
    '<button onclick="closeModal();runVirtualExperiment(\'' + expId + '\')"' +
      ' style="padding:6px 20px;background:var(--ac);border:none;color:#000;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer">Start Experiment</button>' +
  '</div>';

  if (typeof openModal === 'function') openModal(exp.name + ' Guide', h);
}

// ============================================================
//  4. ENHANCED SAMPLE MODAL WITH ALL FEATURES
// ============================================================

function renderEnhancedSampleModal() {
  var sp = typeof focalSpot === 'function' ? focalSpot() : {h:50,v:30,demagH:500,demagV:300};
  var flux = typeof photonFlux === 'function' ? photonFlux(state.energy) : 1e10;

  var h = '';

  // Beam profile section
  h += '<div class="mc"><h4>Beam Profile (Ray-Tracing)</h4>' +
    '<div id="beamProfileContainer"></div>' +
  '</div>';

  // Detector section
  h += '<div class="mc"><h4>Detector Configuration</h4>' +
    '<div class="info-grid">' +
      '<div class="info-item"><div class="lbl">Forward (2D)</div><div class="val" style="color:var(--pr)">Eiger2 X 500K</div></div>' +
      '<div class="info-item"><div class="lbl">Pixel</div><div class="val">512x512, 75um</div></div>' +
      '<div class="info-item"><div class="lbl">Side (SDD)</div><div class="val" style="color:var(--pk)">Vortex ME-4</div></div>' +
      '<div class="info-item"><div class="lbl">SDD Resolution</div><div class="val">130 eV @Mn Ka</div></div>' +
    '</div>' +
    '<div style="margin-top:8px">' +
      '<button onclick="showDetectorDemo(\'eiger\')" class="sb act">Eiger2X Demo</button>' +
      '<button onclick="showDetectorDemo(\'sdd\')" class="sb act" style="background:var(--pk);color:#000">SDD Demo</button>' +
    '</div>' +
  '</div>';

  // Sample info
  h += '<div class="info-grid">' +
    '<div class="info-item"><div class="lbl">Focal Size</div><div class="val" style="color:var(--gn)">' + sp.h.toFixed(0) + ' x ' + sp.v.toFixed(0) + ' nm</div></div>' +
    '<div class="info-item"><div class="lbl">Flux</div><div class="val">' + flux.toExponential(2) + ' ph/s</div></div>' +
    '<div class="info-item"><div class="lbl">Energy</div><div class="val">' + state.energy.toFixed(2) + ' keV</div></div>' +
    '<div class="info-item"><div class="lbl">Demag. Ratio</div><div class="val">H:' + sp.demagH.toFixed(0) + 'x V:' + sp.demagV.toFixed(0) + 'x</div></div>' +
  '</div>';

  // Virtual experiments
  h += '<div id="virtualExpPanel"></div>';

  return h;
}

function showDetectorDemo(type) {
  var h = '';
  if (type === 'eiger') {
    h += '<div class="mc"><h4>Eiger 2X 500K -- Diffraction Pattern Simulation</h4>' +
      '<div style="display:flex;gap:8px;margin-bottom:8px">' +
        '<button onclick="runEigerDemo(\'powder_xrd\')" class="sb" style="font-size:8px">Powder XRD</button>' +
        '<button onclick="runEigerDemo(\'single_xrd\')" class="sb" style="font-size:8px">Single-Crystal XRD</button>' +
        '<button onclick="runEigerDemo(\'saxs\')" class="sb" style="font-size:8px">SAXS</button>' +
      '</div>' +
      '<canvas id="eigerDemoCanvas" width="300" height="300" style="border:1px solid var(--b1);border-radius:4px"></canvas>' +
      '<div class="info-grid" style="margin-top:6px">' +
        '<div class="info-item"><div class="lbl">Model</div><div class="val">Eiger2 X 500K</div></div>' +
        '<div class="info-item"><div class="lbl">Sensor</div><div class="val">CdTe 512x512</div></div>' +
        '<div class="info-item"><div class="lbl">Pixel</div><div class="val">75 um</div></div>' +
        '<div class="info-item"><div class="lbl">Frame Rate</div><div class="val">230 kHz</div></div>' +
      '</div>' +
    '</div>';
  } else {
    var defaultEls = ['Fe', 'Cu', 'Zn'];
    var elKeys = Object.keys(XRF_LINES);
    var elButtons = '';
    for (var _ek = 0; _ek < elKeys.length; _ek++) {
      var el = elKeys[_ek];
      var isDefault = defaultEls.indexOf(el) >= 0;
      elButtons += '<button onclick="toggleSddElement(\'' + el + '\',this)"' +
        ' class="sb" style="font-size:8px;padding:2px 6px;background:' + (isDefault ? 'var(--ac)' : 'var(--s2)') + ';' +
        'color:' + (isDefault ? '#000' : 'var(--t2)') + '" data-el="' + el + '">' + el + '</button>';
    }
    h += '<div class="mc"><h4>Vortex ME-4 SDD -- XRF Spectrum Simulation</h4>' +
      '<div style="margin-bottom:6px;font-size:9px;color:var(--t2)">Select sample elements:</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:8px" id="sddElementSelect">' +
        elButtons +
      '</div>' +
      '<canvas id="sddDemoCanvas" width="450" height="180" style="border:1px solid var(--b1);border-radius:4px"></canvas>' +
      '<div class="info-grid" style="margin-top:6px">' +
        '<div class="info-item"><div class="lbl">Position</div><div class="val" style="color:var(--pk)">90 deg to sample</div></div>' +
        '<div class="info-item"><div class="lbl">Resolution</div><div class="val">130 eV @5.9keV</div></div>' +
        '<div class="info-item"><div class="lbl">Active Area</div><div class="val">50 mm2</div></div>' +
        '<div class="info-item"><div class="lbl">Dead time</div><div class="val" id="sddDeadTime">--</div></div>' +
      '</div>' +
    '</div>';
  }

  if (typeof openModal === 'function') openModal(type === 'eiger' ? 'Eiger 2X Demo' : 'SDD Demo', h);

  setTimeout(function() {
    if (type === 'eiger') runEigerDemo('powder_xrd');
    else runSddDemo();
  }, 50);
}

var sddSelectedElements = ['Fe', 'Cu', 'Zn'];

function toggleSddElement(el, btn) {
  var idx = sddSelectedElements.indexOf(el);
  if (idx >= 0) { sddSelectedElements.splice(idx, 1); btn.style.background = 'var(--s2)'; btn.style.color = 'var(--t2)'; }
  else { sddSelectedElements.push(el); btn.style.background = 'var(--ac)'; btn.style.color = '#000'; }
  runSddDemo();
}

function runEigerDemo(technique) {
  var mat = document.getElementById('material') ? document.getElementById('material').value : 'Cu';
  var img = simulateEiger2X(technique, { material: mat, dwell: 1.0, detector_dist: 200 });
  renderEigerImage('eigerDemoCanvas', img, EIGER2X.sensorSize[0], EIGER2X.sensorSize[1]);
}

function runSddDemo() {
  var elements = sddSelectedElements.map(function(s) { return { symbol: s, concentration: 0.3 }; });
  var spectrum = simulateSDD(elements, 10, state.energy);
  renderSDDSpectrum('sddDemoCanvas', spectrum, elements);
  var dt = document.getElementById('sddDeadTime');
  if (dt) dt.textContent = SDD_DETECTOR.deadTimePercent.toFixed(1) + '%';
}

// ============================================================
//  5. TUTORIAL LAUNCHER (added to sidebar)
// ============================================================

function renderTutorialLauncher() {
  return '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Tutorials & Guides</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div style="display:flex;flex-direction:column;gap:4px">' +
      '<button onclick="startTutorial(\'basics\')" class="sb" style="font-size:9px;padding:4px 8px;width:100%;text-align:left">' +
        'Basic Usage (Beginner)' +
      '</button>' +
      '<button onclick="startTutorial(\'experiments\')" class="sb" style="font-size:9px;padding:4px 8px;width:100%;text-align:left;background:var(--pr);color:#000">' +
        'Virtual Experiment Practice' +
      '</button>' +
      '<button onclick="showExperimentsOverview()" class="sb" style="font-size:9px;padding:4px 8px;width:100%;text-align:left;background:var(--s2);color:var(--t2)">' +
        'Experiment Examples' +
      '</button>' +
    '</div>' +
  '</div></div>';
}

function showExperimentsOverview() {
  var h = '<div style="font-size:11px;margin-bottom:10px">Available virtual experiments. Click an experiment to auto-configure and run it.</div>';
  VIRTUAL_EXPERIMENTS.forEach(function(exp) {
    h += '<div style="background:var(--s1);border:1px solid var(--b1);border-radius:6px;padding:10px 12px;margin-bottom:8px">' +
      '<div style="font-size:12px;font-weight:600;margin-bottom:4px">' + exp.icon + ' ' + exp.name + '</div>' +
      '<div style="font-size:10px;color:var(--t3);margin-bottom:6px">' + exp.description + '</div>' +
      '<div style="font-size:9px;color:var(--t2)">';
    exp.guide.forEach(function(s) { h += '<div style="margin:2px 0">' + s + '</div>'; });
    h += '</div>' +
      '<div style="margin-top:6px;display:flex;gap:4px">' +
        '<button onclick="closeModal();setupVirtualExperiment(\'' + exp.id + '\')" class="sb act">Setup</button>' +
        '<button onclick="closeModal();runVirtualExperiment(\'' + exp.id + '\')" class="sb go act">Run</button>' +
      '</div>' +
    '</div>';
  });
  if (typeof openModal === 'function') openModal('Virtual Experiment List', h);
}



// ===== Guide Tab Renderer =====
function renderGuideTab() {
  var el = document.getElementById('tab-guide');
  if (!el) return;
  var h = '';

  // Tutorial section
  if (typeof renderTutorialLauncher === 'function') {
    h += renderTutorialLauncher();
  }

  // Virtual Experiments section
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Virtual Experiments</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div style="display:flex;flex-direction:column;gap:3px">';

  if (typeof VIRTUAL_EXPERIMENTS !== 'undefined') {
    VIRTUAL_EXPERIMENTS.forEach(function(exp) {
      h += '<div style="display:flex;align-items:center;gap:4px">' +
        '<button onclick="runVirtualExperiment(\'' + exp.id + '\')" class="sb" style="font-size:8px;padding:2px 6px;flex:1;text-align:left">' +
          exp.icon + ' ' + exp.name +
        '</button>' +
        '<button onclick="showExperimentGuide(\'' + exp.id + '\')" style="font-size:8px;padding:2px 4px;background:var(--s2);border:1px solid var(--b1);color:var(--t3);border-radius:2px;cursor:pointer">?</button>' +
      '</div>';
    });
  }

  h += '</div></div></div>';

  // Detector Demos
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Detector Demos</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<button onclick="showDetectorDemo(\'eiger\')" class="sb" style="font-size:8px;padding:3px 6px;width:100%;margin-bottom:3px">' +
      'Eiger2 X 500K (2D Detector)' +
    '</button>' +
    '<button onclick="showDetectorDemo(\'sdd\')" class="sb" style="font-size:8px;padding:3px 6px;width:100%;background:var(--pk);color:#000">' +
      'Vortex SDD (XRF Detector)' +
    '</button>' +
  '</div></div>';

  // Quick Reference
  h += '<div style="margin-bottom:6px">' +
    '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Quick Reference</h4>' +
    '<div class="ctrl-group" style="margin:0">' +
    '<div style="font-size:8px;font-family:var(--mn);color:var(--t3);line-height:1.8">' +
      '<div>IVU -- Target Energy Setting</div>' +
      '<div>DCM -- Energy Fine Tuning</div>' +
      '<div>Optics -- Slit/Mirror Control</div>' +
      '<div>Motors -- 64-Axis Motor Control</div>' +
      '<div>Mask -- Heat Load Analysis</div>' +
      '<div>Meas -- Direct Scan Execution</div>' +
      '<div>Align -- Auto Alignment</div>' +
      '<div>V/R -- Virtual/Real Comparison</div>' +
      '<div>EPICS -- IOC Integration</div>' +
      '<div>BS -- Bluesky Queue Management</div>' +
      '<div>Guide -- Tutorials & Virtual Experiments</div>' +
    '</div>' +
  '</div></div>';


  el.innerHTML = h;
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof TUTORIAL!=="undefined")globalThis.TUTORIAL=TUTORIAL;
if(typeof TUTORIAL_COURSES!=="undefined")globalThis.TUTORIAL_COURSES=TUTORIAL_COURSES;
if(typeof endTutorial!=="undefined")globalThis.endTutorial=endTutorial;
if(typeof renderEnhancedSampleModal!=="undefined")globalThis.renderEnhancedSampleModal=renderEnhancedSampleModal;
if(typeof renderExperimentPanel!=="undefined")globalThis.renderExperimentPanel=renderExperimentPanel;
if(typeof renderGuideTab!=="undefined")globalThis.renderGuideTab=renderGuideTab;
if(typeof renderTutorialLauncher!=="undefined")globalThis.renderTutorialLauncher=renderTutorialLauncher;
if(typeof runEigerDemo!=="undefined")globalThis.runEigerDemo=runEigerDemo;
if(typeof runSddDemo!=="undefined")globalThis.runSddDemo=runSddDemo;
if(typeof runVirtualExperiment!=="undefined")globalThis.runVirtualExperiment=runVirtualExperiment;
if(typeof sddSelectedElements!=="undefined")globalThis.sddSelectedElements=sddSelectedElements;
if(typeof setupVirtualExperiment!=="undefined")globalThis.setupVirtualExperiment=setupVirtualExperiment;
if(typeof showDetectorDemo!=="undefined")globalThis.showDetectorDemo=showDetectorDemo;
if(typeof showExperimentGuide!=="undefined")globalThis.showExperimentGuide=showExperimentGuide;
if(typeof showExperimentsOverview!=="undefined")globalThis.showExperimentsOverview=showExperimentsOverview;
if(typeof showTutorialStep!=="undefined")globalThis.showTutorialStep=showTutorialStep;
if(typeof startTutorial!=="undefined")globalThis.startTutorial=startTutorial;
if(typeof toggleSddElement!=="undefined")globalThis.toggleSddElement=toggleSddElement;
