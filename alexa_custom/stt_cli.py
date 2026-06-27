"""serena-stt — standalone STT diagnostic tool.

Runs the exact same stage-1 + stage-2 pipeline as serena-client (same config,
same backends, same matching logic) and prints every recognition event to
stdout.  Useful for tuning wake words, thresholds, and trigger phrases without
starting the full daemon.

Usage:
    serena-stt                        # live microphone
    serena-stt --record session.wav   # mic + save audio to WAV
    serena-stt --play session.wav     # replay saved WAV instead of mic
    LOG_LEVEL=DEBUG serena-stt        # show vosk debug traces
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading


# ---------------------------------------------------------------------------
# Audio helpers for --record / --play
# ---------------------------------------------------------------------------


class _TeePopen:
    """Wraps a real capture process and tees its stdout to a WAV file.

    Uses an os.pipe() so the read end has a real fileno() that satisfies
    _read_with_timeout (select + os.read).
    """

    def __init__(self, real_proc, channels: int, record_path: str) -> None:
        import wave

        self._real = real_proc
        r_fd, w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb", buffering=0)

        wf = wave.open(record_path, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(16000)

        def _tee() -> None:
            src_fd = real_proc.stdout.fileno()
            while True:
                try:
                    data = os.read(src_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                wf.writeframes(data)
                try:
                    os.write(w_fd, data)
                except OSError:
                    break
            try:
                os.close(w_fd)
            except OSError:
                pass
            wf.close()

        threading.Thread(target=_tee, daemon=True).start()

    @property
    def returncode(self):
        return self._real.returncode

    def poll(self):
        return self._real.poll()

    def terminate(self) -> None:
        self._real.terminate()

    def wait(self, timeout=None):
        return self._real.wait(timeout=timeout)


class _RealTimePopen:
    """Wraps a decode process and re-emits audio at real-time speed via an os.pipe().

    Without this, --play feeds audio as fast as Vosk can consume it — much faster
    than wall clock.  The partial stability check uses time.monotonic(), so a 200ms
    stability window passes in ~30ms of wall time and never fires.  Throttling to
    real-time fixes that without changing any STT logic.
    """

    def __init__(self, src_proc, channels: int, pad_s: float = 1.5) -> None:
        import time as _time

        self._src = src_proc
        r_fd, w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb", buffering=0)
        # bytes per chunk at 16kHz s16le
        chunk = 4096 * channels
        seconds_per_chunk = chunk / (2 * channels * 16000)

        def _feed() -> None:
            src_fd = src_proc.stdout.fileno()
            silence = b"\x00" * chunk
            # Drain the source at real-time pace, then send pad_s of silence.
            try:
                while True:
                    t0 = _time.monotonic()
                    try:
                        data = os.read(src_fd, chunk)
                    except OSError:
                        break
                    if not data:
                        break
                    try:
                        os.write(w_fd, data)
                    except OSError:
                        return
                    elapsed = _time.monotonic() - t0
                    delay = seconds_per_chunk - elapsed
                    if delay > 0:
                        _time.sleep(delay)
                # trailing silence so VAD and stability checks can complete
                pad_chunks = int(pad_s / seconds_per_chunk) + 1
                for _ in range(pad_chunks):
                    try:
                        os.write(w_fd, silence)
                    except OSError:
                        break
                    _time.sleep(seconds_per_chunk)
            finally:
                try:
                    os.close(w_fd)
                except OSError:
                    pass

        threading.Thread(target=_feed, daemon=True).start()

    @property
    def returncode(self):
        return self._src.returncode

    def poll(self):
        return self._src.poll()

    def terminate(self) -> None:
        self._src.terminate()

    def wait(self, timeout=None):
        return self._src.wait(timeout=timeout)


class _WavFilePopen:
    """Pure-Python WAV reader — fallback when ffmpeg/sox are absent.

    Reads raw PCM frames from a WAV file at real-time pace and feeds them
    through an os.pipe(), mimicking the Popen interface expected by the STT
    pipeline.  Only works for WAV files already at 16 kHz / s16le; if the
    file has a different rate or depth the output will be garbled.
    """

    def __init__(self, wav_path: str, channels: int, pad_s: float = 1.5) -> None:
        import wave as _wave
        import time as _time

        self._returncode: int | None = None
        r_fd, w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb", buffering=0)
        chunk_frames = 4096 * channels // 2  # s16le: 2 bytes/sample
        seconds_per_chunk = chunk_frames / 16000.0

        def _feed() -> None:
            try:
                with _wave.open(wav_path, "rb") as wf:
                    silence = b"\x00" * (chunk_frames * wf.getsampwidth() * wf.getnchannels())
                    while True:
                        t0 = _time.monotonic()
                        data = wf.readframes(chunk_frames)
                        if not data:
                            break
                        try:
                            os.write(w_fd, data)
                        except OSError:
                            return
                        elapsed = _time.monotonic() - t0
                        delay = seconds_per_chunk - elapsed
                        if delay > 0:
                            _time.sleep(delay)
                pad_chunks = int(pad_s / seconds_per_chunk) + 1
                for _ in range(pad_chunks):
                    try:
                        os.write(w_fd, silence)
                    except OSError:
                        break
                    _time.sleep(seconds_per_chunk)
            finally:
                self._returncode = 0
                try:
                    os.close(w_fd)
                except OSError:
                    pass

        threading.Thread(target=_feed, daemon=True).start()

    @property
    def returncode(self):
        return self._returncode

    def poll(self):
        return self._returncode

    def terminate(self) -> None:
        pass

    def wait(self, timeout=None):
        return self._returncode


def _make_play_capture(play_path: str, stop_event: threading.Event):
    """Return a start_capture replacement that streams a WAV file at real-time speed."""
    import shutil
    import subprocess

    _played = [False]

    def _play_capture(source, channels: int = 1, config=None):
        if _played[0]:
            print(f"alexa-stt: finished {play_path}", file=sys.stderr)
            stop_event.set()
            proc = subprocess.Popen(
                ["true"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
            )
            return proc
        _played[0] = True
        print(f"alexa-stt: playing {play_path}", file=sys.stderr)

        if shutil.which("ffmpeg"):
            cmd = [
                "ffmpeg",
                "-i",
                play_path,
                "-ar",
                "16000",
                "-ac",
                str(channels),
                "-f",
                "s16le",
                "pipe:1",
            ]
        elif shutil.which("sox"):
            cmd = [
                "sox",
                play_path,
                "-t",
                "raw",
                "-r",
                "16000",
                "-c",
                str(channels),
                "-e",
                "signed-integer",
                "-b",
                "16",
                "-",
            ]
        else:
            return _WavFilePopen(play_path, channels)

        src = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
        return _RealTimePopen(src, channels)

    return _play_capture


def _make_record_capture(record_path: str):
    """Return a start_capture replacement that also writes audio to a WAV file."""
    import alexa_custom.stt_gating as _gating

    _orig = _gating.start_capture

    def _record_capture(source, channels: int = 1, config=None):
        real_proc = _orig(source, channels, config=config)
        print(f"alexa-stt: recording to {record_path}", file=sys.stderr)
        return _TeePopen(real_proc, channels, record_path)

    return _record_capture


# ---------------------------------------------------------------------------
# GStreamer calibration
# ---------------------------------------------------------------------------


def _build_gst_config(base, args):
    """Return a GStreamerCaptureConfig with CLI overrides applied over base."""
    import dataclasses

    overrides = {}
    if args.gst_source is not None:
        overrides["source"] = args.gst_source
    if args.gst_noise_suppression is not None:
        overrides["noise_suppression"] = args.gst_noise_suppression
    if args.gst_noise_suppression_level is not None:
        overrides["noise_suppression_level"] = args.gst_noise_suppression_level
    if args.gst_agc is not None:
        overrides["agc"] = args.gst_agc
    if args.gst_agc_target_level_dbfs is not None:
        overrides["agc_target_level_dbfs"] = args.gst_agc_target_level_dbfs
    if args.gst_agc_compression_gain_db is not None:
        overrides["agc_compression_gain_db"] = args.gst_agc_compression_gain_db
    if args.gst_high_pass_filter is not None:
        overrides["high_pass_filter"] = args.gst_high_pass_filter
    if args.gst_compressor is not None:
        overrides["compressor"] = args.gst_compressor
    if args.gst_compressor_threshold is not None:
        overrides["compressor_threshold"] = args.gst_compressor_threshold
    if args.gst_compressor_ratio is not None:
        overrides["compressor_ratio"] = args.gst_compressor_ratio
    if getattr(args, "gst_expander", None) is not None:
        overrides["expander"] = args.gst_expander
    if getattr(args, "gst_expander_threshold", None) is not None:
        overrides["expander_threshold"] = args.gst_expander_threshold
    if getattr(args, "gst_expander_ratio", None) is not None:
        overrides["expander_ratio"] = args.gst_expander_ratio
    return dataclasses.replace(base, **overrides) if overrides else base


def _run_calibrate_gstreamer(args, config) -> None:
    import dataclasses
    import json
    import random
    import time

    import numpy as np

    from alexa_custom.stt_backends import get_stt_backend
    from alexa_custom.stt_gating import resolve_capture_source, _rms_level
    from alexa_custom.stt_phonetics import _match_wake_word
    from alexa_custom.actions import match_trigger_with_score
    import alexa_custom.tts as _tts_module

    # Build the effective GStreamer config.
    gst_cfg = _build_gst_config(config.audio.gstreamer, args)

    # Collect all candidate phrases (wake words + first command of every trigger).
    phrases = list(config.wake_words)
    for t in config.triggers:
        if t.commands:
            phrases.append(t.commands[0])
    phrase = args.phrase if args.phrase else random.choice(phrases)

    # Effective RMS threshold (CLI override or from config).
    rms_threshold = args.rms_threshold if args.rms_threshold is not None else config.stt.rms_threshold

    # Initialise TTS (real engine — calibration needs to speak).
    try:
        tts_cfg = config.tts if hasattr(config, "tts") else None
        backend_type = tts_cfg.backend if tts_cfg else "piper"
        voice = tts_cfg.voice if tts_cfg else "it_IT-paola-medium"
        _tts_module.init_engine(backend_type, voice=voice)
    except Exception as e:
        print(f"[calibrate] TTS init failed ({e}); prompts will be text-only", file=sys.stderr)

    # --- Announce the phrase ---
    try:
        _tts_module.get_engine().say(f"Di' questo: {phrase}")
    except Exception as e:
        print(f"[calibrate] TTS say failed: {e}", file=sys.stderr)
    print(f"[calibrate] phrase  : {phrase!r}", file=sys.stderr)

    # Short gap, then a ready tone.
    time.sleep(0.3)
    try:
        from alexa_custom.audio_ops import play_tone
        play_tone("wake")
    except Exception:
        pass
    time.sleep(0.5)

    # --- Capture audio via GStreamer ---
    try:
        from alexa_custom.stt_gst_capture import start_capture_gst
    except ImportError as e:
        print(json.dumps({"error": f"GStreamer unavailable: {e}"}))
        return

    source, _ = resolve_capture_source(config.audio.input_device)
    print(f"[calibrate] capturing {args.listen_seconds}s via GStreamer …", file=sys.stderr)

    try:
        proc = start_capture_gst(source, gst_cfg)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}))
        return

    target_bytes = int(args.listen_seconds * 16000 * 2)  # s16le mono
    collected = bytearray()
    rms_chunks: list[float] = []
    deadline = time.monotonic() + args.listen_seconds + 2.0  # hard timeout

    while len(collected) < target_bytes and time.monotonic() < deadline:
        want = min(4096, target_bytes - len(collected))
        try:
            chunk = proc.stdout.read(want)
        except OSError:
            break
        if not chunk:
            break
        collected += chunk
        if len(chunk) >= 2:
            rms_chunks.append(_rms_level(chunk))

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        pass

    captured_bytes = len(collected)
    captured_s = captured_bytes / (16000 * 2)
    print(f"[calibrate] captured : {captured_s:.2f}s ({captured_bytes} bytes)", file=sys.stderr)

    # --- Run STT ---
    try:
        backend = get_stt_backend(config.stt)
    except RuntimeError as e:
        print(json.dumps({"error": f"STT backend: {e}"}))
        return

    chunk_size = 4096
    for i in range(0, len(collected), chunk_size):
        backend.accept_waveform(bytes(collected[i : i + chunk_size]))
    transcript = backend.finalize().strip()
    print(f"[calibrate] transcript: {transcript!r}", file=sys.stderr)

    # --- Score the result ---
    # Wake word match
    wake_phrase, residual = _match_wake_word(transcript, config.wake_words)

    # Trigger match (threshold=0 so we always get a score, even if it misses production gate)
    trig, score = match_trigger_with_score(
        transcript,
        config.triggers,
        algorithm=config.recognition.matching_algorithm,
        threshold=0.0,
    )

    # Exact-phrase match: was the right phrase identified?
    exact_ok = False
    if wake_phrase and any(w == phrase for w in config.wake_words):
        exact_ok = True
    elif trig and phrase in (trig.commands or [trig.phrase]):
        exact_ok = True

    # RMS stats
    rms_peak = max(rms_chunks, default=0.0)
    rms_mean = float(np.mean(rms_chunks)) if rms_chunks else 0.0
    chunks_above = sum(1 for r in rms_chunks if r > rms_threshold)

    result = {
        "phrase_played": phrase,
        "transcript": transcript,
        "exact_match": exact_ok,
        "matched_trigger": trig.phrase if trig else None,
        "matched_wake": wake_phrase,
        "match_score": round(score, 1),
        "production_threshold": config.recognition.matching_threshold,
        "rms_peak": round(rms_peak, 4),
        "rms_mean": round(rms_mean, 4),
        "rms_threshold": rms_threshold,
        "chunks_above_rms": chunks_above,
        "total_chunks": len(rms_chunks),
        "speech_ratio": round(chunks_above / len(rms_chunks), 3) if rms_chunks else 0.0,
        "captured_seconds": round(captured_s, 2),
        "gst_params": {
            f.name: getattr(gst_cfg, f.name)
            for f in dataclasses.fields(gst_cfg)
            if f.name != "profiles"
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Dataset printer
# ---------------------------------------------------------------------------


def _print_dataset(config) -> None:
    """Print all wake words and trigger commands to stdout as a recording guide."""
    lines = []
    lines.append("")
    lines.append("=== DATASET — phrases to record ===")
    lines.append("")
    lines.append("Wake words (say these to activate):")
    for w in config.wake_words:
        lines.append(f"  {w}")
    lines.append("")
    lines.append("Direct commands (no wake word needed):")
    for t in config.triggers:
        if not t.with_wake:
            for cmd in (t.commands or [t.phrase]):
                lines.append(f"  {cmd}")
    lines.append("")
    lines.append("Wake-gated commands (say a wake word first, then):")
    for t in config.triggers:
        if t.with_wake:
            for cmd in (t.commands or [t.phrase]):
                lines.append(f"  {cmd}")
    lines.append("")
    lines.append("One-breath examples (wake word + command in one utterance):")
    wake = config.wake_words[0] if config.wake_words else "ehi serena"
    for t in config.triggers:
        if t.with_wake:
            cmd = t.commands[0] if t.commands else t.phrase
            lines.append(f"  {wake} {cmd}")
    lines.append("")
    lines.append("=" * 38)
    lines.append("")
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="serena-stt: STT diagnostic tool (same pipeline as serena-client)"
    )
    parser.add_argument(
        "--config",
        metavar="DIR",
        default="conf",
        help="configuration directory (default: conf)",
    )
    parser.add_argument(
        "--record",
        metavar="FILE",
        help="record microphone audio to a WAV file while listening",
    )
    parser.add_argument(
        "--play",
        metavar="FILE",
        help="replay a previously recorded WAV file instead of using the microphone",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="listen for a single wake word or command, print 'score=xx' to stdout, and exit",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        metavar="N",
        help="maximum seconds to wait in score mode before exiting with score=0 (default: 20.0)",
    )
    parser.add_argument(
        "--input-gain",
        type=float,
        default=None,
        metavar="F",
        help="microphone input gain override (default: from config)",
    )

    # --calibrate-gstreamer mode
    parser.add_argument(
        "--calibrate-gstreamer",
        action="store_true",
        help="one-shot GStreamer calibration: speak a phrase, capture, decode, print JSON result",
    )
    parser.add_argument(
        "--phrase",
        metavar="TEXT",
        help="specific phrase to use in calibration (default: random from config)",
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=4.0,
        metavar="N",
        help="seconds to capture audio after the ready tone (default: 4.0)",
    )
    parser.add_argument(
        "--rms-threshold",
        type=float,
        default=None,
        metavar="F",
        help="RMS threshold for speech-ratio stats (default: from config)",
    )
    # GStreamer parameter overrides
    gst = parser.add_argument_group("GStreamer overrides (--calibrate-gstreamer)")
    gst.add_argument("--source", dest="gst_source", metavar="SRC",
                     help="pulsesrc | pipewiresrc")
    gst.add_argument("--noise-suppression", dest="gst_noise_suppression",
                     action="store_true", default=None)
    gst.add_argument("--no-noise-suppression", dest="gst_noise_suppression",
                     action="store_false")
    gst.add_argument("--noise-suppression-level", dest="gst_noise_suppression_level",
                     type=int, choices=[0, 1, 2, 3], metavar="0-3",
                     help="0=mild 1=moderate 2=high 3=very-high")
    gst.add_argument("--agc", dest="gst_agc", action="store_true", default=None)
    gst.add_argument("--no-agc", dest="gst_agc", action="store_false")
    gst.add_argument("--agc-target-level-dbfs", dest="gst_agc_target_level_dbfs",
                     type=int, metavar="N",
                     help="AGC target level in dBFS (negative int, e.g. -3)")
    gst.add_argument("--agc-compression-gain-db", dest="gst_agc_compression_gain_db",
                     type=int, metavar="N",
                     help="AGC max compression gain in dB (0-90)")
    gst.add_argument("--high-pass-filter", dest="gst_high_pass_filter",
                     action="store_true", default=None)
    gst.add_argument("--no-high-pass-filter", dest="gst_high_pass_filter",
                     action="store_false")
    gst.add_argument("--compressor", dest="gst_compressor",
                     action="store_true", default=None)
    gst.add_argument("--no-compressor", dest="gst_compressor", action="store_false")
    gst.add_argument("--compressor-threshold", dest="gst_compressor_threshold",
                     type=float, metavar="F",
                     help="Compressor threshold, normalised 0.0-1.0")
    gst.add_argument("--compressor-ratio", dest="gst_compressor_ratio",
                     type=float, metavar="F",
                     help="Compressor ratio (≥1.0)")
    gst.add_argument("--expander", dest="gst_expander",
                     action="store_true", default=None)
    gst.add_argument("--no-expander", dest="gst_expander", action="store_false")
    gst.add_argument("--expander-threshold", dest="gst_expander_threshold",
                     type=float, metavar="F",
                     help="Expander threshold, normalised 0.0-1.0")
    gst.add_argument("--expander-ratio", dest="gst_expander_ratio",
                     type=float, metavar="F",
                     help="Expander ratio (≥1.0)")

    args = parser.parse_args()

    from pathlib import Path

    conf_dir = Path(args.config)

    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    from alexa_custom.config import load_config, load_secrets
    from alexa_custom.stt import start_stt_thread
    from alexa_custom.actions import TelegramClient
    import alexa_custom.stt as _stt_module
    import alexa_custom.tts as _tts_module

    secrets = load_secrets(conf_dir / "secrets.yaml")
    config = load_config(conf_dir / "config.yaml", secrets=secrets)
    if config is None:
        print(f"ERROR: could not load {conf_dir / 'config.yaml'}", file=sys.stderr)
        sys.exit(1)

    from alexa_custom import audio_hw as _audio_hw
    _audio_hw.configure(config)

    config.audio.gstreamer = _build_gst_config(config.audio.gstreamer, args)

    if args.input_gain is not None:
        _audio_hw._state.input_gain = args.input_gain

    # Enforce input gain at hardware/PipeWire layer. Sets _state.hw_gain_applied to True on success.
    try:
        from alexa_custom.audio_hw import pulse_session, set_input_gain
        with pulse_session("serena-stt-init") as pulse:
            set_input_gain(pulse, config.audio.input_device, _audio_hw.get_input_gain())
    except Exception as e:
        print(f"WARNING: Could not set hardware input gain: {e}", file=sys.stderr)

    # --calibrate-gstreamer: run one-shot calibration and exit (uses real TTS).
    if args.calibrate_gstreamer:
        _run_calibrate_gstreamer(args, config)
        return

    # All other modes: silence TTS — log instead of speaking.
    class _SilentTTS(_tts_module.TTSBackend):
        def say(self, text: str, lang: str = "it-IT") -> None:
            if args.score:
                print(f"[tts]        {text!r}", file=sys.stderr, flush=True)
            else:
                print(f"[tts]        {text!r}", flush=True)

    _silent_tts = _SilentTTS()
    _tts_module.get_engine = lambda: _silent_tts

    stop_event = threading.Event()
    connected_flag = threading.Event()

    # Patch start_capture in stt.py's namespace before the thread starts.
    if args.play and args.record:
        print("ERROR: --play and --record are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.play:
        _stt_module.start_capture = _make_play_capture(args.play, stop_event)
        print(f"alexa-stt: playing from {args.play}", file=sys.stderr)
    elif args.record:
        _stt_module.start_capture = _make_record_capture(args.record)
        # Silence tones so they don't contaminate the recording.
        import alexa_custom.stt_capture as _stt_cap
        _stt_module.play_wake_beep = lambda *_a, **_kw: None
        _stt_cap._play_timeout = lambda: None

    if args.score:
        import alexa_custom.stt_capture as _stt_cap
        _stt_module.play_wake_beep = lambda *_a, **_kw: None
        _stt_cap._play_timeout = lambda: None

    score_printed = [False]
    timeout_timer: threading.Timer | None = None

    def print_score_and_exit(score: float | int, text: str = "") -> None:
        if not score_printed[0]:
            score_printed[0] = True
            import json
            result = {
                "score": int(round(score)),
                "text": text,
            }
            print(json.dumps(result), flush=True)
            if timeout_timer is not None:
                timeout_timer.cancel()
            stop_event.set()

    if args.score:
        def on_stt_event(event: str, data: dict) -> None:
            if event == "listening":
                wake_words = data.get("wake_words", [])
                print(f"[listening]  wake words: {wake_words}", file=sys.stderr, flush=True)
            elif event in ("transcribing", "partial"):
                print(f"[partial]    {data.get('text', '')}", file=sys.stderr, flush=True)
            elif event == "wake":
                print(f"[wake]       {data.get('word', '')!r}", file=sys.stderr, flush=True)
                # If timeout is > 0, it means it's a wake-word-only detection (no one-breath)
                # and we can print score=100 and exit.
                if data.get("timeout", 0) > 0:
                    print_score_and_exit(100, data.get("word", ""))
            elif event == "matched":
                score = data.get("score", 0.0)
                text = data.get("transcript", "")
                print(f"[matched]    score={score}", file=sys.stderr, flush=True)
                print_score_and_exit(score, text)
            elif event == "nomatch":
                score = data.get("score", 0.0)
                text = data.get("transcript", "")
                print(f"[nomatch]    score={score}", file=sys.stderr, flush=True)
                print_score_and_exit(score, text)
            elif event == "vad_empty":
                ms = data.get("speech_ms", 0)
                print(f"[vad_empty]  heard {ms}ms above threshold — Vosk produced no text", file=sys.stderr, flush=True)
            elif event == "level":
                pass  # too noisy — suppress mic level events
            else:
                print(f"[{event}]  {data}", file=sys.stderr, flush=True)
    else:
        def on_stt_event(event: str, data: dict) -> None:
            if event == "listening":
                wake_words = data.get("wake_words", [])
                print(f"[listening]  wake words: {wake_words}", flush=True)
            elif event in ("transcribing", "partial"):
                print(f"[partial]    {data.get('text', '')}", flush=True)
            elif event == "wake":
                print(f"[wake]       {data.get('word', '')!r}", flush=True)
            elif event == "direct":
                print(f"[direct]     {data.get('phrase', '')!r}", flush=True)
            elif event == "command":
                print(f"[command]    {data.get('text', '')!r}", flush=True)
            elif event in ("match", "matched"):
                score = data.get("score", "")
                trigger = data.get("trigger", data.get("phrase", ""))
                actions_list = [a.get("type") for a in data.get("actions", [])]
                print(
                    f"[match]      trigger={trigger!r}"
                    f"  score={score}"
                    f"  actions={actions_list}",
                    flush=True,
                )
            elif event in ("no_match", "nomatch"):
                print(f"[no_match]   {data.get('transcript', data.get('text', ''))!r}", flush=True)
            elif event == "vad_empty":
                ms = data.get("speech_ms", 0)
                print(f"[vad_empty]  heard {ms}ms above threshold — Vosk produced no text", flush=True)
            elif event == "level":
                pass  # too noisy — suppress mic level events
            else:
                print(f"[{event}]  {data}", flush=True)

    print("alexa-stt: starting STT pipeline (Ctrl+C to stop)", file=sys.stderr)
    print(
        f"  backend={config.stt.backend}  "
        f"vad_silence_ms={config.stt.vad_silence_ms}  "
        f"wake words={config.wake_words}",
        file=sys.stderr,
    )

    if not args.score:
        _print_dataset(config)

    if args.score:
        timeout_timer = threading.Timer(args.timeout, lambda: print_score_and_exit(0))
        timeout_timer.daemon = True
        timeout_timer.start()

    stt_thread = start_stt_thread(
        config=config,
        stop_event=stop_event,
        telegram_client=TelegramClient(),
        livekit_connect_fn=None,
        livekit_connected_flag=connected_flag,
        on_stt_event=on_stt_event,
    )

    try:
        stt_thread.join()
    except KeyboardInterrupt:
        print("\nalexa-stt: stopping", file=sys.stderr)
        stop_event.set()
        stt_thread.join(timeout=3)
    finally:
        if args.score:
            print_score_and_exit(0)
