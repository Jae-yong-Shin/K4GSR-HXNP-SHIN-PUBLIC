"""Augment training data to 500+ examples for LoRA fine-tuning.

Strategy:
  1. Element x Technique x Formality systematic combinations
  2. Parameter variation (scan ranges, energies)
  3. Korean expression diversity (5+ phrasings per pattern)
  4. Domain context sentences (battery, catalyst, geo, bio, etc.)
  5. Edge cases & error handling patterns

Output: server/training_data_augmented.jsonl

Usage:
  python server/augment_training_data.py
  python server/augment_training_data.py --stats   # show statistics only
"""

import json
import logging
import os
import sys
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("nlp-augment")

sys.path.insert(0, os.path.dirname(__file__))

# Import base training data and system prompt
from generate_training_data import TRAINING_DATA, SYSTEM_PROMPT_LORA

random.seed(42)  # Reproducible

# ======================================================================
# Element Database
# ======================================================================
ELEMENTS = {
    # K-edge elements (5-25 keV range)
    "Ti": {"Z": 22, "K": 4.966, "edge": "K", "kr": "티타늄"},
    "Cr": {"Z": 24, "K": 5.989, "edge": "K", "kr": "크롬"},
    "Mn": {"Z": 25, "K": 6.539, "edge": "K", "kr": "망간"},
    "Fe": {"Z": 26, "K": 7.112, "edge": "K", "kr": "철"},
    "Co": {"Z": 27, "K": 7.709, "edge": "K", "kr": "코발트"},
    "Ni": {"Z": 28, "K": 8.333, "edge": "K", "kr": "니켈"},
    "Cu": {"Z": 29, "K": 8.979, "edge": "K", "kr": "구리"},
    "Zn": {"Z": 30, "K": 9.659, "edge": "K", "kr": "아연"},
    "As": {"Z": 33, "K": 11.867, "edge": "K", "kr": "비소"},
    "Se": {"Z": 34, "K": 12.658, "edge": "K", "kr": "셀레늄"},
    "Sr": {"Z": 38, "K": 16.105, "edge": "K", "kr": "스트론튬"},
    "Mo": {"Z": 42, "K": 20.000, "edge": "K", "kr": "몰리브덴"},
    # L3-edge elements
    "Ce": {"Z": 58, "L3": 5.723, "edge": "L3", "kr": "세륨"},
    "W":  {"Z": 74, "L3": 10.207, "edge": "L3", "kr": "텅스텐"},
    "Pt": {"Z": 78, "L3": 11.564, "edge": "L3", "kr": "백금"},
    "Au": {"Z": 79, "L3": 11.919, "edge": "L3", "kr": "금"},
    "Pb": {"Z": 82, "L3": 13.035, "edge": "L3", "kr": "납"},
}

# Out-of-range elements
OUT_OF_RANGE = {
    "S":  {"Z": 16, "K": 2.472, "kr": "황"},
    "P":  {"Z": 15, "K": 2.145, "kr": "인"},
    "Si": {"Z": 14, "K": 1.839, "kr": "실리콘"},
    "Al": {"Z": 13, "K": 1.560, "kr": "알루미늄"},
    "Mg": {"Z": 12, "K": 1.303, "kr": "마그네슘"},
}

def edge_energy(el):
    """Get edge energy for an element."""
    info = ELEMENTS[el]
    return info.get("K", info.get("L3"))

def xrf_energy(el):
    """Get XRF excitation energy (1-2 keV above edge)."""
    e = edge_energy(el)
    return round(e + 1.5, 1)

def needs_alignment(el, current_energy=10):
    """Check if energy change > 2 keV."""
    return abs(xrf_energy(el) - current_energy) > 2

# ======================================================================
# Korean Expression Templates
# ======================================================================

# XANES request patterns
XANES_TEMPLATES = [
    "{el_kr} K-edge XANES 측정해줘",
    "{el_kr} XANES 해주세요",
    "{el_sym} K-edge XANES 스캔 부탁해",
    "{el_sym} XANES 돌려줘",
    "{el_kr} 화학 상태 분석해줘",
    "{el_kr}의 산화 상태를 XANES로 확인해주세요",
    "{el_sym} K엣지 XANES 측정 부탁드립니다",
    "{el_kr} XANES 스캔해줘",
]

XANES_L3_TEMPLATES = [
    "{el_kr} L3-edge XANES 측정해줘",
    "{el_sym} L3 XANES 해주세요",
    "{el_kr} L3엣지 XANES 스캔해주세요",
    "{el_sym} L3-edge XANES 측정 부탁해",
]

# XAFS request patterns
XAFS_TEMPLATES = [
    "{el_kr} K-edge XAFS 측정해줘",
    "{el_sym} XAFS 해주세요",
    "{el_kr} XAFS 스캔 부탁해",
    "{el_sym} K-edge XAFS 돌려줘",
    "{el_kr} 원자 구조 XAFS로 분석해줘",
]

XAFS_L3_TEMPLATES = [
    "{el_kr} L3-edge XAFS 측정해줘",
    "{el_sym} L3 XAFS 해주세요",
]

# XRF map patterns
XRF_MAP_TEMPLATES = [
    "{el_kr} XRF 2D 맵 측정해줘. {rx}x{ry} {npts}포인트",
    "{el_sym} XRF 맵핑해줘. {rx}x{ry} 범위 {npts}포인트로",
    "{el_kr} 분포를 XRF로 이미징해주세요. {rx}x{ry} {npts}포인트",
    "{el_sym} XRF 2D 스캔 {rx}x{ry} {npts}포인트",
    "{el_kr} 원소 분포 XRF 맵핑 {rx}x{ry} {npts}포인트로 해줘",
]

# Motor move patterns
MOTOR_TEMPLATES = [
    "{motor_kr}를 {val}로 이동해",
    "{motor_kr}를 {val}로 이동해줘",
    "{motor_kr} {val}로 설정해줘",
    "{motor_kr}를 {val}로 맞춰줘",
    "{motor_kr} {val}로 변경해주세요",
]

MOTORS = {
    "M1 피치":   ("m1", "m1_pitch"),
    "M2 피치":   ("m2", "m2_pitch"),
    "DCM 세타":  ("dcm", "dcm_theta"),
    "시료 X":    ("sample", "sample_cx"),
    "시료 Y":    ("sample", "sample_cy"),
    "SSA 수평갭": ("ssa", "ssa_hgap"),
    "SSA 수직갭": ("ssa", "ssa_vgap"),
    "KBV 피치":  ("kbv", "kbv_pitch"),
    "KBH 피치":  ("kbh", "kbh_pitch"),
}

# Energy set patterns
ENERGY_TEMPLATES = [
    "에너지를 {e} keV로 설정해",
    "에너지 {e} keV로 바꿔줘",
    "빔 에너지를 {e} keV로 해주세요",
    "{e} keV로 에너지 설정해줘",
    "에너지를 {e}으로 변경해주세요",
]

# Optimization patterns
OPT_TEMPLATES = [
    "{el_kr} {tech_kr} 최적화해줘",
    "{el_sym} {tech_kr} 최적 조건 찾아줘",
    "{el_kr} {tech_kr} 분석 최적화해주세요",
    "{el_sym} {tech_kr} 최적 설정 계산해줘",
]

TECHNIQUES = {
    "xrf": {"kr": "XRF", "priority": "balanced"},
    "xafs": {"kr": "XAFS", "priority": "balanced"},
    "xanes": {"kr": "XANES", "priority": "balanced"},
    "xrd": {"kr": "XRD", "priority": "balanced"},
    "ptycho": {"kr": "ptychography", "priority": "coherence"},
}

# Signal estimation patterns
SIGNAL_TEMPLATES = [
    "{el_kr} {ppm}ppm 시료 XRF 신호 얼마나 나와?",
    "{el_sym} {ppm}ppm에서 신호 강도 확인해줘",
    "지금 셋업에서 {el_kr} {ppm}ppm 신호 예측해줘",
    "{el_sym} XRF 신호 추정해줘. {ppm}ppm 시료야",
]

# Information query patterns
INFO_TEMPLATES = [
    "{topic}가 뭐야?",
    "{topic}이 뭐예요?",
    "{topic}에 대해 설명해줘",
    "{topic} 설명해주세요",
]

INFO_TOPICS = {
    "XRD": "XRD(X선 회절)는 결정 구조를 분석하는 기법입니다. Bragg 법칙에 따라 회절 패턴으로 물질의 결정 구조를 파악합니다.",
    "XAFS": "XAFS(X선 흡수 미세구조)는 원소의 흡수 엣지 주변 스펙트럼으로 화학 상태와 원자 구조를 분석합니다. XANES와 EXAFS로 나뉩니다.",
    "XANES": "XANES(X선 흡수 근접 엣지 구조)는 흡수 엣지 주변 50-100 eV 영역에서 산화 상태와 화학 환경을 분석합니다.",
    "XRF": "XRF(X선 형광)는 시료에 X선을 조사하여 발생하는 형광 X선으로 원소 조성과 분포를 분석합니다.",
    "DCM": "DCM(이중결정 단색화기)은 Si(111) 또는 Si(311) 결정을 이용하여 특정 에너지의 X선만 선택합니다.",
    "KB 미러": "KB(Kirkpatrick-Baez) 미러는 수직/수평 집속 미러 쌍으로 나노 빔을 만드는 집속 장치입니다.",
    "언듈레이터": "언듈레이터는 싱크로트론 삽입 장치로, 주기적 자석 배열로 밝은 X선을 발생시킵니다.",
    "브래그 법칙": "브래그 법칙(2d sin theta = n lambda)은 결정면에 의한 X선 회절 조건을 정의합니다.",
    "ptychography": "Ptychography는 코히런트 X선으로 시료를 겹쳐 스캔하여 위상 정보를 복원하는 이미징 기법입니다.",
    "빔라인": "빔라인은 싱크로트론에서 X선을 시료까지 전달하는 광학 시스템입니다. 광원, 단색화기, 미러, 슬릿 등으로 구성됩니다.",
}

# Domain context patterns
DOMAIN_CONTEXTS = {
    "battery": [
        "배터리 양극재 시료에서",
        "NMC 622 양극재에서",
        "LiFePO4 시료의",
        "리튬이온 배터리 시료에서",
        "전고체 전지 시료에서",
        "양극재 시료의",
    ],
    "catalyst": [
        "Pt/C 촉매에서",
        "CeO2 담지체의",
        "금 나노입자 촉매에서",
        "니켈 촉매 시료의",
        "촉매 시료에서",
        "반응 중인 촉매의",
    ],
    "semiconductor": [
        "반도체 칩 단면에서",
        "에피택셜 박막의",
        "IC 단면 시료에서",
        "실리콘 웨이퍼 위의",
        "TSV 구조에서",
    ],
    "geology": [
        "토양 시료에서",
        "광물 시료의",
        "사장석 결정에서",
        "광산 폐기물 시료에서",
        "지질 시료의",
    ],
    "environment": [
        "비산재 입자에서",
        "하수 슬러지의",
        "오염 토양에서",
        "대기 미세먼지 시료의",
        "수질 시료에서",
    ],
    "biology": [
        "동결건조 세포에서",
        "신경세포 시료의",
        "뇌 조직 절편에서",
        "식물 조직의",
        "단백질 결정에서",
    ],
    "materials": [
        "페로브스카이트 태양전지에서",
        "고엔트로피 합금의",
        "금속 산화물 시료에서",
        "세라믹 시료의",
        "박막 시료에서",
    ],
}

# ======================================================================
# Augmentation Functions
# ======================================================================

def gen_xanes_examples():
    """Generate XANES measurement examples for all K-edge elements."""
    examples = []
    k_elements = [el for el, info in ELEMENTS.items() if info["edge"] == "K"]
    l3_elements = [el for el, info in ELEMENTS.items() if info["edge"] == "L3"]

    for el in k_elements:
        info = ELEMENTS[el]
        e_edge = info["K"]
        templates = XANES_TEMPLATES
        for tmpl in random.sample(templates, min(5, len(templates))):
            user_input = tmpl.format(el_kr=info["kr"], el_sym=el)
            e_xrf = round(e_edge + 1.5, 1)
            dE = abs(e_xrf - 10)

            actions = []
            if dE > 2:
                actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
                actions.append({"fn": "runFullAlignment", "args": []})
            actions.append({"fn": "quickXanes", "args": [el, "K"]})
            actions.append({"fn": "queueStart", "args": []})

            explanation = f"{el} K-edge XANES 스캔을 실행합니다."
            if dE > 2:
                explanation = f"{el} K-edge XANES. 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."

            examples.append((user_input, "energy=10",
                {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    for el in l3_elements:
        info = ELEMENTS[el]
        e_edge = info["L3"]
        templates = XANES_L3_TEMPLATES
        for tmpl in random.sample(templates, min(3, len(templates))):
            user_input = tmpl.format(el_kr=info["kr"], el_sym=el)
            e_xrf = round(e_edge + 1.5, 1)
            dE = abs(e_xrf - 10)

            actions = []
            if dE > 2:
                actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
                actions.append({"fn": "runFullAlignment", "args": []})
            actions.append({"fn": "quickXanes", "args": [el, "L3"]})
            actions.append({"fn": "queueStart", "args": []})

            explanation = f"{el} L3-edge XANES 스캔을 실행합니다."
            if dE > 2:
                explanation = f"{el} L3-edge XANES. 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."

            examples.append((user_input, "energy=10",
                {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


def gen_xafs_examples():
    """Generate XAFS examples."""
    examples = []
    k_elements = [el for el, info in ELEMENTS.items() if info["edge"] == "K"]
    l3_elements = [el for el, info in ELEMENTS.items() if info["edge"] == "L3"]

    for el in k_elements:
        info = ELEMENTS[el]
        e_edge = info["K"]
        for tmpl in random.sample(XAFS_TEMPLATES, min(3, len(XAFS_TEMPLATES))):
            user_input = tmpl.format(el_kr=info["kr"], el_sym=el)
            dE = abs(e_edge - 10)

            actions = []
            if dE > 2:
                actions.append({"fn": "setTargetEnergy", "args": [round(e_edge, 1)]})
                actions.append({"fn": "runFullAlignment", "args": []})
            actions.append({"fn": "quickXafs", "args": [el, "K"]})
            actions.append({"fn": "queueStart", "args": []})

            explanation = f"{el} K-edge XAFS 스캔을 실행합니다."
            if dE > 2:
                explanation += f" 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."

            examples.append((user_input, "energy=10",
                {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    for el in l3_elements:
        info = ELEMENTS[el]
        for tmpl in random.sample(XAFS_L3_TEMPLATES, min(2, len(XAFS_L3_TEMPLATES))):
            user_input = tmpl.format(el_kr=info["kr"], el_sym=el)
            e_edge = info["L3"]
            dE = abs(e_edge - 10)

            actions = []
            if dE > 2:
                actions.append({"fn": "setTargetEnergy", "args": [round(e_edge, 1)]})
                actions.append({"fn": "runFullAlignment", "args": []})
            actions.append({"fn": "quickXafs", "args": [el, "L3"]})
            actions.append({"fn": "queueStart", "args": []})

            explanation = f"{el} L3-edge XAFS 스캔을 실행합니다."
            examples.append((user_input, "energy=10",
                {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


def gen_xrf_map_examples():
    """Generate XRF mapping examples with varied params."""
    examples = []
    scan_params = [(5, 5, 21), (5, 5, 41), (10, 10, 21), (10, 10, 41),
                   (10, 10, 51), (20, 20, 41), (20, 20, 51), (3, 3, 31)]

    for el in list(ELEMENTS.keys()):
        info = ELEMENTS[el]
        edge = info["edge"]
        e_edge = info.get("K", info.get("L3"))
        e_xrf = round(e_edge + 1.5, 1)
        rx, ry, npts = random.choice(scan_params)
        tmpl = random.choice(XRF_MAP_TEMPLATES)
        user_input = tmpl.format(el_kr=info["kr"], el_sym=el, rx=rx, ry=ry, npts=npts)
        dE = abs(e_xrf - 10)

        actions = []
        if dE > 2:
            actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickRaster", "args": [rx, ry, npts]})
        actions.append({"fn": "queueStart", "args": []})

        explanation = f"{el} XRF {rx}x{ry} {npts}포인트 맵 측정합니다."
        if dE > 2:
            explanation = f"{el} {edge}-edge 위 {e_xrf} keV로 설정 후 정렬, XRF 맵 측정합니다."

        examples.append((user_input, "energy=10",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


def gen_motor_examples():
    """Generate motor move examples."""
    examples = []
    motor_vals = {
        "M1 피치": [2.0, 2.5, 3.0, 3.5],
        "M2 피치": [2.0, 2.5, 3.0, 3.5],
        "DCM 세타": [10, 12, 15, 20],
        "시료 X": [0, 50, 100, -100, 200],
        "시료 Y": [0, 50, 100, -50],
        "SSA 수평갭": [10, 20, 30, 50, 100],
        "SSA 수직갭": [10, 20, 30, 50, 100],
        "KBV 피치": [2.0, 2.5, 3.0],
        "KBH 피치": [2.0, 2.5, 3.0],
    }

    for motor_kr, (group, motor_id) in MOTORS.items():
        vals = motor_vals.get(motor_kr, [1, 2, 3])
        for val in random.sample(vals, min(3, len(vals))):
            tmpl = random.choice(MOTOR_TEMPLATES)
            user_input = tmpl.format(motor_kr=motor_kr, val=val)
            examples.append((user_input, "energy=10",
                {"actions": [{"fn": "motorSetUI", "args": [group, motor_id, val]}],
                 "explanation": f"{motor_kr}를 {val}로 설정합니다.",
                 "confirmation_required": True}))

    return examples


def gen_energy_examples():
    """Generate energy setting examples."""
    examples = []
    energies = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25]

    for e in random.sample(energies, 10):
        tmpl = random.choice(ENERGY_TEMPLATES)
        user_input = tmpl.format(e=e)
        dE = abs(e - 10)

        actions = [{"fn": "setTargetEnergy", "args": [e]}]
        explanation = f"빔 에너지를 {e} keV로 설정합니다."
        if dE > 2:
            actions.append({"fn": "runFullAlignment", "args": []})
            explanation += f" 에너지 변화 {dE} keV이므로 정렬 수행합니다."

        examples.append((user_input, "energy=10",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


def gen_optimize_examples():
    """Generate optimization examples."""
    examples = []
    for el in random.sample(list(ELEMENTS.keys()), 8):
        info = ELEMENTS[el]
        edge = info["edge"]
        for tech_key in random.sample(list(TECHNIQUES.keys()), 2):
            tech = TECHNIQUES[tech_key]
            tmpl = random.choice(OPT_TEMPLATES)
            user_input = tmpl.format(el_kr=info["kr"], el_sym=el, tech_kr=tech["kr"])
            priority = tech["priority"]

            examples.append((user_input, "energy=10",
                {"actions": [{"fn": "optimizeBeamline", "args": [
                    {"technique": tech_key, "element": el, "edge": edge,
                     "ppm": 1000, "sampleType": "solid", "priority": priority}
                ]}],
                 "explanation": f"{el} {tech['kr']} 최적화를 계산합니다.",
                 "confirmation_required": True}))

    return examples


def gen_signal_examples():
    """Generate signal estimation examples."""
    examples = []
    ppms = [1, 10, 100, 1000, 10000, 50000]

    for el in random.sample(list(ELEMENTS.keys()), 6):
        info = ELEMENTS[el]
        ppm = random.choice(ppms)
        tmpl = random.choice(SIGNAL_TEMPLATES)
        user_input = tmpl.format(el_kr=info["kr"], el_sym=el, ppm=ppm)

        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "estimateSignal", "args": ["xrf", el, ppm, 1e10, 50, 10]}],
             "explanation": f"{el} {ppm}ppm 시료의 XRF 신호를 예측합니다.",
             "confirmation_required": False}))

    return examples


def gen_info_examples():
    """Generate information query examples."""
    examples = []
    for topic, explanation in INFO_TOPICS.items():
        for tmpl in random.sample(INFO_TEMPLATES, 2):
            user_input = tmpl.format(topic=topic)
            examples.append((user_input, "energy=10",
                {"actions": [], "explanation": explanation, "confirmation_required": False}))

    # Element edge queries
    for el in random.sample(list(ELEMENTS.keys()), 5):
        info = ELEMENTS[el]
        edge = info["edge"]
        e = info.get("K", info.get("L3"))
        patterns = [
            f"{info['kr']} {edge} 엣지가 몇 keV예요?",
            f"{el} {edge}-edge 에너지가 뭐야?",
            f"{info['kr']}의 흡수 엣지 에너지 알려줘",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [], "explanation": f"{el} {edge}-edge 에너지는 {e} keV입니다.",
             "confirmation_required": False}))

    return examples


def gen_out_of_range_examples():
    """Generate out-of-range element examples."""
    examples = []
    for el, info in OUT_OF_RANGE.items():
        patterns = [
            f"{info['kr']} K-edge XANES 해주세요",
            f"{el} K-edge XAFS 측정해줘",
            f"{info['kr']} 화학 상태 분석해주세요",
        ]
        for pat in random.sample(patterns, 2):
            examples.append((pat, "energy=10",
                {"actions": [],
                 "explanation": f"{info['kr']}({el}) K-edge({info['K']} keV)는 빔라인 에너지 범위(5-25 keV)를 벗어납니다.",
                 "confirmation_required": False}))

    return examples


def gen_domain_examples():
    """Generate domain-specific examples combining context + technique."""
    examples = []

    domain_elements = {
        "battery": ["Ni", "Mn", "Co", "Fe", "Cu"],
        "catalyst": ["Pt", "Ce", "Au", "Ni", "Fe"],
        "semiconductor": ["Cu", "W", "Ti", "Co"],
        "geology": ["Fe", "As", "Cr", "Sr", "Mn"],
        "environment": ["Pb", "As", "Zn", "Cu", "Cr"],
        "biology": ["Fe", "Zn", "Cu", "Mn"],
        "materials": ["Pb", "Cu", "Fe", "Ti", "Ni"],
    }

    for domain, elements in domain_elements.items():
        contexts = DOMAIN_CONTEXTS[domain]
        for el in elements:
            info = ELEMENTS[el]
            edge = info["edge"]
            e_edge = info.get("K", info.get("L3"))
            ctx = random.choice(contexts)

            # XANES variation
            user_input = f"{ctx} {info['kr']} {edge} XANES 측정해주세요"
            dE = abs(e_edge - 10)
            actions = []
            if dE > 2:
                actions.append({"fn": "setTargetEnergy", "args": [round(e_edge + 1.5, 1)]})
                actions.append({"fn": "runFullAlignment", "args": []})
            actions.append({"fn": "quickXanes", "args": [el, edge]})
            actions.append({"fn": "queueStart", "args": []})
            explanation = f"{el} {edge}-edge XANES로 분석합니다."
            if dE > 2:
                explanation += " 에너지 변화로 정렬 수행합니다."

            examples.append((user_input, "energy=10",
                {"actions": actions, "explanation": explanation, "confirmation_required": True}))

            # XRF map variation
            rx, ry, npts = random.choice([(5, 5, 41), (10, 10, 41), (10, 10, 21)])
            user_input2 = f"{ctx} {info['kr']} XRF 맵핑해주세요. {rx}x{ry} {npts}포인트"
            e_xrf = round(e_edge + 1.5, 1)
            dE2 = abs(e_xrf - 10)
            actions2 = []
            if dE2 > 2:
                actions2.append({"fn": "setTargetEnergy", "args": [e_xrf]})
                actions2.append({"fn": "runFullAlignment", "args": []})
            actions2.append({"fn": "quickRaster", "args": [rx, ry, npts]})
            actions2.append({"fn": "queueStart", "args": []})
            explanation2 = f"{el} XRF {rx}x{ry} {npts}포인트 맵 측정합니다."

            examples.append((user_input2, "energy=10",
                {"actions": actions2, "explanation": explanation2, "confirmation_required": True}))

            # XAFS variation (for some elements)
            if random.random() < 0.65:
                user_input3 = f"{ctx} {info['kr']} {edge} XAFS 분석해주세요"
                actions3 = []
                if dE > 2:
                    actions3.append({"fn": "setTargetEnergy", "args": [round(e_edge + 1.5, 1)]})
                    actions3.append({"fn": "runFullAlignment", "args": []})
                actions3.append({"fn": "quickXafs", "args": [el, edge]})
                actions3.append({"fn": "queueStart", "args": []})
                explanation3 = f"{el} {edge}-edge XAFS로 분석합니다."
                examples.append((user_input3, "energy=10",
                    {"actions": actions3, "explanation": explanation3, "confirmation_required": True}))

    return examples


def gen_scan_variation_examples():
    """Generate diverse scan type examples."""
    examples = []

    # LineScan variations
    line_params = [(0,0,10,0), (0,0,10,5), (-5,0,5,0), (0,0,20,0), (0,0,0,10)]
    for x1, y1, x2, y2 in line_params:
        npts = random.choice([21, 41, 51, 101])
        patterns = [
            f"({x1},{y1})에서 ({x2},{y2})까지 {npts}포인트 라인스캔",
            f"라인스캔해줘. ({x1},{y1})에서 ({x2},{y2})까지 {npts}포인트",
            f"({x1},{y1})~({x2},{y2}) {npts}포인트 라인스캔 부탁해",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "quickLineScan", "args": [x1, y1, x2, y2, npts]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"({x1},{y1})에서 ({x2},{y2})까지 {npts}포인트 라인스캔합니다.",
             "confirmation_required": True}))

    # FlyScan variations
    fly_targets = [
        ("m1", "pitch", 1, 4), ("m2", "pitch", 1, 4),
        ("dcm", "theta", 10, 15), ("kbv", "pitch", 1, 4),
    ]
    for motor, axis, start, stop in fly_targets:
        npts = random.choice([21, 51, 101])
        motor_kr = {"m1": "M1 피치", "m2": "M2 피치", "dcm": "DCM 세타", "kbv": "KBV 피치"}[motor]
        patterns = [
            f"{motor_kr} {start}~{stop}에서 {npts}포인트 고속스캔",
            f"{motor_kr}를 {start}부터 {stop}까지 플라이스캔해줘",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "quickFlyScan", "args": [motor, axis, start, stop, npts]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"{motor_kr} {start}-{stop} 고속스캔합니다.",
             "confirmation_required": True}))

    # Fermat variations
    for rx, ry in [(5, 5), (10, 10), (20, 20)]:
        dr = random.choice([0.3, 0.5, 1.0])
        patterns = [
            f"{rx}x{ry} 페르마 나선 스캔해줘",
            f"페르마 스캔 {rx}x{ry} 범위로",
            f"현위치에서 {rx}x{ry} 페르마 스캔 부탁해",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "quickFermat", "args": [rx, ry, dr]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"{rx}x{ry} um 페르마 나선 스캔합니다.",
             "confirmation_required": True}))

    # RelRaster variations
    for dx, dy in [(3, 3), (5, 5), (10, 10)]:
        nx = random.choice([11, 21, 41])
        patterns = [
            f"현위치 기준 {dx}x{dy} 래스터 스캔해줘",
            f"현위치에서 {dx}x{dy} 상대 래스터 {nx}포인트",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "quickRelRaster", "args": [dx, dy, nx, nx]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"현위치 기준 {dx}x{dy} 래스터 스캔합니다.",
             "confirmation_required": True}))

    # RelAlign variations
    for dev, axis in [("m1", "pitch"), ("m2", "pitch"), ("dcm", "theta"), ("kbv", "pitch"), ("kbh", "pitch")]:
        width = random.choice([0.2, 0.5, 1.0])
        npts = random.choice([11, 21])
        dev_kr = {"m1": "M1 피치", "m2": "M2 피치", "dcm": "DCM 세타", "kbv": "KBV 피치", "kbh": "KBH 피치"}[dev]
        patterns = [
            f"{dev_kr} 현위치 기준 +/-{width} 정렬 스캔",
            f"{dev_kr} 상대 정렬 스캔해줘. 범위 {width}",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [{"fn": "quickRelAlign", "args": [dev, axis, width, npts]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"{dev_kr} 상대 정렬 스캔합니다.",
             "confirmation_required": True}))

    return examples


def gen_attenuator_mask_examples():
    """Generate attenuator and mask examples."""
    examples = []

    # Attenuator insert
    materials = ["Carbon", "Al", "Cu", "Mo"]
    thicknesses = [0.1, 0.5, 1.0, 2.0]
    for mat in materials:
        thick = random.choice(thicknesses)
        slot = random.choice([0, 1, 2, 3])
        patterns = [
            f"어테뉴에이터 슬롯{slot}에 {mat} {thick}mm 넣어줘",
            f"어테뉴에이터에 {mat} {thick}mm 삽입해줘",
        ]
        user_input = random.choice(patterns)
        examples.append((user_input, "energy=10",
            {"actions": [
                {"fn": "setAttenFilter", "args": [slot, "material", mat]},
                {"fn": "setAttenFilter", "args": [slot, "thickness", thick]}
            ],
             "explanation": f"슬롯{slot}에 {mat} {thick}mm 삽입합니다.",
             "confirmation_required": True}))

    # Mask variations
    for mask_type, mask_id, mask_kr in [("mmask", "movable mask", "무버블 마스크"), ("fmask", "fixed mask", "고정 마스크")]:
        for h, v in [(0.5, 0.5), (1, 1), (2, 2), (1, 2), (0.5, 1)]:
            patterns = [
                f"{mask_kr} 수평 {h}mm 수직 {v}mm로 설정해줘",
                f"{mask_id} {h}x{v}mm",
            ]
            user_input = random.choice(patterns)
            examples.append((user_input, "energy=10",
                {"actions": [
                    {"fn": "maskAperUpdate", "args": [mask_type, "h", h]},
                    {"fn": "maskAperUpdate", "args": [mask_type, "v", v]}
                ],
                 "explanation": f"{mask_kr} 수평 {h}mm, 수직 {v}mm로 설정합니다.",
                 "confirmation_required": True}))

    return examples


def gen_multi_step_examples():
    """Generate multi-step workflow examples."""
    examples = []

    # Energy + align + scan
    for el in ["Cu", "Fe", "Ni", "Pt", "Au"]:
        info = ELEMENTS[el]
        edge = info["edge"]
        e_edge = info.get("K", info.get("L3"))
        e_xrf = round(e_edge + 1.5, 1)

        patterns = [
            f"{info['kr']} XRF 최적화하고 10x10 41포인트로 측정까지 해줘",
            f"{el} {edge} 최적화 후 맵핑해줘. 10x10 41포인트",
        ]
        user_input = random.choice(patterns)

        actions = [
            {"fn": "optimizeBeamline", "args": [
                {"technique": "xrf", "element": el, "edge": edge,
                 "ppm": 1000, "sampleType": "solid", "priority": "balanced"}
            ]},
            {"fn": "quickRaster", "args": [10, 10, 41]},
            {"fn": "queueStart", "args": []}
        ]
        examples.append((user_input, "energy=10",
            {"actions": actions,
             "explanation": f"{el} XRF 최적화 후 맵 측정합니다.",
             "confirmation_required": True}))

    # Sequential XANES
    seq_pairs = [("Ti", "Sr"), ("Fe", "Ni"), ("Mn", "Co"), ("Cu", "Zn")]
    for el1, el2 in seq_pairs:
        i1 = ELEMENTS[el1]
        i2 = ELEMENTS[el2]
        e1 = i1.get("K", i1.get("L3"))
        e2 = i2.get("K", i2.get("L3"))
        edge1 = i1["edge"]
        edge2 = i2["edge"]

        user_input = f"{i1['kr']} XANES 하고 {i2['kr']} XANES도 해줘"

        actions = [
            {"fn": "quickXanes", "args": [el1, edge1]},
            {"fn": "queueStart", "args": []},
        ]
        if abs(e2 - e1) > 2:
            actions.append({"fn": "setTargetEnergy", "args": [round(e2 + 1.5, 1)]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickXanes", "args": [el2, edge2]})
        actions.append({"fn": "queueStart", "args": []})

        examples.append((user_input, "energy=10",
            {"actions": actions,
             "explanation": f"{el1} XANES 후 {el2} XANES 순차 측정합니다.",
             "confirmation_required": True}))

    return examples


def gen_various_energy_states():
    """Generate examples with different starting energies."""
    examples = []
    start_energies = [5, 7, 8, 12, 15, 20]

    for start_e in start_energies:
        # Fe XANES from different starting energies
        dE = abs(7.112 - start_e)
        actions = []
        if dE > 2:
            actions.append({"fn": "setTargetEnergy", "args": [8.5]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickXanes", "args": ["Fe", "K"]})
        actions.append({"fn": "queueStart", "args": []})

        explanation = "Fe K-edge XANES 스캔을 실행합니다."
        if dE > 2:
            explanation += f" 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."

        examples.append(("철 XANES 측정해줘", f"energy={start_e}",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


def gen_alignment_examples():
    """Generate alignment/calibration examples."""
    examples = []

    # Full alignment
    align_patterns = [
        "전체 정렬 해줘",
        "빔 정렬해주세요",
        "전체 빔라인 정렬 실행해줘",
        "alignment 돌려줘",
        "빔라인 정렬 한번 해줘",
    ]
    for pat in align_patterns:
        examples.append((pat, "energy=10",
            {"actions": [{"fn": "runFullAlignment", "args": []}],
             "explanation": "전체 빔라인 정렬을 수행합니다.",
             "confirmation_required": True}))

    # AutoTune variations
    autotune_patterns = [
        ("KB 미러 오토튠해줘", "kbv"),
        ("KBV 오토튠 해주세요", "kbv"),
        ("KBH 오토튠 해줘", "kbh"),
        ("DCM 오토튠 돌려줘", "dcm"),
        ("M1 오토튠 해주세요", "m1"),
        ("M2 오토튜닝해줘", "m2"),
    ]
    for pat, dev in autotune_patterns:
        examples.append((pat, "energy=10",
            {"actions": [{"fn": "quickAutoTune", "args": [dev]},
                         {"fn": "queueStart", "args": []}],
             "explanation": f"{dev.upper()} 오토튜닝을 수행합니다.",
             "confirmation_required": True}))

    return examples


def gen_queue_control_examples():
    """Generate queue start/stop/status examples."""
    examples = []

    start_patterns = [
        "큐 시작해줘", "실행해줘", "스캔 시작", "큐 실행해주세요", "시작해줘",
    ]
    for pat in start_patterns:
        examples.append((pat, "energy=10",
            {"actions": [{"fn": "queueStart", "args": []}],
             "explanation": "스캔 큐를 시작합니다.",
             "confirmation_required": True}))

    stop_patterns = [
        "큐 정지해줘", "스캔 중지해줘", "정지해줘", "큐 멈춰줘", "스캔 스톱",
    ]
    for pat in stop_patterns:
        examples.append((pat, "energy=10",
            {"actions": [{"fn": "queueStop", "args": []}],
             "explanation": "스캔 큐를 정지합니다.",
             "confirmation_required": True}))

    status_patterns = [
        "큐 상태 알려줘", "현재 상태가 뭐야?", "빔라인 상태 확인해줘",
    ]
    for pat in status_patterns:
        examples.append((pat, "energy=10",
            {"actions": [{"fn": "getStatus", "args": []}],
             "explanation": "현재 빔라인 상태를 확인합니다.",
             "confirmation_required": False}))

    return examples


def gen_mixed_formality_examples():
    """Generate examples with informal/casual Korean styles."""
    examples = []

    # Ultra-casual (banmal)
    casual_pairs = [
        ("철 XANES 해", {"actions": [{"fn": "quickXanes", "args": ["Fe", "K"]},
                                       {"fn": "queueStart", "args": []}],
                          "explanation": "Fe K-edge XANES 스캔을 실행합니다.", "confirmation_required": True}),
        ("에너지 10으로", {"actions": [{"fn": "setTargetEnergy", "args": [10]}],
                          "explanation": "빔 에너지를 10 keV로 설정합니다.", "confirmation_required": True}),
        ("구리 XRF 맵 5x5 21포인트", {"actions": [{"fn": "quickRaster", "args": [5, 5, 21]},
                                                    {"fn": "queueStart", "args": []}],
                                        "explanation": "Cu XRF 5x5 21포인트 맵 측정합니다.", "confirmation_required": True}),
        ("니켈 XAFS 해", {"actions": [{"fn": "quickXafs", "args": ["Ni", "K"]},
                                        {"fn": "queueStart", "args": []}],
                           "explanation": "Ni K-edge XAFS 스캔을 실행합니다.", "confirmation_required": True}),
        ("시료 x 100", {"actions": [{"fn": "motorSetUI", "args": ["sample", "sample_cx", 100]}],
                        "explanation": "시료 X를 100으로 설정합니다.", "confirmation_required": True}),
    ]
    for user_input, output in casual_pairs:
        examples.append((user_input, "energy=10", output))

    # Very polite (존댓말)
    polite_pairs = [
        ("철 K-edge XANES 측정을 실행해 주시겠습니까?",
         {"actions": [{"fn": "quickXanes", "args": ["Fe", "K"]}, {"fn": "queueStart", "args": []}],
          "explanation": "Fe K-edge XANES 스캔을 실행합니다.", "confirmation_required": True}),
        ("에너지를 15 keV로 변경해 주시면 감사하겠습니다",
         {"actions": [{"fn": "setTargetEnergy", "args": [15]}, {"fn": "runFullAlignment", "args": []}],
          "explanation": "빔 에너지를 15 keV로 설정합니다. 에너지 변화 5.0 keV이므로 정렬 수행합니다.",
          "confirmation_required": True}),
    ]
    for user_input, output in polite_pairs:
        examples.append((user_input, "energy=10", output))

    # English-Korean mixed
    mixed_pairs = [
        ("Fe K-edge XANES scan 해줘",
         {"actions": [{"fn": "quickXanes", "args": ["Fe", "K"]}, {"fn": "queueStart", "args": []}],
          "explanation": "Fe K-edge XANES 스캔을 실행합니다.", "confirmation_required": True}),
        ("Cu XRF mapping 10x10 41points로 해줘",
         {"actions": [{"fn": "quickRaster", "args": [10, 10, 41]}, {"fn": "queueStart", "args": []}],
          "explanation": "Cu XRF 10x10 41포인트 맵 측정합니다.", "confirmation_required": True}),
        ("energy 12 keV로 set 해줘",
         {"actions": [{"fn": "setTargetEnergy", "args": [12]}, {"fn": "runFullAlignment", "args": []}],
          "explanation": "빔 에너지를 12 keV로 설정합니다. 에너지 변화 2 keV이므로 정렬 수행합니다.",
          "confirmation_required": True}),
        ("sample stage x를 200으로 move해",
         {"actions": [{"fn": "motorSetUI", "args": ["sample", "sample_cx", 200]}],
          "explanation": "시료 X를 200으로 설정합니다.", "confirmation_required": True}),
    ]
    for user_input, output in mixed_pairs:
        examples.append((user_input, "energy=10", output))

    return examples


def gen_context_variation_examples():
    """Generate examples with different context states (energy, detector, etc.)."""
    examples = []

    # Fe XANES from various starting energies
    for start_e in [5, 7, 8, 9, 12, 15, 18, 20, 25]:
        e_xrf = 8.6
        dE = abs(e_xrf - start_e)
        actions = []
        if dE > 2:
            actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickXanes", "args": ["Fe", "K"]})
        actions.append({"fn": "queueStart", "args": []})
        explanation = "Fe K-edge XANES 스캔을 실행합니다."
        if dE > 2:
            explanation += f" 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."
        examples.append(("철 XANES 해줘", f"energy={start_e}",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    # Cu XANES from various starting energies
    for start_e in [5, 8, 10, 12, 15, 20]:
        e_xrf = 10.5
        dE = abs(e_xrf - start_e)
        actions = []
        if dE > 2:
            actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickXanes", "args": ["Cu", "K"]})
        actions.append({"fn": "queueStart", "args": []})
        explanation = "Cu K-edge XANES 스캔을 실행합니다."
        if dE > 2:
            explanation += f" 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."
        examples.append(("구리 XANES 측정해주세요", f"energy={start_e}",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    # Pt L3 XANES from various
    for start_e in [5, 8, 10, 12, 15]:
        e_xrf = 13.1
        dE = abs(e_xrf - start_e)
        actions = []
        if dE > 2:
            actions.append({"fn": "setTargetEnergy", "args": [e_xrf]})
            actions.append({"fn": "runFullAlignment", "args": []})
        actions.append({"fn": "quickXanes", "args": ["Pt", "L3"]})
        actions.append({"fn": "queueStart", "args": []})
        explanation = "Pt L3-edge XANES 스캔을 실행합니다."
        if dE > 2:
            explanation += f" 에너지 변화 {dE:.1f} keV이므로 정렬 수행합니다."
        examples.append(("백금 L3 XANES 해줘", f"energy={start_e}",
            {"actions": actions, "explanation": explanation, "confirmation_required": True}))

    return examples


# ======================================================================
# Main
# ======================================================================
def generate_all():
    """Generate all augmented training data."""
    all_examples = list(TRAINING_DATA)  # Start with base 78
    log.info(f"Base examples: {len(all_examples)}")

    generators = [
        ("XANES", gen_xanes_examples),
        ("XAFS", gen_xafs_examples),
        ("XRF Map", gen_xrf_map_examples),
        ("Motor", gen_motor_examples),
        ("Energy", gen_energy_examples),
        ("Optimize", gen_optimize_examples),
        ("Signal", gen_signal_examples),
        ("Info", gen_info_examples),
        ("Out-of-range", gen_out_of_range_examples),
        ("Domain", gen_domain_examples),
        ("Scan variations", gen_scan_variation_examples),
        ("Attenuator/Mask", gen_attenuator_mask_examples),
        ("Multi-step", gen_multi_step_examples),
        ("Energy states", gen_various_energy_states),
        ("Alignment", gen_alignment_examples),
        ("Queue control", gen_queue_control_examples),
        ("Mixed formality", gen_mixed_formality_examples),
        ("Context variation", gen_context_variation_examples),
    ]

    for name, gen_fn in generators:
        new_examples = gen_fn()
        all_examples.extend(new_examples)
        log.info(f"  + {name}: {len(new_examples)} examples")

    log.info(f"Total: {len(all_examples)} examples")
    return all_examples


def write_jsonl(examples, output_path):
    """Write examples to JSONL in Qwen3 chat format."""
    records = []
    for user_input, context_str, ideal_output in examples:
        user_msg = user_input
        if context_str:
            user_msg = f"[State: {context_str}] {user_input}"

        record = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_LORA},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": json.dumps(ideal_output, ensure_ascii=False)}
            ]
        }
        records.append(record)

    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return len(records)


def show_stats(examples):
    """Show dataset statistics."""
    cats = {}
    for user_input, _, output in examples:
        has_actions = len(output.get("actions", [])) > 0
        if not has_actions:
            cat = "info/reject"
        else:
            fns = [a["fn"] for a in output["actions"]]
            if "quickXafs" in fns or "quickXanes" in fns:
                cat = "spectroscopy"
            elif "quickRaster" in fns:
                cat = "mapping"
            elif "quickLineScan" in fns or "quickFlyScan" in fns or "quickFermat" in fns:
                cat = "scan_other"
            elif "quickRelAlign" in fns or "quickRelRaster" in fns or "quickAutoTune" in fns:
                cat = "alignment_scan"
            elif "optimizeBeamline" in fns:
                cat = "optimize"
            elif "estimateSignal" in fns:
                cat = "signal_est"
            elif "motorSetUI" in fns:
                cat = "motor"
            elif "setTargetEnergy" in fns and len(fns) <= 2:
                cat = "energy"
            elif "maskAperUpdate" in fns:
                cat = "mask"
            elif "setAttenFilter" in fns:
                cat = "attenuator"
            else:
                cat = "other"
        cats[cat] = cats.get(cat, 0) + 1

    log.info("Category distribution:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        pct = count / len(examples) * 100
        bar = "#" * int(pct / 2)
        log.info(f"  {cat:20s} {count:4d} ({pct:5.1f}%) {bar}")


def load_test_inputs(test_py_path):
    """Load test input strings from test_nlp_qwen3.py."""
    import re
    with open(test_py_path, "r", encoding="utf-8") as f:
        content = f.read()
    matches = re.findall(r'"input":\s*"([^"]+)"', content)
    return set(matches)


def split_train_test(examples, test_inputs):
    """Remove examples whose user_input exactly matches a test input."""
    train = []
    removed = 0
    for user_input, ctx, output in examples:
        if user_input in test_inputs:
            removed += 1
        else:
            train.append((user_input, ctx, output))
    log.info(f"  Removed {removed} examples that match test inputs")
    log.info(f"  Training set: {len(train)} examples")
    return train


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--no-split", action="store_true", help="Skip train/test split")
    args = parser.parse_args()

    examples = generate_all()
    show_stats(examples)

    if not args.stats:
        # Train/test split: remove examples that exactly match test inputs
        if not args.no_split:
            test_py = os.path.join(os.path.dirname(__file__), "test_nlp_qwen3.py")
            if os.path.exists(test_py):
                test_inputs = load_test_inputs(test_py)
                log.info(f"Train/test split: {len(test_inputs)} test inputs found")
                train_examples = split_train_test(examples, test_inputs)
            else:
                log.warning("test_nlp_qwen3.py not found, skipping split")
                train_examples = examples
        else:
            train_examples = examples

        out_path = os.path.join(os.path.dirname(__file__), "training_data_augmented.jsonl")
        n = write_jsonl(train_examples, out_path)
        log.info(f"Written {n} training examples to {out_path}")
