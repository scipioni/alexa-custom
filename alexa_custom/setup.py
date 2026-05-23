"""One-time setup: download Vosk STT model and Piper TTS voice."""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

_VOSK_MODELS = {
    "small": (
        "https://alphacephei.com/vosk/models/vosk-model-small-it-0.22.zip",
        "vosk-model-small-it-0.22.zip",
        "vosk-model-small-it-0.22",
    ),
    "large": (
        "https://alphacephei.com/vosk/models/vosk-model-it-0.22.zip",
        "vosk-model-it-0.22.zip",
        "vosk-model-it-0.22",
    ),
}
_VOSK_DEST = "models/it"

# Piper voice files live in subdirectories under rhasspy/piper-voices on HF.
# Mapping: voice_name -> (language_group, speaker_dir, quality_dir).
_PIPER_VOICES = {
    "it_IT-paola-medium": ("it", "paola", "medium"),
    "it_IT-riccardo-x_low": ("it", "riccardo", "x_low"),
}
_PIPER_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
_PIPER_DEST_DIR = Path("models/piper")


def _progress(count: int, block_size: int, total: int) -> None:
    if total <= 0:
        return
    pct = min(100, count * block_size * 100 // total)
    filled = pct // 2
    print(f"\r  [{'█' * filled}{'░' * (50 - filled)}] {pct:3d}%", end="", flush=True)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print()


def download_vosk(large: bool = False, force: bool = False) -> None:
    size = "large" if large else "small"
    url, zip_name, unpacked = _VOSK_MODELS[size]
    dest = Path(_VOSK_DEST)

    if dest.exists() and not force:
        print(
            f"Vosk model already present at {dest.resolve()} — skipping (use --force to replace)."
        )
        return

    if dest.exists() and force:
        print(f"Removing existing Vosk model at {dest.resolve()} …")
        shutil.rmtree(dest)

    zip_path = Path(zip_name)
    print(f"Downloading Vosk {size} model …")
    _download(url, zip_path)

    print(f"Unpacking {zip_path} …")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(".")
    except Exception as exc:
        print(f"Unzip failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        zip_path.unlink(missing_ok=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    Path(unpacked).rename(dest)
    print(f"Vosk model ready at {dest.resolve()}")


def download_piper_voice(voice: str, force: bool = False) -> None:
    if voice not in _PIPER_VOICES:
        print(
            f"Unknown Piper voice {voice!r}. Available: {', '.join(sorted(_PIPER_VOICES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    lang, speaker, quality = _PIPER_VOICES[voice]
    onnx_dest = _PIPER_DEST_DIR / f"{voice}.onnx"
    json_dest = _PIPER_DEST_DIR / f"{voice}.onnx.json"

    if onnx_dest.is_file() and json_dest.is_file() and not force:
        print(
            f"Piper voice {voice} already present at {_PIPER_DEST_DIR.resolve()} — skipping."
        )
        return

    lang_short = voice.split("-")[0]  # e.g. "it_IT"
    base = f"{_PIPER_HF_BASE}/{lang}/{lang_short}/{speaker}/{quality}/{voice}"

    print(f"Downloading Piper voice {voice} (.onnx, ~60 MB) …")
    _download(f"{base}.onnx", onnx_dest)
    print(f"Downloading Piper voice {voice} (.onnx.json) …")
    _download(f"{base}.onnx.json", json_dest)
    print(f"Piper voice ready at {onnx_dest.resolve()}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Download Vosk STT model and Piper TTS voice"
    )
    parser.add_argument(
        "--large",
        action="store_true",
        help="Vosk: download the full model (~1.2 GB, better accuracy) instead of small (~50 MB)",
    )
    parser.add_argument(
        "--piper-voice",
        default="it_IT-paola-medium",
        help=f"Piper voice to download. Choices: {', '.join(sorted(_PIPER_VOICES))}",
    )
    parser.add_argument(
        "--no-piper",
        action="store_true",
        help="Skip the Piper voice download (Pico TTS will still work)",
    )
    parser.add_argument(
        "--no-vosk",
        action="store_true",
        help="Skip the Vosk model download",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if assets are already present",
    )
    args = parser.parse_args()

    if not args.no_vosk:
        download_vosk(large=args.large, force=args.force)
    if not args.no_piper:
        download_piper_voice(args.piper_voice, force=args.force)


if __name__ == "__main__":
    main()
