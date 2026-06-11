import numpy as np
from unittest.mock import patch, MagicMock

import alexa_custom.audio as audio
import alexa_custom.audio_hw as audio_hw


def test_play_array_does_not_scale_by_output_volume():
    audio_hw._OUTPUT_VOLUME = 0.5

    test_audio = np.ones((100, 2), dtype=np.float32)

    with (
        patch("tempfile.mkstemp") as mock_mkstemp,
        patch("alexa_custom.audio_ops.subprocess.run"),
    ):
        mock_mkstemp.return_value = (999, "dummy_temp_path.wav")

        with (
            patch("alexa_custom.audio_ops.os.close"),
            patch("alexa_custom.audio_ops.os.unlink"),
            patch("wave.open") as mock_wave_open,
        ):
            mock_wf = MagicMock()
            mock_wave_open.return_value.__enter__.return_value = mock_wf

            audio._play_array(test_audio, 16000)

            mock_wf.writeframes.assert_called_once()
            written_bytes = mock_wf.writeframes.call_args[0][0]
            written_samples = np.frombuffer(written_bytes, dtype=np.int16)

            # Software scaling is removed — pipewire sink volume is the sole mechanism
            # Samples should pass through as full-scale: 32767 (not 16383)
            assert np.all(written_samples == 32767)


def test_play_wav_file_applies_volume():
    audio_hw._OUTPUT_VOLUME = 0.25
    audio._PW_PLAY = "/usr/bin/pw-play"

    with patch("alexa_custom.audio_ops.subprocess.run") as mock_run:
        audio.play_wav_file("some_file.wav")

        # Verify pw-play is called with --volume=0.2500
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--volume=0.2500" in cmd
