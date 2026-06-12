'use strict';
// ===== alignment/02_strategies.js -- ALIGN_STRATEGIES (per-device quick scans) =====
// @module alignment/02_strategies
// @exports ALIGN_STRATEGIES, _alignMcSignal
// MC-based alignment signals: motor.moveTo() updates state via _syncState(),
// then mcSignalAt/mcFluxAt runs MC ray trace with current physics state.
// This ensures scan curves match beam profile visualization.
// Dependencies: ALIGN_CONFIG, MOTORS, state, pos, beamAt, mcSignalAt, mcFluxAt,
//   darwinW, alignCentroid, alignGaussianFit, alignHalfBeam, alignRockingCurve

// --- Helper: MC signal at detector (survived ray count) ---
// Uses MC_NRAYS from View tab setting (linked to beam profile ray count).
// motor.moveTo() has already updated state via _syncState() before this is called.
function _alignMcSignal(detId) {
  var nR = (typeof MC_NRAYS !== 'undefined') ? MC_NRAYS : 80000;
  var d = pos(detId);
  if (typeof mcSignalAt === 'function') return mcSignalAt(d, nR);
  if (typeof mcFluxAt === 'function') return mcFluxAt(d, nR) * nR;
  return 0;
}

// --- Override ALIGN_STRATEGIES with MC-based signals ---
// Each signalFn(p) is called AFTER motor.moveTo(p) + _syncState(),
// so MC ray trace sees the updated motor position in state.
window.ALIGN_STRATEGIES = {
  wbslit: {
    name: 'WB Slit H-Centering',
    desc: 'XBPM-WB: scan WB slit H-center, MC measures transmitted flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.wbslit;
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      return await alignCentroid(MOTORS.wbslit.hcenter || MOTORS.wbslit.inboard, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  wbslit_v: {
    name: 'WB Slit V-Centering',
    desc: 'XBPM-WB: scan WB slit V-center, MC measures transmitted flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.wbslit_v;
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      return await alignCentroid(MOTORS.wbslit.vcenter || MOTORS.wbslit.top, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  m1pitch: {
    name: 'M1 Pitch Optimize',
    desc: 'XBPM-M1: scan M1 pitch, MC measures reflected flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.m1pitch;
      // Signal: MC ray trace after motor moveTo updates state.m1pitch
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      return await alignGaussianFit(MOTORS.m1.pitch, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  dcmDTheta2: {
    name: 'DCM dTheta2 Rocking',
    desc: 'XBPM1: scan DCM 2nd crystal parallelism, MC measures diffracted flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.dcmDTheta2;
      var dw = darwinW(state.energy);
      var dynRange = [-dw * 3, dw * 3];
      // Signal: MC ray trace after motor moveTo updates DCM dTheta2
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      return await alignRockingCurve(MOTORS.dcm.dTheta2, sig, dynRange, cfg.nPts, cfg.label, onPoint);
    }
  },
  m2pitch: {
    name: 'M2 Pitch Optimize',
    desc: 'XBPM-M2: scan M2 pitch, MC measures reflected flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.m2pitch;
      // Signal: MC ray trace after motor moveTo updates state.m2pitch
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      return await alignGaussianFit(MOTORS.m2.pitch, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  ssacenter: {
    name: 'SSA H-Centering',
    desc: 'XBPM-SSA: scan SSA H-center, MC measures transmitted flux past slit',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.ssacenter;
      // Signal: MC ray trace after motor moveTo updates state.ssaCX
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      // SSA centering gives a direct intensity peak (not half-cut edge)
      // → use gaussianFit for accurate center finding
      return await alignGaussianFit(MOTORS.ssa.hcen, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  ssacenter_v: {
    name: 'SSA V-Centering',
    desc: 'XBPM-SSA: scan SSA V-center, MC measures transmitted flux past slit',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.ssacenter_v;
      // Signal: MC ray trace after motor moveTo updates state.ssaCY
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      // SSA centering gives a direct intensity peak (not half-cut edge)
      // → use gaussianFit for accurate center finding
      return await alignGaussianFit(MOTORS.ssa.vcen, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
    }
  },
  kbalign: {
    name: 'KB Focus Alignment',
    desc: 'XBPM3: scan KB-V pitch, MC measures focused flux',
    run: async function(onPoint) {
      var cfg = ALIGN_CONFIG.kbalign;
      // Signal: MC ray trace after motor moveTo updates state.kbvpitch
      var sig = function(p) {
        return _alignMcSignal(cfg.detector);
      };
      await alignGaussianFit(MOTORS.kbv.pitch, sig, cfg.range, cfg.nPts, cfg.label, onPoint);
      var sp = focalSpot();
      return { method: 'kb', center: MOTORS.kbv.pitch.value, spot: sp };
    }
  }
};

console.log('[' + APP_VTAG + '] ALIGN_STRATEGIES loaded (MC ray-trace signal mode)');

// ESM bridge: expose module-scoped vars to globalThis
if(typeof ALIGN_STRATEGIES!=="undefined")globalThis.ALIGN_STRATEGIES=ALIGN_STRATEGIES;
if(typeof _alignMcSignal!=="undefined")globalThis._alignMcSignal=_alignMcSignal;
