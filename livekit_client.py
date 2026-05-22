#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
import sounddevice as sd

from livekit.api import AccessToken, VideoGrants
from livekit.rtc import (
    LocalAudioTrack,
    MediaDevices,
    Room,
    TrackKind,
    TrackPublishOptions,
    TrackSource,
)


def _load_env():
    """Load key=value pairs from .env in the same directory, without overriding existing env vars."""
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


_load_env()

ROOM_URL = os.environ.get("LIVEKIT_URL", "")
RECONNECT_DELAY = 5  # seconds between reconnect attempts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(
            f"{key} is not set — fill it in ~/livekit-client/.env"
        )
    return value


def get_token() -> str:
    api_key = _require_env("LIVEKIT_API_KEY")
    api_secret = _require_env("LIVEKIT_API_SECRET")
    room = _require_env("LIVEKIT_ROOM")
    _require_env("LIVEKIT_URL")
    return (
        AccessToken(api_key, api_secret)
        .with_identity("headless-participant")
        .with_name("Headless Participant")
        .with_grants(VideoGrants(room_join=True, room=room))
        .to_jwt()
    )


def make_browser_token(identity: str = "browser-user") -> str:
    """Generate a token for a browser participant with a distinct identity."""
    api_key = _require_env("LIVEKIT_API_KEY")
    api_secret = _require_env("LIVEKIT_API_SECRET")
    room = _require_env("LIVEKIT_ROOM")
    return (
        AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(VideoGrants(room_join=True, room=room))
        .to_jwt()
    )


def browser_join_url(identity: str = "browser-user") -> str:
    """Return the meet.livekit.io URL a browser can open to join the same room."""
    import urllib.parse
    token = make_browser_token(identity)
    room = _require_env("LIVEKIT_ROOM")
    params = urllib.parse.urlencode({"liveKitUrl": ROOM_URL, "token": token})
    return f"https://meet.livekit.io/custom/?{params}"


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    return next(
        (i for i, d in enumerate(sd.query_devices()) if d['name'] == 'pipewire'),
        None,
    )


async def run_session(mic, player, stop_event: asyncio.Event):
    """Connect to one LiveKit session; return when disconnected or stop_event fires."""
    room = Room()
    disconnected = asyncio.Event()
    subscribed_tracks: list = []

    @room.on("disconnected")
    def on_disconnected(reason):
        logger.info(f"Room disconnected: {reason}")
        disconnected.set()

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == TrackKind.KIND_AUDIO:
            logger.info(f"Audio track subscribed from {participant.identity}")
            subscribed_tracks.append(track)
            async def _add():
                try:
                    await player.add_track(track)
                    logger.info(f"Track {track.sid} added to player OK")
                except Exception as e:
                    logger.error(f"add_track failed: {e}")
            asyncio.create_task(_add())

    @room.on("track_unsubscribed")
    def on_track_unsubscribed(track, publication, participant):
        if track.kind == TrackKind.KIND_AUDIO:
            logger.info(f"Audio track unsubscribed from {participant.identity}")
            if track in subscribed_tracks:
                subscribed_tracks.remove(track)
            asyncio.create_task(player.remove_track(track))

    @room.on("participant_connected")
    def on_participant_connected(participant):
        logger.info(f"Participant joined: {participant.identity}")

    @room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logger.info(f"Participant left: {participant.identity}")

    try:
        await room.connect(ROOM_URL, get_token())
        room_name = _require_env('LIVEKIT_ROOM')
        logger.info(f"Connected to {ROOM_URL}/{room_name} as {room.local_participant.identity}")

        # Log participants already in the room at connect time.
        existing = list(room.remote_participants.values())
        if existing:
            for p in existing:
                logger.info(f"Existing participant: {p.identity} ({len(p.track_publications)} tracks)")
        else:
            logger.info("No other participants in room yet — waiting for browser to join")

        track = LocalAudioTrack.create_audio_track("microphone", mic.source)
        opts = TrackPublishOptions()
        opts.source = TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, opts)
        logger.info("Microphone track published — full duplex active")

        # Periodic status: log participant count, subscribed track count, and playback buffer level.
        async def _status_loop():
            while True:
                await asyncio.sleep(15)
                n_participants = len(room.remote_participants)
                n_tracks = len(subscribed_tracks)
                buf_bytes = len(player._buffer)
                logger.info(f"Status: {n_participants} remote participant(s), {n_tracks} subscribed audio track(s), playback buffer {buf_bytes} bytes")

        status_task = asyncio.create_task(_status_loop())

        # Wait until the room disconnects or we are asked to stop
        await asyncio.wait(
            [asyncio.create_task(disconnected.wait()),
             asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        status_task.cancel()
    finally:
        # Remove all tracked audio from the player before disconnecting so
        # add_track() doesn't raise "already added" on the next reconnect.
        for t in list(subscribed_tracks):
            try:
                await player.remove_track(t)
            except Exception:
                pass
        subscribed_tracks.clear()
        await room.disconnect()


async def main():
    # Fail immediately if credentials are missing — don't enter the reconnect loop.
    logger.info(f"Browser join URL:\n  {browser_join_url()}")

    pw_device = find_pipewire_device()
    if pw_device is None:
        raise RuntimeError("PipeWire ALSA device not found. Is PipeWire running?")
    logger.info(f"Using PipeWire device index {pw_device}")

    # input_sample_rate=48000 is standard WebRTC; PipeWire resamples to/from mSBC 16kHz
    devices = MediaDevices(input_sample_rate=48000, output_sample_rate=48000, num_channels=1)

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Opening microphone (AEC + noise suppression + AGC)...")
    mic = devices.open_input(
        enable_aec=True,
        noise_suppression=True,
        high_pass_filter=True,
        auto_gain_control=True,
        input_device=pw_device,
    )

    logger.info("Opening speaker output...")
    player = devices.open_output(output_device=pw_device)
    await player.start()
    logger.info("Speaker output started")

    try:
        while not stop_event.is_set():
            try:
                await run_session(mic, player, stop_event)
            except Exception as e:
                logger.error(f"Session error: {e}")

            if stop_event.is_set():
                break

            logger.info(f"Reconnecting in {RECONNECT_DELAY}s...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=RECONNECT_DELAY)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Shutting down...")
        await mic.aclose()
        await player.aclose()
        logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
