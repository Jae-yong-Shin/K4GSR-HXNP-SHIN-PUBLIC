---
title: "NLP Benchmark Plan"
category: nlp_benchmark
status: archived
updated: 2026-03-21
tags: [nlp, benchmark, plan]
summary: "v1.0 벤치마크 계획 (완료됨). 최종 결과: vLLM Qwen3-32B 97.8% (174/178). 현재 결과는 README.md 참조"
---
# NLP Benchmark & qwen3:235b Pass-Rate Improvement Plan

## 1. Current Status

### 1.1 Model Availability (Workstation: <VLLM_WORKSTATION_IP>)
| Model | Size | Status |
|-------|------|--------|
| qwen3:8b | 4.9 GB | Tested (56.1%) |
| qwen3:32b | 20 GB | Testing in progress |
| qwen3:235b-a22b | 142 GB | Installed, not tested yet |

### 1.2 qwen3:8b Results (Baseline)
- **Pass Rate**: 46/82 = **56.1%**
- **Total Time**: 997s (~12s/test)

#### Per-Category Breakdown
| Category | Pass/Total | Rate | Failed IDs |
|----------|-----------|------|------------|
| motor | 1/3 | 33% | motor_02, motor_03 |
| scan | 5/9 | 56% | scan_01, scan_03, scan_07, scan_09 |
| alignment | 2/4 | 50% | align_01, align_04 |
| multi | 0/1 | 0% | multi_01 |
| optimize | 5/7 | 71% | opt_04, opt_07 |
| attenmask | 1/4 | 25% | atten_01, mask_01, mask_02 |
| info | 1/3 | 33% | info_02, info_03 |
| param | 2/2 | 100% | - |
| scientist | 1/2 | 50% | sample_01 |
| battery | 0/5 | 0% | batt_01~05 |
| catalyst | 1/3 | 33% | cata_01, cata_02 |
| semiconductor | 2/2 | 100% | - |
| geology | 3/3 | 100% | - |
| environment | 2/2 | 100% | - |
| biology | 2/2 | 100% | - |
| materials | 2/3 | 67% | mat_02 |
| edgecase | 2/7 | 29% | edge_01,02,04,05,06 |
| operations | 3/3 | 100% | - |
| workflow | 1/2 | 50% | workflow_02 |
| heldout | 10/15 | 67% | held_05,07,10,13,14 |

### 1.3 Failure Pattern Analysis (8b: 36 failures)
| Pattern | Count | % | Description |
|---------|-------|---|-------------|
| Empty response | 14-17 | 39-47% | Model returns blank (no actions, no explanation) |
| Info->Action confusion | 5 | 14% | Question treated as execution command |
| Function name case | 4 | 11% | quickXAFS vs quickXafs |
| Wrong function | 4 | 11% | quickRelAlign vs quickAutoTune, etc. |
| Function hallucination | 3 | 8% | Inventing non-existent functions |
| Energy range miss | 1-2 | 3-6% | Not detecting out-of-range edges |
| Missing queueStart | 1 | 3% | |
| Motor ID format | 1 | 3% | "pitch" vs "m1_pitch" |

---

## 2. Root Cause: SYSTEM_PROMPT_COMPACT Bottleneck

### The Problem
In `nlp_agent.py` line 613:
```python
# Small local LLMs need compact prompt to avoid function hallucination
ollama_msgs[0]["content"] = SYSTEM_PROMPT_COMPACT
```
**ALL Ollama models**, including 235b (142GB), are forced to use `SYSTEM_PROMPT_COMPACT` (~160 lines).
The full `SYSTEM_PROMPT` (~340 lines) has:
- 28 detailed examples (vs 18+10 in compact)
- More edge energy data
- Richer technique descriptions
- More Korean aliases
- Explicit rule explanations (Rule 8: SCAN PARAMETER CONFIRMATION, Rule 9 detail)
- More optimize/signal examples

### Why This Matters for 235b
- 8b/32b: Compact prompt prevents hallucination but limits capability
- 235b: Has 22B active params (MoE), enough capacity for the full prompt
- The 235b model can handle richer context without hallucinating

---

## 3. Improvement Strategy

### Strategy 1: Model-Size-Aware Prompt Selection (HIGHEST IMPACT)

**Change**: In `OllamaBackend.chat()`, select prompt based on model size.

```python
# nlp_agent.py line 612-613, REPLACE:
# OLD:
#   ollama_msgs[0]["content"] = SYSTEM_PROMPT_COMPACT
# NEW:
_LARGE_MODELS = ("235b", "70b", "72b", "110b", "qwq")
if any(tag in self.model.lower() for tag in _LARGE_MODELS):
    pass  # keep full SYSTEM_PROMPT
else:
    ollama_msgs[0]["content"] = SYSTEM_PROMPT_COMPACT
```

**Expected Impact**: Addresses ~70% of failures (empty responses, wrong function selection, hallucination)

### Strategy 2: Thinking Mode Control for 235b

**Current**: `/no_think` appended for ALL qwen3 models (line 617-618)
**Problem**: 235b benefits from thinking mode for complex reasoning (multi-step, energy calcs)
**But**: Thinking mode + structured output can produce invalid JSON

**Options**:
- A) Keep `/no_think` for 235b (safe, structured output works)
- B) Enable thinking with post-processing to extract JSON
- C) Use `/think` only for complex queries (detected by keyword)

**Recommendation**: Start with Option A (keep `/no_think`), benchmark, then test Option B.
The structured output `format` parameter should enforce valid JSON even with thinking.

### Strategy 3: Temperature & Sampling Tuning for 235b

**Current**: temperature=0.1, top_p=0.9, repeat_penalty=1.05
**For 235b**: Lower temperature may not help since the model is already more capable.

**Recommendation**:
- temperature=0.15 (slightly higher for 235b's better capacity)
- num_predict=2048 (increase from 1024 — 235b can output longer, complex responses)
- Keep top_p=0.9

### Strategy 4: Enhanced SYSTEM_PROMPT for 235b (MEDIUM IMPACT)

Add targeted examples for the worst-performing categories:
1. **Battery (0/5)**: Add 2-3 battery domain examples
2. **Attenmask (1/4)**: Add explicit mask/attenuator call examples
3. **Edge cases (2/7)**: Strengthen out-of-range energy detection rules

**But**: The full SYSTEM_PROMPT already has these. Strategy 1 should solve most of this.

### Strategy 5: Context Window Optimization

235b-a22b supports up to 131K tokens. Currently `num_ctx` is not set (Ollama default: 2048 or 4096).
For longer system prompts, set explicit context:

```python
if any(tag in self.model.lower() for tag in _LARGE_MODELS):
    body["options"]["num_ctx"] = 16384  # plenty for system prompt + history
```

---

## 4. Implementation Plan

### Phase A: Baseline Benchmarks (Current)
1. [x] qwen3:8b baseline: 56.1% (997s)
2. [ ] qwen3:32b with COMPACT prompt: running...
3. [ ] qwen3:235b with COMPACT prompt: pending

### Phase B: Apply Strategy 1 (Model-Aware Prompt)
4. Modify `nlp_agent.py`: add model-size-aware prompt selection
5. Run 235b with FULL prompt benchmark
6. Compare: 235b-compact vs 235b-full

### Phase C: Fine-tune (if needed)
7. Adjust `num_ctx`, `num_predict`, temperature for 235b
8. Test thinking mode (Option B) for 235b
9. Add targeted few-shot examples for worst categories

### Phase D: Production Configuration
10. Update `.env.example` with recommended 235b settings
11. Update server documentation

---

## 5. Expected Results

| Model | Prompt | Expected Rate | Rationale |
|-------|--------|--------------|-----------|
| qwen3:8b | COMPACT | 56.1% | Baseline (measured) |
| qwen3:32b | COMPACT | ~70-75% | 4x params, better reasoning |
| qwen3:235b | COMPACT | ~75-80% | Large model limited by compact prompt |
| qwen3:235b | FULL | **~85-90%** | Full examples + large model capacity |
| qwen3:235b | FULL+tuned | **~90-95%** | Optimized params + targeted examples |

---

## 6. Benchmark Commands

```bash
# 32b benchmark (running)
cd K4GSR_HXNP_SHIN
source .venv/bin/activate
OLLAMA_MODEL=qwen3:32b python server/test_nlp_qwen3.py > /tmp/nlp_bench_32b.log 2>&1

# 235b benchmark (compact prompt - baseline)
OLLAMA_MODEL=qwen3:235b-a22b python server/test_nlp_qwen3.py > /tmp/nlp_bench_235b_compact.log 2>&1

# 235b benchmark (full prompt - after Strategy 1 applied)
OLLAMA_MODEL=qwen3:235b-a22b python server/test_nlp_qwen3.py > /tmp/nlp_bench_235b_full.log 2>&1
```
