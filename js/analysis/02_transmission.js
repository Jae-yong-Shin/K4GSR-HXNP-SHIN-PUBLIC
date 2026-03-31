'use strict';
// ===== analysis/02_transmission.js -- Sample Transmission Calculator =====
// @module analysis/02_transmission
// @exports _onTransInput, _renderTransChart, _transCanvas, _transInputTimer, _transPopup, _transState, _updateTransInputs, calcTransmission, optimalThickness, showTransmission, showTransmissionPopup
// Beer-Lambert: T(E) = exp(-mu/rho * rho * t)
// Provides interactive popup for experiment planning.

// ── Core: Calculate transmission vs energy ──
// Returns {energies_keV[], transmission[], absorbance[], edges[], formula, thickness_um, density_gcc}
window.calcTransmission = function(formula, thickness_um, density_gcc, eMin_keV, eMax_keV, nPoints) {
  if (!formula) return null;
  thickness_um = thickness_um || 10;
  density_gcc = density_gcc || estimateDensity(formula);
  eMin_keV = eMin_keV || 1;
  eMax_keV = eMax_keV || 25;
  nPoints = nPoints || 500;

  var thickness_cm = thickness_um * 1e-4;
  var energies = [];
  var transmission = [];
  var absorbance = [];
  var dE = (eMax_keV - eMin_keV) / (nPoints - 1);

  for (var i = 0; i < nPoints; i++) {
    var E_keV = eMin_keV + i * dE;
    var E_eV = E_keV * 1000;
    var muRho = compoundMuRho(formula, E_eV);
    var muLinear = muRho * density_gcc;
    var muT = muLinear * thickness_cm;
    var T = Math.exp(-muT);

    energies.push(E_keV);
    transmission.push(T);
    absorbance.push(muT);
  }

  var edges = findEdges(formula, eMin_keV * 1000, eMax_keV * 1000);

  return {
    formula: formula,
    thickness_um: thickness_um,
    density_gcc: density_gcc,
    energies_keV: energies,
    transmission: transmission,
    absorbance: absorbance,
    edges: edges,
    nPoints: nPoints
  };
};

// ── Optimal thickness calculator ──
// technique: 'transmission', 'fluorescence', 'ptycho'
window.optimalThickness = function(formula, density_gcc, E_keV, technique) {
  density_gcc = density_gcc || estimateDensity(formula);
  E_keV = E_keV || 10;
  var E_eV = E_keV * 1000;
  var muRho = compoundMuRho(formula, E_eV);
  var muLinear = muRho * density_gcc;

  if (muLinear <= 0) return {min_um:0.1, max_um:1000, optimal_um:10, technique:technique};

  var result = {muRho: muRho, muLinear: muLinear, E_keV: E_keV};
  technique = technique || 'transmission';
  result.technique = technique;

  if (technique === 'transmission' || technique === 'xafs') {
    result.min_um = (0.36 / muLinear) * 1e4;
    result.max_um = (2.3 / muLinear) * 1e4;
    result.optimal_um = (1.0 / muLinear) * 1e4;
    result.T_min = 0.1;
    result.T_max = 0.7;
    result.note = 'XAFS transmission: mu*t = 1 optimal (T=37%)';
  } else if (technique === 'fluorescence' || technique === 'xrf') {
    result.min_um = 0;
    result.max_um = (0.3 / muLinear) * 1e4;
    result.optimal_um = (0.1 / muLinear) * 1e4;
    result.T_min = 0.74;
    result.T_max = 1.0;
    result.note = 'XRF: mu*t < 0.3 for <5% self-absorption';
  } else if (technique === 'ptycho') {
    result.min_um = 0.01;
    result.max_um = (1.0 / muLinear) * 1e4;
    result.optimal_um = (0.5 / muLinear) * 1e4;
    result.T_min = 0.37;
    result.T_max = 1.0;
    result.note = 'Ptychography: absorbance < 1, sufficient contrast';
  }
  return result;
};

// ── Transmission Popup ──
var _transPopup = null;
var _transCanvas = null;
var _transState = {
  formula: 'Cu',
  thickness_um: 10,
  density_gcc: 8.96,
  technique: 'transmission',
  eMin: 1, eMax: 25
};

window.showTransmissionPopup = function(formula, thickness_um, density_gcc) {
  if (formula) _transState.formula = formula;
  if (thickness_um) _transState.thickness_um = thickness_um;
  if (density_gcc) {
    _transState.density_gcc = density_gcc;
  } else if (formula) {
    _transState.density_gcc = estimateDensity(formula);
  }

  if (_transPopup && document.body.contains(_transPopup)) {
    _transPopup.style.display = '';
    _updateTransInputs();
    _renderTransChart();
    return;
  }

  // Build popup
  var box = document.createElement('div');
  box.id = 'transCalcPopup';
  box.style.cssText = 'position:fixed;left:100px;top:80px;width:700px;height:480px;'
    + 'background:var(--s1,#22252b);border:1px solid var(--b1,#3d5068);border-radius:8px;'
    + 'z-index:9990;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.5);'
    + 'font-family:var(--mn,"Consolas",monospace);color:var(--t1,#e8eaed);font-size:11px;';

  // Title bar
  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;align-items:center;padding:6px 10px;background:var(--s2,#2a2d35);'
    + 'border-radius:8px 8px 0 0;cursor:move;user-select:none;flex-shrink:0;';
  hdr.innerHTML = '<span style="flex:1;font-weight:bold;font-size:12px;">Sample Transmission T(E)</span>'
    + '<span onclick="document.getElementById(\'transCalcPopup\').style.display=\'none\'" '
    + 'style="cursor:pointer;padding:2px 6px;color:var(--t3,#6b7280);">&times;</span>';

  // Controls
  var ctrl = document.createElement('div');
  ctrl.id = 'transCtrl';
  ctrl.style.cssText = 'padding:6px 10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;flex-shrink:0;'
    + 'border-bottom:1px solid var(--b1,#3d5068);';
  ctrl.innerHTML = ''
    + '<label>Formula <input id="trFormula" style="width:80px;background:var(--bg,#1a1d23);color:var(--t1);border:1px solid var(--b1,#3d5068);padding:2px 4px;border-radius:3px;font-family:inherit;font-size:11px;" value="' + _transState.formula + '"></label>'
    + '<label>t(<span style="font-size:9px;">um</span>) <input id="trThick" type="number" style="width:60px;background:var(--bg);color:var(--t1);border:1px solid var(--b1,#3d5068);padding:2px 4px;border-radius:3px;font-family:inherit;font-size:11px;" value="' + _transState.thickness_um + '" step="any" min="0.001"></label>'
    + '<label><span style="font-size:9px;">g/cm3</span> <input id="trDens" type="number" style="width:55px;background:var(--bg);color:var(--t1);border:1px solid var(--b1,#3d5068);padding:2px 4px;border-radius:3px;font-family:inherit;font-size:11px;" value="' + _transState.density_gcc + '" step="any" min="0.01"></label>'
    + '<select id="trTech" style="background:var(--bg);color:var(--t1);border:1px solid var(--b1,#3d5068);padding:2px 4px;border-radius:3px;font-family:inherit;font-size:11px;">'
    + '<option value="transmission">XAFS (trans.)</option>'
    + '<option value="fluorescence">XRF (fluor.)</option>'
    + '<option value="ptycho">Ptychography</option></select>';

  // Info bar
  var info = document.createElement('div');
  info.id = 'transInfo';
  info.style.cssText = 'padding:4px 10px;font-size:10px;color:var(--t2,#a0a4ab);flex-shrink:0;min-height:16px;';

  // Canvas
  var cv = document.createElement('canvas');
  cv.id = 'transCanvas';
  cv.style.cssText = 'flex:1;width:100%;min-height:100px;';
  _transCanvas = cv;

  box.appendChild(hdr);
  box.appendChild(ctrl);
  box.appendChild(cv);
  box.appendChild(info);
  document.body.appendChild(box);
  _transPopup = box;

  // Make resizable
  try {
    _makePopupResizable(box, {dragEl: hdr, minWidth: 500, minHeight: 350,
      onResizeCb: function() { _renderTransChart(); }
    });
  } catch(e) { /* popup util not loaded */ }

  // Event handlers
  var inputs = ['trFormula', 'trThick', 'trDens', 'trTech'];
  for (var i = 0; i < inputs.length; i++) {
    var el = document.getElementById(inputs[i]);
    if (el) {
      el.addEventListener('change', _onTransInput);
      el.addEventListener('input', _onTransInput);
    }
  }

  // Initial render
  setTimeout(function() { _renderTransChart(); }, 50);
};

function _updateTransInputs() {
  var f = document.getElementById('trFormula');
  var t = document.getElementById('trThick');
  var d = document.getElementById('trDens');
  if (f) f.value = _transState.formula;
  if (t) t.value = _transState.thickness_um;
  if (d) d.value = _transState.density_gcc;
}

var _transInputTimer = null;
function _onTransInput() {
  if (_transInputTimer) clearTimeout(_transInputTimer);
  _transInputTimer = setTimeout(function() {
    var f = document.getElementById('trFormula');
    var t = document.getElementById('trThick');
    var d = document.getElementById('trDens');
    var tech = document.getElementById('trTech');
    if (f) _transState.formula = f.value.trim();
    if (t) _transState.thickness_um = parseFloat(t.value) || 1;
    if (d) _transState.density_gcc = parseFloat(d.value) || 1;
    if (tech) _transState.technique = tech.value;
    // Auto-update density when formula changes
    if (f && !d.value) {
      _transState.density_gcc = estimateDensity(_transState.formula);
      d.value = _transState.density_gcc.toFixed(2);
    }
    _renderTransChart();
  }, 200);
}

function _renderTransChart() {
  var cv = _transCanvas;
  if (!cv || !cv.parentElement) return;
  var w = cv.clientWidth;
  var h = cv.clientHeight;
  if (w < 10 || h < 10) return;

  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = w * dpr;
  cv.height = h * dpr;
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);

  // Compute
  var result = calcTransmission(_transState.formula, _transState.thickness_um,
    _transState.density_gcc, _transState.eMin, _transState.eMax, 500);
  if (!result) {
    ctx.fillStyle = '#6b7280';
    ctx.font = '12px monospace';
    ctx.fillText('Invalid formula', 20, h / 2);
    return;
  }

  var opt = optimalThickness(_transState.formula, _transState.density_gcc,
    typeof state !== 'undefined' && state.energy ? state.energy / 1000 : 10,
    _transState.technique);

  // Chart dimensions
  var pad = {l:55, r:15, t:10, b:30};
  var cw = w - pad.l - pad.r;
  var ch = h - pad.t - pad.b;

  // Background
  ctx.fillStyle = '#1a1d23';
  ctx.fillRect(0, 0, w, h);

  // Axes
  var eMin = _transState.eMin;
  var eMax = _transState.eMax;
  var tMin = 0;
  var tMax = 1.05;

  function xPx(e) { return pad.l + (e - eMin) / (eMax - eMin) * cw; }
  function yPx(t) { return pad.t + (1 - (t - tMin) / (tMax - tMin)) * ch; }

  // Grid
  ctx.strokeStyle = '#2a2d35';
  ctx.lineWidth = 0.5;
  for (var g = 0; g <= 10; g++) {
    var gy = yPx(g * 0.1);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
  }
  for (var ge = Math.ceil(eMin); ge <= eMax; ge += 5) {
    var gx = xPx(ge);
    ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
  }

  // Technique optimal band
  if (opt && opt.T_min !== undefined) {
    ctx.fillStyle = 'rgba(64, 216, 154, 0.08)';
    var bandTop = yPx(opt.T_max);
    var bandBot = yPx(opt.T_min);
    ctx.fillRect(pad.l, bandTop, cw, bandBot - bandTop);
    ctx.strokeStyle = 'rgba(64, 216, 154, 0.3)';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, bandTop); ctx.lineTo(w - pad.r, bandTop); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pad.l, bandBot); ctx.lineTo(w - pad.r, bandBot); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Absorption edges
  var edges = result.edges;
  for (var ei = 0; ei < edges.length; ei++) {
    var edgeE = edges[ei].energy / 1000;
    var ex = xPx(edgeE);
    ctx.strokeStyle = 'rgba(255, 179, 64, 0.6)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(ex, pad.t); ctx.lineTo(ex, h - pad.b); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#ffb340';
    ctx.font = '9px monospace';
    ctx.fillText(edges[ei].element + ' ' + edges[ei].edge, ex + 2, pad.t + 10 + ei * 11);
    ctx.fillText(edgeE.toFixed(2) + ' keV', ex + 2, pad.t + 19 + ei * 11);
  }

  // Current beamline energy marker
  var curE = (typeof state !== 'undefined' && state.energy) ? state.energy / 1000 : null;
  if (curE && curE >= eMin && curE <= eMax) {
    var cx = xPx(curE);
    ctx.strokeStyle = 'rgba(77, 184, 255, 0.7)';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(cx, pad.t); ctx.lineTo(cx, h - pad.b); ctx.stroke();
    ctx.fillStyle = '#4db8ff';
    ctx.font = '9px monospace';
    ctx.fillText(curE.toFixed(2) + ' keV', cx + 3, h - pad.b - 5);
  }

  // T(E) curve
  ctx.strokeStyle = '#4db8ff';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (var pi = 0; pi < result.nPoints; pi++) {
    var px = xPx(result.energies_keV[pi]);
    var py = yPx(result.transmission[pi]);
    if (pi === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();

  // Fill under curve
  ctx.globalAlpha = 0.1;
  ctx.fillStyle = '#4db8ff';
  ctx.lineTo(xPx(result.energies_keV[result.nPoints - 1]), yPx(0));
  ctx.lineTo(xPx(result.energies_keV[0]), yPx(0));
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1.0;

  // Axes labels
  ctx.fillStyle = '#a0a4ab';
  ctx.font = '10px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Energy (keV)', pad.l + cw / 2, h - 5);
  ctx.textAlign = 'right';
  for (var lx = Math.ceil(eMin); lx <= eMax; lx += 5) {
    ctx.fillText(lx.toString(), xPx(lx), h - pad.b + 14);
  }
  ctx.textAlign = 'right';
  for (var ly = 0; ly <= 10; ly++) {
    ctx.fillText((ly * 10) + '%', pad.l - 4, yPx(ly * 0.1) + 4);
  }
  ctx.save();
  ctx.translate(12, pad.t + ch / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillText('Transmission', 0, 0);
  ctx.restore();

  // Axes frame
  ctx.strokeStyle = '#3d5068';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b);
  ctx.lineTo(w - pad.r, h - pad.b);
  ctx.stroke();

  // Update info bar
  var infoEl = document.getElementById('transInfo');
  if (infoEl) {
    var tAtCur = '';
    if (curE) {
      var muAtCur = compoundMuRho(_transState.formula, curE * 1000);
      var muT = muAtCur * _transState.density_gcc * _transState.thickness_um * 1e-4;
      var TatCur = Math.exp(-muT);
      tAtCur = ' | T(' + curE.toFixed(1) + ' keV) = ' + (TatCur * 100).toFixed(1) + '%';
    }
    var optText = '';
    if (opt && opt.optimal_um !== undefined) {
      var oum = opt.optimal_um;
      var unit = 'um';
      if (oum < 0.1) { oum *= 1000; unit = 'nm'; }
      else if (oum > 1000) { oum /= 1000; unit = 'mm'; }
      optText = ' | Optimal t: ' + oum.toFixed(1) + ' ' + unit + ' (' + opt.note + ')';
    }
    infoEl.textContent = _transState.formula + ', ' + _transState.thickness_um + ' um, '
      + _transState.density_gcc.toFixed(2) + ' g/cm3' + tAtCur + optText;
  }
}

// ── NLP wrapper ──
window.showTransmission = function(formula, thickness_um, density_gcc) {
  try {
    showTransmissionPopup(formula, thickness_um, density_gcc);
  } catch(e) {
    console.error('[Transmission] popup error:', e);
  }
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _onTransInput!=="undefined")globalThis._onTransInput=_onTransInput;
if(typeof _renderTransChart!=="undefined")globalThis._renderTransChart=_renderTransChart;
if(typeof _transCanvas!=="undefined")globalThis._transCanvas=_transCanvas;
if(typeof _transInputTimer!=="undefined")globalThis._transInputTimer=_transInputTimer;
if(typeof _transPopup!=="undefined")globalThis._transPopup=_transPopup;
if(typeof _transState!=="undefined")globalThis._transState=_transState;
if(typeof _updateTransInputs!=="undefined")globalThis._updateTransInputs=_updateTransInputs;
if(typeof calcTransmission!=="undefined")globalThis.calcTransmission=calcTransmission;
if(typeof optimalThickness!=="undefined")globalThis.optimalThickness=optimalThickness;
if(typeof showTransmission!=="undefined")globalThis.showTransmission=showTransmission;
if(typeof showTransmissionPopup!=="undefined")globalThis.showTransmissionPopup=showTransmissionPopup;
