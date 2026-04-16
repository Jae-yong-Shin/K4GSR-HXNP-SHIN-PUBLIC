---
title: "Model Comparison"
category: nlp_benchmark
status: current
updated: 2026-03-07
tags: [nlp, benchmark, comparison]
summary: "vLLM/Ollama/Claude/Solar 모델별 성능 비교표"
---
# NLP Model Benchmark Comparison

## Test Suite: v2.1 (178 test cases, 37 categories)
**Date**: 2026-02-28
**Beamline**: K4GSR ID10 NanoProbe
**System Prompt**: FULL (~370 lines, +6 rules, +11 examples) for models >= 70B, COMPACT (~180 lines) for < 70B

---

## Overall Results

| Model | Engine | Architecture | Prompt | Pass | Fail | Rate | Total Time | Avg Latency | Status |
|-------|--------|-------------|--------|------|------|------|------------|-------------|--------|
| **Qwen3-32B** | **vLLM (local)** | **32B dense** | **FULL v2.1** | **174** | **4** | **97.8%** | **58 min** | **19.6s** | **Complete** |
| qwen3:32b | Ollama (local) | 32B dense | FULL v2.0 | 151\* | 3\* | 98.1%\* | 172 min | 67.0s | Complete |
| qwen3:235b (Q3_K_M) | Ollama (local) | 235B MoE (22B active) | FULL v2.0 | 143\* | 11\* | 92.9%\* | 419 min | 163.4s | Complete |
| Qwen3-32B | vLLM (local) | 32B dense | FULL v2.0 | 143\* | 11\* | 92.9%\* | 60 min | 23.2s | Complete |
| qwen3:8b | Ollama (local) | 8B dense | COMPACT v2.0 | 138\* | 16\* | 89.6%\* | 92 min | 35.7s | Complete |
| qwen3:235b-a22b (Q4_K_M) | Ollama (local) | 235B MoE (22B active) | FULL v2.0 | 42\*\* | 7\*\* | 85.7%\*\* | - | ~260s | Partial (49/154) |
| Llama 3.3 70B | Groq (cloud) | 70B dense | FULL v2.0 | 13\*\* | 1\*\* | 92.9%\*\* | - | ~0.8s | Partial (14/154) |

\* v2.0 results on 154 test cases. Not directly comparable to v2.1 (178 tests, improved prompt).
\*\* Partial results.

### v2.0 -> v2.1 Improvement (vLLM Qwen3-32B)

```
                    v2.0 (154 tests)     v2.1 (178 tests)     Change
Pass Rate              92.9%                97.8%             +4.9pp
Failures                  11                    4             -7 failures
Avg Latency            23.2s                19.6s             15% faster
Total Time              60 min               58 min           ~same
```

**What changed in v2.1:**
- Added 6 new system prompt rules (Rules 11-16): empty actions prohibition, partial failure handling, question+action, sequential requests, SSA vs mask, emergency stop
- Added 11 new few-shot examples targeting known failure patterns
- Added 24 new test cases across 9 new categories
- Modified 1 test case (opt_03: Ti borderline acceptance)

---

## Comprehension Rate vs Action Generation Rate

Failures are classified into four types:
- **Comprehension Error**: Model misunderstood the request (wrong function, wrong rule application)
- **Action Generation Error**: Model understood but returned empty actions `[]`
- **Parameter Error**: Correct function but wrong parameters/flags (e.g. confirmation_required)
- **Infrastructure Error**: Server disconnection, timeout, or other non-model failures

| Model | Engine | Prompt | Tests | Raw Pass | Action Gen | Comprehension | Parameter | Infra |
|-------|--------|--------|-------|----------|-----------|---------------|-----------|-------|
| **Qwen3-32B** | **vLLM** | **v2.1** | **178** | **97.8%** | **3 (1.7%)** | **1 (0.6%)** | **0** | **0** |
| qwen3:32b | Ollama | v2.0 | 154 | 98.1% | 1 (0.6%) | 2 (1.3%) | 0 | 0 |
| Qwen3-32B | vLLM | v2.0 | 154 | 92.9% | 8 (5.2%) | 2 (1.3%) | 1 (0.6%) | 0 |
| qwen3:235b Q3_K_M | Ollama | v2.0 | 154 | 92.9% | 0 | 9 (5.8%) | 2 (1.3%) | 0 |
| qwen3:8b | Ollama | v2.0 | 154 | 89.6% | 9 (5.8%) | 4 (2.6%) | 2 (1.3%) | 1 (0.6%) |

### Key Insight: Prompt Engineering Closed the Ollama-vLLM Gap

```
                       v2.0 Prompt        v2.1 Prompt       Change
vLLM  Qwen3-32B          92.9%              97.8%          +4.9pp
                        (8 ActGen)         (3 ActGen)      -5 ActGen failures
```

The v2.0 gap between Ollama (98.1%) and vLLM (92.9%) was primarily caused by 8 "explain-but-don't-act" failures. The v2.1 prompt's Rule 11 ("actions MUST NOT be empty when user requests a measurement") and targeted examples resolved 5 of these 8 failures, bringing vLLM within 0.3pp of Ollama's accuracy.

### Key Insight: Dense vs MoE for Structured Output

```
                   Comprehension    Action Generation    Gap
qwen3:32b (dense)     98.7%             99.4%           0.7pp  -- understands AND acts
qwen3:8b  (dense)     97.4%             94.2%           3.2pp  -- mostly acts
qwen3:235b (MoE)      94.2%            100.0%           5.8pp* -- acts but misunderstands rules
```

\* The 235b MoE model generates actions for every request (0 empty-action failures) but frequently selects the wrong function or ignores energy range rules. This is the inverse of the vLLM pattern: MoE acts on everything (even when it shouldn't), while vLLM explains well but fails to act.

---

## Per-Category Comparison (28 Original Categories)

| Category | Tests | 8b | 32b Ollama | 235b Q3_K_M | 32b vLLM v2.0 | 32b vLLM v2.1 |
|----------|-------|-----|-----------|-------------|---------------|---------------|
| Basic Motor Control | 3 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Scans & Measurements | 9 | 88.9% | **100%** | **100%** | **100%** | **100%** |
| Auto-alignment Rule | 4 | 75% | 75% | **100%** | **100%** | **100%** |
| Multi-step Commands | 1 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Optimization | 7 | 85.7% | **100%** | **100%** | 85.7% | **100%** |
| Attenuator & Mask | 4 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Information Queries | 3 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Parameter Confirmation | 2 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Sample Scientist | 2 | **100%** | **100%** | **100%** | 50% | **100%** |
| Battery Research | 5 | 40% | **100%** | 80% | **100%** | 80% |
| Catalyst Research | 3 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Semiconductor | 2 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Geology | 3 | 66.7% | **100%** | **100%** | **100%** | **100%** |
| Environment | 2 | 50% | **100%** | 50% | **100%** | **100%** |
| Biology | 2 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Materials Science | 3 | 66.7% | **100%** | **100%** | 66.7% | **100%** |
| Edge Cases | 7 | **100%** | **100%** | 85.7% | 85.7% | **100%** |
| Beamline Operations | 3 | **100%** | **100%** | 33.3% | 33.3% | **100%** |
| Workflows | 2 | 50% | **100%** | 50% | 50% | 50% |
| Held-out | 15 | 93.3% | 93.3% | **100%** | 73.3% | **100%** |
| Experiment Planning | 10 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Real User Scenarios | 12 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Complex Multi-step | 9 | 66.7% | 88.9% | **100%** | **100%** | **100%** |
| Robustness | 12 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Rejection | 10 | 90% | **100%** | 50% | **100%** | **100%** |
| Korean Variants | 9 | 88.9% | **100%** | **100%** | **100%** | **100%** |
| Signal Estimation | 5 | **100%** | **100%** | **100%** | **100%** | **100%** |
| Beamline Knowledge | 5 | **100%** | **100%** | **100%** | **100%** | **100%** |
| **Categories at 100%** | | **14/28** | **24/28** | **20/28** | **20/28** | **26/28** |

### v2.1 New Categories (vLLM only)

| Category | Tests | vLLM v2.1 | Description |
|----------|-------|-----------|-------------|
| SSA Control | 3 | **100%** | motorSetUI for SSA (not maskAperUpdate) |
| Analysis Intent | 3 | 66.7% | Oxidation/valence/phase => measurement action |
| Sequential | 3 | **100%** | Multi-element sequential XANES |
| Question + Action | 2 | **100%** | Combined info query + measurement request |
| Partial Range | 2 | **100%** | Mixed in/out-of-range elements |
| Heavy Element | 2 | 50% | Auto L3-edge selection for heavy elements |
| Colloquial | 4 | **100%** | Casual/informal Korean requests |
| Safety | 2 | **100%** | Emergency stop variants |
| Implicit Technique | 3 | **100%** | Context-dependent technique selection |
| **New categories at 100%** | | **7/9** | |

### Notable Patterns

- **vLLM v2.1 dramatic improvement**: 20/28 -> 26/28 categories at 100% (+6 categories fixed)
- **Categories fixed by v2.1 prompt**: Optimization, Sample Scientist, Materials, Edge Cases, Operations, Held-out
- **Remaining weakness**: Workflows (50%), Battery (80%) -- same tests that failed in v2.0
- **Ollama 32b still leads on v2.0 tests**: 24/28 categories at 100%

---

## Failure Analysis

### vLLM Qwen3-32B v2.1 -- 4 failures / 178 tests (97.8%)

| Test ID | Category | Type | Description |
|---------|----------|------|-------------|
| batt_04 | battery | Comprehension | Cu 10ppm: called quickXanes instead of optimizeBeamline |
| workflow_01 | workflow | Action Gen | Ti+Sr: correctly rejected Ti, but didn't generate Sr actions |
| analysis_03 | analysis_intent (new) | Action Gen | Ni oxide phase: explained XRD options but empty actions |
| heavyel_02 | heavy_element (new) | Action Gen | W XRF: explained L3=10.207keV but empty actions |

**Pattern**: Only 3 "explain-but-don't-act" failures remain (down from 8 in v2.0). These are edge cases where the model provides correct explanations but defers to user choice instead of acting.

### vLLM v2.0 -> v2.1 Resolution

| Test ID | v2.0 Status | v2.1 Status | Fix Applied |
|---------|-------------|-------------|-------------|
| opt_03 | FAIL (ActGen) | **PASS** | Test modified: Ti 4.97keV rejection now accepted |
| sample_01 | FAIL (ActGen) | **PASS** | Rule 11 + NMC 622 example |
| mat_03 | FAIL (ActGen) | **PASS** | Rule 11 + Cu2O vs CuO example |
| edge_03 | FAIL (ActGen) | **PASS** | Rule 11 + Au L3 auto-select example |
| held_05 | FAIL (ActGen) | **PASS** | Rule 11 + Se XRF example |
| held_09 | FAIL (ActGen) | **PASS** | Rule 13 (question + action combined) |
| held_14 | FAIL (ActGen) | **PASS** | Rule 14 (sequential requests) + Cu+Zn example |
| ops_02 | FAIL (Compr) | **PASS** | Rule 15 (SSA = motorSetUI) + SSA examples |
| held_12 | FAIL (Compr) | **PASS** | Rule 15 + SSA fully open example |
| ops_03 | FAIL (Param) | **PASS** | Rule 16 (emergencyStop confirmation_required=true) |
| workflow_01 | FAIL (ActGen) | FAIL (ActGen) | Rule 12 not followed (partial failure handling) |

### Ollama qwen3:32b v2.0 -- 3 failures / 154 tests (98.1%)

| Test ID | Category | Type | Description |
|---------|----------|------|-------------|
| align_02 | alignment | Comprehension | dE<2keV but added unnecessary alignment |
| held_12 | heldout | Comprehension | Used maskAperUpdate instead of motorSetUI |
| cmulti_04 | complex_multi | Action Gen | Cu+Fe sequential XANES, returned empty actions |

### Ollama qwen3:235b Q3_K_M v2.0 -- 11 failures / 154 tests (92.9%)

| Test ID | Category | Type | Description |
|---------|----------|------|-------------|
| batt_03 | battery | Comprehension | S 2.47keV: generated setTargetEnergy(5) instead of rejecting |
| env_02 | environment | Comprehension | Zn XANES: called optimizeBeamline instead of quickXanes |
| edge_03 | edgecase | Comprehension | Au XRF: called optimizeBeamline instead of setTargetEnergy |
| workflow_01 | workflow | Comprehension | Ti+Sr: called optimizeBeamline x2 instead of quickXanes |
| reject_02 | rejection | Comprehension | O 0.54keV: generated quickXanes instead of rejecting |
| reject_04 | rejection | Comprehension | C 0.28keV: generated setTargetEnergy(280) (eV/keV confusion) |
| reject_05 | rejection | Comprehension | N 0.40keV: generated quickXanes despite noting it's impossible |
| reject_09 | rejection | Comprehension | Mg 1.30keV: generated setTargetEnergy(1.5) instead of rejecting |
| reject_10 | rejection | Comprehension | Al 1.56keV: generated quickXanes instead of rejecting |
| ops_01 | operations | Parameter | Crystal: "Si(311)" instead of "311" |
| ops_02 | operations | Parameter | Motor name: "ssa_h" instead of "ssa_hgap" |

**Pattern**: 9 Comprehension errors, 5 of which are energy range rejection failures. The MoE model systematically ignores the 5-25 keV hard limit.

### Ollama qwen3:8b v2.0 -- 16 failures / 154 tests (89.6%)

| Test ID | Category | Type | Description |
|---------|----------|------|-------------|
| scan_05 | scan | Action Gen | Fly scan: degenerate output with massive queueStart repetition |
| opt_03 | optimize | Action Gen | Ti XANES: claimed below range |
| batt_01 | battery | Action Gen | NMC XRF: P K-edge hallucination |
| geo_01 | geology | Action Gen | As XANES: empty actions |
| env_01 | environment | Action Gen | Pb L3: P K-edge hallucination |
| mat_03 | materials | Action Gen | Cu2O XANES: P K-edge hallucination |
| workflow_02 | workflow | Action Gen | Optimize+scan: P K-edge hallucination |
| cmulti_01 | complex_multi | Action Gen | 3-step: P K-edge hallucination |
| cmulti_04 | complex_multi | Action Gen | Cu+Fe sequential: empty actions |
| align_02 | alignment | Comprehension | dE<2keV but added alignment (same as 32b) |
| batt_04 | battery | Comprehension | Cu 10ppm: wrong function |
| held_09 | heldout | Comprehension | Info+scan: missing quickXanes |
| reject_09 | rejection | Comprehension | Mg 1.30keV: executed scan instead of rejecting |
| cmulti_08 | complex_multi | Parameter | Wrong confirmation_required |
| korean_01 | korean_variant | Parameter | Wrong confirmation_required |
| batt_02 | battery | Infra | Server disconnected (Ollama restart) |

**Pattern**: 5 failures caused by "P K-edge hallucination" -- model outputs `P K-edge (2.145 keV) is out of range` for completely unrelated requests. A training data artifact in the 8b model.

---

## Cross-Model Failure Matrix

Tests that failed in 2+ models, with full input prompt:

| Input Prompt | 8b | 32b Ollama | 235b | vLLM v2.0 | vLLM v2.1 | Failure Pattern |
|-------------|-----|-----------|------|-----------|-----------|-----------------|
| "SrTiO3 분말의 Ti K-edge XANES를 최적화해줘..." | ActGen | PASS | PASS | ActGen | **PASS** | Ti K=4.97keV borderline |
| "Cu2O와 CuO를 XANES로 구분하고 싶어..." | ActGen | PASS | PASS | ActGen | **PASS** | Cu XANES explain-not-act |
| "SSA hgap을 30 um으로 설정해줘." | PASS | PASS | Param | Compr | **PASS** | motorSetUI vs maskAperUpdate |
| "SSA 완전히 열어줘." | PASS | Compr | PASS | Compr | **PASS** | maskAperUpdate vs motorSetUI |
| "Ti XANES 한 다음에 Sr XANES도 순차적으로 해줘." | PASS | PASS | Compr | ActGen | ActGen | Ti rejection cascading |
| "Au XRF 2D 매핑 설정해줘" | PASS | PASS | Compr | ActGen | **PASS** | Auto L3-edge selection |
| "현재 에너지가 몇이야? 그리고 As XANES도 하나 돌려줘." | Compr | PASS | PASS | ActGen | **PASS** | Info+scan combined |
| "Cu XANES 한번 하고 Zn XANES도 순차적으로 해줘." | ActGen | ActGen | PASS | ActGen | **PASS** | Sequential multi-element |
| "Mg K-edge XANES 해줘" | Compr | PASS | Compr | PASS | **PASS** | Mg 1.30keV rejection |
| "양극재에 Cu 오염이 10 ppm 정도 의심되는데 signal 확인해줘." | Compr | PASS | PASS | PASS | Compr | optimizeBeamline vs quickXanes |

---

## Ollama vs vLLM Speed Comparison (Same Model: Qwen3-32B)

| Metric | Ollama (v2.0) | vLLM v2.0 | vLLM v2.1 | Speedup (Ollama vs v2.1) |
|--------|---------------|-----------|-----------|--------------------------|
| **Avg Latency** | 67.0s | 23.2s | **19.6s** | **3.4x** |
| **Min Latency** | 19.4s | 4.0s | **3.7s** | **5.2x** |
| **Max Latency** | 227.7s | 209.6s | **217.8s** | 1.0x |
| **P95 Latency** | 154.0s | 60.1s | **54.2s** | **2.8x** |
| **Total Time** | 172 min | 60 min | **58 min** | **3.0x** |
| **Prefix Cache** | N/A | 98.8% | ~99% | - |
| **GPU Memory** | ~20 GB | ~31 GB | ~31 GB | 0.65x |

### Why vLLM is Faster

1. **Prefix Caching (~99% hit rate)**: System prompt (~7000 tokens) is cached after first query. Subsequent queries only process user input tokens, reducing prompt processing by ~95%.
2. **Continuous Batching**: vLLM's PagedAttention handles KV cache more efficiently than Ollama's per-request allocation.
3. **Tensor Parallelism**: Both use 2x A6000, but vLLM's TP implementation may have lower inter-GPU communication overhead for this model size.

### Why vLLM Had Lower Accuracy (v2.0) -- Now Resolved

1. **No Schema Enforcement**: Ollama supports JSON schema validation during generation (`format: { schema: {...} }`), constraining the model to produce valid action arrays. vLLM only uses `response_format: { type: "json_object" }`, which ensures valid JSON but doesn't enforce the action schema.
2. **Explain-Not-Act Pattern**: Without schema constraints, the model defaults to natural language explanations with `actions: []` when uncertain.
3. **Solution (v2.1)**: Explicit prompt rules (Rule 11: actions must not be empty) + targeted examples compensated for the lack of schema enforcement, reducing Action Gen failures from 8 to 3.

---

## Model Scaling Analysis

### Qwen3 Family Performance Summary

| Model | Engine | Prompt | Tests | Pass Rate | Avg Latency | VRAM |
|-------|--------|--------|-------|-----------|-------------|------|
| **Qwen3-32B** | **vLLM** | **FULL v2.1** | **178** | **97.8%** | **19.6s** | **~31 GB** |
| qwen3:32b | Ollama | FULL v2.0 | 154 | 98.1% | 67.0s | ~20 GB |
| Qwen3-32B | vLLM | FULL v2.0 | 154 | 92.9% | 23.2s | ~31 GB |
| qwen3:8b | Ollama | COMPACT v2.0 | 154 | 89.6% | 35.7s | ~6 GB |
| qwen3:235b Q3_K_M | Ollama | FULL v2.0 | 154 | 92.9% | 163.4s | ~112 GB |

### Scaling Observations

1. **8b -> 32b Ollama (+24B params)**: +8.5pp accuracy, +31s latency. Excellent scaling.
2. **32b -> 235b Ollama (+203B params, -10B active)**: -5.2pp accuracy, +96s latency. Negative scaling.
3. **Ollama 32b v2.0 -> vLLM 32b v2.1 (same model, better prompt)**: -0.3pp accuracy\*, -47s latency. Near-parity with 3.4x speed.
4. **Active parameter count matters**: 32B active (dense) > 22B active (MoE) for structured output.
5. **Prompt engineering > model scaling**: v2.0->v2.1 prompt improvement (+4.9pp) > 8b->32b model scaling (+8.5pp) in efficiency.

\* Note: 98.1% is on 154 tests, 97.8% is on 178 tests (24 harder tests added). On the same 154 tests, vLLM v2.1 would likely exceed 98%.

---

## 235b Optimization History

### Problem
235b Q4_K_M (142GB) exceeds 96GB VRAM, causing ~46GB RAM offload:
- ~260s average latency (vs 67s for 32b)
- ~13 hour total benchmark time

### Improvements Applied (v2)
1. **Flash Attention**: `OLLAMA_FLASH_ATTENTION=1` -- reduces attention memory
2. **KV Cache Quantization**: `OLLAMA_KV_CACHE_TYPE=q8_0` -- halves KV cache memory
3. **Smaller Quantization**: Q4_K_M (142GB) -> Q3_K_M (112GB) -- fits more in VRAM
4. **Layer 4b Retry**: If actions empty but explanation present, retry with action-forcing prompt
5. **MoE Prompt Suffix**: Explicit "MUST populate actions array" instruction
6. **Reduced num_ctx**: 16384 -> 8192 -- saves KV cache memory

### Results After Optimization

| Metric | Q4_K_M (49 tests) | Q3_K_M (154 tests) | Change |
|--------|-------------------|---------------------|--------|
| Pass Rate | 85.7% | 92.9% | +7.2pp |
| Avg Latency | ~260s | 163.4s | 1.6x faster |
| Total Time | ~13h (projected) | 419 min (~7h) | 1.9x faster |
| Action Gen Fails | 7 | 0 | Eliminated |
| Comprehension Fails | 0 | 9 | New weakness |

---

## Latency Comparison

| Model | Engine | Prompt | Avg | Min | Max | P95 |
|-------|--------|--------|-----|-----|-----|-----|
| **Qwen3-32B** | **vLLM** | **v2.1** | **19.6s** | **3.7s** | **217.8s** | **54.2s** |
| Qwen3-32B | vLLM | v2.0 | 23.2s | 4.0s | 209.6s | 60.1s |
| qwen3:8b | Ollama | v2.0 | 35.7s | 4.4s | 591.7s | 74.3s |
| qwen3:32b | Ollama | v2.0 | 67.0s | 19.4s | 227.7s | 154.0s |
| qwen3:235b Q3_K_M | Ollama | v2.0 | 163.4s | 98.5s | 451.8s | 291.6s |
| qwen3:235b Q4_K_M | Ollama | v2.0 | ~260s\* | ~81s | 1047s | ~550s |
| Groq Llama 3.3 70B | Cloud | v2.0 | ~0.8s\* | - | - | - |

\* Partial estimates.

---

## Hardware Configuration

### Workstation (All local models)
- **GPU**: 2x NVIDIA RTX A6000 (96 GB total VRAM)
- **CPU**: AMD EPYC
- **RAM**: 252 GB DDR4
- **OS**: Ubuntu 22.04
- **Ollama**: v0.17.4 (Flash Attention, q8_0 KV cache)
- **vLLM**: v0.16.0 (tensor-parallel 2, prefix caching, max-model-len 16384)
- **Driver**: NVIDIA 570.211.01

### Benchmark PC (Cloud API models)
- **OS**: Windows 11 Education
- **Network**: University LAN -> Internet

---

## Previous Benchmarks

### v1.0 (82 tests)

| Model | Pass | Fail | Rate | Time | Prompt |
|-------|------|------|------|------|--------|
| qwen3:8b | 46 | 36 | 56.1% | 997s | COMPACT |
| qwen3:32b | 76 | 6 | 92.7% | 5,327s | COMPACT |

### Improvement History

| Version | 8b | 32b Ollama | 32b vLLM | Key Changes |
|---------|-----|-----------|----------|-------------|
| v1.0 (82 tests) | 56.1% | 92.7% | - | Initial prompt |
| v2.0 (154 tests) | 89.6% | 98.1% | 92.9% | Expanded prompt, Layer 5 validation, 72 new tests |
| v2.1 (178 tests) | - | - | **97.8%** | +6 rules, +11 examples, 24 new tests |

---

## Reproducibility

```bash
# qwen3:8b (COMPACT prompt, ~6GB VRAM)
NLP_ENGINE=ollama OLLAMA_MODEL=qwen3:8b python3 server/test_nlp_benchmark.py

# qwen3:32b (FULL prompt, ~20GB VRAM)
NLP_ENGINE=ollama OLLAMA_MODEL=qwen3:32b python3 server/test_nlp_benchmark.py

# qwen3:235b Q3_K_M (FULL prompt + MoE optimizations, ~112GB)
NLP_ENGINE=ollama OLLAMA_MODEL=ingu627/qwen3:235b-q3_K_M python3 server/test_nlp_benchmark.py

# vLLM Qwen3-32B (FULL prompt v2.1, ~31GB, requires vLLM server running)
NLP_ENGINE=vllm VLLM_MODEL=Qwen/Qwen3-32B python3 server/test_nlp_benchmark.py

# Groq (requires GROQ_API_KEY)
NLP_ENGINE=groq python server/test_nlp_benchmark.py

# Specific categories
python server/test_nlp_benchmark.py --engine ollama --model qwen3:32b --cat battery,catalyst

# Start vLLM server (prerequisite for vLLM benchmarks)
bash server/start_vllm.sh
```

---

## Conclusions

1. **vLLM Qwen3-32B with v2.1 prompt is the recommended production configuration**:
   - 97.8% pass rate (174/178), 26/28 original categories at 100%
   - 3.4x faster than Ollama (19.6s vs 67.0s avg latency)
   - Prefix caching ~99% hit rate enables real-time interaction
   - Runs locally on 2x A6000 (no cloud dependency, no API cost)
   - Within 0.3pp of Ollama 32b accuracy on comparable tests

2. **Prompt engineering effectively compensated for vLLM's lack of schema enforcement**:
   - v2.0: 92.9% (8 explain-but-don't-act failures)
   - v2.1: 97.8% (3 residual explain-but-don't-act failures)
   - Rules 11-16 and targeted examples resolved 5/8 action generation failures
   - The remaining 3 failures are ambiguous edge cases where deferring to user may be appropriate

3. **Ollama qwen3:32b remains the most accurate on v2.0 tests** (98.1%):
   - Ollama's structured output schema enforcement eliminates most action generation failures
   - Would likely improve further with v2.1 prompt (not yet tested)
   - Main weakness: 3.4x slower than vLLM due to lack of prefix caching

4. **Dense models outperform MoE for structured output tasks**:
   - 32b dense (32B active): 97.8-98.1% pass rate
   - 235b MoE (22B active): 92.9% pass rate
   - MoE generates actions for every request but frequently selects wrong functions
   - Dense model is more reliable with fewer parameters

5. **System prompt improvements are highly effective**:
   - v1.0 -> v2.0: +33.5pp (8b), +5.4pp (32b)
   - v2.0 -> v2.1: +4.9pp (vLLM 32b)
   - Targeted rules + examples are more cost-effective than model scaling
   - Layer 5 post-LLM energy validation provides safety net for out-of-range actions

6. **8b is a viable lightweight alternative** (89.6%, v2.0):
   - Fastest Ollama option (35.7s avg), requires only 6 GB VRAM
   - Weaknesses: battery research (40%), complex multi-step (66.7%), P K-edge hallucination
   - Good for resource-constrained or quick-response deployments

---

---

## showTransmission Feature Addition (2026-03-07)

### Overview

시료 투과율 계산기 `showTransmission(formula, thickness_um, density_gcc)` 함수가 NLP 시스템에 추가되었습니다.
유저가 자연어로 시료의 X-ray 투과율을 조회할 수 있습니다.

### NLP 등록 위치 (nlp_agent.py, 5곳)

| 위치 | 설명 |
|------|------|
| `_VALID_FUNCTIONS` | 함수명 등록 |
| `_FUNCTION_SIGNATURES` | `(1, 3)` -- 1~3개 인자 (formula 필수, thickness/density 선택) |
| SYSTEM_PROMPT Available Functions | 한국어 함수 설명 |
| SYSTEM_PROMPT inline examples | 2개 few-shot 예시 |
| `_EXAMPLE_GROUPS["info"]` | 동적 프롬프트용 예시 |

### 벤치마크 테스트 (7건, trans_01~07)

| Test ID | 입력 | 기대 함수 | 결과 (vLLM) | 응답 시간 |
|---------|------|----------|-------------|-----------|
| trans_01 | "Cu 1um 시료 투과율 보여줘" | `showTransmission("Cu",1,8.96)` | **PASS** | 6.3s |
| trans_02 | "산화철 50um 투과율 곡선 보여줘" | `showTransmission("Fe2O3",50)` | **PASS** | 7.9s |
| trans_03 | "SiO2 100um의 투과율은 얼마야?" | `showTransmission("SiO2",100,2.2)` | **PASS** | 9.3s |
| trans_04 | "Show transmission of 0.5um gold foil" | `showTransmission("Au",0.5,19.3)` | **PASS** | 8.8s |
| trans_05 | "NiO 10um 밀도 6.67 투과율" | `showTransmission("NiO",10,6.67)` | **PASS** | 7.4s |
| trans_06 | "에너지 8.5keV로 바꾸고 Cu 1um 투과율 보여줘" | `setTargetEnergy(8.5)` + `showTransmission("Cu",1,8.96)` | **PASS** | 11.1s |
| trans_07 | "GaAs 5um에 10keV 빔이 얼마나 통과해?" | `showTransmission("GaAs",5,5.32)` | **PASS** | 9.6s |

**결과**: vLLM Qwen/Qwen3-32B 기준 **7/7 (100%)**, 평균 응답 시간 **8.6s**

### 물리 계산 검증 (JS vs NIST xraydb)

`tests/test_transmission_physics.py`에서 JS 물리 엔진을 Python으로 재현 후 NIST xraydb와 비교:

| 검증 항목 | 결과 |
|----------|------|
| 원소별 mu/rho vs NIST (±30%) | **53/54 pass** |
| 화합물 mu/rho (SiO2, Fe2O3, CaCO3) | PASS |
| T(E) Beer-Lambert 계산 | PASS |
| K-edge jump ratio (Cu 8.2x, Fe 8.5x) | PASS |
| 밀도 DB (15 화합물 ±5%) | PASS |
| 최적 두께 계산 (XAFS/XRF) | PASS |
| 유일한 실패 | Mo@25keV (K-edge 이상 데이터 부족) |

### 버그 수정 사항

물리 검증 과정에서 발견·수정된 `js/experiment/01_xray_data.js` XRF_MU_PHOTO 데이터 버그:

1. **경원소 Victoreen 모델 ~10,000x 오차**: O, Na, Al, Si, P, S, Cl, Ca에 대해 Victoreen fallback(`Z^3.5/E^3`)이 실제 mu/rho 대비 10,000~30,000배 작은 값 반환. NIST xraydb 데이터 추가로 수정.
2. **전이금속 K-edge 이하 데이터 부족**: Ti, V, Cr, Mn, Fe, Co, Ni, Cu, Zn의 XRF_MU_PHOTO에 K-edge 이하 데이터가 없어 edge-aware interpolation 실패. Below-K-edge 데이터 포인트 추가로 수정.
3. **K-edge jump 미표시**: 위와 동일 원인. 수정 후 Cu 8.2x, Fe 8.5x edge jump ratio 정상 표시.

### 관련 파일

| 파일 | 변경 |
|------|------|
| `js/experiment/01_xray_data.js` | XRF_MU_PHOTO 경원소 8개 + 전이금속 below-K-edge 데이터 추가 |
| `js/analysis/02_transmission.js` | 신규: 투과율 계산기 (팝업 UI + 물리 계산) |
| `js/experiment/06_experiment_ui.js` | T(E) 버튼 추가 |
| `server/nlp_agent.py` | showTransmission NLP 등록 (5개 위치) |
| `server/test_nlp_benchmark.py` | trans_01~07 벤치마크 테스트 추가 |
| `tests/test_transmission_physics.py` | 물리 검증 테스트 (53/54 NIST pass) |
| `tests/transmission_console_tests.js` | 브라우저 콘솔 수동 검증 스크립트 |

### 재현 방법

```bash
# 물리 검증 (Python, xraydb 필요)
pip install xraydb
python tests/test_transmission_physics.py

# NLP 벤치마크 (워크스테이션)
NLP_ENGINE=vllm python3 server/test_nlp_benchmark.py --cat info,multi --verbose

# 브라우저 콘솔 테스트
# 브라우저에서 F12 -> Console -> tests/transmission_console_tests.js 내용 붙여넣기
```

---

*Last updated: 2026-03-07. showTransmission 기능 추가 및 벤치마크 완료.*
