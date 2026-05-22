#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
from typing import Callable

from livekit.api import AccessToken, VideoGrants
from livekit.rtc import (
    LocalAudioTrack,
    MediaDevices,
    Room,
    TrackKind,
    TrackPublishOptions,
    TrackSource,
)

from alexa_custom._env import load_env, require_env
import sounddevice as sd

from alexa_custom.audio import find_pipewire_device, play_startup_chime, set_pipewire_defaults

load_env()

ROOM_URL = os.environ.get("LIVEKIT_URL", "")
RECONNECT_DELAY = 5  # seconds between reconnect attempts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def get_token() -> str:
    api_key = require_env("LIVEKIT_API_KEY")
    api_secret = require_env("LIVEKIT_API_SECRET")
    room = require_env("LIVEKIT_ROOM")
    require_env("LIVEKIT_URL")
    return (
        AccessToken(api_key, api_secret)
        .with_identity("headless-participant")
        .with_name("Headless Participant")
        .with_grants(VideoGrants(room_join=True, room=room))
        .to_jwt()
    )


def make_browser_token(identity: str = "browser-user") -> str:
    """Generate a token for a browser participant with a distinct identity."""
    api_key = require_env("LIVEKIT_API_KEY")
    api_secret = require_env("LIVEKIT_API_SECRET")
    room = require_env("LIVEKIT_ROOM")
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
    room = require_env("LIVEKIT_ROOM")
    params = urllib.parse.urlencode({"liveKitUrl": ROOM_URL, "token": token})
    return f"https://meet.livekit.io/custom/?{params}"


async def run_session(
    mic,
    player,
    stop_event: asyncio.Event,
    on_event: Callable[[str, dict], None] | None = None,
):
    """Connect to one LiveKit session; return when disconnected or stop_event fires."""

    def emit(event: str, data: dict | None = None) -> None:
        if on_event:
            on_event(event, data or {})

    room = Room()
    disconnected = asyncio.Event()
    subscribed_tracks: list = []

    @room.on("disconnected")
    def on_disconnected(reason):
        logger.info(f"Room disconnected: {reason}")
        emit("disconnected", {"reason": reason})
        disconnected.set()

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == TrackKind.KIND_AUDIO:
            logger.info(f"Audio track subscribed from {participant.identity}")
            subscribed_tracks.append(track)
            emit("track_subscribed", {"identity": participant.identity, "track_sid": track.sid})
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
            emit("track_unsubscribed", {"identity": participant.identity})
            if track in subscribed_tracks:
                subscribed_tracks.remove(track)
            asyncio.create_task(player.remove_track(track))

    @room.on("participant_connected")
    def on_participant_connected(participant):
        logger.info(f"Participant joined: {participant.identity}")
        emit("participant_joined", {"identity": participant.identity})

    @room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logger.info(f"Participant left: {participant.identity}")
        emit("participant_left", {"identity": participant.identity})

    try:
        await room.connect(ROOM_URL, get_token())
        room_name = require_env('LIVEKIT_ROOM')
        logger.info(f"Connected to {ROOM_URL}/{room_name} as {room.local_participant.identity}")
        emit("connected", {"room": room_name, "identity": room.local_participant.identity})

        # Emit events for participants already in the room at connect time.
        for p in room.remote_participants.values():
            logger.info(f"Existing participant: {p.identity} ({len(p.track_publications)} tracks)")
            emit("participant_joined", {"identity": p.identity})

        if not room.remote_participants:
            logger.info("No other participants in room yet — waiting for browser to join")

        track = LocalAudioTrack.create_audio_track("microphone", mic.source)
        opts = TrackPublishOptions()
        opts.source = TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, opts)
        logger.info("Microphone track published — full duplex active")

        async def _status_loop():
            while True:
                await asyncio.sleep(15)
                n_participants = len(room.remote_participants)
                n_tracks = len(subscribed_tracks)
                buf_bytes = len(player._buffer)
                logger.info(
                    f"Status: {n_participants} remote participant(s), "
                    f"{n_tracks} subscribed audio track(s), "
                    f"playback buffer {buf_bytes} bytes"
                )

        status_task = asyncio.create_task(_status_loop())

        await asyncio.wait(
            [asyncio.create_task(disconnected.wait()),
             asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        status_task.cancel()
    finally:
        for t in list(subscribed_tracks):
            try:
                await player.remove_track(t)
            except Exception:
                pass
        subscribed_tracks.clear()
        await room.disconnect()


async def _async_main(
    ext_stop_event: asyncio.Event | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> None:
    logger.info(f"Browser join URL:\n  {browser_join_url()}")

    input_spec = os.environ.get('INPUT_DEVICE', '').strip() or None
    output_spec = os.environ.get('OUTPUT_DEVICE', '').strip() or None

    # Route PipeWire to the requested devices, then always talk to LiveKit
    # through the PipeWire virtual device — never open hw: devices directly.
    if input_spec or output_spec:
        await asyncio.to_thread(set_pipewire_defaults, input_spec, output_spec)
        logger.info(f"PipeWire routed — input: {input_spec or 'default'}, output: {output_spec or 'default'}")

    pw_device = find_pipewire_device()
    if pw_device is None:
        raise RuntimeError("PipeWire ALSA device not found. Is PipeWire running?")

    logger.info(f"Input device:  {input_spec or sd.query_devices(pw_device)['name']}")
    logger.info(f"Output device: {output_spec or sd.query_devices(pw_device)['name']}")

    if ext_stop_event is None:  # TUI plays the chime before starting
        try:
            await asyncio.to_thread(play_startup_chime)
        except Exception as e:
            logger.warning(f"Startup chime skipped: {e}")

    devices = MediaDevices(input_sample_rate=48000, output_sample_rate=48000, num_channels=1)

    # Use the provided stop event (TUI mode) or create one and wire signals.
    stop_event = ext_stop_event or asyncio.Event()
    if ext_stop_event is None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

    def _flag(key: str, default: bool = True) -> bool:
        return os.environ.get(key, "1" if default else "0").strip().lower() not in ("0", "false", "no")

    agc  = _flag("MIC_AGC")
    aec  = _flag("MIC_AEC")
    ns   = _flag("MIC_NOISE_SUPPRESSION")
    hpf  = _flag("MIC_HIGH_PASS_FILTER")
    logger.info(f"Opening microphone (AEC={aec} NS={ns} HPF={hpf} AGC={agc})...")
    mic = devices.open_input(
        enable_aec=aec,
        noise_suppression=ns,
        high_pass_filter=hpf,
        auto_gain_control=agc,
        input_device=pw_device,
    )

    logger.info("Opening speaker output...")
    player = devices.open_output(output_device=pw_device)
    await player.start()
    logger.info("Speaker output started")

    try:
        while not stop_event.is_set():
            if on_event:
                on_event("reconnecting", {})
            try:
                await run_session(mic, player, stop_event, on_event=on_event)
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


def main() -> None:
    import argparse
    import threading
    parser = argparse.ArgumentParser(description="alexa-custom LiveKit client")
    parser.add_argument("--tui", action="store_true", help="Launch terminal UI")
    args = parser.parse_args()

    if args.tui:
        from alexa_custom.tui import run_tui
        from alexa_custom.audio import play_startup_chime as _chime
        try:
            _chime()
        except Exception as e:
            logger.warning(f"Startup chime skipped: {e}")
        input_spec = os.environ.get('INPUT_DEVICE', '').strip() or None
        output_spec = os.environ.get('OUTPUT_DEVICE', '').strip() or None
        room = os.environ.get('LIVEKIT_ROOM', '')

        async def _run_for_tui(
            stop_threading: threading.Event,
            on_event: Callable,
        ) -> None:
            # Bridge the threading.Event to an asyncio.Event so _async_main
            # can await it normally in the worker's own event loop.
            stop_asyncio = asyncio.Event()

            async def _bridge() -> None:
                while not stop_threading.is_set():
                    await asyncio.sleep(0.1)
                stop_asyncio.set()

            asyncio.create_task(_bridge())
            await _async_main(ext_stop_event=stop_asyncio, on_event=on_event)

        run_tui(
            run_fn=_run_for_tui,
            input_spec=input_spec,
            output_spec=output_spec,
            room=room,
        )
    else:
        asyncio.run(_async_main())


if __name__ == "__main__":
    main()
