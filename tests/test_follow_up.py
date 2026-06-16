"""Tests for follow-up conversation mode — _follow_up_active and config parsing."""

from __future__ import annotations

from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    RecognitionConfig,
    Trigger,
)
from alexa_custom.stt import _follow_up_active


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**recognition_kwargs) -> ActionsConfig:
    trigger = Trigger(
        commands=["accendi luce"],
        phrase="accendi luce",
        actions=[ActionEntry(type="say", params={"text": "ok"})],
    )
    return ActionsConfig(
        wake_words=["galileo"],
        triggers=[trigger],
        recognition=RecognitionConfig(**recognition_kwargs),
    )


# ---------------------------------------------------------------------------
# _follow_up_active unit tests
# ---------------------------------------------------------------------------


class TestFollowUpActive:
    def _config(self, follow_up: bool) -> ActionsConfig:
        return _make_config(follow_up=follow_up)

    def test_disabled_by_default(self):
        config = self._config(follow_up=False)
        trigger = Trigger(commands=["x"], actions=[ActionEntry(type="say", params={})])
        assert _follow_up_active(trigger, config) is False

    def test_enabled_globally(self):
        config = self._config(follow_up=True)
        trigger = Trigger(commands=["x"], actions=[ActionEntry(type="say", params={})])
        assert _follow_up_active(trigger, config) is True

    def test_per_trigger_force_off_overrides_global_on(self):
        config = self._config(follow_up=True)
        trigger = Trigger(
            commands=["x"], actions=[ActionEntry(type="say", params={})], follow_up=False
        )
        assert _follow_up_active(trigger, config) is False

    def test_per_trigger_force_on_overrides_global_off(self):
        config = self._config(follow_up=False)
        trigger = Trigger(
            commands=["x"], actions=[ActionEntry(type="say", params={})], follow_up=True
        )
        assert _follow_up_active(trigger, config) is True

    def test_llm_chat_only_trigger_suppressed_even_when_global_on(self):
        config = self._config(follow_up=True)
        trigger = Trigger(commands=["x"], actions=[ActionEntry(type="llm_chat", params={})])
        assert _follow_up_active(trigger, config) is False

    def test_mixed_actions_not_suppressed(self):
        config = self._config(follow_up=True)
        trigger = Trigger(
            commands=["x"],
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
# Config parsing: follow-up fields
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
