---
title: "NLP Benchmark Overview"
category: nlp_benchmark
status: current
updated: 2026-03-07
tags: [nlp, benchmark]
summary: "NLP 벤치마크 v2.1 결과 요약 및 디렉토리 가이드"
---
# NLP Benchmark System

K4GSR Beamline NLP(Natural Language Processing) 벤치마크 시스템 문서 및 결과 저장소.

## 폴더 구조

```
docs/nlp_benchmark/
  README.md                    # 이 파일
  BENCHMARK_METHODOLOGY.md     # 벤치마크 평가 방법론 (카테고리, 기준, 메트릭)
  NLP_BENCHMARK_PLAN.md        # 벤치마크 전략 및 모델별 결과 요약
  COMPARISON.md                # 모델 간 비교표 (Qwen3-8b/32b/235b, GPT-4o-mini 등)
  generate_review_table.py     # 결과 JSON -> REVIEW.md 변환 스크립트
  generate_review_survey.py    # REVIEW.md -> SURVEY.html 변환 스크립트
  results/                     # 벤치마크 결과 JSON + 실행 로그
  reviews/                     # REVIEW.md (상세표) + SURVEY.html (설문 페이지)
```

## 주요 결과

| 모델 | 엔진 | 테스트 수 | Pass Rate | 비고 |
|---|---|---|---|---|
| Qwen3-32B | vLLM (2xA6000) | 228 | 96.9% (221/228) | v2.1 prompt, 50 vexp 포함 |
| Qwen3-32B | vLLM (2xA6000) | 178 | 97.8% (174/178) | v2.1 prompt |
| Qwen3-32B | vLLM (2xA6000) | 11 (info+multi) | 90.9% (10/11) | showTransmission 7/7 PASS, multi_01 기존 실패 |
| Qwen3-32B | Ollama | 67 | 98.1% | 초기 67개 테스트 |

## 리뷰 워크플로우

1. 벤치마크 실행 (워크스테이션):
   ```bash
   python3 server/test_nlp_benchmark.py --engine vllm --model Qwen/Qwen3-32B
   ```

2. REVIEW.md 생성:
   ```bash
   python generate_review_table.py <결과.json>
   ```

3. SURVEY.html 생성 (동료 리뷰용):
   ```bash
   python generate_review_survey.py <결과_REVIEW.md>
   ```

4. SURVEY.html을 브라우저에서 열어 리뷰:
   - 키보드 단축키: `1`=OK, `2`=Wrong, `3`=Missing, `4`=Unnecessary, `Space`=OK&Next
   - 진행 상태는 localStorage에 자동 저장
   - 완료 후 JSON Export

## 최근 변경 (2026-03-07)

- **showTransmission 함수 NLP 등록**: 시료 투과율 계산기 자연어 호출 지원
- 벤치마크 테스트 7건 추가 (trans_01~07), vLLM 기준 7/7 (100%) PASS
- 물리 계산 검증: JS mu/rho vs NIST xraydb 53/54 PASS
- 상세: `COMPARISON.md` 하단 "showTransmission Feature Addition" 섹션 참조

## 관련 파일 (server/)

| 파일 | 용도 |
|---|---|
| `server/test_nlp_benchmark.py` | 벤치마크 테스트 스위트 (235개 테스트 케이스 + 실행 엔진) |
| `server/nlp_agent.py` | NLP 에이전트 (멀티 백엔드: vLLM/Ollama/Groq/Claude 등) |
| `server/science_advisor.py` | 실험 계획/타이밍/기법 추천 모듈 |
