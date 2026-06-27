import asyncio
import pytest
from unittest.mock import patch, MagicMock

from alexa_custom.config import ActionEntry, GStreamerCaptureConfig
import alexa_custom.audio_hw as audio_hw
from alexa_custom.actions import handle_calibrate_microphone_complete


# ── GStreamer Overrides Persistence & Configuration Round-trip ────────────────

class TestGStreamerOverridesPersistence:
    def test_overrides_roundtrip(self, tmp_path):
        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            overrides = {
                "noise_suppression": True,
                "noise_suppression_level": 2,
                "agc": True
            }
            audio_hw.save_gstreamer_overrides(overrides)
            result = audio_hw.load_gstreamer_overrides()
        assert result == overrides

    def test_configure_applies_overrides(self, tmp_path):
        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            overrides = {
                "noise_suppression": False,
                "noise_suppression_level": 3,
                "agc": True
            }
            audio_hw.save_gstreamer_overrides(overrides)

            # Create a mock ActionsConfig with audio.gstreamer
            mock_cfg = MagicMock()
            mock_cfg.audio.post_playback_ms = 300
            mock_cfg.audio.tone_preroll_ms = 50
            mock_cfg.audio.sample_rates = {"usb": 48000}
            mock_cfg.audio.card_name = "Yealink"
            mock_cfg.audio.output_volume = 0.5
            mock_cfg.audio.input_gain = 1.0
            mock_cfg.audio.output_device = "Yealink"
            
            # GStreamer actual config
            mock_cfg.audio.gstreamer = GStreamerCaptureConfig(
                noise_suppression=True,
                noise_suppression_level=1,
                agc=False
            )

            # Run configure
            audio_hw.configure(mock_cfg)

            # Assert overrides are correctly applied
            assert mock_cfg.audio.gstreamer.noise_suppression is False
            assert mock_cfg.audio.gstreamer.noise_suppression_level == 3
            assert mock_cfg.audio.gstreamer.agc is True


# ── Complete Calibration Action Execution ────────────────────────────────────

class TestCompleteCalibrationExecution:
    @pytest.mark.asyncio
    async def test_complete_calibration_runs_and_persists_settings(self, tmp_path):
        state_file = tmp_path / "state.yaml"
        action = ActionEntry(type="calibrate_microphone_complete", params={})

        # Mock listen_fn to return sample text mimicking speech
        mock_listen = MagicMock()
        # 5 times for Stage 1 (gain) + 3 times for Stage 2 (GStreamer params) = 8 total calls
        mock_listen.return_value = asyncio.Future()
        mock_listen.return_value.set_result("uno due tre quattro cinque")

        # Mock ActionsConfig
        mock_cfg = MagicMock()
        mock_cfg.audio.gstreamer = GStreamerCaptureConfig()

        with (
            patch.object(audio_hw, "_STATE_FILE", str(state_file)),
            patch("alexa_custom.audio_hw.set_input_gain") as mock_set_gain,
            patch("alexa_custom.audio_hw.set_active_gst_profile") as mock_set_profile,
            patch("alexa_custom.tts.get_engine") as mock_get_engine,
        ):
            # Setup TTS engine mock
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine

            # Run action
            await handle_calibrate_microphone_complete(
                action,
                listen_fn=mock_listen,
                actions_config=mock_cfg
            )

            # Verify gain was set
            mock_set_gain.assert_called()
            # Verify profile changes (includes 'calibration' and restoring the original)
            mock_set_profile.assert_called()

            # Verify persistence files are created
            assert state_file.exists()
            
            # Load state and verify results
            saved_gain = audio_hw.load_input_gain_state()
            saved_overrides = audio_hw.load_gstreamer_overrides()

            assert saved_gain is not None
            assert saved_overrides is not None
            assert "noise_suppression" in saved_overrides
            assert "agc" in saved_overrides
