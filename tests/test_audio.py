import numpy as np
from unittest.mock import patch, MagicMock

import alexa_custom.audio as audio


def test_play_array_scales_by_output_volume():
    # Set a custom output volume
    audio._OUTPUT_VOLUME = 0.5

    test_audio = np.ones((100, 2), dtype=np.float32)

    with (
        patch("tempfile.mkstemp") as mock_mkstemp,
        patch("alexa_custom.audio.subprocess.run"),
    ):
        # Mock mkstemp to return a dummy file descriptor and path
        mock_mkstemp.return_value = (999, "dummy_temp_path.wav")

        # Stub the os.close, wave.open and os.unlink
        with (
            patch("alexa_custom.audio.os.close"),
            patch("alexa_custom.audio.os.unlink"),
            patch("wave.open") as mock_wave_open,
        ):
            mock_wf = MagicMock()
            mock_wave_open.return_value.__enter__.return_value = mock_wf

            audio._play_array(test_audio, 16000)

            # Verify that wave.open's writeframes was called with the scaled array
            # Original test_audio was np.ones, so after scaling by 0.5, it becomes np.ones * 0.5
            # When converted to pcm16, 0.5 * 32767 = 16383 (rounded down)
            mock_wf.writeframes.assert_called_once()
            written_bytes = mock_wf.writeframes.call_args[0][0]
            written_samples = np.frombuffer(written_bytes, dtype=np.int16)

            # Every sample should be exactly 16383 (due to 0.5 volume scaling)
            assert np.all(written_samples == 16383)


def test_play_wav_file_applies_volume():
    audio._OUTPUT_VOLUME = 0.25
    audio._PW_PLAY = "/usr/bin/pw-play"

    with patch("alexa_custom.audio.subprocess.run") as mock_run:
        audio.play_wav_file("some_file.wav")

        # Verify pw-play is called with --volume=0.2500
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--volume=0.2500" in cmd
