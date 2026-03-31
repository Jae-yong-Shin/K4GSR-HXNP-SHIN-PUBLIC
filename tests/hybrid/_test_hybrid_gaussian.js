'use strict';
// Test: compare intensity-pattern FWHM vs CDF-sampled FWHM
// for GAUSSIAN beam footprint on KB-V (sigma=255um, D=900um)
// Uses the PRODUCTION N calculation (Nyquist-aware)

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

// Production-equivalent _hybridFF1D with Nyquist-aware N
function hybridFF1D(footArr, nAlive, D, lambda, nSamples) {
  if (D < 1e-12 || nAlive < 3) return { samples: new Float64Array(nSamples) };

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

  // PRODUCTION N calculation (Nyquist-aware)
  var N_nyquist = Math.ceil(lambda * f_ff / (dz * dz));
  var N = _nextPow2(Math.max(nBins * 2, N_nyquist * 4));
  if (N > 131072) N = 131072;

  var re = new Float64Array(N);
  var im = new Float64Array(N);

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

  // Image size
  var absZMin = Math.abs(zMin - (hMin + hMax) * 0.5);
  var absZMax = Math.abs(zMax - (hMin + hMax) * 0.5);
  var imageHalf1 = Math.min(absZMax, absZMin);
  var imageHalf2 = n_peaks * 0.88 * lambda * f_ff / D;
  var imageHalf = Math.min(imageHalf1, imageHalf2);
  var thetaMax = imageHalf / f_ff;

  // fftshift
  var shifted = new Float64Array(N);
  for (var i = 0; i < N; i++) {
    var j = (i + N / 2) % N;
    shifted[i] = intensity[j];
  }

  var dtheta = dz / f_ff;

  // Crop
  var cropBins = Math.ceil(thetaMax / dtheta);
  var iCropMin = Math.max(0, (N >> 1) - cropBins);
  var iCropMax = Math.min(N - 1, (N >> 1) + cropBins);
  var nCrop = iCropMax - iCropMin + 1;
  if (nCrop < 3) return { samples: new Float64Array(nSamples) };

  var cropped = new Float64Array(nCrop);
  for (var i = 0; i < nCrop; i++) cropped[i] = shifted[iCropMin + i];
  var angMin = (iCropMin - N / 2) * dtheta;
  var angMax = (iCropMax - N / 2) * dtheta;

  // Measure intensity profile FWHM
  var intFwhm = measureFWHM(cropped, nCrop, dtheta);

  // Sample
  var samples = _inverseCdfSample(cropped, nCrop, angMin, angMax, nSamples);

  return {
    samples: samples,
    intensityFwhm: intFwhm,
    N: N, N_nyquist: N_nyquist, dz: dz, f_ff: f_ff,
    nCrop: nCrop, angMin: angMin, angMax: angMax, dtheta: dtheta,
    imageHalf1: imageHalf1, imageHalf2: imageHalf2
  };
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

function sampleFWHM(samples, nS) {
  // Measure FWHM from sampled values via histogram
  var sMin = samples[0], sMax = samples[0];
  for (var i = 1; i < nS; i++) {
    if (samples[i] < sMin) sMin = samples[i];
    if (samples[i] > sMax) sMax = samples[i];
  }
  var nH = 501;
  var range = sMax - sMin;
  if (range < 1e-20) return 0;
  var dx = range / nH;
  var hist = new Float64Array(nH);
  for (var i = 0; i < nS; i++) {
    var bin = Math.floor((samples[i] - sMin) / dx);
    if (bin >= 0 && bin < nH) hist[bin]++;
  }
  return measureFWHM(hist, nH, dx);
}

// ====== Test Cases ======
console.log('=== Hybrid FF1D: Intensity vs Sampled FWHM ===\n');

var E = 10.0;
var lam = HC / E * 1e-10;

// Case 1: Uniform aperture (D=900um)
console.log('--- Case 1: Uniform aperture D=900um ---');
var D = 900e-6;
var nRays = 50000;
var foot = new Float64Array(nRays);
for (var i = 0; i < nRays; i++) foot[i] = (Math.random() - 0.5) * D;
var r = hybridFF1D(foot, nRays, D, lam, 200000);
var sFwhm = sampleFWHM(r.samples, 200000);
var airyFwhm = 0.886 * lam / D;
console.log('  N_nyquist=' + r.N_nyquist + ' N=' + r.N + ' dz=' + (r.dz*1e6).toFixed(2) + 'um');
console.log('  Airy theory = ' + (airyFwhm*1e6).toFixed(4) + ' urad');
console.log('  Intensity FWHM = ' + (r.intensityFwhm*1e6).toFixed(4) + ' urad (ratio=' + (r.intensityFwhm/airyFwhm).toFixed(4) + ')');
console.log('  Sampled FWHM = ' + (sFwhm*1e6).toFixed(4) + ' urad (ratio=' + (sFwhm/airyFwhm).toFixed(4) + ')');
console.log('  Intensity/Sampled = ' + (r.intensityFwhm/sFwhm).toFixed(4));
console.log('  imageHalf1=' + (r.imageHalf1*1e6).toFixed(1) + 'um imageHalf2=' + (r.imageHalf2*1e6).toFixed(1) + 'um');
console.log('');

// Case 2: Gaussian beam sigma=255um, clipped at D=900um (KB-V conditions)
console.log('--- Case 2: Gaussian sigma=255um, D=900um (KB-V 10keV) ---');
var sigma = 255e-6;
D = 900e-6;
nRays = 5500; // realistic MC ray count
foot = new Float64Array(nRays);
var cnt = 0;
while (cnt < nRays) {
  var g = 0;
  for (var i = 0; i < 12; i++) g += Math.random();
  g = (g - 6) * sigma;
  if (g > -D/2 && g < D/2) { foot[cnt++] = g; }
}
r = hybridFF1D(foot, nRays, D, lam, 200000);
sFwhm = sampleFWHM(r.samples, 200000);
// Gaussian theory: FWHM = 2*sqrt(ln2)*lambda/(2*pi*sigma)
var gaussFwhm = 2*Math.sqrt(Math.log(2))*lam/(2*Math.PI*sigma);
console.log('  sigma=' + (sigma*1e6).toFixed(0) + 'um footRange=[' +
  (foot[0]*1e6).toFixed(0) + '..' + (foot[nRays-1]*1e6).toFixed(0) + ']um');
console.log('  N_nyquist=' + r.N_nyquist + ' N=' + r.N + ' dz=' + (r.dz*1e6).toFixed(2) + 'um');
console.log('  f_ff=' + r.f_ff.toFixed(2) + 'm');
console.log('  Airy FWHM (D=900um) = ' + (airyFwhm*1e6).toFixed(4) + ' urad');
console.log('  Gaussian FWHM = ' + (gaussFwhm*1e6).toFixed(4) + ' urad');
console.log('  Intensity FWHM = ' + (r.intensityFwhm*1e6).toFixed(4) + ' urad');
console.log('  Sampled FWHM = ' + (sFwhm*1e6).toFixed(4) + ' urad');
console.log('  Int/Airy = ' + (r.intensityFwhm/airyFwhm).toFixed(4));
console.log('  Samp/Airy = ' + (sFwhm/airyFwhm).toFixed(4));
console.log('  Int/Samp = ' + (r.intensityFwhm/sFwhm).toFixed(4));
console.log('  Position FWHM at q=0.31m: Int=' + (r.intensityFwhm*0.31e9).toFixed(1) + 'nm Samp=' + (sFwhm*0.31e9).toFixed(1) + 'nm');
console.log('  nCrop=' + r.nCrop + ' angRange=[' + (r.angMin*1e6).toFixed(3) + ',' + (r.angMax*1e6).toFixed(3) + '] urad');
console.log('');

// Case 3: Same as Case 2 but with many more rays
console.log('--- Case 3: Gaussian sigma=255um, D=900um, 50K rays ---');
nRays = 50000;
foot = new Float64Array(nRays);
cnt = 0;
while (cnt < nRays) {
  var g = 0;
  for (var i = 0; i < 12; i++) g += Math.random();
  g = (g - 6) * sigma;
  if (g > -D/2 && g < D/2) { foot[cnt++] = g; }
}
r = hybridFF1D(foot, nRays, D, lam, 200000);
sFwhm = sampleFWHM(r.samples, 200000);
console.log('  N_nyquist=' + r.N_nyquist + ' N=' + r.N);
console.log('  Intensity FWHM = ' + (r.intensityFwhm*1e6).toFixed(4) + ' urad');
console.log('  Sampled FWHM = ' + (sFwhm*1e6).toFixed(4) + ' urad');
console.log('  Int/Samp = ' + (r.intensityFwhm/sFwhm).toFixed(4));
console.log('  Position FWHM at q=0.31m: Int=' + (r.intensityFwhm*0.31e9).toFixed(1) + 'nm Samp=' + (sFwhm*0.31e9).toFixed(1) + 'nm');
console.log('');

// Case 4: KB-H conditions (D=300um, sigma=86um)
console.log('--- Case 4: Gaussian sigma=86um, D=300um (KB-H 10keV) ---');
sigma = 86e-6;
D = 300e-6;
nRays = 5500;
foot = new Float64Array(nRays);
cnt = 0;
while (cnt < nRays) {
  var g = 0;
  for (var i = 0; i < 12; i++) g += Math.random();
  g = (g - 6) * sigma;
  if (g > -D/2 && g < D/2) { foot[cnt++] = g; }
}
r = hybridFF1D(foot, nRays, D, lam, 200000);
sFwhm = sampleFWHM(r.samples, 200000);
var airyH = 0.886 * lam / D;
var gaussH = 2*Math.sqrt(Math.log(2))*lam/(2*Math.PI*sigma);
console.log('  N_nyquist=' + r.N_nyquist + ' N=' + r.N);
console.log('  Airy FWHM = ' + (airyH*1e6).toFixed(4) + ' urad');
console.log('  Gaussian FWHM = ' + (gaussH*1e6).toFixed(4) + ' urad');
console.log('  Intensity FWHM = ' + (r.intensityFwhm*1e6).toFixed(4) + ' urad');
console.log('  Sampled FWHM = ' + (sFwhm*1e6).toFixed(4) + ' urad');
console.log('  Int/Samp = ' + (r.intensityFwhm/sFwhm).toFixed(4));
console.log('  Position FWHM at q=0.10m: Int=' + (r.intensityFwhm*0.10e9).toFixed(1) + 'nm Samp=' + (sFwhm*0.10e9).toFixed(1) + 'nm');
console.log('');

// Case 5: Compare N=512 (old) vs N=8192 (new) for Gaussian KB-V
console.log('--- Case 5: N=512 (old) vs Nyquist-aware (KB-V Gaussian) ---');
sigma = 255e-6;
D = 900e-6;
nRays = 5500;
foot = new Float64Array(nRays);
cnt = 0;
while (cnt < nRays) {
  var g = 0;
  for (var i = 0; i < 12; i++) g += Math.random();
  g = (g - 6) * sigma;
  if (g > -D/2 && g < D/2) { foot[cnt++] = g; }
}

// Run with forced N=512
function hybridFF1D_fixedN(footArr, nAlive, D, lambda, nSamples, forceN) {
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
  var N = forceN;
  var re = new Float64Array(N);
  var im = new Float64Array(N);
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
  if (nCrop < 3) return null;
  var cropped = new Float64Array(nCrop);
  for (var i = 0; i < nCrop; i++) cropped[i] = shifted[iCropMin + i];
  var angMin = (iCropMin - N / 2) * dtheta;
  var angMax = (iCropMax - N / 2) * dtheta;
  var intFwhm = measureFWHM(cropped, nCrop, dtheta);
  var samples = _inverseCdfSample(cropped, nCrop, angMin, angMax, nSamples);
  return { intensityFwhm: intFwhm, samples: samples, N: N };
}

var r512 = hybridFF1D_fixedN(foot, nRays, D, lam, 200000, 512);
var r8192 = hybridFF1D_fixedN(foot, nRays, D, lam, 200000, 8192);
if (r512 && r8192) {
  var sf512 = sampleFWHM(r512.samples, 200000);
  var sf8192 = sampleFWHM(r8192.samples, 200000);
  console.log('  N=512:  IntFWHM=' + (r512.intensityFwhm*1e6).toFixed(4) + ' SampFWHM=' + (sf512*1e6).toFixed(4) + ' urad');
  console.log('  N=8192: IntFWHM=' + (r8192.intensityFwhm*1e6).toFixed(4) + ' SampFWHM=' + (sf8192*1e6).toFixed(4) + ' urad');
  console.log('  Ratio 8192/512: Int=' + (r8192.intensityFwhm/r512.intensityFwhm).toFixed(4) + ' Samp=' + (sf8192/sf512).toFixed(4));
}
