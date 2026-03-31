'use strict';
// ===== shared/02_chart_stub.js -- uPlot-based unified 1D chart engine =====
// @module shared/02_chart_stub
// @exports _drawChart1D, _drawHeatmap2D, _drawSpecChart
// All 1D charts (scans, profiles, trends) use _drawChart1D via uPlot.
// Theme-aware: Light (default), Dark, Dark 2.
// Also provides _drawHeatmap2D for 2D heatmaps (canvas-based).

// Chart.js stub -- prevents ReferenceError when CDN unavailable
if (typeof Chart === 'undefined') {
  var Chart = function(cv, cfg) {
    this.config = cfg; this.canvas = cv; this.destroy = function() {};
    var ctx = cv.getContext('2d');
    if (!ctx || !cfg || !cfg.data) return;
    var ds = cfg.data.datasets;
    if (!ds || !ds[0] || !ds[0].data) return;
    var data = ds[0].data;
    if (typeof _drawChart1D === 'function') {
      var arr = [];
      var labels = cfg.data.labels || [];
      for (var i = 0; i < data.length; i++) {
        arr.push({ x: labels[i] != null ? parseFloat(labels[i]) : i, y: typeof data[i] === 'number' ? data[i] : 0 });
      }
      _drawChart1D(cv, arr, { color: ds[0].borderColor || '#4db8ff' });
    }
  };
}

// ============================================================
//  _getCanvasZoom -- detect CSS zoom on ancestor elements
// ============================================================
function _getCanvasZoom(el) {
  var z = 1;
  var node = el;
  while (node && node !== document.body) {
    var s = window.getComputedStyle(node);
    var zv = parseFloat(s.zoom);
    if (zv && zv !== 1 && !isNaN(zv)) z *= zv;
    node = node.parentElement;
  }
  return z;
}

function _chartFmt(v) {
  var a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1e5 || (a < 0.01 && a > 0)) return v.toExponential(1);
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

// ============================================================
//  Theme system
// ============================================================
function _getChartTheme() {
  if (document.body.classList.contains('theme-dark')) return 'dark';
  if (document.body.classList.contains('theme-dark2')) return 'dark2';
  return 'light';
}

var _CHART_THEMES = {
  light: {
    bg: '#ffffff',
    grid: 'rgba(0,0,0,0.08)',
    border: 'rgba(0,0,0,0.15)',
    tick: '#404040',
    label: '#505050',
    cursor: '#333333',
    select: 'rgba(0,100,200,0.1)'
  },
  dark: {
    bg: '#000000',
    grid: 'rgba(255,255,255,0.1)',
    border: 'rgba(255,255,255,0.2)',
    tick: '#888888',
    label: '#a0a0a0',
    cursor: '#cccccc',
    select: 'rgba(0,200,255,0.12)'
  },
  dark2: {
    bg: '#0a0f18',
    grid: 'rgba(80,160,255,0.07)',
    border: 'rgba(80,160,255,0.12)',
    tick: '#3d5068',
    label: '#6b7280',
    cursor: '#4db8ff',
    select: 'rgba(77,184,255,0.08)'
  }
};

// ============================================================
//  _getPlotlyDiv -- kept for backward compat with 2D heatmap
// ============================================================
function _getPlotlyDiv(cv, w, h) {
  var divId = (cv.id || 'cv') + '_plotly';
  var div = document.getElementById(divId);
  if (!div) {
    div = document.createElement('div');
    div.id = divId;
    div.style.cssText = 'border-radius:3px;';
    if (cv.parentElement) {
      cv.parentElement.insertBefore(div, cv);
    }
  }
  div.style.width = w + 'px';
  div.style.height = h + 'px';
  cv.style.display = 'none';
  return div;
}

// Keep old name as alias
function _plotlyDarkLayout(opts) { return _plotlyLayout(opts); }
function _plotlyLayout(opts) {
  var theme = _getChartTheme();
  var C = _CHART_THEMES[theme];
  return {
    paper_bgcolor: C.bg,
    plot_bgcolor: C.bg,
    margin: { t: 16, r: 10, b: 38, l: 52 }
  };
}

// ============================================================
//  _getUplotDiv -- get or create a div container for uPlot
//  Replaces canvas element with a div for uPlot rendering.
// ============================================================
function _getUplotDiv(cv, w, h) {
  var divId = (cv.id || 'cv') + '_uplot';
  var div = document.getElementById(divId);
  if (!div) {
    div = document.createElement('div');
    div.id = divId;
    div.style.cssText = 'border-radius:3px;overflow:hidden;';
    if (cv.parentElement) {
      cv.parentElement.insertBefore(div, cv);
    }
  }
  div.style.width = w + 'px';
  div.style.height = h + 'px';
  cv.style.display = 'none';
  return div;
}

// ============================================================
//  _drawChart1D -- Unified 1D chart via uPlot
//
//  cv:   canvas element (hidden, replaced by uPlot div) or div
//  data: [{x,y}, ...] sorted by x
//  opts: color, xlabel, ylabel, title, showFill, showPoints,
//        barMode, marker, xFmt, yFmt, xRange, yRange,
//        width, height, nTicksX, nTicksY, stabilizeY
// ============================================================
window._drawChart1D = function(cv, data, opts) {
  if (!cv || !data || data.length < 1) return;
  opts = opts || {};

  // If uPlot not available, canvas not in DOM, or useCanvas requested, fall back to canvas renderer
  if (opts.useCanvas || typeof uPlot === 'undefined' || !cv.parentElement) {
    _drawChart1D_canvas(cv, data, opts);
    return;
  }

  var color      = opts.color      || '#4db8ff';
  var showFill   = opts.showFill   !== false;
  var barMode    = opts.barMode    || false;
  var marker     = opts.marker     || null;
  var xFmtFn     = opts.xFmt      || null;
  var yFmtFn     = opts.yFmt      || null;
  var compact    = opts.compact    || false;

  var theme = _getChartTheme();
  var C = _CHART_THEMES[theme];

  // Determine size: getBoundingClientRect divided by CSS zoom to get CSS-pixel size.
  // clientWidth alone can differ from rect in some flex/border/scroll scenarios.
  var cw, ch;
  if (opts.width && opts.height) {
    cw = opts.width; ch = opts.height;
  } else if (cv.parentElement) {
    var _prect = cv.parentElement.getBoundingClientRect();
    var _pzoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv.parentElement) : 1;
    cw = Math.floor(_prect.width / _pzoom) || cv.parentElement.clientWidth || cv.width || 400;
    ch = Math.floor(_prect.height / _pzoom) || cv.parentElement.clientHeight || cv.height || 200;
  } else {
    cw = cv.width || 400;
    ch = cv.height || 200;
  }

  // Get or create uPlot container
  var div;
  if (cv.tagName === 'DIV') {
    div = cv;
    div.style.width = cw + 'px';
    div.style.height = ch + 'px';
  } else {
    div = _getUplotDiv(cv, cw, ch);
  }

  // Extract x,y arrays (uPlot wants separate arrays)
  var xs = new Array(data.length);
  var ys = new Array(data.length);
  for (var i = 0; i < data.length; i++) {
    xs[i] = data[i].x;
    ys[i] = data[i].y;
  }

  // Fill color with alpha
  var fillAlpha = showFill ? 0.08 : 0;

  // Parse hex color to rgba for fill
  function hexToFill(hex, alpha) {
    if (alpha <= 0) return 'transparent';
    var r = parseInt(hex.slice(1,3), 16);
    var g = parseInt(hex.slice(3,5), 16);
    var b = parseInt(hex.slice(5,7), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  var fillColor = hexToFill(color.slice(0, 7), fillAlpha);

  // Build uPlot options
  var uOpts = {
    width: cw,
    height: ch,
    cursor: {
      drag: { x: true, y: false },
      points: {
        size: 8,
        width: 2,
        fill: C.bg,
        stroke: color
      }
    },
    select: {
      show: true,
      fill: C.select
    },
    legend: { show: false },
    scales: {
      x: {},
      y: {}
    },
    axes: [
      {
        stroke: C.tick,
        grid: { stroke: C.grid, width: 1 },
        ticks: { stroke: C.border, width: 1 },
        font: '9px monospace',
        labelFont: '9px monospace',
        label: opts.xlabel || '',
        labelGap: 2,
        labelSize: (opts.xlabel) ? 12 : 0,
        gap: 4,
        size: 28
      },
      {
        stroke: C.tick,
        grid: { stroke: C.grid, width: 1 },
        ticks: { stroke: C.border, width: 1 },
        font: '9px monospace',
        labelFont: '9px monospace',
        label: opts.ylabel || '',
        labelGap: 2,
        labelSize: (opts.ylabel) ? 12 : 0,
        gap: 4,
        size: function(self, vals, axisIdx, cycleNum) {
          if (!vals) return 40;
          var maxW = 0;
          for (var vi = 0; vi < vals.length; vi++) {
            var tw = vals[vi].length;
            if (tw > maxW) maxW = tw;
          }
          return Math.max(36, maxW * 6 + 16);
        }
      }
    ],
    series: [
      {},
      {
        stroke: color,
        width: 1.5,
        fill: showFill ? fillColor : undefined,
        points: { show: false }
      }
    ],
    hooks: {}
  };

  // Apply custom tick formatters
  if (xFmtFn) {
    uOpts.axes[0].values = function(u, vals) {
      return vals.map(function(v) { return xFmtFn(v); });
    };
  }
  if (yFmtFn) {
    uOpts.axes[1].values = function(u, vals) {
      return vals.map(function(v) { return yFmtFn(v); });
    };
  }

  // Custom ranges
  if (opts.xRange) {
    uOpts.scales.x.range = function() { return opts.xRange; };
  }
  if (opts.yRange) {
    uOpts.scales.y.range = function() { return opts.yRange; };
  }

  // Title annotation via hook
  if (opts.title) {
    uOpts.hooks.draw = [function(u) {
      var ctx = u.ctx;
      ctx.save();
      ctx.fillStyle = color;
      ctx.font = '10px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(opts.title, u.bbox.left / devicePixelRatio + u.bbox.width / devicePixelRatio - 4, 12);
      ctx.restore();
    }];
  }

  // Marker (vertical line) via hook
  if (marker && marker.x != null) {
    var mColor = marker.color || '#ffb340';
    if (!uOpts.hooks.draw) uOpts.hooks.draw = [];
    uOpts.hooks.draw.push(function(u) {
      var ctx = u.ctx;
      var cx = u.valToPos(marker.x, 'x', true);
      var top = u.bbox.top;
      var bot = top + u.bbox.height;
      ctx.save();
      ctx.strokeStyle = mColor;
      ctx.lineWidth = 1.5 * devicePixelRatio;
      ctx.setLineDash([4 * devicePixelRatio, 3 * devicePixelRatio]);
      ctx.beginPath();
      ctx.moveTo(cx, top);
      ctx.lineTo(cx, bot);
      ctx.stroke();
      ctx.setLineDash([]);
      if (marker.label) {
        ctx.fillStyle = mColor;
        ctx.font = 'bold ' + (9 * devicePixelRatio) + 'px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(marker.label, cx, top - 3 * devicePixelRatio);
      }
      ctx.restore();
    });
  }

  // Bar mode: draw bars via hook instead of line
  if (barMode) {
    uOpts.series[1].stroke = 'transparent';
    uOpts.series[1].fill = undefined;
    uOpts.series[1].paths = function() { return null; };
    if (!uOpts.hooks.draw) uOpts.hooks.draw = [];
    uOpts.hooks.draw.push(function(u) {
      var ctx = u.ctx;
      var dpr = devicePixelRatio;
      var xd = u.data[0];
      var yd = u.data[1];
      ctx.save();
      ctx.fillStyle = color + '90';
      for (var bi = 0; bi < xd.length; bi++) {
        var cx = u.valToPos(xd[bi], 'x', true);
        var cy = u.valToPos(yd[bi], 'y', true);
        var cy0 = u.valToPos(0, 'y', true);
        var bw = Math.max(2 * dpr, (u.bbox.width / xd.length) * 0.7);
        ctx.fillRect(cx - bw / 2, cy, bw, cy0 - cy);
      }
      ctx.restore();
    });
  }

  // Background color via hook
  uOpts.hooks.drawClear = [function(u) {
    var ctx = u.ctx;
    ctx.save();
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, u.width * devicePixelRatio, u.height * devicePixelRatio);
    ctx.restore();
  }];

  // Tooltip via shared fixed element (CSS zoom safe)
  var _tipXFmt = xFmtFn || _chartFmt;
  var _tipYFmt = yFmtFn || _chartFmt;
  var _tipTheme = theme;
  uOpts.hooks.setCursor = [function(u) {
    var idx = u.cursor.idx;
    if (idx == null || idx < 0 || idx >= u.data[0].length) {
      if (typeof _hideProfileTip === 'function') _hideProfileTip();
      return;
    }
    // Text is updated here; position is set by mousemove on div
    div._tipText = _tipXFmt(u.data[0][idx]) + ', ' + _tipYFmt(u.data[1][idx]);
  }];

  // Data format: uPlot wants [xArray, yArray]
  var uData = [xs, ys];

  // Destroy previous instance if exists on this div
  if (div._uplot) {
    div._uplot.destroy();
    div._uplot = null;
  }
  // Clear div
  div.innerHTML = '';

  try {
    var uChart = new uPlot(uOpts, uData, div);
    div._uplot = uChart;

    // Mousemove for tooltip position (uses fixed tooltip, no zoom issues)
    if (!div._tipBound) {
      div._tipBound = true;
      div.addEventListener('mousemove', function(e) {
        if (div._tipText && typeof _showProfileTip === 'function') {
          _showProfileTip(e, div._tipText, _tipTheme);
        }
      });
      div.addEventListener('mouseleave', function() {
        if (typeof _hideProfileTip === 'function') _hideProfileTip();
      });
    }
  } catch(e) {
    // fallback to canvas
    if (cv.tagName === 'CANVAS') {
      cv.style.display = '';
      _drawChart1D_canvas(cv, data, opts);
    }
  }
};

// ============================================================
//  _drawChart1D_canvas -- Canvas fallback (theme-aware)
// ============================================================
window._drawChart1D_canvas = function(cv, data, opts) {
  if (!cv || !data || data.length < 1) return;
  // If a div was passed, create a canvas inside it
  if (cv.tagName === 'DIV') {
    var cvId = (cv.id || 'fb') + '_cv';
    var existCv = document.getElementById(cvId);
    if (!existCv) {
      existCv = document.createElement('canvas');
      existCv.id = cvId;
      cv.innerHTML = '';
      cv.appendChild(existCv);
    }
    cv = existCv;
  }
  opts = opts || {};
  var color  = opts.color   || '#4db8ff';
  var xlabel = opts.xlabel  || '';
  var ylabel = opts.ylabel  || '';
  var title  = opts.title   || '';
  var nTX    = opts.nTicksX || 5;
  var nTY    = opts.nTicksY || 5;
  var showFill   = opts.showFill !== false;
  var showPoints = opts.showPoints || false;
  var barMode    = opts.barMode || false;
  var hover      = opts.hover !== false;
  var marker     = opts.marker || null;
  var xFmt = opts.xFmt || _chartFmt;
  var yFmt = opts.yFmt || _chartFmt;

  var theme = _getChartTheme();
  var C = _CHART_THEMES[theme];

  var cw, ch;
  if (opts.width && opts.height) {
    cw = opts.width; ch = opts.height;
  } else if (cv.parentElement) {
    var _prect2 = cv.parentElement.getBoundingClientRect();
    var _pzoom2 = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv.parentElement) : 1;
    cw = Math.floor(_prect2.width / _pzoom2) || cv.parentElement.clientWidth || cv.width || 400;
    ch = Math.floor(_prect2.height / _pzoom2) || cv.parentElement.clientHeight || cv.height || 200;
  } else {
    cw = cv.width || 400;
    ch = cv.height || 200;
  }

  var zoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv) : 1;
  var dpr = cv.parentElement ? (Math.max(2, window.devicePixelRatio || 1) * zoom) : 1;
  cv.width = cw * dpr; cv.height = ch * dpr;
  if (cv.parentElement) { cv.style.width = cw + 'px'; cv.style.height = ch + 'px'; }
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  var w = cw, h = ch;

  // Scale font/padding with chart size for readability
  var _fs = Math.max(10, Math.min(14, Math.round(Math.min(w, h) / 38)));
  var defPad = { t: _fs * 2 + 4, r: _fs + 4, b: _fs * 3 + 4, l: _fs * 5 + 4 };
  var pad = opts.pad || defPad;
  if (!pad.t && pad.t !== 0) pad = defPad;

  var pw = w - pad.l - pad.r;
  var ph = h - pad.t - pad.b;
  if (pw < 20 || ph < 20) return;

  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, w, h);

  var n = data.length;
  var xs = [], ys = [];
  for (var i = 0; i < n; i++) { xs.push(data[i].x); ys.push(data[i].y); }
  var xMin, xMax, yMin, yMax;
  if (opts.xRange) { xMin = opts.xRange[0]; xMax = opts.xRange[1]; }
  else { xMin = xs[0]; xMax = xs[0]; for (var i = 1; i < n; i++) { if (xs[i] < xMin) xMin = xs[i]; if (xs[i] > xMax) xMax = xs[i]; } }
  if (opts.yRange) { yMin = opts.yRange[0]; yMax = opts.yRange[1]; }
  else { yMin = ys[0]; yMax = ys[0]; for (var i = 1; i < n; i++) { if (ys[i] < yMin) yMin = ys[i]; if (ys[i] > yMax) yMax = ys[i]; }
    var yr = yMax - yMin || 1; yMin -= yr * 0.05; yMax += yr * 0.05; }
  var xRng = xMax - xMin || 1;
  var yRng = yMax - yMin || 1;

  function tx(x) { return pad.l + (x - xMin) / xRng * pw; }
  function ty(y) { return pad.t + (1 - (y - yMin) / yRng) * ph; }

  ctx.strokeStyle = C.grid; ctx.lineWidth = 0.5;
  for (var gi = 0; gi < nTY; gi++) {
    var gy = pad.t + ph * gi / (nTY - 1);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy); ctx.stroke();
  }
  for (var gi = 0; gi < nTX; gi++) {
    var gx = pad.l + pw * gi / (nTX - 1);
    ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, pad.t + ph); ctx.stroke();
  }

  ctx.strokeStyle = C.border; ctx.lineWidth = 1;
  ctx.strokeRect(pad.l, pad.t, pw, ph);

  if (barMode) {
    var barW = Math.max(1, pw / n * 0.8);
    for (var i = 0; i < n; i++) {
      var bx = tx(xs[i]) - barW / 2;
      var bTop = ty(ys[i]);
      var bBot = pad.t + ph;
      ctx.fillStyle = color + '90';
      ctx.fillRect(bx, bTop, barW, bBot - bTop);
    }
  } else {
    if (showFill) {
      ctx.fillStyle = color.slice(0, 7) + '15';
      ctx.beginPath(); ctx.moveTo(tx(xs[0]), pad.t + ph);
      for (var i = 0; i < n; i++) ctx.lineTo(tx(xs[i]), ty(ys[i]));
      ctx.lineTo(tx(xs[n - 1]), pad.t + ph); ctx.closePath(); ctx.fill();
    }
    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      var px = tx(xs[i]), py = ty(ys[i]);
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();

    if (showPoints && n <= 80) {
      ctx.fillStyle = color;
      for (var i = 0; i < n; i++) {
        ctx.beginPath(); ctx.arc(tx(xs[i]), ty(ys[i]), 2, 0, Math.PI * 2); ctx.fill();
      }
    }
  }

  if (marker && marker.x != null) {
    var mColor = marker.color || '#ffb340';
    ctx.strokeStyle = mColor; ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    var mx = tx(marker.x);
    ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, pad.t + ph); ctx.stroke();
    ctx.setLineDash([]);
    if (marker.label) {
      ctx.fillStyle = mColor; ctx.font = 'bold ' + _fs + 'px monospace'; ctx.textAlign = 'center';
      ctx.fillText(marker.label, mx, pad.t - 4);
    }
  }

  ctx.font = _fs + 'px monospace'; ctx.fillStyle = C.tick; ctx.textAlign = 'right';
  for (var gi = 0; gi < nTY; gi++) {
    var yVal = yMax - yRng * gi / (nTY - 1);
    ctx.fillText(yFmt(yVal), pad.l - 4, pad.t + ph * gi / (nTY - 1) + Math.round(_fs * 0.35));
  }

  ctx.textAlign = 'center';
  for (var gi = 0; gi < nTX; gi++) {
    var xVal = xMin + xRng * gi / (nTX - 1);
    var xPos = pad.l + pw * gi / (nTX - 1);
    ctx.fillText(xFmt(xVal), xPos, h - pad.b + _fs + 4);
  }

  if (xlabel) {
    ctx.fillStyle = C.label; ctx.font = (_fs + 1) + 'px monospace'; ctx.textAlign = 'center';
    ctx.fillText(xlabel, pad.l + pw / 2, h - 2);
  }
  if (ylabel) {
    ctx.save();
    ctx.fillStyle = C.label; ctx.font = (_fs + 1) + 'px monospace'; ctx.textAlign = 'center';
    ctx.translate(Math.round(_fs * 0.8), pad.t + ph / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(ylabel, 0, 0);
    ctx.restore();
  }

  if (title) {
    ctx.fillStyle = color; ctx.font = 'bold ' + (_fs + 1) + 'px monospace'; ctx.textAlign = 'right';
    ctx.fillText(title, w - pad.r, pad.t - 4);
  }

  // Store layout info for tooltip alignment (CSS pixel space)
  cv._chartLayout = {
    pad: pad, w: w, h: h, dpr: dpr,
    xMin: xMin, xMax: xMax, yMin: yMin, yMax: yMax,
    xRng: xRng, yRng: yRng, pw: pw, ph: ph
  };
};

// ============================================================
//  _drawHeatmap2D -- Canvas-based 2D heatmap (theme-aware)
//  For Plotly callers, delegates to canvas rendering.
// ============================================================
window._drawHeatmap2D = function(el, z, opts) {
  if (!el || !z || z.length < 1) return;
  opts = opts || {};

  var cw = opts.width || el.clientWidth || 300;
  var ch = opts.height || el.clientHeight || 300;

  var theme = _getChartTheme();
  var C = _CHART_THEMES[theme];

  // Get or create canvas
  var cv;
  if (el.tagName === 'CANVAS') {
    cv = el;
  } else {
    var cvId = (el.id || 'hm') + '_cv';
    cv = document.getElementById(cvId);
    if (!cv) {
      cv = document.createElement('canvas');
      cv.id = cvId;
      el.innerHTML = '';
      el.appendChild(cv);
    }
  }

  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = cw * dpr;
  cv.height = ch * dpr;
  cv.style.width = cw + 'px';
  cv.style.height = ch + 'px';
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);

  // Background
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, cw, ch);

  var rows = z.length, cols = z[0].length;
  var zMin = opts.zmin != null ? opts.zmin : Infinity;
  var zMax = opts.zmax != null ? opts.zmax : -Infinity;
  if (zMin === Infinity || zMax === -Infinity) {
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var v = z[r][c];
        if (v < zMin) zMin = v;
        if (v > zMax) zMax = v;
      }
    }
  }
  var zRng = zMax - zMin || 1;

  // Blue-cyan colormap
  var pad = { t: 4, r: 4, b: 4, l: 4 };
  var pw = cw - pad.l - pad.r;
  var ph = ch - pad.t - pad.b;

  var img = ctx.createImageData(Math.round(pw * dpr), Math.round(ph * dpr));
  var iw = img.width, ih = img.height;
  var _hmLb = (theme === 'light');
  for (var py = 0; py < ih; py++) {
    var gy = Math.floor(py / ih * rows);
    for (var px = 0; px < iw; px++) {
      var gx = Math.floor(px / iw * cols);
      var t = (z[gy][gx] - zMin) / zRng;
      if (t < 0) t = 0; if (t > 1) t = 1;
      var idx = (py * iw + px) * 4;
      // Blue-cyan gradient
      var _r = Math.round(t * t * 80);
      var _g = Math.round(t * 200 + (1 - t) * 8);
      var _b = Math.round(t * 255 + (1 - t) * 20);
      if (_hmLb) {
        var _inv = (1 - t) * (1 - t);
        _r = Math.round(_r + (255 - _r) * _inv);
        _g = Math.round(_g + (255 - _g) * _inv);
        _b = Math.round(_b + (255 - _b) * _inv);
      }
      img.data[idx] = _r; img.data[idx + 1] = _g; img.data[idx + 2] = _b;
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, pad.l * dpr, pad.t * dpr);
};

// ============================================================
//  _drawSpecChart -- SPEC-style scan chart (fixed x-axis, points added sequentially)
// ============================================================
// Like synchrotron SPEC program: full x-range shown from first point,
// data points appear left→right as scan progresses.
//
// cv: canvas element
// data: [{x, y}, ...] collected so far (may be partial)
// opts: {
//   xRange: [min, max],     // fixed x-axis range (REQUIRED for SPEC mode)
//   xlabel: 'pitch (mrad)', // x-axis label
//   ylabel: 'Intensity',    // y-axis label
//   title: 'Scan (5/21)',   // top-right title
//   centerMarker: value,    // vertical dashed line + label
//   showFill: true,         // fill area under curve (default true)
//   showDots: true,         // show data point dots (default true, <=80 pts)
//   color: '#40d89a',       // data line color
//   markerColor: '#ffb340'  // center marker color
// }
window._drawSpecChart = function(cv, data, opts) {
  opts = opts || {};
  var dw = cv.clientWidth || 500, dh = cv.clientHeight || 240;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = dw * dpr; cv.height = dh * dpr;
  var ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  var W = dw, H = dh;
  var pad = {l: 58, r: 12, t: 20, b: 38};
  var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;

  // Theme
  var th = _getChartTheme();
  var ct = _CHART_THEMES[th] || _CHART_THEMES.dark2;
  ctx.fillStyle = ct.bg; ctx.fillRect(0, 0, W, H);

  if (!data || data.length < 1) {
    ctx.fillStyle = ct.tick; ctx.font = '11px monospace'; ctx.textAlign = 'center';
    ctx.fillText('Scan chart -- waiting...', W / 2, H / 2);
    return;
  }

  // X range: fixed from opts.xRange (SPEC mode)
  var xMin, xMax;
  if (opts.xRange && opts.xRange.length === 2) {
    xMin = opts.xRange[0]; xMax = opts.xRange[1];
  } else {
    xMin = data[0].x; xMax = data[data.length - 1].x;
    if (data.length === 1) { xMin -= 1; xMax += 1; }
  }
  var dx = xMax - xMin || 1;

  // Y range: from data (auto-scale with 5% margin)
  var sMin = Infinity, sMax = -Infinity;
  for (var i = 0; i < data.length; i++) {
    if (data[i].y < sMin) sMin = data[i].y;
    if (data[i].y > sMax) sMax = data[i].y;
  }
  if (sMin === sMax) { sMin -= 1; sMax += 1; }
  var sRange = sMax - sMin;
  sMin -= sRange * 0.05; sMax += sRange * 0.05;
  var ds = sMax - sMin;

  function tx(x) { return pad.l + (x - xMin) / dx * pw; }
  function ty(s) { return pad.t + ph - (s - sMin) / ds * ph; }

  // Grid + Y ticks
  var nT = 5;
  ctx.strokeStyle = ct.grid; ctx.lineWidth = 0.5;
  ctx.fillStyle = ct.tick; ctx.font = '9px monospace';
  ctx.textAlign = 'right';
  for (var g = 0; g < nT; g++) {
    var gy = pad.t + ph * g / (nT - 1);
    var yV = sMax - (sMax - sMin) * g / (nT - 1);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy); ctx.stroke();
    ctx.fillText(_chartFmt(yV), pad.l - 4, gy + 3);
  }

  // Grid + X ticks
  ctx.textAlign = 'center';
  for (var g2 = 0; g2 < nT; g2++) {
    var gx = pad.l + pw * g2 / (nT - 1);
    var xV = xMin + dx * g2 / (nT - 1);
    ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, pad.t + ph); ctx.stroke();
    ctx.fillText(_chartFmt(xV), gx, H - 18);
  }

  // Plot area border
  ctx.strokeStyle = ct.border; ctx.lineWidth = 1;
  ctx.strokeRect(pad.l, pad.t, pw, ph);

  // Data color
  var color = opts.color || '#40d89a';

  // Fill area under curve
  if (opts.showFill !== false && data.length > 1) {
    ctx.fillStyle = color + '18'; // 10% opacity
    ctx.beginPath(); ctx.moveTo(tx(data[0].x), pad.t + ph);
    for (var i2 = 0; i2 < data.length; i2++) ctx.lineTo(tx(data[i2].x), ty(data[i2].y));
    ctx.lineTo(tx(data[data.length - 1].x), pad.t + ph);
    ctx.closePath(); ctx.fill();
  }

  // Data line
  if (data.length > 1) {
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
    for (var i3 = 0; i3 < data.length; i3++) {
      i3 === 0 ? ctx.moveTo(tx(data[i3].x), ty(data[i3].y)) : ctx.lineTo(tx(data[i3].x), ty(data[i3].y));
    }
    ctx.stroke();
  }

  // Data points (dots)
  if (opts.showDots !== false && data.length <= 80) {
    ctx.fillStyle = color;
    for (var i4 = 0; i4 < data.length; i4++) {
      ctx.beginPath(); ctx.arc(tx(data[i4].x), ty(data[i4].y), 2, 0, Math.PI * 2); ctx.fill();
    }
  }

  // Center marker (vertical dashed line)
  if (opts.centerMarker != null) {
    var mColor = opts.markerColor || '#ffb340';
    ctx.strokeStyle = mColor; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(tx(opts.centerMarker), pad.t); ctx.lineTo(tx(opts.centerMarker), pad.t + ph); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = mColor; ctx.font = 'bold 9px monospace'; ctx.textAlign = 'center';
    ctx.fillText('C=' + _chartFmt(opts.centerMarker), tx(opts.centerMarker), pad.t - 3);
  }

  // Title (top-right)
  if (opts.title) {
    ctx.fillStyle = '#4db8ff'; ctx.font = '10px monospace'; ctx.textAlign = 'right';
    ctx.fillText(opts.title, W - pad.r, pad.t - 3);
  }

  // Axis labels
  var lbc = ct.label || '#9ca3af';
  if (opts.xlabel) { ctx.fillStyle = lbc; ctx.font = '9px monospace'; ctx.textAlign = 'center'; ctx.fillText(opts.xlabel, pad.l + pw / 2, H - 3); }
  if (opts.ylabel) { ctx.save(); ctx.fillStyle = lbc; ctx.font = '9px monospace'; ctx.textAlign = 'center'; ctx.translate(9, pad.t + ph / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(opts.ylabel, 0, 0); ctx.restore(); }
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _CHART_THEMES!=="undefined")globalThis._CHART_THEMES=_CHART_THEMES;
if(typeof _chartFmt!=="undefined")globalThis._chartFmt=_chartFmt;
if(typeof _drawChart1D!=="undefined")globalThis._drawChart1D=_drawChart1D;
if(typeof _drawChart1D_canvas!=="undefined")globalThis._drawChart1D_canvas=_drawChart1D_canvas;
if(typeof _drawHeatmap2D!=="undefined")globalThis._drawHeatmap2D=_drawHeatmap2D;
if(typeof _drawSpecChart!=="undefined")globalThis._drawSpecChart=_drawSpecChart;
if(typeof _getCanvasZoom!=="undefined")globalThis._getCanvasZoom=_getCanvasZoom;
if(typeof _getChartTheme!=="undefined")globalThis._getChartTheme=_getChartTheme;
if(typeof _getPlotlyDiv!=="undefined")globalThis._getPlotlyDiv=_getPlotlyDiv;
if(typeof _getUplotDiv!=="undefined")globalThis._getUplotDiv=_getUplotDiv;
if(typeof _plotlyDarkLayout!=="undefined")globalThis._plotlyDarkLayout=_plotlyDarkLayout;
if(typeof _plotlyLayout!=="undefined")globalThis._plotlyLayout=_plotlyLayout;
