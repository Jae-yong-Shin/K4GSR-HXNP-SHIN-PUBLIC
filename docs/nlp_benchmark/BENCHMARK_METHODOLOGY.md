---
title: "Benchmark Methodology"
category: nlp_benchmark
status: current
updated: 2026-03-03
tags: [nlp, benchmark, methodology]
summary: "v2.0/v2.1 벤치마크 방법론 (154->178 테스트, 28->37 카테고리)"
---
# NLP Benchmark Methodology & Validation Framework

## 1. Overview

This document describes the methodology used to evaluate NLP model performance
for the K4GSR nanoprobe beamline control system. The benchmark assesses whether
LLM-based natural language processing can reliably translate user requests
(Korean/English) into structured JSON action commands for beamline operation.

### 1.1 Motivation

The beamline control system accepts natural language input from sample scientists
who may not have X-ray expertise. The NLP module must:
- Correctly identify requested techniques (XAFS, XANES, XRF, XRD, Ptycho)
- Extract physical parameters (element, edge, energy, scan range)
- Generate valid function call sequences
- Request user confirmation for hardware-affecting operations
- Explain limitations when requests cannot be fulfilled

### 1.2 Test Suite Version
- **Version**: v2.0 (154 test cases, 28 categories)
- **Previous**: v1.0 (82 test cases, 20 categories)
- **Date**: 2026-02-28

---

## 2. Test Categories (28 total)

### 2.1 Core Functionality (82 tests, from v1.0)

| Category | Tests | Purpose |
|----------|-------|---------|
| motor | 3 | Basic motor control (energy, pitch, sample position) |
| scan | 9 | All scan types (XAFS, XANES, raster, line, fly, adaptive, Fermat, relative) |
| alignment | 4 | Auto-alignment rule (dE > 2 keV triggers realignment) |
| multi | 1 | Multi-step command chains |
| optimize | 7 | Beamline optimization and signal estimation |
| attenmask | 4 | Attenuator filter and mask aperture control |
| info | 3 | Information queries (no actions expected) |
| param | 2 | Parameter confirmation (partial scan requests) |
| scientist | 2 | Sample scientist scenarios |
| battery | 5 | Battery cathode research domain |
| catalyst | 3 | Catalyst/fuel cell research |
| semiconductor | 2 | Semiconductor analysis |
| geology | 3 | Geology/environmental geology |
| environment | 2 | Environmental science |
| biology | 2 | Biological sample analysis |
| materials | 3 | Materials science |
| edgecase | 7 | Out-of-range energies, heavy elements, edge cases |
| operations | 3 | Beamline operations (crystal change, SSA, emergency) |
| workflow | 2 | Multi-technique sequential workflows |
| heldout | 15 | Generalization tests (phrasings not in training data) |

### 2.2 Extended Categories (72 tests, new in v2.0)

| Category | Tests | Purpose |
|----------|-------|---------|
| experiment_plan | 10 | Experiment planning, time budgets, technique compatibility |
| real_user | 12 | Realistic informal Korean expressions, vague requests |
| complex_multi | 9 | Complex multi-step command chains |
| robustness | 12 | Typos, edge formatting, minimal input, out-of-range values |
| rejection | 10 | Requests that should be refused (out-of-range elements) |
| korean_variant | 9 | Various Korean expression styles (polite, casual, terse) |
| signal_est | 5 | Signal estimation and detection limit queries |
| bl_knowledge | 5 | Beamline specification queries |

---

## 3. Validation Criteria

### 3.1 PASS/FAIL Determination

A test case PASSES if **any** of the following conditions is met:

1. **Primary Check**: All specified criteria match:
   - `expect_fn`: Expected function names appear in correct order (case-insensitive subsequence match)
   - `expect_args_contains`: Expected argument values present in any action
   - `expect_args_check`: Custom lambda validator returns True
   - `expect_fn_exclude`: Excluded functions do NOT appear
   - `expect_fn_count`: Exact function call counts match
   - `expect_confirmation`: confirmation_required field matches expected value
   - `expect_no_actions`: No actions returned (for info/rejection queries)

2. **Alternative Pass** (`expect_alt_pass`): A relaxed lambda validator that
   accepts alternative valid responses. This is used when multiple response
   formats are acceptable. Example: For "Ti XANES", both `optimizeBeamline`
   and `quickXanes` are acceptable responses.

### 3.2 Why Relaxed Criteria?

Many test cases include `expect_alt_pass` because:
- Different models may choose different valid approaches (e.g., optimize first vs scan directly)
- Domain-specific requests can be interpreted at different abstraction levels
- The system should not penalize reasonable alternative interpretations

### 3.3 Case Insensitivity

Function name matching is case-insensitive. The post-processing layer (Layer 3)
performs fuzzy matching to correct case errors (e.g., `quickxafs` -> `quickXafs`).

---

## 4. Tested Models

### 4.1 Local Models (Ollama)

| Model | Parameters | Active Params | VRAM | Speed |
|-------|-----------|---------------|------|-------|
| qwen3:32b | 32B dense | 32B | 20 GB | ~50s/query |
| qwen3:235b-a22b | 235B MoE | 22B | 142 GB | ~90-120s/query |

### 4.2 Cloud API Models

| Engine | Model | Provider | Tier |
|--------|-------|----------|------|
| groq | llama-3.3-70b-versatile | Groq | Free |
| gemini | gemini-2.0-flash | Google | Free |
| claude | claude-sonnet-4-5 | Anthropic | Paid |
| deepseek | deepseek-chat | DeepSeek | Paid |
| openai | gpt-4o-mini | OpenAI | Paid |
| mistral | mistral-small-latest | Mistral | Paid |

---

## 5. Experimental Setup

### 5.1 Deterministic Output

- **Temperature**: 0.1 (Ollama), 0.3 (cloud APIs)
- **top_p**: 0.9
- **Structured output**: JSON schema enforced (Ollama `format` parameter,
  cloud `response_format: json_object`)
- **Single pass**: Each test case run once per model (no averaging across runs)

### 5.2 System Prompt

All models receive the same `SYSTEM_PROMPT` (full version, ~340 lines) with:
- 11 behavioral rules
- 40+ valid function definitions
- 28 few-shot examples
- K/L3 edge energy database
- Korean alias mappings

Exception: Ollama models with < 70B parameters use `SYSTEM_PROMPT_COMPACT`
(~166 lines) to prevent function hallucination from context overflow.

### 5.3 Pre/Post Processing

All models benefit from the 5-layer NLP defense pipeline:
1. **Layer 1 (Pre-processing)**: Element detection, energy range check, hint injection
2. **Layer 2 (LLM Prompt)**: System prompt rules + few-shot examples
3. **Layer 3 (Post-processing)**: Fuzzy function name matching, hallucination removal, auto queueStart
4. **Layer 4 (Retry)**: If empty response, retry once with guidance
5. **Layer 5 (Client fallback)**: Keyword-based contextual help in browser

Layers 1-4 are tested; Layer 5 (client-side) is not part of this benchmark.

### 5.4 Beamline Context

All tests use the same simulated beamline state:
```json
{"energy": 10, "ssaH": 50, "ssaV": 50}
```
This represents: 10 keV beam energy, 50 um SSA aperture (both axes).

---

## 6. Metrics

### 6.1 Primary Metric: Pass Rate

```
Pass Rate = (# PASS tests) / (# Total tests) x 100%
```

Reported as: overall rate + per-category breakdown.

### 6.2 Secondary Metrics

- **Latency**: avg, min, max, p95 response time per model
- **Category pass rate**: Per-category percentage
- **Failure pattern**: Classification of failure types:
  - Empty response (no actions, no explanation)
  - Wrong function (plausible but incorrect)
  - Function hallucination (non-existent function)
  - Missing queueStart
  - Incorrect confirmation_required
  - Argument errors

---

## 7. Statistical Considerations

### 7.1 Reproducibility

- Low temperature (0.1-0.3) provides near-deterministic output
- However, LLM inference is inherently stochastic; exact pass/fail
  for borderline cases may vary between runs
- Results should be interpreted with +/- 2-3% margin

### 7.2 Test Coverage

The 154 test cases cover:
- All 40+ valid function endpoints
- 28+ element types across K and L3 edges
- Korean/English/mixed language inputs
- 7 research domains (battery, catalyst, semiconductor, geology, biology, environment, materials)
- Edge cases (out-of-range, typos, vague requests, rejection scenarios)
- Held-out phrasings not present in training examples

### 7.3 Limitations

1. **Single beamline state**: All tests use E=10 keV context
2. **No conversation memory**: Each test is independent (history reset)
3. **No real hardware validation**: Tests verify JSON structure, not physics correctness
4. **Subjective categories**: "Experiment planning" tests have looser pass criteria
5. **Prompt engineering bias**: Test cases were designed with knowledge of the system prompt

---

## 8. Reproduction

### 8.1 Requirements

```bash
pip install httpx python-dotenv
# For specific backends:
pip install anthropic           # Claude
pip install google-generativeai # Gemini
```

### 8.2 Run Commands

```bash
# Single engine
python server/test_nlp_benchmark.py --engine groq

# Specific Ollama model
python server/test_nlp_benchmark.py --engine ollama --model qwen3:235b-a22b

# Category filter
python server/test_nlp_benchmark.py --cat battery,catalyst

# All configured engines
python server/test_nlp_benchmark.py --all-engines
```

### 8.3 Output

Results are saved to `server/benchmark_results/` as JSON with:
- Per-test pass/fail status, errors, response time
- Per-category aggregation
- Latency statistics
- Full response data for failed tests

---

## 9. Changelog

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-02-27 | Initial 82 tests, 20 categories |
| v2.0 | 2026-02-28 | Expanded to 154 tests, 28 categories. Added experiment planning, robustness, rejection, real-user scenarios. Multi-engine benchmark runner. |
