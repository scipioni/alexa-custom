import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import numpy as np
import pytest
from alexa_custom.client import (
    calculate_peak,
    get_token,
    make_browser_token,
    browser_join_url,
    run_session,
)


class TestClientAsync:
    @pytest.mark.asyncio
    @patch("alexa_custom.client.Room")
    @patch("alexa_custom.client.get_token")
    @patch("alexa_custom.client.LocalAudioTrack")
    @patch("alexa_custom.client.TrackPublishOptions")
    async def test_run_session_basic(
        self, mock_opts, mock_local_track, mock_get_token, mock_room_class
    ):
        mock_room = MagicMock()
        mock_room.connect = AsyncMock()
        mock_room.disconnect = AsyncMock()
        mock_room.local_participant.publish_track = AsyncMock()
        mock_room.local_participant.identity = "test-identity"
        mock_room.remote_participants = {}

        mock_room_class.return_value = mock_room
        mock_get_token.return_value = "test-token"

        mic = MagicMock()
        devices = MagicMock()
        player = MagicMock()
        player.start = AsyncMock()
        player.aclose = AsyncMock()
        devices.open_output.return_value = player
        pw_device = 0
        stop_event = asyncio.Event()

        # We need to trigger the stop event so it doesn't run forever
        async def stop_soon():
            await asyncio.sleep(0.1)
            stop_event.set()

        asyncio.create_task(stop_soon())

        with patch.dict(
            os.environ, {"LIVEKIT_URL": "http://test.url", "LIVEKIT_ROOM": "test-room"}
        ):
            await run_session(mic, devices, pw_device, stop_event)

        mock_room.connect.assert_called_once_with("http://test.url", "test-token")
        mock_room.local_participant.publish_track.assert_called_once()
        mock_room.disconnect.assert_called_once()

    @pytest.mark.asyncio
    @patch("alexa_custom.client.Room")
    @patch("alexa_custom.client.get_token")
    @patch("alexa_custom.client.LocalAudioTrack")
    @patch("alexa_custom.client.TrackPublishOptions")
    async def test_run_session_participant_left_disconnects(
        self, mock_opts, mock_local_track, mock_get_token, mock_room_class
    ):
        mock_room = MagicMock()
        mock_room.connect = AsyncMock()
        mock_room.disconnect = AsyncMock()
        mock_room.local_participant.publish_track = AsyncMock()
        mock_room.local_participant.identity = "test-identity"
        mock_room.remote_participants = {}

        callbacks = {}

        def mock_on(event_name):
            def decorator(func):
                callbacks[event_name] = func
                return func

            return decorator

        mock_room.on.side_effect = mock_on

        mock_room_class.return_value = mock_room
        mock_get_token.return_value = "test-token"

        mic = MagicMock()
        devices = MagicMock()
        player = MagicMock()
        player.start = AsyncMock()
        player.aclose = AsyncMock()
        devices.open_output.return_value = player
        pw_device = 0
        stop_event = asyncio.Event()

        # Simulate other participant disconnected
        async def simulate_participant_left():
            # Wait for connection to be active
            await asyncio.sleep(0.05)
            # When participant disconnected is fired, they are no longer in remote_participants
            mock_participant = MagicMock()
            mock_participant.identity = "other-user"
            mock_room.remote_participants = {}  # empty now

            # Fire the event callback
            callbacks["participant_disconnected"](mock_participant)

        asyncio.create_task(simulate_participant_left())

        with patch.dict(
            os.environ, {"LIVEKIT_URL": "http://test.url", "LIVEKIT_ROOM": "test-room"}
        ):
            # Run without setting stop_event! It should disconnect automatically
            # when the last participant leaves the room.
            await run_session(mic, devices, pw_device, stop_event)

        mock_room.disconnect.assert_called_once()


class TestClientUtils(unittest.TestCase):
    def test_calculate_peak_empty(self):
        frame = MagicMock()
        frame.data = b""
        assert calculate_peak(frame) == 0.0

    def test_calculate_peak_silence(self):
        frame = MagicMock()
        frame.data = np.zeros(100, dtype=np.int16).tobytes()
        assert calculate_peak(frame) == 0.0

    def test_calculate_peak_max(self):
        frame = MagicMock()
        # 32767 is max for int16
        frame.data = np.array([32767], dtype=np.int16).tobytes()
        assert calculate_peak(frame) == pytest.approx(32767.0 / 32768.0)

    def test_calculate_peak_negative_max(self):
        frame = MagicMock()
        # -32768 is min for int16, abs is 32768
        frame.data = np.array([-32768], dtype=np.int16).tobytes()
        assert calculate_peak(frame) == pytest.approx(32768.0 / 32768.0)

    @patch.dict(
        os.environ,
        {
            "LIVEKIT_API_KEY": "test_key",
            "LIVEKIT_API_SECRET": "test_secret",
            "LIVEKIT_ROOM": "test_room",
            "LIVEKIT_URL": "http://test.url",
        },
    )
    def test_tokens(self):
        # We can't easily verify the JWT content without a library,
        # but we can ensure they return strings and don't crash.
        token = get_token()
        assert isinstance(token, str)
        assert len(token) > 0

        token2 = make_browser_token("custom-identity")
        assert isinstance(token2, str)
        assert len(token2) > 0

    @patch.dict(
        os.environ,
        {
            "LIVEKIT_API_KEY": "test_key",
            "LIVEKIT_API_SECRET": "test_secret",
            "LIVEKIT_ROOM": "test_room",
            "LIVEKIT_URL": "http://test.url",
        },
    )
    def test_browser_join_url(self):
        url = browser_join_url("test-user")
        assert "https://meet.livekit.io/custom/?" in url
        assert "liveKitUrl=http%3A%2F%2Ftest.url" in url
        assert "token=" in url


class TestClientCLI(unittest.TestCase):
    @patch("alexa_custom.client.ensure_setup")
    @patch("alexa_custom.config.load_config")
    @patch("alexa_custom.web.run_web")
    @patch("os._exit")
    def test_cli_launches_web(
        self,
        mock_os_exit,
        mock_run_web,
        mock_load_config,
        mock_ensure_setup,
    ):
        from alexa_custom.client import main
        import sys

        mock_load_config.return_value = None

        with patch.object(sys, "argv", ["alexa-client"]):
            main()
            mock_run_web.assert_called_once()
            mock_os_exit.assert_called_once_with(0)
