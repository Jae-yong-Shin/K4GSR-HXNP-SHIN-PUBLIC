"""Virtual Beamline Scientist -- Science Advisor Module.

Provides experiment planning, timing estimation, technique recommendation,
and concurrent experiment compatibility analysis for the K4GSR nanoprobe beamline.

Beamline specs:
  - Energy range: 5-25 keV (IVU24 undulator)
  - Focusing: KB mirrors (~50 nm nanobeam)
  - DCM: Si(111) / Si(311)
  - Detectors: Rayspec 3ch SDD (XRF), EIGER2 4M (XRD/Ptycho)

Usage:
    advisor = ScienceAdvisor()
    analysis = advisor.analyze_sample({"Ni": 30, "Co": 10, "Mn": 10, "O": 43})
    recs = advisor.recommend_techniques(analysis, "oxidation state mapping")
    plan = advisor.plan_experiment(analysis, beamtime_hours=8)
    print(advisor.format_plan_text(plan, "NCM cathode"))
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# ======================================================================
# Absorption Edge Database
# ======================================================================
# Duplicated from nlp_agent._EDGE_DB for independence (no cross-import).
# Contains K and L3 edge energies in keV.

EDGE_DB: Dict[str, Dict[str, float]] = {
    "Ti": {"K": 4.966}, "V": {"K": 5.470}, "Cr": {"K": 5.989},
    "Mn": {"K": 6.539}, "Fe": {"K": 7.112}, "Co": {"K": 7.709},
    "Ni": {"K": 8.333}, "Cu": {"K": 8.979}, "Zn": {"K": 9.659},
    "Ga": {"K": 10.367}, "Ge": {"K": 11.103}, "As": {"K": 11.867},
    "Se": {"K": 12.658}, "Sr": {"K": 16.105}, "Mo": {"K": 20.000},
    "Ag": {"K": 25.514},
    "Si": {"K": 1.839}, "P": {"K": 2.145}, "S": {"K": 2.472},
    "Ca": {"K": 4.038},
    "W": {"K": 69.525, "L3": 10.207},
    "Pt": {"K": 78.395, "L3": 11.564},
    "Au": {"K": 80.725, "L3": 11.919},
    "Pb": {"K": 88.005, "L3": 13.035},
    "Ba": {"L3": 5.247}, "La": {"L3": 5.483},
    "Ce": {"K": 40.443, "L3": 5.723},
}

BEAMLINE_E_MIN: float = 5.0   # keV
BEAMLINE_E_MAX: float = 25.0  # keV

# ======================================================================
# Timing Database -- duration estimates (seconds)
# ======================================================================

TIMING_DB: Dict[str, Any] = {
    # Scan durations
    "xanes": {"base_sec": 300, "desc": "XANES scan, ~300 points at 1 s/pt"},
    "xafs": {"base_sec": 900, "desc": "Full XAFS scan, ~900 points (k=12)"},
    "xafs_3rep": {"base_sec": 2700, "desc": "XAFS 3 repetitions for averaging"},
    "xrf_map_small": {
        "base_sec": 44,
        "desc": "10x10 um, 0.5 um step, 0.1 s dwell (21x21=441 pts)",
    },
    "xrf_map_medium": {
        "base_sec": 260,
        "desc": "50x50 um, 1 um step, 0.1 s dwell (51x51=2601 pts)",
    },
    "xrf_map_large": {
        "base_sec": 1000,
        "desc": "100x100 um, 1 um step, 0.1 s dwell (101x101)",
    },
    "xrd_single": {"base_sec": 60, "desc": "Single XRD pattern (1 min exposure)"},
    "xrd_map_small": {
        "base_sec": 220,
        "desc": "XRD map 10x10 um, 0.5 um step, 0.5 s/pt",
    },
    "ptycho": {
        "base_sec": 75,
        "desc": "12x12 Fermat scan + reconstruction (~75 s total)",
    },
    # Overhead durations (flat seconds)
    "energy_change_small": 120,    # < 2 keV change: DCM only, ~2 min
    "energy_change_large": 600,    # >= 2 keV change: DCM + full realignment, ~10 min
    "alignment_full": 1800,        # Full 7-step alignment: ~30 min
    "alignment_quick": 300,        # Quick alignment: ~5 min
    "sample_change": 300,          # Sample exchange: ~5 min
    "warmup": 600,                 # Initial beam warmup: ~10 min
}

# ======================================================================
# Setup Change Database
# ======================================================================
# Key: (from_technique, to_technique) -- normalised to base technique names.
# Value: dict with time_sec, desc, note.

SETUP_CHANGE_DB: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("xrf", "xrd"): {
        "time_sec": 1800,
        "desc": "XRF SDD detector -> XRD EIGER2 detector exchange",
        "note": "Manual swap ~30 min. Future robot: ~5 min",
    },
    ("xrd", "xrf"): {
        "time_sec": 1800,
        "desc": "XRD EIGER2 -> XRF SDD detector exchange",
        "note": "Manual swap ~30 min. Future robot: ~5 min",
    },
    ("xrf", "ptycho"): {
        "time_sec": 2700,
        "desc": (
            "XRF -> Ptychography "
            "(SDD removal + coherent mode setup + SSA adjustment + vacuum path)"
        ),
        "note": "Most time-consuming change ~45 min. Future robot: ~10 min",
    },
    ("ptycho", "xrf"): {
        "time_sec": 2700,
        "desc": "Ptychography -> XRF (remove coherent setup + mount SDD)",
        "note": "~45 min. Future robot: ~10 min",
    },
    ("xrd", "ptycho"): {
        "time_sec": 1200,
        "desc": "XRD -> Ptychography (same EIGER2, adjust coherence mode)",
        "note": "~20 min (same detector, SSA+vacuum change). Future: ~5 min",
    },
    ("ptycho", "xrd"): {
        "time_sec": 1200,
        "desc": "Ptychography -> XRD (relax coherence constraints)",
        "note": "~20 min. Future: ~5 min",
    },
    ("xrf", "xanes"): {
        "time_sec": 0,
        "desc": "XRF -> XANES (same SDD, switch to energy scan mode)",
        "note": "No hardware change needed",
    },
    ("xanes", "xrf"): {
        "time_sec": 0,
        "desc": "XANES -> XRF (same SDD, switch to raster mode)",
        "note": "No hardware change needed",
    },
    ("xanes", "xafs"): {
        "time_sec": 0,
        "desc": "XANES -> XAFS (same mode, extended energy range)",
        "note": "No hardware change",
    },
    ("xafs", "xanes"): {
        "time_sec": 0,
        "desc": "XAFS -> XANES (shorter scan range)",
        "note": "No hardware change",
    },
    ("xrf", "xafs"): {
        "time_sec": 0,
        "desc": "XRF -> XAFS (same SDD, energy scan mode)",
        "note": "No hardware change",
    },
    ("xafs", "xrf"): {
        "time_sec": 0,
        "desc": "XAFS -> XRF (switch to raster mode)",
        "note": "No hardware change",
    },
    ("xanes", "xrd"): {
        "time_sec": 1800,
        "desc": "XANES -> XRD (SDD -> EIGER2 swap)",
        "note": "~30 min. Future robot: ~5 min",
    },
    ("xrd", "xanes"): {
        "time_sec": 1800,
        "desc": "XRD -> XANES (EIGER2 -> SDD swap)",
        "note": "~30 min. Future robot: ~5 min",
    },
    ("xafs", "xrd"): {
        "time_sec": 1800,
        "desc": "XAFS -> XRD (SDD -> EIGER2)",
        "note": "~30 min. Future robot: ~5 min",
    },
    ("xrd", "xafs"): {
        "time_sec": 1800,
        "desc": "XRD -> XAFS (EIGER2 -> SDD)",
        "note": "~30 min. Future robot: ~5 min",
    },
    ("xanes", "ptycho"): {
        "time_sec": 2700,
        "desc": "XANES -> Ptychography (SDD removal + coherent setup)",
        "note": "~45 min",
    },
    ("ptycho", "xanes"): {
        "time_sec": 2700,
        "desc": "Ptychography -> XANES (remove coherent setup + mount SDD)",
        "note": "~45 min",
    },
    ("xafs", "ptycho"): {
        "time_sec": 2700,
        "desc": "XAFS -> Ptychography",
        "note": "~45 min",
    },
    ("ptycho", "xafs"): {
        "time_sec": 2700,
        "desc": "Ptychography -> XAFS",
        "note": "~45 min",
    },
}

# ======================================================================
# Experiment Compatibility
# ======================================================================
# Techniques that CAN run simultaneously (same detector geometry possible).

CONCURRENT_OK = {
    frozenset({"xrf", "ptycho"}),  # SDD + EIGER2 can coexist
}

# Techniques that CANNOT run simultaneously, with reason.
CONCURRENT_FORBIDDEN: Dict[frozenset, str] = {
    frozenset({"xanes", "xrf"}): (
        "XANES requires energy scanning; XRF mapping requires fixed energy raster"
    ),
    frozenset({"xanes", "xrd"}): "Different detector + different scan mode",
    frozenset({"xafs", "xrf"}): (
        "XAFS energy scan incompatible with XRF raster"
    ),
    frozenset({"xafs", "xrd"}): "Different detector + different scan mode",
    frozenset({"xanes", "ptycho"}): (
        "Energy scanning incompatible with ptychography"
    ),
    frozenset({"xafs", "ptycho"}): (
        "Energy scanning incompatible with ptychography"
    ),
    frozenset({"xrd", "xrf"}): (
        "Different primary detectors (EIGER2 vs SDD)"
    ),
}

# ======================================================================
# Science Knowledge Base
# ======================================================================

SCIENCE_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "battery_cathode": {
        "label": "Battery Cathode Material (2nd battery)",
        "keywords": [
            "battery", "cathode", "anode", "NMC", "NCM", "LFP", "LCO", "NCA",
            "배터리", "양극재", "음극재", "이차전지", "리튬", "충방전",
        ],
        "typical_elements": ["Ni", "Co", "Mn", "Fe", "Cu"],
        "science_questions": [
            "Oxidation state changes of transition metals during cycling",
            "Element distribution uniformity (phase segregation)",
            "Surface CEI (cathode-electrolyte interface) structure",
            "Degradation mechanisms (Ni migration, O loss, spinel formation)",
        ],
        "recommended_experiments": [
            {
                "technique": "xrf",
                "scan_type": "xrf_map_small",
                "target_elements": ["Ni", "Co", "Mn"],
                "purpose": "Multi-element distribution map for phase segregation analysis",
                "science": (
                    "Ni-rich regions correlate with capacity fade. "
                    "Co/Mn distribution indicates structural homogeneity."
                ),
            },
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["Ni"],
                "purpose": "Ni oxidation state quantification (Ni2+/Ni3+/Ni4+)",
                "science": (
                    "Ni redox behavior as function of state of charge. "
                    "Jahn-Teller distortion indicator."
                ),
            },
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["Co"],
                "purpose": "Co oxidation state for structural stability assessment",
                "science": (
                    "Co redox participation indicates structural integrity "
                    "of layered structure."
                ),
            },
            {
                "technique": "xafs",
                "scan_type": "xafs",
                "target_elements": ["Ni"],
                "purpose": "Ni local structure (Ni-O distance, coordination number)",
                "science": (
                    "Evidence for layered-to-spinel transition. "
                    "Jahn-Teller distortion quantification."
                ),
            },
            {
                "technique": "xrd",
                "scan_type": "xrd_map_small",
                "target_elements": [],
                "purpose": "Crystal phase distribution map",
                "science": (
                    "Layered vs spinel vs rock-salt phase spatial distribution "
                    "after cycling."
                ),
            },
        ],
    },
    "catalyst": {
        "label": "Catalyst / Catalysis",
        "keywords": [
            "catalyst", "catalysis", "Pt/C", "PEM", "fuel cell", "CeO2", "TiO2",
            "촉매", "연료전지", "담지체", "활성점", "반응",
        ],
        "typical_elements": ["Pt", "Ce", "Ni", "Co", "Fe", "Cu", "Au"],
        "science_questions": [
            "Active site oxidation state under reaction conditions",
            "Metal-support interaction (SMSI)",
            "Particle size and distribution uniformity",
            "Sintering and degradation during operation",
        ],
        "recommended_experiments": [
            {
                "technique": "xrf",
                "scan_type": "xrf_map_small",
                "target_elements": ["Pt", "Ce", "Ni"],
                "purpose": "Catalyst particle distribution mapping",
                "science": (
                    "Spatial uniformity of active sites. "
                    "Sintering detection via cluster analysis."
                ),
            },
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["Pt"],
                "purpose": "Pt oxidation state (Pt0 vs PtO vs PtO2)",
                "science": "Active site speciation under operando conditions.",
            },
            {
                "technique": "xafs",
                "scan_type": "xafs",
                "target_elements": ["Pt"],
                "purpose": "Pt coordination environment and bond distances",
                "science": (
                    "Particle size estimation from coordination number. "
                    "Metal-support interaction."
                ),
            },
        ],
    },
    "semiconductor": {
        "label": "Semiconductor / Electronics",
        "keywords": [
            "semiconductor", "chip", "IC", "interconnect", "transistor", "epitaxial",
            "반도체", "칩", "배선", "트랜지스터", "에피택셜", "박막", "TSV",
        ],
        "typical_elements": ["Cu", "W", "Co", "Ti", "Ga", "Ge", "As"],
        "science_questions": [
            "Interconnect Cu distribution and voiding",
            "Barrier layer integrity (Ti/TiN, Co)",
            "Strain distribution in epitaxial films",
            "Contamination and dopant profiling",
        ],
        "recommended_experiments": [
            {
                "technique": "xrf",
                "scan_type": "xrf_map_small",
                "target_elements": ["Cu", "W", "Co"],
                "purpose": "Interconnect/via element mapping at high resolution",
                "science": (
                    "Cu voiding detection, W plug distribution, barrier integrity."
                ),
            },
            {
                "technique": "xrd",
                "scan_type": "xrd_map_small",
                "target_elements": [],
                "purpose": "Strain/crystallinity mapping",
                "science": (
                    "Lattice distortion from Bragg peak shifts. Texture analysis."
                ),
            },
            {
                "technique": "ptycho",
                "scan_type": "ptycho",
                "target_elements": [],
                "purpose": "High-resolution phase-contrast imaging (~50 nm)",
                "science": (
                    "Non-destructive cross-section imaging. "
                    "Electron density mapping."
                ),
            },
        ],
    },
    "geology": {
        "label": "Geology / Earth Science",
        "keywords": [
            "geology", "mineral", "soil", "rock", "sediment", "ore", "mine",
            "지질", "광물", "토양", "암석", "퇴적물", "광산", "사장석",
        ],
        "typical_elements": ["Fe", "Mn", "Cr", "As", "Pb", "Sr", "Ti", "Cu", "Zn"],
        "science_questions": [
            "Heavy metal speciation in contaminated soils",
            "Mineral phase identification and distribution",
            "Redox state of transition metals in minerals",
            "Trace element zonation in crystals",
        ],
        "recommended_experiments": [
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["As", "Cr", "Fe"],
                "purpose": (
                    "Speciation analysis "
                    "(e.g., As(III) vs As(V), Cr(III) vs Cr(VI))"
                ),
                "science": (
                    "Redox state determines toxicity and mobility. "
                    "Critical for environmental assessment."
                ),
            },
            {
                "technique": "xrf",
                "scan_type": "xrf_map_medium",
                "target_elements": ["Fe", "Mn", "Sr"],
                "purpose": "Elemental distribution in thin sections",
                "science": (
                    "Mineral zoning patterns, trace element partitioning."
                ),
            },
        ],
    },
    "biology": {
        "label": "Biology / Life Science",
        "keywords": [
            "cell", "tissue", "protein", "neuron", "dendrite", "bacteria",
            "세포", "조직", "단백질", "신경", "박테리아", "동결건조", "생체",
        ],
        "typical_elements": ["Fe", "Zn", "Cu", "Mn", "Ca", "Se"],
        "science_questions": [
            "Trace metal distribution in cells/tissues",
            "Metal cofactor localization in organelles",
            "Toxic element accumulation patterns",
            "Metalloproteomics spatial mapping",
        ],
        "recommended_experiments": [
            {
                "technique": "xrf",
                "scan_type": "xrf_map_small",
                "target_elements": ["Fe", "Zn", "Cu"],
                "purpose": "Trace metal distribution in freeze-dried cells",
                "science": (
                    "Fe/Zn ratio in organelles. Cu in mitochondria. "
                    "Metal homeostasis."
                ),
            },
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["Fe"],
                "purpose": "Iron oxidation state in biological context",
                "science": (
                    "Fe2+/Fe3+ ratio indicates redox environment. "
                    "Ferritin vs free iron."
                ),
            },
        ],
    },
    "environment": {
        "label": "Environmental Science",
        "keywords": [
            "pollution", "waste", "fly ash", "sludge", "contamination",
            "remediation", "환경", "오염", "비산재", "슬러지", "하수",
            "폐기물", "정화",
        ],
        "typical_elements": ["Pb", "As", "Cr", "Zn", "Cu", "Fe", "Mn"],
        "science_questions": [
            "Toxic metal speciation in environmental samples",
            "Pb/As/Cr chemical form for risk assessment",
            "Metal binding to organic/mineral phases",
            "Remediation effectiveness evaluation",
        ],
        "recommended_experiments": [
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": ["Pb", "Cr", "As"],
                "purpose": "Toxic metal speciation for risk assessment",
                "science": (
                    "Cr(VI) vs Cr(III), As(III) vs As(V) "
                    "determine toxicity and mobility."
                ),
            },
            {
                "technique": "xrf",
                "scan_type": "xrf_map_medium",
                "target_elements": ["Pb", "As", "Fe"],
                "purpose": "Spatial distribution of contaminants",
                "science": (
                    "Hotspot identification. "
                    "Association with Fe/Mn oxides indicates sequestration."
                ),
            },
        ],
    },
    "materials": {
        "label": "Materials Science (General)",
        "keywords": [
            "alloy", "ceramic", "perovskite", "solar", "oxide", "thin film",
            "HEA", "합금", "세라믹", "페로브스카이트", "태양전지", "산화물",
            "박막", "고엔트로피",
        ],
        "typical_elements": ["Fe", "Co", "Ni", "Cr", "Mn", "Cu", "Ti", "Pb", "Sr"],
        "science_questions": [
            "Phase distribution and homogeneity",
            "Oxidation state and local structure",
            "Strain and defect mapping",
            "Composition-property correlations",
        ],
        "recommended_experiments": [
            {
                "technique": "xrf",
                "scan_type": "xrf_map_small",
                "target_elements": [],
                "purpose": "Multi-element distribution mapping",
                "science": (
                    "Phase segregation, composition gradient, "
                    "interdiffusion analysis."
                ),
            },
            {
                "technique": "xanes",
                "scan_type": "xanes",
                "target_elements": [],
                "purpose": "Oxidation state analysis",
                "science": (
                    "Chemical environment fingerprinting "
                    "via near-edge structure."
                ),
            },
            {
                "technique": "xrd",
                "scan_type": "xrd_map_small",
                "target_elements": [],
                "purpose": "Phase/crystallinity spatial mapping",
                "science": (
                    "Polymorph distribution, amorphous vs crystalline regions."
                ),
            },
        ],
    },
}

# ======================================================================
# Detector groups -- used for ordering experiments to minimise changes
# ======================================================================
# Lower group number = scheduled first.
# Within a group, techniques sharing the same detector are adjacent.

_DETECTOR_GROUP: Dict[str, int] = {
    "xrf": 0,     # SDD-based techniques first
    "xanes": 0,
    "xafs": 0,
    "xrd": 1,     # EIGER2 techniques next
    "ptycho": 2,  # Ptychography last (coherent mode overhead)
}

_TECHNIQUE_LABEL: Dict[str, str] = {
    "xrf": "XRF Mapping",
    "xanes": "Nano-XANES",
    "xafs": "Nano-XAFS",
    "xrd": "Nano-XRD",
    "ptycho": "Ptychography",
}

# Elements that are not X-ray-measurable (too light or no useful edge)
_UNMEASURABLE_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al",
}


# ======================================================================
# Helper functions (module-private)
# ======================================================================

def _best_edge(elem: str, e_min: float, e_max: float) -> Optional[Tuple[str, float]]:
    """Find the best measurable absorption edge for *elem* within the
    beamline energy range [e_min, e_max].

    Preference order: K > L3 (K is sharper and more interpretable).
    Returns (edge_name, energy_keV) or None if no edge is reachable.
    """
    edges = EDGE_DB.get(elem)
    if edges is None:
        return None
    # Prefer K edge if it is within range
    for edge_name in ("K", "L3"):
        energy = edges.get(edge_name)
        if energy is not None and e_min <= energy <= e_max:
            return (edge_name, energy)
    return None


def _detect_domain(elements: List[str], research_goal: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Detect the most likely science domain from the element list and an
    optional research-goal string.

    Returns (domain_key, label) or (None, None).
    """
    best_key: Optional[str] = None
    best_score: int = 0

    goal_lower = (research_goal or "").lower()

    for domain_key, info in SCIENCE_KNOWLEDGE.items():
        score = 0
        # Keyword match in research_goal
        for kw in info["keywords"]:
            if kw.lower() in goal_lower:
                score += 3
        # Element overlap
        typical = set(info["typical_elements"])
        overlap = typical.intersection(elements)
        score += len(overlap) * 2
        if score > best_score:
            best_score = score
            best_key = domain_key

    if best_score < 2:
        return (None, None)
    return (best_key, SCIENCE_KNOWLEDGE[best_key]["label"])


def _energy_change_overhead(from_energy: float, to_energy: float) -> Tuple[int, str]:
    """Return (overhead_sec, description) for an energy change."""
    delta = abs(to_energy - from_energy)
    if delta < 0.01:
        return (0, "No energy change")
    if delta < 2.0:
        return (
            TIMING_DB["energy_change_small"],
            "Quick DCM tune (%.1f keV -> %.1f keV, delta=%.2f keV)"
            % (from_energy, to_energy, delta),
        )
    return (
        TIMING_DB["energy_change_large"],
        "Full energy change + realignment (%.1f keV -> %.1f keV, delta=%.2f keV)"
        % (from_energy, to_energy, delta),
    )


def _normalise_technique(name: str) -> str:
    """Normalise technique name to canonical form."""
    name = name.strip().lower().replace("-", "").replace("_", "")
    mapping = {
        "xrf": "xrf", "xrfmap": "xrf", "xrfmapping": "xrf",
        "xanes": "xanes", "nanoxanes": "xanes",
        "xafs": "xafs", "exafs": "xafs", "nanoxafs": "xafs",
        "xrd": "xrd", "nanoxrd": "xrd", "xrdmap": "xrd",
        "ptycho": "ptycho", "ptychography": "ptycho", "cdi": "ptycho",
    }
    return mapping.get(name, name)


def _scan_time(scan_type: str, repetitions: int = 1) -> int:
    """Return scan duration in seconds for *scan_type* x *repetitions*."""
    entry = TIMING_DB.get(scan_type)
    if entry is None:
        return 300  # fallback: assume 5 min for unknown scan type
    if isinstance(entry, dict):
        return entry["base_sec"] * max(1, repetitions)
    # Flat integer (overhead entries) -- should not happen but be safe
    return int(entry) * max(1, repetitions)


def _sort_key_for_experiment(exp: dict) -> Tuple[int, float, str]:
    """Sort key to order experiments for minimal setup changes.

    Strategy:
      1. Group by detector (SDD group 0, EIGER2 group 1, Ptycho group 2)
      2. Within a group, sort by energy ascending (minimise energy jumps)
      3. Within same energy, alphabetical by technique name
    """
    tech = _normalise_technique(exp.get("technique", ""))
    group = _DETECTOR_GROUP.get(tech, 99)
    energy = exp.get("energy", 10.0)
    return (group, energy, tech)


# ======================================================================
# ScienceAdvisor class
# ======================================================================

class ScienceAdvisor:
    """Virtual Beamline Scientist -- provides experiment planning and
    technique recommendations for the K4GSR nanoprobe beamline.

    All public methods return plain dicts/lists suitable for JSON
    serialisation so they can be used directly in REST API responses.
    """

    def __init__(self) -> None:
        self.edge_db: Dict[str, Dict[str, float]] = EDGE_DB
        self.e_min: float = BEAMLINE_E_MIN
        self.e_max: float = BEAMLINE_E_MAX

    # ------------------------------------------------------------------
    # analyze_sample
    # ------------------------------------------------------------------

    def analyze_sample(
        self,
        composition: Dict[str, float],
        ppm_values: Optional[Dict[str, float]] = None,
        research_goal: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze sample composition and determine measurable elements.

        Args:
            composition: Element symbol -> weight percent.
                e.g. {"Ni": 30.0, "Co": 10.0, "Mn": 10.0, "Li": 6.9, "O": 43.1}
            ppm_values: Optional element symbol -> ppm for trace analysis.
                e.g. {"Cu": 50}
            research_goal: Optional free-text research objective used for
                domain detection.

        Returns:
            dict with keys:
                measurable: list of element info dicts (sorted by priority)
                not_measurable: list of element info dicts
                domain: detected domain key string or None
                domain_label: human-readable domain description or None
                domain_context: science-questions list or None
                all_elements: list of all element symbols provided
        """
        if ppm_values is None:
            ppm_values = {}

        measurable: List[Dict[str, Any]] = []
        not_measurable: List[Dict[str, Any]] = []
        all_elements: List[str] = []

        # Merge composition + ppm_values into a unified element set
        # (composition takes precedence if both present)
        all_elem_set: Dict[str, Dict[str, Any]] = {}
        for elem, wt_pct in composition.items():
            all_elem_set[elem] = {"wt_pct": wt_pct, "ppm": None}
        for elem, ppm in ppm_values.items():
            if elem in all_elem_set:
                all_elem_set[elem]["ppm"] = ppm
            else:
                all_elem_set[elem] = {"wt_pct": None, "ppm": ppm}

        for elem, info in all_elem_set.items():
            all_elements.append(elem)

            # 1. Unmeasurable light elements
            if elem in _UNMEASURABLE_ELEMENTS:
                not_measurable.append({
                    "element": elem,
                    "reason": (
                        "Too light for hard X-ray fluorescence "
                        "(Z too low or no K/L edge in 5-25 keV range)"
                    ),
                })
                continue

            # 2. Find best edge
            edge_result = _best_edge(elem, self.e_min, self.e_max)
            if edge_result is None:
                # Element is known but edge is out of range
                edges = self.edge_db.get(elem)
                if edges is None:
                    reason = "Element not in edge database"
                else:
                    edge_strs = [
                        "%s=%.3f keV" % (k, v) for k, v in edges.items()
                    ]
                    reason = (
                        "No edge within beamline range (%.0f-%.0f keV). "
                        "Available edges: %s"
                        % (self.e_min, self.e_max, ", ".join(edge_strs))
                    )
                not_measurable.append({"element": elem, "reason": reason})
                continue

            edge_name, edge_energy = edge_result

            # 3. Determine concentration and priority
            wt_pct = info["wt_pct"]
            ppm = info["ppm"]

            if wt_pct is not None and wt_pct > 0:
                concentration_str = "%.2f wt%%" % wt_pct
                # Priority: major > minor > trace
                if wt_pct >= 5.0:
                    priority = "major"
                    priority_score = 100 + wt_pct
                elif wt_pct >= 0.1:
                    priority = "minor"
                    priority_score = 50 + wt_pct
                else:
                    priority = "trace"
                    priority_score = wt_pct
            elif ppm is not None:
                concentration_str = "%.0f ppm" % ppm
                if ppm >= 1000:
                    priority = "minor"
                    priority_score = 50 + ppm / 10000.0
                else:
                    priority = "trace"
                    priority_score = ppm / 10000.0
            else:
                concentration_str = "present"
                priority = "unknown"
                priority_score = 10

            # 4. Determine applicable techniques
            techniques = ["xrf"]  # All measurable elements can do XRF
            techniques.append("xanes")  # XANES at the edge
            techniques.append("xafs")   # XAFS at the edge
            # XRD and Ptycho are element-independent
            # (listed in domain recommendations instead)

            measurable.append({
                "element": elem,
                "wt_pct": wt_pct,
                "ppm": ppm,
                "concentration": concentration_str,
                "edge": edge_name,
                "energy_keV": edge_energy,
                "techniques": techniques,
                "priority": priority,
                "priority_score": priority_score,
            })

        # Sort measurable by priority score descending
        measurable.sort(key=lambda x: x["priority_score"], reverse=True)

        # Domain detection
        elem_symbols = [e["element"] for e in measurable]
        domain_key, domain_label = _detect_domain(elem_symbols, research_goal)
        domain_context: Optional[List[str]] = None
        if domain_key and domain_key in SCIENCE_KNOWLEDGE:
            domain_context = SCIENCE_KNOWLEDGE[domain_key]["science_questions"]

        return {
            "measurable": measurable,
            "not_measurable": not_measurable,
            "domain": domain_key,
            "domain_label": domain_label,
            "domain_context": domain_context,
            "all_elements": all_elements,
        }

    # ------------------------------------------------------------------
    # recommend_techniques
    # ------------------------------------------------------------------

    def recommend_techniques(
        self,
        sample_analysis: Dict[str, Any],
        research_goal: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recommend measurement techniques based on sample analysis.

        Args:
            sample_analysis: Output from :meth:`analyze_sample`.
            research_goal: Optional free-text research objective.

        Returns:
            List of recommended experiments, each dict containing:
                technique, scan_type, target_elements, purpose, science,
                estimated_time_sec, energy_keV, priority
        """
        recommendations: List[Dict[str, Any]] = []
        seen: set = set()  # de-duplicate (technique, scan_type, elem-tuple)

        measurable = sample_analysis.get("measurable", [])
        domain_key = sample_analysis.get("domain")

        # --- Phase 1: domain-specific recommendations ---
        if domain_key and domain_key in SCIENCE_KNOWLEDGE:
            domain_info = SCIENCE_KNOWLEDGE[domain_key]
            measurable_elems = {e["element"] for e in measurable}

            for rec in domain_info["recommended_experiments"]:
                # Filter target elements to measurable ones
                target_elems = [
                    el for el in rec["target_elements"]
                    if el in measurable_elems
                ]
                # For element-independent techniques (XRD, Ptycho), keep as-is
                if rec["target_elements"] and not target_elems:
                    continue  # No measurable targets for this recommendation

                # Determine energy for this experiment
                energy = 10.0  # default
                if target_elems:
                    # Use the first target element's edge energy
                    for m in measurable:
                        if m["element"] == target_elems[0]:
                            energy = m["energy_keV"]
                            break

                dedup_key = (
                    rec["technique"],
                    rec["scan_type"],
                    tuple(sorted(target_elems)),
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                time_sec = _scan_time(rec["scan_type"])
                recommendations.append({
                    "technique": rec["technique"],
                    "scan_type": rec["scan_type"],
                    "target_elements": target_elems or rec["target_elements"],
                    "purpose": rec["purpose"],
                    "science": rec["science"],
                    "estimated_time_sec": time_sec,
                    "energy_keV": energy,
                    "priority": "domain_recommended",
                })

        # --- Phase 2: element-driven recommendations ---
        # For each major/minor measurable element, ensure XRF + XANES coverage
        for elem_info in measurable:
            elem = elem_info["element"]
            energy = elem_info["energy_keV"]
            edge = elem_info["edge"]

            # XRF map for all measurable elements (one map covers all
            # elements at a given excitation energy, so group by energy later)
            xrf_key = ("xrf", "xrf_map_small", (elem,))
            if xrf_key not in seen:
                seen.add(xrf_key)
                recommendations.append({
                    "technique": "xrf",
                    "scan_type": "xrf_map_small",
                    "target_elements": [elem],
                    "purpose": "%s %s-edge XRF mapping" % (elem, edge),
                    "science": (
                        "Spatial distribution of %s at %s %s-edge (%.3f keV)."
                        % (elem, elem, edge, energy)
                    ),
                    "estimated_time_sec": _scan_time("xrf_map_small"),
                    "energy_keV": energy,
                    "priority": elem_info["priority"],
                })

            # XANES for major/minor elements
            if elem_info["priority"] in ("major", "minor"):
                xanes_key = ("xanes", "xanes", (elem,))
                if xanes_key not in seen:
                    seen.add(xanes_key)
                    recommendations.append({
                        "technique": "xanes",
                        "scan_type": "xanes",
                        "target_elements": [elem],
                        "purpose": "%s %s-edge XANES" % (elem, edge),
                        "science": (
                            "Oxidation state and chemical environment of %s "
                            "via near-edge fine structure." % elem
                        ),
                        "estimated_time_sec": _scan_time("xanes"),
                        "energy_keV": energy,
                        "priority": elem_info["priority"],
                    })

        # --- Phase 3: research-goal driven additions ---
        if research_goal:
            goal_lower = research_goal.lower()
            # If user mentions phase/crystal/strain, add XRD
            xrd_keywords = [
                "phase", "crystal", "strain", "lattice", "xrd",
                "결정", "상", "격자", "변형",
            ]
            if any(kw in goal_lower for kw in xrd_keywords):
                xrd_key = ("xrd", "xrd_map_small", ())
                if xrd_key not in seen:
                    seen.add(xrd_key)
                    recommendations.append({
                        "technique": "xrd",
                        "scan_type": "xrd_map_small",
                        "target_elements": [],
                        "purpose": "Crystal phase / strain mapping",
                        "science": (
                            "Bragg peak analysis for phase identification "
                            "and lattice strain."
                        ),
                        "estimated_time_sec": _scan_time("xrd_map_small"),
                        "energy_keV": 10.0,
                        "priority": "goal_driven",
                    })

            # If user mentions imaging/morphology/structure, add Ptycho
            ptycho_keywords = [
                "image", "imaging", "morphology", "structure", "ptycho",
                "resolution", "이미징", "구조", "형태",
            ]
            if any(kw in goal_lower for kw in ptycho_keywords):
                pty_key = ("ptycho", "ptycho", ())
                if pty_key not in seen:
                    seen.add(pty_key)
                    recommendations.append({
                        "technique": "ptycho",
                        "scan_type": "ptycho",
                        "target_elements": [],
                        "purpose": "High-resolution phase-contrast imaging",
                        "science": (
                            "Ptychographic CDI for ~50 nm spatial resolution "
                            "electron density map."
                        ),
                        "estimated_time_sec": _scan_time("ptycho"),
                        "energy_keV": 10.0,
                        "priority": "goal_driven",
                    })

        return recommendations

    # ------------------------------------------------------------------
    # check_compatibility
    # ------------------------------------------------------------------

    def check_compatibility(
        self, technique_a: str, technique_b: str
    ) -> Dict[str, Any]:
        """Check if two techniques can run simultaneously.

        Args:
            technique_a: First technique name.
            technique_b: Second technique name.

        Returns:
            dict with keys:
                compatible (bool): True if simultaneous operation is possible.
                reason (str): Explanation.
        """
        a = _normalise_technique(technique_a)
        b = _normalise_technique(technique_b)

        if a == b:
            return {
                "compatible": True,
                "reason": "Same technique -- trivially compatible.",
            }

        pair = frozenset({a, b})

        if pair in CONCURRENT_OK:
            return {
                "compatible": True,
                "reason": (
                    "%s and %s can run simultaneously "
                    "(compatible detector geometry)."
                    % (_TECHNIQUE_LABEL.get(a, a), _TECHNIQUE_LABEL.get(b, b))
                ),
            }

        reason = CONCURRENT_FORBIDDEN.get(pair)
        if reason:
            return {"compatible": False, "reason": reason}

        # Default: not explicitly listed -> assume incompatible (safe)
        return {
            "compatible": False,
            "reason": (
                "No explicit compatibility data for %s + %s. "
                "Assumed incompatible for safety." % (a, b)
            ),
        }

    # ------------------------------------------------------------------
    # get_setup_change_time
    # ------------------------------------------------------------------

    def get_setup_change_time(
        self, from_technique: str, to_technique: str
    ) -> Dict[str, Any]:
        """Get setup change time between two techniques.

        Args:
            from_technique: Current technique.
            to_technique: Next technique.

        Returns:
            dict with keys: time_sec, time_min, desc, note
        """
        a = _normalise_technique(from_technique)
        b = _normalise_technique(to_technique)

        if a == b:
            return {
                "time_sec": 0,
                "time_min": 0.0,
                "desc": "Same technique -- no setup change needed",
                "note": "Only sample change (~5 min) if different sample.",
            }

        entry = SETUP_CHANGE_DB.get((a, b))
        if entry is not None:
            return {
                "time_sec": entry["time_sec"],
                "time_min": round(entry["time_sec"] / 60.0, 1),
                "desc": entry["desc"],
                "note": entry["note"],
            }

        # Fallback: unknown pair -- assume worst case (30 min)
        return {
            "time_sec": 1800,
            "time_min": 30.0,
            "desc": "Unknown transition %s -> %s (estimated 30 min)" % (a, b),
            "note": "No specific data; using conservative estimate.",
        }

    # ------------------------------------------------------------------
    # estimate_duration
    # ------------------------------------------------------------------

    def estimate_duration(
        self,
        experiments: List[Dict[str, Any]],
        current_energy: float = 10.0,
    ) -> Dict[str, Any]:
        """Calculate total duration for a list of experiments.

        Each experiment dict should have:
            technique (str): e.g. "xrf", "xanes"
            scan_type (str): key into TIMING_DB, e.g. "xrf_map_small"
            energy_keV (float, optional): beam energy for this scan
            element (str, optional): target element symbol
            edge (str, optional): edge name
            repetitions (int, optional): number of repetitions (default 1)

        Args:
            experiments: List of experiment dicts.
            current_energy: Starting beam energy in keV.

        Returns:
            dict with: scan_time_sec, overhead_sec, setup_change_sec,
            total_sec, total_min, breakdown (list of step dicts)
        """
        if not experiments:
            return {
                "scan_time_sec": 0,
                "overhead_sec": 0,
                "setup_change_sec": 0,
                "total_sec": 0,
                "total_min": 0.0,
                "breakdown": [],
            }

        # Sort experiments for optimal ordering
        sorted_exps = sorted(experiments, key=_sort_key_for_experiment)

        scan_time_total = 0
        overhead_total = 0
        setup_change_total = 0
        breakdown: List[Dict[str, Any]] = []
        running_energy = current_energy
        prev_technique: Optional[str] = None

        for exp in sorted_exps:
            tech = _normalise_technique(exp.get("technique", "xrf"))
            scan_type = exp.get("scan_type", tech)
            energy = exp.get("energy_keV", running_energy)
            reps = max(1, exp.get("repetitions", 1))
            elem = exp.get("element", "")
            edge = exp.get("edge", "")

            step_items: List[Dict[str, Any]] = []

            # Setup change overhead
            if prev_technique is not None and prev_technique != tech:
                sc = self.get_setup_change_time(prev_technique, tech)
                if sc["time_sec"] > 0:
                    setup_change_total += sc["time_sec"]
                    step_items.append({
                        "type": "setup_change",
                        "time_sec": sc["time_sec"],
                        "desc": sc["desc"],
                    })

            # Energy change overhead
            ec_sec, ec_desc = _energy_change_overhead(running_energy, energy)
            if ec_sec > 0:
                overhead_total += ec_sec
                step_items.append({
                    "type": "energy_change",
                    "time_sec": ec_sec,
                    "desc": ec_desc,
                })
                running_energy = energy

            # Scan time
            scan_sec = _scan_time(scan_type, reps)
            scan_time_total += scan_sec

            label = "%s %s" % (
                _TECHNIQUE_LABEL.get(tech, tech),
                ("@ %s %s-edge (%.3f keV)" % (elem, edge, energy)) if elem else "",
            )

            step_items.append({
                "type": "scan",
                "time_sec": scan_sec,
                "desc": label.strip(),
                "scan_type": scan_type,
                "repetitions": reps,
            })

            breakdown.append({
                "technique": tech,
                "element": elem,
                "energy_keV": energy,
                "steps": step_items,
                "subtotal_sec": sum(s["time_sec"] for s in step_items),
            })

            prev_technique = tech
            running_energy = energy

        total_sec = scan_time_total + overhead_total + setup_change_total
        return {
            "scan_time_sec": scan_time_total,
            "overhead_sec": overhead_total,
            "setup_change_sec": setup_change_total,
            "total_sec": total_sec,
            "total_min": round(total_sec / 60.0, 1),
            "breakdown": breakdown,
        }

    # ------------------------------------------------------------------
    # plan_experiment
    # ------------------------------------------------------------------

    def plan_experiment(
        self,
        sample_analysis: Dict[str, Any],
        beamtime_hours: float,
        experiments: Optional[List[Dict[str, Any]]] = None,
        current_energy: float = 10.0,
        research_goal: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a time-allocated experiment plan within a beamtime budget.

        Strategy:
          1. Group experiments by detector to minimise setup changes
             (SDD group: XRF, XANES, XAFS -> EIGER2: XRD -> Coherent: Ptycho)
          2. Within each detector group, sort by energy ascending
          3. Add warmup/initial-alignment phase
          4. Calculate running cumulative totals
          5. Warn if total exceeds budget
          6. Recommend 10-15% buffer time

        Args:
            sample_analysis: Output from :meth:`analyze_sample`.
            beamtime_hours: Allocated beamtime in hours.
            experiments: Specific experiments to schedule.
                If None, uses :meth:`recommend_techniques` output.
            current_energy: Current beam energy in keV.
            research_goal: Optional research objective string.

        Returns:
            dict with: phases, total_time_min, spare_time_min, warnings,
            science_outcomes, beamline_strengths, beamline_limitations
        """
        budget_sec = beamtime_hours * 3600.0
        budget_min = beamtime_hours * 60.0

        # Use recommended techniques if none specified
        if experiments is None:
            experiments = self.recommend_techniques(
                sample_analysis, research_goal
            )

        if not experiments:
            return {
                "phases": [],
                "total_time_min": 0.0,
                "spare_time_min": budget_min,
                "warnings": ["No experiments to schedule."],
                "science_outcomes": [],
                "beamline_strengths": [],
                "beamline_limitations": [],
            }

        # --- Enrich experiments with energy info from sample analysis ---
        measurable_map: Dict[str, Dict[str, Any]] = {}
        for m in sample_analysis.get("measurable", []):
            measurable_map[m["element"]] = m

        enriched: List[Dict[str, Any]] = []
        for exp in experiments:
            e = dict(exp)  # shallow copy
            # Resolve energy from target elements if not set
            if "energy_keV" not in e or e["energy_keV"] is None:
                targets = e.get("target_elements", [])
                if targets:
                    first_elem = targets[0]
                    if first_elem in measurable_map:
                        e["energy_keV"] = measurable_map[first_elem]["energy_keV"]
                        e["element"] = first_elem
                        e["edge"] = measurable_map[first_elem]["edge"]
                if "energy_keV" not in e:
                    e["energy_keV"] = 10.0
            # Ensure element/edge fields exist
            if "element" not in e:
                targets = e.get("target_elements", [])
                e["element"] = targets[0] if targets else ""
            if "edge" not in e:
                elem = e.get("element", "")
                if elem and elem in measurable_map:
                    e["edge"] = measurable_map[elem]["edge"]
                else:
                    e["edge"] = ""
            enriched.append(e)

        # --- Sort: detector group -> energy -> technique ---
        enriched.sort(key=_sort_key_for_experiment)

        # --- Build phases ---
        phases: List[Dict[str, Any]] = []
        warnings: List[str] = []
        science_outcomes: List[str] = []

        # Phase 0: Warmup + initial alignment
        warmup_sec = TIMING_DB["warmup"] + TIMING_DB["alignment_full"]
        cumulative_sec = warmup_sec

        phases.append({
            "phase_num": 0,
            "title": "Beam warmup + initial full alignment",
            "experiments": [],
            "start_min": 0.0,
            "end_min": round(warmup_sec / 60.0, 1),
            "duration_min": round(warmup_sec / 60.0, 1),
            "setup_change": None,
            "notes": (
                "Beam warmup (~10 min) + 7-step full alignment (~30 min). "
                "Required at start of every beamtime session."
            ),
        })

        # Group experiments into phases by detector group
        running_energy = current_energy
        prev_technique: Optional[str] = None
        current_group: Optional[int] = None
        phase_num = 0

        for exp in enriched:
            tech = _normalise_technique(exp.get("technique", ""))
            group = _DETECTOR_GROUP.get(tech, 99)
            energy = exp.get("energy_keV", 10.0)
            scan_type = exp.get("scan_type", tech)
            reps = max(1, exp.get("repetitions", 1))
            elem = exp.get("element", "")
            edge = exp.get("edge", "")
            targets = exp.get("target_elements", [])
            purpose = exp.get("purpose", "")
            science = exp.get("science", "")

            # Determine if we need a new phase (detector group change)
            if current_group is not None and group != current_group:
                # Setup change between detector groups
                if prev_technique is not None:
                    sc = self.get_setup_change_time(prev_technique, tech)
                    if sc["time_sec"] > 0:
                        phase_num += 1
                        sc_start = round(cumulative_sec / 60.0, 1)
                        cumulative_sec += sc["time_sec"]
                        phases.append({
                            "phase_num": phase_num,
                            "title": "Setup change: %s" % sc["desc"],
                            "experiments": [],
                            "start_min": sc_start,
                            "end_min": round(cumulative_sec / 60.0, 1),
                            "duration_min": round(sc["time_sec"] / 60.0, 1),
                            "setup_change": {
                                "from": prev_technique,
                                "to": tech,
                                "time_sec": sc["time_sec"],
                                "desc": sc["desc"],
                                "note": sc.get("note", ""),
                            },
                            "notes": sc.get("note", ""),
                        })

            current_group = group

            # Energy change overhead
            ec_sec, ec_desc = _energy_change_overhead(running_energy, energy)
            if ec_sec > 0:
                cumulative_sec += ec_sec

            # Scan time
            scan_sec = _scan_time(scan_type, reps)

            phase_num += 1
            phase_start = round(cumulative_sec / 60.0, 1)
            phase_duration = scan_sec + ec_sec
            cumulative_sec += scan_sec

            # Build experiment entry for this phase
            exp_entry = {
                "technique": tech,
                "technique_label": _TECHNIQUE_LABEL.get(tech, tech),
                "scan_type": scan_type,
                "element": elem,
                "edge": edge,
                "target_elements": targets,
                "energy_keV": energy,
                "repetitions": reps,
                "scan_time_sec": scan_sec,
                "purpose": purpose,
            }

            phase_notes_parts: List[str] = []
            if ec_sec > 0:
                phase_notes_parts.append(
                    "Energy change: %s (+%d sec)" % (ec_desc, ec_sec)
                )
            timing_entry = TIMING_DB.get(scan_type)
            if isinstance(timing_entry, dict) and "desc" in timing_entry:
                phase_notes_parts.append(timing_entry["desc"])

            phases.append({
                "phase_num": phase_num,
                "title": "%s%s" % (
                    _TECHNIQUE_LABEL.get(tech, tech),
                    (" -- %s %s-edge" % (elem, edge)) if elem else "",
                ),
                "experiments": [exp_entry],
                "start_min": phase_start,
                "end_min": round(cumulative_sec / 60.0, 1),
                "duration_min": round(phase_duration / 60.0, 1),
                "setup_change": None,
                "notes": "; ".join(phase_notes_parts) if phase_notes_parts else "",
            })

            # Collect science outcomes
            if science:
                science_outcomes.append(science)
            if purpose:
                science_outcomes.append("-> " + purpose)

            prev_technique = tech
            running_energy = energy

        # --- Budget analysis ---
        total_time_min = round(cumulative_sec / 60.0, 1)
        spare_time_min = round(budget_min - total_time_min, 1)
        buffer_recommended_min = round(budget_min * 0.15, 1)

        if total_time_min > budget_min:
            over_min = round(total_time_min - budget_min, 1)
            warnings.append(
                "OVER BUDGET: Plan requires %.1f min but only %.1f min "
                "(%.1f hours) allocated. Exceeds budget by %.1f min (%.1f hours). "
                "Consider removing lower-priority experiments."
                % (total_time_min, budget_min, beamtime_hours,
                   over_min, over_min / 60.0)
            )
        elif spare_time_min < buffer_recommended_min:
            warnings.append(
                "TIGHT SCHEDULE: Only %.1f min spare (recommended buffer: "
                "%.1f min = 15%% of %.1f hours). Limited room for retries."
                % (spare_time_min, buffer_recommended_min, beamtime_hours)
            )

        if spare_time_min > 0 and spare_time_min < buffer_recommended_min:
            warnings.append(
                "Consider reducing scan count or using smaller map sizes "
                "to free up buffer time."
            )

        # --- Beamline strengths / limitations ---
        beamline_strengths = [
            "Nanobeam focusing ~50 nm (KB mirrors) for high spatial resolution",
            "Wide energy range 5-25 keV covering K-edges of Ti through Ag",
            "Multi-technique capability: XRF, XANES, XAFS, XRD, Ptychography",
            "High flux from IVU24 undulator for fast mapping",
        ]

        beamline_limitations = [
            "Cannot measure light elements (Z < 14, Si) -- energy below 5 keV",
            "L-edges only for heavy elements (W, Pt, Au, Pb) -- K-edges too high",
            "Detector change required between SDD and EIGER2 techniques (~30 min)",
            "Ptychography requires coherent mode setup (~45 min from XRF)",
        ]

        # De-duplicate science outcomes
        seen_outcomes: set = set()
        unique_outcomes: List[str] = []
        for outcome in science_outcomes:
            if outcome not in seen_outcomes:
                seen_outcomes.add(outcome)
                unique_outcomes.append(outcome)

        return {
            "phases": phases,
            "total_time_min": total_time_min,
            "spare_time_min": spare_time_min,
            "budget_hours": beamtime_hours,
            "budget_min": budget_min,
            "buffer_recommended_min": buffer_recommended_min,
            "warnings": warnings,
            "science_outcomes": unique_outcomes,
            "beamline_strengths": beamline_strengths,
            "beamline_limitations": beamline_limitations,
        }

    # ------------------------------------------------------------------
    # format_plan_text
    # ------------------------------------------------------------------

    def format_plan_text(
        self,
        plan: Dict[str, Any],
        sample_desc: str = "",
    ) -> str:
        """Format experiment plan as human-readable Korean text for NLP
        response.

        Args:
            plan: Output from :meth:`plan_experiment`.
            sample_desc: Optional sample description string.

        Returns:
            Multi-line formatted string.
        """
        lines: List[str] = []

        # Header
        lines.append("=" * 60)
        if sample_desc:
            lines.append("  Experiment Plan: %s" % sample_desc)
        else:
            lines.append("  Experiment Plan")
        lines.append(
            "  Budget: %.1f hours (%.0f min)"
            % (plan.get("budget_hours", 0), plan.get("budget_min", 0))
        )
        lines.append("=" * 60)
        lines.append("")

        # Phases
        for phase in plan.get("phases", []):
            pnum = phase["phase_num"]
            title = phase["title"]
            start = phase["start_min"]
            end = phase["end_min"]
            duration = phase["duration_min"]

            if phase.get("setup_change"):
                # Setup change phase
                lines.append(
                    "  [Phase %d] %s" % (pnum, title)
                )
                lines.append(
                    "    Time: %.1f ~ %.1f min (%.1f min)"
                    % (start, end, duration)
                )
                sc = phase["setup_change"]
                if sc.get("note"):
                    lines.append("    Note: %s" % sc["note"])
            elif not phase["experiments"]:
                # Warmup / alignment phase
                lines.append(
                    "  [Phase %d] %s" % (pnum, title)
                )
                lines.append(
                    "    Time: %.1f ~ %.1f min (%.1f min)"
                    % (start, end, duration)
                )
                if phase.get("notes"):
                    lines.append("    Note: %s" % phase["notes"])
            else:
                # Experiment phase
                lines.append(
                    "  [Phase %d] %s" % (pnum, title)
                )
                lines.append(
                    "    Time: %.1f ~ %.1f min (%.1f min)"
                    % (start, end, duration)
                )
                for exp in phase["experiments"]:
                    lines.append(
                        "    Technique: %s" % exp.get("technique_label", exp.get("technique", ""))
                    )
                    if exp.get("energy_keV"):
                        lines.append(
                            "    Energy: %.3f keV" % exp["energy_keV"]
                        )
                    if exp.get("purpose"):
                        lines.append(
                            "    Purpose: %s" % exp["purpose"]
                        )
                    if exp.get("scan_time_sec"):
                        lines.append(
                            "    Scan time: %d sec (%.1f min)"
                            % (exp["scan_time_sec"],
                               exp["scan_time_sec"] / 60.0)
                        )
                if phase.get("notes"):
                    lines.append("    Note: %s" % phase["notes"])
            lines.append("")

        # Summary
        lines.append("-" * 60)
        total_min = plan.get("total_time_min", 0)
        spare_min = plan.get("spare_time_min", 0)
        budget_min = plan.get("budget_min", 0)
        lines.append(
            "  Total: %.1f min (%.1f hours) / Budget: %.1f min (%.1f hours)"
            % (total_min, total_min / 60.0, budget_min, budget_min / 60.0)
        )
        if spare_min >= 0:
            lines.append(
                "  Spare: %.1f min (%.1f hours) -- %.0f%% buffer"
                % (spare_min, spare_min / 60.0,
                   (spare_min / budget_min * 100) if budget_min > 0 else 0)
            )
        else:
            lines.append(
                "  OVER BUDGET by %.1f min (%.1f hours)"
                % (abs(spare_min), abs(spare_min) / 60.0)
            )
        lines.append("-" * 60)
        lines.append("")

        # Warnings
        warnings = plan.get("warnings", [])
        if warnings:
            lines.append("  [Warnings]")
            for w in warnings:
                lines.append("  ! %s" % w)
            lines.append("")

        # Science outcomes
        outcomes = plan.get("science_outcomes", [])
        if outcomes:
            lines.append("  [Expected Science Outcomes]")
            for i, o in enumerate(outcomes, 1):
                lines.append("  %d. %s" % (i, o))
            lines.append("")

        # Beamline strengths
        strengths = plan.get("beamline_strengths", [])
        if strengths:
            lines.append("  [Beamline Strengths]")
            for s in strengths:
                lines.append("  + %s" % s)
            lines.append("")

        # Beamline limitations
        limitations = plan.get("beamline_limitations", [])
        if limitations:
            lines.append("  [Beamline Limitations]")
            for lim in limitations:
                lines.append("  - %s" % lim)
            lines.append("")

        return "\n".join(lines)


# ======================================================================
# Convenience / CLI usage
# ======================================================================

if __name__ == "__main__":
    # Demo: NCM cathode sample
    advisor = ScienceAdvisor()

    print("=== Sample Analysis ===")
    analysis = advisor.analyze_sample(
        composition={"Ni": 30.0, "Co": 10.0, "Mn": 10.0, "Li": 6.9, "O": 43.1},
        ppm_values={"Cu": 50},
        research_goal="oxidation state mapping after cycling",
    )
    print("Domain:", analysis["domain"], "--", analysis["domain_label"])
    print("Measurable elements:")
    for m in analysis["measurable"]:
        print(
            "  %s (%s): %s %s-edge @ %.3f keV [%s]"
            % (m["element"], m["concentration"], m["element"],
               m["edge"], m["energy_keV"], m["priority"])
        )
    print("Not measurable:")
    for nm in analysis["not_measurable"]:
        print("  %s: %s" % (nm["element"], nm["reason"]))
    print()

    print("=== Technique Recommendations ===")
    recs = advisor.recommend_techniques(
        analysis, "oxidation state and phase distribution"
    )
    for r in recs:
        print(
            "  [%s] %s @ %.3f keV -- %s (%d sec)"
            % (r["technique"], r.get("target_elements", []),
               r.get("energy_keV", 0), r["purpose"],
               r["estimated_time_sec"])
        )
    print()

    print("=== Compatibility Checks ===")
    for a, b in [("xrf", "ptycho"), ("xanes", "xrf"), ("xrf", "xrd")]:
        c = advisor.check_compatibility(a, b)
        print("  %s + %s: %s -- %s" % (a, b, c["compatible"], c["reason"]))
    print()

    print("=== Experiment Plan (8 hours) ===")
    plan = advisor.plan_experiment(
        analysis, beamtime_hours=8,
        research_goal="oxidation state and phase distribution",
    )
    print(advisor.format_plan_text(plan, "NCM 811 cathode (cycled 200x)"))
