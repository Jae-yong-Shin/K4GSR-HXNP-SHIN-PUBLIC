'use strict';
// ===== raytrace/04_propagation_ui.js — Beam Profile UI + EPICS tab =====
// @module raytrace/04_propagation_ui
// @exports BP_MAX_MAIN, BP_MIN_MAIN, BP_SIDE_RATIO, _renderTrendPopupChart, _trendPopupOpen, _trendPopupTimer, appendBeamProfileToModal, niceScaleAuto, renderBeamProfileAt, renderBeamProfileCanvas, renderDetectorScreen, renderEpicsTabV2, renderTrendChartV2, setTrendPVPopup, showPropagationLog, ...
// MC-only beam profiles at any optical component
// Provides: appendBeamProfileToModal, showPropagationLog, renderBeamProfileAt,
//   niceScaleAuto, renderEpicsTabV2, renderTrendChartV2

// ============================================================
//  NICE SCALE BAR
// ============================================================
function niceScaleAuto(totalFov, isNano) {
  var targets = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
  var ideal = totalFov * 0.25;
  var best = targets[0];
  for (var _ti = 0; _ti < targets.length; _ti++) { var t = targets[_ti]; if (Math.abs(t - ideal) < Math.abs(best - ideal)) best = t; }
  var unit = isNano ? 'nm' : '\u03BCm';
  if (!isNano && best >= 1000) return { v: best, l: (best / 1000).toFixed(best >= 10000 ? 0 : 1) + ' mm' };
  return { v: best, l: best + ' ' + unit };
}

// ============================================================
//  COMPONENT MODAL: Beam Profile Section
// ============================================================
function appendBeamProfileToModal(compId, distance, containerEl) {
  var mb = containerEl || document.getElementById('modalBody');
  if (!mb) return;

  var div = document.createElement('div');
  div.className = 'mc';
  div.innerHTML = '<h4 style="margin-bottom:6px">Beam Profile @ ' + distance.toFixed(2) + ' m</h4>' +
    '<div style="display:flex;gap:3px;margin-bottom:6px">' +
      '<button class="sb" style="font-size:9px;padding:3px 8px" onclick="renderBeamProfileAt(\'beamProfile_' + compId + '\',' + distance + ')">Refresh</button>' +
      '<button class="sb" style="font-size:9px;padding:3px 8px;background:var(--s2);color:var(--t2)" onclick="showPropagationLog(\'' + compId + '\',' + distance + ')">Propagation Log</button>' +
    '</div>' +
    '<div id="beamProfile_' + compId + '"></div>';
  mb.appendChild(div);

  var comp = null;
  for (var i = 0; i < CD.length; i++) { if (CD[i].id === compId) { comp = CD[i]; break; } }
  var opts = {};
  if (comp && comp.tp === 'slit') {
    opts.showSlit = true;
    if (compId === 'wbslit') {
      opts.slitH = state.wbH * 0.5e-3;
      opts.slitV = state.wbV * 0.5e-3;
    } else if (compId === 'ssa') {
      opts.slitH = state.ssaH * 0.5e-6;
      opts.slitV = state.ssaV * 0.5e-6;
    }
  }

  setTimeout(function() {
    renderBeamProfileAt('beamProfile_' + compId, distance, opts);
  }, 60);
}

// ============================================================
//  PROPAGATION LOG  (MC-synced, 2026-06-10)
// ============================================================
// Per-element cumulative flux/size now come from the MC ray trace
// (mcRayTrace elementTrace snapshots) \u2014 the analytic propagateBeam chain
// lacks M1/M2 secondary-source focusing and over-clips at the SSA by
// ~300x, so its element fluxes must not be displayed. Element flux =
// sourceFlux(E) x _dcmBandFix(E) x T_cum (same normalisation as
// photonFlux/sampleFlux, so the final row matches the live header).
function showPropagationLog(compId, distance) {
  var E = state.energy;
  // Reuse the cached sample-plane trace when it covers the request;
  // otherwise run a lighter fresh trace to the requested distance.
  var mc = (typeof _mcSampleCache !== 'undefined' && _mcSampleCache &&
            _mcSampleCache.elementTrace && _mcSampleCache.elementTrace.length &&
            distance <= (pos('sample') + 0.01)) ? _mcSampleCache : null;
  if (!mc) {
    try { mc = mcRayTrace(distance, 30000); } catch (e) { mc = null; }
  }
  var trace = (mc && mc.elementTrace) ? mc.elementTrace : [];
  var seed = 0;
  try {
    seed = sourceFlux(E) * ((typeof _dcmBandFix === 'function') ? _dcmBandFix(E) : 1);
  } catch (e2) {}

  var html = '<div style="max-height:200px;overflow-y:auto"><table class="cmp-table"><tr><th>Position</th><th>Name</th><th>T<sub>cum</sub></th><th>H FWHM</th><th>V FWHM</th><th>Flux</th></tr>';
  for (var i = 0; i < trace.length; i++) {
    var el = trace[i];
    if (el.dist > distance + 1e-9) break;
    var hum = el.sigH * 2.355e6;
    var vum = el.sigV * 2.355e6;
    var hLabel = hum < 1 ? (hum * 1000).toFixed(0) + ' nm' : hum.toFixed(1) + ' \u03BCm';
    var vLabel = vum < 1 ? (vum * 1000).toFixed(0) + ' nm' : vum.toFixed(1) + ' \u03BCm';
    var fluxStr = (seed > 0) ? (seed * el.T_cum).toExponential(1) : '--';
    html += '<tr><td>' + el.dist.toFixed(1) + 'm</td><td style="color:var(--ac)">' + el.name + '</td><td style="color:var(--t3)">' + el.T_cum.toExponential(2) + '</td><td>' + hLabel + '</td><td>' + vLabel + '</td><td>' + fluxStr + '</td></tr>';
  }
  // Final row: focused sample-plane value from the single sampleFlux() API
  // (tag=3 focused-only weights) \u2014 matches the live "Flux:" header exactly.
  if (distance >= (pos('sample') - 0.5) && mc && mc.fwhmH) {
    var sFlux = (typeof sampleFlux === 'function') ? sampleFlux() : 0;
    html += '<tr style="font-weight:600"><td>' + pos('sample').toFixed(1) + 'm</td>' +
      '<td style="color:var(--gn)">Sample (KB focus)</td><td style="color:var(--t3)">focused</td>' +
      '<td>' + (mc.fwhmH * 1e9).toFixed(0) + ' nm</td><td>' + (mc.fwhmV * 1e9).toFixed(0) + ' nm</td>' +
      '<td style="color:var(--gn)">' + (sFlux > 0 ? sFlux.toExponential(1) : '--') + '</td></tr>';
  }
  html += '</table></div>';
  html += '<div style="margin-top:6px;font-size:9px;color:var(--t3)">Target: ' + distance.toFixed(2) +
    'm | MC trace: ' + (mc ? (mc.nSurvived + '/' + mc.nTotal + ' rays alive') : 'unavailable') +
    ' | Flux = SPECTRA seed \u00D7 band fix \u00D7 T<sub>cum</sub> (MC)</div>';
  openModal('Beam Propagation Log: ' + compId, html);
}

// ============================================================
//  EPICS TAB
// ============================================================
function renderEpicsTabV2() {
  var pane = document.getElementById('tab-epics');
  if (!pane) return;

  pane.innerHTML =
    '<div class="ctrl-group" id="epicsStatus" style="text-align:center;padding:6px;font-size:9px;margin:0 0 6px 0"></div>' +
    '<div class="ctrl-group" id="epicsStats" style="font-size:8px;margin:0 0 6px 0"></div>' +
    '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">QUICK CAPUT</h4>' +
      '<div class="ctrl-group" style="margin:0">' +
      '<select id="caputPvSelect" style="font-size:8px;margin-bottom:3px" onchange="caputSelectChanged()">' +
        '<option value="">&mdash; PV &mdash;</option>' +
      '</select>' +
      '<div style="display:flex;gap:2px">' +
        '<input type="number" id="caputValue" step="any" style="flex:1;font-size:9px;padding:3px" placeholder="value"/>' +
        '<button class="sb" onclick="executeCaput()" style="font-size:8px;padding:3px 8px">PUT</button>' +
      '</div>' +
      '<div id="caputHistory" style="margin-top:3px;font-size:8px;color:var(--t3-bright);max-height:30px;overflow-y:auto"></div>' +
    '</div></div>' +
    '<div class="ctrl-group" style="display:flex;gap:4px;margin:0 0 6px 0">' +
      '<button class="sb" onclick="toggleTrendPopup()" style="flex:1;font-size:9px;padding:4px 0;background:var(--s2);color:var(--ac)">PV Trend Chart</button>' +
      '<button class="sb" onclick="showPVConnectionStatus()" style="flex:1;font-size:9px;padding:4px 0;background:var(--s2);color:var(--gn)">Connection Status</button>' +
    '</div>' +
    '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">PV MONITOR <span style="color:var(--ac);cursor:pointer;font-size:8px" onclick="renderPVMonitor()">&#x27F3;</span></h4>' +
      '<div class="ctrl-group" style="margin:0">' +
      '<div id="pvMonitorBody" style="max-height:200px;overflow-y:auto;font-family:var(--mn)"></div>' +
    '</div></div>' +
    '<div style="margin-bottom:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">SETUP GUIDE</h4>' +
      '<div class="ctrl-group" style="margin:0">' +
      '<div style="font-size:8px;color:var(--t3-bright);line-height:1.5">' +
        'Mode: Virtual/Real/Dual tabs<br>' +
        'Real mode &rarr; auto-connect WS<br>' +
        'Server: ws://host:8001' +
      '</div>' +
    '</div></div>';

  populateCaputSelect();
  updateEpicsUI();
}

// ============================================================
//  PV TREND POPUP
// ============================================================
var _trendPopupOpen = false;
// Holds the setInterval handle for the periodic 2s trend-chart redraw; null when no timer is running.
var _trendPopupTimer = null;

// Open/close the PV trend popup: toggle open flag and class, fill PV select, draw chart, start 2s refresh timer, make resizable.
window.toggleTrendPopup = function() {
  var el = document.getElementById('pvTrendPopup');
  if (!el) return;
  _trendPopupOpen = !_trendPopupOpen;
  el.classList.toggle('open', _trendPopupOpen);
  if (_trendPopupOpen) {
    // Populate PV selector inside popup
    var sel = document.getElementById('trendPopupPvSelect');
    if (sel) {
      var h = '';
      PV_ARCHIVE.watching.forEach(function(pv) {
        var short = pv.replace('BL10:', '');
        h += '<option value="' + pv + '"' +
          (pv === trendPV ? ' selected' : '') +
          '>' + short + '</option>';
      });
      sel.innerHTML = h;
    }
    _renderTrendPopupChart();
    if (!_trendPopupTimer) _trendPopupTimer = setInterval(_renderTrendPopupChart, 2000);
    if (!el._resizeAdded) {
      el.style.position = 'fixed';
      var hdr = document.getElementById('pvTrendPopupHdr');
      window._makePopupResizable(el, {
        dragEl: hdr, minWidth: 360, minHeight: 220,
        onResize: function() { _renderTrendPopupChart(); }
      });
      el._resizeAdded = true;
    }
  } else {
    if (_trendPopupTimer) { clearInterval(_trendPopupTimer); _trendPopupTimer = null; }
  }
};

// Set the active trend PV, update the popup label (BL10: stripped), and redraw the chart.
window.setTrendPVPopup = function(pv) {
  trendPV = pv;
  var lbl = document.getElementById('trendPopupPVLabel');
  if (lbl) lbl.textContent = pv.replace('BL10:', '');
  _renderTrendPopupChart();
};

// Draw the selected PV's archived trace on the popup canvas via _drawChart1D; x is seconds-since-start formatted m:ss.
function _renderTrendPopupChart() {
  if (!_trendPopupOpen) return;
  var cv = document.getElementById('trendPopupCanvas');
  if (!cv) return;
  var trace = PV_ARCHIVE.traces[trendPV];
  if (!trace || trace.length < 2) return;
  if (typeof _drawChart1D !== 'function') return;

  // Update label
  var lbl = document.getElementById('trendPopupPVLabel');
  if (lbl) lbl.textContent = trendPV.replace('BL10:', '');

  // Update current value
  var valEl = document.getElementById('trendPopupCurVal');
  if (valEl && trace.length > 0) {
    var last = trace[trace.length - 1];
    valEl.textContent = last.v.toFixed(4);
  }

  var chartData = [];
  var t0 = trace[0].t;
  for (var i = 0; i < trace.length; i++) {
    chartData.push({ x: (trace[i].t - t0) / 1000, y: trace[i].v });
  }

  function timeFmt(v) {
    var sec = Math.round(v);
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Use canvas fallback (uPlot has sizing issues with CSS zoom on popup)
  // Use clientWidth/Height (CSS layout size, zoom-independent) -- NOT getBoundingClientRect (zoom-doubled)
  var wrap = cv.parentElement;
  var wOpts = {
    color: '#4db8ff',
    xlabel: 'Time',
    ylabel: '',
    title: '',
    nTicksX: 6, nTicksY: 6,
    xFmt: timeFmt,
    hover: true,
    useCanvas: true
  };
  if (wrap) {
    var ww = wrap.clientWidth, wh = wrap.clientHeight;
    if (ww > 0 && wh > 0) {
      wOpts.width = ww;
      wOpts.height = wh;
    }
  }
  _drawChart1D(cv, chartData, wOpts);
}

// Keep old function name for periodic updates from 05_epics_ui.js
function renderTrendChartV2() {
  _renderTrendPopupChart();
}

// ============================================================
//  MC-BASED BEAM PROFILE RENDERER (RESPONSIVE)
//  Layout:  [ 2D Beam Profile ] [ V line profile ]
//           [ H line profile  ] [ Detail info     ]
//  Sizes dynamically computed from container width.
// ============================================================
var BP_SIDE_RATIO = 0.22;  // side panel = 22% of main profile size
var BP_MIN_MAIN = 160;     // minimum main profile size
var BP_MAX_MAIN = 500;     // maximum main profile size

// Convenience wrapper: render the MC beam profile at the sample position.
window.renderBeamProfileCanvas = function(cid) {
  renderBeamProfileAt(cid, pos('sample'));
};

// ============================================================
//  DETECTOR SCREEN: 4-beam KB visualization with 2theta offset
//  Renders color-coded beams: direct(gray), V-only(orange),
//  H-only(cyan), focused(green)
// ============================================================
window.renderDetectorScreen = function(cid, dist) {
  var el = document.getElementById(cid);
  if (!el) return;

  el.innerHTML = '<div style="color:var(--t3);font-size:9px;padding:8px">MC ray tracing for detector...</div>';

  setTimeout(function() {
    try {
      var mc = mcRayTrace(dist);
      var al = mc._aliveRays;
      if (!al || al.length < 10) {
        el.innerHTML = '<div style="color:var(--rd);font-size:9px;padding:8px">Not enough rays at detector (' + (al ? al.length : 0) + ')</div>';
        return;
      }

      // KB 2theta offsets (real KB deflects reflected beam by 2*pitch)
      var kbvPos = pos('kbv') || 149.69;
      var kbhPos = pos('kbh') || 149.9;
      var twoThV = 2 * (state.kbvpitch || 3.0) * 1e-3;  // rad
      var twoThH = 2 * (state.kbhpitch || 3.0) * 1e-3;  // rad
      var dxKB = twoThH * (dist - kbhPos);  // m, H offset for KB-H reflected
      var dyKB = twoThV * (dist - kbvPos);  // m, V offset for KB-V reflected

      // Separate rays by tag and apply 2theta offset
      var rays4 = [[], [], [], []];
      var maxExt = 0;
      for (var i = 0; i < al.length; i++) {
        var r = al[i];
        var tag = (typeof r.tag === 'number') ? r.tag : 0;
        var ox = (tag & 2) ? dxKB : 0;
        var oy = (tag & 1) ? dyKB : 0;
        var px = r.x + ox;
        var py = r.y + oy;
        if (tag >= 0 && tag < 4) rays4[tag].push({x: px, y: py, w: r.w});
        var ax = Math.abs(px), ay = Math.abs(py);
        if (ax > maxExt) maxExt = ax;
        if (ay > maxExt) maxExt = ay;
      }

      var fov = Math.max(maxExt * 1.3, 1e-3);

      // Canvas size
      var containerW = el.parentElement ? el.parentElement.clientWidth - 24 : 400;
      var s = Math.min(480, Math.max(200, containerW - 10));

      // Build per-beam histograms
      var G = 201;
      var beamHists = [];
      var tagNames = ['Direct', 'V-only', 'H-only', 'Focused'];
      var tagColors = ['#808080', '#ffa040', '#40c0ff', '#40d89a'];
      var globalMax = 0;

      for (var t = 0; t < 4; t++) {
        var h = new Float64Array(G * G);
        var bMax = 0;
        for (var ri = 0; ri < rays4[t].length; ri++) {
          var xi = Math.floor((rays4[t][ri].x + fov) / (2 * fov) * G);
          var yi = Math.floor((rays4[t][ri].y + fov) / (2 * fov) * G);
          if (xi >= 0 && xi < G && yi >= 0 && yi < G) {
            h[yi * G + xi] += rays4[t][ri].w;
            if (h[yi * G + xi] > bMax) bMax = h[yi * G + xi];
          }
        }
        beamHists.push({hist: h, max: bMax});
        if (bMax > globalMax) globalMax = bMax;
      }
      if (globalMax < 1e-30) globalMax = 1;

      // Legend
      var legendHtml = '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px;font-size:9px;font-family:var(--mn)">';
      for (var t = 0; t < 4; t++) {
        legendHtml += '<span style="color:' + tagColors[t] + '">' +
          '<span style="display:inline-block;width:8px;height:8px;background:' + tagColors[t] +
          ';border-radius:1px;margin-right:3px;vertical-align:middle"></span>' +
          tagNames[t] + ' (' + rays4[t].length + ')</span>';
      }
      legendHtml += '</div>';

      el.innerHTML = legendHtml +
        '<canvas id="' + cid + '_cv" style="display:block;border-radius:3px;cursor:crosshair"></canvas>';

      // Render
      setTimeout(function() {
        var cv = document.getElementById(cid + '_cv');
        if (!cv) return;

        var dpr = Math.max(2, window.devicePixelRatio || 1);
        cv.width = s * dpr; cv.height = s * dpr;
        cv.style.width = s + 'px'; cv.style.height = s + 'px';
        var ctx = cv.getContext('2d');

        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, s * dpr, s * dpr);

        var imgW = s * dpr, imgH = s * dpr;
        var img = ctx.createImageData(imgW, imgH);

        // Per-beam RGB
        var bRGB = [
          [128, 128, 128],  // direct: gray
          [255, 160, 64],   // V-only: orange
          [64, 192, 255],   // H-only: cyan
          [64, 216, 154]    // focused: green
        ];

        for (var py = 0; py < imgH; py++) {
          var gy = Math.floor(py / imgH * G);
          for (var px = 0; px < imgW; px++) {
            var gx = Math.floor(px / imgW * G);
            var rr = 0, gg = 0, bb = 0;
            for (var t = 0; t < 4; t++) {
              var v = beamHists[t].hist[gy * G + gx] / globalMax;
              if (v > 0) {
                var intensity = Math.pow(v, 0.3);
                rr += bRGB[t][0] * intensity;
                gg += bRGB[t][1] * intensity;
                bb += bRGB[t][2] * intensity;
              }
            }
            var idx = (py * imgW + px) * 4;
            img.data[idx] = Math.min(255, Math.round(rr));
            img.data[idx + 1] = Math.min(255, Math.round(gg));
            img.data[idx + 2] = Math.min(255, Math.round(bb));
            img.data[idx + 3] = 255;
          }
        }
        ctx.putImageData(img, 0, 0);

        // Overlay
        ctx.save();
        ctx.scale(dpr, dpr);

        // Crosshair at direct beam center
        ctx.strokeStyle = 'rgba(255,255,255,0.1)';
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 4]);
        // Direct beam center in pixel coordinates
        var cxPx = (0 + fov) / (2 * fov) * s;
        var cyPx = (0 + fov) / (2 * fov) * s;
        ctx.beginPath();
        ctx.moveTo(cxPx, 0); ctx.lineTo(cxPx, s);
        ctx.moveTo(0, cyPx); ctx.lineTo(s, cyPx);
        ctx.stroke();
        ctx.setLineDash([]);

        // Scale bar (mm)
        var totalFov_mm = fov * 2e3;
        var scTgt = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50];
        var scIdeal = totalFov_mm * 0.25;
        var scBest = scTgt[0];
        for (var si = 0; si < scTgt.length; si++) {
          if (Math.abs(scTgt[si] - scIdeal) < Math.abs(scBest - scIdeal)) scBest = scTgt[si];
        }
        var barPx = scBest / totalFov_mm * s;
        ctx.fillStyle = '#fff';
        ctx.fillRect(6, s - 10, barPx, 1.5);
        ctx.font = 'bold 8px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(scBest + ' mm', 6, s - 13);

        // Info labels
        ctx.fillStyle = 'rgba(255,255,255,0.5)';
        ctx.font = '7px monospace';
        ctx.fillText('2th_H=' + (twoThH * 1e3).toFixed(1) + 'mrad  dx=' + (dxKB * 1e3).toFixed(1) + 'mm', 4, 10);
        ctx.fillText('2th_V=' + (twoThV * 1e3).toFixed(1) + 'mrad  dy=' + (dyKB * 1e3).toFixed(1) + 'mm', 4, 20);

        ctx.fillStyle = 'rgba(77,184,255,0.7)';
        ctx.textAlign = 'right';
        ctx.fillText(al.length + ' rays total', s - 4, 10);
        ctx.fillText('FOV ' + totalFov_mm.toFixed(1) + ' mm', s - 4, 20);

        ctx.restore();

        // Beam statistics panel
        var statsEl = document.getElementById('detBeamStats');
        if (statsEl) {
          var shtml = '';
          for (var t = 0; t < 4; t++) {
            var pct = al.length > 0 ? (rays4[t].length / al.length * 100).toFixed(1) : '0';
            shtml += '<div class="info-item"><div class="lbl" style="color:' + tagColors[t] + '">' +
              tagNames[t] + '</div><div class="val">' + rays4[t].length + ' (' + pct + '%)</div></div>';
          }
          shtml += '<div class="info-item"><div class="lbl">H offset</div><div class="val">' + (dxKB * 1e3).toFixed(1) + ' mm</div></div>';
          shtml += '<div class="info-item"><div class="lbl">V offset</div><div class="val">' + (dyKB * 1e3).toFixed(1) + ' mm</div></div>';
          shtml += '<div class="info-item"><div class="lbl">Pixel (CCD)</div><div class="val">6.5 um</div></div>';
          shtml += '<div class="info-item"><div class="lbl">Throughput</div><div class="val">' +
            (al.length / mc.nTotal * 100).toFixed(1) + '%</div></div>';
          // Focused FWHM from sample cache
          if (typeof _mcSampleCache !== 'undefined' && _mcSampleCache && _mcSampleCache.fwhmH) {
            shtml += '<div class="info-item"><div class="lbl">Focus @sample</div><div class="val" style="color:var(--gn)">' +
              (_mcSampleCache.fwhmH * 1e9).toFixed(1) + ' x ' + (_mcSampleCache.fwhmV * 1e9).toFixed(1) + ' nm</div></div>';
          }
          statsEl.innerHTML = shtml;
        }
      }, 30);
    } catch(e) {
      el.innerHTML = '<div style="color:var(--rd);font-size:9px;padding:8px">Error: ' + e.message + '</div>';
    }
  }, 20);
};

// MC ray-trace at a distance and render 2D + H/V line profiles plus detail (FWHM nm/um/mm, throughput, FOV um).
window.renderBeamProfileAt = function(cid, dist, opts) {
  opts = opts || {};
  var el = document.getElementById(cid);
  if (!el) return;

  // Compute available width from container
  var containerW = el.parentElement ? el.parentElement.clientWidth - 24 : 400;
  var existCv = document.getElementById(cid + '_mc2d');
  var isRefresh = !!existCv;

  // Responsive: fill container, respecting min/max
  var totalW = opts.width || containerW;
  if (totalW < BP_MIN_MAIN + 40) totalW = BP_MIN_MAIN + 40;
  // main + side = totalW with gap
  var side = Math.max(50, Math.min(100, Math.round(totalW * BP_SIDE_RATIO)));
  var s = Math.min(BP_MAX_MAIN, Math.max(BP_MIN_MAIN, totalW - side - 3));
  // Recalculate side based on actual main size
  side = Math.max(50, totalW - s - 3);
  if (side > 120) side = 120;

  if (isRefresh) s = existCv.clientWidth || s;

  var isWB = dist < (pos('dcm') || 32);

  function _compute() {
    var mc = mcRayTrace(dist);
    var isNm = mc.fwhmH < 1e-6;
    var u = isNm ? 'nm' : (mc.fwhmH < 1e-3 ? 'um' : 'mm');
    var mH = u === 'nm' ? mc.fwhmH * 1e9 : (u === 'mm' ? mc.fwhmH * 1e3 : mc.fwhmH * 1e6);
    var mV = u === 'nm' ? mc.fwhmV * 1e9 : (u === 'mm' ? mc.fwhmV * 1e3 : mc.fwhmV * 1e6);
    var sv = mc.nTotal > 0 ? (mc.nSurvived / mc.nTotal * 100).toFixed(1) : '0';
    return {mc: mc, isNm: isNm, u: u, mH: mH, mV: mV, sv: sv};
  }

  function _drawCanvases(d) {
    if (typeof drawMCHist2D === 'function') drawMCHist2D(cid + '_mc2d', d.mc, s);
    if (typeof drawLineProfileH === 'function') drawLineProfileH(cid + '_profH', d.mc, s, side);
    if (typeof drawLineProfileV === 'function') drawLineProfileV(cid + '_profV', d.mc, side, s);
  }

  function _updateDetail(d) {
    var de = document.getElementById(cid + '_detail');
    if (!de) return;
    var u = d.u;
    de.innerHTML =
      '<div style="font-size:8px;color:var(--t3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">Beam Size</div>' +
      '<div style="color:#4db8ff;font-size:11px">H <b>' + d.mH.toFixed(1) + '</b> ' + u + '</div>' +
      '<div style="color:#ffa040;font-size:11px">V <b>' + d.mV.toFixed(1) + '</b> ' + u + '</div>' +
      '<div style="color:var(--t3);margin-top:6px;font-size:9px;border-top:1px solid var(--b0);padding-top:4px">' +
        '<div>' + d.sv + '% throughput</div>' +
        '<div>' + (d.mc.nSurvived || 0) + ' / ' + (d.mc.nTotal || 0) + '</div>' +
        '<div style="margin-top:2px">FOV: ' + (d.mc.fovH * 2e6).toFixed(1) + ' um</div>' +
      '</div>';
  }

  if (isRefresh) {
    setTimeout(function() {
      try {
        var d = _compute();
        var hdr = el.querySelector('[data-bp="type"]');
        if (hdr) {
          hdr.textContent = isWB
            ? 'White Beam @ ' + dist.toFixed(1) + ' m'
            : 'Mono ' + state.energy.toFixed(1) + ' keV @ ' + dist.toFixed(1) + ' m';
        }
        _drawCanvases(d);
        _updateDetail(d);
      } catch(e) {}
    }, 20);
    return;
  }

  // First render
  el.innerHTML = '<div style="color:var(--t3);font-size:9px;padding:8px">MC ray tracing...</div>';
  setTimeout(function() {
    try {
      var d = _compute();
      var tagColor = isWB ? 'var(--am)' : 'var(--ac)';
      var tagBg = isWB ? 'rgba(240,184,64,.12)' : 'rgba(77,184,255,.08)';
      var tagText = isWB
        ? 'White Beam @ ' + dist.toFixed(1) + ' m'
        : 'Mono ' + state.energy.toFixed(1) + ' keV @ ' + dist.toFixed(1) + ' m';

      // Grid layout: [2D][V] / [H][Detail]
      el.innerHTML =
        '<div data-bp="type" style="font-size:9px;padding:3px 8px;background:' + tagBg + ';border-radius:3px;margin-bottom:4px;color:' + tagColor + ';font-family:var(--mn)">' + tagText + '</div>' +
        '<div style="display:grid;grid-template-columns:' + s + 'px ' + side + 'px;grid-template-rows:' + s + 'px ' + side + 'px;gap:3px">' +
          '<div style="position:relative"><canvas id="' + cid + '_mc2d" style="display:block;border-radius:3px;cursor:crosshair"></canvas></div>' +
          '<div id="' + cid + '_profV" style="border-radius:3px;overflow:hidden"></div>' +
          '<div id="' + cid + '_profH" style="border-radius:3px;overflow:hidden"></div>' +
          '<div id="' + cid + '_detail" style="background:var(--s1);border-radius:3px;padding:6px;font-size:9px;font-family:var(--mn);display:flex;flex-direction:column;justify-content:center;gap:1px;overflow:hidden"></div>' +
        '</div>';

      setTimeout(function() {
        _drawCanvases(d);
        _updateDetail(d);
      }, 30);
    } catch(e) {
      el.innerHTML = '<div style="color:var(--rd);font-size:9px;padding:8px">' + e.message + '</div>';
    }
  }, 20);
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof BP_MAX_MAIN!=="undefined")globalThis.BP_MAX_MAIN=BP_MAX_MAIN;
if(typeof BP_MIN_MAIN!=="undefined")globalThis.BP_MIN_MAIN=BP_MIN_MAIN;
if(typeof BP_SIDE_RATIO!=="undefined")globalThis.BP_SIDE_RATIO=BP_SIDE_RATIO;
if(typeof appendBeamProfileToModal!=="undefined")globalThis.appendBeamProfileToModal=appendBeamProfileToModal;
if(typeof niceScaleAuto!=="undefined")globalThis.niceScaleAuto=niceScaleAuto;
if(typeof renderEpicsTabV2!=="undefined")globalThis.renderEpicsTabV2=renderEpicsTabV2;
if(typeof renderTrendChartV2!=="undefined")globalThis.renderTrendChartV2=renderTrendChartV2;
if(typeof showPropagationLog!=="undefined")globalThis.showPropagationLog=showPropagationLog;
if(typeof _renderTrendPopupChart!=="undefined")globalThis._renderTrendPopupChart=_renderTrendPopupChart;
if(typeof _trendPopupOpen!=="undefined")globalThis._trendPopupOpen=_trendPopupOpen;
if(typeof _trendPopupTimer!=="undefined")globalThis._trendPopupTimer=_trendPopupTimer;
if(typeof renderBeamProfileAt!=="undefined")globalThis.renderBeamProfileAt=renderBeamProfileAt;
if(typeof renderBeamProfileCanvas!=="undefined")globalThis.renderBeamProfileCanvas=renderBeamProfileCanvas;
if(typeof renderDetectorScreen!=="undefined")globalThis.renderDetectorScreen=renderDetectorScreen;
if(typeof setTrendPVPopup!=="undefined")globalThis.setTrendPVPopup=setTrendPVPopup;
if(typeof toggleTrendPopup!=="undefined")globalThis.toggleTrendPopup=toggleTrendPopup;
