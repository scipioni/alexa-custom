import asyncio
import json
import logging
import os
import time
import urllib.parse
import webbrowser
from pathlib import Path

from livekit.api import AccessToken, VideoGrants, LiveKitAPI, CreateRoomRequest, ListParticipantsRequest

logger = logging.getLogger(__name__)

_IPC_DIR = Path.home() / ".local" / "share" / "alexa-agent"
_REQUEST_FILE = _IPC_DIR / "request.json"
_STATUS_FILE = _IPC_DIR / "status.json"


async def _create_agent_room(room_name: str):
    """Call LiveKit API to create a room with 5min empty timeout.

    Uses LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL from environment.
    """
    async with LiveKitAPI() as api:
        return await api.room.create_room(
            CreateRoomRequest(
                name=room_name,
                empty_timeout=300,
                max_participants=10,
            )
        )


def _generate_agent_tokens(room_name: str):
    """Generate user and agent JWT tokens with audio-only permissions."""
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")

    user_token = (
        AccessToken(key, secret)
        .with_identity(f"user-{int(time.time())}")
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_name,
                can_publish_sources=["microphone"],
            )
        )
        .to_jwt()
    )

    agent_token = (
        AccessToken(key, secret)
        .with_identity("serena ai")
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_name,
                can_publish_sources=["microphone"],
            )
        )
        .to_jwt()
    )

    return user_token, agent_token


async def _wait_for_agent(room_name: str, timeout: float = 15.0) -> bool:
    """Poll LiveKit API until 'serena ai' appears in the room or timeout."""
    from livekit.api import LiveKitAPI, ListParticipantsRequest

    deadline = time.time() + timeout
    async with LiveKitAPI() as api:
        while time.time() < deadline:
            try:
                resp = await api.room.list_participants(
                    ListParticipantsRequest(room=room_name)
                )
                if any(p.identity == "serena ai" for p in resp.participants):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def _signal_agent(room_name: str, token: str, url: str):
    """Write a request.json for the persistent agent daemon to pick up."""
    _IPC_DIR.mkdir(parents=True, exist_ok=True)
    _REQUEST_FILE.write_text(
        json.dumps({"room": room_name, "token": token, "url": url})
    )


async def _wait_for_status(room_name: str, timeout: float = 5.0) -> bool:
    """Poll status.json until the agent reports 'connecting' for this room."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _STATUS_FILE.exists():
                data = json.loads(_STATUS_FILE.read_text())
                if data.get("state") == "connecting" and data.get("room") == room_name:
                    return True
        except (json.JSONDecodeError, OSError):
            pass
        await asyncio.sleep(0.2)
    return False


async def handle_agent_session(action, livekit_connect_fn=None, **_):
    """Orchestrates a LiveKit agent session: creates room, tokens, signals agent, connects device, opens tab."""
    room_name = f"agent-room-{int(time.time())}"
    logger.info(f"Starting agent session in room: {room_name}")

    try:
        await _create_agent_room(room_name)

        user_token, agent_token = _generate_agent_tokens(room_name)
        room_url = os.environ.get("LIVEKIT_URL")

        if not room_url:
            logger.error("LIVEKIT_URL not set, cannot generate join link")
            return

        logger.info("Signalling persistent agent via %s", _REQUEST_FILE)
        await _signal_agent(room_name, agent_token, room_url)

        picked_up = await _wait_for_status(room_name)
        if not picked_up:
            logger.warning("Agent did not pick up request")
        else:
            logger.info("Agent picked up request, waiting for LiveKit connection...")

        agent_ready = await _wait_for_agent(room_name)
        if not agent_ready:
            logger.warning("Agent did not join room within timeout")

        # Connect the device itself to the room so the user can talk to serena-ai
        from alexa_custom.client import set_pending_connect
        from livekit.api import AccessToken, VideoGrants

        key = os.environ.get("LIVEKIT_API_KEY")
        secret = os.environ.get("LIVEKIT_API_SECRET")
        device_token = (
            AccessToken(key, secret)
            .with_identity("headless-participant")
            .with_name("Headless Participant")
            .with_grants(VideoGrants(room_join=True, room=room_name, can_publish_sources=["microphone"]))
            .to_jwt()
        )
        set_pending_connect(room_name, device_token)

        if livekit_connect_fn is not None:
            logger.info("Triggering device connect to dynamic room %s", room_name)
            await livekit_connect_fn()

        # Open browser tab for caregiver (optional)
        params = urllib.parse.urlencode({"liveKitUrl": room_url, "token": user_token})
        join_url = f"https://meet.livekit.io/custom/?{params}"
        logger.info(f"Agent session join URL: {join_url}")

        def _open_browser():
            try:
                if not webbrowser.open(join_url, new=2):
                    import subprocess
                    subprocess.Popen(
                        ["xdg-open", join_url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except Exception as e:
                logger.error(f"Browser open failed: {e}")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _open_browser)

    except Exception as e:
        logger.error(f"Failed to initialize agent session: {e}")
