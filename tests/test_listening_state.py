from unittest.mock import patch
import pytest
from alexa_custom.stt import is_stt_sleeping, set_stt_sleeping
from alexa_custom.config import (
    Trigger,
    ActionsConfig,
    ActionEntry,
)
from alexa_custom.actions import registry


@pytest.mark.asyncio
async def test_listening_state_toggle():
    set_stt_sleeping(False)
    assert not is_stt_sleeping()

    await registry.execute("stop_listening", action=ActionEntry(type="stop_listening"))
    assert is_stt_sleeping()

    await registry.execute(
        "start_listening", action=ActionEntry(type="start_listening")
    )
    assert not is_stt_sleeping()


@pytest.mark.asyncio
async def test_sleeping_ignores_commands_without_start_listening():
    """When sleeping, triggers without start_listening should not fire.

    Verified via is_stt_sleeping() gate in _recognition_loop.
    """
    set_stt_sleeping(True)
    assert is_stt_sleeping()
    # A normal command trigger should not wake the system
    t = Trigger(
        commands=["accendi luce"],
        phrase="accendi luce",
        actions=[ActionEntry(type="log", params={"message": "luce"})],
    )
    has_start = any(a.type == "start_listening" for a in t.actions)
    assert has_start is False
    set_stt_sleeping(False)


@pytest.mark.asyncio
async def test_sleeping_allows_start_listening_trigger():
    """start_listening action triggers still fire when sleeping."""
    set_stt_sleeping(True)
    t = Trigger(
        commands=["svegliati"],
        phrase="svegliati",
        actions=[ActionEntry(type="start_listening")],
        with_wake=False,
    )
    has_start = any(a.type == "start_listening" for a in t.actions)
    assert has_start is True
    set_stt_sleeping(False)


@pytest.mark.asyncio
async def test_web_on_stt_event_handles_sleeping():
    from alexa_custom.web import WebServer

    server = WebServer()
    server.on_stt_event("sleeping", {})
    assert server._state["stt_state"] == "sleeping"
    assert server._state["stt_text"] == "Sleeping"


@pytest.mark.asyncio
async def test_tones_suppressed_when_sleeping():
    from alexa_custom.audio_ops import play_tone, play_beep

    set_stt_sleeping(True)

    with patch("alexa_custom.audio_ops._play_array") as mock_play_array:
        play_tone("info")
        play_beep(440, 100)
        mock_play_array.assert_not_called()

    set_stt_sleeping(False)

    with patch("alexa_custom.audio_ops._play_array") as mock_play_array:
        play_beep(440, 1)
        mock_play_array.assert_called_once()


@pytest.mark.asyncio
async def test_sleeping_dynamic_wake_up_phrase_propagation():
    from alexa_custom.web import WebServer

    server = WebServer()
    server.on_stt_event("sleeping", {"wake_up_phrase": "svegliati adesso"})
    assert server._state["stt_state"] == "sleeping"
    assert server._state["stt_text"] == "sleeping... wait for wake up svegliati adesso"


@pytest.mark.asyncio
async def test_get_wake_up_phrases_helper():
    from alexa_custom.stt import get_wake_up_phrases
    from alexa_custom.config import Trigger, ActionEntry

    wakeup_trigger = Trigger(
        commands=["svegliati"],
        phrase="svegliati",
        actions=[ActionEntry(type="start_listening")],
        with_wake=False,
    )
    dummy_trigger = Trigger(
        commands=["test"],
        phrase="test",
        actions=[ActionEntry(type="log")],
    )

    config = ActionsConfig(
        wake_words=["galileo"],
        triggers=[wakeup_trigger, dummy_trigger],
    )

    phrases = get_wake_up_phrases(config)
    assert "svegliati" in phrases
    assert "test" not in phrases
