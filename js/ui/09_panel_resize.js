'use strict';
// ===== ui/09_panel_resize.js — Panel Drag-Resize + SVG Pan =====
// @module ui/09_panel_resize
// Extracted from 14_v435_final.js (DDD Phase 5b)
// Provides: right/bottom panel resize, SVG click-drag/scrollbar/wheel pan

// === Panel Drag-Resize (with proportional zoom) ===
// Principle: panel resize scales text and content proportionally
// Direct zoom applied -- grid column/row controlled by explicit sizes
(function(){
  var app = document.querySelector('.app');
  var rside = document.querySelector('.rside');
  var bpan = document.querySelector('.bpan');
  if (!app) return;

  // --- Right panel horizontal resize ---
  var rH = document.getElementById('resizerH');
  var rsideW = 320;
  if (rH) {
    rH.addEventListener('mousedown', function(e) {
      e.preventDefault();
      rH.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      var startX = e.clientX;
      var startW = rsideW;
      function onMove(e2) {
        var dx = startX - e2.clientX;
        rsideW = Math.max(220, Math.min(600, startW + dx));
        app.style.setProperty('--rside-w', rsideW + 'px');
        // Proportional zoom — all content (text, boxes, inputs) scales together
        if (rside) rside.style.zoom = rsideW / 320;
      }
      function onUp() {
        rH.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // --- Bottom panel vertical resize (CSS variable only) ---
  // Change height:var(--bpan-h) -- grid auto row tracks naturally
  // No gridTemplateRows manipulation, no zoom, no maxHeight override
  var rV = document.getElementById('resizerV');
  var bpanH = 160;
  if (rV && bpan) {
    rV.addEventListener('mousedown', function(e) {
      e.preventDefault();
      rV.classList.add('active');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      // Sync actual height at each drag start
      bpanH = bpan.getBoundingClientRect().height || 160;
      var startY = e.clientY;
      var startH = bpanH;
      function onMove(e2) {
        var dy = startY - e2.clientY;
        bpanH = Math.max(80, Math.min(500, startH + dy));
        app.style.setProperty('--bpan-h', bpanH + 'px');
      }
      function onUp() {
        rV.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  console.log('[' + APP_VTAG + '] Panel resize handlers initialized (with proportional zoom)');
})();

// === SVG Pan (click-drag + horizontal scrollbar) ===
(function(){
  var svg = document.getElementById('blSvg');
  var slider = document.getElementById('svgPanSlider');
  if (!svg || !slider) return;

  var VB_W = 1200, VB_H = 400;
  var panX = 0;
  var panMin = 0, panMax = 0;
  var _firstCalc = true;

  /* Calculate pan range based on container vs viewBox aspect ratio */
  function calcPanRange() {
    var rect = svg.getBoundingClientRect();
    var cW = rect.width, cH = rect.height;
    if (cH <= 0 || cW <= 0) return;

    var cAspect = cW / cH;
    var vAspect = VB_W / VB_H; // 3.0

    if (cAspect < vAspect) {
      // Container taller than viewBox → slice clips horizontally
      var visibleW = cW * VB_H / cH;
      var clipped = VB_W - visibleW;
      panMin = -(clipped / 2);
      panMax = clipped / 2;
    } else {
      // Container wider → no horizontal clipping
      panMin = 0;
      panMax = 0;
    }

    if (_firstCalc) { panX = panMin; _firstCalc = false; }
    panX = Math.max(panMin, Math.min(panMax, panX));
    slider.min = Math.round(panMin);
    slider.max = Math.round(panMax);
    slider.value = Math.round(panX);
    slider.disabled = (panMin >= panMax);
  }

  function applyPan() {
    svg.setAttribute('viewBox', panX + ' 0 ' + VB_W + ' ' + VB_H);
  }

  /* Slider input -> pan */
  slider.addEventListener('input', function() {
    panX = parseFloat(slider.value);
    applyPan();
  });

  /* Click-drag on SVG empty space -> pan */
  var dragging = false, startMX, startPanX;

  svg.addEventListener('mousedown', function(e) {
    // comp-g has stopPropagation in dragStart, so this only fires on empty space
    if (e.button !== 0) return;
    dragging = true;
    startMX = e.clientX;
    startPanX = panX;
    svg.classList.add('panning');
    e.preventDefault();
    document.addEventListener('mousemove', onPanMove);
    document.addEventListener('mouseup', onPanEnd);
  });

  function onPanMove(e) {
    if (!dragging) return;
    var dx = e.clientX - startMX;
    // Convert pixel dx to SVG coordinate units
    var rect = svg.getBoundingClientRect();
    var scale = rect.height > 0 ? VB_H / rect.height : 1;
    panX = Math.max(panMin, Math.min(panMax, startPanX - dx * scale));
    applyPan();
    slider.value = Math.round(panX);
  }

  function onPanEnd() {
    dragging = false;
    svg.classList.remove('panning');
    document.removeEventListener('mousemove', onPanMove);
    document.removeEventListener('mouseup', onPanEnd);
  }

  /* Mouse wheel on SVG -> horizontal pan */
  svg.addEventListener('wheel', function(e) {
    if (panMin >= panMax) return;
    e.preventDefault();
    var delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
    panX = Math.max(panMin, Math.min(panMax, panX + delta * 0.5));
    applyPan();
    slider.value = Math.round(panX);
  }, {passive: false});

  /* Recalc on any resize (window or panel drag) */
  var resizeTimer;
  function schedRecalc() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function() { calcPanRange(); applyPan(); }, 80);
  }
  window.addEventListener('resize', schedRecalc);
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(schedRecalc).observe(svg);
  }

  /* Initial */
  setTimeout(function() {
    calcPanRange();
    applyPan();
  }, 200);

  console.log('[' + APP_VTAG + '] SVG pan (drag + scrollbar + wheel) initialized');
})();
