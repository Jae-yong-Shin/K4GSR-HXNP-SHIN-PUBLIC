'use strict';
// ===== optics/divergence_gpu.js — WebGPU compute port of effective divergence =====
// @module optics/divergence_gpu
// @exports divergenceGPU
//
// SPECTRA-style effective angular divergence (sigma_x', sigma_y') at slit
// distance Z, computed on the GPU. Architecture mirrors
// 03_webgpu_flux_acceptance.js:
//
//   * Workgroup: @workgroup_size(16, 16, 1) tile over the 128 x 128
//     observation-angle grid (theta_x, theta_y). Per-cell cost is dominated
//     by the inner fLinFxy2 m-series Bessel evaluation, similar order to
//     fluxAcceptanceGPU per cell.
//
//   * Outer (a, b, id) emittance + energy-spread loop is SPLIT host-side
//     into DG_AB_NUM_BLOCKS = 8 dispatches. First dispatch zero-inits the
//     scratch G_xy buffer (zero_scratch=1); subsequent dispatches
//     accumulate. Per-dispatch budget < 200 ms vs Windows 2 s TDR.
//
// Output:
//   * G_xy[ix, iy] : 128 x 128 angular density (arbitrary units; only the
//     2nd moment is used downstream so normalisation cancels).
//   * Reduced on the host to marginals Px = sum_y G, Py = sum_x G, then
//     rms_x = sqrt(sum(theta^2 * Px) / sum(Px)) (centroid-subtracted),
//     converted to micro-rad. (Z parameter is taken for API parity with
//     fluxDivergenceLookup; the rms is intrinsically in angular units, so
//     Z is informational here — divergence at the source is geometry-
//     invariant in the far field.)
//
// Public API:
//   divergenceGPU(K, n, Z) -> Promise<{ Sxp_urad, Syp_urad, tier }>
//
// Depends on:
//   - window.detectWebGPU() from 02_webgpu_detect.js (window._GPU.device)
//   - calcE1, _undGrids, besselJ (already on globalThis via 01_undulator.js)
//   - SIG_EXP, SIG_EYP, E_SPREAD, N_PERIODS, GAMMA_E, L_UND, HC, BETA_X, BETA_Y
//     (already on globalThis via 01_constants.js)
//
// Coding rules (CLAUDE.md): ES5-strict (var/function only, no arrow/const/let/
// template literals). WGSL source assembled by string concatenation.


// ===========================================================================
// Kernel tuning constants. Exported on globalThis for tests/diagnostics.
//
// Numerical params reverted 2026-06-03 to base config after COVER sweep.
// Python sweep (paper/validation/test_divergence_physics_vs_spectra*.py)
// vs SPECTRA spectra_divmeas_multiK over operational band n=3-11:
//   COVER=3 (NGRID=128, N_ES=7, N_EMIT=9): mean devX 4.87%, devY 1.41%;
//                                          max devX 10.35%, devY 3.25%.
//   COVER=4 (NGRID=128, N_ES=7, N_EMIT=9): inconclusive (truncated run).
//   COVER=5 (NGRID=128, N_ES=7, N_EMIT=9): mean devX 2.53%, devY 1.66%;
//                                          max devX 5.5%, devY 5.1%.  <-- WINNER
//   COVER=8 (NGRID=192, N_ES=9, N_EMIT=11): mean devX 1.66%, devY 4.29%
//                                           (v4.37.29 (a)-config — lopsided).
// No config met Rule-1 (mean<=1% both axes) or Rule-2 (max<2.5% both axes),
// so Rule-3 FALLBACK applies: base COVER=5 has the best-balanced means and
// beats COVER=8's devY=4.29% / COVER=3's devX=10.35%.
// ===========================================================================
var DG_WG_X            = 16;   // workgroup_size X (tile width  in theta-pix)
var DG_WG_Y            = 16;   // workgroup_size Y (tile height in theta-pix)
var DG_N_THETA         = 128;  // theta grid is N_THETA x N_THETA  (NGRID)
var DG_THETA_SIGMA_NX  = 5.0;  // theta range = +/- DG_THETA_SIGMA_NX * sigma_max  (COVER_SIG)
var DG_N_EMIT          = 9;    // emittance Gauss-quad nodes per axis  (N_EMIT)
var DG_N_ESPREAD       = 7;    // energy-spread uniform-mesh nodes, base/floor (N_ESPREAD)
// Energy-spread nodes scale with harmonic n: the sinc^2 oscillates with period
// 1/(2nN) in relative energy deviation, so a fixed count under-resolves the
// convolution at high harmonics (matched the SPECTRA energy-spread scheme in the
// offline source-size/divergence validation, Suppl. S3.5). nE = min(MAX, base+2n),
// capped for interactive GPU latency.
var DG_N_ESPREAD_MAX   = 25;   // cap (GPU latency); offline validation uses uncapped
var DG_BESSEL_MAX_ITER = 50;   // besselJ series cap (Taylor fallback)
var DG_AB_NUM_BLOCKS   = 8;    // # of host-side (a,b) sub-dispatches per call


// LUT (shared format with fluxAcceptanceGPU). Built locally rather than
// imported so this module stays self-contained; the table is small (~17 KB).
var DG_LUT_N_ROWS = 48;
var DG_LUT_X_UPPER = 4.5;
var DG_LUT_DX = 0.05;
var DG_LUT_NX = Math.round(DG_LUT_X_UPPER / DG_LUT_DX) + 1;  // 91

var _dgBesselLUT = null;


// ===========================================================================
// Pipeline / buffer cache (per device + kernel key + buffer shape).
// ===========================================================================
var _dgPipelineCache = {
  device: null,
  kernelKey: '',
  module: null,
  layout: null,
  bindGroupLayout: null,
  pipelineAccum: null,
  bufferKey: '',
  buffers: null
};


function _dgBuildBesselLUT() {
  if (_dgBesselLUT) return _dgBesselLUT;
  if (typeof besselJ !== 'function') {
    throw new Error('besselJ not loaded (01_undulator.js missing)');
  }
  var N = DG_LUT_N_ROWS, NX = DG_LUT_NX, dx = DG_LUT_DX;
  var arr = new Float32Array(N * NX);
  var n, k;
  for (n = 0; n < N; n++) {
    for (k = 0; k < NX; k++) {
      arr[n * NX + k] = besselJ(n, k * dx);
    }
  }
  _dgBesselLUT = arr;
  return arr;
}


// Gaussian-weighted nodes on +/- 5 sigma, normalised weights. Interleaved
// (value, weight) for WGSL vec2<f32> consumption.
function _dgBuildGaussInterleaved(sig, m) {
  var out = new Float32Array(m * 2);
  var s = 0, j, x, ww;
  for (j = 0; j < m; j++) {
    x = (-5 + 10 * j / (m - 1)) * sig;
    ww = Math.exp(-x * x / (2 * sig * sig));
    out[2 * j] = x;
    out[2 * j + 1] = ww;
    s += ww;
  }
  for (j = 0; j < m; j++) out[2 * j + 1] /= s;
  return out;
}


// Prepare all host-side inputs.
function _dgPrepareInputs(K, n, Z) {
  var En = n * calcE1(K);
  var s0 = Math.sqrt((HC / En) * 1e-10 / (2 * L_UND));  // natural divergence (rad)
  var H = 1 + K * K / 2;
  var piNn = Math.PI * n * N_PERIODS;
  var f4 = 4 * s0 * s0;
  var twoNN = 2 * n * N_PERIODS;

  // Emittance nodes fixed; energy-spread nodes scale with harmonic n (uniform
  // mesh, +/-5 sigma, Gaussian-weighted) so the sinc^2 convolution stays resolved
  // at high harmonics, matching the SPECTRA energy-spread scheme validated offline
  // (Suppl. S3.5).  Capped at DG_N_ESPREAD_MAX for interactive GPU latency.
  var nA = DG_N_EMIT;
  var nE_emit = Math.min(DG_N_ESPREAD_MAX, DG_N_ESPREAD + 2 * n);

  // theta range: a few times the projected emittance divergence plus
  // natural divergence, capped to a sensible window.
  var sx = Math.sqrt(SIG_EXP * SIG_EXP + s0 * s0);
  var sy = Math.sqrt(SIG_EYP * SIG_EYP + s0 * s0);
  var smax = Math.max(sx, sy);
  var halfTheta = DG_THETA_SIGMA_NX * smax;

  var nTh = DG_N_THETA;
  var dTh = (2 * halfTheta) / (nTh - 1);

  // Emittance + energy-spread node grids (same as 01_undulator.js eSpreadAngleSupp).
  var emit_x = _dgBuildGaussInterleaved(SIG_EXP, nA);
  var emit_y = _dgBuildGaussInterleaved(SIG_EYP, nA);
  var emit_d = _dgBuildGaussInterleaved(E_SPREAD, nE_emit);

  // (a, b) dispatch split
  var abPairs = nA * nA;
  var abNumBlocks = DG_AB_NUM_BLOCKS;
  if (abNumBlocks > abPairs) abNumBlocks = abPairs;
  if (abNumBlocks < 1) abNumBlocks = 1;
  var abBlockSize = Math.ceil(abPairs / abNumBlocks);

  // Uniform buffer 96 B: 16 f32 + 8 u32.
  var uniBuf = new ArrayBuffer(96);
  var uf = new Float32Array(uniBuf, 0, 16);
  var ui = new Int32Array(uniBuf, 64, 8);

  uf[0] = K;
  uf[1] = halfTheta;
  uf[2] = dTh;
  uf[3] = En;
  uf[4] = GAMMA_E;
  uf[5] = H;
  uf[6] = s0;          // natural divergence
  uf[7] = f4;          // 4 * s0^2
  uf[8] = twoNN;
  uf[9] = piNn;
  uf[10] = E_SPREAD;
  uf[11] = N_PERIODS;
  uf[12] = Z;          // metadata only (rms is in angular units)
  uf[13] = 0;          // pad
  uf[14] = 0;
  uf[15] = 0;

  ui[0] = n | 0;
  ui[1] = nTh | 0;
  ui[2] = nA | 0;
  ui[3] = nE_emit | 0;
  ui[4] = 0;                 // ab_start (host rewrites)
  ui[5] = abBlockSize | 0;   // ab_end   (host rewrites)
  ui[6] = 1;                 // zero_scratch
  ui[7] = 0;                 // pad

  return {
    params: new Uint8Array(uniBuf),
    emit_x: emit_x,
    emit_y: emit_y,
    emit_d: emit_d,
    halfTheta: halfTheta,
    dTh: dTh,
    nTh: nTh,
    nA: nA,
    nE_emit: nE_emit,
    abPairs: abPairs,
    abBlockSize: abBlockSize,
    abNumBlocks: abNumBlocks
  };
}


// ===========================================================================
// WGSL kernel source — single flux_accum entry point producing G_xy.
// Reduction (sum to marginals + rms) is done on the host in JS for simplicity.
// ===========================================================================
function _dgBuildShaderWGSL() {
  var wgX = DG_WG_X;
  var wgY = DG_WG_Y;
  var bessCap = DG_BESSEL_MAX_ITER;
  var lutN = DG_LUT_N_ROWS;
  var lutNX = DG_LUT_NX;
  var lutDx = DG_LUT_DX;
  var lutXup = DG_LUT_X_UPPER;

  var src = [
    '// === HANBIT divergenceGPU compute kernel ===',
    '// workgroup_size(' + wgX + ', ' + wgY + ', 1) tile over theta_x x theta_y.',
    '',
    'struct Params {',
    '  K:           f32,',
    '  halfTheta:   f32,',
    '  dTh:         f32,',
    '  En:          f32,',
    '  GAMMA_E:     f32,',
    '  H:           f32,',
    '  s0:          f32,',
    '  f4:          f32,',
    '  twoNN:       f32,',
    '  piNn:        f32,',
    '  E_SPREAD:    f32,',
    '  N_PERIODS:   f32,',
    '  Z:           f32,',
    '  _pad0:       f32,',
    '  _pad1:       f32,',
    '  _pad2:       f32,',
    '  n:           i32,',
    '  nTh:         u32,',
    '  nA:          u32,',
    '  nE_emit:     u32,',
    '  ab_start:    u32,',
    '  ab_end:      u32,',
    '  zero_scratch: u32,',
    '  _ipad0:      u32,',
    '};',
    '',
    '@group(0) @binding(0) var<uniform>             params     : Params;',
    '@group(0) @binding(1) var<storage, read>       emit_x     : array<vec2<f32>>;',
    '@group(0) @binding(2) var<storage, read>       emit_y     : array<vec2<f32>>;',
    '@group(0) @binding(3) var<storage, read>       emit_d     : array<vec2<f32>>;',
    '@group(0) @binding(4) var<storage, read_write> G_xy       : array<f32>;',
    '@group(0) @binding(5) var<storage, read>       bessel_lut : array<f32>;',
    '',
    'const LUT_N_ROWS: i32 = ' + lutN + ';',
    'const LUT_NX:     i32 = ' + lutNX + ';',
    'const LUT_DX:     f32 = ' + lutDx.toFixed(8) + ';',
    'const LUT_INV_DX: f32 = ' + (1.0 / lutDx).toFixed(8) + ';',
    'const LUT_X_UPPER: f32 = ' + lutXup.toFixed(8) + ';',
    '',
    '// Taylor-series besselJ fallback (NaN-safe for x<0).',
    'fn besselJ_series(nh: i32, x: f32) -> f32 {',
    '  if (abs(x) < 1.0e-10) {',
    '    if (nh == 0) { return 1.0; }',
    '    return 0.0;',
    '  }',
    '  let half_x  = x * 0.5;',
    '  let half_x2 = half_x * half_x;',
    '  var t0: f32 = 1.0;',
    '  for (var k: i32 = 0; k < nh; k = k + 1) { t0 = t0 * half_x; }',
    '  for (var k: i32 = 1; k <= nh; k = k + 1) { t0 = t0 / f32(k); }',
    '  var t: f32 = t0;',
    '  var s: f32 = t;',
    '  for (var m: i32 = 1; m < ' + bessCap + '; m = m + 1) {',
    '    t = -t * half_x2 / (f32(m) * f32(m + nh));',
    '    s = s + t;',
    '    if (abs(t) < 1.0e-15 * max(abs(s), 1.0e-30)) { break; }',
    '  }',
    '  return s;',
    '}',
    '',
    'fn besselJ(nh: i32, x: f32) -> f32 {',
    '  if (nh < 0 || nh >= LUT_N_ROWS) { return besselJ_series(nh, x); }',
    '  var sign: f32 = 1.0;',
    '  var ax = x;',
    '  if (x < 0.0) {',
    '    ax = -x;',
    '    if ((nh & 1) == 1) { sign = -1.0; }',
    '  }',
    '  if (ax > LUT_X_UPPER) { return besselJ_series(nh, x); }',
    '  if (nh >= 8 && ax < 1.0) { return besselJ_series(nh, x); }',
    '  let r = ax * LUT_INV_DX;',
    '  var ki = i32(floor(r));',
    '  if (ki >= LUT_NX - 1) { ki = LUT_NX - 2; }',
    '  if (ki < 0)           { ki = 0; }',
    '  let f = r - f32(ki);',
    '  let base = nh * LUT_NX;',
    '  let v0 = bessel_lut[base + ki];',
    '  let v1 = bessel_lut[base + ki + 1];',
    '  return sign * (v0 * (1.0 - f) + v1 * f);',
    '}',
    '',
    'fn jnS(m: i32, x: f32) -> f32 {',
    '  if (m >= 0) { return besselJ(m, x); }',
    '  let am = -m;',
    '  var sign: f32 = 1.0;',
    '  if ((am & 1) == 1) { sign = -1.0; }',
    '  return sign * besselJ(am, x);',
    '}',
    '',
    'fn cdiv(a: i32, b: i32) -> i32 {',
    '  let q  = i32(floor(f32(abs(a)) / f32(abs(b))));',
    '  let s1 = a < 0;',
    '  let s2 = b < 0;',
    '  if (s1 != s2) { return -q; }',
    '  return q;',
    '}',
    '',
    '// |fxy|^2 angle-dependent amplitude (planar undulator).',
    'fn fLinFxy2(K: f32, nh: i32, gt: f32, phi: f32) -> f32 {',
    '  let gsi: f32 = f32(nh) / (1.0 + K * K * 0.5 + gt * gt);',
    '  let z:   f32 = K * K * gsi * 0.25;',
    '  let u:   f32 = cos(phi);',
    '  let v:   f32 = sin(phi);',
    '  let x:   f32 = 2.0 * gt * K * gsi * u;',
    '  let INF: f32 = 1.0e-30;',
    '  var fx0: f32 = 0.0;',
    '  var fy0: f32 = 0.0;',
    '  if (abs(x) > 1.0e-3) {',
    '    var s1: f32   = INF;',
    '    var s2: f32   = INF;',
    '    var ssum: f32 = INF;',
    '    var ds1a: f32 = s1;',
    '    for (var m: i32 = 1; m < 200; m = m + 1) {',
    '      let ia = cdiv(2 * m - 1 - nh, 2);',
    '      let ib = cdiv(-2 * m + 1 - nh, 2);',
    '      let bjz1 = jnS(ia, z);',
    '      let bjz2 = jnS(ib, z);',
    '      let nn   = 2 * m - 1;',
    '      let bjx  = jnS(nn, x);',
    '      let ds1  = bjx * (bjz1 - bjz2);',
    '      let ds2  = bjx * (f32(ia) * bjz1 - f32(ib) * bjz2);',
    '      s1 = s1 + ds1;',
    '      s2 = s2 + ds2;',
    '      let dssum = abs(bjx) + abs(bjz1) + abs(bjz2);',
    '      ssum = ssum + abs(dssum);',
    '      var fds = (dssum + ds1a) / ssum;',
    '      ds1a = dssum;',
    '      fds = max(fds, abs(ds1 / (s1 + INF)));',
    '      fds = max(fds, abs(ds2 / (s2 + INF)));',
    '      if (fds <= 1.0e-9) { break; }',
    '    }',
    '    let gt_safe = select(1.0, gt, abs(gt) > 1.0e-30);',
    '    let u_safe  = select(1.0, u,  abs(u)  > 1.0e-30);',
    '    fx0 = -(f32(nh) * s1 + 2.0 * s2) / gt_safe / u_safe + 2.0 * gt * gsi * s1 * u;',
    '    fy0 =  2.0 * s1 * gt * v * gsi;',
    '  } else {',
    '    let naa = cdiv(-nh - 1, 2);',
    '    let nbb = cdiv(-nh + 1, 2);',
    '    let s1n = jnS(1, x) * (jnS(nbb, z) - jnS(naa, z));',
    '    let s2n = jnS(naa, z) + jnS(nbb, z);',
    '    fx0 = gsi * (2.0 * s1n * gt * u - K * s2n);',
    '    fy0 = 2.0 * gsi * s1n * gt * v;',
    '  }',
    '  return fx0 * fx0 + fy0 * fy0;',
    '}',
    '',
    '// --- Pass: accumulate G_xy(theta_x, theta_y) over a SUB-RANGE of (a, b). ---',
    '@compute @workgroup_size(' + wgX + ', ' + wgY + ', 1)',
    'fn div_accum(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let ix = gid.x;',
    '  let iy = gid.y;',
    '  if (ix >= params.nTh || iy >= params.nTh) { return; }',
    '',
    '  let nTh_f = f32(params.nTh);',
    '  let Ox: f32 = -params.halfTheta + f32(ix) * params.dTh;',
    '  let Oy: f32 = -params.halfTheta + f32(iy) * params.dTh;',
    '',
    '  let cellIdx: u32 = ix * params.nTh + iy;',
    '  if (params.zero_scratch == 1u) { G_xy[cellIdx] = 0.0; }',
    '',
    '  let nh = params.n;',
    '  let H_param = params.H;',
    '  let g2 = params.GAMMA_E * params.GAMMA_E;',
    '',
    '  var acc: f32 = 0.0;',
    '',
    '  let ab_lo = params.ab_start;',
    '  let ab_hi = params.ab_end;',
    '  for (var ab: u32 = ab_lo; ab < ab_hi; ab = ab + 1u) {',
    '    let a = ab / params.nA;',
    '    let b = ab - a * params.nA;',
    '    let ex   = emit_x[a];',
    '    let thx  = ex.x;',
    '    let wx   = ex.y;',
    '    let ey   = emit_y[b];',
    '    let thy  = ey.x;',
    '    let wy   = ey.y;',
    '    let psix = Ox - thx;',
    '    let psiy = Oy - thy;',
    '    let psi2 = psix * psix + psiy * psiy;',
    '    let gt   = params.GAMMA_E * sqrt(psi2);',
    '    let amp  = fLinFxy2(params.K, nh, gt, atan2(psiy, psix));',
    '    let wab  = wx * wy;',
    '    let r2   = psi2 / params.f4;',
    '    for (var id: u32 = 0u; id < params.nE_emit; id = id + 1u) {',
    '      let ed    = emit_d[id];',
    '      let delta = ed.x;',
    '      let wd    = ed.y;',
    '      let xs    = 3.141592653589793 * (r2 - params.twoNN * delta);',
    '      var sc2: f32;',
    '      if (xs > -1.0e-9 && xs < 1.0e-9) {',
    '        sc2 = 1.0;',
    '      } else {',
    '        let s_ = sin(xs) / xs;',
    '        sc2 = s_ * s_;',
    '      }',
    '      acc = acc + amp * wab * wd * sc2;',
    '    }',
    '  }',
    '  G_xy[cellIdx] = G_xy[cellIdx] + acc;',
    '}',
    ''
  ].join('\n');
  return src;
}


// ===========================================================================
// Pipeline + buffer setup (cached per device + kernel key + buffer shape).
// ===========================================================================
function _dgEnsurePipelines(device) {
  var kernelKey = DG_WG_X + 'x' + DG_WG_Y + '_th' + DG_N_THETA +
                  '_cov' + DG_THETA_SIGMA_NX +
                  '_em' + DG_N_EMIT + '_es' + DG_N_ESPREAD +
                  '_bess' + DG_BESSEL_MAX_ITER +
                  '_lut' + DG_LUT_N_ROWS + 'x' + DG_LUT_NX +
                  '_dx' + DG_LUT_DX + '_v3';
  if (_dgPipelineCache.device === device &&
      _dgPipelineCache.kernelKey === kernelKey &&
      _dgPipelineCache.pipelineAccum) {
    return;
  }
  _dgPipelineCache.device = device;
  _dgPipelineCache.kernelKey = kernelKey;
  _dgPipelineCache.bufferKey = '';
  _dgPipelineCache.buffers = null;

  var src = _dgBuildShaderWGSL();
  var mod = device.createShaderModule({ code: src });
  _dgPipelineCache.module = mod;

  var bgl = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 5, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } }
    ]
  });
  _dgPipelineCache.bindGroupLayout = bgl;

  var layout = device.createPipelineLayout({ bindGroupLayouts: [bgl] });
  _dgPipelineCache.layout = layout;

  _dgPipelineCache.pipelineAccum = device.createComputePipeline({
    layout: layout,
    compute: { module: mod, entryPoint: 'div_accum' }
  });
}


function _dgEnsureBuffers(device, prep) {
  var key = prep.nTh + '_' + prep.nA + '_' + prep.nE_emit;
  if (_dgPipelineCache.bufferKey === key && _dgPipelineCache.buffers) {
    return _dgPipelineCache.buffers;
  }
  if (_dgPipelineCache.buffers) {
    var old = _dgPipelineCache.buffers;
    try { old.params.destroy();     } catch (e) {}
    try { old.emit_x.destroy();     } catch (e) {}
    try { old.emit_y.destroy();     } catch (e) {}
    try { old.emit_d.destroy();     } catch (e) {}
    try { old.G_xy.destroy();       } catch (e) {}
    try { old.readback.destroy();   } catch (e) {}
    try { old.bessel_lut.destroy(); } catch (e) {}
  }

  var gxyBytes = prep.nTh * prep.nTh * 4;
  var bufs = {
    params: device.createBuffer({
      size: 96,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST
    }),
    emit_x: device.createBuffer({
      size: prep.nA * 2 * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
    }),
    emit_y: device.createBuffer({
      size: prep.nA * 2 * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
    }),
    emit_d: device.createBuffer({
      size: prep.nE_emit * 2 * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
    }),
    G_xy: device.createBuffer({
      size: gxyBytes,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC
    }),
    readback: device.createBuffer({
      size: gxyBytes,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
    }),
    bessel_lut: device.createBuffer({
      size: DG_LUT_N_ROWS * DG_LUT_NX * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
    })
  };

  bufs.bindGroup = device.createBindGroup({
    layout: _dgPipelineCache.bindGroupLayout,
    entries: [
      { binding: 0, resource: { buffer: bufs.params } },
      { binding: 1, resource: { buffer: bufs.emit_x } },
      { binding: 2, resource: { buffer: bufs.emit_y } },
      { binding: 3, resource: { buffer: bufs.emit_d } },
      { binding: 4, resource: { buffer: bufs.G_xy } },
      { binding: 5, resource: { buffer: bufs.bessel_lut } }
    ]
  });

  _dgPipelineCache.bufferKey = key;
  _dgPipelineCache.buffers = bufs;
  return bufs;
}


// Patch uniform copy with new ab_start / ab_end / zero_scratch.
function _dgPatchAbRange(baseBytes, ab_start, ab_end, zero_scratch) {
  var copy = new Uint8Array(96);
  copy.set(baseBytes);
  var view = new DataView(copy.buffer);
  // Integer block at offset 64: ui[4]=ab_start, ui[5]=ab_end, ui[6]=zero_scratch.
  view.setUint32(64 + 4 * 4, ab_start | 0,    true);
  view.setUint32(64 + 5 * 4, ab_end | 0,      true);
  view.setUint32(64 + 6 * 4, zero_scratch | 0, true);
  return copy;
}


// Host-side reduction: G_xy -> marginals -> centroid-corrected rms in urad.
function _dgReduceMoments(G_xy, nTh, halfTheta, dTh) {
  // Px[ix] = sum_iy G_xy[ix, iy];  Py[iy] = sum_ix G_xy[ix, iy].
  var Px = new Float64Array(nTh);
  var Py = new Float64Array(nTh);
  var ix, iy, v;
  for (ix = 0; ix < nTh; ix++) {
    for (iy = 0; iy < nTh; iy++) {
      v = G_xy[ix * nTh + iy];
      Px[ix] += v;
      Py[iy] += v;
    }
  }
  function rms(P) {
    var sw = 0, sxw = 0, sx2w = 0, k, th;
    for (k = 0; k < nTh; k++) {
      th = -halfTheta + k * dTh;
      sw   += P[k];
      sxw  += th * P[k];
      sx2w += th * th * P[k];
    }
    if (sw <= 0) return 0;
    var mean = sxw / sw;
    var var2 = sx2w / sw - mean * mean;
    if (var2 < 0) var2 = 0;
    return Math.sqrt(var2);
  }
  var sxp_rad = rms(Px);
  var syp_rad = rms(Py);
  return { Sxp_urad: sxp_rad * 1e6, Syp_urad: syp_rad * 1e6 };
}


// ===========================================================================
// Public API: divergenceGPU(K, n, Z) -> Promise<{Sxp_urad, Syp_urad, tier}>
// ===========================================================================
function divergenceGPU(K, n, Z) {
  if (Z === undefined || Z === null || isNaN(Z)) Z = 30.0;
  if (typeof detectWebGPU !== 'function') {
    return Promise.reject(new Error('02_webgpu_detect.js not loaded (detectWebGPU undefined)'));
  }

  function _run() {
    if (!window._GPU || !window._GPU.device) {
      return Promise.reject(new Error('WebGPU device unavailable'));
    }
    var device = window._GPU.device;
    var prep = _dgPrepareInputs(K, n, Z);

    _dgEnsurePipelines(device);
    var bufs = _dgEnsureBuffers(device, prep);

    var lut = _dgBuildBesselLUT();
    device.queue.writeBuffer(bufs.emit_x,     0, prep.emit_x);
    device.queue.writeBuffer(bufs.emit_y,     0, prep.emit_y);
    device.queue.writeBuffer(bufs.emit_d,     0, prep.emit_d);
    device.queue.writeBuffer(bufs.bessel_lut, 0, lut);

    var wgX = Math.ceil(prep.nTh / DG_WG_X);
    var wgY = Math.ceil(prep.nTh / DG_WG_Y);
    var blocks = prep.abNumBlocks;
    var blockSize = prep.abBlockSize;
    var i, ab_start, ab_end, zero_flag, patched, enc, p1;

    for (i = 0; i < blocks; i++) {
      ab_start = i * blockSize;
      ab_end   = (i + 1) * blockSize;
      if (ab_end > prep.abPairs) ab_end = prep.abPairs;
      zero_flag = (i === 0) ? 1 : 0;

      patched = _dgPatchAbRange(prep.params, ab_start, ab_end, zero_flag);
      device.queue.writeBuffer(bufs.params, 0, patched);

      enc = device.createCommandEncoder();
      p1 = enc.beginComputePass();
      p1.setPipeline(_dgPipelineCache.pipelineAccum);
      p1.setBindGroup(0, bufs.bindGroup);
      p1.dispatchWorkgroups(wgX, wgY, 1);
      p1.end();
      device.queue.submit([enc.finish()]);
    }

    // Copy G_xy -> readback after all accumulate dispatches complete.
    var encR = device.createCommandEncoder();
    encR.copyBufferToBuffer(bufs.G_xy, 0, bufs.readback, 0, prep.nTh * prep.nTh * 4);
    device.queue.submit([encR.finish()]);

    return bufs.readback.mapAsync(GPUMapMode.READ).then(function () {
      var arr = new Float32Array(bufs.readback.getMappedRange().slice(0));
      bufs.readback.unmap();
      var mom = _dgReduceMoments(arr, prep.nTh, prep.halfTheta, prep.dTh);
      return {
        Sxp_urad: mom.Sxp_urad,
        Syp_urad: mom.Syp_urad,
        tier: '[gpu]'
      };
    });
  }

  if (!window._GPU || !window._GPU.device) {
    return detectWebGPU().then(_run);
  }
  return _run();
}


// ESM bridge: expose module-scoped functions to globalThis.
if (typeof divergenceGPU !== 'undefined') globalThis.divergenceGPU = divergenceGPU;
if (typeof _dgBuildShaderWGSL !== 'undefined') globalThis._dgBuildShaderWGSL = _dgBuildShaderWGSL;
if (typeof _dgBuildBesselLUT !== 'undefined') globalThis._dgBuildBesselLUT = _dgBuildBesselLUT;
if (typeof DG_WG_X !== 'undefined') globalThis.DG_WG_X = DG_WG_X;
if (typeof DG_WG_Y !== 'undefined') globalThis.DG_WG_Y = DG_WG_Y;
if (typeof DG_N_THETA !== 'undefined') globalThis.DG_N_THETA = DG_N_THETA;
if (typeof DG_THETA_SIGMA_NX !== 'undefined') globalThis.DG_THETA_SIGMA_NX = DG_THETA_SIGMA_NX;
if (typeof DG_N_EMIT !== 'undefined') globalThis.DG_N_EMIT = DG_N_EMIT;
if (typeof DG_N_ESPREAD !== 'undefined') globalThis.DG_N_ESPREAD = DG_N_ESPREAD;
if (typeof DG_AB_NUM_BLOCKS !== 'undefined') globalThis.DG_AB_NUM_BLOCKS = DG_AB_NUM_BLOCKS;
if (typeof DG_BESSEL_MAX_ITER !== 'undefined') globalThis.DG_BESSEL_MAX_ITER = DG_BESSEL_MAX_ITER;
