import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from alexa_custom.actions import ActionRegistry, _run_action
from alexa_custom.config import ActionEntry


@pytest.mark.asyncio
async def test_action_registry_registration():
    registry = ActionRegistry()
    mock_handler = AsyncMock()

    @registry.register("test_action")
    async def handle_test(action, **kwargs):
        await mock_handler(action, **kwargs)

    action = ActionEntry(type="test_action", params={"foo": "bar"})
    await registry.execute("test_action", action=action, extra="data")

    mock_handler.assert_called_once_with(action, extra="data")


@pytest.mark.asyncio
async def test_action_registry_unknown_action():
    registry = ActionRegistry()
    # Should not raise exception, just log warning
    await registry.execute("unknown")


@pytest.mark.asyncio
async def test_run_action_dispatch():
    mock_action = ActionEntry(type="log", params={"message": "hello"})

    with patch(
        "alexa_custom.actions.registry.execute", new_callable=AsyncMock
    ) as mock_execute:
        await _run_action(
            mock_action,
            telegram_client=MagicMock(),
            livekit_connect_fn=AsyncMock(),
            livekit_connected=False,
        )

        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        assert args[0] == "log"
        assert kwargs["action"] == mock_action
