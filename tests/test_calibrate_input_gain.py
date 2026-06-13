import asyncio
import pytest
from unittest.mock import patch

from alexa_custom.actions import (
    _calibration_winner,
    _calibration_round2_gains,
)
from alexa_custom.config import ActionEntry


# ── _calibration_winner() ────────────────────────────────────────────────────


class TestCalibrationWinner:
    def test_picks_highest_score(self):
        scores = {0.4: 50.0, 0.7: 80.0, 1.2: 60.0}
        assert _calibration_winner(scores) == 0.7

    def test_tie_prefers_lower_gain(self):
        scores = {0.4: 80.0, 0.7: 80.0, 1.2: 60.0}
        assert _calibration_winner(scores) == 0.4

    def test_all_zero_scores_picks_lowest(self):
        scores = {0.4: 0.0, 0.7: 0.0, 1.2: 0.0}
        assert _calibration_winner(scores) == 0.4

    def test_single_entry(self):
        scores = {0.9: 75.0}
        assert _calibration_winner(scores) == 0.9


# ── _calibration_round2_gains() ──────────────────────────────────────────────


class TestCalibrationRound2Gains:
    def test_correct_half_step(self):
        # half_step = (1.2 - 0.4) / 6 = 0.8 / 6 ≈ 0.1333
        gains = _calibration_round2_gains(0.7, 0.4, 1.2)
        half = (1.2 - 0.4) / 6.0
        assert gains[0] == pytest.approx(0.7 - half)
        assert gains[1] == pytest.approx(0.7 + half)

    def test_clamps_at_zero(self):
        # winner at the very bottom, lower probe would go negative
        gains = _calibration_round2_gains(0.05, 0.0, 1.2)
        assert gains[0] == 0.0

    def test_no_clamp_needed_for_upper(self):
        gains = _calibration_round2_gains(0.7, 0.4, 1.2)
        assert gains[1] > 0.7


# ── handle_calibrate_input_gain guard ────────────────────────────────────────


class TestCalibrateInputGainNoListenFn:
    def test_returns_without_side_effects_when_no_listen_fn(self):
        from alexa_custom.actions import handle_calibrate_input_gain

        action = ActionEntry(type="calibrate_input_gain", params={})

        with (
            patch("alexa_custom.audio_hw.set_input_gain") as mock_set,
            patch("alexa_custom.audio_hw.save_input_gain_config") as mock_save,
        ):
            asyncio.run(handle_calibrate_input_gain(action, listen_fn=None))
            mock_set.assert_not_called()
            mock_save.assert_not_called()


# ── save_input_gain_config / load_input_gain_state round-trip ─────────────────


class TestInputGainPersistence:
    def test_roundtrip(self, tmp_path):
        import alexa_custom.audio_hw as audio_hw

        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            audio_hw.save_input_gain_config(0.85)
            result = audio_hw.load_input_gain_state()
        assert result == pytest.approx(0.85)

    def test_missing_key_returns_none(self, tmp_path):
        import alexa_custom.audio_hw as audio_hw

        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            audio_hw.save_volume_config(0.5)  # writes output_volume only
            result = audio_hw.load_input_gain_state()
        assert result is None

    def test_does_not_clobber_volume(self, tmp_path):
        import alexa_custom.audio_hw as audio_hw

        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            audio_hw.save_volume_config(0.6)
            audio_hw.save_input_gain_config(0.9)
            vol = audio_hw.load_volume_state()
            gain = audio_hw.load_input_gain_state()
        assert vol == pytest.approx(0.6)
        assert gain == pytest.approx(0.9)

    def test_no_state_file_returns_none(self, tmp_path):
        import alexa_custom.audio_hw as audio_hw

        state_file = tmp_path / "nonexistent.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            assert audio_hw.load_input_gain_state() is None
