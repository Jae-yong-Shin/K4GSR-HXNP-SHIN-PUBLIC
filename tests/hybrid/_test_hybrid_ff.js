'use strict';
// Standalone test: verify _hybridFF1D produces correct Airy FWHM
// for a uniform aperture.
//
// Expected: FWHM_theta = 0.886 * lambda / D
// Run: node _test_hybrid_ff.js

var HC = 12.3984; // keV*Angstrom

// --- Radix-2 Cooley-Tukey FFT (copied from 01_mc_engine.js) ---
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
        re[b] = re[a] - tRe;
        im[b] = im[a] - tIm;
        re[a] += tRe;
        im[a] += tIm;
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
    var samples = new Float64Array(nSamples);
    for (var i = 0; i < nSamples; i++) samples[i] = xMin + Math.random() * (xMax - xMin);
    return samples;
  }
  for (var i = 0; i < n; i++) cdf[i] /= total;
  var samples = new Float64Array(nSamples);
  for (var s = 0; s < nSamples; s++) {
    var u = Math.random();
    var lo = 0, hi = n - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (cdf[mid] < u) lo = mid + 1;
      else hi = mid;
    }
    var x0 = xMin + lo * dx;
    if (lo > 0 && cdf[lo] > cdf[lo - 1]) {
      var frac = (u - cdf[lo - 1]) / (cdf[lo] - cdf[lo - 1]);
      x0 = xMin + (lo - 1 + frac) * dx;
    }
    samples[s] = x0;
  }
  return samples;
}

// --- _hybridFF1D (copied from modified 01_mc_engine.js) ---
function _hybridFF1D(footArr, nAlive, D, lambda, nSamples) {
  if (D < 1e-12 || nAlive < 3) return new Float64Array(nSamples);

  var n_peaks = 20;
  var k = 2 * Math.PI / lambda;
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

  var N = _nextPow2(nBins * 2);
  var re = new Float64Array(N);
  var im = new Float64Array(N);

  // Center at DFT index 0
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
    re[j] = tRe;
    im[j] = tIm;
  }

  _fft(re, im, true);

  var intensity = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    intensity[i] = re[i] * re[i] + im[i] * im[i];
  }

  var absZMin = Math.abs(zMin - (hMin + hMax) * 0.5);
  var absZMax = Math.abs(zMax - (hMin + hMax) * 0.5);
  var imageHalf1 = Math.min(absZMax, absZMin);
  var imageHalf2 = n_peaks * 0.88 * lambda * f_ff / D;
  var imageHalf = Math.min(imageHalf1, imageHalf2);
  var thetaMax = imageHalf / f_ff;

  // fftshift: centered input -> output centered at N/2
  var shifted = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    var j = (i + N / 2) % N;
    shifted[i] = intensity[j];
  }

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

// Also compute the intensity profile directly (no sampling) for FWHM measurement
function _hybridFF1D_profile(footArr, nAlive, D, lambda) {
  if (D < 1e-12 || nAlive < 3) return null;

  var n_peaks = 20;
  var k = 2 * Math.PI / lambda;
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

  var N = _nextPow2(nBins * 2);
  var re = new Float64Array(N);
  var im = new Float64Array(N);

  // Center at DFT index 0
  var nHalf2 = nBins >> 1;
  for (var i = 0; i < nBins; i++) {
    var amp = Math.sqrt(Math.max(0, hist[i]));
    var z = hMin + (i + 0.5) * dz;
    var zc = z - (hMin + hMax) * 0.5;
    var phi = -k * zc * zc / (2 * f_ff);
    var di = i - nHalf2;
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
    re[j] = tRe;
    im[j] = tIm;
  }

  _fft(re, im, true);

  var intensity = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    intensity[i] = re[i] * re[i] + im[i] * im[i];
  }

  // fftshift: centered input -> output centered at N/2
  var shifted = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    var j = (i + N / 2) % N;
    shifted[i] = intensity[j];
  }

  var dtheta = dz / f_ff;

  return { intensity: shifted, N: N, dtheta: dtheta, f_ff: f_ff, dz: dz, D: D };
}

function measureFWHM(arr, N, dx) {
  var mx = 0;
  for (var i = 0; i < N; i++) if (arr[i] > mx) mx = arr[i];
  if (mx <= 0) return 0;
  var hm = mx * 0.5;
  var x0 = -1, x1 = -1;
  for (var i = 1; i < N; i++) {
    if (arr[i-1] < hm && arr[i] >= hm && x0 < 0) {
      x0 = (i-1) + (hm - arr[i-1]) / (arr[i] - arr[i-1]);
    }
    if (arr[i-1] >= hm && arr[i] < hm) {
      x1 = (i-1) + (hm - arr[i-1]) / (arr[i] - arr[i-1]);
    }
  }
  if (x0 < 0 || x1 < 0) return 0;
  return (x1 - x0) * dx;
}

// ====== Tests ======
console.log('=== Hybrid f_ff Trick Verification ===\n');

var testCases = [
  { E_keV: 10.0, D_mm: 0.300 * Math.sin(0.003), label: 'KB-V 10keV' },
  { E_keV: 10.0, D_mm: 0.100 * Math.sin(0.003), label: 'KB-H 10keV' },
  { E_keV: 5.0,  D_mm: 0.300 * Math.sin(0.003), label: 'KB-V 5keV' },
  { E_keV: 5.0,  D_mm: 0.100 * Math.sin(0.003), label: 'KB-H 5keV' },
  { E_keV: 20.0, D_mm: 0.300 * Math.sin(0.003), label: 'KB-V 20keV' },
  { E_keV: 20.0, D_mm: 0.100 * Math.sin(0.003), label: 'KB-H 20keV' },
];

for (var tc = 0; tc < testCases.length; tc++) {
  var E = testCases[tc].E_keV;
  var D = testCases[tc].D_mm; // already in meters (sin(3mrad)*length)
  var label = testCases[tc].label;
  var lam = HC / E * 1e-10; // wavelength in meters

  // Analytical Airy FWHM: 0.886 * lambda / D [radians]
  var fwhmTheory = 0.886 * lam / D;

  // Create uniform aperture: nRays uniformly distributed over [-D/2, D/2]
  var nRays = 50000;
  var footprint = new Float64Array(nRays);
  for (var i = 0; i < nRays; i++) {
    footprint[i] = (Math.random() - 0.5) * D;
  }

  // Get intensity profile
  var prof = _hybridFF1D_profile(footprint, nRays, D, lam);
  if (!prof) {
    console.log(label + ': FAILED (null profile)');
    continue;
  }

  var fwhmMeasured = measureFWHM(prof.intensity, prof.N, prof.dtheta);

  var ratio = fwhmMeasured / fwhmTheory;
  var status = (Math.abs(ratio - 1.0) < 0.05) ? 'PASS' : 'FAIL';

  console.log(label + ':');
  console.log('  D = ' + (D*1e6).toFixed(1) + ' um, lambda = ' + (lam*1e10).toFixed(4) + ' A');
  console.log('  f_ff = ' + prof.f_ff.toFixed(4) + ' m');
  console.log('  FWHM theory = ' + (fwhmTheory*1e6).toFixed(3) + ' urad');
  console.log('  FWHM measured = ' + (fwhmMeasured*1e6).toFixed(3) + ' urad');
  console.log('  ratio = ' + ratio.toFixed(4) + '  [' + status + ']');
  console.log('');

  // Also test sampling
  var kicks = _hybridFF1D(footprint, nRays, D, lam, 100000);
  // Measure FWHM from sampled kicks via histogram
  var nSH = 501;
  var sHist = new Float64Array(nSH);
  var sRange = fwhmTheory * 10;
  for (var i = 0; i < kicks.length; i++) {
    var bin = Math.floor((kicks[i] + sRange) / (2 * sRange) * nSH);
    if (bin >= 0 && bin < nSH) sHist[bin]++;
  }
  var fwhmSampled = measureFWHM(sHist, nSH, 2 * sRange / nSH);
  var ratioS = fwhmSampled / fwhmTheory;
  var statusS = (Math.abs(ratioS - 1.0) < 0.10) ? 'PASS' : 'FAIL';
  console.log('  Sampled FWHM = ' + (fwhmSampled*1e6).toFixed(3) + ' urad, ratio = ' + ratioS.toFixed(4) + '  [' + statusS + ']');
  console.log('');
}

// Test with KB geometry: q=0.1m (KB-H to sample), D=300um
// Expected spot FWHM = 0.886 * lambda * q / D
console.log('=== Spot Size at Sample ===\n');
var E = 10.0, lam = HC / E * 1e-10;
var qKBH = 0.10; // m
var DKBH = 0.100 * Math.sin(0.003); // m

var fwhmAngle = 0.886 * lam / DKBH;
var fwhmSpot = fwhmAngle * qKBH;
console.log('KB-H 10keV:');
console.log('  Diffraction-limited spot FWHM = ' + (fwhmSpot * 1e9).toFixed(1) + ' nm');
console.log('  (This is the angular kick * q, pure diffraction limit)');

// SSA diffraction test: 50um slit at 10keV
// For a uniformly illuminated slit of width a = 50um:
// FWHM_theta = 0.886 * lambda / a
console.log('\n=== SSA Diffraction Test ===\n');
var ssaTests = [
  { E_keV: 10.0, ssa_um: 50, label: 'SSA 50um 10keV' },
  { E_keV: 10.0, ssa_um: 10, label: 'SSA 10um 10keV' },
  { E_keV: 10.0, ssa_um: 200, label: 'SSA 200um 10keV' },
  { E_keV: 5.0, ssa_um: 50, label: 'SSA 50um 5keV' },
  { E_keV: 20.0, ssa_um: 50, label: 'SSA 50um 20keV' },
];

for (var st = 0; st < ssaTests.length; st++) {
  var sE = ssaTests[st].E_keV;
  var sA = ssaTests[st].ssa_um * 1e-6; // full width in m
  var sLam = HC / sE * 1e-10;
  var sLabel = ssaTests[st].label;

  // Analytical: FWHM = 0.886 * lambda / a
  var sFwhmTheory = 0.886 * sLam / sA;

  // Create uniform aperture positions
  var sNRays = 50000;
  var sFoot = new Float64Array(sNRays);
  for (var i = 0; i < sNRays; i++) {
    sFoot[i] = (Math.random() - 0.5) * sA;
  }

  var sKicks = _hybridFF1D(sFoot, sNRays, sA, sLam, 100000);
  // Measure FWHM from sampled kicks
  var snH = 501;
  var sHist2 = new Float64Array(snH);
  var sRange2 = sFwhmTheory * 15;
  for (var i = 0; i < sKicks.length; i++) {
    var sbin = Math.floor((sKicks[i] + sRange2) / (2 * sRange2) * snH);
    if (sbin >= 0 && sbin < snH) sHist2[sbin]++;
  }
  var sFwhmSampled = measureFWHM(sHist2, snH, 2 * sRange2 / snH);
  var sRatio = sFwhmSampled / sFwhmTheory;
  var sStatus = (Math.abs(sRatio - 1.0) < 0.10) ? 'PASS' : 'FAIL';
  console.log(sLabel + ':');
  console.log('  Aperture = ' + ssaTests[st].ssa_um + ' um, lambda = ' + (sLam*1e10).toFixed(4) + ' A');
  console.log('  FWHM theory = ' + (sFwhmTheory*1e6).toFixed(4) + ' urad');
  console.log('  FWHM sampled = ' + (sFwhmSampled*1e6).toFixed(4) + ' urad');
  console.log('  ratio = ' + sRatio.toFixed(4) + '  [' + sStatus + ']');
  console.log('');
}

var qKBV = 0.31; // m (kbv to sample through kbh)
var DKBV = 0.300 * Math.sin(0.003);
var fwhmAngleV = 0.886 * lam / DKBV;
var fwhmSpotV = fwhmAngleV * qKBV;
console.log('KB-V 10keV:');
console.log('  Diffraction-limited spot FWHM = ' + (fwhmSpotV * 1e9).toFixed(1) + ' nm');
