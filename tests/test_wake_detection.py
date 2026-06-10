"""Unit tests for stage-1 Vosk wake-detection helpers.

Tests cover:
- _vosk_confidence: per-token confidence aggregation modes
- _vosk_check_result: RMS pre-gate and multi-token confidence gating
- Config parsing: confidence_mode validation
- build_intent_map: intent map construction from wake phrases × triggers
- _match_full_intent: exact partial-transcript intent matching
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alexa_custom.stt import _rms_level, _vosk_confidence, _vosk_check_result, _match_full_intent, _extract_wake_command
from alexa_custom.stt_phonetics import build_intent_map, _build_alias_map
from alexa_custom.config import WakeWordGroup, Trigger, STTStage1Config, _parse_stt_stage1_config  # noqa: F401


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


# ---------------------------------------------------------------------------
# build_intent_map
# ---------------------------------------------------------------------------


def _make_trigger(phrase: str, aliases: list[str] | None = None) -> Trigger:
    from alexa_custom.config import ActionEntry
    return Trigger(phrase=phrase, actions=[], aliases=aliases or [])


def _make_group_with_triggers(word: str, triggers: list[Trigger], aliases: list[str] | None = None) -> WakeWordGroup:
    return WakeWordGroup(word=word, aliases=aliases or [], triggers=triggers)


class TestBuildIntentMap:
    def _alias_map(self, groups):
        from alexa_custom.stt_phonetics import _build_alias_map
        return _build_alias_map(groups)

    def test_basic_combo(self):
        t = _make_trigger("chiama stefano")
        group = _make_group_with_triggers("ehi galileo", [t])
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [])
        assert "ehi galileo chiama stefano" in intent_map
        assert intent_map["ehi galileo chiama stefano"] == (group, t)

    def test_wake_alias_included(self):
        t = _make_trigger("accendi")
        group = _make_group_with_triggers("ehi galileo", [t], aliases=["galileo"])
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [])
        assert "galileo accendi" in intent_map
        assert "ehi galileo accendi" in intent_map

    def test_trigger_alias_included(self):
        t = _make_trigger("chiama stefano", aliases=["telefona stefano"])
        group = _make_group_with_triggers("galileo", [t])
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [])
        assert "galileo chiama stefano" in intent_map
        assert "galileo telefona stefano" in intent_map

    def test_per_group_triggers_shadow_globals(self):
        local_t = _make_trigger("comando locale")
        global_t = _make_trigger("comando globale")
        group = _make_group_with_triggers("galileo", [local_t])
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [global_t])
        # Both per-group and global appear (resolve_triggers appends global)
        assert "galileo comando locale" in intent_map
        assert "galileo comando globale" in intent_map

    def test_global_triggers_used_when_no_per_group(self):
        global_t = _make_trigger("chiama")
        group = WakeWordGroup(word="galileo")
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [global_t])
        assert "galileo chiama" in intent_map

    def test_empty_triggers_returns_empty(self):
        group = WakeWordGroup(word="galileo")
        am = self._alias_map([group])
        intent_map = build_intent_map(am, [])
        assert intent_map == {}


# ---------------------------------------------------------------------------
# _match_full_intent
# ---------------------------------------------------------------------------


class TestMatchFullIntent:
    def _setup(self):
        chiama = _make_trigger("chiama stefano")
        accendi = _make_trigger("accendi le luci", aliases=["illumina"])
        group = _make_group_with_triggers("ehi galileo", [chiama, accendi], aliases=["galileo"])
        from alexa_custom.stt_phonetics import _build_alias_map
        am = _build_alias_map([group])
        intent_map = build_intent_map(am, [])
        return am, intent_map, group, chiama, accendi

    def test_full_match_returns_tuple(self):
        am, intent_map, group, chiama, _ = self._setup()
        result = _match_full_intent("ehi galileo chiama stefano", am, intent_map)
        assert result is not None
        assert result[0] is group
        assert result[1] is chiama
        assert result[2] == "chiama stefano"

    def test_wake_only_returns_none(self):
        am, intent_map, _, _, _ = self._setup()
        assert _match_full_intent("ehi galileo", am, intent_map) is None

    def test_unknown_command_returns_none(self):
        am, intent_map, _, _, _ = self._setup()
        assert _match_full_intent("ehi galileo dimmi il meteo", am, intent_map) is None

    def test_trigger_alias_matched(self):
        am, intent_map, group, _, accendi = self._setup()
        result = _match_full_intent("ehi galileo illumina", am, intent_map)
        assert result is not None
        assert result[1] is accendi

    def test_wake_alias_matched(self):
        am, intent_map, group, chiama, _ = self._setup()
        result = _match_full_intent("galileo chiama stefano", am, intent_map)
        assert result is not None
        assert result[1] is chiama

    def test_fuzzy_not_applied(self):
        am, intent_map, _, _, _ = self._setup()
        # "ei galileo" is not in alias_map (fuzzy would catch it, exact doesn't)
        assert _match_full_intent("ei galileo chiama stefano", am, intent_map) is None

    def test_empty_partial_returns_none(self):
        am, intent_map, _, _, _ = self._setup()
        assert _match_full_intent("", am, intent_map) is None


# ---------------------------------------------------------------------------
# _extract_wake_command
# ---------------------------------------------------------------------------


class TestExtractWakeCommand:
    def _alias_map(self):
        group = WakeWordGroup(word="aiuto", aliases=["aiutami"])
        return _build_alias_map([group]), group

    def test_alias_prefix_of_word_not_consumed(self):
        # "aiutami" starts with "aiuto" but must match the alias exactly,
        # not yield "mi" as an inline command.
        am, group = self._alias_map()
        matched, cmd = _extract_wake_command("aiutami", am, fuzzy=False)
        assert matched is group
        assert cmd == ""

    def test_wake_word_alone(self):
        am, group = self._alias_map()
        matched, cmd = _extract_wake_command("aiuto", am, fuzzy=False)
        assert matched is group
        assert cmd == ""

    def test_wake_word_with_command(self):
        am, group = self._alias_map()
        matched, cmd = _extract_wake_command("aiuto fermati", am, fuzzy=False)
        assert matched is group
        assert cmd == "fermati"

    def test_alias_with_command(self):
        am, group = self._alias_map()
        matched, cmd = _extract_wake_command("aiutami fermati", am, fuzzy=False)
        assert matched is group
        assert cmd == "fermati"

    def test_no_match_returns_none(self):
        am, _ = self._alias_map()
        matched, cmd = _extract_wake_command("ciao mondo", am, fuzzy=False)
        assert matched is None
        assert cmd == ""
