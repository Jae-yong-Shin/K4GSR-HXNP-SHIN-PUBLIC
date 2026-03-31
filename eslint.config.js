// ESLint flat config for K4GSR-Beamline
// ES5 browser globals + beamline-specific globals
module.exports = [
  {
    files: ["js/**/*.js"],
    languageOptions: {
      ecmaVersion: 5,
      sourceType: "script",
      globals: {
        // Browser + ESM bridge
        globalThis: "readonly",
        window: "readonly", document: "readonly", console: "readonly",
        setTimeout: "readonly", setInterval: "readonly", clearTimeout: "readonly",
        clearInterval: "readonly", requestAnimationFrame: "readonly",
        cancelAnimationFrame: "readonly", alert: "readonly",
        HTMLElement: "readonly", Event: "readonly", MouseEvent: "readonly",
        KeyboardEvent: "readonly", WebSocket: "readonly", XMLHttpRequest: "readonly",
        URLSearchParams: "readonly", location: "readonly", navigator: "readonly",
        performance: "readonly", Image: "readonly", Blob: "readonly", URL: "readonly",
        FileReader: "readonly", fetch: "readonly", Promise: "readonly",
        Float64Array: "readonly", Float32Array: "readonly", Uint8Array: "readonly",
        ArrayBuffer: "readonly", DataView: "readonly",
        // Ring & IVU constants
        E_RING: "writable", I_RING: "writable", I_RING_A: "writable",
        EMIT_X: "writable", EMIT_Y: "writable", GAMMA_E: "writable",
        BETA_X: "writable", BETA_Y: "writable", E_SPREAD: "writable",
        SIG_EX: "writable", SIG_EXP: "writable", SIG_EY: "writable", SIG_EYP: "writable",
        N_PERIODS: "readonly", LAMBDA_U: "readonly", LAMBDA_U_M: "readonly",
        L_UND: "readonly", HC: "readonly", FIXED_EXIT: "readonly",
        D_SI: "readonly", R_E_A: "readonly", NA: "readonly", V_SI: "readonly",
        RH: "readonly", PT: "readonly",
        HALB_A: "readonly", HALB_B: "readonly", HALB_C: "readonly",
        // State & config
        state: "writable", CD: "writable", pos: "readonly",
        MOTORS: "writable", M_PARAMS: "writable", DEVICE_CONFIGS: "writable",
        EPICS_STATE: "writable", SimIOC: "writable",
        SERVER_HOST: "readonly", SERVER_WS_PORT: "readonly",
        DEVICE_REGISTRY: "writable", PV_REGISTRY: "writable",
        PV_TO_MOTOR: "writable", PV_MONITOR_GROUPS: "writable",
        SYNC_HANDLERS: "writable", VIRTUAL_STATE: "writable",
        LIVE_SCAN: "writable", QUEUE: "writable", PLAN_LIBRARY: "writable",
        COMPARISON: "writable", ALIGN_CONFIG: "writable",
        // Physics functions
        mcRayTrace: "readonly", applyMirrorMC: "readonly",
        applyDCM_MC: "readonly", applyKBMC: "readonly",
        braggAngle: "readonly", mirrorR: "readonly", mirrorCut: "readonly",
        optConst: "readonly", gaussRand: "readonly",
        photonSrc: "readonly", photonFlux: "readonly", sourceFlux: "readonly",
        dcmGap: "readonly", dcmRes: "readonly", dcmThru: "readonly",
        siFf: "readonly", siFh: "readonly", siChi: "readonly", darwinW: "readonly",
        extDepth: "readonly", erf_a: "readonly", recalcElectronBeam: "readonly",
        updateEbeamParam: "readonly", xbpmZone: "readonly",
        updateEnergy: "writable", updateOptics: "writable", updateUnd: "writable",
        mVal: "readonly", mSet: "readonly",
        findHarmonics: "readonly", dcmBandwidth: "readonly",
        calcK: "readonly", calcB0: "readonly",
        _wbMode: "writable",
        // UI utilities
        _drawSpecChart: "readonly", _openPopup: "readonly", _openModal: "readonly",
        _popupManager: "readonly", _makePopupResizable: "readonly",
        _invalidateMCCache: "readonly", updateLiveBeamInfo: "readonly",
        _nomBeamX: "readonly", _mcSampleCache: "writable",
        OPTCONST_TABLES: "readonly",
        MC_NRAYS: "writable", MC_GRID: "writable",
        renderAll: "writable", buildPanel: "writable",
        log: "readonly", showComp: "readonly",
        // Alignment
        _alignFullAuto: "writable", _alignState: "writable",
        _alignBpmCenter: "writable", _bpmFovROI: "readonly",
        runMirrorAlignUI: "readonly", MIRROR_ALIGN_SEQ: "readonly",
        // Bluesky / queue
        executeSimPlan: "readonly", submitBlueskyPlan: "readonly"
      }
    },
    rules: {
      "no-undef": "warn",
      "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
      "no-redeclare": "warn",
      "semi": ["warn", "always"],
      "no-console": "off",
      "no-empty": "warn",
      "no-unreachable": "error",
      "no-constant-condition": "warn",
      "no-dupe-keys": "error",
      "no-duplicate-case": "error",
      "use-isnan": "error",
      "valid-typeof": "error"
    }
  },
  {
    ignores: ["js/optics/00_optconst_tables.js", "node_modules/**", "tests/**"]
  }
];
