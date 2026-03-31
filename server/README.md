---
title: "Server README"
category: other
status: current
updated: 2026-03-03
tags: [server]
summary: "백엔드 서버 파일 목록 및 역할 설명"
---
# Server Directory Guide

K4GSR Beamline 서버 파일 용도 가이드.

## Core (운영 서버)

| 파일 | 용도 |
|---|---|
| `server.py` | 메인 WebSocket 서버 (port 8001, 4 endpoints: /ws/pv, /ws/chat, /ws/scan, /ws/expt) |
| `pv_store.py` | 인메모리 PV 시뮬레이션 (100+ 모터/BPM) |
| `ca_bridge.py` | 실제 EPICS IOC <-> WebSocket 브릿지 (caproto CA) |
| `nlp_agent.py` | 멀티 백엔드 NLP 에이전트 (vLLM/Ollama/Groq/Claude/Gemini/DeepSeek/OpenAI) |
| `science_advisor.py` | 실험 계획/타이밍 추정/기법 추천/검출기 호환성 분석 |
| `experiment_engine.py` | 서버사이드 가상 실험 (XAFS/XRD2D/XRF) 시뮬레이션 |
| `simulation_server.py` | 독립 물리 시뮬레이션 서버 (port 8002, xraylib/pymatgen/pyFAI/Larch) |

## NLP Training (학습 데이터 생성)

| 파일 | 용도 |
|---|---|
| `generate_training_data.py` | 기본 학습 데이터 생성 (102개 예제 -> JSONL) |
| `augment_training_data.py` | 학습 데이터 증강 (500+개, 원소x기법x형식 조합) |
| `training_data.jsonl` | 기본 학습 데이터 |
| `training_data_augmented.jsonl` | 증강된 학습 데이터 |
| `lora_finetune.py` | LoRA 파인튜닝 스크립트 (unsloth, 4-bit, Qwen3:8b) |
| `lora_colab_guide.md` | LoRA 파인튜닝 가이드 (로컬 GPU/Colab/vLLM) |

## NLP Testing (벤치마크)

| 파일 | 용도 |
|---|---|
| `test_nlp_benchmark.py` | 메인 벤치마크 스위트 (228개 테스트 + 44개 카테고리) |
| `test_nlp_qwen3.py` | Qwen3:8b 전용 테스트 (67개, 초기 버전) |

결과 및 리뷰 문서: `docs/nlp_benchmark/` 참조.

## E2E Testing

| 파일 | 용도 |
|---|---|
| `_test_e2e_scenarios.py` | E2E 파이프라인 테스트 (JS -> WS -> simulation_server -> 물리 엔진) |
| `_test_browser_e2e.py` | Playwright 브라우저 E2E 테스트 (번들 HTML 렌더링 검증) |

## Workstation Scripts (워크스테이션 운영)

| 파일 | 용도 |
|---|---|
| `setup_workstation.sh` | 워크스테이션 초기 설치 (Ollama, Qwen, Python, 파일 동기화) |
| `setup_remote_ollama.sh` | 원격 Ollama 서버 설치 (A6000, Qwen3/GLM 모델) |
| `start_beamline.sh` | Soft IOC + 메인 서버 원클릭 시작 |
| `stop_beamline.sh` | 빔라인 관련 프로세스 전체 종료 |
| `start_vllm.sh` | vLLM 서버 시작 (Qwen3-32B, 2xA6000 tensor parallel) |
| `run_vllm_benchmark.sh` | vLLM 벤치마크 자동화 (VRAM 정리 -> vLLM 시작 -> 벤치마크) |

## Temporary / 삭제 가능

| 파일 | 용도 | 상태 |
|---|---|---|
| `nlp_test_output.txt` | 이전 NLP 테스트 로그 | 삭제 가능 |
| `nlp_test_results.json` | 이전 NLP 테스트 결과 | 삭제 가능 |
| `NLP_BENCHMARK_PLAN.md` | 벤치마크 전략 문서 | `docs/nlp_benchmark/`로 이동 완료 |
| `BENCHMARK_METHODOLOGY.md` | 벤치마크 방법론 문서 | `docs/nlp_benchmark/`로 이동 완료 |
| `benchmark_results/` | 벤치마크 결과 원본 | `docs/nlp_benchmark/`에 복사 완료 |

## Sub-directories

| 디렉토리 | 용도 |
|---|---|
| `sim_engines/` | 서버사이드 시뮬레이션 엔진 (XAFS/XRD/XRF/XRDMap, crystal_db, phantoms) |
| `scan_engine/` | Bluesky RunEngine + ophyd 디바이스 + 스캔 플랜 |
| `epics/` | caproto Soft IOC (motor records) |
| `data/` | NexusWriter, SQLite 스캔 이력, 디텍터 시뮬레이션, XRF 시뮬레이션 |
| `benchmark_results/` | 벤치마크 결과 JSON (원본, docs에도 복사됨) |
