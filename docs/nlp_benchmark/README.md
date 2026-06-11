---
title: "NLP Benchmark Overview"
category: nlp_benchmark
status: current
updated: 2026-06-11
tags: [nlp, benchmark]
summary: "NLP 벤치마크 결과 요약 및 디렉토리 가이드 (논문 공식: 228 tests / 44 categories, 98.2%)"
---
# NLP Benchmark System

K4GSR Beamline NLP(Natural Language Processing) 벤치마크 시스템 문서 및 결과 저장소.

## 폴더 구조

```
docs/nlp_benchmark/
  README.md                       # 이 파일
  BENCHMARK_METHODOLOGY.md        # 벤치마크 평가 방법론 (카테고리, 기준, 메트릭)
  NLP_BENCHMARK_PLAN.md           # 벤치마크 전략 및 모델별 결과 요약
  COMPARISON.md                   # 모델 간 비교표 (Qwen3-8b/32b/235b 등)
  nlp_benchmark_228_snapshot.json # 논문 공식 228-케이스 벤치마크 스냅숏 (프롬프트 + 기대 액션)
  generate_review_table.py        # 결과 JSON -> REVIEW.md 변환 스크립트
  generate_review_survey.py       # REVIEW.md -> SURVEY.html 변환 스크립트
  results/                        # 벤치마크 결과 JSON + 실행 로그
  reviews/                        # REVIEW.md (상세표) + SURVEY.html (설문 페이지)
```

## 주요 결과

| 모델 | 엔진 | 테스트 수 | Pass Rate | 비고 |
|---|---|---|---|---|
| Qwen3-32B | vLLM (2xA6000) | 228 / 44 categories | 98.2% (224/228) | v2.1 prompt. 논문 공식 결과 (스냅숏: nlp_benchmark_228_snapshot.json) |
| Qwen3-32B | vLLM (2xA6000) | 228 | 96.9% (221/228) | 이력: v2.1 중간 실행 (50 vexp 포함) |
| Qwen3-32B | vLLM (2xA6000) | 178 | 97.8% (174/178) | 이력: v2.1 prompt |
| Qwen3-32B | Ollama | 67 | 98.1% | 이력: 초기 67개 테스트 |

다국어: 7개 추가 언어(중국어, 아랍어, 힌디어, 독일어, 프랑스어, 태국어, 스페인어) x 5개 = 35개 프롬프트를 별도 평가 (논문 Section 4 및 결과 JSON 참조).

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

## 최근 변경 (2026-06-11)

- 결과 표를 논문 공식 결과(98.2%, 224/228, 44 categories)로 갱신, 이전 실행은 이력으로 표기
- 논문 공식 228-케이스 스냅숏 파일(`nlp_benchmark_228_snapshot.json`) 명시
- 테스트 스위트 규모 갱신: 현재 413개 (핵심 378 + 다국어 35)

## 최근 변경 (2026-03-07)

- **showTransmission 함수 NLP 등록**: 시료 투과율 계산기 자연어 호출 지원
- 벤치마크 테스트 7건 추가 (trans_01~07), vLLM 기준 7/7 (100%) PASS
- 물리 계산 검증: JS mu/rho vs NIST xraydb 53/54 PASS
- 상세: `COMPARISON.md` 하단 "showTransmission Feature Addition" 섹션 참조

## 관련 파일 (server/)

| 파일 | 용도 |
|---|---|
| `server/test_nlp_benchmark.py` | 벤치마크 테스트 스위트 + 실행 엔진 (현재 413개 테스트 케이스: 핵심 378 + 다국어 35; 논문 공식 결과는 228-케이스 스냅숏 기준) |
| `server/nlp_agent.py` | NLP 에이전트 (멀티 백엔드: vLLM/Ollama/Groq/Claude 등) |
| `server/science_advisor.py` | 실험 계획/타이밍/기법 추천 모듈 |
