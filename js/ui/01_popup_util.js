'use strict';
// ===== ui/01_popup_util.js — UI Zoom + Popup Resize Utility =====
// @module ui/01_popup_util
// @exports _makePopupResizable, _openModal, _openPopup, _popupManager, setUIZoom
// Extracted from 14_v435_final.js (DDD Phase 5b)
// Provides: setUIZoom, _makePopupResizable

// ===== UI Zoom Control =====
// Persists zoom level to localStorage, applies CSS --ui-zoom variable
(function(){
  var stored = localStorage.getItem('k4gsr_ui_zoom');
  if (stored) {
    var z = parseFloat(stored);
    if (!isNaN(z) && z >= 0.8 && z <= 3.0) {
      document.documentElement.style.setProperty('--ui-zoom', z);
      document.documentElement.style.setProperty('--rside-w', Math.round(300 * z) + 'px');
    }
  }
  // Update label after DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    var z = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom')) || 1.8;
    var lbl = document.getElementById('uiZoomLabel');
    if (lbl) lbl.textContent = Math.round(z * 100) + '%';
  });
})();
window.setUIZoom = function(delta) {
  var cs = getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom');
  var cur = parseFloat(cs) || 1.8;
  var nv = Math.round((cur + delta) * 10) / 10;
  if (nv < 0.8) nv = 0.8;
  if (nv > 3.0) nv = 3.0;
  document.documentElement.style.setProperty('--ui-zoom', nv);
  localStorage.setItem('k4gsr_ui_zoom', nv);
  var lbl = document.getElementById('uiZoomLabel');
  if (lbl) lbl.textContent = Math.round(nv * 100) + '%';
  // Update right sidebar width proportionally
  var baseW = 300;
  document.documentElement.style.setProperty('--rside-w', Math.round(baseW * nv) + 'px');
};

// ===== Unified Popup Utility: Drag-to-Move + Edge Resize =====
// Principle: All popups/UIs support (1) title bar drag-to-move (2) all-edge drag-to-resize
// opts.dragEl — title bar element for drag-to-move (omit to disable move, resize only)
// opts.minWidth — minimum width (default 300px)
// opts.minHeight — minimum height (default 200px)
window._makePopupResizable = function(boxEl, opts) {
  opts = opts || {};
  var minW = opts.minWidth || 300;
  var minH = opts.minHeight || 200;
  var dragEl = opts.dragEl || null;
  var EDGE = 14; // edge detection zone in px (wider for easier grab)
  var onResizeCb = opts.onResize || null;

  boxEl.style.resize = 'none';
  boxEl.style.overflow = 'auto';
  if (!boxEl.style.position || boxEl.style.position === 'static') {
    boxEl.style.position = 'relative';
  }

  // --- Helper: get CSS zoom factor (for coordinate correction) ---
  function getZoom() {
    var z = parseFloat(boxEl.style.zoom);
    if (!z || isNaN(z)) {
      z = parseFloat(getComputedStyle(boxEl).zoom);
    }
    return (z && !isNaN(z) && z > 0) ? z : 1;
  }

  // --- Helper: switch to fixed position (break out of flex centering) ---
  // Accounts for CSS zoom: getBoundingClientRect returns viewport coords
  // (zoomed), but style.left/top are in the element's pre-zoom space.
  function switchToFixed() {
    if (boxEl.style.position === 'fixed') return;
    var rect = boxEl.getBoundingClientRect();
    var z = getZoom();
    boxEl.style.position = 'fixed';
    boxEl.style.left = (rect.left / z) + 'px';
    boxEl.style.top = (rect.top / z) + 'px';
    boxEl.style.margin = '0';
    boxEl.style.width = (rect.width / z) + 'px';
    boxEl.style.height = (rect.height / z) + 'px';
  }

  // --- Drag-to-move (on title bar) ---
  if (dragEl) {
    dragEl.style.cursor = 'move';
    dragEl.style.userSelect = 'none';
    dragEl.addEventListener('mousedown', function(e) {
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT' ||
          e.target.tagName === 'SELECT' || (e.target.closest && e.target.closest('button'))) return;
      e.preventDefault();
      e.stopPropagation(); // Prevent boxEl resize handler from also firing
      switchToFixed();
      var z = getZoom();
      var startX = e.clientX, startY = e.clientY;
      var oL = parseFloat(boxEl.style.left) || 0;
      var oT = parseFloat(boxEl.style.top) || 0;
      function onMove(ev) {
        var dx = (ev.clientX - startX) / z;
        var dy = (ev.clientY - startY) / z;
        boxEl.style.left = (oL + dx) + 'px';
        boxEl.style.top = Math.max(0, oT + dy) + 'px';
      }
      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // --- Edge detect: which edges are near the mouse? ---
  function getEdges(e) {
    var rect = boxEl.getBoundingClientRect();
    var x = e.clientX - rect.left, y = e.clientY - rect.top;
    var w = rect.width, h = rect.height;
    // EDGE is in logical px, but rect is in viewport (zoomed) px
    var z = getZoom();
    var ez = EDGE * z;
    return {
      top: y < ez, bottom: y > h - ez,
      left: x < ez, right: x > w - ez
    };
  }

  function edgeCursor(ed) {
    if ((ed.top && ed.left) || (ed.bottom && ed.right)) return 'nwse-resize';
    if ((ed.top && ed.right) || (ed.bottom && ed.left)) return 'nesw-resize';
    if (ed.top || ed.bottom) return 'ns-resize';
    if (ed.left || ed.right) return 'ew-resize';
    return '';
  }

  // --- Mousemove on box: update cursor ---
  boxEl.addEventListener('mousemove', function(e) {
    if (boxEl._resizing) return;
    var ed = getEdges(e);
    var cur = edgeCursor(ed);
    boxEl.style.cursor = cur || '';
  });

  boxEl.addEventListener('mouseleave', function() {
    if (!boxEl._resizing) boxEl.style.cursor = '';
  });

  // --- Mousedown on edge: start resize ---
  boxEl.addEventListener('mousedown', function(e) {
    var ed = getEdges(e);
    if (!ed.top && !ed.bottom && !ed.left && !ed.right) return;
    // Don't resize if clicking on interactive elements (but allow CANVAS edge resize)
    if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT' ||
        e.target.tagName === 'SELECT') return;
    e.preventDefault(); e.stopPropagation();
    switchToFixed();
    boxEl._resizing = true;

    var z = getZoom();
    var startX = e.clientX, startY = e.clientY;
    var oL = parseFloat(boxEl.style.left) || 0;
    var oT = parseFloat(boxEl.style.top) || 0;
    var oW = parseFloat(boxEl.style.width) || boxEl.offsetWidth;
    var oH = parseFloat(boxEl.style.height) || boxEl.offsetHeight;
    var cur = edgeCursor(ed);

    document.body.style.cursor = cur;
    document.body.style.userSelect = 'none';

    function onMove(ev) {
      var dx = (ev.clientX - startX) / z;
      var dy = (ev.clientY - startY) / z;
      var nL = oL, nT = oT, nW = oW, nH = oH;
      if (ed.right) nW = Math.max(minW, oW + dx);
      if (ed.bottom) nH = Math.max(minH, oH + dy);
      if (ed.left) { nW = Math.max(minW, oW - dx); nL = oL + oW - nW; }
      if (ed.top) { nH = Math.max(minH, oH - dy); nT = oT + oH - nH; }
      boxEl.style.left = nL + 'px';
      boxEl.style.top = Math.max(0, nT) + 'px';
      boxEl.style.width = nW + 'px';
      boxEl.style.height = nH + 'px';
      if (onResizeCb) try { onResizeCb(nW, nH); } catch(e){}
    }
    function onUp() {
      boxEl._resizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      // If an onResize callback is provided, let it handle canvas resizing
      // (avoids clearing uPlot-managed canvases which causes white screen).
      // Otherwise, auto-resize non-overlay canvases.
      if (onResizeCb) {
        try { onResizeCb(); } catch(e){}
      } else {
        var cvs = boxEl.querySelectorAll('canvas');
        for (var i = 0; i < cvs.length; i++) {
          var cv = cvs[i];
          if (cv.getAttribute('data-overlay')) continue;
          var cw = cv.clientWidth, ch = cv.clientHeight;
          if (cw > 0 && cv.width !== cw) { cv.width = cw; cv.height = ch; }
        }
      }
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  // --- Visual corner indicators (all 4 corners, subtle) ---
  var corners = [
    {r:'0',b:'0',deg:'135',br:'0 0 6px 0'},
    {l:'0',b:'0',deg:'225',br:'0 0 0 6px'},
    {l:'0',t:'0',deg:'315',br:'6px 0 0 0'},
    {r:'0',t:'0',deg:'45',br:'0 6px 0 0'}
  ];
  for (var ci = 0; ci < corners.length; ci++) {
    var cc = corners[ci];
    var corner = document.createElement('div');
    var pos = 'position:absolute;width:14px;height:14px;z-index:10;pointer-events:none;';
    if (cc.r !== undefined) pos += 'right:' + cc.r + ';';
    if (cc.l !== undefined) pos += 'left:' + cc.l + ';';
    if (cc.t !== undefined) pos += 'top:' + cc.t + ';';
    if (cc.b !== undefined) pos += 'bottom:' + cc.b + ';';
    corner.style.cssText = pos
      + 'background:linear-gradient(' + cc.deg + 'deg,transparent 50%,var(--t3,#6b7280) 50%,var(--t3,#6b7280) 65%,transparent 65%,'
      + 'transparent 75%,var(--t3,#6b7280) 75%,var(--t3,#6b7280) 85%,transparent 85%);opacity:0.4;border-radius:' + cc.br;
    boxEl.appendChild(corner);
  }
};

// ===== Non-Modal Popup Manager =====
// Multi-window system: multiple popups open simultaneously, no background overlay.
// Click to focus (bring to front), drag to move, resize edges/corners.
var _popupManager = {
  list: [],
  topZ: 9000,
  bringToFront: function(el) {
    this.topZ += 1;
    el.style.zIndex = this.topZ;
  },
  register: function(el) { this.list.push(el); },
  unregister: function(el) {
    this.list = this.list.filter(function(p) { return p !== el; });
  },
  findById: function(id) {
    for (var i = 0; i < this.list.length; i++) {
      if (this.list[i].id === id) return this.list[i];
    }
    return null;
  }
};
window._popupManager = _popupManager;

// _openPopup — create a non-modal, draggable, resizable popup window
// opts: {
//   id: 'unique_id',          // reuse existing popup if same id
//   title: 'Window Title',
//   width: 500, height: 400,  // initial size
//   x: 100, y: 100,           // initial position (auto if omitted)
//   content: html or element,  // inner content
//   onClose: function,
//   modal: false,              // true = add background overlay
//   resizable: true,
//   minWidth: 300, minHeight: 200,
//   headerColor: 'var(--ac)'  // title bar accent color
// }
// Returns: { el, contentEl, close(), setTitle(t), setContent(c) }
window._openPopup = function(opts) {
  opts = opts || {};
  var id = opts.id || ('popup_' + Date.now());

  // If same ID already open, bring to front
  var existing = _popupManager.findById(id);
  if (existing) {
    _popupManager.bringToFront(existing);
    return existing._popupAPI;
  }

  // Modal overlay (only if opts.modal)
  var overlay = null;
  if (opts.modal) {
    overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.45);z-index:' + (_popupManager.topZ + 1);
    document.body.appendChild(overlay);
  }

  // Popup container
  var pop = document.createElement('div');
  pop.id = id;
  _popupManager.topZ += 2;
  var z = _popupManager.topZ;
  // Account for CSS zoom when computing size and center position
  var uiZoom = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom')) || 1.8;
  var viewW = window.innerWidth / uiZoom;
  var viewH = window.innerHeight / uiZoom;
  var w = opts.width || 340, h = opts.height || 280;
  var x = opts.x != null ? opts.x : Math.max(10, Math.round((viewW - w) / 2));
  var y = opts.y != null ? opts.y : Math.max(10, Math.round((viewH - h) / 2));
  pop.style.cssText = 'position:fixed;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;'
    + 'z-index:' + z + ';background:var(--bg,#1a1d23);border:1px solid var(--b1,#21262d);'
    + 'border-radius:6px;box-shadow:0 8px 32px rgba(0,0,0,0.5);display:flex;flex-direction:column;'
    + 'overflow:hidden;font-family:var(--mn,monospace);color:var(--t1,#e8eaed);'
    + 'zoom:var(--ui-zoom,1.8)';

  // Title bar
  var hdrColor = opts.headerColor || 'var(--ac,#4db8ff)';
  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;align-items:center;padding:6px 10px;background:var(--s1,#22252b);'
    + 'border-bottom:1px solid var(--b1,#21262d);cursor:move;user-select:none;flex-shrink:0';
  hdr.innerHTML = '<span style="flex:1;font-size:11px;font-weight:600;color:' + hdrColor + '">' + (opts.title || '') + '</span>'
    + '<button style="background:none;border:none;color:var(--t3,#6b7280);font-size:16px;cursor:pointer;padding:0 4px;line-height:1">&times;</button>';
  pop.appendChild(hdr);

  // Content area
  var contentEl = document.createElement('div');
  contentEl.style.cssText = 'flex:1;overflow:auto;padding:8px';
  if (typeof opts.content === 'string') contentEl.innerHTML = opts.content;
  else if (opts.content instanceof HTMLElement) contentEl.appendChild(opts.content);
  pop.appendChild(contentEl);

  document.body.appendChild(pop);
  _popupManager.register(pop);

  // Close handler
  var closeBtn = hdr.querySelector('button');
  function closePopup() {
    if (overlay) overlay.remove();
    pop.remove();
    _popupManager.unregister(pop);
    if (opts.onClose) opts.onClose();
  }
  closeBtn.onclick = closePopup;
  if (overlay) overlay.onclick = closePopup;

  // Click to focus (bring to front)
  pop.addEventListener('mousedown', function() {
    _popupManager.bringToFront(pop);
  });

  // Make resizable + draggable
  if (opts.resizable !== false) {
    _makePopupResizable(pop, {
      dragEl: hdr,
      minWidth: opts.minWidth || 300,
      minHeight: opts.minHeight || 200
    });
  }

  // API object
  var api = {
    el: pop,
    contentEl: contentEl,
    close: closePopup,
    setTitle: function(t) {
      var span = hdr.querySelector('span');
      if (span) span.textContent = t;
    },
    setContent: function(c) {
      if (typeof c === 'string') contentEl.innerHTML = c;
      else { contentEl.innerHTML = ''; contentEl.appendChild(c); }
    }
  };
  pop._popupAPI = api;
  return api;
};

// _openModal — convenience wrapper for modal dialogs (safety confirm, etc.)
window._openModal = function(opts) {
  opts = opts || {};
  opts.modal = true;
  return _openPopup(opts);
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _makePopupResizable!=="undefined")globalThis._makePopupResizable=_makePopupResizable;
if(typeof _openModal!=="undefined")globalThis._openModal=_openModal;
if(typeof _openPopup!=="undefined")globalThis._openPopup=_openPopup;
if(typeof _popupManager!=="undefined")globalThis._popupManager=_popupManager;
if(typeof setUIZoom!=="undefined")globalThis.setUIZoom=setUIZoom;
