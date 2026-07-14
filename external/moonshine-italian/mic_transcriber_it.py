#!/usr/bin/env python3
"""
Italian mic transcriber using a locally fine-tuned Moonshine model.

Usage:
  python mic_transcriber_it.py --model-dir output/moonshine-it-tiny-streaming/onnx
  python mic_transcriber_it.py --model-dir output/moonshine-it-medium-streaming/onnx

The model directory must contain:
  encoder_model.ort        (converted from encoder_model.onnx)
  decoder_model_merged.ort (converted from decoder_model_merged.onnx)
  tokenizer.bin            (copied from any existing Moonshine model cache)

Convert .onnx → .ort with:
  python -m onnxruntime.tools.convert_onnx_models_to_ort \\
      --optimization_style Fixed <model-dir>/

Copy tokenizer:
  cp ~/.cache/moonshine_voice/download.moonshine.ai/model/medium-streaming-en/quantized/tokenizer.bin \\
     <model-dir>/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import cast, Callable

from moonshine_voice.mic_transcriber import MicTranscriber
from moonshine_voice.transcriber import (
    ModelArch,
    TranscriptEvent,
    TranscriptEventListener,
    TranscriptLine,
)


class TerminalListener(TranscriptEventListener):
    def __init__(self) -> None:
        self._last_len = 0

    def _overwrite(self, line: TranscriptLine) -> None:
        text = line.text
        print(f"\r{text}", end="", flush=True)
        pad = self._last_len - len(text)
        if pad > 0:
            print(" " * pad, end="", flush=True)
        self._last_len = len(text)

    def on_line_started(self, event) -> None:  # noqa: ARG002
        self._last_len = 0

    def on_line_text_changed(self, event) -> None:
        self._overwrite(event.line)

    def on_line_completed(self, event) -> None:
        self._overwrite(event.line)
        print()
        self._last_len = 0


class FileListener(TranscriptEventListener):
    def on_line_completed(self, event) -> None:
        print(event.line.text, flush=True)


_NON_STREAMING_FILES = ["encoder_model.ort", "decoder_model_merged.ort", "tokenizer.bin"]
_STREAMING_FILES = [
    "frontend.ort", "encoder.ort", "adapter.ort",
    "cross_kv.ort", "decoder_kv.ort",
    "streaming_config.json", "tokenizer.bin",
]


def _check_model_dir(model_dir: Path) -> None:
    # Auto-detect which file set to validate based on what's present
    has_streaming  = (model_dir / "frontend.ort").exists()
    has_non_stream = (model_dir / "encoder_model.ort").exists()

    if has_streaming:
        required = _STREAMING_FILES
    elif has_non_stream:
        required = _NON_STREAMING_FILES
    else:
        # Neither set found — check both and report
        required = _NON_STREAMING_FILES

    missing = [f for f in required if not (model_dir / f).exists()]
    if not missing:
        return

    print(f"ERROR: missing files in {model_dir}:", file=sys.stderr)
    for f in missing:
        print(f"  {f}", file=sys.stderr)

    if has_streaming or not has_non_stream:
        print("\nFor streaming ORT files, run:", file=sys.stderr)
        print(f"  python export_streaming.py --model-dir <final-dir> --output-dir {model_dir}", file=sys.stderr)
    else:
        print("\nConvert .onnx → .ort:", file=sys.stderr)
        print(f"  python -m onnxruntime.tools.convert_onnx_models_to_ort "
              f"--optimization_style Fixed {model_dir}/", file=sys.stderr)
        print("\nCopy tokenizer.bin from any cached English model:", file=sys.stderr)
        print(f"  cp ~/.cache/moonshine_voice/download.moonshine.ai/model/"
              f"medium-streaming-en/quantized/tokenizer.bin {model_dir}/", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe microphone audio in Italian using a fine-tuned Moonshine model",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model-dir",
        default="output/moonshine-it-tiny-streaming/onnx",
        help=(
            "Non-streaming: directory with encoder_model.ort + decoder_model_merged.ort + tokenizer.bin\n"
            "Streaming:     directory with frontend.ort + encoder.ort + adapter.ort + "
            "cross_kv.ort + decoder_kv.ort + streaming_config.json + tokenizer.bin"
        ),
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        help=(
            "Use streaming ModelArch (TINY_STREAMING or MEDIUM_STREAMING depending on model size). "
            "Requires streaming ORT files from export_streaming.py. "
            "Default is ModelArch.TINY (non-streaming)."
        ),
    )
    parser.add_argument(
        "--medium",
        action="store_true",
        help="Use MEDIUM_STREAMING instead of TINY_STREAMING when --streaming is set.",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="sounddevice input device index (default: system default)",
    )
    parser.add_argument(
        "--update-interval",
        type=float,
        default=0.5,
        help="Transcription update interval in seconds",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    if args.streaming:
        model_arch = ModelArch.MEDIUM_STREAMING if args.medium else ModelArch.TINY_STREAMING
    else:
        model_arch = ModelArch.TINY
    _check_model_dir(model_dir)

    arch_label = model_arch.name
    print(f"Loading Italian model ({arch_label}) from {model_dir} ...", file=sys.stderr)
    transcriber = MicTranscriber(
        model_path=str(model_dir),
        model_arch=model_arch,
        update_interval=args.update_interval,
        device=args.device,
    )

    listener = TerminalListener() if sys.stdout.isatty() else FileListener()
    transcriber.add_listener(cast(Callable[[TranscriptEvent], None], listener))

    print("Listening — press Ctrl+C to stop.", file=sys.stderr)
    transcriber.start()
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        transcriber.stop()
        transcriber.close()


if __name__ == "__main__":
    main()
