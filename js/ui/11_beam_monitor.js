'use strict';
// ===== ui/11_beam_monitor.js — XBPM Live Monitor Popup + Attenuator Physics/UI =====
// @module ui/11_beam_monitor
// @exports _renderAttenMotors, _toggleMcSection, attenTransmission, renderAttenUI, setAttenFilter, toggleXbpmPopup
// Extracted from 14_v435_final.js (DDD Phase 5g)
// Provides: toggleXbpmPopup, _drawMcProfile, attenTransmission,
//   renderAttenUI, setAttenFilter, switchTab override (attenuator tab auto-render)

(function(){

  // --- XBPM list is now dynamic: getXbpmList() from shared/01_constants.js ---
  // Reads all tp:'bpm' entries from CD, with positions from state.positions
  // and zones auto-detected from DCM/SSA/KBV positions.

  var _xbpmOpen = false;
  var _xbpmTimer = null;
  var _xbpmRefreshMs = 1000;  // UI refresh interval (ms), adjustable

  // Expose setter for refresh rate control
  window._setXbpmRefreshRate = function(hz) {
    var ms = Math.round(1000 / hz);
    if (ms < 50) ms = 50;         // clamp min 20 Hz (50 ms)
    if (ms > 5000) ms = 5000;     // clamp max 0.2 Hz (5 s)
    _xbpmRefreshMs = ms;
    if (_xbpmTimer) {
      clearInterval(_xbpmTimer);
      _xbpmTimer = setInterval(_updateXbpmMonitor, _xbpmRefreshMs);
    }
    var lbl = document.getElementById('xbpm_refresh_label');
    if (lbl) {
      var hzShown = Math.round(1000 / _xbpmRefreshMs * 10) / 10;
      lbl.textContent = hzShown + ' Hz';
    }
  };

  window.toggleXbpmPopup = function() {
    var el = document.getElementById('xbpmPopup');
    if (!el) return;
    _xbpmOpen = !_xbpmOpen;
    el.classList.toggle('open', _xbpmOpen);
    if (_xbpmOpen) {
      _renderXbpmCards();
      _updateXbpmMonitor();
      if (!_xbpmTimer) _xbpmTimer = setInterval(_updateXbpmMonitor, _xbpmRefreshMs);
      if (!el._resizeAdded) {
        el.style.position = 'fixed';
        var hdrEl = document.getElementById('xbpmPopupHdr');
        window._makePopupResizable(el, {
          dragEl: hdrEl, minWidth:320, minHeight:200,
          onResize: function() {
            var cvs = el.querySelectorAll('canvas');
            for (var ci = 0; ci < cvs.length; ci++) {
              var c = cvs[ci], cw = c.clientWidth, ch = c.clientHeight;
              if (cw > 0 && ch > 0 && (c.width !== cw || c.height !== ch)) {
                c.width = cw; c.height = ch;
              }
            }
          }
        });
        el._resizeAdded = true;
      }
    } else {
      if (_xbpmTimer) { clearInterval(_xbpmTimer); _xbpmTimer = null; }
    }
  };

  // MC simulation collapsible state per BPM
  var _mcExpanded = {};

  // Format current with auto unit (pA/nA/uA/mA)
  function _fmtCurrent(nA) {
    if (nA === null || nA === undefined) return '--';
    var abs = Math.abs(nA);
    if (abs >= 1e6) return (nA / 1e6).toFixed(3) + ' mA';
    if (abs >= 1e3) return (nA / 1e3).toFixed(3) + ' uA';
    if (abs >= 1)   return nA.toFixed(3) + ' nA';
    if (abs >= 0.001) return (nA * 1e3).toFixed(1) + ' pA';
    return nA.toExponential(1) + ' nA';
  }

  // HW/SIM badge HTML (KOHZU pattern — EPICS_STATE.hwGroups based)
  function _hwBadge(xbId) {
    var grpName = '';
    if (xbId === 'xbpm2') grpName = 'XBPM2';
    if (!grpName) return '<span style="color:var(--t3);font-size:7px">SIM</span>';
    var isHw = typeof EPICS_STATE !== 'undefined' && EPICS_STATE.hwGroups &&
      EPICS_STATE.hwGroups.indexOf(grpName) >= 0;
    if (isHw) {
      return '<span style="color:var(--gn);font-size:7px;font-weight:700;' +
        'border:1px solid var(--gn);border-radius:2px;padding:0 2px">HW</span>';
    }
    return '<span style="color:var(--t3);font-size:7px">SIM</span>';
  }

  // Build card HTML for each XBPM (re-renders each open to pick up position/zone changes)
  function _renderXbpmCards() {
    var container = document.getElementById('xbpmCards');
    if (!container) return;
    var list = typeof getXbpmList === 'function' ? getXbpmList() : [];
    var h = '';
    for (var i = 0; i < list.length; i++) {
      var xb = list[i];
      h += '<div class="xbpm-card" id="xc_' + xb.id + '">';
      // Common header with HW/SIM badge
      h += '<h5 style="display:flex;align-items:center;gap:6px">' +
        xb.name + ' <span>' + xb.dist + 'm (' + xb.zone + ')</span>' +
        _hwBadge(xb.id) + '</h5>';

      // In Virtual mode, DBPM uses generic MC layout (no HW data available)
      var _isHwMode = (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.mode !== 'sim');
      if (xb.bpmType === 'dbpm' && _isHwMode) {
        // === DBPM layout: quadEM data is primary (Real/Hybrid mode only) ===
        // Top row: quadrant canvas (left) + 4ch currents (right)
        h += '<div style="display:flex;gap:6px;align-items:flex-start">' +
          '<canvas id="' + xb.id + '_quad" width="100" height="100" ' +
            'style="width:40%;aspect-ratio:1;height:auto;border-radius:3px;background:var(--s2);flex-shrink:0"></canvas>' +
          '<div style="flex:1;display:grid;grid-template-columns:auto 1fr;gap:1px 6px;font-size:8px;color:var(--t2);align-content:center">' +
            '<span>Ch A</span><span class="xv" id="' + xb.id + '_c1">--</span>' +
            '<span>Ch B</span><span class="xv" id="' + xb.id + '_c2">--</span>' +
            '<span>Ch C</span><span class="xv" id="' + xb.id + '_c3">--</span>' +
            '<span>Ch D</span><span class="xv" id="' + xb.id + '_c4">--</span>' +
          '</div>' +
        '</div>';
        // Sum + Range row
        h += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:8px;color:var(--t2);margin-top:3px">' +
          '<span>Sum: <span class="xv" id="' + xb.id + '_sum" style="color:var(--gn)">--</span></span>' +
          '<span>Range: <span class="xv" id="' + xb.id + '_rng">--</span></span>' +
        '</div>';
        // Position X/Y row
        h += '<div style="display:flex;gap:8px;font-size:8px;color:var(--t2)">' +
          '<span>Pos X: <span class="xv" id="' + xb.id + '_px" style="color:var(--ac)">--</span></span>' +
          '<span>Pos Y: <span class="xv" id="' + xb.id + '_py" style="color:var(--ac)">--</span></span>' +
        '</div>';
        // Bias + HW Sample Freq row
        h += '<div style="display:flex;gap:8px;font-size:8px;color:var(--t2)">' +
          '<span>Bias: <span id="' + xb.id + '_bias" style="font-size:7px">--</span></span>' +
          '<span title="Hardware sampling frequency (T4U electrometer)">HW Samp: <span id="' + xb.id + '_freq" style="font-size:7px">--</span></span>' +
        '</div>';
        // UI refresh rate control row
        h += '<div style="display:flex;gap:6px;align-items:center;font-size:8px;color:var(--t2);margin-top:2px" title="How often the UI redraws values (hardware keeps sampling at HW rate)">' +
          '<span>UI Refresh:</span>' +
          '<select onchange="window._setXbpmRefreshRate(parseFloat(this.value))" ' +
            'style="background:var(--bg);color:var(--t1);border:1px solid var(--b1);border-radius:2px;font-size:7px;padding:1px 2px">' +
            '<option value="0.5">0.5 Hz (2 s)</option>' +
            '<option value="1" selected>1 Hz (1 s)</option>' +
            '<option value="2">2 Hz (500 ms)</option>' +
            '<option value="5">5 Hz (200 ms)</option>' +
            '<option value="10">10 Hz (100 ms)</option>' +
            '<option value="20">20 Hz (50 ms)</option>' +
          '</select>' +
          '<span id="xbpm_refresh_label" style="font-size:7px;color:var(--ac)">1 Hz</span>' +
        '</div>';
        // MC Simulation collapsible
        var mcId = xb.id + '_mc';
        h += '<div style="margin-top:4px;border-top:1px solid var(--b0);padding-top:3px">' +
          '<div style="font-size:8px;color:var(--t3);cursor:pointer;user-select:none" ' +
            'onclick="window._toggleMcSection(\'' + xb.id + '\')" id="' + mcId + '_hdr">' +
            '\u25B8 MC Simulation</div>' +
          '<div id="' + mcId + '_body" style="display:none">' +
            '<canvas id="xcv_' + xb.id + '" width="200" height="60" style="width:100%;height:60px;margin-top:2px"></canvas>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px 6px;font-size:8px;color:var(--t2)">' +
              '<span>FWHM H</span><span class="xv" id="xch_' + xb.id + '">--</span>' +
              '<span>FWHM V</span><span class="xv" id="xcv2_' + xb.id + '">--</span>' +
              '<span>Cen H</span><span class="xv" id="xcp_' + xb.id + '">--</span>' +
              '<span>Cen V</span><span class="xv" id="xcq_' + xb.id + '">--</span>' +
              '<span>Flux</span><span class="xv" id="xcf_' + xb.id + '">--</span>' +
            '</div>' +
          '</div>' +
        '</div>';
      } else {
        // === Generic/Screen layout: MC profile is primary ===
        h += '<canvas id="xcv_' + xb.id + '" width="200" height="80"></canvas>' +
          '<div class="xbpm-vals">' +
          '<span>FWHM H</span><span class="xv" id="xch_' + xb.id + '">--</span>' +
          '<span>FWHM V</span><span class="xv" id="xcv2_' + xb.id + '">--</span>' +
          '<span>Cen H</span><span class="xv" id="xcp_' + xb.id + '">--</span>' +
          '<span>Cen V</span><span class="xv" id="xcq_' + xb.id + '">--</span>' +
          '<span>Flux</span><span class="xv" id="xcf_' + xb.id + '">--</span>' +
          '</div>';
      }
      h += '</div>';
    }
    container.innerHTML = h;
  }

  // Toggle MC simulation collapsible for DBPM cards
  window._toggleMcSection = function(xbId) {
    _mcExpanded[xbId] = !_mcExpanded[xbId];
    var bodyEl = document.getElementById(xbId + '_mc_body');
    var hdrEl = document.getElementById(xbId + '_mc_hdr');
    if (bodyEl) bodyEl.style.display = _mcExpanded[xbId] ? 'block' : 'none';
    if (hdrEl) hdrEl.textContent = (_mcExpanded[xbId] ? '\u25BE' : '\u25B8') + ' MC Simulation';
  };

  // MC ray count for XBPM updates
  var XBPM_NRAYS = 10000;

  // Read PV value from PV_REGISTRY or SimIOC
  function _getPV(name) {
    if (typeof PV_REGISTRY !== 'undefined' && PV_REGISTRY[name]) return PV_REGISTRY[name].value;
    if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs[name]) return EPICS_STATE.simIOC.pvs[name].value;
    return null;
  }

  // Update MC simulation values for a single BPM
  function _updateMcSection(xb, E, totalFlux) {
    try {
      var mc = typeof mcRayTrace === 'function' ? mcRayTrace(xb.dist, XBPM_NRAYS) : null;
      if (!mc) return;
      var hEl = document.getElementById('xch_' + xb.id);
      var vEl = document.getElementById('xcv2_' + xb.id);
      var fEl = document.getElementById('xcf_' + xb.id);
      var cpEl = document.getElementById('xcp_' + xb.id);
      var cqEl = document.getElementById('xcq_' + xb.id);
      var fwhmH_um = mc.fwhmH * 1e6;
      var fwhmV_um = mc.fwhmV * 1e6;
      var isNano = fwhmH_um < 1 && fwhmV_um < 1;
      if (hEl) hEl.textContent = isNano ? (mc.fwhmH * 1e9).toFixed(0) + ' nm' : fwhmH_um.toFixed(1) + ' \u03BCm';
      if (vEl) vEl.textContent = isNano ? (mc.fwhmV * 1e9).toFixed(0) + ' nm' : fwhmV_um.toFixed(1) + ' \u03BCm';
      var cenH_um = (mc.meanH || 0) * 1e6;
      var cenV_um = (mc.meanV || 0) * 1e6;
      if (cpEl) cpEl.textContent = cenH_um.toFixed(1) + ' \u03BCm';
      if (cqEl) cqEl.textContent = cenV_um.toFixed(1) + ' \u03BCm';
      var fluxHere = totalFlux > 0 ? totalFlux * (mc.nSurvived / mc.nTotal) : 0;
      if (fEl) fEl.textContent = fluxHere > 0 ? fluxHere.toExponential(2) : '0';
      _drawMcProfile('xcv_' + xb.id, mc);
    } catch(e){}
  }

  // Update DBPM card with quadEM PV data
  function _updateDbpmCard(xb) {
    var prefix = 'BL10:XBPM2:';
    var c1El = document.getElementById(xb.id + '_c1');
    if (!c1El) return;

    var RANGE_LABELS = ['Low (5mA)', 'Med (100uA)', 'Hi (300nA)'];
    var FREQ_LABELS = {10000: '10 kHz', 4000: '4 kHz', 500: '500 Hz'};

    var c1 = _getPV(prefix + 'Current1:MeanValue_RBV');
    var c2 = _getPV(prefix + 'Current2:MeanValue_RBV');
    var c3 = _getPV(prefix + 'Current3:MeanValue_RBV');
    var c4 = _getPV(prefix + 'Current4:MeanValue_RBV');
    var sum = _getPV(prefix + 'SumAll:MeanValue_RBV');
    var px = _getPV(prefix + 'PosX:MeanValue_RBV');
    var py = _getPV(prefix + 'PosY:MeanValue_RBV');
    var rng = _getPV(prefix + 'Range');
    var bias = _getPV(prefix + 'BiasPEn');
    var freq = _getPV(prefix + 'SampleFreq');

    c1El.textContent = _fmtCurrent(c1);
    var c2El = document.getElementById(xb.id + '_c2'); if (c2El) c2El.textContent = _fmtCurrent(c2);
    var c3El = document.getElementById(xb.id + '_c3'); if (c3El) c3El.textContent = _fmtCurrent(c3);
    var c4El = document.getElementById(xb.id + '_c4'); if (c4El) c4El.textContent = _fmtCurrent(c4);

    var sumEl = document.getElementById(xb.id + '_sum');
    if (sumEl) sumEl.textContent = _fmtCurrent(sum);
    var pxEl = document.getElementById(xb.id + '_px');
    if (pxEl) pxEl.textContent = px !== null ? px.toFixed(4) : '--';
    var pyEl = document.getElementById(xb.id + '_py');
    if (pyEl) pyEl.textContent = py !== null ? py.toFixed(4) : '--';
    var rngEl = document.getElementById(xb.id + '_rng');
    if (rngEl) rngEl.textContent = rng !== null && rng >= 0 && rng <= 2 ? RANGE_LABELS[rng] : '--';
    var biasEl = document.getElementById(xb.id + '_bias');
    if (biasEl) {
      biasEl.textContent = bias ? 'ON' : 'OFF';
      biasEl.style.color = bias ? 'var(--gn)' : 'var(--t3)';
    }
    var freqEl = document.getElementById(xb.id + '_freq');
    if (freqEl) {
      var freqRound = freq !== null ? Math.round(freq) : null;
      freqEl.textContent = freqRound !== null ? (FREQ_LABELS[freqRound] || freqRound + ' Hz') : '--';
    }

    _drawQuadDiagram(xb.id, c1, c2, c3, c4, px, py);
  }

  // Update all XBPM readings
  function _updateXbpmMonitor() {
    if (!_xbpmOpen) return;
    var E = state.energy || 10;
    var xmE = document.getElementById('xm_e');
    var xmFlux = document.getElementById('xm_flux');
    var xmAtt = document.getElementById('xm_att');
    if (xmE) xmE.textContent = E.toFixed(2) + ' keV';
    var totalFlux = 0;
    try { totalFlux = typeof sourceFlux === 'function' ? sourceFlux(E) : 0; } catch(e) {}
    if (xmFlux) xmFlux.textContent = totalFlux > 0 ? totalFlux.toExponential(2) : '--';
    var attT = typeof attenTransmission === 'function' ? attenTransmission(E) : 1;
    if (xmAtt) xmAtt.textContent = (attT * 100).toFixed(1) + '%';

    var xbpmList = typeof getXbpmList === 'function' ? getXbpmList() : [];
    for (var i = 0; i < xbpmList.length; i++) {
      var xb = xbpmList[i];
      var _isHwMode2 = (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.mode !== 'sim');
      if (xb.bpmType === 'dbpm' && _isHwMode2) {
        _updateDbpmCard(xb);
        if (_mcExpanded[xb.id]) {
          _updateMcSection(xb, E, totalFlux);
        }
      } else {
        _updateMcSection(xb, E, totalFlux);
      }
    }
  }

  // Draw 4-quadrant current diagram with beam position indicator
  function _drawQuadDiagram(xbId, cA, cB, cC, cD, posX, posY) {
    var cv = document.getElementById(xbId + '_quad');
    if (!cv) return;
    var cw = cv.clientWidth, ch = cv.clientHeight;
    if (cw > 0 && ch > 0) { cv.width = cw; cv.height = ch; }
    var ctx = cv.getContext('2d');
    var w = cv.width, h = cv.height;
    var cx = w / 2, cy = h / 2;
    var r = Math.min(cx, cy) - 8;

    ctx.fillStyle = '#0c111a';
    ctx.fillRect(0, 0, w, h);

    // Draw diamond sensor outline (circle with quadrant dividers)
    ctx.strokeStyle = 'var(--t3)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx, cy - r); ctx.lineTo(cx, cy + r); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx - r, cy); ctx.lineTo(cx + r, cy); ctx.stroke();

    // Fill quadrants proportional to current
    var vals = [cA || 0, cB || 0, cC || 0, cD || 0];
    var maxC = Math.max.apply(null, vals);
    if (maxC <= 0) maxC = 1;
    var colors = ['rgba(77,184,255,', 'rgba(77,184,255,', 'rgba(77,184,255,', 'rgba(77,184,255,'];
    // A = upper-left, B = upper-right, C = lower-right, D = lower-left
    var quads = [
      {sx:-1, sy:-1, label:'A', val:vals[0]},
      {sx: 1, sy:-1, label:'B', val:vals[1]},
      {sx: 1, sy: 1, label:'C', val:vals[2]},
      {sx:-1, sy: 1, label:'D', val:vals[3]}
    ];
    ctx.font = Math.max(8, Math.round(r * 0.15)) + 'px monospace';
    ctx.textAlign = 'center';
    for (var i = 0; i < 4; i++) {
      var q = quads[i];
      var alpha = 0.1 + 0.5 * (q.val / maxC);
      ctx.fillStyle = 'rgba(77,184,255,' + alpha.toFixed(2) + ')';
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, r - 1, (i - 1) * Math.PI / 2, i * Math.PI / 2);
      ctx.closePath();
      ctx.fill();
      // Label
      var lx = cx + q.sx * r * 0.5;
      var ly = cy + q.sy * r * 0.4;
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.fillText(q.label, lx, ly + 3);
    }

    // Beam position crosshair
    if (posX !== null && posY !== null) {
      var bx = cx + posX * r * 0.8;
      var by = cy - posY * r * 0.8;  // Y inverted for screen coords
      ctx.strokeStyle = 'var(--rd)';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(bx - 6, by); ctx.lineTo(bx + 6, by); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(bx, by - 6); ctx.lineTo(bx, by + 6); ctx.stroke();
      ctx.fillStyle = 'var(--rd)';
      ctx.beginPath(); ctx.arc(bx, by, 2, 0, 2 * Math.PI); ctx.fill();
    }
  }

  // Draw MC ray tracing histogram on mini canvas
  function _drawMcProfile(canvasId, mc) {
    var cv = document.getElementById(canvasId);
    if (!cv) return;
    var cw = cv.clientWidth, ch = cv.clientHeight;
    if (cw > 0 && ch > 0) { cv.width = cw; cv.height = ch; }
    var ctx = cv.getContext('2d');
    var w = cv.width, h = cv.height;
    ctx.fillStyle = '#0c111a';
    ctx.fillRect(0, 0, w, h);
    if (!mc || !mc.hist2d || mc.nSurvived < 10) {
      ctx.fillStyle = '#3d5068';
      ctx.font = Math.max(9, Math.round(h * 0.12)) + 'px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('NO BEAM', w / 2, h / 2 + 3);
      return;
    }
    var G = mc.grid;
    var hist = mc.hist2d;
    var maxI = 0;
    for (var k = 0; k < G * G; k++) { if (hist[k] > maxI) maxI = hist[k]; }
    if (maxI <= 0) return;
    var imgData = ctx.createImageData(w, h);
    var data = imgData.data;
    for (var py = 0; py < h; py++) {
      var gy = Math.min(Math.floor(py / h * G), G - 1);
      for (var px = 0; px < w; px++) {
        var gx = Math.min(Math.floor(px / w * G), G - 1);
        var val = hist[gy * G + gx] / maxI;
        var idx = (py * w + px) * 4;
        data[idx]     = Math.floor(40 + 215 * val);
        data[idx + 1] = Math.floor(70 + 185 * val);
        data[idx + 2] = Math.floor(130 + 125 * val);
        data[idx + 3] = 255;
      }
    }
    ctx.putImageData(imgData, 0, 0);
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
    var fwhmHpx = mc.fovH > 0 ? mc.fwhmH / (2 * mc.fovH) * w : 1;
    var fwhmVpx = mc.fovV > 0 ? mc.fwhmV / (2 * mc.fovV) * h : 1;
    ctx.strokeStyle = 'rgba(77,184,255,0.6)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(w / 2, h / 2, Math.min(fwhmHpx / 2, w / 2 - 1), Math.min(fwhmVpx / 2, h / 2 - 1), 0, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = Math.max(8, Math.round(h * 0.1)) + 'px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(mc.nSurvived + '/' + mc.nTotal, w - 3, h - 3);
  }

  // --- Attenuator Transmission Physics ---
  window.attenTransmission = function(E) {
    if (!state.attenFilters) return 1;
    var T = 1;
    for (var i = 0; i < state.attenFilters.length; i++) {
      var f = state.attenFilters[i];
      if (!f || f.material === 'None' || f.thickness <= 0) continue;
      if (typeof NIST_DATA === 'undefined' || !NIST_DATA[f.material]) continue;
      var md = NIST_DATA[f.material];
      var tcm = f.thickness / 10; // mm -> cm
      var mu = _interpLogLog(E, md.energy, md.mu_rho) * md.density; // 1/cm
      T *= Math.exp(-mu * tcm);
    }
    return T;
  };

  function _interpLogLog(x, xs, ys) {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[xs.length-1]) return ys[ys.length-1];
    for (var i = 0; i < xs.length - 1; i++) {
      if (x >= xs[i] && x <= xs[i+1]) {
        var lx = Math.log(x), lx0 = Math.log(xs[i]), lx1 = Math.log(xs[i+1]);
        var ly0 = Math.log(ys[i]), ly1 = Math.log(ys[i+1]);
        var t = (lx - lx0) / (lx1 - lx0);
        return Math.exp(ly0 + t * (ly1 - ly0));
      }
    }
    return ys[ys.length-1];
  }

  // --- Attenuator UI rendering ---
  window.renderAttenUI = function() {
    var container = document.getElementById('attenSlots');
    if (!container) return;
    if (!state.attenFilters) state.attenFilters = [{material:'None',thickness:0},{material:'None',thickness:0},{material:'None',thickness:0},{material:'None',thickness:0}];
    var mats = typeof MASK_MATERIALS !== 'undefined' ? MASK_MATERIALS : ['None','Carbon','Diamond','Silicon','Aluminium','Copper'];
    var h = '';
    for (var i = 0; i < state.attenFilters.length; i++) {
      var f = state.attenFilters[i];
      h += '<div class="att-slot">' +
        '<span style="color:var(--t3);min-width:16px">#' + (i+1) + '</span>' +
        '<select onchange="setAttenFilter(' + i + ',\'material\',this.value)">';
      for (var j = 0; j < mats.length; j++) {
        h += '<option value="' + mats[j] + '"' + (f.material === mats[j] ? ' selected' : '') + '>' + mats[j] + '</option>';
      }
      h += '</select>' +
        '<input type="number" value="' + f.thickness + '" min="0" max="50" step="0.1" ' +
        'onchange="setAttenFilter(' + i + ',\'thickness\',parseFloat(this.value))" title="Thickness (mm)"/>' +
        '<span style="color:var(--t3)">mm</span></div>';
    }
    container.innerHTML = h;
    _updateAttenDisplay();
  };

  window.setAttenFilter = function(idx, key, val) {
    if (!state.attenFilters || !state.attenFilters[idx]) return;
    state.attenFilters[idx][key] = val;
    _updateAttenDisplay();
    if (typeof updateOptics === 'function') updateOptics();
    if (typeof renderLayout === 'function') renderLayout();
  };

  function _updateAttenDisplay() {
    var E = state.energy || 10;
    var T = attenTransmission(E);
    var el = document.getElementById('attenTransVal');
    if (el) {
      el.textContent = (T * 100).toFixed(1) + '%';
      el.style.color = T > 0.5 ? 'var(--gn)' : T > 0.1 ? 'var(--am)' : 'var(--rd)';
    }
    var fluxEl = document.getElementById('attenFluxVal');
    if (fluxEl) {
      var flux = 0;
      try { flux = typeof photonFlux === 'function' ? photonFlux(E) : 0; } catch(e){}
      var attFlux = flux * T;
      fluxEl.textContent = attFlux > 0 ? attFlux.toExponential(2) + ' ph/s' : '\u2014';
    }
  }

  // Render attenuator motors in its tab
  function _renderAttenMotors() {
    var panel = document.getElementById('tab-atten-motors');
    if (!panel) return;
    if (!MOTORS || !MOTORS['atten']) { panel.innerHTML = ''; return; }
    var grp = MOTORS['atten'];
    var motors = Object.values(grp).filter(function(x){ return x && x.id; });
    if (motors.length === 0) { panel.innerHTML = ''; return; }
    var h = '<div style="margin-top:6px">' +
      '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px">Stage Motors</h4>' +
      '<div class="ctrl-group" style="margin:0">';
    motors.forEach(function(m) {
      var mid = 'att_' + m.id;
      var st = m.step || 0.01;
      h += '<div class="ax-ctrl">' +
        '<div class="ax-r1">' +
        '<span class="ax-name">' + m.name + ' <span class="ax-unit">(' + (m.unit||'') + ')</span></span>' +
        '<span class="ctrl-val ax-pos" id="mval_' + m.id + '">' + m.value.toFixed(3) + '</span>' +
        '</div>' +
        '<div class="ax-r2">' +
        '<button class="jog-btn jog-neg" onclick="motorJog(\'atten\',\'' + m.id + '\',-10)">&#x25C4;&#x25C4;</button>' +
        '<button class="jog-btn jog-neg" onclick="motorJog(\'atten\',\'' + m.id + '\',-1)">&#x25C4;</button>' +
        '<input type="number" value="' + st + '" step="' + (st/10) + '" min="0" class="ax-step" id="' + mid + 'st" title="Jog step"/>' +
        '<button class="jog-btn jog-pos" onclick="motorJog(\'atten\',\'' + m.id + '\',1)">&#x25BA;</button>' +
        '<button class="jog-btn jog-pos" onclick="motorJog(\'atten\',\'' + m.id + '\',10)">&#x25BA;&#x25BA;</button>' +
        '</div></div>';
    });
    h += '</div></div>';
    panel.innerHTML = h;
  }

  // NOTE: switchTab override removed — attenuator tab rendering now handled
  // by switchTab in ui/03_panels.js which calls renderAttenUI() and _renderAttenMotors()
  // Expose _renderAttenMotors for external call
  window._renderAttenMotors = _renderAttenMotors;

  // Init attenuator UI on load
  window.addEventListener('load', function() {
    setTimeout(function() {
      renderAttenUI();
    }, 600);
  });

  console.log('[V4.36] XBPM popup + Attenuator system loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _renderAttenMotors!=="undefined")globalThis._renderAttenMotors=_renderAttenMotors;
if(typeof _toggleMcSection!=="undefined")globalThis._toggleMcSection=_toggleMcSection;
if(typeof attenTransmission!=="undefined")globalThis.attenTransmission=attenTransmission;
if(typeof renderAttenUI!=="undefined")globalThis.renderAttenUI=renderAttenUI;
if(typeof setAttenFilter!=="undefined")globalThis.setAttenFilter=setAttenFilter;
if(typeof toggleXbpmPopup!=="undefined")globalThis.toggleXbpmPopup=toggleXbpmPopup;
