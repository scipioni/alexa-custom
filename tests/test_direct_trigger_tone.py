from unittest.mock import MagicMock, patch
import pytest
import asyncio
import threading
from alexa_custom.stt import _wake_detected
from alexa_custom.config import WakeWordGroup, Trigger, ActionsConfig, RecognitionConfig


@pytest.mark.asyncio
async def test_direct_trigger_plays_tone():
    # Arrange
    wake_group = WakeWordGroup(word="galileo")
    proc = MagicMock()
    backend = MagicMock()

    # Create configuration with direct trigger
    recognition_config = RecognitionConfig(wake_tone="custom_direct_tone")
    config = ActionsConfig(
        wake_words=[wake_group],
        triggers=[],
        recognition=recognition_config,
    )

    stop_event = threading.Event()
    telegram_client = MagicMock()
    livekit_connected_flag = threading.Event()
    on_stt_event = MagicMock()
    mqtt_client = MagicMock()

    # Create a direct trigger (wake_words=[])
    direct_trigger = Trigger(
        phrase="chiama stefano",
        actions=[],
        wake_words=[],
    )

    # Setup asyncio loops
    loop = asyncio.get_event_loop()
    dispatch_loop = loop

    # Patch play_wake_beep and dispatch to verify execution
    with (
        patch("alexa_custom.stt.play_wake_beep") as mock_play_wake_beep,
        patch("alexa_custom.stt.dispatch", new_callable=MagicMock) as mock_dispatch,
    ):
        # Act
        _wake_detected(
            wake_group=wake_group,
            proc=proc,
            channels=1,
            backend=backend,
            config=config,
            stop_event=stop_event,
            telegram_client=telegram_client,
            livekit_connect_fn=None,
            livekit_connected_flag=livekit_connected_flag,
            on_stt_event=on_stt_event,
            mqtt_client=mqtt_client,
            loop=loop,
            dispatch_loop=dispatch_loop,
            pre_transcript="chiama stefano",
            pre_trigger=direct_trigger,
        )

        # Assert
        mock_play_wake_beep.assert_called_once_with("custom_direct_tone")
        mock_dispatch.assert_called_once()
