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

from alexa_custom.stt import (
    _rms_level,
    _vosk_confidence,
    _vosk_check_result,
    _match_full_intent,
    _extract_wake_command,
)
from alexa_custom.stt_phonetics import build_intent_map, _build_alias_map, _approx_wake_match
from alexa_custom.config import (
    WakeWordGroup,
    Trigger,
    _parse_stt_stage1_config,
    _parse_recognition_config,
)  # noqa: F401


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
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is not None
        assert match.word == "ehi galileo"

    def test_rms_gate_rejects_quiet_chunk(self, alias_map):
        chunk = _make_pcm(0.005)  # below threshold 0.02
        result = _result("ehi galileo", [0.9, 0.9])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_rms_gate_disabled_at_zero(self, alias_map):
        chunk = _make_pcm(0.0)  # zero RMS
        result = _result("ehi galileo", [0.9, 0.9])
        match = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.0)
        assert match is not None

    def test_first_mode_ignores_weak_second_token(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.10])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is not None  # first mode: 0.90 >= 0.65 → passes

    def test_min_mode_rejects_weak_discriminative_token(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.10])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
        assert match is None  # min mode: min(0.90, 0.10) = 0.10 < 0.65 → rejected

    def test_mean_mode_rejects_average_below_threshold(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.30])  # mean = 0.60 < 0.65
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "mean", 0.02)
        assert match is None

    def test_mean_mode_accepts_average_above_threshold(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.90, 0.50])  # mean = 0.70 >= 0.65
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "mean", 0.02)
        assert match is not None

    def test_non_wake_text_returns_none(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("buongiorno", [0.95])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_empty_text_returns_none(self, alias_map):
        chunk = _make_pcm(0.05)
        result = {"text": "", "result": []}
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "first", 0.02)
        assert match is None

    def test_confidence_exactly_at_threshold_passes(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.65, 0.65])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
        assert match is not None

    def test_confidence_just_below_threshold_rejected(self, alias_map):
        chunk = _make_pcm(0.05)
        result = _result("ehi galileo", [0.64, 0.64])
        match, _ = _vosk_check_result(chunk, result, alias_map, 0.65, "min", 0.02)
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
    return Trigger(phrase=phrase, actions=[], aliases=aliases or [])


def _make_group_with_triggers(
    word: str, triggers: list[Trigger], aliases: list[str] | None = None
) -> WakeWordGroup:
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
        group = _make_group_with_triggers(
            "ehi galileo", [chiama, accendi], aliases=["galileo"]
        )
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

    def test_vosk_path_uses_exact_matching(self):
        # Vosk stage-1 calls _extract_wake_command with fuzzy=False.
        # "ascolta assistente" shares a content word with "ascoltami assistente"
        # but must NOT match — Vosk transcribes accurately so fuzzy is wrong here.
        from alexa_custom.stt_phonetics import _build_alias_map as bam

        group = WakeWordGroup(word="ascoltami assistente")
        am = bam([group])
        matched, cmd = _extract_wake_command("ascolta assistente", am, fuzzy=False)
        assert matched is None


# ---------------------------------------------------------------------------
# _approx_wake_match configurable threshold
# ---------------------------------------------------------------------------


class TestApproxWakeMatchThreshold:
    def _alias_map(self, word: str) -> dict:
        return _build_alias_map([WakeWordGroup(word=word)])

    def test_single_word_of_two_word_phrase_matches_at_default(self):
        # "galileo" alone scores 1/2 = 0.5 for "ehi galileo" → matches default 0.5
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("il galileo", am, threshold=0.5) is not None

    def test_single_word_of_two_word_phrase_rejected_at_higher_threshold(self):
        # 1/2 = 0.5 < 0.7 → no match
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("il galileo", am, threshold=0.7) is None

    def test_both_words_always_match(self):
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("ehi galileo", am, threshold=0.7) is not None
        assert _approx_wake_match("ehi galileo", am, threshold=1.0) is not None

    def test_extract_wake_command_passes_threshold(self):
        am = self._alias_map("ehi galileo")
        # At threshold=0.7, one-word transcript should not match
        matched, _ = _extract_wake_command("il galileo ciao", am, fuzzy=True, wake_match_threshold=0.7)
        assert matched is None
        # At threshold=0.5, it should match
        matched, _ = _extract_wake_command("il galileo ciao", am, fuzzy=True, wake_match_threshold=0.5)
        assert matched is not None


# ---------------------------------------------------------------------------
# New config fields: wake_match_threshold, max_partial_words, min_word_overlap
# ---------------------------------------------------------------------------


class TestNewConfigFields:
    def _stage1_base(self, **kwargs) -> dict:
        return {"backend": "vosk", **kwargs}

    def _recognition_base(self, **kwargs) -> dict:
        return {**kwargs}

    def test_wake_match_threshold_default(self):
        cfg = _parse_stt_stage1_config(self._stage1_base())
        assert cfg.wake_match_threshold == 0.5

    def test_wake_match_threshold_explicit(self):
        cfg = _parse_stt_stage1_config(self._stage1_base(wake_match_threshold=0.7))
        assert cfg.wake_match_threshold == pytest.approx(0.7)

    def test_max_partial_words_default_is_8(self):
        cfg = _parse_stt_stage1_config(self._stage1_base())
        assert cfg.max_partial_words == 8

    def test_max_partial_words_explicit_zero_disables(self):
        cfg = _parse_stt_stage1_config(self._stage1_base(max_partial_words=0))
        assert cfg.max_partial_words == 0

    def test_min_word_overlap_default(self):
        cfg = _parse_recognition_config(self._recognition_base())
        assert cfg.min_word_overlap == pytest.approx(0.0)

    def test_min_word_overlap_explicit(self):
        cfg = _parse_recognition_config(self._recognition_base(min_word_overlap=0.5))
        assert cfg.min_word_overlap == pytest.approx(0.5)

    def test_keywords_threshold_default_is_0_35(self):
        cfg = _parse_stt_stage1_config(self._stage1_base())
        assert cfg.keywords_threshold == pytest.approx(0.35)

    def test_post_dispatch_cooldown_default(self):
        cfg = _parse_recognition_config(self._recognition_base())
        assert cfg.post_dispatch_cooldown_ms == 800

    def test_min_cmd_words_default(self):
        cfg = _parse_recognition_config(self._recognition_base())
        assert cfg.min_cmd_words == 1

    def test_min_cmd_words_explicit(self):
        cfg = _parse_recognition_config(self._recognition_base(min_cmd_words=2))
        assert cfg.min_cmd_words == 2


# ---------------------------------------------------------------------------
# _approx_wake_match reverse-substring tightening
# ---------------------------------------------------------------------------


class TestApproxWakeMatchSubstring:
    def _alias_map(self, word: str) -> dict:
        return _build_alias_map([WakeWordGroup(word=word)])

    def test_short_fragment_does_not_trigger_via_reverse_substring(self):
        # "gali" is 4 chars but only 4/7 = 57% of "galileo" — below 70% threshold
        am = self._alias_map("galileo")
        assert _approx_wake_match("gali", am) is None

    def test_long_enough_fragment_still_matches(self):
        # "galile" is 6/7 = 86% of "galileo" — above 70% threshold
        am = self._alias_map("galileo")
        assert _approx_wake_match("galile", am) is not None

    def test_exact_word_always_matches(self):
        am = self._alias_map("galileo")
        assert _approx_wake_match("galileo", am) is not None


# ---------------------------------------------------------------------------
# Per-trigger min_word_overlap override
# ---------------------------------------------------------------------------


class TestPerTriggerMinWordOverlap:
    def test_per_trigger_override_respected(self):
        from alexa_custom.actions import match_trigger_with_score
        from alexa_custom.config import ActionEntry

        tight = Trigger(
            phrase="chiama stefano",
            actions=[ActionEntry(type="livekit_join", params={})],
            min_word_overlap=1.0,
        )
        loose = Trigger(
            phrase="test",
            actions=[ActionEntry(type="speak", params={})],
            min_word_overlap=None,
        )

        # "ciao" shares no phonetic tokens with "chiama stefano" → tight trigger blocked
        trig, _ = match_trigger_with_score("ciao", [tight, loose], threshold=50.0, min_word_overlap=0.0)
        assert trig is loose or trig is None  # tight must not win

    def test_per_trigger_override_None_uses_global(self):
        from alexa_custom.actions import match_trigger_with_score
        from alexa_custom.config import ActionEntry

        t = Trigger(
            phrase="che ora e",
            actions=[ActionEntry(type="speak", params={})],
            min_word_overlap=None,
        )
        # global min_word_overlap=1.0, no phonetic tokens of trigger in "ciao" → blocked
        trig, _ = match_trigger_with_score("ciao", [t], threshold=50.0, min_word_overlap=1.0)
        assert trig is None
