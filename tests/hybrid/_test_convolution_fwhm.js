'use strict';
// Test: what total FWHM results from convolving geometric beam with diffraction kicks?
// Uses actual _hybridFF1D-generated kicks + synthetic geometric beam

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
function _inverseCdfSample(pdf, n, xMin, xMax, nSamples) {
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

function _hybridFF1D(footArr, nAlive, D, lambda, nSamples) {
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
    var di = i - nHalf;
    if (di < 0) di += N;
    re[di] = amp * Math.cos(phi);
    im[di] = amp * Math.sin(phi);
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
  for (var i = 0; i < N; i++) intensity[i] = re[i] * re[i] + im[i] * im[i];
  var absZMin = Math.abs(zMin - (hMin + hMax) * 0.5);
  var absZMax = Math.abs(zMax - (hMin + hMax) * 0.5);
  var imageHalf1 = Math.min(absZMax, absZMin);
  var imageHalf2 = n_peaks * 0.88 * lambda * f_ff / D;
  var imageHalf = Math.min(imageHalf1, imageHalf2);
  var thetaMax = imageHalf / f_ff;
  var shifted = new Float64Array(N);
  for (var i = 0; i < N; i++) { shifted[i] = intensity[(i + N / 2) % N]; }
  var dtheta = dz / f_ff;
  var cropBins = Math.ceil(thetaMax / dtheta);
  var iCropMin = Math.max(0, (N >> 1) - cropBins);
  var iCropMax = Math.min(N - 1, (N >> 1) + cropBins);
  var nCrop = iCropMax - iCropMin + 1;
  if (nCrop < 3) return new Float64Array(nSamples);
  var cropped = new Float64Array(nCrop);
  for (var i = 0; i < nCrop; i++) cropped[i] = shifted[iCropMin + i];
  var angMin = (iCropMin - N / 2) * dtheta;
  var angMax = (iCropMax - N / 2) * dtheta;
  return _inverseCdfSample(cropped, nCrop, angMin, angMax, nSamples);
}

function histFWHM(values, nValues) {
  var vMin = values[0], vMax = values[0];
  for (var i = 1; i < nValues; i++) {
    if (values[i] < vMin) vMin = values[i];
    if (values[i] > vMax) vMax = values[i];
  }
  var nBins = 501;
  var range = vMax - vMin;
  if (range < 1e-20) return 0;
  var dx = range / nBins;
  var hist = new Float64Array(nBins);
  for (var i = 0; i < nValues; i++) {
    var bin = Math.floor((values[i] - vMin) / dx);
    if (bin >= 0 && bin < nBins) hist[bin]++;
  }
  var mx = 0;
  for (var i = 0; i < nBins; i++) if (hist[i] > mx) mx = hist[i];
  if (mx <= 0) return 0;
  var hm = mx * 0.5;
  var x0 = -1, x1 = -1;
  for (var i = 1; i < nBins; i++) {
    if (hist[i-1] < hm && hist[i] >= hm && x0 < 0)
      x0 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
    if (hist[i-1] >= hm && hist[i] < hm)
      x1 = (i-1) + (hm - hist[i-1]) / (hist[i] - hist[i-1]);
  }
  if (x0 < 0 || x1 < 0) return 0;
  return (x1 - x0) * dx;
}

// Generate Gaussian random numbers (Box-Muller)
function gaussRandom(sigma) {
  var u1 = Math.random(), u2 = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// ====== Simulations ======
console.log('=== Convolution: geometric + diffraction kicks ===\n');

var E = 10.0;
var lam = HC / E * 1e-10;
var qV = 0.31; // KB-V to sample
var qH = 0.10; // KB-H to sample
var DV = 900e-6; // KB-V aperture
var DH = 300e-6; // KB-H aperture
var sigmaV = 255e-6; // footprint sigma on KB-V
var sigmaH = 86e-6;  // footprint sigma on KB-H
var nRays = 100000; // large for statistics

// Generate Gaussian footprint for KB-V
var footV = new Float64Array(nRays);
var cntV = 0;
while (cntV < nRays) {
  var g = gaussRandom(sigmaV);
  if (g > -DV/2 && g < DV/2) { footV[cntV++] = g; }
}

// Generate diffraction kicks
var kicksV = _hybridFF1D(footV, nRays, DV, lam, nRays);

// Test 1: Kick FWHM alone
var kickFwhmV = histFWHM(kicksV, nRays);
console.log('KB-V (D=900um, sigma=255um):');
console.log('  Kick angular FWHM = ' + (kickFwhmV*1e6).toFixed(4) + ' urad');
console.log('  Kick position FWHM at q=0.31m = ' + (kickFwhmV*qV*1e9).toFixed(1) + ' nm');

// Test 2: Geometric beam FWHM at sample
// Geometric position = footprint_pos + geometric_slope * q
// For a focused beam: slope = -footprint_pos / f_focal (thin lens)
// The geometric beam at sample: y_sample = y_mirror + slope * q
// For perfect focusing to sample: f = q, slope = -y/q, y_sample = y - y = 0 (perfect focus)
// In reality, there's residual aberration. The geometric FWHM is ~32nm.
// Let's use MC-like geometric: assume Gaussian with sigma_geo at sample

// Method A: Model geometric as Gaussian with known FWHM
var geomFwhmV_nm = 32.0; // approximate MC geometric FWHM
var geomSigmaV = geomFwhmV_nm * 1e-9 / 2.355;
console.log('  Geometric FWHM = ' + geomFwhmV_nm.toFixed(1) + ' nm (model)');

// Create sample positions: geometric + diffraction
var totalV = new Float64Array(nRays);
for (var i = 0; i < nRays; i++) {
  totalV[i] = gaussRandom(geomSigmaV) + kicksV[i] * qV;
}
var totalFwhmV = histFWHM(totalV, nRays) * 1e9;
var quadratureV = Math.sqrt(geomFwhmV_nm*geomFwhmV_nm + Math.pow(kickFwhmV*qV*1e9, 2));
console.log('  Total FWHM (geom + kick) = ' + totalFwhmV.toFixed(1) + ' nm');
console.log('  Quadrature prediction = ' + quadratureV.toFixed(1) + ' nm');
console.log('  Total/Quadrature = ' + (totalFwhmV/quadratureV).toFixed(4));
console.log('  S4 total V = ~44.8 nm');
console.log('');

// Method B: Use different geometric FWHM values
console.log('--- Sensitivity: total vs geometric FWHM ---');
var geoValues = [25, 28, 30, 32, 34, 36, 38, 40];
for (var gi = 0; gi < geoValues.length; gi++) {
  var gFwhm = geoValues[gi];
  var gSig = gFwhm * 1e-9 / 2.355;
  var tot = new Float64Array(nRays);
  for (var i = 0; i < nRays; i++) {
    tot[i] = gaussRandom(gSig) + kicksV[i] * qV;
  }
  var tFwhm = histFWHM(tot, nRays) * 1e9;
  var quad = Math.sqrt(gFwhm*gFwhm + Math.pow(kickFwhmV*qV*1e9, 2));
  console.log('  geo=' + gFwhm + 'nm: total=' + tFwhm.toFixed(1) + 'nm quad=' + quad.toFixed(1) + 'nm ratio=' + (tFwhm/quad).toFixed(3));
}
console.log('');

// Method C: What if geometric is NOT Gaussian? Use uniform (top-hat)
console.log('--- Non-Gaussian geometric (top-hat) ---');
var gFwhm = 32;
var gHalf = gFwhm * 1e-9 / 2;
var totU = new Float64Array(nRays);
for (var i = 0; i < nRays; i++) {
  totU[i] = (Math.random() - 0.5) * 2 * gHalf + kicksV[i] * qV;
}
var tFwhmU = histFWHM(totU, nRays) * 1e9;
console.log('  Uniform geo=' + gFwhm + 'nm: total=' + tFwhmU.toFixed(1) + 'nm');
console.log('');

// KB-H analysis
console.log('KB-H (D=300um, sigma=86um):');
var footH = new Float64Array(nRays);
var cntH = 0;
while (cntH < nRays) {
  var g = gaussRandom(sigmaH);
  if (g > -DH/2 && g < DH/2) { footH[cntH++] = g; }
}
var kicksH = _hybridFF1D(footH, nRays, DH, lam, nRays);
var kickFwhmH = histFWHM(kicksH, nRays);
console.log('  Kick angular FWHM = ' + (kickFwhmH*1e6).toFixed(4) + ' urad');
console.log('  Kick position FWHM at q=0.10m = ' + (kickFwhmH*qH*1e9).toFixed(1) + ' nm');

var geomFwhmH_nm = 35.0;
var geomSigmaH = geomFwhmH_nm * 1e-9 / 2.355;
var totalH = new Float64Array(nRays);
for (var i = 0; i < nRays; i++) {
  totalH[i] = gaussRandom(geomSigmaH) + kicksH[i] * qH;
}
var totalFwhmH = histFWHM(totalH, nRays) * 1e9;
var quadratureH = Math.sqrt(geomFwhmH_nm*geomFwhmH_nm + Math.pow(kickFwhmH*qH*1e9, 2));
console.log('  Geometric FWHM = ' + geomFwhmH_nm.toFixed(1) + ' nm (model)');
console.log('  Total FWHM = ' + totalFwhmH.toFixed(1) + ' nm');
console.log('  Quadrature = ' + quadratureH.toFixed(1) + ' nm');
console.log('  S4 total H = ~43.0 nm');
