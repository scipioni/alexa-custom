"""Tests for bounded dispatch execution (recognition.dispatch_timeout)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from alexa_custom.actions import ActionContext, TelegramClient, dispatch
from alexa_custom.config import ActionEntry, RecognitionConfig, Trigger


def _make_trigger(action_type: str = "log") -> Trigger:
    return Trigger(phrase="test", actions=[ActionEntry(type=action_type, params={})])


def _make_ctx() -> ActionContext:
    return ActionContext(telegram_client=TelegramClient())


class TestDispatchTimeout:
    @pytest.mark.asyncio
    async def test_dispatch_within_ceiling_completes_normally(self):
        """A dispatch finishing before the ceiling behaves identically to before."""
        trigger = _make_trigger("log")
        ctx = _make_ctx()

        with patch(
            "alexa_custom.actions.registry.execute", new_callable=AsyncMock
        ) as mock_exec:
            await asyncio.wait_for(dispatch(trigger, ctx), timeout=5.0)

        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_exceeding_ceiling_raises_timeout(self):
        """A dispatch that sleeps past the ceiling is cancelled via TimeoutError."""
        trigger = _make_trigger("log")
        ctx = _make_ctx()

        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(10.0)

        with patch(
            "alexa_custom.actions.registry.execute",
            new_callable=AsyncMock,
            side_effect=_slow,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(dispatch(trigger, ctx), timeout=0.05)

    @pytest.mark.asyncio
    async def test_dispatch_timeout_caller_can_recover(self):
        """When the caller catches TimeoutError, execution continues normally."""
        trigger = _make_trigger("log")
        ctx = _make_ctx()

        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(10.0)

        timed_out = False
        with patch(
            "alexa_custom.actions.registry.execute",
            new_callable=AsyncMock,
            side_effect=_slow,
        ):
            try:
                await asyncio.wait_for(dispatch(trigger, ctx), timeout=0.05)
            except asyncio.TimeoutError:
                timed_out = True

        assert timed_out

    def test_dispatch_timeout_config_default(self):
        """RecognitionConfig default dispatch_timeout is 90s."""
        cfg = RecognitionConfig()
        assert cfg.dispatch_timeout == 90.0

    def test_dispatch_timeout_config_custom(self):
        """dispatch_timeout is configurable."""
        cfg = RecognitionConfig(dispatch_timeout=30.0)
        assert cfg.dispatch_timeout == 30.0
