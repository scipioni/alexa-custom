from __future__ import annotations

import shutil
import socket
import sys
import urllib.request
import zipfile
from pathlib import Path

_SHERPA_MODELS = {
    "kroko_128l": (
        "https://huggingface.co/hudaiapa88/sherpa-stt-onnx/resolve/main/it/kroko_128l",
        "models/it/kroko_128l",
    ),
    "kroko_64l": (
        "https://huggingface.co/hudaiapa88/sherpa-stt-onnx/resolve/main/it/kroko_64l",
        "models/it/kroko_64l",
    ),
    "ita": (
        "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-fast-conformer-ctc-be-de-en-es-fr-hr-it-pl-ru-uk-20k/resolve/main",
        "models/sherpa-onnx/nemo-ctc-it",
    ),
}
_SHERPA_FILES = [
    "model.onnx",
    "tokens.txt",
]


def download_sherpa_onnx(model: str = "kroko_128l", force: bool = False) -> None:
    if model not in _SHERPA_MODELS:
        print(
            f"Unknown sherpa-onnx model {model!r}. Available: {', '.join(_SHERPA_MODELS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url, dest_path = _SHERPA_MODELS[model]
    dest = Path(dest_path)

    if dest.exists() and not force:
        print(
            f"sherpa-onnx model already present at {dest.resolve()} — skipping (use --force to replace)."
        )
        return

    if dest.exists() and force:
        print(f"Removing existing sherpa-onnx model at {dest.resolve()} …")
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    for filename in _SHERPA_FILES:
        print(f"Downloading sherpa-onnx {filename} …")
        _download(f"{base_url}/{filename}", dest / filename)

    print(f"sherpa-onnx model ready at {dest.resolve()}")


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

_WHISPER_CPP_MODEL = "ggml-tiny-q4_0.bin"
_WHISPER_CPP_URL = (
    f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{_WHISPER_CPP_MODEL}"
)
_WHISPER_CPP_DEST = Path("models/whisper-cpp") / _WHISPER_CPP_MODEL


def _progress(count: int, block_size: int, total: int) -> None:
    if total <= 0:
        return
    pct = min(100, count * block_size * 100 // total)
    filled = pct // 2
    print(f"\r  [{'█' * filled}{'░' * (50 - filled)}] {pct:3d}%", end="", flush=True)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # urlretrieve has no timeout of its own; without this a stalled server hangs
    # the downloader forever. setdefaulttimeout bounds each socket operation.
    prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(60)
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        socket.setdefaulttimeout(prev_timeout)
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        print("\nDownload failed: received an empty file", file=sys.stderr)
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
    parser.add_argument(
        "--sherpa-onnx",
        nargs="?",
        const="kroko_128l",
        metavar="MODEL",
        help=(
            "Download a sherpa-onnx Italian transducer model. "
            f"MODEL is one of: {', '.join(_SHERPA_MODELS)} (default: kroko_128l)"
        ),
    )
    args = parser.parse_args()

    if not args.no_vosk:
        download_vosk(large=args.large, force=args.force)
    if not args.no_piper:
        download_piper_voice(args.piper_voice, force=args.force)
    if args.sherpa_onnx:
        download_sherpa_onnx(model=args.sherpa_onnx, force=args.force)


if __name__ == "__main__":
    main()
