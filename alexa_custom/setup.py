"""One-time setup: download and unpack the Italian Vosk model."""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-it-0.22.zip"
_ZIP_NAME = "vosk-model-small-it-0.22.zip"
_UNPACKED = "vosk-model-small-it-0.22"
_DEST = "models/it"


def _progress(count: int, block_size: int, total: int) -> None:
    pct = min(100, count * block_size * 100 // total)
    filled = pct // 2
    print(f"\r  [{'█' * filled}{'░' * (50 - filled)}] {pct:3d}%", end="", flush=True)


def download_model() -> None:
    dest = Path(_DEST)
    if dest.exists():
        print(f"Model already present at {dest.resolve()} — nothing to do.")
        return

    zip_path = Path(_ZIP_NAME)
    print(f"Downloading {_MODEL_URL}")
    try:
        urllib.request.urlretrieve(_MODEL_URL, zip_path, reporthook=_progress)
    except Exception as exc:
        zip_path.unlink(missing_ok=True)
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print()

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
    Path(_UNPACKED).rename(dest)
    print(f"Model ready at {dest.resolve()}")


if __name__ == "__main__":
    download_model()
