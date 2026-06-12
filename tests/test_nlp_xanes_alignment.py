"""Regression test: XANES/XAFS energy move + alignment must be shown, not hidden.

User report: "Cu XANES" at 10 keV silently moved the energy to the Cu K-edge
(8.979 keV) and ran a full beamline alignment (IVU gap, DCM, ...) inside
quickXanes -> startExperiment, with no mention in the chat command list.

Fix (server/nlp_agent.py, _postprocess_response): when an experiment function
(quickXanes/quickXafs) implies an energy move >= 1 keV from the current energy,
expose setTargetEnergy + runFullAlignment as EXPLICIT actions before the scan,
and add a notice to the explanation. The experiment's internal energy/align
logic then becomes a no-op (energy already at target), so nothing runs twice.

Run: python tests/test_nlp_xanes_alignment.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import unittest
from nlp_agent import _postprocess_response, _narrate_plan, _keep_domain_commentary


def _resp(fn, args, expl="scan."):
    return {"actions": [{"fn": fn, "args": list(args), "label": "t"}],
            "explanation": expl, "confirmation_required": True}


def _fns(result):
    return [a["fn"] for a in result["actions"]]


class TestXanesAlignmentExposed(unittest.TestCase):
    def test_cu_xanes_far_from_edge_exposes_energy_and_align(self):
        # Current 10 keV, Cu K-edge 8.979 -> dE = 1.02 >= 1 keV
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"]),
                                  current_energy_keV=10.0, user_text="Cu XANES")
        # Contract update (2026-06-12): scan plans end with ONE trailing
        # queueStart (benchmark/paper contract, edge_03/heavyel_01). JS
        # queueStart() no-ops right after a self-starting experiment
        # (QUEUE._exptRunning guard), so it cannot double-execute.
        self.assertEqual(_fns(r), ["setTargetEnergy", "runFullAlignment",
                                   "quickXanes", "queueStart"])
        # The setTargetEnergy must target the edge energy
        self.assertAlmostEqual(r["actions"][0]["args"][0], 8.979, places=3)
        # A proceed/alignment notice must be present
        self.assertIn("align", (r["explanation"] or "").lower())

    def test_cu_xanes_already_near_edge_no_alignment(self):
        # Current 9.0 keV, edge 8.979 -> dE = 0.02 < 1 keV -> the small move
        # IS surfaced (every energy move is shown since the >= 0.01 keV
        # exposure rule) but NO alignment is forced — that is the protective
        # point of this test. (Expectation updated 2026-06-12; the bare
        # ["quickXanes"] shape predated the always-surface rule and the
        # trailing-queueStart contract.)
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"]),
                                  current_energy_keV=9.0, user_text="Cu XANES")
        self.assertNotIn("runFullAlignment", _fns(r))
        self.assertEqual(_fns(r), ["setTargetEnergy", "quickXanes", "queueStart"])

    def test_fe_xafs_far_from_edge_exposes(self):
        # Current 12 keV, Fe K-edge 7.112 -> dE huge -> expose
        r = _postprocess_response(_resp("quickXafs", ["Fe", "K"]),
                                  current_energy_keV=12.0, user_text="Fe XAFS")
        self.assertEqual(_fns(r), ["setTargetEnergy", "runFullAlignment",
                                   "quickXafs", "queueStart"])
        self.assertAlmostEqual(r["actions"][0]["args"][0], 7.112, places=3)

    def test_korean_notice_language(self):
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"], expl="Cu XANES 측정."),
                                  current_energy_keV=10.0, user_text="Cu XANES 측정해줘")
        # Korean notice keyword present
        self.assertIn("정렬", r["explanation"])
        self.assertEqual(_fns(r), ["setTargetEnergy", "runFullAlignment",
                                   "quickXanes", "queueStart"])

    def test_no_double_queue_start(self):
        # Even if the LLM emitted queueStart (possibly mid-plan), the final
        # plan carries exactly ONE queueStart, normalized to the END. The
        # double-execution concern is handled in JS (queueStart() returns
        # immediately after a self-starting experiment via QUEUE._exptRunning;
        # "NLP sends redundant queueStart"). Contract updated 2026-06-12.
        resp = {"actions": [
            {"fn": "quickXanes", "args": ["Cu", "K"], "label": "t"},
            {"fn": "queueStart", "args": [], "label": "t"},
        ], "explanation": "scan.", "confirmation_required": True}
        r = _postprocess_response(resp, current_energy_keV=10.0, user_text="Cu XANES")
        self.assertEqual(_fns(r).count("queueStart"), 1)
        self.assertEqual(_fns(r)[-1], "queueStart")

    def test_raster_not_forced_to_align(self):
        # XRF raster keeps current energy; no implicit edge move -> no forced align
        r = _postprocess_response(_resp("quickRaster", [0.5, 0.5, 21, "siemens_star"]),
                                  current_energy_keV=10.0,
                                  user_text="XRF raster simens star")
        self.assertNotIn("runFullAlignment", _fns(r))
        self.assertEqual(_fns(r), ["quickRaster", "queueStart"])


class TestNarratedExplanationNoContradiction(unittest.TestCase):
    """The displayed explanation is narrated from the FINAL action list, so the
    LLM's procedural prose can never contradict the plan (the user-reported bug:
    'No alignment is needed ... scan will start immediately' shown right above a
    '[Note] ... requires a beamline alignment. Proceed?')."""

    # The exact contradictory prose the model produced (10 - 8.979 = 1.021 keV,
    # which the model wrongly judged as "less than 1 keV").
    BAD_EN = ("Cu K-edge (8.979 keV) XANES scan will be executed with 0.25 eV "
              "resolution. Current energy is 10 keV, which is above the Cu K-edge. "
              "No alignment is needed since the energy change is less than 1 keV. "
              "The scan will start immediately.")

    def test_contradiction_gone_and_note_present(self):
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"], expl=self.BAD_EN),
                                  current_energy_keV=10.0, user_text="Cu XANES")
        self.assertEqual(_fns(r),
                         ["setTargetEnergy", "runFullAlignment",
                          "quickXanes", "queueStart"])
        e = (r["explanation"] or "").lower()
        # The false denials are gone (procedural sentences are not echoed).
        self.assertNotIn("no alignment", e)
        self.assertNotIn("less than 1 kev", e)
        self.assertNotIn("start immediately", e)
        # The authoritative narrated notice is present and consistent with actions.
        self.assertIn("align", e)
        self.assertIn("proceed", e)

    def test_domain_commentary_preserved(self):
        # A non-procedural scientific note must survive into the explanation.
        expl = ("No alignment is needed; the scan will start immediately. "
                "Cu2O and CuO show different near-edge shapes, so oxidation "
                "state can be distinguished.")
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"], expl=expl),
                                  current_energy_keV=10.0, user_text="Cu XANES")
        e = r["explanation"] or ""
        self.assertIn("oxidation", e.lower())        # domain insight kept
        self.assertNotIn("No alignment", e)          # procedure dropped
        self.assertIn("Proceed?", e)                 # narrated notice present

    def test_korean_narration_and_note(self):
        expl = ("에너지 변화가 1 keV 미만이라 정렬이 필요 없습니다. 스캔을 바로 시작합니다. "
                "Cu2O와 CuO는 near-edge 구조가 달라 산화 상태를 구분할 수 있습니다.")
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"], expl=expl),
                                  current_energy_keV=10.0, user_text="Cu XANES 측정해줘")
        e = r["explanation"] or ""
        self.assertIn("정렬", e)                      # narrated [참고] notice
        self.assertIn("진행", e)
        self.assertNotIn("필요 없", e)                 # contradiction gone
        self.assertNotIn("바로 시작", e)

    def test_no_move_case_narrates_without_note(self):
        # Near edge: no forced move, so the narration states the scan but NOT an
        # alignment notice, and never claims "no alignment" either.
        r = _postprocess_response(_resp("quickXanes", ["Cu", "K"], expl="Cu XANES."),
                                  current_energy_keV=9.0, user_text="Cu XANES")
        # Small move surfaced, no alignment, single trailing queueStart
        # (expectation updated 2026-06-12, see TestXanesAlignmentExposed).
        self.assertEqual(_fns(r), ["setTargetEnergy", "quickXanes", "queueStart"])
        e = (r["explanation"] or "").lower()
        self.assertIn("xanes", e)
        self.assertNotIn("proceed", e)               # no energy move -> no notice
        self.assertNotIn("[note]", e)

    def test_narrate_plan_is_pure_function_of_actions(self):
        acts = [{"fn": "setTargetEnergy", "args": [7.112]},
                {"fn": "runFullAlignment", "args": []},
                {"fn": "quickXafs", "args": ["Fe", "K"]}]
        out = _narrate_plan(acts, current_energy_keV=12.0, is_ko=False).lower()
        self.assertIn("7.112", out)
        self.assertIn("alignment", out)
        self.assertIn("fe k-edge xafs", out)
        self.assertIn("proceed", out)

    def test_keep_domain_commentary_drops_procedure_keeps_science(self):
        kept = _keep_domain_commentary(
            "Run a Cu K-edge scan at 8.979 keV with alignment. "
            "CuO indicates a +2 oxidation state.")
        self.assertIn("oxidation", kept.lower())
        self.assertNotIn("keV", kept)
        self.assertNotIn("alignment", kept.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
