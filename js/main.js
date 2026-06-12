/**
 * K4GSR-Beamline ES Module Entry Point
 * =====================================
 * All modules imported in dependency order (matching original HTML load order).
 * Each file currently uses global scope; esbuild --bundle merges them into one IIFE.
 *
 * Migration path:
 *   Phase 1 (current): side-effect imports, globals preserved
 *   Phase 2: add export/import per file, remove window.* assignments
 *   Phase 3: tree-shaking enabled
 */

// Tier 0: Foundation (no dependencies)
import './shared/01_constants.js';
import './shared/02_chart_stub.js';
import './shared/03_i18n.js';

// Tier 1A: Optics data + physics (depends on shared)
import './optics/00_optconst_tables.js';
import './optics/01_undulator.js';
import './optics/02_crystal.js';
import './optics/02b_crystal_psi_tables.js';
import './optics/03_reflectivity.js';
import './optics/04_source.js';
import './optics/divergence_lookup.js';
import './optics/divergence_gpu.js';
import './optics/06_source_optics_table.js';

// Tier 1B: Control (depends on shared)
import './control/01_motors.js';
import './control/02_epics.js';
import './control/03_energy_sync.js';
import './control/04_compare.js';

// Tier 1C: Analysis (depends on shared)
import './analysis/01_mask_calc.js';
import './analysis/02_transmission.js';

// Tier 2: Ray tracing (depends on shared + optics + control)
import './raytrace/01_mc_engine.js';
import './raytrace/02_propagation.js';
import './raytrace/03_beam_profile.js';
import './raytrace/04_propagation_ui.js';

// Tier 5: Optics main (depends on raytrace — loaded after raytrace to resolve circular)
import './optics/05_beam_optics.js';

// Tier 7: Alignment (depends on raytrace + control)
import './alignment/01_signals.js';
import './alignment/02_strategies.js';
import './alignment/03_runners.js';
import './alignment/04_align_ui.js';
import './alignment/05_align_analysis.js';

// Tier 3: UI base (depends on shared + control)
import './ui/01_popup_util.js';
import './ui/02_layout_svg.js';
import './ui/03_panels.js';
import './ui/04_dynamic_tabs.js';
import './ui/05_modal.js';
import './ui/07_meas_chart.js';
import './ui/08_theme_layout.js';
import './ui/09_panel_resize.js';
import './ui/10_motor_jog.js';
import './ui/11_beam_monitor.js';

// Tier 5+: Control UI (depends on ui)
import './control/05_epics_ui.js';

// Tier 6: Detectors
import './detector/01_eiger.js';
import './detector/02_sdd.js';

// Tier 9: Measurement
import './measurement/01_scan_control.js';
import './measurement/03_init.js';

// Tier 8: Experiments
import './experiment/01_xray_data.js';
// 02_xafs_sim, 03_xrd_sim, 04_xrd2d_sim removed (server engine only)
import './experiment/05_ptycho_sim.js';
import './experiment/06_experiment_ui.js';
import './experiment/07_experiment_run.js';
import './experiment/08_phantoms.js';

// Tier 10: Bluesky
import './bluesky/01_queue.js';
import './bluesky/03_bluesky_ui.js';
import './bluesky/06_live_scan.js';
import './bluesky/07_server_history.js';
import './bluesky/08_scan_results.js';

// Tier 12: Tutorial + NLP + Tomo
import './tutorial/01_tutorial.js';
import './tutorial/02_experiment_ui.js';
import './nlp/01_nlp_chat.js';
import './nlp/02_nlp_nano_bridge.js';
import './nlp/02_optimizer.js';
import './tomo/01_tomography.js';
import './ui/13_scanner_panel.js';
