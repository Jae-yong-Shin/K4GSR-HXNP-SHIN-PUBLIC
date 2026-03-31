/**
 * colormaps.js - Client-side colormap rendering for viewer panels
 *
 * Server sends raw complex float32 data; client applies colormap + scale locally.
 * This enables instant colormap/scale changes without server round-trip.
 */

// ── Colormap LUT cache ──────────────────────────────────────────

var COLORMAP_LIST = ['viridis','inferno','plasma','hot','gray','jet','hsv','turbo','cool'];
var _cmapCache = {};

function getCmapLUT(name) {
    if (!_cmapCache[name]) _cmapCache[name] = _buildLUT(name);
    return _cmapCache[name];
}

function _clamp01(x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }

// 6th-order Horner polynomial (used for viridis, inferno, plasma)
function _poly6(c0, c1, c2, c3, c4, c5, c6, t) {
    return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}

function _hsvToRgb255(h, s, v) {
    h = ((h % 360) + 360) % 360;
    var c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c;
    var r, g, b;
    if      (h < 60)  { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else              { r = c; g = 0; b = x; }
    return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

function _buildLUT(name) {
    var lut = new Uint8Array(768); // 256 entries * 3 channels
    for (var i = 0; i < 256; i++) {
        var t = i / 255;
        var r, g, b;
        switch (name) {
            case 'viridis':
                r = _clamp01(_poly6(0.2777, 0.1050, -0.3309, -4.6342, 6.2283, 4.7764, -5.4355, t));
                g = _clamp01(_poly6(0.0054, 1.4046, 0.2148, -5.7991, 14.1799, -13.7451, 4.6459, t));
                b = _clamp01(_poly6(0.3341, 1.7495, 0.0951, -19.3324, 56.6903, -65.3530, 26.3124, t));
                break;
            case 'inferno':
                r = _clamp01(_poly6(0.0002, 0.1065, 11.6025, -41.7040, 77.1629, -73.9611, 27.1104, t));
                g = _clamp01(_poly6(0.0017, 0.5640, -3.9729, 17.4364, -33.4024, 32.6261, -12.2433, t));
                b = _clamp01(_poly6(-0.0195, 3.9327, -15.9424, 44.3541, -81.8073, 73.2095, -23.0703, t));
                break;
            case 'plasma':
                r = _clamp01(_poly6(0.0587, 2.1765, -2.6895, 6.1303, -11.1074, 10.0231, -3.6587, t));
                g = _clamp01(_poly6(0.0233, 0.2384, -7.4559, 42.3462, -82.6663, 71.4136, -22.9315, t));
                b = _clamp01(_poly6(0.5433, 0.7540, 3.1108, -28.5189, 60.1398, -54.0722, 18.1919, t));
                break;
            case 'hot':
                r = _clamp01(t * 3);
                g = _clamp01((t - 0.333) * 3);
                b = _clamp01((t - 0.667) * 3);
                break;
            case 'gray':
                r = g = b = t;
                break;
            case 'jet':
                r = _clamp01(Math.min(4 * t - 1.5, -4 * t + 4.5));
                g = _clamp01(Math.min(4 * t - 0.5, -4 * t + 3.5));
                b = _clamp01(Math.min(4 * t + 0.5, -4 * t + 2.5));
                break;
            case 'hsv':
                var rgb = _hsvToRgb255(t * 360, 1.0, 0.9);
                lut[i * 3]     = Math.round(rgb[0]);
                lut[i * 3 + 1] = Math.round(rgb[1]);
                lut[i * 3 + 2] = Math.round(rgb[2]);
                continue; // skip default assignment
            case 'turbo':
                r = _clamp01(0.1357 + t * (4.5974 + t * (-42.3277 + t * (130.5407 + t * (-150.3616 + t * 56.7093)))));
                g = _clamp01(0.0914 + t * (2.1856 + t * (-14.7150 + t * (29.2833 + t * (-18.6861 + t * 1.8413)))));
                b = _clamp01(0.1067 + t * (12.2848 + t * (-60.5820 + t * (109.5975 + t * (-77.0397 + t * 14.6329)))));
                break;
            case 'cool':
                r = t; g = 1 - t; b = 1;
                break;
            default:
                r = g = b = t;
        }
        lut[i * 3]     = Math.round(r * 255);
        lut[i * 3 + 1] = Math.round(g * 255);
        lut[i * 3 + 2] = Math.round(b * 255);
    }
    return lut;
}


// ── Raw data decoding ───────────────────────────────────────────

function decodeRawComplex(b64) {
    // Use native binary decode (much faster than atob + byte-by-byte loop)
    var raw = Uint8Array.from(atob(b64), function(c) { return c.charCodeAt(0); });
    return new Float32Array(raw.buffer);
}


// ── Panel rendering ─────────────────────────────────────────────

// Shared offscreen canvas for building ImageData at native resolution
var _offCanvas = null;
var _offCtx = null;
function _getOffscreenCtx(w, h) {
    if (!_offCanvas) {
        _offCanvas = document.createElement('canvas');
        _offCtx = _offCanvas.getContext('2d');
    }
    if (_offCanvas.width !== w || _offCanvas.height !== h) {
        _offCanvas.width = w;
        _offCanvas.height = h;
    }
    return _offCtx;
}

var _PANEL_CANVAS_MAP = {
    objAmp:  'viewObjAmp',
    objPhase:'viewObjPhase',
    prAmp:   'viewPrAmp',
    prPhase: 'viewPrPhase'
};

function renderPanel(key) {
    var settings = STATE.viewSettings[key];
    if (!settings) return;

    var isPhase = (key === 'objPhase' || key === 'prPhase');
    var rawKey  = (key === 'objAmp' || key === 'objPhase') ? 'object' : 'probe';
    var complex = STATE.rawData[rawKey];
    var shape   = STATE.rawData[rawKey + 'Shape'];
    if (!complex || !shape) return;

    var h = shape[0], w = shape[1], n = h * w;

    // Extract amplitude or phase from interleaved complex [re, im, re, im, ...]
    var data = new Float32Array(n);
    if (isPhase) {
        for (var i = 0; i < n; i++) {
            data[i] = Math.atan2(complex[2 * i + 1], complex[2 * i]);
        }
    } else {
        for (var i = 0; i < n; i++) {
            var re = complex[2 * i], im = complex[2 * i + 1];
            data[i] = Math.sqrt(re * re + im * im);
        }
    }

    // Compute scale range
    var vmin, vmax;
    if (settings.scale === 'auto') {
        vmin = Infinity; vmax = -Infinity;
        for (var i = 0; i < n; i++) {
            var v = data[i];
            if (v < vmin) vmin = v;
            if (v > vmax) vmax = v;
        }
    } else if (settings.scale === 'robust') {
        // Percentile P0.5 - P99.5 (sort-based)
        var sorted = Float32Array.from(data);
        sorted.sort();
        vmin = sorted[Math.floor(0.005 * (n - 1))];
        vmax = sorted[Math.floor(0.995 * (n - 1))];
    } else {
        // fixed
        vmin = settings.min;
        vmax = settings.max;
    }

    if (vmax - vmin < 1e-12) vmax = vmin + 1;

    // Store current computed range (for "Fixed" initialization and display)
    settings.currentMin = vmin;
    settings.currentMax = vmax;
    updateRangeUI(key);

    // Build colormapped pixels at native data resolution
    var lut = getCmapLUT(settings.colormap);
    var inv = 255 / (vmax - vmin);
    var imgData = _getOffscreenCtx(w, h).createImageData(w, h);
    var px = imgData.data;

    for (var i = 0; i < n; i++) {
        var idx = (data[i] - vmin) * inv;
        idx = idx < 0 ? 0 : (idx > 255 ? 255 : (idx + 0.5) | 0);
        px[i * 4]     = lut[idx * 3];
        px[i * 4 + 1] = lut[idx * 3 + 1];
        px[i * 4 + 2] = lut[idx * 3 + 2];
        px[i * 4 + 3] = 255;
    }

    // Put colormapped data on offscreen canvas, then drawImage to visible canvas
    // This does nearest-neighbor upscale in the 2D context (not GPU compositor)
    var off = _getOffscreenCtx(w, h);
    off.putImageData(imgData, 0, 0);

    var canvas = document.getElementById(_PANEL_CANVAS_MAP[key]);
    if (!canvas) return;
    var dw = canvas.clientWidth || 256;
    var dh = canvas.clientHeight || 256;
    if (canvas.width !== dw || canvas.height !== dh) {
        canvas.width = dw;
        canvas.height = dh;
    }
    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, dw, dh);
    ctx.drawImage(off.canvas, 0, 0, dw, dh);
}

var _renderScheduled = false;
var _PANEL_KEYS = ['objAmp', 'objPhase', 'prAmp', 'prPhase'];

function renderAllPanels() {
    for (var i = 0; i < _PANEL_KEYS.length; i++) renderPanel(_PANEL_KEYS[i]);
}

/**
 * Schedule staggered panel rendering.
 * Renders one panel per frame to avoid overwhelming the GPU compositor.
 * Multiple calls are collapsed into a single render sequence.
 */
function scheduleRender() {
    if (_renderScheduled) return;
    _renderScheduled = true;
    if (typeof _dbg === 'function') _dbg('sched_start');
    _renderStaggered(0);
}

function _renderStaggered(idx) {
    if (idx >= _PANEL_KEYS.length) {
        _renderScheduled = false;
        if (typeof _dbg === 'function') _dbg('sched_done');
        return;
    }
    setTimeout(function() {
        if (typeof _dbg === 'function') _dbg('sched_panel:' + _PANEL_KEYS[idx]);
        renderPanel(_PANEL_KEYS[idx]);
        _renderStaggered(idx + 1);
    }, 30);
}


// ── Range display ───────────────────────────────────────────────

function updateRangeUI(key) {
    var el = document.getElementById('range_' + key);
    if (!el) return;
    var s = STATE.viewSettings[key];
    if (s.scale === 'fixed') {
        el.innerHTML =
            '<input class="vp-range-input" value="' + s.min.toFixed(2) +
            '" onchange="setFixedMin(\'' + key + '\',this.value)" title="Min">' +
            '<input class="vp-range-input" value="' + s.max.toFixed(2) +
            '" onchange="setFixedMax(\'' + key + '\',this.value)" title="Max">';
    } else {
        var mn = (s.currentMin !== undefined) ? s.currentMin.toPrecision(3) : '?';
        var mx = (s.currentMax !== undefined) ? s.currentMax.toPrecision(3) : '?';
        el.textContent = mn + ' ~ ' + mx;
    }
}


// ── View settings handlers ──────────────────────────────────────

function setViewCmap(key, cmap) {
    STATE.viewSettings[key].colormap = cmap;
    renderPanel(key);
}

function setViewScale(key, mode) {
    var s = STATE.viewSettings[key];
    if (mode === 'fixed' && s.currentMin !== undefined) {
        s.min = s.currentMin;
        s.max = s.currentMax;
    }
    s.scale = mode;
    renderPanel(key);
}

function setFixedMin(key, val) {
    var v = parseFloat(val);
    if (!isNaN(v)) { STATE.viewSettings[key].min = v; renderPanel(key); }
}

function setFixedMax(key, val) {
    var v = parseFloat(val);
    if (!isNaN(v)) { STATE.viewSettings[key].max = v; renderPanel(key); }
}


// ── Pixel hover tooltip ─────────────────────────────────────────

var _hoverTooltip = null;

function initPanelHover() {
    _hoverTooltip = document.createElement('div');
    _hoverTooltip.className = 'vp-tooltip';
    _hoverTooltip.style.display = 'none';
    document.body.appendChild(_hoverTooltip);

    ['objAmp', 'objPhase', 'prAmp', 'prPhase'].forEach(function(key) {
        var imgEl = document.getElementById(_PANEL_CANVAS_MAP[key]);
        if (!imgEl) return;
        imgEl.style.cursor = 'crosshair';
        imgEl.addEventListener('mousemove', function(e) { _showPixelInfo(key, imgEl, e); });
        imgEl.addEventListener('mouseleave', function() { _hoverTooltip.style.display = 'none'; });
    });
}

function _showPixelInfo(key, imgEl, e) {
    var isPhase = (key === 'objPhase' || key === 'prPhase');
    var rawKey = (key === 'objAmp' || key === 'objPhase') ? 'object' : 'probe';
    var complex = STATE.rawData[rawKey];
    var shape = STATE.rawData[rawKey + 'Shape'];
    if (!complex || !shape) { _hoverTooltip.style.display = 'none'; return; }

    var h = shape[0], w = shape[1];
    var rect = imgEl.getBoundingClientRect();
    // Canvas is at display resolution; map mouse to data coordinates
    var fx = (e.clientX - rect.left) / rect.width;
    var fy = (e.clientY - rect.top) / rect.height;
    var ix = Math.floor(fx * w);
    var iy = Math.floor(fy * h);
    if (ix < 0 || ix >= w || iy < 0 || iy >= h) { _hoverTooltip.style.display = 'none'; return; }

    var idx = iy * w + ix;
    var re = complex[2 * idx];
    var im = complex[2 * idx + 1];
    var amp = Math.sqrt(re * re + im * im);
    var phase = Math.atan2(im, re);

    var val = isPhase ? phase.toFixed(3) + ' rad' : amp.toFixed(4);
    var sign = im >= 0 ? '+' : '';
    _hoverTooltip.innerHTML =
        '<b>[' + ix + ', ' + iy + ']</b>&ensp;' + val +
        '<br><span style="opacity:.6">' + re.toFixed(4) + sign + im.toFixed(4) + 'j</span>';

    _hoverTooltip.style.display = 'block';
    // Keep tooltip inside viewport
    var tx = e.clientX + 14;
    var ty = e.clientY + 14;
    var tw = _hoverTooltip.offsetWidth;
    var th = _hoverTooltip.offsetHeight;
    if (tx + tw > window.innerWidth - 4) tx = e.clientX - tw - 8;
    if (ty + th > window.innerHeight - 4) ty = e.clientY - th - 8;
    _hoverTooltip.style.left = tx + 'px';
    _hoverTooltip.style.top = ty + 'px';
}
