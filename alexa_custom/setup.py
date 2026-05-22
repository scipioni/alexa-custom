"""One-time setup: download and unpack the Italian Vosk model."""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

_MODELS = {
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
_DEST = "models/it"


def _progress(count: int, block_size: int, total: int) -> None:
    pct = min(100, count * block_size * 100 // total)
    filled = pct // 2
    print(f"\r  [{'█' * filled}{'░' * (50 - filled)}] {pct:3d}%", end="", flush=True)


def download_model(large: bool = False, force: bool = False) -> None:
    size = "large" if large else "small"
    url, zip_name, unpacked = _MODELS[size]
    dest = Path(_DEST)

    if dest.exists() and not force:
        print(f"Model already present at {dest.resolve()} — nothing to do.")
        print("Use --force to replace it, or --large to download the full model.")
        return

    if dest.exists() and force:
        import shutil

        print(f"Removing existing model at {dest.resolve()} …")
        shutil.rmtree(dest)

    zip_path = Path(zip_name)
    print(f"Downloading {size} model ({url})")
    try:
        urllib.request.urlretrieve(url, zip_path, reporthook=_progress)
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
    Path(unpacked).rename(dest)
    print(f"Model ready at {dest.resolve()}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download Italian Vosk model")
    parser.add_argument(
        "--large",
        action="store_true",
        help="Download the full model (~1.2 GB, better accuracy) instead of the small one (~50 MB)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if a model is already present",
    )
    args = parser.parse_args()
    download_model(large=args.large, force=args.force)


if __name__ == "__main__":
    main()
