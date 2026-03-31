'use strict';
// Test: verify S4-ported _hybridFF1D produces correct Airy FWHM
// Compares uniform aperture result against theory: FWHM = 0.886 * lambda / D
// Also tests Gaussian footprint and measures FWHM from CDF-sampled kicks

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

  // S4: n_bins = min(200, round(nAlive/20)), min 10
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

  // FFT size
  var fft_size_raw = Math.round(100 * D * D / (lambda * f_ff * 0.88));
  if (fft_size_raw > 1000000) fft_size_raw = 1000000;
  if (fft_size_raw < nBins * 2) fft_size_raw = nBins * 2;
  var N = _nextPow2(fft_size_raw);
  if (N > 131072) N = 131072;

  var delta = (zMax - zMin) / (N - 1);
  var re = new Float64Array(N);
  var im = new Float64Array(N);

  // Interpolate histogram onto wavefront grid + thin-lens phase
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

  // Fresnel TF propagation
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

  // Extract image
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

function gaussRandom(sigma) {
  var u1 = Math.random(), u2 = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// ========== TEST CASES ==========
console.log('=== S4-ported _hybridFF1D verification ===\n');

var cases = [
  { name: 'KB-V 10keV uniform', E: 10.0, D: 900e-6, sigma: 0, nRays: 50000 },
  { name: 'KB-H 10keV uniform', E: 10.0, D: 300e-6, sigma: 0, nRays: 50000 },
  { name: 'KB-V 10keV Gauss',   E: 10.0, D: 900e-6, sigma: 255e-6, nRays: 50000 },
  { name: 'KB-H 10keV Gauss',   E: 10.0, D: 300e-6, sigma: 86e-6,  nRays: 50000 },
  { name: 'KB-V 5keV uniform',  E: 5.0,  D: 900e-6, sigma: 0, nRays: 50000 },
  { name: 'KB-H 5keV uniform',  E: 5.0,  D: 300e-6, sigma: 0, nRays: 50000 },
  { name: 'KB-V 20keV uniform', E: 20.0, D: 900e-6, sigma: 0, nRays: 50000 },
  { name: 'KB-H 20keV uniform', E: 20.0, D: 300e-6, sigma: 0, nRays: 50000 },
];

var allPass = true;
for (var ci = 0; ci < cases.length; ci++) {
  var c = cases[ci];
  var lam = HC / c.E * 1e-10;
  var airyFwhm = 0.886 * lam / c.D; // theory for uniform aperture

  // Generate footprint
  var foot = new Float64Array(c.nRays);
  if (c.sigma > 0) {
    // Gaussian truncated by aperture
    var cnt = 0;
    while (cnt < c.nRays) {
      var g = gaussRandom(c.sigma);
      if (g > -c.D/2 && g < c.D/2) foot[cnt++] = g;
    }
  } else {
    // Uniform
    for (var i = 0; i < c.nRays; i++) {
      foot[i] = (Math.random() - 0.5) * c.D;
    }
  }

  var kicks = _hybridFF1D(foot, c.nRays, c.D, lam, c.nRays);
  var fwhm = histFWHM(kicks, c.nRays);

  var ratio = fwhm / airyFwhm;
  var status = (c.sigma > 0) ?
    (fwhm > airyFwhm * 0.8 && fwhm < airyFwhm * 2.0 ? 'OK' : 'WARN') :
    (Math.abs(ratio - 1.0) < 0.10 ? 'PASS' : 'FAIL');

  if (status === 'FAIL') allPass = false;

  console.log(c.name + ':');
  console.log('  Theory Airy FWHM = ' + (airyFwhm*1e6).toFixed(4) + ' urad');
  console.log('  Sampled FWHM     = ' + (fwhm*1e6).toFixed(4) + ' urad');
  console.log('  Ratio sampled/Airy = ' + ratio.toFixed(3) + '  [' + status + ']');
  console.log('  N_fft = ' + _nextPow2(Math.round(100*c.D*c.D/(lam*c.D*c.D/(20*2*0.88*lam)*0.88))));
  console.log('  nBins = ' + Math.min(200, Math.round(c.nRays/20)));
  console.log('');
}

console.log(allPass ? 'ALL UNIFORM CASES PASS' : 'SOME CASES FAILED');
