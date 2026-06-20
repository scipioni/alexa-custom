"""alexa-stt — standalone STT diagnostic tool.

Runs the exact same stage-1 + stage-2 pipeline as alexa-client (same config,
same backends, same matching logic) and prints every recognition event to
stdout.  Useful for tuning wake words, thresholds, and trigger phrases without
starting the full daemon.

Usage:
    alexa-stt                        # live microphone
    alexa-stt --record session.wav   # mic + save audio to WAV
    alexa-stt --play session.wav     # replay saved WAV instead of mic
    LOG_LEVEL=DEBUG alexa-stt        # show vosk debug traces
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
            stop_event.set()
            proc = subprocess.Popen(
                ["true"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
            )
            return proc
        _played[0] = True

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
        description="alexa-stt: STT diagnostic tool (same pipeline as alexa-client)"
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

    # Silence TTS — log instead of speaking.
    class _SilentTTS(_tts_module.TTSBackend):
        def say(self, text: str, lang: str = "it-IT") -> None:
            print(f"[tts]        {text!r}", flush=True)

    _silent_tts = _SilentTTS()
    _tts_module.get_engine = lambda: _silent_tts

    secrets = load_secrets(conf_dir / "secrets.yaml")
    config = load_config(conf_dir / "config.yaml", secrets=secrets)
    if config is None:
        print(f"ERROR: could not load {conf_dir / 'config.yaml'}", file=sys.stderr)
        sys.exit(1)

    from alexa_custom import audio_hw as _audio_hw
    _audio_hw.configure(config)

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
        elif event == "match":
            print(
                f"[match]      trigger={data.get('trigger', '')!r}"
                f"  score={data.get('score', '')}"
                f"  actions={[a.get('type') for a in data.get('actions', [])]}",
                flush=True,
            )
        elif event == "no_match":
            print(f"[no_match]   {data.get('text', '')!r}", flush=True)
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

    _print_dataset(config)

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
