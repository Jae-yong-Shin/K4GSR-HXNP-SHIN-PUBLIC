#!/usr/bin/env python3
"""
translate_i18n.py -- Build-time UI string translation generator.

Uses Claude API to translate I18N_STRINGS.en -> 6 additional languages,
referencing server/i18n/glossary.json for domain term handling.

Usage:
    python Scripts/translate_i18n.py [--api-key KEY] [--out output.json]

Output: JSON dict keyed by language code (de, fr, es, th, hi, ar),
each containing the translated I18N key-value pairs.
These can be pasted into js/shared/03_i18n.js I18N_STRINGS.

Requirements:
    pip install anthropic
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = PROJECT_ROOT / "server" / "i18n" / "glossary.json"

# English source strings (extracted from 03_i18n.js I18N_STRINGS.en)
EN_STRINGS = {
    "tab_undulator": "IVU", "tab_dcm": "DCM", "tab_optics": "Optics",
    "tab_motors": "Motors", "tab_mask": "Mask", "tab_measure": "Measure",
    "tab_align": "Align", "tab_compare": "Comp.", "tab_epics": "EPICS",
    "tab_bluesky": "BS", "tab_guide": "Guide", "tab_chat": "Chat",
    "tab_expt": "Expt",
    "hdr_theme": "Color Theme", "hdr_layout": "Layout",
    "hdr_mcrays": "MC Rays", "hdr_grid": "Grid Resolution",
    "hdr_language": "Language",
    "theme_light": "Light (Default)", "theme_dark": "Dark",
    "theme_dark2": "Dark 2", "theme_deuter": "Deuteranopia",
    "theme_protan": "Protanopia", "theme_tritan": "Tritanopia",
    "themedesc_light": "Clean white background",
    "themedesc_dark": "High-contrast dark theme",
    "themedesc_dark2": "Muted dark theme",
    "themedesc_deuter": "Safe for red-green color blindness",
    "themedesc_protan": "Safe for red color blindness",
    "themedesc_tritan": "Safe for blue-yellow color blindness",
    "layout_standard": "Standard", "layout_wide": "Wide View",
    "layout_compact": "Compact", "layout_focus": "Focus",
    "layoutdesc_standard": "Full layout (sidebar 320px)",
    "layoutdesc_wide": "Hide sidebar, maximize view",
    "layoutdesc_compact": "Narrow sidebar (220px)",
    "layoutdesc_focus": "Beamline only, hide panels",
    "mcrays_fast": "Fast -- preview", "mcrays_normal": "Normal -- medium quality",
    "mcrays_default": "Default -- high statistics", "mcrays_precise": "Precise -- slow",
    "mcrays_best": "Best quality -- very slow",
    "grid_standard": "Default -- fast rendering",
    "grid_highres": "4x finer -- small beam detail",
    "btn_estop": "E-STOP", "btn_reset": "Reset",
    "btn_start": "Start", "btn_stop": "Stop",
    "btn_save": "Save", "btn_close": "Close",
    "btn_apply": "Apply", "btn_cancel": "Cancel",
    "panel_source": "Source Parameters",
    "panel_beamline": "Beamline Overview",
    "panel_profile": "Beam Profile",
    "panel_spectrum": "Spectrum",
    "mode_virtual": "Virtual", "mode_real": "Real", "mode_dual": "Dual",
}

TARGET_LANGS = {
    "de": "German (Deutsch)",
    "fr": "French (Francais)",
    "es": "Spanish (Espanol)",
    "th": "Thai",
    "hi": "Hindi",
    "ar": "Arabic",
}


def load_glossary():
    """Load domain glossary for translation context."""
    if GLOSSARY_PATH.exists():
        with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def translate_with_claude(api_key: str, glossary: dict) -> dict:
    """Use Claude API to translate EN_STRINGS to all target languages."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: 'anthropic' package not installed. Run: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    glossary_text = json.dumps(glossary, indent=2, ensure_ascii=False)
    source_text = json.dumps(EN_STRINGS, indent=2, ensure_ascii=False)

    prompt = f"""Translate the following English UI strings into these languages: {', '.join(f'{v} ({k})' for k, v in TARGET_LANGS.items())}.

## Domain Glossary (CRITICAL)
Terms marked "keep": true must NOT be translated (e.g., DCM, XANES, EPICS, keV).
{glossary_text}

## Source strings (English)
{source_text}

## Rules
1. Keep scientific/technical terms as-is per glossary (DCM, IVU, XANES, XRF, XRD, EPICS, BS, keV, mrad, MC)
2. Keep units and numbers unchanged
3. Keep "--" separators in description strings
4. Keep tab labels short (1-2 words)
5. For color blindness terms (deuteranopia, protanopia, tritanopia), use the standard medical term in each language
6. Return ONLY a JSON object with language codes as keys and translated dicts as values
7. No markdown formatting, just raw JSON

Output format:
{{"de": {{"tab_undulator": "IVU", ...}}, "fr": {{...}}, ...}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse JSON from response
    text = response.content[0].text.strip()
    # Remove markdown code block if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description="Generate i18n translations using Claude API")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"),
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--out", default="i18n_translations.json",
                        help="Output JSON file path (default: i18n_translations.json)")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: No API key provided. Use --api-key or set ANTHROPIC_API_KEY")
        sys.exit(1)

    glossary = load_glossary()
    print(f"Loaded glossary with {len(glossary)} terms")
    print(f"Translating {len(EN_STRINGS)} UI strings to {len(TARGET_LANGS)} languages...")

    translations = translate_with_claude(args.api_key, glossary)

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(translations, f, indent=2, ensure_ascii=False)

    print(f"Translations saved to {out_path}")
    print(f"Languages: {', '.join(translations.keys())}")
    for lang, strings in translations.items():
        print(f"  {lang}: {len(strings)} keys")


if __name__ == "__main__":
    main()
