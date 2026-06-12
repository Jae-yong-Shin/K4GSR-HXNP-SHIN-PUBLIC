# test_nlp_d3_recovery.py — D3 regression (Phase 1 roadmap, feature/phase1-nlp)
#
# Pins the deterministic post-processing fixes for the 4/228 benchmark
# failures cited in the JSR manuscript (¶63):
#   workflow_01  empty actions on sequential Ti+Sr XANES (Ti out of range)
#   vexp_03      empty actions on "2D XRF 맵핑 실험 셋업" (no element named)
#   opt_03       confirmation_required=False despite state-changing action
#   batt_04      prompt-level fix (few-shot); here we only pin that
#                post-processing does not break an optimizeBeamline-first plan
# Plus hardening: Korean element-name recovery, multi-element ordering.
#
# No LLM required — calls _postprocess_response directly (Layer 3-7 are
# deterministic). Full-benchmark rerun (vLLM) is tracked separately in
# docs/tasks/TASK_PHASE1_ROADMAP.md.
#
# Run: python -X utf8 tests/test_nlp_d3_recovery.py

import sys
import os
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import nlp_agent as na  # noqa: E402


def _pp(resp, text, e_kev=10.0):
    return na._postprocess_response(dict(resp), e_kev, text)


def _fns(out):
    return [a["fn"] for a in out.get("actions", [])]


FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print("  {:14s} {}  {}".format(name, status, detail))
    if not cond:
        FAILURES.append(name)


def main():
    print("D3 regression — deterministic NLP post-processing")

    # workflow_01: in-range element (Sr) must be recovered from empty actions
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "SrTiO3 시료에서 Ti K-edge XANES 하고 나서 Sr K-edge XANES도 해주세요.")
    check("workflow_01",
          any(a["fn"] == "quickXanes" and "Sr" in str(a["args"])
              for a in out["actions"])
          and not any("Ti" in str(a.get("args")) for a in out["actions"]
                      if a["fn"] == "quickXanes")
          and out.get("confirmation_required") is True,
          _fns(out))

    # vexp_03: XRF preset recovered without a named element
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "2D XRF 맵핑 실험 셋업")
    check("vexp_03",
          any(a["fn"] == "quickRaster" for a in out["actions"])
          and out.get("confirmation_required") is True,
          _fns(out))

    # opt_03: confirmation flag enforced when state-changing actions present
    out = _pp({"actions": [{"fn": "optimizeBeamline",
                            "args": [{"technique": "xanes", "element": "Ti",
                                      "edge": "K", "ppm": 100000}]}],
               "explanation": "", "confirmation_required": False},
              "Ti K-edge XANES 하려는데 시료가 SrTiO3 분말이야")
    check("opt_03", out.get("confirmation_required") is True, _fns(out))

    # batt_04 (post-processing side): optimizeBeamline-first plan preserved
    out = _pp({"actions": [{"fn": "optimizeBeamline",
                            "args": [{"technique": "xrf", "element": "Cu",
                                      "edge": "K", "ppm": 10}]}],
               "explanation": "", "confirmation_required": True},
              "양극재에 구리 오염이 있는지 확인해주세요. 10ppm 수준이에요.")
    check("batt_04_pp",
          any(a["fn"] == "optimizeBeamline" for a in out["actions"])
          and out.get("confirmation_required") is True,
          _fns(out))

    # Hardening: Korean element name recovery ("철" -> Fe)
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "철 XANES 측정해줘")
    check("ko_recovery",
          any(a["fn"] == "quickXanes" and "Fe" in str(a["args"])
              for a in out["actions"]),
          _fns(out))

    # Hardening: multi-element recovery preserves text order
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "구리 XANES 하고 아연 XANES도 해줘")
    xan = [str(a["args"]) for a in out["actions"] if a["fn"] == "quickXanes"]
    check("multi_order", xan == ["['Cu', 'K']", "['Zn', 'K']"], xan)

    # opt_02 backstop: optimization request recovers optimizeBeamline with
    # the priority taken from the wording (NOT a blind quickRaster)
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "철 시료인데 가장 좋은 분해능으로 XRF 맵핑하고 싶어")
    check("opt02_priority",
          any(a["fn"] == "optimizeBeamline"
              and a["args"] and isinstance(a["args"][0], dict)
              and a["args"][0].get("priority") == "resolution"
              and a["args"][0].get("element") == "Fe"
              for a in out["actions"]),
          _fns(out))

    # vexp_02 backstop: powder XRD preset recovered from empty response
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "분말 XRD 실험 시작해줘")
    check("vexp02_powder",
          any(a["fn"] == "setupVirtualExperiment"
              and "powder_xrd" in str(a.get("args"))
              for a in out["actions"])
          and out.get("confirmation_required") is True,
          _fns(out))

    # motor_03 backstop: unit-less "시료 X를 100 이동해" recovers a RELATIVE
    # move (owner convention 2026-06-12; unit-less sample move = um -> mm/1000)
    out = _pp({"actions": [], "explanation": "단위를 알려주세요",
               "confirmation_required": False},
              "시료 X를 100 이동해")
    check("motor03_rel",
          any(a["fn"] == "motorMoveRelUI"
              and a["args"][:2] == ["sample", "sample_cx"]
              and abs(a["args"][2] - 0.1) < 1e-12
              for a in out["actions"])
          and out.get("confirmation_required") is True,
          _fns(out))

    # motor_03 guard: absolute marker (위치로) must NOT trigger the backstop
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "시료 X를 100 위치로 이동해")
    check("motor03_abs_guard",
          not any(a["fn"] == "motorMoveRelUI" for a in out["actions"]),
          _fns(out))

    # analysis_01 backstop: oxidation-state intent (no technique word)
    # recovers Fe K XANES
    out = _pp({"actions": [], "explanation": "", "confirmation_required": False},
              "이 시료의 Fe 산화 상태를 확인하고 싶어요")
    check("analysis01_ox",
          any(a["fn"] == "quickXanes" and "Fe" in str(a["args"])
              for a in out["actions"])
          and out.get("confirmation_required") is True,
          _fns(out))

    # Guard regressions: energy-set-only request must not become a scan
    out = _pp({"actions": [{"fn": "quickXanes", "args": ["Cu", "K"]}],
               "explanation": "", "confirmation_required": True},
              "에너지를 12 keV로 설정해")
    check("energyset_guard",
          not any(a["fn"] in ("quickXanes", "quickXafs")
                  for a in out["actions"]),
          _fns(out))

    print()
    if FAILURES:
        print("FAILED:", FAILURES)
        sys.exit(1)
    print("ALL PASS (12/12)")


if __name__ == "__main__":
    main()
