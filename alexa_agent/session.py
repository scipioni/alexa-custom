import asyncio
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

from livekit.api import AccessToken, VideoGrants, LiveKitAPI, CreateRoomRequest

logger = logging.getLogger(__name__)


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
        .with_identity("ai-agent")
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


async def handle_agent_session(action, **_):
    """Orchestrates a LiveKit agent session: creates room, tokens, starts agent, opens tab."""
    room_name = f"agent-room-{int(time.time())}"
    logger.info(f"Starting agent session in room: {room_name}")

    try:
        await _create_agent_room(room_name)

        user_token, agent_token = _generate_agent_tokens(room_name)

        agent_path = Path(__file__).parent / "agent.py"
        room_url = os.environ.get("LIVEKIT_URL")

        logger.info(f"Starting local agent process for room {room_name}")
        subprocess.Popen(
            [
                sys.executable,
                str(agent_path),
                "--room",
                room_name,
                "--token",
                agent_token,
                "--url",
                room_url,
            ],
        )

        if not room_url:
            logger.error("LIVEKIT_URL not set, cannot generate join link")
            return

        params = urllib.parse.urlencode({"liveKitUrl": room_url, "token": user_token})
        join_url = f"https://meet.livekit.io/custom/?{params}"

        logger.info(f"Opening agent session tab: {join_url}")

        def _open_browser():
            try:
                if not webbrowser.open(join_url, new=2):
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
