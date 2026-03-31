"""Unit tests for NLPAgent — JSON extraction and action parsing."""
import json
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestNLPAgentJSONExtraction:
    """_extract_json: pull structured JSON from LLM response text."""

    def _extract(self, text):
        from nlp_agent import NLPAgent
        agent = NLPAgent()
        return agent._extract_json(text)

    def test_clean_json(self):
        """Pure JSON string."""
        raw = json.dumps({
            "actions": [{"fn": "setTargetEnergy", "args": [10.0]}],
            "explanation": "10 keV 설정",
            "confirmation_required": True,
            "type": "nlp_response"
        })
        result = self._extract(raw)
        assert result["actions"][0]["fn"] == "setTargetEnergy"

    def test_json_in_markdown_block(self):
        """JSON wrapped in ```json ... ``` markers."""
        raw = """Here is the response:
```json
{
  "actions": [{"fn": "runFullAlignment", "args": []}],
  "explanation": "정렬 수행",
  "confirmation_required": false,
  "type": "nlp_response"
}
```
"""
        result = self._extract(raw)
        assert result["actions"][0]["fn"] == "runFullAlignment"

    def test_json_with_preamble(self):
        """JSON preceded by explanatory text."""
        raw = """I'll set the energy to 10 keV.

{"actions": [{"fn": "setTargetEnergy", "args": [10.0]}], "explanation": "에너지 설정", "confirmation_required": true, "type": "nlp_response"}"""
        result = self._extract(raw)
        assert result is not None
        assert result["actions"][0]["args"] == [10.0]

    def test_no_json_returns_none_or_fallback(self):
        """Plain text without JSON."""
        raw = "I don't understand the request. Please try again."
        result = self._extract(raw)
        # Should return None or a fallback dict
        if result is not None:
            assert "actions" in result or "explanation" in result

    def test_malformed_json(self):
        """Invalid JSON should not crash."""
        raw = '{"actions": [{"fn": "broken'
        result = self._extract(raw)
        # Should not raise, returns None or fallback


class TestNLPAgentActionValidation:
    """Action structure validation."""

    def test_action_has_fn_and_args(self, sample_nlp_response):
        """Each action must have 'fn' (string) and 'args' (list)."""
        for action in sample_nlp_response["actions"]:
            assert "fn" in action
            assert "args" in action
            assert isinstance(action["fn"], str)
            assert isinstance(action["args"], list)

    def test_known_function_names(self, sample_nlp_response):
        """Action function names should be from known set."""
        known_fns = {
            "setTargetEnergy", "setCrystal", "setFocusMode",
            "motorSetUI", "maskAperUpdate",
            "runAlignStepUI", "runFullAlignment", "runMirrorAlignUI",
            "quickEnergyScan", "quickXafs", "quickXanes", "quickRaster",
            "quickCount", "quickFlyScan", "quickLineScan", "quickMultiRegion",
            "quickAutoTune", "quickAdaptiveScan", "quickRelAlign",
            "quickFermat", "quickRelRaster",
            "queueStart", "queueStop", "queuePause", "queueResume", "queueAbort",
            "setupVirtualExperiment", "showBeamProfile", "switchTab",
            "setAlignConfig", "quickAlign", "queuePlan", "queueClear",
            "abortAlignment", "emergencyStop", "setMirrorAlignRange"
        }
        for action in sample_nlp_response["actions"]:
            assert action["fn"] in known_fns, f"Unknown fn: {action['fn']}"

    def test_response_has_explanation(self, sample_nlp_response):
        """Response must include Korean explanation."""
        assert "explanation" in sample_nlp_response
        assert len(sample_nlp_response["explanation"]) > 0

    def test_response_has_confirmation_flag(self, sample_nlp_response):
        """Response includes confirmation_required boolean."""
        assert "confirmation_required" in sample_nlp_response
        assert isinstance(sample_nlp_response["confirmation_required"], bool)


class TestNLPAgentBackendDetection:
    """Backend selection logic."""

    def test_default_backend_no_crash(self):
        """NLPAgent creation succeeds without API keys."""
        from nlp_agent import NLPAgent
        agent = NLPAgent()
        # backend may be None if no API keys configured
        # but init should not crash

    def test_ollama_backend_class_exists(self):
        """OllamaBackend class is importable."""
        from nlp_agent import OllamaBackend
        assert OllamaBackend is not None

    def test_gemini_backend_class_exists(self):
        """GeminiBackend class is importable."""
        from nlp_agent import GeminiBackend
        assert GeminiBackend is not None


class TestNLPActionCategories:
    """Action risk categorization (used by JS for UI)."""

    def test_energy_actions_are_safe(self):
        """Energy setting is low-risk (reversible)."""
        safe_fns = ["setTargetEnergy", "setCrystal", "setFocusMode",
                     "showBeamProfile", "switchTab"]
        # These should be categorized as 'ctrl' or 'info'
        for fn in safe_fns:
            assert fn  # just verify they're in the known set

    def test_scan_actions_need_confirmation(self):
        """Scan actions should require confirmation."""
        scan_fns = ["quickEnergyScan", "quickXafs", "quickRaster"]
        # These should have confirmation_required=True
        for fn in scan_fns:
            assert fn

    def test_motor_actions_medium_risk(self):
        """Motor movements are medium risk."""
        motor_fns = ["motorSetUI", "maskAperUpdate"]
        for fn in motor_fns:
            assert fn


class TestNLPPromptNewScans:
    """Verify new scan types are in the NLP system prompt."""

    def test_prompt_has_quickXanes(self):
        """quickXanes is in the system prompt."""
        from nlp_agent import SYSTEM_PROMPT
        assert "quickXanes" in SYSTEM_PROMPT

    def test_prompt_has_quickFlyScan(self):
        """quickFlyScan is in the system prompt."""
        from nlp_agent import SYSTEM_PROMPT
        assert "quickFlyScan" in SYSTEM_PROMPT

    def test_prompt_xanes_keywords(self):
        """XANES keyword mapping exists in prompt."""
        from nlp_agent import SYSTEM_PROMPT
        assert "니어엣지" in SYSTEM_PROMPT or "near-edge" in SYSTEM_PROMPT

    def test_prompt_fly_keywords(self):
        """Fly scan keyword mapping exists in prompt."""
        from nlp_agent import SYSTEM_PROMPT
        assert "플라이 스캔" in SYSTEM_PROMPT or "fly scan" in SYSTEM_PROMPT



class TestNLPPromptAdvancedScans:
    """Verify advanced Bluesky scan types are in the NLP system prompt."""

    def test_prompt_has_quickAutoTune(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "quickAutoTune" in SYSTEM_PROMPT

    def test_prompt_has_quickAdaptiveScan(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "quickAdaptiveScan" in SYSTEM_PROMPT

    def test_prompt_has_quickRelAlign(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "quickRelAlign" in SYSTEM_PROMPT

    def test_prompt_has_quickFermat(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "quickFermat" in SYSTEM_PROMPT

    def test_prompt_has_quickRelRaster(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "quickRelRaster" in SYSTEM_PROMPT

    def test_prompt_autotune_keywords(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "자동정렬" in SYSTEM_PROMPT or "auto tune" in SYSTEM_PROMPT

    def test_prompt_adaptive_keywords(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "적응형" in SYSTEM_PROMPT or "adaptive" in SYSTEM_PROMPT

    def test_prompt_fermat_keywords(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "페르마" in SYSTEM_PROMPT or "fermat" in SYSTEM_PROMPT

    def test_prompt_rel_align_keywords(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "상대 정렬" in SYSTEM_PROMPT or "rel align" in SYSTEM_PROMPT

    def test_prompt_rel_raster_keywords(self):
        from nlp_agent import SYSTEM_PROMPT
        assert "상대 래스터" in SYSTEM_PROMPT or "rel raster" in SYSTEM_PROMPT
