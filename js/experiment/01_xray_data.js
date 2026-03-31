'use strict';
// ===== experiment/01_xray_data.js — X-ray Data: Elements, Crystals, EXAFS paths =====
// @module experiment/01_xray_data
// @exports COMPOUND_DENSITIES, CRYSTALS, FEFF_PATHS, SDD_SPEC, WK_COEFFS, XRAY_ELEMENTS, XRD_SAMPLE_PRESETS, XRF_K_BRANCH, XRF_LINES, XRF_MU_PHOTO, XRF_SAMPLE_PRESETS, XRF_YIELDS, _elementMuRho, _interpolateMuPhoto, _poissonSample, ...

// ── Chemical Formula Parser ──
// parseFormula("Cu2O") => {Cu:2, O:1}
// parseFormula("SrTiO3") => {Sr:1, Ti:1, O:3}
// parseFormula("La0.7Sr0.3MnO3") => {La:0.7, Sr:0.3, Mn:1, O:3}
window.parseFormula = function(formula) {
  var result = {};
  var re = /([A-Z][a-z]?)(\d*\.?\d*)/g;
  var m;
  while ((m = re.exec(formula)) !== null) {
    var el = m[1];
    var n = m[2] === '' ? 1 : parseFloat(m[2]);
    if (isNaN(n)) n = 1;
    result[el] = (result[el] || 0) + n;
  }
  return result;
};

// ── Element Data: Z, mass, edges (eV), emission lines (eV) ──
var XRAY_ELEMENTS = {
  B:  {Z:5,  M:10.81,  K:188},
  C:  {Z:6,  M:12.011, K:284},
  N:  {Z:7,  M:14.007, K:410},
  O:  {Z:8,  M:15.999, K:543},
  Na: {Z:11, M:22.990, K:1071, lines:{Ka:1041}},
  Al: {Z:13, M:26.982, K:1560, lines:{Ka:1487}},
  Si: {Z:14, M:28.086, K:1839, lines:{Ka:1740}},
  P:  {Z:15, M:30.974, K:2145, lines:{Ka:2014}},
  S:  {Z:16, M:32.065, K:2472, lines:{Ka:2308}},
  Cl: {Z:17, M:35.453, K:2822, lines:{Ka:2622}},
  Ca: {Z:20, M:40.078, K:4038, lines:{Ka:3692, Kb:4013}},
  Ti: {Z:22, M:47.867, K:4966, L3:454, lines:{Ka:4510, Kb:4932}},
  V:  {Z:23, M:50.942, K:5465, L3:512, lines:{Ka:4952, Kb:5427}},
  Cr: {Z:24, M:51.996, K:5989, L3:574, lines:{Ka:5414, Kb:5946}},
  Mn: {Z:25, M:54.938, K:6539, L3:639, lines:{Ka:5899, Kb:6490}},
  Fe: {Z:26, M:55.845, K:7112, L3:706, lines:{Ka:6404, Kb:7058}},
  Co: {Z:27, M:58.933, K:7709, L3:778, lines:{Ka:6930, Kb:7649}},
  Ni: {Z:28, M:58.693, K:8333, L3:855, lines:{Ka:7478, Kb:8265}},
  Cu: {Z:29, M:63.546, K:8979, L3:932, lines:{Ka:8048, Kb:8905}},
  Zn: {Z:30, M:65.38,  K:9659, L3:1020, lines:{Ka:8639, Kb:9572}},
  Ga: {Z:31, M:69.723, K:10367, L3:1116, lines:{Ka:9251, Kb:10267}},
  Ge: {Z:32, M:72.630, K:11103, L3:1217, lines:{Ka:9886, Kb:10982}},
  As: {Z:33, M:74.922, K:11867, L3:1324, lines:{Ka:10543, Kb:11726}},
  Se: {Z:34, M:78.971, K:12658, L3:1434, lines:{Ka:11224, Kb:12497}},
  Sr: {Z:38, M:87.62,  K:16105, L3:1940, lines:{Ka:14165, Kb:15835}},
  Mo: {Z:42, M:95.95,  K:20000, L3:2520, lines:{Ka:17480, Kb:19606}},
  Ag: {Z:47, M:107.87, K:25514, L3:3351, lines:{Ka:22163, Kb:24941, La:2983, Lb:3150}},
  Cd: {Z:48, M:112.41, K:26711, L3:3538, lines:{Ka:23173, Kb:26093, La:3133, Lb:3315}},
  Sn: {Z:50, M:118.71, K:29200, L3:3929, lines:{Ka:25271, Kb:28485, La:3444, Lb:3663}},
  Ba: {Z:56, M:137.33, K:37441, L3:5247, lines:{La:4467, Lb:4828}},
  La: {Z:57, M:138.91, K:38925, L3:5483, lines:{La:4651, Lb:5042}},
  Ce: {Z:58, M:140.12, K:40443, L3:5723, lines:{La:4839, Lb:5262}},
  W:  {Z:74, M:183.84, K:69525, L3:10207, lines:{La:8398, Lb:9672}},
  Pt: {Z:78, M:195.08, K:78395, L3:11564, lines:{La:9442, Lb:11071}},
  Au: {Z:79, M:196.97, K:80725, L3:11919, lines:{La:9713, Lb:11443}},
  Pb: {Z:82, M:207.20, K:88005, L3:13035, lines:{La:10551, Lb:12614}}
};

// ── XRF Detailed Fluorescence Lines (eV) ──
// Ref: Elam, Ravel, Sieber, Radiat. Phys. Chem. 63, 121 (2002)
// Ka1=K-L3, Ka2=K-L2, Kb1=K-M3, La1=L3-M5, Lb1=L2-M4
var XRF_LINES = {
  Ti: {Ka1:4512, Ka2:4506, Kb1:4933},
  V:  {Ka1:4953, Ka2:4945, Kb1:5428},
  Cr: {Ka1:5415, Ka2:5405, Kb1:5947},
  Mn: {Ka1:5900, Ka2:5889, Kb1:6492},
  Fe: {Ka1:6405, Ka2:6392, Kb1:7059},
  Co: {Ka1:6931, Ka2:6916, Kb1:7649},
  Ni: {Ka1:7480, Ka2:7463, Kb1:8267},
  Cu: {Ka1:8046, Ka2:8027, Kb1:8904},
  Zn: {Ka1:8637, Ka2:8614, Kb1:9570},
  Ga: {Ka1:9251, Ka2:9224, Kb1:10267},
  Ge: {Ka1:9886, Ka2:9855, Kb1:10982},
  As: {Ka1:10543, Ka2:10508, Kb1:11726},
  Se: {Ka1:11224, Ka2:11184, Kb1:12497},
  Sr: {Ka1:14165, Ka2:14098, Kb1:15835},
  Mo: {Ka1:17480, Ka2:17375, Kb1:19606},
  Ag: {Ka1:22163, Ka2:21990, Kb1:24941, La1:2983, Lb1:3150},
  Ba: {La1:4467, Lb1:4828},
  La: {La1:4651, Lb1:5042},
  Ce: {La1:4839, Lb1:5262},
  W:  {La1:8398, Lb1:9672},
  Pt: {La1:9442, Lb1:11071},
  Au: {La1:9713, Lb1:11443},
  Pb: {La1:10551, Lb1:12614}
};

// ── K-shell Fluorescence Yields ──
// Ref: Krause, J. Phys. Chem. Ref. Data 8, 307 (1979); Elam et al. (2002)
// omega_K = probability of X-ray emission from K vacancy
// omega_L3 = probability of X-ray emission from L3 vacancy
var XRF_YIELDS = {
  Ti: {omega_K:0.219},           V:  {omega_K:0.253},
  Cr: {omega_K:0.287},           Mn: {omega_K:0.319},
  Fe: {omega_K:0.351},           Co: {omega_K:0.382},
  Ni: {omega_K:0.412},           Cu: {omega_K:0.441},
  Zn: {omega_K:0.469},           Ga: {omega_K:0.497},
  Ge: {omega_K:0.523},           As: {omega_K:0.549},
  Se: {omega_K:0.574},           Sr: {omega_K:0.665},
  Mo: {omega_K:0.742},           Ag: {omega_K:0.822},
  Ba: {omega_K:0.920, omega_L3:0.097},
  La: {omega_K:0.928, omega_L3:0.104},
  Ce: {omega_K:0.935, omega_L3:0.111},
  W:  {omega_K:0.983, omega_L3:0.255},
  Pt: {omega_K:0.982, omega_L3:0.306},
  Au: {omega_K:0.981, omega_L3:0.320},
  Pb: {omega_K:0.978, omega_L3:0.360}
};

// ── K-line branching ratios (fraction of K-shell X-ray yield) ──
// Ka1 ~ 58%, Ka2 ~ 29%, Kb1 ~ 8%, Kb3 ~ 4% for 3d metals
var XRF_K_BRANCH = {
  Ka1: 0.578, Ka2: 0.294, Kb1: 0.084, Kb3: 0.044
};

// ── Photoelectric mass attenuation coefficients (cm^2/g) ──
// Ref: NIST XCOM (Berger & Hubbell); selected energies in eV
// {energy_eV: mu_photo}
var XRF_MU_PHOTO = {
  // Light elements (NIST xraydb, Elam 2002) — needed for SiO2, Al2O3, NaCl, CaF2, H2O etc.
  O:  {rho:1.429,  mu:{2000:694, 3000:216, 5000:47, 8000:11, 10000:6, 15000:2}},
  Na: {rho:0.968,  mu:{2000:1519, 3000:506, 5000:118, 8000:30, 10000:15, 15000:4}},
  Al: {rho:2.700,  mu:{2000:2261, 3000:787, 5000:192, 8000:50, 10000:26, 15000:8}},
  Si: {rho:2.330,  mu:{2000:2775, 3000:977, 5000:244, 8000:64, 10000:33, 15000:10}},
  P:  {rho:1.823,  mu:{3000:1116, 5000:285, 8000:76, 10000:40, 15000:12}},
  S:  {rho:2.070,  mu:{3000:1337, 5000:347, 8000:94, 10000:49, 15000:15}},
  Cl: {rho:3.214,  mu:{3000:1471, 5000:389, 8000:107, 10000:56, 15000:17}},
  Ca: {rho:1.550,  mu:{3000:265, 5000:601, 8000:171, 10000:92, 15000:29}},
  // Transition metals — below + above K-edge data for proper edge-jump
  Ti: {rho:4.506,  mu:{3000:330, 4000:150, 4900:85, 5000:599, 8000:201, 10000:110, 12400:60, 15000:35}},
  V:  {rho:6.110,  mu:{3000:372, 4000:169, 5400:73, 5500:546, 8000:220, 10000:121, 12400:67, 15000:38}},
  Cr: {rho:7.190,  mu:{3000:431, 4000:196, 5900:67, 6000:525, 8000:250, 10000:138, 12400:77, 15000:44}},
  Mn: {rho:7.470,  mu:{3000:482, 4000:220, 6400:60, 6600:480, 8000:272, 10000:150, 12400:84, 15000:48}},
  Fe: {rho:7.874,  mu:{5000:129, 6000:79, 7000:54, 7200:440, 8000:304, 10000:169, 12400:95, 15000:54}},
  Co: {rho:8.900,  mu:{6000:67, 7000:47, 7600:47, 7800:400, 8000:323, 10000:183, 12400:103, 15000:58}},
  Ni: {rho:8.908,  mu:{6000:92, 7000:61, 8200:44, 8400:360, 10000:207, 12400:118, 15000:67}},
  Cu: {rho:8.960,  mu:{7000:74, 8000:51, 8900:38, 9000:310, 10000:214, 12400:123, 15000:70}},
  Zn: {rho:7.134,  mu:{7000:64, 8000:45, 9500:35, 9700:270, 10000:231, 12400:134, 15000:76}},
  Sr: {rho:2.640,  mu:{8000:112, 10000:61, 12400:33, 16200:210, 20000:115}},
  Mo: {rho:10.280, mu:{8000:154, 10000:83, 12400:46, 20100:180, 25000:95}},
  Au: {rho:19.300, mu:{8000:201, 10000:113, 12000:174, 12400:164, 15000:98}},
  Pt: {rho:21.450, mu:{8000:193, 10000:108, 11600:158, 12400:158, 15000:94}},
  W:  {rho:19.250, mu:{8000:165, 10000:92, 10300:218, 12400:220, 15000:131}},
  Pb: {rho:11.340, mu:{8000:223, 10000:126, 12400:72, 13100:190, 15000:125}}
};

// ── SDD Detector Specification (Rayspec-type 3-channel SDD) ──
// Ref: Rayspec synchrotron SDD, Hitachi Vortex-ME3 equivalent
var SDD_SPEC = {
  name: 'Rayspec 3ch SDD',
  nChannels: 3,
  activeArea_mm2: 50,            // per channel
  totalArea_mm2: 150,
  fwhm_MnKa_eV: 130,            // at 1us peaking time
  beWindow_um: 12.5,
  siThickness_um: 450,
  maxRate_kcps: 1500,            // per channel (input)
  distance_mm: 25,               // typical sample-to-detector
  takeoffAngle_deg: 15,

  // Detection efficiency at key energies (after Be window + dead layer)
  // eff = T_Be * (1 - exp(-mu_Si * rho_Si * t_Si))
  efficiency: {
    1000:0.24, 2000:0.79, 3000:0.93, 4000:0.97, 5000:0.98,
    6000:0.99, 7000:0.99, 8000:0.99, 9000:0.99, 10000:0.97,
    12000:0.87, 15000:0.66, 20000:0.37, 25000:0.22, 30000:0.14
  }
};

// Solid angle per channel: A / (4*pi*d^2)
SDD_SPEC.solidAngle_sr = SDD_SPEC.activeArea_mm2 / (4 * Math.PI * SDD_SPEC.distance_mm * SDD_SPEC.distance_mm);
SDD_SPEC.totalSolidAngle_sr = SDD_SPEC.solidAngle_sr * SDD_SPEC.nChannels;

// SDD energy resolution model: FWHM(E) = sqrt(noise^2 + 5.545 * F * eps * E)
// F=0.115 (Fano factor Si), eps=3.65 eV/e-h pair
window.sddFWHM = function(E_eV) {
  var noise = 80;        // electronic noise (eV)
  var F = 0.115;
  var eps = 3.65;
  return Math.sqrt(noise * noise + 5.545 * F * eps * E_eV);
};

// SDD efficiency interpolation
window.sddEfficiency = function(E_eV) {
  var eff = SDD_SPEC.efficiency;
  var keys = Object.keys(eff);
  var eArr = [];
  for (var i = 0; i < keys.length; i++) eArr.push(parseInt(keys[i]));
  eArr.sort(function(a, b) { return a - b; });
  if (E_eV <= eArr[0]) return eff[eArr[0]];
  if (E_eV >= eArr[eArr.length - 1]) return eff[eArr[eArr.length - 1]];
  for (var j = 0; j < eArr.length - 1; j++) {
    if (E_eV >= eArr[j] && E_eV <= eArr[j + 1]) {
      var f = (E_eV - eArr[j]) / (eArr[j + 1] - eArr[j]);
      return eff[eArr[j]] * (1 - f) + eff[eArr[j + 1]] * f;
    }
  }
  return 0.5;
};

// ── Nanoprobe Sample Presets ──
// Realistic samples for synchrotron nanoprobe XRF/XRD experiments
var XRF_SAMPLE_PRESETS = {
  semiconductor_ic: {
    name: 'Semiconductor IC (cross-section)',
    formula: 'SiO2',
    matrixDensity: 2.2,
    thickness_um: 3.0,
    sampleType: 'solid',
    elements: {
      Cu: {wt_pct:15.0, role:'Interconnect (M1-M9)'},
      W:  {wt_pct:3.0,  role:'Contact/via plugs'},
      Co: {wt_pct:1.0,  role:'Liner, cap layer'},
      Ti: {wt_pct:0.5,  role:'Adhesion (TiN)'},
      Si: {wt_pct:30.0, role:'Substrate/ILD'}
    }
  },
  battery_nmc622: {
    name: 'NMC622 Battery Cathode',
    formula: 'LiNi0.6Mn0.2Co0.2O2',
    matrixDensity: 4.7,
    thickness_um: 80.0,
    sampleType: 'solid',
    elements: {
      Ni: {wt_pct:36.3, role:'Cathode active (Ni0.6)'},
      Mn: {wt_pct:11.3, role:'Structural stability (Mn0.2)'},
      Co: {wt_pct:12.2, role:'Rate capability (Co0.2)'},
      Fe: {wt_pct:0.01, role:'Contaminant (trace)'},
      Cu: {wt_pct:0.005, role:'Contaminant (trace)'}
    }
  },
  geological_section: {
    name: 'Geological Thin Section',
    formula: 'SiO2',
    matrixDensity: 2.65,
    thickness_um: 30.0,
    sampleType: 'solid',
    elements: {
      Fe: {wt_pct:8.0,   role:'Fe-silicates, oxides'},
      Ti: {wt_pct:1.2,   role:'Rutile, ilmenite'},
      Mn: {wt_pct:0.15,  role:'Garnet, pyroxene'},
      Cr: {wt_pct:0.05,  role:'Chromite'},
      Ni: {wt_pct:0.02,  role:'Olivine, sulfides'},
      Cu: {wt_pct:0.005, role:'Cu-sulfides'},
      Zn: {wt_pct:0.01,  role:'Sphalerite'},
      Sr: {wt_pct:0.05,  role:'Plagioclase'},
      As: {wt_pct:0.001, role:'Arsenopyrite'}
    }
  },
  biological_cell: {
    name: 'Biological Cell (freeze-dried)',
    formula: 'C5H8NO2',
    matrixDensity: 1.35,
    thickness_um: 3.0,
    sampleType: 'solid',
    elements: {
      Fe: {wt_pct:0.020,   role:'Ferritin, mitochondria'},
      Zn: {wt_pct:0.015,   role:'Metalloproteins, vesicles'},
      Cu: {wt_pct:0.002,   role:'SOD, cytochrome c oxidase'},
      Mn: {wt_pct:0.0003,  role:'MnSOD, arginase'},
      Se: {wt_pct:0.00005, role:'Selenoproteins'}
    }
  },
  catalyst_nanoparticle: {
    name: 'Catalyst NPs on Support',
    formula: 'Al2O3',
    matrixDensity: 1.5,
    thickness_um: 0.5,
    sampleType: 'particle',
    elements: {
      Pt: {wt_pct:5.0, role:'Active catalyst (core/shell)'},
      Au: {wt_pct:3.0, role:'Bimetallic partner'},
      Fe: {wt_pct:0.5, role:'Promoter'},
      Ce: {wt_pct:2.0, role:'CeO2 support'}
    }
  },
  environmental_particle: {
    name: 'Environmental Particle (fly ash)',
    formula: 'SiO2',
    matrixDensity: 2.3,
    thickness_um: 10.0,
    sampleType: 'particle',
    elements: {
      Fe: {wt_pct:10.0,  role:'Iron oxides'},
      Ti: {wt_pct:1.5,   role:'TiO2, ilmenite'},
      Mn: {wt_pct:0.3,   role:'Mn oxides'},
      Cr: {wt_pct:0.05,  role:'Cr(III)/Cr(VI)'},
      Cu: {wt_pct:0.02,  role:'Smelter emissions'},
      Zn: {wt_pct:0.1,   role:'ZnO'},
      As: {wt_pct:0.01,  role:'Coal combustion ash'},
      Pb: {wt_pct:0.05,  role:'Lead legacy'},
      Sr: {wt_pct:0.05,  role:'Provenance tracer'}
    }
  },
  siemens_star: {
    name: 'Siemens Star (Au, resolution test)',
    formula: 'Au',
    matrixDensity: 19.3,
    thickness_um: 0.5,
    sampleType: 'thin_film',
    elements: {
      Au: {wt_pct:90.0,  role:'Test pattern spokes'},
      Cr: {wt_pct:5.0,   role:'Adhesion layer'},
      Si: {wt_pct:5.0,   role:'Si3N4 membrane'}
    }
  },
  calibration_grid: {
    name: 'Multi-Element Calibration Grid',
    formula: 'Si',
    matrixDensity: 2.33,
    thickness_um: 0.05,
    sampleType: 'thin_film',
    elements: {
      Ca: {wt_pct:6.25, role:'Row 1 Col 1'},
      Ti: {wt_pct:6.25, role:'Row 1 Col 2'},
      Cr: {wt_pct:6.25, role:'Row 1 Col 3'},
      Mn: {wt_pct:6.25, role:'Row 1 Col 4'},
      Fe: {wt_pct:6.25, role:'Row 2 Col 1'},
      Co: {wt_pct:6.25, role:'Row 2 Col 2'},
      Ni: {wt_pct:6.25, role:'Row 2 Col 3'},
      Cu: {wt_pct:6.25, role:'Row 2 Col 4'},
      Zn: {wt_pct:6.25, role:'Row 3 Col 1'},
      As: {wt_pct:6.25, role:'Row 3 Col 2'},
      Se: {wt_pct:6.25, role:'Row 3 Col 3'},
      Sr: {wt_pct:6.25, role:'Row 3 Col 4'},
      Au: {wt_pct:6.25, role:'Row 4 Col 1'},
      Pt: {wt_pct:6.25, role:'Row 4 Col 2'},
      Pb: {wt_pct:6.25, role:'Row 4 Col 3'},
      W:  {wt_pct:6.25, role:'Row 4 Col 4'}
    }
  }
};

// ── XRD 2D Sample Presets ──
// Realistic measurement scenarios: crystal + recommended geometry
// detDist chosen so that primary rings appear on EIGER2 1M
var XRD_SAMPLE_PRESETS = {
  cu_thin_film: {
    name: 'Cu thin film',
    crystal: 'Cu',
    detDist: 0.05,
    detector: 'EIGER2_1M',
    description: 'Copper thin film crystallinity check'
  },
  si_wafer: {
    name: 'Si wafer',
    crystal: 'Si',
    detDist: 0.04,
    detector: 'EIGER2_1M',
    description: 'Silicon single crystal substrate'
  },
  au_nanoparticle: {
    name: 'Au nanoparticle',
    crystal: 'Au',
    detDist: 0.05,
    detector: 'EIGER2_1M',
    description: 'Gold nanoparticle powder diffraction'
  },
  srtio3_substrate: {
    name: 'SrTiO3 substrate',
    crystal: 'SrTiO3',
    detDist: 0.04,
    detector: 'EIGER2_1M',
    description: 'Perovskite substrate (common epitaxy base)'
  },
  fe2o3_catalyst: {
    name: 'Fe2O3 catalyst',
    crystal: 'Fe2O3',
    detDist: 0.06,
    detector: 'EIGER2_1M',
    description: 'Hematite catalyst phase identification'
  },
  lab6_standard: {
    name: 'LaB6 standard (SRM 660)',
    crystal: 'LaB6',
    detDist: 0.05,
    detector: 'EIGER2_1M',
    description: 'NIST line position/shape standard'
  },
  ceo2_standard: {
    name: 'CeO2 standard (SRM 674)',
    crystal: 'CeO2',
    detDist: 0.05,
    detector: 'EIGER2_1M',
    description: 'NIST quantitative analysis standard'
  },
  tio2_photocatalyst: {
    name: 'TiO2 photocatalyst',
    crystal: 'TiO2',
    detDist: 0.06,
    detector: 'EIGER2_1M',
    description: 'Anatase/Rutile phase identification'
  }
};

// ── Waasmaier-Kirfel scattering factor coefficients ──
// f0(s) = c + Sum_i a_i * exp(-b_i * s^2), s = sin(theta)/lambda (in A^-1)
// Ref: Waasmaier & Kirfel, Acta Cryst. A51, 416-431 (1995)
var WK_COEFFS = {
  B:  {a:[2.0545,1.3326,1.0979,0.7068],b:[23.219,1.0210,60.350,0.1403],c:-0.1932},
  C:  {a:[2.3100,1.0200,1.5886,0.8650],b:[20.844,10.208,0.5687,51.651],c:0.2156},
  N:  {a:[12.213,3.1322,2.0125,1.1663],b:[0.0057,9.8933,28.998,0.5826],c:-11.529},
  O:  {a:[3.0485,2.2868,1.5463,0.8670],b:[13.277,5.7011,0.3239,32.909],c:0.2508},
  Na: {a:[4.7626,3.1736,1.2674,1.1128],b:[3.2850,8.8422,0.3136,129.42],c:0.6760},
  Al: {a:[6.4202,1.9002,1.5936,1.9646],b:[3.0387,0.7426,31.547,85.089],c:1.1151},
  Si: {a:[6.2915,3.0353,1.9891,1.5410],b:[2.4386,32.334,0.6785,81.694],c:1.1407},
  Cl: {a:[11.460,7.1963,6.2556,1.6455],b:[0.0104,1.1662,18.519,47.778],c:-9.5574},
  Ti: {a:[9.7595,7.3558,1.6991,1.9021],b:[7.8508,0.5000,35.634,116.11],c:1.2807},
  Mn: {a:[11.282,7.3573,3.0193,2.2441],b:[5.3409,0.3432,17.867,83.754],c:1.0896},
  Fe: {a:[11.769,7.3573,3.5222,2.3045],b:[4.7611,0.3072,15.354,76.881],c:1.0369},
  Ni: {a:[12.838,7.2920,4.4438,2.3800],b:[3.8785,0.2565,12.176,66.342],c:1.0341},
  Cu: {a:[13.338,7.1676,5.6158,1.6735],b:[3.5828,0.2470,11.397,64.812],c:1.1910},
  Zn: {a:[14.074,7.0318,5.1652,2.4100],b:[3.2655,0.2333,10.316,58.710],c:1.3041},
  Sr: {a:[17.566,9.8184,5.4220,2.6694],b:[1.5564,14.099,0.1664,132.38],c:2.5064},
  La: {a:[20.578,19.599,11.373,3.2879],b:[2.9482,0.2444,18.773,133.12],c:2.1461},
  Au: {a:[16.882,18.591,25.558,5.8600],b:[0.4611,8.6216,1.4826,36.396],c:12.066},
  Pt: {a:[27.006,17.764,15.713,5.7837],b:[1.5129,8.8117,0.4025,38.610],c:11.688}
};

// Compute atomic scattering factor f0 at given s = sin(theta)/lambda
window.scatteringFactor = function(el, s) {
  var c = WK_COEFFS[el];
  if (!c) return 0;
  var s2 = s * s;
  var f = c.c;
  for (var i = 0; i < 4; i++) {
    f += c.a[i] * Math.exp(-c.b[i] * s2);
  }
  return f;
};

// ── Crystal Structure Database ──
var CRYSTALS = {
  Cu: {
    name: 'Copper', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 3.6149, Z: 4, Biso: 0.55,
    atoms: [{el:'Cu', x:0, y:0, z:0}],
    extinct: 'F'
  },
  Fe: {
    name: 'Iron (bcc)', system: 'cubic', sg: 'Im-3m', sgNum: 229,
    a: 2.8665, Z: 2, Biso: 0.35,
    atoms: [{el:'Fe', x:0, y:0, z:0}],
    extinct: 'I'
  },
  Ni: {
    name: 'Nickel', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 3.5238, Z: 4, Biso: 0.37,
    atoms: [{el:'Ni', x:0, y:0, z:0}],
    extinct: 'F'
  },
  Si: {
    name: 'Silicon', system: 'cubic', sg: 'Fd-3m', sgNum: 227,
    a: 5.4310, Z: 8, Biso: 0.46,
    atoms: [{el:'Si', x:0, y:0, z:0}, {el:'Si', x:0.25, y:0.25, z:0.25}],
    extinct: 'Fd'
  },
  Au: {
    name: 'Gold', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 4.0782, Z: 4, Biso: 0.64,
    atoms: [{el:'Au', x:0, y:0, z:0}],
    extinct: 'F'
  },
  Pt: {
    name: 'Platinum', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 3.9242, Z: 4, Biso: 0.39,
    atoms: [{el:'Pt', x:0, y:0, z:0}],
    extinct: 'F'
  },
  NaCl: {
    name: 'Sodium Chloride', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 5.6402, Z: 4, Biso: 1.15,
    atoms: [{el:'Na', x:0, y:0, z:0}, {el:'Cl', x:0.5, y:0.5, z:0.5}],
    extinct: 'F'
  },
  Cu2O: {
    name: 'Cuprite', system: 'cubic', sg: 'Pn-3m', sgNum: 224,
    a: 4.2696, Z: 2, Biso: 0.65,
    atoms: [{el:'Cu', x:0.25, y:0.25, z:0.25}, {el:'Cu', x:0.75, y:0.75, z:0.25},
            {el:'Cu', x:0.75, y:0.25, z:0.75}, {el:'Cu', x:0.25, y:0.75, z:0.75},
            {el:'O', x:0, y:0, z:0}, {el:'O', x:0.5, y:0.5, z:0.5}],
    extinct: 'Pn'
  },
  CuO: {
    name: 'Tenorite', system: 'monoclinic', sg: 'C2/c', sgNum: 15,
    a: 4.6837, b: 3.4226, c: 5.1288, beta: 99.54, Z: 4, Biso: 0.50,
    atoms: [{el:'Cu', x:0.25, y:0.25, z:0}, {el:'O', x:0, y:0.4184, z:0.25}],
    extinct: 'C2c'
  },
  Fe2O3: {
    name: 'Hematite', system: 'hexagonal', sg: 'R-3c', sgNum: 167,
    a: 5.0356, c: 13.7489, Z: 6, Biso: 0.40,
    atoms: [{el:'Fe', x:0, y:0, z:0.35530}, {el:'O', x:0.3059, y:0, z:0.25}],
    extinct: 'R3c'
  },
  Fe3O4: {
    name: 'Magnetite', system: 'cubic', sg: 'Fd-3m', sgNum: 227,
    a: 8.3969, Z: 8, Biso: 0.45,
    atoms: [{el:'Fe', x:0.125, y:0.125, z:0.125},
            {el:'Fe', x:0.5, y:0.5, z:0.5},
            {el:'O', x:0.2549, y:0.2549, z:0.2549}],
    extinct: 'Fd'
  },
  NiO: {
    name: 'Bunsenite', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 4.1771, Z: 4, Biso: 0.40,
    atoms: [{el:'Ni', x:0, y:0, z:0}, {el:'O', x:0.5, y:0.5, z:0.5}],
    extinct: 'F'
  },
  TiO2: {
    name: 'Rutile', system: 'tetragonal', sg: 'P42/mnm', sgNum: 136,
    a: 4.5941, c: 2.9589, Z: 2, Biso: 0.42,
    atoms: [{el:'Ti', x:0, y:0, z:0}, {el:'O', x:0.3049, y:0.3049, z:0}],
    extinct: 'P42mnm'
  },
  LaB6: {
    name: 'Lanthanum Hexaboride', system: 'cubic', sg: 'Pm-3m', sgNum: 221,
    a: 4.1569, Z: 1, Biso: 0.32,
    atoms: [{el:'La', x:0, y:0, z:0}, {el:'B', x:0.1997, y:0.5, z:0.5},
            {el:'B', x:0.5, y:0.1997, z:0.5}, {el:'B', x:0.5, y:0.5, z:0.1997},
            {el:'B', x:0.8003, y:0.5, z:0.5}, {el:'B', x:0.5, y:0.8003, z:0.5},
            {el:'B', x:0.5, y:0.5, z:0.8003}],
    extinct: 'P'
  },
  SrTiO3: {
    name: 'Strontium Titanate', system: 'cubic', sg: 'Pm-3m', sgNum: 221,
    a: 3.9050, Z: 1, Biso: 0.45,
    atoms: [{el:'Sr', x:0.5, y:0.5, z:0.5}, {el:'Ti', x:0, y:0, z:0},
            {el:'O', x:0.5, y:0, z:0}, {el:'O', x:0, y:0.5, z:0}, {el:'O', x:0, y:0, z:0.5}],
    extinct: 'P'
  },
  Al2O3: {
    name: 'Corundum', system: 'hexagonal', sg: 'R-3c', sgNum: 167,
    a: 4.7589, c: 12.9910, Z: 6, Biso: 0.26,
    atoms: [{el:'Al', x:0, y:0, z:0.3520}, {el:'O', x:0.3064, y:0, z:0.25}],
    extinct: 'R3c'
  },
  ZnO: {
    name: 'Wurtzite', system: 'hexagonal', sg: 'P63mc', sgNum: 186,
    a: 3.2498, c: 5.2066, Z: 2, Biso: 0.56,
    atoms: [{el:'Zn', x:0.3333, y:0.6667, z:0}, {el:'O', x:0.3333, y:0.6667, z:0.3819}],
    extinct: 'P63mc'
  },
  GaAs: {
    name: 'Gallium Arsenide', system: 'cubic', sg: 'F-43m', sgNum: 216,
    a: 5.6533, Z: 4, Biso: 0.56,
    atoms: [{el:'Ga', x:0, y:0, z:0}, {el:'As', x:0.25, y:0.25, z:0.25}],
    extinct: 'F'
  },
  InP: {
    name: 'Indium Phosphide', system: 'cubic', sg: 'F-43m', sgNum: 216,
    a: 5.8687, Z: 4, Biso: 0.60,
    atoms: [{el:'In', x:0, y:0, z:0}, {el:'P', x:0.25, y:0.25, z:0.25}],
    extinct: 'F'
  },
  GaN: {
    name: 'Gallium Nitride', system: 'hexagonal', sg: 'P63mc', sgNum: 186,
    a: 3.1890, c: 5.1855, Z: 2, Biso: 0.30,
    atoms: [{el:'Ga', x:0.3333, y:0.6667, z:0}, {el:'N', x:0.3333, y:0.6667, z:0.3750}],
    extinct: 'P63mc'
  },
  BaTiO3: {
    name: 'Barium Titanate', system: 'cubic', sg: 'Pm-3m', sgNum: 221,
    a: 4.0094, Z: 1, Biso: 0.50,
    atoms: [{el:'Ba', x:0.5, y:0.5, z:0.5}, {el:'Ti', x:0, y:0, z:0},
            {el:'O', x:0.5, y:0, z:0}, {el:'O', x:0, y:0.5, z:0}, {el:'O', x:0, y:0, z:0.5}],
    extinct: 'P'
  },
  LiCoO2: {
    name: 'Lithium Cobalt Oxide', system: 'hexagonal', sg: 'R-3m', sgNum: 166,
    a: 2.8160, c: 14.0540, Z: 3, Biso: 0.50,
    atoms: [{el:'Li', x:0, y:0, z:0.5}, {el:'Co', x:0, y:0, z:0}, {el:'O', x:0, y:0, z:0.2605}],
    extinct: 'R3m'
  },
  MoS2: {
    name: 'Molybdenite', system: 'hexagonal', sg: 'P63/mmc', sgNum: 194,
    a: 3.1600, c: 12.2940, Z: 2, Biso: 0.50,
    atoms: [{el:'Mo', x:0.3333, y:0.6667, z:0.25}, {el:'S', x:0.3333, y:0.6667, z:0.621}],
    extinct: 'P'
  },
  Diamond: {
    name: 'Diamond', system: 'cubic', sg: 'Fd-3m', sgNum: 227,
    a: 3.5668, Z: 8, Biso: 0.15,
    atoms: [{el:'C', x:0, y:0, z:0}, {el:'C', x:0.25, y:0.25, z:0.25}],
    extinct: 'Fd'
  },
  W: {
    name: 'Tungsten', system: 'cubic', sg: 'Im-3m', sgNum: 229,
    a: 3.1652, Z: 2, Biso: 0.25,
    atoms: [{el:'W', x:0, y:0, z:0}],
    extinct: 'I'
  },
  MgO: {
    name: 'Periclase', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 4.2112, Z: 4, Biso: 0.35,
    atoms: [{el:'Mg', x:0, y:0, z:0}, {el:'O', x:0.5, y:0.5, z:0.5}],
    extinct: 'F'
  },
  CaF2: {
    name: 'Fluorite', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 5.4626, Z: 4, Biso: 0.80,
    atoms: [{el:'Ca', x:0, y:0, z:0}, {el:'F', x:0.25, y:0.25, z:0.25}],
    extinct: 'F'
  },
  CeO2: {
    name: 'Ceria', system: 'cubic', sg: 'Fm-3m', sgNum: 225,
    a: 5.4113, Z: 4, Biso: 0.40,
    atoms: [{el:'Ce', x:0, y:0, z:0}, {el:'O', x:0.25, y:0.25, z:0.25}],
    extinct: 'F'
  }
};

// ── Systematic Extinction Check ──
// Returns true if reflection (h,k,l) is ALLOWED for given extinction type
window.isReflectionAllowed = function(h, k, l, extinctType) {
  if (extinctType === 'P') return true; // primitive: all allowed
  if (extinctType === 'F') {
    // F-centering: h,k,l all odd or all even
    var p = (h % 2 + 2) % 2 + (k % 2 + 2) % 2 + (l % 2 + 2) % 2;
    return p === 0 || p === 3;
  }
  if (extinctType === 'I') {
    return (h + k + l) % 2 === 0;
  }
  if (extinctType === 'Fd') {
    // F-centering first
    var par = (h % 2 + 2) % 2 + (k % 2 + 2) % 2 + (l % 2 + 2) % 2;
    if (par !== 0 && par !== 3) return false;
    // diamond glide: if all even, h+k+l must be 4n
    if (par === 0) return (h + k + l) % 4 === 0;
    return true;
  }
  if (extinctType === 'Pn') {
    // 0kl: k+l = 2n; 00l: l = 2n
    if (h === 0 && (k + l) % 2 !== 0) return false;
    return true;
  }
  if (extinctType === 'C2c') {
    // C-centering: h+k = 2n; h0l: l = 2n
    if ((h + k) % 2 !== 0) return false;
    if (k === 0 && l % 2 !== 0) return false;
    return true;
  }
  if (extinctType === 'R3c') {
    // R-centering (obverse): -h+k+l = 3n; h-hl: l = 2n (when k=0)
    if ((-h + k + l) % 3 !== 0) return false;
    if (k === 0 && l % 2 !== 0) return false;
    return true;
  }
  if (extinctType === 'P42mnm') {
    // 00l: l = 2n; 0kl: k+l = 2n
    if (h === 0 && k === 0 && l % 2 !== 0) return false;
    if (h === 0 && (k + l) % 2 !== 0) return false;
    return true;
  }
  if (extinctType === 'P63mc') {
    // 000l: l = 2n
    if (h === 0 && k === 0 && l % 2 !== 0) return false;
    return true;
  }
  return true;
};

// ── EXAFS Scattering Path Database ──
// Key: 'material:absorber' or element name
// Each path: {neighbor, N, R (A), sigma2 (A^2)}
var FEFF_PATHS = {
  Cu: [
    {neighbor:'Cu', N:12, R:2.556, sigma2:0.0087},
    {neighbor:'Cu', N:6,  R:3.615, sigma2:0.0100}
  ],
  Fe: [
    {neighbor:'Fe', N:8,  R:2.482, sigma2:0.0060},
    {neighbor:'Fe', N:6,  R:2.867, sigma2:0.0080}
  ],
  Ni: [
    {neighbor:'Ni', N:12, R:2.492, sigma2:0.0060},
    {neighbor:'Ni', N:6,  R:3.524, sigma2:0.0090}
  ],
  Au: [
    {neighbor:'Au', N:12, R:2.884, sigma2:0.0083},
    {neighbor:'Au', N:6,  R:4.078, sigma2:0.0100}
  ],
  Pt: [
    {neighbor:'Pt', N:12, R:2.775, sigma2:0.0053},
    {neighbor:'Pt', N:6,  R:3.924, sigma2:0.0070}
  ],
  'Cu2O:Cu': [
    {neighbor:'O',  N:2,  R:1.85,  sigma2:0.003},
    {neighbor:'Cu', N:12, R:3.02,  sigma2:0.006},
    {neighbor:'O',  N:6,  R:3.59,  sigma2:0.008}
  ],
  'CuO:Cu': [
    {neighbor:'O',  N:4,  R:1.96,  sigma2:0.004},
    {neighbor:'Cu', N:4,  R:2.90,  sigma2:0.007},
    {neighbor:'O',  N:4,  R:2.78,  sigma2:0.009}
  ],
  'Fe2O3:Fe': [
    {neighbor:'O',  N:3,  R:1.945, sigma2:0.004},
    {neighbor:'O',  N:3,  R:2.116, sigma2:0.005},
    {neighbor:'Fe', N:1,  R:2.900, sigma2:0.006},
    {neighbor:'Fe', N:3,  R:2.971, sigma2:0.007}
  ],
  'NiO:Ni': [
    {neighbor:'O',  N:6,  R:2.084, sigma2:0.005},
    {neighbor:'Ni', N:12, R:2.954, sigma2:0.006}
  ],
  'SrTiO3:Ti': [
    {neighbor:'O',  N:6,  R:1.952, sigma2:0.004},
    {neighbor:'Sr', N:8,  R:3.382, sigma2:0.008},
    {neighbor:'Ti', N:6,  R:3.905, sigma2:0.005}
  ],
  'SrTiO3:Sr': [
    {neighbor:'O',  N:12, R:2.761, sigma2:0.010},
    {neighbor:'Ti', N:8,  R:3.382, sigma2:0.008},
    {neighbor:'Sr', N:6,  R:3.905, sigma2:0.006}
  ]
};

// Find best matching FEFF paths for a given formula + absorber
window.matchFEFFPaths = function(formula, absorber) {
  // Try exact compound match first
  var key = formula + ':' + absorber;
  if (FEFF_PATHS[key]) return FEFF_PATHS[key];
  // Try element-only match
  if (FEFF_PATHS[absorber]) return FEFF_PATHS[absorber];
  // Fallback: generic first-shell from element data
  var elData = XRAY_ELEMENTS[absorber];
  if (!elData) return [];
  // Generate generic path (nearest neighbor estimate)
  return [{neighbor:'X', N:6, R:2.0, sigma2:0.006}];
};

// Find all absorption edges in a formula within energy range
window.findEdges = function(formula, eMin, eMax) {
  var parsed = (typeof formula === 'string') ? parseFormula(formula) : formula;
  var edges = [];
  var keys = Object.keys(parsed);
  for (var i = 0; i < keys.length; i++) {
    var el = keys[i];
    var elData = XRAY_ELEMENTS[el];
    if (!elData) continue;
    if (elData.K && elData.K >= eMin && elData.K <= eMax) {
      edges.push({element: el, edge: 'K', energy: elData.K});
    }
    if (elData.L3 && elData.L3 >= eMin && elData.L3 <= eMax) {
      edges.push({element: el, edge: 'L3', energy: elData.L3});
    }
  }
  edges.sort(function(a, b) { return a.energy - b.energy; });
  return edges;
};

// ── XRF Signal Model ──
// Compute fluorescence signal for one element at one position
// flux: photons/s at sample, E_inc: incident energy (eV)
// element: element symbol, wt_frac: weight fraction (0-1)
// thickness_cm: sample thickness (cm), matDensity: matrix density (g/cm3)
// dwell: dwell time (s)
// Returns: {counts_Ka, counts_Kb, counts_La, counts_Lb, total}
window.xrfSignal = function(flux, E_inc, element, wt_frac, thickness_cm, matDensity, dwell) {
  var el = XRAY_ELEMENTS[element];
  var yld = XRF_YIELDS[element];
  if (!el || !yld) return {counts_Ka:0, counts_Kb:0, counts_La:0, counts_Lb:0, total:0};

  // Determine which edge is excited
  var useK = (el.K && E_inc > el.K);
  var useL = (!useK && el.L3 && E_inc > el.L3);
  if (!useK && !useL) return {counts_Ka:0, counts_Kb:0, counts_La:0, counts_Lb:0, total:0};

  // Photoelectric cross section approximation (E^-2.8 scaling from nearest data)
  var muData = XRF_MU_PHOTO[element];
  var mu_pe = 100; // fallback cm^2/g
  if (muData && muData.mu) {
    var bestE = 0, bestMu = 100;
    var mkeys = Object.keys(muData.mu);
    for (var i = 0; i < mkeys.length; i++) {
      var ek = parseInt(mkeys[i]);
      if (Math.abs(ek - E_inc) < Math.abs(bestE - E_inc) || bestE === 0) {
        bestE = ek; bestMu = muData.mu[mkeys[i]];
      }
    }
    // Scale by E^-2.8
    if (bestE > 0 && bestE !== E_inc) {
      mu_pe = bestMu * Math.pow(bestE / E_inc, 2.8);
    } else {
      mu_pe = bestMu;
    }
  } else {
    // Generic: mu ~ Z^4 / E^3 (very rough)
    mu_pe = 1e6 * Math.pow(el.Z / 26.0, 4.0) * Math.pow(7000 / E_inc, 2.8);
  }

  // Fluorescence yield
  var omega = useK ? (yld.omega_K || 0) : (yld.omega_L3 || 0);

  // Self-absorption factor: (1 - exp(-mu*rho*t)) / (mu*rho*t)
  var mu_rho_t = mu_pe * matDensity * thickness_cm;
  var selfAbsFactor = 1.0;
  if (mu_rho_t > 0.001) {
    selfAbsFactor = (1 - Math.exp(-mu_rho_t)) / mu_rho_t;
  }

  // Fundamental signal: N = flux * dwell * wt_frac * mu_pe(cm2/g) * rho(g/cm3) * t(cm)
  //   * omega * (branch) * (Omega/4pi) * eff_det * selfAbsFactor
  var rawSignal = flux * dwell * wt_frac * mu_pe * matDensity * thickness_cm
    * omega * selfAbsFactor
    * SDD_SPEC.totalSolidAngle_sr / (4 * Math.PI);

  // Branch into K or L lines
  var cKa = 0, cKb = 0, cLa = 0, cLb = 0;
  if (useK) {
    var brKa = XRF_K_BRANCH.Ka1 + XRF_K_BRANCH.Ka2;
    var brKb = XRF_K_BRANCH.Kb1 + XRF_K_BRANCH.Kb3;
    var lineKa = el.lines ? (el.lines.Ka || 0) : 0;
    var lineKb = el.lines ? (el.lines.Kb || 0) : 0;
    var effKa = lineKa > 0 ? sddEfficiency(lineKa) : 0.9;
    var effKb = lineKb > 0 ? sddEfficiency(lineKb) : 0.9;
    cKa = rawSignal * brKa * effKa;
    cKb = rawSignal * brKb * effKb;
  }
  if (useL || (useK && el.L3)) {
    // L lines can be excited by K decay (Coster-Kronig) or directly
    var lScale = useL ? 1.0 : 0.1; // minor L contribution when K is primary
    var lineLa = el.lines ? (el.lines.La || 0) : 0;
    var lineLb = el.lines ? (el.lines.Lb || 0) : 0;
    if (lineLa > 0) {
      var effLa = sddEfficiency(lineLa);
      cLa = rawSignal * lScale * 0.7 * effLa;
    }
    if (lineLb > 0) {
      var effLb = sddEfficiency(lineLb);
      cLb = rawSignal * lScale * 0.3 * effLb;
    }
  }

  return {counts_Ka: cKa, counts_Kb: cKb, counts_La: cLa, counts_Lb: cLb,
          total: cKa + cKb + cLa + cLb};
};

// ── XRF Spectrum Generator ──
// Generates a full energy spectrum array (counts vs channel)
// formula: chemical formula string, E_inc: incident beam energy (eV)
// simXRFSpectrum REMOVED — legacy JS simulator deleted.
// XRF spectrum is now generated by server experiment engine (XRF2DEngine).
// The following helper functions (_poissonSample etc.) are retained for other uses.
// simXRFSpectrum DELETED — server experiment engine (XRF2DEngine) only.

// Poisson random sample (Knuth method for small lambda, Gaussian approx for large)
function _poissonSample(lambda) {
  if (lambda <= 0) return 0;
  if (lambda > 100) {
    // Gaussian approximation
    var u1 = Math.random(), u2 = Math.random();
    var z = Math.sqrt(-2 * Math.log(u1 + 1e-30)) * Math.cos(2 * Math.PI * u2);
    return Math.max(0, Math.round(lambda + Math.sqrt(lambda) * z));
  }
  var L = Math.exp(-lambda);
  var k = 0, p = 1;
  do { k++; p *= Math.random(); } while (p > L);
  return k - 1;
}

// ── Compound Density Database ──
// Common materials (g/cm3), ref: CRC Handbook
var COMPOUND_DENSITIES = {
  Cu:8.96, Fe:7.87, Ni:8.91, Au:19.3, Pt:21.45, Ag:10.49,
  Si:2.33, Al:2.70, Ti:4.51, W:19.25, Mo:10.28, Cr:7.19,
  Co:8.90, Zn:7.13, Mn:7.47, V:6.11, Ge:5.32, Se:4.81,
  SiO2:2.20, Al2O3:3.95, Fe2O3:5.24, Fe3O4:5.17, TiO2:4.23,
  Cu2O:6.0, CuO:6.31, NiO:6.67, ZnO:5.61, MgO:3.58,
  CeO2:7.22, BaTiO3:6.02, SrTiO3:5.12, LiCoO2:5.05,
  GaAs:5.32, InP:4.81, GaN:6.15, Si3N4:3.17,
  CaF2:3.18, NaCl:2.16, MoS2:5.06,
  H2O:1.0, C:2.27, BN:2.1, Diamond:3.51
};

// Estimate material density from formula
window.estimateDensity = function(formula) {
  if (COMPOUND_DENSITIES[formula]) return COMPOUND_DENSITIES[formula];
  // Check XRF_MU_PHOTO for single elements
  if (XRF_MU_PHOTO[formula] && XRF_MU_PHOTO[formula].rho) {
    return XRF_MU_PHOTO[formula].rho;
  }
  // Rough estimate from average atomic mass
  var parsed = parseFormula(formula);
  var M = compoundMass(parsed);
  var nAtoms = 0;
  var keys = Object.keys(parsed);
  for (var i = 0; i < keys.length; i++) nAtoms += parsed[keys[i]];
  var avgM = M / Math.max(nAtoms, 1);
  return Math.max(1.0, 0.5 * Math.pow(avgM, 0.6));
};

// ── Compound Mass Attenuation Coefficient ──
// Returns mu/rho (cm^2/g) for a compound at energy E_eV
// Uses XRF_MU_PHOTO for calibrated elements, Victoreen fallback for others
window.compoundMuRho = function(formula, E_eV) {
  var parsed = (typeof formula === 'string') ? parseFormula(formula) : formula;
  var totalMass = compoundMass(parsed);
  if (totalMass <= 0) return 0;
  var muTotal = 0;
  var keys = Object.keys(parsed);
  for (var i = 0; i < keys.length; i++) {
    var el = keys[i];
    var elData = XRAY_ELEMENTS[el];
    if (!elData) continue;
    var wt = parsed[el] * elData.M / totalMass;
    muTotal += wt * _elementMuRho(el, E_eV);
  }
  return muTotal;
};

// Per-element mu/rho with edge-aware interpolation
function _elementMuRho(el, E_eV) {
  var elData = XRAY_ELEMENTS[el];
  if (!elData) return 0;
  var muData = XRF_MU_PHOTO[el];
  if (muData && muData.mu) {
    return _interpolateMuPhoto(muData.mu, E_eV, elData);
  }
  return _victoreenWithEdge(elData.Z, E_eV, elData.K, elData.L3);
}

// Interpolate from XRF_MU_PHOTO with E^-2.8 scaling, edge-aware
function _interpolateMuPhoto(muDict, E_eV, elData) {
  var sorted = [];
  var mkeys = Object.keys(muDict);
  for (var i = 0; i < mkeys.length; i++) {
    sorted.push({e: parseInt(mkeys[i]), mu: muDict[mkeys[i]]});
  }
  sorted.sort(function(a, b) { return a.e - b.e; });
  // Find nearest data point on same side of all edges
  var bestE = sorted[0].e;
  var bestMu = sorted[0].mu;
  var minDist = 1e20;
  for (var k = 0; k < sorted.length; k++) {
    if (_sameEdgeSide(sorted[k].e, E_eV, elData)) {
      var dist = Math.abs(sorted[k].e - E_eV);
      if (dist < minDist) {
        minDist = dist;
        bestE = sorted[k].e;
        bestMu = sorted[k].mu;
      }
    }
  }
  // If no same-side point found, use nearest anyway
  if (minDist >= 1e20) {
    for (var j = 0; j < sorted.length; j++) {
      var d2 = Math.abs(sorted[j].e - E_eV);
      if (d2 < minDist) { minDist = d2; bestE = sorted[j].e; bestMu = sorted[j].mu; }
    }
  }
  if (bestE > 0 && bestE !== E_eV) {
    return bestMu * Math.pow(bestE / E_eV, 2.8);
  }
  return bestMu;
}

function _sameEdgeSide(e1, e2, elData) {
  if (elData.K) {
    if ((e1 < elData.K && e2 >= elData.K) || (e1 >= elData.K && e2 < elData.K)) return false;
  }
  if (elData.L3) {
    if ((e1 < elData.L3 && e2 >= elData.L3) || (e1 >= elData.L3 && e2 < elData.L3)) return false;
  }
  return true;
}

// Victoreen model with edge-jump factors for uncalibrated elements
function _victoreenWithEdge(Z, E_eV, E_K, E_L3) {
  // Base Victoreen: mu ~ Z^3.5 / E^3
  var a = 1e-4 * Math.pow(Z, 3.5);
  var mu = a / Math.pow(E_eV / 1000, 3);
  // Apply edge-jump ratios (empirical: K-edge ~7-10x, L3 ~2-4x)
  if (E_K && E_eV >= E_K) {
    mu *= (5 + 0.15 * Z);
  }
  if (E_L3 && E_eV >= E_L3 && (!E_K || E_eV < E_K)) {
    mu *= 2.5;
  }
  return mu;
}

// Compute compound molecular weight
window.compoundMass = function(formula) {
  var parsed = (typeof formula === 'string') ? parseFormula(formula) : formula;
  var mass = 0;
  var keys = Object.keys(parsed);
  for (var i = 0; i < keys.length; i++) {
    var el = keys[i];
    var elData = XRAY_ELEMENTS[el];
    if (elData) mass += parsed[keys[i]] * elData.M;
  }
  return mass;
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof COMPOUND_DENSITIES!=="undefined")globalThis.COMPOUND_DENSITIES=COMPOUND_DENSITIES;
if(typeof CRYSTALS!=="undefined")globalThis.CRYSTALS=CRYSTALS;
if(typeof FEFF_PATHS!=="undefined")globalThis.FEFF_PATHS=FEFF_PATHS;
if(typeof SDD_SPEC!=="undefined")globalThis.SDD_SPEC=SDD_SPEC;
if(typeof WK_COEFFS!=="undefined")globalThis.WK_COEFFS=WK_COEFFS;
if(typeof XRAY_ELEMENTS!=="undefined")globalThis.XRAY_ELEMENTS=XRAY_ELEMENTS;
if(typeof XRD_SAMPLE_PRESETS!=="undefined")globalThis.XRD_SAMPLE_PRESETS=XRD_SAMPLE_PRESETS;
if(typeof XRF_K_BRANCH!=="undefined")globalThis.XRF_K_BRANCH=XRF_K_BRANCH;
if(typeof XRF_LINES!=="undefined")globalThis.XRF_LINES=XRF_LINES;
if(typeof XRF_MU_PHOTO!=="undefined")globalThis.XRF_MU_PHOTO=XRF_MU_PHOTO;
if(typeof XRF_SAMPLE_PRESETS!=="undefined")globalThis.XRF_SAMPLE_PRESETS=XRF_SAMPLE_PRESETS;
if(typeof XRF_YIELDS!=="undefined")globalThis.XRF_YIELDS=XRF_YIELDS;
if(typeof _elementMuRho!=="undefined")globalThis._elementMuRho=_elementMuRho;
if(typeof _interpolateMuPhoto!=="undefined")globalThis._interpolateMuPhoto=_interpolateMuPhoto;
if(typeof _poissonSample!=="undefined")globalThis._poissonSample=_poissonSample;
if(typeof _sameEdgeSide!=="undefined")globalThis._sameEdgeSide=_sameEdgeSide;
if(typeof _victoreenWithEdge!=="undefined")globalThis._victoreenWithEdge=_victoreenWithEdge;
if(typeof compoundMass!=="undefined")globalThis.compoundMass=compoundMass;
if(typeof compoundMuRho!=="undefined")globalThis.compoundMuRho=compoundMuRho;
if(typeof estimateDensity!=="undefined")globalThis.estimateDensity=estimateDensity;
if(typeof findEdges!=="undefined")globalThis.findEdges=findEdges;
if(typeof isReflectionAllowed!=="undefined")globalThis.isReflectionAllowed=isReflectionAllowed;
if(typeof matchFEFFPaths!=="undefined")globalThis.matchFEFFPaths=matchFEFFPaths;
if(typeof parseFormula!=="undefined")globalThis.parseFormula=parseFormula;
if(typeof scatteringFactor!=="undefined")globalThis.scatteringFactor=scatteringFactor;
if(typeof sddEfficiency!=="undefined")globalThis.sddEfficiency=sddEfficiency;
if(typeof sddFWHM!=="undefined")globalThis.sddFWHM=sddFWHM;
// simXRFSpectrum removed (server engine only)
if(typeof xrfSignal!=="undefined")globalThis.xrfSignal=xrfSignal;
