"""Regression test: quickRaster sample preset (4th arg) repair.

Bug: when a user names a sample (e.g. "simens star"), the LLM frequently emits
quickRaster(x, y, n) WITHOUT the 4th `presetKey` argument, so the JS falls back
to its default sample and the requested one is silently ignored.

Fix lives in server/nlp_agent.py:
  - _resolve_sample_preset(text): deterministic sample-name -> preset-key resolver
  - _postprocess_response(...): injects/overrides quickRaster args[3] from user text

These run on EVERY backend (ollama/groq/vLLM/gemini/claude) because each parser
funnels through _postprocess_response. This test needs no LLM — it exercises the
deterministic layer directly.

Run: python tests/test_nlp_quickRaster_sample.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import unittest
from nlp_agent import (
    _resolve_sample_preset,
    _postprocess_response,
    _user_specified_fov,
    _XRF_PRESET_KEYS,
)


def _raster(args):
    return {"actions": [{"fn": "quickRaster", "args": list(args), "label": "t"}],
            "explanation": "", "confirmation_required": True}


def _first_args(result):
    return result["actions"][0]["args"]


class TestSampleResolver(unittest.TestCase):
    def test_canonical_and_aliases(self):
        cases = {
            # English (incl. the user's actual misspelling "simens")
            "XRF raster scan, simens star, 10 keV": "siemens_star",
            "raster scan on Siemens-star, 0.5 um FOV": "siemens_star",
            "siemens_star resolution target": "siemens_star",
            "XRF map of battery cathode": "battery_nmc622",
            "NMC622 multi-element XRF": "battery_nmc622",
            "biological cell imaging": "biological_cell",
            "geological thin section": "geological_section",
            "catalyst nanoparticle map": "catalyst_nanoparticle",
            "environmental fly ash particle": "environmental_particle",
            "semiconductor IC cross-section": "semiconductor_ic",
            "integrated circuit raster": "semiconductor_ic",
            # Korean (substring match; agglutinative suffixes allowed)
            "지멘스 스타 XRF 맵핑": "siemens_star",
            "반도체 시료 XRF 이미징": "semiconductor_ic",
            "배터리 양극재를 측정": "battery_nmc622",
            "촉매 나노입자 맵": "catalyst_nanoparticle",
        }
        for text, expected in cases.items():
            self.assertEqual(_resolve_sample_preset(text), expected,
                             msg="text=%r" % text)

    def test_no_false_positives(self):
        # No sample named -> None (must NOT guess a preset)
        for text in [
            "XRF raster scan 1 um area, 21x21",
            "atomic resolution alignment",     # 'ic'/'resolution' must not trigger
            "set energy to 12 keV",
            "high resolution scan",            # 'resolution' alone != siemens_star
            "",
        ]:
            self.assertIsNone(_resolve_sample_preset(text), msg="text=%r" % text)

    def test_all_keys_resolvable_by_canonical_name(self):
        for key in _XRF_PRESET_KEYS:
            self.assertEqual(_resolve_sample_preset("run " + key), key)


class TestPostprocessInjection(unittest.TestCase):
    def test_fill_missing_sample(self):
        # No scan size in the request -> sample preset injected AND the FOV is
        # defaulted to the siemens_star recommended FOV (30 um), since the
        # fixed-size phantom would barely show up at the LLM's 0.5 um guess.
        r = _postprocess_response(_raster([0.5, 0.5, 21]),
                                  current_energy_keV=0,
                                  user_text="XRF raster scan, simens star, 10 keV")
        self.assertEqual(_first_args(r), [30.0, 30.0, 21, "siemens_star"])

    def test_override_wrong_sample(self):
        # LLM guessed semiconductor_ic but user clearly said siemens star
        r = _postprocess_response(_raster([0.5, 0.5, 21, "semiconductor_ic"]),
                                  current_energy_keV=0,
                                  user_text="raster scan on Siemens star")
        self.assertEqual(_first_args(r)[3], "siemens_star")

    def test_keep_llm_sample_when_text_ambiguous(self):
        # User text names no sample -> trust the LLM's existing valid key
        r = _postprocess_response(_raster([0.5, 0.5, 21, "battery_nmc622"]),
                                  current_energy_keV=0,
                                  user_text="2D raster, 21x21")
        self.assertEqual(_first_args(r)[3], "battery_nmc622")

    def test_no_sample_no_injection(self):
        r = _postprocess_response(_raster([1.0, 1.0, 21]),
                                  current_energy_keV=0,
                                  user_text="raster scan 1 um area, 21x21")
        self.assertEqual(_first_args(r), [1.0, 1.0, 21])  # unchanged, still 3 args

    def test_korean_request(self):
        # No size given -> preset injected + FOV defaulted to recommended (30 um).
        r = _postprocess_response(_raster([0.5, 0.5, 41]),
                                  current_energy_keV=0,
                                  user_text="지멘스 스타로 XRF 래스터 스캔")
        self.assertEqual(_first_args(r), [30.0, 30.0, 41, "siemens_star"])

    def test_fov_defaults_to_recommended_when_no_size(self):
        # battery_nmc622 recommended FOV is 30 um (the full cathode region).
        r = _postprocess_response(_raster([0.5, 0.5, 64, "battery_nmc622"]),
                                  current_energy_keV=0,
                                  user_text="XRF map of a battery cathode")
        self.assertEqual(_first_args(r), [30.0, 30.0, 64, "battery_nmc622"])

    def test_explicit_fov_is_preserved(self):
        # User states an explicit size -> keep their FOV, only inject the preset.
        for txt, fov in [
            ("siemens star XRF, 2 um FOV", [2.0, 2.0]),
            ("지멘스 스타 500 nm 영역 스캔", [0.5, 0.5]),
            ("siemens star scan, field of view 5 um", [5.0, 5.0]),
        ]:
            r = _postprocess_response(_raster(fov + [21]),
                                      current_energy_keV=0, user_text=txt)
            self.assertEqual(_first_args(r), fov + [21, "siemens_star"],
                             msg="text=%r" % txt)

    def test_no_preset_no_fov_change(self):
        # No sample resolved -> neither preset nor FOV is touched.
        r = _postprocess_response(_raster([0.5, 0.5, 21]),
                                  current_energy_keV=0,
                                  user_text="2D raster scan, 21x21 points")
        self.assertEqual(_first_args(r), [0.5, 0.5, 21])

    def test_same_fov_keyword_does_not_suppress_default(self):
        # Reported bug: "SAME FOV BUT 101 X 101" contains the word "FOV" but no
        # number, so it must NOT count as a user-specified size. The LLM (whose
        # stale context guessed 0.5) emits 0.5; the postprocess must still snap
        # the FOV to the siemens_star recommended 30 um (not leave it at 0.5).
        for txt in ["SAME FOV BUT 101 X 101", "same fov, higher resolution",
                    "동일 FOV 로 101x101"]:
            r = _postprocess_response(_raster([0.5, 0.5, 101, "siemens_star"]),
                                      current_energy_keV=0, user_text=txt)
            self.assertEqual(_first_args(r), [30.0, 30.0, 101, "siemens_star"],
                             msg="text=%r" % txt)


    def test_explanation_fov_stated_from_actions_not_llm_prose(self):
        # The explanation is now narrated from the FINAL action list (_narrate_plan),
        # so the LLM's stale pre-override FOV prose ("0.5x0.5 µm area") cannot leak:
        # the procedural sentence is dropped and the narrator states the real FOV.
        r = _postprocess_response(
            {"actions": [{"fn": "quickRaster", "args": [0.5, 0.5, 21, "siemens_star"],
                          "label": "t"}],
             "explanation": "Scanning 0.5x0.5 µm area with 21x21 points at 10 keV, ~50 nm beam.",
             "confirmation_required": True},
            current_energy_keV=0, user_text="XRF raster scan, simens star, 10 keV")
        expl = r["explanation"]
        self.assertNotIn("0.5", expl)                 # stale LLM FOV figure gone
        self.assertIn("30", expl)                     # actual FOV (30 x 30 um) narrated
        self.assertIn("siemens_star", expl)           # sample stated from the action
        self.assertEqual(r["actions"][0]["args"][:2], [30.0, 30.0])


class TestFovSizeDetection(unittest.TestCase):
    def test_bare_fov_word_is_not_a_size(self):
        for txt in ["same FOV", "동일 FOV", "field of view", "그 FOV 그대로",
                    "SAME FOV BUT 101 X 101", "keep the field of view"]:
            self.assertFalse(_user_specified_fov(txt), msg="text=%r" % txt)

    def test_numeric_size_is_detected(self):
        for txt in ["30 um", "500nm", "5 µm", "FOV 2um", "fov 5",
                    "field of view 5 um", "시야 30um", "5마이크론"]:
            self.assertTrue(_user_specified_fov(txt), msg="text=%r" % txt)

    def test_energy_and_points_are_not_sizes(self):
        for txt in ["10 keV", "21x21", "21 points", "101 X 101",
                    "high resolution", "넓은 영역"]:
            self.assertFalse(_user_specified_fov(txt), msg="text=%r" % txt)

    def test_malformed_arity_untouched(self):
        # Fewer than 3 args: don't fabricate geometry, just leave it
        r = _postprocess_response(_raster([0.5]),
                                  current_energy_keV=0,
                                  user_text="siemens star raster")
        self.assertEqual(_first_args(r), [0.5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
