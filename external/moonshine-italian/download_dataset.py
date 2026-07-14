#!/usr/bin/env python3
"""
Download and prepare Italian speech datasets for Moonshine fine-tuning.

Datasets:
  - Mozilla Common Voice 17 (Italian)  -- requires HF token (free account)
  - FLEURS Italian                     -- ~10h, no auth needed
  - Multilingual LibriSpeech (Italian) -- ~230h, no auth needed, large

Usage:
  # Minimal (FLEURS only, no auth required):
  python download_dataset.py --sources fleurs

  # Recommended (Common Voice + FLEURS):
  python download_dataset.py --sources common_voice fleurs --hf-token hf_xxx

  # Maximum coverage (add MLS, ~230h extra):
  python download_dataset.py --sources common_voice fleurs mls --hf-token hf_xxx
"""

from __future__ import annotations

import argparse
import logging
import re
import unicodedata
from pathlib import Path

from datasets import Audio, DatasetDict, concatenate_datasets, load_dataset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

TARGET_SR = 16_000
MIN_DURATION_S = 0.5
MAX_DURATION_S = 20.0


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_common_voice(cache_dir: str, token: str | None) -> DatasetDict:
    """Mozilla Common Voice 17 Italian (~200h validated)."""
    log.info("Downloading Common Voice 17 Italian...")
    if not token:
        raise ValueError(
            "Common Voice requires a HuggingFace token. "
            "Create a free account at huggingface.co and pass --hf-token."
        )
    ds = load_dataset(
        "mozilla-foundation/common_voice_17_0",
        "it",
        cache_dir=cache_dir,
        token=token,
        trust_remote_code=True,
    )
    # CV uses 'sentence' for transcript, 'other' for unvalidated split
    ds = ds.rename_column("sentence", "text")
    ds = ds.select_columns(["audio", "text"])
    # CV has train/validation/test/other/invalidated — keep standard splits
    keep = {k: v for k, v in ds.items() if k in ("train", "validation", "test")}
    return DatasetDict(keep)


def _load_fleurs(cache_dir: str) -> DatasetDict:
    """Google FLEURS Italian (~10h, no auth required)."""
    log.info("Downloading FLEURS Italian...")
    ds = load_dataset(
        "google/fleurs",
        "it_it",
        cache_dir=cache_dir,
        trust_remote_code=True,
    )
    ds = ds.rename_column("transcription", "text")
    return DatasetDict({k: v.select_columns(["audio", "text"]) for k, v in ds.items()})


def _load_mls(cache_dir: str) -> DatasetDict:
    """Multilingual LibriSpeech Italian (~230h, no auth required)."""
    log.info("Downloading Multilingual LibriSpeech Italian (large: ~230h)...")
    ds = load_dataset(
        "facebook/multilingual_librispeech",
        "italian",
        cache_dir=cache_dir,
        trust_remote_code=True,
    )
    ds = ds.rename_column("transcript", "text")
    return DatasetDict({k: v.select_columns(["audio", "text"]) for k, v in ds.items()})


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_MULTI_SPACE = re.compile(r"\s+")

def _normalize_text(text: str) -> str:
    """Lowercase + unicode NFC + collapse whitespace."""
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _filter_duration(dataset: DatasetDict) -> DatasetDict:
    """Drop clips shorter than MIN_DURATION_S or longer than MAX_DURATION_S."""
    def _ok(example):
        arr = example["audio"]["array"]
        sr = example["audio"]["sampling_rate"]
        dur = len(arr) / sr
        return MIN_DURATION_S <= dur <= MAX_DURATION_S

    return DatasetDict({
        split: ds.filter(_ok, desc=f"duration filter ({split})")
        for split, ds in dataset.items()
    })


def _filter_empty_text(dataset: DatasetDict) -> DatasetDict:
    def _ok(example):
        return bool(example["text"].strip())

    return DatasetDict({
        split: ds.filter(_ok, desc=f"empty text filter ({split})")
        for split, ds in dataset.items()
    })


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and merge Italian ASR datasets for Moonshine fine-tuning",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["common_voice", "fleurs"],
        choices=["common_voice", "fleurs", "mls"],
        help="Dataset sources to include. 'mls' is large (~230h).",
    )
    parser.add_argument("--output-dir", default="./data/italian", help="Where to save the merged dataset")
    parser.add_argument("--cache-dir", default="./data/.hf_cache", help="HuggingFace download cache")
    parser.add_argument(
        "--hf-token",
        default=None,
        metavar="TOKEN",
        help="HuggingFace access token (required for Common Voice)",
    )
    parser.add_argument(
        "--num-proc",
        type=int,
        default=4,
        help="Number of parallel workers for dataset processing",
    )
    args = parser.parse_args()

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    cache_dir = str(Path(args.cache_dir).resolve())

    # --- Load all requested sources ---
    parts: dict[str, list] = {"train": [], "validation": [], "test": []}

    loader_map = {
        "common_voice": lambda: _load_common_voice(cache_dir, args.hf_token),
        "fleurs": lambda: _load_fleurs(cache_dir),
        "mls": lambda: _load_mls(cache_dir),
    }
    for source in args.sources:
        ds = loader_map[source]()
        ds = _filter_duration(ds)
        ds = _filter_empty_text(ds)
        for split in ("train", "validation", "test"):
            if split in ds:
                parts[split].append(ds[split])
            # FLEURS uses 'validation' but some datasets use 'dev'
            if split == "validation" and "dev" in ds:
                parts[split].append(ds["dev"])

    # --- Merge ---
    merged: dict[str, any] = {}
    for split, ds_list in parts.items():
        if ds_list:
            merged[split] = concatenate_datasets(ds_list).shuffle(seed=42)

    if not merged:
        raise RuntimeError("No data loaded — check your --sources and --hf-token.")

    dataset = DatasetDict(merged)

    # --- Resample to 16 kHz ---
    log.info("Resampling all audio to 16 kHz...")
    dataset = dataset.cast_column("audio", Audio(sampling_rate=TARGET_SR))

    # --- Normalise text ---
    log.info("Normalising text...")
    dataset = dataset.map(
        lambda batch: {"text": [_normalize_text(t) for t in batch["text"]]},
        batched=True,
        batch_size=1000,
        num_proc=args.num_proc,
        desc="Normalize text",
    )

    # --- Save ---
    save_path = output_path / "combined"
    log.info(f"Saving to {save_path} ...")
    dataset.save_to_disk(str(save_path))

    # --- Summary ---
    log.info("\n=== Dataset summary ===")
    total = 0
    for split, ds in dataset.items():
        n = len(ds)
        total += n
        log.info(f"  {split:12s}: {n:>7,} examples")
    log.info(f"  {'TOTAL':12s}: {total:>7,} examples")
    log.info(f"\nDataset saved to: {save_path}")
    log.info(
        "\nNext step:\n"
        f"  python train.py --dataset-dir {save_path} --model tiny-streaming\n"
        f"  python train.py --dataset-dir {save_path} --model medium-streaming"
    )


if __name__ == "__main__":
    main()
