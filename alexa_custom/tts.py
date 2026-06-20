from __future__ import annotations

import abc
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alexa_custom.audio_hw import get_output_volume, get_post_playback_ms
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


class TTSBackend(abc.ABC):
    @abc.abstractmethod
    def say(self, text: str, lang: str = "it-IT") -> None:
        """Speak the given text in the specified language."""
        pass


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
    """Neural TTS via piper. Loads the ONNX voice once and reuses it for every say()."""

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

        voice_path = PIPER_VOICES_DIR / f"{voice}.onnx"
        if not voice_path.is_file():
            raise FileNotFoundError(
                f"Piper voice not found at {voice_path}. "
                f"Run 'alexa-setup --piper-voice {voice}' to download it."
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
        and WAV-fallback paths share one code path.
        """
        for clause in _split_clauses(text):
            for chunk in self._voice.synthesize(clause):
                arr = np.asarray(chunk.audio_int16_array, dtype=np.int16)
                samplerate = int(getattr(chunk, "sample_rate", self._samplerate))
                yield arr, samplerate

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

        try:
            for arr, chunk_rate in self._synthesize(text):
                if samplerate is None:
                    samplerate = chunk_rate

                if proc is None:
                    proc = subprocess.Popen(
                        [
                            paplay,
                            "--raw",
                            f"--rate={samplerate}",
                            "--channels=1",
                            "--format=s16le",
                        ],
                        stdin=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )
                    _audio_lock.acquire()
                    _playback_active.set()

                    if self._preroll_ms > 0:
                        n_preroll = samplerate * self._preroll_ms // 1000
                        proc.stdin.write(bytes(n_preroll * 2))  # type: ignore[union-attr]

                assert proc.stdin is not None
                # Digitally scale the audio chunk by the global output volume.
                # Clip before casting: volume > 1.0 would otherwise wrap int16
                # (matches _play_array / _play_raw in audio_ops).
                volume = get_output_volume()
                scaled_arr = np.clip(arr * volume, -32768, 32767).astype(np.int16)
                proc.stdin.write(scaled_arr.tobytes())
                n = len(scaled_arr)
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
            try:
                proc.wait(timeout=60.0)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Piper TTS (streaming): paplay hang detected, killing process"
                )
                proc.kill()
                proc.wait()
            post_ms = get_post_playback_ms()
            if post_ms > 0:
                time.sleep(post_ms / 1000.0)

        except Exception as e:
            logger.error(f"Piper TTS (streaming) failed: {e}")
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
        finally:
            if proc is not None:
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
