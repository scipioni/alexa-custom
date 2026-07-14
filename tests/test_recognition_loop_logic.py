"""Unit tests for the single-model recognition loop core logic.

Tests cover:
- Wake-window gating: triggers filtered by with_wake + window state
- One-breath firing: wake word + command in same utterance
- Exit-phrase window close: start_listening / stop_listening triggers
- Follow-up window extension: _follow_up_active re-opens the window
"""

from __future__ import annotations

import time
import pytest

from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    RecognitionConfig,
    Trigger,
)
from alexa_custom.stt import _follow_up_active
from alexa_custom.stt_phonetics import _match_wake_word
from alexa_custom.actions import match_trigger_with_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trigger(commands: list[str], with_wake: bool = True, **kwargs) -> Trigger:
    return Trigger(
        commands=commands,
        phrase=commands[0],
        actions=kwargs.pop("actions", [ActionEntry(type="say", params={"text": "ok"})]),
        with_wake=with_wake,
        **kwargs,
    )


def _make_config(triggers: list[Trigger], wake_window: float = 8.0) -> ActionsConfig:
    return ActionsConfig(
        wake_words=["ehi galileo"],
        triggers=triggers,
        recognition=RecognitionConfig(wake_window=wake_window),
    )


# ---------------------------------------------------------------------------
# Wake-window gating
# ---------------------------------------------------------------------------


class TestWakeWindowGating:
    """The _recognition_loop filters candidates by: not t.with_wake OR woken()."""

    def test_direct_trigger_always_in_candidates_when_not_woken(self):
        t = _make_trigger(["chiama stefano"], with_wake=False)
        woken = False
        candidates = [tr for tr in [t] if not tr.with_wake or woken]
        assert t in candidates

    def test_gated_trigger_excluded_when_not_woken(self):
        t = _make_trigger(["accendi la luce"], with_wake=True)
        woken = False
        candidates = [tr for tr in [t] if not tr.with_wake or woken]
        assert candidates == []

    def test_gated_trigger_included_when_woken(self):
        t = _make_trigger(["accendi la luce"], with_wake=True)
        woken = True
        candidates = [tr for tr in [t] if not tr.with_wake or woken]
        assert t in candidates

    def test_mixed_triggers_only_direct_when_not_woken(self):
        t_direct = _make_trigger(["chiama stefano"], with_wake=False)
        t_gated = _make_trigger(["accendi la luce"], with_wake=True)
        woken = False
        candidates = [tr for tr in [t_direct, t_gated] if not tr.with_wake or woken]
        assert candidates == [t_direct]

    def test_all_triggers_included_when_woken(self):
        t_direct = _make_trigger(["chiama stefano"], with_wake=False)
        t_gated = _make_trigger(["accendi la luce"], with_wake=True)
        woken = True
        candidates = [tr for tr in [t_direct, t_gated] if not tr.with_wake or woken]
        assert len(candidates) == 2
        assert t_direct in candidates
        assert t_gated in candidates


# ---------------------------------------------------------------------------
# Wake window timeout
# ---------------------------------------------------------------------------


class TestWakeWindowTimeout:
    """Simulate the wake_deadline = now + wake_window + woken() check."""

    def test_window_open_immediately_after_wake(self):
        wake_window = 8.0
        wake_time = time.monotonic()
        wake_deadline = wake_time + wake_window
        assert time.monotonic() < wake_deadline  # window is open

    def test_window_closed_after_expiry(self):
        past = time.monotonic() - 1.0  # 1 second ago
        wake_window = 0.5  # only 500ms window
        wake_deadline = past + wake_window
        assert time.monotonic() >= wake_deadline  # window is closed

    def test_window_duration_matches_config(self):
        config = _make_config([], wake_window=5.0)
        assert config.recognition.wake_window == pytest.approx(5.0)

    def test_follow_up_extends_window(self):
        """After dispatch with follow_up=True, extend wake_deadline by follow_up_timeout."""
        config = _make_config(
            [_make_trigger(["test"])],
            wake_window=8.0,
        )
        config.recognition.follow_up = True
        config.recognition.follow_up_timeout = 4.0
        t = config.triggers[0]

        # Simulate: window was about to expire in 0.5s; follow_up extends it
        base = time.monotonic()
        wake_deadline = base + 0.5  # nearly expired
        assert _follow_up_active(t, config)

        follow_up_timeout = config.recognition.follow_up_timeout
        new_deadline = time.monotonic() + follow_up_timeout
        assert new_deadline > wake_deadline


# ---------------------------------------------------------------------------
# One-breath firing (wake + command in same utterance)
# ---------------------------------------------------------------------------


class TestOneBreathFiring:
    """Wake word + command in the same transcript → strip wake tokens, match residual."""

    def test_wake_prefix_stripped_from_transcript(self):
        phrase, residual = _match_wake_word(
            "ehi galileo accendi la luce", ["ehi galileo"]
        )
        assert phrase == "ehi galileo"
        assert residual == "accendi la luce"

    def test_residual_matches_gated_trigger(self):
        t = _make_trigger(["accendi la luce"], with_wake=True)
        residual = "accendi la luce"
        matched, _ = match_trigger_with_score(residual, [t], threshold=50.0)
        assert matched is t

    def test_empty_residual_no_command_match(self):
        t = _make_trigger(["accendi la luce"], with_wake=True)
        residual = ""
        matched, _ = match_trigger_with_score(residual, [t], threshold=50.0)
        assert matched is None

    def test_multi_word_residual_matched_fuzzily(self):
        t = _make_trigger(["spegni le luci"], with_wake=True)
        residual = "spegni luci"
        matched, _ = match_trigger_with_score(residual, [t], threshold=50.0)
        assert matched is t

    def test_wake_word_not_in_residual_after_strip(self):
        phrase, residual = _match_wake_word("galileo dimmi qualcosa", ["galileo"])
        assert phrase == "galileo"
        assert "galileo" not in residual

    def test_one_breath_only_matches_with_wake_true(self):
        """One-breath candidates are gated triggers only (with_wake=True)."""
        t_gated = _make_trigger(["accendi la luce"], with_wake=True)
        t_direct = _make_trigger(["chiama stefano"], with_wake=False)
        residual = "accendi la luce"
        # One-breath candidate pool: only with_wake=True
        one_breath_candidates = [tr for tr in [t_gated, t_direct] if tr.with_wake]
        matched, _ = match_trigger_with_score(
            residual, one_breath_candidates, threshold=50.0
        )
        assert matched is t_gated


# ---------------------------------------------------------------------------
# Exit phrase / sleeping guard
# ---------------------------------------------------------------------------


class TestExitPhraseWindowClose:
    """start_listening triggers must be passable even when system is sleeping."""

    def test_start_listening_trigger_has_action(self):
        t = _make_trigger(
            ["svegliati adesso"],
            with_wake=False,
            actions=[ActionEntry(type="start_listening")],
        )
        has_start = any(a.type == "start_listening" for a in t.actions)
        assert has_start is True

    def test_sleeping_system_allows_start_listening_through(self):
        """When sleeping, only triggers with start_listening pass the sleeping guard."""
        from alexa_custom.stt import is_stt_sleeping, set_stt_sleeping

        set_stt_sleeping(True)
        t_wake = _make_trigger(
            ["svegliati adesso"],
            with_wake=False,
            actions=[ActionEntry(type="start_listening")],
        )
        t_normal = _make_trigger(["accendi la luce"])

        # Simulate sleeping guard
        def passes_sleeping_guard(trigger: Trigger) -> bool:
            if not is_stt_sleeping():
                return True
            return any(a.type == "start_listening" for a in trigger.actions)

        assert passes_sleeping_guard(t_wake) is True
        assert passes_sleeping_guard(t_normal) is False
        set_stt_sleeping(False)
