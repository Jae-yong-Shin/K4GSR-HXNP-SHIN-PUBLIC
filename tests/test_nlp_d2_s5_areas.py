# test_nlp_d2_s5_areas.py — D2 regression (Phase 1 roadmap, feature/phase1-nlp)
#
# Pins the deterministic mitigations for the ten S5.1 expert-identified
# priority areas (Supplementary S5.1, P1-P10). All checks run WITHOUT an
# LLM: they call _postprocess_response / _validate_domain_rules directly.
#
# Run: python -X utf8 tests/test_nlp_d2_s5_areas.py

import sys
import os
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import nlp_agent as na  # noqa: E402


def _pp(actions, text, e_kev=10.0):
    return na._postprocess_response(
        {"actions": actions, "explanation": "기존 LLM 설명",
         "confirmation_required": True}, e_kev, text)


def _fns(out):
    return [a["fn"] for a in out.get("actions", [])]


FAILURES = []


def check(name, cond, detail=""):
    print("  {:16s} {}  {}".format(name, "PASS" if cond else "FAIL", detail))
    if not cond:
        FAILURES.append(name)


def main():
    print("D2 regression — S5.1 P1-P10 deterministic mitigations")

    # P1: scan plans always state the exposure time (default + user-stated)
    out = _pp([{"fn": "quickRaster", "args": [10, 10, 41]}],
              "철 XRF 맵 10x10 41포인트")
    check("P1_default", "노출 시간: 0.1초" in out["explanation"])
    out = _pp([{"fn": "quickRaster", "args": [5, 5, 41]}],
              "Fe XRF 맵 5x5 41포인트 노출 0.5초로")
    check("P1_user", "0.5" in out["explanation"] and "노출" in out["explanation"])

    # P2: small move crossing the Pt L3 coating boundary triggers alignment
    out = _pp([{"fn": "setTargetEnergy", "args": [11.8]}],
              "에너지를 11.8 keV로 설정해", e_kev=11.2)
    check("P2_boundary", "runFullAlignment" in _fns(out)
          and "코팅 경계" in out["explanation"], _fns(out))
    out = _pp([{"fn": "setTargetEnergy", "args": [12.5]}],
              "에너지를 12.5 keV로 설정해", e_kev=12.0)
    check("P2_sameside", "runFullAlignment" not in _fns(out), _fns(out))

    # P3: Nyquist undersampling / oversampling notes on quickRaster
    out = _pp([{"fn": "quickRaster", "args": [100, 100, 41]}],
              "100x100um 41포인트 XRF 맵")
    check("P3_under", "나이퀴스트" in out["explanation"])
    out = _pp([{"fn": "quickRaster", "args": [1, 1, 201]}],
              "1x1um 201포인트 XRF 맵")
    check("P3_over", "빔 한계" in out["explanation"])

    # P4: multi-element XRF excitation floor (Ni 8.333 -> floor 9.5)
    out = _pp([{"fn": "quickRaster", "args": [10, 10, 41]}],
              "NMC 시료 Ni Mn Co XRF 매핑해줘", e_kev=7.5)
    ste = [a["args"][0] for a in out["actions"]
           if a["fn"] == "setTargetEnergy"]
    check("P4_floor", bool(ste and ste[0] >= 9.3), ste)
    out = _pp([{"fn": "quickRaster", "args": [10, 10, 41]}],
              "NMC 시료 Ni Mn Co XRF 매핑해줘", e_kev=10.0)
    check("P4_ok", "setTargetEnergy" not in _fns(out), _fns(out))

    # P5: sub-micron request confirms the focusing optic
    out = _pp([{"fn": "quickRaster", "args": [5, 5, 41]}],
              "시료의 원소 맵핑을 고해상도로 나노빔으로 측정해줘")
    check("P5_optic", "KB 집속" in out["explanation"])

    # P6: setup-only suppresses queueStart; execute keeps it
    out = _pp([{"fn": "quickEnergyScan", "args": []}],
              "Mo K-edge 에너지 스캔 셋업해줘")
    check("P6_setup", "queueStart" not in _fns(out), _fns(out))
    out = _pp([{"fn": "quickEnergyScan", "args": []}],
              "Mo K-edge 에너지 스캔 시작해줘")
    check("P6_exec", "queueStart" in _fns(out), _fns(out))

    # P7: Pt L-edge scan gets the Rh-stripe recommendation (unstrippable)
    out = _pp([{"fn": "quickXanes", "args": ["Pt", "L3"]}],
              "Pt L3 XANES 측정해줘")
    check("P7_rh", "Rh" in out["explanation"])

    # P8: co-mounted XRF/XRD — no detector-swap warning from Layer 6
    r = na._validate_domain_rules(
        {"actions": [{"fn": "quickRaster", "args": [5, 5, 41]},
                     {"fn": "queueStart", "args": []},
                     {"fn": "setupVirtualExperiment", "args": ["powder_xrd"]},
                     {"fn": "queueStart", "args": []}],
         "explanation": "", "confirmation_required": True}, 10.0)
    check("P8_noswap", "검출기 교체" not in r.get("explanation", ""))
    # ptycho transition warning must SURVIVE (genuine reconfiguration)
    check("P8_ptycho_kept",
          na._SETUP_CHANGE_SEC.get(("xrf", "ptycho"), 0) > 0)

    # P9: pure question strips actions; imperative mix keeps them
    out = _pp([{"fn": "quickXanes", "args": ["Fe", "K"]}],
              "Fe XANES 하려면 몇 keV로 가야 해?")
    check("P9_strip", _fns(out) == [] and
          out["confirmation_required"] is False, _fns(out))
    out = _pp([{"fn": "quickXanes", "args": ["Fe", "K"]}],
              "Fe XANES 측정해줘")
    check("P9_imperative", "quickXanes" in _fns(out), _fns(out))

    # P10: powder XRD plan states the 2-theta / q-range
    out = _pp([{"fn": "setupVirtualExperiment", "args": ["powder_xrd"]}],
              "분말 XRD 측정 시작해줘", e_kev=15.0)
    check("P10_qrange", "q ≈" in out["explanation"]
          and "2θ" in out["explanation"])

    # Notes must NOT fire on non-scan plans
    out = _pp([{"fn": "motorSetUI", "args": ["m1", "m1_pitch", 2.5]}],
              "M1 피치를 2.5로")
    check("neg_motor", "노출" not in out["explanation"]
          and "나이퀴스트" not in out["explanation"])

    print()
    if FAILURES:
        print("FAILED:", FAILURES)
        sys.exit(1)
    print("ALL PASS (17/17)")


if __name__ == "__main__":
    main()
