"""NLP Agent — Multi-backend natural language parser for beamline control.

Supports four LLM backends (configured via NLP_ENGINE in .env):
  - ollama:  Local LLM via Ollama (free, offline after model download)
  - gemini:  Google Gemini API (free tier available)
  - groq:    Groq API (free tier — Llama 3.3 70B, very fast)
  - claude:  Anthropic Claude API (paid)

Converts user requests (Korean/English) into structured JSON action commands
that the JS client can execute after user confirmation.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List

log = logging.getLogger("nlp-agent")

# Try loading dotenv for local development
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Optional imports — each backend gracefully skips if not installed
try:
    import anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False

try:
    import httpx
    _HTTPX_OK = True
except ImportError:
    _HTTPX_OK = False

try:
    import google.generativeai as genai
    _GEMINI_OK = True
except ImportError:
    _GEMINI_OK = False


# ══════════════════════════════════════════════════════════════════════
# Layer 1 (Pre-processing) & Layer 3 (Post-processing) — shared data
# ══════════════════════════════════════════════════════════════════════

import re
import unicodedata

# ══════════════════════════════════════════════════════════════════════
# Language Auto-Detection — detect language from user input text
# ══════════════════════════════════════════════════════════════════════

def _detect_language(text: str) -> str:
    """Detect language from user input text.

    Returns 'ko', 'en', 'ja', 'zh', or fallback 'en'.
    Uses Unicode script analysis — no external dependencies.
    """
    # Count characters by script (ignore ASCII digits, punctuation, whitespace)
    counts = {"ko": 0, "ja": 0, "zh": 0, "latin": 0}
    for ch in text:
        cp = ord(ch)
        # Korean: Hangul Syllables + Jamo
        if 0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
            counts["ko"] += 1
        # Japanese: Hiragana + Katakana
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            counts["ja"] += 1
        # CJK Unified Ideographs (shared by ja/zh, counted as zh)
        elif 0x4E00 <= cp <= 0x9FFF:
            counts["zh"] += 1
        # Latin letters
        elif ch.isalpha():
            counts["latin"] += 1

    # If Korean characters present, it's Korean (even if mixed with English terms)
    if counts["ko"] > 0:
        return "ko"
    # Japanese hiragana/katakana present
    if counts["ja"] > 0:
        return "ja"
    # CJK ideographs without kana → Chinese
    if counts["zh"] > 0:
        return "zh"
    # Default: English (Latin or no script detected)
    return "en"


# Absorption edge database: element -> {edge: energy_keV}
_EDGE_DB = {
    "Ti": {"K": 4.966}, "V": {"K": 5.470}, "Cr": {"K": 5.989},
    "Mn": {"K": 6.539}, "Fe": {"K": 7.112}, "Co": {"K": 7.709},
    "Ni": {"K": 8.333}, "Cu": {"K": 8.979}, "Zn": {"K": 9.659},
    "Ga": {"K": 10.367}, "Ge": {"K": 11.103}, "As": {"K": 11.867},
    "Se": {"K": 12.658}, "Sr": {"K": 16.105}, "Mo": {"K": 20.000},
    "Ag": {"K": 25.514},
    "C": {"K": 0.284}, "N": {"K": 0.400}, "O": {"K": 0.543},
    "Mg": {"K": 1.303}, "Al": {"K": 1.560},
    "Si": {"K": 1.839}, "P": {"K": 2.145}, "S": {"K": 2.472},
    "Ca": {"K": 4.038}, "W": {"K": 69.525, "L3": 10.207},
    "Pt": {"K": 78.395, "L3": 11.564}, "Au": {"K": 80.725, "L3": 11.919},
    "Pb": {"K": 88.005, "L3": 13.035}, "Ba": {"L3": 5.247},
    "La": {"L3": 5.483}, "Ce": {"K": 40.443, "L3": 5.723},
}

# ══════════════════════════════════════════════════════════════════════
# XRF sample preset resolution (quickRaster 4th arg `presetKey`)
# ══════════════════════════════════════════════════════════════════════
# Canonical preset keys are defined in js/experiment/01_xray_data.js
# (var XRF_SAMPLE_PRESETS). The 4th positional arg of quickRaster selects the
# sample; the LLM frequently omits it, so the JS falls back to its default
# sample and silently ignores the one the user named. We resolve the user's
# stated sample here and repair the arg deterministically (Layer 3).
_XRF_PRESET_KEYS = (
    "semiconductor_ic", "battery_nmc622", "geological_section",
    "biological_cell", "catalyst_nanoparticle", "environmental_particle",
    "siemens_star",
)

# Free-text mentions (EN/KO + common misspellings) -> canonical preset key.
# Order matters: distinctive samples first; the broad "semiconductor" group last.
# ASCII aliases match on word boundaries (avoids "atomic" -> "ic"); non-ASCII
# (Korean) match as substrings, since Korean is agglutinative and word
# boundaries would miss particle-suffixed forms ("반도체를", "양극재에서").
_SAMPLE_ALIASES = [
    ("siemens_star",           ["siemens star", "siemens-star", "simens star",
                                 "simens-star", "star pattern", "resolution test",
                                 "resolution target", "지멘스", "분해능"]),
    ("battery_nmc622",         ["nmc622", "nmc 622", "nmc", "battery cathode",
                                 "cathode", "battery", "양극재", "양극", "배터리",
                                 "이차전지", "리튬전지"]),
    ("geological_section",     ["geological", "geology", "thin section", "rock",
                                 "mineral", "지질", "암석", "광물", "박편"]),
    ("biological_cell",        ["biological", "bio cell", "freeze-dried",
                                 "freeze dried", "cell", "cells", "세포", "생체",
                                 "바이오"]),
    ("catalyst_nanoparticle",  ["catalyst", "catalytic", "nanoparticle",
                                 "nano-particle", "nanoparticles", "촉매", "나노입자"]),
    ("environmental_particle", ["environmental", "fly ash", "fly-ash", "aerosol",
                                 "particulate", "pollutant", "pollution", "환경",
                                 "비산재", "미세먼지", "분진"]),
    ("semiconductor_ic",       ["semiconductor", "semi-conductor",
                                 "integrated circuit", "interconnect", "ic chip",
                                 "반도체", "집적회로"]),
]


# Recommended full scan FOV (um) per preset -- single source of truth lives in
# phantoms.py. When the user names a sample but gives no scan size, the
# quickRaster FOV defaults to this so the fixed-physical-size phantom is framed
# sensibly (a generic ~0.5 um guess would only show a tiny corner of, e.g., a
# 30 um battery cathode or a 20 um cell).
try:
    from sim_engines.phantoms import RECOMMENDED_FOV_UM as _RECOMMENDED_FOV
except Exception:   # pragma: no cover - phantoms is always importable server-side
    _RECOMMENDED_FOV = {}

# A scan size/FOV is "specified" only if the text carries a NUMBER tied to a
# length unit ("30um", "500 nm") or to an explicit FOV phrase ("FOV 2um",
# "field of view 5", "5 um fov"). The bare word "FOV" with NO number must NOT
# count: "same FOV", "동일 FOV" are RELATIVE references (keep the previous /
# recommended framing), not a new size. Energy ("10 keV") and point counts
# ("21x21", "21 points") are not sizes either.
_FOV_SIZE_RE = re.compile(
    r'\d+(?:\.\d+)?\s*(?:nm|um|µm|μm|mm|micron|microns|마이크론|마이크로미터|나노미터)'
    r'|(?:\bfov\b|field[\s-]*of[\s-]*view|시야)\s*[:=]?\s*\d'
    r'|\d+(?:\.\d+)?\s*(?:\bfov\b|field[\s-]*of[\s-]*view|시야)',
    re.IGNORECASE)


def _user_specified_fov(text):
    """True if the user's text explicitly states a scan size / field of view."""
    return bool(text) and bool(_FOV_SIZE_RE.search(text))


def _resolve_sample_preset(text):
    """Return the canonical XRF preset key named in `text`, or None.

    Deterministic resolver — the user's stated sample is authoritative and is
    used to fill/repair the 4th `presetKey` arg of quickRaster.
    """
    if not text:
        return None
    t = text.lower()
    # An explicit canonical key in the text wins (LLM or user wrote it verbatim).
    for key in _XRF_PRESET_KEYS:
        if key in t:
            return key
    for key, aliases in _SAMPLE_ALIASES:
        for a in aliases:
            if a.isascii():
                if re.search(r'(?<![a-z0-9])' + re.escape(a) + r'(?![a-z0-9])', t):
                    return key
            elif a in t:
                return key
    return None


def _as_num(v):
    """Coerce an action arg to float for display; 0.0 on failure."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ══════════════════════════════════════════════════════════════════════
# Deterministic advisory notes (D2 / S5.1 P-areas, 2026-06-11)
# Each helper inspects the FINAL action list + the user text and returns a
# short note string (or None). Emitted through _narrate_plan's `notes`
# channel — after _keep_domain_commentary — so they can never be stripped.
# Zero prompt tokens: pure post-processing.
# ══════════════════════════════════════════════════════════════════════

_NOTE_SCAN_FNS = {"quickRaster", "quickXanes", "quickXafs", "quickEnergyScan",
                  "setupVirtualExperiment"}

# ── P2 (S5, ~12 cases): re-alignment boundaries ──
# A small energy move (dE < 1 keV) still requires re-alignment when it
# crosses a mirror-coating absorption edge: the reflectivity profile (and
# the optimal stripe choice) changes discontinuously there. Values are READ
# FROM the engine (js/optics/03_reflectivity.js mu_rho breakpoints), not
# guessed: Pt L3 = 11.56 keV (line 41), Rh K = 23.22 keV (line 36).
_REALIGN_BOUNDARIES_KEV = (
    (11.564, "Pt L3 coating edge"),
    (23.220, "Rh K coating edge"),
)


def _needs_realign(e_from, e_to):
    """True when an energy move requires a full re-alignment: either the
    move is >= 1 keV, or it crosses a mirror-coating boundary (P2).
    Returns (needed: bool, reason: str|None)."""
    try:
        e_from = float(e_from)
        e_to = float(e_to)
    except (TypeError, ValueError):
        return (False, None)
    if e_from <= 0 or e_to <= 0:
        return (False, None)
    if abs(e_to - e_from) >= 1.0:
        return (True, "dE >= 1 keV")
    lo, hi = min(e_from, e_to), max(e_from, e_to)
    for bound, reason in _REALIGN_BOUNDARIES_KEV:
        if lo < bound < hi:
            return (True, reason)
    return (False, None)


def _note_exposure_time(actions, user_text, current_energy_keV, is_ko):
    """P1 (~25 S5 cases): every scan plan states its exposure time.

    If the user supplied a dwell, restate it; otherwise state the 0.1 s/pt
    default with an inline change offer (infer-default + ask, NOT a blocking
    clarification — benchmark scan cases expect actions to be present).
    nano* functions are excluded (they carry an explicit dwell argument
    handled by prompt rule 28)."""
    import re as _re
    fns = {a.get("fn") for a in actions}
    if not (fns & _NOTE_SCAN_FNS):
        return None
    ut = user_text.lower()
    m = None
    if any(k in ut for k in ["노출", "dwell", "체류", "exposure", "/포인트",
                              "per point", "per-point"]):
        m = _re.search(r'(\d+(?:\.\d+)?)\s*(ms|msec|밀리초|초|s\b|sec)', ut)
    if m:
        val, unit = m.group(1), m.group(2)
        unit_ko = "ms" if unit in ("ms", "msec", "밀리초") else "초"
        return ((u"노출 시간: {}{}/포인트로 설정합니다." if is_ko else
                 u"Exposure time: {} {}/point as requested.")
                .format(val, unit_ko if is_ko else
                        ("ms" if unit_ko == "ms" else "s")))
    return (u"노출 시간: 0.1초/포인트 기본으로 진행합니다. 변경하시려면 말씀해 주세요."
            if is_ko else
            u"Exposure time: default 0.1 s/point. Tell me if you want it changed.")


def _note_nyquist_step(actions, user_text, current_energy_keV, is_ko,
                       beam_nm=50.0):
    """P3 (~10 S5 cases): flag (never block) step-size vs beam-size mismatch.

    quickRaster step = FOV/(npts-1). Undersampling (step > 2x beam) gets a
    Nyquist hint; heavy oversampling (step < beam/2) gets a time note.
    beam_nm defaults to the 50 nm KB nominal focus."""
    for a in actions:
        if a.get("fn") != "quickRaster":
            continue
        args = a.get("args") or []
        if len(args) < 3:
            continue
        try:
            fov_um = max(float(args[0]), float(args[1]))
            npts = max(int(args[2]) - 1, 1)
        except (TypeError, ValueError):
            continue
        step_nm = fov_um * 1000.0 / npts
        if step_nm > 2.0 * beam_nm:
            nyq = beam_nm / 2.0
            return ((u"[참고] 스텝 {:.0f} nm는 집속 빔(~{:.0f} nm)보다 커서 "
                     u"언더샘플링입니다. 나이퀴스트 기준 스텝은 ~{:.0f} nm입니다. "
                     u"그대로 진행할까요?" if is_ko else
                     u"[Note] Step {:.0f} nm exceeds the focused beam "
                     u"(~{:.0f} nm) — undersampling. The Nyquist step is "
                     u"~{:.0f} nm. Proceed as requested?")
                    .format(step_nm, beam_nm, nyq))
        if step_nm < beam_nm / 2.0:
            return ((u"[참고] 스텝 {:.0f} nm는 빔 크기(~{:.0f} nm)보다 충분히 작아 "
                     u"해상도는 빔 한계입니다. 포인트 수를 줄이면 측정 시간이 단축됩니다."
                     if is_ko else
                     u"[Note] Step {:.0f} nm is well below the beam size "
                     u"(~{:.0f} nm); resolution is beam-limited. Fewer points "
                     u"would shorten the scan.").format(step_nm, beam_nm))
    return None


def _note_pt_coating(actions, user_text, current_energy_keV, is_ko):
    """P7 (~3 S5 cases): Pt L-edge measurements collide with the Pt mirror
    coating — recommend the Rh stripe. Deterministic (the prompt-taught
    sentence was being stripped by the commentary filter's '변경' marker)."""
    ut = user_text.lower()
    pt_scan = any(a.get("fn") in ("quickXanes", "quickXafs", "quickEnergyScan")
                  and "Pt" in str(a.get("args")) for a in actions)
    pt_energy = any(a.get("fn") == "setTargetEnergy" and (a.get("args") or [0])
                    and 11.0 <= _as_num(a["args"][0]) <= 12.6 for a in actions
                    ) and ("pt" in ut or "백금" in ut)
    if not (pt_scan or pt_energy):
        return None
    return (u"[참고] Pt L3 (11.564 keV)는 미러 Pt 코팅 흡수단과 겹쳐 반사율 이상과 "
            u"미러 유래 Pt 형광 간섭이 생길 수 있습니다. 측정 전 M2 stripe을 Rh로 "
            u"전환하시기를 권장합니다." if is_ko else
            u"[Note] Pt L3 (11.564 keV) overlaps the Pt mirror-coating "
            u"absorption edge; reflectivity anomalies and mirror-derived Pt "
            u"fluorescence can interfere. Switching the M2 stripe to Rh "
            u"before the scan is recommended.")


# Eiger2 detector half-width (mm) for the default sample-detector distance.
_XRD_DET_HALF_MM = 38.6   # Eiger2 1M module half-height
_XRD_DET_DIST_MM = 150.0  # default sample-detector distance


def _note_xrd_qrange(actions, user_text, current_energy_keV, is_ko):
    """P10 (~4 S5 cases): state the accessible 2-theta / q-range for XRD
    plans (computed nowhere before). Geometry: default 150 mm detector
    distance, Eiger2 half-width."""
    import math as _m
    is_xrd = any(a.get("fn") == "setupVirtualExperiment" and
                 any(p in str(a.get("args")) for p in
                     ("powder_xrd", "xrd_grazing", "xrd_2d_map"))
                 for a in actions)
    if not is_xrd:
        return None
    e_kev = current_energy_keV if current_energy_keV > 0 else 10.0
    for a in actions:
        if a.get("fn") == "setTargetEnergy" and (a.get("args") or []):
            e_kev = _as_num(a["args"][0])
    lam_A = 12.398 / e_kev
    tth_max = _m.degrees(_m.atan(_XRD_DET_HALF_MM / _XRD_DET_DIST_MM))
    q_max = 4.0 * _m.pi * _m.sin(_m.radians(tth_max / 2.0)) / lam_A
    return ((u"[참고] 검출기 거리 {:.0f} mm 기준 2θ ≈ 0–{:.1f}°, "
             u"q ≈ 0–{:.2f} Å⁻¹ ({:.3g} keV)." if is_ko else
             u"[Note] At {:.0f} mm detector distance: 2-theta ≈ 0–{:.1f}°, "
             u"q ≈ 0–{:.2f} 1/Å ({:.3g} keV).")
            .format(_XRD_DET_DIST_MM, tth_max, q_max, e_kev))


def _note_focus_optic(actions, user_text, current_energy_keV, is_ko):
    """P5 (~6 S5 cases): confirm the focusing optic + target beam size for
    sub-micron requests when the user named no optic and the plan sets none."""
    import re as _re
    ut = user_text.lower()
    named_optic = any(k in ut for k in ["kb", "존플", "zone plate", "zoneplate",
                                          "zp", "crl"])
    sets_focus = any(a.get("fn") == "setFocusMode" for a in actions)
    has_scan = any(a.get("fn") in _NOTE_SCAN_FNS for a in actions)
    if named_optic or sets_focus or not has_scan:
        return None
    sub_micron = bool(_re.search(r'\d+(?:\.\d+)?\s*nm', ut)) and \
        any(k in ut for k in ["빔", "beam", "분해능", "해상도", "resolution"])
    nano_words = any(k in ut for k in ["나노빔", "nanobeam", "nano beam",
                                        "sub-micron", "서브미크론", "고해상도"])
    if not (sub_micron or nano_words):
        return None
    m = _re.search(r'(\d+(?:\.\d+)?)\s*nm', ut)
    tgt = (u" 목표 빔 사이즈 {} nm 확인 부탁드립니다.".format(m.group(1)) if m and is_ko
           else (u" Please confirm the {} nm target beam size.".format(m.group(1))
                 if m else u""))
    return ((u"[참고] KB 집속(~50 nm 빔)을 사용합니다. Zone plate/CRL 집속을 "
             u"원하시면 말씀해 주세요." + tgt) if is_ko else
            (u"[Note] Using KB focusing (~50 nm beam). Say the word if you "
             u"want zone-plate/CRL focusing instead." + tgt))


def _narrate_plan(actions, current_energy_keV, is_ko, domain_note="", notes=None):
    """Build the human-facing explanation deterministically from the FINAL action
    list, so the prose can never contradict the plan.

    Procedural facts (energy set, alignment, scan type/params, FOV) are read
    straight from `actions`; the alignment notice is emitted IFF the plan really
    contains setTargetEnergy + an alignment AND the move is >= 1 keV. The optional
    `domain_note` (non-procedural scientific commentary the LLM supplied) is
    appended after. Because the layer that KNOWS the plan is the layer that
    SPEAKS it, the alignment/energy/scan claims are true by construction.

    `notes` (D2/S5 P-areas, 2026-06-11): deterministic advisory lines appended
    by post-processing (exposure time, Nyquist step check, Pt-coating warning,
    XRD q-range, focusing-optic confirmation). They are added HERE — after
    _keep_domain_commentary has already filtered the LLM text — so the
    commentary filter can never strip them (the P1 audit found the filter was
    erasing the LLM's prompt-compliant exposure sentence).
    """
    lines = []
    fns = [a.get("fn") for a in actions]
    set_e = next((a for a in actions if a.get("fn") == "setTargetEnergy"), None)
    has_align = any(f in fns for f in
                    ("runFullAlignment", "runMirrorAlignUI", "runAlignStepUI"))
    for a in actions:
        fn = a.get("fn", "")
        args = a.get("args", []) or []
        if fn == "setTargetEnergy" and args:
            lines.append((u"빔 에너지를 {:g} keV로 설정합니다." if is_ko
                          else u"Set the beam energy to {:g} keV.")
                         .format(_as_num(args[0])))
        elif fn in ("runFullAlignment", "runMirrorAlignUI", "runAlignStepUI"):
            lines.append(u"빔라인 정렬을 수행합니다." if is_ko
                         else u"Run a full beamline alignment.")
        elif fn == "quickXanes":
            el = args[0] if args else "?"
            edge = args[1] if len(args) > 1 else "K"
            lines.append((u"{} {}-edge XANES 스캔(0.25 eV 분해능)을 실행합니다." if is_ko
                          else u"Run a {} {}-edge XANES scan (0.25 eV resolution).")
                         .format(el, edge))
        elif fn == "quickXafs":
            el = args[0] if args else "?"
            edge = args[1] if len(args) > 1 else "K"
            lines.append((u"{} {}-edge XAFS 스캔을 실행합니다." if is_ko
                          else u"Run a {} {}-edge XAFS scan.").format(el, edge))
        elif fn == "quickRaster" and len(args) >= 3:
            preset = args[3] if len(args) >= 4 else None
            base = (u"{:g} x {:g} µm 영역을 {}x{} 포인트로 XRF 래스터 스캔합니다." if is_ko
                    else u"XRF raster scan over {:g} x {:g} µm at {}x{} points.")\
                .format(_as_num(args[0]), _as_num(args[1]), args[2], args[2])
            if preset:
                base += (u" (시료: {})".format(preset) if is_ko
                         else u" (sample: {})".format(preset))
            lines.append(base)
        elif fn == "quickEnergyScan":
            lines.append(u"에너지 스캔을 실행합니다." if is_ko
                         else u"Run an energy scan.")
        elif fn == "setCrystal" and args:
            lines.append((u"DCM 결정을 {}로 설정합니다." if is_ko
                          else u"Set the DCM crystal to {}.").format(args[0]))
        elif fn == "setFocusMode" and args:
            lines.append((u"집속 모드를 {}로 설정합니다." if is_ko
                          else u"Set the focus mode to {}.").format(args[0]))
        elif fn == "optimizeBeamline":
            lines.append(u"빔라인 최적화를 실행합니다." if is_ko
                         else u"Optimize the beamline.")
        elif fn in ("showBeamProfile", "showTransmission"):
            lines.append(u"결과를 표시합니다." if is_ko else u"Show the result.")
        elif fn == "queueStart":
            # The scan line already conveys execution; skip so we don't claim a
            # "start now" next to a "Proceed?" notice.
            continue
        else:
            # Graceful fallback for less common functions: use the label/fn name.
            lbl = a.get("label") or fn
            if lbl:
                lines.append((u"{} 실행." if is_ko else u"Run {}.").format(lbl))
    # Energy-move + alignment notice, true only when the plan actually moves energy.
    if set_e and has_align and current_energy_keV > 0:
        te = _as_num((set_e.get("args") or [0])[0])
        if abs(te - current_energy_keV) >= 1.0:
            lines.append((u"[참고] 현재 {:.3f} keV에서 {:.3f} keV로 이동(1 keV 이상)하므로 "
                          u"IVU gap/DCM 등 빔라인 정렬이 함께 수행됩니다. 진행하시겠습니까?"
                          if is_ko else
                          u"[Note] Moving from {:.3f} keV to {:.3f} keV (>= 1 keV) "
                          u"requires a beamline alignment (IVU gap, DCM, etc.). "
                          u"Proceed?").format(current_energy_keV, te))
        else:
            # P2: small move that crosses a mirror-coating boundary
            _need_b, _why_b = _needs_realign(current_energy_keV, te)
            if _need_b:
                lines.append((u"[참고] {:.3f} → {:.3f} keV 이동은 1 keV 미만이지만 "
                              u"미러 코팅 경계({})를 지나므로 빔라인 정렬이 함께 "
                              u"수행됩니다. 진행하시겠습니까?" if is_ko else
                              u"[Note] The {:.3f} → {:.3f} keV move is below "
                              u"1 keV but crosses a mirror-coating boundary "
                              u"({}), so a beamline alignment is included. "
                              u"Proceed?").format(current_energy_keV, te, _why_b))
    body = "\n".join(lines)
    note = (domain_note or "").strip()
    if note:
        body = (body + "\n" + note) if body else note
    for n in (notes or []):
        n = (n or "").strip()
        if n:
            body = (body + "\n" + n) if body else n
    return body


def _keep_domain_commentary(text):
    """Backstop: keep only NON-procedural sentences from the LLM explanation.

    Procedure (energy/alignment/scan) is narrated deterministically by
    `_narrate_plan`, so the LLM's free text is used only for scientific
    commentary (e.g. oxidation-state contrast, mirror-coating interference).
    This drops any sentence that asserts a procedural claim about alignment,
    the energy move, or starting the scan immediately, so a model that ignores
    the prompt and restates procedure cannot reintroduce a contradiction. It is
    a safety net, not the primary mechanism: the narrator is authoritative.
    """
    if not text:
        return text
    parts = re.split(r'(?<=[.!?])\s+|\n+', text)
    # Drop any sentence that states procedure (the narrator already states it) or
    # asserts a contradicting claim. Markers are procedural VOCABULARY, not an
    # open-ended list of ways to say "no" — so contradictions (which are inherently
    # procedural) are caught while scientific commentary (oxidation state, coating
    # interference, chemistry) survives. Over-removal is benign (less commentary,
    # never a contradiction).
    markers = (
        # procedural vocabulary narrated from the action list
        "kev", "energy", "에너지", "align", "정렬",
        "scan", "스캔", "raster", "래스터", "mapping", "매핑",
        "fov", "µm", "μm", "분해능", "resolution",
        "points", "포인트", "픽셀", "pixel",
        "set energy", "설정", "변경", "이동", "move",
        "start", "begin", "immediately", "시작", "수행", "실행",
        "queue", "대기열",
    )
    fov_fig = re.compile(r'\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:um|µm|μm)')
    kept = []
    for p in parts:
        pl = p.lower()
        if any(m in pl for m in markers):
            continue
        if fov_fig.search(pl):
            continue
        if p.strip():
            kept.append(p.strip())
    return " ".join(kept).strip()


# Korean element aliases
_ELEMENT_ALIASES_KR = {
    "철": "Fe", "구리": "Cu", "아연": "Zn", "니켈": "Ni", "코발트": "Co",
    "망간": "Mn", "크롬": "Cr", "티타늄": "Ti", "바나듐": "V",
    "비소": "As", "셀레늄": "Se", "스트론튬": "Sr", "몰리브덴": "Mo",
    "은": "Ag", "금": "Au", "백금": "Pt", "납": "Pb", "텅스텐": "W",
    "세륨": "Ce", "란탄": "La", "바륨": "Ba", "갈륨": "Ga",
    "게르마늄": "Ge", "규소": "Si", "인": "P", "황": "S", "칼슘": "Ca",
    "탄소": "C", "질소": "N", "산소": "O", "마그네슘": "Mg", "알루미늄": "Al",
}

# All valid function names (Layer 3 fuzzy matching target)
_VALID_FUNCTIONS = {
    "setTargetEnergy", "setCrystal", "setFocusMode", "motorSetUI", "motorMoveRelUI",
    "maskAperUpdate", "setAttenFilter", "setAlignConfig", "setMirrorAlignRange",
    "runAlignStepUI", "runFullAlignment", "runMirrorAlignUI", "abortAlignment",
    "emergencyStop", "homeMotor",
    "quickEnergyScan", "quickXafs", "quickXanes", "quickRaster", "quickCount",
    "quickAlign", "quickFlyScan",
    "quickAutoTune", "quickAdaptiveScan", "quickRelAlign", "quickFermat",
    "quickRelRaster",
    "queuePlan", "queueStart", "queueStop", "queuePause", "queueResume",
    "queueAbort", "queueClear",
    "setupVirtualExperiment", "showBeamProfile", "showTransmission", "switchTab",
    "optimizeBeamline", "estimateSignal", "sweepEnergy", "sweepSSA",
    "applyOptimization", "cancelOptimization",
    # Nano scanner functions
    "nanoScanStep2D", "nanoScanFly1D", "nanoScanSpiral",
    "nanoJog", "nanoMoveTo", "nanoStatus", "nanoScanAbort",
    "queryHardwareStatus",
}

# Lowercase lookup for fuzzy matching
_VALID_FN_LOWER = {fn.lower(): fn for fn in _VALID_FUNCTIONS}

# Scan functions that require queueStart() afterwards
_SCAN_FUNCTIONS = {
    "quickEnergyScan", "quickXafs", "quickXanes", "quickRaster", "quickCount",
    "quickAlign", "quickFlyScan",
    "quickAutoTune", "quickAdaptiveScan", "quickRelAlign", "quickFermat",
    "quickRelRaster",
}

BEAMLINE_E_MIN = 5.0   # keV
BEAMLINE_E_MAX = 25.0  # keV

# ══════════════════════════════════════════════════════════════════════
# Intent Detection Keywords (for Dynamic Prompt Composition)
# ══════════════════════════════════════════════════════════════════════

_INTENT_KEYWORDS = {
    "motor": [
        "에너지", "energy", "keV", "모터", "motor", "이동", "설정해", "설정",
        "피치", "pitch", "슬릿", "slit", "SSA", "ssa", "결정", "crystal",
        "Si(111)", "Si(311)", "집속", "focus",
    ],
    "scan_xrf": [
        "XRF", "xrf", "형광", "원소 분포", "원소 맵", "이미징", "맵핑", "매핑",
        "래스터", "raster", "2D", "2차원", "스캐닝", "오염",
    ],
    "scan_xanes": [
        "XANES", "xanes", "XAFS", "xafs", "EXAFS", "흡수", "near-edge",
        "니어엣지", "산화 상태", "산화상태", "화학 결합", "화학결합",
    ],
    "scan_xrd": [
        "XRD", "xrd", "회절", "분말", "결정상", "결정 구조", "Debye",
        "상분율", "격자", "grazing", "GIXRD", "GI-XRD", "입사각",
        "incidence", "박막", "thin film", "표면 회절",
    ],
    "alignment": [
        "정렬", "align", "정렬해", "auto tune", "자동정렬", "자동 정렬",
        "센트로이드", "centroid", "로킹커브",
    ],
    "info": [
        "뭐야", "뭐가", "알려줘", "설명", "차이가", "할 수 있", "몇",
        "가능", "시간", "걸려", "필요", "얼마",
        "투과율", "투과", "transmission", "보여줘", "프로파일",
    ],
    # P1 (S5): activates the 'exposure'-tagged few-shots (previously dead —
    # no intent ever carried this tag, so _select_few_shots never scored it)
    "exposure": [
        "노출", "dwell", "체류", "exposure", "초/포인트", "per point",
    ],
    "optimize": [
        "최적화", "optimize", "최적", "추천", "신호", "signal",
        "ppm", "분해능", "resolution", "flux",
    ],
    "mask_atten": [
        "마스크", "mask", "어테뉴에이터", "attenuator", "감쇠", "필터",
        "조리개",
    ],
    "ptycho": [
        "ptychography", "ptycho", "위상", "coherent", "결맞음",
        "나선", "fermat", "spiral",
    ],
    "rejection": [],  # Always included — no keywords needed
    "scan_advanced": [
        "라인스캔", "라인 스캔", "line scan", "플라이", "fly",
        "적응형", "adaptive", "멀티리전", "multi region", "상대",
    ],
    "nano_scanner": [
        "나노스캐너", "나노스캔", "나노 스캔", "나노 스캐너", "nano scan",
        "MCS2", "mcs2", "피코스케일", "picoscale", "SmarAct", "smaract",
        "간섭계", "interferometer", "나노 이동", "나노 조그",
    ],
    "hw_status": [
        "하드웨어 상태", "장비 상태", "연결 상태", "연결됐", "정상이",
        "XBPM", "xbpm", "링 전류", "ring current",
    ],
    "setup": [
        "셋업", "세팅", "준비", "setup", "프리셋", "preset",
        "가상 실험", "virtual",
    ],
}


def _detect_intents(text: str) -> set:
    """Detect query intents by keyword matching.

    Returns a set of intent category names (e.g. {'scan_xanes', 'motor'}).
    'rejection' is always included.
    """
    text_lower = text.lower()
    intents = {"rejection"}  # always included

    for category, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                intents.add(category)
                break

    # If no specific intent detected (besides rejection), include common ones
    if len(intents) <= 1:
        intents.update({"motor", "info"})

    return intents


# ══════════════════════════════════════════════════════════════════════
# RAG Intent Router — knowledge query classification
# ══════════════════════════════════════════════════════════════════════

_RAG_TRIGGER_KEYWORDS = [
    # Korean
    "왜", "어떻게", "원리", "차이", "비교", "장단점",
    "뭐가 좋", "추천", "언제 쓰", "설명해",
    "무슨 차이", "어떤 원리", "작동 원리",
    "알려줘",  # only triggers RAG when no command intent
    # English
    "why", "how does", "principle", "difference", "compare",
    "trade-off", "when to use", "explain", "pros and cons",
    "what is the", "tell me about",
]

# Intents that indicate a command (not a knowledge query)
_COMMAND_INTENTS = {
    "motor", "scan_xrf", "scan_xanes", "scan_xrd",
    "alignment", "mask_atten", "ptycho", "scan_advanced", "setup",
    "nano_scanner", "hw_status",
}


def _is_knowledge_query(preproc: dict, text: str) -> bool:
    """Determine if user input is a knowledge query (RAG path)
    vs a command (existing pipeline).

    Conservative: returns False when ambiguous, preserving 97.8% pass rate.
    """
    intents = preproc.get("intents", set())

    # 1. Explicit command intents → command path
    if intents & _COMMAND_INTENTS:
        return False

    text_lower = text.lower()

    # 2. "info" intent + RAG trigger keyword → RAG path
    if "info" in intents:
        for kw in _RAG_TRIGGER_KEYWORDS:
            if kw in text_lower:
                return True

    # 3. No command intent + RAG keyword (handles "왜...?", "how does...?" etc.
    #    where _detect_intents may not flag "info" but the query is clearly
    #    a knowledge question, not a command)
    if not intents:
        for kw in _RAG_TRIGGER_KEYWORDS:
            if kw in text_lower:
                return True

    # 4. Default: command path (conservative)
    return False


# ══════════════════════════════════════════════════════════════════════
# Layer 6: Domain Rule Validation — constants
# ══════════════════════════════════════════════════════════════════════

# Technique detection from action function names
_FN_TO_TECHNIQUE = {
    "quickXanes": "xanes",
    "quickXafs": "xafs",
    "quickRaster": "xrf",      # default; could be xrd depending on context
    "quickFermat": "ptycho",
    "quickRelRaster": "xrf",
    "setupVirtualExperiment": None,  # depends on args
}

# Setup change costs (subset of science_advisor.SETUP_CHANGE_DB)
# P8 (S5, ~3 cases, 2026-06-11): the ID10 endstation mounts the SDD (XRF)
# and EIGER2 (XRD) detectors at DIFFERENT scattering angles — XRF and XRD
# are collected simultaneously with NO detector swap. The former
# xrf<->xrd / xanes<->xrd 1800 s entries contradicted prompt rule 21 and
# produced a spurious "[검출기 교체 경고] ~30분" on co-mounted plans.
# Ptychography transitions are kept: coherent-mode setup (SSA, vacuum
# path, SDD removal) is a genuine reconfiguration.
_SETUP_CHANGE_SEC = {
    ("xrf", "ptycho"): 2700,
    ("ptycho", "xrf"): 2700,
    ("xrd", "ptycho"): 1200,
    ("ptycho", "xrd"): 1200,
    ("xanes", "ptycho"): 2700,
    ("ptycho", "xanes"): 2700,
    ("xafs", "ptycho"): 2700,
    ("ptycho", "xafs"): 2700,
}

# Function signature validation: {fn_name: (min_args, max_args)}
_FUNCTION_SIGNATURES = {
    "setTargetEnergy": (1, 1),
    "setCrystal": (1, 1),
    "setFocusMode": (1, 1),
    "motorSetUI": (3, 3),
    "motorMoveRelUI": (3, 3),
    "maskAperUpdate": (3, 3),
    "setAttenFilter": (3, 3),
    "runAlignStepUI": (1, 1),
    "runFullAlignment": (0, 0),
    "runMirrorAlignUI": (1, 1),
    "abortAlignment": (0, 0),
    "emergencyStop": (0, 0),
    "homeMotor": (2, 2),
    "quickEnergyScan": (3, 3),
    "quickXafs": (2, 2),
    "quickXanes": (2, 2),
    "quickRaster": (3, 4),  # (xRange, yRange, numPts, presetKey)
    "quickCount": (2, 2),
    "quickAlign": (1, 1),
    "quickFlyScan": (5, 5),
    "quickAutoTune": (5, 5),
    "quickAdaptiveScan": (4, 4),
    "quickRelAlign": (4, 4),
    "quickFermat": (3, 3),
    "quickRelRaster": (4, 4),
    "queueStart": (0, 0),
    "queueStop": (0, 0),
    "queuePause": (0, 0),
    "queueResume": (0, 0),
    "queueAbort": (0, 0),
    "queueClear": (0, 0),
    "queuePlan": (2, 2),
    "setupVirtualExperiment": (1, 1),
    "showBeamProfile": (1, 1),
    "showTransmission": (1, 3),
    "switchTab": (1, 1),
    "optimizeBeamline": (1, 1),
    "estimateSignal": (6, 6),
    "sweepEnergy": (3, 3),
    "sweepSSA": (2, 2),
    "applyOptimization": (0, 0),
    "cancelOptimization": (0, 0),
    # Nano scanner functions
    "nanoScanStep2D": (5, 5),
    "nanoScanFly1D": (4, 4),
    "nanoScanSpiral": (3, 3),
    "nanoJog": (2, 2),
    "nanoMoveTo": (2, 2),
    "nanoStatus": (0, 0),
    "nanoScanAbort": (0, 0),
    "queryHardwareStatus": (1, 1),
}

# Valid motor groups and their motor IDs
_VALID_MOTORS = {
    "ivu": {"ivu_gap"},
    "m1": {"m1_x", "m1_y", "m1_z", "m1_pitch", "m1_pitch_fine", "m1_roll",
            "m1_yaw", "m1_bend_u", "m1_bend_d"},
    "dcm": {"dcm_theta", "dcm_y1", "dcm_chi1", "dcm_tx", "dcm_y2", "dcm_z2",
             "dcm_dTheta2", "dcm_roll2", "dcm_dTheta2F"},
    "m2": {"m2_x", "m2_y", "m2_z", "m2_pitch", "m2_pitch_fine", "m2_roll",
            "m2_yaw", "m2_bend_u", "m2_bend_d"},
    "wbslit": {"wbslit_top", "wbslit_bottom", "wbslit_inboard", "wbslit_outboard",
               "wbslit_hgap", "wbslit_vgap", "wbslit_hcen", "wbslit_vcen"},
    "ssa": {"ssa_hgap", "ssa_vgap", "ssa_hcen", "ssa_vcen"},
    "kbslit": {"kbslit_hgap", "kbslit_vgap", "kbslit_hcen", "kbslit_vcen"},
    "kbv": {"kbv_x", "kbv_y", "kbv_z", "kbv_pitch", "kbv_bend_u", "kbv_bend_d"},
    "kbh": {"kbh_x", "kbh_y", "kbh_z", "kbh_pitch", "kbh_bend_u", "kbh_bend_d"},
    "zp": {"zp_x", "zp_y", "zp_z"},
    "sample": {"sample_cx", "sample_cy", "sample_cz", "sample_th", "sample_phi",
               "sample_fx", "sample_fy", "sample_fz", "sample_sx", "sample_sy"},
    "fmask": {"fmask_hgap", "fmask_vgap", "fmask_x", "fmask_y"},
    "mmask": {"mmask_hgap", "mmask_vgap", "mmask_x", "mmask_y"},
    "det": {"det_x", "det_y", "det_z"},
}


def _preprocess_input(text: str) -> dict:
    """Layer 1: Analyze user input and generate hint tags before LLM call.

    Returns dict with:
      - elements: list of detected element symbols
      - out_of_range: list of {element, edge, energy} that are outside beamline range
      - hints: list of hint strings to append to the user message
    """
    result = {"elements": [], "out_of_range": [], "hints": []}

    # Detect element symbols (English)
    found_elements = set()
    for elem in _EDGE_DB:
        # Match standalone element symbol (word boundary)
        if re.search(r'\b' + re.escape(elem) + r'\b', text):
            found_elements.add(elem)

    # Detect Korean element names
    for kr_name, elem in _ELEMENT_ALIASES_KR.items():
        if kr_name in text:
            found_elements.add(elem)

    result["elements"] = sorted(found_elements)

    # Detect query intents for dynamic prompt composition
    result["intents"] = _detect_intents(text)

    # Check energy range for detected elements
    for elem in found_elements:
        edges = _EDGE_DB.get(elem, {})
        for edge_name, energy in edges.items():
            if energy < BEAMLINE_E_MIN:
                result["out_of_range"].append({
                    "element": elem, "edge": edge_name,
                    "energy": energy, "reason": "below_min"
                })
                result["hints"].append(
                    f"[HINT: {elem} {edge_name}-edge = {energy:.3f} keV is BELOW "
                    f"beamline minimum {BEAMLINE_E_MIN} keV. Explain this to user.]"
                )
            elif energy > BEAMLINE_E_MAX:
                # Check if L3-edge is available as alternative
                l3_energy = edges.get("L3")
                if l3_energy and BEAMLINE_E_MIN <= l3_energy <= BEAMLINE_E_MAX:
                    result["hints"].append(
                        f"[HINT: {elem} {edge_name}-edge = {energy:.1f} keV exceeds "
                        f"beamline max {BEAMLINE_E_MAX} keV. Suggest L3-edge = "
                        f"{l3_energy:.3f} keV instead.]"
                    )
                else:
                    result["out_of_range"].append({
                        "element": elem, "edge": edge_name,
                        "energy": energy, "reason": "above_max"
                    })
                    result["hints"].append(
                        f"[HINT: {elem} {edge_name}-edge = {energy:.1f} keV is ABOVE "
                        f"beamline maximum {BEAMLINE_E_MAX} keV. Cannot measure. "
                        f"Explain to user.]"
                    )

    return result


# ── Intent Guard: keyword lists ──────────────────────────────────────
_ALIGNMENT_KEYWORDS = [
    "full alignment", "전체 정렬", "빔 정렬", "beam alignment",
    "full beam alignment", "전체 빔 정렬", "정렬 시작", "정렬해줘",
    "정렬해", "빔라인 정렬", "beamline alignment", "7단계 정렬",
    "전체 빔라인 정렬",
]
_ALIGNMENT_FUNCTIONS = {"runFullAlignment", "runAlignStepUI", "runMirrorAlignUI",
                        # Motor-specific auto-tune scans ARE alignment plans
                        # (align_04 regression 2026-06-12: the intent guard
                        # force-overwrote a correct quickAutoTune("m1","pitch",
                        # 1,4,...) with a bare runFullAlignment because these
                        # were missing from the whitelist). JS quickAutoTune
                        # itself routes pitch axes to runMirrorAlignUI.
                        "quickAutoTune", "quickRelAlign"}


def _extract_element_edge(text: str):
    """Extract (element, edge) from text using _EDGE_DB. Returns (None, None) if not found."""
    import re as _re
    text_u = text.upper()
    # Explicit L3 mention?
    has_l3 = ("L3" in text_u or "L-III" in text_u or "L III" in text_u)
    for elem in _EDGE_DB:
        if _re.search(r'\b' + _re.escape(elem.upper()) + r'\b', text_u):
            edges = _EDGE_DB[elem]
            if has_l3 and "L3" in edges:
                return (elem, "L3")
            if "K" in edges and edges["K"] <= BEAMLINE_E_MAX:
                return (elem, "K")
            # Heavy element: K too high, fallback to L3
            if "L3" in edges:
                return (elem, "L3")
    return (None, None)


def _extract_elements_in_range(text: str) -> list:
    """Extract ALL (element, edge) pairs from text whose edge energy lies
    inside the beamline range [BEAMLINE_E_MIN, BEAMLINE_E_MAX].

    Multi-element backstop for _recover_from_empty (D3, 2026-06-11): a
    sequential request like "Ti K-edge XANES 하고 나서 Sr K-edge XANES" must
    not collapse to an empty plan just because the FIRST element (Ti K =
    4.966 keV) is below range — the in-range elements (Sr K = 16.105 keV)
    should still be recovered. Returns [(elem, edge), ...] in text order;
    out-of-range elements are silently skipped (the LLM explanation already
    tells the user why).
    """
    import re as _re
    # Normalize Korean element names to symbols first ("철 XANES" -> "Fe XANES")
    # so the keyword backstop also fires on Korean-only requests.
    for kr, sym in _ELEMENT_ALIASES_KR.items():
        if kr in text:
            text = text.replace(kr, " " + sym + " ")
    text_u = text.upper()
    has_l3 = ("L3" in text_u or "L-III" in text_u or "L III" in text_u)
    found = []
    for elem in _EDGE_DB:
        m = _re.search(r'\b' + _re.escape(elem.upper()) + r'\b', text_u)
        if not m:
            continue
        edges = _EDGE_DB[elem]
        pick = None
        if has_l3 and "L3" in edges and \
                BEAMLINE_E_MIN <= edges["L3"] <= BEAMLINE_E_MAX:
            pick = "L3"
        elif "K" in edges and BEAMLINE_E_MIN <= edges["K"] <= BEAMLINE_E_MAX:
            pick = "K"
        elif "L3" in edges and \
                BEAMLINE_E_MIN <= edges["L3"] <= BEAMLINE_E_MAX:
            pick = "L3"
        if pick:
            found.append((m.start(), elem, pick))
    found.sort()  # text order
    return [(e, ed) for _, e, ed in found]


def _recover_from_empty(user_text: str, current_energy_keV: float) -> list:
    """Attempt to recover actions from an empty LLM response using keywords.

    D3 hardening (2026-06-11, JSR future-work item: the 4/228 benchmark
    failures included two empty-action responses):
    - XANES/XAFS: recovers ALL in-range elements as a sequential plan
      (workflow_01: Ti out-of-range must not suppress the Sr scan).
    - XRF/raster: recovers a default preset even when no element is named
      (vexp_03: "2D XRF 맵핑 실험 셋업" -> default raster instead of nothing).
    queueStart() injection and confirmation_required enforcement are handled
    downstream by _postprocess_response (deterministic layers).
    """
    ut = user_text.lower()

    # Alignment
    if any(k in ut for k in _ALIGNMENT_KEYWORDS):
        return [{"fn": "runFullAlignment", "args": [],
                 "label": "Full Alignment (recovered)"}]

    # Bare relative sample move (motor_03 backstop, 2026-06-12): owner
    # convention — unit-less "N 이동" with no absolute marker (위치로/좌표로/
    # 까지) is a RELATIVE move. The LLM sometimes returns empty actions and
    # asks for the unit instead; recover motorMoveRelUI with the operator
    # default (unit-less sample moves are micrometers on a nanoprobe;
    # sample_c* args are mm). "N(으)로" absolute forms are excluded by the
    # trailing lookahead so they stay with the LLM/rule-25 path.
    if any(k in ut for k in ["이동", "움직", "옮겨", "move"]) and \
            not any(k in ut for k in ["위치로", "좌표로", "까지", "absolute"]):
        _mv = re.search(
            r'(?:시료|샘플|sample)\s*c?([xyz])\s*(?:축)?\s*(?:를|을)?\s*'
            r'([+-]?\d+(?:\.\d+)?)\s*'
            r'(mm|밀리|um|µm|μm|마이크로|micro\w*|nm|나노)?'
            r'(?!\s*(?:으로|로))',
            user_text, re.IGNORECASE)
        if _mv:
            _ax = _mv.group(1).lower()
            _num = float(_mv.group(2))
            _unit = (_mv.group(3) or "").lower()
            if _unit in ("mm", "밀리"):
                _delta_mm = _num
            elif _unit in ("nm", "나노"):
                _delta_mm = _num / 1e6
            else:  # micrometer family, or unit-less (operator default: um)
                _delta_mm = _num / 1000.0
            return [{"fn": "motorMoveRelUI",
                     "args": ["sample", "sample_c" + _ax, _delta_mm],
                     "label": "Sample {} {:+g} um relative (recovered)".format(
                         _ax.upper(), _delta_mm * 1000.0)}]

    # Optimization request — must NOT degrade into a blind raster
    # (opt_01/02 regression 2026-06-11: a truncated LLM response fell into
    # the XRF branch below and recovered quickRaster where the user asked
    # for optimizeBeamline). Recover the optimizer when an element is known;
    # otherwise return nothing and let the explanation ask for details.
    if any(k in ut for k in ["최적화", "optimiz", "최적의", "가장 좋은"]):
        pairs = _extract_elements_in_range(user_text)
        if pairs:
            elem, edge = pairs[0]
            # Priority from the request wording (resolution vs flux)
            if any(k in ut for k in ["분해능", "resolution", "해상도"]):
                prio = "resolution"
            elif any(k in ut for k in ["flux", "플럭스", "신호", "감도"]):
                prio = "flux"
            else:
                prio = "balanced"
            return [{"fn": "optimizeBeamline",
                     "args": [{"technique": "xrf", "element": elem,
                               "edge": edge, "priority": prio}],
                     "label": "{} XRF optimize (recovered)".format(elem)}]
        return []

    # Powder XRD experiment preset (empty-response backstop)
    if "xrd" in ut and any(k in ut for k in ["분말", "powder"]):
        return [{"fn": "setupVirtualExperiment", "args": ["powder_xrd"],
                 "label": "Powder XRD preset (recovered)"}]

    # Adaptive energy scan (scan_06 backstop, 2026-06-12): explicit adaptive
    # wording + a recognizable element -> quickAdaptiveScan around its edge.
    if any(k in ut for k in ["적응형", "adaptive"]):
        pairs = _extract_elements_in_range(user_text)
        if pairs:
            _ae = _EDGE_DB[pairs[0][0]][pairs[0][1]]
            return [{"fn": "quickAdaptiveScan",
                     "args": [round(_ae - 0.05, 3), round(_ae + 0.3, 3),
                              0.25, 5],
                     "label": "{} adaptive scan (recovered)".format(pairs[0][0])}]
        return []

    # Oxidation / chemical-state intent (analysis_01 backstop, 2026-06-12):
    # "Fe 산화 상태를 확인하고 싶어요" names no technique, but the
    # measurement is XANES by definition. Element required — no blind
    # default scan when nothing recognizable is named.
    if any(k in ut for k in ["산화 상태", "산화상태", "산화수",
                              "oxidation state", "valence", "원자가",
                              "화학 상태", "chemical state"]):
        pairs = _extract_elements_in_range(user_text)
        if pairs:
            return [{"fn": "quickXanes", "args": [elem, edge],
                     "label": "{} {} XANES (recovered)".format(elem, edge)}
                    for elem, edge in pairs]
        return []

    # XANES / XAFS — recover every in-range element (sequential plan).
    # qact_01 regression fix (2026-06-12): honor an explicit XAFS/EXAFS
    # request — the branch previously hardcoded quickXanes, substituting
    # XANES for a user who literally asked for "Fe XAFS". XANES wording
    # wins on a mixed mention; "exafs" contains "xafs" so it also routes
    # to quickXafs.
    if any(k in ut for k in ["xanes", "xafs", "near-edge", "near edge"]):
        if "xafs" in ut and "xanes" not in ut:
            _rec_fn, _rec_nm = "quickXafs", "XAFS"
        else:
            _rec_fn, _rec_nm = "quickXanes", "XANES"
        pairs = _extract_elements_in_range(user_text)
        if pairs:
            return [{"fn": _rec_fn, "args": [elem, edge],
                     "label": "{} {} {} (recovered)".format(elem, edge, _rec_nm)}
                    for elem, edge in pairs]

    # XRF / raster — element optional; fall back to a default preset
    if any(k in ut for k in ["xrf", "형광", "매핑", "맵핑", "mapping",
                              "raster", "이미징"]):
        return [{"fn": "quickRaster", "args": [5, 5, 21],
                 "label": "XRF map (recovered)"}]

    return []


def _postprocess_response(result: dict, current_energy_keV: float = 0,
                          user_text: str = "") -> dict:
    """Layer 3: Validate and auto-correct LLM response.

    - Guard: energy-set intent should not trigger quickXanes/quickXafs
    - Fuzzy-match function names (case-insensitive)
    - Remove hallucinated (non-existent) functions
    - Add missing queueStart() after scan functions
    - Generate warning messages for removed actions
    """
    _recovered = False
    actions = result.get("actions", [])
    if not actions:
        # Attempt keyword-based recovery from empty response
        recovered = _recover_from_empty(user_text, current_energy_keV)
        if recovered:
            result["actions"] = recovered
            actions = recovered
            _recovered = True  # surfaced as a meta-note after the plan narration
            log.warning("NLP postprocess: recovered empty response for '%s' -> %s",
                           user_text[:80], [a["fn"] for a in recovered])
        else:
            return result

    # Guard: if user only asked to SET energy (not scan/measure),
    # replace quickXanes/quickXafs with setTargetEnergy
    _ut = user_text.lower()
    # Korean-vs-English for any notices we add below (derive from the input text).
    _is_ko = (_detect_language(user_text) == "ko")
    _is_energy_set = any(k in _ut for k in [
        "set energy", "energy set", "에너지 설정", "에너지를 설정",
        "에너지를 바꿔", "에너지 변경", "에너지를 변경",
        "kev로 설정", "kev set", "kev 설정", "kev로 바꿔",
        "kev로 맞춰", "에너지를 맞춰", "에너지 맞춰"
    ])
    _is_scan = any(k in _ut for k in [
        "xanes", "xafs", "scan", "측정", "스캔", "분석",
        "xrf", "xrd", "raster", "래스터"
    ])
    if _is_energy_set and not _is_scan:
        # Extract the target energy: prefer explicit number from user text
        import re as _re
        _e_match = _re.search(r'(\d+(?:\.\d+)?)\s*(?:kev|keV)', user_text)
        _target_e = float(_e_match.group(1)) if _e_match else None

        # If LLM hallucinated scan functions, convert to setTargetEnergy
        for act in actions:
            fn = act.get("fn", "")
            if fn in ("quickXanes", "quickXafs"):
                args = act.get("args", [])
                el = args[0] if args else "Cu"
                edge = args[1] if len(args) > 1 else "K"
                edge_e = _EDGE_DB.get(el, {}).get(edge, 0)
                if edge_e > 0:
                    act["fn"] = "setTargetEnergy"
                    act["args"] = [round(edge_e, 3)]
                    act["label"] = "Set Energy (corrected from {})".format(fn)

        # Strip to ONLY the setTargetEnergy with user's requested value
        # (remove hallucinated extra actions like queueStart, duplicate
        # setTargetEnergy). multi_01 regression fix (2026-06-12): read-only
        # display steps the user ALSO asked for ("...빔 프로파일 보여줘") are
        # not hallucinations — keep them after the energy move so a multi-step
        # command survives the rewrite. runFullAlignment is re-derived
        # downstream by the dE/coating-boundary logic when the move needs it.
        _KEEP_DISPLAY_FNS = ("showBeamProfile", "showTransmission", "switchTab")
        _kept_display = [a for a in actions if a.get("fn") in _KEEP_DISPLAY_FNS]
        if _target_e is not None:
            actions = [{"fn": "setTargetEnergy", "args": [_target_e],
                        "label": "Set Energy to {} keV".format(_target_e)}] \
                + _kept_display
        else:
            # No explicit energy in text — keep only setTargetEnergy actions
            actions = [a for a in actions
                       if a.get("fn") == "setTargetEnergy"] + _kept_display

    corrected = []
    removed = []

    for act in actions:
        fn = act.get("fn", "")
        fn_lower = fn.lower()

        # Fuzzy match: find correct case
        if fn in _VALID_FUNCTIONS:
            corrected.append(act)
        elif fn_lower in _VALID_FN_LOWER:
            # Case mismatch — auto-correct
            act["fn"] = _VALID_FN_LOWER[fn_lower]
            corrected.append(act)
        else:
            # Hallucinated function — remove
            removed.append(fn)

    # ── P9 (S5, ~5 cases): pure-question action stripper ──
    # Info questions that contain command nouns ("Fe XANES 하려면 몇 keV로
    # 가야 해?") bypass the RAG router by design and previously executed an
    # action. If the text carries an info-question marker AND no imperative
    # marker anywhere, strip state-changing actions and keep the LLM's
    # explanation (it contains the answer). The no-imperative condition
    # preserves question+command mixes ("...해줘", "...맞춰") untouched.
    _P9_QUESTION = ["얼마로 해야", "얼마야", "얼마나 걸려", "몇 kev", "몇이야",
                    "해야 해?", "해야 하죠", "어떻게 해야", "뭐가 좋아",
                    # vexp_11/42/50 regression fix (2026-06-12): info-question
                    # forms the D3 recovery hardening was turning into
                    # executable plans ("...필요한가요?" / "...시간이 어떻게
                    # 돼?" / "...동시에 ...도 할 수 있어?"). The no-imperative
                    # condition below still protects question+command mixes.
                    "필요한가", "어떻게 돼", "할 수 있어",
                    "what is", "how much", "how long", "which energy",
                    "what energy"]
    _P9_IMPERATIVE = ["해줘", "주세요", "맞춰", "설정해", "실행", "시작", "돌려",
                      "측정해", "찍어", "스캔해", "열어", "보여줘", "해 줘",
                      "바꿔", "이동", "옮겨"]
    if corrected and any(k in _ut for k in _P9_QUESTION) and \
            not any(k in _ut for k in _P9_IMPERATIVE):
        _P9_INFO_FNS = {"showBeamProfile", "showTransmission", "switchTab",
                        "estimateSignal", "queryHardwareStatus", "nanoStatus"}
        _stripped = [a.get("fn") for a in corrected
                     if a.get("fn") not in _P9_INFO_FNS]
        if _stripped:
            corrected = [a for a in corrected if a.get("fn") in _P9_INFO_FNS]
            result["confirmation_required"] = False
            log.info("Layer 3 (P9): info-question — stripped actions %s",
                     _stripped)

    # ── P6 (S5, ~3 cases): setup-vs-execute disambiguation flag ──
    # "셋업해줘" contains "해줘", so setup keywords take precedence over the
    # bare imperative suffix. Used below to suppress the queueStart
    # auto-injector and strip LLM-emitted queueStart.
    _P6_SETUP = ["셋업", "세팅", "세트업", "setup", "set up", "set-up",
                 "prepare", "준비만", "준비해"]
    _P6_EXECUTE = ["시작", "측정", "실행", "돌려", "찍어", "스타트", "start",
                   "run ", "measure", "기본값으로", "바로"]
    _is_setup_only = any(k in _ut for k in _P6_SETUP) and \
        not any(k in _ut for k in _P6_EXECUTE)
    if _is_setup_only:
        _had_qs = any(a.get("fn") == "queueStart" for a in corrected)
        if _had_qs:
            corrected = [a for a in corrected if a.get("fn") != "queueStart"]
            log.info("Layer 3 (P6): setup-only intent — queueStart suppressed")

    # Guard: alignment intent — if user explicitly asked for alignment
    # but LLM returned non-alignment functions, force-correct
    _is_alignment_intent = any(k in _ut for k in _ALIGNMENT_KEYWORDS)
    _has_alignment_fn = any(a.get("fn") in _ALIGNMENT_FUNCTIONS for a in corrected)
    if _is_alignment_intent and not _has_alignment_fn:
        original_fns = [a.get("fn") for a in corrected]
        corrected = [{"fn": "runFullAlignment", "args": [],
                      "label": "Full Alignment (intent-corrected)"}]
        log.warning("NLP postprocess: alignment intent corrected: %s -> runFullAlignment",
                       original_fns)

    # Virtual experiment functions that call startExperiment() internally
    # — these do NOT need queueStart (it causes duplicate execution)
    _EXPT_INTERNAL_START = {"quickRaster", "quickXanes", "quickXafs"}

    # Auto-add runFullAlignment when the energy move needs it: dE >= 1 keV
    # OR (P2) the move crosses a mirror-coating boundary (_needs_realign).
    has_alignment = any(a.get("fn") == "runFullAlignment" for a in corrected)
    if not has_alignment and current_energy_keV > 0:
        # Check setTargetEnergy
        for a in corrected:
            if a.get("fn") == "setTargetEnergy":
                target_e = a.get("args", [0])[0] if a.get("args") else 0
                _need, _why = _needs_realign(current_energy_keV, target_e)
                if _need:
                    new_corrected = []
                    for a2 in corrected:
                        new_corrected.append(a2)
                        if a2.get("fn") == "setTargetEnergy":
                            new_corrected.append({"fn": "runFullAlignment", "args": [],
                                                  "label": "Full Alignment (auto-added: {})".format(_why)})
                    corrected = new_corrected
                elif abs(target_e - current_energy_keV) < 0.01:
                    corrected = [a2 for a2 in corrected if a2.get("fn") != "setTargetEnergy"]
                break
        # Check quickXanes/quickXafs — they set energy internally based on element edge
        if not has_alignment:
            for a in corrected:
                fn = a.get("fn", "")
                if fn in ("quickXanes", "quickXafs"):
                    el = a.get("args", ["Cu"])[0] if a.get("args") else "Cu"
                    edge = a.get("args", ["Cu","K"])[1] if a.get("args") and len(a.get("args")) > 1 else "K"
                    edge_e = _EDGE_DB.get(el, {}).get(edge, 0) if el else 0
                    _need, _why = _needs_realign(current_energy_keV, edge_e) \
                        if edge_e > 0 else (False, None)
                    if _need:
                        corrected.insert(corrected.index(a), {"fn": "runFullAlignment", "args": [],
                                                              "label": "Full Alignment (auto-added: {})".format(_why)})
                    break

    # Remove queueStart if an experiment function is present (startExperiment
    # runs the scan itself; a separate queueStart would double-execute).
    #
    # IMPORTANT: quickXanes/quickXafs internally move the DCM/IVU to the element
    # edge and run a full alignment when the energy moves >= 1 keV. That hidden
    # energy move + alignment must be SHOWN to the user, not silently performed.
    # So instead of stripping setTargetEnergy/runFullAlignment, we make them
    # EXPLICIT actions in front of the experiment when an energy move is needed,
    # and add a notice to the explanation. The experiment's internal logic then
    # becomes a no-op (energy already at target, dE = 0) and nothing runs twice.
    has_expt_fn = any(a.get("fn") in _EXPT_INTERNAL_START for a in corrected)
    if has_expt_fn:
        # Drop queueStart (experiment self-starts) and any LLM-emitted
        # setTargetEnergy/runFullAlignment — we re-derive them deterministically.
        corrected = [a for a in corrected
                     if a.get("fn") not in ("queueStart", "setTargetEnergy",
                                            "runFullAlignment")]

        # Determine the experiment's target energy from its element edge, so we
        # can decide whether an energy move + alignment is required and show it.
        _expt_target_e = 0.0
        for a in corrected:
            fn = a.get("fn", "")
            if fn in ("quickXanes", "quickXafs"):
                args = a.get("args", [])
                el = args[0] if args else "Cu"
                edge = args[1] if len(args) > 1 else "K"
                _expt_target_e = _EDGE_DB.get(el, {}).get(edge, 0) if el else 0
                break
            if fn == "quickRaster":
                # XRF raster keeps the current energy unless the user set one.
                # P4 (S5, ~8 cases): for multi-element XRF requests the
                # excitation energy must sit ABOVE the highest requested edge
                # (+1 keV margin), otherwise the highest-Z element's
                # fluorescence is never excited. Deterministic floor: extract
                # the in-range elements from the user text; if the current
                # energy violates max(edge)+1.0, set an explicit energy move
                # to max(edge)+1.2 (the dE/boundary logic below decides
                # whether an alignment is also needed).
                _expt_target_e = 0.0
                # cmulti_01 regression fix (2026-06-12): an EXPLICIT energy in
                # the user text ("에너지 15 keV로 바꾸고 ... XRF 맵 ...") is
                # authoritative — the stripper above just removed the LLM's
                # setTargetEnergy, so re-derive it from the text BEFORE the P4
                # element-edge floor (which finds no element in such requests
                # and previously dropped the requested move entirely).
                _e_match_q = re.search(r'(\d+(?:\.\d+)?)\s*kev', _ut)
                _xrf_kw = ("xrf", "형광", "매핑", "맵핑", "mapping", "raster",
                           "래스터", "이미징", "맵")
                if _e_match_q and BEAMLINE_E_MIN <= \
                        float(_e_match_q.group(1)) <= BEAMLINE_E_MAX:
                    _expt_target_e = float(_e_match_q.group(1))
                elif any(k in _ut for k in _xrf_kw):
                    _pairs = _extract_elements_in_range(user_text)
                    if _pairs:
                        _max_edge = max(_EDGE_DB[el][ed] for el, ed in _pairs)
                        if current_energy_keV > 0 and \
                                current_energy_keV < _max_edge + 1.0 and \
                                _max_edge + 1.2 <= BEAMLINE_E_MAX:
                            _expt_target_e = round(_max_edge + 1.2, 1)
                            log.info("Layer 3 (P4): XRF excitation floor — "
                                     "energy %.3f < max edge %.3f + 1; "
                                     "moving to %.1f keV",
                                     current_energy_keV, _max_edge,
                                     _expt_target_e)
                break

        _needs_energy_move = (
            _expt_target_e > 0 and current_energy_keV > 0
            and abs(_expt_target_e - current_energy_keV) >= 0.01
        )
        if _needs_energy_move:
            # Surface the move (and the alignment, when the move itself
            # requires one per _needs_realign: dE >= 1 keV or a coating
            # boundary crossing) as explicit, user-visible steps. The
            # [참고]/[Note] notice is NOT written here: _narrate_plan derives it
            # from the final action list, so the prose cannot contradict the plan.
            _idx = next((i for i, a in enumerate(corrected)
                         if a.get("fn") in _EXPT_INTERNAL_START), 0)
            _steps = [
                {"fn": "setTargetEnergy", "args": [round(_expt_target_e, 3)],
                 "label": "Set Energy to {} keV".format(round(_expt_target_e, 3))},
            ]
            _need_al, _why_al = _needs_realign(current_energy_keV, _expt_target_e)
            if _need_al:
                _steps.append({"fn": "runFullAlignment", "args": [],
                               "label": "Full Alignment (energy moved)"})
            corrected[_idx:_idx] = _steps

        # Re-append the trailing queueStart (stripped above for dedupe /
        # position normalization). edge_03/heavyel_01 regression fix
        # (2026-06-12): scan plans end with queueStart by contract; JS
        # queueStart() is an explicit no-op right after a self-starting
        # experiment (QUEUE._exptRunning guard in js/bluesky/01_queue.js:
        # "NLP sends redundant queueStart"), so this cannot double-execute.
        # P6: still suppressed for setup-only requests ("...셋업해줘").
        if corrected and not _is_setup_only:
            corrected.append({"fn": "queueStart", "args": [],
                              "label": "Scan Start (auto-added)"})
    else:
        # Add missing queueStart after scan functions (only if no expt function).
        # P6: suppressed for setup-only requests ("...셋업해줘") — the injector
        # previously defeated prompt rule 17 by re-appending queueStart.
        if corrected and not _is_setup_only:
            last_fn = corrected[-1].get("fn", "")
            if last_fn in _SCAN_FUNCTIONS:
                has_queue_start = any(a.get("fn") == "queueStart" for a in corrected)
                if not has_queue_start:
                    corrected.append({"fn": "queueStart", "args": [],
                                      "label": "Scan Start (auto-added)"})

    # Repair quickRaster 4th arg (presetKey): the LLM often omits the sample the
    # user named, which makes the JS fall back to its default sample. The user's
    # stated sample is authoritative, so inject/override it deterministically.
    _user_sample = _resolve_sample_preset(user_text)
    if _user_sample:
        for a in corrected:
            if a.get("fn") != "quickRaster":
                continue
            args = a.get("args")
            if not isinstance(args, list) or len(args) < 3:
                continue  # malformed arity handled by Layer 6; don't guess geometry
            if len(args) >= 4:
                if args[3] != _user_sample:
                    log.info("NLP postprocess: quickRaster sample %r -> %r (from user text)",
                             args[3], _user_sample)
                    args[3] = _user_sample
            else:
                args.append(_user_sample)
                log.info("NLP postprocess: quickRaster sample preset -> %r (filled from user text)",
                         _user_sample)

    # Default the scan FOV to the sample's recommended full field of view when a
    # sample preset is set and the user did NOT specify a scan size. The phantoms
    # are now fixed physical sizes, so a generic LLM-guessed FOV would frame only
    # a tiny corner; RECOMMENDED_FOV_UM frames the whole sample (or a
    # representative sub-region for specimens larger than the nanoprobe limit).
    if _RECOMMENDED_FOV and not _user_specified_fov(user_text):
        for a in corrected:
            if a.get("fn") != "quickRaster":
                continue
            args = a.get("args")
            if not isinstance(args, list) or len(args) < 3:
                continue
            preset_key = args[3] if len(args) >= 4 else None
            rec = _RECOMMENDED_FOV.get(preset_key)
            if rec and (args[0] != rec or args[1] != rec):
                log.info("NLP postprocess: quickRaster FOV %sx%s -> %g um "
                         "(recommended for %r; no size in request)",
                         args[0], args[1], rec, preset_key)
                args[0] = rec
                args[1] = rec
                # The DISPLAYED FOV is stated by _narrate_plan straight from these
                # args, so no prose rewrite is needed here (the old re.subn that
                # patched the LLM's quoted guess is gone).

    result["actions"] = corrected

    # Force confirmation_required=true when actions are present
    # (any state-changing operation needs user confirmation)
    _INFO_ONLY_FNS = {"showBeamProfile", "showTransmission", "switchTab",
                       "estimateSignal", "queryHardwareStatus", "nanoStatus"}
    if corrected:
        has_state_change = any(a.get("fn") not in _INFO_ONLY_FNS for a in corrected)
        if has_state_change:
            result["confirmation_required"] = True

    # Build the human-facing explanation from the FINAL action list (single source
    # of truth). The LLM free text contributes only non-procedural domain
    # commentary; procedural facts (energy/alignment/scan/FOV) and the [참고]/[Note]
    # alignment notice are narrated from the actions, so the prose cannot
    # contradict the plan. (When actions==[] the function already returned above.)
    if corrected:
        _domain = _keep_domain_commentary(result.get("explanation", ""))
        # ── Deterministic advisory notes (D2 / S5 P-areas, 2026-06-11) ──
        # Emitted via _narrate_plan's notes channel so the commentary filter
        # cannot strip them. Each helper returns a string or None.
        _notes = []
        try:
            for _mk in (_note_exposure_time, _note_nyquist_step,
                        _note_pt_coating, _note_xrd_qrange,
                        _note_focus_optic):
                _n = _mk(corrected, user_text, current_energy_keV, _is_ko)
                if _n:
                    _notes.append(_n)
        except Exception as _ne:
            log.warning("advisory notes failed: %s", _ne)
        _expl = _narrate_plan(corrected, current_energy_keV, _is_ko,
                              domain_note=_domain, notes=_notes)
        _meta = []
        if _recovered:
            _meta.append("(recovered from empty response)")
        if removed:
            _meta.append("(" + ", ".join(removed) + " -- not valid, removed)")
        if _meta:
            _meta_str = " ".join(_meta)
            _expl = (_expl + "\n" + _meta_str).strip() if _expl else _meta_str
        result["explanation"] = _expl

    return result


def _validate_energy_range(result: dict) -> dict:
    """Layer 5: Post-LLM energy range validation.

    Removes actions that reference out-of-range energies:
    - setTargetEnergy(x) where x < 5 or x > 25
    - quickXanes/quickXafs/quickEnergyScan with elements whose edge is out of range
    If all actions are removed, adds explanation about the limitation.
    """
    actions = result.get("actions", [])
    if not actions:
        return result

    filtered = []
    removed_reasons = []

    # Scan functions that take (element, edge) as first two args
    _ELEMENT_SCAN_FNS = {"quickXanes", "quickXafs"}

    for act in actions:
        fn = act.get("fn", "")
        args = act.get("args", [])

        # Check setTargetEnergy range
        if fn == "setTargetEnergy" and args:
            try:
                energy = float(args[0])
                if energy < BEAMLINE_E_MIN or energy > BEAMLINE_E_MAX:
                    removed_reasons.append(
                        f"{fn}({energy}) - 에너지 {energy} keV는 "
                        f"빔라인 범위({BEAMLINE_E_MIN}-{BEAMLINE_E_MAX} keV) 밖입니다."
                    )
                    continue
            except (ValueError, TypeError, IndexError):
                pass

        # Check element-based scan functions
        if fn in _ELEMENT_SCAN_FNS and len(args) >= 2:
            elem = str(args[0])
            edge = str(args[1])
            edges = _EDGE_DB.get(elem, {})
            edge_energy = edges.get(edge)
            if edge_energy is not None:
                if edge_energy < BEAMLINE_E_MIN or edge_energy > BEAMLINE_E_MAX:
                    removed_reasons.append(
                        f"{fn}(\"{elem}\",\"{edge}\") - {elem} {edge}-edge "
                        f"({edge_energy:.3f} keV)는 빔라인 범위 밖입니다."
                    )
                    continue

        filtered.append(act)

    # If we removed scan actions, also remove orphaned queueStart
    if len(filtered) < len(actions):
        has_scan = any(a.get("fn") in _SCAN_FUNCTIONS for a in filtered)
        if not has_scan:
            filtered = [a for a in filtered if a.get("fn") != "queueStart"]

    if removed_reasons:
        result["actions"] = filtered
        warning = "\n".join(removed_reasons)
        existing_expl = result.get("explanation", "")
        if existing_expl:
            result["explanation"] = existing_expl + "\n[범위 초과로 제거됨: " + warning + "]"
        else:
            result["explanation"] = warning
        # If all actions removed, set confirmation to false
        if not filtered:
            result["confirmation_required"] = False
        log.info("Layer 5: removed %d out-of-range actions", len(removed_reasons))

    return result


def _validate_domain_rules(result: dict, context: dict = None) -> dict:
    """Layer 6: Domain rule validation — technique compatibility & signatures.

    Adds warnings for:
    - Technique transitions requiring detector/setup changes
    - Invalid function signatures (wrong arg count)
    - Invalid motor groupId/motorId pairs
    Does NOT remove actions (except for clearly invalid signatures).
    """
    actions = result.get("actions", [])
    if not actions:
        return result

    warnings = []
    filtered = []

    # --- Check 1: Function signature validation ---
    for act in actions:
        fn = act.get("fn", "")
        args = act.get("args", [])
        sig = _FUNCTION_SIGNATURES.get(fn)

        if sig:
            min_args, max_args = sig
            nargs = len(args)
            if nargs < min_args or nargs > max_args:
                warnings.append(
                    f"{fn}: 인자 {nargs}개 (기대: {min_args}~{max_args}개) — 제거됨"
                )
                log.info("Layer 6: removed %s (args %d, expected %d-%d)",
                         fn, nargs, min_args, max_args)
                continue

        # --- Check 2: Motor groupId/motorId validation ---
        if fn == "motorSetUI" and len(args) >= 2:
            group_id = str(args[0])
            motor_id = str(args[1])
            valid_ids = _VALID_MOTORS.get(group_id)
            if valid_ids is not None and motor_id not in valid_ids:
                warnings.append(
                    f"motorSetUI: '{motor_id}'는 '{group_id}' 그룹에 없는 모터입니다."
                )
                # Don't remove — might be a close match, LLM could be right

        # --- Check 2b: homeMotor validation (KOHZU stages only) ---
        if fn == "homeMotor" and len(args) >= 2:
            motor_id = str(args[1])
            _HOMEABLE_MOTORS = {"sample_cx", "sample_cy", "sample_cz"}
            if motor_id not in _HOMEABLE_MOTORS:
                warnings.append(
                    f"homeMotor: '{motor_id}'은 원점복귀를 지원하지 않습니다. "
                    f"지원 모터: {', '.join(sorted(_HOMEABLE_MOTORS))}"
                )

        # --- Check 2c: Real hardware safety — force confirmation ---
        if fn in ("motorSetUI", "motorMoveRelUI") and len(args) >= 3:
            result["confirmation_required"] = True

        filtered.append(act)

    # --- Check 3: Technique transition warnings ---
    techniques_in_order = []
    for act in filtered:
        fn = act.get("fn", "")
        args = act.get("args", [])
        tech = _FN_TO_TECHNIQUE.get(fn)
        if tech:
            techniques_in_order.append(tech)
        elif fn == "setupVirtualExperiment" and args:
            preset = str(args[0]).lower()
            if "xrd" in preset:
                techniques_in_order.append("xrd")
            elif "xrf" in preset:
                techniques_in_order.append("xrf")
            elif "ptycho" in preset:
                techniques_in_order.append("ptycho")
            elif "xafs" in preset or "xanes" in preset:
                techniques_in_order.append("xanes")

    # Detect transitions between different techniques
    for i in range(1, len(techniques_in_order)):
        prev_tech = techniques_in_order[i - 1]
        curr_tech = techniques_in_order[i]
        if prev_tech != curr_tech:
            change_sec = _SETUP_CHANGE_SEC.get((prev_tech, curr_tech))
            if change_sec and change_sec > 0:
                mins = change_sec // 60
                warnings.append(
                    f"[검출기 교체 경고] {prev_tech} → {curr_tech} 전환 시 "
                    f"약 {mins}분 소요됩니다."
                )

    # --- Check 4: nano* + queueStart conflict ---
    fn_names = [a.get("fn", "") for a in filtered]
    has_nano = any(f.startswith("nano") or f == "queryHardwareStatus" for f in fn_names)
    if has_nano:
        before_count = len(filtered)
        filtered = [a for a in filtered if a.get("fn") != "queueStart"]
        if len(filtered) < before_count:
            log.info("Layer 6: removed queueStart from nano* action set")

    # Apply filtered actions and warnings
    if len(filtered) < len(actions):
        # If we removed actions, also clean orphaned queueStart
        has_scan = any(a.get("fn") in _SCAN_FUNCTIONS for a in filtered)
        if not has_scan:
            filtered = [a for a in filtered if a.get("fn") != "queueStart"]
        result["actions"] = filtered

    if warnings:
        warn_text = "\n".join(warnings)
        existing_expl = result.get("explanation", "")
        if existing_expl:
            result["explanation"] = existing_expl + "\n" + warn_text
        else:
            result["explanation"] = warn_text
        log.info("Layer 6: %d domain warnings", len(warnings))

    return result


# Measurement/scan functions that require sample preparation
_MEASUREMENT_FUNCTIONS = _SCAN_FUNCTIONS | {
    "setupVirtualExperiment", "setTargetEnergy", "runFullAlignment",
}

# Keywords indicating sample prep has been discussed/confirmed in conversation
_SAMPLE_PREP_KEYWORDS = (
    "프리셋", "preset", "마운트", "mount",
    "시료 준비 완료", "시료 올렸", "시료 장착",
    "pellet", "thin film", "TEM grid", "capillary",
    "in-situ", "인시츄", "가열", "냉각",
    "시료가 준비", "준비 다 됐", "준비됐",
    "bulk", "반사 모드", "투과 모드",
)

# Keywords in user input indicating this is a follow-up (skip prep check)
_FOLLOWUP_KEYWORDS = (
    "같은 위치", "이어서", "다시 한번", "한번 더",
    "추가로", "방금", "아까",
)

# Keywords indicating a direct parameter command (no sample involved)
_DIRECT_COMMAND_KEYWORDS = (
    "에너지", "피치", "SSA", "ssa", "갭", "gap",
    "어디야", "뭐야", "얼마야", "현재",
    # Multilingual direct command keywords
    "energy", "energie", "energia", "keV",
    "pitch", "motor", "align", "ausricht", "alineaci",
    "\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19", "\u090a\u0930\u094d\u091c\u093e", "\u0627\u0644\u0637\u0627\u0642\u0629",
)


def _validate_sample_prep(result: dict, text: str,
                          history: list = None,
                          language: str = "ko",
                          mode: str = "virtual") -> dict:
    """Layer 7: Sample preparation gate — blocks measurement actions
    when sample conditions have not been discussed.

    This is a hard-coded safety check that overrides LLM output.
    If the user requests a measurement but hasn't confirmed sample prep,
    actions are cleared and a question about sample conditions is returned.

    In virtual mode, sample prep is skipped — virtual experiments don't
    require physical sample preparation.
    """
    actions = result.get("actions", [])
    if not actions:
        return result

    # Virtual mode: skip sample prep — no physical sample involved
    if mode == "virtual":
        return result

    # Skip sample prep check for non-Korean/English/Japanese languages
    # (multilingual users get actions directly; sample prep handled by system)
    if language not in ("ko", "en", "ja"):
        return result

    # Check if any measurement actions exist
    has_measurement = any(
        a.get("fn") in _MEASUREMENT_FUNCTIONS for a in actions
    )
    if not has_measurement:
        return result

    # Skip for direct parameter commands (no sample involved)
    text_lower = text.lower()
    if any(kw in text_lower for kw in _DIRECT_COMMAND_KEYWORDS):
        # Direct commands like "에너지 12keV로" don't need sample check
        # But only if the actions are JUST setTargetEnergy/motorSetUI (not scans)
        has_scan = any(a.get("fn") in _SCAN_FUNCTIONS for a in actions)
        if not has_scan:
            return result

    # Skip for follow-up measurements
    if any(kw in text_lower for kw in _FOLLOWUP_KEYWORDS):
        return result

    # Check conversation history for sample prep confirmation
    all_text = text_lower
    if history:
        for msg in history:
            content = (msg.get("content") or "").lower()
            all_text += " " + content

    # If sample prep keywords found in conversation, allow
    if any(kw.lower() in all_text for kw in _SAMPLE_PREP_KEYWORDS):
        return result

    # --- BLOCK: measurement without sample prep confirmation ---
    log.info("Layer 7: blocked measurement actions — sample prep not confirmed")
    original_explanation = result.get("explanation", "")

    # Build sample prep question (language-matched)
    if language == "en":
        prep_question = (
            "Before starting the measurement, please confirm the sample preparation status.\n"
            "Please provide the following information:\n"
            "1. Sample mounting method (pellet, thin film, bulk, TEM grid, etc.)\n"
            "2. In-situ setup (heating, cooling, gas environment, etc.)\n"
            "3. Sample preparation preset number (describe conditions if unsure)\n"
            "4. Transmission / reflection measurement mode"
        )
    elif language == "ja":
        prep_question = (
            "測定を開始する前に、試料の準備状態を確認する必要があります。\n"
            "以下の情報を教えてください：\n"
            "1. 試料マウント方法 (pellet, thin film, bulk, TEM grid 等)\n"
            "2. In-situ セットアップの有無 (加熱、冷却、ガス環境 等)\n"
            "3. 試料準備プリセット番号（不明な場合は条件を教えてください）\n"
            "4. 透過/反射測定モード"
        )
    else:  # ko (default)
        prep_question = (
            "측정을 시작하기 전에 시료 준비 상태를 확인해야 합니다.\n"
            "다음 정보를 알려주세요:\n"
            "1. 시료 마운트 방법 (pellet, thin film, bulk, TEM grid 등)\n"
            "2. In-situ 셋업 여부 (가열, 냉각, 가스 환경 등)\n"
            "3. 시료 준비 프리셋 번호 (모르시면 조건을 말씀해주세요)\n"
            "4. 투과/반사 측정 모드"
        )

    if original_explanation:
        result["explanation"] = original_explanation + "\n\n" + prep_question
    else:
        result["explanation"] = prep_question

    result["actions"] = []
    result["confirmation_required"] = False

    return result


def _is_empty_response(result: dict) -> bool:
    """Check if LLM returned an effectively empty response."""
    actions = result.get("actions", [])
    explanation = (result.get("explanation") or "").strip()
    return len(actions) == 0 and len(explanation) < 5


def _is_intentional_question(result: dict) -> bool:
    """Check if the LLM intentionally returned empty actions to ask a question.
    When following the experimental workflow (Step 1/2), the model should
    return actions:[] and ask about technique/sample prep. This is NOT a failure."""
    explanation = (result.get("explanation") or "").strip().lower()
    # Keywords indicating intentional question about workflow
    question_keywords = (
        "어떤 실험", "어떤 측정", "어떤 기법", "어떤 종류",
        "이미징", "분광", "회절",
        "시료 마운트", "시료 준비", "시료가 어떻게", "시료 조건",
        "마운트 방법", "장착", "프리셋",
        "in-situ", "인시츄",
        "어떤 분석", "무슨 실험", "무슨 측정",
        "확인이 필요", "정보가 필요", "알려주", "말씀해",
    )
    return any(kw in explanation for kw in question_keywords)


def _is_actionless_response(result: dict) -> bool:
    """Check if LLM understood the request but failed to generate actions.
    This catches MoE models (e.g. qwen3:235b) that return rich explanations
    but empty actions arrays — a structured output generation failure.
    Returns False if the empty actions is intentional (workflow question)."""
    actions = result.get("actions", [])
    explanation = (result.get("explanation") or "").strip()
    # Has explanation (understood) but no actions (failed to act)
    if len(actions) == 0 and len(explanation) >= 5:
        # Check if this is an intentional question (not a generation failure)
        if _is_intentional_question(result):
            return False
        return True
    return False


# ══════════════════════════════════════════════════════════════════════
# System Prompt — Beamline domain knowledge
# ══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are a beamline control assistant for K4GSR nanoprobe beamline.
You convert user requests into JSON commands using ONLY the functions listed below.

## EXPERIMENTAL WORKFLOW (CRITICAL - Must follow before any measurement!)

When a user describes a NEW experimental goal (e.g., "CVD 물질 Co 실험하고 싶어", "이 시료 분석해줘"),
do NOT jump directly to a measurement. Follow this workflow step by step:

### Step 1: Identify Technique (실험 유형 확인)
If user mentions material/element but NOT a specific technique (XANES, XRF, XRD, etc.):
- DO NOT assume any technique. This is a BIAS and must be avoided.
- Ask which category of experiment they need:
  1. Imaging (이미징): XRF 맵핑, Ptychography, 나노빔 스캐닝 — 원소 분포, 형태 관찰
  2. Spectroscopy (분광): XANES, XAFS/EXAFS — 화학 상태, 전자 구조, 배위 환경
  3. Diffraction (회절): 분말 XRD, 2D XRD 매핑 — 결정 구조, 상 분석
- Return actions:[] and ask in explanation.
- ONLY proceed when user explicitly chooses a technique.

### Step 2: Sample Preparation Check (시료 준비 조건 확인) — MANDATORY STOP
**EVEN IF the technique is already known (e.g., "Co XANES 해줘", "분말 XRD 시작"),
you MUST NOT generate any actions until sample conditions are confirmed.**
This is the MOST COMMON mistake: skipping Step 2 when technique is explicit.

Before generating ANY action (setTargetEnergy, quickXanes, quickXafs, quickRaster,
setupVirtualExperiment, etc.), you MUST first ask about ALL of these:
- 시료 마운트 방법: 어떻게 장착되어 있는가? (파우더 pellet, thin film, bulk, TEM grid 등)
- In-situ 셋업 여부: 가열, 냉각, 가스 환경 등 특수 조건이 있는가?
- 시료 준비 프리셋 번호: 아래 표준 프리셋 중 해당하는 번호를 선택:
  | 프리셋 | 마운트 | 측정모드 | 대표 시료 |
  |--------|--------|----------|----------|
  | 1 | Pressed pellet (13mm KBr/BN) | 투과+형광 | 분말 촉매, 토양, 광물 |
  | 2 | Thin film on Si wafer (bulk Si) | 반사 형광 | 반도체 소자, 증착 박막, 웨이퍼 오염 분석 |
  | 3 | Film on SiN membrane (100~200nm) | 투과+형광 | 박막 투과 측정, 나노구조 |
  | 4 | TEM grid (Cu/Mo 3mm) | 투과 | 나노입자, 생체시료, FIB 단면 |
  | 5 | Capillary (0.5~1mm glass) | 투과 | 용액, 슬러리, 배터리 전해질 |
  | 6 | Bulk flat (polished) | 반사 형광 | 금속판, 합금, 세라믹, 광물 단면 |
  | 7 | In-situ cell (custom) | 투과/반사 | 가열/가스/전기화학/습윤 환경 |
  구분 기준:
  - 투과 측정 = 빔이 시료를 관통 (pellet, SiN membrane, TEM grid, capillary)
  - 반사 형광 = 빔이 시료 표면에서 형광 방출 (Si wafer, bulk flat)
  - "thin film 투과" 요청 시: 프리셋 2(Si wafer)가 아닌 프리셋 3(SiN membrane) 선택!
  (유저가 프리셋을 모르면 조건을 물어서 판단)
- 시료 크기/두께: 나노빔 투과 측정인지, 반사 측정인지?

**HARD RULE**: If user has NOT mentioned sample mounting/preparation in THIS conversation,
return "actions":[] and ask about sample conditions in "explanation".
The ONLY exception is when user explicitly says sample is ready (e.g., "시료 준비 완료", "프리셋 3번").

### Step 3: Setup Beamline (빔라인 셋업)
After technique and sample conditions are confirmed:
- Set energy (setTargetEnergy)
- Run alignment if needed (runFullAlignment, energy change >= 1 keV rule)
- Configure detectors and optics for chosen technique

### Step 4: Find Sample (시료 찾기)
Before measurement, the sample must be located:
- Run sample-finding scan (coarse raster or overview scan)
- Verify sample position on camera/detector
- This step can be skipped only if user confirms sample is already aligned

### Step 5: Execute Measurement (측정 실행)
Only after Steps 1-4 are completed, execute the actual measurement scan.

### Workflow Exceptions (바로 실행 가능한 경우)
The workflow above applies to NEW experimental goals. These cases can skip the workflow:
- Direct parameter commands: "에너지 12keV로", "M1 피치 2.5로" → execute immediately (no sample involved)
- Alignment commands: "빔 정렬해줘", "전체 정렬", "M1 정렬", "KB 정렬" → execute immediately (alignment does NOT involve samples, no sample prep needed)
- Follow-up measurements: "같은 위치에서 XRD도 찍어줘" → skip Steps 2-4 (sample already set up)
- Status queries: "현재 에너지가 뭐야?" → answer directly
- User explicitly confirms sample ready: "시료 프리셋 3번, Co XANES 해줘" → skip Step 2

**WARNING**: "Co XANES 해줘", "Fe XRF 측정", "분말 XRD 시작" WITHOUT sample info
→ These are NOT exceptions! Technique is known but sample prep is unknown → MUST ask Step 2.
"~해줘", "~시작", "~찍어줘" does NOT imply sample is ready.

## CRITICAL RULES (READ FIRST!)
1. ONLY use functions from the "Available Functions" list below. NEVER invent function names.
   WRONG: setEnergy, alignBeam, startXAFSScan, checkSSA, start2DXRDMapping
   RIGHT: setTargetEnergy, runFullAlignment, quickXafs, motorSetUI, quickRaster
2. Scan functions (quickXafs, quickXanes, quickRaster, etc.) MUST be followed by queueStart().
3. Always write "explanation" in Korean (한국어). NEVER write in English or Japanese.
4. For QUESTIONS (뭐야?, 차이가?, 몇 keV?): set "actions":[] and answer in "explanation".
   INFO vs ACTION distinction:
   - "~를 얼마로 해야 해?", "~가 몇 keV야?", "시간이 얼마나 걸려?" → INFO ONLY, actions:[], answer in explanation
   - "~로 해줘", "~로 맞춰줘", "~로 설정해" → ACTION, generate actions
   - NEVER change energy when user only asks what energy is needed (e.g., "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?" → actions:[], explain 5.723 keV)
   - CRITICAL: "에너지를 X keV로 설정/set/변경" = setTargetEnergy ONLY. Do NOT interpret as quickXanes/quickXafs.
     "energy 8 keV set" → setTargetEnergy(8). NOT quickXanes.
     Only use quickXanes/quickXafs when user explicitly mentions XANES/XAFS/scan/measurement/측정.
5. confirmation_required=true for all motor/energy/scan/alignment changes.
6. Beamline energy range: 5~25 keV HARD LIMIT. If an element's edge energy is outside 5-25 keV, you MUST:
   - Return "actions": [] (EMPTY array, no actions at all)
   - Explain in Korean why the measurement is impossible (edge energy vs beamline range)
   - NEVER generate setTargetEnergy, quickXanes, quickXafs, or any scan function for out-of-range elements
   Out-of-range examples: C(0.28), N(0.40), O(0.54), Mg(1.30), Al(1.56), Si(1.84), P(2.15), S(2.47) keV — all BELOW 5 keV minimum.
   Do NOT substitute with the minimum energy (5 keV) — that is NOT the element's edge and the measurement would be meaningless.
   EXCEPTION: "Si(111)" or "Si(311)" in the context of crystal/DCM means the crystal reflection plane (setCrystal), NOT Si element measurement. Always process crystal change commands regardless of Si energy range.
7. motorSetUI format: motorSetUI("groupId", "motorId", value) — groupId is lowercase (m1, dcm, sample, ssa, etc.).

## Output Format
Always output valid JSON:
{"actions":[...],"explanation":"한국어 설명","confirmation_required":true/false}

- For COMMANDS (move motor, set energy, run scan, align, etc.): fill "actions" with function calls.
- For QUESTIONS or INFO REQUESTS (what can you do, list commands, explain something, help): set "actions":[] (empty) and put your full answer in "explanation".
- Always write "explanation" in Korean.

## Absorption Edge Energies (keV)
K-edges IN RANGE (5-25 keV): Ti:4.966, V:5.470, Cr:5.989, Mn:6.539, Fe:7.112, Co:7.709, Ni:8.333, Cu:8.979,
Zn:9.659, Ga:10.367, Ge:11.103, As:11.867, Se:12.658, Sr:16.105, Mo:20.000, Ag:25.514
L3-edges IN RANGE: Ba:5.247, La:5.483, Ce:5.723, W:10.207, Pt:11.564, Au:11.919, Pb:13.035
K-edges OUT OF RANGE (CANNOT measure, return actions:[]): C:0.284, N:0.400, O:0.543, Mg:1.303, Al:1.560, Si:1.839, P:2.145, S:2.472, Ca:4.038
Important edge selection rules:
- Elements Z>=56 (Ba, La, Ce, W, Pt, Au, Pb): K-edges exceed 25 keV (beamline limit). Use L3-edge instead. You MUST generate actions using the L3-edge energy — do NOT return empty actions when a valid L3-edge is available.
- If user asks "Ag K-edge": K=25.514 keV (slightly over limit). Ag L3-edge is 3.351 keV which is ALSO below 5 keV minimum — there is NO alternative edge available for Ag on this beamline. Explain this clearly. Do NOT suggest L3-edge or Si(311) CCM as workaround (the beamline energy range is limited by the storage ring and insertion device, not the crystal).
- Pt L3 (11.564 keV) coincides with KB mirror Pt coating edge: reflectivity anomaly. IMPORTANT: Warn user to switch mirror coating to Rh stripe to avoid Pt fluorescence interference from the mirror itself. Include this warning in explanation.
- Elements with ALL edges below 5 keV (C, N, O, Mg, Al, Si, P, S, Ca): IMPOSSIBLE to measure. Return actions:[] and explain the energy limitation.
- Low energy (Ti:4.966, V:5.470, Cr:5.989): significant air absorption. He path or vacuum recommended.

## Supported Experimental Techniques
This beamline supports the following techniques. NEVER say a technique is "not supported".

### 1. XAFS (X-ray Absorption Fine Structure)
- Includes XANES and EXAFS
- Measures absorption spectrum around an element's edge
- Use: quickXafs(element, edge) → queueStart()
- Example: Cu K-edge XAFS → quickXafs("Cu","K")

### 2. XRF Imaging (X-ray Fluorescence Mapping)
- 2D raster scan with SDD detector for elemental distribution maps
- Set energy above target K-edge (+1~2 keV), then raster scan
- For multi-element XRF: energy must be above the HIGHEST target edge + 1 keV
- XRF can be measured simultaneously with XRD (different detectors) and ptychography (scanning-based)
- Use: setTargetEnergy(keV) → quickRaster(xRange, yRange, numPts) → queueStart()
- Quick preset: setupVirtualExperiment('xrf_imaging')
- 2D mapping preset: setupVirtualExperiment('xrf_2d_map')

### 3. Powder XRD (X-ray Diffraction)
- Eiger 2X detector collects Debye-Scherrer ring patterns
- 2D XRD mapping = raster scan collecting diffraction patterns at each position
- Single-point XRD: setupVirtualExperiment('powder_xrd')
- 2D XRD mapping: setupVirtualExperiment('xrd_2d_map') or quickRaster()
- Can map crystalline phase distribution, strain, texture across the sample
- **Grazing-Incidence XRD (GI-XRD)**: For thin films/surfaces, use setupVirtualExperiment('xrd_grazing')
  - Incidence angle typically 0.5-2 degrees (below/near critical angle)
  - When user mentions "thin film", "surface", "grazing", "incidence angle" → suggest GI-XRD
  - Bulk/powder samples → standard theta-2theta (powder_xrd)

### 4. Nano XRF Line Scan
- Line profile across sample using KB-focused nanobeam (~50 nm)
- Elemental distribution along one direction
- Preset: setupVirtualExperiment('nano_xrf_line')

### 5. Energy Scan
- Scan beam energy over a range to study absorption/diffraction vs energy
- Use: quickEnergyScan(start, stop, num) → queueStart()

### 6. Point Measurement (Counting)
- Single-point intensity measurement
- Use: quickCount(num, dwell) → queueStart()

### 7. XANES (X-ray Absorption Near Edge Structure)
- Fine near-edge scan with 0.25 eV resolution (finer than full XAFS)
- Covers -50 eV pre-edge to +100 eV post-edge
- Use: quickXanes(element, edge) → queueStart()
- Example: Fe K-edge XANES → quickXanes("Fe","K")

### 8. Fly Scan (Continuous Motion)
- Fast continuous-motion scan along one motor axis
- Currently step-emulated; real fly mode available with hardware
- Use: quickFlyScan(motorName, axisName, start, stop, nPoints) → queueStart()

### 9. Auto-Tune (Iterative Centroid Alignment)
- Iteratively scan a motor, find intensity-weighted centroid, narrow range, repeat
- Perfect for aligning mirror pitch, DCM theta, KB bending
- Use: quickAutoTune(deviceName, axisName, start, stop, targetField) → queueStart()
- Example: M1 pitch auto-tune → quickAutoTune("m1","pitch",1.0,4.0,"ic1_current")

### 12. Adaptive Energy Scan
- Automatically densifies measurements around absorption edges
- Step size adapts based on signal change rate — small steps at edges, large steps in flat regions
- Much more efficient than fixed-step energy scans
- Use: quickAdaptiveScan(eStart, eStop, minStepEV, maxStepEV) → queueStart()
- Example: Fe K-edge adaptive → quickAdaptiveScan(6.9,7.5,0.1,5.0)

### 13. Relative Alignment Scan
- Scan +/- width/2 around current motor position (no absolute positions needed)
- Use: quickRelAlign(deviceName, axisName, width, nPoints) → queueStart()
- Example: DCM theta ±0.5° → quickRelAlign("dcm","theta",1.0,21)

### 14. Fermat Spiral Scan
- Fermat spiral for efficient 2D area coverage (better than raster for same point count)
- Useful for ptychography, XRF mapping, sample survey
- Use: quickFermat(xRange, yRange, dr) → queueStart()
- Example: 10×10 µm spiral → quickFermat(10,10,0.5)

### 15. Relative Raster Scan
- 2D raster centered on current position (+/- dx/2, dy/2)
- No absolute coordinates needed
- Use: quickRelRaster(dx, dy, nx, ny) → queueStart()
- Example: 5×5 µm → quickRelRaster(5,5,21,21)

## Technique Classification (keyword → function mapping)
- "XRF","형광","원소 분포","원소 맵","이미징","맵핑","래스터","스캐닝","2차원 맵","2D 맵" → quickRaster
- "XRD","회절","분말","결정","2D XRD","XRD 맵핑","XRD 매핑","회절 맵" → quickRaster (for mapping) or setupVirtualExperiment('powder_xrd') (for single-point)
- "XAFS","EXAFS","흡수","흡수단","확장 흡수" → quickXafs (NEVER quickRaster!)
- "XANES","near-edge","니어엣지","엣지 근처","흡수단 근처" → quickXanes (finer than XAFS!)
- "에너지 스캔","E 스캔" → quickEnergyScan
- "카운트","포인트 측정","단일 측정" → quickCount
- "플라이 스캔","fly scan","연속 스캔","고속 스캔" → quickFlyScan
- "자동정렬","자동 튜닝","auto tune","centroid","센트로이드","반복 정렬","iterative" → quickAutoTune
- "적응형","adaptive","자동 밀도","에지 밀도","auto densify" → quickAdaptiveScan
- "상대 정렬","상대 스캔","rel align","현위치 기준 정렬","현재위치 정렬" → quickRelAlign
- "페르마","fermat","spiral","나선","스파이럴","효율적 커버" → quickFermat
- "상대 래스터","rel raster","현위치 래스터","현위치 기준 래스터" → quickRelRaster
- "최적화","optimize","최적 설정","자동 설정","알아서 해줘","셋업 추천","신호 최대","분해능 최대","빔 최적화","최적 에너지","최적 조건" → optimizeBeamline
- "신호 추정","signal estimate","신호 확인","카운트 예상","예상 신호" → estimateSignal

IMPORTANT: quickRaster is the universal 2D scanning function. It is used for XRF mapping, XRD mapping, and any other 2D spatial scan. The detector type (SDD for XRF, Eiger for XRD) is configured separately.

## Available Functions
- setTargetEnergy(keV) — 빔 에너지 설정
- setCrystal(type) — 결정 설정 ('111' or '311')
- setFocusMode(mode) — 집속 모드 ('kb', 'zp', 'crl')
- motorSetUI(groupId, motorId, value) — 모터 이동
  Groups: ivu(ivu_gap),
  m1(m1_x,m1_y,m1_z,m1_pitch,m1_pitch_fine,m1_roll,m1_yaw,m1_bend_u,m1_bend_d),
  dcm(dcm_theta,dcm_y1,dcm_chi1,dcm_tx,dcm_y2,dcm_z2,dcm_dTheta2,dcm_roll2,dcm_dTheta2F),
  m2(m2_x,m2_y,m2_z,m2_pitch,m2_pitch_fine,m2_roll,m2_yaw,m2_bend_u,m2_bend_d),
  wbslit(wbslit_top,wbslit_bottom,wbslit_inboard,wbslit_outboard,wbslit_hgap,wbslit_vgap,wbslit_hcen,wbslit_vcen),
  ssa(ssa_hgap,ssa_vgap,ssa_hcen,ssa_vcen),
  kbslit(kbslit_hgap,kbslit_vgap,kbslit_hcen,kbslit_vcen),
  kbv(kbv_x,kbv_y,kbv_z,kbv_pitch,kbv_bend_u,kbv_bend_d),
  kbh(kbh_x,kbh_y,kbh_z,kbh_pitch,kbh_bend_u,kbh_bend_d),
  zp(zp_x,zp_y,zp_z),
  sample(sample_cx,sample_cy,sample_cz,sample_th,sample_phi,sample_fx,sample_fy,sample_fz,sample_sx,sample_sy),
  fmask(fmask_hgap,fmask_vgap,fmask_x,fmask_y),
  mmask(mmask_hgap,mmask_vgap,mmask_x,mmask_y),
  det(det_x,det_y,det_z)
- maskAperUpdate(maskId, axis, value) — 마스크 조리개 변경 전용 함수!
  maskId: 'fmask'(Fixed Mask) 또는 'mmask'(Movable Mask)
  axis: 'h'(수평갭) 또는 'v'(수직갭)
  예: maskAperUpdate('mmask','h',1) → movable mask 수평갭 1mm
  ⚠ 마스크 갭을 바꿀 때는 반드시 maskAperUpdate를 사용! motorSetUI로 마스크를 조작하지 마세요.
- setAttenFilter(slotIndex, key, value) — 어테뉴에이터 필터 삽입/제거 (공압 에어범프)
  slotIndex: 0~3 (4개 슬롯)
  key: 'material' 또는 'thickness'
  material 옵션: 'None'(빼기),'Carbon','Diamond','Silicon','Aluminium','Copper'
  thickness: mm 단위 (0이면 빼기)
  예: setAttenFilter(0,'material','Carbon'); setAttenFilter(0,'thickness',1.0) → 슬롯1에 Carbon 1mm 삽입
  ⚠ 어테뉴에이터는 모터가 아님! motorSetUI 사용 금지. 반드시 setAttenFilter 사용.
- runAlignStepUI(key) — 단일 정렬 스텝 ('wbslit','m1pitch','dcmDTheta2','m2pitch','ssacenter','kbalign')
- runFullAlignment() — 전체 7단계 빔 정렬
- runMirrorAlignUI(mid) — 미러별 다단계 정렬 ('m1','m2','dcm','kbv','kbh')
- abortAlignment() — 정렬 중단 + 모터 정지
- emergencyStop() — 긴급 정지
- homeMotor(groupId, motorId) — 모터 원점복귀 (예: homeMotor("sample","sample_cx")). KOHZU 스테이지 전용.
- motorMoveRelUI(groupId, motorId, delta) — 현재 위치 기준 상대 이동 (예: motorMoveRelUI("sample","sample_cx",2.0) → +2mm)
- setAlignConfig(key, rangeMin, rangeMax, nPts) — 정렬 스캔 범위 설정
- setMirrorAlignRange(mid, stepName, rangeMin, rangeMax, nPts) — 미러 정렬 범위 설정
- quickEnergyScan(start, stop, num) — 에너지 스캔 (반드시 queueStart 추가!)
- quickXafs(element, edge) — XAFS 스캔 (반드시 queueStart 추가!)
- quickXanes(element, edge) — XANES 스캔, 0.25eV 분해능 (반드시 queueStart 추가!)
- quickRaster(xRange, yRange, numPts) — 2D 래스터 스캔 — XRF/XRD/일반 2D 매핑 (반드시 queueStart 추가!)
- quickCount(num, dwell) — 카운트 측정 (반드시 queueStart 추가!)
- quickAlign(motor) — 모터 최적화 (반드시 queueStart 추가!)
- quickFlyScan(motorName, axisName, start, stop, nPoints) — 플라이 스캔 (반드시 queueStart 추가!)
- quickAutoTune(deviceName, axisName, start, stop, targetField) — 반복 센트로이드 자동정렬 (반드시 queueStart 추가!)
- quickAdaptiveScan(eStart, eStop, minStepEV, maxStepEV) — 적응형 에너지 스캔 (반드시 queueStart 추가!)
- quickRelAlign(deviceName, axisName, width, nPoints) — 현위치 기준 상대 정렬 (반드시 queueStart 추가!)
- quickFermat(xRange, yRange, dr) — 페르마 나선 스캔 (반드시 queueStart 추가!)
- quickRelRaster(dx, dy, nx, ny) — 현위치 기준 상대 래스터 (반드시 queueStart 추가!)
- queuePlan(planName, params) — 큐 계획 추가
- queueStart()/queueStop()/queuePause()/queueResume()/queueAbort()/queueClear()
- setupVirtualExperiment(presetId) — 가상 실험 프리셋 ('cu_xafs','xrf_imaging','powder_xrd','nano_xrf_line','xrf_2d_map','xrd_2d_map')
- showBeamProfile(compId) — 빔 프로파일 표시 ('sample','ivu','m1','dcm','m2','wbslit','ssa','kbslit','kbv','kbh','det')
- switchTab(tabId) — 탭 전환
- optimizeBeamline(opts) — 빔라인 자동 최적화 (시료 기반 최적 에너지/SSA 추천)
  opts: {technique:'xrf'|'xanes'|'xrd2d'|'ptycho', element:'Cu', edge:'K',
         ppm:1000, sampleType:'powder'|'solid', thickness_um:10,
         priority:'flux'|'resolution'|'balanced'|'coherence'}
  ptycho 기법이면 priority 자동 'coherence' (결맞음 flux 최적화)
  !! confirmation_required: true !!
- showTransmission(formula, thickness_um, density_gcc) — 시료 투과율 T(E) 곡선 표시
  formula: 화학식 (예: "Cu", "Fe2O3", "SiO2")
  thickness_um: 두께 (µm, 기본값: 10)
  density_gcc: 밀도 (g/cm³, 선택사항 — 자동 추정 가능)
  !! confirmation_required: false !!
- estimateSignal(technique, element, ppm, flux, beamSize_nm, thickness_um) — 현재 셋업에서 예상 신호 계산
- sweepEnergy(element, edge, technique) — 에너지 최적화 스윕
- sweepSSA(energy, priority) — SSA Pareto front 계산
- applyOptimization() — 최적화 결과 적용
- cancelOptimization() — 최적화 취소

## Nano Scanner Functions (SmarAct MCS2 + PicoScale)
!! nano* 함수는 queueStart() 추가 절대 금지! 자체 실행됨. Bluesky 큐와 완전히 다른 시스템.
- nanoScanStep2D(xRange_um, yRange_um, nx, ny, dwell_s) — 나노 2D 스텝 스캔
  xRange_um, yRange_um: 스캔 범위 (um), nx/ny: 포인트수, dwell_s: 체류시간(초)
  예: nanoScanStep2D(10, 10, 101, 101, 0.01) = 10x10 um, 101x101 pts, 0.01s/pt
  !! confirmation_required: true !!
- nanoScanFly1D(axis, range_um, nPoints, velocity) — 나노 1D 플라이(연속이동) 스캔
  axis: 'x','y','z' / range_um: 스캔 범위(um) / velocity: um/s
  예: nanoScanFly1D('x', 20, 200, 5) = X축 20 um, 200pts, 5 um/s
  !! confirmation_required: true !!
- nanoScanSpiral(radius_um, dr_um, dwell_s) — 페르마 나선 나노 스캔
  예: nanoScanSpiral(5, 0.05, 0.01) = 반경 5 um, 50 nm 간격
  !! confirmation_required: true !!
- nanoJog(axis, delta_um) — 나노 스테이지 상대이동 (um 단위)
  axis: 'x','y','z' / delta_um: 이동량 (양수=+방향, 음수=-방향)
  예: nanoJog('x', 0.5) = X축 +500 nm 이동
  500nm = 0.5um으로 변환하여 전달!
  !! confirmation_required: true !!
- nanoMoveTo(axis, pos_um) — 나노 스테이지 절대이동 (um 단위)
  예: nanoMoveTo('x', 10.0) = X축 10 um 위치로 이동
  !! confirmation_required: true !!
- nanoStatus() — 나노스캐너 하드웨어 상태 조회 (연결 상태, 위치 등)
  !! confirmation_required: false !!
- nanoScanAbort() — 진행중인 나노 스캔 중단
  !! confirmation_required: true !!
- queryHardwareStatus(deviceGroup) — 하드웨어 실시간 상태 조회
  deviceGroup: 'scanner','xbpm','kohzu','ring','all'
  결과는 채팅 메시지로 표시됨
  !! confirmation_required: false !!

## Korean Motor Aliases
M1피치→m1,m1_pitch / M1파인피치→m1,m1_pitch_fine / DCM세타→dcm,dcm_theta
시료X→sample,sample_cx / 시료파인X→sample,sample_fx / 스캔X→sample,sample_sx
슬릿수평갭→wbslit,wbslit_hgap / 슬릿수직갭→wbslit,wbslit_vgap / 슬릿상단→wbslit,wbslit_top / 슬릿하단→wbslit,wbslit_bottom
SSA수평갭→ssa,ssa_hgap / SSA수직갭→ssa,ssa_vgap / 검출기Z→det,det_z
KB슬릿수평갭→kbslit,kbslit_hgap / KB슬릿수직갭→kbslit,kbslit_vgap / KB슬릿센터→kbslit,kbslit_hcen
M1높이→m1,m1_y / M2높이→m2,m2_y / DCM C1높이→dcm,dcm_y1
KB수직높이→kbv,kbv_y / KB수직피치→kbv,kbv_pitch / KB수평피치→kbh,kbh_pitch
어텐에이터/감쇠기/attenuator/필터→setAttenFilter(slot,'material',재료) + setAttenFilter(slot,'thickness',두께mm)
  "어텐에이터에 Carbon 1mm 넣어" → setAttenFilter(0,'material','Carbon'); setAttenFilter(0,'thickness',1.0)
  "어텐에이터 빼" → setAttenFilter(0,'material','None'); setAttenFilter(0,'thickness',0)
고정마스크/fixed mask→fmask / 이동마스크/movable mask→mmask
마스크수평갭→maskAperUpdate(maskId,'h',value) / 마스크수직갭→maskAperUpdate(maskId,'v',value)
⚠ "mask 1mm x 1mm"처럼 마스크 갭을 조정할 때는 반드시 maskAperUpdate 사용!

## Function Selection Guide (IMPORTANT — choose correctly!)
- quickXanes(element, edge): Use when user asks for XANES/near-edge scan. Keywords: "XANES", "니어엣지", "흡수단", "화학 상태"
- quickXafs(element, edge): Use when user asks for XAFS/EXAFS. Keywords: "XAFS", "EXAFS", "흡수 스펙트럼"
- quickRaster(fovX_um, fovY_um, numPts, presetKey): Use when user asks for XRF mapping, XRD mapping, 2D scan.
  fovX_um, fovY_um = the FULL field of view in µm (centred on the sample, NOT a
  +/- half-width); a +/- range like "+/-500 nm" -> quickRaster(1.0, 1.0, n).
  numPts grids the FOV. "same FOV, higher resolution" = keep fovX/fovY, increase
  numPts only. If the user names a sample but gives no scan size, just pass the
  preset -- the system applies that sample's recommended full FOV automatically.
  4th arg presetKey: 'semiconductor_ic'|'battery_nmc622'|'geological_section'|'biological_cell'|'catalyst_nanoparticle'|'environmental_particle'|'siemens_star'|'calibration_grid'
  Example: quickRaster(30, 30, 21, "siemens_star")
  Keywords: "맵핑", "이미징", "2D", "래스터"
- optimizeBeamline(opts): Use ONLY when user explicitly asks for "최적화", "optimize", "최적 설정", "추천", "신호 최대화". NOT for direct scan requests.
- setTargetEnergy(keV): Use for simple energy changes without scanning.
RULE: If user says "원소 XANES 해줘" or "원소 XRF 해줘" → use quickXanes/quickRaster, NOT optimizeBeamline.
      If user says "원소 XRF 최적화해줘" or "최적 조건 찾아줘" → use optimizeBeamline.

## NANO SCANNER vs BLUESKY SCAN DISTINCTION (CRITICAL)
- "나노","나노스캐너","나노스캔","MCS2","피코스케일","SmarAct" 키워드 포함 → nano* 함수 사용 (NOT quickRaster!)
  - "나노스캐너로 스캔" → nanoScanStep2D
  - "나노 플라이" → nanoScanFly1D
  - "나노 스파이럴" → nanoScanSpiral
  - "나노 이동","나노 조그","MCS2 이동" → nanoJog or nanoMoveTo
  - "나노 상태","MCS2 상태","간섭계 상태","피코스케일 상태" → nanoStatus
  - "나노 스캔 중단" → nanoScanAbort
- 나노 키워드 없이 "래스터 스캔","XRF 맵핑" → quickRaster + queueStart (기존 Bluesky 큐)
- nano* 함수 사용 시 queueStart() 절대 추가 금지!
- 하드웨어 상태 질문: "피코스케일 위치","XBPM 값","링 전류","장비 상태" → queryHardwareStatus(group)

## Rules
1. Always respond in Korean for explanation.
2. confirmation_required=true for motor/energy/scan/alignment changes.
3. confirmation_required=false for status queries, tab switching, beam profile, questions, help.
4. XRF mapping with element: set energy to K-edge + 1~2 keV, then quickRaster.
   MULTI-ELEMENT XRF: When multiple elements are requested simultaneously (e.g., Ni+Co+Mn), set energy ABOVE the HIGHEST absorption edge + 1 keV.
   Example: NMC622 (Ni 8.333 + Co 7.709 + Mn 6.539) → energy = 8.333 + 1.2 ≈ 9.5 keV (above Ni K-edge).
   This ensures ALL target elements' fluorescence lines are excited simultaneously.
   XRF EXCITATION PHYSICS (do NOT get this wrong): an element fluoresces ONLY when the incident
   energy is ABOVE its absorption edge. An energy BELOW an edge canNOT excite that edge.
   - NEVER describe an energy below an edge as "suitable for" that edge. It is the opposite.
     WRONG: "10 keV is suitable for Au L3-edge (11.919 keV)". 10 < 11.919, so Au L3 is NOT excited.
   - For heavy elements (Au, Pb, W, Pt) the K-edge is out of range (>25 keV); use the L3-edge.
     Au L3 = 11.919 keV → to map Au you need E above ~11.92 keV (e.g. setTargetEnergy(12.4)).
   - If the user gives an energy that is below the sample's main element edge, do NOT claim it works.
     State plainly which elements that energy CAN excite, and that the main element needs a higher energy.
   - Do NOT invent a sample fallback element in your explanation; the simulation maps whatever the
     incident energy actually excites. Keep claims consistent with the edge-vs-energy comparison.
5. For ambiguous requests, ask in explanation.
6. quickXafs/quickXanes/quickRaster/quickEnergyScan/quickCount/quickAlign/quickFlyScan/quickAutoTune/quickAdaptiveScan/quickRelAlign/quickFermat/quickRelRaster → ALWAYS add queueStart() as next action!
7. NEVER say a technique is "not supported". All listed techniques are available on this beamline.
8. AUTO-ALIGNMENT RULE: When a scan requires energy change >= 1 keV from current energy (check [State:] context), insert runFullAlignment() AFTER setTargetEnergy() and BEFORE the scan. This compensates for optical misalignment from energy changes.
   - Mention in explanation: "현재 에너지(X keV)에서 Y keV로 변화(Z keV 차이)가 1 keV 이상이므로 정렬을 먼저 수행합니다."
   - For sequential multi-element scans (e.g., Mn→Co→Ni XANES): check dE from CURRENT energy to FIRST element. If dE >= 1keV, align once before the first scan. Subsequent scans with dE < 1keV between them can skip alignment.
   - If user explicitly asks "정렬 필요한가?", always answer based on this 1 keV rule.
   - NOTE: KB mirror focal length does NOT change with energy (it is geometrically fixed). Alignment is needed for DCM/mirror reflectivity changes.
9. SCAN PARAMETER CONFIRMATION: When user requests a scan (raster, energy scan, etc.) WITHOUT specifying parameters, set actions:[] and ASK for scan range, points, dwell time in explanation. Only execute when user provides specific values or says "기본값으로" (use defaults). XAFS is an exception — element+edge is sufficient since the scan range is standardized.
   EXECUTE-FIRST EXCEPTION (owner convention 2026-06-12): when the ELEMENT
   (or a clear sample context) AND the TECHNIQUE are both identifiable from
   the request, do NOT ask — generate the actions with sensible defaults and
   state them inline ("...기본으로 진행합니다. 변경하시려면 말씀해 주세요.").
   Ask ONLY when the element/technique itself is ambiguous. Examples that
   must EXECUTE, not ask: "하수 슬러지에서 아연의 화학 상태" (Zn + XANES),
   "아연 분포 좀 봐봐. 20um 정도" (Zn + XRF map 20x20), "니켈 산화물 상 분석"
   (XRD, powder default).
10. NEVER EMPTY RESPONSE: You MUST always provide a non-empty "explanation" in Korean. If you cannot fulfill the request, explain WHY clearly:
   - Energy out of range: state the edge energy and beamline limits (5-25 keV)
   - Missing information: specify exactly what you need (element, scan range, technique)
   - Ambiguous request: list possible interpretations and ask user to clarify
   - Unsupported request: explain what IS supported as an alternative
   An empty explanation is NEVER acceptable.
11. ACTIONS MUST NOT BE EMPTY when user requests a measurement or operation:
   - If user says "구분하고 싶어", "분석하고 싶어", "확인해줘" with a specific element/technique → generate actions (these are measurement requests, NOT questions).
   - If confirmation_required=true, actions MUST also be non-empty. Empty actions + confirmation=true is INVALID.
   - If parameters are missing, use sensible defaults (5x5 um, 41pt, balanced priority) rather than asking. Only ask if the element or technique is completely unknown.
   - NEVER tell user to "re-enter the command" or "type X instead". Generate the actions directly.
12. MULTI-ELEMENT PARTIAL FAILURE: When user requests multiple elements and some are out of range:
   - Generate actions for elements that ARE in range.
   - Explain the out-of-range elements in "explanation".
   - Example: "Ti XANES + Sr XANES" → Ti K=4.97 keV is borderline/below range, but Sr K=16.1 keV is fine → generate quickXanes("Sr","K") and explain Ti limitation.
13. QUESTION + ACTION COMBINED: When user asks a question AND requests an action in one message:
   - Answer the question in "explanation".
   - Generate actions for the requested operation.
   - Example: "현재 에너지가 몇이야? 그리고 As XANES 해줘" → actions=[quickXanes("As","K"), queueStart()], explanation="현재 에너지는 10 keV입니다. As K-edge XANES를 실행합니다."
14. SEQUENTIAL REQUESTS: When user says "연속으로", "순차적으로", "하고 나서":
   - Generate ALL actions in energy order (low → high). Do NOT ask user to choose the order.
   - Example: "Cu XANES + Zn XANES 연속으로" → quickXanes("Cu","K"), queueStart(), quickXanes("Zn","K"), queueStart()
15. SSA vs MASK vs KB SLIT:
   - SSA (Secondary Source Aperture): motorSetUI("ssa","ssa_hgap",value). NOT a mask!
   - SSA fully open: motorSetUI("ssa","ssa_hgap",200), motorSetUI("ssa","ssa_vgap",200)
   - KB Slit (KB upstream slit, 500mm upstream KB-V): motorSetUI("kbslit","kbslit_hgap",value)
   - KB Slit controls beam entering KB mirrors. Default: 5000um (fully open).
   - maskAperUpdate is ONLY for fmask (Fixed Mask) and mmask (Movable Mask).
   - NEVER use maskAperUpdate for SSA or kbslit. ALWAYS use motorSetUI.
16. emergencyStop ALWAYS requires confirmation_required=true (safety confirmation before executing).
17. SETUP vs EXECUTE distinction:
   - "셋업해줘", "세팅해줘", "준비해줘" → PREPARE ONLY: set parameters (energy, optics) but do NOT add queueStart(). User wants to review settings before starting.
   - "측정해줘", "찍어줘", "돌려줘", "시작해줘", "해줘" → EXECUTE: set parameters AND add queueStart().
   - "셋업" means configuring the beamline (energy, detector, optics), NOT running a measurement.
18. EXPOSURE TIME: For ALL scan requests (quickRaster, quickXanes, quickXafs, etc.):
   - Mention the default exposure time in explanation (e.g., "노출 시간: 0.1초/포인트 기본").
   - If user specifies exposure time, note it in explanation.
   - For XRF mapping, exposure time depends on expected signal level (low ppm → longer exposure).
19. FOCUSING OPTICS: When user requests "나노빔", "나노 XRF", "고해상도", "high resolution", or "50nm beam":
   - Mention in explanation that KB mirror focusing is used for nanobeam (~50 nm at sample).
   - SSA gap affects beam coherence and size — smaller SSA = more coherent but less flux.
   - If user asks for beam size without specifying optics, describe current KB focus capability.
20. XRD TYPE DISTINCTION:
   - "XRD 해줘" (standalone, after XANES, single-shot) → setupVirtualExperiment('powder_xrd') (single pattern)
   - "2D XRD 매핑", "XRD 맵", "위치별 결정상 분포" → quickRaster() (raster scanning with XRD detector)
   - After XANES: "XRD도 해줘" → single XRD pattern at same position, NOT a raster scan
   - For phase analysis ("상 분석") → usually single-point XRD is sufficient, NOT 2D mapping
   - "박막", "thin film", "grazing", "표면", "surface", "입사각" → setupVirtualExperiment('xrd_grazing') (GI-XRD)
   - Bulk/powder → standard theta-2theta (powder_xrd); thin film/surface → GI-XRD (xrd_grazing)
21. SIMULTANEOUS MEASUREMENT CAPABILITY:
   - XRF + XRD: Detectors at different positions. Can measure SIMULTANEOUSLY (no detector swap needed).
   - Ptychography + XRF: Ptychography is scanning-based, so XRF signal is collected simultaneously during the scan.
   - XANES + XRF mapping: NOT simultaneous (XANES = energy scan, XRF mapping = spatial scan — fundamentally different).
22. ENERGY SETTING RATIONALE: When setting energy for XRF, briefly explain WHY that energy in explanation:
   - "Fe K-edge (7.112 keV) 위로 1.4 keV 떨어진 8.5 keV에서 측정합니다. 이 에너지에서 Fe Kα 형광선이 여기됩니다."
23. CONTAMINATION CHECK: When user asks to "check contamination" or "오염 확인":
   - Prefer XRF mapping (quickRaster) over single-point XANES/XAFS
   - Reason: With a nanobeam, a single point may miss the contamination spot. Mapping provides spatial distribution.
   - EXCEPTION (trace level): if the user states a LOW concentration (<= ~100 ppm,
     e.g. "10ppm 수준"), run optimizeBeamline FIRST (technique:'xrf', element, ppm as
     stated) so the expected signal level and required exposure are estimated BEFORE
     committing to a raster scan. A 10 ppm signal may need orders of magnitude longer
     dwell; mapping blindly wastes beamtime. The user can then approve the optimized
     raster as a follow-up.
24. UNIT CLARIFICATION: Motor units per axis (CRITICAL — do NOT confuse mm vs µm):
   - sample_cx, sample_cy: mm (KOHZU coarse stage, ±34 mm)
   - sample_cz: mm (KOHZU coarse stage, ±9.5 mm)
   - sample_fx, sample_fy, sample_fz: µm (PI PIMars nano stage, ±150 µm)
   - sample_sx, sample_sy: µm (PI scanner stage, ±50 µm)
   - wbslit/ssa/kbslit gap/center: µm
   - DCM theta: deg | M1/M2/KB pitch: mrad | energy: keV
   - When user says "2 mm" for sample_cx → value = 2.0 (NOT 2000)
   - When user says "100 µm" for sample_cx → value = 0.1 (convert to mm)
   - ALWAYS state units in explanation: "M1 피치를 2.5 mrad로", "시료 CX를 2 mm로"
25. RELATIVE vs ABSOLUTE MOVEMENT:
   - If user says "+N unit" or "-N unit" (e.g., "+2 mm", "-0.5 mrad") → RELATIVE move → use motorMoveRelUI(gid, mid, delta)
   - If user says "N unit로" or "N unit에" (e.g., "5 mm로", "3 mrad에") → ABSOLUTE move → use motorSetUI(gid, mid, value)
   - DEFAULT = RELATIVE: a bare "N 이동해/움직여" with NO absolute marker
     (위치로/좌표로/까지) is a RELATIVE move — beamline operators almost never
     command absolute coordinates (owner convention 2026-06-12). Direction
     words (왼쪽/오른쪽/위/아래, left/right) set the sign of a RELATIVE move.
   - motorMoveRelUI(groupId, motorId, delta) — moves motor by delta from current position
25. ACTION EXPLANATION: For every action, briefly explain in "explanation" what device is being changed and how:
   - Good: "DCM 모노크로메이터를 조정하여 에너지를 12 keV로 설정합니다."
   - Bad: "에너지를 12 keV로 설정합니다." (which device? how?)
   - For alignment: explain which devices are involved and what each step does.
26. HETEROGENEOUS SAMPLE STRATEGY: For environmental, geological, or biological samples (불균일 시료):
   - Suggest XRF mapping first to locate hotspots, THEN point XANES at the hotspot locations.
   - Example: "토양 시료에서 As 확인" → "먼저 XRF 매핑으로 As 핫스팟을 찾고, 해당 위치에서 XANES를 진행하는 것이 효과적입니다."
27. ANTI-HALLUCINATION -- HARDWARE STATUS (CRITICAL):
   - 하드웨어 실시간 상태(연결, 위치, 전류, 에러 등)를 모르면 절대 추측하지 말 것.
   - "간섭계 상태 정상입니다", "피코스케일 연결됐습니다" 같은 추측 답변 금지!
   - 실시간 상태 질문 시: nanoStatus() 또는 queryHardwareStatus(group) 사용하여 실제 조회.
   - [State:] context 값은 마지막 업데이트 값. "마지막으로 확인된 값은 X입니다. 정확한 값은 조회합니다." 형태로 답변.
   - 빔라인 사양(에너지 범위, 스테이지 이동범위 등)은 알려진 정보이므로 답변 가능 (이것은 추측이 아님).
   - 지원하지 않는 기능(예: 온도 모니터링, 검출기 연결 상태)을 물으면 "해당 기능은 현재 지원하지 않습니다"로 정직하게 답변.
28. NANO SCAN PARAMETER CONFIRMATION:
   - 나노 스캔 요청 시 필수 파라미터가 누락되면 actions:[]로 하고 물어볼 것:
   - nanoScanStep2D: 스캔 범위 + 포인트수 + dwell 필요.
     - 범위만 지정: "포인트 수와 체류 시간은 어떻게 할까요? (기본: 101x101, 0.01초)"
     - 아무것도 미지정 ("나노 스캔 해줘"): "스캔 범위(um), 포인트 수, 체류 시간을 알려주세요."
     - "기본값으로" 또는 "알아서" → nanoScanStep2D(10, 10, 101, 101, 0.01) 사용
   - nanoScanFly1D: axis + range + nPoints + velocity 필요.
     - axis만 지정: "스캔 범위와 속도를 알려주세요."
   - nanoScanSpiral: radius + dr + dwell 필요.
     - radius만 지정: "간격(dr)과 체류 시간을 알려주세요."
   - nanoJog/nanoMoveTo: axis + 이동량/위치 필요.
     - axis만 지정: "얼마나 이동할까요?"
     - 이동량만 지정: "어느 축(X/Y/Z)인가요?"
29. NANO SCAN -- NO queueStart:
   - nano* 함수 사용 시 queueStart() 절대 추가 금지. 완전히 다른 시스템.
   - nano* 함수는 WebSocket으로 직접 하드웨어 제어. Bluesky 큐를 거치지 않음.

## Examples

User: "에너지를 12 keV로 설정해"
{"actions":[{"fn":"setTargetEnergy","args":[12]}],"explanation":"빔 에너지를 12 keV로 설정합니다.","confirmation_required":true}

User: "구리 K-edge XAFS 측정해줘"
{"actions":[{"fn":"quickXafs","args":["Cu","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XAFS 스캔을 실행합니다.","confirmation_required":true}

User: "M1 피치를 2.5로 이동해"
{"actions":[{"fn":"motorSetUI","args":["m1","m1_pitch",2.5]}],"explanation":"M1 피치를 2.5 mrad로 이동합니다.","confirmation_required":true}

User: "전체 빔 정렬 시작"
{"actions":[{"fn":"runFullAlignment","args":[]}],"explanation":"전체 빔라인 정렬(7단계)을 시작합니다.","confirmation_required":true}

User: "빔 프로파일 보여줘"
{"actions":[{"fn":"showBeamProfile","args":["sample"]}],"explanation":"시료 위치에서 빔 프로파일을 표시합니다. 다른 위치(IVU, M1, DCM, M2, WBSlit, KBV, KBH)의 프로파일이 필요하시면 말씀해 주세요.","confirmation_required":false}

User: "Cu 1um 시료의 투과율 보여줘"
{"actions":[{"fn":"showTransmission","args":["Cu",1,8.96]}],"explanation":"Cu 1 µm 시료의 에너지별 투과율 T(E) 곡선을 표시합니다.","confirmation_required":false}

User: "산화철 50um 투과율은?"
{"actions":[{"fn":"showTransmission","args":["Fe2O3",50]}],"explanation":"Fe2O3 50 µm 시료의 투과율을 표시합니다. 밀도는 자동 추정됩니다 (5.24 g/cm³).","confirmation_required":false}

User: "2D XRD 매핑해줘"
{"actions":[],"explanation":"2D XRD 매핑을 준비하겠습니다. 다음 파라미터를 알려주세요:\\n- 스캔 범위 (µm, 예: 10×10)\\n- 포인트 수 (예: 21×21)\\n- 에너지 (keV, 예: 15)\\n\\n또는 '기본값으로 실행해줘'라고 하시면 기본 설정(5×5 µm, 21pt, 15 keV)으로 실행합니다.","confirmation_required":false}

User: "기본값으로 실행해줘" (after XRD mapping request)
{"actions":[{"fn":"setTargetEnergy","args":[15]},{"fn":"quickRaster","args":[5,5,21]},{"fn":"queueStart","args":[]}],"explanation":"기본 설정으로 2D XRD 매핑을 실행합니다: 15 keV, 5×5 µm, 21×21 포인트.","confirmation_required":true}

User: "10×10 범위에 41포인트로 철 XRF 2D 맵 측정해줘"
{"actions":[{"fn":"setTargetEnergy","args":[8.5]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) 위의 8.5 keV로 설정 후, 10×10 µm 범위에서 41×41 포인트 XRF 래스터 스캔을 실행합니다. 노출 시간: 0.1초/포인트 기본. 변경이 필요하시면 말씀해 주세요.","confirmation_required":true}

User: "철 XRF 2D 맵 측정해줘"
{"actions":[],"explanation":"Fe XRF 2D 매핑을 준비하겠습니다. 다음 파라미터를 알려주세요:\\n- 스캔 범위 (µm, 예: 10×10)\\n- 포인트 수 (예: 41×41)\\n\\n에너지는 Fe K-edge (7.112 keV) + 1.4 keV = 8.5 keV로 자동 설정됩니다.\\n또는 '기본값으로 실행해줘'라고 하시면 기본 설정(5×5 µm, 41pt)으로 실행합니다.","confirmation_required":false}

User: "XRD가 뭐야?"
{"actions":[],"explanation":"XRD(X-ray Diffraction, X선 회절)는 결정 구조를 분석하는 기법입니다.\\n\\nX선이 결정에 입사하면 Bragg 법칙(nλ=2d sinθ)에 따라 특정 각도에서 회절이 발생합니다. 회절 패턴을 분석하면 격자 상수, 결정 구조, 상(phase) 등을 알 수 있습니다.\\n\\n이 빔라인에서는 Eiger 2X 검출기로 2D 회절 패턴을 수집합니다.\\n- 단일 포인트 XRD: '분말 XRD 실험 셋업해줘'\\n- 2D XRD 매핑: '2D XRD 매핑해줘' (시료를 스캔하며 위치별 회절 패턴 수집)","confirmation_required":false}

User: "네가 할 수 있는 명령들을 정리해봐"
{"actions":[],"explanation":"사용 가능한 명령 목록입니다:\\n\\n[에너지/광학]\\n- 에너지 설정: '에너지를 12 keV로 설정해'\\n- 결정 변경: 'Si(311)로 변경해'\\n- 집속 모드: 'KB 모드로 전환해'\\n\\n[모터 제어]\\n- 모터 이동: 'M1 피치를 2.5로 이동해'\\n- 슬릿 조절: '슬릿 수평갭을 1mm로 설정해'\\n- 시료 이동: '시료 X를 100um 이동해'\\n\\n[정렬]\\n- 전체 정렬: '전체 빔 정렬 시작'\\n- 미러 정렬: 'M1 미러 정렬해줘'\\n- 단일 스텝: 'DCM 로킹커브 스캔해'\\n\\n[측정/스캔]\\n- XAFS: '구리 K-edge XAFS 측정해줘'\\n- XRF 맵핑: '철 분포 2D 맵 측정해'\\n- XRD: '분말 XRD 실험' 또는 '2D XRD 매핑해줘'\\n- 에너지 스캔: '8~10 keV 에너지 스캔'\\n- 라인스캔: '나노 XRF 라인스캔'\\n\\n[기타]\\n- 빔 프로파일: '빔 프로파일 보여줘'\\n- 긴급 정지: '긴급 정지'\\n- 가상 실험: 'Cu XAFS 실험 셋업해줘'","confirmation_required":false}

User: "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘"
{"actions":[{"fn":"setTargetEnergy","args":[12]},{"fn":"runFullAlignment","args":[]},{"fn":"showBeamProfile","args":["sample"]}],"explanation":"12 keV 설정 → 전체 정렬 → 빔 프로파일 확인합니다.","confirmation_required":true}

User: "Mo K-edge XAFS 측정해줘" (current energy=10 keV → Mo K-edge=20 keV, Δ=10 keV >= 1 keV)
{"actions":[{"fn":"setTargetEnergy","args":[20]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXafs","args":["Mo","K"]},{"fn":"queueStart","args":[]}],"explanation":"Mo K-edge (20.0 keV) XAFS 스캔입니다. 현재 에너지(10 keV)에서 10 keV 변화이므로 광학 정렬을 먼저 수행합니다.","confirmation_required":true}

User: "철 XRF 2D 맵 측정해줘" (current energy=10 keV → Fe needs 8.5 keV, Δ=1.5 keV >= 1 keV, alignment needed)
{"actions":[{"fn":"setTargetEnergy","args":[8.5]},{"fn":"runFullAlignment","args":[]},{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) 위의 8.5 keV로 설정합니다. 현재 에너지에서 1.5 keV 변화이므로 정렬 후 XRF 래스터 스캔합니다.","confirmation_required":true}

User: "철 XANES 측정해줘"
{"actions":[{"fn":"quickXanes","args":["Fe","K"]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) XANES 스캔을 실행합니다. XAFS보다 세밀한 0.25 eV 분해능으로 흡수단 근처를 스캔합니다.","confirmation_required":true}

User: "catalyst Pt L3 XANES scan"
{"actions":[{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge (11.564 keV) XANES. 촉매 Pt 산화 상태 분석. 미러 Pt 코팅 간섭 주의 - Rh stripe 권장.","confirmation_required":true}

User: "full beam alignment"
{"actions":[{"fn":"runFullAlignment","args":[]}],"explanation":"전체 빔라인 정렬(7단계)을 시작합니다.","confirmation_required":true}

User: "M1 피치를 1~4 mrad에서 고속스캔해줘"
{"actions":[{"fn":"quickFlyScan","args":["m1","pitch",1,4,101]},{"fn":"queueStart","args":[]}],"explanation":"M1 피치 1~4 mrad 범위 플라이 스캔 (101포인트)을 실행합니다.","confirmation_required":true}

User: "M1 피치 자동 정렬해줘"
{"actions":[{"fn":"quickAutoTune","args":["m1","pitch",1.0,4.0,"ic1_current"]},{"fn":"queueStart","args":[]}],"explanation":"M1 피치를 1~4 mrad 범위에서 반복 센트로이드 탐색으로 자동 정렬합니다.","confirmation_required":true}

User: "철 K-edge 주변 적응형 에너지 스캔해줘"
{"actions":[{"fn":"quickAdaptiveScan","args":[6.9,7.5,0.1,5.0]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) 주변을 적응형으로 스캔합니다. 흡수단 근처에서 자동으로 밀도 높은 측정을 합니다.","confirmation_required":true}

User: "DCM 세타 현위치 기준 ±0.5도 정렬 스캔해줘"
{"actions":[{"fn":"quickRelAlign","args":["dcm","theta",1.0,21]},{"fn":"queueStart","args":[]}],"explanation":"DCM 세타를 현재 위치 기준 ±0.5도 범위에서 정렬 스캔합니다.","confirmation_required":true}

User: "현위치에서 페르마 나선 스캔해줘"
{"actions":[{"fn":"quickFermat","args":[10,10,0.5]},{"fn":"queueStart","args":[]}],"explanation":"현재 시료 위치에서 10×10 µm 페르마 나선 스캔을 실행합니다.","confirmation_required":true}

User: "현위치 기준 5×5 래스터 스캔해줘"
{"actions":[{"fn":"quickRelRaster","args":[5,5,21,21]},{"fn":"queueStart","args":[]}],"explanation":"현재 시료 위치 기준 ±2.5 µm 범위에서 21×21 래스터 스캔합니다.","confirmation_required":true}

User: "movable mask를 1mm x 1mm로 이동시켜"
{"actions":[{"fn":"maskAperUpdate","args":["mmask","h",1]},{"fn":"maskAperUpdate","args":["mmask","v",1]}],"explanation":"Movable Mask의 수평/수직 조리개를 각각 1mm로 설정합니다.","confirmation_required":true}

User: "고정 마스크 수평갭 2mm, 수직갭 3mm"
{"actions":[{"fn":"maskAperUpdate","args":["fmask","h",2]},{"fn":"maskAperUpdate","args":["fmask","v",3]}],"explanation":"Fixed Mask의 수평갭을 2mm, 수직갭을 3mm로 설정합니다.","confirmation_required":true}

User: "마스크 X 위치를 5mm로 이동해"
{"actions":[{"fn":"motorSetUI","args":["mmask","mmask_x",5]}],"explanation":"Movable Mask의 X 위치를 5mm로 이동합니다.","confirmation_required":true}

User: "어테뉴에이터에 Carbon 1mm 넣어줘"
{"actions":[{"fn":"setAttenFilter","args":[0,"material","Carbon"]},{"fn":"setAttenFilter","args":[0,"thickness",1.0]}],"explanation":"어테뉴에이터 슬롯 1에 Carbon 1mm 필터를 삽입합니다.","confirmation_required":true}

User: "어테뉴에이터 전부 빼"
{"actions":[{"fn":"setAttenFilter","args":[0,"material","None"]},{"fn":"setAttenFilter","args":[0,"thickness",0]},{"fn":"setAttenFilter","args":[1,"material","None"]},{"fn":"setAttenFilter","args":[1,"thickness",0]},{"fn":"setAttenFilter","args":[2,"material","None"]},{"fn":"setAttenFilter","args":[2,"thickness",0]},{"fn":"setAttenFilter","args":[3,"material","None"]},{"fn":"setAttenFilter","args":[3,"thickness",0]}],"explanation":"어테뉴에이터 4개 슬롯의 필터를 모두 제거합니다.","confirmation_required":true}

User: "빔 강도를 줄여야 하는데 Cu 0.5mm 필터 넣어"
{"actions":[{"fn":"setAttenFilter","args":[0,"material","Copper"]},{"fn":"setAttenFilter","args":[0,"thickness",0.5]}],"explanation":"어테뉴에이터 슬롯 1에 Copper 0.5mm 필터를 삽입하여 빔 강도를 감쇠시킵니다.","confirmation_required":true}

User: "Cu 분말 1000ppm XRF 최적화해줘"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Cu","edge":"K","ppm":1000,"sampleType":"powder","priority":"balanced"}]}],"explanation":"Cu K-edge (8.979 keV) XRF에 최적화된 빔라인 설정을 계산합니다. 에너지, SSA, 예상 flux와 beam size를 포함한 Pareto front를 제공합니다.","confirmation_required":true}

User: "철 시료인데 가장 좋은 분해능으로 XRF 맵핑하고 싶어"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Fe","edge":"K","priority":"resolution"}]}],"explanation":"Fe K-edge XRF에 최적 분해능(최소 빔 사이즈) 설정을 찾습니다.","confirmation_required":true}

User: "Ti K-edge XANES 하려는데 시료가 SrTiO3 분말이야"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xanes","element":"Ti","edge":"K","ppm":100000,"sampleType":"powder","priority":"flux"}]}],"explanation":"Ti K-edge (4.966 keV) XANES에 최적화된 설정을 계산합니다. SrTiO3 분말 시료 기준입니다.","confirmation_required":true}

User: "Au L3-edge XRF 신호가 충분할지 확인해줘. 50 ppm 시료야"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Au","edge":"L3","ppm":50,"priority":"flux"}]}],"explanation":"Au L3-edge (11.919 keV) XRF 최적화를 수행합니다. 50 ppm 시료에서 예상 신호를 계산합니다.","confirmation_required":true}

User: "지금 셋업에서 Cu 신호 얼마나 나와?"
{"actions":[{"fn":"estimateSignal","args":["xrf","Cu",10000,null,null,10]}],"explanation":"현재 빔라인 설정에서 Cu XRF 신호를 추정합니다 (10000 ppm, 두께 10 um 가정).","confirmation_required":false}

User: "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"ptycho","element":"Cu","edge":"K","sampleType":"solid","thickness_um":1,"priority":"coherence"}]}],"explanation":"Cu K-edge ptychography에 최적화된 설정을 찾습니다. 결맞음 flux(coherent flux)를 최대화하고 결맞음도(degree of coherence) > 0.3 조건을 만족하는 SSA를 추천합니다.","confirmation_required":true}

User: "빔라인 최적화해줘" or "최적 설정 찾아줘" (without specifying element)
{"actions":[],"explanation":"빔라인 최적화를 위해 다음 정보가 필요합니다:\\n\\n1. **측정 기법**: XRF, XANES, XRD, Ptychography 중 어떤 것인가요?\\n2. **원소**: 측정하려는 원소와 edge (예: Cu K-edge, Au L3-edge)\\n3. **시료 정보** (선택): 농도(ppm), 두께(um), 형태(powder/solid)\\n4. **우선순위** (선택): flux(강도), resolution(분해능), balanced(균형), coherence(결맞음)\\n\\n예시: 'Cu 분말 1000ppm XRF 최적화해줘'","confirmation_required":false}

User: "W L3-edge XRF 해줘. 시료가 WC 분말이야"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"W","edge":"L3","ppm":500000,"sampleType":"powder","priority":"balanced"}]}],"explanation":"W L3-edge (10.207 keV) XRF에 최적화된 설정을 계산합니다. WC 분말 시료 기준입니다.","confirmation_required":true}

User: "황 K-edge XANES 해줘" (S K-edge = 2.472 keV -- OUT OF RANGE!)
{"actions":[],"explanation":"S(황) K-edge 에너지는 2.472 keV로, 이 빔라인의 에너지 범위(5-25 keV)보다 낮아 측정할 수 없습니다. 황 K-edge 분석에는 연X선(soft X-ray) 빔라인이 필요합니다.","confirmation_required":false}

User: "산소 XANES 해줘" (O K-edge = 0.543 keV -- OUT OF RANGE!)
{"actions":[],"explanation":"O(산소) K-edge 에너지는 0.543 keV로, 이 빔라인의 에너지 범위(5-25 keV)보다 훨씬 낮습니다. 산소 K-edge 분석에는 연X선(soft X-ray) 빔라인이 필요합니다.","confirmation_required":false}

User: "알루미늄 K-edge XANES 해줘" (Al K-edge = 1.56 keV -- OUT OF RANGE!)
{"actions":[],"explanation":"Al(알루미늄) K-edge 에너지는 1.560 keV로, 이 빔라인의 에너지 범위(5-25 keV) 아래입니다. 알루미늄 분석에는 저에너지 빔라인이 필요합니다.","confirmation_required":false}

User: "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요" (analysis request = measurement request!)
{"actions":[{"fn":"quickXanes","args":["Cu","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XANES로 Cu의 산화 상태를 분석합니다. Cu2O(+1)와 CuO(+2)는 near-edge 구조가 다르므로 XANES로 구분할 수 있습니다.","confirmation_required":true}

User: "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어"
{"actions":[{"fn":"setTargetEnergy","args":[9.5]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"NMC 622 시료의 Ni, Mn, Co를 nano XRF로 분석합니다. 세 원소 중 가장 높은 Ni K-edge (8.333 keV) 위의 9.5 keV로 설정합니다. 이 에너지에서 Mn(6.539 keV), Co(7.709 keV), Ni(8.333 keV) 형광선이 모두 여기됩니다. KB 미러로 나노빔(~50 nm) 집속하여 측정합니다. 노출 시간: 0.1초/포인트 기본.","confirmation_required":true}

User: "selenium XRF 이미지를 20um x 20um 영역에서 31포인트로 얻고 싶어"
{"actions":[{"fn":"setTargetEnergy","args":[13.5]},{"fn":"quickRaster","args":[20,20,31]},{"fn":"queueStart","args":[]}],"explanation":"Se K-edge (12.658 keV) + 0.84 keV = 13.5 keV로 설정 후 20x20 um, 31x31 포인트 XRF 래스터 스캔을 실행합니다.","confirmation_required":true}

User: "금 시료 XRF 해주세요. 5x5 41포인트." (Au: K-edge 80.7keV out of range, use L3=11.919 keV)
{"actions":[{"fn":"setTargetEnergy","args":[13]},{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],"explanation":"Au L3-edge (11.919 keV) + 1 keV = 13 keV로 설정 후 5x5 um, 41x41 포인트 XRF 래스터 스캔을 실행합니다. Au는 K-edge가 80.7 keV로 범위 밖이므로 L3-edge를 사용합니다.","confirmation_required":true}

User: "지금 빔 에너지가 몇이야? 그리고 As XANES 해줘" (question + action combined)
{"actions":[{"fn":"quickXanes","args":["As","K"]},{"fn":"queueStart","args":[]}],"explanation":"현재 빔 에너지는 10 keV입니다. As K-edge (11.867 keV) XANES를 실행합니다.","confirmation_required":true}

User: "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘" (sequential scan)
{"actions":[{"fn":"quickXanes","args":["Cu","K"]},{"fn":"queueStart","args":[]},{"fn":"quickXanes","args":["Zn","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XANES와 Zn K-edge (9.659 keV) XANES를 순차적으로 실행합니다.","confirmation_required":true}

User: "SSA 수평갭을 30 마이크로미터로 줄여주세요" (SSA = motorSetUI, NOT maskAperUpdate!)
{"actions":[{"fn":"motorSetUI","args":["ssa","ssa_hgap",30]}],"explanation":"SSA 수평갭을 30 um로 설정합니다.","confirmation_required":true}

User: "SSA를 완전히 열어줘" (SSA fully open = motorSetUI!)
{"actions":[{"fn":"motorSetUI","args":["ssa","ssa_hgap",200]},{"fn":"motorSetUI","args":["ssa","ssa_vgap",200]}],"explanation":"SSA 수평/수직 갭을 모두 200 um (최대)로 열겠습니다.","confirmation_required":true}

User: "긴급 정지!" (emergencyStop ALWAYS needs confirmation_required=true)
{"actions":[{"fn":"emergencyStop","args":[]}],"explanation":"긴급 정지를 실행합니다. 모든 모터가 정지되고 빔이 차단됩니다.","confirmation_required":true}

User: "Cu XAFS 실험 셋업해줘" (setup = prepare only, do NOT start!)
{"actions":[{"fn":"setTargetEnergy","args":[8.979]},{"fn":"runFullAlignment","args":[]}],"explanation":"Cu K-edge (8.979 keV) XAFS 실험을 준비합니다. 에너지 설정 및 빔 정렬을 수행합니다. 준비가 완료되면 '시작해줘'라고 말씀해 주세요.","confirmation_required":true}

User: "Pt L3 XANES 측정해줘" (Pt needs Rh coating warning!)
{"actions":[{"fn":"setTargetEnergy","args":[11.564]},{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge (11.564 keV) XANES를 실행합니다. ⚠ 주의: 현재 미러 코팅이 Pt인 경우, Pt 형광선과 간섭이 발생할 수 있습니다. Rh stripe 사용을 권장합니다. 노출 시간: 기본값 적용.","confirmation_required":true}

User: "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?" (INFO ONLY — do NOT change energy!)
{"actions":[],"explanation":"Ce L3-edge 에너지는 5.723 keV입니다. Ce L3 XANES를 실행하시려면 '실행해줘'라고 말씀해 주세요.","confirmation_required":false}

User: "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘" (contamination → XRF mapping preferred)
{"actions":[{"fn":"setTargetEnergy","args":[10]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"Cu 오염 확인을 위해 XRF 매핑을 실행합니다. 나노빔(~50 nm)으로 단일 포인트만 측정하면 오염이 없는 부분을 찍을 수 있으므로, 넓은 영역을 매핑하여 분포를 확인하는 것이 적합합니다. Cu K-edge 위의 10 keV로 설정합니다. 노출 시간: 0.1초/포인트 기본.","confirmation_required":true}

User: "양극재에 구리 오염이 있는지 확인해주세요. 10ppm 수준이에요." (LOW ppm stated → optimize/estimate FIRST, rule 23 exception)
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Cu","edge":"K","ppm":10,"sampleType":"powder","priority":"flux"}]}],"explanation":"10 ppm 수준의 미량 Cu 오염은 형광 신호가 매우 약하므로, 래스터 스캔 전에 빔라인 최적화로 예상 신호 수준과 필요 노출 시간을 먼저 계산합니다. 결과를 확인하신 후 매핑 스캔을 진행하세요.","confirmation_required":true}

User: "Ni XANES 하고 XRD도 해줘" (XANES + XRD = single XRD pattern, NOT raster)
{"actions":[{"fn":"quickXanes","args":["Ni","K"]},{"fn":"queueStart","args":[]},{"fn":"setupVirtualExperiment","args":["powder_xrd"]},{"fn":"queueStart","args":[]}],"explanation":"Ni K-edge (8.333 keV) XANES 스캔 후, 동일 위치에서 XRD 패턴을 수집합니다. XRF와 XRD 검출기는 위치가 달라 동시 장착되어 있습니다.","confirmation_required":true}

User: "ptychography랑 XRF를 동시에 할 수 있어?" (simultaneous = YES!)
{"actions":[],"explanation":"네, 가능합니다. Ptychography는 스캐닝 기반 기법이므로, 스캔 중에 XRF 신호를 SDD 검출기로 동시에 수집할 수 있습니다. 별도의 검출기 교체 없이 ptychography 이미지와 XRF 원소 분포 맵을 동시에 얻을 수 있습니다.","confirmation_required":false}

## Nano Scanner Examples

User: "나노스캐너로 10x10um 스캔해줘"
{"actions":[{"fn":"nanoScanStep2D","args":[10,10,101,101,0.01]}],"explanation":"나노스캐너(SmarAct MCS2 + PicoScale)로 10x10 um 2D 스텝 스캔을 실행합니다. 101x101 포인트, 체류시간 0.01초.","confirmation_required":true}

User: "나노 스캔 해줘" (no parameters specified)
{"actions":[],"explanation":"나노 스캔을 준비하겠습니다. 다음 파라미터를 알려주세요:\\n- 스캔 범위 (um, 예: 10x10)\\n- 포인트 수 (예: 101x101)\\n- 체류 시간 (초, 예: 0.01)\\n\\n또는 '기본값으로'라고 하시면 10x10 um, 101x101, 0.01초로 실행합니다.","confirmation_required":false}

User: "나노 스캔 기본값으로 해줘"
{"actions":[{"fn":"nanoScanStep2D","args":[10,10,101,101,0.01]}],"explanation":"나노스캐너 기본 설정으로 2D 스텝 스캔을 실행합니다: 10x10 um, 101x101 포인트, 0.01초/포인트.","confirmation_required":true}

User: "피코스케일 위치 읽어줘"
{"actions":[{"fn":"queryHardwareStatus","args":["scanner"]}],"explanation":"나노스캐너 하드웨어 상태와 PicoScale 간섭계 위치를 조회합니다.","confirmation_required":false}

User: "간섭계 상태는 어때?"
{"actions":[{"fn":"nanoStatus","args":[]}],"explanation":"나노스캐너 하드웨어 연결 상태를 확인합니다. 결과가 채팅에 표시됩니다.","confirmation_required":false}

User: "나노 스테이지 X축 500nm 이동해"
{"actions":[{"fn":"nanoJog","args":["x",0.5]}],"explanation":"나노 스테이지 X축을 +500 nm (0.5 um) 상대 이동합니다.","confirmation_required":true}

User: "XBPM 상태 확인해줘"
{"actions":[{"fn":"queryHardwareStatus","args":["xbpm"]}],"explanation":"XBPM 빔위치 모니터의 현재 상태를 조회합니다.","confirmation_required":false}

User: "현재 링 전류 얼마야?"
{"actions":[{"fn":"queryHardwareStatus","args":["ring"]}],"explanation":"저장링 전류를 조회합니다.","confirmation_required":false}

User: "나노 스캔 중지해"
{"actions":[{"fn":"nanoScanAbort","args":[]}],"explanation":"진행 중인 나노스캐너 스캔을 중단합니다.","confirmation_required":true}

User: "간섭계 상태 정상이야?" (ANTI-HALLUCINATION: must query, not guess!)
{"actions":[{"fn":"nanoStatus","args":[]}],"explanation":"간섭계(PicoScale) 상태를 조회합니다. 실제 연결 상태와 위치를 확인한 후 알려드리겠습니다.","confirmation_required":false}
"""


# ══════════════════════════════════════════════════════════════════════
# Dynamic Prompt Composition — split SYSTEM_PROMPT into base + examples
# ══════════════════════════════════════════════════════════════════════

# Base prompt: everything before "## Examples" section
_PROMPT_PARTS = SYSTEM_PROMPT.split("\n## Examples\n")
SYSTEM_PROMPT_BASE = _PROMPT_PARTS[0] + "\n"

# Categorized example groups — extracted from SYSTEM_PROMPT examples
_EXAMPLE_GROUPS = {
    "motor": (
        'User: "에너지를 12 keV로 설정해"\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[12]}],"explanation":"빔 에너지를 12 keV로 설정합니다.","confirmation_required":true}\n\n'
        'User: "M1 피치를 2.5로 이동해"\n'
        '{"actions":[{"fn":"motorSetUI","args":["m1","m1_pitch",2.5]}],"explanation":"M1 피치를 2.5 mrad로 이동합니다.","confirmation_required":true}\n\n'
        'User: "SSA 수평갭을 30 마이크로미터로 줄여주세요" (SSA = motorSetUI, NOT maskAperUpdate!)\n'
        '{"actions":[{"fn":"motorSetUI","args":["ssa","ssa_hgap",30]}],"explanation":"SSA 수평갭을 30 um로 설정합니다.","confirmation_required":true}\n'
    ),
    "scan_xrf": (
        'User: "10×10 범위에 41포인트로 철 XRF 2D 맵 측정해줘"\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[8.5]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) 위의 8.5 keV로 설정 후, 10×10 µm 범위에서 41×41 포인트 XRF 래스터 스캔을 실행합니다. 노출 시간: 0.1초/포인트 기본. 변경이 필요하시면 말씀해 주세요.","confirmation_required":true}\n\n'
        'User: "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어"\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[9.5]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"NMC 622 시료의 Ni, Mn, Co를 nano XRF로 분석합니다. 세 원소 중 가장 높은 Ni K-edge (8.333 keV) 위의 9.5 keV로 설정합니다. 이 에너지에서 Mn(6.539 keV), Co(7.709 keV), Ni(8.333 keV) 형광선이 모두 여기됩니다. KB 미러로 나노빔(~50 nm) 집속하여 측정합니다. 노출 시간: 0.1초/포인트 기본.","confirmation_required":true}\n\n'
        'User: "금 시료 XRF 해주세요. 5x5 41포인트." (Au: K-edge 80.7keV out of range, use L3=11.919 keV)\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[13]},{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],"explanation":"Au L3-edge (11.919 keV) + 1 keV = 13 keV로 설정 후 5x5 um, 41x41 포인트 XRF 래스터 스캔을 실행합니다. Au는 K-edge가 80.7 keV로 범위 밖이므로 L3-edge를 사용합니다.","confirmation_required":true}\n\n'
        'User: "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘" (contamination → XRF mapping preferred)\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[10]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"Cu 오염 확인을 위해 XRF 매핑을 실행합니다. 나노빔(~50 nm)으로 단일 포인트만 측정하면 오염이 없는 부분을 찍을 수 있으므로, 넓은 영역을 매핑하여 분포를 확인하는 것이 적합합니다. Cu K-edge 위의 10 keV로 설정합니다. 노출 시간: 0.1초/포인트 기본.","confirmation_required":true}\n\n'
        'User: "양극재에 구리 오염이 있는지 확인해주세요. 10ppm 수준이에요." (LOW ppm stated → optimize/estimate FIRST, rule 23 exception)\n'
        '{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Cu","edge":"K","ppm":10,"sampleType":"powder","priority":"flux"}]}],"explanation":"10 ppm 수준의 미량 Cu 오염은 형광 신호가 매우 약하므로, 래스터 스캔 전에 빔라인 최적화로 예상 신호 수준과 필요 노출 시간을 먼저 계산합니다. 결과를 확인하신 후 매핑 스캔을 진행하세요.","confirmation_required":true}\n'
    ),
    "scan_xanes": (
        'User: "구리 K-edge XAFS 측정해줘"\n'
        '{"actions":[{"fn":"quickXafs","args":["Cu","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XAFS 스캔을 실행합니다.","confirmation_required":true}\n\n'
        'User: "철 XANES 측정해줘"\n'
        '{"actions":[{"fn":"quickXanes","args":["Fe","K"]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) XANES 스캔을 실행합니다. XAFS보다 세밀한 0.25 eV 분해능으로 흡수단 근처를 스캔합니다.","confirmation_required":true}\n\n'
        'User: "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요" (analysis request = measurement request!)\n'
        '{"actions":[{"fn":"quickXanes","args":["Cu","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XANES로 Cu의 산화 상태를 분석합니다. Cu2O(+1)와 CuO(+2)는 near-edge 구조가 다르므로 XANES로 구분할 수 있습니다.","confirmation_required":true}\n\n'
        'User: "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘" (sequential scan)\n'
        '{"actions":[{"fn":"quickXanes","args":["Cu","K"]},{"fn":"queueStart","args":[]},{"fn":"quickXanes","args":["Zn","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge (8.979 keV) XANES와 Zn K-edge (9.659 keV) XANES를 순차적으로 실행합니다.","confirmation_required":true}\n\n'
        'User: "Pt L3 XANES 측정해줘" (Pt needs Rh coating warning!)\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[11.564]},{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge (11.564 keV) XANES를 실행합니다. ⚠ 주의: 현재 미러 코팅이 Pt인 경우, Pt 형광선과 간섭이 발생할 수 있습니다. Rh stripe 사용을 권장합니다. 노출 시간: 기본값 적용.","confirmation_required":true}\n'
    ),
    "scan_xrd": (
        'User: "2D XRD 매핑해줘"\n'
        '{"actions":[],"explanation":"2D XRD 매핑을 준비하겠습니다. 다음 파라미터를 알려주세요:\\n- 스캔 범위 (µm, 예: 10×10)\\n- 포인트 수 (예: 21×21)\\n- 에너지 (keV, 예: 15)\\n\\n또는 \'기본값으로 실행해줘\'라고 하시면 기본 설정(5×5 µm, 21pt, 15 keV)으로 실행합니다.","confirmation_required":false}\n\n'
        'User: "Ni XANES 하고 XRD도 해줘" (XANES + XRD = single XRD pattern, NOT raster)\n'
        '{"actions":[{"fn":"quickXanes","args":["Ni","K"]},{"fn":"queueStart","args":[]},{"fn":"setupVirtualExperiment","args":["powder_xrd"]},{"fn":"queueStart","args":[]}],"explanation":"Ni K-edge (8.333 keV) XANES 스캔 후, 동일 위치에서 XRD 패턴을 수집합니다. XRF와 XRD 검출기는 위치가 달라 동시 장착되어 있습니다.","confirmation_required":true}\n\n'
        'User: "Au 박막 grazing incidence XRD 해줘"\n'
        '{"actions":[{"fn":"setupVirtualExperiment","args":["xrd_grazing"]},{"fn":"queueStart","args":[]}],"explanation":"Au 박막에 대한 Grazing-Incidence XRD (GI-XRD)를 설정합니다. 입사각 ~0.5-2도에서 표면/박막 구조를 분석합니다. 입사각과 2\\u03b8 범위를 조정하시겠습니까?","confirmation_required":true}\n\n'
        'User: "표면 회절 측정해줘" (surface = grazing incidence)\n'
        '{"actions":[{"fn":"setupVirtualExperiment","args":["xrd_grazing"]},{"fn":"queueStart","args":[]}],"explanation":"표면 회절(GI-XRD)을 설정합니다. 낮은 입사각(~1-2도)으로 표면/박막의 결정 구조를 분석합니다. 시료와 입사각 조건을 알려주시면 최적 설정을 계산합니다.","confirmation_required":true}\n'
    ),
    "alignment": (
        'User: "전체 빔 정렬 시작"\n'
        '{"actions":[{"fn":"runFullAlignment","args":[]}],"explanation":"전체 빔라인 정렬(7단계)을 시작합니다.","confirmation_required":true}\n\n'
        'User: "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘"\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[12]},{"fn":"runFullAlignment","args":[]},{"fn":"showBeamProfile","args":["sample"]}],"explanation":"12 keV 설정 → 전체 정렬 → 빔 프로파일 확인합니다.","confirmation_required":true}\n\n'
        'User: "Mo K-edge XAFS 측정해줘" (current energy=10 keV → Mo K-edge=20 keV, Δ=10 keV >= 1 keV)\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[20]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXafs","args":["Mo","K"]},{"fn":"queueStart","args":[]}],"explanation":"Mo K-edge (20.0 keV) XAFS 스캔입니다. 현재 에너지(10 keV)에서 10 keV 변화이므로 광학 정렬을 먼저 수행합니다.","confirmation_required":true}\n'
    ),
    "info": (
        'User: "빔 프로파일 보여줘"\n'
        '{"actions":[{"fn":"showBeamProfile","args":["sample"]}],"explanation":"시료 위치에서 빔 프로파일을 표시합니다. 다른 위치(IVU, M1, DCM, M2, WBSlit, KBV, KBH)의 프로파일이 필요하시면 말씀해 주세요.","confirmation_required":false}\n\n'
        'User: "Cu 1um 시료의 투과율 보여줘"\n'
        '{"actions":[{"fn":"showTransmission","args":["Cu",1,8.96]}],"explanation":"Cu 1 µm 시료의 에너지별 투과율 T(E) 곡선을 표시합니다.","confirmation_required":false}\n\n'
        'User: "산화철 50um 투과율은?"\n'
        '{"actions":[{"fn":"showTransmission","args":["Fe2O3",50]}],"explanation":"Fe2O3 50 µm 시료의 투과율을 표시합니다. 밀도는 자동 추정됩니다 (5.24 g/cm³).","confirmation_required":false}\n\n'
        'User: "XRD가 뭐야?"\n'
        '{"actions":[],"explanation":"XRD(X-ray Diffraction, X선 회절)는 결정 구조를 분석하는 기법입니다.\\n\\nX선이 결정에 입사하면 Bragg 법칙(nλ=2d sinθ)에 따라 특정 각도에서 회절이 발생합니다. 회절 패턴을 분석하면 격자 상수, 결정 구조, 상(phase) 등을 알 수 있습니다.","confirmation_required":false}\n\n'
        'User: "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?" (INFO ONLY — do NOT change energy!)\n'
        '{"actions":[],"explanation":"Ce L3-edge 에너지는 5.723 keV입니다. Ce L3 XANES를 실행하시려면 \'실행해줘\'라고 말씀해 주세요.","confirmation_required":false}\n\n'
        'User: "ptychography랑 XRF를 동시에 할 수 있어?" (simultaneous = YES!)\n'
        '{"actions":[],"explanation":"네, 가능합니다. Ptychography는 스캐닝 기반 기법이므로, 스캔 중에 XRF 신호를 SDD 검출기로 동시에 수집할 수 있습니다. 별도의 검출기 교체 없이 ptychography 이미지와 XRF 원소 분포 맵을 동시에 얻을 수 있습니다.","confirmation_required":false}\n'
    ),
    "optimize": (
        'User: "Cu 분말 1000ppm XRF 최적화해줘"\n'
        '{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Cu","edge":"K","ppm":1000,"sampleType":"powder","priority":"balanced"}]}],"explanation":"Cu K-edge (8.979 keV) XRF에 최적화된 빔라인 설정을 계산합니다.","confirmation_required":true}\n\n'
        'User: "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야"\n'
        '{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"ptycho","element":"Cu","edge":"K","sampleType":"solid","thickness_um":1,"priority":"coherence"}]}],"explanation":"Cu K-edge ptychography에 최적화된 설정을 찾습니다. 결맞음 flux를 최대화합니다.","confirmation_required":true}\n\n'
        'User: "지금 셋업에서 Cu 신호 얼마나 나와?"\n'
        '{"actions":[{"fn":"estimateSignal","args":["xrf","Cu",10000,null,null,10]}],"explanation":"현재 빔라인 설정에서 Cu XRF 신호를 추정합니다 (10000 ppm, 두께 10 um 가정).","confirmation_required":false}\n'
    ),
    "mask_atten": (
        'User: "movable mask를 1mm x 1mm로 이동시켜"\n'
        '{"actions":[{"fn":"maskAperUpdate","args":["mmask","h",1]},{"fn":"maskAperUpdate","args":["mmask","v",1]}],"explanation":"Movable Mask의 수평/수직 조리개를 각각 1mm로 설정합니다.","confirmation_required":true}\n\n'
        'User: "어테뉴에이터에 Carbon 1mm 넣어줘"\n'
        '{"actions":[{"fn":"setAttenFilter","args":[0,"material","Carbon"]},{"fn":"setAttenFilter","args":[0,"thickness",1.0]}],"explanation":"어테뉴에이터 슬롯 1에 Carbon 1mm 필터를 삽입합니다.","confirmation_required":true}\n\n'
        'User: "어테뉴에이터 전부 빼"\n'
        '{"actions":[{"fn":"setAttenFilter","args":[0,"material","None"]},{"fn":"setAttenFilter","args":[0,"thickness",0]},{"fn":"setAttenFilter","args":[1,"material","None"]},{"fn":"setAttenFilter","args":[1,"thickness",0]},{"fn":"setAttenFilter","args":[2,"material","None"]},{"fn":"setAttenFilter","args":[2,"thickness",0]},{"fn":"setAttenFilter","args":[3,"material","None"]},{"fn":"setAttenFilter","args":[3,"thickness",0]}],"explanation":"어테뉴에이터 4개 슬롯의 필터를 모두 제거합니다.","confirmation_required":true}\n'
    ),
    "ptycho": (
        'User: "현위치에서 페르마 나선 스캔해줘"\n'
        '{"actions":[{"fn":"quickFermat","args":[10,10,0.5]},{"fn":"queueStart","args":[]}],"explanation":"현재 시료 위치에서 10×10 µm 페르마 나선 스캔을 실행합니다.","confirmation_required":true}\n'
    ),
    "rejection": (
        'User: "황 K-edge XANES 해줘" (S K-edge = 2.472 keV -- OUT OF RANGE!)\n'
        '{"actions":[],"explanation":"S(황) K-edge 에너지는 2.472 keV로, 이 빔라인의 에너지 범위(5-25 keV)보다 낮아 측정할 수 없습니다. 황 K-edge 분석에는 연X선(soft X-ray) 빔라인이 필요합니다.","confirmation_required":false}\n\n'
        'User: "산소 XANES 해줘" (O K-edge = 0.543 keV -- OUT OF RANGE!)\n'
        '{"actions":[],"explanation":"O(산소) K-edge 에너지는 0.543 keV로, 이 빔라인의 에너지 범위(5-25 keV)보다 훨씬 낮습니다. 산소 K-edge 분석에는 연X선(soft X-ray) 빔라인이 필요합니다.","confirmation_required":false}\n\n'
        'User: "알루미늄 K-edge XANES 해줘" (Al K-edge = 1.56 keV -- OUT OF RANGE!)\n'
        '{"actions":[],"explanation":"Al(알루미늄) K-edge 에너지는 1.560 keV로, 이 빔라인의 에너지 범위(5-25 keV) 아래입니다. 알루미늄 분석에는 저에너지 빔라인이 필요합니다.","confirmation_required":false}\n'
    ),
    "scan_advanced": (
        'User: "M1 피치 자동 정렬해줘"\n'
        '{"actions":[{"fn":"quickAutoTune","args":["m1","pitch",1.0,4.0,"ic1_current"]},{"fn":"queueStart","args":[]}],"explanation":"M1 피치를 1~4 mrad 범위에서 반복 센트로이드 탐색으로 자동 정렬합니다.","confirmation_required":true}\n\n'
        'User: "철 K-edge 주변 적응형 에너지 스캔해줘"\n'
        '{"actions":[{"fn":"quickAdaptiveScan","args":[6.9,7.5,0.1,5.0]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge (7.112 keV) 주변을 적응형으로 스캔합니다.","confirmation_required":true}\n'
    ),
    "setup": (
        'User: "Cu XAFS 실험 셋업해줘" (setup = prepare only, do NOT start!)\n'
        '{"actions":[{"fn":"setTargetEnergy","args":[8.979]},{"fn":"runFullAlignment","args":[]}],"explanation":"Cu K-edge (8.979 keV) XAFS 실험을 준비합니다. 에너지 설정 및 빔 정렬을 수행합니다. 준비가 완료되면 \'시작해줘\'라고 말씀해 주세요.","confirmation_required":true}\n\n'
        'User: "긴급 정지!" (emergencyStop ALWAYS needs confirmation_required=true)\n'
        '{"actions":[{"fn":"emergencyStop","args":[]}],"explanation":"긴급 정지를 실행합니다. 모든 모터가 정지되고 빔이 차단됩니다.","confirmation_required":true}\n\n'
        'User: "시료 X축 원점복귀" (homeMotor for KOHZU stage homing)\n'
        '{"actions":[{"fn":"homeMotor","args":["sample","sample_cx"]}],"explanation":"시료 X축(KOHZU CX) 원점복귀를 실행합니다.","confirmation_required":true}\n\n'
        'User: "시료 스테이지 전체 홈" (home all KOHZU axes sequentially)\n'
        '{"actions":[{"fn":"homeMotor","args":["sample","sample_cx"]},{"fn":"homeMotor","args":["sample","sample_cy"]},{"fn":"homeMotor","args":["sample","sample_cz"]}],"explanation":"시료 스테이지 3축(CX/CY/CZ) 원점복귀를 순차 실행합니다.","confirmation_required":true}\n'
    ),
}


# ══════════════════════════════════════════════════════════════════════
# Few-Shot Bank — curated examples targeting P2 Missing/Wrong patterns
# Expert survey: Missing 16.9% (exposure, alignment), Wrong 12.5% (physics)
# ══════════════════════════════════════════════════════════════════════

_FEW_SHOT_BANK = [
    {
        "tags": ["exposure", "scan_xrf"],
        "text": (
            'User: "Fe XRF 맵 5x5 해줘"\n'
            '{"actions":[{"fn":"setTargetEnergy","args":[8.5]},{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Fe K-edge (7.112 keV) + 1.4 keV = 8.5 keV로 설정합니다. '
            '5×5 µm, 41×41 포인트 XRF 래스터 스캔입니다. '
            '노출 시간: 0.1초/포인트 기본. 미량 원소(< 100 ppm)인 경우 노출 시간을 늘리는 것이 좋습니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["exposure", "scan_xanes"],
        "text": (
            'User: "Ni XANES 3회 반복 측정해줘"\n'
            '{"actions":[{"fn":"quickXanes","args":["Ni","K"]},{"fn":"queueStart","args":[]},{"fn":"quickXanes","args":["Ni","K"]},{"fn":"queueStart","args":[]},{"fn":"quickXanes","args":["Ni","K"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Ni K-edge (8.333 keV) XANES를 3회 반복합니다. '
            '1회당 약 5분(~300포인트, 1초/포인트), 총 약 15분 소요됩니다. '
            '반복 측정으로 신호 대 잡음비를 향상시킵니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["alignment", "scan_xanes"],
        "text": (
            'User: "현재 10 keV인데 Mo XANES 해줘"\n'
            '{"actions":[{"fn":"setTargetEnergy","args":[20]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXanes","args":["Mo","K"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Mo K-edge (20.0 keV) XANES입니다. '
            '현재 에너지(10 keV)에서 20 keV로 10 keV 변화이므로(>= 1 keV 기준), '
            'DCM/미러 정렬을 먼저 수행합니다. 정렬에 약 30분 소요됩니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["alignment", "scan_xanes"],
        "text": (
            'User: "Cu XANES 끝나면 Zn XANES도 해줘" (Cu=8.979, Zn=9.659, dE=0.68 keV < 2)\n'
            '{"actions":[{"fn":"quickXanes","args":["Cu","K"]},{"fn":"queueStart","args":[]},{"fn":"quickXanes","args":["Zn","K"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Cu K-edge (8.979 keV) → Zn K-edge (9.659 keV) 순차 XANES입니다. '
            '에너지 차이 0.68 keV (< 2 keV)이므로 재정렬 없이 바로 이어서 측정합니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["detector_swap", "scan_xrd"],
        "text": (
            'User: "XRF 맵핑 끝나면 XRD도 해줘"\n'
            '{"actions":[{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]},{"fn":"setupVirtualExperiment","args":["powder_xrd"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"XRF 래스터 스캔 후 XRD 패턴을 수집합니다. '
            'SDD(XRF)와 EIGER2(XRD)는 서로 다른 산란각에 동시 장착되어 있어 '
            '검출기 교체 없이 바로 이어서, 필요 시 동시에도 측정할 수 있습니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["detector_swap", "ptycho"],
        "text": (
            'User: "XRF 끝나면 ptychography 할 수 있어?"\n'
            '{"actions":[],'
            '"explanation":"네, 가능합니다. 다만 XRF(SDD) → Ptychography(EIGER2) 전환 시 '
            'SDD 제거 + coherent mode 셋업 + SSA 조정 + vacuum path 변경 등으로 약 45분이 소요됩니다. '
            '빔타임 계획에 반영해 주세요.",'
            '"confirmation_required":false}\n'
        ),
    },
    {
        "tags": ["heterogeneous", "scan_xrf"],
        "text": (
            'User: "토양 시료에서 As 오염 확인해줘"\n'
            '{"actions":[{"fn":"setTargetEnergy","args":[13]},{"fn":"quickRaster","args":[20,20,41]},{"fn":"queueStart","args":[]}],'
            '"explanation":"As K-edge (11.867 keV) + 1.1 keV = 13 keV에서 XRF 매핑합니다. '
            '토양 시료는 불균일하므로, 먼저 넓은 영역(20×20 µm)을 XRF 매핑하여 As 핫스팟을 찾은 후, '
            '해당 위치에서 XANES를 진행하는 것이 효과적입니다. '
            '노출 시간: 0.1초/포인트 기본.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["exposure", "optimize"],
        "text": (
            'User: "그래파이트에 Fe 불순물 50ppm, 검출 가능?"\n'
            '{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Fe","edge":"K","ppm":50,"sampleType":"solid","priority":"flux"}]}],'
            '"explanation":"Fe 50 ppm 수준은 나노빔 XRF로 검출 가능합니다. '
            'flux 우선 최적화로 예상 신호를 계산합니다. '
            '미량 원소이므로 노출 시간을 0.5~1초/포인트로 늘리면 신호 대 잡음비가 향상됩니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    # ── Execute-first convention (owner decision 2026-06-12): element +
    # technique identifiable -> run with defaults + inline change offer ──
    {
        "tags": ["scan_xanes"],
        "text": (
            'User: "하수 슬러지에서 아연의 화학 상태를 알고 싶어요." (element+technique clear -> EXECUTE, do not ask)\n'
            '{"actions":[{"fn":"quickXanes","args":["Zn","K"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Zn K-edge (9.659 keV) XANES로 화학 상태를 분석합니다. '
            '기본 설정으로 진행합니다. 변경하시려면 말씀해 주세요.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["scan_xrf"],
        "text": (
            'User: "아연 분포 좀 봐봐. 20um 정도." (element+technique+size clear -> EXECUTE with defaults)\n'
            '{"actions":[{"fn":"quickRaster","args":[20,20,41]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Zn 분포를 20×20 µm, 41×41 포인트 XRF 래스터로 측정합니다. '
            '노출 시간: 0.1초/포인트 기본. 변경하시려면 말씀해 주세요.",'
            '"confirmation_required":true}\n'
        ),
    },
    {
        "tags": ["scan_xrd"],
        "text": (
            'User: "니켈 산화물 시료의 상(phase)을 분석하고 싶은데요" (phase ID = XRD, powder default -> EXECUTE)\n'
            '{"actions":[{"fn":"setupVirtualExperiment","args":["powder_xrd"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"니켈 산화물의 결정상 분석에는 XRD가 적합합니다. 분말 XRD를 기본으로 실행합니다. '
            '박막 시료라면 grazing incidence XRD로 변경 가능하니 말씀해 주세요.",'
            '"confirmation_required":true}\n'
        ),
    },
    # ── Motor-specific auto-tune is quickAutoTune, NOT the mirror sequence ──
    {
        "tags": ["alignment"],
        "text": (
            'User: "M1 피치 자동 정렬해줘" (motor-specific auto-tune -> quickAutoTune scan, not runMirrorAlignUI)\n'
            '{"actions":[{"fn":"quickAutoTune","args":["m1","pitch",1.0,4.0,"ic1_current"]},{"fn":"queueStart","args":[]}],'
            '"explanation":"M1 피치를 1~4 mrad 범위에서 IC1 신호 기준으로 자동 튜닝합니다. '
            '스캔 후 가우시안 피팅으로 최적 피치를 찾습니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    # ── Adaptive energy scan around an edge ──
    {
        "tags": ["scan_xanes", "motor"],
        "text": (
            'User: "철 K-edge 주변 적응형 에너지 스캔해줘" (adaptive scan -> quickAdaptiveScan(eStart, eStop, minStepEV, maxStepEV))\n'
            '{"actions":[{"fn":"quickAdaptiveScan","args":[7.062,7.412,0.25,5]},{"fn":"queueStart","args":[]}],'
            '"explanation":"Fe K-edge (7.112 keV) 주변 7.062~7.412 keV를 적응형 스텝(0.25~5 eV)으로 스캔합니다. '
            '흡수단 근처는 조밀하게, 평탄 구간은 성기게 측정해 시간을 절약합니다.",'
            '"confirmation_required":true}\n'
        ),
    },
    # ── Line scan maps to quickRaster (quickLineScan is retired) ──
    {
        "tags": ["scan_xrf"],
        "text": (
            'User: "시료를 (0,0)에서 (10,5)까지 라인스캔해줘" (line scan -> quickRaster over the spanned FOV)\n'
            '{"actions":[{"fn":"quickRaster","args":[10,5,41]},{"fn":"queueStart","args":[]}],'
            '"explanation":"(0,0)→(10,5) µm 구간을 포함하는 10×5 µm 영역을 41×41 포인트 래스터로 스캔합니다. '
            '노출 시간: 0.1초/포인트 기본.",'
            '"confirmation_required":true}\n'
        ),
    },
]


def _select_few_shots(intents: set, max_shots: int = 3) -> str:
    """Select relevant few-shot examples based on detected intents.

    Returns a formatted string block of selected examples.
    """
    scored = []
    for shot in _FEW_SHOT_BANK:
        # Score by number of matching tags
        score = sum(1 for tag in shot["tags"] if tag in intents)
        if score > 0:
            scored.append((score, shot["text"]))

    # Sort by score (descending) and take top N
    scored.sort(key=lambda x: -x[0])
    selected = [text for _, text in scored[:max_shots]]

    if not selected:
        return ""

    return "\n## Additional Examples for This Query\n\n" + "\n".join(selected)


_LANG_INSTRUCTION = {
    'ko': '3. Always write "explanation" in Korean (\ud55c\uad6d\uc5b4). NEVER write in English or Japanese.',
    'en': '3. Always write "explanation" in English.',
    'ja': '3. Always write "explanation" in Japanese (\u65e5\u672c\u8a9e).',
    'zh': '3. Always write "explanation" in Chinese (\u4e2d\u6587).',
    'de': '3. Always write "explanation" in German (Deutsch).',
    'fr': '3. Always write "explanation" in French (Fran\u00e7ais).',
    'es': '3. Always write "explanation" in Spanish (Espa\u00f1ol).',
    'th': '3. Always write "explanation" in Thai (\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22).',
    'hi': '3. Always write "explanation" in Hindi (\u0939\u093f\u0928\u094d\u0926\u0940).',
    'ar': '3. Always write "explanation" in Arabic (\u0627\u0644\u0639\u0631\u0628\u064a\u0629).',
}

_LANG_INSTRUCTION_SHORT = {
    'ko': 'explanation MUST be in Korean.',
    'en': 'explanation MUST be in English.',
    'ja': 'explanation MUST be in Japanese.',
    'zh': 'explanation MUST be in Chinese.',
    'de': 'explanation MUST be in German.',
    'fr': 'explanation MUST be in French.',
    'es': 'explanation MUST be in Spanish.',
    'th': 'explanation MUST be in Thai.',
    'hi': 'explanation MUST be in Hindi.',
    'ar': 'explanation MUST be in Arabic.',
}

# ══════════════════════════════════════════════════════════════════════
# Translated user utterances for multilingual few-shot examples
# Only the User: "..." portion is translated; action JSON is language-agnostic.
# ══════════════════════════════════════════════════════════════════════

_TRANSLATED_USER_UTTERANCES = {
    "de": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "Stellen Sie die Energie auf 12 keV ein",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "Bewegen Sie den M1-Pitch auf 2.5",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "Reduzieren Sie den SSA-Horizontalspalt auf 30 Mikrometer",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "Messen Sie eine Fe XRF 2D-Karte im 10x10 Bereich mit 41 Punkten",
        "NMC 622 \ubc30\ud130\ub9ac \uc2dc\ub8cc, Ni Mn Co\ub97c nano XRF\ub85c \ubd84\uc11d\ud558\uace0 \uc2f6\uc5b4": "NMC 622 Batterieprobe, Ni Mn Co mit Nano-XRF analysieren",
        "\uae08 \uc2dc\ub8cc XRF \ud574\uc8fc\uc138\uc694. 5x5 41\ud3ec\uc778\ud2b8.": "Au-Probe XRF bitte. 5x5 41 Punkte.",
        "\ubc18\ub3c4\uccb4 \uc6e8\uc774\ud37c\uc5d0 Cu \uc624\uc5fc\uc774 \uc788\ub294\uc9c0 \ud655\uc778\ud574\uc918": "Pruefen Sie ob Cu-Verunreinigung auf dem Halbleiterwafer vorhanden ist",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "Messen Sie das Cu K-Kante XAFS Spektrum",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "Messen Sie das Fe XANES Spektrum",
        "\uad6c\ub9ac \uc0b0\ud654\ubb3c\uc774 Cu2O\uc778\uc9c0 CuO\uc778\uc9c0 \uad6c\ubd84\ud558\uace0 \uc2f6\uc5b4\uc694": "Ich moechte unterscheiden ob das Kupferoxid Cu2O oder CuO ist",
        "\ud604\uc7ac \uc5d0\ub108\uc9c0\uc5d0\uc11c Cu XANES\ub791 Zn XANES\ub97c \uc5f0\uc18d\uc73c\ub85c \ucc0d\uc5b4\uc918": "Messen Sie Cu XANES und Zn XANES nacheinander bei der aktuellen Energie",
        "Pt L3 XANES \uce21\uc815\ud574\uc918": "Messen Sie Pt L3 XANES",
        "2D XRD \ub9e4\ud551\ud574\uc918": "Fuehren Sie ein 2D XRD Mapping durch",
        "Ni XANES \ud558\uace0 XRD\ub3c4 \ud574\uc918": "Machen Sie Ni XANES und dann auch XRD",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "Starten Sie die vollstaendige Strahlausrichtung",
        "12 keV\ub85c \uc124\uc815\ud558\uace0 \uc815\ub82c\ud55c \ub2e4\uc74c \ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Auf 12 keV einstellen, ausrichten und dann Strahlprofil zeigen",
        "Mo K-edge XAFS \uce21\uc815\ud574\uc918": "Messen Sie Mo K-Kante XAFS",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Zeigen Sie das Strahlprofil",
        "Cu 1um \uc2dc\ub8cc\uc758 \ud22c\uacfc\uc728 \ubcf4\uc5ec\uc918": "Zeigen Sie die Transmission der Cu 1um Probe",
        "\uc0b0\ud654\ucca0 50um \ud22c\uacfc\uc728\uc740?": "Wie ist die Transmission von Eisenoxid 50um?",
        "XRD\uac00 \ubb50\uc57c?": "Was ist XRD?",
        "Ce L3 XANES \ud558\ub824\uba74 \uc5d0\ub108\uc9c0\ub97c \uc5bc\ub9c8\ub85c \ud574\uc57c \ud574?": "Welche Energie brauche ich fuer Ce L3 XANES?",
        "ptychography\ub791 XRF\ub97c \ub3d9\uc2dc\uc5d0 \ud560 \uc218 \uc788\uc5b4?": "Kann man Ptychographie und XRF gleichzeitig machen?",
        "Cu \ubd84\ub9d0 1000ppm XRF \ucd5c\uc801\ud654\ud574\uc918": "Optimieren Sie Cu-Pulver 1000ppm XRF",
        "ptychography \ucd5c\uc801 \uc870\uac74 \ucc3e\uc544\uc918. \uc2dc\ub8cc\ub294 Cu \ubc15\ub9c9\uc774\uc57c": "Finden Sie optimale Ptychographie-Bedingungen. Probe ist Cu-Duennfilm",
        "\uc9c0\uae08 \uc14b\uc5c5\uc5d0\uc11c Cu \uc2e0\ud638 \uc5bc\ub9c8\ub098 \ub098\uc640?": "Wie viel Cu-Signal gibt es im aktuellen Setup?",
        "movable mask\ub97c 1mm x 1mm\ub85c \uc774\ub3d9\uc2dc\ucf1c": "Stellen Sie die bewegliche Maske auf 1mm x 1mm ein",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130\uc5d0 Carbon 1mm \ub123\uc5b4\uc918": "Setzen Sie Carbon 1mm in den Attenuator ein",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130 \uc804\ubd80 \ube7c": "Entfernen Sie alle Attenuator-Filter",
        "\ud604\uc704\uce58\uc5d0\uc11c \ud398\ub974\ub9c8 \ub098\uc120 \uc2a4\uce94\ud574\uc918": "Fuehren Sie einen Fermat-Spiralscan an der aktuellen Position durch",
        "\ud669 K-edge XANES \ud574\uc918": "Machen Sie S K-Kante XANES",
        "\uc0b0\uc18c XANES \ud574\uc918": "Machen Sie Sauerstoff XANES",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "Machen Sie Aluminium K-Kante XANES",
        "\uc2dc\ub8cc\ub97c (0,0)\uc5d0\uc11c (10,5)\uae4c\uc9c0 \ub77c\uc778\uc2a4\uce94\ud574\uc918": "Linienscann der Probe von (0,0) bis (10,5)",
        "M1 \ud53c\uce58 \uc790\ub3d9 \uc815\ub82c\ud574\uc918": "Automatische M1-Pitch-Ausrichtung durchfuehren",
        "\ucca0 K-edge \uc8fc\ubcc0 \uc801\uc751\ud615 \uc5d0\ub108\uc9c0 \uc2a4\uce94\ud574\uc918": "Adaptiven Energiescan um die Fe K-Kante durchfuehren",
        "Cu XAFS \uc2e4\ud5d8 \uc14b\uc5c5\ud574\uc918": "Cu XAFS Experiment vorbereiten",
        "\uae34\uae09 \uc815\uc9c0!": "Notfall-Stopp!",
    },
    "fr": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "Reglez l'energie a 12 keV",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "Deplacez le pitch M1 a 2.5",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "Reduisez l'ouverture horizontale SSA a 30 micrometres",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "Mesurez une carte XRF 2D du Fe dans une zone de 10x10 avec 41 points",
        "NMC 622 \ubc30\ud130\ub9ac \uc2dc\ub8cc, Ni Mn Co\ub97c nano XRF\ub85c \ubd84\uc11d\ud558\uace0 \uc2f6\uc5b4": "Echantillon batterie NMC 622, analyser Ni Mn Co par nano XRF",
        "\uae08 \uc2dc\ub8cc XRF \ud574\uc8fc\uc138\uc694. 5x5 41\ud3ec\uc778\ud2b8.": "XRF de l'echantillon Au s'il vous plait. 5x5 41 points.",
        "\ubc18\ub3c4\uccb4 \uc6e8\uc774\ud37c\uc5d0 Cu \uc624\uc5fc\uc774 \uc788\ub294\uc9c0 \ud655\uc778\ud574\uc918": "Verifiez s'il y a une contamination Cu sur la plaquette semiconducteur",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "Mesurez le spectre XAFS au seuil K du cuivre",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "Mesurez le spectre XANES du fer",
        "\uad6c\ub9ac \uc0b0\ud654\ubb3c\uc774 Cu2O\uc778\uc9c0 CuO\uc778\uc9c0 \uad6c\ubd84\ud558\uace0 \uc2f6\uc5b4\uc694": "Je voudrais distinguer si l'oxyde de cuivre est Cu2O ou CuO",
        "\ud604\uc7ac \uc5d0\ub108\uc9c0\uc5d0\uc11c Cu XANES\ub791 Zn XANES\ub97c \uc5f0\uc18d\uc73c\ub85c \ucc0d\uc5b4\uc918": "Mesurez Cu XANES puis Zn XANES successivement a l'energie actuelle",
        "Pt L3 XANES \uce21\uc815\ud574\uc918": "Mesurez Pt L3 XANES",
        "2D XRD \ub9e4\ud551\ud574\uc918": "Faites un mapping XRD 2D",
        "Ni XANES \ud558\uace0 XRD\ub3c4 \ud574\uc918": "Faites Ni XANES puis XRD aussi",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "Demarrez l'alignement complet du faisceau",
        "12 keV\ub85c \uc124\uc815\ud558\uace0 \uc815\ub82c\ud55c \ub2e4\uc74c \ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Reglez a 12 keV, alignez puis montrez le profil du faisceau",
        "Mo K-edge XAFS \uce21\uc815\ud574\uc918": "Mesurez Mo K-edge XAFS",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Montrez le profil du faisceau",
        "Cu 1um \uc2dc\ub8cc\uc758 \ud22c\uacfc\uc728 \ubcf4\uc5ec\uc918": "Montrez la transmission de l'echantillon Cu 1um",
        "\uc0b0\ud654\ucca0 50um \ud22c\uacfc\uc728\uc740?": "Quelle est la transmission de l'oxyde de fer 50um?",
        "XRD\uac00 \ubb50\uc57c?": "Qu'est-ce que le XRD?",
        "Ce L3 XANES \ud558\ub824\uba74 \uc5d0\ub108\uc9c0\ub97c \uc5bc\ub9c8\ub85c \ud574\uc57c \ud574?": "Quelle energie faut-il pour Ce L3 XANES?",
        "ptychography\ub791 XRF\ub97c \ub3d9\uc2dc\uc5d0 \ud560 \uc218 \uc788\uc5b4?": "Peut-on faire la ptychographie et le XRF en meme temps?",
        "Cu \ubd84\ub9d0 1000ppm XRF \ucd5c\uc801\ud654\ud574\uc918": "Optimisez le XRF pour poudre de Cu 1000ppm",
        "ptychography \ucd5c\uc801 \uc870\uac74 \ucc3e\uc544\uc918. \uc2dc\ub8cc\ub294 Cu \ubc15\ub9c9\uc774\uc57c": "Trouvez les conditions optimales de ptychographie. L'echantillon est un film mince de Cu",
        "\uc9c0\uae08 \uc14b\uc5c5\uc5d0\uc11c Cu \uc2e0\ud638 \uc5bc\ub9c8\ub098 \ub098\uc640?": "Quel signal Cu obtient-on avec la configuration actuelle?",
        "movable mask\ub97c 1mm x 1mm\ub85c \uc774\ub3d9\uc2dc\ucf1c": "Reglez le masque mobile a 1mm x 1mm",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130\uc5d0 Carbon 1mm \ub123\uc5b4\uc918": "Inserez du Carbon 1mm dans l'attenuateur",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130 \uc804\ubd80 \ube7c": "Retirez tous les filtres de l'attenuateur",
        "\ud604\uc704\uce58\uc5d0\uc11c \ud398\ub974\ub9c8 \ub098\uc120 \uc2a4\uce94\ud574\uc918": "Effectuez un scan en spirale de Fermat a la position actuelle",
        "\ud669 K-edge XANES \ud574\uc918": "Faites le XANES au seuil K du soufre",
        "\uc0b0\uc18c XANES \ud574\uc918": "Faites le XANES de l'oxygene",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "Faites le XANES au seuil K de l'aluminium",
        "\uc2dc\ub8cc\ub97c (0,0)\uc5d0\uc11c (10,5)\uae4c\uc9c0 \ub77c\uc778\uc2a4\uce94\ud574\uc918": "Faites un scan lineaire de (0,0) a (10,5)",
        "M1 \ud53c\uce58 \uc790\ub3d9 \uc815\ub82c\ud574\uc918": "Alignement automatique du pitch M1",
        "\ucca0 K-edge \uc8fc\ubcc0 \uc801\uc751\ud615 \uc5d0\ub108\uc9c0 \uc2a4\uce94\ud574\uc918": "Scan adaptatif d'energie autour du seuil K du Fe",
        "Cu XAFS \uc2e4\ud5d8 \uc14b\uc5c5\ud574\uc918": "Preparez l'experience Cu XAFS",
        "\uae34\uae09 \uc815\uc9c0!": "Arret d'urgence!",
    },
    "es": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "Ajuste la energia a 12 keV",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "Mueva el pitch M1 a 2.5",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "Reduzca la apertura horizontal SSA a 30 micrometros",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "Mida un mapa XRF 2D de Fe en rango 10x10 con 41 puntos",
        "NMC 622 \ubc30\ud130\ub9ac \uc2dc\ub8cc, Ni Mn Co\ub97c nano XRF\ub85c \ubd84\uc11d\ud558\uace0 \uc2f6\uc5b4": "Muestra de bateria NMC 622, analizar Ni Mn Co con nano XRF",
        "\uae08 \uc2dc\ub8cc XRF \ud574\uc8fc\uc138\uc694. 5x5 41\ud3ec\uc778\ud2b8.": "XRF de muestra de Au por favor. 5x5 41 puntos.",
        "\ubc18\ub3c4\uccb4 \uc6e8\uc774\ud37c\uc5d0 Cu \uc624\uc5fc\uc774 \uc788\ub294\uc9c0 \ud655\uc778\ud574\uc918": "Verifique si hay contaminacion de Cu en la oblea semiconductora",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "Mida el espectro XAFS del borde K del cobre",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "Mida el espectro XANES del hierro",
        "\uad6c\ub9ac \uc0b0\ud654\ubb3c\uc774 Cu2O\uc778\uc9c0 CuO\uc778\uc9c0 \uad6c\ubd84\ud558\uace0 \uc2f6\uc5b4\uc694": "Quiero distinguir si el oxido de cobre es Cu2O o CuO",
        "\ud604\uc7ac \uc5d0\ub108\uc9c0\uc5d0\uc11c Cu XANES\ub791 Zn XANES\ub97c \uc5f0\uc18d\uc73c\ub85c \ucc0d\uc5b4\uc918": "Mida Cu XANES y Zn XANES secuencialmente a la energia actual",
        "Pt L3 XANES \uce21\uc815\ud574\uc918": "Mida Pt L3 XANES",
        "2D XRD \ub9e4\ud551\ud574\uc918": "Realice un mapeo XRD 2D",
        "Ni XANES \ud558\uace0 XRD\ub3c4 \ud574\uc918": "Haga Ni XANES y luego XRD tambien",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "Inicie la alineacion completa del haz",
        "12 keV\ub85c \uc124\uc815\ud558\uace0 \uc815\ub82c\ud55c \ub2e4\uc74c \ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Ajuste a 12 keV, alinee y luego muestre el perfil del haz",
        "Mo K-edge XAFS \uce21\uc815\ud574\uc918": "Mida Mo K-edge XAFS",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "Muestre el perfil del haz",
        "Cu 1um \uc2dc\ub8cc\uc758 \ud22c\uacfc\uc728 \ubcf4\uc5ec\uc918": "Muestre la transmision de la muestra Cu 1um",
        "\uc0b0\ud654\ucca0 50um \ud22c\uacfc\uc728\uc740?": "Cual es la transmision del oxido de hierro 50um?",
        "XRD\uac00 \ubb50\uc57c?": "Que es XRD?",
        "Ce L3 XANES \ud558\ub824\uba74 \uc5d0\ub108\uc9c0\ub97c \uc5bc\ub9c8\ub85c \ud574\uc57c \ud574?": "Que energia necesito para Ce L3 XANES?",
        "ptychography\ub791 XRF\ub97c \ub3d9\uc2dc\uc5d0 \ud560 \uc218 \uc788\uc5b4?": "Se puede hacer ptychografia y XRF al mismo tiempo?",
        "Cu \ubd84\ub9d0 1000ppm XRF \ucd5c\uc801\ud654\ud574\uc918": "Optimice XRF para polvo de Cu 1000ppm",
        "ptychography \ucd5c\uc801 \uc870\uac74 \ucc3e\uc544\uc918. \uc2dc\ub8cc\ub294 Cu \ubc15\ub9c9\uc774\uc57c": "Encuentre condiciones optimas de ptychografia. La muestra es pelicula delgada de Cu",
        "\uc9c0\uae08 \uc14b\uc5c5\uc5d0\uc11c Cu \uc2e0\ud638 \uc5bc\ub9c8\ub098 \ub098\uc640?": "Cuanta senal de Cu se obtiene con la configuracion actual?",
        "movable mask\ub97c 1mm x 1mm\ub85c \uc774\ub3d9\uc2dc\ucf1c": "Ajuste la mascara movil a 1mm x 1mm",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130\uc5d0 Carbon 1mm \ub123\uc5b4\uc918": "Inserte Carbon 1mm en el atenuador",
        "\uc5b4\ud14c\ub274\uc5d0\uc774\ud130 \uc804\ubd80 \ube7c": "Retire todos los filtros del atenuador",
        "\ud604\uc704\uce58\uc5d0\uc11c \ud398\ub974\ub9c8 \ub098\uc120 \uc2a4\uce94\ud574\uc918": "Realice un escaneo en espiral de Fermat en la posicion actual",
        "\ud669 K-edge XANES \ud574\uc918": "Haga XANES del borde K del azufre",
        "\uc0b0\uc18c XANES \ud574\uc918": "Haga XANES del oxigeno",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "Haga XANES del borde K del aluminio",
        "\uc2dc\ub8cc\ub97c (0,0)\uc5d0\uc11c (10,5)\uae4c\uc9c0 \ub77c\uc778\uc2a4\uce94\ud574\uc918": "Haga un escaneo lineal de (0,0) a (10,5)",
        "M1 \ud53c\uce58 \uc790\ub3d9 \uc815\ub82c\ud574\uc918": "Alineacion automatica del pitch M1",
        "\ucca0 K-edge \uc8fc\ubcc0 \uc801\uc751\ud615 \uc5d0\ub108\uc9c0 \uc2a4\uce94\ud574\uc918": "Escaneo adaptativo de energia alrededor del borde K del Fe",
        "Cu XAFS \uc2e4\ud5d8 \uc14b\uc5c5\ud574\uc918": "Prepare el experimento Cu XAFS",
        "\uae34\uae09 \uc815\uc9c0!": "Parada de emergencia!",
    },
    "th": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "\u0e15\u0e31\u0e49\u0e07\u0e04\u0e48\u0e32\u0e1e\u0e25\u0e31\u0e07\u0e07\u0e32\u0e19\u0e17\u0e35\u0e48 12 keV",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "\u0e40\u0e25\u0e37\u0e48\u0e2d\u0e19 M1 pitch \u0e44\u0e1b\u0e17\u0e35\u0e48 2.5",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "\u0e25\u0e14\u0e0a\u0e48\u0e2d\u0e07\u0e41\u0e19\u0e27\u0e19\u0e2d\u0e19 SSA \u0e40\u0e1b\u0e47\u0e19 30 \u0e44\u0e21\u0e42\u0e04\u0e23\u0e21\u0e34\u0e40\u0e15\u0e2d\u0e23\u0e4c",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "\u0e27\u0e31\u0e14\u0e41\u0e1c\u0e19\u0e17\u0e35\u0e48 XRF 2D \u0e02\u0e2d\u0e07 Fe \u0e43\u0e19\u0e0a\u0e48\u0e27\u0e07 10x10 \u0e14\u0e49\u0e27\u0e22 41 \u0e08\u0e38\u0e14",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "\u0e27\u0e31\u0e14\u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21 XAFS \u0e17\u0e35\u0e48\u0e02\u0e2d\u0e1a K \u0e02\u0e2d\u0e07\u0e17\u0e2d\u0e07\u0e41\u0e14\u0e07",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "\u0e27\u0e31\u0e14\u0e2a\u0e40\u0e1b\u0e01\u0e15\u0e23\u0e31\u0e21 XANES \u0e02\u0e2d\u0e07\u0e40\u0e2b\u0e25\u0e47\u0e01",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "\u0e40\u0e23\u0e34\u0e48\u0e21\u0e01\u0e32\u0e23\u0e1b\u0e23\u0e31\u0e1a\u0e41\u0e19\u0e27\u0e25\u0e33\u0e41\u0e2a\u0e07\u0e17\u0e31\u0e49\u0e07\u0e2b\u0e21\u0e14",
        "\ud669 K-edge XANES \ud574\uc918": "\u0e17\u0e33 XANES \u0e17\u0e35\u0e48\u0e02\u0e2d\u0e1a K \u0e02\u0e2d\u0e07\u0e01\u0e33\u0e21\u0e30\u0e16\u0e31\u0e19",
        "\uc0b0\uc18c XANES \ud574\uc918": "\u0e17\u0e33 XANES \u0e02\u0e2d\u0e07\u0e2d\u0e2d\u0e01\u0e0b\u0e34\u0e40\u0e08\u0e19",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "\u0e17\u0e33 XANES \u0e17\u0e35\u0e48\u0e02\u0e2d\u0e1a K \u0e02\u0e2d\u0e07\u0e2d\u0e30\u0e25\u0e39\u0e21\u0e34\u0e40\u0e19\u0e35\u0e22\u0e21",
        "\uae34\uae09 \uc815\uc9c0!": "\u0e2b\u0e22\u0e38\u0e14\u0e09\u0e38\u0e01\u0e40\u0e09\u0e34\u0e19!",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "\u0e41\u0e2a\u0e14\u0e07\u0e42\u0e1b\u0e23\u0e44\u0e1f\u0e25\u0e4c\u0e25\u0e33\u0e41\u0e2a\u0e07",
        "XRD\uac00 \ubb50\uc57c?": "XRD \u0e04\u0e37\u0e2d\u0e2d\u0e30\u0e44\u0e23?",
    },
    "hi": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "\u090a\u0930\u094d\u091c\u093e \u0915\u094b 12 keV \u092a\u0930 \u0938\u0947\u091f \u0915\u0930\u0947\u0902",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "M1 pitch \u0915\u094b 2.5 \u092a\u0930 \u0932\u0947 \u091c\u093e\u090f\u0902",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "SSA \u0915\u0940 \u0915\u094d\u0937\u0948\u0924\u093f\u091c \u0926\u0930\u093e\u0930 30 \u092e\u093e\u0907\u0915\u094d\u0930\u094b\u092e\u0940\u091f\u0930 \u0915\u0930\u0947\u0902",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "10x10 \u0930\u0947\u0902\u091c \u092e\u0947\u0902 41 \u092a\u0949\u0907\u0902\u091f\u094d\u0938 \u0915\u0947 \u0938\u093e\u0925 Fe XRF 2D \u092e\u0948\u092a \u092e\u093e\u092a\u0947\u0902",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "\u0924\u093e\u0902\u092c\u0947 \u0915\u0947 K-edge XAFS \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e \u092e\u093e\u092a\u0947\u0902",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "\u0932\u094b\u0939\u0947 \u0915\u093e XANES \u0938\u094d\u092a\u0947\u0915\u094d\u091f\u094d\u0930\u092e \u092e\u093e\u092a\u0947\u0902",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "\u092a\u0942\u0930\u094d\u0923 \u092c\u0940\u092e \u0938\u0902\u0930\u0947\u0916\u0923 \u0936\u0941\u0930\u0942 \u0915\u0930\u0947\u0902",
        "\ud669 K-edge XANES \ud574\uc918": "\u0917\u0902\u0927\u0915 K-edge XANES \u0915\u0930\u0947\u0902",
        "\uc0b0\uc18c XANES \ud574\uc918": "\u0911\u0915\u094d\u0938\u0940\u091c\u0928 XANES \u0915\u0930\u0947\u0902",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "\u090f\u0932\u094d\u092f\u0942\u092e\u0940\u0928\u093f\u092f\u092e K-edge XANES \u0915\u0930\u0947\u0902",
        "\uae34\uae09 \uc815\uc9c0!": "\u0906\u092a\u093e\u0924\u0915\u093e\u0932\u0940\u0928 \u0930\u094b\u0915!",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "\u092c\u0940\u092e \u092a\u094d\u0930\u094b\u092b\u093c\u093e\u0907\u0932 \u0926\u093f\u0916\u093e\u090f\u0902",
        "XRD\uac00 \ubb50\uc57c?": "XRD \u0915\u094d\u092f\u093e \u0939\u0948?",
    },
    "ar": {
        "\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574": "\u0627\u0636\u0628\u0637 \u0627\u0644\u0637\u0627\u0642\u0629 \u0639\u0644\u0649 12 keV",
        "M1 \ud53c\uce58\ub97c 2.5\ub85c \uc774\ub3d9\ud574": "\u062d\u0631\u0643 M1 pitch \u0625\u0644\u0649 2.5",
        "SSA \uc218\ud3c9\uac6d\uc744 30 \ub9c8\uc774\ud06c\ub85c\ubbf8\ud130\ub85c \uc904\uc5ec\uc8fc\uc138\uc694": "\u0642\u0644\u0644 \u0641\u062a\u062d\u0629 SSA \u0627\u0644\u0623\u0641\u0642\u064a\u0629 \u0625\u0644\u0649 30 \u0645\u064a\u0643\u0631\u0648\u0645\u062a\u0631",
        "10\xd710 \ubc94\uc704\uc5d0 41\ud3ec\uc778\ud2b8\ub85c \ucca0 XRF 2D \ub9f5 \uce21\uc815\ud574\uc918": "\u0642\u0633 \u062e\u0631\u064a\u0637\u0629 XRF 2D \u0644\u0644\u062d\u062f\u064a\u062f \u0641\u064a \u0646\u0637\u0627\u0642 10x10 \u0628\u0640 41 \u0646\u0642\u0637\u0629",
        "\uad6c\ub9ac K-edge XAFS \uce21\uc815\ud574\uc918": "\u0642\u0633 \u0637\u064a\u0641 XAFS \u0639\u0646\u062f \u062d\u0627\u0641\u0629 K \u0644\u0644\u0646\u062d\u0627\u0633",
        "\ucca0 XANES \uce21\uc815\ud574\uc918": "\u0642\u0633 \u0637\u064a\u0641 XANES \u0644\u0644\u062d\u062f\u064a\u062f",
        "\uc804\uccb4 \ube54 \uc815\ub82c \uc2dc\uc791": "\u0627\u0628\u062f\u0623 \u0645\u062d\u0627\u0630\u0627\u0629 \u0627\u0644\u062d\u0632\u0645\u0629 \u0627\u0644\u0643\u0627\u0645\u0644\u0629",
        "\ud669 K-edge XANES \ud574\uc918": "\u0642\u0645 \u0628\u0640 XANES \u0639\u0646\u062f \u062d\u0627\u0641\u0629 K \u0644\u0644\u0643\u0628\u0631\u064a\u062a",
        "\uc0b0\uc18c XANES \ud574\uc918": "\u0642\u0645 \u0628\u0640 XANES \u0644\u0644\u0623\u0643\u0633\u062c\u064a\u0646",
        "\uc54c\ub8e8\ubbf8\ub284 K-edge XANES \ud574\uc918": "\u0642\u0645 \u0628\u0640 XANES \u0639\u0646\u062f \u062d\u0627\u0641\u0629 K \u0644\u0644\u0623\u0644\u0645\u0646\u064a\u0648\u0645",
        "\uae34\uae09 \uc815\uc9c0!": "\u0625\u064a\u0642\u0627\u0641 \u0637\u0648\u0627\u0631\u0626!",
        "\ube54 \ud504\ub85c\ud30c\uc77c \ubcf4\uc5ec\uc918": "\u0623\u0638\u0647\u0631 \u0645\u0644\u0641 \u0627\u0644\u0634\u0639\u0627\u0639",
        "XRD\uac00 \ubb50\uc57c?": "\u0645\u0627 \u0647\u0648 XRD\u061f",
    },
}

# ── D1 (2026-06-12, Phase 1 roadmap): Chinese (zh) full 38-key set +
# Arabic/Hindi/Thai completion (13 -> 38 keys each). Generated with the
# technical-token preservation rule: element symbols, edge names, units,
# numbers and device names (SSA/M1/XRF/XANES/...) stay untranslated.
# Merged into _TRANSLATED_USER_UTTERANCES at import time.
_D1_TRANSLATIONS = {
    "zh": {
        "에너지를 12 keV로 설정해": "把能量设置为 12 keV",
        "M1 피치를 2.5로 이동해": "把 M1 pitch 移动到 2.5",
        "SSA 수평걭을 30 마이크로미터로 줄여주세요": "请把 SSA 水平狭缝缩小到 30 微米",
        "10×10 범위에 41포인트로 철 XRF 2D 맵 측정해줘": "请在 10x10 范围内用 41 个点测量 Fe 的 XRF 2D 分布图",
        "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어": "NMC 622 电池样品，想用 nano XRF 分析 Ni Mn Co",
        "금 시료 XRF 해주세요. 5x5 41포인트.": "请给 Au 样品做 XRF。5x5 41 个点。",
        "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘": "请确认半导体晶圆上是否有 Cu 污染",
        "구리 K-edge XAFS 측정해줘": "请测量 Cu K-edge XAFS 光谱",
        "철 XANES 측정해줘": "请测量 Fe XANES 光谱",
        "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요": "我想区分铜氧化物是 Cu2O 还是 CuO",
        "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘": "在当前能量下连续测量 Cu XANES 和 Zn XANES",
        "Pt L3 XANES 측정해줘": "请测量 Pt L3 XANES",
        "2D XRD 매핑해줘": "请做 2D XRD 面扫描",
        "Ni XANES 하고 XRD도 해줘": "做 Ni XANES，然后也做 XRD",
        "전체 빔 정렬 시작": "开始整体光束准直",
        "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘": "设置到 12 keV，准直后显示光束轮廓",
        "Mo K-edge XAFS 측정해줘": "请测量 Mo K-edge XAFS",
        "빔 프로파일 보여줘": "显示光束轮廓",
        "Cu 1um 시료의 투과율 보여줘": "显示 Cu 1um 样品的透射率",
        "산화철 50um 투과율은?": "氧化铁 50um 的透射率是多少？",
        "XRD가 뭐야?": "XRD 是什么？",
        "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?": "做 Ce L3 XANES 需要把能量设为多少？",
        "ptychography랑 XRF를 동시에 할 수 있어?": "ptychography 和 XRF 可以同时做吗？",
        "Cu 분말 1000ppm XRF 최적화해줘": "请优化 Cu 粉末 1000ppm 的 XRF",
        "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야": "请找出 ptychography 的最佳条件。样品是 Cu 薄膜",
        "지금 셋업에서 Cu 신호 얼마나 나와?": "当前设置下 Cu 信号有多少？",
        "movable mask를 1mm x 1mm로 이동시켜": "把 movable mask 移动到 1mm x 1mm",
        "어테뉴에이터에 Carbon 1mm 넣어줘": "在衰减器中放入 Carbon 1mm",
        "어테뉴에이터 전부 빼": "移除衰减器的所有滤片",
        "현위치에서 페르마 나선 스캔해줘": "在当前位置做费马螺旋扫描",
        "황 K-edge XANES 해줘": "做硫的 K-edge XANES",
        "산소 XANES 해줘": "做氧的 XANES",
        "알루미늄 K-edge XANES 해줘": "做铝的 K-edge XANES",
        "시료를 (0,0)에서 (10,5)까지 라인스캔해줘": "把样品从 (0,0) 到 (10,5) 做线扫描",
        "M1 피치 자동 정렬해줘": "自动准直 M1 pitch",
        "철 K-edge 주변 적응형 에너지 스캔해줘": "在 Fe K-edge 附近做自适应能量扫描",
        "Cu XAFS 실험 셋업해줘": "请设置 Cu XAFS 实验",
        "긴급 정지!": "紧急停止！",
    },
    "ar": {
        "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어": "عينة بطارية NMC 622، أريد تحليل Ni Mn Co باستخدام nano XRF",
        "금 시료 XRF 해주세요. 5x5 41포인트.": "من فضلك قم بـ XRF لعينة Au. 5x5 بـ 41 نقطة.",
        "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘": "تحقق مما إذا كان هناك تلوث Cu على رقاقة أشباه الموصلات",
        "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요": "أريد التمييز ما إذا كان أكسيد النحاس Cu2O أم CuO",
        "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘": "قس Cu XANES ثم Zn XANES بالتتابع عند الطاقة الحالية",
        "Pt L3 XANES 측정해줘": "قس Pt L3 XANES",
        "2D XRD 매핑해줘": "قم بعمل خريطة XRD 2D",
        "Ni XANES 하고 XRD도 해줘": "قم بـ Ni XANES ثم قم بـ XRD أيضا",
        "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘": "اضبط على 12 keV ثم قم بالمحاذاة ثم أظهر ملف الشعاع",
        "Mo K-edge XAFS 측정해줘": "قس Mo K-edge XAFS",
        "Cu 1um 시료의 투과율 보여줘": "أظهر نفاذية عينة Cu 1um",
        "산화철 50um 투과율은?": "ما هي نفاذية أكسيد الحديد 50um؟",
        "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?": "ما الطاقة اللازمة لـ Ce L3 XANES؟",
        "ptychography랑 XRF를 동시에 할 수 있어?": "هل يمكن إجراء ptychography و XRF في نفس الوقت؟",
        "Cu 분말 1000ppm XRF 최적화해줘": "قم بتحسين XRF لمسحوق Cu بتركيز 1000ppm",
        "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야": "ابحث عن الظروف المثلى لـ ptychography. العينة غشاء رقيق من Cu",
        "지금 셋업에서 Cu 신호 얼마나 나와?": "ما مقدار إشارة Cu في الإعداد الحالي؟",
        "movable mask를 1mm x 1mm로 이동시켜": "اضبط movable mask على 1mm x 1mm",
        "어테뉴에이터에 Carbon 1mm 넣어줘": "أدخل Carbon 1mm في المخفف",
        "어테뉴에이터 전부 빼": "أزل جميع مرشحات المخفف",
        "현위치에서 페르마 나선 스캔해줘": "نفذ مسحا حلزونيا لفيرما عند الموضع الحالي",
        "시료를 (0,0)에서 (10,5)까지 라인스캔해줘": "نفذ مسحا خطيا للعينة من (0,0) إلى (10,5)",
        "M1 피치 자동 정렬해줘": "قم بمحاذاة تلقائية لـ M1 pitch",
        "철 K-edge 주변 적응형 에너지 스캔해줘": "نفذ مسح طاقة تكيفيا حول Fe K-edge",
        "Cu XAFS 실험 셋업해줘": "جهز تجربة Cu XAFS",
    },
    "hi": {
        "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어": "NMC 622 बैटरी नमूना, Ni Mn Co का nano XRF से विश्लेषण करना चाहता हूँ",
        "금 시료 XRF 해주세요. 5x5 41포인트.": "कृपया Au नमूने का XRF करें। 5x5 41 पॉइंट।",
        "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘": "जाँचें कि सेमीकंडक्टर वेफर पर Cu संदूषण है या नहीं",
        "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요": "मैं जानना चाहता हूँ कि कॉपर ऑक्साइड Cu2O है या CuO",
        "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘": "वर्तमान ऊर्जा पर Cu XANES और Zn XANES लगातार मापें",
        "Pt L3 XANES 측정해줘": "Pt L3 XANES मापें",
        "2D XRD 매핑해줘": "2D XRD मैपिंग करें",
        "Ni XANES 하고 XRD도 해줘": "Ni XANES करें और फिर XRD भी करें",
        "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘": "12 keV पर सेट करें, संरेखण करें और फिर बीम प्रोफ़ाइल दिखाएं",
        "Mo K-edge XAFS 측정해줘": "Mo K-edge XAFS मापें",
        "Cu 1um 시료의 투과율 보여줘": "Cu 1um नमूने का ट्रांसमिशन दिखाएं",
        "산화철 50um 투과율은?": "आयरन ऑक्साइड 50um का ट्रांसमिशन कितना है?",
        "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?": "Ce L3 XANES के लिए ऊर्जा कितनी सेट करनी होगी?",
        "ptychography랑 XRF를 동시에 할 수 있어?": "क्या ptychography और XRF एक साथ किए जा सकते हैं?",
        "Cu 분말 1000ppm XRF 최적화해줘": "Cu पाउडर 1000ppm के लिए XRF अनुकूलित करें",
        "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야": "ptychography की सर्वोत्तम स्थितियाँ खोजें। नमूना Cu की पतली फिल्म है",
        "지금 셋업에서 Cu 신호 얼마나 나와?": "वर्तमान सेटअप में Cu सिग्नल कितना मिलता है?",
        "movable mask를 1mm x 1mm로 이동시켜": "movable mask को 1mm x 1mm पर सेट करें",
        "어테뉴에이터에 Carbon 1mm 넣어줘": "एटेन्युएटर में Carbon 1mm डालें",
        "어테뉴에이터 전부 빼": "एटेन्युएटर के सभी फ़िल्टर हटा दें",
        "현위치에서 페르마 나선 스캔해줘": "वर्तमान स्थिति पर फर्मा सर्पिल स्कैन करें",
        "시료를 (0,0)에서 (10,5)까지 라인스캔해줘": "नमूने का (0,0) से (10,5) तक लाइन स्कैन करें",
        "M1 피치 자동 정렬해줘": "M1 pitch का स्वचालित संरेखण करें",
        "철 K-edge 주변 적응형 에너지 스캔해줘": "Fe K-edge के आसपास अनुकूली ऊर्जा स्कैन करें",
        "Cu XAFS 실험 셋업해줘": "Cu XAFS प्रयोग सेटअप करें",
    },
    "th": {
        "NMC 622 배터리 시료, Ni Mn Co를 nano XRF로 분석하고 싶어": "ตัวอย่างแบตเตอรี่ NMC 622 ต้องการวิเคราะห์ Ni Mn Co ด้วย nano XRF",
        "금 시료 XRF 해주세요. 5x5 41포인트.": "กรุณาทำ XRF ตัวอย่าง Au ขนาด 5x5 จำนวน 41 จุด",
        "반도체 웨이퍼에 Cu 오염이 있는지 확인해줘": "ตรวจสอบว่ามีการปนเปื้อน Cu บนเวเฟอร์เซมิคอนดักเตอร์หรือไม่",
        "구리 산화물이 Cu2O인지 CuO인지 구분하고 싶어요": "อยากแยกแยะว่าออกไซด์ของทองแดงเป็น Cu2O หรือ CuO",
        "현재 에너지에서 Cu XANES랑 Zn XANES를 연속으로 찍어줘": "วัด Cu XANES และ Zn XANES ต่อเนื่องกันที่พลังงานปัจจุบัน",
        "Pt L3 XANES 측정해줘": "วัด Pt L3 XANES",
        "2D XRD 매핑해줘": "ทำการแมป XRD 2D",
        "Ni XANES 하고 XRD도 해줘": "ทำ Ni XANES แล้วทำ XRD ด้วย",
        "12 keV로 설정하고 정렬한 다음 빔 프로파일 보여줘": "ตั้งค่าเป็น 12 keV ปรับแนวลำแสง แล้วแสดงโปรไฟล์ลำแสง",
        "Mo K-edge XAFS 측정해줘": "วัด Mo K-edge XAFS",
        "Cu 1um 시료의 투과율 보여줘": "แสดงค่าการส่งผ่านของตัวอย่าง Cu 1um",
        "산화철 50um 투과율은?": "ค่าการส่งผ่านของเหล็กออกไซด์ 50um เป็นเท่าไร?",
        "Ce L3 XANES 하려면 에너지를 얼마로 해야 해?": "ต้องตั้งพลังงานเท่าไรสำหรับ Ce L3 XANES?",
        "ptychography랑 XRF를 동시에 할 수 있어?": "ทำ ptychography กับ XRF พร้อมกันได้ไหม?",
        "Cu 분말 1000ppm XRF 최적화해줘": "ปรับ XRF ให้เหมาะสมสำหรับผง Cu 1000ppm",
        "ptychography 최적 조건 찾아줘. 시료는 Cu 박막이야": "หาเงื่อนไขที่เหมาะสมที่สุดสำหรับ ptychography ตัวอย่างเป็นฟิล์มบาง Cu",
        "지금 셋업에서 Cu 신호 얼마나 나와?": "การตั้งค่าปัจจุบันได้สัญญาณ Cu เท่าไร?",
        "movable mask를 1mm x 1mm로 이동시켜": "ตั้ง movable mask เป็น 1mm x 1mm",
        "어테뉴에이터에 Carbon 1mm 넣어줘": "ใส่ Carbon 1mm ในตัวลดทอน",
        "어테뉴에이터 전부 빼": "ถอดฟิลเตอร์ของตัวลดทอนออกทั้งหมด",
        "현위치에서 페르마 나선 스캔해줘": "ทำการสแกนเกลียวแฟร์มาที่ตำแหน่งปัจจุบัน",
        "시료를 (0,0)에서 (10,5)까지 라인스캔해줘": "สแกนเส้นตัวอย่างจาก (0,0) ถึง (10,5)",
        "M1 피치 자동 정렬해줘": "ปรับแนว M1 pitch อัตโนมัติ",
        "철 K-edge 주변 적응형 에너지 스캔해줘": "ทำการสแกนพลังงานแบบปรับตัวรอบ Fe K-edge",
        "Cu XAFS 실험 셋업해줘": "เตรียมการทดลอง Cu XAFS",
    },
}
for _d1_lang, _d1_map in _D1_TRANSLATIONS.items():
    _TRANSLATED_USER_UTTERANCES.setdefault(_d1_lang, {}).update(_d1_map)
del _D1_TRANSLATIONS


def _build_dynamic_prompt(intents: set, language: str = "ko",
                          mode: str = "virtual") -> str:
    """Build a dynamic system prompt based on detected intents.

    Combines SYSTEM_PROMPT_BASE + relevant example groups + few-shot examples.
    Always includes 'rejection' examples.
    Language parameter controls the explanation language instruction.
    Mode parameter ('virtual'/'real'/'dual') affects experiment-related behavior.
    """
    # Replace ALL Korean-only language instructions with dynamic ones
    base = SYSTEM_PROMPT_BASE
    lang_name = {
        'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 'zh': 'Chinese',
        'de': 'German', 'fr': 'French', 'es': 'Spanish',
        'th': 'Thai', 'hi': 'Hindi', 'ar': 'Arabic',
    }.get(language, 'English')
    lang_instr = _LANG_INSTRUCTION.get(language, _LANG_INSTRUCTION['en'])
    lang_short = _LANG_INSTRUCTION_SHORT.get(language, _LANG_INSTRUCTION_SHORT['en'])
    # (1) Main instruction line
    base = base.replace(
        '3. Always write "explanation" in Korean (\ud55c\uad6d\uc5b4). NEVER write in English or Japanese.',
        lang_instr
    )
    # (2) Shorter variant
    base = base.replace(
        '- Always write "explanation" in Korean.',
        '- ' + lang_short
    )
    # (3) Rejection section instruction
    base = base.replace(
        '- Explain in Korean why the measurement is impossible',
        '- Explain in ' + lang_name + ' why the measurement is impossible'
    )
    # (4) Response rules section
    base = base.replace(
        '1. Always respond in Korean for explanation.',
        '1. Always respond in ' + lang_name + ' for explanation.'
    )
    # (5) Never empty response instruction
    base = base.replace(
        'You MUST always provide a non-empty "explanation" in Korean.',
        'You MUST always provide a non-empty "explanation" in ' + lang_name + '.'
    )

    # Add explicit multilingual instruction for non-Korean/English/Japanese
    if language not in ("ko", "en", "ja"):
        base += (
            "\n\n## CRITICAL: Multilingual Command Processing\n"
            "The user is communicating in " + lang_name + ".\n"
            "You MUST process commands in ANY language identically to Korean/English.\n"
            "Map the user's intent to the SAME action functions regardless of input language.\n"
            "For example: 'Set energy to 12 keV' (English) = '\uc5d0\ub108\uc9c0\ub97c 12 keV\ub85c \uc124\uc815\ud574' (Korean) "
            "= same actions [{\"fn\":\"setTargetEnergy\",\"args\":[12]}].\n"
            "NEVER return empty actions just because the input language is not Korean.\n\n"
            "IMPORTANT OVERRIDE for " + lang_name + " users:\n"
            "- SKIP the Sample Preparation Check (Step 2). The system handles sample prep separately.\n"
            "- Generate actions DIRECTLY when the user's intent is clear.\n"
            "- Direct parameter commands (energy, motor, SSA) -> execute immediately.\n"
            "- XANES/XAFS/XRF/XRD measurement commands -> generate actions with confirmation_required=true.\n"
            "- Alignment commands -> generate runFullAlignment action.\n"
            "- Out-of-range requests -> return empty actions with explanation.\n"
            "- DO NOT ask about sample mounting, preparation presets, or measurement mode.\n"
        )
        # Also remove the sample prep HARD RULE from the base prompt
        base = base.replace(
            "**HARD RULE**: If user has NOT mentioned sample mounting/preparation "
            "in THIS conversation,\nreturn \"actions\":[] and ask about sample "
            "conditions in \"explanation\".",
            "For " + lang_name + " users: generate actions directly. "
            "Sample preparation is handled by the system."
        )

    parts = [base, "\n## Examples\n\n"]

    # Get translations for non-Korean/English/Japanese languages
    translations = None
    if language not in ("ko", "en", "ja"):
        translations = _TRANSLATED_USER_UTTERANCES.get(language)

    # ── Example-group token budget (D3 hardening, 2026-06-11) ──
    # When 3-4 intents fire together (e.g. optimize + scan_xrd + scan_xrf +
    # rejection) the assembled prompt reached 15.4k tokens, leaving only
    # ~800 output tokens inside the 16384 vLLM window -- responses were
    # truncated mid-JSON, parsed as empty, and benchmark cases regressed
    # (opt_01/02, batt_05, vexp_02 on 2026-06-11 rerun). Cap the prompt at
    # _PROMPT_BUDGET_CHARS (conservative ~2.6 chars/token, same estimate as
    # the chat() fallback counter): the base prompt always ships; example
    # groups are added smallest-first so that dropping the LARGEST surplus
    # group frees the most tokens while keeping every other intent covered.
    # 'rejection' (safety examples) is always kept.
    # Budget = (16384 window - 1100 output floor - 96 margin) tokens.
    # The base prompt alone is ~13.0k tok (33.9k chars), so the original
    # 13.8k-tok budget left only ~1.9k chars for example groups — in the
    # non-Korean path (D1) the multilingual override grew the base enough
    # to drop even the 'motor' group, defeating the few-shot translations.
    # Observed truncations (2026-06-11) happened at an ~840-token output
    # budget; real /no_think JSON responses run ~300-700 tokens, so an
    # 1.1k floor keeps >= 260 tok above the worst observed truncation point
    # (finish_reason=length telemetry guards regressions; chat() additionally
    # re-caps max_tokens against the REAL tokenized prompt at request time,
    # so this floor is a planning value, not the hard limit).
    # Floor 1300 -> 1100 (2026-06-12 regression triage, measured): the base
    # prompt is 33.9k chars, leaving only ~1.06k chars of group room after
    # the rejection group — below scan_xanes (1411 chars) and scan_xrf
    # (1945 chars) — so even SINGLE-task-intent prompts lost their relevant
    # example group (analysis_01/held_04 lost scan_xanes; edge_03/heavyel_01/
    # cmulti_01 lost scan_xrf) and the LLM regressed to clarifying-question /
    # empty-action mode. +540 chars restores both groups in the measured
    # 2-intent worst cases.
    # chars/token ratio 2.7: measured 13.5k tok for a 37k-char assembled
    # prompt (mixed EN rules + KO examples); 2.6 was over-conservative and
    # starved the non-Korean (D1) path of its translated example groups.
    _PROMPT_BUDGET_CHARS = int((16384 - 1100 - 96) * 2.7)
    # The budget must account for everything appended AFTER the group loop:
    # the few-shot block (computed here, appended below) and the mode /
    # language tail blocks (~3.2k chars for VIRTUAL MODE + ~0.2k language).
    # Without this reserve the assembled prompt exceeded the window by ~1k
    # tokens in the worst 4-intent case (measured 43.5k chars, 2026-06-12).
    few_shot_text = _select_few_shots(intents)
    _TAIL_RESERVE = len(few_shot_text) + 3600
    used = sum(len(p) for p in parts) + _TAIL_RESERVE
    groups = []
    for group_name in sorted(intents):
        group_text = _EXAMPLE_GROUPS.get(group_name)
        if group_text:
            # Substitute user utterances with target language translations
            if translations:
                for ko_text, translated in translations.items():
                    group_text = group_text.replace(
                        'User: "' + ko_text + '"',
                        'User: "' + translated + '"'
                    )
            groups.append((group_name, group_text))
    # rejection first (always kept), then smallest-first
    groups.sort(key=lambda g: (g[0] != "rejection", len(g[1])))
    dropped = []
    for group_name, group_text in groups:
        if group_name != "rejection" and \
                used + len(group_text) > _PROMPT_BUDGET_CHARS:
            dropped.append(group_name)
            continue
        parts.append(group_text)
        parts.append("\n")
        used += len(group_text) + 1
    if dropped:
        log.warning("dynamic prompt: dropped example group(s) %s to fit "
                    "the context budget (%d chars used)", dropped, used)

    # Add few-shot examples targeting P2 gaps (computed above, inside the
    # budget reserve)
    if few_shot_text:
        parts.append(few_shot_text)

    # ── Mode context: virtual vs real experiment behavior ──
    if mode == "virtual":
        parts.append("""
## VIRTUAL MODE — Important Behavioral Rules
The beamline is currently in **VIRTUAL (simulation) mode**.
- Do NOT ask about sample preparation (mounting, in-situ setup, etc.)
- Measurements run as virtual simulations — no physical sample is involved.
- When the user requests a scan/measurement, ask which virtual experiment preset
  and sample they want to use. Do NOT just run quickRaster directly.
- Use setupVirtualExperiment(presetId) to start virtual experiments.

### Available Experiment Presets:
  | Preset ID       | Description |
  |-----------------|-------------|
  | cu_xafs         | Cu K-edge XAFS (absorption spectroscopy) |
  | xrf_imaging     | XRF element mapping (2D fluorescence imaging) |
  | powder_xrd      | Powder X-ray diffraction |
  | nano_xrf_line   | Nano-XRF line scan |
  | xrf_2d_map      | XRF 2D raster map |
  | xrd_2d_map      | XRD 2D raster map |
  | xrd_grazing     | Grazing incidence XRD (thin film) |

### Available Sample Presets (for XRF/XRD virtual experiments):
  | Sample ID              | Description |
  |------------------------|-------------|
  | semiconductor_ic       | Semiconductor IC cross-section (Cu, W, Co, Ti) |
  | battery_nmc622         | NMC622 battery cathode (Ni, Mn, Co) |
  | geological_section     | Geological thin section (Fe, Ti, Mn, Cr) |
  | biological_cell        | Biological cell, freeze-dried (Fe, Zn, Cu) |
  | catalyst_nanoparticle  | Catalyst NPs on support (Pt, Au, Fe, Ce) |
  | environmental_particle | Environmental fly ash particle (Fe, Ti, Cr, Pb) |
  | siemens_star           | Au Siemens star (resolution test) |

### CRITICAL virtual experiment rules:
- In VIRTUAL mode, NEVER use nanoScanStep2D/nanoScanFly1D/nanoScanSpiral.
  These are REAL hardware commands. Use quickRaster/quickXanes/quickXafs instead,
  which route to the server experiment engine and show results in a popup.
  Example: "XRF raster scan on semiconductor" → quickRaster(6, 6, 21, "semiconductor_ic") + queueStart()
  Example: "Siemens star XRF map" → quickRaster(30, 30, 21, "siemens_star") + queueStart()
    ALWAYS pass the 4th argument presetKey when the user names a sample. If you omit it,
    the scan falls back to the default sample and ignores the one the user requested.
    The two FOV values are full-sample sizes; if the user gives no size the system
    substitutes the sample's recommended full FOV, so just pass the preset.
    Valid presetKey: semiconductor_ic|battery_nmc622|geological_section|biological_cell|catalyst_nanoparticle|environmental_particle|siemens_star|calibration_grid
  Example: "Cu XANES" → quickXanes("Cu","K") + queueStart()
  DO NOT call setupVirtualExperiment — it's for tutorial only. quickRaster/quickXanes handle presets internally.
- NEVER run quickRaster/quickXanes/quickXafs without sample information.
  EXCEPTION (execute-first, owner convention): if the user already names the
  ELEMENT or a recognizable sample context (e.g. "아연의 화학 상태",
  "니켈 산화물", "양극재"), that IS sufficient sample information — proceed
  with defaults and state them inline instead of asking.
- If user says "XRF scan", "raster scan", "XAFS", "XRD" etc. WITHOUT specifying
  a sample type, you MUST respond with actions=[] and ask:
  "Which sample would you like to use? Available presets:
   1. semiconductor_ic — Semiconductor IC (Cu/W/Co/Ti in SiO2)
   2. battery_nmc622 — NMC622 battery cathode (Ni/Mn/Co)
   3. geological_section — Geological thin section (Fe/Ti/Mn/Cr)
   4. biological_cell — Biological cell (Fe/Zn/Cu)
   5. catalyst_nanoparticle — Catalyst NPs (Pt/Au/Fe/Ce)
   6. environmental_particle — Fly ash particle (Fe/Ti/Cr/Pb)
   7. siemens_star — Au Siemens star (resolution test)
   Or describe your own sample (formula, thickness, density)."
- For XRD experiments, also ask: detector distance (default 150mm), crystal type.
- If user specifies enough context (e.g., "battery cathode XRF"), pick the matching
  preset and proceed directly with setupVirtualExperiment + startExperiment.
- When experiment energy differs from current by >= 1 keV, include alignment:
  setTargetEnergy → runFullAlignment → experiment
- Always respond in the user's language.
""")
    elif mode == "real":
        parts.append("""
## REAL MODE — Important Behavioral Rules
The beamline is currently in **REAL (hardware) mode**.
- Physical sample is mounted on the stage.
- Sample preparation confirmation is REQUIRED before any measurement.
- Safety checks are strictly enforced.
""")

    # ── Final language enforcement (placed LAST to override few-shot bias) ──
    if language != "ko":
        lang_name = {
            'en': 'English', 'ja': 'Japanese', 'zh': 'Chinese',
            'de': 'German', 'fr': 'French', 'es': 'Spanish',
            'th': 'Thai', 'hi': 'Hindi', 'ar': 'Arabic',
        }.get(language, 'English')
        parts.append(f"""
## CRITICAL — RESPONSE LANGUAGE
The user is writing in {lang_name}. You MUST write the "explanation" field in {lang_name}.
Do NOT write in Korean. Write ONLY in {lang_name}.
""")

    return "".join(parts)


# ══════════════════════════════════════════════════════════════════════
# Compact System Prompt — for small local LLMs (Qwen3:8b etc.)
# Reduced from 330 lines to ~120 lines to prevent function hallucination.
# ══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT_COMPACT = """You are a K4GSR nanoprobe beamline assistant. Convert user requests into JSON actions.
IMPORTANT: You must ALWAYS try to generate actions. Do NOT return empty actions unless genuinely unable to determine what to do.

## STRICT RULES
1. ONLY use functions listed below. NEVER invent functions.
2. After scan functions, ALWAYS add queueStart().
3. explanation MUST be in Korean.
4. For questions (뭐야, 차이, 몇 keV): actions=[], answer in explanation.
5. confirmation_required=true for motor/energy/scan changes. false for questions/info/showBeamProfile.
6. Energy range: 5-25 keV HARD LIMIT. Elements with edge below 5 keV CANNOT be measured:
   C(0.28), N(0.40), O(0.54), Mg(1.30), Al(1.56), Si(1.84), P(2.15), S(2.47), Ca(4.04) keV — ALL out of range.
   For these: return actions:[] and explain in Korean. NEVER use setTargetEnergy/quickXanes/quickXafs.
   Do NOT substitute with 5 keV — that is NOT the element's edge.
7. Heavy elements (Z>=56): Use L3-edge. W L3=10.207, Pt L3=11.564, Au L3=11.919, Pb L3=13.035, Ce L3=5.723
8. DEFAULT PARAMETERS: If user gives partial scan params, use sensible defaults (nPoints=51, dr=0.5, nPts=11). ONLY ask if element/technique is completely unclear.
9. AUTO-ALIGNMENT: If |energy change| >= 1 keV from current energy, add runFullAlignment() after setTargetEnergy. For sequential scans, align once before first scan if dE >= 1 keV from current. KB mirror focal length does NOT change with energy.
10. DOMAIN MAPPING: When user mentions sample context (battery, catalyst, semiconductor, cell...), extract the element and technique, then call the appropriate function. Example: "배터리 양극재 Ni XANES" → quickXanes("Ni","K")
11. FUNCTION SELECTION: "XANES/XAFS 해줘" → quickXanes/quickXafs. "최적화/optimize" → optimizeBeamline. "XRF 맵핑/이미징" → quickRaster. Do NOT use optimizeBeamline for direct scan requests.
12. NEVER EMPTY RESPONSE: You MUST always provide a non-empty "explanation" in Korean.
13. ACTIONS MUST NOT BE EMPTY for measurement requests. "분석하고 싶어", "구분하고 싶어", "확인해줘" = measurement → actions. Use defaults if missing.
14. MULTI-ELEMENT PARTIAL: Out-of-range elements → generate for in-range, explain rest.
15. QUESTION+ACTION: answer in explanation + actions for scan.
16. SEQUENTIAL: generate ALL actions in energy order.
17. SSA = motorSetUI("ssa","ssa_hgap/ssa_vgap",value). maskAperUpdate ONLY for fmask/mmask.
18. emergencyStop requires confirmation_required=true.
19. SETUP vs EXECUTE: "셋업/세팅/준비" = prepare only (NO queueStart). "측정/찍어/돌려/시작/해줘" = execute (add queueStart).
20. MULTI-ELEMENT XRF: Energy ABOVE the HIGHEST edge + 1 keV. Example: Ni+Co+Mn → 8.333+1.2 = 9.5 keV.
21. EXPOSURE TIME: Mention default exposure time in explanation for all scans (e.g., "노출 시간: 0.1초/포인트 기본").
22. Pt MEASUREMENT: Warn about mirror Pt coating interference. Recommend switching to Rh stripe.
23. INFO vs ACTION: "얼마로 해야 해?" = info only (actions:[]). "해줘/맞춰줘" = action.
24. XRD: Single-shot XRD = setupVirtualExperiment('powder_xrd'). 2D XRD mapping = quickRaster. After XANES "XRD도" = single-shot. Phase analysis = usually single-shot. Thin film/surface/grazing = setupVirtualExperiment('xrd_grazing').
25. SIMULTANEOUS: XRF+XRD = simultaneous (different detectors). Ptychography+XRF = simultaneous (scanning-based). XANES+XRF mapping = NOT simultaneous.
26. CONTAMINATION CHECK: Prefer XRF mapping over single-point XANES (nanobeam may miss spot).
27. UNIT CLARIFICATION: Always state units in explanation. If unit is ambiguous, ask user.
28. ACTION EXPLANATION: For every action, explain which device is changed and how in explanation.
29. HETEROGENEOUS SAMPLE: Environmental/geological/bio samples → suggest XRF mapping first for hotspot, then XANES.
30. Ag K-edge (25.514 keV) is over limit AND Ag L3-edge (3.351 keV) is under limit. NO edge available for Ag. Do NOT suggest L3 or CCM workaround.

## Output format
{"actions":[{"fn":"funcName","args":[...]}],"explanation":"한국어 설명","confirmation_required":true}

## K-edges (keV)
IN RANGE: Ti:4.966 Cr:5.989 Mn:6.539 Fe:7.112 Co:7.709 Ni:8.333 Cu:8.979 Zn:9.659 As:11.867 Se:12.658 Sr:16.105 Mo:20.000
L3-edges: Ce:5.723 W:10.207 Pt:11.564 Au:11.919 Pb:13.035
OUT OF RANGE (actions:[], explain only): C:0.28 N:0.40 O:0.54 Mg:1.30 Al:1.56 Si:1.84 P:2.15 S:2.47 Ca:4.04

## XRF energy rule: set energy 1-2 keV ABOVE K/L3-edge to excite fluorescence
Fe XRF → ~8.5 keV, Cu XRF → ~10 keV, Zn XRF → ~11 keV, Au L3 XRF → ~13.5 keV, Pb L3 XRF → ~14.5 keV

## ALL Available Functions (use ONLY these!)
- setTargetEnergy(keV) — set beam energy
- setCrystal("111"|"311") — change crystal
- motorSetUI("groupId","motorId",value) — move motor
  Groups: m1(m1_pitch,...), dcm(dcm_theta,...), m2(m2_pitch,...), ssa(ssa_hgap,ssa_vgap,...), kbslit(kbslit_hgap,kbslit_vgap,kbslit_hcen,kbslit_vcen), sample(sample_cx,sample_cy,...), kbv(kbv_pitch,...), kbh(kbh_pitch,...), wbslit(...), det(det_x,det_y,det_z)
- maskAperUpdate("fmask"|"mmask","h"|"v",value_mm) — mask gap
- setAttenFilter(slot,"material"|"thickness",value) — attenuator (slot 0-3, material:"None" to remove)
- runFullAlignment() — full 7-step alignment
- runMirrorAlignUI("m1"|"m2"|"dcm"|"kbv"|"kbh") — single mirror alignment
- quickXafs("element","edge") + queueStart() — XAFS scan
- quickXanes("element","edge") + queueStart() — XANES scan (0.25eV)
- quickRaster(xRange,yRange,numPts) + queueStart() — 2D XRF/XRD map
- quickEnergyScan(start,stop,num) + queueStart() — energy scan
- quickFlyScan("motor","axis",start,stop,nPts) + queueStart() — fly scan (default nPts=51)
- quickFermat(xRange,yRange,dr) + queueStart() — Fermat spiral (default dr=0.5)
- quickRelRaster(dx,dy,nx,ny) + queueStart() — relative raster from current position
- quickRelAlign("dev","axis",width,nPts) + queueStart() — relative alignment scan (default nPts=11)
- quickAutoTune("dev","axis",start,stop,"targetField") + queueStart() — auto-tune
- quickAdaptiveScan(eStart,eStop,minStep,maxStep) + queueStart() — adaptive energy scan
- quickCount(num,dwell) + queueStart() — point measurement
- queueStart()/queueStop()/queuePause()/queueClear()
- optimizeBeamline({technique,element,edge,ppm,sampleType,priority}) — optimize settings
  technique: "xrf"|"xafs"|"xanes"|"xrd"|"ptycho"
  priority: "balanced"|"resolution"|"speed"|"signal"|"coherence"
- estimateSignal("tech","element",ppm,flux,beamSize,thickness) — signal estimate
- showBeamProfile("sample"|"m1"|"dcm"|...) — beam profile
- showTransmission("formula",thickness_um,density_gcc) — sample transmission T(E) curve
- emergencyStop() — emergency stop
- homeMotor(groupId,motorId) — motor homing (KOHZU stages only)
- switchTab("tabId") — tab switch

## Korean Aliases
M1피치→motorSetUI("m1","m1_pitch",v) / 시료X절대→motorSetUI("sample","sample_cx",v) / 시료X상대→motorMoveRelUI("sample","sample_cx",v) / SSA수평→motorSetUI("ssa","ssa_hgap",v)
원점복귀/홈/home→homeMotor("sample","sample_cx") / 긴급정지/비상정지/estop→emergencyStop()

## Examples (18 basic + 10 advanced)
User: "에너지를 12 keV로 설정해"
{"actions":[{"fn":"setTargetEnergy","args":[12]}],"explanation":"빔 에너지를 12 keV로 설정합니다.","confirmation_required":true}

User: "구리 K-edge XAFS 측정해줘"
{"actions":[{"fn":"quickXafs","args":["Cu","K"]},{"fn":"queueStart","args":[]}],"explanation":"Cu K-edge XAFS 스캔을 실행합니다.","confirmation_required":true}

User: "M1 피치를 2.5로 이동해"
{"actions":[{"fn":"motorSetUI","args":["m1","m1_pitch",2.5]}],"explanation":"M1 피치를 2.5 mrad로 이동합니다.","confirmation_required":true}

User: "시료 X를 5 mm로 이동해" (absolute move)
{"actions":[{"fn":"motorSetUI","args":["sample","sample_cx",5.0]}],"explanation":"시료 CX를 절대 위치 5.0 mm로 이동합니다.","confirmation_required":true}

User: "샘플 엑스 방향 모터를 +로 2 밀리미터 움직여" (relative +2mm from current)
{"actions":[{"fn":"motorMoveRelUI","args":["sample","sample_cx",2.0]}],"explanation":"시료 CX를 현재 위치에서 +2.0 mm 상대 이동합니다.","confirmation_required":true}

User: "전체 빔 정렬 시작"
{"actions":[{"fn":"runFullAlignment","args":[]}],"explanation":"전체 빔라인 정렬(7단계)을 시작합니다.","confirmation_required":true}

User: "빔 프로파일 보여줘"
{"actions":[{"fn":"showBeamProfile","args":["sample"]}],"explanation":"시료 위치에서 빔 프로파일을 표시합니다.","confirmation_required":false}

User: "10x10 41포인트 철 XRF 2D 맵 측정해줘"
{"actions":[{"fn":"setTargetEnergy","args":[8.5]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge 위 8.5 keV로 설정 후 XRF 래스터 스캔합니다.","confirmation_required":true}

User: "철 XANES 측정해줘"
{"actions":[{"fn":"quickXanes","args":["Fe","K"]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge XANES 스캔을 실행합니다.","confirmation_required":true}

User: "Mo K-edge XAFS 측정해줘" [State: energy=10]
{"actions":[{"fn":"setTargetEnergy","args":[20]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXafs","args":["Mo","K"]},{"fn":"queueStart","args":[]}],"explanation":"Mo K-edge (20 keV) XAFS. 에너지 변화 10keV이므로 정렬 수행합니다.","confirmation_required":true}

User: "Cu 분말 1000ppm XRF 최적화해줘"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Cu","edge":"K","ppm":1000,"sampleType":"powder","priority":"balanced"}]}],"explanation":"Cu XRF 최적화 설정을 계산합니다.","confirmation_required":true}

User: "XRD가 뭐야?"
{"actions":[],"explanation":"XRD(X선 회절)는 결정 구조를 분석하는 기법입니다. Bragg 법칙에 따라 특정 각도에서 회절이 발생합니다.","confirmation_required":false}

User: "어테뉴에이터에 Carbon 1mm 넣어줘"
{"actions":[{"fn":"setAttenFilter","args":[0,"material","Carbon"]},{"fn":"setAttenFilter","args":[0,"thickness",1.0]}],"explanation":"슬롯0에 Carbon 1mm 삽입합니다.","confirmation_required":true}

User: "movable mask를 1mm x 1mm로 해줘"
{"actions":[{"fn":"maskAperUpdate","args":["mmask","h",1]},{"fn":"maskAperUpdate","args":["mmask","v",1]}],"explanation":"Movable Mask 1mm x 1mm로 설정합니다.","confirmation_required":true}

User: "긴급 정지!"
{"actions":[{"fn":"emergencyStop","args":[]}],"explanation":"긴급 정지를 실행합니다.","confirmation_required":true}

User: "현위치 기준 5x5 래스터 스캔해줘"
{"actions":[{"fn":"quickRelRaster","args":[5,5,21,21]},{"fn":"queueStart","args":[]}],"explanation":"현위치 기준 5x5 래스터 스캔합니다.","confirmation_required":true}

User: "M1 피치 자동 정렬해줘"
{"actions":[{"fn":"quickAutoTune","args":["m1","pitch",1.0,4.0,"ic1_current"]},{"fn":"queueStart","args":[]}],"explanation":"M1 피치 자동 정렬합니다.","confirmation_required":true}

User: "SSA 수평갭 30으로"
{"actions":[{"fn":"motorSetUI","args":["ssa","ssa_hgap",30]}],"explanation":"SSA 수평갭을 30 um로 설정합니다.","confirmation_required":true}

User: "Pt L3-edge XANES 측정해줘"
{"actions":[{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge XANES 스캔입니다.","confirmation_required":true}

User: "Si(311)로 변경해줘"
{"actions":[{"fn":"setCrystal","args":["311"]}],"explanation":"결정을 Si(311)로 변경합니다.","confirmation_required":true}

User: "catalyst Pt L3 XANES scan"
{"actions":[{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge (11.564 keV) XANES. 촉매 시료의 Pt 산화 상태를 분석합니다. 미러 Pt 코팅 간섭 주의 - Rh stripe 권장.","confirmation_required":true}

User: "full beam alignment"
{"actions":[{"fn":"runFullAlignment","args":[]}],"explanation":"전체 빔라인 정렬(7단계)을 시작합니다.","confirmation_required":true}

User: "M1 피치를 1~4 mrad에서 고속스캔해줘"
{"actions":[{"fn":"quickFlyScan","args":["m1","pitch",1,4,51]},{"fn":"queueStart","args":[]}],"explanation":"M1 피치 1-4 mrad 고속스캔합니다.","confirmation_required":true}

User: "철 K-edge 주변 적응형 에너지 스캔해줘"
{"actions":[{"fn":"quickAdaptiveScan","args":[7.0,7.3,0.5,2.0]},{"fn":"queueStart","args":[]}],"explanation":"Fe K-edge 주변 적응형 에너지 스캔합니다.","confirmation_required":true}

User: "DCM 세타 현위치 기준 +/-0.5도 정렬 스캔해줘"
{"actions":[{"fn":"quickRelAlign","args":["dcm","theta",0.5,11]},{"fn":"queueStart","args":[]}],"explanation":"DCM 세타 상대 정렬 스캔합니다.","confirmation_required":true}

User: "현위치에서 페르마 나선 스캔해줘"
{"actions":[{"fn":"quickFermat","args":[10,10,0.5]},{"fn":"queueStart","args":[]}],"explanation":"현위치에서 10x10 um 페르마 나선 스캔합니다.","confirmation_required":true}

User: "지금 셋업에서 Cu 신호 얼마나 나와?"
{"actions":[{"fn":"estimateSignal","args":["xrf","Cu",10000,1e10,50,10]}],"explanation":"현재 설정에서 Cu XRF 신호를 예측합니다.","confirmation_required":false}

User: "어테뉴에이터 전부 빼"
{"actions":[{"fn":"setAttenFilter","args":[0,"material","None"]},{"fn":"setAttenFilter","args":[0,"thickness",0]},{"fn":"setAttenFilter","args":[1,"material","None"]},{"fn":"setAttenFilter","args":[1,"thickness",0]},{"fn":"setAttenFilter","args":[2,"material","None"]},{"fn":"setAttenFilter","args":[2,"thickness",0]},{"fn":"setAttenFilter","args":[3,"material","None"]},{"fn":"setAttenFilter","args":[3,"thickness",0]}],"explanation":"4개 슬롯 모두 제거합니다.","confirmation_required":true}

User: "철 시료인데 가장 좋은 분해능으로 XRF 맵핑하고 싶어"
{"actions":[{"fn":"optimizeBeamline","args":[{"technique":"xrf","element":"Fe","edge":"K","ppm":1000,"sampleType":"solid","priority":"resolution"}]}],"explanation":"Fe XRF 고분해능 최적화를 계산합니다.","confirmation_required":true}

User: "Pt/C 촉매에서 백금 산화 상태를 XANES로 확인해주세요"
{"actions":[{"fn":"quickXanes","args":["Pt","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pt L3-edge XANES로 백금 산화 상태를 분석합니다.","confirmation_required":true}

User: "금 시료 XRF 해주세요. 5x5 41포인트." [State: energy=10]
{"actions":[{"fn":"setTargetEnergy","args":[13.5]},{"fn":"runFullAlignment","args":[]},{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],"explanation":"Au L3-edge 위 13.5 keV로 설정 후 정렬, 5x5 XRF 맵 측정합니다.","confirmation_required":true}

User: "배터리 양극재에서 Ni, Mn, Co 원소 분포를 XRF 맵핑해주세요. 10x10 41포인트" [State: energy=10]
{"actions":[{"fn":"setTargetEnergy","args":[10]},{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"NMC 양극재 다원소 XRF 맵핑. Ni/Mn/Co K-edge 모두 10keV 이하이므로 현재 에너지로 측정합니다.","confirmation_required":true}

User: "동결건조 세포에서 Fe, Zn 나노 XRF 이미징해줘. 5x5 41포인트" [State: energy=10]
{"actions":[{"fn":"quickRaster","args":[5,5,41]},{"fn":"queueStart","args":[]}],"explanation":"Fe/Zn XRF 이미징. 두 원소 K-edge 모두 10 keV 이하이므로 현재 에너지로 측정합니다.","confirmation_required":true}

User: "하수 슬러지 시료 아연 화학 상태 확인해주세요"
{"actions":[{"fn":"quickXanes","args":["Zn","K"]},{"fn":"queueStart","args":[]}],"explanation":"Zn K-edge XANES로 아연의 화학 상태를 분석합니다.","confirmation_required":true}

User: "비산재 입자에서 납 XANES 해주세요"
{"actions":[{"fn":"setTargetEnergy","args":[14.5]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXanes","args":["Pb","L3"]},{"fn":"queueStart","args":[]}],"explanation":"Pb L3-edge XANES. 에너지 변화 4.5keV이므로 정렬 수행합니다.","confirmation_required":true}

User: "고엔트로피 합금 Fe,Co,Ni,Cr,Mn XRF 맵핑. 10x10 41포인트"
{"actions":[{"fn":"quickRaster","args":[10,10,41]},{"fn":"queueStart","args":[]}],"explanation":"HEA 다원소 XRF 맵핑. 모든 원소 K-edge가 10keV 이하이므로 현재 에너지로 측정합니다.","confirmation_required":true}

User: "SrTiO3에서 Ti XANES 하고 Sr XANES도 해주세요" [State: energy=10]
{"actions":[{"fn":"quickXanes","args":["Ti","K"]},{"fn":"queueStart","args":[]},{"fn":"setTargetEnergy","args":[17]},{"fn":"runFullAlignment","args":[]},{"fn":"quickXanes","args":["Sr","K"]},{"fn":"queueStart","args":[]}],"explanation":"Ti K-edge XANES 후 Sr K-edge XANES. Sr 측정 시 에너지 변화 7keV이므로 정렬 수행합니다.","confirmation_required":true}

User: "황 XANES 해줘" (S K-edge=2.47 keV -- OUT OF RANGE!)
{"actions":[],"explanation":"S(황) K-edge 에너지는 2.472 keV로, 빔라인 에너지 범위(5-25 keV)보다 낮아 측정할 수 없습니다.","confirmation_required":false}

User: "산소 K-edge XANES 측정해줘" (O K-edge=0.54 keV -- OUT OF RANGE!)
{"actions":[],"explanation":"O(산소) K-edge 에너지는 0.543 keV로, 빔라인 에너지 범위(5-25 keV) 아래입니다. 연X선 빔라인이 필요합니다.","confirmation_required":false}
"""


# ══════════════════════════════════════════════════════════════════════
# Backend: Ollama (local LLM — free, offline)
# ══════════════════════════════════════════════════════════════════════
class OllamaBackend:
    def __init__(self):
        if not _HTTPX_OK:
            raise ImportError("httpx required for Ollama. Install: pip install httpx")
        self.url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        self._client = httpx.AsyncClient(timeout=60.0)  # D11: 600s→60s
        log.info(f"  Ollama: model={self.model}, url={self.url}")

    async def chat(self, system: str, messages: List[Dict], max_tokens: int = 1024) -> str:
        ollama_msgs = [{"role": "system", "content": system}]
        for m in messages:
            ollama_msgs.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": self.model,
            "messages": ollama_msgs,
            "stream": False,
            "format": {
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "fn": {"type": "string"},
                                "args": {"type": "array"}
                            },
                            "required": ["label", "fn", "args"]
                        }
                    },
                    "explanation": {"type": "string"},
                    "confirmation_required": {"type": "boolean"}
                },
                "required": ["actions", "explanation", "confirmation_required"]
            },
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.1,
                "top_p": 0.9,
                "repeat_penalty": 1.05
            }
        }

        # Model-size-aware prompt selection (Strategy 1):
        # Large models (235b, 70b, 72b, 110b, qwq) get FULL prompt for best accuracy.
        # Small models get COMPACT prompt to avoid function hallucination.
        _LARGE_MODELS = ("235b", "70b", "72b", "110b", "qwq")
        _MOE_MODELS = ("235b", "a22b", "moe")  # MoE models need action reinforcement
        is_large = any(tag in self.model.lower() for tag in _LARGE_MODELS)
        is_moe = any(tag in self.model.lower() for tag in _MOE_MODELS)

        if is_large:
            body["options"]["num_ctx"] = 8192   # reduced from 16384 to save KV cache VRAM
            body["options"]["num_predict"] = 4096  # MoE models need more output tokens
        else:
            ollama_msgs[0]["content"] = SYSTEM_PROMPT_COMPACT

        # MoE models tend to generate explanation but leave actions empty.
        # Add explicit action-forcing instruction at end of system prompt.
        if is_moe:
            moe_suffix = (
                "\n\n[CRITICAL INSTRUCTION FOR STRUCTURED OUTPUT]\n"
                "You MUST always populate the 'actions' array when the user "
                "requests any actionable operation (scan, motor move, energy change, "
                "optimization, alignment, etc.). "
                "NEVER return actions:[] for actionable requests. "
                "If unsure about parameters, use reasonable defaults and set "
                "confirmation_required:true. "
                "Only return empty actions for pure information queries or "
                "genuinely impossible requests (e.g. element not measurable)."
            )
            ollama_msgs[0]["content"] = ollama_msgs[0]["content"] + moe_suffix

        # Qwen3 thinking mode produces invalid JSON with structured output.
        # Disable thinking by adding /no_think tag to system prompt.
        if "qwen3" in self.model.lower():
            ollama_msgs[0]["content"] = "/no_think\n" + ollama_msgs[0]["content"]

        resp = await self._client.post(f"{self.url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


# ══════════════════════════════════════════════════════════════════════
# Backend: Google Gemini (free tier available)
# ══════════════════════════════════════════════════════════════════════
class GeminiBackend:
    def __init__(self):
        if not _GEMINI_OK:
            raise ImportError(
                "google-generativeai required for Gemini. "
                "Install: pip install google-generativeai"
            )
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set in environment or .env")
        genai.configure(api_key=api_key)
        self.model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        log.info(f"  Gemini: model={self.model_name}")

    async def chat(self, system: str, messages: List[Dict], max_tokens: int = 1024) -> str:
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system,
            generation_config=genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        response = await model.generate_content_async(contents)
        return response.text


# ══════════════════════════════════════════════════════════════════════
# Backend: Anthropic Claude (paid)
# ══════════════════════════════════════════════════════════════════════
class ClaudeBackend:
    def __init__(self):
        if not _ANTHROPIC_OK:
            raise ImportError("anthropic required for Claude. Install: pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment or .env")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
        log.info(f"  Claude: model={self.model}")

    async def chat(self, system: str, messages: List[Dict], max_tokens: int = 1024) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages
        )
        return response.content[0].text


# ══════════════════════════════════════════════════════════════════════
# Backend: Groq (free tier — Llama 3.3 70B, very fast inference)
# ══════════════════════════════════════════════════════════════════════
class GroqBackend:
    def __init__(self):
        if not _HTTPX_OK:
            raise ImportError("httpx required for Groq. Install: pip install httpx")
        self.api_key = os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set in environment or .env")
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._client = httpx.AsyncClient(timeout=120.0)
        log.info(f"  Groq: model={self.model}")

    async def chat(self, system: str, messages: List[Dict], max_tokens: int = 1024) -> str:
        api_msgs = [{"role": "system", "content": system}]
        for m in messages:
            api_msgs.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "top_p": 0.9,
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        max_retries = 4
        for attempt in range(max_retries):
            resp = await self._client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=body, headers=headers
            )

            # On 400 error, retry without json_object constraint
            if resp.status_code == 400:
                log.warning("Groq 400 error — retrying without response_format")
                body.pop("response_format", None)
                resp = await self._client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=body, headers=headers
                )

            # On 429 rate limit, exponential backoff retry
            if resp.status_code == 429:
                wait = 2 ** attempt  # 1, 2, 4, 8 seconds
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                log.warning(f"Groq 429 rate limit — retry {attempt+1}/{max_retries} after {wait}s")
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                    continue
                else:
                    raise RuntimeError(
                        f"Groq rate limit (429) exceeded after {max_retries} retries. "
                        "Consider switching to NLP_ENGINE=gemini in server/.env"
                    )

            break  # success or non-retryable error

        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════════════
# Backend: OpenAI-Compatible (DeepSeek, OpenAI, Mistral, Together, etc.)
# ══════════════════════════════════════════════════════════════════════
# Preset configurations for known providers
_OPENAI_COMPAT_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "key_env": "MISTRAL_API_KEY",
        "model_env": "MISTRAL_MODEL",
    },
    "solar": {
        "base_url": "https://api.upstage.ai/v1",
        "model": "solar-pro3",
        "key_env": "UPSTAGE_API_KEY",
        "model_env": "SOLAR_MODEL",
    },
}


class OpenAICompatBackend:
    """Generic backend for any OpenAI-compatible API (DeepSeek, OpenAI, Mistral, etc.)."""

    def __init__(self, preset_name: str = None):
        if not _HTTPX_OK:
            raise ImportError("httpx required. Install: pip install httpx")

        preset = _OPENAI_COMPAT_PRESETS.get(preset_name, {})
        self.base_url = os.environ.get(
            "OPENAI_COMPAT_BASE_URL",
            preset.get("base_url", "https://api.openai.com/v1")
        )
        key_env = preset.get("key_env", "OPENAI_COMPAT_API_KEY")
        self.api_key = os.environ.get(key_env)
        if not self.api_key:
            # Fallback to generic key
            self.api_key = os.environ.get("OPENAI_COMPAT_API_KEY")
        if not self.api_key:
            raise ValueError(
                f"{key_env} not set in environment or .env"
            )

        model_env = preset.get("model_env", "OPENAI_COMPAT_MODEL")
        self.model = os.environ.get(
            model_env,
            preset.get("model", "gpt-4o-mini")
        )
        self._client = httpx.AsyncClient(timeout=120.0)
        log.info(f"  OpenAI-Compat: model={self.model}, url={self.base_url}")

    async def chat(self, system: str, messages: List[Dict], max_tokens: int = 1024) -> str:
        api_msgs = [{"role": "system", "content": system}]
        for m in messages:
            api_msgs.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "top_p": 0.9,
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            json=body, headers=headers
        )

        # On 400 error, retry without json_object constraint
        if resp.status_code == 400:
            log.warning("OpenAI-compat 400 error -- retrying without response_format")
            body.pop("response_format", None)
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=body, headers=headers
            )

        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# Factory functions for preset backends
def _make_deepseek():
    return OpenAICompatBackend("deepseek")

def _make_openai():
    return OpenAICompatBackend("openai")

def _make_mistral():
    return OpenAICompatBackend("mistral")

def _make_solar():
    return OpenAICompatBackend("solar")

def _make_custom():
    return OpenAICompatBackend()


# ══════════════════════════════════════════════════════════════════════
# Backend: vLLM (local, OpenAI-compatible, with prefix caching)
# ══════════════════════════════════════════════════════════════════════
class VLLMBackend:
    """Local vLLM server backend. Uses OpenAI-compatible API with
    optimizations: prefix caching, tensor parallelism, low temperature."""

    def __init__(self):
        if not _HTTPX_OK:
            raise ImportError("httpx required. Install: pip install httpx")
        self.url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
        self.model = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-32B")
        self._client = httpx.AsyncClient(timeout=300.0)
        self._max_len = None  # served context window (max_model_len), fetched lazily
        log.info(f"  vLLM: model={self.model}, url={self.url}")

    async def _get_max_len(self) -> int:
        """Served context window (vLLM max_model_len), cached. 16384 fallback.

        vLLM may be (re)started with a smaller context than the system prompt +
        output need; querying it lets us fit the request instead of 400-ing.
        """
        if self._max_len is None:
            env = os.environ.get("VLLM_MAX_MODEL_LEN", "")
            if env.isdigit():
                self._max_len = int(env)
            else:
                try:
                    r = await self._client.get(f"{self.url}/models", timeout=10.0)
                    self._max_len = int(r.json()["data"][0]["max_model_len"])
                except Exception:
                    self._max_len = 16384
        return self._max_len

    async def chat(self, system: str, messages: List[Dict],
                   max_tokens: int = 1024) -> str:
        api_msgs = [{"role": "system", "content": system}]
        for m in messages:
            api_msgs.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "top_p": 0.9,
            "response_format": {"type": "json_object"},
        }

        _model_lower = self.model.lower()

        # Qwen3: disable thinking mode to prevent invalid JSON
        if "qwen3" in _model_lower or "qwen" in _model_lower:
            api_msgs[0]["content"] = "/no_think\n" + api_msgs[0]["content"]

        # Gemma 4: vLLM does not support response_format for Gemma models;
        # remove it to avoid 400 errors. Increase max_tokens for reasoning.
        # Add explicit JSON + confirmation_required reinforcement.
        if "gemma-4" in _model_lower or "gemma4" in _model_lower or "gemma" in _model_lower:
            body.pop("response_format", None)
            body["max_tokens"] = max(max_tokens, 2048)
            # Gemma tends to omit confirmation_required and return empty actions
            # for indirect requests. Reinforce these rules.
            _gemma_suffix = (
                "\n\n[CRITICAL RULES FOR JSON OUTPUT]\n"
                "1. You MUST output ONLY valid JSON. No markdown, no ```json blocks, no extra text.\n"
                "2. confirmation_required MUST be true for ANY action that changes beamline state "
                "(motor moves, energy changes, scans, alignments, experiments). "
                "Only set false for pure info/status queries with actions:[].\n"
                "3. When user mentions element analysis (산화상태, 화학결합, speciation, phase ID, "
                "contamination check, distribution), this IS a measurement request. "
                "Map to the correct technique (XANES for oxidation/bonding, XRF for distribution) "
                "and generate actions. Do NOT return empty actions.\n"
                "4. For XRF of heavy elements (Au, Pb, W, Pt): you MUST add "
                "setTargetEnergy(edge+1.5) BEFORE quickRaster because the energy must be "
                "set above the L3-edge to excite fluorescence.\n"
                "5. Multi-step commands (A하고 B해줘): generate ALL actions in sequence."
            )
            api_msgs[0]["content"] = api_msgs[0]["content"] + _gemma_suffix

        headers = {"Content-Type": "application/json"}

        # Fit the request inside the served context window. The base prompt is
        # already ~14.5k tokens, so accumulated conversation history + max_tokens
        # can overflow a small window (e.g. 16384) -> vLLM 400 "maximum context
        # length". Use vLLM's /tokenize for the EXACT input count (char estimates
        # mis-judge Korean-heavy prompts), drop oldest history until the output
        # floor fits, then cap max_tokens to the remaining budget.
        max_len = await self._get_max_len()
        _FLOOR = 512    # keep room for a complete JSON response
        _MARGIN = 96    # generation-prompt / grammar slack

        async def _count(msgs):
            try:
                r = await self._client.post(
                    f"{self.url}/tokenize",
                    json={"model": self.model, "messages": msgs}, timeout=15.0)
                if r.status_code == 200:
                    d = r.json()
                    return int(d.get("count") or len(d.get("tokens") or []))
            except Exception:
                pass
            # Fallback: conservative char estimate (~2.6 chars/token overcounts
            # tokens for this mixed EN/KO prompt, so we under-fill rather than 400).
            chars = sum(len(m.get("content") or "") for m in msgs)
            return int(chars / 2.6) + 8 * len(msgs) + 16

        inp = await _count(api_msgs)
        while inp + _FLOOR + _MARGIN > max_len and len(api_msgs) > 2:
            del api_msgs[1]   # drop oldest history turn (keep system + last user)
            inp = await _count(api_msgs)
        budget = max_len - inp - _MARGIN
        if budget < body["max_tokens"]:
            body["max_tokens"] = max(64, budget)

        async def _post():
            return await self._client.post(
                f"{self.url}/chat/completions", json=body, headers=headers)

        resp = await _post()
        # Reactive safety net (in case /tokenize and the chat path differ): on a
        # context-400, halve max_tokens, then drop oldest history, then drop the
        # json_object constraint -- guaranteed to converge.
        for _attempt in range(4):
            if resp.status_code != 400:
                break
            if re.search(r"maximum context length", resp.text):
                if body["max_tokens"] > 128:
                    body["max_tokens"] //= 2
                    log.warning("vLLM 400 (context): halve max_tokens=%d", body["max_tokens"])
                elif len(api_msgs) > 2:
                    del api_msgs[1]
                    log.warning("vLLM 400 (context): dropped oldest history turn")
                else:
                    body.pop("response_format", None)
            else:
                log.warning("vLLM 400 error -- retrying without response_format")
                body.pop("response_format", None)
            resp = await _post()

        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        # Truncation telemetry (D3, 2026-06-11): a 'length' finish means the
        # reply hit max_tokens (output budget exhausted by an oversized
        # prompt) — the JSON is almost certainly incomplete and will parse
        # as empty actions downstream. Log loudly so prompt-size regressions
        # are visible in server.log instead of silently degrading accuracy.
        if choice.get("finish_reason") == "length":
            log.warning(
                "vLLM response TRUNCATED at max_tokens=%s (prompt too large; "
                "see dynamic-prompt budget). JSON likely incomplete.",
                body.get("max_tokens"))
        return choice["message"]["content"]


# ══════════════════════════════════════════════════════════════════════
# NLP Agent — routes to selected backend
# ══════════════════════════════════════════════════════════════════════
BACKEND_MAP = {
    "ollama":   OllamaBackend,
    "gemini":   GeminiBackend,
    "groq":     GroqBackend,
    "claude":   ClaudeBackend,
    "vllm":     VLLMBackend,
    "deepseek": _make_deepseek,
    "openai":   _make_openai,
    "mistral":  _make_mistral,
    "solar":    _make_solar,
    "custom":   _make_custom,
}


class NLPAgent:
    """Multi-backend NLP agent for beamline control."""

    def __init__(self, rag_engine=None):
        engine = os.environ.get("NLP_ENGINE", "ollama").lower().strip()

        if engine not in BACKEND_MAP:
            raise ValueError(
                f"Unknown NLP_ENGINE='{engine}'. "
                f"Valid: {', '.join(BACKEND_MAP.keys())}"
            )

        self.backend = BACKEND_MAP[engine]()
        self.engine = engine
        self.conversation_history: List[Dict] = []
        self.max_history = 20
        self.rag_engine = rag_engine  # BeamlineRAG instance or None
        # D11: limit concurrent LLM requests
        self._semaphore = asyncio.Semaphore(3)

        log.info(f"NLP Agent initialized (engine: {engine}, "
                 f"rag={'enabled' if rag_engine else 'disabled'})")

    async def process(self, text: str, context: Dict[str, Any] = None,
                      language: str = "ko") -> Dict[str, Any]:
        """Process user text and return structured action response.

        Pipeline: Layer 1 (pre-process) -> LLM -> Layer 3 (post-process)
                  -> Layer 4 (retry if empty)

        Parameters
        ----------
        language : str
            Response language code (en, ko, ja, zh). Affects explanation language.
        """

        # D11: limit concurrent LLM requests (max 3 simultaneous)
        async with self._semaphore:
            return await self._process_inner(text, context, language)

    async def _process_inner(self, text: str, context: Dict[str, Any] = None,
                             language: str = "ko") -> Dict[str, Any]:
        # ── Language auto-detection: override UI language with input text language ──
        detected_lang = _detect_language(text)
        if detected_lang != language:
            log.info("Language auto-detect: UI=%s, text=%s → using %s",
                     language, detected_lang, detected_lang)
            language = detected_lang

        # ── Layer 1: Pre-processing — analyze input, generate hints ──
        preproc = _preprocess_input(text)

        # Store raw user text (without context) in history
        self.conversation_history.append({
            "role": "user",
            "content": text
        })

        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

        # ── RAG branch: knowledge queries bypass command pipeline ──
        if self.rag_engine and _is_knowledge_query(preproc, text):
            log.info("RAG: routing to knowledge query path")
            try:
                chunks = self.rag_engine.retrieve(text, top_k=5)
                if chunks:
                    rag_result = await self.rag_engine.generate_answer(
                        text, chunks, self.backend, language=language
                    )
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": rag_result["answer"]
                    })
                    return {
                        "type": "rag_response",
                        "actions": [],
                        "explanation": rag_result["answer"],
                        "sources": rag_result["sources"],
                        "confirmation_required": False,
                    }
                else:
                    log.info("RAG: no chunks retrieved, falling back to command pipeline")
            except Exception as e:
                log.warning("RAG retrieval/generation failed: %s, "
                            "falling back to command pipeline", e)

        # Build messages for LLM — append context + Layer 1 hints
        send_msgs = self._build_messages(context, preproc)

        # ── Dynamic prompt: select relevant examples based on intent ──
        intents = preproc.get("intents", set())
        beamline_mode = (context or {}).get("mode", "virtual")
        dynamic_prompt = _build_dynamic_prompt(intents, language=language,
                                               mode=beamline_mode)

        try:
            result = await self._call_llm_and_parse(send_msgs, dynamic_prompt)

            # ── Layer 3: Post-processing — fix function names, validate ──
            _cur_e = context.get("energy", 0) or context.get("energy_keV", 0) if context else 0
            result = _postprocess_response(result, current_energy_keV=_cur_e,
                                           user_text=text)

            # ── Layer 5: Energy range validation — remove out-of-range actions ──
            result = _validate_energy_range(result)

            # ── Layer 6: Domain rule validation — signatures, motors, transitions ──
            result = _validate_domain_rules(result, context)

            # ── Layer 7: Sample prep gate — block scans without prep confirmation ──
            result = _validate_sample_prep(result, text,
                                           self.conversation_history,
                                           language=language,
                                           mode=beamline_mode)

            # ── Layer 4: Retry — if empty response, retry once with guidance ──
            if _is_empty_response(result):
                log.info("Layer 4: empty response detected, retrying with guidance")
                lang_name = {'ko': 'Korean', 'en': 'English', 'ja': 'Japanese', 'zh': 'Chinese'}.get(language, 'English')
                retry_hint = (
                    "[SYSTEM: Your previous response was empty. "
                    f"You MUST provide a non-empty {lang_name} explanation. "
                    "If you cannot execute the request, explain WHY "
                    "(energy out of range, missing parameters, etc.). "
                    "Never return an empty response.]"
                )
                # Add retry hint to messages
                retry_msgs = list(send_msgs)
                if retry_msgs:
                    last = retry_msgs[-1]
                    retry_msgs[-1] = {
                        "role": last["role"],
                        "content": last["content"] + "\n" + retry_hint
                    }
                result2 = await self._call_llm_and_parse(retry_msgs,
                                                        dynamic_prompt)
                result2 = _postprocess_response(result2)
                result2 = _validate_energy_range(result2)
                result2 = _validate_domain_rules(result2, context)
                result2 = _validate_sample_prep(result2, text,
                                                self.conversation_history,
                                                language=language,
                                                mode=beamline_mode)

                # Use retry result if it's better (non-empty)
                if not _is_empty_response(result2):
                    result = result2
                else:
                    # Both attempts empty — generate fallback explanation
                    result = self._generate_fallback(text, preproc)

            # ── Layer 4b: Action retry — understood but no actions ──
            # Catches MoE models that generate explanation but empty actions.
            elif _is_actionless_response(result):
                log.info("Layer 4b: explanation present but actions empty, "
                         "retrying with action-forcing prompt")
                action_hint = (
                    "[SYSTEM: Your previous response had a good explanation "
                    "but the actions array was EMPTY. "
                    "You MUST populate the 'actions' array with the correct "
                    "function calls. Use the functions listed in your instructions. "
                    "For example: {\"actions\":[{\"label\":\"...\",\"fn\":\"setTargetEnergy\","
                    "\"args\":[12]}], \"explanation\":\"...\", "
                    "\"confirmation_required\":true}. "
                    "Do NOT leave actions empty if the request is actionable.]"
                )
                retry_msgs = list(send_msgs)
                if retry_msgs:
                    last = retry_msgs[-1]
                    retry_msgs[-1] = {
                        "role": last["role"],
                        "content": last["content"] + "\n" + action_hint
                    }
                result2 = await self._call_llm_and_parse(retry_msgs,
                                                        dynamic_prompt)
                result2 = _postprocess_response(result2)
                result2 = _validate_energy_range(result2)
                result2 = _validate_domain_rules(result2, context)
                result2 = _validate_sample_prep(result2, text,
                                                self.conversation_history,
                                                language=language,
                                                mode=beamline_mode)

                if len(result2.get("actions", [])) > 0:
                    log.info("Layer 4b: retry produced %d actions",
                             len(result2["actions"]))
                    result = result2
                else:
                    log.warning("Layer 4b: retry still produced no actions")

            result["type"] = "nlp_response"
            return result

        except Exception as e:
            log.error(f"NLP backend error ({self.engine}): {e}")
            return {
                "type": "error",
                "message": f"NLP error ({self.engine}): {str(e)}"
            }

    def _build_messages(self, context: Dict, preproc: dict) -> List[Dict]:
        """Build LLM message list with context and Layer 1 hints."""
        send_msgs = []
        hints = preproc.get("hints", [])
        hint_str = "\n".join(hints) if hints else ""

        for i, m in enumerate(self.conversation_history):
            if i == len(self.conversation_history) - 1 and m["role"] == "user":
                parts = [m["content"]]
                # Append beamline state context
                if context:
                    ctx_parts = []
                    for k, v in context.items():
                        if isinstance(v, float):
                            ctx_parts.append(f"{k}={v:.3g}")
                        else:
                            ctx_parts.append(f"{k}={v}")
                    parts.append("[State: " + " | ".join(ctx_parts) + "]")
                # Append Layer 1 hints
                if hint_str:
                    parts.append(hint_str)
                send_msgs.append({"role": "user", "content": "\n".join(parts)})
            else:
                send_msgs.append(m)
        return send_msgs

    async def _call_llm_and_parse(self, send_msgs: List[Dict],
                                   system_prompt: str = None) -> dict:
        """Call LLM backend and parse JSON response."""
        assistant_text = await self.backend.chat(
            system_prompt or SYSTEM_PROMPT,
            send_msgs,
            1024
        )
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_text
        })
        return self._extract_json(assistant_text)

    @staticmethod
    def _generate_fallback(text: str, preproc: dict) -> dict:
        """Generate a helpful fallback response when LLM fails twice."""
        parts = []

        # Check for out-of-range elements
        oor = preproc.get("out_of_range", [])
        if oor:
            for item in oor:
                elem = item["element"]
                edge = item["edge"]
                energy = item["energy"]
                if item["reason"] == "below_min":
                    parts.append(
                        f"{elem} {edge}-edge ({energy:.3f} keV)는 "
                        f"빔라인 에너지 범위(5-25 keV) 아래입니다. "
                        f"이 빔라인에서는 측정할 수 없습니다."
                    )
                elif item["reason"] == "above_max":
                    # Check L3 alternative
                    edges = _EDGE_DB.get(elem, {})
                    l3 = edges.get("L3")
                    if l3:
                        parts.append(
                            f"{elem} {edge}-edge ({energy:.1f} keV)는 "
                            f"빔라인 최대 에너지(25 keV)를 초과합니다. "
                            f"대신 L3-edge ({l3:.3f} keV)를 사용하실 수 있습니다."
                        )
                    else:
                        parts.append(
                            f"{elem} {edge}-edge ({energy:.1f} keV)는 "
                            f"빔라인 에너지 범위를 초과합니다."
                        )

        if not parts:
            # Generic fallback
            elements = preproc.get("elements", [])
            if elements:
                elem_str = ", ".join(elements)
                parts.append(
                    f"요청을 처리하지 못했습니다. "
                    f"감지된 원소: {elem_str}. "
                    f"측정 기법(XAFS, XRF, XRD 등)과 "
                    f"구체적인 파라미터를 말씀해주세요."
                )
            else:
                parts.append(
                    "요청을 정확히 이해하지 못했습니다. "
                    "다음과 같이 구체적으로 말씀해주세요:\n"
                    "- 'Cu K-edge XAFS 측정해줘'\n"
                    "- '에너지를 12 keV로 설정해'\n"
                    "- '10x10 41포인트 Fe XRF 맵핑해줘'\n"
                    "- '전체 빔 정렬 시작'"
                )

        return {
            "actions": [],
            "explanation": "\n".join(parts),
            "confirmation_required": False,
        }

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response, handling surrounding text."""
        text = text.strip()

        # 1) Direct parse
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # 2) Find first { ... last } in text
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        # 3) Fallback — treat entire text as natural language explanation
        return {
            "actions": [],
            "explanation": text,
            "confirmation_required": False
        }

    def reset_history(self):
        """Clear conversation history."""
        self.conversation_history.clear()
