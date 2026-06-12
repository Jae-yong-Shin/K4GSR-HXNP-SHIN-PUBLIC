'use strict';
// ===== optics/05_beam_optics.js — updateOptics (inline merged) =====
// @module optics/05_beam_optics
// @exports updateOptics
// Extracted from 08_ui_core.js + 12_v435_physics.js (DDD Phase 6)
// Base: sidebar slit/spot/demag updates + renderLayout
// Addition: _mcSampleCache invalidation + beamAt status bar updates

// === updateOptics — INLINE MERGED (base + status bar wrapper) ===
window.updateOptics = function() {
  // --- base logic (from 08_ui_core.js) ---
  var _s = function(id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
  var _v = function(id, v) { var e = document.getElementById(id); if (e) e.value = v; };
  _v('wbH', state.wbH); _v('wbV', state.wbV);
  _v('ssaH', state.ssaH); _v('ssaV', state.ssaV);
  // Invalidate MC cache BEFORE focalSpot() so it re-computes with new physics
  if (typeof _invalidateMCCache === 'function') _invalidateMCCache();
  var s = focalSpot();
  _s('vSpot', s.h.toFixed(0) + ' x ' + s.v.toFixed(0) + ' nm');
  _s('vDemag', 'H:' + s.demagH.toFixed(0) + 'x V:' + s.demagV.toFixed(0) + 'x');
  try { renderLayout(); } catch (e) {}
  if (typeof updateLiveBeamInfo === 'function') {
    try { updateLiveBeamInfo(); } catch (e) {}
  }

  // --- status bar updates (beamAt is analytical, no MC needed) ---
  var diagIds = ['fmask', 'mmask', 'wbslit', 'ssa', 'sample'];
  diagIds.forEach(function(id) {
    var el = document.getElementById('beamAt_' + id);
    if (!el) return;
    if (id === 'sample') {
      // Re-use cached focalSpot result (dirty already cleared above)
      el.textContent = ' ' + s.h.toFixed(0) + 'x' + s.v.toFixed(0) + ' nm';
      el.style.color = 'var(--gn)';
    } else {
      var b = beamAt(pos(id));
      var d2 = b.h > 1e3 ? 1e3 : 1, uu = b.h > 1e3 ? 'mm' : 'um';
      el.textContent = ' ' + (b.h / d2).toFixed(b.h > 1e3 ? 2 : 1) + 'x' + (b.v / d2).toFixed(b.h > 1e3 ? 2 : 1) + ' ' + uu;
      el.style.color = 'var(--ac)';
    }
  });
};

// Initial update after load
setTimeout(function() {
  if (typeof updateOptics === 'function') updateOptics();
}, 500);

console.log('[' + APP_VTAG + '] updateOptics inline merged (base + status bar)');

// ESM bridge: expose module-scoped vars to globalThis
if(typeof updateOptics!=="undefined")globalThis.updateOptics=updateOptics;
