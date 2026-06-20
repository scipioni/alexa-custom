#!/usr/bin/env python3
"""
Fine-tune Moonshine for Italian ASR.

Supports:
  - moonshine-tiny-streaming   (34 M params)
  - moonshine-medium-streaming (245 M params)

Training strategy: curriculum learning in three phases (short → medium → full).
Loss: cross-entropy over decoder token sequence (standard seq2seq).
Optimizer: AdamW with linear warmup + cosine decay.
Export: ONNX via optimum-cli after training.

Usage:
  # Tiny streaming (fits in ~6 GB VRAM with fp16 + gradient checkpointing)
  python train.py --dataset-dir ./data/italian/combined --model tiny-streaming

  # Medium streaming (~24 GB VRAM; use --gradient-checkpointing and fp16)
  python train.py --dataset-dir ./data/italian/combined --model medium-streaming \\
      --per-device-batch-size 2 --gradient-accumulation 32

  # Resume from checkpoint
  python train.py --dataset-dir ./data/italian/combined --model tiny-streaming \\
      --resume-from-checkpoint ./output/moonshine-it-tiny-streaming/checkpoint-500
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from datasets import DatasetDict, load_from_disk
from transformers import (
    AutoProcessor,
    EarlyStoppingCallback,
    MoonshineForConditionalGeneration,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
)
import evaluate

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODEL_REGISTRY = {
    "tiny-streaming": "UsefulSensors/moonshine-tiny-streaming",
    "medium-streaming": "UsefulSensors/moonshine-medium-streaming",
    # Non-streaming fallbacks (same seq2seq API, usable if streaming HF weights
    # are not yet released as PyTorch checkpoints):
    "tiny": "UsefulSensors/moonshine-tiny",
    "base": "UsefulSensors/moonshine-base",
}

# Recommended defaults per model size (override via CLI)
MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "tiny-streaming": dict(
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        gradient_accumulation_steps=8,
        learning_rate=3e-4,
        max_steps=10_000,
    ),
    "medium-streaming": dict(
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=32,
        learning_rate=1e-4,
        max_steps=20_000,
    ),
    "tiny": dict(
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        gradient_accumulation_steps=8,
        learning_rate=3e-4,
        max_steps=10_000,
    ),
    "base": dict(
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        gradient_accumulation_steps=16,
        learning_rate=2e-4,
        max_steps=15_000,
    ),
}


# ---------------------------------------------------------------------------
# Curriculum phases
# ---------------------------------------------------------------------------

@dataclass
class CurriculumPhase:
    name: str
    min_duration_s: float
    max_duration_s: float
    max_steps: int            # steps to spend in this phase
    wer_threshold: float      # advance to next phase if WER drops below this


CURRICULUM: list[CurriculumPhase] = [
    CurriculumPhase("short",  0.5,  6.0,  2_000, 0.50),
    CurriculumPhase("medium", 2.0, 12.0,  4_000, 0.35),
    CurriculumPhase("full",   0.5, 20.0, 99_999, 0.00),
]


# ---------------------------------------------------------------------------
# Data collator
# ---------------------------------------------------------------------------

class DataCollatorSpeechSeq2Seq:
    """
    Pads audio features to the same length within a batch and tokenises labels.
    """

    def __init__(self, processor, max_label_length: int = 448):
        self.processor = processor
        self.max_label_length = max_label_length

    def __call__(self, features: list[dict]) -> dict[str, torch.Tensor]:
        # --- Audio ---
        audio_arrays = [f["audio"]["array"] for f in features]
        sampling_rates = [f["audio"]["sampling_rate"] for f in features]
        assert all(sr == sampling_rates[0] for sr in sampling_rates), (
            "Mixed sampling rates in batch"
        )
        inputs = self.processor.feature_extractor(
            audio_arrays,
            sampling_rate=sampling_rates[0],
            return_tensors="pt",
            padding=True,
        )

        # --- Labels ---
        label_features = [{"input_ids": self.processor.tokenizer(f["text"]).input_ids}
                           for f in features]
        labels_batch = self.processor.tokenizer.pad(
            label_features,
            max_length=self.max_label_length,
            padding=True,
            return_tensors="pt",
        )
        # Replace tokenizer pad token id with -100 (ignored in loss)
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch["attention_mask"].eq(0), -100
        )
        # Drop BOS token from labels if present (model adds it during generation)
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all():
            labels = labels[:, 1:]

        return {
            "input_features": inputs.input_features,
            "labels": labels,
        }


# ---------------------------------------------------------------------------
# WER computation
# ---------------------------------------------------------------------------

def build_compute_metrics(processor):
    wer_metric = evaluate.load("wer")

    def compute_metrics(pred):
        pred_ids = pred.predictions
        label_ids = pred.label_ids

        # Replace -100 (padding) with pad token id for decoding
        label_ids[label_ids == -100] = processor.tokenizer.pad_token_id

        pred_str = processor.batch_decode(pred_ids, skip_special_tokens=True)
        label_str = processor.batch_decode(label_ids, skip_special_tokens=True)

        wer = wer_metric.compute(predictions=pred_str, references=label_str)
        return {"wer": round(wer, 4)}

    return compute_metrics


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def filter_by_duration(dataset: DatasetDict, phase: CurriculumPhase) -> DatasetDict:
    def _ok(example):
        arr = example["audio"]["array"]
        sr = example["audio"]["sampling_rate"]
        dur = len(arr) / sr
        return phase.min_duration_s <= dur <= phase.max_duration_s

    return DatasetDict({
        split: ds.filter(_ok, desc=f"[{phase.name}] duration filter ({split})")
        for split, ds in dataset.items()
    })


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_phase(
    phase: CurriculumPhase,
    full_dataset: DatasetDict,
    model: MoonshineForConditionalGeneration,
    processor,
    output_dir: Path,
    args,
    global_step: int,
    fp16: bool,
    bf16: bool,
) -> tuple[MoonshineForConditionalGeneration, int, float]:
    """
    Run one curriculum phase. Returns (model, last_global_step, best_wer).
    """
    log.info(f"\n{'='*60}")
    log.info(f"Curriculum phase: {phase.name}  "
             f"({phase.min_duration_s}–{phase.max_duration_s}s clips, "
             f"max {phase.max_steps:,} steps)")
    log.info(f"{'='*60}")

    phase_dataset = filter_by_duration(full_dataset, phase)
    if len(phase_dataset.get("train", [])) == 0:
        log.warning(f"No training examples for phase '{phase.name}', skipping.")
        return model, global_step, float("inf")

    phase_dir = output_dir / f"phase-{phase.name}"

    effective_batch = (
        args.per_device_batch_size * args.gradient_accumulation
    )
    log.info(f"Effective batch size: {effective_batch}")

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(phase_dir),
        per_device_train_batch_size=args.per_device_batch_size,
        per_device_eval_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        warmup_steps=min(args.warmup_steps, phase.max_steps // 10),
        max_steps=phase.max_steps,
        fp16=fp16,
        bf16=bf16,
        gradient_checkpointing=args.gradient_checkpointing,
        evaluation_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.eval_steps,
        load_best_model_at_end=True,
        metric_for_best_model="wer",
        greater_is_better=False,
        logging_steps=max(1, args.eval_steps // 5),
        predict_with_generate=True,
        generation_max_length=448,
        label_smoothing_factor=0.1,
        dataloader_num_workers=4,
        report_to=["tensorboard"] if args.tensorboard else [],
        push_to_hub=False,
        remove_unused_columns=False,
    )

    collator = DataCollatorSpeechSeq2Seq(processor)
    compute_metrics = build_compute_metrics(processor)

    callbacks = [EarlyStoppingCallback(early_stopping_patience=3)]

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=phase_dataset["train"],
        eval_dataset=phase_dataset.get("validation"),
        tokenizer=processor.feature_extractor,
        data_collator=collator,
        compute_metrics=compute_metrics,
        callbacks=callbacks,
    )

    train_result = trainer.train(
        resume_from_checkpoint=args.resume_from_checkpoint
        if global_step == 0 else None
    )

    best_wer = trainer.state.best_metric or float("inf")
    global_step += train_result.global_step

    # Save phase checkpoint
    trainer.save_model(str(phase_dir / "best"))
    processor.save_pretrained(str(phase_dir / "best"))

    log.info(f"Phase '{phase.name}' complete — best WER: {best_wer:.4f}")
    return model, global_step, best_wer


def export_onnx(model_dir: Path, output_dir: Path) -> None:
    """Export the fine-tuned model to ONNX using optimum."""
    try:
        from optimum.exporters.onnx import main_export
    except ImportError:
        log.warning(
            "optimum not installed — skipping ONNX export.\n"
            "Install with: pip install optimum[exporters]"
        )
        return

    onnx_dir = output_dir / "onnx"
    log.info(f"Exporting to ONNX: {onnx_dir}")
    main_export(
        model_name_or_path=str(model_dir),
        output=str(onnx_dir),
        task="automatic-speech-recognition-with-past",
        no_post_process=False,
        optimize=None,
    )
    log.info(f"ONNX export complete: {onnx_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fine-tune Moonshine for Italian ASR",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--model",
        default="tiny-streaming",
        choices=list(MODEL_REGISTRY),
        help="Model variant to fine-tune",
    )
    p.add_argument(
        "--base-model-id",
        default=None,
        help="Override HuggingFace model ID (default from --model registry)",
    )
    p.add_argument(
        "--dataset-dir",
        required=True,
        metavar="PATH",
        help="Path to dataset saved by download_dataset.py",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: ./output/moonshine-it-{model})",
    )
    p.add_argument("--per-device-batch-size", type=int, default=None)
    p.add_argument("--gradient-accumulation", type=int, default=None)
    p.add_argument("--learning-rate", type=float, default=None)
    p.add_argument("--max-steps", type=int, default=None,
                   help="Override total max steps (overrides curriculum budget)")
    p.add_argument("--warmup-steps", type=int, default=500)
    p.add_argument("--eval-steps", type=int, default=500)
    p.add_argument(
        "--freeze-encoder",
        action="store_true",
        help="Freeze encoder weights; only train decoder (faster, less VRAM)",
    )
    p.add_argument("--gradient-checkpointing", action="store_true", default=True)
    p.add_argument("--no-gradient-checkpointing", dest="gradient_checkpointing",
                   action="store_false")
    p.add_argument("--fp16", action="store_true", default=None)
    p.add_argument("--bf16", action="store_true", default=None)
    p.add_argument(
        "--skip-curriculum",
        action="store_true",
        help="Train on full dataset in one phase (faster but lower quality)",
    )
    p.add_argument(
        "--resume-from-checkpoint",
        default=None,
        metavar="PATH",
        help="Resume training from a saved checkpoint directory",
    )
    p.add_argument("--export-onnx", action="store_true",
                   help="Export final model to ONNX after training")
    p.add_argument("--tensorboard", action="store_true",
                   help="Enable TensorBoard logging")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # --- Resolve model ID and defaults ---
    model_id = args.base_model_id or MODEL_REGISTRY[args.model]
    defaults = MODEL_DEFAULTS[args.model]

    if args.per_device_batch_size is None:
        args.per_device_batch_size = defaults["per_device_train_batch_size"]
    if args.gradient_accumulation is None:
        args.gradient_accumulation = defaults["gradient_accumulation_steps"]
    if args.learning_rate is None:
        args.learning_rate = defaults["learning_rate"]

    if args.output_dir is None:
        args.output_dir = f"./output/moonshine-it-{args.model}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Determine precision ---
    if args.fp16 is None and args.bf16 is None:
        # Auto-detect: prefer bf16 on Ampere+, fp16 otherwise
        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability()
            args.bf16 = cap[0] >= 8
            args.fp16 = not args.bf16
        else:
            args.fp16 = False
            args.bf16 = False
    fp16 = bool(args.fp16)
    bf16 = bool(args.bf16)

    log.info(f"Model: {model_id}")
    log.info(f"Output: {output_dir}")
    log.info(f"Precision: {'bf16' if bf16 else 'fp16' if fp16 else 'fp32'}")

    # --- Load dataset ---
    log.info(f"Loading dataset from {args.dataset_dir} ...")
    dataset = load_from_disk(args.dataset_dir)
    log.info(f"  train: {len(dataset['train']):,}  "
             f"validation: {len(dataset.get('validation', [])):,}")

    # --- Load processor and model ---
    log.info(f"Loading processor and model from {model_id} ...")
    processor = AutoProcessor.from_pretrained(model_id)

    # Set Italian language token if the processor supports it
    if hasattr(processor.tokenizer, "set_prefix_tokens"):
        try:
            processor.tokenizer.set_prefix_tokens(language="it", task="transcribe")
            log.info("Tokenizer language set to Italian.")
        except Exception:
            log.warning("Could not set language prefix tokens — model may be English-only tokenizer.")

    model = MoonshineForConditionalGeneration.from_pretrained(model_id)

    # Required for gradient checkpointing
    model.config.use_cache = False

    if args.freeze_encoder:
        log.info("Freezing encoder weights.")
        for param in model.encoder.parameters():
            param.requires_grad = False

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log.info(f"Parameters: {total_params/1e6:.1f}M total, {trainable_params/1e6:.1f}M trainable")

    # --- Curriculum training ---
    phases = (
        [CurriculumPhase("full", 0.5, 20.0, args.max_steps or defaults["max_steps"], 0.0)]
        if args.skip_curriculum
        else CURRICULUM
    )

    # Optionally override phase budgets to respect --max-steps total
    if args.max_steps:
        # Distribute steps across phases proportionally
        total_budget = args.max_steps
        weights = [0.2, 0.3, 0.5]
        adjusted: list[CurriculumPhase] = []
        for phase, w in zip(phases, weights):
            adjusted.append(dataclasses.replace(phase, max_steps=max(1, int(total_budget * w))))
        phases = adjusted

    global_step = 0
    for phase in phases:
        model, global_step, best_wer = train_phase(
            phase=phase,
            full_dataset=dataset,
            model=model,
            processor=processor,
            output_dir=output_dir,
            args=args,
            global_step=global_step,
            fp16=fp16,
            bf16=bf16,
        )
        if best_wer <= phase.wer_threshold:
            log.info(
                f"WER {best_wer:.4f} ≤ threshold {phase.wer_threshold} — "
                f"advancing from phase '{phase.name}'"
            )

    # --- Save final model ---
    final_dir = output_dir / "final"
    log.info(f"Saving final model to {final_dir} ...")
    model.save_pretrained(str(final_dir))
    processor.save_pretrained(str(final_dir))

    # --- ONNX export ---
    if args.export_onnx:
        export_onnx(final_dir, output_dir)

    log.info("\nTraining complete.")
    log.info(f"Model saved to: {final_dir}")
    if not args.export_onnx:
        log.info(
            "\nTo export to ONNX for deployment:\n"
            f"  optimum-cli export onnx --model {final_dir} "
            f"  --task automatic-speech-recognition-with-past "
            f"  {output_dir}/onnx"
        )


if __name__ == "__main__":
    main()
