"""Unit tests for stage-1 Vosk wake-detection helpers.

Tests cover:
- _vosk_confidence: per-token confidence aggregation modes
- _vosk_check_result: RMS pre-gate and multi-token confidence gating
- Config parsing: confidence_mode validation
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alexa_custom.stt import _rms_level, _vosk_confidence, _vosk_check_result
from alexa_custom.config import WakeWordGroup, STTStage1Config, _parse_stt_stage1_config  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcm(rms_target: float, n_samples: int = 4096) -> bytes:
    """Return s16le PCM with approximately the given normalised RMS level."""
    amplitude = int(rms_target * 32768)
    amplitude = max(0, min(32767, amplitude))
    samples = np.full(n_samples, amplitude, dtype=np.int16)
    return samples.tobytes()


def _make_alias_map(words: list[str]) -> dict:
    from alexa_custom.stt import _build_alias_map

    return _build_alias_map([WakeWordGroup(word=w) for w in words])


# ---------------------------------------------------------------------------
# _vosk_confidence
# ---------------------------------------------------------------------------


class TestVoskConfidence:
    def _words(self, confs: list[float]) -> list[dict]:
        return [{"word": f"w{i}", "conf": c} for i, c in enumerate(confs)]

    def test_empty_words_returns_zero(self):
        assert _vosk_confidence([], "first") == 0.0
        assert _vosk_confidence([], "min") == 0.0
        assert _vosk_confidence([], "mean") == 0.0

    def test_first_mode_returns_first_token(self):
        words = self._words([0.9, 0.3, 0.7])
        assert _vosk_confidence(words, "first") == pytest.approx(0.9)

    def test_first_mode_single_token(self):
        words = self._words([0.75])
        assert _vosk_confidence(words, "first") == pytest.approx(0.75)

    def test_min_mode_returns_minimum(self):
        words = self._words([0.9, 0.3, 0.7])
        assert _vosk_confidence(words, "min") == pytest.approx(0.3)

    def test_mean_mode_returns_average(self):
        words = self._words([0.9, 0.3, 0.6])
        assert _vosk_confidence(words, "mean") == pytest.approx(0.6)

    def test_unknown_mode_falls_back_to_first(self):
        words = self._words([0.8, 0.2])
        assert _vosk_confidence(words, "unknown") == pytest.approx(0.8)

    def test_min_catches_weak_discriminative_token(self):
        # Simulates "ehi" (conf=0.95) + "galileo" (conf=0.20): min rejects it
        words = self._words([0.95, 0.20])
        assert _vosk_confidence(words, "first") == pytest.approx(0.95)  # passes
        assert _vosk_confidence(words, "min") == pytest.approx(
            0.20
        )  # would fail threshold


# ---------------------------------------------------------------------------
# _vosk_check_result
# ---------------------------------------------------------------------------


@pytest.fixture()
def alias_map():
    return _make_alias_map(["ehi galileo", "assistente"])


def _result(text: str, confs: list[float]) -> dict:
    words = [
        {"word": w, "conf": c, "start": i * 0.3, "end": (i + 1) * 0.3}
        for i, (w, c) in enumerate(zip(text.split(), confs))
    ]
    return {"text": text, "result": words}


class TestVoskCheckResult:
    def test_basic_wake_detected(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.9, 0.9])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is not None
        assert match.word == "ehi galileo"

    def test_rms_gate_rejects_quiet_chunk(self, alias_map):
        chunk = _make_pcm(0.005)  # below threshold 0.02
        result = _result("ehi galileo", [0.9, 0.9])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_rms_gate_disabled_at_zero(self, alias_map):
        chunk = _make_pcm(0.0)  # zero RMS
        result = _result("ehi galileo", [0.9, 0.9])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.0)
        assert match is not None

    def test_first_mode_ignores_weak_second_token(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.10])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is not None  # first mode: 0.90 >= 0.65 → passes

    def test_min_mode_rejects_weak_discriminative_token(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.10])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
        assert match is None  # min mode: min(0.90, 0.10) = 0.10 < 0.65 → rejected

    def test_mean_mode_rejects_average_below_threshold(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.30])  # mean = 0.60 < 0.65
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "mean", 0.02)
        assert match is None

    def test_mean_mode_accepts_average_above_threshold(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.50])  # mean = 0.70 >= 0.65
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "mean", 0.02)
        assert match is not None

    def test_non_wake_text_returns_none(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("buongiorno", [0.95])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_empty_text_returns_none(self, alias_map):
        chunk = _make_pcm(0.05)
        result = {"text": "", "result": []}
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_confidence_exactly_at_threshold_passes(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.65, 0.65])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
        assert match is not None

    def test_confidence_just_below_threshold_rejected(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.64, 0.64])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
        assert match is None


# ---------------------------------------------------------------------------
# RMS level helper
# ---------------------------------------------------------------------------


class TestRmsLevel:
    def test_silence_is_zero(self):
        assert _rms_level(bytes(4096)) == pytest.approx(0.0)

    def test_empty_is_zero(self):
        assert _rms_level(b"") == pytest.approx(0.0)

    def test_max_amplitude_is_one(self):
        samples = np.full(1024, 32767, dtype=np.int16)
        rms = _rms_level(samples.tobytes())
        assert rms == pytest.approx(1.0, abs=0.001)

    def test_rms_scales_with_amplitude(self):
        rms_high = _rms_level(_make_pcm(0.1))
        rms_low = _rms_level(_make_pcm(0.05))
        assert rms_high > rms_low


# ---------------------------------------------------------------------------
# Config parsing: confidence_mode
# ---------------------------------------------------------------------------


class TestConfidenceModeConfig:
    def _base(self, **kwargs) -> dict:
        return {"backend": "vosk", **kwargs}

    def test_default_is_first(self):
        cfg = _parse_stt_stage1_config(self._base())
        assert cfg.confidence_mode == "first"

    def test_explicit_min(self):
        cfg = _parse_stt_stage1_config(self._base(confidence_mode="min"))
        assert cfg.confidence_mode == "min"

    def test_explicit_mean(self):
        cfg = _parse_stt_stage1_config(self._base(confidence_mode="mean"))
        assert cfg.confidence_mode == "mean"

    def test_invalid_raises(self):
        from alexa_custom.config import ConfigError

        with pytest.raises(ConfigError, match="confidence_mode"):
            _parse_stt_stage1_config(self._base(confidence_mode="max"))
