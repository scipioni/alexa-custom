"""Unit tests for wake-detection helpers in the single-model design.

Tests cover:
- _rms_level: RMS amplitude calculation
- _match_wake_word: new flat-list wake-word matching helper
- _approx_wake_match: fuzzy WakeWordGroup-based matching (eval harness path)
- _parse_stt_config / _parse_recognition_config: config field parsing
- match_trigger_with_score: per-trigger min_word_overlap override
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alexa_custom.stt import _rms_level
from alexa_custom.stt_phonetics import (
    _match_wake_word,
    _approx_wake_match,
    _build_alias_map,
)
from alexa_custom.config import (
    WakeWordGroup,
    Trigger,
    _parse_stt_config,
    _parse_recognition_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcm(rms_target: float, n_samples: int = 4096) -> bytes:
    amplitude = int(rms_target * 32768)
    amplitude = max(0, min(32767, amplitude))
    samples = np.full(n_samples, amplitude, dtype=np.int16)
    return samples.tobytes()


# ---------------------------------------------------------------------------
# _rms_level
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
# _match_wake_word (new single-model helper)
# ---------------------------------------------------------------------------


class TestMatchWakeWord:
    def test_exact_prefix_match(self):
        phrase, residual = _match_wake_word("ehi galileo che ore sono", ["ehi galileo"])
        assert phrase == "ehi galileo"
        assert residual == "che ore sono"

    def test_exact_wake_word_only(self):
        phrase, residual = _match_wake_word("ehi galileo", ["ehi galileo"])
        assert phrase == "ehi galileo"
        assert residual == ""

    def test_no_match_returns_none(self):
        phrase, residual = _match_wake_word("buongiorno", ["ehi galileo"])
        assert phrase is None
        assert residual == ""

    def test_isolated_keyword_wakes_but_embedded_does_not(self):
        # The distinctive keyword said ALONE is an intentional address → wake
        # (corpus: truncated-wake recall). The same keyword embedded in longer
        # speech is conversation → all phrase words are required → no match.
        phrase, _ = _match_wake_word("galileo", ["ehi galileo"], threshold=0.5)
        assert phrase == "ehi galileo"
        phrase, _ = _match_wake_word("il galileo", ["ehi galileo"], threshold=0.5)
        assert phrase is None

    def test_serena_false_positive_rejected(self):
        # "serena" alone in a multi-word transcript must NOT fire "ehi serena".
        # This was the observed false-positive: 6/9 char score passed 0.5 but
        # "ehi" was never present.
        phrase, _ = _match_wake_word(
            "a ogni tanto controlliamo serena standard", ["ehi serena"]
        )
        assert phrase is None

    def test_fuzzy_both_words_match(self):
        # Both words present → match.
        phrase, _ = _match_wake_word("ehi serena", ["ehi serena"], threshold=0.5)
        assert phrase == "ehi serena"

    def test_ehi_transcribed_as_e(self):
        # Vosk (Italian) commonly emits the single vowel "e" for the interjection
        # "ehi". The per-word gate must accept this truncation so that "e serena"
        # still wakes on "ehi serena". Regression for b857c79.
        phrase, _ = _match_wake_word("e serena", ["ehi serena"], threshold=0.5)
        assert phrase == "ehi serena"

    def test_prefix_boundary_not_consumed_mid_word(self):
        # "aiuto" prefix of "aiutami" — should NOT match because no word boundary
        phrase, cmd = _match_wake_word("aiutami fermati", ["aiuto"])
        assert phrase is None or cmd != "fermati"

    def test_multiple_wake_words_first_exact_wins(self):
        phrase, residual = _match_wake_word(
            "assistente che ore sono", ["ehi galileo", "assistente"]
        )
        assert phrase == "assistente"
        assert residual == "che ore sono"

    def test_residual_stripping(self):
        phrase, residual = _match_wake_word(
            "ascolta assistente accendi la luce", ["ascolta assistente"]
        )
        assert phrase == "ascolta assistente"
        assert residual == "accendi la luce"

    def test_phonetic_variant_matches(self):
        # STT spells the wake word phonetically ("kiave" for "chiave"); the
        # phonetic-aware matcher accepts it where raw substring matching missed.
        phrase, _ = _match_wake_word("kiave apri", ["chiave"])
        assert phrase == "chiave"

    def test_esistente_ascolta_assistente_match(self):
        phrase, residual = _match_wake_word(
            "ascolta esistente attiva microfono normale", ["ascolta assistente"]
        )
        assert phrase == "ascolta assistente"
        assert residual == "attiva microfono normale"

    def test_midword_occurrence_no_longer_false_wakes(self):
        # "galileo" buried mid-word must NOT fire the wake word — prefix-anchored
        # matching rejects substring-anywhere hits that used to leak through.
        phrase, _ = _match_wake_word("scartagalileozzo", ["ehi galileo"])
        assert phrase is None

    def test_prefix_truncation_with_all_words(self):
        # STT truncation ("galile" for "galileo") recognised when "ehi" is also present.
        phrase, _ = _match_wake_word("ehi galile", ["ehi galileo"], threshold=0.5)
        assert phrase == "ehi galileo"


# ---------------------------------------------------------------------------
# _approx_wake_match (WakeWordGroup-based fuzzy, backward compat)
# ---------------------------------------------------------------------------


class TestApproxWakeMatchThreshold:
    def _alias_map(self, word: str) -> dict:
        return _build_alias_map([WakeWordGroup(word=word)])

    def test_single_word_of_two_word_phrase_no_longer_matches(self):
        # "galileo" alone is no longer enough — "ehi" must also be present.
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("il galileo", am, threshold=0.5) is None

    def test_both_words_required_for_fuzzy_match(self):
        # Both "ehi" and "galileo" present → match; missing either → no match.
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("ehi galileo accendi", am, threshold=0.5) is not None
        assert _approx_wake_match("il galileo", am, threshold=0.5) is None
        assert _approx_wake_match("ehi come stai", am, threshold=0.5) is None

    def test_short_component_alone_does_not_wake(self):
        # The short filler "ehi" (3 of 10 chars = 0.3) must not fire the wake on
        # its own at the default threshold — the key false-wake class.
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("ehi come stai", am, threshold=0.5) is None

    def test_both_words_always_match(self):
        am = self._alias_map("ehi galileo")
        assert _approx_wake_match("ehi galileo", am, threshold=0.7) is not None
        assert _approx_wake_match("ehi galileo", am, threshold=1.0) is not None


class TestApproxWakeMatchSubstring:
    def _alias_map(self, word: str) -> dict:
        return _build_alias_map([WakeWordGroup(word=word)])

    def test_short_fragment_does_not_trigger_via_reverse_substring(self):
        am = self._alias_map("galileo")
        assert _approx_wake_match("gali", am) is None

    def test_long_enough_fragment_still_matches(self):
        am = self._alias_map("galileo")
        assert _approx_wake_match("galile", am) is not None

    def test_exact_word_always_matches(self):
        am = self._alias_map("galileo")
        assert _approx_wake_match("galileo", am) is not None

    def test_midword_occurrence_does_not_match(self):
        # "galileo" embedded inside an unrelated word no longer matches via the
        # old substring-anywhere rule.
        am = self._alias_map("galileo")
        assert _approx_wake_match("exgalileox", am) is None

    def test_phonetic_variant_matches(self):
        # "chiave" → phonetic "kiave"; an STT "kiave" now matches.
        am = self._alias_map("chiave")
        assert _approx_wake_match("kiave", am) is not None


# ---------------------------------------------------------------------------
# Config parsing: STTConfig and RecognitionConfig fields
# ---------------------------------------------------------------------------


class TestSttConfigParsing:
    def test_defaults(self):
        cfg = _parse_stt_config({})
        assert cfg.backend == "vosk"
        assert cfg.vad_silence_ms == 900
        assert cfg.rms_threshold == pytest.approx(0.02)
        assert cfg.adaptive_rms is True
        assert cfg.wake_match_threshold == pytest.approx(0.5)

    def test_explicit_backend(self):
        cfg = _parse_stt_config({"backend": "vosk"})
        assert cfg.backend == "vosk"

    def test_explicit_vad_silence_ms(self):
        cfg = _parse_stt_config({"vad_silence_ms": 700})
        assert cfg.vad_silence_ms == 700

    def test_explicit_wake_match_threshold(self):
        cfg = _parse_stt_config({"wake_match_threshold": 0.7})
        assert cfg.wake_match_threshold == pytest.approx(0.7)

    def test_invalid_backend_raises(self):
        from alexa_custom.config import ConfigError

        with pytest.raises(ConfigError, match="stt.backend"):
            _parse_stt_config({"backend": "unknown"})

    def test_sherpa_onnx_backend_accepted(self):
        # sherpa-onnx became a valid stt.backend value in
        # openspec/changes/archive/2026-07-12-add-sherpa-onnx-stt-backend
        cfg = _parse_stt_config({"backend": "sherpa-onnx"})
        assert cfg.backend == "sherpa-onnx"


class TestRecognitionConfigParsing:
    def test_defaults(self):
        cfg = _parse_recognition_config({})
        assert cfg.wake_window == pytest.approx(8.0)
        assert cfg.follow_up is False
        assert cfg.follow_up_timeout == pytest.approx(4.0)
        assert cfg.follow_up_max_turns == 5
        assert cfg.follow_up_tone == "info"
        assert cfg.post_dispatch_cooldown_ms == 800
        assert cfg.min_cmd_words == 1
        assert cfg.min_word_overlap == pytest.approx(0.0)

    def test_explicit_wake_window(self):
        cfg = _parse_recognition_config({"wake_window": 12.0})
        assert cfg.wake_window == pytest.approx(12.0)

    def test_explicit_follow_up_fields(self):
        cfg = _parse_recognition_config(
            {"follow_up": True, "follow_up_timeout": 3.0, "follow_up_max_turns": 4}
        )
        assert cfg.follow_up is True
        assert cfg.follow_up_timeout == pytest.approx(3.0)
        assert cfg.follow_up_max_turns == 4

    def test_explicit_min_cmd_words(self):
        cfg = _parse_recognition_config({"min_cmd_words": 2})
        assert cfg.min_cmd_words == 2


# ---------------------------------------------------------------------------
# Per-trigger min_word_overlap override
# ---------------------------------------------------------------------------


class TestPerTriggerMinWordOverlap:
    def test_per_trigger_override_respected(self):
        from alexa_custom.actions import match_trigger_with_score
        from alexa_custom.config import ActionEntry

        tight = Trigger(
            commands=["chiama stefano"],
            phrase="chiama stefano",
            actions=[ActionEntry(type="livekit_join", params={})],
            min_word_overlap=1.0,
        )
        loose = Trigger(
            commands=["test"],
            phrase="test",
            actions=[ActionEntry(type="speak", params={})],
            min_word_overlap=None,
        )

        trig, _ = match_trigger_with_score(
            "ciao", [tight, loose], threshold=50.0, min_word_overlap=0.0
        )
        assert trig is loose or trig is None

    def test_per_trigger_override_none_uses_global(self):
        from alexa_custom.actions import match_trigger_with_score
        from alexa_custom.config import ActionEntry

        t = Trigger(
            commands=["che ora e"],
            phrase="che ora e",
            actions=[ActionEntry(type="speak", params={})],
            min_word_overlap=None,
        )
        trig, _ = match_trigger_with_score(
            "ciao", [t], threshold=50.0, min_word_overlap=1.0
        )
        assert trig is None
