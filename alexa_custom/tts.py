from __future__ import annotations

import abc
import collections
import logging
import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alexa_custom import metrics
from alexa_custom.audio_hw import (
    get_output_volume,
    get_playback_latency_ms,
    get_post_playback_ms,
)
from alexa_custom.audio_ops import (
    _audio_lock,
    _play_array,
    _playback_active,
    set_playback_level,
)

if TYPE_CHECKING:
    import threading

logger = logging.getLogger(__name__)

# Directory where Piper voices (.onnx + .onnx.json) are stored.
PIPER_VOICES_DIR = Path(os.environ.get("PIPER_VOICES_DIR", "models/piper"))

# --- Playback stall guards -------------------------------------------------
# paplay drains its stdin at realtime, so the pipe only stays full when the
# output device has stopped consuming altogether — e.g. the USB playback PCM
# stuck in an ALSA XRUN/recover loop (pipewire logs `snd_pcm_avail after
# recover: Broken pipe` every 2 s). Writes to the player MUST be bounded: they
# run while holding _audio_lock, so a single wedged player would otherwise
# block that write forever and deadlock every later playback — voice replies
# and MQTT tts/set alike — for the lifetime of the process.
_WRITE_STALL_TIMEOUT_S = 15.0

# Upper bound on waiting for _audio_lock. Normal contention is one short tone
# or utterance ahead of us; anything longer means the holder is stuck, and
# blocking indefinitely here would just propagate the stall to the caller
# (the MQTT subscriber loop drops its broker keepalive after ~60 s).
_LOCK_ACQUIRE_TIMEOUT_S = 30.0


class _PlaybackStalled(RuntimeError):
    """The player stopped draining its stdin — the output device is wedged."""


def _write_all_bounded(
    fd: int, data: bytes, timeout: float = _WRITE_STALL_TIMEOUT_S
) -> None:
    """Write every byte of ``data`` to non-blocking ``fd``, or raise.

    The timeout restarts on every chunk, so it bounds *lack of progress*, not
    total duration: a healthy player accepts a chunk every few tens of ms no
    matter how long the utterance is, while a wedged one trips the timeout once
    the pipe buffer fills.
    """
    view = memoryview(data)
    while view:
        _, writable, _ = select.select((), (fd,), (), timeout)
        if not writable:
            raise _PlaybackStalled(
                f"player stopped reading stdin for {timeout:.0f}s, "
                f"{len(view)} bytes unwritten"
            )
        try:
            written = os.write(fd, view[:65536])
        except BlockingIOError:
            continue
        view = view[written:]


def _kill_player(proc: subprocess.Popen | None) -> None:
    """Terminate a player process, ignoring anything that goes wrong."""
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait(timeout=5.0)
    except Exception:
        pass


class TTSBackend(abc.ABC):
    @abc.abstractmethod
    def say(self, text: str, lang: str = "it-IT") -> None:
        """Speak the given text in the specified language."""
        pass

    def prewarm(self, texts: "Iterable[str]") -> None:
        """Pre-synthesize the given texts so their first playback is instant.

        Default is a no-op; backends with a synthesis cache (PiperTTS) override
        this to populate it. Used at startup to warm the configured ask
        prompts/responses, which otherwise pay ~0.7s of Piper synthesis latency
        the first time they are spoken.
        """
        return None


_CLAUSE_RE = re.compile(r"[^.!?;:,]+[.!?;:,]*")


def _split_clauses(text: str, min_len: int = 12) -> list[str]:
    """Split text into clause-sized units to lower TTS time-to-first-audio.

    Piper synthesizes one AudioChunk per *sentence*, so a long comma-spliced
    sentence must be fully synthesized before any audio plays. Breaking on
    commas/semicolons/colons too lets the first unit synthesize and start
    playing sooner. Fragments shorter than ``min_len`` are merged into the
    neighbouring piece so prosody stays natural instead of choppy.
    """
    parts = [p.strip() for p in _CLAUSE_RE.findall(text)]
    parts = [p for p in parts if p]
    if not parts:
        return []

    merged: list[str] = []
    buf = ""
    for p in parts:
        buf = f"{buf} {p}".strip() if buf else p
        if len(buf) >= min_len:
            merged.append(buf)
            buf = ""
    if buf:
        if merged:
            merged[-1] = f"{merged[-1]} {buf}".strip()
        else:
            merged.append(buf)
    return merged


def _read_wav_as_float32(path: str) -> tuple[np.ndarray, int]:
    """Read a PCM WAV file into a float32 numpy array shaped (frames, channels)."""
    with wave.open(path, "rb") as wf:
        samplerate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        raise ValueError(f"Unsupported sample width {sampwidth} (expected 16-bit PCM)")

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels)
    else:
        samples = samples.reshape(-1, 1)
    return samples, samplerate


class PicoTTS(TTSBackend):
    def __init__(
        self, stt_gated_flag: threading.Event | None = None, preroll_ms: int = 400
    ):
        self._stt_gated_flag = stt_gated_flag
        self._preroll_ms = preroll_ms

    def say(self, text: str, lang: str = "it-IT") -> None:
        if not text:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name

        try:
            logger.info(f"TTS (Pico): '{text}' [{lang}]")

            subprocess.run(
                ["pico2wave", "-l", lang, "-w", wav_path, text],
                check=True,
                stderr=subprocess.DEVNULL,
            )

            samples, samplerate = _read_wav_as_float32(wav_path)

            if self._preroll_ms > 0:
                n_preroll = int(samplerate * self._preroll_ms / 1000)
                channels = samples.shape[1]
                preroll = np.zeros((n_preroll, channels), dtype=np.float32)
                samples = np.concatenate([preroll, samples])

            _play_array(samples, samplerate)

        except Exception as e:
            logger.error(f"TTS failed: {e}")
        finally:
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass


class PiperTTS(TTSBackend):
    """Neural TTS via piper. Loads the ONNX voice once and reuses it for every say().

    Synthesized PCM for short texts is kept in a small LRU cache: Piper runs
    slower than real time on this board (~2 s to first audio for a short
    phrase), so repeated prompts (ready messages, confirmations, error
    phrases) play instantly on the second occurrence instead of paying the
    full synthesis cost every time.
    """

    # LRU bounds: 32 entries of <=200-char texts ≈ a few MB of int16 PCM.
    _CACHE_MAX_ENTRIES = 32
    _CACHE_MAX_TEXT_LEN = 200

    def __init__(
        self,
        voice: str,
        stt_gated_flag: threading.Event | None = None,
        preroll_ms: int = 400,
    ):
        # ORT prints GPU device-discovery warnings directly to stderr fd on
        # boards without standard PCI sysfs layout. Suppress during import+load.
        import os as _os

        _saved = _os.dup(2)
        _devnull = _os.open(_os.devnull, _os.O_WRONLY)
        _os.dup2(_devnull, 2)
        _os.close(_devnull)
        try:
            from piper import (
                PiperVoice,
            )  # imported lazily so pico still works without piper
        finally:
            _os.dup2(_saved, 2)
            _os.close(_saved)

        self._stt_gated_flag = stt_gated_flag
        self._preroll_ms = preroll_ms
        self._voice_name = voice
        self._cache: collections.OrderedDict[str, list[tuple[np.ndarray, int]]] = (
            collections.OrderedDict()
        )

        # Silence Piper's noisy internal debug logs (e.g. phonemes printing)
        logging.getLogger("piper").setLevel(logging.INFO)

        voice_path = PIPER_VOICES_DIR / f"{voice}.onnx"
        if not voice_path.is_file():
            raise FileNotFoundError(
                f"Piper voice not found at {voice_path}. "
                f"Run 'serena-setup --piper-voice {voice}' to download it."
            )

        logger.info(f"Loading Piper voice: {voice_path}")
        self._voice = PiperVoice.load(str(voice_path))
        # SampleRate is exposed differently across piper-tts versions; probe both.
        cfg = getattr(self._voice, "config", None)
        self._samplerate = int(
            getattr(cfg, "sample_rate", None)
            or getattr(self._voice, "sample_rate", 22050)
        )

        # Warm up ORT: the first inference pays a one-time graph-optimization
        # cost. Run a throwaway synth at load so the first real reply doesn't
        # eat that latency. Suppress stderr as in load (ORT device warnings).
        _saved = _os.dup(2)
        _devnull = _os.open(_os.devnull, _os.O_WRONLY)
        _os.dup2(_devnull, 2)
        _os.close(_devnull)
        try:
            for _ in self._voice.synthesize("ok"):
                pass
        except Exception as e:
            logger.debug(f"Piper warmup skipped: {e}")
        finally:
            _os.dup2(_saved, 2)
            _os.close(_saved)

    def _synthesize(self, text: str):
        """Yield ``(int16_array, samplerate)`` clause-by-clause.

        Splitting into clauses lowers time-to-first-audio (Piper yields one
        chunk per sentence). Audio extraction lives here so both the streaming
        and WAV-fallback paths share one code path. Short texts are served
        from / recorded into the LRU cache (unscaled — volume is applied at
        playback time, so cached audio follows volume changes).
        """
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            logger.debug("TTS cache hit: %r", text)
            yield from cached
            return

        cacheable = len(text) <= self._CACHE_MAX_TEXT_LEN
        chunks: list[tuple[np.ndarray, int]] = []
        for clause in _split_clauses(text):
            for chunk in self._voice.synthesize(clause):
                arr = np.asarray(chunk.audio_int16_array, dtype=np.int16)
                samplerate = int(getattr(chunk, "sample_rate", self._samplerate))
                if cacheable:
                    chunks.append((arr, samplerate))
                yield arr, samplerate

        # Reached only when the generator is fully consumed — an aborted
        # playback never caches a truncated utterance.
        if cacheable and chunks:
            self._cache[text] = chunks
            while len(self._cache) > self._CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

    def prewarm(self, texts: Iterable[str]) -> None:
        """Synthesize each text once so it lands in the LRU cache.

        Called at startup with the configured ask prompts/responses so their
        first playback is a cache hit (instant time-to-first-audio) instead of
        paying Piper's ~0.7s synthesis latency mid-conversation. Skips texts
        already cached or too long to cache. Best-effort: a synth failure for
        one text is logged and skipped, never raised.
        """
        _saved = os.dup(2)
        _devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_devnull, 2)
        os.close(_devnull)
        try:
            for text in texts:
                if not text or text in self._cache:
                    continue
                if len(text) > self._CACHE_MAX_TEXT_LEN:
                    continue
                try:
                    for _ in self._synthesize(text):
                        pass
                    logger.debug("TTS prewarmed: %r", text)
                except Exception as e:
                    logger.debug("TTS prewarm failed for %r: %s", text, e)
        finally:
            os.dup2(_saved, 2)
            os.close(_saved)

    def say(self, text: str, lang: str = "it-IT") -> None:
        if not text:
            return

        logger.info(f"TTS (Piper/{self._voice_name}): '{text}'")

        paplay = shutil.which("paplay")
        if paplay:
            self._say_streaming(text, paplay)
        else:
            self._say_wav_fallback(text)

    def _say_streaming(self, text: str, paplay: str) -> None:
        """Stream synthesis chunks to paplay stdin sentence-by-sentence."""
        samplerate: int | None = None
        proc: subprocess.Popen | None = None
        stdin_fd = -1
        lock_held = False
        # Playback-timing diagnostics: how long the mic gate is held vs the actual
        # audio duration. A large paplay_wall - audio gap is dead-time in which a
        # fast reply is discarded (the ask-reply barge-in investigation).
        _diag = logger.isEnabledFor(logging.DEBUG)
        _t_gate_set = 0.0
        _samples_written = 0

        try:
            for arr, chunk_rate in self._synthesize(text):
                if samplerate is None:
                    samplerate = chunk_rate

                if proc is None:
                    # Reserve the audio path BEFORE spawning the player: spawning
                    # first would leave a paplay connected to the sink while this
                    # thread waits for the lock. Bounded, so a wedged holder
                    # degrades to a dropped utterance instead of a hung caller.
                    if not _audio_lock.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S):
                        metrics.inc("tts_playback_lock_timeout")
                        logger.error(
                            "Piper TTS: audio path still busy after %.0fs — "
                            "dropping %r (a previous playback is stuck; check "
                            "for a wedged output device)",
                            _LOCK_ACQUIRE_TIMEOUT_S,
                            text,
                        )
                        return
                    lock_held = True
                    _t_gate_set = time.monotonic()
                    proc = subprocess.Popen(
                        [
                            paplay,
                            "--raw",
                            f"--rate={samplerate}",
                            "--channels=1",
                            "--format=s16le",
                            # Large enough that opening a *closed* USB playback
                            # PCM negotiates a safe ALSA period — a 20 ms buffer
                            # wedges the NewPie in a permanent XRUN loop, after
                            # which paplay never drains (see AudioConfig).
                            f"--latency-msec={get_playback_latency_ms()}",
                        ],
                        stdin=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )
                    assert proc.stdin is not None
                    # All writes go through _write_all_bounded on the raw fd, so
                    # the BufferedWriter stays empty and non-blocking mode is
                    # safe (its only remaining job is close()).
                    stdin_fd = proc.stdin.fileno()
                    os.set_blocking(stdin_fd, False)
                    _playback_active.set()

                    if self._preroll_ms > 0:
                        n_preroll = samplerate * self._preroll_ms // 1000
                        _write_all_bounded(
                            stdin_fd, bytes(n_preroll * 2), _WRITE_STALL_TIMEOUT_S
                        )

                assert proc.stdin is not None
                # Digitally scale the audio chunk by the global output volume.
                # Clip before casting: volume > 1.0 would otherwise wrap int16
                # (matches _play_array / _play_raw in audio_ops).
                volume = get_output_volume()
                scaled_arr = np.clip(arr * volume, -32768, 32767).astype(np.int16)
                _write_all_bounded(
                    stdin_fd, scaled_arr.tobytes(), _WRITE_STALL_TIMEOUT_S
                )
                n = len(scaled_arr)
                _samples_written += n
                if n:
                    # Compute in float64: norm() on int16 squares samples in
                    # int16 and overflows (e.g. 32000² wraps), giving garbage.
                    rms = float(np.linalg.norm(scaled_arr.astype(np.float64))) / (
                        32768.0 * n**0.5
                    )
                    set_playback_level(rms)

            if proc is None:
                return

            assert proc.stdin is not None
            proc.stdin.close()
            _t_wait_start = time.monotonic()
            # Bound the drain wait by what is actually still queued. The old flat
            # 60 s did both things wrong: it truncated utterances longer than a
            # minute, and it kept a stalled short one alive 60 s while holding
            # the audio lock.
            _queued_s = (
                (_samples_written / samplerate + self._preroll_ms / 1000.0)
                if samplerate
                else 0.0
            )
            _wait_timeout = max(_queued_s + 10.0, 8.0)
            try:
                proc.wait(timeout=_wait_timeout)
            except subprocess.TimeoutExpired:
                metrics.inc("tts_playback_stalled")
                logger.warning(
                    "Piper TTS: paplay still alive %.0fs after the last sample "
                    "(%.1fs queued) — killing; output device likely wedged",
                    _wait_timeout,
                    _queued_s,
                )
                _kill_player(proc)
            if _diag and samplerate:
                _t_wait_end = time.monotonic()
                _wall = _t_wait_end - _t_gate_set
                _audio = _samples_written / samplerate + self._preroll_ms / 1000.0
                # Split the wall into: write = synth + stdin writes (should be ~0
                # on a cache hit), wait = time blocked in proc.wait() (paplay
                # stream drain + process exit + GIL re-acquire). Standalone this
                # is ~audio+0.25s; if wait balloons only under the concurrent
                # reply capture, the extra is scheduling/GIL contention, not
                # paplay itself.
                _write = _t_wait_start - _t_gate_set
                _wait = _t_wait_end - _t_wait_start
                logger.debug(
                    "TTS playback: audio=%.2fs write=%.2fs wait=%.2fs "
                    "paplay_wall=%.2fs overhead=%.2fs; +post_playback=%dms held after",
                    _audio,
                    _write,
                    _wait,
                    _wall,
                    _wall - _audio,
                    get_post_playback_ms(),
                )
            post_ms = get_post_playback_ms()
            if post_ms > 0:
                time.sleep(post_ms / 1000.0)

        except _PlaybackStalled as e:
            metrics.inc("tts_playback_stalled")
            logger.error(
                "Piper TTS: output device stalled (%s) — killing paplay. If this "
                "repeats, the playback PCM is wedged: check "
                "`cat /proc/asound/card*/pcm*p/sub0/status` for XRUN and run "
                "`task audio:restart`",
                e,
            )
            _kill_player(proc)
        except Exception as e:
            logger.error(f"Piper TTS (streaming) failed: {e}")
            _kill_player(proc)
        finally:
            if lock_held:
                set_playback_level(0.0)
                _playback_active.clear()
                _audio_lock.release()

    def _say_wav_fallback(self, text: str) -> None:
        """Collect all chunks, write a WAV, and play via aplay (paplay absent)."""
        try:
            buffers: list[np.ndarray] = []
            chunk_rate: int | None = None
            for arr, rate in self._synthesize(text):
                buffers.append(arr)
                if chunk_rate is None:
                    chunk_rate = rate

            if not buffers:
                return

            samplerate = chunk_rate or self._samplerate
            samples_i16 = np.concatenate(buffers)
            samples = (samples_i16.astype(np.float32) / 32768.0).reshape(-1, 1)

            if self._preroll_ms > 0:
                n_preroll = int(samplerate * self._preroll_ms / 1000)
                preroll = np.zeros((n_preroll, 1), dtype=np.float32)
                samples = np.concatenate([preroll, samples])

            _play_array(samples, samplerate)

        except Exception as e:
            logger.error(f"Piper TTS (wav fallback) failed: {e}")


# Singleton placeholder - will be initialized in main()
_engine: TTSBackend | None = None


def get_engine() -> TTSBackend:
    if _engine is None:
        # Fallback if not initialized (though main should handle this)
        return PicoTTS()
    return _engine


def init_engine(backend_type: str = "piper", **kwargs) -> TTSBackend:
    global _engine
    stt_gated_flag = kwargs.get("stt_gated_flag")
    preroll_ms = kwargs.get("preroll_ms", 400)

    if backend_type == "pico":
        _engine = PicoTTS(stt_gated_flag=stt_gated_flag, preroll_ms=preroll_ms)
    elif backend_type == "piper":
        voice = kwargs.get("voice", "it_IT-paola-medium")
        try:
            _engine = PiperTTS(
                voice=voice,
                stt_gated_flag=stt_gated_flag,
                preroll_ms=preroll_ms,
            )
        except (ImportError, FileNotFoundError) as e:
            logger.warning(f"Piper unavailable ({e}); falling back to Pico TTS")
            _engine = PicoTTS(stt_gated_flag=stt_gated_flag, preroll_ms=preroll_ms)
    else:
        raise ValueError(f"Unknown TTS backend: {backend_type}")
    return _engine


def main_say(args: list[str] | None = None) -> None:
    """CLI entry point for serena-say."""
    import argparse
    import sys
    from alexa_custom.config import load_config, load_secrets
    from alexa_custom import audio_hw as _audio_hw

    def volume_type(value: str) -> float:
        try:
            val = float(value.replace("%", "").strip())
            if not (0.0 <= val <= 200.0):
                raise argparse.ArgumentTypeError("Volume must be between 0% and 200%")
            return val / 100.0
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid volume value: {value}")

    def loop_type(value: str) -> float | str:
        if value == "DEFAULT_SILENCE":
            return value
        try:
            val = float(value)
            if val <= 0.0:
                raise argparse.ArgumentTypeError("Loop seconds must be greater than 0")
            return val
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid loop value: {value}")

    def silence_type(value: str) -> float:
        try:
            val = float(value)
            if val < 0.0:
                raise argparse.ArgumentTypeError("Silence seconds cannot be negative")
            return val
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid silence value: {value}")

    parser = argparse.ArgumentParser(
        description="Speak text using the configured TTS backend and voice."
    )
    parser.add_argument(
        "text",
        nargs="+",
        help="Text to say",
    )
    parser.add_argument(
        "--config",
        metavar="DIR",
        default="conf",
        help="Configuration directory (default: conf)",
    )
    parser.add_argument(
        "--volume",
        "-v",
        type=volume_type,
        default=1.0,
        help="Volume percentage, e.g. 100 or 100%% (default: 100%%)",
    )
    parser.add_argument(
        "--loop",
        "-l",
        nargs="?",
        const="DEFAULT_SILENCE",
        type=loop_type,
        metavar="SECONDS",
        default=None,
        help="Repeat speech every SECONDS seconds (defaults to silence value if no SECONDS provided)",
    )
    parser.add_argument(
        "--silence",
        type=silence_type,
        default=8.0,
        help="Silence in seconds between sentences split by period (default: 8)",
    )

    parsed_args = parser.parse_args(args)
    text_to_say = " ".join(parsed_args.text)

    loop_val = parsed_args.loop
    if loop_val == "DEFAULT_SILENCE":
        loop_val = parsed_args.silence

    conf_dir = Path(parsed_args.config)

    # Set up basic logging (standard for CLI utilities in this project)
    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    secrets_path = conf_dir / "secrets.yaml"
    secrets = load_secrets(secrets_path)

    config_path = conf_dir / "config.yaml"
    if not config_path.exists():
        print(f"ERROR: config file not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path, secrets=secrets)
    if config is None:
        print(f"ERROR: could not load config from {config_path}", file=sys.stderr)
        sys.exit(1)

    # Configure audio hardware (specifically sets up the volume and output sink)
    _audio_hw.configure(config)

    # Override with CLI specified volume
    _audio_hw._state.output_volume = parsed_args.volume

    # Initialize TTS engine
    init_engine(
        backend_type=config.tts.backend,
        voice=config.tts.voice,
        preroll_ms=config.tts.preroll_ms,
    )

    # Split text into sentences by ".", "?", or "!"
    sentences = [s.strip() for s in re.split(r"[.?!]", text_to_say) if s.strip()]

    # Speak the text
    engine = get_engine()

    def _speak_flow() -> None:
        for idx, sentence in enumerate(sentences):
            if idx > 0:
                time.sleep(parsed_args.silence)
            engine.say(sentence)

    if loop_val is not None:
        print(
            f"Entering loop mode. Speaking sentences every {loop_val} seconds. Press Ctrl+C to exit.",
            file=sys.stderr,
        )
        try:
            while True:
                _speak_flow()
                time.sleep(loop_val)
        except KeyboardInterrupt:
            print("\nExiting loop mode.", file=sys.stderr)
    else:
        try:
            _speak_flow()
        except KeyboardInterrupt:
            print("\nSpeech interrupted.", file=sys.stderr)
