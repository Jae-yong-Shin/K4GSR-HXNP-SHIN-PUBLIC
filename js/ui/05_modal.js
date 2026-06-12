'use strict';
// ===== ui/05_modal.js -- Modal System (openModal/closeModal inline merged) =====
// @module ui/05_modal
// @exports _alignPopupDismissed, _appendDbpmToModal, _dbpmFmtCurrent, _dbpmGetPV, _drawDbpmPosition, _makePopupResizable, _mcId, _updateDbpmModal, closeModal, curModal, drawBPM, mcSlider, modalSetPos, niceScale, openModal, ...
// Extracted from 08_ui_core.js + alignment/04_align_ui.js (DDD Phase 6)
// openModal/closeModal: inline merged (no _orig chain)

// --- Module-level state ---
var curModal = null;
// Module-level counter, reset to 0 per showComp() call, incremented by mcSlider to mint unique 'mc<n>' DOM element IDs.
var _mcId = 0;

// ===================================================================
// openModal -- INLINE MERGED (base 08_ui_core.js + alignment/04_align_ui.js)
// ===================================================================
window.openModal = function(t, h) {
  var dlg = document.getElementById('modalDialog');
  // [alignment wrapper] reset zoom/position before base logic
  if (dlg) {
    dlg.style.zoom = '';
    dlg.style.position = '';
    dlg.style.left = '';
    dlg.style.top = '';
  }
  // [base] set title, body, show overlay
  var titleEl = document.getElementById('modalTitle');
  if (titleEl) titleEl.textContent = t;
  var bodyEl = document.getElementById('modalBody');
  if (bodyEl) bodyEl.innerHTML = h;
  var ovl = document.getElementById('modalOverlay');
  if (ovl) ovl.classList.add('open');
  // [base] reset position on open (centered via CSS flex)
  if (dlg) {
    dlg.style.position = '';
    dlg.style.left = '';
    dlg.style.top = '';
    dlg.style.margin = '';
  }
};

// ===================================================================
// closeModal -- INLINE MERGED (base 08_ui_core.js + alignment/04_align_ui.js)
// ===================================================================
window.closeModal = function() {
  // [alignment wrapper] track user dismissal during alignment
  if (window._alignState && window._alignState.active) {
    window._alignPopupDismissed = true;
  }
  // [base] clear curModal, remove 'open' class
  curModal = null;
  var ovl = document.getElementById('modalOverlay');
  if (ovl) ovl.classList.remove('open');
  // [alignment wrapper] reset zoom on close
  var _md = document.getElementById('modalDialog');
  if (_md) _md.style.zoom = '';
};

// ===================================================================
// modalSetPos -- position setter
// ===================================================================
window.modalSetPos = function(id, v) {
  var n = parseFloat(v);
  if (isNaN(n) || n < 0 || n > 200) return;
  state.positions[id] = n;
  if (typeof renderLayout === 'function') renderLayout();
  setTimeout(function() { showComp(id); }, 30);
  if (typeof log === 'function') log('info', id + ' -> ' + n.toFixed(2) + 'm');
};

// ===================================================================
// mcSlider -- synced slider + number pair
// ===================================================================
window.mcSlider = function(label, min, max, step, val, onUpdate) {
  var uid = 'mc' + (_mcId++);
  return '<div class="mc-row"><label>' + label + '</label>' +
    '<div style="display:flex;align-items:center;gap:3px;flex:1">' +
    '<button class="jog-btn jog-neg" style="padding:2px 6px;font-size:10px" ' +
    'onclick="var el=document.getElementById(\'' + uid + 'n\');var v=Math.max(' + min + ',parseFloat(el.value)-' + step + ');el.value=v;(' + onUpdate + ')(v)">&#x25C4;</button>' +
    '<input type="number" id="' + uid + 'n" min="' + min + '" max="' + max +
    '" step="' + step + '" value="' + val +
    '" style="width:75px;text-align:center" onchange="(' + onUpdate + ')(this.value)"/>' +
    '<button class="jog-btn jog-pos" style="padding:2px 6px;font-size:10px" ' +
    'onclick="var el=document.getElementById(\'' + uid + 'n\');var v=Math.min(' + max + ',parseFloat(el.value)+' + step + ');el.value=v;(' + onUpdate + ')(v)">&#x25BA;</button>' +
    '</div></div>';
};

// ===================================================================
// Modal drag handler IIFE (mousedown on modalHead for drag-to-move)
// ===================================================================
(function() {
  var _dragState = null;
  function _getModalZoom(dlg) {
    var z = parseFloat(dlg.style.zoom);
    if (!z || isNaN(z)) z = parseFloat(getComputedStyle(dlg).zoom);
    return (z && !isNaN(z) && z > 0) ? z : 1;
  }
  function initModalDrag() {
    var head = document.getElementById('modalHead');
    if (!head) return;
    head.addEventListener('mousedown', function(e) {
      if (e.target.closest('.modal-close')) return;
      var dlg = document.getElementById('modalDialog');
      if (!dlg) return;
      var rect = dlg.getBoundingClientRect();
      var z = _getModalZoom(dlg);
      dlg.style.position = 'absolute';
      dlg.style.left = (rect.left / z) + 'px';
      dlg.style.top = (rect.top / z) + 'px';
      dlg.style.margin = '0';
      dlg.classList.add('dragging');
      _dragState = { startX: e.clientX, startY: e.clientY, origLeft: rect.left / z, origTop: rect.top / z, zoom: z };
      e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
      if (!_dragState) return;
      var dlg = document.getElementById('modalDialog');
      if (!dlg) return;
      var dx = (e.clientX - _dragState.startX) / _dragState.zoom;
      var dy = (e.clientY - _dragState.startY) / _dragState.zoom;
      dlg.style.left = (_dragState.origLeft + dx) + 'px';
      dlg.style.top = Math.max(0, _dragState.origTop + dy) + 'px';
    });
    document.addEventListener('mouseup', function() {
      if (!_dragState) return;
      _dragState = null;
      var dlg = document.getElementById('modalDialog');
      if (dlg) dlg.classList.remove('dragging');
    });
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive')
    setTimeout(initModalDrag, 200);
  else document.addEventListener('DOMContentLoaded', function() { setTimeout(initModalDrag, 200); });
})();

// ===================================================================
// Modal resize handler IIFE -- _makePopupResizable + overlay mousedown close
// ===================================================================
(function() {
  function _initModalResize() {
    var dlg = document.getElementById('modalDialog');
    var ovl = document.getElementById('modalOverlay');
    if (!dlg) return;
    dlg.style.resize = 'none';
    if (typeof window._makePopupResizable === 'function') {
      window._makePopupResizable(dlg, { minWidth: 360 });
    }
    // Overlay close via mousedown (not onclick -- prevent close during resize drag)
    if (ovl) {
      ovl.removeAttribute('onclick');
      ovl.addEventListener('mousedown', function(e) {
        if (e.target === ovl) closeModal();
      });
    }
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive')
    setTimeout(_initModalResize, 300);
  else document.addEventListener('DOMContentLoaded', function() { setTimeout(_initModalResize, 300); });
})();

// ===================================================================
// showComp -- INLINE MERGED (base 08_ui_core.js + ui/10_motor_jog.js Advanced Motors)
// ===================================================================
window.showComp = function(id) {
  // Attenuator: switch to Atten tab instead of generic modal
  if (id === 'atten') {
    if (typeof switchTab === 'function') switchTab('atten');
    return;
  }
  _mcId = 0;
  curModal = id;
  var c = null;
  for (var ci = 0; ci < CD.length; ci++) {
    if (CD[ci].id === id) { c = CD[ci]; break; }
  }
  if (!c) return;
  var p = pos(id);
  var ctrl = '<div class="mc"><h4>Position & Controls</h4>' +
    '<div class="mc-row"><label>Position (m)</label>' +
    '<input type="number" value="' + p + '" step="0.1" min="0" max="200" ' +
    'onchange="modalSetPos(\'' + id + '\',this.value)" style="width:65px"/>' +
    '<span class="mc-val">' + p.toFixed(2) + ' m</span></div>';
  var info = '';
  var B0 = calcB0(state.gap);
  var K = calcK(B0);
  var E1 = calcE1(K);

  if (id === 'ivu') {
    ctrl += mcSlider('Gap (mm)', 5, 25, 0.1, state.gap, 'function(v){compSliderUpdate(\'ivu\',\'gap\',v)}');
    var ps = photonSrc(E1);
    info = '<div class="info-item"><div class="lbl">B0</div><div class="val">' + B0.toFixed(4) + ' T</div></div>' +
      '<div class="info-item"><div class="lbl">K</div><div class="val">' + K.toFixed(3) + '</div></div>' +
      '<div class="info-item"><div class="lbl">E1</div><div class="val">' + E1.toFixed(2) + ' keV</div></div>' +
      '<div class="info-item"><div class="lbl">Harmonic</div><div class="val">n=' + state.harmonic + '</div></div>' +
      '<div class="info-item"><div class="lbl">Power</div><div class="val">' + (calcPtotal(B0) / 1000).toFixed(2) + ' kW</div></div>' +
      '<div class="info-item"><div class="lbl">sigma\'_r</div><div class="val">' + (ps.srp * 1e6).toFixed(2) + ' \u03BCrad</div></div>' +
      '<div class="info-item"><div class="lbl">sigma_r</div><div class="val">' + (ps.sr * 1e6).toFixed(2) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">Phi on-axis</div><div class="val">' + onAxisFlux(K, 1).toExponential(2) + '</div></div>' +
      '<div class="info-item"><div class="lbl">E_ring</div><div class="val">' + E_RING + ' GeV / ' + I_RING + ' mA</div></div>' +
      '<div class="info-item"><div class="lbl">eps_x / eps_y</div><div class="val">' + (EMIT_X * 1e12).toFixed(1) + ' / ' + (EMIT_Y * 1e12).toFixed(1) + ' pm</div></div>' +
      '<div class="info-item"><div class="lbl">beta_x / beta_y</div><div class="val">' + BETA_X.toFixed(2) + ' / ' + BETA_Y.toFixed(1) + ' m</div></div>' +
      '<div class="info-item"><div class="lbl">sigma_x / sigma_y</div><div class="val">' + (SIG_EX * 1e6).toFixed(1) + ' / ' + (SIG_EY * 1e6).toFixed(2) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">sigma\'_x / sigma\'_y</div><div class="val">' + (SIG_EXP * 1e6).toFixed(2) + ' / ' + (SIG_EYP * 1e6).toFixed(2) + ' \u03BCrad</div></div>' +
      '<div class="info-item"><div class="lbl">sigma_E</div><div class="val">' + (E_SPREAD * 1e4).toFixed(1) + ' x10^-4</div></div>';
  } else if (id === 'wbslit') {
    ctrl += mcSlider('H (mm)', 0.1, 5, 0.1, state.wbH, 'function(v){compSliderUpdate(\'wbslit\',\'h\',v)}');
    ctrl += mcSlider('V (mm)', 0.1, 3, 0.1, state.wbV, 'function(v){compSliderUpdate(\'wbslit\',\'v\',v)}');
    var bw = beamAt(p);
    info = '<div class="info-item"><div class="lbl">Beam FWHM</div><div class="val">' + bw.h.toFixed(0) + 'x' + bw.v.toFixed(0) + ' \u03BCm</div></div>';
  } else if (id === 'm1' || id === 'm2') {
    var pitch = id === 'm1' ? state.m1pitch : state.m2pitch;
    ctrl += mcSlider('Pitch (mrad)', 2, 5, 0.01, pitch, 'function(v){compSliderUpdate(\'' + id + '\',\'pitch\',v)}');
    var _st = (typeof getStripeMaterial === 'function') ? getStripeMaterial(id) : null;
    var _mat = (_st && _st.mat) ? _st.mat : RH;
    var _matName = _st ? _st.name : 'Rh';
    var _matZ = _mat.Z || 45;
    var oc = optConst(state.energy, _mat);
    var R = mirrorR(state.energy, pitch, _mat);
    info = '<div class="info-item"><div class="lbl">Coating</div><div class="val">' + _matName + ' (Z=' + _matZ + ')</div></div>' +
      '<div class="info-item"><div class="lbl">Type</div><div class="val">Horizontal deflecting</div></div>' +
      '<div class="info-item"><div class="lbl">delta</div><div class="val">' + oc.delta.toExponential(2) + '</div></div>' +
      '<div class="info-item"><div class="lbl">beta</div><div class="val">' + oc.beta.toExponential(2) + '</div></div>' +
      '<div class="info-item"><div class="lbl">theta_c</div><div class="val">' + (Math.sqrt(2 * oc.delta) * 1e3).toFixed(2) + ' mrad</div></div>' +
      '<div class="info-item"><div class="lbl">Cut-off</div><div class="val">' + mirrorCut(pitch, _mat).toFixed(1) + ' keV</div></div>' +
      '<div class="info-item"><div class="lbl">R @' + state.energy.toFixed(1) + 'keV</div><div class="val">' + (R * 100).toFixed(1) + '%</div></div>';
  } else if (id === 'dcm') {
    ctrl += '<div class="mc-row"><label>Crystal</label><select style="flex:1;background:var(--s2);border:1px solid var(--b1);color:var(--ac);font-family:var(--mn);font-size:10px;padding:3px;border-radius:3px" onchange="setCrystal(this.value);refreshInfoOnly(\'dcm\');refreshBeamOnly(\'dcm\')"><option value="111"' + (state.crystal === '111' ? ' selected' : '') + '>Si(111)</option><option value="311"' + (state.crystal === '311' ? ' selected' : '') + '>Si(311)</option></select></div>';
    ctrl += mcSlider('Energy (keV)', 4, 40, 0.01, state.energy, 'function(v){compSliderUpdate(\'dcm\',\'energy\',v)}');
    var th = braggAngle(state.energy);
    var td = isNaN(th) ? 0 : th * 180 / Math.PI;
    var d = D_SI[state.crystal];
    info = '<div class="info-item"><div class="lbl">Crystal</div><div class="val">Si(' + state.crystal + ')</div></div>' +
      '<div class="info-item"><div class="lbl">d-spacing</div><div class="val">' + d.toFixed(4) + ' A</div></div>' +
      '<div class="info-item"><div class="lbl">theta_B</div><div class="val">' + td.toFixed(3) + ' deg</div></div>' +
      '<div class="info-item"><div class="lbl">Gap</div><div class="val">' + (isNaN(th) ? '-' : dcmGap(th).toFixed(2)) + ' mm</div></div>' +
      '<div class="info-item"><div class="lbl">Darwin W.</div><div class="val">' + darwinW(state.energy).toFixed(2) + ' arcsec</div></div>' +
      '<div class="info-item"><div class="lbl">dE/E</div><div class="val">' + dcmRes(state.energy).toExponential(2) + '</div></div>' +
      '<div class="info-item"><div class="lbl">Ext. Depth</div><div class="val">' + extDepth(state.energy).toFixed(2) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">Selects</div><div class="val">n=' + state.harmonic + ' @' + state.energy.toFixed(2) + ' keV</div></div>' +
      '<div class="info-item"><div class="lbl">Fixed Exit</div><div class="val">' + FIXED_EXIT + ' mm</div></div>';
  } else if (id === 'ic1') {
    // ── IC1 ion chamber panel (A3) ──
    // The chain narrates the user's key physics point: the current is made
    // from the flux that REACHES the chamber, i.e. after the upstream air.
    var icc = (typeof icLiveChain === 'function') ? icLiveChain() : null;
    var gasSel = '';
    ['N2', 'He', 'Ar', 'air'].forEach(function(g) {
      gasSel += '<option value="' + g + '"' +
        ((state.ic1Gas || 'N2') === g ? ' selected' : '') + '>' + g + '</option>';
    });
    ctrl += '<div class="mc"><h4>Chamber Config</h4><div class="info-grid">' +
      '<div class="info-item"><div class="lbl">Gas</div><div class="val">' +
      '<select onchange="state.ic1Gas=this.value;showComp(\'ic1\')" style="font-size:10px">' + gasSel + '</select></div></div>' +
      '<div class="info-item"><div class="lbl">Length (cm)</div><div class="val">' +
      '<input type="number" value="' + (state.ic1LenCm || 10) + '" min="1" max="50" step="1" style="width:60px;font-size:10px" ' +
      'onchange="state.ic1LenCm=parseFloat(this.value)||10;showComp(\'ic1\')"/></div></div>' +
      '<div class="info-item"><div class="lbl">Pressure (atm)</div><div class="val">' +
      '<input type="number" value="' + (state.ic1PressAtm || 1.0) + '" min="0.01" max="2" step="0.05" style="width:60px;font-size:10px" ' +
      'onchange="state.ic1PressAtm=parseFloat(this.value)||1;showComp(\'ic1\')"/></div></div>' +
      '<div class="info-item"><div class="lbl">Air before (cm)</div><div class="val">' +
      '<input type="number" value="' + (state.ic1AirBeforeCm != null ? state.ic1AirBeforeCm : 5) + '" min="0" max="500" step="1" style="width:60px;font-size:10px" ' +
      'onchange="state.ic1AirBeforeCm=parseFloat(this.value)||0;showComp(\'ic1\')"/></div></div>' +
      '<div class="info-item"><div class="lbl">Air after (cm)</div><div class="val">' +
      '<input type="number" value="' + (state.ic1AirAfterCm != null ? state.ic1AirAfterCm : 2) + '" min="0" max="500" step="1" style="width:60px;font-size:10px" ' +
      'onchange="state.ic1AirAfterCm=parseFloat(this.value)||0;showComp(\'ic1\')"/></div></div>' +
      '</div></div>';
    if (icc) {
      var uA1 = icc.current_A * 1e6;
      info = '<div class="info-item"><div class="lbl">Pre-KB beam' + (icc.ratioExact ? '' : ' (approx)') + '</div><div class="val">' + icc.fluxICRegion.toExponential(2) + ' ph/s</div></div>' +
        '<div class="info-item"><div class="lbl">T air (before)</div><div class="val">' + (icc.T_airBefore * 100).toFixed(2) + ' %</div></div>' +
        '<div class="info-item"><div class="lbl">Flux at IC1</div><div class="val" style="color:var(--ac)">' + icc.fluxAtIC.toExponential(2) + ' ph/s</div></div>' +
        '<div class="info-item"><div class="lbl">IC current</div><div class="val" style="color:var(--gn);font-weight:700">' +
        (uA1 >= 1 ? uA1.toFixed(2) + ' µA' : (uA1 * 1000).toFixed(1) + ' nA') + '</div></div>' +
        '<div class="info-item"><div class="lbl">T chamber</div><div class="val">' + (icc.T_ic * 100).toFixed(2) + ' %</div></div>' +
        '<div class="info-item"><div class="lbl">T air (after)</div><div class="val">' + (icc.T_airAfter * 100).toFixed(2) + ' %</div></div>' +
        '<div class="info-item"><div class="lbl">Flux at sample</div><div class="val" style="color:var(--am)">' + icc.fluxAtSample.toExponential(2) + ' ph/s</div></div>' +
        '<div class="info-item"><div class="lbl">Chain</div><div class="val" style="font-size:8px">KBslit→air→IC1→air→KB→sample (pre-focus x' + icc.ratioPreFocus.toFixed(1) + ')</div></div>';
    } else {
      info = '<div class="info-item"><div class="lbl">Status</div><div class="val">flux unavailable (engine warming)</div></div>';
    }
  } else if (id === 'ssa') {
    ctrl += mcSlider('H Gap (um)', 5, 200, 1, state.ssaH, 'function(v){ssaSliderUpdate(\'h\',v)}');
    ctrl += mcSlider('V Gap (um)', 5, 200, 1, state.ssaV, 'function(v){ssaSliderUpdate(\'v\',v)}');
    ctrl += mcSlider('H Ctr (um)', -100, 100, 1, state.ssaCX || 0, 'function(v){ssaSliderUpdate(\'cx\',v)}');
    ctrl += mcSlider('V Ctr (um)', -100, 100, 1, state.ssaCY || 0, 'function(v){ssaSliderUpdate(\'cy\',v)}');
    var bs = beamAt(p);
    info = '<div class="info-item"><div class="lbl">Beam</div><div class="val">' + bs.h.toFixed(0) + 'x' + bs.v.toFixed(0) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">Function</div><div class="val">Virtual source for focusing</div></div>';
  } else if (id === 'kbslit') {
    ctrl += mcSlider('H Gap (um)', 5, 5000, 1, state.kbslitH, 'function(v){kbslitSliderUpdate(\'h\',v)}');
    ctrl += mcSlider('V Gap (um)', 5, 5000, 1, state.kbslitV, 'function(v){kbslitSliderUpdate(\'v\',v)}');
    ctrl += mcSlider('H Ctr (um)', -2500, 2500, 1, state.kbslitCX || 0, 'function(v){kbslitSliderUpdate(\'cx\',v)}');
    ctrl += mcSlider('V Ctr (um)', -2500, 2500, 1, state.kbslitCY || 0, 'function(v){kbslitSliderUpdate(\'cy\',v)}');
    var bks = beamAt(p);
    info = '<div class="info-item"><div class="lbl">Beam</div><div class="val">' + bks.h.toFixed(0) + 'x' + bks.v.toFixed(0) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">Position</div><div class="val">500 mm upstream KB-V</div></div>' +
      '<div class="info-item"><div class="lbl">Function</div><div class="val">KB beam definition aperture</div></div>';
  } else if (id === 'kbv' || id === 'kbh') {
    var sp = focalSpot();
    var isV = id === 'kbv';
    var fm = state.focusMode || 'kb';
    var _kbp = (typeof KB_PARAMS !== 'undefined') ? KB_PARAMS[id] : null;
    var _kbLen = _kbp ? (_kbp.len * 1000) : (isV ? 300 : 100);
    var _kbPitch = isV ? state.kbvpitch : state.kbhpitch;
    var _kbSt = (typeof getStripeMaterial === 'function') ? getStripeMaterial(id) : null;
    var _kbMat = (_kbSt && _kbSt.mat) ? _kbSt.mat : PT;
    var _kbMatName = _kbSt ? _kbSt.name : 'Pt';
    ctrl += mcSlider('Pitch (mrad)', 1, 5, 0.01, _kbPitch, 'function(v){compSliderUpdate(\'' + id + '\',\'pitch\',v)}');
    if (fm === 'kb') {
      var _kbR = mirrorR(state.energy, _kbPitch, _kbMat);
      info = '<div class="info-item"><div class="lbl">Type</div><div class="val">KB Mirror (Elliptical)</div></div>' +
        '<div class="info-item"><div class="lbl">Length</div><div class="val">' + _kbLen.toFixed(0) + ' mm</div></div>' +
        '<div class="info-item"><div class="lbl">Coating</div><div class="val">' + _kbMatName + ' (Z=' + _kbMat.Z + ')</div></div>' +
        '<div class="info-item"><div class="lbl">Focuses</div><div class="val">' + (isV ? 'Vertical (side view)' : 'Horizontal (top view)') + '</div></div>' +
        '<div class="info-item"><div class="lbl">Demag</div><div class="val">' + (isV ? sp.demagV.toFixed(0) : sp.demagH.toFixed(0)) + 'x</div></div>' +
        '<div class="info-item"><div class="lbl">R @' + state.energy.toFixed(1) + 'keV</div><div class="val">' + (_kbR * 100).toFixed(1) + '%</div></div>' +
        '<div class="info-item"><div class="lbl">Focus</div><div class="val" style="color:var(--gn)">' + (isV ? sp.v.toFixed(0) : sp.h.toFixed(0)) + ' nm</div></div>';
    } else if (fm === 'zp') {
      info = '<div class="info-item"><div class="lbl">Type</div><div class="val">Fresnel Zone Plate</div></div>' +
        '<div class="info-item"><div class="lbl">Focuses</div><div class="val">Both H &amp; V</div></div>' +
        '<div class="info-item"><div class="lbl">Resolution</div><div class="val">~30 nm (outermost zone)</div></div>' +
        '<div class="info-item"><div class="lbl">Efficiency</div><div class="val">~10% (1st order)</div></div>' +
        '<div class="info-item"><div class="lbl">Spot</div><div class="val" style="color:var(--gn)">' + sp.h.toFixed(0) + 'x' + sp.v.toFixed(0) + ' nm</div></div>';
    } else {
      info = '<div class="info-item"><div class="lbl">Type</div><div class="val">Compound Refractive Lens</div></div>' +
        '<div class="info-item"><div class="lbl">Material</div><div class="val">Be / Al</div></div>' +
        '<div class="info-item"><div class="lbl">Focuses</div><div class="val">Both H &amp; V</div></div>' +
        '<div class="info-item"><div class="lbl">N lenses</div><div class="val">~50-200</div></div>' +
        '<div class="info-item"><div class="lbl">Spot</div><div class="val" style="color:var(--gn)">' + sp.h.toFixed(0) + 'x' + sp.v.toFixed(0) + ' nm</div></div>';
    }
  } else if (id === 'sample') {
    var sp2 = focalSpot();
    // Sample-plane flux: single API (sampleFlux) shared by every display.
    var _flux = (typeof sampleFlux === 'function') ? sampleFlux() : photonFlux(state.energy);
    ctrl += '</div>';
    var bodyHtml = '<div class="mc"><h4>Beam Profile (Monte Carlo Ray-Tracing)</h4><div id="beamProfileContainer"></div></div>';
    bodyHtml += '<div class="mc"><h4>Detector Configuration</h4><div class="info-grid">';
    bodyHtml += '<div class="info-item"><div class="lbl">Forward (2D)</div><div class="val" style="color:var(--pr)">Eiger2 X 500K</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">Pixel</div><div class="val">512x512, 75um</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">Lateral (SDD)</div><div class="val" style="color:var(--pk)">Vortex ME-4</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">SDD Resolution</div><div class="val">130 eV @Mn Ka</div></div></div>';
    bodyHtml += '<div style="margin-top:8px;display:flex;gap:4px">';
    bodyHtml += '<button onclick="showDetectorDemo(\'eiger\')" class="sb" style="font-size:9px;padding:3px 10px">Eiger2X Demo</button>';
    bodyHtml += '<button onclick="showDetectorDemo(\'sdd\')" class="sb" style="font-size:9px;padding:3px 10px;background:var(--pk);color:#000">SDD Demo</button>';
    bodyHtml += '</div></div>';
    bodyHtml += '<div class="info-grid">';
    bodyHtml += '<div class="info-item"><div class="lbl">Focal Size</div><div class="val" style="color:var(--gn)">' + sp2.h.toFixed(0) + 'x' + sp2.v.toFixed(0) + ' nm</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">Flux</div><div class="val">' + _flux.toExponential(2) + ' ph/s</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">Energy</div><div class="val">' + state.energy.toFixed(2) + ' keV</div></div>';
    bodyHtml += '<div class="info-item"><div class="lbl">Demag. Ratio</div><div class="val">H:' + sp2.demagH.toFixed(0) + 'x V:' + sp2.demagV.toFixed(0) + 'x</div></div>';
    bodyHtml += '</div>';
    bodyHtml += '<div id="virtualExpPanel"></div>';
    if (typeof _openPopup === 'function') {
      var _samplePopup = _openPopup({
        id: 'comp_sample', title: 'Sample Station',
        width: 520, height: 650, content: bodyHtml,
        resizable: true, minWidth: 500, minHeight: 400
      });
      setTimeout(function() {
        if (typeof renderBeamProfileCanvas === 'function') renderBeamProfileCanvas('beamProfileContainer');
        if (typeof renderExperimentPanel === 'function') renderExperimentPanel('virtualExpPanel');
      }, 100);
    } else {
      openModal('Sample Station', bodyHtml);
      setTimeout(function() {
        if (typeof renderBeamProfileCanvas === 'function') renderBeamProfileCanvas('beamProfileContainer');
        if (typeof renderExperimentPanel === 'function') renderExperimentPanel('virtualExpPanel');
      }, 100);
    }
    return;
  } else if (c.tp === 'bpm') {
    var bs3 = beamAt(p);
    var _bpmType = c.bpmType || 'generic';
    var _bpmLabel = _bpmType === 'dbpm' ? 'Diamond BPM (SI-DBPM-M403V)' : 'X-ray BPM';
    // HW/SIM badge
    var _bpmBadge = '';
    if (_bpmType === 'dbpm') {
      var _isHw = typeof EPICS_STATE !== 'undefined' && EPICS_STATE.hwGroups &&
        EPICS_STATE.hwGroups.indexOf('XBPM2') >= 0;
      _bpmBadge = _isHw
        ? ' <span style="color:var(--gn);font-size:8px;font-weight:700;border:1px solid var(--gn);border-radius:2px;padding:0 3px;margin-left:4px">HW</span>'
        : ' <span style="color:var(--t3);font-size:8px;margin-left:4px">SIM</span>';
    }
    info = '<div class="info-item"><div class="lbl">Type</div><div class="val">' + _bpmLabel + _bpmBadge + '</div></div>' +
      '<div class="info-item"><div class="lbl">Beam FWHM</div><div class="val">' + bs3.h.toFixed(0) + 'x' + bs3.v.toFixed(0) + ' \u03BCm</div></div>';
  } else if (id === 'fmask' || id === 'mmask') {
    var msId = id;
    var ms = maskState[msId];
    ctrl += mcSlider('H Gap (mm)', 0.1, 20, 0.1, ms.aperH, 'function(v){maskAperUpdate(\'' + msId + '\',\'h\',v)}');
    ctrl += mcSlider('V Gap (mm)', 0.1, 20, 0.1, ms.aperV, 'function(v){maskAperUpdate(\'' + msId + '\',\'v\',v)}');
    var maskR = calcMaskHeatLoad(msId);
    var bmAtMask = beamAt(p);
    var maskTrans = maskTransmission(msId, bmAtMask.h / 1000, bmAtMask.v / 1000);
    info = '<div class="info-item"><div class="lbl">Type</div><div class="val">' + (id === 'fmask' ? 'Fixed' : 'Movable') + ' Mask</div></div>' +
      '<div class="info-item"><div class="lbl">Aperture</div><div class="val">' + ms.aperH.toFixed(1) + 'x' + ms.aperV.toFixed(1) + ' mm</div></div>' +
      '<div class="info-item"><div class="lbl">Beam Here</div><div class="val">' + bmAtMask.h.toFixed(0) + 'x' + bmAtMask.v.toFixed(0) + ' \u03BCm</div></div>' +
      '<div class="info-item"><div class="lbl">Transmission</div><div class="val" style="color:' + (maskTrans > 0.95 ? 'var(--gn)' : maskTrans > 0.5 ? 'var(--am)' : 'var(--rd)') + '">' + (maskTrans * 100).toFixed(1) + '%</div></div>' +
      '<div class="info-item"><div class="lbl">Total Power</div><div class="val">' + maskR.P_total.toFixed(0) + ' W</div></div>' +
      '<div class="info-item"><div class="lbl">Aper. Power</div><div class="val">' + maskR.P_aper.toFixed(1) + ' W</div></div>' +
      '<div class="info-item"><div class="lbl">After Atten.</div><div class="val" style="color:' + (maskR.finalP > 500 ? 'var(--rd)' : 'var(--gn)') + '">' + maskR.finalP.toFixed(1) + ' W</div></div>' +
      '<div class="info-item"><div class="lbl">Absorbed</div><div class="val" style="color:var(--am)">' + maskR.totalAbs.toFixed(1) + ' W</div></div>' +
      '<div class="info-item"><div class="lbl">Peak Dens.</div><div class="val">' + maskR.profile.peakDens.toFixed(3) + ' W/mm2</div></div>' +
      '<div class="info-item"><div class="lbl">FWHM HxV</div><div class="val">' + maskR.profile.fwhmH.toFixed(2) + 'x' + maskR.profile.fwhmV.toFixed(2) + ' mm</div></div>';
    // Full Analysis button with motor list
    ctrl += '</div><div class="mc"><h4>Analysis</h4>';
    ctrl += '<button onclick="openMaskFullAnalysis(\'' + msId + '\')" class="sb" style="width:100%;padding:5px 10px;margin-bottom:6px;background:var(--pr);color:#fff;font-size:9px">Full Analysis (101x101 profile)</button>';
    ctrl += '<h4 style="margin-top:6px">Motors</h4>';
    ctrl += '<div id="maskMotorPanel_' + msId + '"></div>';
    ctrl += '<script>setTimeout(function(){var p=document.getElementById("maskMotorPanel_' + msId + '");if(p&&typeof MOTORS!=="undefined"&&MOTORS["' + msId + '"]){var grp=MOTORS["' + msId + '"];var ms=Array.isArray(grp)?grp:Object.values(grp).filter(function(x){return x&&x.id});var h="";ms.forEach(function(m){h+="<div style=\\"display:flex;align-items:center;gap:4px;margin:2px 0;font-size:8px\\"><span style=\\"min-width:60px;color:var(--t2)\\">"+m.name+"</span><span style=\\"color:var(--ac)\\">"+m.value.toFixed(3)+" "+m.unit+"</span></div>"});p.innerHTML=h}},50)</' + 'script>';
    ctrl += '</div><div class="mc"><button onclick="openMaskFullAnalysis(\'' + msId + '\')" class="sb" style="width:100%;font-size:9px;padding:5px;background:var(--pr);color:#fff">Full Heat Load Analysis (101x101)</button></div><div class="mc" style="display:none">';
  } else if (id === 'det') {
    var detDist = p - (pos('sample') || 150);
    var _spDet = focalSpot();
    // Detector-plane flux ~ sample-plane flux (no absorber modeled between):
    // use the single sampleFlux() API so Sample/Detector popups agree.
    var _flDet = (typeof sampleFlux === 'function') ? sampleFlux() : photonFlux(state.energy);
    info = '<div class="info-item"><div class="lbl">Type</div><div class="val">Detector Screen</div></div>' +
      '<div class="info-item"><div class="lbl">Distance</div><div class="val">' + detDist.toFixed(1) + ' m from sample</div></div>' +
      '<div class="info-item"><div class="lbl">Pixel</div><div class="val">6.5 \u03bcm (CCD)</div></div>' +
      '<div class="info-item"><div class="lbl">Energy</div><div class="val">' + state.energy.toFixed(2) + ' keV</div></div>' +
      '<div class="info-item"><div class="lbl">Flux</div><div class="val">' + _flDet.toExponential(2) + ' ph/s</div></div>' +
      '<div class="info-item"><div class="lbl">Focal Size</div><div class="val" style="color:var(--gn)">' + _spDet.h.toFixed(0) + 'x' + _spDet.v.toFixed(0) + ' nm</div></div>';
    // \u2500\u2500 Ion Chamber mode (A3): use the detector position as an I1 chamber \u2500\u2500
    // Incident flux = sample-plane flux x sample transmission x air path
    // (sample -> det, from the live positions). Gas/length/transmission are
    // user-adjustable; the air attenuation over the multi-meter path is the
    // dominant term at low energies.
    if (typeof icCurrent === 'function') {
      var _i1Gas = state.det_icGas || 'N2';
      var _i1Len = state.det_icLenCm || 10;
      var _i1Ts = (typeof state.det_icSampleT === 'number') ? state.det_icSampleT : 1.0;
      var _i1AirCm = Math.max(0, (p - (pos('sample') || 150)) * 100 - _i1Len);
      var _i1TAir = (typeof icTransmittedFraction === 'function')
        ? icTransmittedFraction('air', _i1AirCm, state.energy) : 1;
      if (isNaN(_i1TAir)) _i1TAir = 1;
      var _i1In = _flDet * _i1Ts * _i1TAir;
      var _i1A = icCurrent(_i1In, _i1Gas, _i1Len, state.energy);
      var _i1uA = _i1A * 1e6;
      var _i1Sel = '';
      ['N2', 'He', 'Ar', 'air'].forEach(function(g) {
        _i1Sel += '<option value="' + g + '"' + (_i1Gas === g ? ' selected' : '') + '>' + g + '</option>';
      });
      info += '<div class="info-item" style="grid-column:1/-1;border-top:1px solid var(--b1);margin-top:4px;padding-top:4px"><div class="lbl">ION CHAMBER (I1) MODE</div><div class="val" style="font-size:8px;color:var(--t3)">det position as transmission chamber; air path sample\u2192det = ' + _i1AirCm.toFixed(0) + ' cm</div></div>' +
        '<div class="info-item"><div class="lbl">Gas / Length</div><div class="val">' +
        '<select onchange="state.det_icGas=this.value;showComp(\'det\')" style="font-size:10px">' + _i1Sel + '</select> ' +
        '<input type="number" value="' + _i1Len + '" min="1" max="50" step="1" style="width:48px;font-size:10px" ' +
        'onchange="state.det_icLenCm=parseFloat(this.value)||10;showComp(\'det\')"/> cm</div></div>' +
        '<div class="info-item"><div class="lbl">Sample T</div><div class="val">' +
        '<input type="number" value="' + _i1Ts + '" min="0" max="1" step="0.05" style="width:55px;font-size:10px" ' +
        'onchange="state.det_icSampleT=parseFloat(this.value);showComp(\'det\')"/></div></div>' +
        '<div class="info-item"><div class="lbl">T air (path)</div><div class="val">' + (_i1TAir * 100).toFixed(2) + ' %</div></div>' +
        '<div class="info-item"><div class="lbl">Flux at I1</div><div class="val" style="color:var(--ac)">' + _i1In.toExponential(2) + ' ph/s</div></div>' +
        '<div class="info-item"><div class="lbl">I1 current</div><div class="val" style="color:var(--gn);font-weight:700">' +
        (_i1uA >= 1 ? _i1uA.toFixed(2) + ' \u00b5A' : (_i1uA * 1000).toFixed(2) + ' nA') + '</div></div>';
    }
  } else {
    info = '<div class="info-item"><div class="lbl">Type</div><div class="val">' + c.tp + '</div></div>';
  }
  ctrl += '</div>';
  var bodyHtml2 = ctrl + '<div class="info-grid">' + info + '</div>';

  // Use non-modal popup system for component details
  if (typeof _openPopup === 'function') {
    var _compPopup = _openPopup({
      id: 'comp_' + id,
      title: c.name,
      width: 460,
      height: 550,
      content: bodyHtml2,
      resizable: true,
      minWidth: 400,
      minHeight: 300
    });

    // Universal beam profile for all diagnostic components
    var profileComponents = ['bpm', 'slit', 'hmirror', 'dcm', 'kbv', 'kbh', 'sample', 'mask', 'shutter', 'det'];
    var hasProfile = false;
    for (var pi = 0; pi < profileComponents.length; pi++) {
      if (c.tp === profileComponents[pi]) { hasProfile = true; break; }
    }
    // DBPM hardware section
    if (c.tp === 'bpm' && (c.bpmType === 'dbpm') && typeof _appendDbpmToModal === 'function') {
      _appendDbpmToModal(id, _compPopup.contentEl);
    }
    if (hasProfile && typeof appendBeamProfileToModal === 'function') {
      appendBeamProfileToModal(id, p, _compPopup.contentEl);
    }
  } else {
    // Fallback: legacy modal
    openModal(c.name, bodyHtml2);
    var profileComponents2 = ['bpm', 'slit', 'hmirror', 'dcm', 'kbv', 'kbh', 'sample', 'mask', 'shutter', 'det'];
    var hasProfile2 = false;
    for (var pi2 = 0; pi2 < profileComponents2.length; pi2++) {
      if (c.tp === profileComponents2[pi2]) { hasProfile2 = true; break; }
    }
    if (c.tp === 'bpm' && (c.bpmType === 'dbpm')) { _appendDbpmToModal(id); }
    if (hasProfile2 && typeof appendBeamProfileToModal === 'function') {
      appendBeamProfileToModal(id, p);
    }
  }

};

// ===================================================================
// niceScale -- BPM beam profile scale bar helper
// ===================================================================
function niceScale(um) {
  var tgt = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];
  var ideal = um * 0.3;
  var best = tgt[0];
  for (var i = 0; i < tgt.length; i++) {
    if (Math.abs(tgt[i] - ideal) < Math.abs(best - ideal)) best = tgt[i];
  }
  if (best < 1) return { v: best, l: (best * 1000).toFixed(0) + ' nm' };
  if (best >= 1000) return { v: best, l: (best / 1000).toFixed(0) + ' mm' };
  return { v: best, l: best + ' \u03BCm' };
}

// ===================================================================
// drawBPM -- BPM beam profile rendering (uses Math.pow instead of **)
// ===================================================================
function drawBPM(bs) {
  var cv = document.getElementById('diagCanvas');
  if (!cv) return;
  var ctx = cv.getContext('2d');
  var w = cv.width, h = cv.height, cx = w / 2, cy = h / 2;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);
  var sH = bs.h / 2.355, sV = bs.v / 2.355;
  var vwH = bs.h * 4, vwV = bs.v * 4;
  var scH = w / vwH, scV = h / vwV;
  var img = ctx.createImageData(w, h);
  for (var py = 0; py < h; py++) {
    for (var px = 0; px < w; px++) {
      var x = (px - cx) / scH, y = (py - cy) / scV;
      var v = Math.exp(-0.5 * (Math.pow(x / sH, 2) + Math.pow(y / sV, 2)));
      var idx = (py * w + px) * 4;
      img.data[idx] = Math.round(v * 60);
      img.data[idx + 1] = Math.round(v * 180 + (1 - v) * 10);
      img.data[idx + 2] = Math.round(v * 255);
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  ctx.strokeStyle = 'rgba(255,255,255,.25)';
  ctx.lineWidth = 0.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();
  ctx.setLineDash([]);
  var sc = niceScale(vwH);
  var barPx = sc.v * scH;
  ctx.fillStyle = '#fff';
  ctx.fillRect(20, h - 22, barPx, 2);
  ctx.fillRect(20, h - 26, 1, 8);
  ctx.fillRect(20 + barPx, h - 26, 1, 8);
  ctx.font = '10px IBM Plex Mono';
  ctx.fillText(sc.l, 20, h - 30);
  ctx.fillStyle = 'rgba(77,184,255,.8)';
  ctx.fillText('H: ' + bs.h.toFixed(1) + ' \u03BCm', w - 130, 18);
  ctx.fillText('V: ' + bs.v.toFixed(1) + ' \u03BCm', w - 130, 32);
}

// ===================================================================
// _appendDbpmToModal -- DBPM hardware section (T4U Viewer style)
// Layout: Position X-Y plot (left) + Channel bar graph (right)
//         Status info row (bottom)
// ===================================================================
function _appendDbpmToModal(compId, containerEl) {
  var mb = containerEl || document.getElementById('modalBody');
  if (!mb) return;

  var div = document.createElement('div');
  div.className = 'mc';
  div.id = 'dbpmSection_' + compId;

  var h = '<h4 style="margin-bottom:6px">DBPM Hardware (T4U quadEM)</h4>';
  // Main row: Position canvas (left) + Channel values (right)
  h += '<div style="display:flex;gap:8px;align-items:stretch">';
  // Position X-Y plot (T4U Viewer style)
  h += '<canvas id="dbpm_pos_' + compId + '" ' +
    'style="flex:3;min-width:160px;aspect-ratio:1;background:#fff;border:1px solid #ccc"></canvas>';
  // Channel currents — text grid (replaces bar chart)
  h += '<div style="flex:2;min-width:120px;display:flex;flex-direction:column;justify-content:center;gap:6px;' +
    'padding:8px;background:#fafafa;border:1px solid #ccc;border-radius:2px;font-family:monospace">';
  h += '<div style="font-size:10px;color:#333;font-weight:700;text-align:center;margin-bottom:2px">Channel Currents</div>';
  var chLabels = ['A', 'B', 'C', 'D'];
  var chColors = ['#e5a50a', '#26a269', '#1a5fb4', '#c01c28'];
  for (var ci = 0; ci < 4; ci++) {
    h += '<div style="display:flex;justify-content:space-between;align-items:center;font-size:10px">' +
      '<span style="color:' + chColors[ci] + ';font-weight:700">Ch ' + chLabels[ci] + '</span>' +
      '<span id="dbpm_' + compId + '_c' + (ci + 1) + '" style="color:#333">--</span>' +
    '</div>';
  }
  h += '</div>';
  h += '</div>';
  // Status info row
  h += '<div style="display:flex;flex-wrap:wrap;gap:4px 16px;padding:5px 0 0;font-size:10px;color:#333;font-family:monospace">' +
    '<span>Pos X: <b id="dbpm_' + compId + '_px" style="color:#1a5fb4">--</b></span>' +
    '<span>Pos Y: <b id="dbpm_' + compId + '_py" style="color:#1a5fb4">--</b></span>' +
    '<span>Sum: <b id="dbpm_' + compId + '_sum" style="color:#26a269">--</b></span>' +
    '<span>Range: <span id="dbpm_' + compId + '_rng">--</span></span>' +
    '<span>Bias: <span id="dbpm_' + compId + '_bias">--</span></span>' +
    '<span>Freq: <span id="dbpm_' + compId + '_freq">--</span></span>' +
  '</div>';

  div.innerHTML = h;
  mb.appendChild(div);

  // Initial update + timer
  setTimeout(function() { _updateDbpmModal(compId); }, 100);
  var _dbpmTimer = setInterval(function() {
    if (!document.getElementById('dbpmSection_' + compId)) {
      clearInterval(_dbpmTimer);
      return;
    }
    _updateDbpmModal(compId);
  }, 1000);
}

// Format current with auto unit (pA/nA/uA/mA)
function _dbpmFmtCurrent(nA) {
  if (nA === null || nA === undefined) return '--';
  var abs = Math.abs(nA);
  if (abs >= 1e6) return (nA / 1e6).toFixed(3) + ' mA';
  if (abs >= 1e3) return (nA / 1e3).toFixed(3) + ' uA';
  if (abs >= 1)   return nA.toFixed(3) + ' nA';
  if (abs >= 0.001) return (nA * 1e3).toFixed(1) + ' pA';
  return nA.toExponential(1) + ' nA';
}


// Read PV value
function _dbpmGetPV(name) {
  if (typeof PV_REGISTRY !== 'undefined' && PV_REGISTRY[name]) return PV_REGISTRY[name].value;
  if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.simIOC && EPICS_STATE.simIOC.pvs[name]) return EPICS_STATE.simIOC.pvs[name].value;
  return null;
}

// Update DBPM modal PV values
function _updateDbpmModal(compId) {
  var posCanvas = document.getElementById('dbpm_pos_' + compId);
  if (!posCanvas) return;

  var prefix = 'BL10:XBPM2:';
  var RANGE_LABELS = ['Low (5mA)', 'Med (100uA)', 'Hi (300nA)'];
  var FREQ_LABELS = {10000: '10 kHz', 4000: '4 kHz', 500: '500 Hz'};

  var c1 = _dbpmGetPV(prefix + 'Current1:MeanValue_RBV');
  var c2 = _dbpmGetPV(prefix + 'Current2:MeanValue_RBV');
  var c3 = _dbpmGetPV(prefix + 'Current3:MeanValue_RBV');
  var c4 = _dbpmGetPV(prefix + 'Current4:MeanValue_RBV');
  var sum = _dbpmGetPV(prefix + 'SumAll:MeanValue_RBV');
  var px = _dbpmGetPV(prefix + 'PosX:MeanValue_RBV');
  var py = _dbpmGetPV(prefix + 'PosY:MeanValue_RBV');
  var rng = _dbpmGetPV(prefix + 'Range');
  var bias = _dbpmGetPV(prefix + 'BiasPEn');
  var freq = _dbpmGetPV(prefix + 'SampleFreq');

  // Update text readouts
  var pxEl = document.getElementById('dbpm_' + compId + '_px');
  if (pxEl) pxEl.textContent = px !== null ? px.toFixed(4) : '--';
  var pyEl = document.getElementById('dbpm_' + compId + '_py');
  if (pyEl) pyEl.textContent = py !== null ? py.toFixed(4) : '--';
  var sumEl = document.getElementById('dbpm_' + compId + '_sum');
  if (sumEl) sumEl.textContent = _dbpmFmtCurrent(sum);
  var rngEl = document.getElementById('dbpm_' + compId + '_rng');
  if (rngEl) rngEl.textContent = rng !== null && rng >= 0 && rng <= 2 ? RANGE_LABELS[rng] : '--';
  var biasEl = document.getElementById('dbpm_' + compId + '_bias');
  if (biasEl) {
    biasEl.textContent = bias ? 'ON' : 'OFF';
    biasEl.style.color = bias ? '#26a269' : '#888';
    biasEl.style.fontWeight = bias ? '700' : '400';
  }
  var freqEl = document.getElementById('dbpm_' + compId + '_freq');
  if (freqEl) {
    var freqRound = freq !== null ? Math.round(freq) : null;
    freqEl.textContent = freqRound !== null ? (FREQ_LABELS[freqRound] || freqRound + ' Hz') : '--';
  }

  // Update channel current text values
  var c1El = document.getElementById('dbpm_' + compId + '_c1');
  if (c1El) c1El.textContent = _dbpmFmtCurrent(c1);
  var c2El = document.getElementById('dbpm_' + compId + '_c2');
  if (c2El) c2El.textContent = _dbpmFmtCurrent(c2);
  var c3El = document.getElementById('dbpm_' + compId + '_c3');
  if (c3El) c3El.textContent = _dbpmFmtCurrent(c3);
  var c4El = document.getElementById('dbpm_' + compId + '_c4');
  if (c4El) c4El.textContent = _dbpmFmtCurrent(c4);

  // Draw position canvas
  _drawDbpmPosition('dbpm_pos_' + compId, px, py);
}

// Draw T4U-style X-Y position plot (white bg, grid, beam dot) — HiDPI
function _drawDbpmPosition(canvasId, posX, posY) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;
  var cw = cv.clientWidth, ch = cv.clientHeight;
  if (cw <= 0 || ch <= 0) return;

  // HiDPI: buffer at DPR scale, draw in CSS px
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = cw * dpr;
  cv.height = ch * dpr;
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  var w = cw, h = ch;

  // White background
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, w, h);

  // Plot area margins (leave room for axis labels)
  var ml = 32, mr = 10, mt = 10, mb = 22;
  var pw = w - ml - mr, ph = h - mt - mb;

  // Grid lines (at -1, -0.5, 0, 0.5, 1)
  ctx.strokeStyle = '#ddd';
  ctx.lineWidth = 0.5;
  var ticks = [-1, -0.5, 0, 0.5, 1];
  for (var ti = 0; ti < ticks.length; ti++) {
    var t = ticks[ti];
    var gy = mt + ph * (1 - (t + 1) / 2);
    ctx.beginPath(); ctx.moveTo(ml, gy); ctx.lineTo(ml + pw, gy); ctx.stroke();
    var gx = ml + pw * (t + 1) / 2;
    ctx.beginPath(); ctx.moveTo(gx, mt); ctx.lineTo(gx, mt + ph); ctx.stroke();
  }

  // Axis lines (at 0)
  ctx.strokeStyle = '#999';
  ctx.lineWidth = 1;
  var zeroX = ml + pw * 0.5;
  var zeroY = mt + ph * 0.5;
  ctx.beginPath(); ctx.moveTo(ml, zeroY); ctx.lineTo(ml + pw, zeroY); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(zeroX, mt); ctx.lineTo(zeroX, mt + ph); ctx.stroke();

  // Axis labels (normalized, unitless)
  ctx.fillStyle = '#666';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'right';
  for (var li = 0; li < ticks.length; li++) {
    var lv = ticks[li];
    var ly = mt + ph * (1 - (lv + 1) / 2);
    ctx.fillText(lv === 0 ? '0' : lv.toString(), ml - 4, ly + 3);
  }
  ctx.textAlign = 'center';
  for (var xi = 0; xi < ticks.length; xi++) {
    var xv = ticks[xi];
    var lx = ml + pw * (xv + 1) / 2;
    ctx.fillText(xv === 0 ? '0' : xv.toString(), lx, mt + ph + 12);
  }

  // Axis unit labels
  ctx.fillStyle = '#999';
  ctx.font = '8px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('X (norm.)', ml + pw / 2, mt + ph + 20);
  ctx.save();
  ctx.translate(8, mt + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Y (norm.)', 0, 0);
  ctx.restore();

  // Plot border
  ctx.strokeStyle = '#bbb';
  ctx.lineWidth = 1;
  ctx.strokeRect(ml, mt, pw, ph);

  // Beam position dot
  if (posX !== null && posY !== null && isFinite(posX) && isFinite(posY)) {
    var clampX = Math.max(-1, Math.min(1, posX));
    var clampY = Math.max(-1, Math.min(1, posY));
    var bx = ml + pw * (clampX + 1) / 2;
    var by = mt + ph * (1 - (clampY + 1) / 2);
    // Dot
    ctx.fillStyle = '#1a5fb4';
    ctx.beginPath(); ctx.arc(bx, by, 4, 0, 2 * Math.PI); ctx.fill();
    // Crosshair
    ctx.strokeStyle = 'rgba(26,95,180,0.4)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(ml, by); ctx.lineTo(ml + pw, by); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx, mt); ctx.lineTo(bx, mt + ph); ctx.stroke();
    ctx.setLineDash([]);
  }
}

// _drawDbpmBars removed — replaced by text grid in _appendDbpmToModal

console.log('[ui/05_modal] Modal system loaded (inline merged, Phase 6)');

// ESM bridge: expose module-scoped vars to globalThis
if(typeof curModal!=="undefined")globalThis.curModal=curModal;
if(typeof drawBPM!=="undefined")globalThis.drawBPM=drawBPM;
if(typeof niceScale!=="undefined")globalThis.niceScale=niceScale;
if(typeof _alignPopupDismissed!=="undefined")globalThis._alignPopupDismissed=_alignPopupDismissed;
if(typeof _appendDbpmToModal!=="undefined")globalThis._appendDbpmToModal=_appendDbpmToModal;
if(typeof _dbpmFmtCurrent!=="undefined")globalThis._dbpmFmtCurrent=_dbpmFmtCurrent;
if(typeof _dbpmGetPV!=="undefined")globalThis._dbpmGetPV=_dbpmGetPV;
if(typeof _drawDbpmPosition!=="undefined")globalThis._drawDbpmPosition=_drawDbpmPosition;
if(typeof _makePopupResizable!=="undefined")globalThis._makePopupResizable=_makePopupResizable;
if(typeof _mcId!=="undefined")globalThis._mcId=_mcId;
if(typeof _updateDbpmModal!=="undefined")globalThis._updateDbpmModal=_updateDbpmModal;
if(typeof closeModal!=="undefined")globalThis.closeModal=closeModal;
if(typeof mcSlider!=="undefined")globalThis.mcSlider=mcSlider;
if(typeof modalSetPos!=="undefined")globalThis.modalSetPos=modalSetPos;
if(typeof openModal!=="undefined")globalThis.openModal=openModal;
if(typeof showComp!=="undefined")globalThis.showComp=showComp;
