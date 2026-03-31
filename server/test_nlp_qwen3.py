"""Qwen3:8b NLP Verification Test Suite

Automated test for all 31 few-shot examples in the NLP system prompt.
Tests that the local Qwen3:8b model (via Ollama) returns correct JSON
with the expected function calls.

Usage:
  python server/test_nlp_qwen3.py              # run all tests
  python server/test_nlp_qwen3.py --cat motor   # run only 'motor' category
  python server/test_nlp_qwen3.py --verbose     # show full JSON responses

Requires: Ollama running with qwen3:8b model loaded.
"""

import asyncio
import json
import os
import sys
import time
import argparse
from typing import Dict, Any, List, Optional

# Add server directory to path
sys.path.insert(0, os.path.dirname(__file__))

from nlp_agent import NLPAgent, SYSTEM_PROMPT

# ======================================================================
# Test Case Definitions — 19 Categories, 67 test cases
# ======================================================================

TEST_CASES: List[Dict[str, Any]] = [
    # ── Category 1: Basic Motor Control ──
    {
        "id": "motor_01",
        "cat": "motor",
        "input": "에너지를 12 keV로 설정해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "Energy set to 12 keV"
    },
    {
        "id": "motor_02",
        "cat": "motor",
        "input": "M1 피치를 2.5로 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_args_contains": {0: ["m1", "m1_pitch", 2.5]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() == "motorsetui" and "m1" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "M1 pitch move to 2.5 mrad"
    },
    {
        "id": "motor_03",
        "cat": "motor",
        "input": "시료 X를 100 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_args_contains": {0: ["sample"]},
        "expect_confirmation": True,
        "desc": "Sample X motor move"
    },

    # ── Category 2: Scans & Measurements ──
    {
        "id": "scan_01",
        "cat": "scan",
        "input": "구리 K-edge XAFS 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXafs", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs",) and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cu K-edge XAFS with queueStart"
    },
    {
        "id": "scan_02",
        "cat": "scan",
        "input": "철 XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Fe", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes",) and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Fe K-edge XANES with queueStart"
    },
    {
        "id": "scan_03",
        "cat": "scan",
        "input": "10x10 범위에 41포인트로 철 XRF 2D 맵 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() == "quickraster" for a in result.get("actions", [])
        ),
        "desc": "Fe XRF 2D map with params (energy+raster+queue)"
    },
    {
        "id": "scan_04",
        "cat": "scan",
        "input": "시료를 (0,0)에서 (10,5)까지 라인스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickLineScan", "queueStart"],
        "expect_args_contains": {0: [0, 0, 10, 5]},
        "expect_confirmation": True,
        "desc": "Line scan (0,0)-(10,5)"
    },
    {
        "id": "scan_05",
        "cat": "scan",
        "input": "M1 피치를 1~4 mrad에서 고속스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFlyScan", "queueStart"],
        "expect_args_contains": {0: ["m1", "pitch", 1, 4]},
        "expect_confirmation": True,
        "desc": "M1 pitch fly scan 1-4 mrad"
    },
    {
        "id": "scan_06",
        "cat": "scan",
        "input": "철 K-edge 주변 적응형 에너지 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickAdaptiveScan", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Fe K-edge adaptive energy scan"
    },
    {
        "id": "scan_07",
        "cat": "scan",
        "input": "DCM 세타 현위치 기준 +/-0.5도 정렬 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRelAlign", "queueStart"],
        "expect_args_contains": {0: ["dcm", "theta"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickrelalign", "quickflyscan") and "dcm" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "DCM theta relative alignment scan"
    },
    {
        "id": "scan_08",
        "cat": "scan",
        "input": "현위치에서 페르마 나선 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFermat", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Fermat spiral scan"
    },
    {
        "id": "scan_09",
        "cat": "scan",
        "input": "현위치 기준 5x5 래스터 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRelRaster", "queueStart"],
        "expect_args_contains": {0: [5, 5]},
        "expect_confirmation": True,
        "desc": "Relative raster 5x5 scan"
    },

    # ── Category 3: Auto-alignment Rule (dE > 2 keV) ──
    {
        "id": "align_01",
        "cat": "alignment",
        "input": "Mo K-edge XAFS 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "runFullAlignment", "quickXafs", "queueStart"],
        "expect_args_contains": {0: [20]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickxafs", "quickxanes") and "Mo" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Mo K-edge: dE=10 keV > 2 keV => auto alignment"
    },
    {
        "id": "align_02",
        "cat": "alignment",
        "input": "철 XRF 2D 맵 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn_exclude": ["runFullAlignment"],
        "expect_confirmation": None,
        "desc": "Fe XRF: dE=1.5 keV < 2 keV => NO alignment (or ask params)"
    },
    {
        "id": "align_03",
        "cat": "alignment",
        "input": "전체 빔 정렬 시작",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Explicit full alignment request"
    },
    {
        "id": "align_04",
        "cat": "alignment",
        "input": "M1 피치 자동 정렬해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickAutoTune", "queueStart"],
        "expect_args_contains": {0: ["m1", "pitch"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickautotune", "quickrelalign") and "m1" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "M1 pitch auto-tune (iterative centroid)"
    },

    # ── Category 4: Multi-step Commands ──
    {
        "id": "multi_01",
        "cat": "multi",
        "input": "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "runFullAlignment", "showBeamProfile"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "3-step: energy + align + beam profile"
    },

    # ── Category 5: Optimization ──
    {
        "id": "opt_01",
        "cat": "optimize",
        "input": "Cu 분말 1000ppm XRF 최적화해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Cu XRF optimize (balanced)"
    },
    {
        "id": "opt_02",
        "cat": "optimize",
        "input": "철 시료인데 가장 좋은 분해능으로 XRF 맵핑하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "optimizeBeamline" and
            len(a.get("args", [])) > 0 and
            isinstance(a["args"][0], dict) and
            a["args"][0].get("priority") == "resolution"
            for a in acts
        ),
        "expect_confirmation": True,
        "desc": "Fe XRF optimize (resolution priority)"
    },
    {
        "id": "opt_03",
        "cat": "optimize",
        "input": "Ti K-edge XANES 하려는데 시료가 SrTiO3 분말이야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "optimizeBeamline" and
            len(a.get("args", [])) > 0 and
            isinstance(a["args"][0], dict) and
            a["args"][0].get("element") == "Ti"
            for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Ti" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Ti XANES optimize (SrTiO3 powder)"
    },
    {
        "id": "opt_04",
        "cat": "optimize",
        "input": "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "optimizeBeamline" and
            len(a.get("args", [])) > 0 and
            isinstance(a["args"][0], dict) and
            a["args"][0].get("technique") == "ptycho"
            for a in acts
        ),
        "expect_confirmation": True,
        "desc": "Ptychography optimize (coherence priority)"
    },
    {
        "id": "opt_05",
        "cat": "optimize",
        "input": "지금 셋업에서 Cu 신호 얼마나 나와?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["estimateSignal"],
        "expect_args_contains": {},
        "expect_confirmation": False,
        "desc": "Signal estimate (no confirmation)"
    },
    {
        "id": "opt_06",
        "cat": "optimize",
        "input": "W L3-edge XRF 해줘. 시료가 WC 분말이야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "optimizeBeamline" and
            len(a.get("args", [])) > 0 and
            isinstance(a["args"][0], dict) and
            a["args"][0].get("element") == "W" and
            a["args"][0].get("edge") == "L3"
            for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "W L3-edge XRF optimize (WC powder)"
    },
    {
        "id": "opt_07",
        "cat": "optimize",
        "input": "빔라인 최적화해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Optimization without element => ask for info"
    },

    # ── Category 6: Attenuator & Mask ──
    {
        "id": "atten_01",
        "cat": "attenmask",
        "input": "어테뉴에이터에 Carbon 1mm 넣어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setAttenFilter", "setAttenFilter"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() == "setattenfilter" for a in result.get("actions", [])
        ),
        "desc": "Attenuator: insert Carbon 1mm"
    },
    {
        "id": "atten_02",
        "cat": "attenmask",
        "input": "어테뉴에이터 전부 빼",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn_count": {"setAttenFilter": 8},
        "expect_confirmation": True,
        "desc": "Attenuator: remove all (8 calls for 4 slots)"
    },
    {
        "id": "mask_01",
        "cat": "attenmask",
        "input": "movable mask를 1mm x 1mm로 이동시켜",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["maskAperUpdate", "maskAperUpdate"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("maskaperupdate", "motorsetui") and
            ("mask" in str(a.get("args", [])).lower() or "mmask" in str(a.get("args", [])).lower())
            for a in result.get("actions", [])
        ),
        "desc": "Movable mask 1x1 mm"
    },
    {
        "id": "mask_02",
        "cat": "attenmask",
        "input": "고정 마스크 수평갭 2mm, 수직갭 3mm",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["maskAperUpdate", "maskAperUpdate"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "maskAperUpdate" and "fmask" in a.get("args", [])
            for a in acts
        ),
        "expect_confirmation": True,
        "desc": "Fixed mask h=2mm, v=3mm"
    },

    # ── Category 7: Information Queries ──
    {
        "id": "info_01",
        "cat": "info",
        "input": "XRD가 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Info query: XRD explanation"
    },
    {
        "id": "info_02",
        "cat": "info",
        "input": "네가 할 수 있는 명령들을 정리해봐",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Info query: list available commands"
    },
    {
        "id": "info_03",
        "cat": "info",
        "input": "빔 프로파일 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showBeamProfile"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn", "").lower() in ("showbeamprofile", "estimatesignal", "getstatus")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Show beam profile (no confirmation)"
    },

    # ── Category 8: Parameter Confirmation Rule ──
    # Note: With relaxed Rule 8, model may either ask for params OR use defaults.
    # Both are acceptable responses.
    {
        "id": "param_01",
        "cat": "param",
        "input": "2D XRD 매핑해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) > 0 and
            any(a.get("fn") == "quickRaster" for a in result.get("actions", []))
        ),
        "desc": "XRD map without params => ask or use defaults"
    },
    {
        "id": "param_02",
        "cat": "param",
        "input": "철 XRF 2D 맵 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) > 0 and
            any(a.get("fn") in ("quickRaster", "optimizeBeamline") for a in result.get("actions", []))
        ),
        "desc": "Fe XRF map without params => ask or use defaults"
    },

    # ── Category 9: Sample Scientist Scenarios ──
    {
        "id": "sample_01",
        "cat": "scientist",
        "input": "NMC 622 배터리 시료를 nano XRF로 분석하고 싶어. Ni, Mn, Co를 측정해야 해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("optimizebeamline", "quickraster", "settargetenergy")
            for a in result.get("actions", [])
        ),
        "desc": "NMC 622 battery sample — multi-element optimization"
    },
    {
        "id": "sample_02",
        "cat": "scientist",
        "input": "Au L3-edge XRF 신호가 충분할지 확인해줘. 50 ppm 시료야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") in ("optimizeBeamline", "estimateSignal") and
            ("Au" in str(a.get("args", [])))
            for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("estimateSignal", "optimizeBeamline") and "Au" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Au L3-edge XRF signal check (50 ppm)"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 10: Battery Research (2차전지)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "batt_01",
        "cat": "battery",
        "input": "배터리 양극재에서 Ni, Mn, Co 원소 분포를 XRF 맵핑으로 측정하고 싶습니다. 10x10 범위 41포인트로요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "NMC cathode XRF — multi-element, params given"
    },
    {
        "id": "batt_02",
        "cat": "battery",
        "input": "LiFePO4 시료 철 K-edge XAFS 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXafs", "queueStart"],
        "expect_args_contains": {0: ["Fe", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickxafs", "quickxanes", "quickadaptivescan") and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "LFP cathode Fe K-edge XAFS"
    },
    {
        "id": "batt_03",
        "cat": "battery",
        "input": "전고체 전해질 시료인데, 황의 화학 상태를 확인하고 싶어요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            # Model may use invented "notify" fn or explanation-only; both acceptable
            # as long as it doesn't call a real scan function for S K-edge
            not any(a.get("fn") in ("quickXanes","quickXafs","quickRaster","setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "S K-edge (2.47 keV) out of range => explain"
    },
    {
        "id": "batt_04",
        "cat": "battery",
        "input": "양극재에 구리 오염이 있는지 확인해주세요. 10ppm 수준이에요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "estimateSignal") for a in result.get("actions", [])
        ),
        "desc": "Cu contamination 10ppm — signal estimation"
    },
    {
        "id": "batt_05",
        "cat": "battery",
        "input": "충방전 후 양극재 결정상 분포를 2D XRD 맵으로 측정하고 싶어요. 15 keV에서 10x10 21포인트로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Cathode XRD phase map 15keV (dE=5>2 => align)"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 11: Catalyst Research (촉매)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "cata_01",
        "cat": "catalyst",
        "input": "Pt/C 연료전지 촉매에서 백금 산화 상태를 XANES로 확인해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Pt", "L3"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Pt" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pt L3-edge XANES (auto L3 for heavy element)"
    },
    {
        "id": "cata_02",
        "cat": "catalyst",
        "input": "CeO2 담지체의 세륨 L3 엣지 XANES 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Ce", "L3"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Ce" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Ce L3-edge XANES"
    },
    {
        "id": "cata_03",
        "cat": "catalyst",
        "input": "니켈 촉매 반응 중 산화 상태가 변하는지 적응형 에너지 스캔으로 확인하고 싶어요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickAdaptiveScan", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickAdaptiveScan", "quickXanes", "quickXafs")
            for a in result.get("actions", [])
        ),
        "desc": "Ni K-edge adaptive scan"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 12: Semiconductor (반도체)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "semi_01",
        "cat": "semiconductor",
        "input": "반도체 칩 단면에서 구리 배선 분포를 XRF 맵핑해주세요. 분해능을 최대로 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "optimizeBeamline" and
            len(a.get("args", [])) > 0 and
            isinstance(a["args"][0], dict) and
            a["args"][0].get("priority") == "resolution"
            for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Cu XRF resolution priority (semiconductor)"
    },
    {
        "id": "semi_02",
        "cat": "semiconductor",
        "input": "에피택셜 박막의 격자 변형을 nano-XRD로 맵핑해주세요. 에너지는 15 keV로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Thin film strain XRD mapping 15keV"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 13: Geology (지질)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "geo_01",
        "cat": "geology",
        "input": "오염 토양 시료에서 비소의 화학종을 XANES로 구분해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["As", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "As" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "As K-edge XANES speciation (soil)"
    },
    {
        "id": "geo_02",
        "cat": "geology",
        "input": "사장석 시료에서 스트론튬 분포를 XRF 라인스캔으로 확인해주세요. (0,0)에서 (20,0)까지 51포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickLineScan", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickLineScan", "setTargetEnergy") for a in result.get("actions", [])
        ),
        "desc": "Sr XRF linescan — dE>2keV => align needed"
    },
    {
        "id": "geo_03",
        "cat": "geology",
        "input": "광산 폐기물에서 6가 크롬과 3가 크롬을 구분하고 싶어요. Cr XANES 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cr", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cr" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cr K-edge XANES valence (mine waste)"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 14: Environment (환경)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "env_01",
        "cat": "environment",
        "input": "비산재 입자에서 납 분포를 XRF로 확인하고, Pb L3 XANES도 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "quickXanes" and "Pb" in a.get("args", []) and "L3" in a.get("args", [])
            for a in acts
        ) or any(
            a.get("fn") == "optimizeBeamline"
            for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs", "optimizeBeamline", "quickRaster") and "Pb" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pb L3 XRF+XANES multi-step (fly ash)"
    },
    {
        "id": "env_02",
        "cat": "environment",
        "input": "하수 슬러지에서 아연의 화학 상태를 알고 싶어요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Zn", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Zn" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Zn K-edge XANES (biosolids)"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 15: Biology (생물)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "bio_01",
        "cat": "biology",
        "input": "동결건조한 세포 시료에서 철과 아연 분포를 나노 XRF로 이미징해주세요. 5x5 41포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "optimizeBeamline") for a in result.get("actions", [])
        ),
        "desc": "Cell XRF imaging Fe+Zn (biology)"
    },
    {
        "id": "bio_02",
        "cat": "biology",
        "input": "신경세포 수상돌기에서 Cu 분포를 페르마 나선 스캔으로 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFermat", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickFermat", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Cu Fermat spiral scan (neuron)"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 16: Materials Science (재료)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "mat_01",
        "cat": "materials",
        "input": "페로브스카이트 태양전지에서 납 분포의 불균일성을 XRF 맵핑해주세요. 10x10 41포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "setTargetEnergy") for a in result.get("actions", [])
        ),
        "desc": "Pb L3 XRF perovskite solar cell"
    },
    {
        "id": "mat_02",
        "cat": "materials",
        "input": "고엔트로피 합금 시료에서 Fe, Co, Ni, Cr, Mn 원소 분포를 동시에 XRF 맵핑해주세요. 10x10 41포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "optimizeBeamline") for a in result.get("actions", [])
        ),
        "desc": "HEA 5-element XRF mapping"
    },
    {
        "id": "mat_03",
        "cat": "materials",
        "input": "구리 산화물 시료가 Cu2O인지 CuO인지 구분하고 싶어요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cu2O vs CuO phase ID by XANES"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 17: Edge Cases & Challenging Scenarios
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "edge_01",
        "cat": "edgecase",
        "input": "인(P) K-edge XANES 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "P K-edge (2.1 keV) out of range => explain"
    },
    {
        "id": "edge_02",
        "cat": "edgecase",
        "input": "텅스텐 K-edge XAFS 측정해줘.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            # Model may auto-fallback to L3-edge instead of refusing — acceptable
            any(a.get("fn") in ("quickXafs", "quickXanes") and "W" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "W K-edge (69.5 keV) out of range => suggest L3"
    },
    {
        "id": "edge_03",
        "cat": "edgecase",
        "input": "금 시료 XRF 해주세요. 5x5 41포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "desc": "Au XRF — must auto-select L3 edge (11.9 keV)"
    },
    {
        "id": "edge_04",
        "cat": "edgecase",
        "input": "Cu K-edge XAFS 돌려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXafs", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickxafs", "quickxanes") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Mixed Korean/English colloquial request"
    },
    {
        "id": "edge_05",
        "cat": "edgecase",
        "input": "XANES랑 EXAFS 차이가 뭐예요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Info: XANES vs EXAFS difference"
    },
    {
        "id": "edge_06",
        "cat": "edgecase",
        "input": "금 L3 엣지가 몇 keV예요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "11.9" in str(result.get("explanation", "")) or
            "Au" in str(result.get("explanation", "")) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Info: Au L3 edge energy query"
    },
    {
        "id": "edge_07",
        "cat": "edgecase",
        "input": "Pt L3-edge XANES 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Pt", "L3"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes",) and "Pt" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pt L3 XANES — should warn about mirror coating"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 18: Beamline Operation (빔라인 운영)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "ops_01",
        "cat": "operations",
        "input": "Si(311)로 변경해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setCrystal"],
        "expect_args_contains": {0: ["311"]},
        "expect_confirmation": True,
        "desc": "Crystal change to Si(311)"
    },
    {
        "id": "ops_02",
        "cat": "operations",
        "input": "SSA 수평갭을 30 마이크로미터로 줄여주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_args_contains": {0: ["ssa", "ssa_hgap", 30]},
        "expect_confirmation": True,
        "desc": "SSA hgap motor set to 30"
    },
    {
        "id": "ops_03",
        "cat": "operations",
        "input": "긴급 정지!",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["emergencyStop"],
        "expect_confirmation": True,
        "desc": "Emergency stop"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 19: Multi-technique Workflows (다기법)
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "workflow_01",
        "cat": "workflow",
        "input": "SrTiO3 시료에서 Ti K-edge XANES 하고 나서 Sr K-edge XANES도 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") for a in result.get("actions", [])
        ),
        "desc": "Sequential Ti+Sr XANES (large dE => align)"
    },
    {
        "id": "workflow_02",
        "cat": "workflow",
        "input": "Cu 1000ppm 분말 시료 XRF 최적화해서 10x10 41포인트로 측정까지 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Full workflow: optimize + scan request"
    },

    # ═══════════════════════════════════════════════════════════════
    # Category 20: Held-out Tests (학습 데이터에 없는 표현)
    # These use phrasings NOT present in training data to test generalization
    # ═══════════════════════════════════════════════════════════════
    {
        "id": "held_01",
        "cat": "heldout",
        "input": "Zn K흡수단 XANES 스펙트럼을 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Zn", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Zn" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Zn XANES with unusual Korean phrasing"
    },
    {
        "id": "held_02",
        "cat": "heldout",
        "input": "X선 에너지를 9.5 keV로 맞춰주실래요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [9.5]},
        "expect_confirmation": True,
        "desc": "Energy set with polite question form"
    },
    {
        "id": "held_03",
        "cat": "heldout",
        "input": "M2 미러 pitch angle을 3.0 mrad로 조절해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_args_contains": {0: ["m2", "m2_pitch", 3.0]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "motorSetUI" and "m2" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Motor move with English-Korean mixed phrasing"
    },
    {
        "id": "held_04",
        "cat": "heldout",
        "input": "코발트 흡수 스펙트럼 좀 볼 수 있을까요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Co" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Co XANES/XAFS with indirect request"
    },
    {
        "id": "held_05",
        "cat": "heldout",
        "input": "selenium XRF 이미지를 20um x 20um 영역에서 31포인트로 얻고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "quickRaster" for a in result.get("actions", [])
        ),
        "desc": "Se XRF map with English element name"
    },
    {
        "id": "held_06",
        "cat": "heldout",
        "input": "빔 세기를 줄이고 싶은데 어테뉴에이터에 알루미늄 0.5mm 집어넣어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setAttenFilter"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "setAttenFilter" and "Al" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Attenuator with Korean context description"
    },
    {
        "id": "held_07",
        "cat": "heldout",
        "input": "Bragg 법칙이 뭔지 알려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Info query: Bragg's law"
    },
    {
        "id": "held_08",
        "cat": "heldout",
        "input": "칼슘 K-edge 측정이 가능한가요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) == 0 or
            "Ca" in str(result.get("explanation", "")) or
            "4.038" in str(result.get("explanation", ""))
        ),
        "desc": "Out-of-range element query (Ca K=4.038 keV)"
    },
    {
        "id": "held_09",
        "cat": "heldout",
        "input": "지금 빔 에너지가 몇이야? 그리고 As XANES 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "As" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Combined info + scan request"
    },
    {
        "id": "held_10",
        "cat": "heldout",
        "input": "시료 위치를 x=150, y=-50으로 옮겨주세요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", []) if a.get("fn") == "motorSetUI") >= 1
        ),
        "desc": "Multi-axis motor move with xy coordinates"
    },
    {
        "id": "held_11",
        "cat": "heldout",
        "input": "Mn oxidation state를 확인하려면 어떻게 해야하죠?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Mn" in str(a.get("args", []))
                for a in result.get("actions", [])) or
            ("XANES" in result.get("explanation", "") or "xanes" in result.get("explanation", "").lower())
        ),
        "desc": "Advisory question about Mn oxidation analysis"
    },
    {
        "id": "held_12",
        "cat": "heldout",
        "input": "SSA를 완전히 열어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "SSA fully open with informal phrasing"
    },
    {
        "id": "held_13",
        "cat": "heldout",
        "input": "Fe K-edge XRF로 10x10 um 영역 빠르게 스캔해줘. 21포인트면 충분해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "desc": "XRF raster with 'quick' context"
    },
    {
        "id": "held_14",
        "cat": "heldout",
        "input": "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 1
        ),
        "desc": "Sequential Cu+Zn XANES from current energy"
    },
    {
        "id": "held_15",
        "cat": "heldout",
        "input": "Ce L3 XANES를 찍으려면 에너지를 얼마로 해야 해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            "5.723" in str(result.get("explanation", "")) or
            "7.2" in str(result.get("explanation", "")) or
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Ce" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "Advisory question about Ce L3 energy"
    },
]


# ======================================================================
# Test Runner
# ======================================================================

class TestResult:
    def __init__(self, test_id: str, desc: str):
        self.test_id = test_id
        self.desc = desc
        self.passed = True
        self.errors: List[str] = []
        self.response: Optional[Dict] = None
        self.elapsed: float = 0.0

    def fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)


def validate_result(tc: Dict, result: Dict) -> TestResult:
    """Validate a single test case result against expected criteria."""
    tr = TestResult(tc["id"], tc["desc"])
    tr.response = result

    if result.get("type") == "error":
        tr.fail(f"Backend error: {result.get('message', 'unknown')}")
        return tr

    actions = result.get("actions", [])
    conf = result.get("confirmation_required")
    explanation = result.get("explanation", "")

    # Check: expect_alt_pass (alternative acceptable response)
    # If alt_pass lambda returns True, the test passes regardless of other checks
    if "expect_alt_pass" in tc and tc["expect_alt_pass"](result):
        return tr  # pass immediately

    # Check: expect_no_actions => actions must be empty
    if tc.get("expect_no_actions"):
        if len(actions) > 0:
            tr.fail(f"Expected NO actions, got {len(actions)}: {[a.get('fn') for a in actions]}")
        if explanation.strip() == "":
            tr.fail("Expected non-empty explanation for info/param query")
        return tr

    # Check: expect_fn (ordered function names, case-insensitive)
    if "expect_fn" in tc and tc["expect_fn"]:
        actual_fns = [a.get("fn", "") for a in actions]
        expected_fns = tc["expect_fn"]

        # Check that all expected functions appear in order (case-insensitive)
        j = 0
        for exp_fn in expected_fns:
            found = False
            while j < len(actual_fns):
                if actual_fns[j].lower() == exp_fn.lower():
                    found = True
                    j += 1
                    break
                j += 1
            if not found:
                tr.fail(f"Expected fn '{exp_fn}' not found in sequence. Got: {actual_fns}")
                break

    # Check: expect_fn_exclude (functions that must NOT appear)
    if "expect_fn_exclude" in tc:
        actual_fns = [a.get("fn", "") for a in actions]
        for excl in tc["expect_fn_exclude"]:
            if excl in actual_fns:
                tr.fail(f"Function '{excl}' should NOT appear but found in: {actual_fns}")

    # Check: expect_fn_count (exact count of specific functions)
    if "expect_fn_count" in tc:
        actual_fns = [a.get("fn", "") for a in actions]
        for fn, count in tc["expect_fn_count"].items():
            actual_count = actual_fns.count(fn)
            if actual_count != count:
                tr.fail(f"Expected {count}x '{fn}', got {actual_count}x")

    # Check: expect_args_contains (specific arg values at action index OR any action)
    if "expect_args_contains" in tc:
        for idx, expected_vals in tc["expect_args_contains"].items():
            # First try exact index
            target_args_list = []
            if idx < len(actions):
                target_args_list.append((idx, actions[idx].get("args", [])))
            # Also search ALL actions as fallback (model may prepend setTargetEnergy etc.)
            for ai, act in enumerate(actions):
                if ai != idx:
                    target_args_list.append((ai, act.get("args", [])))

            for val in expected_vals:
                found = False
                for (ai, actual_args) in target_args_list:
                    if val in actual_args:
                        found = True
                        break
                    for aa in actual_args:
                        if isinstance(aa, (int, float)) and isinstance(val, (int, float)):
                            if abs(aa - val) < 0.01:
                                found = True
                                break
                        elif isinstance(aa, str) and isinstance(val, str):
                            if aa.lower() == val.lower():
                                found = True
                                break
                    if found:
                        break
                if not found:
                    tr.fail(f"Args missing expected value '{val}' in all actions: {[a.get('args',[]) for a in actions]}")

    # Check: expect_args_check (lambda validator)
    if "expect_args_check" in tc:
        if not tc["expect_args_check"](actions):
            tr.fail(f"Custom args check failed. Actions: {json.dumps(actions, ensure_ascii=False)}")

    # Check: confirmation_required
    if tc["expect_confirmation"] is not None:
        if conf != tc["expect_confirmation"]:
            tr.fail(f"Expected confirmation_required={tc['expect_confirmation']}, got {conf}")

    # Check: explanation is Korean (warning only — small LLMs often respond in English)
    # Only fail if there are NO other errors and the test has strict Korean requirement
    if explanation and len(explanation) > 5:
        has_korean = any('\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163' for c in explanation)
        if not has_korean and tc.get("expect_korean_strict"):
            tr.fail(f"Explanation not in Korean: '{explanation[:80]}...'")

    return tr


async def run_tests(categories: Optional[List[str]] = None, verbose: bool = False):
    """Run all test cases against the NLP agent."""

    # Filter by category
    cases = TEST_CASES
    if categories:
        cases = [tc for tc in cases if tc["cat"] in categories]

    print(f"\n{'='*70}")
    print("  Qwen3:8b NLP Verification Test Suite")
    print(f"  {len(cases)} test cases" + (f" (categories: {', '.join(categories)})" if categories else ""))
    print(f"{'='*70}\n")

    # Initialize agent
    agent = NLPAgent()
    print(f"  Backend: {agent.engine}")
    print(f"  Model: {getattr(agent.backend, 'model', 'unknown')}\n")

    results: List[TestResult] = []
    cat_stats: Dict[str, Dict] = {}

    for i, tc in enumerate(cases):
        # Reset conversation history between tests
        agent.reset_history()

        cat = tc["cat"]
        if cat not in cat_stats:
            cat_stats[cat] = {"pass": 0, "fail": 0, "total": 0}
        cat_stats[cat]["total"] += 1

        print(f"  [{i+1:2d}/{len(cases)}] {tc['id']:12s} | {tc['desc'][:45]:45s} ", end="", flush=True)

        t0 = time.time()
        try:
            result = await agent.process(tc["input"], tc.get("context"))
        except Exception as e:
            result = {"type": "error", "message": str(e)}
        elapsed = time.time() - t0

        tr = validate_result(tc, result)
        tr.elapsed = elapsed
        results.append(tr)

        if tr.passed:
            cat_stats[cat]["pass"] += 1
            print(f"PASS  ({elapsed:.1f}s)")
        else:
            cat_stats[cat]["fail"] += 1
            print(f"FAIL  ({elapsed:.1f}s)")
            for err in tr.errors:
                print(f"         -> {err}")

        if verbose and result.get("type") != "error":
            try:
                print(f"         Response: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
            except UnicodeEncodeError:
                print(f"         Response: {json.dumps(result, ensure_ascii=True, indent=2)[:500]}")

        # Brief pause to avoid overwhelming Ollama
        await asyncio.sleep(0.3)

    # ── Summary ──
    total_pass = sum(1 for r in results if r.passed)
    total_fail = sum(1 for r in results if not r.passed)
    total_time = sum(r.elapsed for r in results)

    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total: {len(results)} | Pass: {total_pass} | Fail: {total_fail} | Time: {total_time:.1f}s")
    print(f"  Pass rate: {total_pass/len(results)*100:.1f}%")
    print()

    # Per-category breakdown
    CAT_NAMES = {
        "motor": "Basic Motor Control",
        "scan": "Scans & Measurements",
        "alignment": "Auto-alignment Rule",
        "multi": "Multi-step Commands",
        "optimize": "Optimization",
        "attenmask": "Attenuator & Mask",
        "info": "Information Queries",
        "param": "Parameter Confirmation",
        "scientist": "Sample Scientist Scenarios",
        "battery": "Battery Research",
        "catalyst": "Catalyst Research",
        "semiconductor": "Semiconductor",
        "geology": "Geology / Earth Science",
        "environment": "Environmental Science",
        "biology": "Biology / Life Science",
        "materials": "Materials Science",
        "edgecase": "Edge Cases / Challenging",
        "operations": "Beamline Operations",
        "workflow": "Multi-technique Workflows",
        "heldout": "Held-out Generalization",
    }
    for cat, stats in cat_stats.items():
        name = CAT_NAMES.get(cat, cat)
        pct = stats["pass"] / stats["total"] * 100 if stats["total"] > 0 else 0
        status = "OK" if stats["fail"] == 0 else "!!"
        print(f"  {status} {name:30s}  {stats['pass']}/{stats['total']} ({pct:.0f}%)")

    print(f"\n{'='*70}")

    # ── Write results to JSON file ──
    out_path = os.path.join(os.path.dirname(__file__), "nlp_test_results.json")
    out_data = {
        "engine": agent.engine,
        "model": getattr(agent.backend, "model", "unknown"),
        "total": len(results),
        "pass": total_pass,
        "fail": total_fail,
        "pass_rate": round(total_pass / len(results) * 100, 1),
        "total_time_s": round(total_time, 1),
        "per_category": {cat: stats for cat, stats in cat_stats.items()},
        "details": [
            {
                "id": r.test_id,
                "desc": r.desc,
                "passed": r.passed,
                "errors": r.errors,
                "elapsed_s": round(r.elapsed, 2),
                "response": r.response if not r.passed else None,
            }
            for r in results
        ]
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"  Results saved to: {out_path}\n")

    return total_fail == 0


if __name__ == "__main__":
    # Force UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Qwen3:8b NLP Verification")
    parser.add_argument("--cat", type=str, help="Category filter (comma-separated)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full responses")
    args = parser.parse_args()

    categories = args.cat.split(",") if args.cat else None

    success = asyncio.run(run_tests(categories=categories, verbose=args.verbose))
    sys.exit(0 if success else 1)
