#!/usr/bin/env python3
"""Analyze trigger-dump WAV files to identify false positives.

Usage:
    uv run scripts/analyze_dumps.py [--dir DUMP_DIR] [--config CONFIG]

For each WAV in DUMP_DIR (default: the dump_triggers_dir from config or
/tmp/trigger_dumps), runs the configured stage-1 STT backend and reports:
  - the transcript produced
  - which trigger the filename says fired
  - whether the transcript would have matched that trigger (or anything else)

Requires a valid conf/config.yaml with at least wake_words defined.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alexa_custom.config import load_config
from alexa_custom.actions import match_trigger_with_score, normalize_text
from alexa_custom.stt_phonetics import (
    _build_alias_map,
    _approx_wake_match,
    _resolve_triggers,
)


def _read_wav_mono_s16le(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    if channels == 1:
        return frames
    samples = (
        __import__("numpy")
        .frombuffer(frames, dtype=__import__("numpy").int16)
        .reshape(-1, channels)
    )
    idx = __import__("numpy").argmax(__import__("numpy").abs(samples), axis=1)
    return samples[__import__("numpy").arange(len(samples)), idx].tobytes()


def _transcribe(audio: bytes, cfg) -> str:
    from alexa_custom.stt_backends import get_stt_backend

    backend = get_stt_backend(cfg.stt.stage1)
    chunk = 4096
    for i in range(0, len(audio), chunk):
        backend.accept_waveform(audio[i : i + chunk])
    return backend.finalize().strip() or backend.text().strip()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dir", default=None, help="Directory of WAV dump files")
    ap.add_argument("--config", default="conf/config.yaml", help="Config file path")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if cfg is None:
        print(f"ERROR: could not load config from {args.config}", file=sys.stderr)
        sys.exit(1)

    dump_dir = (
        Path(args.dir)
        if args.dir
        else (
            Path(cfg.dump_triggers_dir)
            if cfg.dump_triggers_dir
            else Path("/tmp/trigger_dumps")
        )
    )
    wavs = sorted(dump_dir.glob("*.wav"))
    if not wavs:
        print(f"No WAV files found in {dump_dir}")
        return

    alias_map = _build_alias_map(cfg.wake_words)
    direct_triggers = cfg.direct_triggers

    col = "\033[{m}m{t}\033[0m".format
    GREEN, RED, YELLOW = "32", "31", "33"

    print(f"Analyzing {len(wavs)} dump(s) from {dump_dir}\n")
    false_positives = 0

    for wav_path in wavs:
        # Filename: <timestamp>_<label>.wav — label is the trigger phrase that fired
        label = wav_path.stem.split("_", 2)[-1].replace("_", " ")
        print(f"{'─' * 70}")
        print(f"File : {wav_path.name}")
        print(f"Fired: {label!r}")

        try:
            audio = _read_wav_mono_s16le(wav_path)
            transcript = _transcribe(audio, cfg)
        except Exception as e:
            print(f"ERROR transcribing: {e}\n")
            continue

        print(f"STT  : {transcript!r}")

        if not transcript:
            print(col(YELLOW, "  → empty transcript (noise burst?)"))
            false_positives += 1
            print()
            continue

        # Check wake word match
        wake = _approx_wake_match(
            transcript, alias_map, threshold=cfg.stt.stage1.wake_match_threshold
        )
        if wake:
            print(f"Wake : {col(GREEN, wake.word)!r} matched")
            triggers = _resolve_triggers(wake, cfg.triggers)
            norm = normalize_text(transcript)
            # Strip wake tokens to get command
            wake_tokens = {
                w for p in [wake.word] + wake.aliases for w in normalize_text(p).split()
            }
            cmd = " ".join(t for t in norm.split() if t not in wake_tokens)
            if cmd:
                trig, score = match_trigger_with_score(
                    cmd,
                    triggers,
                    algorithm=cfg.recognition.matching_algorithm,
                    threshold=cfg.recognition.matching_threshold,
                    min_word_overlap=cfg.recognition.min_word_overlap,
                )
                if trig:
                    print(
                        f"Cmd  : {col(GREEN, cmd)!r} → trigger {trig.phrase!r} (score={score:.0f})"
                    )
                else:
                    print(
                        f"Cmd  : {col(YELLOW, cmd)!r} → no trigger match (best score={score:.0f})"
                    )
            else:
                print("Cmd  : (none — wake only)")
        else:
            # Check direct triggers
            trig, score = (
                match_trigger_with_score(
                    transcript,
                    direct_triggers,
                    algorithm=cfg.recognition.matching_algorithm,
                    threshold=cfg.recognition.matching_threshold,
                    min_word_overlap=1.0,
                )
                if direct_triggers
                else (None, 0.0)
            )
            if trig:
                print(
                    f"Direct: {col(GREEN, transcript)!r} → {trig.phrase!r} (score={score:.0f})"
                )
            else:
                print(
                    col(
                        RED,
                        f"  → FALSE POSITIVE: transcript {transcript!r} did not match expected trigger {label!r}",
                    )
                )
                false_positives += 1

        print()

    print(f"{'─' * 70}")
    summary = f"{false_positives}/{len(wavs)} likely false positives"
    print(col(RED if false_positives else GREEN, summary))


if __name__ == "__main__":
    main()
