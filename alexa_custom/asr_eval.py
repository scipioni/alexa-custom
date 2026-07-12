"""Standalone Italian ASR evaluation tool (serena-vad).

Evaluates the architecture proposed in docs/asr-plan.md — a VAD-gated,
always-on streaming ASR pipeline using sherpa-onnx + the Kroko Zipformer
Italian model + Silero VAD — with a real microphone, printing live partial
and final transcripts to stdout.

This is deliberately NOT wired into the production STT pipeline
(alexa_custom/stt.py, currently Vosk-only). It exists to validate accuracy
and latency before deciding whether to migrate that pipeline. It does reuse
the project's existing capture plumbing (alexa_custom.stt_gating) so it
inherits the same device-agnostic USB audio handling as the real daemon.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np

from alexa_custom.stt_gating import (
    _apply_input_gain,
    _downmix_to_mono,
    resolve_capture_source,
    start_capture,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_ROOT = REPO_ROOT / "models" / "it"
VAD_MODEL_PATH = REPO_ROOT / "models" / "vad" / "silero_vad.onnx"
VAD_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
)

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512  # 32 ms @ 16 kHz — Silero VAD's native window size
CHUNK_BYTES = CHUNK_SAMPLES * 2  # s16le
PRE_ROLL_CHUNKS = 6  # ~192 ms, matches docs/asr-plan.md's ring-buffer sizing
RIGHT_CONTEXT_SAMPLES = int(0.66 * SAMPLE_RATE)  # Zipformer's tail lookahead


def _ensure_vad_model() -> Path:
    if VAD_MODEL_PATH.exists():
        return VAD_MODEL_PATH
    VAD_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[setup] downloading silero_vad.onnx -> {VAD_MODEL_PATH}", file=sys.stderr)
    urllib.request.urlretrieve(VAD_MODEL_URL, VAD_MODEL_PATH)
    return VAD_MODEL_PATH


def _build_recognizer(model_dir: Path, num_threads: int):
    import sherpa_onnx

    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / "encoder.int8.onnx"),
        decoder=str(model_dir / "decoder.int8.onnx"),
        joiner=str(model_dir / "joiner.int8.onnx"),
        num_threads=num_threads,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
        provider="cpu",
    )


def _build_vad(
    vad_model_path: Path,
    threshold: float,
    min_silence_ms: int,
    min_speech_ms: int,
):
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(vad_model_path)
    config.silero_vad.threshold = threshold
    config.silero_vad.min_silence_duration = min_silence_ms / 1000.0
    # Default (250 ms) requires that much *sustained* above-threshold speech
    # before is_speech_detected() ever flips True — short commands like
    # "accendi le luci" have brief inter-word dips and can end before the
    # debounce confirms, silently vanishing into the pre-roll buffer with no
    # output at all. Lower it so short commands are recognized as speech fast.
    config.silero_vad.min_speech_duration = min_speech_ms / 1000.0
    config.silero_vad.window_size = CHUNK_SAMPLES
    config.sample_rate = SAMPLE_RATE
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=10)


def _read_exact(stdout, nbytes: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = stdout.read(nbytes - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _resolve_capture_config(use_config: bool, apply_gain: bool):
    """Optionally load conf/config.yaml's audio.input_gain and/or capture settings.

    Gain is opt-in (--apply-config-gain), not automatic: verified on this board
    that ALSA capture ('Mic') and the PulseAudio source volume are both already
    at 100% — there's no analog headroom left, so multiplying by the persisted
    software gain (1.5x here) clips already-near-full-scale audio instead of
    helping quiet trailing speech, which measurably made recognition *worse*
    (confirmed 2026-07-12: "nero" decoded fully at 1.0x, truncated at 1.5x).
    Only enable this if your board's hardware capture level isn't already maxed.

    Also returns the parsed config when use_config=True, so
    --capture-backend=config can drive the same gstreamer/pipewiresrc path the
    production daemon uses (e.g. SP92 pro-audio) instead of duplicating that
    device-specific logic here.
    """
    if not use_config and not apply_gain:
        return None

    from alexa_custom.config import load_config

    cfg = load_config()
    if cfg is None:
        print(
            "[warn] conf/config.yaml not found"
            + (" — input gain stays at 1.0x" if apply_gain else "")
            + (", falling back to parec" if use_config else ""),
            file=sys.stderr,
        )
        return None

    if apply_gain:
        from alexa_custom import audio_hw

        audio_hw.configure(cfg)
        print(
            f"[setup] input gain from conf/config.yaml: "
            f"{audio_hw.get_software_input_gain():.2f}x",
            file=sys.stderr,
        )

    return cfg if use_config else None


def _stream_utterances(proc, channels: int, recognizer, vad, print_live: bool = False):
    """Consume PCM from proc.stdout, yield (final_text, elapsed_ms) per utterance.

    Shared by the live-mic loop (run(), proc never ends) and --bench (proc ends
    when WAV replay finishes), so the VAD-gating / tail-padding logic used to
    validate docs/asr-plan.md lives in exactly one place.
    """
    stream = recognizer.create_stream()
    pre_roll: deque = deque(maxlen=PRE_ROLL_CHUNKS)
    was_speaking = False
    speech_started_at = 0.0

    assert proc.stdout is not None
    while True:
        raw = _read_exact(proc.stdout, CHUNK_BYTES * channels)
        if raw is None:
            return

        mono = _apply_input_gain(_downmix_to_mono(raw, channels))
        samples = np.frombuffer(mono, dtype=np.int16).astype(np.float32) / 32768.0

        vad.accept_waveform(samples)
        while not vad.empty():
            vad.pop()

        speaking = vad.is_speech_detected()

        if speaking:
            if not was_speaking:
                speech_started_at = time.monotonic()
                for buffered in pre_roll:
                    stream.accept_waveform(SAMPLE_RATE, buffered)
                pre_roll.clear()
                if print_live:
                    print("\n[vad] speech start", file=sys.stderr)

            stream.accept_waveform(SAMPLE_RATE, samples)
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)

            if print_live:
                partial = recognizer.get_result(stream)
                if partial:
                    print(f"\r[live] {partial}", end="", flush=True)
        else:
            if was_speaking:
                if print_live:
                    pre_tail_text = recognizer.get_result(stream)
                    print(
                        f"\n[debug] pre-tail (VAD just flipped to silence): "
                        f"{pre_tail_text or '<empty>'}",
                        file=sys.stderr,
                    )

                # Zipformer's encoder needs ~0.66s of trailing right-context to
                # decode the last word(s) of an utterance. VAD's own hangover
                # (min_silence_duration) already keeps feeding real audio while
                # is_speech_detected() is True, but the declared endpoint can
                # still land a bit early on real mic input (natural trailing
                # amplitude decay dipping under threshold before the word is
                # truly finished) — substituting hard silence here would throw
                # that genuine trailing audio away. Keep reading real captured
                # audio for the right-context window and only zero-pad the
                # remainder once the capture itself runs out (WAV replay EOF).
                fed_samples = 0
                tail_rms = 0.0
                while fed_samples < RIGHT_CONTEXT_SAMPLES:
                    raw_tail = _read_exact(proc.stdout, CHUNK_BYTES * channels)
                    if raw_tail is None:
                        break
                    mono_tail = _apply_input_gain(_downmix_to_mono(raw_tail, channels))
                    tail_samples = (
                        np.frombuffer(mono_tail, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    stream.accept_waveform(SAMPLE_RATE, tail_samples)
                    fed_samples += len(tail_samples)
                    tail_rms = max(tail_rms, float(np.sqrt(np.mean(tail_samples**2))))
                if fed_samples < RIGHT_CONTEXT_SAMPLES:
                    stream.accept_waveform(
                        SAMPLE_RATE,
                        np.zeros(RIGHT_CONTEXT_SAMPLES - fed_samples, dtype=np.float32),
                    )
                if print_live:
                    print(
                        f"[debug] tail feed: {fed_samples} real samples "
                        f"({fed_samples / SAMPLE_RATE * 1000:.0f} ms), peak RMS={tail_rms:.4f} "
                        f"(>0.01 suggests real trailing audio, not just noise floor)",
                        file=sys.stderr,
                    )
                stream.input_finished()
                while recognizer.is_ready(stream):
                    recognizer.decode_stream(stream)
                final_text = recognizer.get_result(stream)
                elapsed_ms = (time.monotonic() - speech_started_at) * 1000.0
                if print_live:
                    print()
                yield final_text, elapsed_ms
                stream = recognizer.create_stream()
            else:
                pre_roll.append(samples)

        was_speaking = speaking


def run(args: argparse.Namespace) -> None:
    import sherpa_onnx  # noqa: F401 — import early so a missing dep fails clearly

    model_dir = MODELS_ROOT / args.model
    if not model_dir.is_dir():
        raise SystemExit(f"model directory not found: {model_dir}")

    vad_model_path = _ensure_vad_model()

    print(
        f"[setup] loading recognizer ({args.model}, {args.num_threads} threads)...",
        file=sys.stderr,
    )
    recognizer = _build_recognizer(model_dir, args.num_threads)
    vad = _build_vad(
        vad_model_path, args.vad_threshold, args.vad_silence_ms, args.vad_speech_ms
    )

    capture_config = _resolve_capture_config(
        args.capture_backend == "config", args.apply_config_gain
    )
    source, channels = resolve_capture_source(args.input)
    print(
        f"[setup] capturing from source={source or 'default'} channels={channels} "
        f"backend={args.capture_backend}",
        file=sys.stderr,
    )
    proc = start_capture(source, channels, config=capture_config)

    print("[ready] listening — speak in Italian, Ctrl+C to stop", file=sys.stderr)
    try:
        for final_text, elapsed_ms in _stream_utterances(
            proc, channels, recognizer, vad, print_live=True
        ):
            print(f"[final] ({elapsed_ms:.0f} ms) {final_text or '<empty>'}")
        print("[error] capture process ended", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[stop] interrupted", file=sys.stderr)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def _synthesize_bench_wav(phrase: str, voice: str) -> Path:
    """Synthesize `phrase` with Piper to a temp WAV, reusing the project's TTS engine."""
    import wave

    from alexa_custom.tts import PiperTTS

    tts = PiperTTS(voice)
    chunks = list(tts._synthesize(phrase))
    if not chunks:
        raise SystemExit(f"piper produced no audio for {phrase!r}")

    samplerate = chunks[0][1]
    pcm = np.concatenate([arr for arr, _ in chunks])

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="serena-vad-bench-")
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(pcm.tobytes())
    return Path(path)


def _print_bench_table(rows: list[dict], label: str) -> None:
    print()
    print(f"=== serena-vad --bench: {label!r} ===")
    print(f"{'threads':>7}  {'min ms':>8}  {'mean ms':>8}  {'max ms':>8}  runs  transcript")
    for row in rows:
        timings = row["timings"]
        if not timings:
            print(
                f"{row['num_threads']:>7}  {'--':>8}  {'--':>8}  {'--':>8}  "
                f"0/{row['attempted']}  <no utterance detected>"
            )
            continue
        text = row["texts"][-1] if row["texts"] else ""
        print(
            f"{row['num_threads']:>7}  {min(timings):8.0f}  "
            f"{sum(timings) / len(timings):8.0f}  {max(timings):8.0f}  "
            f"{len(timings)}/{row['attempted']}   {text!r}"
        )


def run_bench(args: argparse.Namespace) -> None:
    import sherpa_onnx  # noqa: F401 — import early so a missing dep fails clearly

    from alexa_custom.stt_cli import _make_play_capture

    model_dir = MODELS_ROOT / args.model
    if not model_dir.is_dir():
        raise SystemExit(f"model directory not found: {model_dir}")

    vad_model_path = _ensure_vad_model()

    cleanup_wav = False
    if args.bench_wav:
        wav_path = Path(args.bench_wav)
        if not wav_path.is_file():
            raise SystemExit(f"WAV file not found: {wav_path}")
        label = str(wav_path)
    else:
        print(
            f"[bench] synthesizing {args.bench_phrase!r} with piper "
            f"({args.bench_voice})...",
            file=sys.stderr,
        )
        wav_path = _synthesize_bench_wav(args.bench_phrase, args.bench_voice)
        cleanup_wav = True
        label = args.bench_phrase

    try:
        thread_counts = [int(t) for t in args.bench_threads.split(",") if t.strip()]
        rows = []
        for n_threads in thread_counts:
            print(f"[bench] num_threads={n_threads}: loading recognizer...", file=sys.stderr)
            t0 = time.monotonic()
            recognizer = _build_recognizer(model_dir, n_threads)
            print(f"[bench]   recognizer loaded in {time.monotonic() - t0:.1f}s", file=sys.stderr)

            timings: list[float] = []
            texts: list[str] = []
            for i in range(args.bench_repeats):
                vad = _build_vad(
                    vad_model_path,
                    args.vad_threshold,
                    args.vad_silence_ms,
                    args.vad_speech_ms,
                )
                stop_event = threading.Event()
                play_capture = _make_play_capture(str(wav_path), stop_event)
                proc = play_capture(None, 1)

                utterances = list(
                    _stream_utterances(proc, 1, recognizer, vad, print_live=False)
                )
                proc.terminate()

                if utterances:
                    text, elapsed_ms = utterances[0]
                    timings.append(elapsed_ms)
                    texts.append(text)
                    print(
                        f"[bench]   run {i + 1}/{args.bench_repeats}: "
                        f"{elapsed_ms:.0f} ms — {text!r}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[bench]   run {i + 1}/{args.bench_repeats}: "
                        "no utterance detected",
                        file=sys.stderr,
                    )

            rows.append(
                {
                    "num_threads": n_threads,
                    "timings": timings,
                    "texts": texts,
                    "attempted": args.bench_repeats,
                }
            )

        _print_bench_table(rows, label)
    finally:
        if cleanup_wav:
            wav_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="kroko_64l",
        choices=["kroko_64l", "kroko_128l"],
        help="Kroko model variant under models/it/",
    )
    parser.add_argument(
        "--input",
        default="auto",
        help="PipeWire source name substring, or 'auto' for the first USB audio source",
    )
    parser.add_argument(
        "--capture-backend",
        default="parec",
        choices=["parec", "config"],
        help="'parec' (default, works for NewPie/BT51) or 'config' to reuse "
        "conf/config.yaml's stt.capture_backend (needed for SP92 pro-audio)",
    )
    parser.add_argument(
        "--apply-config-gain",
        action="store_true",
        dest="apply_config_gain",
        help="Apply conf/config.yaml's audio.input_gain (matches the production "
        "daemon). Off by default — verified to clip already-maxed hardware "
        "capture on this board rather than help quiet trailing speech.",
    )
    parser.add_argument("--num-threads", type=int, default=2, dest="num_threads")
    parser.add_argument("--vad-threshold", type=float, default=0.5, dest="vad_threshold")
    parser.add_argument(
        "--vad-silence-ms", type=int, default=400, dest="vad_silence_ms"
    )
    parser.add_argument(
        "--vad-speech-ms",
        type=int,
        default=100,
        dest="vad_speech_ms",
        help="Minimum sustained speech before VAD confirms speech start "
        "(sherpa-onnx default 250ms misses short commands)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    default_threads = sorted({1, 2, min(4, os.cpu_count() or 4)})
    parser.add_argument(
        "--bench",
        action="store_true",
        help="Benchmark --num-threads values on a canned/synthesized utterance "
        "instead of listening on the live microphone",
    )
    parser.add_argument(
        "--bench-phrase",
        default="accendi le luci",
        dest="bench_phrase",
        help="Phrase to synthesize with Piper for --bench (ignored if --bench-wav is given)",
    )
    parser.add_argument(
        "--bench-voice",
        default="it_IT-paola-medium",
        dest="bench_voice",
        help="Piper voice used to synthesize --bench-phrase",
    )
    parser.add_argument(
        "--bench-wav",
        default=None,
        dest="bench_wav",
        help="Use this WAV file for --bench instead of synthesizing --bench-phrase",
    )
    parser.add_argument(
        "--bench-threads",
        default=",".join(str(n) for n in default_threads),
        dest="bench_threads",
        help="Comma-separated num_threads values to compare",
    )
    parser.add_argument(
        "--bench-repeats",
        type=int,
        default=3,
        dest="bench_repeats",
        help="Repeats per thread count, for min/mean/max stability",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    try:
        if args.bench:
            run_bench(args)
        else:
            run(args)
    except ModuleNotFoundError as e:
        if "sherpa_onnx" in str(e):
            raise SystemExit(
                "sherpa-onnx is not installed. Run: uv sync --extra asr-eval"
            ) from e
        raise


if __name__ == "__main__":
    main()
