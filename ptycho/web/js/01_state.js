/**
 * 01_state.js - Global state object and constants
 * Matches K4GSR-Beamline global state pattern
 */
const STATE = {
    // Connection
    ws: null,
    wsUrl: 'ws://localhost:8765',
    connected: false,
    reconnectTimer: null,
    gpuAvailable: false,

    // Engine config
    engine: 'DM_ML',
    params: {
        engine: 'DM_ML',
        number_iterations: 50,
        pfft_relaxation: 0.1,
        probe_change_start: 1,
        probe_modes: 1,
        use_gpu: true,
        probe_support_radius: 0.9,
        // ML
        opt_iter: 50,
        opt_errmetric: 'poisson',
        // LSQML
        beta_LSQ: 0.9,
        delta_p: 0.1,
        probe_position_search: 0,
        // Pipeline
        dm_iterations: 300,
        ml_iterations: 30,
        lsqml_iterations: 20,
    },

    // Data
    dataLoaded: false,
    dataInfo: null,
    dataSource: 'synth',
    synthParams: {
        // Sample
        dataset_id: 6,
        material: 'Au',
        energy_keV: 6.2,
        objheight: 1e-6,
        // Scan
        asize: 128,
        scan_step_um: 1.5,
        scan_lx_um: 10,
        scan_ly_um: 10,
        z_m: 5.0,
        overlap: 0.75,
        // Noise
        N_photons: 1000,
        noise_sigma: 0.0,
        rng_seed: 42,
    },

    // Reconstruction
    running: false,
    currentJobId: null,
    iteration: 0,
    totalIterations: 0,
    errorHistory: [],
    elapsedSec: 0,
    etaSec: 0,
    pipelineStage: 1,

    // Images — raw complex data for client-side colormap rendering
    images: {
        objectAmp: null,
        objectPhase: null,
        probeAmp: null,
        probePhase: null,
    },

    // Raw complex float32 data cache (interleaved [re, im, re, im, ...])
    rawData: {
        object: null,       // Float32Array
        objectShape: null,  // [H, W]
        probe: null,        // Float32Array
        probeShape: null,   // [H, W]
    },

    // Per-panel view settings (colormap + scale)
    viewSettings: {
        objAmp:   { colormap: 'viridis', scale: 'robust', min: 0, max: 1, currentMin: undefined, currentMax: undefined },
        objPhase: { colormap: 'hsv',     scale: 'auto',   min: -Math.PI, max: Math.PI, currentMin: undefined, currentMax: undefined },
        prAmp:    { colormap: 'hot',     scale: 'robust', min: 0, max: 1, currentMin: undefined, currentMax: undefined },
        prPhase:  { colormap: 'hsv',     scale: 'auto',   min: -Math.PI, max: Math.PI, currentMin: undefined, currentMax: undefined },
    },

    // Batch
    batchQueue: [],
    batchRunning: false,

    // History
    historyEntries: [],
};

// Engine display names
const ENGINE_NAMES = {
    'DM': 'DM (Difference Map)',
    'ML': 'ML (Maximum Likelihood)',
    'LSQML': 'LSQML (GPU)',
    'DM_ML': 'DM \u2192 ML',
    'DM_LSQML': 'DM \u2192 LSQML',
};
