from unittest.mock import MagicMock, patch
import pytest
import asyncio
import threading
from alexa_custom.stt import _wake_detected, is_stt_sleeping, set_stt_sleeping
from alexa_custom.config import WakeWordGroup, Trigger, ActionsConfig, ActionEntry, RecognitionConfig
from alexa_custom.actions import registry

@pytest.mark.asyncio
async def test_listening_state_toggle():
    # Verify initial state is not sleeping
    set_stt_sleeping(False)
    assert not is_stt_sleeping()
    
    # Execute stop_listening action
    await registry.execute("stop_listening", action=ActionEntry(type="stop_listening"))
    assert is_stt_sleeping()
    
    # Execute start_listening action
    await registry.execute("start_listening", action=ActionEntry(type="start_listening"))
    assert not is_stt_sleeping()

@pytest.mark.asyncio
async def test_wake_detected_ignores_commands_when_sleeping():
    # Arrange
    set_stt_sleeping(True)
    
    wake_group = WakeWordGroup(word="galileo")
    proc = MagicMock()
    backend = MagicMock()
    config = ActionsConfig(
        wake_words=[wake_group],
        triggers=[],
        recognition=RecognitionConfig(),
    )
    
    stop_event = threading.Event()
    telegram_client = MagicMock()
    livekit_connected_flag = threading.Event()
    on_stt_event = MagicMock()
    mqtt_client = MagicMock()
    
    # Standard trigger (without start_listening action)
    standard_trigger = Trigger(
        phrase="accendi luce",
        actions=[ActionEntry(type="log", params={"message": "luce"})],
    )
    
    loop = asyncio.get_event_loop()
    dispatch_loop = loop
    
    # Patch dispatch to see if it gets called
    with patch("alexa_custom.stt.dispatch", new_callable=MagicMock) as mock_dispatch:
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
            pre_transcript="accendi luce",
            pre_trigger=standard_trigger,
        )
        
        # Assert - should NOT be called because STT is sleeping and trigger is standard
        mock_dispatch.assert_not_called()

@pytest.mark.asyncio
async def test_wake_detected_allows_start_listening_when_sleeping():
    # Arrange
    set_stt_sleeping(True)
    
    wake_group = WakeWordGroup(word="galileo")
    proc = MagicMock()
    backend = MagicMock()
    config = ActionsConfig(
        wake_words=[wake_group],
        triggers=[],
        recognition=RecognitionConfig(),
    )
    
    stop_event = threading.Event()
    telegram_client = MagicMock()
    livekit_connected_flag = threading.Event()
    on_stt_event = MagicMock()
    mqtt_client = MagicMock()
    
    # Trigger with start_listening action
    start_listening_trigger = Trigger(
        phrase="svegliati",
        actions=[ActionEntry(type="start_listening")],
        wake_words=[],
    )
    
    loop = asyncio.get_event_loop()
    dispatch_loop = loop
    
    # Patch dispatch to see if it gets called
    with patch("alexa_custom.stt.dispatch", new_callable=MagicMock) as mock_dispatch:
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
            pre_transcript="svegliati",
            pre_trigger=start_listening_trigger,
        )
        
        # Assert - should be called because it contains start_listening
        mock_dispatch.assert_called_once()
        
    # Cleanup state
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
    
    # Patch _play_array (which is called by play_tone/play_beep on success)
    with patch("alexa_custom.audio_ops._play_array") as mock_play_array:
        play_tone("info")
        play_beep(440, 100)
        
        # Both play_tone and play_beep should return early without calling _play_array
        mock_play_array.assert_not_called()
        
    set_stt_sleeping(False)
    
    # Patch _play_array again when awake
    with patch("alexa_custom.audio_ops._play_array") as mock_play_array:
        play_beep(440, 1) # very short beep
        
        # When awake, it should call _play_array
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
    from alexa_custom.config import ActionsConfig, Trigger, ActionEntry, WakeWordGroup
    
    # Trigger with start_listening
    wakeup_trigger = Trigger(
        phrase="svegliati",
        actions=[ActionEntry(type="start_listening")],
    )
    # Trigger without start_listening
    dummy_trigger = Trigger(
        phrase="test",
        actions=[ActionEntry(type="log")],
    )
    
    config = ActionsConfig(
        wake_words=[WakeWordGroup(word="galileo")],
        triggers=[wakeup_trigger, dummy_trigger],
        direct_triggers=[dummy_trigger],
    )
    
    phrases = get_wake_up_phrases(config)
    assert "svegliati" in phrases
    assert "test" not in phrases


