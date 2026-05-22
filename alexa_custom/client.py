#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
import threading
from typing import Callable

from livekit.api import AccessToken, VideoGrants
import numpy as np
from livekit.rtc import (
    AudioStream,
    LocalAudioTrack,
    MediaDevices,
    Room,
    TrackKind,
    TrackPublishOptions,
    TrackSource,
)

from alexa_custom._env import load_env, require_env
import sounddevice as sd

from alexa_custom.audio import (
    find_pipewire_device,
    play_call_end,
    play_call_start,
    play_startup_chime,
    set_pipewire_defaults,
)

load_env()

ROOM_URL = os.environ.get("LIVEKIT_URL", "")
RECONNECT_DELAY = 5  # seconds between reconnect attempts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def calculate_peak(frame) -> float:
    """Calculate normalized peak level (0.0-1.0) from an AudioFrame."""
    samples = np.frombuffer(frame.data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    return float(np.max(np.abs(samples.astype(np.float32)))) / 32768.0


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
    require_env("LIVEKIT_ROOM")
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

    empty_room_timeout = float(os.environ.get("EMPTY_ROOM_TIMEOUT", "0") or "0")

    room = Room()
    disconnected = asyncio.Event()
    call_connected = False
    subscribed_tracks: dict[str, AudioStream] = {}
    volumes = {"mic": 0.0, "spk": 0.0}
    tap_tasks: list[asyncio.Task] = []

    async def _tap_mic(track: LocalAudioTrack):
        stream = AudioStream(track)
        async for event in stream:
            volumes["mic"] = max(volumes["mic"], calculate_peak(event.frame))
            if disconnected.is_set() or stop_event.is_set():
                break

    async def _tap_remote(identity: str, track):
        stream = AudioStream(track)
        subscribed_tracks[identity] = stream
        async for event in stream:
            # We track the max peak across all remote participants for the "Speaker" meter
            volumes["spk"] = max(volumes["spk"], calculate_peak(event.frame))
            if (
                identity not in subscribed_tracks
                or disconnected.is_set()
                or stop_event.is_set()
            ):
                break

    async def _volume_emitter():
        while not disconnected.is_set() and not stop_event.is_set():
            await asyncio.sleep(0.1)  # 10Hz throttle
            emit("volume_update", {"mic": volumes["mic"], "spk": volumes["spk"]})
            # Decay levels so meters drop when silent
            volumes["mic"] *= 0.6
            volumes["spk"] *= 0.6

    @room.on("disconnected")
    def on_disconnected(reason):
        logger.info(f"Room disconnected: {reason}")
        emit("disconnected", {"reason": reason})
        disconnected.set()

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == TrackKind.KIND_AUDIO:
            logger.info(f"Audio track subscribed from {participant.identity}")
            emit(
                "track_subscribed",
                {"identity": participant.identity, "track_sid": track.sid},
            )

            # Start tapping remote track
            tap_tasks.append(
                asyncio.create_task(_tap_remote(participant.identity, track))
            )

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
            subscribed_tracks.pop(participant.identity, None)
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
        room_name = require_env("LIVEKIT_ROOM")
        logger.info(
            f"Connected to {ROOM_URL}/{room_name} as {room.local_participant.identity}"
        )
        emit(
            "connected",
            {"room": room_name, "identity": room.local_participant.identity},
        )
        call_connected = True
        asyncio.create_task(asyncio.to_thread(play_call_start))

        # Emit events for participants already in the room at connect time.
        for p in room.remote_participants.values():
            logger.info(
                f"Existing participant: {p.identity} ({len(p.track_publications)} tracks)"
            )
            emit("participant_joined", {"identity": p.identity})

        if not room.remote_participants:
            logger.info(
                "No other participants in room yet — waiting for browser to join"
            )

        track = LocalAudioTrack.create_audio_track("microphone", mic.source)
        opts = TrackPublishOptions()
        opts.source = TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, opts)
        logger.info("Microphone track published — full duplex active")

        # Start microphone tap and volume emitter
        tap_tasks.append(asyncio.create_task(_tap_mic(track)))
        tap_tasks.append(asyncio.create_task(_volume_emitter()))

        async def _empty_room_watchdog() -> None:
            import time as _time

            empty_since: float | None = (
                None if room.remote_participants else _time.monotonic()
            )
            if empty_since is not None:
                logger.info(
                    f"Room empty at connect — disconnecting in {empty_room_timeout:.0f}s"
                )
            while not disconnected.is_set() and not stop_event.is_set():
                await asyncio.sleep(1.0)
                if room.remote_participants:
                    if empty_since is not None:
                        logger.debug("Participants rejoined — empty-room timer reset")
                    empty_since = None
                else:
                    now = _time.monotonic()
                    if empty_since is None:
                        empty_since = now
                        logger.info(
                            f"Room empty — disconnecting in {empty_room_timeout:.0f}s"
                        )
                    elif now - empty_since >= empty_room_timeout:
                        logger.info("Empty room timeout — disconnecting session")
                        emit("empty_room_timeout", {})
                        disconnected.set()
                        return

        if empty_room_timeout > 0:
            tap_tasks.append(asyncio.create_task(_empty_room_watchdog()))

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
            [
                asyncio.create_task(disconnected.wait()),
                asyncio.create_task(stop_event.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        status_task.cancel()
    finally:
        for t in tap_tasks:
            t.cancel()
        tap_tasks.clear()
        subscribed_tracks.clear()
        if call_connected:
            try:
                await asyncio.to_thread(play_call_end)
            except Exception:
                pass
        await room.disconnect()


async def _async_main(
    ext_stop_event: asyncio.Event | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    connect_trigger: threading.Event | None = None,
    livekit_connected_flag: threading.Event | None = None,
) -> None:
    logger.info(f"Browser join URL:\n  {browser_join_url()}")

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip() or None

    # Route PipeWire to the requested devices, then always talk to LiveKit
    # through the PipeWire virtual device — never open hw: devices directly.
    if input_spec or output_spec:
        await asyncio.to_thread(set_pipewire_defaults, input_spec, output_spec)
        logger.info(
            f"PipeWire routed — input: {input_spec or 'default'}, output: {output_spec or 'default'}"
        )

    pw_device = find_pipewire_device()
    if pw_device is None:
        raise RuntimeError("PipeWire ALSA device not found. Is PipeWire running?")

    logger.info(f"Input device:  {input_spec or sd.query_devices(pw_device)['name']}")
    logger.info(f"Output device: {output_spec or sd.query_devices(pw_device)['name']}")

    try:
        await asyncio.to_thread(play_startup_chime)
    except Exception as e:
        logger.warning(f"Startup chime skipped: {e}")

    devices = MediaDevices(
        input_sample_rate=48000, output_sample_rate=48000, num_channels=1
    )

    # Use the provided stop event (TUI mode) or create one and wire signals.
    stop_event = ext_stop_event or asyncio.Event()
    if ext_stop_event is None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

    def _flag(key: str, default: bool = True) -> bool:
        return os.environ.get(key, "1" if default else "0").strip().lower() not in (
            "0",
            "false",
            "no",
        )

    agc = _flag("MIC_AGC")
    aec = _flag("MIC_AEC")
    ns = _flag("MIC_NOISE_SUPPRESSION")
    hpf = _flag("MIC_HIGH_PASS_FILTER")
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

    def _wrapped_on_event(event: str, data: dict) -> None:
        if livekit_connected_flag is not None:
            if event == "connected":
                livekit_connected_flag.set()
            elif event == "disconnected":
                livekit_connected_flag.clear()
        if on_event:
            on_event(event, data)

    try:
        while not stop_event.is_set():
            # On-demand mode: wait for STT to signal a connect trigger.
            if connect_trigger is not None:
                logger.info("Waiting for voice trigger to connect to LiveKit…")
                while not stop_event.is_set():
                    if connect_trigger.is_set():
                        connect_trigger.clear()
                        break
                    await asyncio.sleep(0.5)
                if stop_event.is_set():
                    break

            _wrapped_on_event("reconnecting", {})
            try:
                await run_session(mic, player, stop_event, on_event=_wrapped_on_event)
            except Exception as e:
                logger.error(f"Session error: {e}")

            if livekit_connected_flag is not None:
                livekit_connected_flag.clear()

            if stop_event.is_set():
                break

            # In on-demand mode don't auto-reconnect; wait for another trigger.
            if connect_trigger is not None:
                logger.info("LiveKit session ended — waiting for next voice trigger")
                continue

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


def ensure_setup() -> None:
    """Check if Vosk model and audio hardware setup are present; download/warn as needed."""
    from alexa_custom.setup import download_model
    from alexa_custom.stt import _MODEL_PATH

    # 1. Vosk model - download automatically if missing
    if not os.path.isdir(_MODEL_PATH):
        logger.info(
            f"Vosk model not found at {_MODEL_PATH}. Downloading automatically..."
        )
        try:
            download_model()
        except Exception as e:
            logger.error(f"Failed to download Vosk model: {e}")

    # 2. Audio hardware setup - warn if udev rule is missing and OUTPUT_DEVICE is set
    udev_path = "/etc/udev/rules.d/89-alsa-usb-volume.rules"
    if not os.path.exists(udev_path):
        output_spec = os.environ.get("OUTPUT_DEVICE", "").strip()
        if output_spec:
            print("\n" + "!" * 60)
            print("WARNING: Audio hardware volume setup seems incomplete.")
            print(f"Udev rule {udev_path} is missing.")
            print("Please run 'alexa-audio-setup' manually to fix this.")
            print("!" * 60 + "\n")


def main() -> None:
    import argparse
    import threading

    from alexa_custom.config import load_actions_config

    ensure_setup()

    parser = argparse.ArgumentParser(description="alexa-custom LiveKit client")
    parser.add_argument("--tui", action="store_true", help="Launch terminal UI")
    args = parser.parse_args()

    config = load_actions_config()

    if args.tui:
        from alexa_custom.tui import run_tui

        input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
        output_spec = os.environ.get("OUTPUT_DEVICE", "").strip() or None
        room = os.environ.get("LIVEKIT_ROOM", "")

        connect_trigger: threading.Event | None = None
        livekit_connected_flag: threading.Event | None = None
        stt_params: dict | None = None

        if config is not None:
            from alexa_custom.actions import TelegramClient

            connect_trigger = threading.Event()
            livekit_connected_flag = threading.Event()

            async def _livekit_connect_fn() -> None:
                assert connect_trigger is not None
                connect_trigger.set()

            stt_params = {
                "config": config,
                "stop_event": threading.Event(),
                "telegram_client": TelegramClient(),
                "connect_fn": _livekit_connect_fn,
                "connected_flag": livekit_connected_flag,
            }

        async def _run_for_tui(
            stop_threading: threading.Event,
            on_event: Callable,
            stop_asyncio: asyncio.Event,
        ) -> None:
            await _async_main(
                ext_stop_event=stop_asyncio,
                on_event=on_event,
                connect_trigger=connect_trigger,
                livekit_connected_flag=livekit_connected_flag,
            )

        run_tui(
            run_fn=_run_for_tui,
            input_spec=input_spec,
            output_spec=output_spec,
            room=room,
            stt_params=stt_params,
        )

        # LiveKit's Rust FFI leaves non-cooperative threads that block Python
        # 3.13's finalizer.  The terminal is already restored by this point
        # (Textual's cleanup ran inside app.run()), so a hard exit is safe.
        import time as _time
        import os as _os

        _time.sleep(0.2)
        _os._exit(0)

    else:
        if config is not None:
            from alexa_custom.actions import TelegramClient
            from alexa_custom.stt import start_stt_thread

            connect_trigger = threading.Event()
            livekit_connected_flag = threading.Event()
            telegram_client = TelegramClient()
            stt_stop = threading.Event()

            async def _livekit_connect_fn() -> None:
                connect_trigger.set()

            start_stt_thread(
                config=config,
                stop_event=stt_stop,
                telegram_client=telegram_client,
                livekit_connect_fn=_livekit_connect_fn,
                livekit_connected_flag=livekit_connected_flag,
            )
            logger.info(
                f"STT started — wake words: {config.wake_words}, "
                f"{len(config.triggers)} trigger(s) configured"
            )

            try:
                asyncio.run(
                    _async_main(
                        connect_trigger=connect_trigger,
                        livekit_connected_flag=livekit_connected_flag,
                    )
                )
            finally:
                stt_stop.set()
        else:
            asyncio.run(_async_main())


if __name__ == "__main__":
    main()
