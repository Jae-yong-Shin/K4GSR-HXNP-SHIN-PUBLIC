'use strict';
// ===== shared/03_i18n.js -- Internationalization (i18n) System =====
// @module shared/03_i18n
// @exports _t, setUILanguage, refreshUILanguage, UI_LANG
// Provides: _t(key), setUILanguage(id), refreshUILanguage(), UI_LANG
// 4 languages: English, Korean, Japanese, Chinese

var UI_LANG = 'en';

var I18N_STRINGS = {
  en: {
    // Tab labels
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: 'Optics',
    tab_motors: 'Motors',   tab_mask: 'Mask',    tab_measure: 'Meas',
    tab_align: 'Align',     tab_compare: 'V/R',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: 'Guide',  tab_chat: 'Chat',
    tab_expt: 'Expt',
    // Mode menu headers
    hdr_theme: 'Color Theme',   hdr_layout: 'Layout',
    hdr_mcrays: 'MC Rays',      hdr_grid: 'Grid Resolution',
    hdr_popupfont: 'Popup Font Size',
    popupfont_default: 'Default size',
    popupfont_large: '1.5x -- larger text',
    popupfont_xlarge: '2x -- much larger',
    popupfont_max: '3x -- maximum size',
    hdr_language: 'Language',
    // Theme labels
    theme_light: 'Light (Default)',   theme_dark: 'Dark',
    theme_dark2: 'Dark 2',           theme_deuter: 'Deuteranopia',
    theme_protan: 'Protanopia',      theme_tritan: 'Tritanopia',
    // Theme descriptions
    themedesc_light: 'Clean white background',
    themedesc_dark: 'High contrast dark theme',
    themedesc_dark2: 'Muted dark theme',
    themedesc_deuter: 'Red-green color blind safe',
    themedesc_protan: 'Red blind safe',
    themedesc_tritan: 'Blue-yellow color blind safe',
    // Layout labels
    layout_standard: 'Standard',  layout_wide: 'Wide View',
    layout_compact: 'Compact',    layout_focus: 'Focus',
    // Layout descriptions
    layoutdesc_standard: 'Full panel layout (320px sidebar)',
    layoutdesc_wide: 'Hide sidebar, maximize beamline view',
    layoutdesc_compact: 'Narrow sidebar (220px)',
    layoutdesc_focus: 'Beamline only, hide all panels',
    // MC Rays descriptions
    mcrays_fast: 'Fast -- preview',      mcrays_normal: 'Normal -- moderate quality',
    mcrays_default: 'Default -- high statistics', mcrays_precise: 'Precise -- slow',
    mcrays_best: 'Best quality -- very slow',
    // Grid descriptions
    grid_standard: 'Default -- fast rendering',
    grid_highres: '4x finer -- small beam detail',
    // Buttons
    btn_estop: 'E-STOP',       btn_reset: 'Reset',
    btn_start: 'Start',        btn_stop: 'Stop',
    btn_save: 'Save',          btn_close: 'Close',
    btn_apply: 'Apply',        btn_cancel: 'Cancel',
    // Panel headers
    panel_source: 'Source Parameters',
    panel_beamline: 'Beamline Overview',
    panel_profile: 'Beam Profile',
    panel_spectrum: 'Spectrum',
    // Mode
    mode_virtual: 'Virtual',   mode_real: 'Real',   mode_dual: 'Dual',
    // ── Alignment panel ──
    align_ready: 'Ready',
    align_starting: 'Starting...',
    align_scanning: 'scanning...',
    align_abort: 'Abort',
    align_export_log: 'Export Log',
    align_scan_waiting: 'Scan chart -- waiting...',
    align_pass: 'PASS',
    align_fail: 'FAIL',
    align_step_fmt: 'Step {0}/{1}: {2}',
    align_motor_fmt: 'Motor={0}',
    align_intensity_fmt: 'Intensity={0}',
    align_centroid_fmt: 'Centroid={0} mm',
    align_beam_at: 'Beam @ {0} ({1}m)',
    align_halfcut: 'Half-Cut (pitch=0)',
    align_halfcut_c1: 'Half-Cut C1 (theta=0)',
    align_set_angle: 'Set Operating Angle',
    align_rot_center: 'Rotation Center',
    align_set_bragg: 'Set Bragg',
    align_dtheta2_coarse: 'dTheta2 Coarse',
    align_dtheta2_fine: 'dTheta2 Fine',
    align_m1_full: 'M1 Full Alignment',
    align_m2_full: 'M2 Full Alignment',
    align_kbv: 'KB-V Alignment',
    align_kbh: 'KB-H Alignment',
    align_dcm_full: 'DCM Full Alignment',
    // ── Experiment panel ──
    expt_start: 'Start',
    expt_stop: 'Stop',
    expt_show: 'Show',
    expt_save: 'Save',
    expt_starting_fmt: 'Starting {0}...',
    expt_computing: 'Computing...',
    expt_no_result: 'No result to save',
    expt_saved_fmt: 'Saved: {0}',
    expt_ready_msg: 'Ready. Results will open in a separate popup window.',
    expt_server_disc: 'Simulation server (port {0}) not connected.',
    expt_beamline_status: 'Beamline',
    expt_server_not_connected: 'Simulation server not connected',
    expt_formula: 'Formula',
    expt_absorber: 'Absorber',
    expt_edge: 'Edge',
    expt_e_range: 'E range (eV)',
    expt_e_step: 'E step',
    expt_presets: 'Presets',
    expt_sample: 'Sample',
    expt_conc: 'Conc (ppm)',
    // ── Bluesky panel ──
    bs_submit_plan: 'Submit Plan',
    bs_add_queue: 'Add to Queue',
    bs_run_now: 'Run Now',
    bs_queue_fmt: 'Queue ({0})',
    bs_queue_empty: 'No plans in queue',
    bs_clear: 'Clear',
    bs_run_history_fmt: 'Run History ({0})',
    bs_quick_run: 'Quick Run',
    bs_qs_connection: 'Queue Server Connection',
    bs_connected: '[Connected]',
    bs_sim_mode: '[Simulation Mode]',
    bs_connect: 'Connect',
    bs_server_history: 'Server Scan History',
    bs_click_refresh: 'Click [Refresh] to load server history',
    // ── Status ──
    status_idle: 'IDLE',
    status_running: 'RUNNING',
    status_paused: 'PAUSED',
    status_error: 'ERROR',
    status_completed: 'OK',
    status_aborted: '--',
    // ── Tutorial ──
    tut_basics_name: 'Basic Usage',
    tut_basics_desc: 'Learn the basic interface and key features of the program',
    tut_b1_title: 'Welcome!',
    tut_b1_content: '<p>Welcome to the Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>This tutorial will guide you through the basic usage step by step.</p><p style="color:var(--am)">Follow the instructions at each step.</p>',
    tut_b2_title: '1. Beamline Layout',
    tut_b2_content: '<p>The center of the screen shows <b>two views</b>:</p><p>* <span style="color:var(--ac)">TOP VIEW</span> -- Horizontal plane (M1/M2 mirror reflections)</p><p>* <span style="color:var(--ac)">SIDE VIEW</span> -- Vertical plane (DCM Bragg diffraction)</p><p style="color:var(--gn)">Click on any component to open its details and control panel.</p>',
    tut_b3_title: '2. Energy Setting',
    tut_b3_content: '<p>Set the target energy in the <b>IVU tab</b> on the right sidebar.</p><p style="color:var(--am)">Try dragging the slider to set energy to 10 keV.</p><p>The system will automatically:</p><p>* Select the optimal harmonic</p><p>* Adjust the IVU gap</p><p>* Calculate the DCM Bragg angle</p>',
    tut_b4_title: '3. Optical Component Adjustment',
    tut_b4_content: '<p>Adjust the beamline optics in the <b>Optics tab</b>:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- White beam slit size</p><p>* <span style="color:var(--ac)">M1/M2</span> -- Horizontal deflection mirror angles</p><p>* <span style="color:var(--ac)">SSA</span> -- Secondary slit (KB virtual source)</p><p>* <span style="color:var(--ac)">KB</span> -- Final focusing result</p><p style="color:var(--am)">Try clicking the Optics tab.</p>',
    tut_b5_title: '4. Status Monitoring',
    tut_b5_content: '<p>Check real-time beam information in the status bar at the bottom:</p><p>* <span style="color:var(--ac)">E</span> -- Current energy</p><p>* <span style="color:var(--gn)">Flux</span> -- Photon flux</p><p>* <span style="color:var(--pk)">Spot</span> -- Focal spot size</p><p>Beam sizes at each component position are also displayed.</p>',
    tut_b6_title: '5. Running Measurements',
    tut_b6_content: '<p>You can run virtual experiments from the <b>Meas tab</b>:</p><p>* XANES -- Absorption spectrum</p><p>* XRD -- Diffraction pattern</p><p>* XRF -- Fluorescence spectrum</p><p>* 2D Map -- Spatial mapping</p><p style="color:var(--gn)">Press the START button to begin a scan.</p>',
    tut_b7_title: '6. Bluesky Experiment Queue',
    tut_b7_content: '<p>Manage Bluesky-style experiments from the <b>BS tab</b>:</p><p>* Select plan and set parameters</p><p>* Add to queue for sequential execution</p><p>* Real-time progress monitoring</p><p style="color:var(--pr)">You can also use Quick Run buttons to start immediately.</p>',
    tut_b8_title: '7. Mode Switching',
    tut_b8_content: '<p>Switch the operation mode using the mode buttons in the top bar:</p><p>* <span style="color:var(--gn)">Virtual</span> -- Simulation only</p><p>* <span style="color:var(--am)">Real</span> -- Real EPICS IOC connection</p><p>* <span style="color:var(--ac)">Dual</span> -- V/R comparison mode</p><p>For first-time use, practice in Virtual mode before switching to Real.</p>',
    tut_b9_title: 'Basic Tutorial Complete!',
    tut_b9_content: '<p style="color:var(--gn)">Congratulations! You have learned the basic usage.</p><p>Proceed to the next steps:</p><p>* <b>Virtual Experiments</b> -- Simulate real experiments</p><p>* <b>EPICS Integration</b> -- Connect to real equipment</p><p>* <b>V/R Comparison</b> -- Compare simulation and reality</p>',
    tut_exp_name: 'Virtual Experiment Practice',
    tut_exp_desc: 'Perform virtual experiments for each measurement technique',
    tut_e1_title: 'Cu K-edge XANES Experiment',
    tut_e1_content: '<p>In this exercise, you will perform a <b>Cu K-edge XANES</b> measurement.</p><p style="color:var(--am)">Press the "Auto Setup" button below to automatically configure the experiment.</p>',
    tut_e2_title: 'Run XANES Scan',
    tut_e2_content: '<p>Energy has been set to Cu K-edge (8.979 keV).</p><p style="color:var(--am)">In the BS tab, press the XANES button to start the scan.</p><p>When the scan completes, the µ(E) spectrum will be displayed in the bottom panel.</p>',
    tut_e3_title: 'XRF Imaging Experiment',
    tut_e3_content: '<p>Now we will perform <b>XRF Imaging</b>.</p><p>The SDD detector collects fluorescence X-rays at 90 deg from the sample.</p><p style="color:var(--am)">After auto setup, a raster scan will generate an elemental distribution map.</p>',
    tut_e4_title: 'Powder XRD Experiment',
    tut_e4_content: '<p>Perform a <b>Powder XRD</b> measurement.</p><p>The Eiger 2X detector will collect Debye-Scherrer ring patterns.</p>',
    tut_prev: 'Prev', tut_next: 'Next', tut_done: 'Done'
  },
  ko: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\uad11\ud559',
    tab_motors: '\ubaa8\ud130',  tab_mask: '\ub9c8\uc2a4\ud06c', tab_measure: '\uce21\uc815',
    tab_align: '\uc815\ub82c',   tab_compare: '\ube44\uad50',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\uac00\uc774\ub4dc', tab_chat: '\ucc44\ud305',
    tab_expt: '\uc2e4\ud5d8',
    hdr_theme: '\uc0c9\uc0c1 \ud14c\ub9c8',  hdr_layout: '\ub808\uc774\uc544\uc6c3',
    hdr_mcrays: 'MC \uad11\uc120',  hdr_grid: '\uadf8\ub9ac\ub4dc \ud574\uc0c1\ub3c4',
    hdr_popupfont: '\ud31d\uc5c5 \ud3f0\ud2b8 \ud06c\uae30',
    popupfont_default: '\uae30\ubcf8 \ud06c\uae30',
    popupfont_large: '1.5\ubc30 -- \ub354 \ud070 \uae00\uc790',
    popupfont_xlarge: '2\ubc30 -- \ud6e8\uc52c \ud070 \uae00\uc790',
    popupfont_max: '3\ubc30 -- \ucd5c\ub300 \ud06c\uae30',
    hdr_language: '\uc5b8\uc5b4',
    theme_light: '\ub77c\uc774\ud2b8 (\uae30\ubcf8)',  theme_dark: '\ub2e4\ud06c',
    theme_dark2: '\ub2e4\ud06c 2',          theme_deuter: '\uc801\ub85d \uc0c9\ub9f9',
    theme_protan: '\uc801\uc0c9 \uc0c9\ub9f9',      theme_tritan: '\uccad\ud669 \uc0c9\ub9f9',
    themedesc_light: '\uae68\ub057\ud55c \ud770 \ubc30\uacbd',
    themedesc_dark: '\uace0\ub300\ube44 \uc5b4\ub450\uc6b4 \ud14c\ub9c8',
    themedesc_dark2: '\ucc28\ubd84\ud55c \uc5b4\ub450\uc6b4 \ud14c\ub9c8',
    themedesc_deuter: '\uc801\ub85d \uc0c9\ub9f9 \uc548\uc804',
    themedesc_protan: '\uc801\uc0c9 \uc0c9\ub9f9 \uc548\uc804',
    themedesc_tritan: '\uccad\ud669 \uc0c9\ub9f9 \uc548\uc804',
    layout_standard: '\ud45c\uc900',      layout_wide: '\ub113\uac8c \ubcf4\uae30',
    layout_compact: '\ucef4\ud329\ud2b8',  layout_focus: '\uc9d1\uc911',
    layoutdesc_standard: '\uc804\uccb4 \ud328\ub110 \ub808\uc774\uc544\uc6c3 (320px \uc0ac\uc774\ub4dc\ubc14)',
    layoutdesc_wide: '\uc0ac\uc774\ub4dc\ubc14 \uc228\uae30\uace0 \ube54\ub77c\uc778 \ubdf0 \ucd5c\ub300\ud654',
    layoutdesc_compact: '\uc88c\uc740 \uc0ac\uc774\ub4dc\ubc14 (220px)',
    layoutdesc_focus: '\ube54\ub77c\uc778\ub9cc \ubcf4\uae30, \ud328\ub110 \uc228\uae40',
    mcrays_fast: '\ube60\ub984 -- \ubbf8\ub9ac\ubcf4\uae30',
    mcrays_normal: '\ubcf4\ud1b5 -- \uc911\uac04 \ud488\uc9c8',
    mcrays_default: '\uae30\ubcf8 -- \ub192\uc740 \ud1b5\uacc4',
    mcrays_precise: '\uc815\ubc00 -- \ub290\ub9bc',
    mcrays_best: '\ucd5c\uace0 \ud488\uc9c8 -- \ub9e4\uc6b0 \ub290\ub9bc',
    grid_standard: '\uae30\ubcf8 -- \ube60\ub978 \ub80c\ub354\ub9c1',
    grid_highres: '4\ubc30 \uc815\ubc00 -- \uc791\uc740 \ube54 \uc0c1\uc138',
    btn_estop: '\uae34\uae09\uc815\uc9c0',    btn_reset: '\ucd08\uae30\ud654',
    btn_start: '\uc2dc\uc791',       btn_stop: '\uc815\uc9c0',
    btn_save: '\uc800\uc7a5',        btn_close: '\ub2eb\uae30',
    btn_apply: '\uc801\uc6a9',       btn_cancel: '\ucde8\uc18c',
    panel_source: '\uad11\uc6d0 \ud30c\ub77c\ubbf8\ud130',
    panel_beamline: '\ube54\ub77c\uc778 \uac1c\uc694',
    panel_profile: '\ube54 \ud504\ub85c\ud544',
    panel_spectrum: '\uc2a4\ud399\ud2b8\ub7fc',
    mode_virtual: '\uac00\uc0c1',   mode_real: '\uc2e4\uc81c',   mode_dual: '\ub4c0\uc5bc',
    // ── Alignment panel ──
    align_ready: '\ub300\uae30',
    align_starting: '\uc2dc\uc791 \uc911...',
    align_scanning: '\uc2a4\uce94 \uc911...',
    align_abort: '\uc911\ub2e8',
    align_export_log: '\ub85c\uadf8 \ub0b4\ubcf4\ub0b4\uae30',
    align_scan_waiting: '\uc2a4\uce94 \ucc28\ud2b8 -- \ub300\uae30 \uc911...',
    align_pass: '\ud1b5\uacfc',
    align_fail: '\uc2e4\ud328',
    align_step_fmt: '\ub2e8\uacc4 {0}/{1}: {2}',
    align_motor_fmt: '\ubaa8\ud130={0}',
    align_intensity_fmt: '\uac15\ub3c4={0}',
    align_centroid_fmt: '\uc911\uc2ec={0} mm',
    align_beam_at: '\ube54 @ {0} ({1}m)',
    align_halfcut: '\ubc18\uc808\ub2e8 (pitch=0)',
    align_halfcut_c1: '\ubc18\uc808\ub2e8 C1 (theta=0)',
    align_set_angle: '\ub3d9\uc791 \uac01\ub3c4 \uc124\uc815',
    align_rot_center: '\ud68c\uc804 \uc911\uc2ec',
    align_set_bragg: 'Bragg \uac01 \uc124\uc815',
    align_dtheta2_coarse: 'dTheta2 \uc870\ub300',
    align_dtheta2_fine: 'dTheta2 \ubbf8\uc138',
    align_m1_full: 'M1 \uc804\uccb4 \uc815\ub82c',
    align_m2_full: 'M2 \uc804\uccb4 \uc815\ub82c',
    align_kbv: 'KB-V \uc815\ub82c',
    align_kbh: 'KB-H \uc815\ub82c',
    align_dcm_full: 'DCM \uc804\uccb4 \uc815\ub82c',
    // ── Experiment panel ──
    expt_start: '\uc2dc\uc791',
    expt_stop: '\uc815\uc9c0',
    expt_show: '\ubcf4\uae30',
    expt_save: '\uc800\uc7a5',
    expt_starting_fmt: '{0} \uc2dc\uc791 \uc911...',
    expt_computing: '\uacc4\uc0b0 \uc911...',
    expt_no_result: '\uc800\uc7a5\ud560 \uacb0\uacfc\uac00 \uc5c6\uc2b5\ub2c8\ub2e4',
    expt_saved_fmt: '\uc800\uc7a5\ub428: {0}',
    expt_ready_msg: '\uc900\ube44 \uc644\ub8cc. \uacb0\uacfc\ub294 \ubcc4\ub3c4 \ud31d\uc5c5 \ucc3d\uc5d0 \ud45c\uc2dc\ub429\ub2c8\ub2e4.',
    expt_server_disc: '\uc2dc\ubbac\ub808\uc774\uc158 \uc11c\ubc84 (\ud3ec\ud2b8 {0}) \ubbf8\uc811\uc18d.',
    expt_beamline_status: '\ube54\ub77c\uc778',
    expt_server_not_connected: '\uc2dc\ubbac\ub808\uc774\uc158 \uc11c\ubc84\uac00 \uc5f0\uacb0\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4',
    expt_formula: '\ud654\ud559\uc2dd',
    expt_absorber: '\ud761\uc218\uccb4',
    expt_edge: '\ud761\uc218\ub2e8',
    expt_e_range: 'E \ubc94\uc704 (eV)',
    expt_e_step: 'E \uc2a4\ud15d',
    expt_presets: '\ud504\ub9ac\uc14b',
    expt_sample: '\uc2dc\ub8cc',
    expt_conc: '\ub18d\ub3c4 (ppm)',
    // ── Bluesky panel ──
    bs_submit_plan: '\ud50c\ub79c \uc81c\ucd9c',
    bs_add_queue: '\ud050\uc5d0 \ucd94\uac00',
    bs_run_now: '\uc989\uc2dc \uc2e4\ud589',
    bs_queue_fmt: '\ud050 ({0})',
    bs_queue_empty: '\ud050\uc5d0 \ud50c\ub79c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4',
    bs_clear: '\uc9c0\uc6b0\uae30',
    bs_run_history_fmt: '\uc2e4\ud589 \uc774\ub825 ({0})',
    bs_quick_run: '\ube60\ub978 \uc2e4\ud589',
    bs_qs_connection: '\ud050 \uc11c\ubc84 \uc5f0\uacb0',
    bs_connected: '[\uc5f0\uacb0\ub428]',
    bs_sim_mode: '[\uc2dc\ubbac\ub808\uc774\uc158 \ubaa8\ub4dc]',
    bs_connect: '\uc5f0\uacb0',
    bs_server_history: '\uc11c\ubc84 \uc2a4\uce94 \uc774\ub825',
    bs_click_refresh: '[\uc0c8\ub85c\uace0\uce68]\uc744 \ud074\ub9ad\ud558\uc5ec \uc11c\ubc84 \uc774\ub825 \ub85c\ub4dc',
    // ── Status ──
    status_idle: '\ub300\uae30',
    status_running: '\uc2e4\ud589 \uc911',
    status_paused: '\uc77c\uc2dc\uc815\uc9c0',
    status_error: '\uc624\ub958',
    status_completed: '\uc644\ub8cc',
    status_aborted: '\uc911\ub2e8',
    // ── Tutorial ──
    tut_basics_name: '\uae30\ubcf8 \uc0ac\uc6a9\ubc95',
    tut_basics_desc: '\ud504\ub85c\uadf8\ub7a8\uc758 \uae30\ubcf8 \uc778\ud130\ud398\uc774\uc2a4\uc640 \uc8fc\uc694 \uae30\ub2a5 \ud559\uc2b5',
    tut_b1_title: '\ud658\uc601\ud569\ub2c8\ub2e4!',
    tut_b1_content: '<p>Korea-4GSR ID10 NanoProbe \uac00\uc0c1 \ube54\ub77c\uc778\uc5d0 \uc624\uc2e0 \uac83\uc744 \ud658\uc601\ud569\ub2c8\ub2e4!</p><p>\uc774 \ud29c\ud1a0\ub9ac\uc5bc\uc740 \uae30\ubcf8 \uc0ac\uc6a9\ubc95\uc744 \ub2e8\uacc4\ubcc4\ub85c \uc548\ub0b4\ud569\ub2c8\ub2e4.</p><p style="color:var(--am)">\uac01 \ub2e8\uacc4\uc758 \uc9c0\uc2dc\ub97c \ub530\ub77c\ud574 \uc8fc\uc138\uc694.</p>',
    tut_b2_title: '1. \ube54\ub77c\uc778 \ub808\uc774\uc544\uc6c3',
    tut_b2_content: '<p>\ud654\uba74 \uc911\uc559\uc5d0 <b>\ub450 \uac00\uc9c0 \ubdf0</b>\uac00 \ud45c\uc2dc\ub429\ub2c8\ub2e4:</p><p>* <span style="color:var(--ac)">\uc704\uc5d0\uc11c \ubcf4\uae30</span> -- \uc218\ud3c9\uba74 (M1/M2 \ubbf8\ub7ec \ubc18\uc0ac)</p><p>* <span style="color:var(--ac)">\uc606\uc5d0\uc11c \ubcf4\uae30</span> -- \uc218\uc9c1\uba74 (DCM Bragg \ud68c\uc808)</p><p style="color:var(--gn)">\uad6c\uc131 \uc694\uc18c\ub97c \ud074\ub9ad\ud558\uba74 \uc0c1\uc138 \uc815\ubcf4\uc640 \uc81c\uc5b4 \ud328\ub110\uc774 \uc5f4\ub9bd\ub2c8\ub2e4.</p>',
    tut_b3_title: '2. \uc5d0\ub108\uc9c0 \uc124\uc815',
    tut_b3_content: '<p>\uc624\ub978\ucabd \uc0ac\uc774\ub4dc\ubc14\uc758 <b>IVU \ud0ed</b>\uc5d0\uc11c \ubaa9\ud45c \uc5d0\ub108\uc9c0\ub97c \uc124\uc815\ud569\ub2c8\ub2e4.</p><p style="color:var(--am)">\uc2ac\ub77c\uc774\ub354\ub97c \ub4dc\ub798\uadf8\ud558\uc5ec 10 keV\ub85c \uc124\uc815\ud574 \ubcf4\uc138\uc694.</p><p>\uc2dc\uc2a4\ud15c\uc774 \uc790\ub3d9\uc73c\ub85c:</p><p>* \ucd5c\uc801 \uace0\uc870\ud30c \uc120\ud0dd</p><p>* IVU \uac2d \uc870\uc815</p><p>* DCM Bragg \uac01 \uacc4\uc0b0</p>',
    tut_b4_title: '3. \uad11\ud559 \uc694\uc18c \uc870\uc815',
    tut_b4_content: '<p><b>\uad11\ud559 \ud0ed</b>\uc5d0\uc11c \ube54\ub77c\uc778 \uad11\ud559\uc744 \uc870\uc815\ud569\ub2c8\ub2e4:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- \ubc31\uc0c9\uad11 \uc2ac\ub9bf \ud06c\uae30</p><p>* <span style="color:var(--ac)">M1/M2</span> -- \uc218\ud3c9 \ud3b8\ud5a5 \ubbf8\ub7ec \uac01\ub3c4</p><p>* <span style="color:var(--ac)">SSA</span> -- 2\ucc28 \uc2ac\ub9bf (KB \uac00\uc0c1 \uad11\uc6d0)</p><p>* <span style="color:var(--ac)">KB</span> -- \ucd5c\uc885 \uc9d1\uc18d \uacb0\uacfc</p><p style="color:var(--am)">\uad11\ud559 \ud0ed\uc744 \ud074\ub9ad\ud574 \ubcf4\uc138\uc694.</p>',
    tut_b5_title: '4. \uc0c1\ud0dc \ubaa8\ub2c8\ud130\ub9c1',
    tut_b5_content: '<p>\ud558\ub2e8 \uc0c1\ud0dc \ubc14\uc5d0\uc11c \uc2e4\uc2dc\uac04 \ube54 \uc815\ubcf4\ub97c \ud655\uc778\ud569\ub2c8\ub2e4:</p><p>* <span style="color:var(--ac)">E</span> -- \ud604\uc7ac \uc5d0\ub108\uc9c0</p><p>* <span style="color:var(--gn)">Flux</span> -- \uad11\uc790 \ud50c\ub7ed\uc2a4</p><p>* <span style="color:var(--pk)">Spot</span> -- \ucd08\uc810 \uc2a4\ud31f \ud06c\uae30</p><p>\uac01 \uad6c\uc131 \uc694\uc18c \uc704\uce58\uc758 \ube54 \ud06c\uae30\ub3c4 \ud45c\uc2dc\ub429\ub2c8\ub2e4.</p>',
    tut_b6_title: '5. \uce21\uc815 \uc2e4\ud589',
    tut_b6_content: '<p><b>\uce21\uc815 \ud0ed</b>\uc5d0\uc11c \uac00\uc0c1 \uc2e4\ud5d8\uc744 \uc2e4\ud589\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4:</p><p>* XANES -- \ud761\uc218 \uc2a4\ud399\ud2b8\ub7fc</p><p>* XRD -- \ud68c\uc808 \ud328\ud134</p><p>* XRF -- \ud615\uad11 \uc2a4\ud399\ud2b8\ub7fc</p><p>* 2D \ub9f5 -- \uacf5\uac04 \ub9e4\ud551</p><p style="color:var(--gn)">\uc2dc\uc791 \ubc84\ud2bc\uc744 \ub20c\ub7ec \uc2a4\uce94\uc744 \uc2dc\uc791\ud558\uc138\uc694.</p>',
    tut_b7_title: '6. Bluesky \uc2e4\ud5d8 \ud050',
    tut_b7_content: '<p><b>BS \ud0ed</b>\uc5d0\uc11c Bluesky \uc2a4\ud0c0\uc77c \uc2e4\ud5d8\uc744 \uad00\ub9ac\ud569\ub2c8\ub2e4:</p><p>* \ud50c\ub79c\uc744 \uc120\ud0dd\ud558\uace0 \ud30c\ub77c\ubbf8\ud130 \uc124\uc815</p><p>* \ud050\uc5d0 \ucd94\uac00\ud558\uc5ec \uc21c\ucc28 \uc2e4\ud589</p><p>* \uc2e4\uc2dc\uac04 \uc9c4\ud589 \ubaa8\ub2c8\ud130\ub9c1</p><p style="color:var(--pr)">Quick Run \ubc84\ud2bc\uc73c\ub85c \uc989\uc2dc \uc2e4\ud589\ud560 \uc218\ub3c4 \uc788\uc2b5\ub2c8\ub2e4.</p>',
    tut_b8_title: '7. \ubaa8\ub4dc \uc804\ud658',
    tut_b8_content: '<p>\uc0c1\ub2e8 \ubc14\uc758 \ubaa8\ub4dc \ubc84\ud2bc\uc73c\ub85c \uc6b4\uc601 \ubaa8\ub4dc\ub97c \uc804\ud658\ud569\ub2c8\ub2e4:</p><p>* <span style="color:var(--gn)">\uac00\uc0c1</span> -- \uc2dc\ubbac\ub808\uc774\uc158\ub9cc</p><p>* <span style="color:var(--am)">\uc2e4\uc81c</span> -- \uc2e4\uc81c EPICS IOC \uc5f0\uacb0</p><p>* <span style="color:var(--ac)">\ub4c0\uc5bc</span> -- \uac00\uc0c1/\uc2e4\uc81c \ube44\uad50 \ubaa8\ub4dc</p><p>\ucc98\uc74c \uc0ac\uc6a9 \uc2dc \uac00\uc0c1 \ubaa8\ub4dc\uc5d0\uc11c \uc5f0\uc2b5 \ud6c4 \uc2e4\uc81c\ub85c \uc804\ud658\ud558\uc138\uc694.</p>',
    tut_b9_title: '\uae30\ubcf8 \ud29c\ud1a0\ub9ac\uc5bc \uc644\ub8cc!',
    tut_b9_content: '<p style="color:var(--gn)">\ucd95\ud558\ud569\ub2c8\ub2e4! \uae30\ubcf8 \uc0ac\uc6a9\ubc95\uc744 \uc775\ud788\uc168\uc2b5\ub2c8\ub2e4.</p><p>\ub2e4\uc74c \ub2e8\uacc4\ub85c \uc9c4\ud589\ud558\uc138\uc694:</p><p>* <b>\uac00\uc0c1 \uc2e4\ud5d8</b> -- \uc2e4\uc81c \uc2e4\ud5d8 \uc2dc\ubbac\ub808\uc774\uc158</p><p>* <b>EPICS \uc5f0\ub3d9</b> -- \uc2e4\uc81c \uc7a5\ube44 \uc5f0\uacb0</p><p>* <b>\uac00\uc0c1/\uc2e4\uc81c \ube44\uad50</b> -- \uc2dc\ubbac\ub808\uc774\uc158\uacfc \uc2e4\uc81c \ube44\uad50</p>',
    tut_exp_name: '\uac00\uc0c1 \uc2e4\ud5d8 \uc5f0\uc2b5',
    tut_exp_desc: '\uac01 \uce21\uc815 \uae30\ubc95\ubcc4 \uac00\uc0c1 \uc2e4\ud5d8 \uc218\ud589',
    tut_e1_title: 'Cu K-edge XANES \uc2e4\ud5d8',
    tut_e1_content: '<p>\uc774 \uc5f0\uc2b5\uc5d0\uc11c\ub294 <b>Cu K-edge XANES</b> \uce21\uc815\uc744 \uc218\ud589\ud569\ub2c8\ub2e4.</p><p style="color:var(--am)">"\uc790\ub3d9 \uc124\uc815" \ubc84\ud2bc\uc744 \ub20c\ub7ec \uc2e4\ud5d8\uc744 \uc790\ub3d9\uc73c\ub85c \uad6c\uc131\ud569\ub2c8\ub2e4.</p>',
    tut_e2_title: 'XANES \uc2a4\uce94 \uc2e4\ud589',
    tut_e2_content: '<p>\uc5d0\ub108\uc9c0\uac00 Cu K-edge (8.979 keV)\ub85c \uc124\uc815\ub418\uc5c8\uc2b5\ub2c8\ub2e4.</p><p style="color:var(--am)">BS \ud0ed\uc5d0\uc11c XANES \ubc84\ud2bc\uc744 \ub20c\ub7ec \uc2a4\uce94\uc744 \uc2dc\uc791\ud558\uc138\uc694.</p><p>\uc2a4\uce94 \uc644\ub8cc \uc2dc µ(E) \uc2a4\ud399\ud2b8\ub7fc\uc774 \ud558\ub2e8 \ud328\ub110\uc5d0 \ud45c\uc2dc\ub429\ub2c8\ub2e4.</p>',
    tut_e3_title: 'XRF \uc774\ubbf8\uc9d5 \uc2e4\ud5d8',
    tut_e3_content: '<p>\uc774\uc81c <b>XRF \uc774\ubbf8\uc9d5</b>\uc744 \uc218\ud589\ud569\ub2c8\ub2e4.</p><p>SDD \uac80\ucd9c\uae30\uac00 \uc2dc\ub8cc\uc5d0\uc11c 90\ub3c4\ub85c \ud615\uad11 X-\uc120\uc744 \uc218\uc9d1\ud569\ub2c8\ub2e4.</p><p style="color:var(--am)">\uc790\ub3d9 \uc124\uc815 \ud6c4 \ub798\uc2a4\ud130 \uc2a4\uce94\uc73c\ub85c \uc6d0\uc18c \ubd84\ud3ec \ub9f5\uc774 \uc0dd\uc131\ub429\ub2c8\ub2e4.</p>',
    tut_e4_title: '\ubd84\ub9d0 XRD \uc2e4\ud5d8',
    tut_e4_content: '<p><b>\ubd84\ub9d0 XRD</b> \uce21\uc815\uc744 \uc218\ud589\ud569\ub2c8\ub2e4.</p><p>Eiger 2X \uac80\ucd9c\uae30\uac00 Debye-Scherrer \ub9c1 \ud328\ud134\uc744 \uc218\uc9d1\ud569\ub2c8\ub2e4.</p>',
    tut_prev: '\uc774\uc804', tut_next: '\ub2e4\uc74c', tut_done: '\uc644\ub8cc'
  },
  ja: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u5149\u5b66',
    tab_motors: '\u30e2\u30fc\u30bf',  tab_mask: '\u30de\u30b9\u30af', tab_measure: '\u6e2c\u5b9a',
    tab_align: '\u6574\u5217',   tab_compare: '\u6bd4\u8f03',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\u30ac\u30a4\u30c9', tab_chat: '\u30c1\u30e3\u30c3\u30c8',
    tab_expt: '\u5b9f\u9a13',
    hdr_theme: '\u30ab\u30e9\u30fc\u30c6\u30fc\u30de',  hdr_layout: '\u30ec\u30a4\u30a2\u30a6\u30c8',
    hdr_mcrays: 'MC \u5149\u7dda',  hdr_grid: '\u30b0\u30ea\u30c3\u30c9\u89e3\u50cf\u5ea6',
    hdr_language: '\u8a00\u8a9e',
    theme_light: '\u30e9\u30a4\u30c8\uff08\u30c7\u30d5\u30a9\u30eb\u30c8\uff09',  theme_dark: '\u30c0\u30fc\u30af',
    theme_dark2: '\u30c0\u30fc\u30af 2',       theme_deuter: '\u7dd1\u8d64\u8272\u89c8',
    theme_protan: '\u8d64\u8272\u89c8',         theme_tritan: '\u9752\u9ec4\u8272\u89c8',
    themedesc_light: '\u6e05\u6f54\u306a\u767d\u3044\u80cc\u666f',
    themedesc_dark: '\u9ad8\u30b3\u30f3\u30c8\u30e9\u30b9\u30c8\u306e\u30c0\u30fc\u30af\u30c6\u30fc\u30de',
    themedesc_dark2: '\u843d\u3061\u7740\u3044\u305f\u30c0\u30fc\u30af\u30c6\u30fc\u30de',
    themedesc_deuter: '\u7dd1\u8d64\u8272\u89c8\u5bfe\u5fdc',
    themedesc_protan: '\u8d64\u8272\u89c8\u5bfe\u5fdc',
    themedesc_tritan: '\u9752\u9ec4\u8272\u89c8\u5bfe\u5fdc',
    layout_standard: '\u6a19\u6e96',       layout_wide: '\u30ef\u30a4\u30c9\u30d3\u30e5\u30fc',
    layout_compact: '\u30b3\u30f3\u30d1\u30af\u30c8', layout_focus: '\u30d5\u30a9\u30fc\u30ab\u30b9',
    layoutdesc_standard: '\u30d5\u30eb\u30d1\u30cd\u30eb\u30ec\u30a4\u30a2\u30a6\u30c8 (320px\u30b5\u30a4\u30c9\u30d0\u30fc)',
    layoutdesc_wide: '\u30b5\u30a4\u30c9\u30d0\u30fc\u3092\u96a0\u3057\u30d3\u30fc\u30e0\u30e9\u30a4\u30f3\u30d3\u30e5\u30fc\u3092\u6700\u5927\u5316',
    layoutdesc_compact: '\u72ed\u3044\u30b5\u30a4\u30c9\u30d0\u30fc (220px)',
    layoutdesc_focus: '\u30d3\u30fc\u30e0\u30e9\u30a4\u30f3\u306e\u307f\u8868\u793a',
    mcrays_fast: '\u9ad8\u901f -- \u30d7\u30ec\u30d3\u30e5\u30fc',
    mcrays_normal: '\u901a\u5e38 -- \u4e2d\u7a0b\u5ea6\u306e\u54c1\u8cea',
    mcrays_default: '\u30c7\u30d5\u30a9\u30eb\u30c8 -- \u9ad8\u7d71\u8a08',
    mcrays_precise: '\u7cbe\u5bc6 -- \u4f4e\u901f',
    mcrays_best: '\u6700\u9ad8\u54c1\u8cea -- \u975e\u5e38\u306b\u4f4e\u901f',
    grid_standard: '\u30c7\u30d5\u30a9\u30eb\u30c8 -- \u9ad8\u901f\u63cf\u753b',
    grid_highres: '4\u500d\u7cbe\u5bc6 -- \u5c0f\u3055\u306a\u30d3\u30fc\u30e0\u306e\u8a73\u7d30',
    btn_estop: '\u7dca\u6025\u505c\u6b62',     btn_reset: '\u30ea\u30bb\u30c3\u30c8',
    btn_start: '\u958b\u59cb',        btn_stop: '\u505c\u6b62',
    btn_save: '\u4fdd\u5b58',         btn_close: '\u9589\u3058\u308b',
    btn_apply: '\u9069\u7528',        btn_cancel: '\u30ad\u30e3\u30f3\u30bb\u30eb',
    panel_source: '\u5149\u6e90\u30d1\u30e9\u30e1\u30fc\u30bf',
    panel_beamline: '\u30d3\u30fc\u30e0\u30e9\u30a4\u30f3\u6982\u8981',
    panel_profile: '\u30d3\u30fc\u30e0\u30d7\u30ed\u30d5\u30a1\u30a4\u30eb',
    panel_spectrum: '\u30b9\u30da\u30af\u30c8\u30eb',
    mode_virtual: '\u4eee\u60f3',    mode_real: '\u5b9f\u6a5f',    mode_dual: '\u30c7\u30e5\u30a2\u30eb',
    align_ready: '\u6e96\u5099\u5b8c\u4e86', align_starting: '\u958b\u59cb\u4e2d...', align_scanning: '\u30b9\u30ad\u30e3\u30f3\u4e2d...', align_abort: '\u4e2d\u6b62', align_export_log: '\u30ed\u30b0\u51fa\u529b',
    align_scan_waiting: '\u30b9\u30ad\u30e3\u30f3\u30c1\u30e3\u30fc\u30c8 -- \u5f85\u6a5f\u4e2d...', align_pass: '\u5408\u683c', align_fail: '\u5931\u6557',
    align_step_fmt: '\u30b9\u30c6\u30c3\u30d7 {0}/{1}: {2}', align_motor_fmt: '\u30e2\u30fc\u30bf={0}', align_intensity_fmt: '\u5f37\u5ea6={0}',
    align_centroid_fmt: '\u91cd\u5fc3={0} mm', align_beam_at: '\u30d3\u30fc\u30e0 @ {0} ({1}m)',
    align_halfcut: '\u30cf\u30fc\u30d5\u30ab\u30c3\u30c8 (pitch=0)', align_halfcut_c1: '\u30cf\u30fc\u30d5\u30ab\u30c3\u30c8 C1 (theta=0)',
    align_set_angle: '\u52d5\u4f5c\u89d2\u5ea6\u8a2d\u5b9a', align_rot_center: '\u56de\u8ee2\u4e2d\u5fc3', align_set_bragg: 'Bragg\u89d2\u8a2d\u5b9a',
    align_dtheta2_coarse: 'dTheta2 \u7c97\u8abf\u6574', align_dtheta2_fine: 'dTheta2 \u5fae\u8abf\u6574',
    align_m1_full: 'M1 \u5168\u4f53\u30a2\u30e9\u30a4\u30e1\u30f3\u30c8', align_m2_full: 'M2 \u5168\u4f53\u30a2\u30e9\u30a4\u30e1\u30f3\u30c8',
    align_kbv: 'KB-V \u30a2\u30e9\u30a4\u30e1\u30f3\u30c8', align_kbh: 'KB-H \u30a2\u30e9\u30a4\u30e1\u30f3\u30c8', align_dcm_full: 'DCM \u5168\u4f53\u30a2\u30e9\u30a4\u30e1\u30f3\u30c8',
    expt_start: '\u958b\u59cb', expt_stop: '\u505c\u6b62', expt_show: '\u8868\u793a', expt_save: '\u4fdd\u5b58',
    expt_starting_fmt: '{0} \u958b\u59cb\u4e2d...', expt_computing: '\u8a08\u7b97\u4e2d...', expt_no_result: '\u4fdd\u5b58\u3059\u308b\u7d50\u679c\u304c\u3042\u308a\u307e\u305b\u3093',
    expt_saved_fmt: '\u4fdd\u5b58\u6e08\u307f: {0}', expt_ready_msg: '\u6e96\u5099\u5b8c\u4e86\u3002\u7d50\u679c\u306f\u5225\u30a6\u30a3\u30f3\u30c9\u30a6\u306b\u8868\u793a\u3055\u308c\u307e\u3059\u3002',
    expt_server_disc: '\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3\u30b5\u30fc\u30d0\u30fc (\u30dd\u30fc\u30c8 {0}) \u672a\u63a5\u7d9a\u3002',
    expt_beamline_status: '\u30d3\u30fc\u30e0\u30e9\u30a4\u30f3', expt_server_not_connected: '\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3\u30b5\u30fc\u30d0\u30fc\u672a\u63a5\u7d9a',
    expt_formula: '\u5316\u5b66\u5f0f', expt_absorber: '\u5438\u53ce\u4f53', expt_edge: '\u5438\u53ce\u7aef', expt_e_range: 'E \u7bc4\u56f2 (eV)', expt_e_step: 'E \u30b9\u30c6\u30c3\u30d7',
    expt_presets: '\u30d7\u30ea\u30bb\u30c3\u30c8', expt_sample: '\u8a66\u6599', expt_conc: '\u6fc3\u5ea6 (ppm)',
    bs_submit_plan: '\u30d7\u30e9\u30f3\u9001\u4fe1', bs_add_queue: '\u30ad\u30e5\u30fc\u306b\u8ffd\u52a0', bs_run_now: '\u5373\u5b9f\u884c', bs_queue_fmt: '\u30ad\u30e5\u30fc ({0})',
    bs_queue_empty: '\u30ad\u30e5\u30fc\u306b\u30d7\u30e9\u30f3\u304c\u3042\u308a\u307e\u305b\u3093', bs_clear: '\u30af\u30ea\u30a2', bs_run_history_fmt: '\u5b9f\u884c\u5c65\u6b74 ({0})',
    bs_quick_run: '\u30af\u30a4\u30c3\u30af\u5b9f\u884c', bs_qs_connection: '\u30ad\u30e5\u30fc\u30b5\u30fc\u30d0\u30fc\u63a5\u7d9a', bs_connected: '[\u63a5\u7d9a\u6e08\u307f]',
    bs_sim_mode: '[\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3\u30e2\u30fc\u30c9]', bs_connect: '\u63a5\u7d9a', bs_server_history: '\u30b5\u30fc\u30d0\u30fc\u30b9\u30ad\u30e3\u30f3\u5c65\u6b74',
    bs_click_refresh: '[\u66f4\u65b0]\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u30b5\u30fc\u30d0\u30fc\u5c65\u6b74\u3092\u8aad\u307f\u8fbc\u307f',
    status_idle: '\u5f85\u6a5f', status_running: '\u5b9f\u884c\u4e2d', status_paused: '\u4e00\u6642\u505c\u6b62', status_error: '\u30a8\u30e9\u30fc',
    status_completed: '\u5b8c\u4e86', status_aborted: '\u4e2d\u6b62',
    tut_basics_name: '\u57fa\u672c\u64cd\u4f5c', tut_basics_desc: '\u30d7\u30ed\u30b0\u30e9\u30e0\u306e\u57fa\u672c\u30a4\u30f3\u30bf\u30fc\u30d5\u30a7\u30fc\u30b9\u3068\u4e3b\u8981\u6a5f\u80fd\u3092\u5b66\u3076',
    tut_b1_title: '\u3088\u3046\u3053\u305d!', tut_b2_title: '1. \u30d3\u30fc\u30e0\u30e9\u30a4\u30f3\u30ec\u30a4\u30a2\u30a6\u30c8', tut_b3_title: '2. \u30a8\u30cd\u30eb\u30ae\u30fc\u8a2d\u5b9a',
    tut_b4_title: '3. \u5149\u5b66\u7d20\u5b50\u8abf\u6574', tut_b5_title: '4. \u30b9\u30c6\u30fc\u30bf\u30b9\u30e2\u30cb\u30bf\u30ea\u30f3\u30b0', tut_b6_title: '5. \u6e2c\u5b9a\u5b9f\u884c',
    tut_b7_title: '6. Bluesky \u5b9f\u9a13\u30ad\u30e5\u30fc', tut_b8_title: '7. \u30e2\u30fc\u30c9\u5207\u66ff', tut_b9_title: '\u57fa\u672c\u30c1\u30e5\u30fc\u30c8\u30ea\u30a2\u30eb\u5b8c\u4e86!',
    tut_exp_name: '\u4eee\u60f3\u5b9f\u9a13\u7df4\u7fd2', tut_exp_desc: '\u5404\u6e2c\u5b9a\u6280\u6cd5\u306e\u4eee\u60f3\u5b9f\u9a13\u3092\u5b9f\u65bd',
    tut_e1_title: 'Cu K-edge XANES \u5b9f\u9a13', tut_e2_title: 'XANES \u30b9\u30ad\u30e3\u30f3\u5b9f\u884c',
    tut_e3_title: 'XRF \u30a4\u30e1\u30fc\u30b8\u30f3\u30b0\u5b9f\u9a13', tut_e4_title: '\u7c89\u672b XRD \u5b9f\u9a13',
    tut_prev: '\u524d\u3078', tut_next: '\u6b21\u3078', tut_done: '\u5b8c\u4e86'
  },
  zh: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u5149\u5b66',
    tab_motors: '\u7535\u673a',  tab_mask: '\u63a9\u819c', tab_measure: '\u6d4b\u91cf',
    tab_align: '\u5bf9\u51c6',   tab_compare: '\u6bd4\u8f83',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\u6307\u5357', tab_chat: '\u804a\u5929',
    tab_expt: '\u5b9e\u9a8c',
    hdr_theme: '\u989c\u8272\u4e3b\u9898',  hdr_layout: '\u5e03\u5c40',
    hdr_mcrays: 'MC \u5149\u7ebf',  hdr_grid: '\u7f51\u683c\u5206\u8fa8\u7387',
    hdr_language: '\u8bed\u8a00',
    theme_light: '\u6d45\u8272\uff08\u9ed8\u8ba4\uff09',  theme_dark: '\u6df1\u8272',
    theme_dark2: '\u6df1\u8272 2',        theme_deuter: '\u7ea2\u7eff\u8272\u76f2',
    theme_protan: '\u7ea2\u8272\u76f2',       theme_tritan: '\u84dd\u9ec4\u8272\u76f2',
    themedesc_light: '\u6e05\u6d01\u7684\u767d\u8272\u80cc\u666f',
    themedesc_dark: '\u9ad8\u5bf9\u6bd4\u5ea6\u6df1\u8272\u4e3b\u9898',
    themedesc_dark2: '\u67d4\u548c\u7684\u6df1\u8272\u4e3b\u9898',
    themedesc_deuter: '\u7ea2\u7eff\u8272\u76f2\u5b89\u5168',
    themedesc_protan: '\u7ea2\u8272\u76f2\u5b89\u5168',
    themedesc_tritan: '\u84dd\u9ec4\u8272\u76f2\u5b89\u5168',
    layout_standard: '\u6807\u51c6',       layout_wide: '\u5bbd\u89c6\u56fe',
    layout_compact: '\u7d27\u51d1',  layout_focus: '\u4e13\u6ce8',
    layoutdesc_standard: '\u5168\u9762\u677f\u5e03\u5c40 (320px\u4fa7\u8fb9\u680f)',
    layoutdesc_wide: '\u9690\u85cf\u4fa7\u8fb9\u680f\uff0c\u6700\u5927\u5316\u5149\u675f\u7ebf\u89c6\u56fe',
    layoutdesc_compact: '\u7a84\u4fa7\u8fb9\u680f (220px)',
    layoutdesc_focus: '\u4ec5\u663e\u793a\u5149\u675f\u7ebf\uff0c\u9690\u85cf\u6240\u6709\u9762\u677f',
    mcrays_fast: '\u5feb\u901f -- \u9884\u89c8',
    mcrays_normal: '\u6b63\u5e38 -- \u4e2d\u7b49\u8d28\u91cf',
    mcrays_default: '\u9ed8\u8ba4 -- \u9ad8\u7edf\u8ba1',
    mcrays_precise: '\u7cbe\u786e -- \u8f83\u6162',
    mcrays_best: '\u6700\u4f73\u8d28\u91cf -- \u975e\u5e38\u6162',
    grid_standard: '\u9ed8\u8ba4 -- \u5feb\u901f\u6e32\u67d3',
    grid_highres: '4\u500d\u7cbe\u7ec6 -- \u5c0f\u5149\u675f\u7ec6\u8282',
    btn_estop: '\u7d27\u6025\u505c\u6b62',     btn_reset: '\u91cd\u7f6e',
    btn_start: '\u5f00\u59cb',        btn_stop: '\u505c\u6b62',
    btn_save: '\u4fdd\u5b58',         btn_close: '\u5173\u95ed',
    btn_apply: '\u5e94\u7528',        btn_cancel: '\u53d6\u6d88',
    panel_source: '\u5149\u6e90\u53c2\u6570',
    panel_beamline: '\u5149\u675f\u7ebf\u6982\u89c8',
    panel_profile: '\u5149\u675f\u8f6e\u5ed3',
    panel_spectrum: '\u5149\u8c31',
    mode_virtual: '\u865a\u62df',    mode_real: '\u5b9e\u9645',    mode_dual: '\u53cc\u6a21\u5f0f',
    align_ready: '\u5c31\u7eea', align_starting: '\u542f\u52a8\u4e2d...', align_scanning: '\u626b\u63cf\u4e2d...', align_abort: '\u4e2d\u6b62', align_export_log: '\u5bfc\u51fa\u65e5\u5fd7',
    align_scan_waiting: '\u626b\u63cf\u56fe\u8868 -- \u7b49\u5f85\u4e2d...', align_pass: '\u901a\u8fc7', align_fail: '\u5931\u8d25',
    align_step_fmt: '\u6b65\u9aa4 {0}/{1}: {2}', align_motor_fmt: '\u7535\u673a={0}', align_intensity_fmt: '\u5f3a\u5ea6={0}',
    align_centroid_fmt: '\u8d28\u5fc3={0} mm', align_beam_at: '\u5149\u675f @ {0} ({1}m)',
    align_halfcut: '\u534a\u5207 (pitch=0)', align_halfcut_c1: '\u534a\u5207 C1 (theta=0)',
    align_set_angle: '\u8bbe\u5b9a\u5de5\u4f5c\u89d2\u5ea6', align_rot_center: '\u65cb\u8f6c\u4e2d\u5fc3', align_set_bragg: '\u8bbe\u5b9a Bragg \u89d2',
    align_dtheta2_coarse: 'dTheta2 \u7c97\u8c03', align_dtheta2_fine: 'dTheta2 \u7cbe\u8c03',
    align_m1_full: 'M1 \u5168\u5bf9\u51c6', align_m2_full: 'M2 \u5168\u5bf9\u51c6',
    align_kbv: 'KB-V \u5bf9\u51c6', align_kbh: 'KB-H \u5bf9\u51c6', align_dcm_full: 'DCM \u5168\u5bf9\u51c6',
    expt_start: '\u5f00\u59cb', expt_stop: '\u505c\u6b62', expt_show: '\u663e\u793a', expt_save: '\u4fdd\u5b58',
    expt_starting_fmt: '\u6b63\u5728\u542f\u52a8 {0}...', expt_computing: '\u8ba1\u7b97\u4e2d...', expt_no_result: '\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u7ed3\u679c',
    expt_saved_fmt: '\u5df2\u4fdd\u5b58: {0}', expt_ready_msg: '\u5c31\u7eea\u3002\u7ed3\u679c\u5c06\u5728\u5355\u72ec\u7684\u5f39\u7a97\u4e2d\u663e\u793a\u3002',
    expt_server_disc: '\u4eff\u771f\u670d\u52a1\u5668 (\u7aef\u53e3 {0}) \u672a\u8fde\u63a5\u3002',
    expt_beamline_status: '\u5149\u675f\u7ebf', expt_server_not_connected: '\u4eff\u771f\u670d\u52a1\u5668\u672a\u8fde\u63a5',
    expt_formula: '\u5316\u5b66\u5f0f', expt_absorber: '\u5438\u6536\u4f53', expt_edge: '\u5438\u6536\u8fb9', expt_e_range: 'E \u8303\u56f4 (eV)', expt_e_step: 'E \u6b65\u957f',
    expt_presets: '\u9884\u8bbe', expt_sample: '\u6837\u54c1', expt_conc: '\u6d53\u5ea6 (ppm)',
    bs_submit_plan: '\u63d0\u4ea4\u65b9\u6848', bs_add_queue: '\u52a0\u5165\u961f\u5217', bs_run_now: '\u7acb\u5373\u8fd0\u884c', bs_queue_fmt: '\u961f\u5217 ({0})',
    bs_queue_empty: '\u961f\u5217\u4e2d\u6ca1\u6709\u65b9\u6848', bs_clear: '\u6e05\u9664', bs_run_history_fmt: '\u8fd0\u884c\u5386\u53f2 ({0})',
    bs_quick_run: '\u5feb\u901f\u8fd0\u884c', bs_qs_connection: '\u961f\u5217\u670d\u52a1\u5668\u8fde\u63a5', bs_connected: '[\u5df2\u8fde\u63a5]',
    bs_sim_mode: '[\u4eff\u771f\u6a21\u5f0f]', bs_connect: '\u8fde\u63a5', bs_server_history: '\u670d\u52a1\u5668\u626b\u63cf\u5386\u53f2',
    bs_click_refresh: '\u70b9\u51fb[\u5237\u65b0]\u52a0\u8f7d\u670d\u52a1\u5668\u5386\u53f2',
    status_idle: '\u7a7a\u95f2', status_running: '\u8fd0\u884c\u4e2d', status_paused: '\u6682\u505c', status_error: '\u9519\u8bef',
    status_completed: '\u5b8c\u6210', status_aborted: '\u4e2d\u6b62',
    tut_basics_name: '\u57fa\u672c\u4f7f\u7528', tut_basics_desc: '\u5b66\u4e60\u7a0b\u5e8f\u7684\u57fa\u672c\u754c\u9762\u548c\u4e3b\u8981\u529f\u80fd',
    tut_b1_title: '\u6b22\u8fce!', tut_b2_title: '1. \u5149\u675f\u7ebf\u5e03\u5c40', tut_b3_title: '2. \u80fd\u91cf\u8bbe\u7f6e',
    tut_b4_title: '3. \u5149\u5b66\u5143\u4ef6\u8c03\u6574', tut_b5_title: '4. \u72b6\u6001\u76d1\u63a7', tut_b6_title: '5. \u8fd0\u884c\u6d4b\u91cf',
    tut_b7_title: '6. Bluesky \u5b9e\u9a8c\u961f\u5217', tut_b8_title: '7. \u6a21\u5f0f\u5207\u6362', tut_b9_title: '\u57fa\u7840\u6559\u7a0b\u5b8c\u6210!',
    tut_b1_content: '<p>\u6b22\u8fce\u6765\u5230 Korea-4GSR ID10 NanoProbe \u865a\u62df\u5149\u675f\u7ebf!</p><p>\u672c\u6559\u7a0b\u5c06\u9010\u6b65\u6307\u5bfc\u60a8\u57fa\u672c\u4f7f\u7528\u3002</p><p style="color:var(--am)">\u8bf7\u6309\u7167\u6bcf\u4e2a\u6b65\u9aa4\u7684\u8bf4\u660e\u64cd\u4f5c\u3002</p>',
    tut_b2_content: '<p>\u5c4f\u5e55\u4e2d\u592e\u663e\u793a<b>\u4e24\u4e2a\u89c6\u56fe</b>:</p><p>* <span style="color:var(--ac)">\u4fef\u89c6\u56fe</span> -- \u6c34\u5e73\u9762 (M1/M2 \u955c\u9762\u53cd\u5c04)</p><p>* <span style="color:var(--ac)">\u4fa7\u89c6\u56fe</span> -- \u5782\u76f4\u9762 (DCM Bragg \u8861\u5c04)</p><p style="color:var(--gn)">\u70b9\u51fb\u4efb\u4e00\u7ec4\u4ef6\u53ef\u6253\u5f00\u8be6\u60c5\u548c\u63a7\u5236\u9762\u677f\u3002</p>',
    tut_b3_content: '<p>\u5728\u53f3\u4fa7\u8fb9\u680f\u7684 <b>IVU \u9009\u9879\u5361</b>\u4e2d\u8bbe\u7f6e\u76ee\u6807\u80fd\u91cf\u3002</p><p style="color:var(--am)">\u62d6\u52a8\u6ed1\u5757\u8bbe\u7f6e\u4e3a 10 keV\u3002</p><p>\u7cfb\u7edf\u5c06\u81ea\u52a8:</p><p>* \u9009\u62e9\u6700\u4f73\u8c10\u6ce2</p><p>* \u8c03\u6574 IVU \u95f4\u8ddd</p><p>* \u8ba1\u7b97 DCM Bragg \u89d2</p>',
    tut_b4_content: '<p>\u5728 <b>\u5149\u5b66\u9009\u9879\u5361</b>\u4e2d\u8c03\u6574\u5149\u675f\u7ebf\u5149\u5b66:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- \u767d\u5149\u72ed\u7f1d\u5927\u5c0f</p><p>* <span style="color:var(--ac)">M1/M2</span> -- \u6c34\u5e73\u504f\u8f6c\u955c\u89d2\u5ea6</p><p>* <span style="color:var(--ac)">SSA</span> -- \u4e8c\u6b21\u72ed\u7f1d (KB \u865a\u62df\u5149\u6e90)</p><p>* <span style="color:var(--ac)">KB</span> -- \u6700\u7ec8\u805a\u7126\u7ed3\u679c</p><p style="color:var(--am)">\u8bf7\u70b9\u51fb\u5149\u5b66\u9009\u9879\u5361\u3002</p>',
    tut_b5_content: '<p>\u5728\u5e95\u90e8\u72b6\u6001\u680f\u67e5\u770b\u5b9e\u65f6\u5149\u675f\u4fe1\u606f:</p><p>* <span style="color:var(--ac)">E</span> -- \u5f53\u524d\u80fd\u91cf</p><p>* <span style="color:var(--gn)">Flux</span> -- \u5149\u5b50\u901a\u91cf</p><p>* <span style="color:var(--pk)">Spot</span> -- \u7126\u70b9\u5149\u6591\u5927\u5c0f</p><p>\u5404\u7ec4\u4ef6\u4f4d\u7f6e\u7684\u5149\u675f\u5c3a\u5bf8\u4e5f\u4f1a\u663e\u793a\u3002</p>',
    tut_b6_content: '<p>\u5728 <b>\u6d4b\u91cf\u9009\u9879\u5361</b>\u4e2d\u8fd0\u884c\u865a\u62df\u5b9e\u9a8c:</p><p>* XANES -- \u5438\u6536\u8c31</p><p>* XRD -- \u8861\u5c04\u56fe\u6837</p><p>* XRF -- \u8367\u5149\u8c31</p><p>* 2D \u6620\u5c04 -- \u7a7a\u95f4\u626b\u63cf</p><p style="color:var(--gn)">\u6309\u5f00\u59cb\u6309\u94ae\u542f\u52a8\u626b\u63cf\u3002</p>',
    tut_b7_content: '<p>\u5728 <b>BS \u9009\u9879\u5361</b>\u4e2d\u7ba1\u7406 Bluesky \u5f0f\u5b9e\u9a8c:</p><p>* \u9009\u62e9\u65b9\u6848\u5e76\u8bbe\u7f6e\u53c2\u6570</p><p>* \u52a0\u5165\u961f\u5217\u987a\u5e8f\u6267\u884c</p><p>* \u5b9e\u65f6\u8fdb\u5ea6\u76d1\u63a7</p><p style="color:var(--pr)">\u4e5f\u53ef\u4ee5\u7528\u5feb\u901f\u8fd0\u884c\u6309\u94ae\u7acb\u5373\u6267\u884c\u3002</p>',
    tut_b8_content: '<p>\u7528\u9876\u90e8\u6a21\u5f0f\u6309\u94ae\u5207\u6362\u8fd0\u884c\u6a21\u5f0f:</p><p>* <span style="color:var(--gn)">\u865a\u62df</span> -- \u4ec5\u4eff\u771f</p><p>* <span style="color:var(--am)">\u5b9e\u9645</span> -- \u8fde\u63a5\u5b9e\u9645 EPICS IOC</p><p>* <span style="color:var(--ac)">\u53cc\u6a21\u5f0f</span> -- \u865a\u62df/\u5b9e\u9645\u5bf9\u6bd4</p><p>\u521d\u6b21\u4f7f\u7528\u5efa\u8bae\u5148\u5728\u865a\u62df\u6a21\u5f0f\u7ec3\u4e60\u3002</p>',
    tut_b9_content: '<p style="color:var(--gn)">\u606d\u559c! \u60a8\u5df2\u5b66\u4f1a\u57fa\u672c\u4f7f\u7528\u3002</p><p>\u63a5\u4e0b\u6765:</p><p>* <b>\u865a\u62df\u5b9e\u9a8c</b> -- \u6a21\u62df\u771f\u5b9e\u5b9e\u9a8c</p><p>* <b>EPICS \u96c6\u6210</b> -- \u8fde\u63a5\u5b9e\u9645\u8bbe\u5907</p><p>* <b>\u865a\u62df/\u5b9e\u9645\u5bf9\u6bd4</b> -- \u6bd4\u8f83\u4eff\u771f\u4e0e\u5b9e\u9645</p>',
    tut_exp_name: '\u865a\u62df\u5b9e\u9a8c\u7ec3\u4e60', tut_exp_desc: '\u5bf9\u6bcf\u79cd\u6d4b\u91cf\u6280\u672f\u8fdb\u884c\u865a\u62df\u5b9e\u9a8c',
    tut_e1_title: 'Cu K-edge XANES \u5b9e\u9a8c', tut_e2_title: 'XANES \u626b\u63cf\u8fd0\u884c',
    tut_e3_title: 'XRF \u6210\u50cf\u5b9e\u9a8c', tut_e4_title: '\u7c89\u672b XRD \u5b9e\u9a8c',
    tut_e1_content: '<p>\u672c\u7ec3\u4e60\u5c06\u8fdb\u884c <b>Cu K-edge XANES</b> \u6d4b\u91cf\u3002</p><p style="color:var(--am)">\u6309\u4e0b\u65b9\u201c\u81ea\u52a8\u8bbe\u7f6e\u201d\u6309\u94ae\u81ea\u52a8\u914d\u7f6e\u5b9e\u9a8c\u3002</p>',
    tut_e2_content: '<p>\u80fd\u91cf\u5df2\u8bbe\u7f6e\u4e3a Cu K-edge (8.979 keV)\u3002</p><p style="color:var(--am)">\u5728 BS \u9009\u9879\u5361\u6309 XANES \u6309\u94ae\u542f\u52a8\u626b\u63cf\u3002</p><p>\u626b\u63cf\u5b8c\u6210\u540e µ(E) \u5149\u8c31\u5c06\u663e\u793a\u5728\u5e95\u90e8\u9762\u677f\u3002</p>',
    tut_e3_content: '<p>\u73b0\u5728\u8fdb\u884c <b>XRF \u6210\u50cf</b>\u3002</p><p>SDD \u63a2\u6d4b\u5668\u4ee5 90\u00b0\u89d2\u91c7\u96c6\u8367\u5149 X \u5c04\u7ebf\u3002</p><p style="color:var(--am)">\u81ea\u52a8\u8bbe\u7f6e\u540e\u5149\u6805\u626b\u63cf\u5c06\u751f\u6210\u5143\u7d20\u5206\u5e03\u56fe\u3002</p>',
    tut_e4_content: '<p>\u8fdb\u884c <b>\u7c89\u672b XRD</b> \u6d4b\u91cf\u3002</p><p>Eiger 2X \u63a2\u6d4b\u5668\u5c06\u91c7\u96c6 Debye-Scherrer \u73af\u5f62\u56fe\u6837\u3002</p>',
    tut_prev: '\u4e0a\u4e00\u6b65', tut_next: '\u4e0b\u4e00\u6b65', tut_done: '\u5b8c\u6210'
  },
  de: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: 'Optik',
    tab_motors: 'Motoren',  tab_mask: 'Maske',   tab_measure: 'Messung',
    tab_align: 'Justage',   tab_compare: 'Vgl.',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: 'Hilfe',  tab_chat: 'Chat',
    tab_expt: 'Expt',
    hdr_theme: 'Farbschema',   hdr_layout: 'Layout',
    hdr_mcrays: 'MC Strahlen', hdr_grid: 'Gitteraufl\u00f6sung',
    hdr_language: 'Sprache',
    theme_light: 'Hell (Standard)',   theme_dark: 'Dunkel',
    theme_dark2: 'Dunkel 2',         theme_deuter: 'Deuteranopie',
    theme_protan: 'Protanopie',      theme_tritan: 'Tritanopie',
    themedesc_light: 'Sauberer wei\u00dfer Hintergrund',
    themedesc_dark: 'Dunkles Design mit hohem Kontrast',
    themedesc_dark2: 'Ged\u00e4mpftes dunkles Design',
    themedesc_deuter: 'Rot-Gr\u00fcn-Sehschw\u00e4che sicher',
    themedesc_protan: 'Rotsehschw\u00e4che sicher',
    themedesc_tritan: 'Blau-Gelb-Sehschw\u00e4che sicher',
    layout_standard: 'Standard',      layout_wide: 'Breitansicht',
    layout_compact: 'Kompakt',        layout_focus: 'Fokus',
    layoutdesc_standard: 'Volles Panel-Layout (320px Seitenleiste)',
    layoutdesc_wide: 'Seitenleiste ausblenden, Strahlansicht maximieren',
    layoutdesc_compact: 'Schmale Seitenleiste (220px)',
    layoutdesc_focus: 'Nur Beamline, alle Panels ausblenden',
    mcrays_fast: 'Schnell -- Vorschau',     mcrays_normal: 'Normal -- mittlere Qualit\u00e4t',
    mcrays_default: 'Standard -- hohe Statistik',  mcrays_precise: 'Pr\u00e4zise -- langsam',
    mcrays_best: 'Beste Qualit\u00e4t -- sehr langsam',
    grid_standard: 'Standard -- schnelles Rendern',
    grid_highres: '4x feiner -- kleine Strahldetails',
    btn_estop: 'NOT-HALT',       btn_reset: 'Zur\u00fccksetzen',
    btn_start: 'Start',          btn_stop: 'Stopp',
    btn_save: 'Speichern',       btn_close: 'Schlie\u00dfen',
    btn_apply: 'Anwenden',       btn_cancel: 'Abbrechen',
    panel_source: 'Quellenparameter',
    panel_beamline: 'Beamline-\u00dcbersicht',
    panel_profile: 'Strahlprofil',
    panel_spectrum: 'Spektrum',
    mode_virtual: 'Virtuell',   mode_real: 'Real',   mode_dual: 'Dual',
    align_ready: 'Bereit', align_starting: 'Starte...', align_scanning: 'Scanne...', align_abort: 'Abbruch', align_export_log: 'Log exportieren',
    align_scan_waiting: 'Scan-Diagramm -- Warten...', align_pass: 'OK', align_fail: 'FEHLER',
    align_step_fmt: 'Schritt {0}/{1}: {2}', align_motor_fmt: 'Motor={0}', align_intensity_fmt: 'Intensit\u00e4t={0}',
    align_centroid_fmt: 'Schwerpunkt={0} mm', align_beam_at: 'Strahl @ {0} ({1}m)',
    align_halfcut: 'Halbschnitt (pitch=0)', align_halfcut_c1: 'Halbschnitt C1 (theta=0)',
    align_set_angle: 'Arbeitswinkel setzen', align_rot_center: 'Rotationszentrum', align_set_bragg: 'Bragg-Winkel setzen',
    align_dtheta2_coarse: 'dTheta2 Grob', align_dtheta2_fine: 'dTheta2 Fein',
    align_m1_full: 'M1 Volljustage', align_m2_full: 'M2 Volljustage',
    align_kbv: 'KB-V Justage', align_kbh: 'KB-H Justage', align_dcm_full: 'DCM Volljustage',
    expt_start: 'Start', expt_stop: 'Stopp', expt_show: 'Anzeigen', expt_save: 'Speichern',
    expt_starting_fmt: '{0} wird gestartet...', expt_computing: 'Berechne...', expt_no_result: 'Kein Ergebnis zum Speichern',
    expt_saved_fmt: 'Gespeichert: {0}', expt_ready_msg: 'Bereit. Ergebnisse werden in einem separaten Fenster angezeigt.',
    expt_server_disc: 'Simulationsserver (Port {0}) nicht verbunden.',
    expt_beamline_status: 'Beamline', expt_server_not_connected: 'Simulationsserver nicht verbunden',
    expt_formula: 'Formel', expt_absorber: 'Absorber', expt_edge: 'Kante', expt_e_range: 'E-Bereich (eV)', expt_e_step: 'E-Schritt',
    expt_presets: 'Voreinstellungen', expt_sample: 'Probe', expt_conc: 'Konz. (ppm)',
    bs_submit_plan: 'Plan senden', bs_add_queue: 'Zur Warteschlange', bs_run_now: 'Sofort starten', bs_queue_fmt: 'Warteschlange ({0})',
    bs_queue_empty: 'Keine Pl\u00e4ne in der Warteschlange', bs_clear: 'L\u00f6schen', bs_run_history_fmt: 'Verlauf ({0})',
    bs_quick_run: 'Schnellstart', bs_qs_connection: 'Queue-Server-Verbindung', bs_connected: '[Verbunden]',
    bs_sim_mode: '[Simulationsmodus]', bs_connect: 'Verbinden', bs_server_history: 'Server-Scan-Verlauf',
    bs_click_refresh: '[Aktualisieren] klicken f\u00fcr Server-Verlauf',
    status_idle: 'BEREIT', status_running: 'L\u00c4UFT', status_paused: 'PAUSE', status_error: 'FEHLER',
    status_completed: 'OK', status_aborted: 'ABBRUCH',
    tut_basics_name: 'Grundlagen', tut_basics_desc: 'Grundlegende Bedienung und Hauptfunktionen lernen',
    tut_b1_title: 'Willkommen!', tut_b2_title: '1. Beamline-Layout', tut_b3_title: '2. Energieeinstellung',
    tut_b4_title: '3. Optische Komponenten', tut_b5_title: '4. Status\u00fcberwachung', tut_b6_title: '5. Messungen durchf\u00fchren',
    tut_b7_title: '6. Bluesky-Experimentwarteschlange', tut_b8_title: '7. Moduswechsel', tut_b9_title: 'Grundlagen abgeschlossen!',
    tut_b1_content: '<p>Willkommen bei der Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>Dieses Tutorial f\u00fchrt Sie schrittweise durch die Grundlagen.</p><p style="color:var(--am)">Folgen Sie den Anweisungen in jedem Schritt.</p>',
    tut_b2_content: '<p>In der Mitte sehen Sie <b>zwei Ansichten</b>:</p><p>* <span style="color:var(--ac)">Draufsicht</span> -- Horizontale Ebene (M1/M2 Spiegelreflexionen)</p><p>* <span style="color:var(--ac)">Seitenansicht</span> -- Vertikale Ebene (DCM Bragg-Beugung)</p><p style="color:var(--gn)">Klicken Sie auf eine Komponente f\u00fcr Details und Steuerung.</p>',
    tut_b3_content: '<p>Stellen Sie die Zielenergie im <b>IVU-Tab</b> in der rechten Seitenleiste ein.</p><p style="color:var(--am)">Ziehen Sie den Schieber auf 10 keV.</p><p>Das System wird automatisch:</p><p>* Optimale Harmonische w\u00e4hlen</p><p>* IVU-L\u00fccke anpassen</p><p>* DCM Bragg-Winkel berechnen</p>',
    tut_b4_content: '<p>Passen Sie die Optik im <b>Optik-Tab</b> an:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- Wei\u00dfstrahl-Spaltgr\u00f6\u00dfe</p><p>* <span style="color:var(--ac)">M1/M2</span> -- Horizontale Ablenkspiegel</p><p>* <span style="color:var(--ac)">SSA</span> -- Sekund\u00e4rspalt (KB virtuelle Quelle)</p><p>* <span style="color:var(--ac)">KB</span> -- Endergebnis der Fokussierung</p><p style="color:var(--am)">Klicken Sie auf den Optik-Tab.</p>',
    tut_b5_content: '<p>Echtzeitinformationen in der Statusleiste unten:</p><p>* <span style="color:var(--ac)">E</span> -- Aktuelle Energie</p><p>* <span style="color:var(--gn)">Flux</span> -- Photonenfluss</p><p>* <span style="color:var(--pk)">Spot</span> -- Fokalgr\u00f6\u00dfe</p><p>Strahlgr\u00f6\u00dfen an jeder Komponente werden ebenfalls angezeigt.</p>',
    tut_b6_content: '<p>Virtuelle Experimente im <b>Mess-Tab</b>:</p><p>* XANES -- Absorptionsspektrum</p><p>* XRD -- Beugungsmuster</p><p>* XRF -- Fluoreszenzspektrum</p><p>* 2D-Karte -- R\u00e4umliche Kartierung</p><p style="color:var(--gn)">Dr\u00fccken Sie Start f\u00fcr den Scan.</p>',
    tut_b7_content: '<p>Bluesky-Experimente im <b>BS-Tab</b>:</p><p>* Plan w\u00e4hlen und Parameter einstellen</p><p>* Zur Warteschlange f\u00fcr sequentielle Ausf\u00fchrung</p><p>* Echtzeit-Fortschritts\u00fcberwachung</p><p style="color:var(--pr)">Schnellstart-Buttons f\u00fcr sofortige Ausf\u00fchrung.</p>',
    tut_b8_content: '<p>Betriebsmodus mit den Modus-Buttons oben umschalten:</p><p>* <span style="color:var(--gn)">Virtuell</span> -- Nur Simulation</p><p>* <span style="color:var(--am)">Real</span> -- Echte EPICS IOC-Verbindung</p><p>* <span style="color:var(--ac)">Dual</span> -- V/R-Vergleichsmodus</p><p>Zuerst im virtuellen Modus \u00fcben.</p>',
    tut_b9_content: '<p style="color:var(--gn)">Gl\u00fcckwunsch! Sie haben die Grundlagen gelernt.</p><p>N\u00e4chste Schritte:</p><p>* <b>Virtuelle Experimente</b> -- Echte Experimente simulieren</p><p>* <b>EPICS-Integration</b> -- Echte Ger\u00e4te verbinden</p><p>* <b>V/R-Vergleich</b> -- Simulation und Realit\u00e4t vergleichen</p>',
    tut_exp_name: 'Virtuelle Experiment\u00fcbung', tut_exp_desc: 'Virtuelle Experimente f\u00fcr jede Messtechnik',
    tut_e1_title: 'Cu K-Kante XANES', tut_e2_title: 'XANES-Scan starten',
    tut_e3_title: 'XRF-Imaging-Experiment', tut_e4_title: 'Pulver-XRD-Experiment',
    tut_e1_content: '<p>In dieser \u00dcbung f\u00fchren Sie eine <b>Cu K-Kante XANES</b>-Messung durch.</p><p style="color:var(--am)">Dr\u00fccken Sie "Auto Setup" zur automatischen Konfiguration.</p>',
    tut_e2_content: '<p>Energie auf Cu K-Kante (8.979 keV) eingestellt.</p><p style="color:var(--am)">Im BS-Tab XANES-Button dr\u00fccken.</p><p>Nach Abschluss wird das µ(E)-Spektrum unten angezeigt.</p>',
    tut_e3_content: '<p>Jetzt <b>XRF-Imaging</b> durchf\u00fchren.</p><p>Der SDD-Detektor sammelt Fluoreszenz-R\u00f6ntgenstrahlen bei 90\u00b0.</p><p style="color:var(--am)">Nach Auto Setup erzeugt der Rasterscan eine Elementverteilungskarte.</p>',
    tut_e4_content: '<p><b>Pulver-XRD</b>-Messung durchf\u00fchren.</p><p>Der Eiger 2X-Detektor sammelt Debye-Scherrer-Ringmuster.</p>',
    tut_prev: 'Zur\u00fcck', tut_next: 'Weiter', tut_done: 'Fertig'
  },
  fr: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: 'Optique',
    tab_motors: 'Moteurs',  tab_mask: 'Masque',  tab_measure: 'Mesure',
    tab_align: 'Alignement', tab_compare: 'Comp.', tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: 'Guide',  tab_chat: 'Chat',
    tab_expt: 'Exp\u00e9r.',
    hdr_theme: 'Th\u00e8me de couleur',  hdr_layout: 'Disposition',
    hdr_mcrays: 'Rayons MC',   hdr_grid: 'R\u00e9solution grille',
    hdr_language: 'Langue',
    theme_light: 'Clair (D\u00e9faut)',   theme_dark: 'Sombre',
    theme_dark2: 'Sombre 2',             theme_deuter: 'Deut\u00e9ranopie',
    theme_protan: 'Protanopie',          theme_tritan: 'Tritanopie',
    themedesc_light: 'Fond blanc propre',
    themedesc_dark: 'Th\u00e8me sombre \u00e0 contraste \u00e9lev\u00e9',
    themedesc_dark2: 'Th\u00e8me sombre att\u00e9nu\u00e9',
    themedesc_deuter: 'S\u00fbr pour daltonisme rouge-vert',
    themedesc_protan: 'S\u00fbr pour daltonisme rouge',
    themedesc_tritan: 'S\u00fbr pour daltonisme bleu-jaune',
    layout_standard: 'Standard',       layout_wide: 'Vue large',
    layout_compact: 'Compact',         layout_focus: 'Focus',
    layoutdesc_standard: 'Disposition compl\u00e8te (barre lat\u00e9rale 320px)',
    layoutdesc_wide: 'Masquer la barre lat\u00e9rale, maximiser la vue',
    layoutdesc_compact: 'Barre lat\u00e9rale \u00e9troite (220px)',
    layoutdesc_focus: 'Beamline uniquement, masquer les panneaux',
    mcrays_fast: 'Rapide -- aper\u00e7u',     mcrays_normal: 'Normal -- qualit\u00e9 moyenne',
    mcrays_default: 'D\u00e9faut -- haute statistique', mcrays_precise: 'Pr\u00e9cis -- lent',
    mcrays_best: 'Meilleure qualit\u00e9 -- tr\u00e8s lent',
    grid_standard: 'D\u00e9faut -- rendu rapide',
    grid_highres: '4x plus fin -- d\u00e9tails petit faisceau',
    btn_estop: 'ARR\u00caT URG.',    btn_reset: 'R\u00e9initialiser',
    btn_start: 'D\u00e9marrer',       btn_stop: 'Arr\u00eater',
    btn_save: 'Enregistrer',          btn_close: 'Fermer',
    btn_apply: 'Appliquer',           btn_cancel: 'Annuler',
    panel_source: 'Param\u00e8tres source',
    panel_beamline: 'Vue d\'ensemble beamline',
    panel_profile: 'Profil de faisceau',
    panel_spectrum: 'Spectre',
    mode_virtual: 'Virtuel',   mode_real: 'R\u00e9el',   mode_dual: 'Double',
    align_ready: 'Pr\u00eat', align_starting: 'D\u00e9marrage...', align_scanning: 'Scan en cours...', align_abort: 'Abandonner', align_export_log: 'Exporter le journal',
    align_scan_waiting: 'Graphique de scan -- en attente...', align_pass: 'OK', align_fail: '\u00c9CHEC',
    align_step_fmt: '\u00c9tape {0}/{1}: {2}', align_motor_fmt: 'Moteur={0}', align_intensity_fmt: 'Intensit\u00e9={0}',
    align_centroid_fmt: 'Centro\u00efde={0} mm', align_beam_at: 'Faisceau @ {0} ({1}m)',
    align_halfcut: 'Demi-coupe (pitch=0)', align_halfcut_c1: 'Demi-coupe C1 (theta=0)',
    align_set_angle: 'D\u00e9finir angle de travail', align_rot_center: 'Centre de rotation', align_set_bragg: 'D\u00e9finir angle de Bragg',
    align_dtheta2_coarse: 'dTheta2 Grossier', align_dtheta2_fine: 'dTheta2 Fin',
    align_m1_full: 'M1 Alignement complet', align_m2_full: 'M2 Alignement complet',
    align_kbv: 'KB-V Alignement', align_kbh: 'KB-H Alignement', align_dcm_full: 'DCM Alignement complet',
    expt_start: 'D\u00e9marrer', expt_stop: 'Arr\u00eater', expt_show: 'Afficher', expt_save: 'Enregistrer',
    expt_starting_fmt: 'D\u00e9marrage de {0}...', expt_computing: 'Calcul en cours...', expt_no_result: 'Aucun r\u00e9sultat \u00e0 enregistrer',
    expt_saved_fmt: 'Enregistr\u00e9: {0}', expt_ready_msg: 'Pr\u00eat. Les r\u00e9sultats s\'afficheront dans une fen\u00eatre s\u00e9par\u00e9e.',
    expt_server_disc: 'Serveur de simulation (port {0}) non connect\u00e9.',
    expt_beamline_status: 'Ligne de lumi\u00e8re', expt_server_not_connected: 'Serveur de simulation non connect\u00e9',
    expt_formula: 'Formule', expt_absorber: 'Absorbeur', expt_edge: 'Seuil', expt_e_range: 'Plage E (eV)', expt_e_step: 'Pas E',
    expt_presets: 'Pr\u00e9r\u00e9glages', expt_sample: '\u00c9chantillon', expt_conc: 'Conc. (ppm)',
    bs_submit_plan: 'Soumettre le plan', bs_add_queue: 'Ajouter \u00e0 la file', bs_run_now: 'Ex\u00e9cuter maintenant', bs_queue_fmt: 'File ({0})',
    bs_queue_empty: 'Aucun plan dans la file', bs_clear: 'Effacer', bs_run_history_fmt: 'Historique ({0})',
    bs_quick_run: 'Ex\u00e9cution rapide', bs_qs_connection: 'Connexion serveur de file', bs_connected: '[Connect\u00e9]',
    bs_sim_mode: '[Mode simulation]', bs_connect: 'Connecter', bs_server_history: 'Historique des scans serveur',
    bs_click_refresh: 'Cliquer [Actualiser] pour charger l\'historique',
    status_idle: 'INACTIF', status_running: 'EN COURS', status_paused: 'PAUSE', status_error: 'ERREUR',
    status_completed: 'OK', status_aborted: 'ABANDONN\u00c9',
    tut_basics_name: 'Utilisation de base', tut_basics_desc: 'Apprendre l\'interface et les fonctions principales',
    tut_b1_title: 'Bienvenue!', tut_b2_title: '1. Disposition de la beamline', tut_b3_title: '2. R\u00e9glage de l\'\u00e9nergie',
    tut_b4_title: '3. Composants optiques', tut_b5_title: '4. Surveillance d\'\u00e9tat', tut_b6_title: '5. Ex\u00e9cution des mesures',
    tut_b7_title: '6. File d\'exp\u00e9riences Bluesky', tut_b8_title: '7. Changement de mode', tut_b9_title: 'Tutoriel de base termin\u00e9!',
    tut_b1_content: '<p>Bienvenue sur la Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>Ce tutoriel vous guidera pas \u00e0 pas.</p><p style="color:var(--am)">Suivez les instructions \u00e0 chaque \u00e9tape.</p>',
    tut_b2_content: '<p>Au centre, <b>deux vues</b>:</p><p>* <span style="color:var(--ac)">Vue de dessus</span> -- Plan horizontal (r\u00e9flexions M1/M2)</p><p>* <span style="color:var(--ac)">Vue de c\u00f4t\u00e9</span> -- Plan vertical (diffraction Bragg DCM)</p><p style="color:var(--gn)">Cliquez sur un composant pour les d\u00e9tails et le contr\u00f4le.</p>',
    tut_b3_content: '<p>D\u00e9finissez l\'\u00e9nergie dans l\'onglet <b>IVU</b> de la barre lat\u00e9rale.</p><p style="color:var(--am)">Glissez le curseur \u00e0 10 keV.</p><p>Le syst\u00e8me va automatiquement:</p><p>* Choisir l\'harmonique optimale</p><p>* Ajuster l\'ouverture IVU</p><p>* Calculer l\'angle de Bragg DCM</p>',
    tut_b4_content: '<p>Ajustez l\'optique dans l\'onglet <b>Optique</b>:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- Taille de fente blanc</p><p>* <span style="color:var(--ac)">M1/M2</span> -- Angles des miroirs de d\u00e9flexion</p><p>* <span style="color:var(--ac)">SSA</span> -- Fente secondaire (source virtuelle KB)</p><p>* <span style="color:var(--ac)">KB</span> -- R\u00e9sultat de focalisation finale</p><p style="color:var(--am)">Cliquez sur l\'onglet Optique.</p>',
    tut_b5_content: '<p>Informations en temps r\u00e9el dans la barre d\'\u00e9tat:</p><p>* <span style="color:var(--ac)">E</span> -- \u00c9nergie actuelle</p><p>* <span style="color:var(--gn)">Flux</span> -- Flux de photons</p><p>* <span style="color:var(--pk)">Spot</span> -- Taille du spot focal</p><p>Les tailles de faisceau sont aussi affich\u00e9es.</p>',
    tut_b6_content: '<p>Exp\u00e9riences virtuelles dans l\'onglet <b>Mesure</b>:</p><p>* XANES -- Spectre d\'absorption</p><p>* XRD -- Motif de diffraction</p><p>* XRF -- Spectre de fluorescence</p><p>* Carte 2D -- Cartographie spatiale</p><p style="color:var(--gn)">Appuyez sur D\u00e9marrer.</p>',
    tut_b7_content: '<p>Exp\u00e9riences Bluesky dans l\'onglet <b>BS</b>:</p><p>* Choisir un plan et d\u00e9finir les param\u00e8tres</p><p>* Ajouter \u00e0 la file pour ex\u00e9cution s\u00e9quentielle</p><p>* Suivi en temps r\u00e9el</p><p style="color:var(--pr)">Boutons d\'ex\u00e9cution rapide disponibles.</p>',
    tut_b8_content: '<p>Changez le mode avec les boutons en haut:</p><p>* <span style="color:var(--gn)">Virtuel</span> -- Simulation uniquement</p><p>* <span style="color:var(--am)">R\u00e9el</span> -- Connexion EPICS IOC r\u00e9elle</p><p>* <span style="color:var(--ac)">Double</span> -- Mode de comparaison V/R</p><p>Pratiquez d\'abord en mode virtuel.</p>',
    tut_b9_content: '<p style="color:var(--gn)">F\u00e9licitations! Vous ma\u00eetrisez les bases.</p><p>Prochaines \u00e9tapes:</p><p>* <b>Exp\u00e9riences virtuelles</b> -- Simuler des exp\u00e9riences r\u00e9elles</p><p>* <b>Int\u00e9gration EPICS</b> -- Connecter des \u00e9quipements r\u00e9els</p><p>* <b>Comparaison V/R</b> -- Comparer simulation et r\u00e9alit\u00e9</p>',
    tut_exp_name: 'Pratique d\'exp\u00e9rience virtuelle', tut_exp_desc: 'Exp\u00e9riences virtuelles pour chaque technique',
    tut_e1_title: 'XANES Cu K-edge', tut_e2_title: 'Ex\u00e9cuter scan XANES',
    tut_e3_title: 'Exp\u00e9rience imagerie XRF', tut_e4_title: 'Exp\u00e9rience XRD poudre',
    tut_e1_content: '<p>Vous allez r\u00e9aliser une mesure <b>Cu K-edge XANES</b>.</p><p style="color:var(--am)">Appuyez sur "Config. auto" pour configurer automatiquement.</p>',
    tut_e2_content: '<p>\u00c9nergie r\u00e9gl\u00e9e sur Cu K-edge (8.979 keV).</p><p style="color:var(--am)">Dans l\'onglet BS, appuyez sur XANES.</p><p>Apr\u00e8s le scan, le spectre µ(E) sera affich\u00e9.</p>',
    tut_e3_content: '<p>Maintenant, <b>imagerie XRF</b>.</p><p>Le d\u00e9tecteur SDD collecte les rayons X de fluorescence \u00e0 90\u00b0.</p><p style="color:var(--am)">Apr\u00e8s config. auto, un scan raster g\u00e9n\u00e9rera une carte de distribution \u00e9l\u00e9mentaire.</p>',
    tut_e4_content: '<p>Mesure <b>XRD poudre</b>.</p><p>Le d\u00e9tecteur Eiger 2X collectera des anneaux Debye-Scherrer.</p>',
    tut_prev: 'Pr\u00e9c.', tut_next: 'Suivant', tut_done: 'Termin\u00e9'
  },
  es: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u00d3ptica',
    tab_motors: 'Motores',  tab_mask: 'M\u00e1scara', tab_measure: 'Medida',
    tab_align: 'Alinear',   tab_compare: 'Comp.',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: 'Gu\u00eda', tab_chat: 'Chat',
    tab_expt: 'Expt',
    hdr_theme: 'Tema de color',   hdr_layout: 'Disposici\u00f3n',
    hdr_mcrays: 'Rayos MC',       hdr_grid: 'Resoluci\u00f3n de malla',
    hdr_language: 'Idioma',
    theme_light: 'Claro (Predeterminado)',   theme_dark: 'Oscuro',
    theme_dark2: 'Oscuro 2',               theme_deuter: 'Deuteranop\u00eda',
    theme_protan: 'Protanop\u00eda',        theme_tritan: 'Tritanop\u00eda',
    themedesc_light: 'Fondo blanco limpio',
    themedesc_dark: 'Tema oscuro de alto contraste',
    themedesc_dark2: 'Tema oscuro atenuado',
    themedesc_deuter: 'Seguro para daltonismo rojo-verde',
    themedesc_protan: 'Seguro para daltonismo rojo',
    themedesc_tritan: 'Seguro para daltonismo azul-amarillo',
    layout_standard: 'Est\u00e1ndar',      layout_wide: 'Vista amplia',
    layout_compact: 'Compacto',             layout_focus: 'Enfoque',
    layoutdesc_standard: 'Disposici\u00f3n completa (barra lateral 320px)',
    layoutdesc_wide: 'Ocultar barra lateral, maximizar vista',
    layoutdesc_compact: 'Barra lateral estrecha (220px)',
    layoutdesc_focus: 'Solo beamline, ocultar paneles',
    mcrays_fast: 'R\u00e1pido -- vista previa',   mcrays_normal: 'Normal -- calidad media',
    mcrays_default: 'Predeterminado -- alta estad\u00edstica', mcrays_precise: 'Preciso -- lento',
    mcrays_best: 'Mejor calidad -- muy lento',
    grid_standard: 'Predeterminado -- renderizado r\u00e1pido',
    grid_highres: '4x m\u00e1s fino -- detalle de haz peque\u00f1o',
    btn_estop: 'PARADA URG.',    btn_reset: 'Reiniciar',
    btn_start: 'Iniciar',        btn_stop: 'Detener',
    btn_save: 'Guardar',         btn_close: 'Cerrar',
    btn_apply: 'Aplicar',        btn_cancel: 'Cancelar',
    panel_source: 'Par\u00e1metros de fuente',
    panel_beamline: 'Vista general beamline',
    panel_profile: 'Perfil de haz',
    panel_spectrum: 'Espectro',
    mode_virtual: 'Virtual',   mode_real: 'Real',   mode_dual: 'Dual',
    align_ready: 'Listo', align_starting: 'Iniciando...', align_scanning: 'Escaneando...', align_abort: 'Abortar', align_export_log: 'Exportar registro',
    align_scan_waiting: 'Gr\u00e1fico de escaneo -- esperando...', align_pass: 'OK', align_fail: 'FALLO',
    align_step_fmt: 'Paso {0}/{1}: {2}', align_motor_fmt: 'Motor={0}', align_intensity_fmt: 'Intensidad={0}',
    align_centroid_fmt: 'Centroide={0} mm', align_beam_at: 'Haz @ {0} ({1}m)',
    align_halfcut: 'Medio corte (pitch=0)', align_halfcut_c1: 'Medio corte C1 (theta=0)',
    align_set_angle: 'Establecer \u00e1ngulo de trabajo', align_rot_center: 'Centro de rotaci\u00f3n', align_set_bragg: 'Establecer \u00e1ngulo de Bragg',
    align_dtheta2_coarse: 'dTheta2 Grueso', align_dtheta2_fine: 'dTheta2 Fino',
    align_m1_full: 'M1 Alineaci\u00f3n completa', align_m2_full: 'M2 Alineaci\u00f3n completa',
    align_kbv: 'KB-V Alineaci\u00f3n', align_kbh: 'KB-H Alineaci\u00f3n', align_dcm_full: 'DCM Alineaci\u00f3n completa',
    expt_start: 'Iniciar', expt_stop: 'Detener', expt_show: 'Mostrar', expt_save: 'Guardar',
    expt_starting_fmt: 'Iniciando {0}...', expt_computing: 'Calculando...', expt_no_result: 'Sin resultado para guardar',
    expt_saved_fmt: 'Guardado: {0}', expt_ready_msg: 'Listo. Los resultados se mostrar\u00e1n en una ventana separada.',
    expt_server_disc: 'Servidor de simulaci\u00f3n (puerto {0}) no conectado.',
    expt_beamline_status: 'L\u00ednea de luz', expt_server_not_connected: 'Servidor de simulaci\u00f3n no conectado',
    expt_formula: 'F\u00f3rmula', expt_absorber: 'Absorbente', expt_edge: 'Borde', expt_e_range: 'Rango E (eV)', expt_e_step: 'Paso E',
    expt_presets: 'Preajustes', expt_sample: 'Muestra', expt_conc: 'Conc. (ppm)',
    bs_submit_plan: 'Enviar plan', bs_add_queue: 'A\u00f1adir a cola', bs_run_now: 'Ejecutar ahora', bs_queue_fmt: 'Cola ({0})',
    bs_queue_empty: 'No hay planes en la cola', bs_clear: 'Limpiar', bs_run_history_fmt: 'Historial ({0})',
    bs_quick_run: 'Ejecuci\u00f3n r\u00e1pida', bs_qs_connection: 'Conexi\u00f3n servidor de cola', bs_connected: '[Conectado]',
    bs_sim_mode: '[Modo simulaci\u00f3n]', bs_connect: 'Conectar', bs_server_history: 'Historial de escaneos del servidor',
    bs_click_refresh: 'Clic en [Actualizar] para cargar historial',
    status_idle: 'INACTIVO', status_running: 'EJECUTANDO', status_paused: 'PAUSA', status_error: 'ERROR',
    status_completed: 'OK', status_aborted: 'ABORTADO',
    tut_basics_name: 'Uso b\u00e1sico', tut_basics_desc: 'Aprender la interfaz b\u00e1sica y funciones principales',
    tut_b1_title: '\u00a1Bienvenido!', tut_b2_title: '1. Disposici\u00f3n de la beamline', tut_b3_title: '2. Ajuste de energ\u00eda',
    tut_b4_title: '3. Componentes \u00f3pticos', tut_b5_title: '4. Monitoreo de estado', tut_b6_title: '5. Ejecutar mediciones',
    tut_b7_title: '6. Cola de experimentos Bluesky', tut_b8_title: '7. Cambio de modo', tut_b9_title: '\u00a1Tutorial b\u00e1sico completado!',
    tut_b1_content: '<p>\u00a1Bienvenido a Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>Este tutorial le guiar\u00e1 paso a paso.</p><p style="color:var(--am)">Siga las instrucciones en cada paso.</p>',
    tut_b2_content: '<p>En el centro, <b>dos vistas</b>:</p><p>* <span style="color:var(--ac)">Vista superior</span> -- Plano horizontal (reflexiones M1/M2)</p><p>* <span style="color:var(--ac)">Vista lateral</span> -- Plano vertical (difracci\u00f3n Bragg DCM)</p><p style="color:var(--gn)">Haga clic en cualquier componente para detalles y control.</p>',
    tut_b3_content: '<p>Establezca la energ\u00eda en la pesta\u00f1a <b>IVU</b> de la barra lateral.</p><p style="color:var(--am)">Arrastre el control a 10 keV.</p><p>El sistema autom\u00e1ticamente:</p><p>* Seleccionar\u00e1 el arm\u00f3nico \u00f3ptimo</p><p>* Ajustar\u00e1 la apertura IVU</p><p>* Calcular\u00e1 el \u00e1ngulo de Bragg DCM</p>',
    tut_b4_content: '<p>Ajuste la \u00f3ptica en la pesta\u00f1a <b>\u00d3ptica</b>:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- Tama\u00f1o de rendija blanca</p><p>* <span style="color:var(--ac)">M1/M2</span> -- Espejos de deflexi\u00f3n horizontal</p><p>* <span style="color:var(--ac)">SSA</span> -- Rendija secundaria (fuente virtual KB)</p><p>* <span style="color:var(--ac)">KB</span> -- Resultado final de enfoque</p><p style="color:var(--am)">Haga clic en la pesta\u00f1a \u00d3ptica.</p>',
    tut_b5_content: '<p>Informaci\u00f3n en tiempo real en la barra de estado:</p><p>* <span style="color:var(--ac)">E</span> -- Energ\u00eda actual</p><p>* <span style="color:var(--gn)">Flux</span> -- Flujo de fotones</p><p>* <span style="color:var(--pk)">Spot</span> -- Tama\u00f1o del punto focal</p><p>Los tama\u00f1os del haz en cada componente tambi\u00e9n se muestran.</p>',
    tut_b6_content: '<p>Experimentos virtuales en la pesta\u00f1a <b>Medida</b>:</p><p>* XANES -- Espectro de absorci\u00f3n</p><p>* XRD -- Patr\u00f3n de difracci\u00f3n</p><p>* XRF -- Espectro de fluorescencia</p><p>* Mapa 2D -- Cartograf\u00eda espacial</p><p style="color:var(--gn)">Pulse Iniciar para el escaneo.</p>',
    tut_b7_content: '<p>Experimentos Bluesky en la pesta\u00f1a <b>BS</b>:</p><p>* Seleccionar plan y par\u00e1metros</p><p>* A\u00f1adir a cola para ejecuci\u00f3n secuencial</p><p>* Monitoreo en tiempo real</p><p style="color:var(--pr)">Botones de ejecuci\u00f3n r\u00e1pida disponibles.</p>',
    tut_b8_content: '<p>Cambie el modo con los botones superiores:</p><p>* <span style="color:var(--gn)">Virtual</span> -- Solo simulaci\u00f3n</p><p>* <span style="color:var(--am)">Real</span> -- Conexi\u00f3n EPICS IOC real</p><p>* <span style="color:var(--ac)">Dual</span> -- Modo comparaci\u00f3n V/R</p><p>Practique primero en modo virtual.</p>',
    tut_b9_content: '<p style="color:var(--gn)">\u00a1Felicidades! Ha aprendido el uso b\u00e1sico.</p><p>Pr\u00f3ximos pasos:</p><p>* <b>Experimentos virtuales</b> -- Simular experimentos reales</p><p>* <b>Integraci\u00f3n EPICS</b> -- Conectar equipos reales</p><p>* <b>Comparaci\u00f3n V/R</b> -- Comparar simulaci\u00f3n y realidad</p>',
    tut_exp_name: 'Pr\u00e1ctica de experimento virtual', tut_exp_desc: 'Experimentos virtuales para cada t\u00e9cnica de medici\u00f3n',
    tut_e1_title: 'XANES Cu K-edge', tut_e2_title: 'Ejecutar escaneo XANES',
    tut_e3_title: 'Experimento de imagen XRF', tut_e4_title: 'Experimento XRD de polvo',
    tut_e1_content: '<p>Realizar\u00e1 una medici\u00f3n <b>Cu K-edge XANES</b>.</p><p style="color:var(--am)">Pulse "Config. auto" para configurar autom\u00e1ticamente.</p>',
    tut_e2_content: '<p>Energ\u00eda configurada en Cu K-edge (8.979 keV).</p><p style="color:var(--am)">En la pesta\u00f1a BS, pulse XANES.</p><p>Al completar, el espectro µ(E) se mostrar\u00e1 abajo.</p>',
    tut_e3_content: '<p>Ahora, <b>imagen XRF</b>.</p><p>El detector SDD recoge rayos X de fluorescencia a 90\u00b0.</p><p style="color:var(--am)">Tras config. auto, un escaneo r\u00e1ster generar\u00e1 un mapa de distribuci\u00f3n elemental.</p>',
    tut_e4_content: '<p>Medici\u00f3n <b>XRD de polvo</b>.</p><p>El detector Eiger 2X recoger\u00e1 patrones de anillos Debye-Scherrer.</p>',
    tut_prev: 'Anterior', tut_next: 'Siguiente', tut_done: 'Hecho'
  },
  th: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u0e2d\u0e2d\u0e1e\u0e15\u0e34\u0e01',
    tab_motors: '\u0e21\u0e2d\u0e40\u0e15\u0e2d\u0e23\u0e4c',  tab_mask: '\u0e21\u0e32\u0e2a\u0e01\u0e4c', tab_measure: '\u0e27\u0e31\u0e14',
    tab_align: '\u0e08\u0e31\u0e14\u0e41\u0e19\u0e27',   tab_compare: '\u0e40\u0e17\u0e35\u0e22\u0e1a',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\u0e04\u0e39\u0e48\u0e21\u0e37\u0e2d', tab_chat: '\u0e41\u0e0a\u0e17',
    tab_expt: '\u0e17\u0e14\u0e25\u0e2d\u0e07',
    hdr_theme: '\u0e18\u0e35\u0e21\u0e2a\u0e35',   hdr_layout: '\u0e40\u0e25\u0e22\u0e4c\u0e40\u0e2d\u0e32\u0e17\u0e4c',
    hdr_mcrays: '\u0e23\u0e31\u0e07\u0e2a\u0e35 MC',  hdr_grid: '\u0e04\u0e27\u0e32\u0e21\u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14\u0e01\u0e23\u0e34\u0e14',
    hdr_language: '\u0e20\u0e32\u0e29\u0e32',
    theme_light: '\u0e2a\u0e27\u0e48\u0e32\u0e07 (\u0e40\u0e23\u0e34\u0e48\u0e21\u0e15\u0e49\u0e19)',   theme_dark: '\u0e21\u0e37\u0e14',
    theme_dark2: '\u0e21\u0e37\u0e14 2',         theme_deuter: '\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e41\u0e14\u0e07-\u0e40\u0e02\u0e35\u0e22\u0e27',
    theme_protan: '\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e41\u0e14\u0e07',      theme_tritan: '\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e19\u0e49\u0e33\u0e40\u0e07\u0e34\u0e19-\u0e40\u0e2b\u0e25\u0e37\u0e2d\u0e07',
    themedesc_light: '\u0e1e\u0e37\u0e49\u0e19\u0e2b\u0e25\u0e31\u0e07\u0e02\u0e32\u0e27\u0e2a\u0e30\u0e2d\u0e32\u0e14',
    themedesc_dark: '\u0e18\u0e35\u0e21\u0e21\u0e37\u0e14\u0e04\u0e2d\u0e19\u0e17\u0e23\u0e32\u0e2a\u0e15\u0e4c\u0e2a\u0e39\u0e07',
    themedesc_dark2: '\u0e18\u0e35\u0e21\u0e21\u0e37\u0e14\u0e19\u0e38\u0e48\u0e21',
    themedesc_deuter: '\u0e1b\u0e25\u0e2d\u0e14\u0e20\u0e31\u0e22\u0e2a\u0e33\u0e2b\u0e23\u0e31\u0e1a\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e41\u0e14\u0e07-\u0e40\u0e02\u0e35\u0e22\u0e27',
    themedesc_protan: '\u0e1b\u0e25\u0e2d\u0e14\u0e20\u0e31\u0e22\u0e2a\u0e33\u0e2b\u0e23\u0e31\u0e1a\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e41\u0e14\u0e07',
    themedesc_tritan: '\u0e1b\u0e25\u0e2d\u0e14\u0e20\u0e31\u0e22\u0e2a\u0e33\u0e2b\u0e23\u0e31\u0e1a\u0e15\u0e32\u0e1a\u0e2d\u0e14\u0e19\u0e49\u0e33\u0e40\u0e07\u0e34\u0e19-\u0e40\u0e2b\u0e25\u0e37\u0e2d\u0e07',
    layout_standard: '\u0e21\u0e32\u0e15\u0e23\u0e10\u0e32\u0e19',      layout_wide: '\u0e21\u0e38\u0e21\u0e01\u0e27\u0e49\u0e32\u0e07',
    layout_compact: '\u0e01\u0e30\u0e17\u0e31\u0e14\u0e23\u0e31\u0e14', layout_focus: '\u0e42\u0e1f\u0e01\u0e31\u0e2a',
    layoutdesc_standard: '\u0e40\u0e25\u0e22\u0e4c\u0e40\u0e2d\u0e32\u0e17\u0e4c\u0e40\u0e15\u0e47\u0e21 (\u0e41\u0e16\u0e1a\u0e02\u0e49\u0e32\u0e07 320px)',
    layoutdesc_wide: '\u0e0b\u0e48\u0e2d\u0e19\u0e41\u0e16\u0e1a\u0e02\u0e49\u0e32\u0e07 \u0e02\u0e22\u0e32\u0e22\u0e21\u0e38\u0e21\u0e21\u0e2d\u0e07\u0e1a\u0e35\u0e21\u0e44\u0e25\u0e19\u0e4c',
    layoutdesc_compact: '\u0e41\u0e16\u0e1a\u0e02\u0e49\u0e32\u0e07\u0e41\u0e04\u0e1a (220px)',
    layoutdesc_focus: '\u0e1a\u0e35\u0e21\u0e44\u0e25\u0e19\u0e4c\u0e40\u0e17\u0e48\u0e32\u0e19\u0e31\u0e49\u0e19 \u0e0b\u0e48\u0e2d\u0e19\u0e41\u0e1c\u0e07\u0e17\u0e31\u0e49\u0e07\u0e2b\u0e21\u0e14',
    mcrays_fast: '\u0e40\u0e23\u0e47\u0e27 -- \u0e15\u0e31\u0e27\u0e2d\u0e22\u0e48\u0e32\u0e07',   mcrays_normal: '\u0e1b\u0e01\u0e15\u0e34 -- \u0e04\u0e38\u0e13\u0e20\u0e32\u0e1e\u0e1b\u0e32\u0e19\u0e01\u0e25\u0e32\u0e07',
    mcrays_default: '\u0e40\u0e23\u0e34\u0e48\u0e21\u0e15\u0e49\u0e19 -- \u0e2a\u0e16\u0e34\u0e15\u0e34\u0e2a\u0e39\u0e07', mcrays_precise: '\u0e41\u0e21\u0e48\u0e19\u0e22\u0e33 -- \u0e0a\u0e49\u0e32',
    mcrays_best: '\u0e04\u0e38\u0e13\u0e20\u0e32\u0e1e\u0e2a\u0e39\u0e07\u0e2a\u0e38\u0e14 -- \u0e0a\u0e49\u0e32\u0e21\u0e32\u0e01',
    grid_standard: '\u0e40\u0e23\u0e34\u0e48\u0e21\u0e15\u0e49\u0e19 -- \u0e40\u0e23\u0e19\u0e40\u0e14\u0e2d\u0e23\u0e4c\u0e40\u0e23\u0e47\u0e27',
    grid_highres: '4x \u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14 -- \u0e23\u0e32\u0e22\u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14\u0e25\u0e33\u0e41\u0e2a\u0e07\u0e40\u0e25\u0e47\u0e01',
    btn_estop: '\u0e2b\u0e22\u0e38\u0e14\u0e09\u0e38\u0e01\u0e40\u0e09\u0e34\u0e19',  btn_reset: '\u0e23\u0e35\u0e40\u0e0b\u0e47\u0e15',
    btn_start: '\u0e40\u0e23\u0e34\u0e48\u0e21',       btn_stop: '\u0e2b\u0e22\u0e38\u0e14',
    btn_save: '\u0e1a\u0e31\u0e19\u0e17\u0e36\u0e01',   btn_close: '\u0e1b\u0e34\u0e14',
    btn_apply: '\u0e43\u0e0a\u0e49\u0e07\u0e32\u0e19',  btn_cancel: '\u0e22\u0e01\u0e40\u0e25\u0e34\u0e01',
    panel_source: '\u0e1e\u0e32\u0e23\u0e32\u0e21\u0e34\u0e40\u0e15\u0e2d\u0e23\u0e4c\u0e41\u0e2b\u0e25\u0e48\u0e07\u0e01\u0e33\u0e40\u0e19\u0e34\u0e14',
    panel_beamline: '\u0e20\u0e32\u0e1e\u0e23\u0e27\u0e21\u0e1a\u0e35\u0e21\u0e44\u0e25\u0e19\u0e4c',
    panel_profile: '\u0e42\u0e1b\u0e23\u0e44\u0e1f\u0e25\u0e4c\u0e25\u0e33\u0e41\u0e2a\u0e07',
    panel_spectrum: '\u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21',
    mode_virtual: '\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19',  mode_real: '\u0e08\u0e23\u0e34\u0e07',  mode_dual: '\u0e04\u0e39\u0e48',
    align_ready: '\u0e1e\u0e23\u0e49\u0e2d\u0e21', align_starting: '\u0e01\u0e33\u0e25\u0e31\u0e07\u0e40\u0e23\u0e34\u0e48\u0e21...', align_scanning: '\u0e01\u0e33\u0e25\u0e31\u0e07\u0e2a\u0e41\u0e01\u0e19...', align_abort: '\u0e22\u0e01\u0e40\u0e25\u0e34\u0e01', align_export_log: '\u0e2a\u0e48\u0e07\u0e2d\u0e2d\u0e01\u0e1a\u0e31\u0e19\u0e17\u0e36\u0e01',
    align_scan_waiting: '\u0e41\u0e1c\u0e19\u0e20\u0e39\u0e21\u0e34\u0e2a\u0e41\u0e01\u0e19 -- \u0e23\u0e2d...', align_pass: '\u0e1c\u0e48\u0e32\u0e19', align_fail: '\u0e44\u0e21\u0e48\u0e1c\u0e48\u0e32\u0e19',
    align_step_fmt: '\u0e02\u0e31\u0e49\u0e19\u0e15\u0e2d\u0e19 {0}/{1}: {2}', align_motor_fmt: '\u0e21\u0e2d\u0e40\u0e15\u0e2d\u0e23\u0e4c={0}', align_intensity_fmt: '\u0e04\u0e27\u0e32\u0e21\u0e40\u0e02\u0e49\u0e21={0}',
    align_centroid_fmt: '\u0e08\u0e38\u0e14\u0e28\u0e39\u0e19\u0e22\u0e4c\u0e01\u0e25\u0e32\u0e07={0} mm', align_beam_at: '\u0e25\u0e33\u0e41\u0e2a\u0e07 @ {0} ({1}m)',
    align_halfcut: '\u0e04\u0e23\u0e36\u0e48\u0e07\u0e15\u0e31\u0e14 (pitch=0)', align_halfcut_c1: '\u0e04\u0e23\u0e36\u0e48\u0e07\u0e15\u0e31\u0e14 C1 (theta=0)',
    align_set_angle: '\u0e15\u0e31\u0e49\u0e07\u0e21\u0e38\u0e21\u0e17\u0e33\u0e07\u0e32\u0e19', align_rot_center: '\u0e28\u0e39\u0e19\u0e22\u0e4c\u0e2b\u0e21\u0e38\u0e19', align_set_bragg: '\u0e15\u0e31\u0e49\u0e07\u0e21\u0e38\u0e21 Bragg',
    align_dtheta2_coarse: 'dTheta2 \u0e2b\u0e22\u0e32\u0e1a', align_dtheta2_fine: 'dTheta2 \u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14',
    align_m1_full: 'M1 \u0e08\u0e31\u0e14\u0e41\u0e19\u0e27\u0e40\u0e15\u0e47\u0e21', align_m2_full: 'M2 \u0e08\u0e31\u0e14\u0e41\u0e19\u0e27\u0e40\u0e15\u0e47\u0e21',
    align_kbv: 'KB-V \u0e08\u0e31\u0e14\u0e41\u0e19\u0e27', align_kbh: 'KB-H \u0e08\u0e31\u0e14\u0e41\u0e19\u0e27', align_dcm_full: 'DCM \u0e08\u0e31\u0e14\u0e41\u0e19\u0e27\u0e40\u0e15\u0e47\u0e21',
    expt_start: '\u0e40\u0e23\u0e34\u0e48\u0e21', expt_stop: '\u0e2b\u0e22\u0e38\u0e14', expt_show: '\u0e41\u0e2a\u0e14\u0e07', expt_save: '\u0e1a\u0e31\u0e19\u0e17\u0e36\u0e01',
    expt_starting_fmt: '\u0e01\u0e33\u0e25\u0e31\u0e07\u0e40\u0e23\u0e34\u0e48\u0e21 {0}...', expt_computing: '\u0e01\u0e33\u0e25\u0e31\u0e07\u0e04\u0e33\u0e19\u0e27\u0e13...', expt_no_result: '\u0e44\u0e21\u0e48\u0e21\u0e35\u0e1c\u0e25\u0e25\u0e31\u0e1e\u0e18\u0e4c\u0e43\u0e2b\u0e49\u0e1a\u0e31\u0e19\u0e17\u0e36\u0e01',
    expt_saved_fmt: '\u0e1a\u0e31\u0e19\u0e17\u0e36\u0e01\u0e41\u0e25\u0e49\u0e27: {0}', expt_ready_msg: '\u0e1e\u0e23\u0e49\u0e2d\u0e21 \u0e1c\u0e25\u0e25\u0e31\u0e1e\u0e18\u0e4c\u0e08\u0e30\u0e41\u0e2a\u0e14\u0e07\u0e43\u0e19\u0e2b\u0e19\u0e49\u0e32\u0e15\u0e48\u0e32\u0e07\u0e41\u0e22\u0e01',
    expt_server_disc: '\u0e40\u0e0b\u0e34\u0e23\u0e4c\u0e1f\u0e40\u0e27\u0e2d\u0e23\u0e4c\u0e08\u0e33\u0e25\u0e2d\u0e07 (\u0e1e\u0e2d\u0e23\u0e4c\u0e15 {0}) \u0e44\u0e21\u0e48\u0e44\u0e14\u0e49\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d',
    expt_beamline_status: '\u0e1a\u0e35\u0e21\u0e44\u0e25\u0e19\u0e4c', expt_server_not_connected: '\u0e40\u0e0b\u0e34\u0e23\u0e4c\u0e1f\u0e40\u0e27\u0e2d\u0e23\u0e4c\u0e08\u0e33\u0e25\u0e2d\u0e07\u0e44\u0e21\u0e48\u0e44\u0e14\u0e49\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d',
    expt_formula: '\u0e2a\u0e39\u0e15\u0e23\u0e40\u0e04\u0e21\u0e35', expt_absorber: '\u0e15\u0e31\u0e27\u0e14\u0e39\u0e14\u0e0b\u0e31\u0e1a', expt_edge: '\u0e02\u0e2d\u0e1a\u0e14\u0e39\u0e14\u0e0b\u0e31\u0e1a', expt_e_range: '\u0e0a\u0e48\u0e27\u0e07 E (eV)', expt_e_step: '\u0e02\u0e31\u0e49\u0e19 E',
    expt_presets: '\u0e1e\u0e23\u0e35\u0e40\u0e0b\u0e47\u0e15', expt_sample: '\u0e15\u0e31\u0e27\u0e2d\u0e22\u0e48\u0e32\u0e07', expt_conc: '\u0e04\u0e27\u0e32\u0e21\u0e40\u0e02\u0e49\u0e21\u0e02\u0e49\u0e19 (ppm)',
    bs_submit_plan: '\u0e2a\u0e48\u0e07\u0e41\u0e1c\u0e19', bs_add_queue: '\u0e40\u0e1e\u0e34\u0e48\u0e21\u0e43\u0e19\u0e04\u0e34\u0e27', bs_run_now: '\u0e23\u0e31\u0e19\u0e17\u0e31\u0e19\u0e17\u0e35', bs_queue_fmt: '\u0e04\u0e34\u0e27 ({0})',
    bs_queue_empty: '\u0e44\u0e21\u0e48\u0e21\u0e35\u0e41\u0e1c\u0e19\u0e43\u0e19\u0e04\u0e34\u0e27', bs_clear: '\u0e25\u0e49\u0e32\u0e07', bs_run_history_fmt: '\u0e1b\u0e23\u0e30\u0e27\u0e31\u0e15\u0e34\u0e01\u0e32\u0e23\u0e23\u0e31\u0e19 ({0})',
    bs_quick_run: '\u0e23\u0e31\u0e19\u0e40\u0e23\u0e47\u0e27', bs_qs_connection: '\u0e01\u0e32\u0e23\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d\u0e40\u0e0b\u0e34\u0e23\u0e4c\u0e1f\u0e40\u0e27\u0e2d\u0e23\u0e4c\u0e04\u0e34\u0e27', bs_connected: '[\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d\u0e41\u0e25\u0e49\u0e27]',
    bs_sim_mode: '[\u0e42\u0e2b\u0e21\u0e14\u0e08\u0e33\u0e25\u0e2d\u0e07]', bs_connect: '\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d', bs_server_history: '\u0e1b\u0e23\u0e30\u0e27\u0e31\u0e15\u0e34\u0e2a\u0e41\u0e01\u0e19\u0e40\u0e0b\u0e34\u0e23\u0e4c\u0e1f\u0e40\u0e27\u0e2d\u0e23\u0e4c',
    bs_click_refresh: '\u0e04\u0e25\u0e34\u0e01[\u0e23\u0e35\u0e40\u0e1f\u0e23\u0e0a]\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e42\u0e2b\u0e25\u0e14\u0e1b\u0e23\u0e30\u0e27\u0e31\u0e15\u0e34\u0e40\u0e0b\u0e34\u0e23\u0e4c\u0e1f\u0e40\u0e27\u0e2d\u0e23\u0e4c',
    status_idle: '\u0e27\u0e48\u0e32\u0e07', status_running: '\u0e01\u0e33\u0e25\u0e31\u0e07\u0e17\u0e33\u0e07\u0e32\u0e19', status_paused: '\u0e2b\u0e22\u0e38\u0e14\u0e0a\u0e31\u0e48\u0e27\u0e04\u0e23\u0e32\u0e27', status_error: '\u0e1c\u0e34\u0e14\u0e1e\u0e25\u0e32\u0e14',
    status_completed: '\u0e40\u0e2a\u0e23\u0e47\u0e08', status_aborted: '\u0e22\u0e01\u0e40\u0e25\u0e34\u0e01',
    tut_basics_name: '\u0e01\u0e32\u0e23\u0e43\u0e0a\u0e49\u0e07\u0e32\u0e19\u0e1e\u0e37\u0e49\u0e19\u0e10\u0e32\u0e19', tut_basics_desc: '\u0e40\u0e23\u0e35\u0e22\u0e19\u0e23\u0e39\u0e49\u0e2d\u0e34\u0e19\u0e40\u0e17\u0e2d\u0e23\u0e4c\u0e40\u0e1f\u0e0b\u0e1e\u0e37\u0e49\u0e19\u0e10\u0e32\u0e19\u0e41\u0e25\u0e30\u0e1f\u0e31\u0e07\u0e01\u0e4c\u0e0a\u0e31\u0e19\u0e2b\u0e25\u0e31\u0e01',
    tut_b1_title: '\u0e22\u0e34\u0e19\u0e14\u0e35\u0e15\u0e49\u0e2d\u0e19\u0e23\u0e31\u0e1a!', tut_b2_title: '1. \u0e1c\u0e31\u0e07\u0e1a\u0e35\u0e21\u0e44\u0e25\u0e19\u0e4c', tut_b3_title: '2. \u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19',
    tut_b4_title: '3. \u0e1b\u0e23\u0e31\u0e1a\u0e2d\u0e38\u0e1b\u0e01\u0e23\u0e13\u0e4c\u0e2d\u0e2d\u0e1e\u0e15\u0e34\u0e01', tut_b5_title: '4. \u0e15\u0e34\u0e14\u0e15\u0e32\u0e21\u0e2a\u0e16\u0e32\u0e19\u0e30', tut_b6_title: '5. \u0e23\u0e31\u0e19\u0e01\u0e32\u0e23\u0e27\u0e31\u0e14',
    tut_b7_title: '6. \u0e04\u0e34\u0e27\u0e17\u0e14\u0e25\u0e2d\u0e07 Bluesky', tut_b8_title: '7. \u0e2a\u0e25\u0e31\u0e1a\u0e42\u0e2b\u0e21\u0e14', tut_b9_title: '\u0e1a\u0e17\u0e40\u0e23\u0e35\u0e22\u0e19\u0e1e\u0e37\u0e49\u0e19\u0e10\u0e32\u0e19\u0e40\u0e2a\u0e23\u0e47\u0e08!',
    tut_b1_content: '<p>\u0e22\u0e34\u0e19\u0e14\u0e35\u0e15\u0e49\u0e2d\u0e19\u0e23\u0e31\u0e1a\u0e2a\u0e39\u0e48 Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>\u0e1a\u0e17\u0e40\u0e23\u0e35\u0e22\u0e19\u0e19\u0e35\u0e49\u0e08\u0e30\u0e41\u0e19\u0e30\u0e19\u0e33\u0e04\u0e38\u0e13\u0e17\u0e35\u0e25\u0e30\u0e02\u0e31\u0e49\u0e19\u0e15\u0e2d\u0e19</p><p style="color:var(--am)">\u0e17\u0e33\u0e15\u0e32\u0e21\u0e04\u0e33\u0e41\u0e19\u0e30\u0e19\u0e33\u0e43\u0e19\u0e41\u0e15\u0e48\u0e25\u0e30\u0e02\u0e31\u0e49\u0e19\u0e15\u0e2d\u0e19</p>',
    tut_b2_content: '<p>\u0e15\u0e23\u0e07\u0e01\u0e25\u0e32\u0e07\u0e41\u0e2a\u0e14\u0e07<b>\u0e2a\u0e2d\u0e07\u0e21\u0e38\u0e21\u0e21\u0e2d\u0e07</b>:</p><p>* <span style="color:var(--ac)">\u0e21\u0e38\u0e21\u0e1a\u0e19</span> -- \u0e23\u0e30\u0e19\u0e32\u0e1a\u0e41\u0e19\u0e27\u0e19\u0e2d\u0e19 (M1/M2 \u0e2a\u0e30\u0e17\u0e49\u0e2d\u0e19\u0e01\u0e23\u0e30\u0e08\u0e01)</p><p>* <span style="color:var(--ac)">\u0e21\u0e38\u0e21\u0e02\u0e49\u0e32\u0e07</span> -- \u0e23\u0e30\u0e19\u0e32\u0e1a\u0e41\u0e19\u0e27\u0e15\u0e31\u0e49\u0e07 (DCM Bragg \u0e01\u0e32\u0e23\u0e40\u0e25\u0e35\u0e49\u0e22\u0e27\u0e40\u0e1a\u0e19)</p><p style="color:var(--gn)">\u0e04\u0e25\u0e34\u0e01\u0e2d\u0e07\u0e04\u0e4c\u0e1b\u0e23\u0e30\u0e01\u0e2d\u0e1a\u0e43\u0e14\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e14\u0e39\u0e23\u0e32\u0e22\u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14\u0e41\u0e25\u0e30\u0e04\u0e27\u0e1a\u0e04\u0e38\u0e21</p>',
    tut_b3_content: '<p>\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e43\u0e19\u0e41\u0e17\u0e47\u0e1a <b>IVU</b> \u0e17\u0e35\u0e48\u0e41\u0e16\u0e1a\u0e02\u0e49\u0e32\u0e07</p><p style="color:var(--am)">\u0e25\u0e32\u0e01\u0e15\u0e31\u0e27\u0e40\u0e25\u0e37\u0e48\u0e2d\u0e19\u0e44\u0e1b\u0e17\u0e35\u0e48 10 keV</p><p>\u0e23\u0e30\u0e1a\u0e1a\u0e08\u0e30\u0e2d\u0e31\u0e15\u0e42\u0e19\u0e21\u0e31\u0e15\u0e34:</p><p>* \u0e40\u0e25\u0e37\u0e2d\u0e01\u0e2e\u0e32\u0e23\u0e4c\u0e21\u0e2d\u0e19\u0e34\u0e01\u0e17\u0e35\u0e48\u0e14\u0e35\u0e17\u0e35\u0e48\u0e2a\u0e38\u0e14</p><p>* \u0e1b\u0e23\u0e31\u0e1a\u0e0a\u0e48\u0e2d\u0e07\u0e27\u0e48\u0e32\u0e07 IVU</p><p>* \u0e04\u0e33\u0e19\u0e27\u0e13\u0e21\u0e38\u0e21 DCM Bragg</p>',
    tut_b4_content: '<p>\u0e1b\u0e23\u0e31\u0e1a\u0e2d\u0e2d\u0e1e\u0e15\u0e34\u0e01\u0e43\u0e19\u0e41\u0e17\u0e47\u0e1a <b>\u0e2d\u0e2d\u0e1e\u0e15\u0e34\u0e01</b>:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- \u0e02\u0e19\u0e32\u0e14\u0e0a\u0e48\u0e2d\u0e07\u0e40\u0e1b\u0e34\u0e14\u0e41\u0e2a\u0e07\u0e02\u0e32\u0e27</p><p>* <span style="color:var(--ac)">M1/M2</span> -- \u0e21\u0e38\u0e21\u0e01\u0e23\u0e30\u0e08\u0e01\u0e40\u0e1a\u0e35\u0e48\u0e22\u0e07\u0e40\u0e1a\u0e19\u0e41\u0e19\u0e27\u0e19\u0e2d\u0e19</p><p>* <span style="color:var(--ac)">SSA</span> -- \u0e0a\u0e48\u0e2d\u0e07\u0e40\u0e1b\u0e34\u0e14\u0e23\u0e2d\u0e07 (\u0e41\u0e2b\u0e25\u0e48\u0e07\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19 KB)</p><p>* <span style="color:var(--ac)">KB</span> -- \u0e1c\u0e25\u0e01\u0e32\u0e23\u0e42\u0e1f\u0e01\u0e31\u0e2a\u0e2a\u0e38\u0e14\u0e17\u0e49\u0e32\u0e22</p><p style="color:var(--am)">\u0e04\u0e25\u0e34\u0e01\u0e41\u0e17\u0e47\u0e1a\u0e2d\u0e2d\u0e1e\u0e15\u0e34\u0e01</p>',
    tut_b5_content: '<p>\u0e02\u0e49\u0e2d\u0e21\u0e39\u0e25\u0e25\u0e33\u0e41\u0e2a\u0e07\u0e41\u0e1a\u0e1a\u0e40\u0e23\u0e35\u0e22\u0e25\u0e44\u0e17\u0e21\u0e4c\u0e17\u0e35\u0e48\u0e41\u0e16\u0e1a\u0e2a\u0e16\u0e32\u0e19\u0e30\u0e14\u0e49\u0e32\u0e19\u0e25\u0e48\u0e32\u0e07:</p><p>* <span style="color:var(--ac)">E</span> -- \u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e1b\u0e31\u0e08\u0e08\u0e38\u0e1a\u0e31\u0e19</p><p>* <span style="color:var(--gn)">Flux</span> -- \u0e1f\u0e25\u0e31\u0e01\u0e0b\u0e4c\u0e42\u0e1f\u0e15\u0e2d\u0e19</p><p>* <span style="color:var(--pk)">Spot</span> -- \u0e02\u0e19\u0e32\u0e14\u0e08\u0e38\u0e14\u0e42\u0e1f\u0e01\u0e31\u0e2a</p><p>\u0e02\u0e19\u0e32\u0e14\u0e25\u0e33\u0e41\u0e2a\u0e07\u0e17\u0e35\u0e48\u0e41\u0e15\u0e48\u0e25\u0e30\u0e2d\u0e07\u0e04\u0e4c\u0e1b\u0e23\u0e30\u0e01\u0e2d\u0e1a\u0e01\u0e47\u0e41\u0e2a\u0e14\u0e07\u0e14\u0e49\u0e27\u0e22</p>',
    tut_b6_content: '<p>\u0e17\u0e14\u0e25\u0e2d\u0e07\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19\u0e43\u0e19\u0e41\u0e17\u0e47\u0e1a <b>\u0e27\u0e31\u0e14</b>:</p><p>* XANES -- \u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21\u0e01\u0e32\u0e23\u0e14\u0e39\u0e14\u0e0b\u0e31\u0e1a</p><p>* XRD -- \u0e23\u0e39\u0e1b\u0e41\u0e1a\u0e1a\u0e01\u0e32\u0e23\u0e40\u0e25\u0e35\u0e49\u0e22\u0e27\u0e40\u0e1a\u0e19</p><p>* XRF -- \u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21\u0e1f\u0e25\u0e39\u0e2d\u0e40\u0e23\u0e2a\u0e40\u0e0b\u0e19\u0e15\u0e4c</p><p>* \u0e41\u0e1c\u0e19\u0e17\u0e35\u0e48 2D -- \u0e01\u0e32\u0e23\u0e17\u0e33\u0e41\u0e1c\u0e19\u0e17\u0e35\u0e48\u0e40\u0e0a\u0e34\u0e07\u0e1e\u0e37\u0e49\u0e19\u0e17\u0e35\u0e48</p><p style="color:var(--gn)">\u0e01\u0e14\u0e40\u0e23\u0e34\u0e48\u0e21\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e2a\u0e41\u0e01\u0e19</p>',
    tut_b7_content: '<p>\u0e17\u0e14\u0e25\u0e2d\u0e07 Bluesky \u0e43\u0e19\u0e41\u0e17\u0e47\u0e1a <b>BS</b>:</p><p>* \u0e40\u0e25\u0e37\u0e2d\u0e01\u0e41\u0e1c\u0e19\u0e41\u0e25\u0e30\u0e15\u0e31\u0e49\u0e07\u0e1e\u0e32\u0e23\u0e32\u0e21\u0e34\u0e40\u0e15\u0e2d\u0e23\u0e4c</p><p>* \u0e40\u0e1e\u0e34\u0e48\u0e21\u0e43\u0e19\u0e04\u0e34\u0e27\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e23\u0e31\u0e19\u0e15\u0e32\u0e21\u0e25\u0e33\u0e14\u0e31\u0e1a</p><p>* \u0e15\u0e34\u0e14\u0e15\u0e32\u0e21\u0e04\u0e27\u0e32\u0e21\u0e04\u0e37\u0e1a\u0e2b\u0e19\u0e49\u0e32\u0e41\u0e1a\u0e1a\u0e40\u0e23\u0e35\u0e22\u0e25\u0e44\u0e17\u0e21\u0e4c</p><p style="color:var(--pr)">\u0e1b\u0e38\u0e48\u0e21\u0e23\u0e31\u0e19\u0e40\u0e23\u0e47\u0e27\u0e43\u0e0a\u0e49\u0e44\u0e14\u0e49\u0e40\u0e0a\u0e48\u0e19\u0e01\u0e31\u0e19</p>',
    tut_b8_content: '<p>\u0e2a\u0e25\u0e31\u0e1a\u0e42\u0e2b\u0e21\u0e14\u0e14\u0e49\u0e27\u0e22\u0e1b\u0e38\u0e48\u0e21\u0e14\u0e49\u0e32\u0e19\u0e1a\u0e19:</p><p>* <span style="color:var(--gn)">\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19</span> -- \u0e08\u0e33\u0e25\u0e2d\u0e07\u0e40\u0e17\u0e48\u0e32\u0e19\u0e31\u0e49\u0e19</p><p>* <span style="color:var(--am)">\u0e08\u0e23\u0e34\u0e07</span> -- \u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d EPICS IOC \u0e08\u0e23\u0e34\u0e07</p><p>* <span style="color:var(--ac)">\u0e04\u0e39\u0e48</span> -- \u0e42\u0e2b\u0e21\u0e14\u0e40\u0e1b\u0e23\u0e35\u0e22\u0e1a\u0e40\u0e17\u0e35\u0e22\u0e1a V/R</p><p>\u0e1d\u0e36\u0e01\u0e43\u0e19\u0e42\u0e2b\u0e21\u0e14\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19\u0e01\u0e48\u0e2d\u0e19</p>',
    tut_b9_content: '<p style="color:var(--gn)">\u0e22\u0e34\u0e19\u0e14\u0e35! \u0e04\u0e38\u0e13\u0e44\u0e14\u0e49\u0e40\u0e23\u0e35\u0e22\u0e19\u0e23\u0e39\u0e49\u0e01\u0e32\u0e23\u0e43\u0e0a\u0e49\u0e07\u0e32\u0e19\u0e1e\u0e37\u0e49\u0e19\u0e10\u0e32\u0e19\u0e41\u0e25\u0e49\u0e27</p><p>\u0e02\u0e31\u0e49\u0e19\u0e15\u0e48\u0e2d\u0e44\u0e1b:</p><p>* <b>\u0e17\u0e14\u0e25\u0e2d\u0e07\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19</b> -- \u0e08\u0e33\u0e25\u0e2d\u0e07\u0e01\u0e32\u0e23\u0e17\u0e14\u0e25\u0e2d\u0e07\u0e08\u0e23\u0e34\u0e07</p><p>* <b>\u0e01\u0e32\u0e23\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d EPICS</b> -- \u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0e2d\u0e2d\u0e38\u0e1b\u0e01\u0e23\u0e13\u0e4c\u0e08\u0e23\u0e34\u0e07</p><p>* <b>\u0e40\u0e1b\u0e23\u0e35\u0e22\u0e1a\u0e40\u0e17\u0e35\u0e22\u0e1a V/R</b> -- \u0e40\u0e1b\u0e23\u0e35\u0e22\u0e1a\u0e08\u0e33\u0e25\u0e2d\u0e07\u0e01\u0e31\u0e1a\u0e02\u0e2d\u0e07\u0e08\u0e23\u0e34\u0e07</p>',
    tut_exp_name: '\u0e1d\u0e36\u0e01\u0e17\u0e14\u0e25\u0e2d\u0e07\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19', tut_exp_desc: '\u0e17\u0e14\u0e25\u0e2d\u0e07\u0e40\u0e2a\u0e21\u0e37\u0e2d\u0e19\u0e2a\u0e33\u0e2b\u0e23\u0e31\u0e1a\u0e41\u0e15\u0e48\u0e25\u0e30\u0e40\u0e17\u0e04\u0e19\u0e34\u0e04',
    tut_e1_title: 'Cu K-edge XANES', tut_e2_title: '\u0e23\u0e31\u0e19\u0e2a\u0e41\u0e01\u0e19 XANES',
    tut_e3_title: '\u0e17\u0e14\u0e25\u0e2d\u0e07 XRF Imaging', tut_e4_title: '\u0e17\u0e14\u0e25\u0e2d\u0e07 Powder XRD',
    tut_e1_content: '<p>\u0e04\u0e38\u0e13\u0e08\u0e30\u0e17\u0e33\u0e01\u0e32\u0e23\u0e27\u0e31\u0e14 <b>Cu K-edge XANES</b></p><p style="color:var(--am)">\u0e01\u0e14 "\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e2d\u0e31\u0e15\u0e42\u0e19\u0e21\u0e31\u0e15\u0e34" \u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e01\u0e33\u0e2b\u0e19\u0e14\u0e04\u0e48\u0e32\u0e2d\u0e31\u0e15\u0e42\u0e19\u0e21\u0e31\u0e15\u0e34</p>',
    tut_e2_content: '<p>\u0e15\u0e31\u0e49\u0e07\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e40\u0e1b\u0e47\u0e19 Cu K-edge (8.979 keV)</p><p style="color:var(--am)">\u0e43\u0e19\u0e41\u0e17\u0e47\u0e1a BS \u0e01\u0e14\u0e1b\u0e38\u0e48\u0e21 XANES \u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e40\u0e23\u0e34\u0e48\u0e21\u0e2a\u0e41\u0e01\u0e19</p><p>\u0e40\u0e21\u0e37\u0e48\u0e2d\u0e2a\u0e41\u0e01\u0e19\u0e40\u0e2a\u0e23\u0e47\u0e08 \u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21 µ(E) \u0e08\u0e30\u0e41\u0e2a\u0e14\u0e07\u0e14\u0e49\u0e32\u0e19\u0e25\u0e48\u0e32\u0e07</p>',
    tut_e3_content: '<p>\u0e15\u0e2d\u0e19\u0e19\u0e35\u0e49 <b>XRF Imaging</b></p><p>\u0e40\u0e04\u0e23\u0e37\u0e48\u0e2d\u0e07\u0e15\u0e23\u0e27\u0e08\u0e27\u0e31\u0e14 SDD \u0e23\u0e31\u0e1a\u0e23\u0e31\u0e07\u0e2a\u0e35\u0e40\u0e2d\u0e01\u0e0b\u0e4c\u0e1f\u0e25\u0e39\u0e2d\u0e40\u0e23\u0e2a\u0e40\u0e0b\u0e19\u0e15\u0e4c\u0e17\u0e35\u0e48 90\u00b0</p><p style="color:var(--am)">\u0e2b\u0e25\u0e31\u0e07\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e2d\u0e31\u0e15\u0e42\u0e19\u0e21\u0e31\u0e15\u0e34 \u0e2a\u0e41\u0e01\u0e19\u0e41\u0e1a\u0e1a\u0e23\u0e32\u0e2a\u0e40\u0e15\u0e2d\u0e23\u0e4c\u0e08\u0e30\u0e2a\u0e23\u0e49\u0e32\u0e07\u0e41\u0e1c\u0e19\u0e17\u0e35\u0e48\u0e01\u0e32\u0e23\u0e01\u0e23\u0e30\u0e08\u0e32\u0e22\u0e18\u0e32\u0e15\u0e38</p>',
    tut_e4_content: '<p>\u0e17\u0e33\u0e01\u0e32\u0e23\u0e27\u0e31\u0e14 <b>Powder XRD</b></p><p>\u0e40\u0e04\u0e23\u0e37\u0e48\u0e2d\u0e07\u0e15\u0e23\u0e27\u0e08\u0e27\u0e31\u0e14 Eiger 2X \u0e08\u0e30\u0e23\u0e31\u0e1a\u0e23\u0e39\u0e1b\u0e41\u0e1a\u0e1a\u0e27\u0e07\u0e41\u0e2b\u0e27\u0e19 Debye-Scherrer</p>',
    tut_prev: '\u0e01\u0e48\u0e2d\u0e19\u0e2b\u0e19\u0e49\u0e32', tut_next: '\u0e16\u0e31\u0e14\u0e44\u0e1b', tut_done: '\u0e40\u0e2a\u0e23\u0e47\u0e08'
  },
  hi: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u0911\u092a\u094d\u091f\u093f\u0915\u094d\u0938',
    tab_motors: '\u092e\u094b\u091f\u0930',  tab_mask: '\u092e\u093e\u0938\u094d\u0915', tab_measure: '\u092e\u093e\u092a',
    tab_align: '\u0938\u0902\u0930\u0947\u0916\u0923',  tab_compare: '\u0924\u0941\u0932\u0928\u093e',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\u0917\u093e\u0907\u0921', tab_chat: '\u091a\u0948\u091f',
    tab_expt: '\u092a\u094d\u0930\u092f\u094b\u0917',
    hdr_theme: '\u0930\u0902\u0917 \u0925\u0940\u092e',   hdr_layout: '\u0932\u0947\u0906\u0909\u091f',
    hdr_mcrays: 'MC \u0915\u093f\u0930\u0923\u0947\u0902',  hdr_grid: '\u0917\u094d\u0930\u093f\u0921 \u0930\u093f\u091c\u093c\u0949\u0932\u094d\u092f\u0942\u0936\u0928',
    hdr_language: '\u092d\u093e\u0937\u093e',
    theme_light: '\u0939\u0932\u094d\u0915\u093e (\u0921\u093f\u092b\u093c\u0949\u0932\u094d\u091f)',   theme_dark: '\u0917\u0939\u0930\u093e',
    theme_dark2: '\u0917\u0939\u0930\u093e 2',         theme_deuter: '\u0921\u094d\u092f\u0942\u091f\u0947\u0930\u0947\u0928\u094b\u092a\u093f\u092f\u093e',
    theme_protan: '\u092a\u094d\u0930\u094b\u091f\u0947\u0928\u094b\u092a\u093f\u092f\u093e',      theme_tritan: '\u091f\u094d\u0930\u093f\u091f\u0947\u0928\u094b\u092a\u093f\u092f\u093e',
    themedesc_light: '\u0938\u093e\u092b\u093c \u0938\u092b\u093c\u0947\u0926 \u092a\u0943\u0937\u094d\u0920\u092d\u0942\u092e\u093f',
    themedesc_dark: '\u0909\u091a\u094d\u091a \u0915\u0902\u091f\u094d\u0930\u093e\u0938\u094d\u091f \u0917\u0939\u0930\u0940 \u0925\u0940\u092e',
    themedesc_dark2: '\u092e\u0902\u0926 \u0917\u0939\u0930\u0940 \u0925\u0940\u092e',
    themedesc_deuter: '\u0932\u093e\u0932-\u0939\u0930\u093e \u0935\u0930\u094d\u0923\u093e\u0902\u0927\u0924\u093e \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924',
    themedesc_protan: '\u0932\u093e\u0932 \u0935\u0930\u094d\u0923\u093e\u0902\u0927\u0924\u093e \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924',
    themedesc_tritan: '\u0928\u0940\u0932\u093e-\u092a\u0940\u0932\u093e \u0935\u0930\u094d\u0923\u093e\u0902\u0927\u0924\u093e \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924',
    layout_standard: '\u092e\u093e\u0928\u0915',       layout_wide: '\u091a\u094c\u0921\u093c\u093e \u0926\u0943\u0936\u094d\u092f',
    layout_compact: '\u0938\u0902\u0915\u094d\u0937\u093f\u092a\u094d\u0924',  layout_focus: '\u092b\u093c\u094b\u0915\u0938',
    layoutdesc_standard: '\u092a\u0942\u0930\u094d\u0923 \u092a\u0948\u0928\u0932 \u0932\u0947\u0906\u0909\u091f (320px \u0938\u093e\u0907\u0921\u092c\u093e\u0930)',
    layoutdesc_wide: '\u0938\u093e\u0907\u0921\u092c\u093e\u0930 \u091b\u0941\u092a\u093e\u090f\u0902, \u092c\u0940\u092e\u0932\u093e\u0907\u0928 \u0926\u0943\u0936\u094d\u092f \u0905\u0927\u093f\u0915\u0924\u092e',
    layoutdesc_compact: '\u0938\u0902\u0915\u094d\u0937\u093f\u092a\u094d\u0924 \u0938\u093e\u0907\u0921\u092c\u093e\u0930 (220px)',
    layoutdesc_focus: '\u0915\u0947\u0935\u0932 \u092c\u0940\u092e\u0932\u093e\u0907\u0928, \u0938\u092d\u0940 \u092a\u0948\u0928\u0932 \u091b\u0941\u092a\u093e\u090f\u0902',
    mcrays_fast: '\u0924\u0947\u091c\u093c -- \u092a\u0942\u0930\u094d\u0935\u093e\u0935\u0932\u094b\u0915\u0928',   mcrays_normal: '\u0938\u093e\u092e\u093e\u0928\u094d\u092f -- \u092e\u0927\u094d\u092f\u092e \u0917\u0941\u0923\u0935\u0924\u094d\u0924\u093e',
    mcrays_default: '\u0921\u093f\u092b\u093c\u0949\u0932\u094d\u091f -- \u0909\u091a\u094d\u091a \u0938\u093e\u0902\u0916\u094d\u092f\u093f\u0915\u0940', mcrays_precise: '\u0938\u091f\u0940\u0915 -- \u0927\u0940\u092e\u093e',
    mcrays_best: '\u0938\u0930\u094d\u0935\u094b\u0924\u094d\u0924\u092e \u0917\u0941\u0923\u0935\u0924\u094d\u0924\u093e -- \u092c\u0939\u0941\u0924 \u0927\u0940\u092e\u093e',
    grid_standard: '\u0921\u093f\u092b\u093c\u0949\u0932\u094d\u091f -- \u0924\u0947\u091c\u093c \u0930\u0947\u0902\u0921\u0930\u093f\u0902\u0917',
    grid_highres: '4x \u0938\u0942\u0915\u094d\u0937\u094d\u092e -- \u091b\u094b\u091f\u0940 \u0915\u093f\u0930\u0923 \u0935\u093f\u0938\u094d\u0924\u093e\u0930',
    btn_estop: '\u0906\u092a\u093e\u0924 \u0930\u094b\u0915',   btn_reset: '\u0930\u0940\u0938\u0947\u091f',
    btn_start: '\u0936\u0941\u0930\u0942',       btn_stop: '\u0930\u0941\u0915\u0947\u0902',
    btn_save: '\u0938\u0939\u0947\u091c\u0947\u0902',    btn_close: '\u092c\u0902\u0926 \u0915\u0930\u0947\u0902',
    btn_apply: '\u0932\u093e\u0917\u0942 \u0915\u0930\u0947\u0902', btn_cancel: '\u0930\u0926\u094d\u0926 \u0915\u0930\u0947\u0902',
    panel_source: '\u0938\u094d\u0930\u094b\u0924 \u092a\u0948\u0930\u093e\u092e\u0940\u091f\u0930',
    panel_beamline: '\u092c\u0940\u092e\u0932\u093e\u0907\u0928 \u0905\u0935\u0932\u094b\u0915\u0928',
    panel_profile: '\u092c\u0940\u092e \u092a\u094d\u0930\u094b\u092b\u093c\u093e\u0907\u0932',
    panel_spectrum: '\u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e',
    mode_virtual: '\u0906\u092d\u093e\u0938\u0940',  mode_real: '\u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915',  mode_dual: '\u0926\u094b\u0939\u0930\u093e',
    align_ready: '\u0924\u0948\u092f\u093e\u0930', align_starting: '\u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e...', align_scanning: '\u0938\u094d\u0915\u0948\u0928 \u0939\u094b \u0930\u0939\u093e...', align_abort: '\u0930\u0926\u094d\u0926', align_export_log: '\u0932\u0949\u0917 \u0928\u093f\u0930\u094d\u092f\u093e\u0924',
    align_scan_waiting: '\u0938\u094d\u0915\u0948\u0928 \u091a\u093e\u0930\u094d\u091f -- \u092a\u094d\u0930\u0924\u0940\u0915\u094d\u0937\u093e...', align_pass: '\u092a\u093e\u0938', align_fail: '\u0935\u093f\u092b\u0932',
    align_step_fmt: '\u091a\u0930\u0923 {0}/{1}: {2}', align_motor_fmt: '\u092e\u094b\u091f\u0930={0}', align_intensity_fmt: '\u0924\u0940\u0935\u094d\u0930\u0924\u093e={0}',
    align_centroid_fmt: '\u0915\u0947\u0902\u0926\u094d\u0930\u0915={0} mm', align_beam_at: '\u092c\u0940\u092e @ {0} ({1}m)',
    align_halfcut: '\u0939\u093e\u092b-\u0915\u091f (pitch=0)', align_halfcut_c1: '\u0939\u093e\u092b-\u0915\u091f C1 (theta=0)',
    align_set_angle: '\u0915\u093e\u0930\u094d\u092f \u0915\u094b\u0923 \u0938\u0947\u091f \u0915\u0930\u0947\u0902', align_rot_center: '\u0918\u0942\u0930\u094d\u0923\u0928 \u0915\u0947\u0902\u0926\u094d\u0930', align_set_bragg: 'Bragg \u0915\u094b\u0923 \u0938\u0947\u091f \u0915\u0930\u0947\u0902',
    align_dtheta2_coarse: 'dTheta2 \u092e\u094b\u091f\u093e', align_dtheta2_fine: 'dTheta2 \u0938\u0942\u0915\u094d\u0937\u094d\u092e',
    align_m1_full: 'M1 \u092a\u0942\u0930\u094d\u0923 \u0938\u0902\u0930\u0947\u0916\u0923', align_m2_full: 'M2 \u092a\u0942\u0930\u094d\u0923 \u0938\u0902\u0930\u0947\u0916\u0923',
    align_kbv: 'KB-V \u0938\u0902\u0930\u0947\u0916\u0923', align_kbh: 'KB-H \u0938\u0902\u0930\u0947\u0916\u0923', align_dcm_full: 'DCM \u092a\u0942\u0930\u094d\u0923 \u0938\u0902\u0930\u0947\u0916\u0923',
    expt_start: '\u0936\u0941\u0930\u0942', expt_stop: '\u0930\u0941\u0915\u0947\u0902', expt_show: '\u0926\u093f\u0916\u093e\u090f\u0902', expt_save: '\u0938\u0939\u0947\u091c\u0947\u0902',
    expt_starting_fmt: '{0} \u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e...', expt_computing: '\u0917\u0923\u0928\u093e \u0939\u094b \u0930\u0939\u0940...', expt_no_result: '\u0938\u0939\u0947\u091c\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0915\u094b\u0908 \u092a\u0930\u093f\u0923\u093e\u092e \u0928\u0939\u0940\u0902',
    expt_saved_fmt: '\u0938\u0939\u0947\u091c\u093e \u0917\u092f\u093e: {0}', expt_ready_msg: '\u0924\u0948\u092f\u093e\u0930\u0964 \u092a\u0930\u093f\u0923\u093e\u092e \u0905\u0932\u0917 \u0935\u093f\u0902\u0921\u094b \u092e\u0947\u0902 \u0926\u093f\u0916\u093e\u0908 \u0926\u0947\u0902\u0917\u0947\u0964',
    expt_server_disc: '\u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928 \u0938\u0930\u094d\u0935\u0930 (\u092a\u094b\u0930\u094d\u091f {0}) \u0915\u0928\u0947\u0915\u094d\u091f \u0928\u0939\u0940\u0902\u0964',
    expt_beamline_status: '\u092c\u0940\u092e\u0932\u093e\u0907\u0928', expt_server_not_connected: '\u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928 \u0938\u0930\u094d\u0935\u0930 \u0915\u0928\u0947\u0915\u094d\u091f \u0928\u0939\u0940\u0902',
    expt_formula: '\u0938\u0942\u0924\u094d\u0930', expt_absorber: '\u0905\u0935\u0936\u094b\u0937\u0915', expt_edge: '\u0905\u0935\u0936\u094b\u0937\u0923 \u0915\u093f\u0928\u093e\u0930\u093e', expt_e_range: 'E \u0938\u0940\u092e\u093e (eV)', expt_e_step: 'E \u091a\u0930\u0923',
    expt_presets: '\u092a\u094d\u0930\u0940\u0938\u0947\u091f', expt_sample: '\u0928\u092e\u0942\u0928\u093e', expt_conc: '\u0938\u093e\u0902\u0926\u094d\u0930\u0924\u093e (ppm)',
    bs_submit_plan: '\u092f\u094b\u091c\u0928\u093e \u0938\u092c\u092e\u093f\u091f \u0915\u0930\u0947\u0902', bs_add_queue: '\u0915\u0924\u093e\u0930 \u092e\u0947\u0902 \u091c\u094b\u0921\u093c\u0947\u0902', bs_run_now: '\u0905\u092d\u0940 \u091a\u0932\u093e\u090f\u0902', bs_queue_fmt: '\u0915\u0924\u093e\u0930 ({0})',
    bs_queue_empty: '\u0915\u0924\u093e\u0930 \u092e\u0947\u0902 \u0915\u094b\u0908 \u092f\u094b\u091c\u0928\u093e \u0928\u0939\u0940\u0902', bs_clear: '\u0938\u093e\u092b\u093c \u0915\u0930\u0947\u0902', bs_run_history_fmt: '\u0930\u0928 \u0907\u0924\u093f\u0939\u093e\u0938 ({0})',
    bs_quick_run: '\u0924\u094d\u0935\u0930\u093f\u0924 \u091a\u0932\u093e\u090f\u0902', bs_qs_connection: '\u0915\u0924\u093e\u0930 \u0938\u0930\u094d\u0935\u0930 \u0915\u0928\u0947\u0915\u094d\u0936\u0928', bs_connected: '[\u0915\u0928\u0947\u0915\u094d\u091f\u0947\u0921]',
    bs_sim_mode: '[\u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928 \u092e\u094b\u0921]', bs_connect: '\u0915\u0928\u0947\u0915\u094d\u091f \u0915\u0930\u0947\u0902', bs_server_history: '\u0938\u0930\u094d\u0935\u0930 \u0938\u094d\u0915\u0948\u0928 \u0907\u0924\u093f\u0939\u093e\u0938',
    bs_click_refresh: '[\u0930\u093f\u092b\u094d\u0930\u0947\u0936] \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0947\u0902 \u0938\u0930\u094d\u0935\u0930 \u0907\u0924\u093f\u0939\u093e\u0938 \u0932\u094b\u0921 \u0915\u0930\u0947\u0902',
    status_idle: '\u0928\u093f\u0937\u094d\u0915\u094d\u0930\u093f\u092f', status_running: '\u091a\u0932 \u0930\u0939\u093e', status_paused: '\u0930\u0941\u0915\u093e', status_error: '\u0924\u094d\u0930\u0941\u091f\u093f',
    status_completed: '\u092a\u0942\u0930\u094d\u0923', status_aborted: '\u0930\u0926\u094d\u0926',
    tut_basics_name: '\u092e\u0942\u0932 \u0909\u092a\u092f\u094b\u0917', tut_basics_desc: '\u092a\u094d\u0930\u094b\u0917\u094d\u0930\u093e\u092e \u0915\u0947 \u092e\u0942\u0932 \u0907\u0902\u091f\u0930\u092b\u093c\u0947\u0938 \u0914\u0930 \u092a\u094d\u0930\u092e\u0941\u0916 \u0915\u093e\u0930\u094d\u092f \u0938\u0940\u0916\u0947\u0902',
    tut_b1_title: '\u0938\u094d\u0935\u093e\u0917\u0924!', tut_b2_title: '1. \u092c\u0940\u092e\u0932\u093e\u0907\u0928 \u0932\u0947\u0906\u0909\u091f', tut_b3_title: '2. \u090a\u0930\u094d\u091c\u093e \u0938\u0947\u091f\u093f\u0902\u0917',
    tut_b4_title: '3. \u0911\u092a\u094d\u091f\u093f\u0915\u0932 \u0915\u0902\u092a\u094b\u0928\u0947\u0902\u091f', tut_b5_title: '4. \u0938\u094d\u0925\u093f\u0924\u093f \u0928\u093f\u0917\u0930\u093e\u0928\u0940', tut_b6_title: '5. \u092e\u093e\u092a \u091a\u0932\u093e\u090f\u0902',
    tut_b7_title: '6. Bluesky \u092a\u094d\u0930\u092f\u094b\u0917 \u0915\u0924\u093e\u0930', tut_b8_title: '7. \u092e\u094b\u0921 \u092c\u0926\u0932\u0947\u0902', tut_b9_title: '\u092e\u0942\u0932 \u091f\u094d\u092f\u0942\u091f\u094b\u0930\u093f\u092f\u0932 \u092a\u0942\u0930\u094d\u0923!',
    tut_b1_content: '<p>\u0938\u094d\u0935\u093e\u0917\u0924! Korea-4GSR ID10 NanoProbe Virtual Beamline \u092e\u0947\u0902!</p><p>\u092f\u0939 \u091f\u094d\u092f\u0942\u091f\u094b\u0930\u093f\u092f\u0932 \u0906\u092a\u0915\u094b \u091a\u0930\u0923\u092c\u0926\u094d\u0927 \u092e\u093e\u0930\u094d\u0917\u0926\u0930\u094d\u0936\u0928 \u0926\u0947\u0917\u093e\u0964</p><p style="color:var(--am)">\u092a\u094d\u0930\u0924\u094d\u092f\u0947\u0915 \u091a\u0930\u0923 \u0915\u0947 \u0928\u093f\u0930\u094d\u0926\u0947\u0936 \u092a\u093e\u0932\u0928 \u0915\u0930\u0947\u0902\u0964</p>',
    tut_b2_content: '<p>\u0915\u0947\u0902\u0926\u094d\u0930 \u092e\u0947\u0902 <b>\u0926\u094b \u0926\u0943\u0936\u094d\u092f</b>:</p><p>* <span style="color:var(--ac)">\u090a\u092a\u0930\u0940 \u0926\u0943\u0936\u094d\u092f</span> -- \u0915\u094d\u0937\u0948\u0924\u093f\u091c \u0924\u0932 (M1/M2 \u0926\u0930\u094d\u092a\u0923 \u092a\u0930\u093e\u0935\u0930\u094d\u0924\u0928)</p><p>* <span style="color:var(--ac)">\u092a\u093e\u0930\u094d\u0936\u094d\u0935 \u0926\u0943\u0936\u094d\u092f</span> -- \u0932\u0902\u092c\u0935\u0924 \u0924\u0932 (DCM Bragg \u0935\u093f\u0935\u0930\u094d\u0924\u0928)</p><p style="color:var(--gn)">\u0935\u093f\u0935\u0930\u0923 \u0914\u0930 \u0928\u093f\u092f\u0902\u0924\u094d\u0930\u0923 \u0915\u0947 \u0932\u093f\u090f \u0915\u093f\u0938\u0940 \u092d\u0940 \u0918\u091f\u0915 \u092a\u0930 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0947\u0902\u0964</p>',
    tut_b3_content: '<p><b>IVU \u091f\u0948\u092c</b> \u092e\u0947\u0902 \u0932\u0915\u094d\u0937\u094d\u092f \u090a\u0930\u094d\u091c\u093e \u0938\u0947\u091f \u0915\u0930\u0947\u0902\u0964</p><p style="color:var(--am)">\u0938\u094d\u0932\u093e\u0907\u0921\u0930 \u0915\u094b 10 keV \u092a\u0930 \u0916\u0940\u0902\u091a\u0947\u0902\u0964</p><p>\u0938\u093f\u0938\u094d\u091f\u092e \u0938\u094d\u0935\u091a\u093e\u0932\u093f\u0924 \u0930\u0942\u092a \u0938\u0947:</p><p>* \u0907\u0937\u094d\u091f\u0924\u092e \u0939\u093e\u0930\u094d\u092e\u094b\u0928\u093f\u0915 \u091a\u0941\u0928\u0947\u0917\u093e</p><p>* IVU \u0917\u0948\u092a \u0938\u092e\u093e\u092f\u094b\u091c\u093f\u0924 \u0915\u0930\u0947\u0917\u093e</p><p>* DCM Bragg \u0915\u094b\u0923 \u0917\u0923\u0928\u093e \u0915\u0930\u0947\u0917\u093e</p>',
    tut_b4_content: '<p><b>\u0911\u092a\u094d\u091f\u093f\u0915\u094d\u0938 \u091f\u0948\u092c</b> \u092e\u0947\u0902 \u0911\u092a\u094d\u091f\u093f\u0915\u094d\u0938 \u0938\u092e\u093e\u092f\u094b\u091c\u093f\u0924 \u0915\u0930\u0947\u0902:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- \u0936\u094d\u0935\u0947\u0924 \u092c\u0940\u092e \u0938\u094d\u0932\u093f\u091f</p><p>* <span style="color:var(--ac)">M1/M2</span> -- \u0915\u094d\u0937\u0948\u0924\u093f\u091c \u0935\u093f\u0915\u094d\u0937\u0947\u092a\u0923 \u0926\u0930\u094d\u092a\u0923</p><p>* <span style="color:var(--ac)">SSA</span> -- \u0926\u094d\u0935\u093f\u0924\u0940\u092f\u0915 \u0938\u094d\u0932\u093f\u091f (KB \u0906\u092d\u093e\u0938\u0940 \u0938\u094d\u0930\u094b\u0924)</p><p>* <span style="color:var(--ac)">KB</span> -- \u0905\u0902\u0924\u093f\u092e \u092b\u094b\u0915\u0938 \u092a\u0930\u093f\u0923\u093e\u092e</p><p style="color:var(--am)">\u0911\u092a\u094d\u091f\u093f\u0915\u094d\u0938 \u091f\u0948\u092c \u092a\u0930 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0947\u0902\u0964</p>',
    tut_b5_content: '<p>\u0928\u0940\u091a\u0947 \u0938\u094d\u091f\u0947\u091f\u0938 \u092c\u093e\u0930 \u092e\u0947\u0902 \u0930\u093f\u092f\u0932\u091f\u093e\u0907\u092e \u091c\u093e\u0928\u0915\u093e\u0930\u0940:</p><p>* <span style="color:var(--ac)">E</span> -- \u0935\u0930\u094d\u0924\u092e\u093e\u0928 \u090a\u0930\u094d\u091c\u093e</p><p>* <span style="color:var(--gn)">Flux</span> -- \u092b\u094b\u091f\u0949\u0928 \u092b\u094d\u0932\u0915\u094d\u0938</p><p>* <span style="color:var(--pk)">Spot</span> -- \u092b\u094b\u0915\u0932 \u0938\u094d\u092a\u0949\u091f \u0906\u0915\u093e\u0930</p><p>\u092a\u094d\u0930\u0924\u094d\u092f\u0947\u0915 \u0918\u091f\u0915 \u092a\u0930 \u092c\u0940\u092e \u0906\u0915\u093e\u0930 \u092d\u0940 \u0926\u093f\u0916\u093e\u090f \u091c\u093e\u0924\u0947 \u0939\u0948\u0902\u0964</p>',
    tut_b6_content: '<p><b>\u092e\u093e\u092a \u091f\u0948\u092c</b> \u092e\u0947\u0902 \u0906\u092d\u093e\u0938\u0940 \u092a\u094d\u0930\u092f\u094b\u0917:</p><p>* XANES -- \u0905\u0935\u0936\u094b\u0937\u0923 \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e</p><p>* XRD -- \u0935\u093f\u0935\u0930\u094d\u0924\u0928 \u092a\u094d\u0930\u093e\u0930\u0942\u092a</p><p>* XRF -- \u092a\u094d\u0930\u0924\u093f\u0926\u0940\u092a\u094d\u0924\u093f \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e</p><p>* 2D \u092e\u093e\u0928\u091a\u093f\u0924\u094d\u0930 -- \u0938\u094d\u0925\u093e\u0928\u093f\u0915 \u092e\u0948\u092a\u093f\u0902\u0917</p><p style="color:var(--gn)">\u0938\u094d\u0915\u0948\u0928 \u0936\u0941\u0930\u0942 \u0915\u0930\u0947\u0902\u0964</p>',
    tut_b7_content: '<p><b>BS \u091f\u0948\u092c</b> \u092e\u0947\u0902 Bluesky \u092a\u094d\u0930\u092f\u094b\u0917:</p><p>* \u092f\u094b\u091c\u0928\u093e \u091a\u0941\u0928\u0947\u0902 \u0914\u0930 \u092a\u0948\u0930\u093e\u092e\u0940\u091f\u0930 \u0938\u0947\u091f \u0915\u0930\u0947\u0902</p><p>* \u0915\u094d\u0930\u092e\u0936: \u0915\u0924\u093e\u0930 \u092e\u0947\u0902 \u091c\u094b\u0921\u093c\u0947\u0902</p><p>* \u0930\u093f\u092f\u0932\u091f\u093e\u0907\u092e \u092a\u094d\u0930\u0917\u0924\u093f \u0928\u093f\u0917\u0930\u093e\u0928\u0940</p><p style="color:var(--pr)">\u0924\u094d\u0935\u0930\u093f\u0924 \u091a\u0932\u093e\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u092c\u091f\u0928 \u092d\u0940 \u0909\u092a\u0932\u092c\u094d\u0927</p>',
    tut_b8_content: '<p>\u090a\u092a\u0930 \u092e\u094b\u0921 \u092c\u091f\u0928 \u0938\u0947 \u092e\u094b\u0921 \u092c\u0926\u0932\u0947\u0902:</p><p>* <span style="color:var(--gn)">\u0906\u092d\u093e\u0938\u0940</span> -- \u0915\u0947\u0935\u0932 \u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928</p><p>* <span style="color:var(--am)">\u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915</span> -- \u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915 EPICS IOC \u0915\u0928\u0947\u0915\u094d\u0936\u0928</p><p>* <span style="color:var(--ac)">\u0926\u094b\u0939\u0930\u093e</span> -- V/R \u0924\u0941\u0932\u0928\u093e \u092e\u094b\u0921</p><p>\u092a\u0939\u0932\u0947 \u0906\u092d\u093e\u0938\u0940 \u092e\u094b\u0921 \u092e\u0947\u0902 \u0905\u092d\u094d\u092f\u093e\u0938 \u0915\u0930\u0947\u0902\u0964</p>',
    tut_b9_content: '<p style="color:var(--gn)">\u092c\u0927\u093e\u0908! \u0906\u092a\u0928\u0947 \u092e\u0942\u0932 \u0909\u092a\u092f\u094b\u0917 \u0938\u0940\u0916 \u0932\u093f\u092f\u093e\u0964</p><p>\u0905\u0917\u0932\u0947 \u0915\u0926\u092e:</p><p>* <b>\u0906\u092d\u093e\u0938\u0940 \u092a\u094d\u0930\u092f\u094b\u0917</b> -- \u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915 \u092a\u094d\u0930\u092f\u094b\u0917 \u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928</p><p>* <b>EPICS \u090f\u0915\u0940\u0915\u0930\u0923</b> -- \u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915 \u0909\u092a\u0915\u0930\u0923 \u0915\u0928\u0947\u0915\u094d\u091f \u0915\u0930\u0947\u0902</p><p>* <b>V/R \u0924\u0941\u0932\u0928\u093e</b> -- \u0938\u093f\u092e\u0941\u0932\u0947\u0936\u0928 \u0914\u0930 \u0935\u093e\u0938\u094d\u0924\u0935\u093f\u0915\u0924\u093e \u0924\u0941\u0932\u0928\u093e</p>',
    tut_exp_name: '\u0906\u092d\u093e\u0938\u0940 \u092a\u094d\u0930\u092f\u094b\u0917 \u0905\u092d\u094d\u092f\u093e\u0938', tut_exp_desc: '\u092a\u094d\u0930\u0924\u094d\u092f\u0947\u0915 \u092e\u093e\u092a \u0924\u0915\u0928\u0940\u0915 \u0915\u0947 \u0932\u093f\u090f \u0906\u092d\u093e\u0938\u0940 \u092a\u094d\u0930\u092f\u094b\u0917',
    tut_e1_title: 'Cu K-edge XANES', tut_e2_title: 'XANES \u0938\u094d\u0915\u0948\u0928 \u091a\u0932\u093e\u090f\u0902',
    tut_e3_title: 'XRF \u0907\u092e\u0947\u091c\u093f\u0902\u0917 \u092a\u094d\u0930\u092f\u094b\u0917', tut_e4_title: '\u092a\u093e\u0909\u0921\u0930 XRD \u092a\u094d\u0930\u092f\u094b\u0917',
    tut_e1_content: '<p>\u0906\u092a <b>Cu K-edge XANES</b> \u092e\u093e\u092a \u0915\u0930\u0947\u0902\u0917\u0947\u0964</p><p style="color:var(--am)">\u0938\u094d\u0935\u091a\u093e\u0932\u093f\u0924 \u0915\u0949\u0928\u094d\u092b\u093f\u0917\u0930\u0947\u0936\u0928 \u0915\u0947 \u0932\u093f\u090f "\u0911\u091f\u094b \u0938\u0947\u091f\u0905\u092a" \u0926\u092c\u093e\u090f\u0902\u0964</p>',
    tut_e2_content: '<p>\u090a\u0930\u094d\u091c\u093e Cu K-edge (8.979 keV) \u092a\u0930 \u0938\u0947\u091f \u0939\u0948\u0964</p><p style="color:var(--am)">BS \u091f\u0948\u092c \u092e\u0947\u0902 XANES \u0926\u092c\u093e\u090f\u0902\u0964</p><p>\u0938\u094d\u0915\u0948\u0928 \u092a\u0942\u0930\u093e \u0939\u094b\u0928\u0947 \u092a\u0930 µ(E) \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e \u0928\u0940\u091a\u0947 \u0926\u093f\u0916\u0947\u0917\u093e\u0964</p>',
    tut_e3_content: '<p>\u0905\u092c <b>XRF \u0907\u092e\u0947\u091c\u093f\u0902\u0917</b>\u0964</p><p>SDD \u0921\u093f\u091f\u0947\u0915\u094d\u091f\u0930 90\u00b0 \u092a\u0930 \u092b\u094d\u0932\u0942\u0930\u094b\u0938\u0947\u0902\u091f X-\u0930\u0947 \u0938\u0902\u0917\u094d\u0930\u0939\u0940\u0924 \u0915\u0930\u0924\u093e \u0939\u0948\u0964</p><p style="color:var(--am)">\u0911\u091f\u094b \u0938\u0947\u091f\u0905\u092a \u0915\u0947 \u092c\u093e\u0926 \u0930\u093e\u0938\u094d\u091f\u0930 \u0938\u094d\u0915\u0948\u0928 \u0924\u093e\u0924\u094d\u0935\u093f\u0915 \u0935\u093f\u0924\u0930\u0923 \u092e\u0948\u092a \u092c\u0928\u093e\u090f\u0917\u093e\u0964</p>',
    tut_e4_content: '<p><b>\u092a\u093e\u0909\u0921\u0930 XRD</b> \u092e\u093e\u092a\u0964</p><p>Eiger 2X \u0921\u093f\u091f\u0947\u0915\u094d\u091f\u0930 Debye-Scherrer \u0930\u093f\u0902\u0917 \u092a\u0948\u091f\u0930\u094d\u0928 \u0938\u0902\u0917\u094d\u0930\u0939\u0940\u0924 \u0915\u0930\u0947\u0917\u093e\u0964</p>',
    tut_prev: '\u092a\u093f\u091b\u0932\u093e', tut_next: '\u0905\u0917\u0932\u093e', tut_done: '\u092a\u0942\u0930\u094d\u0923'
  },
  ar: {
    tab_undulator: 'IVU',   tab_dcm: 'DCM',     tab_optics: '\u0628\u0635\u0631\u064a\u0627\u062a',
    tab_motors: '\u0645\u062d\u0631\u0643\u0627\u062a',  tab_mask: '\u0642\u0646\u0627\u0639', tab_measure: '\u0642\u064a\u0627\u0633',
    tab_align: '\u0645\u062d\u0627\u0630\u0627\u0629',  tab_compare: '\u0645\u0642\u0627\u0631\u0646\u0629',  tab_epics: 'EPICS',
    tab_bluesky: 'BS',      tab_guide: '\u062f\u0644\u064a\u0644', tab_chat: '\u062f\u0631\u062f\u0634\u0629',
    tab_expt: '\u062a\u062c\u0631\u0628\u0629',
    hdr_theme: '\u0633\u0645\u0629 \u0627\u0644\u0644\u0648\u0646',   hdr_layout: '\u0627\u0644\u062a\u062e\u0637\u064a\u0637',
    hdr_mcrays: '\u0623\u0634\u0639\u0629 MC',  hdr_grid: '\u062f\u0642\u0629 \u0627\u0644\u0634\u0628\u0643\u0629',
    hdr_language: '\u0627\u0644\u0644\u063a\u0629',
    theme_light: '\u0641\u0627\u062a\u062d (\u0627\u0641\u062a\u0631\u0627\u0636\u064a)',   theme_dark: '\u062f\u0627\u0643\u0646',
    theme_dark2: '\u062f\u0627\u0643\u0646 2',         theme_deuter: '\u0639\u0645\u0649 \u0623\u062d\u0645\u0631-\u0623\u062e\u0636\u0631',
    theme_protan: '\u0639\u0645\u0649 \u0623\u062d\u0645\u0631',      theme_tritan: '\u0639\u0645\u0649 \u0623\u0632\u0631\u0642-\u0623\u0635\u0641\u0631',
    themedesc_light: '\u062e\u0644\u0641\u064a\u0629 \u0628\u064a\u0636\u0627\u0621 \u0646\u0638\u064a\u0641\u0629',
    themedesc_dark: '\u0633\u0645\u0629 \u062f\u0627\u0643\u0646\u0629 \u0639\u0627\u0644\u064a\u0629 \u0627\u0644\u062a\u0628\u0627\u064a\u0646',
    themedesc_dark2: '\u0633\u0645\u0629 \u062f\u0627\u0643\u0646\u0629 \u0647\u0627\u062f\u0626\u0629',
    themedesc_deuter: '\u0622\u0645\u0646 \u0644\u0639\u0645\u0649 \u0627\u0644\u0623\u062d\u0645\u0631-\u0627\u0644\u0623\u062e\u0636\u0631',
    themedesc_protan: '\u0622\u0645\u0646 \u0644\u0639\u0645\u0649 \u0627\u0644\u0623\u062d\u0645\u0631',
    themedesc_tritan: '\u0622\u0645\u0646 \u0644\u0639\u0645\u0649 \u0627\u0644\u0623\u0632\u0631\u0642-\u0627\u0644\u0623\u0635\u0641\u0631',
    layout_standard: '\u0642\u064a\u0627\u0633\u064a',       layout_wide: '\u0639\u0631\u0636 \u0648\u0627\u0633\u0639',
    layout_compact: '\u0645\u0636\u063a\u0648\u0637',  layout_focus: '\u062a\u0631\u0643\u064a\u0632',
    layoutdesc_standard: '\u062a\u062e\u0637\u064a\u0637 \u0643\u0627\u0645\u0644 (\u0634\u0631\u064a\u0637 \u062c\u0627\u0646\u0628\u064a 320px)',
    layoutdesc_wide: '\u0625\u062e\u0641\u0627\u0621 \u0627\u0644\u0634\u0631\u064a\u0637 \u0627\u0644\u062c\u0627\u0646\u0628\u064a\u060c \u062a\u0643\u0628\u064a\u0631 \u0639\u0631\u0636 \u0627\u0644\u062e\u0637',
    layoutdesc_compact: '\u0634\u0631\u064a\u0637 \u062c\u0627\u0646\u0628\u064a \u0636\u064a\u0642 (220px)',
    layoutdesc_focus: '\u062e\u0637 \u0627\u0644\u0634\u0639\u0627\u0639 \u0641\u0642\u0637\u060c \u0625\u062e\u0641\u0627\u0621 \u0643\u0644 \u0627\u0644\u0644\u0648\u062d\u0627\u062a',
    mcrays_fast: '\u0633\u0631\u064a\u0639 -- \u0645\u0639\u0627\u064a\u0646\u0629',   mcrays_normal: '\u0639\u0627\u062f\u064a -- \u062c\u0648\u062f\u0629 \u0645\u062a\u0648\u0633\u0637\u0629',
    mcrays_default: '\u0627\u0641\u062a\u0631\u0627\u0636\u064a -- \u0625\u062d\u0635\u0627\u0626\u064a\u0627\u062a \u0639\u0627\u0644\u064a\u0629', mcrays_precise: '\u062f\u0642\u064a\u0642 -- \u0628\u0637\u064a\u0621',
    mcrays_best: '\u0623\u0641\u0636\u0644 \u062c\u0648\u062f\u0629 -- \u0628\u0637\u064a\u0621 \u062c\u062f\u0627\u064b',
    grid_standard: '\u0627\u0641\u062a\u0631\u0627\u0636\u064a -- \u0639\u0631\u0636 \u0633\u0631\u064a\u0639',
    grid_highres: '4x \u0623\u062f\u0642 -- \u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0634\u0639\u0627\u0639 \u0627\u0644\u0635\u063a\u064a\u0631',
    btn_estop: '\u0625\u064a\u0642\u0627\u0641 \u0637\u0648\u0627\u0631\u0626',  btn_reset: '\u0625\u0639\u0627\u062f\u0629 \u062a\u0639\u064a\u064a\u0646',
    btn_start: '\u0628\u062f\u0621',         btn_stop: '\u0625\u064a\u0642\u0627\u0641',
    btn_save: '\u062d\u0641\u0638',          btn_close: '\u0625\u063a\u0644\u0627\u0642',
    btn_apply: '\u062a\u0637\u0628\u064a\u0642',  btn_cancel: '\u0625\u0644\u063a\u0627\u0621',
    panel_source: '\u0645\u0639\u0644\u0645\u0627\u062a \u0627\u0644\u0645\u0635\u062f\u0631',
    panel_beamline: '\u0646\u0638\u0631\u0629 \u0639\u0627\u0645\u0629 \u0639\u0644\u0649 \u062e\u0637 \u0627\u0644\u0634\u0639\u0627\u0639',
    panel_profile: '\u0645\u0644\u0641 \u0627\u0644\u0634\u0639\u0627\u0639',
    panel_spectrum: '\u0627\u0644\u0637\u064a\u0641',
    mode_virtual: '\u0627\u0641\u062a\u0631\u0627\u0636\u064a',  mode_real: '\u062d\u0642\u064a\u0642\u064a',  mode_dual: '\u0645\u0632\u062f\u0648\u062c',
    align_ready: '\u062c\u0627\u0647\u0632', align_starting: '\u062c\u0627\u0631\u064a \u0627\u0644\u0628\u062f\u0621...', align_scanning: '\u062c\u0627\u0631\u064a \u0627\u0644\u0645\u0633\u062d...', align_abort: '\u0625\u0644\u063a\u0627\u0621', align_export_log: '\u062a\u0635\u062f\u064a\u0631 \u0627\u0644\u0633\u062c\u0644',
    align_scan_waiting: '\u0645\u062e\u0637\u0637 \u0627\u0644\u0645\u0633\u062d -- \u0627\u0646\u062a\u0638\u0627\u0631...', align_pass: '\u0646\u062c\u0627\u062d', align_fail: '\u0641\u0634\u0644',
    align_step_fmt: '\u062e\u0637\u0648\u0629 {0}/{1}: {2}', align_motor_fmt: '\u0645\u062d\u0631\u0643={0}', align_intensity_fmt: '\u0634\u062f\u0629={0}',
    align_centroid_fmt: '\u0645\u0631\u0643\u0632 \u0627\u0644\u062b\u0642\u0644={0} mm', align_beam_at: '\u0627\u0644\u0634\u0639\u0627\u0639 @ {0} ({1}m)',
    align_halfcut: '\u0646\u0635\u0641 \u0642\u0637\u0639 (pitch=0)', align_halfcut_c1: '\u0646\u0635\u0641 \u0642\u0637\u0639 C1 (theta=0)',
    align_set_angle: '\u062a\u0639\u064a\u064a\u0646 \u0632\u0627\u0648\u064a\u0629 \u0627\u0644\u0639\u0645\u0644', align_rot_center: '\u0645\u0631\u0643\u0632 \u0627\u0644\u062f\u0648\u0631\u0627\u0646', align_set_bragg: '\u062a\u0639\u064a\u064a\u0646 \u0632\u0627\u0648\u064a\u0629 Bragg',
    align_dtheta2_coarse: 'dTheta2 \u062e\u0634\u0646', align_dtheta2_fine: 'dTheta2 \u062f\u0642\u064a\u0642',
    align_m1_full: 'M1 \u0645\u062d\u0627\u0630\u0627\u0629 \u0643\u0627\u0645\u0644\u0629', align_m2_full: 'M2 \u0645\u062d\u0627\u0630\u0627\u0629 \u0643\u0627\u0645\u0644\u0629',
    align_kbv: 'KB-V \u0645\u062d\u0627\u0630\u0627\u0629', align_kbh: 'KB-H \u0645\u062d\u0627\u0630\u0627\u0629', align_dcm_full: 'DCM \u0645\u062d\u0627\u0630\u0627\u0629 \u0643\u0627\u0645\u0644\u0629',
    expt_start: '\u0628\u062f\u0621', expt_stop: '\u0625\u064a\u0642\u0627\u0641', expt_show: '\u0639\u0631\u0636', expt_save: '\u062d\u0641\u0638',
    expt_starting_fmt: '\u062c\u0627\u0631\u064a \u0628\u062f\u0621 {0}...', expt_computing: '\u062c\u0627\u0631\u064a \u0627\u0644\u062d\u0633\u0627\u0628...', expt_no_result: '\u0644\u0627 \u062a\u0648\u062c\u062f \u0646\u062a\u0627\u0626\u062c \u0644\u0644\u062d\u0641\u0638',
    expt_saved_fmt: '\u062a\u0645 \u0627\u0644\u062d\u0641\u0638: {0}', expt_ready_msg: '\u062c\u0627\u0647\u0632. \u0633\u062a\u0638\u0647\u0631 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0641\u064a \u0646\u0627\u0641\u0630\u0629 \u0645\u0646\u0641\u0635\u0644\u0629.',
    expt_server_disc: '\u062e\u0627\u062f\u0645 \u0627\u0644\u0645\u062d\u0627\u0643\u0627\u0629 (\u0645\u0646\u0641\u0630 {0}) \u063a\u064a\u0631 \u0645\u062a\u0635\u0644.',
    expt_beamline_status: '\u062e\u0637 \u0627\u0644\u0634\u0639\u0627\u0639', expt_server_not_connected: '\u062e\u0627\u062f\u0645 \u0627\u0644\u0645\u062d\u0627\u0643\u0627\u0629 \u063a\u064a\u0631 \u0645\u062a\u0635\u0644',
    expt_formula: '\u0627\u0644\u0635\u064a\u063a\u0629', expt_absorber: '\u0627\u0644\u0645\u0627\u0635', expt_edge: '\u062d\u0627\u0641\u0629 \u0627\u0644\u0627\u0645\u062a\u0635\u0627\u0635', expt_e_range: '\u0646\u0637\u0627\u0642 E (eV)', expt_e_step: '\u062e\u0637\u0648\u0629 E',
    expt_presets: '\u0625\u0639\u062f\u0627\u062f\u0627\u062a \u0645\u0633\u0628\u0642\u0629', expt_sample: '\u0639\u064a\u0646\u0629', expt_conc: '\u062a\u0631\u0643\u064a\u0632 (ppm)',
    bs_submit_plan: '\u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u062e\u0637\u0629', bs_add_queue: '\u0625\u0636\u0627\u0641\u0629 \u0644\u0644\u0637\u0627\u0628\u0648\u0631', bs_run_now: '\u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0622\u0646', bs_queue_fmt: '\u0637\u0627\u0628\u0648\u0631 ({0})',
    bs_queue_empty: '\u0644\u0627 \u062a\u0648\u062c\u062f \u062e\u0637\u0637 \u0641\u064a \u0627\u0644\u0637\u0627\u0628\u0648\u0631', bs_clear: '\u0645\u0633\u062d', bs_run_history_fmt: '\u0633\u062c\u0644 \u0627\u0644\u062a\u0634\u063a\u064a\u0644 ({0})',
    bs_quick_run: '\u062a\u0634\u063a\u064a\u0644 \u0633\u0631\u064a\u0639', bs_qs_connection: '\u0627\u062a\u0635\u0627\u0644 \u062e\u0627\u062f\u0645 \u0627\u0644\u0637\u0627\u0628\u0648\u0631', bs_connected: '[\u0645\u062a\u0635\u0644]',
    bs_sim_mode: '[\u0648\u0636\u0639 \u0627\u0644\u0645\u062d\u0627\u0643\u0627\u0629]', bs_connect: '\u0627\u062a\u0635\u0627\u0644', bs_server_history: '\u0633\u062c\u0644 \u0645\u0633\u062d \u0627\u0644\u062e\u0627\u062f\u0645',
    bs_click_refresh: '\u0627\u0636\u063a\u0637 [\u062a\u062d\u062f\u064a\u062b] \u0644\u062a\u062d\u0645\u064a\u0644 \u0633\u062c\u0644 \u0627\u0644\u062e\u0627\u062f\u0645',
    status_idle: '\u062e\u0627\u0645\u0644', status_running: '\u064a\u0639\u0645\u0644', status_paused: '\u0645\u0624\u0642\u062a', status_error: '\u062e\u0637\u0623',
    status_completed: '\u0645\u0643\u062a\u0645\u0644', status_aborted: '\u0645\u0644\u063a\u0649',
    tut_basics_name: '\u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0627\u0644\u0623\u0633\u0627\u0633\u064a', tut_basics_desc: '\u062a\u0639\u0644\u0645 \u0627\u0644\u0648\u0627\u062c\u0647\u0629 \u0627\u0644\u0623\u0633\u0627\u0633\u064a\u0629 \u0648\u0627\u0644\u0648\u0638\u0627\u0626\u0641 \u0627\u0644\u0631\u0626\u064a\u0633\u064a\u0629',
    tut_b1_title: '\u0645\u0631\u062d\u0628\u0627!', tut_b2_title: '1. \u062a\u062e\u0637\u064a\u0637 \u062e\u0637 \u0627\u0644\u0634\u0639\u0627\u0639', tut_b3_title: '2. \u0625\u0639\u062f\u0627\u062f \u0627\u0644\u0637\u0627\u0642\u0629',
    tut_b4_title: '3. \u0627\u0644\u0645\u0643\u0648\u0646\u0627\u062a \u0627\u0644\u0628\u0635\u0631\u064a\u0629', tut_b5_title: '4. \u0645\u0631\u0627\u0642\u0628\u0629 \u0627\u0644\u062d\u0627\u0644\u0629', tut_b6_title: '5. \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0642\u064a\u0627\u0633\u0627\u062a',
    tut_b7_title: '6. \u0637\u0627\u0628\u0648\u0631 \u062a\u062c\u0627\u0631\u0628 Bluesky', tut_b8_title: '7. \u062a\u0628\u062f\u064a\u0644 \u0627\u0644\u0648\u0636\u0639', tut_b9_title: '\u0627\u0643\u062a\u0645\u0644 \u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c \u0627\u0644\u062a\u0639\u0644\u064a\u0645\u064a!',
    tut_b1_content: '<p>\u0645\u0631\u062d\u0628\u0627 \u0628\u0643 \u0641\u064a Korea-4GSR ID10 NanoProbe Virtual Beamline!</p><p>\u0633\u064a\u0631\u0634\u062f\u0643 \u0647\u0630\u0627 \u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c \u0627\u0644\u062a\u0639\u0644\u064a\u0645\u064a \u062e\u0637\u0648\u0629 \u0628\u062e\u0637\u0648\u0629.</p><p style="color:var(--am)">\u0627\u062a\u0628\u0639 \u0627\u0644\u062a\u0639\u0644\u064a\u0645\u0627\u062a \u0641\u064a \u0643\u0644 \u062e\u0637\u0648\u0629.</p>',
    tut_b2_content: '<p>\u0641\u064a \u0627\u0644\u0645\u0646\u062a\u0635\u0641 <b>\u0639\u0631\u0636\u0627\u0646</b>:</p><p>* <span style="color:var(--ac)">\u0645\u0646\u0638\u0631 \u0639\u0644\u0648\u064a</span> -- \u0627\u0644\u0645\u0633\u062a\u0648\u0649 \u0627\u0644\u0623\u0641\u0642\u064a (\u0627\u0646\u0639\u0643\u0627\u0633\u0627\u062a M1/M2)</p><p>* <span style="color:var(--ac)">\u0645\u0646\u0638\u0631 \u062c\u0627\u0646\u0628\u064a</span> -- \u0627\u0644\u0645\u0633\u062a\u0648\u0649 \u0627\u0644\u0631\u0623\u0633\u064a (\u062d\u064a\u0648\u062f Bragg DCM)</p><p style="color:var(--gn)">\u0627\u0646\u0642\u0631 \u0639\u0644\u0649 \u0623\u064a \u0645\u0643\u0648\u0646 \u0644\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0648\u0627\u0644\u062a\u062d\u0643\u0645.</p>',
    tut_b3_content: '<p>\u0627\u0636\u0628\u0637 \u0627\u0644\u0637\u0627\u0642\u0629 \u0641\u064a \u062a\u0628\u0648\u064a\u0628 <b>IVU</b>.</p><p style="color:var(--am)">\u0627\u0633\u062d\u0628 \u0627\u0644\u0645\u0624\u0634\u0631 \u0625\u0644\u0649 10 keV.</p><p>\u0627\u0644\u0646\u0638\u0627\u0645 \u0633\u064a\u0642\u0648\u0645 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b \u0628:</p><p>* \u0627\u062e\u062a\u064a\u0627\u0631 \u0627\u0644\u062a\u0648\u0627\u0641\u0642\u064a \u0627\u0644\u0623\u0645\u062b\u0644</p><p>* \u0636\u0628\u0637 \u0641\u062c\u0648\u0629 IVU</p><p>* \u062d\u0633\u0627\u0628 \u0632\u0627\u0648\u064a\u0629 DCM Bragg</p>',
    tut_b4_content: '<p>\u0627\u0636\u0628\u0637 \u0627\u0644\u0628\u0635\u0631\u064a\u0627\u062a \u0641\u064a \u062a\u0628\u0648\u064a\u0628 <b>\u0627\u0644\u0628\u0635\u0631\u064a\u0627\u062a</b>:</p><p>* <span style="color:var(--ac)">WB Slit</span> -- \u062d\u062c\u0645 \u0634\u0642 \u0627\u0644\u0634\u0639\u0627\u0639 \u0627\u0644\u0623\u0628\u064a\u0636</p><p>* <span style="color:var(--ac)">M1/M2</span> -- \u0632\u0648\u0627\u064a\u0627 \u0645\u0631\u0627\u064a\u0627 \u0627\u0644\u0627\u0646\u062d\u0631\u0627\u0641</p><p>* <span style="color:var(--ac)">SSA</span> -- \u0634\u0642 \u062b\u0627\u0646\u0648\u064a (\u0645\u0635\u062f\u0631 \u0627\u0641\u062a\u0631\u0627\u0636\u064a KB)</p><p>* <span style="color:var(--ac)">KB</span> -- \u0646\u062a\u064a\u062c\u0629 \u0627\u0644\u062a\u0631\u0643\u064a\u0632 \u0627\u0644\u0646\u0647\u0627\u0626\u064a</p><p style="color:var(--am)">\u0627\u0646\u0642\u0631 \u0639\u0644\u0649 \u062a\u0628\u0648\u064a\u0628 \u0627\u0644\u0628\u0635\u0631\u064a\u0627\u062a.</p>',
    tut_b5_content: '<p>\u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0641\u0648\u0631\u064a\u0629 \u0641\u064a \u0634\u0631\u064a\u0637 \u0627\u0644\u062d\u0627\u0644\u0629:</p><p>* <span style="color:var(--ac)">E</span> -- \u0627\u0644\u0637\u0627\u0642\u0629 \u0627\u0644\u062d\u0627\u0644\u064a\u0629</p><p>* <span style="color:var(--gn)">Flux</span> -- \u062a\u062f\u0641\u0642 \u0627\u0644\u0641\u0648\u062a\u0648\u0646\u0627\u062a</p><p>* <span style="color:var(--pk)">Spot</span> -- \u062d\u062c\u0645 \u0627\u0644\u0628\u0642\u0639\u0629 \u0627\u0644\u0628\u0624\u0631\u064a\u0629</p><p>\u0623\u062d\u062c\u0627\u0645 \u0627\u0644\u0634\u0639\u0627\u0639 \u0639\u0646\u062f \u0643\u0644 \u0645\u0643\u0648\u0646 \u0645\u0639\u0631\u0648\u0636\u0629 \u0623\u064a\u0636\u0627\u064b.</p>',
    tut_b6_content: '<p>\u062a\u062c\u0627\u0631\u0628 \u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629 \u0641\u064a \u062a\u0628\u0648\u064a\u0628 <b>\u0627\u0644\u0642\u064a\u0627\u0633</b>:</p><p>* XANES -- \u0637\u064a\u0641 \u0627\u0644\u0627\u0645\u062a\u0635\u0627\u0635</p><p>* XRD -- \u0646\u0645\u0637 \u0627\u0644\u062d\u064a\u0648\u062f</p><p>* XRF -- \u0637\u064a\u0641 \u0627\u0644\u0641\u0644\u0648\u0631\u0629</p><p>* \u062e\u0631\u064a\u0637\u0629 2D -- \u0627\u0644\u0645\u0633\u062d \u0627\u0644\u0645\u0643\u0627\u0646\u064a</p><p style="color:var(--gn)">\u0627\u0636\u063a\u0637 \u0628\u062f\u0621 \u0644\u0644\u0645\u0633\u062d.</p>',
    tut_b7_content: '<p>\u062a\u062c\u0627\u0631\u0628 Bluesky \u0641\u064a \u062a\u0628\u0648\u064a\u0628 <b>BS</b>:</p><p>* \u0627\u062e\u062a\u064a\u0627\u0631 \u062e\u0637\u0629 \u0648\u0636\u0628\u0637 \u0627\u0644\u0645\u0639\u0644\u0645\u0627\u062a</p><p>* \u0625\u0636\u0627\u0641\u0629 \u0644\u0644\u0637\u0627\u0628\u0648\u0631 \u0644\u0644\u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0645\u062a\u0633\u0644\u0633\u0644</p><p>* \u0645\u0631\u0627\u0642\u0628\u0629 \u0641\u0648\u0631\u064a\u0629</p><p style="color:var(--pr)">\u0623\u0632\u0631\u0627\u0631 \u0627\u0644\u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0633\u0631\u064a\u0639 \u0645\u062a\u0627\u062d\u0629.</p>',
    tut_b8_content: '<p>\u0628\u062f\u0644 \u0627\u0644\u0648\u0636\u0639 \u0628\u0623\u0632\u0631\u0627\u0631 \u0627\u0644\u0623\u0639\u0644\u0649:</p><p>* <span style="color:var(--gn)">\u0627\u0641\u062a\u0631\u0627\u0636\u064a</span> -- \u0645\u062d\u0627\u0643\u0627\u0629 \u0641\u0642\u0637</p><p>* <span style="color:var(--am)">\u062d\u0642\u064a\u0642\u064a</span> -- \u0627\u062a\u0635\u0627\u0644 EPICS IOC \u062d\u0642\u064a\u0642\u064a</p><p>* <span style="color:var(--ac)">\u0645\u0632\u062f\u0648\u062c</span> -- \u0648\u0636\u0639 \u0645\u0642\u0627\u0631\u0646\u0629 V/R</p><p>\u062a\u062f\u0631\u0628 \u0641\u064a \u0627\u0644\u0648\u0636\u0639 \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a \u0623\u0648\u0644\u0627\u064b.</p>',
    tut_b9_content: '<p style="color:var(--gn)">\u062a\u0647\u0627\u0646\u064a\u0646\u0627! \u0644\u0642\u062f \u062a\u0639\u0644\u0645\u062a \u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0627\u0644\u0623\u0633\u0627\u0633\u064a.</p><p>\u0627\u0644\u062e\u0637\u0648\u0627\u062a \u0627\u0644\u062a\u0627\u0644\u064a\u0629:</p><p>* <b>\u062a\u062c\u0627\u0631\u0628 \u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629</b> -- \u0645\u062d\u0627\u0643\u0627\u0629 \u062a\u062c\u0627\u0631\u0628 \u062d\u0642\u064a\u0642\u064a\u0629</p><p>* <b>\u062a\u0643\u0627\u0645\u0644 EPICS</b> -- \u0631\u0628\u0637 \u0627\u0644\u0623\u062c\u0647\u0632\u0629 \u0627\u0644\u062d\u0642\u064a\u0642\u064a\u0629</p><p>* <b>\u0645\u0642\u0627\u0631\u0646\u0629 V/R</b> -- \u0645\u0642\u0627\u0631\u0646\u0629 \u0627\u0644\u0645\u062d\u0627\u0643\u0627\u0629 \u0648\u0627\u0644\u0648\u0627\u0642\u0639</p>',
    tut_exp_name: '\u062a\u062f\u0631\u064a\u0628 \u0627\u0644\u062a\u062c\u0627\u0631\u0628 \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629', tut_exp_desc: '\u062a\u062c\u0627\u0631\u0628 \u0627\u0641\u062a\u0631\u0627\u0636\u064a\u0629 \u0644\u0643\u0644 \u062a\u0642\u0646\u064a\u0629 \u0642\u064a\u0627\u0633',
    tut_e1_title: 'Cu K-edge XANES', tut_e2_title: '\u062a\u0634\u063a\u064a\u0644 \u0645\u0633\u062d XANES',
    tut_e3_title: '\u062a\u062c\u0631\u0628\u0629 \u062a\u0635\u0648\u064a\u0631 XRF', tut_e4_title: '\u062a\u062c\u0631\u0628\u0629 XRD \u0627\u0644\u0645\u0633\u062d\u0648\u0642',
    tut_e1_content: '<p>\u0633\u062a\u062c\u0631\u064a \u0642\u064a\u0627\u0633 <b>Cu K-edge XANES</b>.</p><p style="color:var(--am)">\u0627\u0636\u063a\u0637 "\u0625\u0639\u062f\u0627\u062f \u062a\u0644\u0642\u0627\u0626\u064a" \u0644\u0644\u062a\u0643\u0648\u064a\u0646 \u0627\u0644\u062a\u0644\u0642\u0627\u0626\u064a.</p>',
    tut_e2_content: '<p>\u0627\u0644\u0637\u0627\u0642\u0629 \u0645\u0636\u0628\u0648\u0637\u0629 \u0639\u0644\u0649 Cu K-edge (8.979 keV).</p><p style="color:var(--am)">\u0641\u064a \u062a\u0628\u0648\u064a\u0628 BS \u0627\u0636\u063a\u0637 XANES.</p><p>\u0628\u0639\u062f \u0627\u0644\u0645\u0633\u062d \u0633\u064a\u0638\u0647\u0631 \u0637\u064a\u0641 µ(E) \u0641\u064a \u0627\u0644\u0623\u0633\u0641\u0644.</p>',
    tut_e3_content: '<p>\u0627\u0644\u0622\u0646 <b>\u062a\u0635\u0648\u064a\u0631 XRF</b>.</p><p>\u0643\u0627\u0634\u0641 SDD \u064a\u062c\u0645\u0639 \u0623\u0634\u0639\u0629 \u0627\u0644\u0641\u0644\u0648\u0631\u0629 \u0639\u0646\u062f 90\u00b0.</p><p style="color:var(--am)">\u0628\u0639\u062f \u0627\u0644\u0625\u0639\u062f\u0627\u062f \u0627\u0644\u062a\u0644\u0642\u0627\u0626\u064a \u0633\u064a\u0646\u062a\u062c \u0627\u0644\u0645\u0633\u062d \u062e\u0631\u064a\u0637\u0629 \u062a\u0648\u0632\u064a\u0639 \u0627\u0644\u0639\u0646\u0627\u0635\u0631.</p>',
    tut_e4_content: '<p>\u0642\u064a\u0627\u0633 <b>XRD \u0627\u0644\u0645\u0633\u062d\u0648\u0642</b>.</p><p>\u0643\u0627\u0634\u0641 Eiger 2X \u0633\u064a\u062c\u0645\u0639 \u0623\u0646\u0645\u0627\u0637 \u062d\u0644\u0642\u0627\u062a Debye-Scherrer.</p>',
    tut_prev: '\u0627\u0644\u0633\u0627\u0628\u0642', tut_next: '\u0627\u0644\u062a\u0627\u0644\u064a', tut_done: '\u062a\u0645'
  }
};

/**
 * Translate a key to the current UI language.
 * Falls back to English, then returns the key itself.
 */
function _t(key) {
  var lang = I18N_STRINGS[UI_LANG];
  if (lang && lang[key] !== undefined) return lang[key];
  var en = I18N_STRINGS['en'];
  if (en && en[key] !== undefined) return en[key];
  return key;
}

/**
 * Translate with format placeholders: _tf('key', arg0, arg1, ...)
 * Template: "Step {0}/{1}: {2}" + args(1, 3, 'name') => "Step 1/3: name"
 */
function _tf(key) {
  var s = _t(key);
  for (var i = 1; i < arguments.length; i++) {
    s = s.replace('{' + (i - 1) + '}', arguments[i]);
  }
  return s;
}

/**
 * Set UI language and refresh all translatable elements.
 */
function setUILanguage(id) {
  if (!I18N_STRINGS[id]) return;
  UI_LANG = id;
  try { localStorage.setItem('bl10_lang', id); } catch(e) {}
  refreshUILanguage();
  _updateLangBtn();
  if (typeof renderLangMenu === 'function') renderLangMenu();
  if (typeof renderModeMenu === 'function') renderModeMenu();
  if (typeof log === 'function') log('info', 'Language: ' + id);
}

/**
 * Refresh all tab labels and translatable UI elements.
 */
function refreshUILanguage() {
  // 1. Refresh tab labels
  var TAB_IDS = ['undulator','dcm','optics','motors','mask','measure',
                 'align','compare','epics','bluesky','guide','chat','expt'];
  var tabs = document.querySelectorAll('.tab');
  var reverseMap = {};
  TAB_IDS.forEach(function(tid) {
    Object.keys(I18N_STRINGS).forEach(function(langId) {
      var s = I18N_STRINGS[langId];
      if (s && s['tab_' + tid]) reverseMap[s['tab_' + tid]] = tid;
    });
  });
  tabs.forEach(function(t) {
    var txt = t.textContent.trim();
    var tid = reverseMap[txt];
    if (tid) {
      t.textContent = _t('tab_' + tid);
    }
  });

  // 2. Auto-update all elements with data-i18n attribute
  var i18nEls = document.querySelectorAll('[data-i18n]');
  for (var i = 0; i < i18nEls.length; i++) {
    var el = i18nEls[i];
    var key = el.getAttribute('data-i18n');
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      el.placeholder = _t(key);
    } else {
      el.textContent = _t(key);
    }
  }
  // Also handle data-i18n-html (for innerHTML content like tutorials)
  var htmlEls = document.querySelectorAll('[data-i18n-html]');
  for (var j = 0; j < htmlEls.length; j++) {
    htmlEls[j].innerHTML = _t(htmlEls[j].getAttribute('data-i18n-html'));
  }
  // Also handle data-i18n-title for tooltips
  var titleEls = document.querySelectorAll('[data-i18n-title]');
  for (var k = 0; k < titleEls.length; k++) {
    titleEls[k].title = _t(titleEls[k].getAttribute('data-i18n-title'));
  }

  // 3. Re-render dynamic panels if their renderers exist
  if (typeof renderExptTab === 'function') {
    try { renderExptTab(); } catch(e) {}
  }
  if (typeof renderBlueskyTab === 'function') {
    try { renderBlueskyTab(); } catch(e) {}
  }
  // 4. Tutorial: if active, refresh current step
  if (typeof TUTORIAL !== 'undefined' && TUTORIAL && TUTORIAL.active &&
      typeof showTutorialStep === 'function') {
    try { showTutorialStep(TUTORIAL.currentStep); } catch(e) {}
  }
}

// Restore saved language preference
(function() {
  try {
    var saved = localStorage.getItem('bl10_lang');
    if (saved && I18N_STRINGS[saved]) {
      UI_LANG = saved;
    } else {
      var nav = (navigator.language || '').slice(0, 2).toLowerCase();
      if (I18N_STRINGS[nav]) UI_LANG = nav;
    }
  } catch(e) {}
  // Refresh tab labels and lang button once DOM is ready
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function() { refreshUILanguage(); _updateLangBtn(); });
    } else {
      refreshUILanguage();
      _updateLangBtn();
    }
  }
})();

/**
 * Render language dropdown menu (separate from View menu).
 */
function renderLangMenu() {
  var el = document.getElementById('langMenu');
  if (!el) return;
  var LANGS = [
    {id:'en', label:'English',  desc:'Default'},
    {id:'ko', label:'\ud55c\uad6d\uc5b4',    desc:'Korean'},
    {id:'ja', label:'\u65e5\u672c\u8a9e',    desc:'Japanese'},
    {id:'zh', label:'\u4e2d\u6587',      desc:'Chinese'},
    {id:'de', label:'Deutsch',  desc:'German'},
    {id:'fr', label:'Fran\u00e7ais', desc:'French'},
    {id:'es', label:'Espa\u00f1ol',  desc:'Spanish'},
    {id:'th', label:'\u0e44\u0e17\u0e22',      desc:'Thai'},
    {id:'hi', label:'\u0939\u093f\u0928\u094d\u0926\u0940',    desc:'Hindi'},
    {id:'ar', label:'\u0627\u0644\u0639\u0631\u0628\u064a\u0629',   desc:'Arabic'}
  ];
  var h = '';
  LANGS.forEach(function(l) {
    var act = (UI_LANG === l.id) ? ' active' : '';
    h += '<div class="mode-opt' + act + '" onclick="setUILanguage(\'' + l.id + '\')">' +
      '<span class="dot"></span>' +
      '<div><div style="font-weight:500">' + l.label + '</div>' +
      '<div style="font-size:8px;color:var(--t3)">' + l.desc + '</div></div></div>';
  });
  el.innerHTML = h;
}

/**
 * Toggle language dropdown visibility.
 */
function toggleLangMenu() {
  var el = document.getElementById('langMenu');
  if (!el) return;
  var isOpen = el.classList.contains('open');
  el.classList.toggle('open');
  if (!isOpen) {
    renderLangMenu();
    setTimeout(function() {
      function closeLang(e) {
        if (!el.contains(e.target) && e.target.id !== 'langSelectorBtn') {
          el.classList.remove('open');
          document.removeEventListener('click', closeLang);
        }
      }
      document.addEventListener('click', closeLang);
    }, 10);
  }
}

/**
 * Update the Lang button label to show current language code.
 */
function _updateLangBtn() {
  var btn = document.getElementById('langSelectorBtn');
  if (btn) {
    var codes = {en:'EN', ko:'KO', ja:'JA', zh:'ZH', de:'DE', fr:'FR', es:'ES', th:'TH', hi:'HI', ar:'AR'};
    btn.textContent = codes[UI_LANG] || 'EN';
  }
}

window._t = _t;
window.setUILanguage = setUILanguage;
window.refreshUILanguage = refreshUILanguage;
window.renderLangMenu = renderLangMenu;
window.toggleLangMenu = toggleLangMenu;

// ESM bridge: expose module-scoped vars to globalThis
if(typeof I18N_STRINGS!=="undefined")globalThis.I18N_STRINGS=I18N_STRINGS;
if(typeof UI_LANG!=="undefined")globalThis.UI_LANG=UI_LANG;
if(typeof _t!=="undefined")globalThis._t=_t;
if(typeof _tf!=="undefined")globalThis._tf=_tf;
if(typeof _updateLangBtn!=="undefined")globalThis._updateLangBtn=_updateLangBtn;
if(typeof refreshUILanguage!=="undefined")globalThis.refreshUILanguage=refreshUILanguage;
if(typeof renderLangMenu!=="undefined")globalThis.renderLangMenu=renderLangMenu;
if(typeof setUILanguage!=="undefined")globalThis.setUILanguage=setUILanguage;
if(typeof toggleLangMenu!=="undefined")globalThis.toggleLangMenu=toggleLangMenu;
