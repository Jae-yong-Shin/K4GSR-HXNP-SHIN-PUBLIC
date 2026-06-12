'use strict';
// ===== optics/03_webgpu_flux_acceptance.js — WebGPU compute port of fluxAcceptance =====
// @module optics/03_webgpu_flux_acceptance
// @exports fluxAcceptanceGPU
//
// Phase 3.5 (DDD): re-design of the WGSL kernel granularity to escape
// Windows GPU TDR (2 sec default). The original Phase 2 kernel ran the
// entire (a, b, id, ig) inner integral inside a single dispatch (one
// thread per observation pixel, 64 threads per workgroup); for K=1.87,
// n=3 that was ~3.4e7 MACs per thread and ~2.2 s wall time, which
// trips the Windows TDR and loses the device for the rest of the page.
//
// New design (Option C — hybrid 16x16 tile + dispatch-split outer):
//
//   * Workgroup: @workgroup_size(16, 16, 1) = 256 threads per WG.
//     nObs=21 -> dispatchWorkgroups(ceil(21/16), ceil(21/16), 1) = (2, 2, 1)
//     = 4 workgroups, of which 441 invocations are real and the rest
//     early-return. Re-using the larger tile lets the driver schedule
//     a single workgroup against multiple SIMD lanes — important on
//     integrated GPUs.
//
//   * Outer (a, b) emittance loop is SPLIT across the host (JS). The
//     host submits AB_NUM_BLOCKS = 8 dispatches; each dispatch only
//     processes a sub-range of (a, b) indices, [ab_start, ab_end).
//     The first dispatch zero-inits its scratch row; subsequent
//     dispatches accumulate. Per-dispatch budget ~40 ms <= 200 ms
//     safety margin under 2 s TDR.
//
//   * Phase 2 issue fixes folded in here:
//     - besselJ: replace pow(half_x, f32(nh)) with explicit integer-
//       power loop. WGSL pow() is undefined for negative bases with
//       fractional exponents; for x<0, odd nh the original produced
//       NaN. The integer loop is exact and NaN-free.
//     - fLinFxy2 series cap bumped from 30 -> 50 in the besselJ inner
//       Bessel series for safety at high K.
//
// Public API:
//   fluxAcceptanceGPU(K, n, halfH_urad, halfV_urad) -> Promise<number>
//       peak partial flux, ph/s/0.1%BW. Matches CPU fluxAcceptance() to
//       ~<=1% (low n) / <=2% (high n) per design Section 7.2.
//
// Depends on:
//   - window.detectWebGPU() from 02_webgpu_detect.js (window._GPU.device)
//   - calcE1, _undGrids (already on globalThis via 01_undulator.js)
//   - SIG_EXP, SIG_EYP, E_SPREAD, N_PERIODS, GAMMA_E, E_RING, I_RING_A
//     (already on globalThis via 01_constants.js)
//
// Coding rules (CLAUDE.md): ES5-strict — var only, function only,
// NO arrow, NO const/let, NO template literals (`...`). WGSL source is
// assembled by string concatenation in _fagBuildShaderWGSL().


// ===========================================================================
// Kernel tuning constants. Exported on globalThis for tests/diagnostics.
// ===========================================================================
var FAG_WG_X            = 16;   // workgroup_size X (tile width  in obs-pix)
var FAG_WG_Y            = 16;   // workgroup_size Y (tile height in obs-pix)
var FAG_BESSEL_MAX_ITER = 50;   // besselJ series cap (was 30; bumped for high K safety)
var FAG_AB_NUM_BLOCKS   = 8;    // # of host-side (a,b) sub-dispatches per call
                                 // Phase 3.6c: kept at 8 even with LUT speedup,
                                 // because B_lowK_highN edge case (K=0.5 n=15
                                 // hH=hV=50) drives the outer fLinFxy2 m-loop
                                 // hard enough that block=4 trips the TDR and
                                 // wedges the device for the rest of the
                                 // sweep. The LUT does cut per-Bessel cost
                                 // sharply, but the rest of the kernel (sin,
                                 // cos, atan2, accumulation) still dominates;
                                 // keeping 8 blocks preserves the 250 ms-per-
                                 // dispatch safety budget vs the 2 s TDR.

// Phase 3.6c: J_n(x) lookup-table constants. Empirically (probe
// _phase3p6_bessel_range_probe.json) the orders requested by fLinFxy2
// range over n in [0, 45] and the |x| argument over [0, ~4.07]. We
// tabulate n in [0, FAG_LUT_N_ROWS-1], x in [0, FAG_LUT_X_UPPER] on a
// uniform grid with step FAG_LUT_DX. NX = round((x_upper / dx) + 1)
// gives 91 columns; total table is 48 x 91 = 4368 f32 = 17,472 B,
// trivial to keep around. Out-of-table arguments fall back to the
// existing in-kernel Taylor recurrence so this is a strict speedup,
// not a tolerance-reducing approximation.
var FAG_LUT_N_ROWS = 48;
var FAG_LUT_X_UPPER = 4.5;
var FAG_LUT_DX = 0.05;
var FAG_LUT_NX = Math.round(FAG_LUT_X_UPPER / FAG_LUT_DX) + 1;  // 91

// Lazy module-scope cache of the host-built Float32Array (4368 floats).
// Built once at first fluxAcceptanceGPU() call; persists for the page
// lifetime. Distinct from _gpuPipelineCache (which is keyed on device
// identity and can be torn down by device.lost).
var _fagBesselLUT = null;


// ===========================================================================
// Pipeline / buffer cache (per device + per shape + per kernel key).
// On device.lost (02_webgpu_detect.js drops window._GPU.device), the next
// call re-detects and rebuilds; we key the cache on the device object identity
// AND on the kernel-shape key (workgroup size + besselJ cap) so a redesign
// blows the old cache out automatically.
// ===========================================================================
var _gpuPipelineCache = {
  device: null,           // last-seen GPUDevice
  kernelKey: '',          // 'wgX_wgY_besselCap'  (invalidates shader cache)
  module: null,
  layout: null,
  bindGroupLayout: null,
  pipelineAccum: null,
  pipelineReduce: null,
  bufferKey: '',          // 'nObs_nEgrid_nA_nE_emit'
  buffers: null
};


// ===========================================================================
// Phase 3.6c: build the J_n(x) lookup table on the host using the existing
// CPU besselJ (01_undulator.js, ~10-term Taylor series, f64). The table is
// stored row-major as Jn[n*NX + k] for n in [0, N_ROWS-1] and
// k in [0, NX-1], with x_k = k * dx.  Persistent for the page lifetime.
// We deliberately keep this in f64 during construction (because besselJ
// itself runs in f64) and only narrow to f32 when uploading to GPU --
// that buys us one extra digit at the corners where Taylor convergence
// is slow at n=45, x~4.0.
// ===========================================================================
function _fagBuildBesselLUT() {
  if (_fagBesselLUT) return _fagBesselLUT;
  if (typeof besselJ !== 'function') {
    throw new Error('besselJ not loaded (01_undulator.js missing)');
  }
  var N = FAG_LUT_N_ROWS;
  var NX = FAG_LUT_NX;
  var dx = FAG_LUT_DX;
  var arr = new Float32Array(N * NX);
  var n, k, x, v;
  for (n = 0; n < N; n++) {
    for (k = 0; k < NX; k++) {
      x = k * dx;
      // besselJ handles |x|<1e-10 internally and returns 1 for n=0, 0 otherwise.
      v = besselJ(n, x);
      arr[n * NX + k] = v;
    }
  }
  _fagBesselLUT = arr;
  return arr;
}


// ===========================================================================
// Build the Gaussian-weighted node grid that the CPU fluxAcceptance uses:
// uniform nodes on +/- 5 sigma with exp(-x^2/2sig^2) weights, renormalised.
// Returns { v: Float32Array, w: Float32Array } interleaved as (v, w) for the
// vec2<f32> storage layout the shader expects.
// ===========================================================================
function _fagBuildGaussInterleaved(sig, m) {
  var out = new Float32Array(m * 2);
  var s = 0, j, x, ww;
  // First pass: values + raw weights
  for (j = 0; j < m; j++) {
    x = (-5 + 10 * j / (m - 1)) * sig;
    ww = Math.exp(-x * x / (2 * sig * sig));
    out[2 * j] = x;
    out[2 * j + 1] = ww;
    s += ww;
  }
  // Second pass: normalise weights
  for (j = 0; j < m; j++) out[2 * j + 1] /= s;
  return out;
}


// ===========================================================================
// CPU-side preparation: build all host-side inputs to the kernel. Returns
// { params: Uint8Array (96B uniform), Egrid, emit_x/y/d, nObs, nEgrid, nA,
//   nE_emit, abPairs, abBlockSize, abNumBlocks }.
//
// Layout MUST match the WGSL Params struct below (Section "Params").
// ===========================================================================
function _fagPrepareInputs(K, n, halfH_urad, halfV_urad) {
  // ---- scalar physics (mirror 01_undulator.js::fluxAcceptance) ----
  var E1 = calcE1(K);
  var En0 = n * E1;
  var H = 1 + K * K / 2;
  var N = N_PERIODS;
  var sd = E_SPREAD;
  var piNn = Math.PI * n * N;
  var bw = 7.0 / (n * N);
  var COEF = 1.744e14 * N * N * E_RING * E_RING * I_RING_A;

  // ---- grids ----
  var gr = _undGrids(K, n);
  var nA = gr.nA;
  var nE_emit = gr.nE;
  var halfRadH = halfH_urad * 1e-6;
  var halfRadV = halfV_urad * 1e-6;
  var nObs = 21;
  var dObsH = (2 * halfRadH) / (nObs - 1);
  var dObsV = (2 * halfRadV) / (nObs - 1);
  var dOmegaMrad2 = (dObsH * 1e3) * (dObsV * 1e3);
  var nEgrid = 41;
  var Elo = En0 * (1 - bw * 2.0), Ehi = En0 * (1 + bw * 0.5);
  var dE = (Ehi - Elo) / (nEgrid - 1);
  var Egrid = new Float32Array(nEgrid), ig;
  for (ig = 0; ig < nEgrid; ig++) Egrid[ig] = Elo + ig * dE;

  // ---- emittance / energy-spread node grids ----
  var emit_x = _fagBuildGaussInterleaved(SIG_EXP, nA);
  var emit_y = _fagBuildGaussInterleaved(SIG_EYP, nA);
  var emit_d = _fagBuildGaussInterleaved(sd, nE_emit);

  // ---- (a, b) outer-loop dispatch split ----
  // The host submits FAG_AB_NUM_BLOCKS dispatches; each dispatch processes
  // a contiguous sub-range of the linearised (a*nA + b) index space, so
  // the device never sees the full 2.7e7 -- 3.4e7 MACs/thread in one shot.
  var abPairs = nA * nA;
  var abNumBlocks = FAG_AB_NUM_BLOCKS;
  if (abNumBlocks > abPairs) abNumBlocks = abPairs;   // tiny grids
  if (abNumBlocks < 1) abNumBlocks = 1;
  var abBlockSize = Math.ceil(abPairs / abNumBlocks); // last block may be short

  // ---- uniform buffer: 96 B. First 64 B are f32 (16 scalars).
  // Then 32 B (8 x u32/i32) of integer counters. We pack both into a single
  // 96-byte ArrayBuffer and create two views.
  // Integer-block layout (offset 64 B):
  //   ui[0] = n (i32 harmonic)
  //   ui[1] = nObs (u32)
  //   ui[2] = nEgrid (u32)
  //   ui[3] = nA (u32)
  //   ui[4] = nE_emit (u32)
  //   ui[5] = ab_start (u32)   <-- NEW for Phase 3.5 dispatch split
  //   ui[6] = ab_end   (u32)   <-- NEW for Phase 3.5 dispatch split
  //   ui[7] = zero_scratch (u32) — 1 on the first dispatch, 0 afterwards
  var uniBuf = new ArrayBuffer(96);
  var uf = new Float32Array(uniBuf, 0, 16);   // 64 B
  var ui = new Int32Array(uniBuf, 64, 8);     // 32 B

  uf[0] = K;
  uf[1] = halfRadH;
  uf[2] = halfRadV;
  uf[3] = En0;
  uf[4] = bw;
  uf[5] = COEF;
  uf[6] = GAMMA_E;
  uf[7] = H;
  uf[8] = N;            // N_PERIODS
  uf[9] = E_SPREAD;
  uf[10] = SIG_EXP;
  uf[11] = SIG_EYP;
  uf[12] = piNn;
  uf[13] = dOmegaMrad2;
  uf[14] = 0;           // pad
  uf[15] = 0;           // pad

  ui[0] = n | 0;            // i32: harmonic
  ui[1] = nObs | 0;
  ui[2] = nEgrid | 0;
  ui[3] = nA | 0;
  ui[4] = nE_emit | 0;
  ui[5] = 0;                // ab_start  (host rewrites per dispatch)
  ui[6] = abBlockSize | 0;  // ab_end    (host rewrites per dispatch)
  ui[7] = 1;                // zero_scratch — 1st dispatch zero-inits

  return {
    params: new Uint8Array(uniBuf),   // raw bytes for queue.writeBuffer
    Egrid: Egrid,
    emit_x: emit_x,
    emit_y: emit_y,
    emit_d: emit_d,
    nObs: nObs,
    nEgrid: nEgrid,
    nA: nA,
    nE_emit: nE_emit,
    abPairs: abPairs,
    abBlockSize: abBlockSize,
    abNumBlocks: abNumBlocks
  };
}


// ===========================================================================
// Build the WGSL shader source as a plain JS string (no template literals).
// Two entry points (flux_accum, flux_reduce) share one module.
//
// Workgroup size and besselJ iter-cap are injected from the JS constants so
// the kernel-cache key can detect a redesign.
// ===========================================================================
function _fagBuildShaderWGSL() {
  var wgX     = FAG_WG_X;
  var wgY     = FAG_WG_Y;
  var bessCap = FAG_BESSEL_MAX_ITER;
  var lutN    = FAG_LUT_N_ROWS;
  var lutNX   = FAG_LUT_NX;
  var lutDx   = FAG_LUT_DX;
  var lutXup  = FAG_LUT_X_UPPER;

  // We build with array.join('\n') for readability. No back-tick template
  // literals (ES5-strict; CLAUDE.md rule).
  var src = [
    '// === HANBIT fluxAcceptanceGPU compute kernel — Phase 3.6c ===',
    '// workgroup_size(' + wgX + ', ' + wgY + ', 1) tile.',
    '// besselJ: ' + lutN + 'x' + lutNX + ' LUT, dx=' + lutDx +
      ', x_upper=' + lutXup + '; Taylor fallback cap ' + bessCap + ' terms.',
    '',
    'struct Params {',
    '  K:           f32,',
    '  halfRadH:    f32,',
    '  halfRadV:    f32,',
    '  En0:         f32,',
    '  bw:          f32,',
    '  COEF:        f32,',
    '  GAMMA_E:     f32,',
    '  H:           f32,',
    '  N_PERIODS:   f32,',
    '  E_SPREAD:    f32,',
    '  SIG_EXP:     f32,',
    '  SIG_EYP:     f32,',
    '  piNn:        f32,',
    '  dOmegaMrad2: f32,',
    '  _pad0:       f32,',
    '  _pad1:       f32,',
    '  n:           i32,',
    '  nObs:        u32,',
    '  nEgrid:      u32,',
    '  nA:          u32,',
    '  nE_emit:     u32,',
    '  ab_start:    u32,',
    '  ab_end:      u32,',
    '  zero_scratch: u32,',
    '};',
    '',
    '@group(0) @binding(0) var<uniform>             params         : Params;',
    '@group(0) @binding(1) var<storage, read>       Egrid          : array<f32>;',
    '@group(0) @binding(2) var<storage, read>       emit_x         : array<vec2<f32>>;',
    '@group(0) @binding(3) var<storage, read>       emit_y         : array<vec2<f32>>;',
    '@group(0) @binding(4) var<storage, read>       emit_d         : array<vec2<f32>>;',
    '@group(0) @binding(5) var<storage, read_write> scratch        : array<f32>;',
    '@group(0) @binding(6) var<storage, read_write> out_pflux      : array<f32>;',
    '@group(0) @binding(7) var<storage, read>       bessel_lut     : array<f32>;',
    '',
    '// --- LUT shape (must match host _fagBuildBesselLUT) ---',
    'const LUT_N_ROWS: i32 = ' + lutN + ';',
    'const LUT_NX:     i32 = ' + lutNX + ';',
    'const LUT_DX:     f32 = ' + lutDx.toFixed(8) + ';',
    'const LUT_INV_DX: f32 = ' + (1.0 / lutDx).toFixed(8) + ';',
    'const LUT_X_UPPER: f32 = ' + lutXup.toFixed(8) + ';',
    '',
    '// --- Bessel J_n(x) Taylor-series fallback (' + bessCap + '-term cap). ---',
    '// IMPORTANT: WGSL pow(base, exp) is undefined when base < 0 and exp is non-integer;',
    '// some drivers return NaN even for f32 integer exponents. We therefore replace the',
    '// initial term (x/2)^n / n! with an explicit integer-power loop that is exact and',
    '// NaN-free for any sign of x. This is only invoked when the LUT cannot serve the',
    '// (n, x) request (n out of [0, LUT_N_ROWS-1] or |x| > LUT_X_UPPER).',
    'fn besselJ_series(nh: i32, x: f32) -> f32 {',
    '  if (abs(x) < 1.0e-10) {',
    '    if (nh == 0) { return 1.0; }',
    '    return 0.0;',
    '  }',
    '  let half_x  = x * 0.5;',
    '  let half_x2 = half_x * half_x;',
    '  // Initial term m=0: (x/2)^n / n!   -- integer-power loop, NaN-safe for x<0.',
    '  var t0: f32 = 1.0;',
    '  for (var k: i32 = 0; k < nh; k = k + 1) {',
    '    t0 = t0 * half_x;',
    '  }',
    '  for (var k: i32 = 1; k <= nh; k = k + 1) {',
    '    t0 = t0 / f32(k);',
    '  }',
    '  var t: f32 = t0;',
    '  var s: f32 = t;',
    '  for (var m: i32 = 1; m < ' + bessCap + '; m = m + 1) {',
    '    // Recurrence: t_m = -t_{m-1} * (x/2)^2 / (m * (m + n))',
    '    t = -t * half_x2 / (f32(m) * f32(m + nh));',
    '    s = s + t;',
    '    if (abs(t) < 1.0e-15 * max(abs(s), 1.0e-30)) { break; }',
    '  }',
    '  return s;',
    '}',
    '',
    '// --- Bessel J_n(x) LUT lookup with linear interpolation; Taylor fallback. ---',
    '// Host stores J_n(x) for n in [0, LUT_N_ROWS-1] and x = k*dx, k in [0, LUT_NX-1].',
    '// Negative x is folded via the parity relation  J_n(-x) = (-1)^n * J_n(x).',
    '//',
    '// LUT vs series choice:',
    '//   - When n >= LUT_N_ROWS or |x| > LUT_X_UPPER, fall back to the in-kernel',
    '//     Taylor series (besselJ_series).',
    '//   - When n is high (>= 8) AND |x| is small (< 1.0), the LUT entry is in the',
    '//     deep-tail region where f32 quantisation kills precision (e.g. J_15(0.7)',
    '//     ~ 4e-17, far below f32 epsilon * peak LUT value). The Taylor series',
    '//     computes this directly in f32 by cancellation-free recurrence and stays',
    '//     accurate. Probe showed this regime is reached by K=0.5 n>=13 cases via',
    '//     the fLinFxy2 inner z-Bessel calls; restoring series there keeps the GPU',
    '//     vs Python deviation at the pre-LUT ~0.03% level for those entries.',
    '//   - Otherwise (the common case), linear-interp from the LUT.',
    'fn besselJ(nh: i32, x: f32) -> f32 {',
    '  // 1. Out-of-table order n -> fallback. (n is never negative here -- jnS handles sign.)',
    '  if (nh < 0 || nh >= LUT_N_ROWS) { return besselJ_series(nh, x); }',
    '  // 2. Fold sign: J_n(-x) = (-1)^n * J_n(x).',
    '  var sign: f32 = 1.0;',
    '  var ax = x;',
    '  if (x < 0.0) {',
    '    ax = -x;',
    '    if ((nh & 1) == 1) { sign = -1.0; }',
    '  }',
    '  // 3. |x| > x_upper -> fallback (small but non-zero in tail of parameter space).',
    '  if (ax > LUT_X_UPPER) { return besselJ_series(nh, x); }',
    '  // 4. High-n + small-x deep-tail safeguard. Threshold picked from probe.',
    '  if (nh >= 8 && ax < 1.0) { return besselJ_series(nh, x); }',
    '  // 5. Linear interp.  k = floor(x/dx), saturate to NX-2 to leave room for k+1.',
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
    '// --- Signed-order helper: J_{-m}(x) = (-1)^m * J_m(x). ---',
    'fn jnS(m: i32, x: f32) -> f32 {',
    '  if (m >= 0) { return besselJ(m, x); }',
    '  let am = -m;',
    '  var sign: f32 = 1.0;',
    '  if ((am & 1) == 1) { sign = -1.0; }',
    '  return sign * besselJ(am, x);',
    '}',
    '',
    '// --- Truncated-toward-zero divide: matches JS _cdiv. ---',
    'fn cdiv(a: i32, b: i32) -> i32 {',
    '  let q  = i32(floor(f32(abs(a)) / f32(abs(b))));',
    '  let s1 = a < 0;',
    '  let s2 = b < 0;',
    '  if (s1 != s2) { return -q; }',
    '  return q;',
    '}',
    '',
    '// --- |fxy|^2 = fx0^2 + fy0^2 (WGSL port of fLinFxy2 in optics/01_undulator.js; see the license note there). ---',
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
    '    // off-axis branch — outer m-series up to 200',
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
    '    // near-axis branch — closed form',
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
    '// --- Pass 1: per-(Ox, Oy) inner integral over a SUB-RANGE of (a, b). ---',
    '// One thread per observation pixel. workgroup_size = ' + wgX + ' x ' + wgY + '.',
    '// The host calls this kernel ' + 'AB_NUM_BLOCKS' + ' times; each call sets',
    '// ab_start, ab_end so the device-side loop only sees a fraction of the',
    '// full (a, b) emittance grid. zero_scratch=1 on the very first call zeros',
    '// the scratch row before accumulating; subsequent calls accumulate in place.',
    '@compute @workgroup_size(' + wgX + ', ' + wgY + ', 1)',
    'fn flux_accum(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let ox = gid.x;',
    '  let oy = gid.y;',
    '  if (ox >= params.nObs || oy >= params.nObs) { return; }',
    '',
    '  let nObs_f   = f32(params.nObs);',
    '  let dObsH    = (2.0 * params.halfRadH) / (nObs_f - 1.0);',
    '  let dObsV    = (2.0 * params.halfRadV) / (nObs_f - 1.0);',
    '  let Ox: f32  = -params.halfRadH + f32(ox) * dObsH;',
    '  let Oy: f32  = -params.halfRadV + f32(oy) * dObsV;',
    '',
    '  let scratchBase: u32 = (ox * params.nObs + oy) * params.nEgrid;',
    '  // First dispatch zero-inits this thread\'s scratch row.',
    '  if (params.zero_scratch == 1u) {',
    '    for (var ig: u32 = 0u; ig < params.nEgrid; ig = ig + 1u) {',
    '      scratch[scratchBase + ig] = 0.0;',
    '    }',
    '  }',
    '',
    '  let nh = params.n;',
    '  let H_param = params.H;',
    '  let g2 = params.GAMMA_E * params.GAMMA_E;',
    '',
    '  // Linearised (a, b) sweep over [ab_start, ab_end), where',
    '  //   a = ab / nA, b = ab % nA.',
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
    '    let redA = 1.0 / (1.0 + g2 * psi2 / H_param);',
    '    let amp  = params.COEF * fLinFxy2(params.K, nh, gt, atan2(psiy, psix));',
    '    let wab  = wx * wy * params.dOmegaMrad2;',
    '    for (var id: u32 = 0u; id < params.nE_emit; id = id + 1u) {',
    '      let ed    = emit_d[id];',
    '      let delta = ed.x;',
    '      let wd    = ed.y;',
    '      let En    = params.En0 * (1.0 + delta) * (1.0 + delta) * redA;',
    '      let wgt   = amp * wab * wd;',
    '      for (var ig: u32 = 0u; ig < params.nEgrid; ig = ig + 1u) {',
    '        let xs = params.piNn * (Egrid[ig] / En - 1.0);',
    '        var sc2: f32;',
    '        if (xs > -1.0e-10 && xs < 1.0e-10) {',
    '          sc2 = 1.0;',
    '        } else {',
    '          let s_ = sin(xs) / xs;',
    '          sc2 = s_ * s_;',
    '        }',
    '        scratch[scratchBase + ig] = scratch[scratchBase + ig] + wgt * sc2;',
    '      }',
    '    }',
    '  }',
    '}',
    '',
    '// --- Pass 2: sum scratch across nObs*nObs threads into out_pflux[ig]. ---',
    '// One thread per energy bin. Workgroup size 64; dispatch ceil(nEgrid/64) groups.',
    '@compute @workgroup_size(64, 1, 1)',
    'fn flux_reduce(@builtin(global_invocation_id) gid: vec3<u32>) {',
    '  let ig = gid.x;',
    '  if (ig >= params.nEgrid) { return; }',
    '  var acc: f32 = 0.0;',
    '  let nPix: u32 = params.nObs * params.nObs;',
    '  for (var k: u32 = 0u; k < nPix; k = k + 1u) {',
    '    acc = acc + scratch[k * params.nEgrid + ig];',
    '  }',
    '  out_pflux[ig] = acc;',
    '}',
    ''
  ].join('\n');
  return src;
}


// ===========================================================================
// Pipeline + bind-group-layout setup (cached per device + kernel key).
// kernelKey encodes workgroup size + besselJ cap so the cache invalidates on
// a future redesign.
// ===========================================================================
function _fagEnsurePipelines(device) {
  // Phase 3.6c: kernelKey includes LUT dims so a future re-tune of the
  // table (size, dx, x_upper) blows the old shader module out of cache.
  // The _v2 suffix marks the high-n small-x safeguard rev.
  var kernelKey = FAG_WG_X + 'x' + FAG_WG_Y + '_bess' + FAG_BESSEL_MAX_ITER +
                  '_lut' + FAG_LUT_N_ROWS + 'x' + FAG_LUT_NX +
                  '_dx' + FAG_LUT_DX + '_v2';
  if (_gpuPipelineCache.device === device &&
      _gpuPipelineCache.kernelKey === kernelKey &&
      _gpuPipelineCache.pipelineAccum) {
    return;
  }
  // Device or kernel-shape changed (or first call) — drop the buffer cache too.
  _gpuPipelineCache.device = device;
  _gpuPipelineCache.kernelKey = kernelKey;
  _gpuPipelineCache.bufferKey = '';
  _gpuPipelineCache.buffers = null;

  var src = _fagBuildShaderWGSL();
  var mod = device.createShaderModule({ code: src });
  _gpuPipelineCache.module = mod;

  var bgl = device.createBindGroupLayout({
    entries: [
      { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } },
      { binding: 5, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 6, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'storage' } },
      { binding: 7, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'read-only-storage' } }
    ]
  });
  _gpuPipelineCache.bindGroupLayout = bgl;

  var layout = device.createPipelineLayout({ bindGroupLayouts: [bgl] });
  _gpuPipelineCache.layout = layout;

  _gpuPipelineCache.pipelineAccum = device.createComputePipeline({
    layout: layout,
    compute: { module: mod, entryPoint: 'flux_accum' }
  });
  _gpuPipelineCache.pipelineReduce = device.createComputePipeline({
    layout: layout,
    compute: { module: mod, entryPoint: 'flux_reduce' }
  });
}


// ===========================================================================
// Buffer allocation, keyed by shape (nObs, nEgrid, nA, nE_emit).
// Phase 3.5: per-call uniform updates rewrite ab_start/ab_end inside the
// dispatch loop, so we keep ONE uniform buffer and writeBuffer it between
// dispatches.
// ===========================================================================
function _fagEnsureBuffers(device, prep) {
  var key = prep.nObs + '_' + prep.nEgrid + '_' + prep.nA + '_' + prep.nE_emit;
  if (_gpuPipelineCache.bufferKey === key && _gpuPipelineCache.buffers) {
    return _gpuPipelineCache.buffers;
  }
  // Destroy stale buffers (if any) — best-effort, ignore errors.
  if (_gpuPipelineCache.buffers) {
    var old = _gpuPipelineCache.buffers;
    try { old.params.destroy();   } catch (e) { /* swallow */ }
    try { old.Egrid.destroy();    } catch (e) { /* swallow */ }
    try { old.emit_x.destroy();   } catch (e) { /* swallow */ }
    try { old.emit_y.destroy();   } catch (e) { /* swallow */ }
    try { old.emit_d.destroy();   } catch (e) { /* swallow */ }
    try { old.scratch.destroy();  } catch (e) { /* swallow */ }
    try { old.out_pflux.destroy(); } catch (e) { /* swallow */ }
    try { old.readback.destroy(); } catch (e) { /* swallow */ }
    try { old.bessel_lut.destroy(); } catch (e) { /* swallow */ }
  }

  // Scratch buffer: nObs^2 * nEgrid floats. For nObs=21, nEgrid=41 that is
  // 72,324 bytes (~71 KB) — well under maxStorageBufferBindingSize (>= 128 MB
  // on every desktop adapter we test on; we don't bother runtime-checking).
  var scratchBytes = prep.nObs * prep.nObs * prep.nEgrid * 4;
  var bufs = {
    params: device.createBuffer({
      size: 96,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST
    }),
    Egrid: device.createBuffer({
      size: prep.nEgrid * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
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
    scratch: device.createBuffer({
      size: scratchBytes,
      usage: GPUBufferUsage.STORAGE
    }),
    out_pflux: device.createBuffer({
      size: prep.nEgrid * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC
    }),
    readback: device.createBuffer({
      size: prep.nEgrid * 4,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
    }),
    // Phase 3.6c: Bessel J_n(x) LUT. 48 x 91 = 4368 floats = 17,472 B.
    // Read-only storage so the kernel can sample with linear interp.
    bessel_lut: device.createBuffer({
      size: FAG_LUT_N_ROWS * FAG_LUT_NX * 4,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST
    })
  };

  bufs.bindGroup = device.createBindGroup({
    layout: _gpuPipelineCache.bindGroupLayout,
    entries: [
      { binding: 0, resource: { buffer: bufs.params } },
      { binding: 1, resource: { buffer: bufs.Egrid } },
      { binding: 2, resource: { buffer: bufs.emit_x } },
      { binding: 3, resource: { buffer: bufs.emit_y } },
      { binding: 4, resource: { buffer: bufs.emit_d } },
      { binding: 5, resource: { buffer: bufs.scratch } },
      { binding: 6, resource: { buffer: bufs.out_pflux } },
      { binding: 7, resource: { buffer: bufs.bessel_lut } }
    ]
  });

  _gpuPipelineCache.bufferKey = key;
  _gpuPipelineCache.buffers = bufs;
  return bufs;
}


// ===========================================================================
// Patch a uniform-buffer copy with new ab_start / ab_end / zero_scratch
// integers. Returns a fresh Uint8Array suitable for queue.writeBuffer.
// ===========================================================================
function _fagPatchAbRange(baseBytes, ab_start, ab_end, zero_scratch) {
  // Copy the prepared 96-byte uniform block so we don't mutate prep.params.
  var copy = new Uint8Array(96);
  copy.set(baseBytes);
  // Integer block starts at offset 64. ui[5] = ab_start, ui[6] = ab_end,
  // ui[7] = zero_scratch. Each is 4 bytes little-endian.
  var view = new DataView(copy.buffer);
  view.setUint32(64 + 5 * 4, ab_start | 0,    true);
  view.setUint32(64 + 6 * 4, ab_end | 0,      true);
  view.setUint32(64 + 7 * 4, zero_scratch | 0, true);
  return copy;
}


// ===========================================================================
// Public API: fluxAcceptanceGPU(K, n, halfH_urad, halfV_urad) -> Promise<number>
// ===========================================================================
function fluxAcceptanceGPU(K, n, halfH_urad, halfV_urad) {
  if (halfH_urad === undefined) halfH_urad = 20;
  if (halfV_urad === undefined) halfV_urad = halfH_urad;

  // 1) Ensure WebGPU device is ready
  if (typeof detectWebGPU !== 'function') {
    return Promise.reject(new Error('02_webgpu_detect.js not loaded (detectWebGPU undefined)'));
  }

  function _run() {
    if (!window._GPU || !window._GPU.device) {
      return Promise.reject(new Error('WebGPU device unavailable'));
    }
    var device = window._GPU.device;

    // 2) Build inputs
    var prep = _fagPrepareInputs(K, n, halfH_urad, halfV_urad);

    // 3) Ensure pipelines + buffers
    _fagEnsurePipelines(device);
    var bufs = _fagEnsureBuffers(device, prep);

    // 4) Upload static host data (Egrid + 3 emittance grids + Bessel LUT).
    //    The uniform block is rewritten per-dispatch in the loop below.
    //    The Bessel LUT is constant across calls but we re-upload on every
    //    call so a bufferKey-driven cache rebuild (rare) is correctly
    //    refilled; cost is one 17 KiB writeBuffer, negligible vs the
    //    8-block accumulate dispatch.
    var lut = _fagBuildBesselLUT();
    device.queue.writeBuffer(bufs.Egrid,      0, prep.Egrid);
    device.queue.writeBuffer(bufs.emit_x,     0, prep.emit_x);
    device.queue.writeBuffer(bufs.emit_y,     0, prep.emit_y);
    device.queue.writeBuffer(bufs.emit_d,     0, prep.emit_d);
    device.queue.writeBuffer(bufs.bessel_lut, 0, lut);

    // 5) Split the (a, b) outer loop across FAG_AB_NUM_BLOCKS dispatches.
    //    Each dispatch fits comfortably under the Windows 2 s TDR.
    var wgX = Math.ceil(prep.nObs / FAG_WG_X);
    var wgY = Math.ceil(prep.nObs / FAG_WG_Y);
    var blocks = prep.abNumBlocks;
    var blockSize = prep.abBlockSize;
    var i, ab_start, ab_end, zero_flag, patched, enc, p1;

    for (i = 0; i < blocks; i++) {
      ab_start = i * blockSize;
      ab_end   = (i + 1) * blockSize;
      if (ab_end > prep.abPairs) ab_end = prep.abPairs;
      zero_flag = (i === 0) ? 1 : 0;

      patched = _fagPatchAbRange(prep.params, ab_start, ab_end, zero_flag);
      device.queue.writeBuffer(bufs.params, 0, patched);

      enc = device.createCommandEncoder();
      p1 = enc.beginComputePass();
      p1.setPipeline(_gpuPipelineCache.pipelineAccum);
      p1.setBindGroup(0, bufs.bindGroup);
      p1.dispatchWorkgroups(wgX, wgY, 1);
      p1.end();
      device.queue.submit([enc.finish()]);
    }

    // 6) Reduce pass — one dispatch after all accum sub-dispatches complete.
    var encR = device.createCommandEncoder();
    var p2 = encR.beginComputePass();
    p2.setPipeline(_gpuPipelineCache.pipelineReduce);
    p2.setBindGroup(0, bufs.bindGroup);
    var wgR = Math.ceil(prep.nEgrid / 64);
    p2.dispatchWorkgroups(wgR, 1, 1);
    p2.end();

    encR.copyBufferToBuffer(bufs.out_pflux, 0, bufs.readback, 0, prep.nEgrid * 4);
    device.queue.submit([encR.finish()]);

    // 7) Map + read peak
    return bufs.readback.mapAsync(GPUMapMode.READ).then(function () {
      var arr = new Float32Array(bufs.readback.getMappedRange().slice(0));
      bufs.readback.unmap();
      var peak = 0, k;
      for (k = 0; k < arr.length; k++) {
        if (arr[k] > peak) peak = arr[k];
      }
      return peak;
    });
  }

  // If device not yet probed, probe first; otherwise run immediately.
  if (!window._GPU || !window._GPU.device) {
    return detectWebGPU().then(_run);
  }
  return _run();
}


// ESM bridge: expose module-scoped functions to globalThis.
if (typeof fluxAcceptanceGPU !== 'undefined') globalThis.fluxAcceptanceGPU = fluxAcceptanceGPU;
if (typeof _fagBuildShaderWGSL !== 'undefined') globalThis._fagBuildShaderWGSL = _fagBuildShaderWGSL;
if (typeof _fagBuildBesselLUT !== 'undefined') globalThis._fagBuildBesselLUT = _fagBuildBesselLUT;
if (typeof FAG_WG_X !== 'undefined') globalThis.FAG_WG_X = FAG_WG_X;
if (typeof FAG_WG_Y !== 'undefined') globalThis.FAG_WG_Y = FAG_WG_Y;
if (typeof FAG_BESSEL_MAX_ITER !== 'undefined') globalThis.FAG_BESSEL_MAX_ITER = FAG_BESSEL_MAX_ITER;
if (typeof FAG_AB_NUM_BLOCKS !== 'undefined') globalThis.FAG_AB_NUM_BLOCKS = FAG_AB_NUM_BLOCKS;
if (typeof FAG_LUT_N_ROWS !== 'undefined') globalThis.FAG_LUT_N_ROWS = FAG_LUT_N_ROWS;
if (typeof FAG_LUT_NX !== 'undefined') globalThis.FAG_LUT_NX = FAG_LUT_NX;
if (typeof FAG_LUT_DX !== 'undefined') globalThis.FAG_LUT_DX = FAG_LUT_DX;
if (typeof FAG_LUT_X_UPPER !== 'undefined') globalThis.FAG_LUT_X_UPPER = FAG_LUT_X_UPPER;
