from __future__ import annotations

import abc
import logging
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING

from alexa_custom.audio import play_wav_file

if TYPE_CHECKING:
    import threading

logger = logging.getLogger(__name__)


class TTSBackend(abc.ABC):
    @abc.abstractmethod
    def say(self, text: str, lang: str = "it-IT") -> None:
        """Speak the given text in the specified language."""
        pass


class PicoTTS(TTSBackend):
    def __init__(self, stt_gated_flag: threading.Event | None = None):
        self._stt_gated_flag = stt_gated_flag

    def say(self, text: str, lang: str = "it-IT") -> None:
        if not text:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            logger.info(f"TTS (Pico): '{text}' [{lang}]")

            # 1. Generate speech
            # NOTE: Order and format (it-IT) are crucial for some pico2wave wrappers
            subprocess.run(
                ["pico2wave", "-l", lang, "-w", temp_path, text],
                check=True,
                stderr=subprocess.DEVNULL,
            )

            # 2. Gate STT (pause listening)
            if self._stt_gated_flag:
                self._stt_gated_flag.set()

            # 3. Play audio (blocking)
            try:
                play_wav_file(temp_path)
            finally:
                # 4. Ungate STT
                if self._stt_gated_flag:
                    self._stt_gated_flag.clear()

        except Exception as e:
            logger.error(f"TTS failed: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


# Singleton placeholder - will be initialized in main()
_engine: TTSBackend | None = None


def get_engine() -> TTSBackend:
    if _engine is None:
        # Fallback if not initialized (though main should handle this)
        return PicoTTS()
    return _engine


def init_engine(backend_type: str = "pico", **kwargs) -> TTSBackend:
    global _engine
    if backend_type == "pico":
        _engine = PicoTTS(stt_gated_flag=kwargs.get("stt_gated_flag"))
    else:
        raise ValueError(f"Unknown TTS backend: {backend_type}")
    return _engine
