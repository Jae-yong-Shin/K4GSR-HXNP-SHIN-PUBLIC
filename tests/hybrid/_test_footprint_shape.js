'use strict';
// Test: how different footprint shapes affect diffraction kick FWHM from _hybridFF1D
// Critical question: does a Gaussian footprint produce sub-Airy kicks?

var HC = 12.3984;

// --- FFT (same as production) ---
function _fft(re, im, inv) {
  var N = re.length;
  for (var i = 1, j = 0; i < N; i++) {
    var bit = N >> 1;
    while (j & bit) { j ^= bit; bit >>= 1; }
    j ^= bit;
    if (i < j) {
      var t = re[i]; re[i] = re[j]; re[j] = t;
      t = im[i]; im[i] = im[j]; im[j] = t;
    }
  }
  var sign = inv ? 1 : -1;
  for (var len = 2; len <= N; len <<= 1) {
    var ang = sign * 2 * Math.PI / len;
    var wRe = Math.cos(ang), wIm = Math.sin(ang);
    for (var i = 0; i < N; i += len) {
      var curRe = 1, curIm = 0;
      for (var j = 0; j < (len >> 1); j++) {
        var a = i + j, b = i + j + (len >> 1);
        var tRe = curRe * re[b] - curIm * im[b];
        var tIm = curRe * im[b] + curIm * re[b];
        re[b] = re[a] - tRe; im[b] = im[a] - tIm;
        re[a] += tRe; im[a] += tIm;
        var tmpR = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = tmpR;
      }
    }
  }
  if (inv) { for (var i = 0; i < N; i++) { re[i] /= N; im[i] /= N; } }
}
function _nextPow2(n) { var p = 1; while (p < n) p <<= 1; return p; }

// --- S4-ported _inverseCdfSample ---
function _inverseCdfSample(pdf, n, xMin, xMax, nSamples) {
  var dx = (xMax - xMin) / (n - 1);
  var cdf = new Float64Array(n);
  cdf[0] = pdf[0];
  for (var i = 1; i < n; i++) cdf[i] = cdf[i - 1] + pdf[i];
  var cdf0 = cdf[0];
  for (var i = 0; i < n; i++) cdf[i] -= cdf0;
  var cdfMax = cdf[n - 1];
  if (cdfMax <= 0) {
    var samples = new Float64Array(nSamples);
    for (var i = 0; i < nSamples; i++) samples[i] = xMin + Math.random() * (xMax - xMin);
    return samples;
  }
  for (var i = 0; i < n; i++) cdf[i] /= cdfMax;
  var samples = new Float64Array(nSamples);
  for (var s = 0; s < nSamples; s++) {
    var u = Math.random();
    var lo = 0, hi = n - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (cdf[mid] < u) lo = mid + 1;
      else hi = mid;
    }
    var ix = lo;
    if (ix > 0) ix--;
    var delta_val = 0;
    if (ix < n - 1) {
      var pendent = cdf[ix + 1] - cdf[ix];
      if (pendent > 0) delta_val = (u - cdf[ix]) / pendent;
    }
    samples[s] = xMin + (ix + delta_val) * dx;
  }
  return samples;
}

// --- S4-ported _hybridFF1D ---
function _hybridFF1D(footArr, nAlive, D, lambda, nSamples) {
  if (D < 1e-12 || nAlive < 3) return new Float64Array(nSamples);
  var n_peaks = 20;
  var k = 2 * Math.PI / lambda;
  var f_ff = D * D / (n_peaks * 2 * 0.88 * lambda);

  var nBins = Math.min(200, Math.round(nAlive / 20));
  if (nBins < 10) nBins = 10;

  var zMin = footArr[0], zMax = footArr[0];
  for (var i = 1; i < nAlive; i++) {
    if (footArr[i] < zMin) zMin = footArr[i];
    if (footArr[i] > zMax) zMax = footArr[i];
  }
  if (zMax - zMin < 1e-15) return new Float64Array(nSamples);

  var dz_hist = (zMax - zMin) / nBins;
  var hist = new Float64Array(nBins);
  for (var i = 0; i < nAlive; i++) {
    var bin = Math.floor((footArr[i] - zMin) / dz_hist);
    if (bin >= nBins) bin = nBins - 1;
    if (bin >= 0) hist[bin]++;
  }
  var hist_delta = (nBins > 1) ? (zMax - zMin) / (nBins - 1) : 1e-15;

  var fft_size_raw = Math.round(100 * D * D / (lambda * f_ff * 0.88));
  if (fft_size_raw > 1000000) fft_size_raw = 1000000;
  if (fft_size_raw < nBins * 2) fft_size_raw = nBins * 2;
  var N = _nextPow2(fft_size_raw);
  if (N > 131072) N = 131072;

  var delta = (zMax - zMin) / (N - 1);
  var re = new Float64Array(N);
  var im = new Float64Array(N);

  for (var j = 0; j < N; j++) {
    var z = zMin + j * delta;
    var frac_idx = (z - zMin) / hist_delta;
    var idx0 = Math.floor(frac_idx);
    var idx1 = idx0 + 1;
    if (idx0 < 0) { idx0 = 0; idx1 = 0; }
    if (idx1 >= nBins) { idx1 = nBins - 1; if (idx0 >= nBins) idx0 = nBins - 1; }
    var interp_val;
    if (idx0 === idx1) interp_val = hist[idx0];
    else interp_val = hist[idx0] + (hist[idx1] - hist[idx0]) * (frac_idx - idx0);
    var amp = Math.sqrt(Math.max(0, interp_val));
    var phi = -k * z * z / (2 * f_ff);
    re[j] = amp * Math.cos(phi);
    im[j] = amp * Math.sin(phi);
  }

  _fft(re, im, false);
  var coeff = -Math.PI * lambda * f_ff;
  for (var j = 0; j < N; j++) {
    var freq_idx = (j < N / 2) ? j : (j - N);
    var fj = freq_idx / (N * delta);
    var phase = coeff * fj * fj;
    var cP = Math.cos(phase), sP = Math.sin(phase);
    var tRe = re[j] * cP - im[j] * sP;
    var tIm = re[j] * sP + im[j] * cP;
    re[j] = tRe; im[j] = tIm;
  }
  _fft(re, im, true);

  var image_size = Math.min(Math.abs(zMax), Math.abs(zMin)) * 2;
  image_size = Math.min(image_size,
      n_peaks * 2 * 0.88 * lambda * f_ff / Math.abs(zMax - zMin));
  var image_n_pts = Math.round(image_size / delta / 2) * 2 + 1;
  if (image_n_pts < 3) image_n_pts = 3;
  if (image_n_pts > N) image_n_pts = N;

  var half_pts = (image_n_pts - 1) / 2;
  var intensity = new Float64Array(image_n_pts);
  for (var ip = 0; ip < image_n_pts; ip++) {
    var pos = (ip - half_pts) * delta;
    var wf_frac = (pos - zMin) / delta;
    var i0 = Math.floor(wf_frac);
    var i1 = i0 + 1;
    if (i0 < 0 || i1 >= N) { intensity[ip] = 0; continue; }
    var frac = wf_frac - i0;
    var re_i = re[i0] + (re[i1] - re[i0]) * frac;
    var im_i = im[i0] + (im[i1] - im[i0]) * frac;
    intensity[ip] = re_i * re_i + im_i * im_i;
  }

  var angMin = -half_pts * delta / f_ff;
  var angMax = half_pts * delta / f_ff;
  return _inverseCdfSample(intensity, image_n_pts, angMin, angMax, nSamples);
}

// --- Histogram FWHM measurement ---
function histFWHM(values, n) {
  var vMin = values[0], vMax = values[0];
  for (var i = 1; i < n; i++) {
    if (values[i] < vMin) vMin = values[i];
    if (values[i] > vMax) vMax = values[i];
  }
  var nB = 501, range = vMax - vMin;
  if (range < 1e-20) return 0;
  var dx = range / nB;
  var hist = new Float64Array(nB);
  for (var i = 0; i < n; i++) {
    var bin = Math.floor((values[i] - vMin) / dx);
    if (bin >= 0 && bin < nB) hist[bin]++;
  }
  var mx = 0;
  for (var i = 0; i < nB; i++) if (hist[i] > mx) mx = hist[i];
  if (mx <= 0) return 0;
  var hm = mx * 0.5, x0 = -1, x1 = -1;
  for (var i = 1; i < nB; i++) {
    if (hist[i-1] < hm && hist[i] >= hm && x0 < 0)
      x0 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
    if (hist[i-1] >= hm && hist[i] < hm)
      x1 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
  }
  if (x0 < 0 || x1 < 0) return 0;
  return (x1 - x0) * dx;
}

// --- Gaussian random (Box-Muller) ---
function gaussRandom(sigma) {
  var u1 = Math.random(), u2 = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// --- Generate footprint array ---
function makeFootprint(nRays, D, sigma) {
  var foot = new Float64Array(nRays);
  if (sigma <= 0) {
    // Uniform
    for (var i = 0; i < nRays; i++) {
      foot[i] = (Math.random() - 0.5) * D;
    }
  } else {
    // Gaussian truncated at +/- D/2
    var cnt = 0;
    while (cnt < nRays) {
      var g = gaussRandom(sigma);
      if (g > -D / 2 && g < D / 2) foot[cnt++] = g;
    }
  }
  return foot;
}

// ========== MAIN TEST ==========
console.log('=== Footprint Shape vs Diffraction Kick FWHM ===');
console.log('Question: Does Gaussian footprint in _hybridFF1D produce sub-Airy kicks?\n');

var nRays = 10000;
var nRepeats = 5;

// Define mirror configs
var mirrors = [
  { name: 'KB-V', D: 900e-6 },
  { name: 'KB-H', D: 300e-6 }
];

var E_keV = 10.0;
var lam = HC / E_keV * 1e-10;  // 1.24e-10 m

// Define footprint shapes - sigma values scale proportionally with D
var shapeFactors = [
  { label: 'UNIFORM',                    sigmaFrac: 0 },
  { label: 'Gauss sig=0.283D (FWHM~67%D)', sigmaFrac: 0.2833 },  // 255/900
  { label: 'Gauss sig=0.211D (FWHM~50%D)', sigmaFrac: 0.2111 },  // 190/900
  { label: 'Gauss sig=0.141D (FWHM~33%D)', sigmaFrac: 0.1411 },  // 127/900
  { label: 'Gauss sig=0.422D (FWHM~100%D)', sigmaFrac: 0.4222 }  // 380/900
];

for (var mi = 0; mi < mirrors.length; mi++) {
  var mir = mirrors[mi];
  var D = mir.D;
  var airyFwhm = 0.886 * lam / D;

  console.log('============================================================');
  console.log(mir.name + '  D=' + (D * 1e6).toFixed(0) + 'um  E=10keV  lambda=' + (lam * 1e10).toFixed(4) + 'A');
  console.log('Airy FWHM (0.886*lam/D) = ' + (airyFwhm * 1e6).toFixed(4) + ' urad');
  console.log('------------------------------------------------------------');
  console.log('  Shape                          | sigma(um) | FWHM/D  | kick FWHM(urad) | ratio vs Airy | std(ratio)');
  console.log('  -------------------------------|-----------|---------|-----------------|---------------|----------');

  for (var si = 0; si < shapeFactors.length; si++) {
    var sf = shapeFactors[si];
    var sigma = sf.sigmaFrac * D;
    var fwhmOfGauss = sigma * 2.355;

    var ratios = [];
    var fwhms = [];
    for (var rep = 0; rep < nRepeats; rep++) {
      var foot = makeFootprint(nRays, D, sigma);
      var kicks = _hybridFF1D(foot, nRays, D, lam, nRays);
      var fwhm = histFWHM(kicks, nRays);
      fwhms.push(fwhm);
      ratios.push(fwhm / airyFwhm);
    }

    // Average and std
    var avgRatio = 0, avgFwhm = 0;
    for (var r = 0; r < nRepeats; r++) { avgRatio += ratios[r]; avgFwhm += fwhms[r]; }
    avgRatio /= nRepeats;
    avgFwhm /= nRepeats;
    var stdRatio = 0;
    for (var r = 0; r < nRepeats; r++) stdRatio += (ratios[r] - avgRatio) * (ratios[r] - avgRatio);
    stdRatio = Math.sqrt(stdRatio / nRepeats);

    var sigmaUm = (sigma * 1e6).toFixed(0);
    var fwhmDpct = (sigma > 0) ? (fwhmOfGauss / D * 100).toFixed(0) + '%' : '100%';

    // Pad strings for alignment
    var labelPad = sf.label;
    while (labelPad.length < 33) labelPad += ' ';
    var sigmaPad = sigmaUm;
    while (sigmaPad.length < 9) sigmaPad = ' ' + sigmaPad;
    var fwhmDpad = fwhmDpct;
    while (fwhmDpad.length < 7) fwhmDpad = ' ' + fwhmDpad;

    console.log('  ' + labelPad + '| ' + sigmaPad + ' | ' + fwhmDpad + ' | '
      + (avgFwhm * 1e6).toFixed(4).padStart(15) + ' | '
      + avgRatio.toFixed(4).padStart(13) + ' | '
      + stdRatio.toFixed(4).padStart(8));
  }
  console.log('');
}

// ========== ANALYSIS ==========
console.log('============================================================');
console.log('ANALYSIS');
console.log('============================================================');
console.log('');
console.log('Key question: _hybridFF1D builds a histogram of footprint positions,');
console.log('then does Fresnel propagation of that amplitude profile.');
console.log('');
console.log('For UNIFORM footprint: histogram is flat -> rect aperture -> Airy (sinc^2)');
console.log('For GAUSSIAN footprint: histogram is Gaussian -> Gaussian FT -> Gaussian');
console.log('  The FT of a Gaussian with sigma_x is a Gaussian with sigma_f = 1/(2*pi*sigma_x)');
console.log('  In angular space: sigma_theta = lambda / (2*pi*sigma_x)');
console.log('  FWHM_theta = 2.355 * lambda / (2*pi*sigma_x)');
console.log('');

// Theoretical predictions
console.log('Theoretical predictions for KB-V (D=900um):');
var D_V = 900e-6;
var airyV = 0.886 * lam / D_V;
console.log('  Airy FWHM (uniform):  ' + (airyV * 1e6).toFixed(4) + ' urad');

var sigmas_um = [255, 190, 127, 380];
var labels_gauss = ['67%D', '50%D', '33%D', '~100%D'];
for (var gi = 0; gi < sigmas_um.length; gi++) {
  var sig = sigmas_um[gi] * 1e-6;
  // Gaussian FT FWHM: 2.355 * lambda / (2*pi*sigma)
  var gaussFTfwhm = 2.355 * lam / (2 * Math.PI * sig);
  console.log('  Gauss FT FWHM (sigma=' + sigmas_um[gi] + 'um, ' + labels_gauss[gi] + '): '
    + (gaussFTfwhm * 1e6).toFixed(4) + ' urad  (ratio vs Airy: '
    + (gaussFTfwhm / airyV).toFixed(4) + ')');
}

console.log('');
console.log('Note: Gaussian FT FWHM = 0.886*lam/D * (D / (2*pi*sigma)) * 2.355');
console.log('For sigma=D*0.283 (FWHM=67%D): ratio = 2.355/(2*pi*0.283) = 1.325');
console.log('  -> Gaussian footprint should produce LARGER kicks than Airy, not smaller!');
console.log('');
console.log('But S4 hybrid applies a THIN LENS + Fresnel propagation, not a simple FT.');
console.log('The histogram amplitude goes through a physical Fresnel propagation.');
console.log('Let us see what the numerical results actually show...');
console.log('');
console.log('DONE.');
