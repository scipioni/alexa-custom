from __future__ import annotations

import abc
import logging
import os
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

import alexa_custom.audio as _audio_module
from alexa_custom.audio import _play_array

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
            for chunk in self._voice.synthesize(text):
                # piper-tts >=1.2 yields AudioChunk; older releases yield raw bytes.
                arr = getattr(chunk, "audio_int16_array", None)
                if arr is None:
                    raw = getattr(chunk, "audio_int16_bytes", None) or bytes(chunk)
                    arr = np.frombuffer(raw, dtype=np.int16)

                if samplerate is None:
                    samplerate = int(getattr(chunk, "sample_rate", self._samplerate))

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
                    _audio_module._audio_lock.acquire()
                    _audio_module._playback_active.set()

                    if self._preroll_ms > 0:
                        n_preroll = samplerate * self._preroll_ms // 1000
                        proc.stdin.write(bytes(n_preroll * 2))  # type: ignore[union-attr]

                assert proc.stdin is not None
                # Digitally scale the audio chunk by the global output volume
                scaled_arr = (
                    np.asarray(arr, dtype=np.int16) * _audio_module._OUTPUT_VOLUME
                ).astype(np.int16)
                proc.stdin.write(scaled_arr.tobytes())
                n = len(scaled_arr)
                if n:
                    rms = float(np.linalg.norm(scaled_arr)) / (32768.0 * n**0.5)
                    _audio_module.set_playback_level(rms)

            if proc is None:
                return

            proc.stdin.close()
            try:
                proc.wait(timeout=60.0)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Piper TTS (streaming): paplay hang detected, killing process"
                )
                proc.kill()
                proc.wait()
            if _audio_module._POST_PLAYBACK_MS > 0:
                time.sleep(_audio_module._POST_PLAYBACK_MS / 1000.0)

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
                _audio_module.set_playback_level(0.0)
                _audio_module._playback_active.clear()
                _audio_module._audio_lock.release()

    def _say_wav_fallback(self, text: str) -> None:
        """Collect all chunks, write a WAV, and play via aplay (paplay absent)."""
        try:
            buffers: list[np.ndarray] = []
            chunk_rate: int | None = None
            for chunk in self._voice.synthesize(text):
                arr = getattr(chunk, "audio_int16_array", None)
                if arr is None:
                    raw = getattr(chunk, "audio_int16_bytes", None) or bytes(chunk)
                    arr = np.frombuffer(raw, dtype=np.int16)
                buffers.append(np.asarray(arr, dtype=np.int16))
                if chunk_rate is None:
                    chunk_rate = int(getattr(chunk, "sample_rate", self._samplerate))

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
