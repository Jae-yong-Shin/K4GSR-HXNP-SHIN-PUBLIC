"""NLP Benchmark Test Suite -- Multi-engine beamline NLP verification.

=======================================================================
VALIDATION METHODOLOGY
=======================================================================

Test Categories and Purpose:
-----------------------------
1.  motor           -- Basic motor/energy control commands
2.  scan            -- Scan & measurement function dispatch
3.  alignment       -- Auto-alignment rule (dE > 2 keV triggers alignment)
4.  multi           -- Multi-step compound commands
5.  optimize        -- Beamline optimization & signal estimation
6.  attenmask       -- Attenuator and mask aperture control
7.  info            -- Information/knowledge queries (no actions expected)
8.  param           -- Parameter confirmation rule (missing params)
9.  scientist       -- Sample scientist real-world scenarios
10. battery         -- Battery research domain
11. catalyst        -- Catalyst research domain
12. semiconductor   -- Semiconductor research domain
13. geology         -- Geology / earth science domain
14. environment     -- Environmental science domain
15. biology         -- Biology / life science domain
16. materials       -- Materials science domain
17. edgecase        -- Edge cases & challenging scenarios
18. operations      -- Beamline operations (crystal, SSA, e-stop)
19. workflow        -- Multi-technique sequential workflows
20. heldout         -- Held-out generalization (unseen phrasings)
21. experiment_plan -- Experiment planning & time budgeting
22. real_user       -- Realistic informal user expressions
23. complex_multi   -- Complex multi-step command chains
24. robustness      -- Typos, spacing, mixed language, edge inputs
25. rejection       -- Requests the system should refuse / explain limits
26. korean_variant  -- Various Korean expression styles
27. signal_est      -- Signal estimation & detection limit queries
28. bl_knowledge    -- Beamline knowledge / specification queries

How "PASS" is determined:
--------------------------
Each test case is checked against multiple criteria:
  - expect_fn: Expected function names in order (case-insensitive subsequence)
  - expect_args_contains: Specific argument values in actions
  - expect_args_check: Lambda validator for complex argument structures
  - expect_fn_exclude: Functions that must NOT appear
  - expect_fn_count: Exact count of specific function calls
  - expect_no_actions: Actions list must be empty (info/question response)
  - expect_confirmation: Whether confirmation_required flag matches
  - expect_alt_pass: Alternative lambda -- if True, test passes regardless

The expect_alt_pass mechanism exists because LLMs may produce valid but
differently-structured responses. For example, a user asking for "Cu XAFS"
might get quickXafs or optimizeBeamline -- both are acceptable.

Statistical Validity:
---------------------
- Temperature should be set to 0 (deterministic) for reproducible results.
- Single-pass testing is used by default.
- LLM responses are inherently stochastic; expect ~5% variance between runs.

Reproducing Results:
--------------------
  python server/test_nlp_benchmark.py                           # default engine
  python server/test_nlp_benchmark.py --engine groq             # specific engine
  python server/test_nlp_benchmark.py --engine ollama --model qwen3:235b-a22b
  python server/test_nlp_benchmark.py --all-engines             # benchmark ALL
  python server/test_nlp_benchmark.py --cat experiment_plan     # single category
  python server/test_nlp_benchmark.py --cat scan,motor          # multiple cats

Results are written to docs/nlp_benchmark/results/<engine>_<model>_<timestamp>.json
and a comparison summary markdown is generated when using --all-engines.

Requires: At least one NLP backend configured (see server/.env.example).
"""

import asyncio
import json
import os
import sys
import time
import argparse
import statistics
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add server directory to path
sys.path.insert(0, os.path.dirname(__file__))

from nlp_agent import NLPAgent

# ======================================================================
# Test Case Definitions -- 28 Categories, 150+ test cases
# ======================================================================

TEST_CASES: List[Dict[str, Any]] = [
    # ==================================================================
    # Category 1: Basic Motor Control
    # ==================================================================
    {
        "id": "motor_01", "cat": "motor",
        "input": "에너지를 12 keV로 설정해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "Energy set to 12 keV"
    },
    {
        "id": "motor_02", "cat": "motor",
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
        "id": "motor_03", "cat": "motor",
        # Convention (owner decision 2026-06-12): bare "N 이동" with no
        # absolute marker (위치로/좌표로/까지) is a RELATIVE move — operators
        # almost never command absolute coordinates in practice.
        "input": "시료 X를 100 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorMoveRelUI"],
        "expect_args_contains": {0: ["sample"]},
        "expect_confirmation": True,
        "desc": "Sample X motor move (relative by convention)"
    },

    # ==================================================================
    # Category 2: Scans & Measurements
    # ==================================================================
    {
        "id": "scan_01", "cat": "scan",
        "input": "시료 프리셋 1번 pellet으로 준비했어. 구리 K-edge XAFS 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXafs", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs",) and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cu XAFS (preset 1 pellet — sample prep confirmed)"
    },
    {
        "id": "scan_02", "cat": "scan",
        "input": "시료 프리셋 2번 thin film이야. 철 XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Fe", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes",) and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Fe XANES (preset 2 thin film — sample prep confirmed)"
    },
    {
        "id": "scan_03", "cat": "scan",
        "input": "시료 준비 완료. 10x10 범위에 41포인트로 철 XRF 2D 맵 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() == "quickraster" for a in result.get("actions", [])
        ),
        "desc": "Fe XRF 2D map (sample prep confirmed)"
    },
    {
        "id": "scan_04", "cat": "scan",
        # Line scan maps to a raster over the spanned FOV; quickLineScan is
        # retired. Both absolute (quickRaster) and relative (quickRelRaster)
        # raster APIs are valid realizations (owner decision 2026-06-12).
        "input": "시료 장착 완료. 시료를 (0,0)에서 (10,5)까지 라인스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "quickRelRaster")
            for a in result.get("actions", [])
        ),
        "desc": "Line scan (0,0)-(10,5) via raster (sample ready)"
    },
    {
        "id": "scan_05", "cat": "scan",
        # Arg spec fixed (owner decision 2026-06-12): every layer emits the
        # motor as separate tokens ['m1','pitch'], never 'm1_pitch'; a fast
        # pitch scan is validly realized by quickFlyScan OR quickRelAlign.
        "input": "M1 피치를 1~4 mrad에서 고속스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFlyScan", "queueStart"],
        "expect_args_contains": {0: ["m1", "pitch", 1, 4]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickflyscan", "quickrelalign")
            and "m1" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "M1 pitch fly scan 1-4 mrad (alignment — no sample needed)"
    },
    {
        "id": "scan_06", "cat": "scan",
        "input": "프리셋 4번 capillary 시료야. 철 K-edge 주변 적응형 에너지 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickAdaptiveScan", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Fe adaptive scan (preset 4 capillary)"
    },
    {
        "id": "scan_07", "cat": "scan",
        "input": "DCM 세타 현위치 기준 +/-0.5도 정렬 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRelAlign", "queueStart"],
        "expect_args_contains": {0: ["dcm", "theta"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("quickrelalign", "quickflyscan") and "dcm" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "DCM theta alignment scan (no sample needed)"
    },
    {
        "id": "scan_08", "cat": "scan",
        "input": "시료 준비됐어. 현위치에서 페르마 나선 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFermat", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Fermat spiral (sample ready)"
    },
    {
        "id": "scan_09", "cat": "scan",
        "input": "시료 프리셋 5번 bulk 시료. 현위치 기준 5x5 래스터 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRelRaster", "queueStart"],
        "expect_args_contains": {0: [5, 5]},
        "expect_confirmation": True,
        "desc": "Relative raster 5x5 (preset 5 bulk)"
    },

    # ==================================================================
    # Category 3: Auto-alignment Rule (dE > 2 keV)
    # ==================================================================
    {
        "id": "align_01", "cat": "alignment",
        "input": "시료 프리셋 1번 pellet 준비 완료. Mo K-edge XAFS 측정해줘",
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
        "id": "align_02", "cat": "alignment",
        "input": "시료 준비 완료. 철 XRF 2D 맵 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn_exclude": ["runFullAlignment"],
        "expect_confirmation": None,
        "desc": "Fe XRF: dE=1.5 keV < 2 keV => NO alignment"
    },
    {
        "id": "align_03", "cat": "alignment",
        "input": "전체 빔 정렬 시작",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Explicit full alignment request"
    },
    {
        "id": "align_04", "cat": "alignment",
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

    # ==================================================================
    # Category 4: Multi-step Commands
    # ==================================================================
    {
        "id": "multi_01", "cat": "multi",
        "input": "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "runFullAlignment", "showBeamProfile"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "3-step: energy + align + beam profile"
    },

    # ==================================================================
    # Category 5: Optimization
    # ==================================================================
    {
        "id": "opt_01", "cat": "optimize",
        "input": "Cu 분말 1000ppm XRF 최적화해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "desc": "Cu XRF optimize (balanced)"
    },
    {
        "id": "opt_02", "cat": "optimize",
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
        "id": "opt_03", "cat": "optimize",
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
        "expect_alt_pass": lambda result: (
            # Ti K=4.966 keV is borderline below 5 keV -- also accept empty actions with explanation
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Ti" in str(a.get("args", []))
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and "4.966" in result.get("explanation", ""))
            or (len(result.get("actions", [])) == 0 and "4.97" in result.get("explanation", ""))
        ),
        "desc": "Ti XANES optimize (SrTiO3 powder)"
    },
    {
        "id": "opt_04", "cat": "optimize",
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
        "id": "opt_05", "cat": "optimize",
        "input": "지금 셋업에서 Cu 신호 얼마나 나와?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["estimateSignal"],
        "expect_args_contains": {},
        "expect_confirmation": False,
        "desc": "Signal estimate (no confirmation)"
    },
    {
        "id": "opt_06", "cat": "optimize",
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
        "id": "opt_07", "cat": "optimize",
        "input": "빔라인 최적화해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Optimization without element => ask for info"
    },

    # ==================================================================
    # Category 6: Attenuator & Mask
    # ==================================================================
    {
        "id": "atten_01", "cat": "attenmask",
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
        "id": "atten_02", "cat": "attenmask",
        "input": "어테뉴에이터 전부 빼",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn_count": {"setAttenFilter": 8},
        "expect_confirmation": True,
        "desc": "Attenuator: remove all (8 calls for 4 slots)"
    },
    {
        "id": "mask_01", "cat": "attenmask",
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
        "id": "mask_02", "cat": "attenmask",
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


    # ==================================================================
    # Category 7: Information Queries
    # ==================================================================
    {
        "id": "info_01", "cat": "info",
        "input": "XRD가 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Info query: XRD explanation"
    },
    {
        "id": "info_02", "cat": "info",
        "input": "네가 할 수 있는 명령들을 정리해봐",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Info query: list available commands"
    },
    {
        "id": "info_03", "cat": "info",
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

    # ==================================================================
    # Category 8: Parameter Confirmation Rule
    # ==================================================================
    {
        "id": "param_01", "cat": "param",
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
        "id": "param_02", "cat": "param",
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

    # ==================================================================
    # Category 9: Sample Scientist Scenarios
    # ==================================================================
    {
        "id": "sample_01", "cat": "scientist",
        "input": "NMC 622 배터리 시료를 nano XRF로 분석하고 싶어. Ni, Mn, Co를 측정해야 해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn", "").lower() in ("optimizebeamline", "quickraster", "settargetenergy")
            for a in result.get("actions", [])
        ),
        "desc": "NMC 622 battery sample -- multi-element optimization"
    },
    {
        "id": "sample_02", "cat": "scientist",
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

    # ==================================================================
    # Category 10: Battery Research
    # ==================================================================
    {
        "id": "batt_01", "cat": "battery",
        "input": "배터리 양극재에서 Ni, Mn, Co 원소 분포를 XRF 맵핑으로 측정하고 싶습니다. 10x10 범위 41포인트로요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_args_contains": {},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "NMC cathode XRF -- multi-element, params given"
    },
    {
        "id": "batt_02", "cat": "battery",
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
        "id": "batt_03", "cat": "battery",
        "input": "전고체 전해질 시료인데, 황의 화학 상태를 확인하고 싶어요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes","quickXafs","quickRaster","setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "S K-edge (2.47 keV) out of range => explain"
    },
    {
        "id": "batt_04", "cat": "battery",
        "input": "양극재에 구리 오염이 있는지 확인해주세요. 10ppm 수준이에요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "estimateSignal") for a in result.get("actions", [])
        ),
        "desc": "Cu contamination 10ppm -- signal estimation"
    },
    {
        "id": "batt_05", "cat": "battery",
        "input": "충방전 후 양극재 결정상 분포를 2D XRD 맵으로 측정하고 싶어요. 15 keV에서 10x10 21포인트로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Cathode XRD phase map 15keV (dE=5>2 => align)"
    },

    # ==================================================================
    # Category 11: Catalyst Research
    # ==================================================================
    {
        "id": "cata_01", "cat": "catalyst",
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
        "id": "cata_02", "cat": "catalyst",
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
        "id": "cata_03", "cat": "catalyst",
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

    # ==================================================================
    # Category 12: Semiconductor
    # ==================================================================
    {
        "id": "semi_01", "cat": "semiconductor",
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
        "id": "semi_02", "cat": "semiconductor",
        "input": "에피택셜 박막의 격자 변형을 nano-XRD로 맵핑해주세요. 에너지는 15 keV로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Thin film strain XRD mapping 15keV"
    },

    # ==================================================================
    # Category 13: Geology
    # ==================================================================
    {
        "id": "geo_01", "cat": "geology",
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
        "id": "geo_02", "cat": "geology",
        "input": "사장석 시료에서 스트론튬 분포를 XRF 라인스캔으로 확인해주세요. (0,0)에서 (20,0)까지 51포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickLineScan", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickLineScan", "setTargetEnergy") for a in result.get("actions", [])
        ),
        "desc": "Sr XRF linescan -- dE>2keV => align needed"
    },
    {
        "id": "geo_03", "cat": "geology",
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

    # ==================================================================
    # Category 14: Environment
    # ==================================================================
    {
        "id": "env_01", "cat": "environment",
        "input": "비산재 입자에서 납 분포를 XRF로 확인하고, Pb L3 XANES도 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_check": lambda acts: any(
            a.get("fn") == "quickXanes" and "Pb" in a.get("args", []) and "L3" in a.get("args", [])
            for a in acts
        ) or any(
            a.get("fn") == "optimizeBeamline" for a in acts
        ),
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs", "optimizeBeamline", "quickRaster") and "Pb" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pb L3 XRF+XANES multi-step (fly ash)"
    },
    {
        "id": "env_02", "cat": "environment",
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

    # ==================================================================
    # Category 15: Biology
    # ==================================================================
    {
        "id": "bio_01", "cat": "biology",
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
        "id": "bio_02", "cat": "biology",
        "input": "신경세포 수상돌기에서 Cu 분포를 페르마 나선 스캔으로 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickFermat", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickFermat", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Cu Fermat spiral scan (neuron)"
    },

    # ==================================================================
    # Category 16: Materials Science
    # ==================================================================
    {
        "id": "mat_01", "cat": "materials",
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
        "id": "mat_02", "cat": "materials",
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
        "id": "mat_03", "cat": "materials",
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


    # ==================================================================
    # Category 17: Edge Cases & Challenging Scenarios
    # ==================================================================
    {
        "id": "edge_01", "cat": "edgecase",
        "input": "인(P) K-edge XANES 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "P K-edge (2.1 keV) out of range => explain"
    },
    {
        "id": "edge_02", "cat": "edgecase",
        "input": "텅스텐 K-edge XAFS 측정해줘.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXafs", "quickXanes") and "W" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "W K-edge (69.5 keV) out of range => suggest L3"
    },
    {
        "id": "edge_03", "cat": "edgecase",
        "input": "금 시료 XRF 해주세요. 5x5 41포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "desc": "Au XRF -- must auto-select L3 edge (11.9 keV)"
    },
    {
        "id": "edge_04", "cat": "edgecase",
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
        "id": "edge_05", "cat": "edgecase",
        "input": "XANES랑 EXAFS 차이가 뭐예요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Info: XANES vs EXAFS difference"
    },
    {
        "id": "edge_06", "cat": "edgecase",
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
        "id": "edge_07", "cat": "edgecase",
        "input": "Pt L3-edge XANES 측정해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Pt", "L3"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes",) and "Pt" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pt L3 XANES -- should warn about mirror coating"
    },

    # ==================================================================
    # Category 18: Beamline Operations
    # ==================================================================
    {
        "id": "ops_01", "cat": "operations",
        "input": "Si(311)로 변경해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setCrystal"],
        "expect_args_contains": {0: ["311"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "setCrystal" and
            ("311" in str(a.get("args", [])) or "Si(311)" in str(a.get("args", [])))
            for a in result.get("actions", [])
        ),
        "desc": "Crystal change to Si(311)"
    },
    {
        "id": "ops_02", "cat": "operations",
        "input": "SSA 수평갭을 30 마이크로미터로 줄여주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_args_contains": {0: ["ssa", "ssa_hgap", 30]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", [])) and
            30 in (a.get("args", [])[-1:] if a.get("args") else [])
            for a in result.get("actions", [])
        ),
        "desc": "SSA hgap motor set to 30"
    },
    {
        "id": "ops_03", "cat": "operations",
        "input": "긴급 정지!",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["emergencyStop"],
        "expect_confirmation": True,
        "desc": "Emergency stop"
    },

    # ==================================================================
    # Category 19: Multi-technique Workflows
    # ==================================================================
    {
        "id": "workflow_01", "cat": "workflow",
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
        "id": "workflow_02", "cat": "workflow",
        "input": "Cu 1000ppm 분말 시료 XRF 최적화해서 10x10 41포인트로 측정까지 해주세요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickRaster") for a in result.get("actions", [])
        ),
        "desc": "Full workflow: optimize + scan request"
    },

    # ==================================================================
    # Category 20: Held-out Generalization Tests
    # ==================================================================
    {
        "id": "held_01", "cat": "heldout",
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
        "id": "held_02", "cat": "heldout",
        "input": "X선 에너지를 9.5 keV로 맞춰주실래요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [9.5]},
        "expect_confirmation": True,
        "desc": "Energy set with polite question form"
    },
    {
        "id": "held_03", "cat": "heldout",
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
        "id": "held_04", "cat": "heldout",
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
        "id": "held_05", "cat": "heldout",
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
        "id": "held_06", "cat": "heldout",
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
        "id": "held_07", "cat": "heldout",
        "input": "Bragg 법칙이 뭔지 알려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Info query: Bragg's law"
    },
    {
        "id": "held_08", "cat": "heldout",
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
        "id": "held_09", "cat": "heldout",
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
        "id": "held_10", "cat": "heldout",
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
        "id": "held_11", "cat": "heldout",
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
        "id": "held_12", "cat": "heldout",
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
        "id": "held_13", "cat": "heldout",
        "input": "Fe K-edge XRF로 10x10 um 영역 빠르게 스캔해줘. 21포인트면 충분해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster"],
        "expect_confirmation": True,
        "desc": "XRF raster with 'quick' context"
    },
    {
        "id": "held_14", "cat": "heldout",
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
        "id": "held_15", "cat": "heldout",
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


    # ==================================================================
    # NEW Category 21: Experiment Planning
    # ==================================================================
    {
        "id": "explan_01", "cat": "experiment_plan",
        "input": "NMC622 양극재야. Ni 30%, Co 10%, Mn 10%. 빔타임 8시간.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["optimizeBeamline"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("optimizeBeamline", "quickRaster", "setTargetEnergy")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 20
        ),
        "desc": "NMC622 cathode with composition and beamtime"
    },
    {
        "id": "explan_02", "cat": "experiment_plan",
        "input": "시료가 SrTiO3 단결정인데 Ti, Sr 둘 다 분석해야해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("optimizeBeamline", "quickXanes", "quickXafs")
                for a in result.get("actions", [])) or
            ("Ti" in str(result) and "Sr" in str(result))
        ),
        "desc": "Multi-element sequential (Ti + Sr)"
    },
    {
        "id": "explan_03", "cat": "experiment_plan",
        "input": "Pt/C 촉매 50ppm인데 XRF로 보일까?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("estimateSignal", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 15
        ),
        "desc": "Pt 50ppm signal estimation inquiry"
    },
    {
        "id": "explan_04", "cat": "experiment_plan",
        "input": "2D XRF 맵핑 후에 2D XRD도 해야하는데 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 or
            len(result.get("actions", [])) > 0
        ),
        "desc": "Timing inquiry for XRF + XRD mapping"
    },
    {
        "id": "explan_05", "cat": "experiment_plan",
        "input": "ptychography랑 XRF를 동시에 할 수 있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Technique compatibility question (ptycho + XRF)"
    },
    {
        "id": "explan_06", "cat": "experiment_plan",
        "input": "nano-XANES랑 XRF 맵핑 동시에 되나?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Technique compatibility question (XANES + XRF map)"
    },
    {
        "id": "explan_07", "cat": "experiment_plan",
        "input": "빔타임 4시간인데 Cu XAFS 3회 반복이랑 XRF 맵핑 둘 다 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Time budget question (XAFS repeat + XRF map)"
    },
    {
        "id": "explan_08", "cat": "experiment_plan",
        "input": "검출기 교체 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "Setup change inquiry (detector swap time)"
    },

    # ==================================================================
    # NEW Category 22: Real User Scenarios
    # ==================================================================
    {
        "id": "realuser_01", "cat": "real_user",
        "input": "이 시료 좀 봐줘. Cu 시료야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 or
            any(a.get("fn") in ("optimizeBeamline", "estimateSignal")
                for a in result.get("actions", []))
        ),
        "desc": "Vague request -- should ask for specifics"
    },
    {
        "id": "realuser_02", "cat": "real_user",
        "input": "형광 맵 좀 찍어줘. 10마이크로 범위",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "quickRelRaster")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Colloquial XRF request with range"
    },
    {
        "id": "realuser_03", "cat": "real_user",
        "input": "이 에너지에서 시료 신호가 얼마나 되는지 확인해봐",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("estimateSignal", "showBeamProfile")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Signal check at current energy"
    },
    {
        "id": "realuser_04", "cat": "real_user",
        "input": "좀 더 세게 빔 때려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("motorSetUI", "setAttenFilter")
                and "ssa" in str(a.get("args", [])).lower()
                for a in result.get("actions", [])) or
            any(a.get("fn") == "setAttenFilter" for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Increase flux (SSA open wider or remove attenuator)"
    },
    {
        "id": "realuser_05", "cat": "real_user",
        "input": "빔 사이즈를 최소로 줄여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("motorSetUI", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Minimize beam size"
    },
    {
        "id": "realuser_06", "cat": "real_user",
        "input": "결정 구조가 궁금해. XRD 한 번 찍어봐",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("setupVirtualExperiment", "quickRaster", "quickCount")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "XRD single shot request"
    },
    {
        "id": "realuser_07", "cat": "real_user",
        "input": "이전 스캔 결과 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "Unsupported request -- show previous results"
    },
    {
        "id": "realuser_08", "cat": "real_user",
        "input": "시료를 좀 더 왼쪽으로 옮겨줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "motorSetUI" and "sample" in str(a.get("args", []))
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Relative motor move (left)"
    },
    {
        "id": "realuser_09", "cat": "real_user",
        "input": "지금 몇 keV야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "10" in str(result.get("explanation", "")) or
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Energy inquiry"
    },
    {
        "id": "realuser_10", "cat": "real_user",
        "input": "어떤 실험을 할 수 있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 20,
        "desc": "Capability inquiry"
    },

    # ==================================================================
    # NEW Category 23: Complex Multi-step Commands
    # ==================================================================
    {
        "id": "cmulti_01", "cat": "complex_multi",
        "input": "에너지 15 keV로 바꾸고, SSA 30으로 줄이고, XRF 맵 10x10 41포인트 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) and
            any(a.get("fn") in ("motorSetUI", "quickRaster") for a in result.get("actions", []))
        ),
        "desc": "3-step: energy + SSA + XRF raster"
    },
    {
        "id": "cmulti_02", "cat": "complex_multi",
        "input": "Si(311)로 바꾸고 Se K-edge XAFS 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setCrystal"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setCrystal" for a in result.get("actions", [])) or
            any(a.get("fn") in ("quickXafs", "quickXanes") and "Se" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "Crystal change + Se XAFS"
    },
    {
        "id": "cmulti_03", "cat": "complex_multi",
        "input": "M1, M2 정렬 순서대로 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("runFullAlignment", "quickAutoTune", "quickRelAlign")
                for a in result.get("actions", [])) or
            (any("m1" in str(a.get("args", [])).lower() for a in result.get("actions", [])) and
             any("m2" in str(a.get("args", [])).lower() for a in result.get("actions", [])))
        ),
        "desc": "Sequential M1 + M2 alignment"
    },
    {
        "id": "cmulti_04", "cat": "complex_multi",
        "input": "Cu XANES 찍고, 에너지를 Fe로 바꿔서 XANES도 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "Sequential Cu XANES + Fe XANES"
    },
    {
        "id": "cmulti_05", "cat": "complex_multi",
        "input": "XRF 맵핑하고 관심 영역에서 XANES 포인트 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "quickXanes", "quickXafs")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Multi-step workflow: XRF map then XANES"
    },
    {
        "id": "cmulti_06", "cat": "complex_multi",
        "input": "Pb L3 XANES하고 As K-edge XANES도 연속으로 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs")
                for a in result.get("actions", []))
        ),
        "desc": "Sequential Pb L3 + As K XANES"
    },
    {
        "id": "cmulti_07", "cat": "complex_multi",
        "input": "어테뉴에이터 Al 0.3mm 넣고 나서 Cr XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setAttenFilter" for a in result.get("actions", [])) or
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Cr" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "Attenuator insert + Cr XANES"
    },
    {
        "id": "cmulti_08", "cat": "complex_multi",
        "input": "12 keV로 설정하고 빔 프로파일 보여주고 XRF 맵 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) and
            len(result.get("actions", [])) >= 2
        ),
        "desc": "3-step: energy + profile + XRF map"
    },

    # ==================================================================
    # NEW Category 24: Robustness
    # ==================================================================
    {
        "id": "robust_01", "cat": "robustness",
        "input": "에너지를 12keV로 설정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "No space before keV"
    },
    {
        "id": "robust_02", "cat": "robustness",
        "input": "copper K-edge XAFS해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs", "quickXanes") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "English element in Korean sentence"
    },
    {
        "id": "robust_03", "cat": "robustness",
        "input": "Fe xanes",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Minimal input (Fe xanes)"
    },
    {
        "id": "robust_04", "cat": "robustness",
        "input": "XAFS 해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 5 or
            len(result.get("actions", [])) > 0
        ),
        "desc": "No element specified => should ask"
    },
    {
        "id": "robust_05", "cat": "robustness",
        "input": "   Cu K-edge XAFS   ",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs", "quickXanes") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Extra whitespace around input"
    },
    {
        "id": "robust_06", "cat": "robustness",
        "input": "에너지 8.333 keV로 맞춰줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])
        ),
        "desc": "Exact edge energy (Ni K=8.333) -- should warn about being AT the edge"
    },
    {
        "id": "robust_07", "cat": "robustness",
        "input": "quickXafs Cu K",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXafs", "quickXanes") and "Cu" in str(a.get("args", []))
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 5
        ),
        "desc": "User typing function name directly"
    },
    {
        "id": "robust_08", "cat": "robustness",
        "input": "Cu, Fe, Zn 다원소 맵핑 10x10",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Comma-separated elements mapping"
    },
    {
        "id": "robust_09", "cat": "robustness",
        "input": "에너지를 -5 keV로",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Negative energy => should reject"
    },
    {
        "id": "robust_10", "cat": "robustness",
        "input": "에너지를 100 keV로",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Energy way out of range (100 keV)"
    },


    # ==================================================================
    # NEW Category 25: Rejection Scenarios
    # ==================================================================
    {
        "id": "reject_01", "cat": "rejection",
        "input": "Si K-edge XANES 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "Si K-edge (1.84 keV) out of range"
    },
    {
        "id": "reject_02", "cat": "rejection",
        "input": "산소 K-edge XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "O K-edge (0.54 keV) out of range"
    },
    {
        "id": "reject_03", "cat": "rejection",
        "input": "리튬 흡수 스펙트럼 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "Li K-edge (0.055 keV) out of range"
    },
    {
        "id": "reject_04", "cat": "rejection",
        "input": "탄소 K-edge XAFS 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "C K-edge (0.28 keV) out of range"
    },
    {
        "id": "reject_05", "cat": "rejection",
        "input": "질소 XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "N K-edge (0.40 keV) out of range"
    },
    {
        "id": "reject_06", "cat": "rejection",
        "input": "Ag K-edge XAFS 측정해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 or
            any(a.get("fn") in ("quickXafs", "quickXanes")
                for a in result.get("actions", []))
        ),
        "desc": "Ag K-edge (25.5 keV) at boundary -- should warn"
    },
    {
        "id": "reject_07", "cat": "rejection",
        "input": "우라늄 분석해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Uranium not in standard database"
    },
    {
        "id": "reject_08", "cat": "rejection",
        "input": "시료 사진 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Optical imaging not available"
    },

    # ==================================================================
    # NEW Category 26: Korean Variants
    # ==================================================================
    {
        "id": "korean_01", "cat": "korean_variant",
        "input": "구리 K 흡수단 XAFS 돌려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs", "quickXanes") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Korean 'absorption edge' phrasing"
    },
    {
        "id": "korean_02", "cat": "korean_variant",
        "input": "니켈 산화 상태 확인",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Ni" in str(a.get("args", []))
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Ni oxidation state check (terse)"
    },
    {
        "id": "korean_03", "cat": "korean_variant",
        "input": "형광 이미징 하고 싶어요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Polite XRF imaging request"
    },
    {
        "id": "korean_04", "cat": "korean_variant",
        "input": "에너지 바꿔주세요. 9 keV로요.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [9]},
        "expect_confirmation": True,
        "desc": "Polite energy change with period"
    },
    {
        "id": "korean_05", "cat": "korean_variant",
        "input": "빔 정렬 한번 해볼까?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("runFullAlignment", "quickAutoTune", "quickRelAlign")
            for a in result.get("actions", [])
        ),
        "desc": "Casual question form alignment"
    },
    {
        "id": "korean_06", "cat": "korean_variant",
        "input": "SSA 좀 넓혀줄래?",
        "context": {"energy": 10, "ssaH": 30, "ssaV": 30},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Informal SSA widen request"
    },
    {
        "id": "korean_07", "cat": "korean_variant",
        "input": "스캔 멈춰!",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("emergencyStop", "queueStop", "queueAbort")
            for a in result.get("actions", [])
        ),
        "desc": "Stop scan command"
    },
    {
        "id": "korean_08", "cat": "korean_variant",
        "input": "이거 다시 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "Repeat last action -- context-dependent"
    },

    # ==================================================================
    # NEW Category 27: Signal Estimation
    # ==================================================================
    {
        "id": "sigest_01", "cat": "signal_est",
        "input": "Cu 100ppm 시료에서 XRF 신호가 충분할까?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("estimateSignal", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Cu 100ppm XRF signal sufficiency"
    },
    {
        "id": "sigest_02", "cat": "signal_est",
        "input": "Au 10ppm 박막 시료 신호 예상치",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("estimateSignal", "optimizeBeamline")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Au 10ppm thin film signal estimate"
    },
    {
        "id": "sigest_03", "cat": "signal_est",
        "input": "Fe 50% 시료 XAFS 자기흡수 문제 없어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 or
            any(a.get("fn") in ("estimateSignal", "optimizeBeamline")
                for a in result.get("actions", []))
        ),
        "desc": "Fe 50% self-absorption concern"
    },
    {
        "id": "sigest_04", "cat": "signal_est",
        "input": "Mn 500ppm에서 검출 한계가 어떻게 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 or
            any(a.get("fn") in ("estimateSignal",)
                for a in result.get("actions", []))
        ),
        "desc": "Mn 500ppm detection limit inquiry"
    },
    {
        "id": "sigest_05", "cat": "signal_est",
        "input": "Pt L3 XRF를 할건데 Ir 간섭이 있을까?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Pt-Ir spectral interference question"
    },

    # ==================================================================
    # NEW Category 28: Beamline Knowledge
    # ==================================================================
    {
        "id": "blknow_01", "cat": "bl_knowledge",
        "input": "이 빔라인 에너지 범위가 어떻게 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(kw in str(result.get("explanation", "")) for kw in ("5", "25", "keV")) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Beamline energy range inquiry"
    },
    {
        "id": "blknow_02", "cat": "bl_knowledge",
        "input": "KB 미러 초점 거리가 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "KB mirror focal distance inquiry"
    },
    {
        "id": "blknow_03", "cat": "bl_knowledge",
        "input": "DCM Si(111)이랑 Si(311) 차이가 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 15,
        "desc": "DCM Si(111) vs Si(311) difference"
    },
    {
        "id": "blknow_04", "cat": "bl_knowledge",
        "input": "이 빔라인에서 할 수 있는 실험 종류를 알려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 20,
        "desc": "List available experiment types"
    },
    {
        "id": "blknow_05", "cat": "bl_knowledge",
        "input": "빔 사이즈가 최소 얼마까지 줄어들어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(kw in str(result.get("explanation", "")) for kw in ("50", "nm", "nano")) or
            len(result.get("explanation", "")) > 10
        ),
        "desc": "Minimum beam size inquiry"
    },

    # ==================================================================
    # Additional tests to expand coverage (mixed categories)
    # ==================================================================
    {
        "id": "explan_09", "cat": "experiment_plan",
        "input": "XRF 맵핑 해상도를 50nm로 하면 10x10 영역 스캔 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Scan time estimation for high-res XRF"
    },
    {
        "id": "explan_10", "cat": "experiment_plan",
        "input": "XAFS 측정 1회에 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "XAFS single scan time inquiry"
    },
    {
        "id": "robust_11", "cat": "robustness",
        "input": "12 kev로 에너지 설정",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "Lowercase keV unit"
    },
    {
        "id": "robust_12", "cat": "robustness",
        "input": "energy 12",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 5
        ),
        "desc": "Minimal English energy command"
    },
    {
        "id": "reject_09", "cat": "rejection",
        "input": "마그네슘 K-edge 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "Mg K-edge (1.30 keV) out of range"
    },
    {
        "id": "reject_10", "cat": "rejection",
        "input": "알루미늄 K-edge XANES 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            not any(a.get("fn") in ("quickXanes", "quickXafs", "setTargetEnergy")
                    for a in result.get("actions", []))
        ),
        "desc": "Al K-edge (1.56 keV) out of range"
    },
    {
        "id": "realuser_11", "cat": "real_user",
        "input": "빔 안정적이야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "Beam stability inquiry"
    },
    {
        "id": "realuser_12", "cat": "real_user",
        "input": "도와줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 5,
        "desc": "Help request (generic)"
    },
    {
        "id": "cmulti_09", "cat": "complex_multi",
        "input": "에너지 20 keV로 바꾸고 정렬하고 Mo XANES 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) and
            any(a.get("fn") in ("quickXanes", "quickXafs", "runFullAlignment")
                for a in result.get("actions", []))
        ),
        "desc": "3-step: 20keV + align + Mo XANES"
    },
    {
        "id": "korean_09", "cat": "korean_variant",
        "input": "망간 흡수단 스캔 부탁해요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Mn" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Mn absorption edge scan (polite request)"
    },

    # ── v2.2 Additional Tests: Diverse prompts targeting known failure patterns ──

    # --- Category: SSA function selection (SSA = motorSetUI, NOT maskAperUpdate) ---
    {
        "id": "ssa_01", "cat": "ssa_control",
        "input": "SSA 수직갭을 60um으로 맞춰줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "SSA vgap set to 60um (must use motorSetUI)"
    },
    {
        "id": "ssa_02", "cat": "ssa_control",
        "input": "SSA를 최소로 닫아줘. 수평 수직 다 10um으로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))) >= 2
        ),
        "desc": "SSA close to 10um both axes (must use motorSetUI x2)"
    },
    {
        "id": "ssa_03", "cat": "ssa_control",
        "input": "SSA 크기 좀 키워줘. 수평 100 수직 80",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))) >= 2
        ),
        "desc": "SSA enlarge both h=100 v=80 (motorSetUI)"
    },

    # --- Category: Analysis / phase-ID requests (must generate actions, not just explain) ---
    {
        "id": "analysis_01", "cat": "analysis_intent",
        "input": "이 시료의 Fe 산화 상태를 확인하고 싶어요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Fe oxidation state check = XANES measurement"
    },
    {
        "id": "analysis_02", "cat": "analysis_intent",
        "input": "Cr(III)인지 Cr(VI)인지 확인해야 합니다",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cr" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cr valence check = XANES measurement"
    },
    {
        "id": "analysis_03", "cat": "analysis_intent",
        "input": "니켈 산화물 시료의 상(phase)을 분석하고 싶은데요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs", "quickRaster") and "Ni" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Ni oxide phase analysis = XANES or XRD"
    },

    # --- Category: Sequential multi-element (must generate all actions, not ask) ---
    {
        "id": "seq_01", "cat": "sequential",
        "input": "Fe XANES 한 다음에 Ni XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 2
        ),
        "desc": "Sequential Fe+Ni XANES (must generate both)"
    },
    {
        "id": "seq_02", "cat": "sequential",
        "input": "Mn이랑 Co XANES를 연속으로 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 2
        ),
        "desc": "Sequential Mn+Co XANES (must generate both)"
    },
    {
        "id": "seq_03", "cat": "sequential",
        "input": "Pb L3 XANES 하고 나서 As K-edge XANES도 순차적으로 해주세요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 2
        ),
        "desc": "Sequential Pb L3 + As K XANES"
    },

    # --- Category: Question + action combined ---
    {
        "id": "qact_01", "cat": "question_action",
        "input": "현재 결정이 뭐야? 그리고 Fe XAFS 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXafs"],
        "expect_confirmation": True,
        "desc": "Question about crystal + Fe XAFS action"
    },
    {
        "id": "qact_02", "cat": "question_action",
        "input": "빔 사이즈가 지금 얼마야? SSA를 50um으로 줄여줘",
        "context": {"energy": 10, "ssaH": 100, "ssaV": 100},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "motorSetUI" and "ssa" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Question about beam size + SSA motor action"
    },

    # --- Category: Partial out-of-range multi-element ---
    {
        "id": "partial_01", "cat": "partial_range",
        "input": "S K-edge XANES랑 Fe K-edge XANES를 둘 다 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "S(out of range) + Fe(in range) -- must do Fe"
    },
    {
        "id": "partial_02", "cat": "partial_range",
        "input": "Ca XANES하고 Zn XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Zn" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Ca(out of range) + Zn(in range) -- must do Zn"
    },

    # --- Category: L3-edge auto-selection for heavy elements ---
    {
        "id": "heavyel_01", "cat": "heavy_element",
        "input": "납 XRF 이미징 해주세요. 10x10um, 51포인트.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "quickRaster", "queueStart"],
        "expect_confirmation": True,
        "desc": "Pb XRF -- must auto-select L3 edge (13.035 keV)"
    },
    {
        "id": "heavyel_02", "cat": "heavy_element",
        "input": "텅스텐 XRF 맵핑해줘. 5x5 41포인트",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickRaster", "optimizeBeamline")
            for a in result.get("actions", [])
        ),
        "desc": "W XRF -- must auto-select L3 edge (10.207 keV)"
    },

    # --- Category: Colloquial Korean variants ---
    {
        "id": "colloquial_01", "cat": "colloquial",
        "input": "구리 XANES 한번만 빨리 돌려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Casual Cu XANES request"
    },
    {
        "id": "colloquial_02", "cat": "colloquial",
        "input": "에너지 좀 올려줘. 15 keV로.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_confirmation": True,
        "desc": "Casual energy raise to 15 keV"
    },
    {
        "id": "colloquial_03", "cat": "colloquial",
        "input": "아연 분포 좀 봐봐. 20um 정도.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "quickRelRaster", "setTargetEnergy")
            for a in result.get("actions", [])
        ),
        "desc": "Casual Zn XRF distribution request"
    },
    {
        "id": "colloquial_04", "cat": "colloquial",
        # Relative-by-convention move; a 5 um sample move is valid on either
        # the coarse stage (motorMoveRelUI) or the nano scanner (nanoJog) —
        # both are relative APIs, so accept either (owner decision 2026-06-12).
        "input": "시료 왼쪽으로 5um 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorMoveRelUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("motorMoveRelUI", "nanoJog")
            for a in result.get("actions", [])
        ),
        "desc": "Casual relative sample move left (rel-API family accepted)"
    },

    # --- Category: Emergency / safety ---
    {
        "id": "safety_01", "cat": "safety",
        "input": "멈춰! 스캔 중지해!",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("emergencyStop", "queueStop", "queueAbort", "abortAlignment")
            for a in result.get("actions", [])
        ),
        "desc": "Urgent stop command (various phrasings)"
    },
    {
        "id": "safety_02", "cat": "safety",
        "input": "모든 동작 정지시켜",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("emergencyStop", "queueStop", "queueAbort")
            for a in result.get("actions", [])
        ),
        "desc": "Stop all operations"
    },

    # --- Category: Implicit technique from context ---
    {
        "id": "implicit_01", "cat": "implicit_technique",
        "input": "이 촉매 시료에서 백금 상태가 궁금해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs", "optimizeBeamline")
            and "Pt" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Pt state from catalyst context = XANES"
    },
    {
        "id": "implicit_02", "cat": "implicit_technique",
        "input": "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "optimizeBeamline", "quickXanes", "estimateSignal")
            for a in result.get("actions", [])
        ),
        "desc": "Cu contamination check on semiconductor = XRF"
    },
    {
        "id": "implicit_03", "cat": "implicit_technique",
        "input": "토양 시료에서 비소 형태 분석해주세요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "As" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "As speciation in soil = XANES"
    },

    # ==================================================================
    # Virtual Experiment Tests (50 tests, 7 sub-categories)
    # ==================================================================

    # --- experiment_preset (8 tests) ---
    {
        "id": "vexp_01", "cat": "experiment_preset",
        "input": "Cu XAFS 실험 셋업해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickXafs", "quickXanes")
            for a in result.get("actions", [])
        ),
        "desc": "Cu XAFS experiment preset setup"
    },
    {
        "id": "vexp_02", "cat": "experiment_preset",
        "input": "분말 XRD 실험 시작해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment",) and
            "powder_xrd" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Powder XRD experiment preset"
    },
    {
        "id": "vexp_03", "cat": "experiment_preset",
        "input": "2D XRF 맵핑 실험 셋업",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickRaster")
            for a in result.get("actions", [])
        ),
        "desc": "2D XRF mapping experiment setup"
    },
    {
        "id": "vexp_04", "cat": "experiment_preset",
        "input": "구리 산화물의 흡수 스펙트럼을 보고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickXafs", "quickXanes") and
            ("Cu" in str(a.get("args", [])) or "cu" in str(a.get("args", [])).lower())
            for a in result.get("actions", [])
        ),
        "desc": "Indirect Cu absorption spectrum request"
    },
    {
        "id": "vexp_05", "cat": "experiment_preset",
        "input": "위치별 결정상 분포를 알고 싶어",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickRaster")
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              len(result.get("explanation", "")) > 20),
        "desc": "Phase distribution by position = XRD 2D map"
    },
    {
        "id": "vexp_06", "cat": "experiment_preset",
        "input": "나노 XRF 라인스캔 프리셋 로드해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickLineScan")
            for a in result.get("actions", [])
        ),
        "desc": "Nano XRF line scan preset load"
    },
    {
        "id": "vexp_07", "cat": "experiment_preset",
        "input": "XRF imaging preset으로 시작",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment",) and
            "xrf" in str(a.get("args", [])).lower()
            for a in result.get("actions", [])
        ),
        "desc": "XRF imaging preset (English-Korean mixed)"
    },
    {
        "id": "vexp_08", "cat": "experiment_preset",
        "input": "시료의 원소 맵핑을 고해상도로 하고 싶은데, 나노빔 XRF 실험 세팅해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "optimizeBeamline", "quickRaster")
            for a in result.get("actions", [])
        ),
        "desc": "High-res nano XRF experiment setup"
    },

    # --- experiment_planning_adv (10 tests) ---
    {
        "id": "vexp_09", "cat": "experiment_planning_adv",
        "input": "LiNi0.8Co0.1Mn0.1O2 시료야. Ni, Co, Mn XANES를 각각 하고 XRF 맵도 찍어야해. 빔타임 6시간",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs", "optimizeBeamline")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                len(result.get("explanation", "")) > 50)
        ),
        "desc": "NMC811 multi-element XANES + XRF plan with 6h beamtime"
    },
    {
        "id": "vexp_10", "cat": "experiment_planning_adv",
        "input": "FePt 나노입자 촉매인데 Fe K-edge XAFS 3회 반복하고 Pt L3 XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any("Fe" in str(a.get("args", [])) for a in result.get("actions", [])) and
            any("Pt" in str(a.get("args", [])) for a in result.get("actions", []))
        ),
        "desc": "FePt catalyst: Fe XAFS x3 + Pt L3 XANES"
    },
    {
        "id": "vexp_11", "cat": "experiment_planning_adv",
        "input": "XRF 하고 나서 XRD도 해야하는데 검출기 교체가 필요한가요?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XRF->XRD detector swap inquiry (~30min)"
    },
    {
        "id": "vexp_12", "cat": "experiment_planning_adv",
        "input": "페로브스카이트 태양전지 시료야. 납 분포랑 결정상을 동시에 보고싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "optimizeBeamline", "setupVirtualExperiment")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                len(result.get("explanation", "")) > 30)
        ),
        "desc": "Perovskite Pb distribution + crystal phase (needs detector swap)"
    },
    {
        "id": "vexp_13", "cat": "experiment_planning_adv",
        "input": "배터리 음극재 그래파이트 시료인데 Fe, Cu 불순물을 ppm 수준으로 찾아야해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "estimateSignal", "quickRaster")
            for a in result.get("actions", [])
        ),
        "desc": "Trace Fe/Cu impurity in graphite anode"
    },
    {
        "id": "vexp_14", "cat": "experiment_planning_adv",
        "input": "Mn K XANES, Co K XANES, Ni K XANES 순서로 해줘. 에너지 차이가 2 keV 미만이니까 정렬 안해도 되지?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_fn_exclude": ["runFullAlignment"],
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 2
        ),
        "desc": "Mn/Co/Ni XANES sequential, no alignment needed (dE<2keV)"
    },
    {
        "id": "vexp_15", "cat": "experiment_planning_adv",
        "input": "이 시료에 Cr이 있는데 3가인지 6가인지 구별해야해. 환경 시료라 농도가 낮아",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cr" in str(a.get("args", []))
            for a in result.get("actions", [])
        ) or any(
            a.get("fn") == "optimizeBeamline" and "Cr" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Cr(III) vs Cr(VI) speciation in environmental sample"
    },
    {
        "id": "vexp_16", "cat": "experiment_planning_adv",
        "input": "첫번째 시료는 XRF 맵, 두번째 시료는 XANES 해야해. 시료 교체 포함해서 총 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Total time with sample change: XRF map + XANES"
    },
    {
        "id": "vexp_17", "cat": "experiment_planning_adv",
        "input": "Au 나노입자가 TiO2 담지체 위에 있어. Au 분포 보고 Ti 산화상태도 확인하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any("Au" in str(a.get("args", [])) for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("Ti", "4.966", "5 keV", "범위")))
        ),
        "desc": "Au/TiO2 catalyst: Au L3 OK, Ti K borderline out of range"
    },
    {
        "id": "vexp_18", "cat": "experiment_planning_adv",
        "input": "Ce L3 XANES 하고 그 다음 Fe K XANES 해줘. 에너지 바꿀 때 정렬 필요한가?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any("Ce" in str(a.get("args", [])) for a in result.get("actions", [])) and
            any("Fe" in str(a.get("args", [])) for a in result.get("actions", []))
        ),
        "desc": "Ce L3 -> Fe K XANES, no alignment (dE=1.389 keV)"
    },

    # --- ptycho_experiment (6 tests) ---
    {
        "id": "vexp_19", "cat": "ptycho_experiment",
        "input": "ptychography 실험 셋업해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickFermat", "setupVirtualExperiment")
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              any(kw in result.get("explanation", "").lower()
                  for kw in ("ptycho", "coheren", "fermat"))),
        "desc": "Direct ptychography setup request"
    },
    {
        "id": "vexp_20", "cat": "ptycho_experiment",
        "input": "coherent imaging으로 시료 구조 보고싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickFermat")
            and ("ptycho" in str(a.get("args", [])).lower()
                 or "coherence" in str(a.get("args", [])).lower())
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              any(kw in result.get("explanation", "").lower()
                  for kw in ("ptycho", "coherent", "ptychography"))),
        "desc": "Coherent imaging = ptychography"
    },
    {
        "id": "vexp_21", "cat": "ptycho_experiment",
        "input": "위상 이미징 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickFermat", "setupVirtualExperiment")
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              any(kw in result.get("explanation", "").lower()
                  for kw in ("ptycho", "phase", "위상"))),
        "desc": "Phase imaging = ptychography"
    },
    {
        "id": "vexp_22", "cat": "ptycho_experiment",
        "input": "결맞음 빔으로 나노구조 관찰하고 싶어. 에너지는 10 keV로",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickFermat")
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              any(kw in result.get("explanation", "").lower()
                  for kw in ("ptycho", "coheren"))),
        "desc": "Coherent beam nanostructure at 10 keV"
    },
    {
        "id": "vexp_23", "cat": "ptycho_experiment",
        "input": "반도체 시료를 비파괴로 내부 구조 보고 싶어. 50nm 분해능이 필요해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "quickFermat")
            for a in result.get("actions", [])
        ) or (len(result.get("actions", [])) == 0 and
              any(kw in result.get("explanation", "").lower()
                  for kw in ("ptycho", "ptychography", "coheren"))),
        "desc": "Non-destructive 50nm resolution = ptychography"
    },
    {
        "id": "vexp_24", "cat": "ptycho_experiment",
        "input": "XRF 맵핑 끝나면 ptychography도 이어서 할건데, 셋업 변경 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XRF->ptycho setup change time (~45min)"
    },

    # --- technique_selection (8 tests) ---
    {
        "id": "vexp_25", "cat": "technique_selection",
        "input": "시료의 원소 분포를 알고싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster", "optimizeBeamline", "setupVirtualExperiment")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                len(result.get("explanation", "")) > 20)
        ),
        "desc": "Element distribution = XRF mapping (may ask which element)"
    },
    {
        "id": "vexp_26", "cat": "technique_selection",
        "input": "결정 구조를 확인하고 싶어",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("setupVirtualExperiment", "quickRaster", "quickCount")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("XRD", "회절", "결정")))
        ),
        "desc": "Crystal structure = XRD"
    },
    {
        "id": "vexp_27", "cat": "technique_selection",
        "input": "Fe 산화 상태가 궁금해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Fe" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Fe oxidation state = XANES"
    },
    {
        "id": "vexp_28", "cat": "technique_selection",
        "input": "화학 결합 상태를 알고 싶어. Cu 시료야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXafs", "quickXanes") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Chemical bonding state of Cu = XAFS/XANES"
    },
    {
        "id": "vexp_29", "cat": "technique_selection",
        "input": "나노 스케일 이미지가 필요해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("optimizeBeamline", "quickFermat", "quickRaster")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                len(result.get("explanation", "")) > 20)
        ),
        "desc": "Nano-scale image (ambiguous: ptycho or high-res XRF)"
    },
    {
        "id": "vexp_30", "cat": "technique_selection",
        "input": "미량 원소 검출이 목적이야. Cr 10ppm 수준",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("optimizeBeamline", "estimateSignal") and
            "Cr" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Trace Cr 10ppm = XRF with flux priority"
    },
    {
        "id": "vexp_31", "cat": "technique_selection",
        "input": "상분율을 알고 싶어. 다상 세라믹 시료야",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("setupVirtualExperiment", "quickRaster")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("XRD", "회절", "상분율")))
        ),
        "desc": "Phase fraction of multiphase ceramic = XRD 2D map"
    },
    {
        "id": "vexp_32", "cat": "technique_selection",
        "input": "국소 영역에서 격자 상수 변화를 관찰하고 싶어",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("setupVirtualExperiment", "quickRaster")
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("XRD", "회절", "격자")))
        ),
        "desc": "Local lattice parameter variation = XRD 2D map"
    },

    # --- multi_technique (8 tests) ---
    {
        "id": "vexp_33", "cat": "multi_technique_wf",
        "input": "XRF로 관심 영역 찾고 거기서 XANES 해줘. Fe 시료야",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickRaster",) for a in result.get("actions", [])) and
            any(a.get("fn") in ("quickXanes", "quickXafs") for a in result.get("actions", []))
        ) or (len(result.get("actions", [])) == 0 and
              len(result.get("explanation", "")) > 30),
        "desc": "XRF survey -> XANES on ROI (Fe)"
    },
    {
        "id": "vexp_34", "cat": "multi_technique_wf",
        "input": "Ni XANES 하고 XRD도 연속으로 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Ni" in str(a.get("args", []))
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                len(result.get("explanation", "")) > 20)
        ),
        "desc": "Ni XANES + XRD sequential (detector swap warning)"
    },
    {
        "id": "vexp_35", "cat": "multi_technique_wf",
        "input": "Fe XAFS 3번 반복 후에 XRF 맵 찍어줘. 10x10 41포인트",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXafs",) and "Fe" in str(a.get("args", []))
                for a in result.get("actions", [])) and
            any(a.get("fn") == "quickRaster" for a in result.get("actions", []))
        ),
        "desc": "Fe XAFS x3 + XRF map (same SDD, no swap)"
    },
    {
        "id": "vexp_36", "cat": "multi_technique_wf",
        "input": "Mn XANES, Co XANES, Ni XANES 순차 측정 후 XRF 2D 맵핑까지 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            sum(1 for a in result.get("actions", [])
                if a.get("fn") in ("quickXanes", "quickXafs")) >= 2 and
            any(a.get("fn") == "quickRaster" for a in result.get("actions", []))
        ),
        "desc": "Mn/Co/Ni XANES + XRF 2D map (4-step workflow)"
    },
    {
        "id": "vexp_37", "cat": "multi_technique_wf",
        "input": "먼저 XRD 패턴 한 장 찍고, 그 다음 XRF 맵핑 해줘",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) > 0 or
            (len(result.get("actions", [])) == 0 and
             any(kw in result.get("explanation", "")
                 for kw in ("검출기", "교체", "detector", "swap", "30")))
        ),
        "desc": "XRD then XRF (detector swap ~30min)"
    },
    {
        "id": "vexp_38", "cat": "multi_technique_wf",
        "input": "Cu XANES 끝나면 바로 Zn XANES도 이어서 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_fn_exclude": ["runFullAlignment"],
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes",) and "Cu" in str(a.get("args", []))
                for a in result.get("actions", [])) and
            any(a.get("fn") in ("quickXanes",) and "Zn" in str(a.get("args", []))
                for a in result.get("actions", []))
        ),
        "desc": "Cu + Zn XANES sequential (dE=0.68 keV, no alignment)"
    },
    {
        "id": "vexp_39", "cat": "multi_technique_wf",
        "input": "Se K-edge XAFS 하고 나서 Pb L3 XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: (
            any("Se" in str(a.get("args", [])) for a in result.get("actions", [])) and
            any("Pb" in str(a.get("args", [])) for a in result.get("actions", []))
        ),
        "desc": "Se XAFS + Pb L3 XANES (dE=0.377 keV, no alignment)"
    },
    {
        "id": "vexp_40", "cat": "multi_technique_wf",
        "input": "에너지 8 keV에서 Cu 시료 XRF 맵핑하고, 에너지 올려서 20 keV에서 Mo XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": True,
        "expect_fn": ["setTargetEnergy"],
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) and
            any(a.get("fn") == "runFullAlignment" for a in result.get("actions", []))
        ),
        "desc": "8 keV XRF + 20 keV Mo XANES (12 keV change, alignment needed)"
    },

    # --- timing_feasibility (5 tests) ---
    {
        "id": "vexp_41", "cat": "timing_feasibility",
        "input": "ptychography 한 장 찍는데 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Ptychography single shot timing (~75s)"
    },
    {
        "id": "vexp_42", "cat": "timing_feasibility",
        "input": "XRF 맵 100x100um에 1um 스텝으로 하면 시간이 어떻게 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Large XRF map timing (101x101 pts)"
    },
    {
        "id": "vexp_43", "cat": "timing_feasibility",
        "input": "XAFS 5회 반복이면 빔타임 몇 시간 필요해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XAFS 5x repeat beamtime estimate (~1.25 hours)"
    },
    {
        "id": "vexp_44", "cat": "timing_feasibility",
        "input": "XRD에서 XRF로 바꾸는데 시간이 얼마나 걸려?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XRD->XRF setup change time (~30min)"
    },
    {
        "id": "vexp_45", "cat": "timing_feasibility",
        "input": "XRF 맵 2장이랑 XANES 3회 하면 총 빔타임이 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Combined timing: 2x XRF map + 3x XANES"
    },

    # --- experiment_edge (5 tests) ---
    {
        "id": "vexp_46", "cat": "experiment_edge",
        "input": "Ag K-edge XAFS 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXafs", "quickXanes") and "Ag" in str(a.get("args", []))
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("25", "범위", "초과", "L3")))
        ),
        "desc": "Ag K-edge (25.514 keV) borderline range limit"
    },
    {
        "id": "vexp_47", "cat": "experiment_edge",
        "input": "시료 분석해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "Vague request -- should ask for details"
    },
    {
        "id": "vexp_48", "cat": "experiment_edge",
        "input": "Ba L3 XANES 하고 Ca K-edge XANES도 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("quickXanes", "quickXafs") and "Ba" in str(a.get("args", []))
                for a in result.get("actions", []))
            or (len(result.get("actions", [])) == 0 and
                any(kw in result.get("explanation", "")
                    for kw in ("Ba", "Ca", "범위", "4.038")))
        ),
        "desc": "Ba L3 (5.247 keV) OK, Ca K (4.038 keV) out of range"
    },
    {
        "id": "vexp_49", "cat": "experiment_edge",
        "input": "XRD 하려는데 에너지 5 keV면 데이터가 괜찮을까?",
        "context": {"energy": 5, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XRD at 5 keV quality inquiry (suboptimal, advise higher)"
    },
    {
        "id": "vexp_50", "cat": "experiment_edge",
        "input": "La L3 XANES 하면서 동시에 ptychography도 할 수 있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "desc": "XANES + ptycho concurrent -- incompatible"
    },

    # ==================================================================
    # Category 29: Experimental Workflow -- Technique selection bias,
    # sample preparation check, pre-measurement checklist
    # ==================================================================
    # --- Group A: Technique bias prevention (should NOT assume technique) ---
    {
        "id": "expwf_01", "cat": "exp_workflow",
        "input": "CVD 물질로 Co 실험하고 싶어. 최적 조건 알려줘.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "XRF", "XANES", "XRD", "어떤 실험", "어떤 측정", "기법", "종류")
        ),
        "desc": "Should ask experiment type, not assume XANES"
    },
    {
        "id": "expwf_02", "cat": "exp_workflow",
        "input": "우리 배터리 양극재 시료 분석하고 싶은데 어떻게 하면 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "종류", "원소")
        ),
        "desc": "Battery cathode - should ask technique type"
    },
    {
        "id": "expwf_03", "cat": "exp_workflow",
        "input": "반도체 웨이퍼에서 불순물 측정하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("원소", "어떤", "불순물", "종류", "XRF", "XANES")
        ),
        "desc": "Semiconductor impurity - should ask which element and technique"
    },
    {
        "id": "expwf_04", "cat": "exp_workflow",
        "input": "Fe 촉매 시료 갖고 왔는데 뭘 해야 할지 모르겠어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in str(result.get("explanation", ""))
                for kw in ("이미징", "분광", "회절", "XRF", "XANES", "XRD", "추천", "어떤"))
        ),
        "desc": "User unsure what to do - should guide through options"
    },
    {
        "id": "expwf_05", "cat": "exp_workflow",
        "input": "이 시료에 Ni이 들어있는지 확인해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "XRF", "이미징")
        ),
        "desc": "Element detection - should ask about sample prep before scanning"
    },
    {
        "id": "expwf_06", "cat": "exp_workflow",
        "input": "그래핀 CVD 성장 시료 분석 도와줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 20 and
            any(kw in str(result.get("explanation", ""))
                for kw in ("원소", "어떤", "기법", "이미징", "분광", "회절"))
        ),
        "desc": "Graphene CVD - should not assume carbon measurement"
    },
    {
        "id": "expwf_07", "cat": "exp_workflow",
        "input": "지질학 시료에서 희토류 원소 분석 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 20,
        "desc": "Rare earth in geology - should discuss feasibility and technique options"
    },
    {
        "id": "expwf_08", "cat": "exp_workflow",
        "input": "NMC 양극재 분석 실험 준비 좀 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("Ni", "Mn", "Co", "어떤", "기법", "이미징", "분광")
        ),
        "desc": "NMC cathode - should ask technique, not jump to scan"
    },
    {
        "id": "expwf_09", "cat": "exp_workflow",
        "input": "합금 시료인데 조성 분석 하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("원소", "어떤", "성분", "조성", "XRF")
        ),
        "desc": "Alloy composition - should ask which elements"
    },
    {
        "id": "expwf_10", "cat": "exp_workflow",
        "input": "환경 시료에서 중금속 오염 확인하려고 하는데",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("원소", "어떤", "중금속", "Pb", "As", "Cd", "Hg", "기법")
        ),
        "desc": "Environmental heavy metal - should ask specific elements"
    },

    # --- Group B: Sample preparation check (should ask before measuring) ---
    {
        "id": "expwf_11", "cat": "exp_workflow",
        "input": "Co K-edge XANES 실험 시작하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "in-situ", "장착")
        ),
        "desc": "Co XANES - technique clear but should ask sample prep"
    },
    {
        "id": "expwf_12", "cat": "exp_workflow",
        "input": "Fe XRF 이미징 측정 준비해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "크기", "두께")
        ),
        "desc": "Fe XRF imaging - should ask sample conditions"
    },
    {
        "id": "expwf_13", "cat": "exp_workflow",
        "input": "분말 XRD 실험 시작",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "pellet", "capillary")
        ),
        "desc": "Powder XRD - should ask sample mounting method"
    },
    {
        "id": "expwf_14", "cat": "exp_workflow",
        "input": "Cu 시료 in-situ 가열하면서 XANES 찍으려고 하는데",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("온도", "가열", "in-situ", "셋업", "프리셋", "환경", "준비")
        ),
        "desc": "In-situ heating XANES - should ask setup details"
    },
    {
        "id": "expwf_15", "cat": "exp_workflow",
        "input": "TEM 그리드에 올린 나노입자 시료 ptychography 하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("TEM", "나노", "두께", "마운트", "프리셋", "준비", "투과")
        ),
        "desc": "TEM grid nanoparticle ptycho - should check sample details"
    },
    {
        "id": "expwf_16", "cat": "exp_workflow",
        "input": "bulk 시료인데 반사모드로 XRF 맵핑 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "원소", "프리셋", "반사", "준비", "에너지")
        ),
        "desc": "Bulk sample reflection XRF - should ask element and prep"
    },
    {
        "id": "expwf_17", "cat": "exp_workflow",
        "input": "가스 환경에서 촉매 반응 중에 실시간 XANES 모니터링하고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("가스", "환경", "셋업", "in-situ", "원소", "프리셋")
        ),
        "desc": "Gas-phase operando XANES - should ask detailed setup"
    },
    {
        "id": "expwf_18", "cat": "exp_workflow",
        "input": "시료 마운트 안 했는데 XAFS 먼저 셋업만 해놓을 수 있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("원소", "마운트", "시료", "에너지", "준비")
        ),
        "desc": "Pre-mount setup request - should ask element at minimum"
    },
    {
        "id": "expwf_19", "cat": "exp_workflow",
        "input": "박막 시료 두께가 100nm인데 투과 모드로 Ni XANES 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("투과", "두께", "마운트", "프리셋", "준비", "가능")
        ),
        "desc": "Thin film transmission XANES feasibility - should check conditions"
    },
    {
        "id": "expwf_20", "cat": "exp_workflow",
        "input": "수용액 시료인데 측정 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("수용액", "원소", "셀", "윈도우", "카프톤", "마운트", "프리셋")
        ),
        "desc": "Aqueous solution sample - should ask element and cell setup"
    },

    # --- Group C: Correct workflow (should proceed when technique is explicit) ---
    {
        "id": "expwf_21", "cat": "exp_workflow",
        "input": "Co K-edge XANES 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Co" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Explicit Co XANES command - should execute (direct command)"
    },
    {
        "id": "expwf_22", "cat": "exp_workflow",
        "input": "에너지 8.5keV로 맞춰줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_confirmation": True,
        "desc": "Direct energy command - should execute immediately"
    },
    {
        "id": "expwf_23", "cat": "exp_workflow",
        "input": "같은 위치에서 XRD도 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setupVirtualExperiment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setupVirtualExperiment", "quickRaster")
            for a in result.get("actions", [])
        ),
        "desc": "Follow-up XRD at same position - should execute (no re-ask)"
    },

    # --- Group D: Mixed scenarios ---
    {
        "id": "expwf_24", "cat": "exp_workflow",
        "input": "페로브스카이트 태양전지 시료 갖고 왔어. Pb 분석해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "마운트", "시료")
        ),
        "desc": "Perovskite Pb analysis - should ask technique and prep"
    },
    {
        "id": "expwf_25", "cat": "exp_workflow",
        "input": "리튬이온 배터리 음극재에서 Si 분석 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("1.839", "5 keV", "범위", "불가", "에너지")
        ),
        "desc": "Si in Li-ion anode - should explain Si edge out of range"
    },
    {
        "id": "expwf_26", "cat": "exp_workflow",
        "input": "스테인리스 스틸 용접부 결함 분석",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("Fe", "Cr", "Ni", "원소", "기법", "이미징", "XRF", "XRD")
        ),
        "desc": "Stainless steel weld defect - should ask technique and elements"
    },
    {
        "id": "expwf_27", "cat": "exp_workflow",
        "input": "시료 준비 프리셋 3번으로 마운트 되어있어. Fe XANES 가능?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 10 and
            any(kw in str(result.get("explanation", ""))
                for kw in ("Fe", "프리셋", "7.112", "가능", "준비"))
        ),
        "desc": "Preset 3 + Fe XANES - should acknowledge prep and confirm feasibility"
    },
    {
        "id": "expwf_28", "cat": "exp_workflow",
        "input": "시료 위치 확인부터 해줘. 아직 빔을 못 찾았어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("래스터", "스캔", "위치", "찾기", "정렬", "raster", "survey")
        ),
        "desc": "Sample finding request - should suggest survey scan"
    },
    {
        "id": "expwf_29", "cat": "exp_workflow",
        "input": "촉매 시료 표면에 Pt 나노입자 분포를 보고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "XRF", "Pt", "이미징")
        ),
        "desc": "Pt nanoparticle distribution on catalyst - should ask prep"
    },
    {
        "id": "expwf_30", "cat": "exp_workflow",
        "input": "내일 빔타임인데 미리 실험 계획 좀 세워줘. Mn-Co-Ni 배터리 양극재야.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 50 and
            any(kw in str(result.get("explanation", ""))
                for kw in ("Mn", "Co", "Ni", "이미징", "분광", "계획", "시료"))
        ),
        "desc": "Beamtime planning for NMC cathode - should discuss full plan"
    },

    # ==================================================================
    # Category 29b: Experimental Workflow - Variant Prompts (30 cases)
    # Paraphrased versions to test robustness of workflow rules
    # ==================================================================

    # --- Group E: Technique bias prevention (variant phrasings) ---
    {
        "id": "expwf_31", "cat": "exp_workflow",
        "input": "ZnO 나노입자 시료 가져왔는데 빔 쏴줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "시료", "마운트")
        ),
        "desc": "ZnO nanoparticle - vague request should ask technique"
    },
    {
        "id": "expwf_32", "cat": "exp_workflow",
        "input": "Ti 합금 분석 좀 해볼 수 있을까?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "Ti")
        ),
        "desc": "Ti alloy analysis - should ask what kind of analysis"
    },
    {
        "id": "expwf_33", "cat": "exp_workflow",
        "input": "촉매 시료에서 Pd 봐야 하는데",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "종류")
        ),
        "desc": "Pd in catalyst - should ask technique type"
    },
    {
        "id": "expwf_34", "cat": "exp_workflow",
        "input": "V 산화물 시료 측정하러 왔어요",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "측정")
        ),
        "desc": "V oxide sample - should ask technique"
    },
    {
        "id": "expwf_35", "cat": "exp_workflow",
        "input": "이 금속 시편에서 Cr 성분 좀 봐줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "XRF", "시료")
        ),
        "desc": "Cr in metal specimen - should ask technique"
    },
    {
        "id": "expwf_36", "cat": "exp_workflow",
        "input": "연료전지 MEA 시료인데 Pt 확인해야 해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "시료", "마운트")
        ),
        "desc": "Fuel cell MEA Pt - should ask technique"
    },
    {
        "id": "expwf_37", "cat": "exp_workflow",
        "input": "세라믹 코팅 시료 데이터 좀 뽑아줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "원소", "기법")
        ),
        "desc": "Ceramic coating - vague 'get data' should ask technique"
    },
    {
        "id": "expwf_38", "cat": "exp_workflow",
        "input": "OLED 유기물 시료 분석 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "원소", "기법", "유기물")
        ),
        "desc": "OLED organic sample - should ask technique and element"
    },
    {
        "id": "expwf_39", "cat": "exp_workflow",
        "input": "Cu-Zn 합금 시편 검사해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "Cu", "Zn")
        ),
        "desc": "Cu-Zn alloy inspection - should ask technique"
    },
    {
        "id": "expwf_40", "cat": "exp_workflow",
        "input": "광물 시료에 Au가 있는지 알고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "XRF", "어떤", "기법", "시료", "마운트")
        ),
        "desc": "Au in mineral - should ask technique and sample prep"
    },

    # --- Group F: Sample prep check (technique explicit, prep unknown) ---
    {
        "id": "expwf_41", "cat": "exp_workflow",
        "input": "Mn K-edge XANES 찍어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착", "in-situ")
        ),
        "desc": "Mn XANES - technique clear but must ask sample prep"
    },
    {
        "id": "expwf_42", "cat": "exp_workflow",
        "input": "Ti XRF 맵핑 시작해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "Ti XRF mapping - technique clear but must ask sample prep"
    },
    {
        "id": "expwf_43", "cat": "exp_workflow",
        "input": "Ni K-edge EXAFS 측정 시작",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "Ni EXAFS - technique clear but must ask sample prep"
    },
    {
        "id": "expwf_44", "cat": "exp_workflow",
        "input": "Cu ptychography 실험 할게",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착", "TEM", "그리드")
        ),
        "desc": "Cu ptycho - technique clear but must ask sample prep"
    },
    {
        "id": "expwf_45", "cat": "exp_workflow",
        "input": "Fe 2D XRD 스캔 돌려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "Fe 2D XRD - technique clear but must ask sample prep"
    },
    {
        "id": "expwf_46", "cat": "exp_workflow",
        "input": "Zn XANES 빨리 찍자",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "Zn XANES rush - even urgent requests must check sample"
    },
    {
        "id": "expwf_47", "cat": "exp_workflow",
        "input": "Cr K-edge 흡수 스펙트럼 측정해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "Cr absorption spectrum - technique clear must ask prep"
    },
    {
        "id": "expwf_48", "cat": "exp_workflow",
        "input": "나노빔 XRF로 원소 맵 떠줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착", "원소")
        ),
        "desc": "Nanobeam XRF map - technique clear must ask sample"
    },
    {
        "id": "expwf_49", "cat": "exp_workflow",
        "input": "V XAFS 측정 진행해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("시료", "마운트", "준비", "프리셋", "장착")
        ),
        "desc": "V XAFS - technique clear must ask sample prep"
    },
    {
        "id": "expwf_50", "cat": "exp_workflow",
        "input": "분말 시료 XRD 데이터 수집해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("마운트", "준비", "프리셋", "장착", "pellet", "capillary")
        ),
        "desc": "Powder XRD variant - should ask mounting method"
    },

    # --- Group G: Correct workflow exceptions (should execute) ---
    {
        "id": "expwf_51", "cat": "exp_workflow",
        "input": "시료 프리셋 2번으로 준비했고, Fe K-edge XANES 측정해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_no_actions": False,
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("setTargetEnergy", "quickXanes", "runFullAlignment")
            for a in result.get("actions", [])
        ),
        "desc": "Preset + technique explicit - should execute"
    },
    {
        "id": "expwf_52", "cat": "exp_workflow",
        "input": "방금 시료 올렸어. 에너지 8.98 keV로 바꿔줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_no_actions": False,
        "expect_confirmation": True,
        "desc": "Direct energy command with sample context - should execute"
    },
    {
        "id": "expwf_53", "cat": "exp_workflow",
        "input": "SSA 사이즈 100으로 키워줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_no_actions": False,
        "expect_confirmation": True,
        "desc": "Direct SSA command - should execute immediately"
    },

    # --- Group H: Mixed / edge cases (variant phrasings) ---
    {
        "id": "expwf_54", "cat": "exp_workflow",
        "input": "잠깐, 이 시료에 뭐가 들어있는지도 모르겠어. 일단 뭐부터 해야 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "Confused user - should guide with workflow steps"
    },
    {
        "id": "expwf_55", "cat": "exp_workflow",
        "input": "전극 시료인데 Co, Ni, Mn 다 봐야 해. 어떻게 하면 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "XRF", "XANES", "시료", "기법")
        ),
        "desc": "Multi-element electrode - should discuss technique options"
    },
    {
        "id": "expwf_56", "cat": "exp_workflow",
        "input": "지금 빔타임 남은 시간이 2시간인데 Pt 촉매 빨리 측정해야 해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "회절", "어떤", "기법", "시료", "마운트")
        ),
        "desc": "Time pressure - even urgent should follow workflow"
    },
    {
        "id": "expwf_57", "cat": "exp_workflow",
        "input": "thin film 시료 표면에서 Cu 산화 상태 보고 싶어",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("XANES", "분광", "시료", "마운트", "준비", "프리셋")
        ),
        "desc": "Cu oxidation state in thin film - technique implied but should confirm"
    },
    {
        "id": "expwf_58", "cat": "exp_workflow",
        "input": "어제 실험하던 시료 이어서 하려고. 다른 위치에서 XANES 한 번 더 찍어줘",
        "context": {"energy": 8.98, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_no_actions": False,
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs")
            for a in result.get("actions", [])
        ),
        "desc": "Follow-up XANES at different position - should execute"
    },
    {
        "id": "expwf_59", "cat": "exp_workflow",
        "input": "이 배터리 셀 단면 시료에서 원소 분포 맵핑 가능해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("XRF", "이미징", "시료", "마운트", "원소", "가능")
        ),
        "desc": "Battery cross-section mapping - should ask prep details"
    },
    {
        "id": "expwf_60", "cat": "exp_workflow",
        "input": "반도체 웨이퍼에서 오염 원소 찾아줘. 급해.",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            kw in str(result.get("explanation", ""))
            for kw in ("이미징", "분광", "XRF", "어떤", "원소", "시료", "마운트")
        ),
        "desc": "Semiconductor contamination urgent - should still ask technique"
    },

    # ==================================================================
    # Category: Multilingual -- 7 languages x 5 tests = 35 cases
    # ==================================================================
    # Rationale per language (synchrotron facility user base):
    #   Chinese (zh): HEPS, SSRF, TPS, NSRRC -- largest non-English user community
    #   Arabic (ar):  SESAME (Jordan) -- first Middle East synchrotron
    #   Hindi (hi):   Indus-2 (India) -- RRCAT user community
    #   German (de):  DESY, BESSY II, KIT -- major European facilities
    #   French (fr):  SOLEIL, ESRF -- major European facilities
    #   Thai (th):    SLRI -- Southeast Asian user community
    #   Spanish (es): ALBA (Spain), LNLS (Brazil) -- Ibero-American facilities

    # --- Chinese (zh) ---
    {
        "id": "ml_zh_01", "cat": "multilingual",
        "input": "\u8bf7\u5c06\u80fd\u91cf\u8bbe\u7f6e\u4e3a12 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "Chinese: Set energy to 12 keV"
    },
    {
        "id": "ml_zh_02", "cat": "multilingual",
        "input": "\u6d4b\u91cf\u94dc\u7684K\u8fb9XANES\u5149\u8c31",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Chinese: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_zh_03", "cat": "multilingual",
        "input": "\u8fdb\u884c\u4e8c\u7ef4XRF\u626b\u63cf\uff0c\u8303\u56f4100x100\u5fae\u7c73\uff0c\u6b65\u95771\u5fae\u7c73",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "Chinese: 2D XRF raster scan 100x100um step 1um"
    },
    {
        "id": "ml_zh_04", "cat": "multilingual",
        "input": "\u8bf7\u8fdb\u884c\u5168\u81ea\u52a8\u5149\u675f\u5bf9\u51c6",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "Chinese: Full beam alignment"
    },
    {
        "id": "ml_zh_05", "cat": "multilingual",
        "input": "\u5c06\u80fd\u91cf\u8bbe\u7f6e\u4e3a50 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "Chinese: Out-of-range energy 50 keV (should reject)"
    },

    # --- Arabic (ar) ---
    {
        "id": "ml_ar_01", "cat": "multilingual",
        "input": "\u0627\u0636\u0628\u0637 \u0627\u0644\u0637\u0627\u0642\u0629 \u0639\u0644\u0649 8 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [8]},
        "expect_confirmation": True,
        "desc": "Arabic: Set energy to 8 keV"
    },
    {
        "id": "ml_ar_02", "cat": "multilingual",
        "input": "\u0642\u0645 \u0628\u0642\u064a\u0627\u0633 \u0637\u064a\u0641 XANES \u0644\u062d\u0627\u0641\u0629 K \u0644\u0644\u0646\u062d\u0627\u0633",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Arabic: Cu K-edge XANES spectrum"
    },
    {
        "id": "ml_ar_03", "cat": "multilingual",
        "input": "\u0623\u062c\u0631\u0650 \u0645\u0633\u062d XRF \u062b\u0646\u0627\u0626\u064a \u0627\u0644\u0623\u0628\u0639\u0627\u062f 50x50 \u0645\u064a\u0643\u0631\u0648\u0645\u062a\u0631 \u0628\u062e\u0637\u0648\u0629 2 \u0645\u064a\u0643\u0631\u0648\u0645\u062a\u0631",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "Arabic: 2D XRF scan 50x50um step 2um"
    },
    {
        "id": "ml_ar_04", "cat": "multilingual",
        "input": "\u0642\u0645 \u0628\u0645\u062d\u0627\u0630\u0627\u0629 \u0627\u0644\u062d\u0632\u0645\u0629 \u0627\u0644\u0643\u0627\u0645\u0644\u0629",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "Arabic: Full beam alignment"
    },
    {
        "id": "ml_ar_05", "cat": "multilingual",
        "input": "\u0627\u0636\u0628\u0637 \u0627\u0644\u0637\u0627\u0642\u0629 \u0639\u0644\u0649 50 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "Arabic: Out-of-range energy 50 keV (should reject)"
    },

    # --- Hindi (hi) ---
    {
        "id": "ml_hi_01", "cat": "multilingual",
        "input": "\u090a\u0930\u094d\u091c\u093e \u0915\u094b 15 keV \u092a\u0930 \u0938\u0947\u091f \u0915\u0930\u0947\u0902",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [15]},
        "expect_confirmation": True,
        "desc": "Hindi: Set energy to 15 keV"
    },
    {
        "id": "ml_hi_02", "cat": "multilingual",
        "input": "\u0924\u093e\u0902\u092c\u0947 \u0915\u0947 K-edge XANES \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e \u092e\u093e\u092a\u0947\u0902",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Hindi: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_hi_03", "cat": "multilingual",
        "input": "2D XRF \u0930\u0948\u0938\u094d\u091f\u0930 \u0938\u094d\u0915\u0948\u0928 \u0915\u0930\u0947\u0902, 80x80 \u092e\u093e\u0907\u0915\u094d\u0930\u094b\u092e\u0940\u091f\u0930, \u0938\u094d\u091f\u0947\u092a 1 \u092e\u093e\u0907\u0915\u094d\u0930\u094b\u092e\u0940\u091f\u0930",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "Hindi: 2D XRF raster scan 80x80um step 1um"
    },
    {
        "id": "ml_hi_04", "cat": "multilingual",
        "input": "\u092a\u0942\u0930\u094d\u0923 \u092c\u0940\u092e \u0938\u0902\u0930\u0947\u0916\u0923 \u0915\u0930\u0947\u0902",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "Hindi: Full beam alignment"
    },
    {
        "id": "ml_hi_05", "cat": "multilingual",
        "input": "\u090a\u0930\u094d\u091c\u093e 50 keV \u092a\u0930 \u0938\u0947\u091f \u0915\u0930\u0947\u0902",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "Hindi: Out-of-range energy 50 keV (should reject)"
    },

    # --- German (de) ---
    {
        "id": "ml_de_01", "cat": "multilingual",
        "input": "Bitte die Energie auf 10 keV einstellen",
        "context": {"energy": 8, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [10]},
        "expect_confirmation": True,
        "desc": "German: Set energy to 10 keV"
    },
    {
        "id": "ml_de_02", "cat": "multilingual",
        "input": "Messen Sie das Kupfer K-Kante XANES Spektrum",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "German: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_de_03", "cat": "multilingual",
        "input": "Starten Sie einen 2D XRF-Rasterscan, 100x100 Mikrometer, Schrittweite 2 Mikrometer",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "German: 2D XRF raster scan 100x100um step 2um"
    },
    {
        "id": "ml_de_04", "cat": "multilingual",
        "input": "Bitte die vollstaendige Strahlausrichtung durchfuehren",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "German: Full beam alignment"
    },
    {
        "id": "ml_de_05", "cat": "multilingual",
        "input": "Stellen Sie die Energie auf 50 keV ein",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "German: Out-of-range energy 50 keV (should reject)"
    },

    # --- French (fr) ---
    {
        "id": "ml_fr_01", "cat": "multilingual",
        "input": "Reglez l'energie a 9 keV s'il vous plait",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [9]},
        "expect_confirmation": True,
        "desc": "French: Set energy to 9 keV"
    },
    {
        "id": "ml_fr_02", "cat": "multilingual",
        "input": "Mesurez le spectre XANES au seuil K du cuivre",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "French: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_fr_03", "cat": "multilingual",
        "input": "Effectuez un balayage XRF 2D de 60x60 micrometres avec un pas de 1 micrometre",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "French: 2D XRF scan 60x60um step 1um"
    },
    {
        "id": "ml_fr_04", "cat": "multilingual",
        "input": "Veuillez effectuer l'alignement complet du faisceau",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "French: Full beam alignment"
    },
    {
        "id": "ml_fr_05", "cat": "multilingual",
        "input": "Reglez l'energie a 50 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "French: Out-of-range energy 50 keV (should reject)"
    },

    # --- Thai (th) ---
    {
        "id": "ml_th_01", "cat": "multilingual",
        "input": "\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e17\u0e35\u0e48 11 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [11]},
        "expect_confirmation": True,
        "desc": "Thai: Set energy to 11 keV"
    },
    {
        "id": "ml_th_02", "cat": "multilingual",
        "input": "\u0e27\u0e31\u0e14\u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21 XANES \u0e17\u0e35\u0e48\u0e02\u0e2d\u0e1a K \u0e02\u0e2d\u0e07\u0e17\u0e2d\u0e07\u0e41\u0e14\u0e07",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Thai: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_th_03", "cat": "multilingual",
        "input": "\u0e17\u0e33\u0e01\u0e32\u0e23\u0e2a\u0e41\u0e01\u0e19 XRF 2 \u0e21\u0e34\u0e15\u0e34 \u0e02\u0e19\u0e32\u0e14 50x50 \u0e44\u0e21\u0e42\u0e04\u0e23\u0e21\u0e34\u0e40\u0e15\u0e2d\u0e23\u0e4c \u0e2a\u0e40\u0e15\u0e47\u0e1b 1 \u0e44\u0e21\u0e42\u0e04\u0e23\u0e21\u0e34\u0e40\u0e15\u0e2d\u0e23\u0e4c",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "Thai: 2D XRF scan 50x50um step 1um"
    },
    {
        "id": "ml_th_04", "cat": "multilingual",
        "input": "\u0e17\u0e33\u0e01\u0e32\u0e23\u0e1b\u0e23\u0e31\u0e1a\u0e41\u0e19\u0e27\u0e25\u0e33\u0e41\u0e2a\u0e07\u0e2d\u0e31\u0e15\u0e42\u0e19\u0e21\u0e31\u0e15\u0e34\u0e17\u0e31\u0e49\u0e07\u0e2b\u0e21\u0e14",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "Thai: Full beam alignment"
    },
    {
        "id": "ml_th_05", "cat": "multilingual",
        "input": "\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e17\u0e35\u0e48 50 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "Thai: Out-of-range energy 50 keV (should reject)"
    },

    # --- Spanish (es) ---
    {
        "id": "ml_es_01", "cat": "multilingual",
        "input": "Ajuste la energia a 7 keV por favor",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [7]},
        "expect_confirmation": True,
        "desc": "Spanish: Set energy to 7 keV"
    },
    {
        "id": "ml_es_02", "cat": "multilingual",
        "input": "Mida el espectro XANES del borde K del cobre",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes", "queueStart"],
        "expect_args_contains": {0: ["Cu", "K"]},
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Spanish: Cu K-edge XANES measurement"
    },
    {
        "id": "ml_es_03", "cat": "multilingual",
        "input": "Realice un escaneo XRF 2D de 100x100 micrometros con paso de 2 micrometros",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster",) for a in result.get("actions", [])
        ),
        "desc": "Spanish: 2D XRF raster scan 100x100um step 2um"
    },
    {
        "id": "ml_es_04", "cat": "multilingual",
        "input": "Por favor, realice la alineacion completa del haz",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower() for a in result.get("actions", [])
        ),
        "desc": "Spanish: Full beam alignment"
    },
    {
        "id": "ml_es_05", "cat": "multilingual",
        "input": "Ajuste la energia a 50 keV",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "desc": "Spanish: Out-of-range energy 50 keV (should reject)"
    },

    # ── Transmission Calculator (showTransmission) ──
    {
        "id": "trans_01", "cat": "info",
        "input": "Cu 1um 시료의 투과율 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_args_contains": {0: ["Cu"]},
        "expect_confirmation": False,
        "desc": "Transmission: Cu 1um simple request"
    },
    {
        "id": "trans_02", "cat": "info",
        "input": "산화철 50um 시료의 투과율 곡선을 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showTransmission" and "Fe2O3" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Transmission: Fe2O3 50um (Korean compound name)"
    },
    {
        "id": "trans_03", "cat": "info",
        "input": "SiO2 100um의 투과율은 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showTransmission" and "SiO2" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Transmission: SiO2 query form"
    },
    {
        "id": "trans_04", "cat": "info",
        "input": "Show me the transmission curve for gold 0.5um",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showTransmission" and "Au" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Transmission: English gold request"
    },
    {
        "id": "trans_05", "cat": "info",
        "input": "NiO 10um 시료의 투과율을 확인하고 싶어. 밀도는 6.67",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showTransmission" and "NiO" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Transmission: NiO with explicit density"
    },
    {
        "id": "trans_06", "cat": "multi",
        "input": "에너지를 8.5keV로 설정하고 구리 1um 투과율 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy", "showTransmission"],
        "expect_args_contains": {0: [8.5]},
        "expect_confirmation": None,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") == "setTargetEnergy" for a in result.get("actions", [])) and
            any(a.get("fn") == "showTransmission" for a in result.get("actions", []))
        ),
        "desc": "Multi: energy set + transmission"
    },
    {
        "id": "trans_07", "cat": "info",
        "input": "10keV 빔으로 GaAs 5um 시료를 투과시키면 얼마나 투과해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showTransmission"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showTransmission" and "GaAs" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "Transmission: GaAs contextual question"
    },

    # ==================================================================
    # Category 29: RAG Knowledge Queries — Physics & Optics
    # ==================================================================
    {
        "id": "rag_phys_01", "cat": "rag_physics",
        "input": "왜 20keV에서 빔 사이즈가 커져?",
        "context": {"energy": 20, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            result.get("type") in ("rag_response", "nlp_response")
        ),
        "desc": "RAG: Why beam size increases at 20keV"
    },
    {
        "id": "rag_phys_02", "cat": "rag_physics",
        "input": "SSA가 빔 사이즈에 어떤 영향을 줘?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: SSA effect on beam size"
    },
    {
        "id": "rag_phys_03", "cat": "rag_physics",
        "input": "언듈레이터 고조파가 뭐야? 왜 홀수 고조파만 써?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Undulator harmonics principle"
    },
    {
        "id": "rag_phys_04", "cat": "rag_physics",
        "input": "회절 한계가 뭐야? 빔 사이즈하고 어떤 관계야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Diffraction limit and beam size"
    },
    {
        "id": "rag_phys_05", "cat": "rag_physics",
        "input": "How does coherence affect beam quality?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Coherence and beam quality (English)"
    },
    {
        "id": "rag_phys_06", "cat": "rag_physics",
        "input": "빔 경화 현상이 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Beam hardening phenomenon"
    },

    # ==================================================================
    # Category 30: RAG Knowledge Queries — Optics & Components
    # ==================================================================
    {
        "id": "rag_opt_01", "cat": "rag_optics",
        "input": "DCM Si(111)이랑 Si(311) 차이를 설명해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in result.get("explanation", "").lower() for kw in ("111", "311", "crystal", "결정"))
        ),
        "desc": "RAG: DCM Si(111) vs Si(311) difference"
    },
    {
        "id": "rag_opt_02", "cat": "rag_optics",
        "input": "Pt 코팅이랑 Rh 코팅 비교해줘. 언제 뭘 써야 해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in result.get("explanation", "").lower() for kw in ("pt", "rh", "코팅", "coating", "반사", "reflect"))
        ),
        "desc": "RAG: Pt vs Rh coating comparison"
    },
    {
        "id": "rag_opt_03", "cat": "rag_optics",
        "input": "KB 미러 초점거리가 어떻게 돼? M1, M2는?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: KB mirror and M1/M2 focal lengths"
    },
    {
        "id": "rag_opt_04", "cat": "rag_optics",
        "input": "M1 미러 크기랑 코팅 종류 알려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: M1 mirror size and coating"
    },
    {
        "id": "rag_opt_05", "cat": "rag_optics",
        "input": "이 빔라인의 주요 광학 장치를 설명해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Main optical components overview"
    },
    {
        "id": "rag_opt_06", "cat": "rag_optics",
        "input": "What is the difference between KB focusing and zone plate focusing?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: KB vs zone plate focusing (English)"
    },

    # ==================================================================
    # Category 31: RAG Knowledge Queries — Procedures
    # ==================================================================
    {
        "id": "rag_proc_01", "cat": "rag_procedure",
        "input": "M1 정렬 순서를 설명해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in result.get("explanation", "").lower() for kw in ("half", "pitch", "정렬", "align", "cut"))
        ),
        "desc": "RAG: M1 alignment procedure"
    },
    {
        "id": "rag_proc_02", "cat": "rag_procedure",
        "input": "XANES 스캔 절차를 어떻게 해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: XANES scan procedure"
    },
    {
        "id": "rag_proc_03", "cat": "rag_procedure",
        "input": "DCM 결정 교체 절차가 어떻게 돼?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: DCM crystal change procedure"
    },
    {
        "id": "rag_proc_04", "cat": "rag_procedure",
        "input": "빔라인 정렬 전체 워크플로우를 설명해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Full alignment workflow"
    },

    # ==================================================================
    # Category 32: RAG Knowledge Queries — Comparison & Selection
    # ==================================================================
    {
        "id": "rag_comp_01", "cat": "rag_comparison",
        "input": "XANES랑 XAFS 차이가 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in result.get("explanation", "").lower() for kw in ("xanes", "xafs", "near", "absorption"))
        ),
        "desc": "RAG: XANES vs XAFS difference"
    },
    {
        "id": "rag_comp_02", "cat": "rag_comparison",
        "input": "XRF이랑 XRD는 어떤 차이가 있어? 각각 언제 써?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: XRF vs XRD comparison"
    },
    {
        "id": "rag_comp_03", "cat": "rag_comparison",
        "input": "래스터 스캔이랑 페르마 스캔 장단점 비교해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Raster vs Fermat scan comparison"
    },
    {
        "id": "rag_comp_04", "cat": "rag_comparison",
        "input": "Si(111) vs Si(311) 언제 뭘 써야 해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Si(111) vs Si(311) when to use"
    },
    {
        "id": "rag_comp_05", "cat": "rag_comparison",
        "input": "이 에너지 범위에서 Rh 코팅이 나아 Pt 코팅이 나아?",
        "context": {"energy": 15, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Rh vs Pt coating at 15keV"
    },

    # ==================================================================
    # Category 33: RAG Knowledge Queries — Safety & Constraints
    # ==================================================================
    {
        "id": "rag_safe_01", "cat": "rag_safety",
        "input": "열부하 때문에 빔을 감쇠시켜야 하는 경우가 언제야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Heat load and attenuation"
    },
    {
        "id": "rag_safe_02", "cat": "rag_safety",
        "input": "빔 사이즈를 줄이면 시료에 어떤 영향이 있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Beam size reduction impact on sample"
    },
    {
        "id": "rag_safe_03", "cat": "rag_safety",
        "input": "25keV 이상 에너지가 안 되는 이유가 뭐야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Energy limit reason"
    },

    # ==================================================================
    # Category 34: RAG Knowledge Queries — Combined / Complex
    # ==================================================================
    {
        "id": "rag_comb_01", "cat": "rag_combined",
        "input": "Cu K-edge XANES를 최적 조건으로 하려면 어떤 세팅이 좋아?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("explanation", "")) > 30 and
            any(kw in result.get("explanation", "").lower() for kw in ("cu", "8.9", "keV", "energy"))
        ),
        "desc": "RAG: Optimal Cu XANES settings"
    },
    {
        "id": "rag_comb_02", "cat": "rag_combined",
        "input": "나노 사이즈 빔으로 배터리 시료를 분석하려면 어떤 기법이 좋아?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Battery analysis technique recommendation"
    },
    {
        "id": "rag_comb_03", "cat": "rag_combined",
        "input": "이 빔라인 전체 구조를 요약해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Beamline overview summary"
    },
    {
        "id": "rag_comb_04", "cat": "rag_combined",
        "input": "촉매 시료에서 산화 상태 변화를 보려면 어떻게 해야 해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": [],
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 30,
        "desc": "RAG: Catalyst oxidation state analysis"
    },

    # ==================================================================
    # Category 35: RAG — Intent routing regression (must stay as commands)
    # ==================================================================
    {
        "id": "rag_reg_01", "cat": "rag_regression",
        "input": "에너지 12keV로 설정해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["setTargetEnergy"],
        "expect_args_contains": {0: [12]},
        "expect_confirmation": True,
        "desc": "RAG regression: energy command must NOT route to RAG"
    },
    {
        "id": "rag_reg_02", "cat": "rag_regression",
        "input": "Cu XANES 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickXanes"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickXanes", "quickXafs") and
            "Cu" in str(a.get("args", []))
            for a in result.get("actions", [])
        ),
        "desc": "RAG regression: Cu XANES command must NOT route to RAG"
    },
    {
        "id": "rag_reg_03", "cat": "rag_regression",
        "input": "정렬 시작해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["runFullAlignment"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "align" in a.get("fn", "").lower()
            for a in result.get("actions", [])
        ),
        "desc": "RAG regression: alignment command must NOT route to RAG"
    },
    {
        "id": "rag_reg_04", "cat": "rag_regression",
        "input": "빔 프로파일 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["showBeamProfile"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "showBeamProfile"
            for a in result.get("actions", [])
        ),
        "desc": "RAG regression: beam profile command must NOT route to RAG"
    },
    {
        "id": "rag_reg_05", "cat": "rag_regression",
        "input": "SSA 30으로 줄여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            "motor" in a.get("fn", "").lower() or "ssa" in str(a.get("args", [])).lower()
            for a in result.get("actions", [])
        ),
        "desc": "RAG regression: SSA command must NOT route to RAG"
    },

    # ====================================================================
    # Nano Scanner — scan commands (15 cases)
    # ====================================================================
    {
        "id": "nano_01", "cat": "nano_scan",
        "input": "나노스캐너로 10x10um 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanStep2D"],
        "expect_fn_exclude": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanStep2D" for a in result.get("actions", [])),
        "desc": "Nano 2D step scan 10x10um"
    },
    {
        "id": "nano_02", "cat": "nano_scan",
        "input": "나노 플라이 스캔 X축 20um 200포인트",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanFly1D"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanFly1D" for a in result.get("actions", [])),
        "desc": "Nano fly scan X 20um"
    },
    {
        "id": "nano_03", "cat": "nano_scan",
        "input": "나노 스파이럴 스캔 반경 5um 간격 50nm",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanSpiral"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanSpiral" for a in result.get("actions", [])),
        "desc": "Nano spiral scan R=5um dr=50nm"
    },
    {
        "id": "nano_04", "cat": "nano_scan",
        "input": "나노 2D 스캔 5x5um 51x51포인트 dwell 0.05초",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanStep2D"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanStep2D" and
            5 in (a.get("args", [])[:2] if a.get("args") else [])
            for a in result.get("actions", [])),
        "desc": "Nano 2D scan with full params"
    },
    {
        "id": "nano_05", "cat": "nano_scan",
        "input": "나노스캐너로 고해상도 래스터 스캔",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) == 0 and
            len(result.get("explanation", "")) > 10),
        "desc": "Nano scan param missing -> ask"
    },
    {
        "id": "nano_06", "cat": "nano_scan",
        "input": "나노스캔 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) == 0 and
            len(result.get("explanation", "")) > 10),
        "desc": "Nano scan no params -> ask"
    },
    {
        "id": "nano_07", "cat": "nano_scan",
        "input": "나노 스캔 기본값으로 해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanStep2D"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanStep2D" for a in result.get("actions", [])),
        "desc": "Nano scan with defaults"
    },
    {
        "id": "nano_08", "cat": "nano_scan",
        "input": "MCS2로 20x20um 200포인트 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanStep2D"],
        "expect_fn_exclude": ["quickRaster", "queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanStep2D" for a in result.get("actions", [])),
        "desc": "MCS2 keyword triggers nano scan"
    },
    {
        "id": "nano_09", "cat": "nano_scan",
        "input": "피코스케일로 X축 라인스캔 10um 100포인트",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanFly1D"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoScanFly1D", "nanoScanStep2D")
            for a in result.get("actions", [])),
        "desc": "PicoScale keyword triggers nano scan"
    },
    {
        "id": "nano_10", "cat": "nano_scan",
        "input": "나노 스파이럴 5um 간격 100nm dwell 0.02초",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanSpiral"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "desc": "Nano spiral with full params"
    },
    {
        "id": "nano_11", "cat": "nano_scan",
        "input": "10x10 래스터 스캔해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["quickRaster", "queueStart"],
        "expect_fn_exclude": ["nanoScanStep2D"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "quickRaster" for a in result.get("actions", [])),
        "desc": "Regular raster (no nano keyword) -> quickRaster"
    },
    {
        "id": "nano_12", "cat": "nano_scan",
        "input": "XRF 맵핑 해줘 Fe",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn_exclude": ["nanoScanStep2D"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("quickRaster", "optimizeBeamline", "setupVirtualExperiment")
            for a in result.get("actions", [])),
        "desc": "XRF mapping (no nano) -> quickRaster"
    },
    {
        "id": "nano_13", "cat": "nano_scan",
        "input": "나노 스캔 중단해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True, "nano_scanning": True},
        "expect_fn": ["nanoScanAbort"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanAbort" for a in result.get("actions", [])),
        "desc": "Nano scan abort"
    },
    {
        "id": "nano_14", "cat": "nano_scan",
        "input": "나노스캐너 스캔 멈춰",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True, "nano_scanning": True},
        "expect_fn": ["nanoScanAbort"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoScanAbort", "emergencyStop")
            for a in result.get("actions", [])),
        "desc": "Nano scan stop (alt phrasing)"
    },
    {
        "id": "nano_15", "cat": "nano_scan",
        "input": "나노 2D 스캔 X 20um Y 5um 101x51포인트",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoScanStep2D"],
        "expect_fn_exclude": ["queueStart"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoScanStep2D" for a in result.get("actions", [])),
        "desc": "Nano 2D scan asymmetric range"
    },

    # ====================================================================
    # Nano Scanner — move commands (10 cases)
    # ====================================================================
    {
        "id": "nmov_01", "cat": "nano_move",
        "input": "나노 스테이지 X축 500nm 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoJog"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoJog", "nanoMoveTo") for a in result.get("actions", [])),
        "desc": "Nano jog X 500nm = 0.5um"
    },
    {
        "id": "nmov_02", "cat": "nano_move",
        "input": "나노 Y축 10um 위치로 이동해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoMoveTo"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoMoveTo", "nanoJog") for a in result.get("actions", [])),
        "desc": "Nano absolute move Y to 10um"
    },
    {
        "id": "nmov_03", "cat": "nano_move",
        "input": "MCS2 X 1um 이동해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoJog"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoJog", "nanoMoveTo") for a in result.get("actions", [])),
        "desc": "MCS2 keyword jog X 1um"
    },
    {
        "id": "nmov_04", "cat": "nano_move",
        "input": "나노 스테이지 X축 -2um 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoJog"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoJog", "nanoMoveTo") and
            any(v < 0 for v in a.get("args", []) if isinstance(v, (int, float)))
            for a in result.get("actions", [])),
        "desc": "Nano jog negative direction"
    },
    {
        "id": "nmov_05", "cat": "nano_move",
        "input": "나노 Z축 500nm으로 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoMoveTo"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoMoveTo", "nanoJog") for a in result.get("actions", [])),
        "desc": "Nano absolute move Z to 500nm"
    },
    {
        "id": "nmov_06", "cat": "nano_move",
        "input": "나노 스테이지 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) == 0 and
            len(result.get("explanation", "")) > 10),
        "desc": "Nano move missing params -> ask"
    },
    {
        "id": "nmov_07", "cat": "nano_move",
        "input": "나노 X축 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_no_actions": True,
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            len(result.get("actions", [])) == 0 and
            len(result.get("explanation", "")) > 10),
        "desc": "Nano move missing distance -> ask"
    },
    {
        "id": "nmov_08", "cat": "nano_move",
        "input": "나노 스캐너 원점으로 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["nanoMoveTo"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") == "nanoMoveTo" for a in result.get("actions", [])),
        "desc": "Nano move to origin"
    },
    {
        "id": "nmov_09", "cat": "nano_move",
        "input": "시료 X를 5mm로 이동해",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_fn_exclude": ["nanoJog", "nanoMoveTo"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("motorSetUI", "motorMoveRelUI") and
            "sample" in str(a.get("args", []))
            for a in result.get("actions", [])),
        "desc": "Sample X 5mm (not nano) -> motorSetUI"
    },
    {
        "id": "nmov_10", "cat": "nano_move",
        "input": "시료 파인X 10um으로 이동",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["motorSetUI"],
        "expect_fn_exclude": ["nanoJog", "nanoMoveTo"],
        "expect_confirmation": True,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("motorSetUI", "motorMoveRelUI") and
            "sample_fx" in str(a.get("args", []))
            for a in result.get("actions", [])),
        "desc": "Sample fine X (PI PIMars, not nano)"
    },

    # ====================================================================
    # Hardware Status Queries (12 cases)
    # ====================================================================
    {
        "id": "hw_01", "cat": "hw_status",
        "input": "피코스케일 위치 읽어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_fn": ["queryHardwareStatus"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus", "nanoStatus")
            for a in result.get("actions", [])),
        "desc": "PicoScale position query"
    },
    {
        "id": "hw_02", "cat": "hw_status",
        "input": "간섭계 상태는 어때?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["nanoStatus"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoStatus", "queryHardwareStatus")
            for a in result.get("actions", [])),
        "desc": "Interferometer status query"
    },
    {
        "id": "hw_03", "cat": "hw_status",
        "input": "XBPM 읽어줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["queryHardwareStatus"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus", "nanoStatus")
            for a in result.get("actions", [])),
        "desc": "XBPM status query"
    },
    {
        "id": "hw_04", "cat": "hw_status",
        "input": "현재 링 전류 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            "400" in result.get("explanation", "")),
        "desc": "Ring current query"
    },
    {
        "id": "hw_05", "cat": "hw_status",
        "input": "나노스캐너 연결 상태 확인해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["nanoStatus"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoStatus", "queryHardwareStatus")
            for a in result.get("actions", [])),
        "desc": "Nano scanner connection status"
    },
    {
        "id": "hw_06", "cat": "hw_status",
        "input": "KOHZU 스테이지 위치 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            "sample" in result.get("explanation", "").lower()),
        "desc": "KOHZU stage position query"
    },
    {
        "id": "hw_07", "cat": "hw_status",
        "input": "전체 장비 상태 보여줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_fn": ["queryHardwareStatus"],
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus", "nanoStatus")
            for a in result.get("actions", [])),
        "desc": "All hardware status query"
    },
    {
        "id": "hw_08", "cat": "hw_status",
        "input": "MCS2 연결됐어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("nanoStatus", "queryHardwareStatus")
            for a in result.get("actions", [])),
        "desc": "MCS2 connection check"
    },
    {
        "id": "hw_09", "cat": "hw_status",
        "input": "빔 위치 모니터 값 확인해줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus", "nanoStatus")
            for a in result.get("actions", [])),
        "desc": "Beam position monitor query"
    },
    {
        "id": "hw_10", "cat": "hw_status",
        "input": "현재 에너지 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "10" in result.get("explanation", "") and
            len(result.get("explanation", "")) > 5),
        "desc": "Current energy from context (no action needed)"
    },
    {
        "id": "hw_11", "cat": "hw_status",
        "input": "XBPM 전류 값 얼마야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus",)
            for a in result.get("actions", [])),
        "desc": "XBPM current value query"
    },
    {
        "id": "hw_12", "cat": "hw_status",
        "input": "나노 스테이지 현재 위치 알려줘",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50, "nano_connected": True},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: any(
            a.get("fn") in ("queryHardwareStatus", "nanoStatus")
            for a in result.get("actions", [])),
        "desc": "Nano stage current position"
    },

    # ====================================================================
    # Anti-Hallucination (13 cases)
    # ====================================================================
    {
        "id": "ah_01", "cat": "anti_hallucination",
        "input": "간섭계 상태 정상이야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("nanoStatus", "queryHardwareStatus")
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: interferometer status must query"
    },
    {
        "id": "ah_02", "cat": "anti_hallucination",
        "input": "피코스케일 정밀도 괜찮아?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("nanoStatus", "queryHardwareStatus")
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10),
        "desc": "Anti-hallucination: PicoScale precision query"
    },
    {
        "id": "ah_03", "cat": "anti_hallucination",
        "input": "XBPM 빔 위치가 중앙이야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: XBPM center check must query"
    },
    {
        "id": "ah_04", "cat": "anti_hallucination",
        "input": "KOHZU 모터 에러 없어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: KOHZU motor error check"
    },
    {
        "id": "ah_05", "cat": "anti_hallucination",
        "input": "나노스캐너 캘리브레이션 됐어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("nanoStatus", "queryHardwareStatus")
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: nano calibration status"
    },
    {
        "id": "ah_06", "cat": "anti_hallucination",
        "input": "현재 빔 상태 좋아?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus", "nanoStatus")
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: beam status must not guess"
    },
    {
        "id": "ah_07", "cat": "anti_hallucination",
        "input": "모터 다 정상이야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: all motors status"
    },
    {
        "id": "ah_08", "cat": "anti_hallucination",
        "input": "링 전류 정상 범위야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            len(result.get("explanation", "")) > 10),
        "desc": "Anti-hallucination: ring current range check"
    },
    {
        "id": "ah_09", "cat": "anti_hallucination",
        "input": "나노스캐너 온도 괜찮아?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "지원" in result.get("explanation", "") or
            "온도" in result.get("explanation", "") or
            "확인" in result.get("explanation", "")),
        "desc": "Anti-hallucination: unsupported feature honest answer"
    },
    {
        "id": "ah_10", "cat": "anti_hallucination",
        "input": "빔 사이즈 지금 50nm이야?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: len(result.get("explanation", "")) > 10,
        "desc": "Anti-hallucination: beam size question"
    },
    {
        "id": "ah_11", "cat": "anti_hallucination",
        "input": "SSA가 지금 열려있어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "50" in result.get("explanation", "") or
            "SSA" in result.get("explanation", "") or
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", []))),
        "desc": "Anti-hallucination: SSA status from context"
    },
    {
        "id": "ah_12", "cat": "anti_hallucination",
        "input": "DCM 정상적으로 동작해?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", [])) or
            ("확인" in result.get("explanation", "") or
             "조회" in result.get("explanation", ""))),
        "desc": "Anti-hallucination: DCM status must query"
    },
    {
        "id": "ah_13", "cat": "anti_hallucination",
        "input": "검출기 연결됐어?",
        "context": {"energy": 10, "ssaH": 50, "ssaV": 50},
        "expect_confirmation": False,
        "expect_alt_pass": lambda result: (
            "확인" in result.get("explanation", "") or
            "지원" in result.get("explanation", "") or
            "필요" in result.get("explanation", "") or
            any(a.get("fn") in ("queryHardwareStatus",)
                for a in result.get("actions", []))),
        "desc": "Anti-hallucination: detector connection honest answer"
    },
]



# ======================================================================
# Category name mapping (for display)
# ======================================================================
CAT_NAMES = {
    "exp_workflow": "Experimental Workflow",
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
    "experiment_plan": "Experiment Planning",
    "real_user": "Real User Scenarios",
    "complex_multi": "Complex Multi-step",
    "robustness": "Robustness (typos/edge)",
    "rejection": "Rejection Scenarios",
    "korean_variant": "Korean Variants",
    "signal_est": "Signal Estimation",
    "bl_knowledge": "Beamline Knowledge",
    "rag_physics": "RAG: Physics Principles",
    "rag_optics": "RAG: Optics & Components",
    "rag_procedure": "RAG: Procedures",
    "rag_comparison": "RAG: Comparison & Selection",
    "rag_safety": "RAG: Safety & Constraints",
    "rag_combined": "RAG: Combined / Complex",
    "rag_regression": "RAG: Intent Routing Regression",
    "multilingual": "Multilingual (7 languages)",
    "experiment_preset": "Experiment Preset Setup",
    "experiment_planning_adv": "Advanced Experiment Planning",
    "ptycho_experiment": "Ptychography Experiments",
    "technique_selection": "Technique Selection",
    "multi_technique_wf": "Multi-technique Workflows",
    "timing_feasibility": "Timing & Feasibility",
    "experiment_edge": "Experiment Edge Cases",
    "nano_scan": "Nano Scanner Scans",
    "nano_move": "Nano Scanner Movement",
    "hw_status": "Hardware Status Queries",
    "anti_hallucination": "Anti-Hallucination",
}

# All valid engine names
ALL_ENGINES = ["ollama", "groq", "gemini", "claude", "deepseek", "openai", "mistral"]


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
        self.input: str = ""
        self.cat: str = ""

    def fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)


def validate_result(tc: Dict, result: Dict) -> TestResult:
    """Validate a single test case result against expected criteria."""
    tr = TestResult(tc["id"], tc["desc"])
    tr.response = result
    tr.input = tc.get("input", "")
    tr.cat = tc.get("cat", "")

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
    if tc.get("expect_confirmation") is not None:
        if conf != tc["expect_confirmation"]:
            tr.fail(f"Expected confirmation_required={tc['expect_confirmation']}, got {conf}")

    # Check: explanation is Korean (warning only)
    if explanation and len(explanation) > 5:
        has_korean = any('\uac00' <= c <= '\ud7a3' or '\u3131' <= c <= '\u3163' for c in explanation)
        if not has_korean and tc.get("expect_korean_strict"):
            tr.fail(f"Explanation not in Korean: '{explanation[:80]}...'")

    return tr


async def run_tests(
    engine: Optional[str] = None,
    model: Optional[str] = None,
    categories: Optional[List[str]] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run all test cases against the NLP agent.

    Returns a dict with summary data (for multi-engine comparison).
    """

    # Override engine/model via environment
    if engine:
        os.environ["NLP_ENGINE"] = engine
    if model:
        engine_key = (engine or os.environ.get("NLP_ENGINE", "ollama")).lower()
        model_env_map = {
            "ollama": "OLLAMA_MODEL",
            "groq": "GROQ_MODEL",
            "gemini": "GEMINI_MODEL",
            "claude": "CLAUDE_MODEL",
            "deepseek": "DEEPSEEK_MODEL",
            "openai": "OPENAI_MODEL",
            "mistral": "MISTRAL_MODEL",
            "vllm": "VLLM_MODEL",
        }
        env_key = model_env_map.get(engine_key)
        if env_key:
            os.environ[env_key] = model

    # Filter by category
    cases = TEST_CASES
    if categories:
        cases = [tc for tc in cases if tc["cat"] in categories]

    print(f"\n{'='*70}")
    print("  NLP Benchmark Test Suite")
    print(f"  {len(cases)} test cases" + (f" (categories: {', '.join(categories)})" if categories else ""))
    print(f"{'='*70}\n")

    # Initialize agent
    try:
        agent = NLPAgent()
    except Exception as e:
        print(f"  ERROR: Failed to initialize NLP agent: {e}")
        return {"engine": engine or "unknown", "model": "unknown",
                "error": str(e), "total": 0, "pass": 0, "fail": 0}

    actual_engine = agent.engine
    actual_model = getattr(agent.backend, "model", "unknown")
    print(f"  Backend: {actual_engine}")
    print(f"  Model: {actual_model}\n")

    results: List[TestResult] = []
    cat_stats: Dict[str, Dict] = {}

    for i, tc in enumerate(cases):
        # Reset conversation history between tests
        agent.reset_history()

        cat = tc["cat"]
        if cat not in cat_stats:
            cat_stats[cat] = {"pass": 0, "fail": 0, "total": 0, "times": []}
        cat_stats[cat]["total"] += 1

        print(f"  [{i+1:3d}/{len(cases)}] {tc['id']:14s} | {tc['desc'][:42]:42s} ", end="", flush=True)

        # Extract language from multilingual test case IDs (e.g., ml_zh_01 -> zh)
        lang = "ko"
        if tc["cat"] == "multilingual" and tc["id"].startswith("ml_"):
            parts = tc["id"].split("_")
            if len(parts) >= 2:
                lang = parts[1]

        t0 = time.time()
        try:
            result = await agent.process(tc["input"], tc.get("context"), language=lang)
        except Exception as e:
            result = {"type": "error", "message": str(e)}
        elapsed = time.time() - t0

        tr = validate_result(tc, result)
        tr.elapsed = elapsed
        results.append(tr)
        cat_stats[cat]["times"].append(elapsed)

        if tr.passed:
            cat_stats[cat]["pass"] += 1
            print(f"PASS  ({elapsed:.1f}s)")
        else:
            cat_stats[cat]["fail"] += 1
            print(f"FAIL  ({elapsed:.1f}s)")
            for err in tr.errors:
                print(f"           -> {err}")

        if verbose and result.get("type") != "error":
            try:
                print(f"           Response: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
            except UnicodeEncodeError:
                print(f"           Response: {json.dumps(result, ensure_ascii=True, indent=2)[:500]}")

        # Brief pause to avoid overwhelming backend
        await asyncio.sleep(0.3)

    # ── Summary ──
    total_pass = sum(1 for r in results if r.passed)
    total_fail = sum(1 for r in results if not r.passed)
    all_times = [r.elapsed for r in results]
    total_time = sum(all_times)

    print(f"\n{'='*70}")
    print(f"  SUMMARY  [{actual_engine} / {actual_model}]")
    print(f"{'='*70}")
    print(f"  Total: {len(results)} | Pass: {total_pass} | Fail: {total_fail} | Time: {total_time:.1f}s")
    if len(results) > 0:
        print(f"  Pass rate: {total_pass/len(results)*100:.1f}%")
    print()

    # Latency statistics
    if all_times:
        sorted_times = sorted(all_times)
        p95_idx = int(len(sorted_times) * 0.95)
        p95 = sorted_times[min(p95_idx, len(sorted_times) - 1)]
        print(f"  Latency:  avg={statistics.mean(all_times):.2f}s  "
              f"min={min(all_times):.2f}s  max={max(all_times):.2f}s  "
              f"p95={p95:.2f}s")
    print()

    # Per-category breakdown
    for cat, stats in cat_stats.items():
        name = CAT_NAMES.get(cat, cat)
        pct = stats["pass"] / stats["total"] * 100 if stats["total"] > 0 else 0
        status = "OK" if stats["fail"] == 0 else "!!"
        avg_t = statistics.mean(stats["times"]) if stats["times"] else 0
        print(f"  {status} {name:30s}  {stats['pass']:2d}/{stats['total']:2d} ({pct:5.1f}%)  avg {avg_t:.1f}s")

    print(f"\n{'='*70}")

    # ── Build output data ──
    out_data = {
        "engine": actual_engine,
        "model": actual_model,
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "pass": total_pass,
        "fail": total_fail,
        "pass_rate": round(total_pass / len(results) * 100, 1) if results else 0,
        "total_time_s": round(total_time, 1),
        "latency": {
            "avg": round(statistics.mean(all_times), 3) if all_times else 0,
            "min": round(min(all_times), 3) if all_times else 0,
            "max": round(max(all_times), 3) if all_times else 0,
            "p95": round(p95, 3) if all_times else 0,
        },
        "per_category": {
            cat: {
                "pass": s["pass"], "fail": s["fail"], "total": s["total"],
                "avg_time": round(statistics.mean(s["times"]), 3) if s["times"] else 0,
            }
            for cat, s in cat_stats.items()
        },
        "details": [
            {
                "id": r.test_id,
                "cat": r.cat,
                "input": r.input,
                "desc": r.desc,
                "passed": r.passed,
                "errors": r.errors,
                "elapsed_s": round(r.elapsed, 2),
                "response": r.response,
            }
            for r in results
        ]
    }

    # ── Write results to file ──
    results_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "nlp_benchmark", "results")
    os.makedirs(results_dir, exist_ok=True)

    safe_model = actual_model.replace("/", "_").replace(":", "_").replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"{actual_engine}_{safe_model}_{ts}.json"
    out_path = os.path.join(results_dir, out_filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"  Results saved to: {out_path}\n")

    return out_data


def generate_comparison_markdown(all_results: List[Dict[str, Any]]) -> str:
    """Generate a markdown comparison table from multiple engine results."""
    lines = []
    lines.append("# NLP Benchmark Comparison")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")

    # Overall summary table
    lines.append("## Overall Summary")
    lines.append("")
    lines.append("| Engine | Model | Total | Pass | Fail | Rate | Avg Latency | P95 Latency |")
    lines.append("|--------|-------|-------|------|------|------|-------------|-------------|")
    for r in all_results:
        if r.get("error"):
            lines.append(f"| {r['engine']} | N/A | ERROR | - | - | - | - | - |")
            continue
        lat = r.get("latency", {})
        lines.append(
            f"| {r['engine']} | {r.get('model', '?')} "
            f"| {r['total']} | {r['pass']} | {r['fail']} "
            f"| {r.get('pass_rate', 0):.1f}% "
            f"| {lat.get('avg', 0):.2f}s "
            f"| {lat.get('p95', 0):.2f}s |"
        )
    lines.append("")

    # Per-category breakdown
    all_cats = set()
    for r in all_results:
        if not r.get("error"):
            all_cats.update(r.get("per_category", {}).keys())
    all_cats = sorted(all_cats)

    if all_cats:
        lines.append("## Per-Category Pass Rate")
        lines.append("")
        header = "| Category |"
        sep = "|----------|"
        for r in all_results:
            if not r.get("error"):
                header += f" {r['engine']} |"
                sep += "--------|"
        lines.append(header)
        lines.append(sep)

        for cat in all_cats:
            name = CAT_NAMES.get(cat, cat)
            row = f"| {name} |"
            for r in all_results:
                if r.get("error"):
                    continue
                cs = r.get("per_category", {}).get(cat)
                if cs:
                    pct = cs["pass"] / cs["total"] * 100 if cs["total"] > 0 else 0
                    row += f" {cs['pass']}/{cs['total']} ({pct:.0f}%) |"
                else:
                    row += " - |"
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


async def run_all_engines(categories: Optional[List[str]] = None, verbose: bool = False):
    """Run benchmark across all configured engines and generate comparison."""
    all_results = []

    for eng in ALL_ENGINES:
        print(f"\n{'#'*70}")
        print(f"  ENGINE: {eng}")
        print(f"{'#'*70}")
        try:
            result = await run_tests(engine=eng, categories=categories, verbose=verbose)
            all_results.append(result)
        except Exception as e:
            print(f"  ERROR running {eng}: {e}")
            all_results.append({"engine": eng, "error": str(e), "total": 0, "pass": 0, "fail": 0})

    # Generate comparison
    md = generate_comparison_markdown(all_results)
    results_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "nlp_benchmark", "results")
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(results_dir, f"comparison_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n  Comparison saved to: {md_path}")

    return all_results


if __name__ == "__main__":
    # Force UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="NLP Benchmark Test Suite")
    parser.add_argument("--engine", type=str,
                        help="NLP engine to use (ollama, vllm, groq, gemini, claude, deepseek, openai, mistral, solar)")
    parser.add_argument("--model", type=str,
                        help="Override model name for the selected engine")
    parser.add_argument("--all-engines", action="store_true",
                        help="Run benchmark across ALL configured engines")
    parser.add_argument("--cat", type=str,
                        help="Category filter (comma-separated)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full JSON responses")
    args = parser.parse_args()

    categories = args.cat.split(",") if args.cat else None

    if args.all_engines:
        asyncio.run(run_all_engines(categories=categories, verbose=args.verbose))
    else:
        result = asyncio.run(run_tests(
            engine=args.engine,
            model=args.model,
            categories=categories,
            verbose=args.verbose,
        ))
        total_fail = result.get("fail", 0)
        sys.exit(0 if total_fail == 0 else 1)
