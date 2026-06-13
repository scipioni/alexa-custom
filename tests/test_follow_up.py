"""Tests for follow-up conversation mode in _wake_detected / _follow_up_active."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    RecognitionConfig,
    Trigger,
    WakeWordGroup,
)
from alexa_custom.stt import _follow_up_active, _wake_detected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**recognition_kwargs) -> ActionsConfig:
    wake_group = WakeWordGroup(word="galileo")
    trigger = Trigger(
        phrase="accendi luce",
        actions=[ActionEntry(type="say", params={"text": "ok"})],
    )
    return ActionsConfig(
        wake_words=[wake_group],
        triggers=[trigger],
        recognition=RecognitionConfig(**recognition_kwargs),
    )


def _make_wake_detected_kwargs(
    config: ActionsConfig, *, pre_transcript: str = "accendi luce"
):
    loop = asyncio.new_event_loop()
    return dict(
        wake_group=config.wake_words[0],
        proc=MagicMock(),
        channels=1,
        backend=MagicMock(),
        config=config,
        stop_event=threading.Event(),
        telegram_client=MagicMock(),
        livekit_connect_fn=None,
        livekit_connected_flag=threading.Event(),
        on_stt_event=MagicMock(),
        mqtt_client=None,
        loop=loop,
        dispatch_loop=loop,
        pre_transcript=pre_transcript,
    )


def _run(config, pre_transcript, capture_side_effect, dispatch_side_effect=None):
    """Run _wake_detected with patched capture_transcript, dispatch, drain, and tone."""
    kwargs = _make_wake_detected_kwargs(config, pre_transcript=pre_transcript)
    drain_mock = MagicMock()
    tone_mock = MagicMock()

    dispatch_kwargs: dict = {}
    if dispatch_side_effect is not None:
        dispatch_kwargs["side_effect"] = dispatch_side_effect

    with (
        patch(
            "alexa_custom.stt.capture_transcript", side_effect=capture_side_effect
        ) as cap_mock,
        patch("alexa_custom.stt.dispatch", new_callable=AsyncMock, **dispatch_kwargs),
        patch("alexa_custom.stt._drain_pipe", drain_mock),
        patch("alexa_custom.stt.play_wake_beep", tone_mock),
    ):
        _wake_detected(**kwargs)

    return cap_mock, drain_mock, tone_mock


# ---------------------------------------------------------------------------
# _follow_up_active unit tests
# ---------------------------------------------------------------------------


class TestFollowUpActive:
    def _config(self, follow_up: bool) -> ActionsConfig:
        return _make_config(follow_up=follow_up)

    def test_disabled_by_default(self):
        config = self._config(follow_up=False)
        trigger = Trigger(phrase="x", actions=[ActionEntry(type="say", params={})])
        assert _follow_up_active(trigger, config) is False

    def test_enabled_globally(self):
        config = self._config(follow_up=True)
        trigger = Trigger(phrase="x", actions=[ActionEntry(type="say", params={})])
        assert _follow_up_active(trigger, config) is True

    def test_per_trigger_force_off_overrides_global_on(self):
        config = self._config(follow_up=True)
        trigger = Trigger(
            phrase="x", actions=[ActionEntry(type="say", params={})], follow_up=False
        )
        assert _follow_up_active(trigger, config) is False

    def test_per_trigger_force_on_overrides_global_off(self):
        config = self._config(follow_up=False)
        trigger = Trigger(
            phrase="x", actions=[ActionEntry(type="say", params={})], follow_up=True
        )
        assert _follow_up_active(trigger, config) is True

    def test_llm_chat_only_trigger_suppressed_even_when_global_on(self):
        config = self._config(follow_up=True)
        trigger = Trigger(phrase="x", actions=[ActionEntry(type="llm_chat", params={})])
        assert _follow_up_active(trigger, config) is False

    def test_mixed_actions_not_suppressed(self):
        config = self._config(follow_up=True)
        trigger = Trigger(
            phrase="x",
            actions=[
                ActionEntry(type="say", params={"text": "ok"}),
                ActionEntry(type="llm_chat", params={}),
            ],
        )
        assert _follow_up_active(trigger, config) is True

    def test_none_trigger_with_global_off(self):
        config = self._config(follow_up=False)
        assert _follow_up_active(None, config) is False

    def test_none_trigger_with_global_on(self):
        config = self._config(follow_up=True)
        assert _follow_up_active(None, config) is True


# ---------------------------------------------------------------------------
# Integration: _wake_detected follow-up loop behaviour
# ---------------------------------------------------------------------------


class TestWakeDetectedFollowUp:
    # 4.1 Follow-up disabled by default — no extra capture calls
    def test_disabled_by_default_no_follow_up(self):
        config = _make_config(follow_up=False)
        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=[],
        )
        cap_mock.assert_not_called()

    # 4.2 Follow-up enabled — second command dispatched without wake word
    def test_enabled_second_command_dispatched(self):
        config = _make_config(follow_up=True, follow_up_max_turns=3)
        dispatched = []

        async def _track(trigger, *a, **kw):
            dispatched.append(trigger.phrase)

        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=["accendi luce", ""],  # follow-up match, then silence
            dispatch_side_effect=_track,
        )
        assert cap_mock.call_count == 2  # follow-up capture + silence
        assert "accendi luce" in dispatched  # first command dispatched

    # 4.3 Silence closes the window
    def test_silence_closes_window(self):
        config = _make_config(follow_up=True, follow_up_max_turns=5)
        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=[""],  # immediate silence
        )
        assert cap_mock.call_count == 1

    # 4.4 Exit phrase closes the window without additional dispatch
    def test_exit_phrase_closes_window(self):
        config = _make_config(follow_up=True, follow_up_max_turns=5)
        dispatched = []

        async def _track(trigger, *a, **kw):
            dispatched.append(trigger.phrase)

        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=["basta"],
            dispatch_side_effect=_track,
        )
        assert cap_mock.call_count == 1
        # Only the first command dispatched; "basta" triggered no dispatch
        assert len([d for d in dispatched if d != "accendi luce"]) == 0

    # 4.5 max_turns cap
    def test_max_turns_cap(self):
        config = _make_config(follow_up=True, follow_up_max_turns=2)
        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=["accendi luce", "accendi luce", "accendi luce"],
        )
        assert cap_mock.call_count == 2

    # 4.6a Per-trigger override: follow_up: false suppresses when global on
    def test_per_trigger_false_suppresses_global_on(self):
        config = _make_config(follow_up=True)
        config.triggers[0] = Trigger(
            phrase="accendi luce",
            actions=[ActionEntry(type="say", params={"text": "ok"})],
            follow_up=False,
        )
        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=[],
        )
        cap_mock.assert_not_called()

    # 4.6b Per-trigger override: follow_up: true opens when global off
    def test_per_trigger_true_opens_global_off(self):
        config = _make_config(follow_up=False)
        config.triggers[0] = Trigger(
            phrase="accendi luce",
            actions=[ActionEntry(type="say", params={"text": "ok"})],
            follow_up=True,
        )
        cap_mock, _, _ = _run(
            config,
            pre_transcript="accendi luce",
            capture_side_effect=[""],  # silence closes immediately
        )
        assert cap_mock.call_count == 1

    # 4.7 Suppression during active LiveKit call
    def test_suppressed_during_livekit_call(self):
        config = _make_config(follow_up=True)
        kwargs = _make_wake_detected_kwargs(config, pre_transcript="accendi luce")
        kwargs["livekit_connected_flag"].set()  # simulate active call
        cap_mock = MagicMock()

        with (
            patch("alexa_custom.stt.capture_transcript", cap_mock),
            patch("alexa_custom.stt.dispatch", new_callable=AsyncMock),
            patch("alexa_custom.stt._drain_pipe"),
            patch("alexa_custom.stt.play_wake_beep"),
        ):
            _wake_detected(**kwargs)

        cap_mock.assert_not_called()

    # 4.8 Echo safety: _drain_pipe called before follow-up capture_transcript
    def test_drain_pipe_called_before_follow_up_capture(self):
        config = _make_config(follow_up=True, follow_up_max_turns=1)
        call_order: list[str] = []

        def _drain(proc, *a, **kw):
            call_order.append("drain")

        def _capture(*a, **kw):
            call_order.append("capture")
            return ""

        kwargs = _make_wake_detected_kwargs(config, pre_transcript="accendi luce")
        with (
            patch("alexa_custom.stt.capture_transcript", side_effect=_capture),
            patch("alexa_custom.stt.dispatch", new_callable=AsyncMock),
            patch("alexa_custom.stt._drain_pipe", side_effect=_drain),
            patch("alexa_custom.stt.play_wake_beep"),
        ):
            _wake_detected(**kwargs)

        # drain must appear before capture in the follow-up iteration
        assert "drain" in call_order
        assert "capture" in call_order
        drain_idx = call_order.index("drain")
        capture_idx = call_order.index("capture")
        assert drain_idx < capture_idx

    # 4.9 No-match follow-up routes to llm_chat when fallback_on_no_match enabled
    def test_no_match_follow_up_routes_to_llm_fallback(self):
        from alexa_custom.config import LLMConfig

        config = ActionsConfig(
            wake_words=[WakeWordGroup(word="galileo")],
            triggers=[
                Trigger(
                    phrase="accendi luce",
                    actions=[ActionEntry(type="say", params={"text": "ok"})],
                )
            ],
            recognition=RecognitionConfig(follow_up=True, follow_up_max_turns=1),
            llm=LLMConfig(
                backend="ollama",
                host="http://localhost:11434",
                fallback_on_no_match=True,
            ),
        )
        dispatched_phrases: list[str] = []

        async def _track(trigger, *a, **kw):
            dispatched_phrases.append(trigger.phrase)

        kwargs = _make_wake_detected_kwargs(config, pre_transcript="accendi luce")
        with (
            patch(
                "alexa_custom.stt.capture_transcript",
                side_effect=["qualcosa sconosciuto"],
            ),
            patch(
                "alexa_custom.stt.dispatch", new_callable=AsyncMock, side_effect=_track
            ),
            patch("alexa_custom.stt._drain_pipe"),
            patch("alexa_custom.stt.play_wake_beep"),
        ):
            _wake_detected(**kwargs)

        assert "__llm_fallback__" in dispatched_phrases


# ---------------------------------------------------------------------------
# 4.10 Config parsing: follow-up fields
# ---------------------------------------------------------------------------


class TestFollowUpConfigParsing:
    def test_defaults_when_absent(self):
        from alexa_custom.config import _parse_recognition_config

        cfg = _parse_recognition_config({})
        assert cfg.follow_up is False
        assert cfg.follow_up_timeout == 4.0
        assert cfg.follow_up_max_turns == 5
        assert cfg.follow_up_tone == "info"

    def test_fields_parsed_correctly(self):
        from alexa_custom.config import _parse_recognition_config

        cfg = _parse_recognition_config(
            {
                "follow_up": True,
                "follow_up_timeout": 3.0,
                "follow_up_max_turns": 4,
                "follow_up_tone": "success",
            }
        )
        assert cfg.follow_up is True
        assert cfg.follow_up_timeout == 3.0
        assert cfg.follow_up_max_turns == 4
        assert cfg.follow_up_tone == "success"

    def test_trigger_follow_up_none_when_absent(self):
        from alexa_custom.config import _parse_triggers

        triggers = _parse_triggers(
            [{"phrase": "ciao", "actions": [{"type": "say", "text": "ciao"}]}],
            "test",
        )
        assert triggers[0].follow_up is None

    def test_trigger_follow_up_false(self):
        from alexa_custom.config import _parse_triggers

        triggers = _parse_triggers(
            [
                {
                    "phrase": "ciao",
                    "follow_up": False,
                    "actions": [{"type": "say", "text": "ciao"}],
                }
            ],
            "test",
        )
        assert triggers[0].follow_up is False

    def test_trigger_follow_up_true(self):
        from alexa_custom.config import _parse_triggers

        triggers = _parse_triggers(
            [
                {
                    "phrase": "ciao",
                    "follow_up": True,
                    "actions": [{"type": "say", "text": "ciao"}],
                }
            ],
            "test",
        )
        assert triggers[0].follow_up is True
