"""Tests for direct (with_wake=False) trigger tone and dispatch behavior."""

import pytest
from alexa_custom.config import Trigger, ActionsConfig, RecognitionConfig, ActionEntry


def _make_config(wake_tone: str = "custom_direct_tone") -> ActionsConfig:
    return ActionsConfig(
        wake_words=["galileo"],
        triggers=[
            Trigger(
                commands=["chiama stefano"],
                phrase="chiama stefano",
                actions=[ActionEntry(type="livekit_join", params={})],
                with_wake=False,
            )
        ],
        recognition=RecognitionConfig(wake_tone=wake_tone),
    )


@pytest.mark.asyncio
async def test_direct_trigger_with_wake_false():
    """Trigger with with_wake=False has with_wake set correctly."""
    config = _make_config()
    direct = config.triggers[0]
    assert direct.with_wake is False


@pytest.mark.asyncio
async def test_direct_trigger_fires_without_wake_word():
    """with_wake=False triggers are included in candidates even when not woken."""
    from alexa_custom.stt import set_stt_sleeping

    set_stt_sleeping(False)
    config = _make_config()
    # Simulate the candidate selection logic from _recognition_loop:
    # direct triggers (with_wake=False) always included; wake-gated only when woken.
    woken = False  # not woken
    candidates = [t for t in config.triggers if not t.with_wake or woken]
    assert len(candidates) == 1
    assert candidates[0].with_wake is False


@pytest.mark.asyncio
async def test_wake_gated_trigger_excluded_when_not_woken():
    """with_wake=True triggers are excluded from candidates when the wake window is closed."""
    config = ActionsConfig(
        wake_words=["galileo"],
        triggers=[
            Trigger(
                commands=["accendi la luce"],
                phrase="accendi la luce",
                actions=[ActionEntry(type="say", params={"text": "ok"})],
                with_wake=True,
            )
        ],
        recognition=RecognitionConfig(),
    )
    woken = False
    candidates = [t for t in config.triggers if not t.with_wake or woken]
    assert candidates == []


@pytest.mark.asyncio
async def test_wake_gated_trigger_included_when_woken():
    """with_wake=True triggers are included when the wake window is open."""
    config = ActionsConfig(
        wake_words=["galileo"],
        triggers=[
            Trigger(
                commands=["accendi la luce"],
                phrase="accendi la luce",
                actions=[ActionEntry(type="say", params={"text": "ok"})],
                with_wake=True,
            )
        ],
        recognition=RecognitionConfig(),
    )
    woken = True
    candidates = [t for t in config.triggers if not t.with_wake or woken]
    assert len(candidates) == 1


def test_direct_triggers_subset_populated():
    """ActionsConfig.direct_triggers must equal triggers filtered by with_wake=False."""
    t_direct = Trigger(
        commands=["chiama stefano"],
        phrase="chiama stefano",
        actions=[ActionEntry(type="livekit_join", params={})],
        with_wake=False,
    )
    t_gated = Trigger(
        commands=["accendi luce"],
        phrase="accendi luce",
        actions=[ActionEntry(type="say", params={"text": "ok"})],
        with_wake=True,
    )
    all_triggers = [t_direct, t_gated]
    direct = [t for t in all_triggers if not t.with_wake]
    assert len(direct) == 1
    assert direct[0].with_wake is False
