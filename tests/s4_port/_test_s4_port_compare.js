'use strict';
// Compare OLD vs NEW _hybridFF1D kick FWHM for Gaussian footprint (realistic KB)
// This tests whether the S4 line-by-line port produces different kicks

var HC = 12.3984;

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

// OLD CDF (before S4 port)
function _inverseCdfSample_OLD(pdf, n, xMin, xMax, nSamples) {
  var dx = (xMax - xMin) / (n - 1);
  var cdf = new Float64Array(n);
  cdf[0] = pdf[0];
  for (var i = 1; i < n; i++) cdf[i] = cdf[i - 1] + pdf[i];
  var total = cdf[n - 1];
  if (total <= 0) {
    var s = new Float64Array(nSamples);
    for (var i = 0; i < nSamples; i++) s[i] = xMin + Math.random() * (xMax - xMin);
    return s;
  }
  for (var i = 0; i < n; i++) cdf[i] /= total;
  var s = new Float64Array(nSamples);
  for (var si = 0; si < nSamples; si++) {
    var u = Math.random();
    var lo = 0, hi = n - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (cdf[mid] < u) lo = mid + 1; else hi = mid; }
    var x0 = xMin + lo * dx;
    if (lo > 0 && cdf[lo] > cdf[lo - 1]) {
      var frac = (u - cdf[lo - 1]) / (cdf[lo] - cdf[lo - 1]);
      x0 = xMin + (lo - 1 + frac) * dx;
    }
    s[si] = x0;
  }
  return s;
}

// NEW CDF (S4 port)
function _inverseCdfSample_NEW(pdf, n, xMin, xMax, nSamples) {
  var dx = (xMax - xMin) / (n - 1);
  var cdf = new Float64Array(n);
  cdf[0] = pdf[0];
  for (var i = 1; i < n; i++) cdf[i] = cdf[i - 1] + pdf[i];
  var cdf0 = cdf[0];
  for (var i = 0; i < n; i++) cdf[i] -= cdf0;
  var cdfMax = cdf[n - 1];
  if (cdfMax <= 0) {
    var s = new Float64Array(nSamples);
    for (var i = 0; i < nSamples; i++) s[i] = xMin + Math.random() * (xMax - xMin);
    return s;
  }
  for (var i = 0; i < n; i++) cdf[i] /= cdfMax;
  var s = new Float64Array(nSamples);
  for (var si = 0; si < nSamples; si++) {
    var u = Math.random();
    var lo = 0, hi = n - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (cdf[mid] < u) lo = mid + 1; else hi = mid; }
    var ix = lo;
    if (ix > 0) ix--;
    var dv = 0;
    if (ix < n - 1) {
      var p = cdf[ix + 1] - cdf[ix];
      if (p > 0) dv = (u - cdf[ix]) / p;
    }
    s[si] = xMin + (ix + dv) * dx;
  }
  return s;
}

// OLD _hybridFF1D (sparse histogram in large FFT array)
function _hybridFF1D_OLD(footArr, nAlive, D, lambda, nSamples) {
  if (D < 1e-12 || nAlive < 3) return new Float64Array(nSamples);
  var n_peaks = 20, k = 2 * Math.PI / lambda;
  var f_ff = D * D / (n_peaks * 2 * 0.88 * lambda);
  var nBins = 256;
  var zMin = footArr[0], zMax = footArr[0];
  for (var i = 1; i < nAlive; i++) {
    if (footArr[i] < zMin) zMin = footArr[i];
    if (footArr[i] > zMax) zMax = footArr[i];
  }
  var hMargin = (zMax - zMin) * 0.02;
  if (hMargin < 1e-12) hMargin = D * 0.01;
  var hMin = zMin - hMargin, hMax = zMax + hMargin;
  var dz = (hMax - hMin) / nBins;
  var hist = new Float64Array(nBins);
  for (var i = 0; i < nAlive; i++) {
    var bin = Math.floor((footArr[i] - hMin) / dz);
    if (bin >= 0 && bin < nBins) hist[bin]++;
  }
  var N_nyquist = Math.ceil(lambda * f_ff / (dz * dz));
  var N = _nextPow2(Math.max(nBins * 2, N_nyquist * 4));
  if (N > 131072) N = 131072;
  var re = new Float64Array(N), im = new Float64Array(N);
  var nHalf = nBins >> 1;
  for (var i = 0; i < nBins; i++) {
    var amp = Math.sqrt(Math.max(0, hist[i]));
    var z = hMin + (i + 0.5) * dz;
    var zc = z - (hMin + hMax) * 0.5;
    var phi = -k * zc * zc / (2 * f_ff);
    var di = i - nHalf; if (di < 0) di += N;
    re[di] = amp * Math.cos(phi); im[di] = amp * Math.sin(phi);
  }
  _fft(re, im, false);
  var coeff = -Math.PI * lambda * f_ff;
  for (var j = 0; j < N; j++) {
    var fj = (j <= N / 2) ? j / (N * dz) : (j - N) / (N * dz);
    var phase = coeff * fj * fj;
    var cP = Math.cos(phase), sP = Math.sin(phase);
    var tRe = re[j] * cP - im[j] * sP;
    var tIm = re[j] * sP + im[j] * cP;
    re[j] = tRe; im[j] = tIm;
  }
  _fft(re, im, true);
  var intensity = new Float64Array(N);
  for (var i = 0; i < N; i++) intensity[i] = re[i]*re[i] + im[i]*im[i];
  var absZMin = Math.abs(zMin - (hMin + hMax) * 0.5);
  var absZMax = Math.abs(zMax - (hMin + hMax) * 0.5);
  var imageHalf = Math.min(Math.min(absZMax, absZMin), n_peaks * 0.88 * lambda * f_ff / D);
  var thetaMax = imageHalf / f_ff;
  var shifted = new Float64Array(N);
  for (var i = 0; i < N; i++) shifted[i] = intensity[(i + N/2) % N];
  var dtheta = dz / f_ff;
  var cropBins = Math.ceil(thetaMax / dtheta);
  var iCMin = Math.max(0, (N>>1) - cropBins);
  var iCMax = Math.min(N-1, (N>>1) + cropBins);
  var nCrop = iCMax - iCMin + 1;
  if (nCrop < 3) return new Float64Array(nSamples);
  var cropped = new Float64Array(nCrop);
  for (var i = 0; i < nCrop; i++) cropped[i] = shifted[iCMin + i];
  var aMin = (iCMin - N/2) * dtheta, aMax = (iCMax - N/2) * dtheta;
  return _inverseCdfSample_OLD(cropped, nCrop, aMin, aMax, nSamples);
}

// NEW _hybridFF1D (S4 port: interpolated histogram on dense wavefront grid)
function _hybridFF1D_NEW(footArr, nAlive, D, lambda, nSamples) {
  if (D < 1e-12 || nAlive < 3) return new Float64Array(nSamples);
  var n_peaks = 20, k = 2 * Math.PI / lambda;
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
  var re = new Float64Array(N), im = new Float64Array(N);
  for (var j = 0; j < N; j++) {
    var z = zMin + j * delta;
    var frac_idx = (z - zMin) / hist_delta;
    var idx0 = Math.floor(frac_idx), idx1 = idx0 + 1;
    if (idx0 < 0) { idx0 = 0; idx1 = 0; }
    if (idx1 >= nBins) { idx1 = nBins - 1; if (idx0 >= nBins) idx0 = nBins - 1; }
    var iv;
    if (idx0 === idx1) iv = hist[idx0];
    else iv = hist[idx0] + (hist[idx1] - hist[idx0]) * (frac_idx - idx0);
    var amp = Math.sqrt(Math.max(0, iv));
    var phi = -k * z * z / (2 * f_ff);
    re[j] = amp * Math.cos(phi); im[j] = amp * Math.sin(phi);
  }
  _fft(re, im, false);
  var coeff = -Math.PI * lambda * f_ff;
  for (var j = 0; j < N; j++) {
    var fi = (j < N/2) ? j : (j - N);
    var fj = fi / (N * delta);
    var phase = coeff * fj * fj;
    var cP = Math.cos(phase), sP = Math.sin(phase);
    var tRe = re[j]*cP - im[j]*sP, tIm = re[j]*sP + im[j]*cP;
    re[j] = tRe; im[j] = tIm;
  }
  _fft(re, im, true);
  var image_size = Math.min(Math.abs(zMax), Math.abs(zMin)) * 2;
  image_size = Math.min(image_size, n_peaks*2*0.88*lambda*f_ff/Math.abs(zMax-zMin));
  var image_n_pts = Math.round(image_size / delta / 2) * 2 + 1;
  if (image_n_pts < 3) image_n_pts = 3;
  if (image_n_pts > N) image_n_pts = N;
  var half_pts = (image_n_pts - 1) / 2;
  var intensity = new Float64Array(image_n_pts);
  for (var ip = 0; ip < image_n_pts; ip++) {
    var pos = (ip - half_pts) * delta;
    var wf = (pos - zMin) / delta;
    var i0 = Math.floor(wf), i1 = i0 + 1;
    if (i0 < 0 || i1 >= N) { intensity[ip] = 0; continue; }
    var f = wf - i0;
    var rr = re[i0]+(re[i1]-re[i0])*f, ii = im[i0]+(im[i1]-im[i0])*f;
    intensity[ip] = rr*rr + ii*ii;
  }
  var angMin = -half_pts * delta / f_ff, angMax = half_pts * delta / f_ff;
  return _inverseCdfSample_NEW(intensity, image_n_pts, angMin, angMax, nSamples);
}

function histFWHM(values, n) {
  var vMin = values[0], vMax = values[0];
  for (var i = 1; i < n; i++) {
    if (values[i] < vMin) vMin = values[i];
    if (values[i] > vMax) vMax = values[i];
  }
  var nB = 501, range = vMax - vMin;
  if (range < 1e-20) return 0;
  var dx = range / nB;
  var h = new Float64Array(nB);
  for (var i = 0; i < n; i++) { var b = Math.floor((values[i]-vMin)/dx); if (b>=0&&b<nB) h[b]++; }
  var mx = 0;
  for (var i = 0; i < nB; i++) if (h[i] > mx) mx = h[i];
  if (mx <= 0) return 0;
  var hm = mx*0.5, x0 = -1, x1 = -1;
  for (var i = 1; i < nB; i++) {
    if (h[i-1]<hm && h[i]>=hm && x0<0) x0=(i-1)+(hm-h[i-1])/(h[i]-h[i-1]);
    if (h[i-1]>=hm && h[i]<hm) x1=(i-1)+(hm-h[i-1])/(h[i]-h[i-1]);
  }
  if (x0<0||x1<0) return 0;
  return (x1-x0)*dx;
}

function gaussRandom(sigma) {
  var u1 = Math.random(), u2 = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// ========== COMPARE OLD vs NEW ==========
console.log('=== OLD vs NEW _hybridFF1D kick FWHM comparison ===\n');

var cases = [
  { name: 'KB-V 10keV', E: 10.0, D: 900e-6, sigma: 255e-6, q: 0.31 },
  { name: 'KB-H 10keV', E: 10.0, D: 300e-6, sigma: 86e-6,  q: 0.10 },
  { name: 'KB-V 5keV',  E: 5.0,  D: 900e-6, sigma: 255e-6, q: 0.31 },
  { name: 'KB-H 5keV',  E: 5.0,  D: 300e-6, sigma: 86e-6,  q: 0.10 },
  { name: 'KB-V 20keV', E: 20.0, D: 900e-6, sigma: 255e-6, q: 0.31 },
  { name: 'KB-H 20keV', E: 20.0, D: 300e-6, sigma: 86e-6,  q: 0.10 },
];

var nRays = 80000;
console.log('nRays = ' + nRays + '\n');
console.log(padR('Case',14) + padR('OLD urad',12) + padR('NEW urad',12) +
            padR('OLD@q nm',12) + padR('NEW@q nm',12) + padR('diff%',8));
console.log('-'.repeat(70));

function padR(s, w) { s = String(s); while (s.length < w) s += ' '; return s; }

for (var ci = 0; ci < cases.length; ci++) {
  var c = cases[ci];
  var lam = HC / c.E * 1e-10;

  // Generate Gaussian footprint truncated by aperture
  var foot = new Float64Array(nRays);
  var cnt = 0;
  while (cnt < nRays) {
    var g = gaussRandom(c.sigma);
    if (g > -c.D/2 && g < c.D/2) foot[cnt++] = g;
  }

  var kicksOLD = _hybridFF1D_OLD(foot, nRays, c.D, lam, nRays);
  var kicksNEW = _hybridFF1D_NEW(foot, nRays, c.D, lam, nRays);

  var fwhmOLD = histFWHM(kicksOLD, nRays);
  var fwhmNEW = histFWHM(kicksNEW, nRays);
  var diffPct = ((fwhmNEW - fwhmOLD) / fwhmOLD * 100).toFixed(1);

  console.log(
    padR(c.name, 14) +
    padR((fwhmOLD*1e6).toFixed(4), 12) +
    padR((fwhmNEW*1e6).toFixed(4), 12) +
    padR((fwhmOLD*c.q*1e9).toFixed(1), 12) +
    padR((fwhmNEW*c.q*1e9).toFixed(1), 12) +
    padR(diffPct + '%', 8)
  );
}
