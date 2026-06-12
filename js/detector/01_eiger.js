// ===== PHASE 4: Detectors + Ray-Tracing =====
// ===== detectors.js — Eiger 2X & SDD Detector Simulation =====
// @module detector/01_eiger
// @exports EIGER2X, SDD_DETECTOR, VIRTUAL_EXPERIMENTS, XRF_LINES, drawHeatmap, drawSingleProfile, niceScaleNm, poissonSample, renderEigerImage, renderSDDSpectrum, renderXRFMaps, simulateEiger2X, simulateSDD, simulateXRFMap
// Korea-4GSR ID10 NanoProbe v4.36 — Phase 4
'use strict';

// ============================================================
//  1. RAY-TRACING BEAM PROFILE AT SAMPLE
// ============================================================


function drawSingleProfile(ctx, prof, x, y, w, h, color, label, fovNm) {
  var N = prof.length;
  var max = Math.max.apply(null, Array.prototype.slice.call(prof)) || 1;

  // Background
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(x, y, w, h);

  // Draw profile
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (var i = 0; i < N; i++) {
    var px = x + (i / (N-1)) * w;
    var py = y + h - (prof[i] / max) * h * 0.9;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }
  ctx.stroke();

  // Fill
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x, y + h);
  ctx.closePath();
  ctx.fillStyle = color.replace(')', ',0.1)').replace('rgb', 'rgba');
  ctx.fill();

  // FWHM line
  ctx.strokeStyle = 'rgba(255,255,255,0.3)';
  ctx.setLineDash([2,2]);
  ctx.beginPath();
  ctx.moveTo(x, y + h * 0.55);
  ctx.lineTo(x + w, y + h * 0.55);
  ctx.stroke();
  ctx.setLineDash([]);

  // Label
  ctx.fillStyle = color;
  ctx.font = '9px IBM Plex Mono';
  ctx.fillText(label, x + 4, y + 10);
}

// Pick a round scale-bar length (1..5000 nm) nearest 0.3*FOV; return value plus label in nm or um.
function niceScaleNm(fovNm) {
  var targets = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
  var ideal = fovNm * 0.3;
  var best = targets[0];
  for (var _ti = 0; _ti < targets.length; _ti++) {
    var t = targets[_ti];
    if (Math.abs(t - ideal) < Math.abs(best - ideal)) best = t;
  }
  if (best >= 1000) return {v: best, l: (best/1000).toFixed(0) + ' \u00b5m'};
  return {v: best, l: best + ' nm'};
}

// ============================================================
//  3. EIGER 2X 2D DETECTOR SIMULATION
// ============================================================

var EIGER2X = {
  name: 'Eiger2 X 500K',
  pixelSize: 75,        // um
  sensorSize: [512, 512],
  maxRate: 2.3e5,       // frames/s (500K model)
  bitDepth: 32,
  sensorMaterial: 'CdTe',  // for high energy
  threshold: 0,          // keV
  // Simulation state
  image: null,
  roiData: null
};

// Generate a 512x512 Float64 frame for powder/single XRD or SAXS using lambda=12.3984/E and Poisson noise.
function simulateEiger2X(technique, params) {
  var nx = EIGER2X.sensorSize[0], ny = EIGER2X.sensorSize[1];
  var img = new Float64Array(nx * ny);
  var E = state.energy;
  var lambda = 12.3984 / E;  // Angstrom
  var dwell = params.dwell || 1.0;  // seconds
  var flux = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
  if (!flux) flux = 1e10;

  if (technique === 'xrd' || technique === 'powder_xrd') {
    // Powder XRD rings (Debye-Scherrer)
    var mat = params.material || 'Cu';
    var matData = typeof MATERIALS !== 'undefined' ? MATERIALS[mat] : null;
    var peaks2theta = matData ? matData.xrd : [43.3, 50.4, 74.1];
    var cx = nx / 2, cy = ny / 2;
    var sdd_dist = params.detector_dist || 200;  // mm
    var pixSize = EIGER2X.pixelSize / 1000;  // mm

    for (var y = 0; y < ny; y++) {
      for (var x = 0; x < nx; x++) {
        var dx = (x - cx) * pixSize;
        var dy = (y - cy) * pixSize;
        var r_mm = Math.sqrt(dx*dx + dy*dy);
        var twoTheta = Math.atan(r_mm / sdd_dist) * 180 / Math.PI;

        // Background: air scatter + thermal diffuse
        var val = 5 + 3 * Math.exp(-twoTheta * 0.05) + Math.random() * 2;

        // Debye rings
        peaks2theta.forEach(function(pk, j) {
          var width = 0.15 + j * 0.03;
          var intensity = (500 - j * 80) * flux / 1e10 * dwell;
          val += intensity * Math.exp(-0.5 * Math.pow(((twoTheta - pk) / width), 2));
        });

        // Poisson noise
        val = Math.max(0, poissonSample(val));
        img[y * nx + x] = val;
      }
    }
  } else if (technique === 'single_xrd') {
    // Single crystal Bragg spots
    var cx = nx / 2, cy = ny / 2;
    var nSpots = 15 + Math.floor(Math.random() * 20);
    // Background
    for (var i = 0; i < nx * ny; i++) img[i] = poissonSample(3 + Math.random() * 2);

    for (var s = 0; s < nSpots; s++) {
      var sx = cx + (Math.random() - 0.5) * nx * 0.8;
      var sy = cy + (Math.random() - 0.5) * ny * 0.8;
      var intensity = (200 + Math.random() * 2000) * flux / 1e10 * dwell;
      var sigX = 1.5 + Math.random() * 2;
      var sigY = 1.5 + Math.random() * 2;

      for (var dy = -10; dy <= 10; dy++) {
        for (var dx = -10; dx <= 10; dx++) {
          var px = Math.round(sx + dx);
          var py = Math.round(sy + dy);
          if (px >= 0 && px < nx && py >= 0 && py < ny) {
            var v = intensity * Math.exp(-0.5 * (Math.pow((dx/sigX), 2) + Math.pow((dy/sigY), 2)));
            img[py * nx + px] += poissonSample(v);
          }
        }
      }
    }
  } else if (technique === 'saxs') {
    // SAXS pattern (q-ring + central beam stop)
    var cx = nx / 2, cy = ny / 2;
    var beamstopR = 15;

    for (var y = 0; y < ny; y++) {
      for (var x = 0; x < nx; x++) {
        var dx = x - cx, dy = y - cy;
        var r = Math.sqrt(dx*dx + dy*dy);

        if (r < beamstopR) { img[y * nx + x] = 0; continue; }

        // I(q) ~ q^-2 (Porod) + rings
        var q = r * 0.01;
        var val = 1000 / (q * q + 0.01) * flux / 1e10 * dwell * 0.001;
        // Lamellar peak
        val += 500 * Math.exp(-0.5 * Math.pow(((r - 80) / 5), 2)) * dwell;
        val += 200 * Math.exp(-0.5 * Math.pow(((r - 160) / 8), 2)) * dwell;

        img[y * nx + x] = poissonSample(Math.max(0, val));
      }
    }
  }

  EIGER2X.image = img;
  return img;
}

// Draw the detector frame as a log10(counts+1) viridis heatmap via _drawHeatmap2D, titling with max counts.
function renderEigerImage(canvasId, img, nx, ny) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;

  var maxV = 0;
  for (var i = 0; i < img.length; i++) if (img[i] > maxV) maxV = img[i];

  // Build 2D array (log scale)
  var z = [];
  for (var y = 0; y < ny; y++) {
    var row = [];
    for (var x = 0; x < nx; x++) {
      row.push(Math.log10(img[y * nx + x] + 1));
    }
    z.push(row);
  }

  if (typeof _drawHeatmap2D === 'function') {
    _drawHeatmap2D(cv, z, {
      title: 'Eiger2X ' + nx + 'x' + ny + ' | max: ' + maxV.toFixed(0) + ' cts',
      width: cv.width || 400, height: cv.height || 400,
      showColorbar: true,
      colorscale: [
        [0, 'rgb(68,1,84)'], [0.25, 'rgb(59,82,139)'],
        [0.5, 'rgb(33,145,140)'], [0.75, 'rgb(94,201,98)'], [1, 'rgb(253,231,37)']
      ]
    });
  }
}

// Draw a Poisson random count for mean lambda; Gaussian approximation when lambda>100, else Knuth product method.
function poissonSample(lambda) {
  if (lambda <= 0) return 0;
  if (lambda > 100) return Math.round(lambda + Math.sqrt(lambda) * gaussRand());
  var L = Math.exp(-lambda), k = 0, p = 1;
  do { k++; p *= Math.random(); } while (p > L);
  return k - 1;
}

// ============================================================
//  4. SDD DETECTOR SIMULATION (90 deg XRF)
// ============================================================

var SDD_DETECTOR = {
  name: 'Vortex ME-4 SDD',
  channels: 2048,
  energyRange: 20,       // keV
  resolution: 130,       // eV at Mn K-alpha (5.9 keV)
  activeArea: 50,        // mm2
  solidAngle: 0.1,       // sr (geometry dependent)
  deadTimePercent: 0,
  spectrum: null
};

// Complete fluorescence line database
var XRF_LINES = {
  Si: { Z: 14, Ka: 1.740, Kb: 1.836, yield: 0.042 },
  Ti: { Z: 22, Ka: 4.510, Kb: 4.932, yield: 0.219 },
  Cr: { Z: 24, Ka: 5.414, Kb: 5.947, yield: 0.275 },
  Mn: { Z: 25, Ka: 5.899, Kb: 6.490, yield: 0.303 },
  Fe: { Z: 26, Ka: 6.404, Kb: 7.058, yield: 0.332 },
  Co: { Z: 27, Ka: 6.930, Kb: 7.649, yield: 0.360 },
  Ni: { Z: 28, Ka: 7.478, Kb: 8.265, yield: 0.388 },
  Cu: { Z: 29, Ka: 8.048, Kb: 8.905, yield: 0.415 },
  Zn: { Z: 30, Ka: 8.639, Kb: 9.572, yield: 0.442 },
  As: { Z: 33, Ka: 10.544, Kb: 11.726, yield: 0.519 },
  Sr: { Z: 38, Ka: 14.165, Kb: 15.836, yield: 0.630 },
  Zr: { Z: 40, Ka: 15.775, Kb: 17.668, yield: 0.668 },
  Au: { Z: 79, La: 9.713, Lb: 11.443, yield: 0.945 },
  Pt: { Z: 78, La: 9.442, Lb: 11.071, yield: 0.942 },
  Pb: { Z: 82, La: 10.551, Lb: 12.614, yield: 0.950 }
};

// Build a 2048-channel XRF spectrum: Brems/Compton/elastic background plus Ka/Kb/La/Lb Gaussian lines, sqrt(E) resolution.
function simulateSDD(sampleElements, dwell, excitationE) {
  var nCh = SDD_DETECTOR.channels;
  var eRange = SDD_DETECTOR.energyRange;
  var chWidth = eRange / nCh;  // keV per channel
  var spectrum = new Float64Array(nCh);
  var _useE = excitationE || state.energy;
  var flux = 0;
  // sampleFlux() is keyed to state.energy; for off-state excitation energies
  // (energy sweeps) fall through to photonFlux(_useE).
  if ((!excitationE || excitationE === state.energy) && typeof sampleFlux === 'function') {
    flux = sampleFlux();
  }
  if (!flux) { try { flux = photonFlux(_useE); } catch(e) { flux = 0; } }
  if (!flux) flux = 1e10;
  var E0 = _useE;

  // Background: Compton scatter + Bremsstrahlung
  for (var ch = 0; ch < nCh; ch++) {
    var e = ch * chWidth;
    // Bremsstrahlung
    var bg = 50 * Math.exp(-e * 0.3) * dwell;
    // Compton peak (broad)
    var comptonE = E0 / (1 + E0 / 511 * (1 - Math.cos(Math.PI / 2)));
    bg += 200 * dwell * Math.exp(-0.5 * Math.pow(((e - comptonE) / 0.5), 2));
    // Elastic scatter peak
    bg += 500 * dwell * Math.exp(-0.5 * Math.pow(((e - E0) / 0.15), 2));
    spectrum[ch] = poissonSample(Math.max(0, bg));
  }

  // Fluorescence lines
  sampleElements.forEach(function(elem) {
    var lines = XRF_LINES[elem.symbol];
    if (!lines) return;
    var conc = elem.concentration || 1.0;  // weight fraction

    // Energy resolution scales with sqrt(E)
    var resScale = function(e) { return SDD_DETECTOR.resolution / 1000 * Math.sqrt(e / 5.9); };

    var addLine = function(lineE, relIntensity) {
      if (lineE >= E0) return;  // Can't excite above incident energy
      var sigma = resScale(lineE) / 2.355;
      var totalCounts = flux * dwell * conc * lines.yield * relIntensity * SDD_DETECTOR.solidAngle * 1e-6;
      for (var ch = Math.max(0, Math.floor((lineE - 5*sigma) / chWidth));
           ch < Math.min(nCh, Math.ceil((lineE + 5*sigma) / chWidth)); ch++) {
        var e = ch * chWidth;
        var v = totalCounts * Math.exp(-0.5 * Math.pow(((e - lineE) / sigma), 2)) / (sigma * Math.sqrt(2 * Math.PI));
        spectrum[ch] += poissonSample(Math.max(0, v));
      }
    };

    if (lines.Ka) { addLine(lines.Ka, 1.0); addLine(lines.Kb, 0.15); }
    if (lines.La) { addLine(lines.La, 1.0); addLine(lines.Lb, 0.5); }
  });

  // Dead time calculation
  var totalRate = 0;
  spectrum.forEach(function(v) { totalRate += v / dwell; });
  SDD_DETECTOR.deadTimePercent = Math.min(90, totalRate / 1e6 * 100);

  SDD_DETECTOR.spectrum = spectrum;
  return spectrum;
}

// Plot the SDD spectrum as log10 counts vs energy (keV) over its channel width via _drawChart1D.
function renderSDDSpectrum(canvasId, spectrum, elements) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;
  var nCh = spectrum.length;
  var chWidth = SDD_DETECTOR.energyRange / nCh;

  // Build data array (log scale)
  var data = [];
  var maxV = 0;
  for (var i = 10; i < nCh - 10; i++) if (spectrum[i] > maxV) maxV = spectrum[i];

  for (var i = 0; i < nCh; i++) {
    data.push({ x: i * chWidth, y: spectrum[i] > 0 ? Math.log10(spectrum[i] + 1) : 0 });
  }

  if (typeof _drawChart1D === 'function') {
    var logMax = Math.log10(maxV + 1);
    _drawChart1D(cv, data, {
      color: '#4db8ff',
      xlabel: 'Energy (keV)',
      ylabel: 'Counts (log)',
      nTicksX: 6, nTicksY: 5,
      yRange: [0, logMax * 1.1]
    });
  }

  // TODO: Plotly annotations for fluorescence lines could be added
  // For now the element labels are visible in the hover tooltip
}

// ============================================================
//  5. XRF IMAGING (SDD + Raster Scan)
// ============================================================

function simulateXRFMap(params) {
  var xStart = params.x_start || -5;
  var xStop = params.x_stop || 5;
  var yStart = params.y_start || -5;
  var yStop = params.y_stop || 5;
  var nx = params.nx || 41;
  var ny = params.ny || 41;
  var dwell = params.dwell || 0.1;
  var elements = params.elements || [
    {symbol: 'Fe', concentration: 0.3},
    {symbol: 'Cu', concentration: 0.2},
    {symbol: 'Zn', concentration: 0.1}
  ];

  var xStep = (xStop - xStart) / (nx - 1);
  var yStep = (yStop - yStart) / (ny - 1);

  // Create element-specific maps
  var maps = {};
  elements.forEach(function(el) {
    maps[el.symbol] = new Float64Array(nx * ny);
  });
  var totalMap = new Float64Array(nx * ny);

  for (var j = 0; j < ny; j++) {
    for (var i = 0; i < nx; i++) {
      var x = xStart + i * xStep;
      var y = yStart + j * yStep;

      // Simulate spatial distribution of elements
      elements.forEach(function(el, eIdx) {
        var conc = el.concentration;
        // Spatial features
        if (el.symbol === 'Fe') {
          // Iron: concentrated in a ring structure
          var r = Math.sqrt(x*x + y*y);
          conc *= (0.3 + 0.7 * Math.exp(0-Math.pow(((r - 2) / 0.8), 2)));
          // Hot spot
          conc += 0.5 * Math.exp(0-(Math.pow((x-1), 2) + Math.pow((y+1), 2)) / 0.5);
        } else if (el.symbol === 'Cu') {
          // Copper: linear gradient + particle
          conc *= (0.5 + 0.5 * (x - xStart) / (xStop - xStart));
          conc += 0.8 * Math.exp(0-(Math.pow((x+2), 2) + Math.pow((y-2), 2)) / 0.3);
        } else if (el.symbol === 'Zn') {
          // Zinc: scattered particles
          conc *= 0.2;
          for (var p = 0; p < 5; p++) {
            var px = Math.sin(p * 1.7) * 3;
            var py = Math.cos(p * 2.3) * 3;
            conc += 0.6 * Math.exp(0-(Math.pow((x-px), 2) + Math.pow((y-py), 2)) / 0.2);
          }
        }

        // Simulate fluorescence counts
        var flux = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
        if (!flux) flux = 1e10;
        var lines = XRF_LINES[el.symbol];
        var counts = flux * dwell * conc * (lines ? lines.yield : 0.3) * SDD_DETECTOR.solidAngle * 1e-6;
        var measured = poissonSample(Math.max(0, counts));

        maps[el.symbol][j * nx + i] = measured;
        totalMap[j * nx + i] += measured;
      });
    }
  }

  return { maps: maps, totalMap: totalMap, nx: nx, ny: ny, xStart: xStart, xStop: xStop, yStart: yStart, yStop: yStop, elements: elements };
}

// Build canvases for the total and per-element maps then draw each as a colored heatmap after a 20ms timeout.
function renderXRFMaps(containerId, result) {
  var container = document.getElementById(containerId);
  if (!container) return;
  var maps = result.maps;
  var totalMap = result.totalMap;
  var nx = result.nx;
  var ny = result.ny;
  var elements = result.elements;

  var h = '<div style="display:flex;flex-wrap:wrap;gap:4px">';

  // Total map
  h += '<div><div style="font-size:8px;color:var(--t2);text-align:center">Total</div>' +
    '<canvas id="xrfMapTotal" width="120" height="120"></canvas></div>';

  // Element maps
  elements.forEach(function(el) {
    h += '<div><div style="font-size:8px;color:var(--am);text-align:center">' + el.symbol + '</div>' +
      '<canvas id="xrfMap_' + el.symbol + '" width="120" height="120"></canvas></div>';
  });
  h += '</div>';
  container.innerHTML = h;

  setTimeout(function() {
    drawHeatmap('xrfMapTotal', totalMap, nx, ny, 'viridis');
    elements.forEach(function(el) {
      var colors = {Fe: 'red', Cu: 'green', Zn: 'blue', Ni: 'cyan', Ti: 'magenta', Au: 'gold'};
      drawHeatmap('xrfMap_' + el.symbol, maps[el.symbol], nx, ny, colors[el.symbol] || 'viridis');
    });
  }, 20);
}

// Reshape a flat nx*ny array to 2D and render via _drawHeatmap2D using a named colormap (red/green/blue/gold/viridis).
function drawHeatmap(canvasId, data, nx, ny, colorScheme) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;

  // Build 2D array
  var z = [];
  for (var y = 0; y < ny; y++) {
    var row = [];
    for (var x = 0; x < nx; x++) {
      row.push(data[y * nx + x]);
    }
    z.push(row);
  }

  var colorMap;
  if (colorScheme === 'red') colorMap = [[0,'rgb(0,0,0)'],[1,'rgb(255,50,0)']];
  else if (colorScheme === 'green') colorMap = [[0,'rgb(0,0,0)'],[1,'rgb(0,255,50)']];
  else if (colorScheme === 'blue') colorMap = [[0,'rgb(0,0,0)'],[1,'rgb(50,100,255)']];
  else if (colorScheme === 'gold') colorMap = [[0,'rgb(0,0,0)'],[1,'rgb(255,200,0)']];
  else colorMap = [[0,'rgb(68,1,84)'],[0.25,'rgb(59,82,139)'],[0.5,'rgb(33,145,140)'],[0.75,'rgb(94,201,98)'],[1,'rgb(253,231,37)']];

  if (typeof _drawHeatmap2D === 'function') {
    _drawHeatmap2D(cv, z, {
      width: cv.width || 120, height: cv.height || 120,
      showColorbar: false,
      colorscale: colorMap
    });
  }
}

// ============================================================
//  6. VIRTUAL EXPERIMENT PRESETS
// ============================================================

var VIRTUAL_EXPERIMENTS = [
  {
    id: 'cu_xanes',
    name: 'Cu K-edge XANES',
    icon: '[S]',
    description: 'Cu K-edge XANES measurement -- electronic structure analysis',
    category: 'spectroscopy',
    setup: {
      energy: 8.979,
      material: 'Cu',
      technique: 'xanes',
      plan: 'xanes_scan',
      params: { element: 'Cu', edge: 'K', pre_start: -150, k_max: 12 }
    },
    guide: [
      '1. Set energy to Cu K-edge (8.979 keV)',
      '2. DCM automatically calculates Bragg angle',
      '3. IVU gap adjusts to optimal harmonic',
      '4. Start XANES scan to collect µ(E) spectrum',
      '5. Sequentially measure Pre-edge -> Edge -> EXANES regions'
    ]
  },
  {
    id: 'xrf_imaging',
    name: 'XRF Elemental Mapping',
    icon: '[M]',
    description: 'Nano XRF imaging with SDD detector -- elemental distribution analysis',
    category: 'imaging',
    setup: {
      energy: 12.0,
      technique: 'xrf_map',
      elements: [{symbol:'Fe',concentration:0.3},{symbol:'Cu',concentration:0.2},{symbol:'Zn',concentration:0.1}],
      params: { x_start:-5, x_stop:5, y_start:-5, y_stop:5, nx:41, ny:41, dwell:0.1 }
    },
    guide: [
      '1. Set excitation energy to 12 keV (excites Fe, Cu, Zn K lines)',
      '2. SDD is positioned at 90 deg to sample to collect fluorescence X-rays',
      '3. Sample stage performs X-Y raster scan',
      '4. XRF spectrum collected at each position',
      '5. Elemental fluorescence intensity maps are generated'
    ]
  },
  {
    id: 'powder_xrd',
    name: 'Powder XRD',
    icon: '[D]',
    description: 'Powder diffraction pattern measurement with Eiger 2X',
    category: 'diffraction',
    setup: {
      energy: 15.0,
      material: 'Cu',
      technique: 'powder_xrd',
      params: { dwell: 1.0, detector_dist: 200 }
    },
    guide: [
      '1. Set energy to 15 keV',
      '2. Eiger 2X is positioned behind the sample (200mm)',
      '3. Collect Debye-Scherrer ring pattern with a single exposure',
      '4. Obtain 1D diffraction pattern via radial integration',
      '5. Analyze lattice constants and crystal structure'
    ]
  },
  {
    id: 'nano_xrf_line',
    name: 'Nano XRF Line Scan',
    icon: '[L]',
    description: 'Elemental distribution measurement across sample with nanobeam',
    category: 'imaging',
    setup: {
      energy: 10.0,
      technique: 'xrf_line',
      elements: [{symbol:'Fe',concentration:0.5},{symbol:'Ni',concentration:0.3}],
      params: { start: -3, stop: 3, num: 61, dwell: 0.2 }
    },
    guide: [
      '1. Form nanobeam (~50 nm) with KB mirrors',
      '2. Scan sample in one direction',
      '3. SDD collects XRF spectrum at each position',
      '4. Elemental line profiles are generated',
      '5. Analyze interface structures, particle distributions, etc.'
    ]
  },
  {
    id: 'xrf_2d_map',
    name: '2D XRF Elemental Mapping',
    icon: '[2D]',
    description: '2D raster scan with nanobeam -- generate elemental distribution map',
    category: 'imaging',
    setup: {
      energy: 12.0,
      technique: 'xrf_2d_map',
      elements: [{symbol:'Fe',concentration:0.3},{symbol:'Cu',concentration:0.2},{symbol:'Zn',concentration:0.1}],
      plan: 'raster_scan',
      params: { x_start:-5, x_stop:5, y_start:-5, y_stop:5, x_num:41, y_num:41, dwell:0.1 }
    },
    guide: [
      '1. Set excitation energy above target element K-edge',
      '2. Form nanobeam (~50 nm) with KB mirrors',
      '3. Sample stage performs X-Y 2D raster scan',
      '4. SDD collects XRF spectrum at each position',
      '5. 2D elemental fluorescence intensity maps are generated'
    ]
  },
  {
    id: 'xrd_2d_map',
    name: '2D XRD Mapping',
    icon: '[XRD]',
    description: '2D raster scan with Eiger 2X -- collect diffraction pattern per position',
    category: 'diffraction',
    setup: {
      energy: 15.0,
      technique: 'xrd_2d_map',
      plan: 'raster_scan',
      params: { x_start:-5, x_stop:5, y_start:-5, y_stop:5, x_num:21, y_num:21, dwell:1.0, detector_dist:200 }
    },
    guide: [
      '1. Set energy to 15 keV',
      '2. Eiger 2X is positioned 200mm behind the sample',
      '3. Sample stage performs X-Y 2D raster scan',
      '4. Collect Debye-Scherrer ring pattern at each position',
      '5. Generate maps of crystal phase, strain, and texture distribution per position'
    ]
  }
];

// ESM bridge: expose module-scoped vars to globalThis
if(typeof EIGER2X!=="undefined")globalThis.EIGER2X=EIGER2X;
if(typeof SDD_DETECTOR!=="undefined")globalThis.SDD_DETECTOR=SDD_DETECTOR;
if(typeof VIRTUAL_EXPERIMENTS!=="undefined")globalThis.VIRTUAL_EXPERIMENTS=VIRTUAL_EXPERIMENTS;
if(typeof XRF_LINES!=="undefined")globalThis.XRF_LINES=XRF_LINES;
if(typeof drawHeatmap!=="undefined")globalThis.drawHeatmap=drawHeatmap;
if(typeof drawSingleProfile!=="undefined")globalThis.drawSingleProfile=drawSingleProfile;
if(typeof niceScaleNm!=="undefined")globalThis.niceScaleNm=niceScaleNm;
if(typeof poissonSample!=="undefined")globalThis.poissonSample=poissonSample;
if(typeof renderEigerImage!=="undefined")globalThis.renderEigerImage=renderEigerImage;
if(typeof renderSDDSpectrum!=="undefined")globalThis.renderSDDSpectrum=renderSDDSpectrum;
if(typeof renderXRFMaps!=="undefined")globalThis.renderXRFMaps=renderXRFMaps;
if(typeof simulateEiger2X!=="undefined")globalThis.simulateEiger2X=simulateEiger2X;
if(typeof simulateSDD!=="undefined")globalThis.simulateSDD=simulateSDD;
if(typeof simulateXRFMap!=="undefined")globalThis.simulateXRFMap=simulateXRFMap;
