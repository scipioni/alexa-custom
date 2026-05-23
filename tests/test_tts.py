import unittest
import wave
from unittest.mock import patch, MagicMock

import numpy as np

from alexa_custom.tts import PicoTTS


def _write_test_wav(path: str, samplerate: int = 16000, n_samples: int = 1600) -> None:
    """Write a 100ms 16kHz mono silent WAV at the given path."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(b"\x00\x00" * n_samples)


class TestTTS(unittest.TestCase):
    @patch("alexa_custom.tts._play_array")
    @patch("alexa_custom.tts.subprocess.run")
    def test_pico_tts_prepends_preroll_silence(self, mock_run, mock_play):
        # Stub pico2wave so it materialises a real WAV at the requested path
        def fake_pico(cmd, **_):
            wav_path = cmd[cmd.index("-w") + 1]
            _write_test_wav(wav_path)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_pico

        engine = PicoTTS(preroll_ms=500)
        engine.say("test", "en-US")

        # pico2wave called exactly once — no ffmpeg, no pw-play subprocess.
        assert mock_run.call_count == 1
        assert mock_run.call_args_list[0][0][0][0] == "pico2wave"

        # _play_array got the audio with the 500ms preroll prepended.
        mock_play.assert_called_once()
        audio, samplerate = mock_play.call_args[0]
        assert samplerate == 16000
        # 500ms @ 16kHz = 8000 samples of leading silence, then 1600 samples of WAV
        assert audio.shape[0] == 8000 + 1600
        assert audio.shape[1] == 1
        # Leading region is all zeros
        assert float(np.max(np.abs(audio[:8000]))) == 0.0


if __name__ == "__main__":
    unittest.main()
