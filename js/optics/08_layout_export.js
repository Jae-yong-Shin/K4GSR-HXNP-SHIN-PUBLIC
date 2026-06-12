'use strict';
// ===== optics/08_layout_export.js - beamline layout export (Phase 1 / A2) =====
// @module optics/08_layout_export
// @exports BEAMLINE_LAYOUT_SCHEMA, BEAMLINE_LAYOUT_SCHEMA_VERSION, exportBeamlineLayout
//
// Serializes the CURRENT live optical state into a versioned JSON document
// for the offline high-fidelity backends (xrt now, SRW later).
// Hybrid A2 architecture (docs/tasks/TASK_PHASE1_ROADMAP.md section 3):
//   browser  : exportBeamlineLayout({download:true})  -> beamline_layout_*.json
//   offline  : python Scripts/layout_to_xrt.py layout.json out_script.py
//              python out_script.py                  (requires xrt 1.6.0)
// Schema documentation: docs/tasks/TASK_A2_XRT_EXPORT.md
// Validation harness:   paper/validation/run_layout_export_check.js
//
// All reads are defensive (typeof guards) so the module also works headless
// (Node vm harness) and when optional modules (mc_engine, motors) are absent.

var BEAMLINE_LAYOUT_SCHEMA = 'hanbit.beamline.layout';
var BEAMLINE_LAYOUT_SCHEMA_VERSION = 1;

/** Safe numeric read: first defined finite candidate, else fb. */
function _bleNum(v, fb) {
  return (typeof v === 'number' && isFinite(v)) ? v : fb;
}

/** Mirror coating name via getStripeMaterial (live y-motor aware), with fallback. */
function _bleCoating(mid, fb) {
  try {
    if (typeof getStripeMaterial === 'function') {
      var st = getStripeMaterial(mid);
      if (st && st.name) return st.name;
    }
  } catch (e) { /* fall through to fb */ }
  return fb;
}

/**
 * Export the current beamline layout as a versioned plain object.
 * @param {Object} [opts] - {download:true} additionally triggers a browser
 *        file download (guarded: silently skipped in headless contexts).
 * @returns {Object} layout document (JSON-serializable, no functions/cycles)
 */
function exportBeamlineLayout(opts) {
  opts = opts || {};
  var st = (typeof state !== 'undefined') ? state : {};
  var cd = (typeof CD !== 'undefined') ? CD : [];
  var posFn = (typeof pos === 'function') ? pos : function () { return null; };

  // --- components: every CD element with its live position [m] ---
  var components = [];
  var positions = {};
  for (var i = 0; i < cd.length; i++) {
    var c = cd[i];
    var p = _bleNum(posFn(c.id), c.dp);
    components.push({ id: c.id, name: c.name, type: c.tp, position_m: p });
    positions[c.id] = p;
  }

  // --- KB p/q geometry (engine convention: secondary source at the SSA) ---
  var sSSA = _bleNum(positions.ssa, 58.0);
  var sKBV = _bleNum(positions.kbv, 149.69);
  var sKBH = _bleNum(positions.kbh, 149.9);
  var sSmp = _bleNum(positions.sample, 150.0);

  var layout = {
    schema: BEAMLINE_LAYOUT_SCHEMA,
    schemaVersion: BEAMLINE_LAYOUT_SCHEMA_VERSION,
    exportedAt: new Date().toISOString(),
    engineVersion: (typeof APP_VERSION !== 'undefined') ? APP_VERSION : null,

    beam: {
      energy_keV: _bleNum(st.energy, 10.0),
      targetEnergy_keV: _bleNum(st.targetEnergy, _bleNum(st.energy, 10.0)),
      crystal: (typeof st.crystal === 'string') ? st.crystal : '111',
      gap_mm: _bleNum(st.gap, 7.0),
      harmonic: _bleNum(st.harmonic, 1)
    },

    // Source params: live engine variables (user-tunable vars, CLAUDE.md)
    source: {
      type: 'IVU24',
      E_GeV: (typeof E_RING !== 'undefined') ? E_RING : 4.0,
      I_mA: (typeof I_RING !== 'undefined') ? I_RING : 400,
      emitX_m_rad: (typeof EMIT_X !== 'undefined') ? EMIT_X : 62e-12,
      emitY_m_rad: (typeof EMIT_Y !== 'undefined') ? EMIT_Y : 6.2e-12,
      betaX_m: (typeof BETA_X !== 'undefined') ? BETA_X : 6.334,
      betaY_m: (typeof BETA_Y !== 'undefined') ? BETA_Y : 2.841,
      eSpread: (typeof E_SPREAD !== 'undefined') ? E_SPREAD : 1.20e-3,
      lambdaU_mm: (typeof LAMBDA_U !== 'undefined') ? LAMBDA_U : 24,
      nPeriods: (typeof N_PERIODS !== 'undefined') ? N_PERIODS : 123,
      undLength_m: (typeof L_UND !== 'undefined') ? L_UND : 2.952
    },

    components: components,

    slits: {
      wb: {
        hGap_mm: _bleNum(st.wbH, 1.2), vGap_mm: _bleNum(st.wbV, 1.2),
        hCenter_mm: _bleNum(st.wbCX, 0), vCenter_mm: _bleNum(st.wbCY, 0)
      },
      ssa: {
        hGap_um: _bleNum(st.ssaH, 50), vGap_um: _bleNum(st.ssaV, 50),
        hCenter_um: _bleNum(st.ssaCX, 0), vCenter_um: _bleNum(st.ssaCY, 0)
      },
      kbslit: {
        hGap_um: _bleNum(st.kbslitH, 5000), vGap_um: _bleNum(st.kbslitV, 5000),
        hCenter_um: _bleNum(st.kbslitCX, 0), vCenter_um: _bleNum(st.kbslitCY, 0)
      }
    },

    mirrors: {
      m1: {
        pitch_mrad: _bleNum(st.m1pitch, 2.5),
        coating: _bleCoating('m1', 'Pt'),
        focusPlane: 'v',  // sagittal V-focus (fixed curvature)
        p_m: (typeof M1_P !== 'undefined') ? M1_P : 29.0,
        q_m: (typeof M1_Q !== 'undefined') ? M1_Q : 29.0,
        length_m: 0.60, width_m: 0.060
      },
      m2: {
        pitch_mrad: _bleNum(st.m2pitch, 2.5),
        coating: _bleCoating('m2', 'Rh'),
        focusPlane: 'h',  // tangential H-focus (bendable)
        p_m: (typeof M2_P !== 'undefined') ? M2_P : 32.0,
        q_m: (typeof M2_Q !== 'undefined') ? M2_Q : 26.0,
        length_m: 0.60, width_m: 0.060
      },
      kbv: {
        pitch_mrad: _bleNum(st.kbvpitch, 3.0),
        coating: _bleCoating('kbv', 'Pt'),
        focusPlane: 'v',
        p_m: sKBV - sSSA,       // 91.69 (KB ellipse arm from SSA secondary source)
        q_m: sSmp - sKBV,       // 0.31
        length_m: (typeof KB_PARAMS !== 'undefined' && KB_PARAMS.kbv) ? KB_PARAMS.kbv.len : 0.300,
        width_m: (typeof KB_PARAMS !== 'undefined' && KB_PARAMS.kbv) ? KB_PARAMS.kbv.wid : 0.030
      },
      kbh: {
        pitch_mrad: _bleNum(st.kbhpitch, 3.0),
        coating: _bleCoating('kbh', 'Pt'),
        focusPlane: 'h',
        p_m: sKBH - sSSA,       // 91.90
        q_m: sSmp - sKBH,       // 0.10
        length_m: (typeof KB_PARAMS !== 'undefined' && KB_PARAMS.kbh) ? KB_PARAMS.kbh.len : 0.100,
        width_m: (typeof KB_PARAMS !== 'undefined' && KB_PARAMS.kbh) ? KB_PARAMS.kbh.wid : 0.030
      }
    },

    dcm: {
      crystal: (typeof st.crystal === 'string') ? st.crystal : '111',
      fixedExit_mm: (typeof FIXED_EXIT !== 'undefined') ? FIXED_EXIT : 12.0,
      dSpacing_A: (typeof D_SI !== 'undefined' && st.crystal && D_SI[st.crystal] !== undefined)
        ? D_SI[st.crystal] : null
    }
  };

  if (opts.download) _bleDownload(layout);
  return layout;
}

/** Trigger a browser download of the layout JSON (no-op when headless). */
function _bleDownload(layout) {
  if (typeof document === 'undefined' || typeof Blob === 'undefined' ||
      typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
    if (typeof console !== 'undefined' && console.log) {
      console.log('[layout_export] headless context: download skipped');
    }
    return;
  }
  try {
    var nameE = String(layout.beam.energy_keV).replace('.', 'p');
    var stamp = layout.exportedAt.replace(/[:.]/g, '-');
    var fname = 'beamline_layout_' + nameE + 'keV_' + stamp + '.json';
    var blob = new Blob([JSON.stringify(layout, null, 1)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = fname;
    if (document.body) document.body.appendChild(a);
    a.click();
    if (a.parentNode) a.parentNode.removeChild(a);
    setTimeout(function () { try { URL.revokeObjectURL(url); } catch (e) {} }, 1000);
  } catch (e) {
    if (typeof console !== 'undefined' && console.warn) {
      console.warn('[layout_export] download failed: ' + e.message);
    }
  }
}

// ESM bridge: expose module-scoped vars to globalThis
if (typeof BEAMLINE_LAYOUT_SCHEMA !== 'undefined') globalThis.BEAMLINE_LAYOUT_SCHEMA = BEAMLINE_LAYOUT_SCHEMA;
if (typeof BEAMLINE_LAYOUT_SCHEMA_VERSION !== 'undefined') globalThis.BEAMLINE_LAYOUT_SCHEMA_VERSION = BEAMLINE_LAYOUT_SCHEMA_VERSION;
if (typeof exportBeamlineLayout !== 'undefined') globalThis.exportBeamlineLayout = exportBeamlineLayout;
