import unittest
import wave
from unittest.mock import patch, MagicMock

import numpy as np

from alexa_custom.tts import PicoTTS, _split_clauses


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


class TestSplitClauses(unittest.TestCase):
    def test_long_sentence_breaks_on_commas(self):
        # A comma-spliced sentence is broken so the first unit is short, which
        # lets Piper synthesize and start playing it before the rest is done.
        text = "Sto chiamando Stefano adesso, attendi un momento per favore."
        clauses = _split_clauses(text)
        assert len(clauses) == 2
        assert clauses[0] == "Sto chiamando Stefano adesso,"

    def test_short_text_stays_whole(self):
        assert _split_clauses("Certo.") == ["Certo."]

    def test_tiny_fragments_merge(self):
        # Fragments below min_len merge instead of producing choppy 1-word chunks.
        assert _split_clauses("Sì, no.") == ["Sì, no."]

    def test_empty(self):
        assert _split_clauses("") == []
        assert _split_clauses("   ") == []

    def test_reassembles_full_text(self):
        text = "Uno, due; tre: quattro. Cinque!"
        joined = " ".join(_split_clauses(text))
        # Same words, same order, no content lost.
        assert joined.replace(" ", "") == text.replace(" ", "")


class TestMainSay(unittest.TestCase):
    @patch("alexa_custom.tts.get_engine")
    @patch("alexa_custom.tts.init_engine")
    @patch("alexa_custom.audio_hw.configure")
    @patch("alexa_custom.config.load_config")
    @patch("alexa_custom.config.load_secrets")
    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_success(self, mock_exists, mock_load_secrets, mock_load_config, mock_configure, mock_init_engine, mock_get_engine):
        from pathlib import Path
        mock_exists.return_value = True

        # Mock load_config to return a mock config
        mock_config = MagicMock()
        mock_config.tts.backend = "piper"
        mock_config.tts.voice = "it_IT-paola-medium"
        mock_config.tts.preroll_ms = 100
        mock_load_config.return_value = mock_config

        mock_secrets = MagicMock()
        mock_load_secrets.return_value = mock_secrets

        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        from alexa_custom.tts import main_say
        from alexa_custom import audio_hw
        main_say(["Ciao, come stai?", "--config", "conf"])

        mock_load_secrets.assert_called_once_with(Path("conf/secrets.yaml"))
        mock_load_config.assert_called_once_with(Path("conf/config.yaml"), secrets=mock_secrets)
        mock_configure.assert_called_once_with(mock_config)
        self.assertEqual(audio_hw._state.output_volume, 1.0)
        mock_init_engine.assert_called_once_with(
            backend_type="piper",
            voice="it_IT-paola-medium",
            preroll_ms=100
        )
        mock_engine.say.assert_called_once_with("Ciao, come stai?")

    @patch("alexa_custom.tts.get_engine")
    @patch("alexa_custom.tts.init_engine")
    @patch("alexa_custom.audio_hw.configure")
    @patch("alexa_custom.config.load_config")
    @patch("alexa_custom.config.load_secrets")
    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_custom_volume(self, mock_exists, mock_load_secrets, mock_load_config, mock_configure, mock_init_engine, mock_get_engine):
        mock_exists.return_value = True

        mock_config = MagicMock()
        mock_config.tts.backend = "piper"
        mock_config.tts.voice = "it_IT-paola-medium"
        mock_config.tts.preroll_ms = 100
        mock_load_config.return_value = mock_config

        mock_secrets = MagicMock()
        mock_load_secrets.return_value = mock_secrets

        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        from alexa_custom.tts import main_say
        from alexa_custom import audio_hw
        
        main_say(["Ciao", "--volume", "50%"])
        self.assertEqual(audio_hw._state.output_volume, 0.5)

        main_say(["Ciao", "-v", "75"])
        self.assertEqual(audio_hw._state.output_volume, 0.75)

    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_invalid_volume(self, mock_exists):
        mock_exists.return_value = True
        
        from alexa_custom.tts import main_say
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main_say(["Ciao", "--volume", "invalid"])
            self.assertEqual(cm.exception.code, 2)
            
            with self.assertRaises(SystemExit) as cm:
                main_say(["Ciao", "--volume", "250%"])
            self.assertEqual(cm.exception.code, 2)

    @patch("alexa_custom.tts.time.sleep")
    @patch("alexa_custom.tts.get_engine")
    @patch("alexa_custom.tts.init_engine")
    @patch("alexa_custom.audio_hw.configure")
    @patch("alexa_custom.config.load_config")
    @patch("alexa_custom.config.load_secrets")
    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_loop(self, mock_exists, mock_load_secrets, mock_load_config, mock_configure, mock_init_engine, mock_get_engine, mock_sleep):
        mock_exists.return_value = True

        mock_config = MagicMock()
        mock_config.tts.backend = "piper"
        mock_config.tts.voice = "it_IT-paola-medium"
        mock_config.tts.preroll_ms = 100
        mock_load_config.return_value = mock_config

        mock_secrets = MagicMock()
        mock_load_secrets.return_value = mock_secrets

        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        # sleep raises KeyboardInterrupt to exit loop mode immediately
        mock_sleep.side_effect = KeyboardInterrupt()

        from alexa_custom.tts import main_say
        with patch("sys.stderr"):
            main_say(["Ciao", "--loop", "5"])

        mock_engine.say.assert_called_once_with("Ciao")
        mock_sleep.assert_called_once_with(5.0)

    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_invalid_loop(self, mock_exists):
        mock_exists.return_value = True
        
        from alexa_custom.tts import main_say
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main_say(["Ciao", "--loop", "invalid"])
            self.assertEqual(cm.exception.code, 2)
            
            with self.assertRaises(SystemExit) as cm:
                main_say(["Ciao", "--loop", "-5"])
            self.assertEqual(cm.exception.code, 2)

    @patch("alexa_custom.tts.Path.exists")
    def test_main_say_missing_config(self, mock_exists):
        mock_exists.return_value = False

        from alexa_custom.tts import main_say
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as cm:
                main_say(["Ciao", "--config", "conf"])
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
