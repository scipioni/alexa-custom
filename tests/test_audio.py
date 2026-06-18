import numpy as np
import pytest
from unittest.mock import patch, MagicMock

import alexa_custom.audio as audio
import alexa_custom.audio_hw as audio_hw


def test_play_array_scales_by_output_volume():
    audio_hw._state.output_volume = 0.5

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

            # Digital gain is applied at the application layer — samples
            # are scaled by the output volume before writing the WAV
            assert np.all(written_samples == 16383)


def test_play_array_full_volume_passthrough():
    audio_hw._state.output_volume = 1.0

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

            # At full volume, samples pass through unattenuated
            assert np.all(written_samples == 32767)


def test_play_wav_file_no_volume_flag():
    audio_hw._state.output_volume = 0.25
    audio._PW_PLAY = "/usr/bin/pw-play"

    with patch("alexa_custom.audio_ops.subprocess.run") as mock_run:
        audio.play_wav_file("some_file.wav")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--volume=" not in cmd
        assert "some_file.wav" in cmd


def test_set_output_volume_no_longer_calls_wpctl():
    audio_hw._state.output_volume = 0.5

    with patch("subprocess.run") as mock_run:
        audio_hw.set_output_volume(None, "pipewire", 0.3)

        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            assert "wpctl" not in cmd, f"wpctl found in command: {cmd}"


def test_set_input_gain_calls_pactl_when_source_found():
    audio_hw._state.input_gain = 1.0

    mock_source = MagicMock()
    mock_source.name = "alsa_input.usb-0a12_NewPie_SABINESMICDFU-00.analog-stereo"
    mock_source.description = "NewPie Audio"

    mock_pulse_instance = MagicMock()
    mock_pulse_instance.source_list.return_value = [mock_source]
    mock_pulse_instance.__enter__ = MagicMock(return_value=mock_pulse_instance)
    mock_pulse_instance.__exit__ = MagicMock(return_value=False)

    with (
        patch("pulsectl.Pulse", return_value=mock_pulse_instance),
        patch("subprocess.run") as mock_run,
        patch.object(audio_hw, "_restore_hw_pcm"),
    ):
        audio_hw.set_input_gain(None, "NewPie", 1.5)

        pactl_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "pactl"]
        assert len(pactl_calls) == 1, f"Expected 1 pactl call, got {len(pactl_calls)}"
        pactl_cmd = pactl_calls[0][0][0]
        assert "set-source-volume" in pactl_cmd
        assert "150%" in pactl_cmd
        assert audio_hw.get_input_gain() == 1.5


def test_set_input_gain_noop_when_source_not_found():
    audio_hw._state.input_gain = 1.0

    mock_pulse_instance = MagicMock()
    mock_pulse_instance.source_list.return_value = []
    mock_pulse_instance.__enter__ = MagicMock(return_value=mock_pulse_instance)
    mock_pulse_instance.__exit__ = MagicMock(return_value=False)

    with (
        patch("pulsectl.Pulse", return_value=mock_pulse_instance),
        patch("subprocess.run") as mock_run,
        patch.object(audio_hw, "_restore_hw_pcm"),
    ):
        audio_hw.set_input_gain(None, "NonExistentDevice", 2.0)

        pactl_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "pactl"]
        assert len(pactl_calls) == 0, f"Expected 0 pactl calls, got {pactl_calls}"
        assert audio_hw.get_input_gain() == 2.0


def test_restore_hw_pcm_noop_without_newpie():
    with patch.object(audio_hw, "_find_alsa_card", return_value=None):
        with patch("subprocess.run") as mock_run:
            audio_hw._restore_hw_pcm()

            amixer_calls = [
                c for c in mock_run.call_args_list if c[0][0][0] == "amixer"
            ]
            assert len(amixer_calls) == 0, (
                f"Expected 0 amixer calls, got {amixer_calls}"
            )


def test_restore_hw_pcm_calls_amixer_when_newpie_found():
    with (
        patch.object(audio_hw, "get_default_card_name", return_value="NewPie"),
        patch.object(audio_hw, "_find_alsa_card", return_value=(2, "NewPie")),
        patch("subprocess.run") as mock_run,
    ):
        audio_hw._restore_hw_pcm()

        amixer_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "amixer"]
        assert len(amixer_calls) == 1
        amixer_cmd = amixer_calls[0][0][0]
        assert "amixer" in amixer_cmd
        assert "-c" in amixer_cmd
        assert "2" in amixer_cmd
        assert "PCM" in amixer_cmd
        assert "100%" in amixer_cmd


def test_configure_propagates_to_globals(monkeypatch):
    monkeypatch.setattr("alexa_custom.audio_hw.load_volume_state", lambda: None)
    monkeypatch.setattr("alexa_custom.audio_hw.load_input_gain_state", lambda: None)
    fake_audio = MagicMock()
    fake_audio.post_playback_ms = 200
    fake_audio.tone_preroll_ms = 400
    fake_audio.sample_rates = {"usb": 44100, "bluetooth": 16000}
    fake_audio.card_name = "ConferenceCam"
    fake_audio.output_volume = 0.35
    fake_audio.input_gain = 1.8

    fake_cfg = MagicMock()
    fake_cfg.audio = fake_audio

    audio_hw.configure(fake_cfg)

    assert audio_hw.get_output_volume() == 0.35
    assert audio_hw.get_input_gain() == 1.8
    assert audio_hw.get_post_playback_ms() == 200
    assert audio_hw.get_tone_preroll_ms() == 400
    assert audio_hw.get_default_card_name() == "ConferenceCam"
    assert audio_hw.get_sample_rates() == {"usb": 44100, "bluetooth": 16000}


def test_pulse_session_restores_pcm_on_success():
    fake_pulse = MagicMock()
    with (
        patch("alexa_custom.audio_hw.pulsectl.Pulse", return_value=fake_pulse),
        patch("alexa_custom.audio_hw._restore_hw_pcm") as mock_restore,
    ):
        with audio_hw.pulse_session("test") as p:
            assert p is fake_pulse
    fake_pulse.close.assert_called_once()
    mock_restore.assert_called_once()


def test_pulse_session_restores_pcm_on_exception():
    fake_pulse = MagicMock()
    with (
        patch("alexa_custom.audio_hw.pulsectl.Pulse", return_value=fake_pulse),
        patch("alexa_custom.audio_hw._restore_hw_pcm") as mock_restore,
    ):
        with pytest.raises(RuntimeError):
            with audio_hw.pulse_session("test"):
                raise RuntimeError("boom")
    # PCM must be restored even when the body raises.
    fake_pulse.close.assert_called_once()
    mock_restore.assert_called_once()


def test_get_software_input_gain_hardware_vs_software_scaling():
    # 1. When hardware gain succeeded
    audio_hw._state.input_gain = 0.85
    audio_hw._state.hw_gain_applied = True
    assert audio_hw.get_input_gain() == 0.85
    assert audio_hw.get_software_input_gain() == 1.0

    # 2. When hardware gain failed (software scaling fallback)
    audio_hw._state.hw_gain_applied = False
    assert audio_hw.get_input_gain() == 0.85
    assert audio_hw.get_software_input_gain() == 0.85


def test_set_input_gain_sets_hw_gain_applied_correctly():
    mock_source = MagicMock()
    mock_source.name = "alsa_input.usb-0a12_NewPie_SABINESMICDFU-00.analog-stereo"
    mock_source.description = "NewPie Audio"

    mock_pulse_instance = MagicMock()
    mock_pulse_instance.source_list.return_value = [mock_source]
    mock_pulse_instance.__enter__ = MagicMock(return_value=mock_pulse_instance)
    mock_pulse_instance.__exit__ = MagicMock(return_value=False)

    # Success scenario (subprocess.run returncode = 0)
    mock_res_success = MagicMock()
    mock_res_success.returncode = 0

    with (
        patch("pulsectl.Pulse", return_value=mock_pulse_instance),
        patch("subprocess.run", return_value=mock_res_success),
        patch.object(audio_hw, "_restore_hw_pcm"),
    ):
        audio_hw.set_input_gain(None, "NewPie", 0.75)
        assert audio_hw.get_input_gain() == 0.75
        assert audio_hw.get_software_input_gain() == 1.0  # Hardware success -> bypass software scaling

    # Failure scenario (subprocess.run returncode = 1)
    mock_res_failure = MagicMock()
    mock_res_failure.returncode = 1
    mock_res_failure.stderr = b"error"

    with (
        patch("pulsectl.Pulse", return_value=mock_pulse_instance),
        patch("subprocess.run", return_value=mock_res_failure),
        patch.object(audio_hw, "_restore_hw_pcm"),
    ):
        audio_hw.set_input_gain(None, "NewPie", 0.75)
        assert audio_hw.get_input_gain() == 0.75
        assert audio_hw.get_software_input_gain() == 0.75  # Hardware failed -> use software scaling fallback
