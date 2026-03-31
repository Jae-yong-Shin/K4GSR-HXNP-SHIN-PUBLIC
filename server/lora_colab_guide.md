---
title: "LoRA Fine-tuning Guide"
category: other
status: current
updated: 2026-03-03
tags: [nlp, lora, training]
summary: "Qwen3:8b LoRA 학습 가이드 (로컬 GPU / Colab)"
---
# LoRA Fine-tuning Guide for Qwen3:8b Beamline NLP

## Overview

Qwen3:8b 모델을 K4GSR 빔라인 NLP 명령어에 특화하여 fine-tuning합니다.
프롬프트 엔지니어링만으로 ~60-65% 패스레이트를 달성했으며,
LoRA fine-tuning으로 90%+ 목표입니다.

## 파일 구조

```
server/
  training_data.jsonl       # 78개 학습 데이터 (자동 생성)
  generate_training_data.py  # 학습 데이터 생성 스크립트
  lora_finetune.py          # LoRA 학습 + GGUF 변환 스크립트
  lora_output/              # LoRA adapter 저장 (학습 후)
  gguf_output/              # GGUF + Modelfile (변환 후)
```

## 방법 1: 로컬 GPU (8GB+ VRAM)

### 설치
```bash
pip install "unsloth @ git+https://github.com/unslothai/unsloth.git"
pip install torch transformers datasets peft bitsandbytes accelerate trl
```

### 학습 + 변환
```bash
# 학습 데이터 생성 (이미 있으면 스킵)
python server/generate_training_data.py

# LoRA 학습 (~10-15분)
python server/lora_finetune.py

# GGUF 변환
python server/lora_finetune.py --export-gguf

# 또는 한번에
python server/lora_finetune.py --train-and-export
```

### Ollama 등록
```bash
cd server/gguf_output
ollama create qwen3-beamline -f Modelfile
```

### .env 수정
```
OLLAMA_MODEL=qwen3-beamline
```

## 방법 2: Google Colab (무료 T4 GPU)

### Step 1: Colab에서 실행
```python
!pip install unsloth torch transformers datasets peft bitsandbytes accelerate trl

# training_data.jsonl 업로드 후:
!python lora_finetune.py --train-and-export --quant q4_k_m
```

### Step 2: GGUF 다운로드
```python
from google.colab import files
files.download('server/gguf_output/unsloth.Q4_K_M.gguf')
files.download('server/gguf_output/Modelfile')
```

### Step 3: 로컬에서 Ollama 등록
```bash
# 다운로드한 파일을 server/gguf_output/에 넣고:
cd server/gguf_output
ollama create qwen3-beamline -f Modelfile
```

## 방법 3: Ollama 직접 학습 (가장 간단)

Ollama 0.6+에서는 직접 fine-tuning 지원 예정입니다.
현재는 아직 불가능하므로 위 방법 1 또는 2를 사용합니다.

## 학습 데이터 확장

패스레이트를 높이려면 학습 데이터를 늘리세요:

1. `generate_training_data.py`의 `TRAINING_DATA` 리스트에 예제 추가
2. `python server/generate_training_data.py` 재실행
3. 재학습

### 권장 데이터 규모
- 78개 (현재): 기본 fine-tuning, ~80% 예상
- 200개: 패러프레이즈 추가, ~90% 예상
- 500+개: 한국어 다양성 극대화, ~95% 예상

## Hyperparameter 튜닝 가이드

| 파라미터 | 현재값 | 조절 방향 |
|---------|--------|----------|
| LORA_R | 16 | 32로 올리면 표현력 증가 (VRAM 더 필요) |
| EPOCHS | 3 | 78개에 3 epoch → overfitting 주의. 5까지 가능 |
| LR | 2e-4 | 과적합 시 1e-4로 낮추기 |
| MAX_SEQ_LEN | 2048 | 프롬프트+응답이 2048 토큰 내 들어오므로 충분 |

## 검증

학습 후 테스트:
```bash
# .env에서 OLLAMA_MODEL=qwen3-beamline 설정 후
python server/test_nlp_qwen3.py --verbose
```
