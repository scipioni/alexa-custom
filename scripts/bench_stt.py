#!/usr/bin/env python3
"""bench_stt.py — on-board benchmark for the single always-on STT model.

Validates task 1.2 of the `stt-one-model` change: can the target board (Arduino
Uno Q / Snapdragon 801) sustain ONE always-on full-transcription model, and how
does each backend compare on real-time factor, CPU load, endpoint latency, and
idle false-fire rate?

It drives the real capture path (`parec` via stt_gating.start_capture) and the
real backends (stt_backends.get_stt_backend), so the numbers reflect production
code, not a toy loop.

Run on the board:

    # Real-time-factor + CPU on pure silence (no mic needed) — the always-on cost
    uv run python scripts/bench_stt.py --backend vosk --feed silence --duration 30
    uv run python scripts/bench_stt.py --backend sherpa-onnx --feed silence --duration 30

    # Idle false-fire test from the live mic (stay silent in a quiet room)
    uv run python scripts/bench_stt.py --backend vosk --source NewPie --duration 60

    # Latency test: speak wake words / commands, watch per-utterance latency
    uv run python scripts/bench_stt.py --backend sherpa-onnx --source NewPie --live --duration 60

    # Reproducible: feed a recorded WAV (16 kHz; stereo is downmixed)
    uv run python scripts/bench_stt.py --backend vosk --wav sample.wav

Compare both backends in one go:

    uv run python scripts/bench_stt.py --backend vosk --backend sherpa-onnx --feed silence --duration 30

Key metrics
-----------
* RTF (real-time factor) = decode_time / audio_time per chunk. Mean and p95.
  RTF < 1.0 means the model keeps up always-on; p95 >= 1.0 means it stalls.
* CPU% = process CPU time / wall time (sums all decode threads). On a quad-core
  ~100% = one full core; >300% leaves no headroom for TTS + audio I/O.
* Endpoint latency = time from end-of-speech (software VAD) to a finalized,
  non-empty transcript. Lower feels snappier; the old partial-match path was
  near-instant, so watch for regressions here.
* Finalized utterances during silence/idle = false fires (open-vocab + fuzzy is
  noisier than the old grammar gate).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave

# Make the package importable when run as `python scripts/bench_stt.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alexa_custom.config import STTConfig  # noqa: E402
from alexa_custom.stt_backends import get_stt_backend  # noqa: E402
from alexa_custom.stt_gating import (  # noqa: E402
    _CHUNK,
    _downmix_to_mono,
    _read_with_timeout,
    _rms_level,
    resolve_capture_source,
    start_capture,
)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


class AudioSource:
    """Yields mono s16le chunks from mic, a WAV file, or synthetic silence."""

    def __init__(self, args):
        self.kind = "mic"
        self._proc = None
        self._wav = None
        self.channels = 1
        if args.wav:
            self.kind = "wav"
            self._wav = wave.open(args.wav, "rb")
            if self._wav.getframerate() != 16000:
                raise SystemExit(
                    f"WAV must be 16 kHz, got {self._wav.getframerate()} Hz"
                )
            self.channels = self._wav.getnchannels()
        elif args.feed == "silence":
            self.kind = "silence"
            self.channels = 1
        else:
            source, channels = resolve_capture_source(args.source)
            self.channels = channels
            self._proc = start_capture(source, channels)
            print(
                f"  capture: source={source or 'default'} channels={channels}",
                file=sys.stderr,
            )

    def read_mono(self) -> bytes | None:
        """Return one mono s16le chunk, or None on EOF."""
        if self.kind == "mic":
            assert self._proc is not None
            raw = _read_with_timeout(self._proc.stdout, _CHUNK, timeout=2.0)
            if not raw:
                return None
            return _downmix_to_mono(raw, self.channels)
        if self.kind == "wav":
            assert self._wav is not None
            frames = self._wav.readframes(_CHUNK // 2 // self.channels)
            if not frames:
                return None
            return _downmix_to_mono(frames, self.channels)
        # silence
        return b"\x00" * (_CHUNK // 2)

    def close(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
        if self._wav is not None:
            self._wav.close()


def _make_backend(backend: str, model_path: str | None, num_threads: int):
    """Build a single full-transcription model (free-vocab — no grammar)."""
    cfg = STTConfig(
        backend=backend,
        model_path=model_path,
        vosk_grammar=False,  # always-on free vocab, the single-model design
        num_threads=num_threads,
    )
    return get_stt_backend(cfg, grammar=None)


def benchmark(args, backend: str) -> dict:
    print(
        f"\n=== backend: {backend} (num_threads={args.num_threads}) ===",
        file=sys.stderr,
    )
    t_load0 = time.monotonic()
    be = _make_backend(backend, args.model, args.num_threads)
    load_s = time.monotonic() - t_load0
    print(f"  model loaded in {load_s:.1f}s", file=sys.stderr)

    src = AudioSource(args)

    # software-VAD state (mirrors the real recognition loop)
    rms_threshold = args.rms_threshold
    min_speech_ms = args.min_speech_ms
    vad_silence_ms = args.vad_silence_ms

    speech_ms = 0.0
    last_speech_t = 0.0
    in_speech = False
    speech_end_wall = 0.0

    rtfs: list[float] = []
    chunk_decode_ms: list[float] = []
    latencies: list[float] = []
    utterances: list[tuple[str, float, bool]] = []  # (text, latency_s, had_speech)

    audio_secs = 0.0
    cpu0 = time.process_time()
    wall0 = time.monotonic()
    deadline = wall0 + args.duration

    try:
        while time.monotonic() < deadline:
            mono = src.read_mono()
            if mono is None:
                break  # WAV EOF
            chunk_audio_s = (len(mono) / 2) / 16000.0
            audio_secs += chunk_audio_s
            rms = _rms_level(mono)

            now = time.monotonic()
            if rms > rms_threshold:
                if not in_speech:
                    in_speech = True
                last_speech_t = now
                speech_ms += chunk_audio_s * 1000.0

            # time the actual decode — this is the always-on cost
            d0 = time.perf_counter()
            endpoint = be.accept_waveform(mono)
            d_ms = (time.perf_counter() - d0) * 1000.0
            chunk_decode_ms.append(d_ms)
            rtfs.append((d_ms / 1000.0) / chunk_audio_s if chunk_audio_s else 0.0)

            vad_fire = (
                speech_ms >= min_speech_ms
                and last_speech_t > 0
                and (now - last_speech_t) * 1000.0 >= vad_silence_ms
            )

            if vad_fire and not endpoint:
                speech_end_wall = last_speech_t
                text = be.finalize().strip()
            elif endpoint:
                # backend endpoint: end-of-speech ~ last speech chunk seen
                speech_end_wall = last_speech_t or now
                text = be.text().strip()
                be.reset()
            else:
                continue

            had_speech = speech_ms >= min_speech_ms
            speech_ms = 0.0
            last_speech_t = 0.0
            in_speech = False

            if text:
                latency = max(0.0, time.monotonic() - speech_end_wall)
                latencies.append(latency)
                utterances.append((text, latency, had_speech))
                tag = "SPEECH" if had_speech else "IDLE-FIRE"
                print(
                    f"  [{tag}] {latency * 1000:6.0f} ms  {text!r}",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        print("  interrupted", file=sys.stderr)
    finally:
        src.close()

    cpu_s = time.process_time() - cpu0
    wall_s = time.monotonic() - wall0

    false_fires = sum(1 for _, _, had in utterances if not had)
    return {
        "backend": backend,
        "load_s": load_s,
        "wall_s": wall_s,
        "audio_secs": audio_secs,
        "cpu_pct": (cpu_s / wall_s * 100.0) if wall_s else 0.0,
        "rtf_mean": (sum(rtfs) / len(rtfs)) if rtfs else 0.0,
        "rtf_p95": _pct(rtfs, 95),
        "decode_ms_mean": (sum(chunk_decode_ms) / len(chunk_decode_ms))
        if chunk_decode_ms
        else 0.0,
        "decode_ms_p95": _pct(chunk_decode_ms, 95),
        "latency_ms_mean": (sum(latencies) / len(latencies) * 1000.0)
        if latencies
        else 0.0,
        "latency_ms_p95": _pct(latencies, 95) * 1000.0,
        "utterances": len(utterances),
        "false_fires": false_fires,
    }


def _print_report(results: list[dict], cores: int):
    print("\n" + "=" * 78)
    print(f"BENCHMARK REPORT   (cores={cores}; RTF<1.0 keeps up; CPU% per all threads)")
    print("=" * 78)
    hdr = (
        f"{'backend':<14}{'RTF avg':>8}{'RTF p95':>8}{'CPU%':>7}"
        f"{'dec avg':>9}{'dec p95':>9}{'lat avg':>9}{'lat p95':>9}{'fires':>7}{'false':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(
            f"{r['backend']:<14}"
            f"{r['rtf_mean']:>8.2f}{r['rtf_p95']:>8.2f}{r['cpu_pct']:>7.0f}"
            f"{r['decode_ms_mean']:>8.1f}m{r['decode_ms_p95']:>8.1f}m"
            f"{r['latency_ms_mean']:>8.0f}m{r['latency_ms_p95']:>8.0f}m"
            f"{r['utterances']:>7}{r['false_fires']:>7}"
        )
    print("-" * len(hdr))
    print(
        "RTF p95 >= 1.0 → the model cannot keep up always-on (chunks back up).\n"
        "Idle run: 'false' counts finalized transcripts with no real speech.\n"
        "Pick the backend with RTF p95 < ~0.7, CPU% leaving headroom for TTS, and\n"
        "few idle fires. Feed it into design.md (default backend) and tune\n"
        "vad_silence_ms / wake_window from the latency column."
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--backend",
        action="append",
        default=[],
        choices=["vosk", "sherpa-onnx"],
        help="backend(s) to test; repeat to compare (default: vosk)",
    )
    ap.add_argument(
        "--model",
        default=None,
        help="model dir override (default: backend's built-in path)",
    )
    ap.add_argument(
        "--source",
        default=None,
        help="mic device spec (e.g. 'NewPie'); default = system default",
    )
    ap.add_argument("--wav", default=None, help="feed a 16 kHz WAV instead of the mic")
    ap.add_argument(
        "--feed",
        choices=["mic", "silence"],
        default="mic",
        help="'silence' generates zeros (no mic) for pure RTF/CPU",
    )
    ap.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="seconds to run (ignored for WAV: runs to EOF)",
    )
    ap.add_argument(
        "--live",
        action="store_true",
        help="latency mode: speak phrases and watch per-utterance latency",
    )
    ap.add_argument(
        "--num-threads",
        type=int,
        default=2,
        help="Number of decoder threads (default: 2)",
    )
    ap.add_argument("--rms-threshold", type=float, default=0.02)
    ap.add_argument("--min-speech-ms", type=int, default=200)
    ap.add_argument("--vad-silence-ms", type=int, default=500)
    args = ap.parse_args()

    backends = args.backend or ["vosk"]
    if args.live and args.feed == "silence":
        print(
            "note: --live with synthetic silence will never see speech", file=sys.stderr
        )

    cores = os.cpu_count() or 1
    results = []
    for backend in backends:
        try:
            results.append(benchmark(args, backend))
        except Exception as e:  # noqa: BLE001
            print(f"  !! {backend} failed: {e}", file=sys.stderr)
    if results:
        _print_report(results, cores)


if __name__ == "__main__":
    main()
