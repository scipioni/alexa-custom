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
                "agc": True,
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
                "agc": True,
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
                noise_suppression=True, noise_suppression_level=1, agc=False
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
                action, listen_fn=mock_listen, actions_config=mock_cfg
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


# ── Stage-2 candidate construction ───────────────────────────────────────────


class TestCalibrationCandidates:
    def test_no_agc_candidate_by_default(self):
        from alexa_custom.actions import _gst_calibration_candidates

        cands = _gst_calibration_candidates(
            {"highpass_cutoff_hz": 220}, allow_agc=False
        )
        assert len(cands) == 3
        assert all(c["agc"] is False for c in cands), (
            "AGC must never be enabled by default — it garbles the first "
            "command after idle on hardware-DSP speakerphones"
        )

    def test_allow_agc_adds_one_candidate(self):
        from alexa_custom.actions import _gst_calibration_candidates

        cands = _gst_calibration_candidates({}, allow_agc=True)
        assert len(cands) == 4
        assert sum(1 for c in cands if c["agc"]) == 1

    def test_candidates_preserve_device_critical_params(self):
        from alexa_custom.actions import _gst_calibration_candidates

        base = {"highpass_cutoff_hz": 220, "source": "pulsesrc", "rms_threshold": 0.015}
        for c in _gst_calibration_candidates(base, allow_agc=False):
            assert c["highpass_cutoff_hz"] == 220
            assert c["source"] == "pulsesrc"
            assert c["rms_threshold"] == 0.015

    def test_simplest_candidate_first(self):
        from alexa_custom.actions import _gst_calibration_candidates

        cands = _gst_calibration_candidates({}, allow_agc=False)
        assert cands[0]["noise_suppression"] is False  # trust hardware DSP on ties


class TestAggregateScores:
    def test_min_is_worst_case(self):
        from alexa_custom.actions import _aggregate_scores

        assert _aggregate_scores([90.0, 40.0], "min") == 40.0

    def test_mean(self):
        from alexa_custom.actions import _aggregate_scores

        assert _aggregate_scores([90.0, 50.0], "mean") == 70.0

    def test_empty(self):
        from alexa_custom.actions import _aggregate_scores

        assert _aggregate_scores([], "min") == 0.0


# ── Calibration overrides take precedence over the named profile ─────────────


class TestOverridePrecedence:
    def _mk_config(self, profile_agc: bool):
        cfg = MagicMock()
        cfg.stt.capture_backend = "gstreamer"
        cfg.audio.gstreamer = GStreamerCaptureConfig(
            agc=profile_agc,
            profiles={"yealink": {"agc": profile_agc, "highpass_cutoff_hz": 220}},
        )
        return cfg

    def test_state_override_beats_profile(self):
        from alexa_custom import stt_gating

        cfg = self._mk_config(profile_agc=True)
        with (
            patch("alexa_custom.stt_gst_capture.start_capture_gst") as mock_start,
            patch(
                "alexa_custom.audio_hw.get_active_gst_profile", return_value="yealink"
            ),
            patch(
                "alexa_custom.audio_hw.load_gstreamer_overrides",
                return_value={"agc": False, "noise_suppression": True},
            ),
        ):
            stt_gating.start_capture("src", 1, config=cfg)
        gst_cfg = mock_start.call_args[0][1]
        assert gst_cfg.agc is False  # calibration override wins over profile
        assert gst_cfg.noise_suppression is True
        assert gst_cfg.highpass_cutoff_hz == 220  # profile keys stay

    def test_calibration_profile_ignores_state_override(self):
        # While probing, each candidate must control its own params.
        from alexa_custom import stt_gating

        cfg = self._mk_config(profile_agc=False)
        cfg.audio.gstreamer.profiles["calibration"] = {"agc": True}
        with (
            patch("alexa_custom.stt_gst_capture.start_capture_gst") as mock_start,
            patch(
                "alexa_custom.audio_hw.get_active_gst_profile",
                return_value="calibration",
            ),
            patch(
                "alexa_custom.audio_hw.load_gstreamer_overrides",
                return_value={"agc": False},
            ),
        ):
            stt_gating.start_capture("src", 1, config=cfg)
        gst_cfg = mock_start.call_args[0][1]
        assert gst_cfg.agc is True  # probe's own value, not the stale override


# ── Multi-condition end-to-end behaviour ─────────────────────────────────────


class TestMultiConditionCalibration:
    @pytest.mark.asyncio
    async def test_worst_case_aggregation_picks_far_robust_candidate(self, tmp_path):
        """Candidate 0 wins near but fails far; candidate 2 is decent in both.

        With aggregate: min the far-robust candidate must win.
        """
        state_file = tmp_path / "state.yaml"
        action = ActionEntry(
            type="calibrate_microphone_complete",
            params={"conditions": ["vicino", "lontano"], "settle_ms": 0},
        )
        sentence = "uno due tre quattro cinque"

        mock_cfg = MagicMock()
        mock_cfg.audio.gstreamer = GStreamerCaptureConfig()

        calls = {"n": 0}
        # Call order: 5 stage-1 near probes, 2 gain finalists on "lontano",
        # then stage 2: 3 candidates x near, 3 candidates x far.
        stage2_far = {8: "uno", 9: "uno due tre", 10: "uno due tre quattro"}

        async def fake_listen(timeout):
            calls["n"] += 1
            n = calls["n"]
            if n <= 7:
                return sentence  # gain stage: all perfect
            idx = n - 8
            if idx < 3:
                return sentence  # stage 2 near: all candidates perfect
            return stage2_far[idx - 3 + 8]  # stage 2 far: candidate 2 best

        with (
            patch.object(audio_hw, "_STATE_FILE", str(state_file)),
            patch("alexa_custom.audio_hw.set_input_gain"),
            patch("alexa_custom.audio_hw.set_active_gst_profile"),
            patch("alexa_custom.tts.get_engine", return_value=MagicMock()),
            patch("asyncio.sleep"),
        ):
            await handle_calibrate_microphone_complete(
                action, listen_fn=fake_listen, actions_config=mock_cfg
            )
            overrides = audio_hw.load_gstreamer_overrides()

        # Candidate 2 (ns level 2) has the best worst-case score
        assert overrides["noise_suppression"] is True
        assert overrides["noise_suppression_level"] == 2
        assert overrides["agc"] is False


# ── Interruption safety & per-trigger dispatch timeout ───────────────────────


class TestCalibrationInterruption:
    @pytest.mark.asyncio
    async def test_cancellation_restores_gain_and_profile(self, tmp_path):
        """A dispatch timeout cancels the coroutine mid-run: the original
        gain and GStreamer profile must be restored, not the probe values."""
        state_file = tmp_path / "state.yaml"
        action = ActionEntry(type="calibrate_microphone_complete", params={})

        async def hang_forever(timeout):
            await asyncio.sleep(3600)

        with (
            patch.object(audio_hw, "_STATE_FILE", str(state_file)),
            patch("alexa_custom.audio_hw.get_input_gain", return_value=1.5),
            patch(
                "alexa_custom.audio_hw.get_active_gst_profile",
                return_value="yealink",
            ),
            patch("alexa_custom.audio_hw.set_input_gain") as mock_set_gain,
            patch("alexa_custom.audio_hw.set_active_gst_profile") as mock_set_profile,
            patch("alexa_custom.tts.get_engine", return_value=MagicMock()),
        ):
            mock_cfg = MagicMock()
            mock_cfg.audio.gstreamer = GStreamerCaptureConfig()
            task = asyncio.ensure_future(
                handle_calibrate_microphone_complete(
                    action, listen_fn=hang_forever, actions_config=mock_cfg
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # Last calls must restore the snapshot, not leave probe state
            assert mock_set_gain.call_args[0][2] == 1.5
            assert mock_set_profile.call_args[0][0] == "yealink"


def test_trigger_dispatch_timeout_parsed():
    from alexa_custom.config import _parse_triggers

    triggers = _parse_triggers(
        [
            {
                "commands": ["calibra microfono"],
                "dispatch_timeout": 600,
                "actions": [{"type": "calibrate_microphone_complete"}],
            },
            {
                "commands": ["che ore sono"],
                "actions": [{"type": "say", "text": "ciao"}],
            },
        ],
        "test",
    )
    by_phrase = {t.phrase: t for t in triggers}
    assert by_phrase["calibra microfono"].dispatch_timeout == 600.0
    assert by_phrase["che ore sono"].dispatch_timeout is None
