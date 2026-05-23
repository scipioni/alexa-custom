import os
import unittest
from unittest.mock import patch, MagicMock
from alexa_custom.tts import PicoTTS

class TestTTS(unittest.TestCase):
    @patch("subprocess.run")
    @patch("alexa_custom.tts.play_wav_file")
    def test_pico_tts_preroll(self, mock_play, mock_run):
        # Mock successful pico2wave and ffmpeg runs
        mock_run.return_value = MagicMock(returncode=0)
        
        engine = PicoTTS(preroll_ms=1000)
        engine.say("test", "en-US")
        
        # Should be called twice: once for pico2wave, once for ffmpeg
        assert mock_run.call_count == 2
        
        # Verify ffmpeg arguments
        args = mock_run.call_args_list[1][0][0]
        assert "ffmpeg" in args
        assert "adelay=1000|1000" in args
        
        # Verify play_wav_file was called
        mock_play.assert_called_once()

if __name__ == "__main__":
    unittest.main()
