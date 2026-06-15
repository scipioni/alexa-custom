import argparse
import asyncio
import logging
import os
from livekit import rtc, api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-agent")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", default=os.environ.get("LIVEKIT_URL"))
    args = parser.parse_args()

    room = rtc.Room()

    @room.on("participant_connected")
    def on_participant_connected(participant):
        logger.info(f"Participant connected: {participant.identity}")

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Subscribed to audio track from {participant.identity}")
            # Here we would feed audio to STT/LLM/TTS

    logger.info(f"Connecting to room {args.room}...")
    await room.connect(args.url, args.token)
    logger.info("Connected!")

    # Simple greeting
    # (In a real implementation, we would publish a TTS track here)
    
    try:
        await asyncio.Event().wait()
    finally:
        await room.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
