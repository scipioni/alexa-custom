"""Tests for audio subprocess/playback hardening
(harden-serena-runtime group 7): subprocess timeouts, output-sink
invalidation on device reconnect, and play_wav_file failure logging."""

import subprocess
from unittest.mock import MagicMock, patch

import alexa_custom.audio_hw as audio_hw
import alexa_custom.audio_ops as audio_ops


class TestRestoreHwPcmTimeout:
    def test_timeout_expired_is_caught_and_logged(self, caplog):
        audio_hw._state.default_card_name = "TestCard"
        with (
            patch(
                "alexa_custom.audio_hw._find_alsa_card", return_value=(0, "TestCard")
            ),
            patch(
                "alexa_custom.audio_hw.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="amixer", timeout=5),
            ),
            caplog.at_level("WARNING"),
        ):
            audio_hw._restore_hw_pcm()  # must not raise
        assert any("timed out" in r.message for r in caplog.records)

    def test_amixer_call_has_a_timeout(self):
        audio_hw._state.default_card_name = "TestCard"
        with (
            patch(
                "alexa_custom.audio_hw._find_alsa_card", return_value=(0, "TestCard")
            ),
            patch("alexa_custom.audio_hw.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            audio_hw._restore_hw_pcm()
        assert mock_run.call_args.kwargs.get("timeout") == 5


class TestSetInputGainTimeout:
    def test_pactl_timeout_falls_back_without_raising(self, caplog):
        with (
            patch(
                "alexa_custom.audio_hw._find_pipewire_source",
                return_value="alsa_input.usb-test",
            ),
            patch("alexa_custom.audio_hw._restore_hw_pcm"),
            patch(
                "alexa_custom.audio_hw.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="pactl", timeout=5),
            ),
            caplog.at_level("WARNING"),
        ):
            audio_hw.set_input_gain(None, "usb", 1.0)  # must not raise
        assert any("timed out" in r.message for r in caplog.records)


class TestOutputSinkInvalidation:
    def setup_method(self):
        audio_hw._state.output_spec = "auto"
        audio_hw._state.output_sink = "alsa_output.usb-old-device"
        audio_hw._state.output_sink_dirty = False

    def test_get_output_sink_returns_cached_value_when_clean(self):
        assert audio_hw.get_output_sink() == "alsa_output.usb-old-device"

    def test_invalidate_marks_dirty_and_triggers_reresolve(self):
        audio_hw.invalidate_output_sink()
        assert audio_hw._state.output_sink_dirty is True

        with patch("alexa_custom.audio_hw.resolve_output_sink") as mock_resolve:

            def _set_new_sink(spec, retries=5, retry_delay=1.0):
                audio_hw._state.output_sink = "alsa_output.usb-new-device"
                return "alsa_output.usb-new-device"

            mock_resolve.side_effect = _set_new_sink
            sink = audio_hw.get_output_sink()

        mock_resolve.assert_called_once()
        assert sink == "alsa_output.usb-new-device"
        assert audio_hw._state.output_sink_dirty is False


class TestPlayWavFileLogsFailures:
    def test_nonzero_returncode_is_logged(self, caplog):
        with (
            patch(
                "alexa_custom.audio_ops.subprocess.run",
                return_value=MagicMock(returncode=1, stderr=b"target sink not found"),
            ),
            patch("alexa_custom.audio_ops.get_output_sink", return_value=None),
            patch("wave.open", side_effect=OSError("no such file")),
            caplog.at_level("ERROR"),
        ):
            audio_ops.play_wav_file("/tmp/does-not-matter.wav")
        assert any(
            "exited" in r.message or "failed" in r.message for r in caplog.records
        )
