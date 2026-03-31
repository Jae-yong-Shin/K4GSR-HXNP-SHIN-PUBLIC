"""LoRA Fine-tuning Script for Qwen3:8b Beamline NLP

Fine-tunes Qwen3:8b with LoRA using unsloth for 4-bit quantized training.
Requires: unsloth, torch, transformers, datasets, peft, bitsandbytes

Environment setup (once):
  pip install unsloth
  # Or on Windows without triton:
  pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
  pip install torch transformers datasets peft bitsandbytes accelerate trl

Usage:
  python server/lora_finetune.py                    # train
  python server/lora_finetune.py --export-gguf       # export to GGUF for Ollama
  python server/lora_finetune.py --export-gguf --quant q4_k_m  # specific quantization

Hardware: 8GB VRAM GPU (RTX 3060/4060 etc.) with 4-bit quantization
Training time: ~30-45 minutes for 428 examples, 3 epochs
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("nlp-finetune")

# ======================================================================
# Configuration
# ======================================================================
MODEL_NAME = "unsloth/Qwen3-8B-bnb-4bit"  # 4-bit pre-quantized for low VRAM
TRAIN_DATA = os.path.join(os.path.dirname(__file__), "training_data_augmented.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "lora_output")
GGUF_DIR = os.path.join(os.path.dirname(__file__), "gguf_output")

# LoRA hyperparameters
LORA_R = 16           # LoRA rank (16 is good balance for 8B model)
LORA_ALPHA = 32       # LoRA alpha (typically 2*r)
LORA_DROPOUT = 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]

# Training hyperparameters
EPOCHS = 3
BATCH_SIZE = 1        # Small batch for 8GB VRAM
GRAD_ACCUM = 4        # Effective batch size = 4
LEARNING_RATE = 2e-4
MAX_SEQ_LEN = 2048    # Sufficient for our prompt+response
WARMUP_STEPS = 10
WEIGHT_DECAY = 0.01


def load_training_data(path):
    """Load JSONL training data."""
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    log.info(f"Loaded {len(data)} training examples from {path}")
    return data


def format_for_qwen3(example):
    """Format a training example into Qwen3 chat template string."""
    messages = example["messages"]
    # Qwen3 uses ChatML format:
    # <|im_start|>system\n{content}<|im_end|>\n
    # <|im_start|>user\n{content}<|im_end|>\n
    # <|im_start|>assistant\n{content}<|im_end|>
    parts = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    return "\n".join(parts)


def train():
    """Run LoRA fine-tuning."""
    try:
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
        from transformers import TrainingArguments
        from datasets import Dataset
    except ImportError as e:
        log.error(f"Missing dependency: {e}")
        log.error("Install required packages:")
        log.error("  pip install unsloth torch transformers datasets peft bitsandbytes accelerate trl")
        sys.exit(1)

    # Load model with 4-bit quantization
    log.info(f"{'='*60}")
    log.info(f"  LoRA Fine-tuning: {MODEL_NAME}")
    log.info(f"{'='*60}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LEN,
        dtype=None,  # Auto-detect
        load_in_4bit=True,
    )

    # Apply LoRA adapters
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        target_modules=TARGET_MODULES,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        use_gradient_checkpointing="unsloth",  # Memory optimization
        random_state=42,
    )

    # Load and format training data
    raw_data = load_training_data(TRAIN_DATA)
    formatted = [{"text": format_for_qwen3(ex)} for ex in raw_data]
    dataset = Dataset.from_list(formatted)

    log.info(f"  LoRA rank: {LORA_R}, alpha: {LORA_ALPHA}")
    log.info(f"  Target modules: {TARGET_MODULES}")
    log.info(f"  Epochs: {EPOCHS}, LR: {LEARNING_RATE}")
    log.info(f"  Effective batch: {BATCH_SIZE * GRAD_ACCUM}")
    log.info(f"  Dataset: {len(dataset)} examples")

    # Training arguments
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        num_train_epochs=EPOCHS,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        weight_decay=WEIGHT_DECAY,
        logging_steps=5,
        save_strategy="epoch",
        fp16=True,
        optim="adamw_8bit",
        seed=42,
        report_to="none",  # Disable W&B etc.
    )

    # SFT Trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LEN,
        packing=True,  # Pack multiple short examples into one sequence
    )

    # Train
    log.info("Starting training...")
    stats = trainer.train()
    log.info("Training complete!")
    log.info(f"  Loss: {stats.training_loss:.4f}")
    log.info(f"  Runtime: {stats.metrics['train_runtime']:.1f}s")

    # Save LoRA adapter
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    log.info(f"  LoRA adapter saved to: {OUTPUT_DIR}")

    return model, tokenizer


def export_gguf(quant="q4_k_m"):
    """Export fine-tuned model to GGUF format for Ollama."""
    try:
        from unsloth import FastLanguageModel
    except ImportError:
        log.error("unsloth required for GGUF export. Install: pip install unsloth")
        sys.exit(1)

    log.info(f"{'='*60}")
    log.info(f"  Exporting to GGUF ({quant})")
    log.info(f"{'='*60}")

    # Load the fine-tuned model
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=OUTPUT_DIR,
        max_seq_length=MAX_SEQ_LEN,
        dtype=None,
        load_in_4bit=True,
    )

    os.makedirs(GGUF_DIR, exist_ok=True)

    # Export to GGUF
    model.save_pretrained_gguf(
        GGUF_DIR,
        tokenizer,
        quantization_method=quant,
    )

    gguf_file = os.path.join(GGUF_DIR, f"unsloth.{quant.upper()}.gguf")
    log.info(f"  GGUF saved to: {gguf_file}")

    # Generate Ollama Modelfile
    modelfile_path = os.path.join(GGUF_DIR, "Modelfile")
    modelfile_content = f"""FROM ./{os.path.basename(gguf_file)}

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.05
PARAMETER num_predict 1024

TEMPLATE \"\"\"{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{- end }}}}
<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
\"\"\"

SYSTEM \"\"\"You are a K4GSR nanoprobe beamline assistant.\"\"\"
"""
    with open(modelfile_path, "w", encoding="utf-8") as f:
        f.write(modelfile_content)

    log.info(f"  Modelfile saved to: {modelfile_path}")
    log.info("  To register with Ollama:")
    log.info(f"    cd {GGUF_DIR}")
    log.info("    ollama create qwen3-beamline -f Modelfile")
    log.info("  Then update .env:")
    log.info("    OLLAMA_MODEL=qwen3-beamline")

    return gguf_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoRA Fine-tuning for Beamline NLP")
    parser.add_argument("--export-gguf", action="store_true", help="Export to GGUF (skip training)")
    parser.add_argument("--quant", default="q4_k_m", help="GGUF quantization (default: q4_k_m)")
    parser.add_argument("--train-and-export", action="store_true", help="Train then export")
    args = parser.parse_args()

    if args.export_gguf:
        export_gguf(args.quant)
    elif args.train_and_export:
        train()
        export_gguf(args.quant)
    else:
        train()
