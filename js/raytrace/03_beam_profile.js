'use strict';
// ===== raytrace/03_beam_profile.js — MC+SRW Dual 2D Beam Profiles =====
// @module raytrace/03_beam_profile
// @exports KB_H_LEN, KB_V_LEN, MC_GRID, _getProfileTip, _hideProfileTip, _mcMarginalToData, _niceTicks, _setup2DTooltip, _setupHiDPI, _showProfileTip, _tickFmt, abcdTransform, applyColormap, beamAt, beamSizeFromQ, ...
// Extracted from 11_v433_fixes.js + 12_v435_physics.js + 13_alignment.js (DDD Phase 4/6/8)
// beamAt, focalSpot, hybridConvolve, ABCD matrix Gaussian beam propagation,
// MC histogram rendering, SRW 2D profiles, dual line profile overlay

// === KB mirror lengths for diffraction convolution ===
var KB_V_LEN = 0.300;   // KB-V mirror length [m]
var KB_H_LEN = 0.100;   // KB-H mirror length [m]

// === hybridConvolve: KB diffraction (sinc^2) convolution of MC result ===
// From 13_alignment.js — convolves MC histogram with KB aperture diffraction
function hybridConvolve(mc, E) {
  if (!mc || !mc.hist2d || mc.nSurvived < 10) return mc;
  var lam = 12.3984 / E * 1e-10;
  var qV = pos('sample') - pos('kbv');
  var qH = pos('sample') - pos('kbh');
  var aV = KB_V_LEN * Math.sin(0.003);
  var aH = KB_H_LEN * Math.sin(0.003);
  var G = mc.grid, pixH = 2 * mc.fovH / G, pixV = 2 * mc.fovV / G;
  function sincSq(x) {
    if (Math.abs(x) < 1e-12) return 1;
    var px = Math.PI * x;
    return Math.pow(Math.sin(px) / px, 2);
  }
  function buildK(a, q, pix) {
    var sc = a * pix / (lam * q);
    var h = Math.floor(G / 2);
    while (h > 1 && sincSq(sc * h) < 0.001) h--;
    var k = new Float64Array(2 * h + 1), s = 0;
    for (var i = -h; i <= h; i++) { k[i + h] = sincSq(sc * i); s += k[i + h]; }
    for (var i = 0; i < k.length; i++) k[i] /= s;
    return { d: k, h: h };
  }
  var kH = buildK(aH, qH, pixH), kV = buildK(aV, qV, pixV);
  var tmp = new Float64Array(G * G), out = new Float64Array(G * G);
  for (var y = 0; y < G; y++) for (var x = 0; x < G; x++) {
    var v = 0;
    for (var k = -kH.h; k <= kH.h; k++) { var sx = x + k; if (sx >= 0 && sx < G) v += mc.hist2d[y * G + sx] * kH.d[k + kH.h]; }
    tmp[y * G + x] = v;
  }
  for (var x = 0; x < G; x++) for (var y = 0; y < G; y++) {
    var v = 0;
    for (var k = -kV.h; k <= kV.h; k++) { var sy = y + k; if (sy >= 0 && sy < G) v += tmp[sy * G + x] * kV.d[k + kV.h]; }
    out[y * G + x] = v;
  }
  var mH = new Float64Array(G), mV = new Float64Array(G);
  for (var y = 0; y < G; y++) for (var x = 0; x < G; x++) { mH[x] += out[y * G + x]; mV[y] += out[y * G + x]; }
  function fw(m, fov) {
    var mx = 0; for (var i = 0; i < G; i++) if (m[i] > mx) mx = m[i];
    var hm = mx * 0.5;
    // Sub-pixel interpolation at half-max crossings
    var x0 = -1, x1 = -1;
    for (var i = 1; i < G; i++) {
      if (m[i - 1] < hm && m[i] >= hm && x0 < 0) {
        x0 = (i - 1) + (hm - m[i - 1]) / (m[i] - m[i - 1] + 1e-30);
      }
      if (m[i - 1] >= hm && m[i] < hm) {
        x1 = (i - 1) + (hm - m[i - 1]) / (m[i] - m[i - 1] - 1e-30);
      }
    }
    if (x0 < 0 || x1 < 0) return mc.fwhmH || (2 * fov * 0.1);
    return (x1 - x0) * (2 * fov / G);
  }
  var fH = fw(mH, mc.fovH), fV = fw(mV, mc.fovV);
  return { hist2d: out, margH: mH, margV: mV, grid: G, nSurvived: mc.nSurvived, nTotal: mc.nTotal,
    sigH: fH / 2.355, sigV: fV / 2.355, fwhmH: fH, fwhmV: fV,
    fovH: mc.fovH, fovV: mc.fovV, meanX: mc.meanX, meanY: mc.meanY, hybrid: true };
}

// === beamAt(d): analytical beam FWHM [um] at distance d ===
window.beamAt = function(d) {
  var ps = photonSrc(state.energy), m1d = pos('m1'), ssaD = pos('ssa');
  var wbD = pos('wbslit');
  if (d <= m1d) {
    var xpH = ps.Sxp, xpV = ps.Syp;
    if (d > wbD) {
      xpH = Math.min(xpH, (state.wbH * 0.5e-3) / wbD);
      xpV = Math.min(xpV, (state.wbV * 0.5e-3) / wbD);
    }
    return {
      h: Math.sqrt(ps.Sx * ps.Sx + Math.pow(xpH * d, 2)) * 2.355e6,
      v: Math.sqrt(ps.Sy * ps.Sy + Math.pow(xpV * d, 2)) * 2.355e6
    };
  }
  var sigH_ssa = ps.Sx * M2_DM, sigV_ssa = ps.Sy * M1_DM;
  if (d <= ssaD) {
    var f = (d - m1d) / (ssaD - m1d);
    var sHm = Math.sqrt(ps.Sx * ps.Sx + Math.pow(ps.Sxp * m1d, 2));
    var sVm = Math.sqrt(ps.Sy * ps.Sy + Math.pow(ps.Syp * m1d, 2));
    return {
      h: (sHm * (1 - f) + sigH_ssa * f) * 2.355e6,
      v: (sVm * (1 - f) + sigV_ssa * f) * 2.355e6
    };
  }
  var dd = d - ssaD;
  var eH = Math.min(sigH_ssa, state.ssaH * 0.5e-6);
  var eV = Math.min(sigV_ssa, state.ssaV * 0.5e-6);
  return {
    h: Math.sqrt(eH * eH + Math.pow(ps.Sxp / M2_DM * dd, 2)) * 2.355e6,
    v: Math.sqrt(eV * eV + Math.pow(ps.Syp / M1_DM * dd, 2)) * 2.355e6
  };
};

// === focalSpot: MC-based (uses MC_NRAYS from View tab) ===
// Cache is invalidated ONLY by _invalidateMCCache() (called from updateOptics
// when physics actually changes). Tab switches and UI-only operations do NOT
// invalidate, so the displayed beam size stays stable.
window.focalSpot = function() {
  var pV = pos('kbv') - pos('ssa'), qV = pos('sample') - pos('kbv');
  var pH = pos('kbh') - pos('ssa'), qH = pos('sample') - pos('kbh');
  var MV = qV / pV, MH = qH / pH;
  try {
    if (_mcSampleDirty || !_mcSampleCache) {
      var nRays = (typeof MC_NRAYS !== 'undefined') ? MC_NRAYS : 100000;
      _mcSampleCache = mcRayTrace(pos('sample'), nRays);
      _mcSampleDirty = false;
      // MC completed → live-update experiment panel flux/spot
      try { if (typeof _updateExptBeamlineStatus === 'function') _updateExptBeamlineStatus(); } catch(_e) {}
    }
    var mc = _mcSampleCache;
    if (mc && mc.nSurvived > 10) {
      return {
        h: Math.max(15, mc.fwhmH * 1e9),
        v: Math.max(15, mc.fwhmV * 1e9),
        demagV: 1 / MV,
        demagH: 1 / MH
      };
    }
    // MC failed: too few surviving rays — guide user
    console.warn('[MC] Only ' + (mc ? mc.nSurvived : 0) + ' rays survived. Increase MC rays in View tab.');
    if (typeof log === 'function') {
      log('warn', 'MC: too few surviving rays (' + (mc ? mc.nSurvived : 0) +
        '/' + (mc ? mc.nTotal : 0) + '). Increase ray count in View tab for accurate results.');
    }
  } catch(e) { console.warn('[' + APP_VTAG + '] focalSpot MC err:', e); }
  // Fallback: return large spot to indicate inaccuracy
  return {
    h: 9999, v: 9999,
    demagV: 1 / MV, demagH: 1 / MH
  };
};

// ============================================================
//  1. SRW FIX: Gaussian Beam ABCD Matrix Propagation
// ============================================================
// Real SRW uses wavefront propagation with proper sampling.
// For educational virtual beamline, analytical Gaussian beam
// propagation via ABCD (ray transfer) matrices is exact for
// Gaussian beams and physically correct.
//
// Complex beam parameter: q = z + i*z_R
// After ABCD matrix [A B; C D]: q' = (A*q + B) / (C*q + D)
// Beam size: w(z) = sqrt(lambda * Im(q) / pi) (or from q directly)


// Complex beam parameter ABCD transform
// q_in = [re, im], ABCD = [A B; C D]
// q_out = (A*q + B) / (C*q + D)
function abcdTransform(q, A, B, C, D) {
  // Numerator: A*q + B = (A*re + B) + i*(A*im)
  var numRe = A * q[0] + B;
  var numIm = A * q[1];
  // Denominator: C*q + D = (C*re + D) + i*(C*im)
  var denRe = C * q[0] + D;
  var denIm = C * q[1];
  // Complex division: (a+bi)/(c+di)
  var den2 = denRe * denRe + denIm * denIm + 1e-60;
  return [
    (numRe * denRe + numIm * denIm) / den2,
    (numIm * denRe - numRe * denIm) / den2
  ];
}

// Beam size (RMS sigma) from complex beam parameter q
// w(z) = sqrt(lambda / pi * |Im(1/q)|^-1)... actually:
// The beam radius w relates to q by: 1/q = 1/R - i*lambda/(pi*w^2)
// So: w^2 = lambda * |q|^2 / (pi * Im(q))
function beamSizeFromQ(q, lambda) {
  var qMag2 = q[0] * q[0] + q[1] * q[1];
  var imQ = Math.abs(q[1]);
  if (imQ < 1e-30) return 1e-6; // fallback 1µm
  return Math.sqrt(lambda * qMag2 / (Math.PI * imQ));
}

// fresnelProp1D: canonical definition in raytrace/04_propagation_ui.js
// renderBeamProfileAt: canonical definition in raytrace/04_propagation_ui.js

function drawProfile2DCanvas(canvasId, beam, mode, size, opts) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;
  var w = size || cv.width, h = size || cv.height;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  var zoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv) : 1;
  dpr *= zoom;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + 'px'; cv.style.height = h + 'px';
  var ctx = cv.getContext('2d');
  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var bgCol = theme === 'dark' ? '#000' : theme === 'dark2' ? '#0a0f18' : '#fff';
  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w * dpr, h * dpr);

  var sigH, sigV, cohFH, cohFV, cohLH, cohLV;
  if (mode === 'srw') {
    sigH = beam.extH / 4; sigV = beam.extV / 4; // ext = 4σ
    cohFH = 0; cohFV = 0;
  } else {
    sigH = beam.sigH || beam.fwhmH_um * 1e-6 / 2.355;
    sigV = beam.sigV || beam.fwhmV_um * 1e-6 / 2.355;
    cohFH = beam.cohFracH || 0; cohFV = beam.cohFracV || 0;
    cohLH = beam.cohH || sigH; cohLV = beam.cohV || sigV;
  }
  var fovH = sigH * 8, fovV = sigV * 8;

  // For SRW: use intensity profiles to build 2D (at HiDPI resolution)
  var imgW = Math.round(w * dpr), imgH = Math.round(h * dpr);
  var img = ctx.createImageData(imgW, imgH);
  var _lb = (theme === 'light');
  if (mode === 'srw' && beam.intH && beam.intV) {
    var iH = beam.intH, iV = beam.intV, N = iH.length;
    var mH = 0, mV = 0;
    for (var i = 0; i < N; i++) { if (iH[i] > mH) mH = iH[i]; if (iV[i] > mV) mV = iV[i]; }
    if (mH < 1e-30) mH = 1; if (mV < 1e-30) mV = 1;
    for (var py = 0; py < imgH; py++) {
      var iy = Math.floor(py / imgH * N);
      var valV = iV[iy] / mV;
      for (var px = 0; px < imgW; px++) {
        var ix = Math.floor(px / imgW * N);
        var v = (iH[ix] / mH) * valV;
        applyColormap(img.data, (py * imgW + px) * 4, v, 'green', _lb);
      }
    }
  } else {
    for (var py = 0; py < imgH; py++) {
      for (var px = 0; px < imgW; px++) {
        var x = (px - imgW / 2) / (imgW / 2) * fovH;
        var y = (py - imgH / 2) / (imgH / 2) * fovV;
        var v = Math.exp(-0.5 * (Math.pow(x / sigH, 2) + Math.pow(y / sigV, 2)));
        if (cohFH > 0.2 && cohLH) {
          v += 0.06 * v * cohFH * Math.cos(x / cohLH * 2 * Math.PI);
        }
        if (cohFV > 0.2 && cohLV) {
          v += 0.06 * v * cohFV * Math.cos(y / cohLV * 2 * Math.PI);
        }
        v = Math.max(0, Math.min(1, v));
        applyColormap(img.data, (py * imgW + px) * 4, v, 'blue', _lb);
      }
    }
  }
  ctx.putImageData(img, 0, 0);

  // Scale context for vector overlays
  ctx.save();
  ctx.scale(dpr, dpr);

  // Slit overlay
  if (opts && opts.showSlit) {
    ctx.strokeStyle = 'rgba(240,184,64,0.6)'; ctx.lineWidth = 1; ctx.setLineDash([3, 2]);
    if (opts.slitH && opts.slitH < fovH) {
      var sx = w / 2 - opts.slitH / fovH * (w / 2);
      ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.moveTo(w - sx, 0); ctx.lineTo(w - sx, h); ctx.stroke();
    }
    if (opts.slitV && opts.slitV < fovV) {
      var sy = h / 2 - opts.slitV / fovV * (h / 2);
      ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.moveTo(0, h - sy); ctx.lineTo(w, h - sy); ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  // Crosshair + scale bar
  var crossCol = theme === 'light' ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.12)';
  var scaleCol = theme === 'light' ? '#333' : '#fff';
  ctx.strokeStyle = crossCol; ctx.lineWidth = 0.5; ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
  ctx.setLineDash([]);

  var isNm = sigH * 2.355e6 < 1;
  var totalFov = isNm ? sigH * 8e9 : sigH * 8e6;
  var sc = niceScaleAuto(totalFov, isNm);
  var barPx = sc.v / totalFov * w;
  ctx.fillStyle = scaleCol; ctx.fillRect(6, h - 10, barPx, 1.5);
  ctx.font = '8px monospace'; ctx.fillText(sc.l, 6, h - 13);
  ctx.restore();
}

// lightBg: if true, low values → white; if false, low values → black
function applyColormap(data, idx, v, scheme, lightBg) {
  var r, g, b;
  if (scheme === 'green') {
    // Green-cyan colormap for SRW
    // Peak: bright green (r~60, g=255, b~155) — not white, for light-bg visibility
    if (v < 0.2) {
      r = 0; g = Math.round(v / 0.2 * 100); b = Math.round(v / 0.2 * 80);
    } else if (v < 0.5) {
      var t = (v - 0.2) / 0.3;
      r = 0; g = Math.round(100 + t * 155); b = Math.round(80 + t * 100);
    } else if (v < 0.8) {
      var t = (v - 0.5) / 0.3;
      r = Math.round(t * 60); g = 255; b = Math.round(180 - t * 60);
    } else {
      var t = (v - 0.8) / 0.2;
      r = Math.round(60 + t * 20); g = 255; b = Math.round(120 + t * 40);
    }
  } else {
    // Blue-cyan colormap for MC
    // Peak: bright cyan (r~140, g=255, b=255) — not white, for light-bg visibility
    if (v < 0.15) {
      r = 0; g = Math.round(v / 0.15 * 60); b = Math.round(v / 0.15 * 180);
    } else if (v < 0.45) {
      var t = (v - 0.15) / 0.3;
      r = Math.round(t * 60); g = Math.round(60 + t * 160); b = Math.round(180 + t * 75);
    } else if (v < 0.75) {
      var t = (v - 0.45) / 0.3;
      r = Math.round(60 + t * 40); g = Math.round(220 + t * 35); b = 255;
    } else {
      var t = (v - 0.75) / 0.25;
      r = Math.round(100 + t * 40); g = 255; b = 255;
    }
  }
  // Light background: blend low-value pixels toward white
  if (lightBg) {
    var inv = 1 - v; // how "empty" the pixel is
    var blend = inv * inv; // quadratic: more white at low values
    r = Math.round(r + (255 - r) * blend);
    g = Math.round(g + (255 - g) * blend);
    b = Math.round(b + (255 - b) * blend);
  }
  data[idx] = r; data[idx + 1] = g; data[idx + 2] = b; data[idx + 3] = 255;
}

// MC_NRAYS declared in 01_mc_engine.js (default 100000, user-adjustable via View tab)
var MC_GRID  = 51;    // histogram grid size (compact for low-survival coherence conditions)

function drawMCHist2D(canvasId, mc, size) {
  var cv = document.getElementById(canvasId);
  if (!cv || !mc.hist2d) return;
  var w = size, h = size;

  // HiDPI rendering (minimum 2x for crisp text)
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  var zoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv) : 1;
  dpr *= zoom;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + 'px'; cv.style.height = h + 'px';
  var ctx = cv.getContext('2d');

  // Theme-aware background
  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var bgCol = theme === 'dark' ? '#000' : theme === 'dark2' ? '#0a0f18' : '#fff';
  var crossCol = theme === 'light' ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.12)';
  var textCol = theme === 'light' ? 'rgba(0,102,170,0.7)' : 'rgba(77,184,255,0.7)';
  var scaleCol = theme === 'light' ? '#333' : '#fff';

  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w * dpr, h * dpr);

  var G = mc.grid;
  var hist = mc.hist2d;
  var maxVal = 0;
  for (var i = 0; i < G * G; i++) { if (hist[i] > maxVal) maxVal = hist[i]; }
  if (maxVal <= 0) return;

  // Render heatmap at HiDPI resolution
  var imgW = Math.round(w * dpr), imgH = Math.round(h * dpr);
  var img = ctx.createImageData(imgW, imgH);
  var _lb2 = (theme === 'light');
  for (var py = 0; py < imgH; py++) {
    var gy = Math.floor(py / imgH * G);
    for (var px = 0; px < imgW; px++) {
      var gx = Math.floor(px / imgW * G);
      var v = hist[gy * G + gx] / maxVal;
      applyColormap(img.data, (py * imgW + px) * 4, v, 'blue', _lb2);
    }
  }
  ctx.putImageData(img, 0, 0);

  // Store mc data for tooltip
  cv._mcData = mc;
  cv._mcMaxVal = maxVal;

  // Scale context for overlay drawing
  ctx.save();
  ctx.scale(dpr, dpr);

  // Crosshair
  ctx.strokeStyle = crossCol; ctx.lineWidth = 0.5;
  ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(w/2,0); ctx.lineTo(w/2,h); ctx.moveTo(0,h/2); ctx.lineTo(w,h/2); ctx.stroke();
  ctx.setLineDash([]);

  // Scale bar
  var isNm = mc.fwhmH < 1e-6;
  var totalFov = isNm ? mc.fovH * 2e9 : mc.fovH * 2e6;
  var sc = niceScaleAuto(totalFov, isNm);
  var barPx = sc.v / totalFov * w;
  ctx.fillStyle = scaleCol; ctx.fillRect(6, h-10, barPx, 1.5);
  ctx.font = 'bold 8px monospace'; ctx.fillText(sc.l, 6, h-13);

  // Stats label
  ctx.fillStyle = textCol; ctx.font = 'bold 8px monospace';
  ctx.textAlign = 'right';
  ctx.fillText(mc.nSurvived + ' rays', w-4, 10);
  ctx.restore();

  // Tooltip on hover
  _setup2DTooltip(cv, mc, w, h, theme);
}

// ============================================================
//  2D Profile Tooltip: show position & intensity on mousemove
//  Uses shared fixed tooltip (_getProfileTip) for CSS zoom safety
// ============================================================
function _setup2DTooltip(cv, mc, cw, ch, theme) {
  if (cv._tipBound) return;
  cv._tipBound = true;

  cv.addEventListener('mousemove', function(e) {
    var d = cv._mcData;
    if (!d || !d.hist2d) return;
    var rect = cv.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;
    var G = d.grid;
    var gx = Math.floor(mx / rect.width * G);
    var gy = Math.floor(my / rect.height * G);
    if (gx < 0 || gx >= G || gy < 0 || gy >= G) { _hideProfileTip(); return; }

    var val = d.hist2d[gy * G + gx];
    var maxV = cv._mcMaxVal || 1;
    var norm = (val / maxV).toFixed(3);

    var isNm = d.fwhmH < 1e-6;
    var scale = isNm ? 2e9 : 2e6;
    var posH = ((gx + 0.5) / G - 0.5) * d.fovH * scale;
    var posV = ((gy + 0.5) / G - 0.5) * d.fovV * scale;
    var fmt = isNm ? 0 : 1;
    var th = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
    _showProfileTip(e, 'H:' + posH.toFixed(fmt) + ' V:' + posV.toFixed(fmt) + '  I:' + norm, th);
  });

  cv.addEventListener('mouseleave', _hideProfileTip);
}


// ============================================================
//  HiDPI canvas helper (with CSS zoom compensation)
// ============================================================
function _setupHiDPI(cv, w, h) {
  var zoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv) : 1;
  var dpr = Math.max(2, (window.devicePixelRatio || 1)) * zoom;
  cv.width = w * dpr;
  cv.height = h * dpr;
  cv.style.width = w + 'px';
  cv.style.height = h + 'px';
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  return ctx;
}

// ============================================================
//  _mcMarginalToData -- Convert MC marginal histogram to [{x,y}]
//  Maps grid indices to position coordinates centered at 0.
//  fov: half-FOV in meters, G: grid size
//  Returns array of {x: position_in_display_units, y: normalized_intensity}
// ============================================================
function _mcMarginalToData(marg, fov, G, isNm) {
  var scale = isNm ? 2e9 : 2e6; // convert fov (half, in m) to total display units
  var totalDisp = fov * scale; // total FOV in nm or um
  var maxV = 0;
  for (var i = 0; i < G; i++) { if (marg[i] > maxV) maxV = marg[i]; }
  if (maxV < 1) maxV = 1;
  var data = [];
  for (var i = 0; i < G; i++) {
    var pos = ((i + 0.5) / G - 0.5) * totalDisp; // centered at 0
    data.push({x: pos, y: marg[i] / maxV});
  }
  return data;
}

// ============================================================
//  Shared fixed-position tooltip for 1D/2D profiles
//  Avoids CSS zoom coordinate issues by using position:fixed
// ============================================================
function _getProfileTip() {
  var tip = document.getElementById('_profTip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = '_profTip';
    tip.style.cssText = 'position:fixed;pointer-events:none;z-index:9999;' +
      'padding:4px 10px;border-radius:4px;font:18px monospace;white-space:nowrap;' +
      'box-shadow:0 2px 8px rgba(0,0,0,0.22);opacity:0;transition:opacity 0.1s;';
    document.body.appendChild(tip);
  }
  return tip;
}

function _showProfileTip(e, text, theme) {
  var tip = _getProfileTip();
  var isLight = (theme === 'light');
  tip.style.background = isLight ? '#fff' : '#111';
  tip.style.border = '1px solid ' + (isLight ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.2)');
  tip.style.color = isLight ? '#333' : '#ddd';
  tip.textContent = text;
  var tx = e.clientX + 12;
  var ty = e.clientY - 20;
  var tw = tip.offsetWidth || 80;
  if (tx + tw > window.innerWidth - 4) tx = e.clientX - tw - 8;
  if (ty < 4) ty = e.clientY + 16;
  tip.style.left = tx + 'px';
  tip.style.top = ty + 'px';
  tip.style.opacity = '1';
}

function _hideProfileTip() {
  var tip = document.getElementById('_profTip');
  if (tip) tip.style.opacity = '0';
}

// ============================================================
//  Nice tick generator: returns array of tick values
//  range [lo, hi], target ~nTicks ticks
// ============================================================
function _niceTicks(lo, hi, nTicks) {
  if (hi <= lo) return [lo];
  var range = hi - lo;
  var rough = range / (nTicks || 4);
  var mag = Math.pow(10, Math.floor(Math.log(rough) / Math.LN10));
  var residual = rough / mag;
  var step;
  if (residual <= 1.5) step = 1 * mag;
  else if (residual <= 3) step = 2 * mag;
  else if (residual <= 7) step = 5 * mag;
  else step = 10 * mag;
  var tStart = Math.ceil(lo / step) * step;
  var ticks = [];
  for (var v = tStart; v <= hi + step * 0.001; v += step) {
    ticks.push(Math.round(v / step) * step);
  }
  return ticks;
}

function _tickFmt(v, step) {
  if (step >= 1) return v.toFixed(0);
  var dec = Math.max(0, -Math.floor(Math.log(step) / Math.LN10) + 0);
  return v.toFixed(dec);
}

// ============================================================
//  H DIRECTION LINE PROFILE (canvas, HiDPI, themed)
//  X-axis: position centered at 0, Y-axis: normalized intensity
// ============================================================
function drawLineProfileH(elId, mc, canvasW, canvasH) {
  var el = document.getElementById(elId);
  if (!el || !mc.margH) return;
  var w = canvasW || 200, h = canvasH || 80;

  var cv;
  if (el.tagName === 'CANVAS') {
    cv = el;
  } else {
    var cvId = elId + '_cv';
    cv = document.getElementById(cvId);
    if (!cv) {
      cv = document.createElement('canvas');
      cv.id = cvId;
      cv.style.cssText = 'display:block;border-radius:3px;cursor:crosshair;';
      el.innerHTML = '';
      el.appendChild(cv);
    }
  }
  var ctx = _setupHiDPI(cv, w, h);

  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var C = (typeof _CHART_THEMES !== 'undefined') ? _CHART_THEMES[theme] : {};
  var bgCol = C.bg || '#fff';
  var gridCol = C.grid || 'rgba(0,0,0,0.08)';
  var borderCol = C.border || 'rgba(0,0,0,0.15)';
  var tickCol = C.tick || '#606060';
  var lineCol = theme === 'light' ? '#0066aa' : '#4db8ff';
  var fillCol = theme === 'light' ? 'rgba(0,102,170,0.08)' : 'rgba(77,184,255,0.08)';

  var G = mc.grid || mc.margH.length;
  var isNm = mc.fwhmH < 1e-6;
  var fovDisp = isNm ? mc.fovH * 2e9 : mc.fovH * 2e6;
  var halfFov = fovDisp / 2;

  var marg = mc.margH, maxV = 0;
  for (var i = 0; i < G; i++) { if (marg[i] > maxV) maxV = marg[i]; }
  if (maxV < 1) maxV = 1;

  // Padding: left for Y ticks, bottom for X ticks
  var pad = {t: 4, b: 14, l: 4, r: 4};
  var pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;

  // Background
  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w, h);

  // X-axis ticks
  var xTicks = _niceTicks(-halfFov, halfFov, Math.max(3, Math.floor(pw / 40)));
  var xStep = xTicks.length > 1 ? Math.abs(xTicks[1] - xTicks[0]) : 1;
  ctx.strokeStyle = gridCol; ctx.lineWidth = 0.5;
  ctx.fillStyle = tickCol; ctx.font = 'bold 7px monospace'; ctx.textAlign = 'center';
  for (var ti = 0; ti < xTicks.length; ti++) {
    var xv = xTicks[ti];
    var sx = pad.l + (xv + halfFov) / fovDisp * pw;
    if (sx < pad.l || sx > pad.l + pw) continue;
    ctx.beginPath(); ctx.moveTo(sx, pad.t); ctx.lineTo(sx, pad.t + ph); ctx.stroke();
    ctx.fillText(_tickFmt(xv, xStep), sx, h - 2);
  }

  // Y-axis grid (no labels, just 0/0.5/1 grid lines)
  for (var yi = 0; yi <= 2; yi++) {
    var gy = pad.t + ph * (1 - yi / 2);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy); ctx.stroke();
  }

  // Border
  ctx.strokeStyle = borderCol; ctx.lineWidth = 1;
  ctx.strokeRect(pad.l, pad.t, pw, ph);

  // Fill under curve
  ctx.fillStyle = fillCol;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t + ph);
  for (var i = 0; i < G; i++) {
    var px = pad.l + (i + 0.5) / G * pw;
    var py = pad.t + ph * (1 - marg[i] / maxV);
    ctx.lineTo(px, py);
  }
  ctx.lineTo(pad.l + pw, pad.t + ph); ctx.closePath(); ctx.fill();

  // Line
  ctx.beginPath();
  for (var i = 0; i < G; i++) {
    var px = pad.l + (i + 0.5) / G * pw;
    var py = pad.t + ph * (1 - marg[i] / maxV);
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.strokeStyle = lineCol; ctx.lineWidth = 1.5; ctx.stroke();

  // Store data for tooltip
  cv._profData = {axis:'H', marg:marg, maxV:maxV, G:G, fov:mc.fovH, isNm:isNm,
    pad:pad, pw:pw, ph:ph, w:w, h:h, theme:theme};

  // Tooltip listeners (only once)
  if (!cv._profTipBound) {
    cv._profTipBound = true;
    cv.addEventListener('mousemove', function(e) {
      var d = cv._profData;
      if (!d) return;
      var rect = cv.getBoundingClientRect();
      var mx = (e.clientX - rect.left) / rect.width * d.w;
      var my = (e.clientY - rect.top) / rect.height * d.h;
      var gi = Math.floor((mx - d.pad.l) / d.pw * d.G);
      if (gi < 0 || gi >= d.G) { _hideProfileTip(); return; }
      var pos = ((gi + 0.5) / d.G - 0.5) * d.fov * (d.isNm ? 2e9 : 2e6);
      var val = (d.marg[gi] / d.maxV);
      _showProfileTip(e, (d.isNm ? pos.toFixed(0) : pos.toFixed(1)) + ', ' + val.toFixed(3), d.theme);
    });
    cv.addEventListener('mouseleave', _hideProfileTip);
  }
}

// ============================================================
//  V DIRECTION LINE PROFILE (canvas, HiDPI, rotated orientation)
//  Y-axis: spatial position (top=negative, bottom=positive)
//  X-axis: intensity (0 at left, 1 at right)
// ============================================================
function drawLineProfileV(elId, mc, canvasW, canvasH) {
  var el = document.getElementById(elId);
  if (!el || !mc.margV) return;
  var w = canvasW || 80, h = canvasH || 200;

  var cv;
  if (el.tagName === 'CANVAS') {
    cv = el;
  } else {
    var cvId = elId + '_cv';
    cv = document.getElementById(cvId);
    if (!cv) {
      cv = document.createElement('canvas');
      cv.id = cvId;
      cv.style.cssText = 'display:block;border-radius:3px;cursor:crosshair;';
      el.innerHTML = '';
      el.appendChild(cv);
    }
  }
  var ctx = _setupHiDPI(cv, w, h);

  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var C = (typeof _CHART_THEMES !== 'undefined') ? _CHART_THEMES[theme] : {};
  var bgCol = C.bg || '#fff';
  var gridCol = C.grid || 'rgba(0,0,0,0.08)';
  var borderCol = C.border || 'rgba(0,0,0,0.15)';
  var tickCol = C.tick || '#606060';
  var lineCol = theme === 'light' ? '#b07800' : '#ffa040';
  var fillCol = theme === 'light' ? 'rgba(176,120,0,0.08)' : 'rgba(255,160,64,0.08)';

  var G = mc.grid || mc.margV.length;
  var isNm = mc.fwhmV < 1e-6;
  var fovDisp = isNm ? mc.fovV * 2e9 : mc.fovV * 2e6;
  var halfFov = fovDisp / 2;

  var marg = mc.margV, maxV = 0;
  for (var i = 0; i < G; i++) { if (marg[i] > maxV) maxV = marg[i]; }
  if (maxV < 1) maxV = 1;

  // Padding: left for Y ticks, bottom minimal
  var pad = {t: 4, b: 4, l: 20, r: 4};
  var pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;

  // Background
  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w, h);

  // Y-axis ticks (position labels, centered at 0)
  var yTicks = _niceTicks(-halfFov, halfFov, Math.max(3, Math.floor(ph / 30)));
  var yStep = yTicks.length > 1 ? Math.abs(yTicks[1] - yTicks[0]) : 1;
  ctx.strokeStyle = gridCol; ctx.lineWidth = 0.5;
  ctx.fillStyle = tickCol; ctx.font = 'bold 7px monospace'; ctx.textAlign = 'right';
  for (var ti = 0; ti < yTicks.length; ti++) {
    var yv = yTicks[ti];
    var sy = pad.t + (yv + halfFov) / fovDisp * ph;
    if (sy < pad.t || sy > pad.t + ph) continue;
    ctx.beginPath(); ctx.moveTo(pad.l, sy); ctx.lineTo(pad.l + pw, sy); ctx.stroke();
    ctx.fillText(_tickFmt(yv, yStep), pad.l - 2, sy + 3);
  }

  // X-axis grid (no labels, just 0/0.5/1)
  for (var xi = 0; xi <= 2; xi++) {
    var gx = pad.l + pw * xi / 2;
    ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, pad.t + ph); ctx.stroke();
  }

  // Border
  ctx.strokeStyle = borderCol; ctx.lineWidth = 1;
  ctx.strokeRect(pad.l, pad.t, pw, ph);

  // Fill under curve
  ctx.fillStyle = fillCol;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t);
  for (var i = 0; i < G; i++) {
    var py = pad.t + (i + 0.5) / G * ph;
    var px = pad.l + (marg[i] / maxV) * pw;
    ctx.lineTo(px, py);
  }
  ctx.lineTo(pad.l, pad.t + ph); ctx.closePath(); ctx.fill();

  // Line
  ctx.beginPath();
  for (var i = 0; i < G; i++) {
    var py = pad.t + (i + 0.5) / G * ph;
    var px = pad.l + (marg[i] / maxV) * pw;
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.strokeStyle = lineCol; ctx.lineWidth = 1.5; ctx.stroke();

  // Store data for tooltip
  cv._profData = {axis:'V', marg:marg, maxV:maxV, G:G, fov:mc.fovV, isNm:isNm,
    pad:pad, pw:pw, ph:ph, w:w, h:h, theme:theme};

  // Tooltip listeners (only once)
  if (!cv._profTipBound) {
    cv._profTipBound = true;
    cv.addEventListener('mousemove', function(e) {
      var d = cv._profData;
      if (!d) return;
      var rect = cv.getBoundingClientRect();
      var mx = (e.clientX - rect.left) / rect.width * d.w;
      var my = (e.clientY - rect.top) / rect.height * d.h;
      var gi = Math.floor((my - d.pad.t) / d.ph * d.G);
      if (gi < 0 || gi >= d.G) { _hideProfileTip(); return; }
      var pos = ((gi + 0.5) / d.G - 0.5) * d.fov * (d.isNm ? 2e9 : 2e6);
      var val = (d.marg[gi] / d.maxV);
      _showProfileTip(e, (d.isNm ? pos.toFixed(0) : pos.toFixed(1)) + ', ' + val.toFixed(3), d.theme);
    });
    cv.addEventListener('mouseleave', _hideProfileTip);
  }
}

// ============================================================
//  SRW 2D RENDERER (ABCD-based, separable profiles)
// ============================================================
function drawSRW2D(canvasId, srw, size) {
  var cv = document.getElementById(canvasId);
  if (!cv || !srw.intH || !srw.intV) return;
  var w = size, h = size;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  var zoom = (typeof _getCanvasZoom === 'function') ? _getCanvasZoom(cv) : 1;
  dpr *= zoom;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + 'px'; cv.style.height = h + 'px';
  var ctx = cv.getContext('2d');
  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var bgCol = theme === 'dark' ? '#000' : theme === 'dark2' ? '#0a0f18' : '#fff';
  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w * dpr, h * dpr);

  var iH = srw.intH, iV = srw.intV, N = iH.length;
  var mH = 0, mV = 0;
  for (var i = 0; i < N; i++) { if (iH[i] > mH) mH = iH[i]; if (iV[i] > mV) mV = iV[i]; }
  if (mH < 1e-30) mH = 1; if (mV < 1e-30) mV = 1;

  var imgW = Math.round(w * dpr), imgH = Math.round(h * dpr);
  var img = ctx.createImageData(imgW, imgH);
  var _lb3 = (theme === 'light');
  for (var py = 0; py < imgH; py++) {
    var iy = Math.floor(py / imgH * N);
    var vV = iV[iy] / mV;
    for (var px = 0; px < imgW; px++) {
      var ix = Math.floor(px / imgW * N);
      var v = (iH[ix] / mH) * vV;
      applyColormap(img.data, (py * imgW + px) * 4, v, 'green', _lb3);
    }
  }
  ctx.putImageData(img, 0, 0);

  // Scale context for overlay
  ctx.save();
  ctx.scale(dpr, dpr);
  var crossCol = theme === 'light' ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.12)';
  var scaleCol = theme === 'light' ? '#333' : '#fff';
  ctx.strokeStyle = crossCol; ctx.lineWidth = 0.5;
  ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(w/2,0); ctx.lineTo(w/2,h); ctx.moveTo(0,h/2); ctx.lineTo(w,h/2); ctx.stroke();
  ctx.setLineDash([]);

  var isNm = srw.fwhmH_um < 1;
  var totalFov = isNm ? srw.extH * 2e9 : srw.extH * 2e6;
  var sc = niceScaleAuto(totalFov, isNm);
  var barPx = sc.v / totalFov * w;
  ctx.fillStyle = scaleCol; ctx.fillRect(6, h-10, barPx, 1.5);
  ctx.font = '8px monospace'; ctx.fillText(sc.l, 6, h-13);
  ctx.fillStyle = 'rgba(64,216,154,0.7)'; ctx.textAlign = 'right';
  ctx.fillText('ABCD', w-4, 10);
  ctx.restore();
}


// ============================================================
//  1D DUAL LINE PROFILE (MC histogram + SRW curve)
// ============================================================
function drawDualLineProfile(canvasId, mc, srw, axis, canvasW, canvasH, isNano) {
  var cv = document.getElementById(canvasId);
  if (!cv) return;
  var w = canvasW || cv.width, h = canvasH || cv.height;
  var ctx = _setupHiDPI(cv, w, h);
  var theme = (typeof _getChartTheme === 'function') ? _getChartTheme() : 'light';
  var bgCol = theme === 'dark' ? '#000' : theme === 'dark2' ? '#0a0f18' : '#fff';
  ctx.fillStyle = bgCol; ctx.fillRect(0, 0, w, h);

  var pad = {t:8, b:12, l:4, r:4};
  var pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;

  // MC marginal histogram
  var mcMarg = axis === 'H' ? mc.margH : mc.margV;
  var mcFov = axis === 'H' ? mc.fovH : mc.fovV;
  // SRW profile
  var srwProf = axis === 'H' ? srw.intH : srw.intV;
  var srwExt = axis === 'H' ? srw.extH : srw.extV;

  if (!mcMarg || !srwProf) return;

  // Normalize both
  var mcMax = 0, srwMax = 0;
  var G = mc.grid || mcMarg.length;
  var N = srwProf.length;
  for (var i = 0; i < G; i++) { if (mcMarg[i] > mcMax) mcMax = mcMarg[i]; }
  for (var i = 0; i < N; i++) { if (srwProf[i] > srwMax) srwMax = srwProf[i]; }
  if (mcMax < 1) mcMax = 1; if (srwMax < 1e-30) srwMax = 1;

  // Draw MC as filled histogram bars (blue)
  ctx.fillStyle = 'rgba(77,184,255,0.25)';
  var barW = pw / G;
  for (var i = 0; i < G; i++) {
    var bh = mcMarg[i] / mcMax * ph;
    var bx = pad.l + i * barW;
    var by = pad.t + ph - bh;
    ctx.fillRect(bx, by, barW + 0.5, bh);
  }
  // MC line on top
  ctx.beginPath();
  for (var i = 0; i < G; i++) {
    var px = pad.l + (i + 0.5) * barW;
    var py = pad.t + (1 - mcMarg[i] / mcMax) * ph;
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.strokeStyle = '#4db8ff'; ctx.lineWidth = 1; ctx.stroke();

  // SRW as dashed green curve
  ctx.beginPath();
  for (var i = 0; i < N; i++) {
    var px = pad.l + i / (N - 1) * pw;
    var py = pad.t + (1 - srwProf[i] / srwMax) * ph;
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.strokeStyle = '#40d89a'; ctx.lineWidth = 1.2;
  ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]);

  // FWHM labels
  var unit = isNano ? 'nm' : 'µm';
  var mcFWHM = axis === 'H' ? mc.fwhmH : mc.fwhmV;
  var srwFWHM = axis === 'H' ? srw.fwhmH_nm * 1e-3 : srw.fwhmV_nm * 1e-3; // to µm
  if (isNano) {
    mcFWHM = mcFWHM * 1e9;
    srwFWHM = axis === 'H' ? srw.fwhmH_nm : srw.fwhmV_nm;
  } else {
    mcFWHM = mcFWHM * 1e6;
    srwFWHM = axis === 'H' ? srw.fwhmH_um : srw.fwhmV_um;
  }
  ctx.font = '8px monospace'; ctx.textAlign = 'left';
  ctx.fillStyle = '#4db8ff'; ctx.fillText('MC:' + mcFWHM.toFixed(1) + unit, pad.l + 2, pad.t + 8);
  ctx.fillStyle = '#40d89a'; ctx.fillText('SRW:' + srwFWHM.toFixed(1) + unit, pad.l + 2, pad.t + 16);

  // Axis
  ctx.fillStyle = '#3d5068'; ctx.textAlign = 'center';
  var fovDisp = isNano ? mcFov * 2e9 : mcFov * 2e6;
  ctx.fillText('±' + (fovDisp/2).toFixed(isNano ? 0 : 1) + ' ' + unit, w/2, h - 1);
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof KB_H_LEN!=="undefined")globalThis.KB_H_LEN=KB_H_LEN;
if(typeof KB_V_LEN!=="undefined")globalThis.KB_V_LEN=KB_V_LEN;
if(typeof MC_GRID!=="undefined")globalThis.MC_GRID=MC_GRID;
if(typeof abcdTransform!=="undefined")globalThis.abcdTransform=abcdTransform;
if(typeof applyColormap!=="undefined")globalThis.applyColormap=applyColormap;
if(typeof beamSizeFromQ!=="undefined")globalThis.beamSizeFromQ=beamSizeFromQ;
if(typeof drawDualLineProfile!=="undefined")globalThis.drawDualLineProfile=drawDualLineProfile;
if(typeof drawLineProfileH!=="undefined")globalThis.drawLineProfileH=drawLineProfileH;
if(typeof drawLineProfileV!=="undefined")globalThis.drawLineProfileV=drawLineProfileV;
if(typeof drawMCHist2D!=="undefined")globalThis.drawMCHist2D=drawMCHist2D;
if(typeof drawProfile2DCanvas!=="undefined")globalThis.drawProfile2DCanvas=drawProfile2DCanvas;
if(typeof drawSRW2D!=="undefined")globalThis.drawSRW2D=drawSRW2D;
if(typeof hybridConvolve!=="undefined")globalThis.hybridConvolve=hybridConvolve;
if(typeof _getProfileTip!=="undefined")globalThis._getProfileTip=_getProfileTip;
if(typeof _hideProfileTip!=="undefined")globalThis._hideProfileTip=_hideProfileTip;
if(typeof _mcMarginalToData!=="undefined")globalThis._mcMarginalToData=_mcMarginalToData;
if(typeof _niceTicks!=="undefined")globalThis._niceTicks=_niceTicks;
if(typeof _setup2DTooltip!=="undefined")globalThis._setup2DTooltip=_setup2DTooltip;
if(typeof _setupHiDPI!=="undefined")globalThis._setupHiDPI=_setupHiDPI;
if(typeof _showProfileTip!=="undefined")globalThis._showProfileTip=_showProfileTip;
if(typeof _tickFmt!=="undefined")globalThis._tickFmt=_tickFmt;
if(typeof beamAt!=="undefined")globalThis.beamAt=beamAt;
if(typeof focalSpot!=="undefined")globalThis.focalSpot=focalSpot;
