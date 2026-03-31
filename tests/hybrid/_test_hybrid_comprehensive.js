'use strict';
// Comprehensive hybrid f_ff verification across diverse conditions
// Tests: SSA (10/50/100/200um) x Energy (5/8/10/15/20/25/30 keV)
//        KB-V/KB-H x Energy (5/10/15/20/25 keV)
//        Gaussian beam profiles (realistic beamline)
// Run: node _test_hybrid_comprehensive.js

var HC = 12.3984; // keV*Angstrom

// --- FFT, inverse CDF (same as 01_mc_engine.js) ---
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
        curIm = curRe * wIm + curIm * wRe; curRe = tmpR;
      }
    }
  }
  if (inv) { for (var i = 0; i < N; i++) { re[i] /= N; im[i] /= N; } }
}
function _nextPow2(n) { var p = 1; while (p < n) p <<= 1; return p; }
function _inverseCdfSample(pdf, n, xMin, xMax, nSamples) {
  var dx = (xMax - xMin) / (n - 1);
  var cdf = new Float64Array(n); cdf[0] = pdf[0];
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
    while (lo < hi) { var mid = (lo + hi) >> 1; if (cdf[mid] < u) lo = mid + 1; else hi = mid; }
    var x0 = xMin + lo * dx;
    if (lo > 0 && cdf[lo] > cdf[lo - 1]) {
      var frac = (u - cdf[lo - 1]) / (cdf[lo] - cdf[lo - 1]);
      x0 = xMin + (lo - 1 + frac) * dx;
    }
    samples[s] = x0;
  }
  return samples;
}

// --- _hybridFF1D (exact copy from 01_mc_engine.js) ---
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
  for (var i = 0; i < N; i++) { var j = (i + N / 2) % N; shifted[i] = intensity[j]; }
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

// --- Utilities ---
function gaussRand() {
  var u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function measureFWHM(arr, N, dx) {
  var mx = 0;
  for (var i = 0; i < N; i++) if (arr[i] > mx) mx = arr[i];
  if (mx <= 0) return 0;
  var hm = mx * 0.5, x0 = -1, x1 = -1;
  for (var i = 1; i < N; i++) {
    if (arr[i-1] < hm && arr[i] >= hm && x0 < 0)
      x0 = (i-1) + (hm - arr[i-1]) / (arr[i] - arr[i-1]);
    if (arr[i-1] >= hm && arr[i] < hm)
      x1 = (i-1) + (hm - arr[i-1]) / (arr[i] - arr[i-1]);
  }
  if (x0 < 0 || x1 < 0) return 0;
  return (x1 - x0) * dx;
}

function histFWHM(kicks, nKicks, nBins, range) {
  var hist = new Float64Array(nBins);
  for (var i = 0; i < nKicks; i++) {
    var bin = Math.floor((kicks[i] + range) / (2 * range) * nBins);
    if (bin >= 0 && bin < nBins) hist[bin]++;
  }
  return measureFWHM(hist, nBins, 2 * range / nBins);
}

// ============================================================
// TEST 1: Uniform aperture — SSA x Energy matrix
// ============================================================
console.log('================================================================');
console.log('  TEST 1: Uniform Aperture (SSA diffraction)');
console.log('  Theory: FWHM_theta = 0.886 * lambda / D');
console.log('================================================================\n');

var ssaSizes = [10, 25, 50, 100, 200]; // um
var energies = [5, 8, 10, 15, 20, 25, 30]; // keV
var nRays = 50000;
var nKicks = 100000;
var nBinsHist = 501;

var passCount = 0, failCount = 0;

console.log('SSA(um)  E(keV)  Theory(urad)  Measured(urad)  Ratio    Status');
console.log('-------  ------  -----------   -------------   ------   ------');

for (var si = 0; si < ssaSizes.length; si++) {
  for (var ei = 0; ei < energies.length; ei++) {
    var ssa = ssaSizes[si] * 1e-6; // full width in m
    var E = energies[ei];
    var lam = HC / E * 1e-10;
    var fwhmTheory = 0.886 * lam / ssa;

    // Generate uniform aperture footprint
    var foot = new Float64Array(nRays);
    for (var i = 0; i < nRays; i++) foot[i] = (Math.random() - 0.5) * ssa;

    var kicks = _hybridFF1D(foot, nRays, ssa, lam, nKicks);
    var fwhmMeas = histFWHM(kicks, nKicks, nBinsHist, fwhmTheory * 15);
    var ratio = fwhmMeas / fwhmTheory;
    var ok = Math.abs(ratio - 1.0) < 0.05;
    if (ok) passCount++; else failCount++;

    console.log(
      ('   ' + ssaSizes[si]).slice(-4) + '     ' +
      ('  ' + E).slice(-3) + '     ' +
      (fwhmTheory * 1e6).toFixed(4).padStart(10) + '    ' +
      (fwhmMeas * 1e6).toFixed(4).padStart(10) + '    ' +
      ratio.toFixed(4) + '   ' + (ok ? 'PASS' : '**FAIL**')
    );
  }
}

// ============================================================
// TEST 2: KB aperture x Energy matrix
// ============================================================
console.log('\n================================================================');
console.log('  TEST 2: KB Aperture x Energy');
console.log('  KB-V: L=300mm, KB-H: L=100mm, theta_g=3mrad');
console.log('================================================================\n');

var kbConfigs = [
  { name: 'KB-V', len: 0.300, tg: 0.003 },
  { name: 'KB-H', len: 0.100, tg: 0.003 },
];
var kbEnergies = [5, 8, 10, 15, 20, 25];

console.log('KB     E(keV)  D(um)  Theory(urad)  Measured(urad)  Ratio    Status');
console.log('-----  ------  -----  -----------   -------------   ------   ------');

for (var ki = 0; ki < kbConfigs.length; ki++) {
  var kb = kbConfigs[ki];
  var D = kb.len * Math.sin(kb.tg);

  for (var ei = 0; ei < kbEnergies.length; ei++) {
    var E = kbEnergies[ei];
    var lam = HC / E * 1e-10;
    var fwhmTheory = 0.886 * lam / D;

    var foot = new Float64Array(nRays);
    for (var i = 0; i < nRays; i++) foot[i] = (Math.random() - 0.5) * D;

    var kicks = _hybridFF1D(foot, nRays, D, lam, nKicks);
    var fwhmMeas = histFWHM(kicks, nKicks, nBinsHist, fwhmTheory * 15);
    var ratio = fwhmMeas / fwhmTheory;
    var ok = Math.abs(ratio - 1.0) < 0.05;
    if (ok) passCount++; else failCount++;

    console.log(
      kb.name.padEnd(6) + ('  ' + E).slice(-3) + '     ' +
      (D * 1e6).toFixed(0).padStart(4) + '  ' +
      (fwhmTheory * 1e6).toFixed(4).padStart(10) + '    ' +
      (fwhmMeas * 1e6).toFixed(4).padStart(10) + '    ' +
      ratio.toFixed(4) + '   ' + (ok ? 'PASS' : '**FAIL**')
    );
  }
}

// ============================================================
// TEST 3: Gaussian beam within SSA (realistic beamline case)
// ============================================================
console.log('\n================================================================');
console.log('  TEST 3: Gaussian Beam in SSA (realistic BL10)');
console.log('  Beam sigma at SSA: 20um (10keV) to 40um (5keV)');
console.log('  SSA clips only tails -> diffraction from beam, not slit');
console.log('================================================================\n');

var gaussTests = [
  { E: 10, ssa_um: 50, beam_sigma_um: 20, label: '10keV SSA50 sig20' },
  { E: 10, ssa_um: 50, beam_sigma_um: 10, label: '10keV SSA50 sig10' },
  { E: 10, ssa_um: 10, beam_sigma_um: 20, label: '10keV SSA10 sig20 (clips)' },
  { E: 10, ssa_um: 200, beam_sigma_um: 20, label: '10keV SSA200 sig20 (no clip)' },
  { E: 5, ssa_um: 50, beam_sigma_um: 30, label: '5keV SSA50 sig30' },
  { E: 20, ssa_um: 50, beam_sigma_um: 15, label: '20keV SSA50 sig15' },
];

console.log('Condition                      Eff_D(um)  Theory(urad)  Measured(urad)  Ratio    Status');
console.log('-----------------------------  --------   -----------   -------------   ------   ------');

for (var gi = 0; gi < gaussTests.length; gi++) {
  var gt = gaussTests[gi];
  var lam = HC / gt.E * 1e-10;
  var halfSSA = gt.ssa_um * 0.5e-6;
  var beamSig = gt.beam_sigma_um * 1e-6;

  // Generate Gaussian beam, clip by SSA
  var gFoot = [];
  for (var i = 0; i < nRays * 3; i++) {
    var x = gaussRand() * beamSig;
    if (Math.abs(x) <= halfSSA) gFoot.push(x);
    if (gFoot.length >= nRays) break;
  }
  var gN = gFoot.length;
  if (gN < 100) { console.log(gt.label + ': too few rays survived'); continue; }
  var gArr = new Float64Array(gN);
  for (var i = 0; i < gN; i++) gArr[i] = gFoot[i];

  // Effective D from actual footprint
  var gMin = gArr[0], gMax = gArr[0];
  for (var i = 1; i < gN; i++) {
    if (gArr[i] < gMin) gMin = gArr[i];
    if (gArr[i] > gMax) gMax = gArr[i];
  }
  var effD = gMax - gMin;
  if (effD > 2 * halfSSA) effD = 2 * halfSSA;

  // For Gaussian illumination, the analytical FWHM is different from uniform.
  // For a Gaussian aperture of RMS sigma: FWHM_theta = 0.886 * lambda / (2*sqrt(2*ln2)*sigma)
  // But for truncated Gaussian (SSA clip), there's no simple formula.
  // We compare against uniform-aperture theory using the effective D as reference.
  var fwhmRef = 0.886 * lam / effD;

  var kicks = _hybridFF1D(gArr, gN, effD, lam, nKicks);
  var fwhmMeas = histFWHM(kicks, nKicks, nBinsHist, fwhmRef * 15);
  var ratio = fwhmMeas / fwhmRef;

  // For Gaussian illumination, expect ratio ~ 1.0-1.5 (Gaussian gives wider diffraction
  // than uniform aperture of same width due to apodization)
  var ok = ratio > 0.5 && ratio < 2.5 && fwhmMeas > 0;
  if (ok) passCount++; else failCount++;

  console.log(
    gt.label.padEnd(30) + ' ' +
    (effD * 1e6).toFixed(1).padStart(7) + '   ' +
    (fwhmRef * 1e6).toFixed(4).padStart(10) + '    ' +
    (fwhmMeas * 1e6).toFixed(4).padStart(10) + '    ' +
    ratio.toFixed(4) + '   ' + (ok ? 'PASS' : '**FAIL**')
  );
}

// ============================================================
// TEST 4: Spot size at sample (angular FWHM * q)
// ============================================================
console.log('\n================================================================');
console.log('  TEST 4: Expected Spot Size at Sample (diffraction limit)');
console.log('  Spot FWHM = angular_FWHM * q_distance');
console.log('================================================================\n');

var spotTests = [
  { E: 10, name: 'KB-H', len: 0.100, tg: 0.003, q: 0.10 },
  { E: 10, name: 'KB-V', len: 0.300, tg: 0.003, q: 0.31 },
  { E: 5,  name: 'KB-H', len: 0.100, tg: 0.003, q: 0.10 },
  { E: 5,  name: 'KB-V', len: 0.300, tg: 0.003, q: 0.31 },
  { E: 20, name: 'KB-H', len: 0.100, tg: 0.003, q: 0.10 },
  { E: 20, name: 'KB-V', len: 0.300, tg: 0.003, q: 0.31 },
];

console.log('KB     E(keV)  q(m)   Diff_FWHM(nm)  S4_ref(nm)  Comment');
console.log('-----  ------  -----  ------------   ---------   -------');

// S4 reference values from paper/validation/data/
var s4Ref = {
  '10_H': 40.8, '10_V': 45.2,
  '5_H': 66.2, '5_V': 70.8,
  '20_H': 35.6, '20_V': 32.5
};

for (var si2 = 0; si2 < spotTests.length; si2++) {
  var st = spotTests[si2];
  var D = st.len * Math.sin(st.tg);
  var lam = HC / st.E * 1e-10;
  var diffFwhm = 0.886 * lam / D * st.q * 1e9; // nm
  var key = st.E + '_' + (st.name === 'KB-H' ? 'H' : 'V');
  var s4 = s4Ref[key] || 0;
  var comment = s4 > 0 ? ('geo+diff, S4 includes both') : '';

  console.log(
    st.name.padEnd(6) + ('  ' + st.E).slice(-3) + '     ' +
    st.q.toFixed(2) + '   ' +
    diffFwhm.toFixed(1).padStart(10) + '      ' +
    (s4 > 0 ? s4.toFixed(1) : 'N/A').padStart(7) + '     ' +
    comment
  );
}

// ============================================================
// Summary
// ============================================================
console.log('\n================================================================');
console.log('  SUMMARY');
console.log('================================================================');
console.log('  Total tests: ' + (passCount + failCount));
console.log('  PASS: ' + passCount);
console.log('  FAIL: ' + failCount);
console.log('  Pass rate: ' + (passCount / (passCount + failCount) * 100).toFixed(1) + '%');
if (failCount === 0) {
  console.log('  ** ALL TESTS PASSED **');
} else {
  console.log('  ** SOME TESTS FAILED **');
}
