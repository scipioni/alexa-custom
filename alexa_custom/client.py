#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Callable

from livekit.api import AccessToken, VideoGrants
from livekit.rtc import (
    AudioStream,
    LocalAudioTrack,
    MediaDevices,
    Room,
    TrackKind,
    TrackPublishOptions,
    TrackSource,
)

from alexa_custom._env import require_env
import sounddevice as sd
from alexa_custom.config import ActionsConfig
from alexa_custom.mqtt import MQTTClient


from alexa_custom.audio import (
    find_pipewire_device,
    play_call_end,
    play_call_start,
    set_pipewire_defaults,
)
from alexa_custom.watchdog import sd_notify, should_use_watchdog

# Re-exported for backward compatibility (tests and callers import these from client).
from alexa_custom.livekit_audio import (  # noqa: F401
    PaplayAudioOutput,
    ParecAudioCapture,
    calculate_peak,
)

RECONNECT_DELAY = 5  # seconds between reconnect attempts


def _stt_heartbeat_fresh(
    stt_heartbeat_ref: "list[float] | None",
    heartbeat_freshness: float,
) -> bool:
    """Return True when the STT heartbeat is recent enough to justify a watchdog ping.

    Returns True unconditionally when STT is not running or no freshness threshold
    is configured (watchdog_sec <= ping_interval).
    """
    if stt_heartbeat_ref is None or heartbeat_freshness <= 0.0:
        return True
    return (time.monotonic() - stt_heartbeat_ref[0]) < heartbeat_freshness


async def _graceful_shutdown(
    stt_stop: threading.Event | None,
    mqtt_client,
    livekit_stop: asyncio.Event | None,
) -> None:
    """Ordered teardown: STT → MQTT offline → LiveKit stop → drain → os.execv."""
    import sys

    logger.info("Graceful shutdown: stopping STT...")
    if stt_stop is not None:
        stt_stop.set()

    if mqtt_client is not None:
        logger.info("Graceful shutdown: publishing MQTT offline...")
        try:
            await asyncio.wait_for(mqtt_client.publish_offline(), timeout=0.5)
        except Exception as e:
            logger.debug("MQTT offline publish failed: %s", e)

    if livekit_stop is not None:
        logger.info("Graceful shutdown: stopping LiveKit session...")
        livekit_stop.set()

    await asyncio.sleep(0.3)
    logger.info("Graceful shutdown: restarting process...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
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
    room_url = require_env("LIVEKIT_URL")
    require_env("LIVEKIT_ROOM")
    params = urllib.parse.urlencode({"liveKitUrl": room_url, "token": token})
    return f"https://meet.livekit.io/custom/?{params}"


class LiveKitSessionManager:
    """Manages a single LiveKit room session, track publishing, and player state."""

    def __init__(
        self,
        mic,
        devices: MediaDevices,
        pw_device: int,
        on_event: Callable[[str, dict], None] | None = None,
        empty_room_timeout: int = 0,
        wait_for_participant: bool = True,
        answer_timeout: float = 60,
        call_tone: bool = True,
    ):
        self.mic = mic
        self.devices = devices
        self.pw_device = pw_device
        self.on_event = on_event
        self._empty_room_timeout = empty_room_timeout
        self._wait_for_participant = wait_for_participant
        self._answer_timeout = answer_timeout
        self._call_tone = call_tone
        self.room = Room()
        self.disconnected = asyncio.Event()
        self._participant_arrived = asyncio.Event()
        self.call_connected = False
        self.subscribed_tracks: dict[str, AudioStream] = {}
        self.player_tracks: set[str] = set()
        self.volumes = {"mic": 0.0, "spk": 0.0}
        self.tap_tasks: list[asyncio.Task] = []
        self.player = None

        @self.room.on("disconnected")
        def on_disconnected(reason):
            logger.info(f"Room disconnected: {reason}")
            self.emit("disconnected", {"reason": reason})
            self.disconnected.set()

        @self.room.on("track_subscribed")
        def on_track_subscribed(track, publication, participant):
            if track.kind == TrackKind.KIND_AUDIO:
                logger.info(f"Audio track subscribed from {participant.identity}")
                self.emit(
                    "track_subscribed",
                    {"identity": participant.identity, "track_sid": track.sid},
                )

                async def _add():
                    try:
                        await self.player.add_track(track)
                        self.player_tracks.add(track.sid)
                        logger.debug(f"Track {track.sid} added to player")
                    except Exception as e:
                        logger.error(f"add_track failed: {e}")

                asyncio.create_task(_add())

        @self.room.on("track_unsubscribed")
        def on_track_unsubscribed(track, publication, participant):
            if track.kind == TrackKind.KIND_AUDIO:
                logger.info(f"Audio track unsubscribed from {participant.identity}")
                self.emit("track_unsubscribed", {"identity": participant.identity})
                self.subscribed_tracks.pop(participant.identity, None)
                if track.sid in self.player_tracks:
                    asyncio.create_task(self.player.remove_track(track))
                    self.player_tracks.discard(track.sid)

        @self.room.on("participant_connected")
        def on_participant_connected(participant):
            logger.info(f"Participant joined: {participant.identity}")
            self._participant_arrived.set()
            self.emit("participant_joined", {"identity": participant.identity})

        @self.room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.info(f"Participant left: {participant.identity}")
            self.emit("participant_left", {"identity": participant.identity})

            # Disconnect if no other remote participants are left in the room
            other_participants = [
                p
                for p in self.room.remote_participants.values()
                if p.identity != participant.identity
            ]
            if not other_participants:
                logger.info("Last participant left — disconnecting call")
                self.disconnected.set()

    def emit(self, event: str, data: dict | None = None) -> None:
        if self.on_event:
            self.on_event(event, data or {})

    async def _tap_mic(self, track: LocalAudioTrack, stop_event: asyncio.Event):
        stream = AudioStream(track)
        async for event in stream:
            self.volumes["mic"] = max(self.volumes["mic"], calculate_peak(event.frame))
            if self.disconnected.is_set() or stop_event.is_set():
                break

    def _update_spk(self, peak: float) -> None:
        self.volumes["spk"] = max(self.volumes["spk"], peak)

    async def _volume_emitter(self, stop_event: asyncio.Event):
        while not self.disconnected.is_set() and not stop_event.is_set():
            await asyncio.sleep(0.1)
            self.emit(
                "volume_update",
                {"mic": self.volumes["mic"], "spk": self.volumes["spk"]},
            )
            self.volumes["mic"] *= 0.6
            self.volumes["spk"] *= 0.6

    async def _empty_room_watchdog(
        self, timeout: float, stop_event: asyncio.Event
    ) -> None:
        import time as _time

        empty_since: float | None = (
            None if self.room.remote_participants else _time.monotonic()
        )
        while not self.disconnected.is_set() and not stop_event.is_set():
            await asyncio.sleep(1.0)
            if self.room.remote_participants:
                empty_since = None
            else:
                now = _time.monotonic()
                if empty_since is None:
                    empty_since = now
                    logger.info(f"Room empty — disconnecting in {timeout:.0f}s")
                elif now - empty_since >= timeout:
                    logger.info("Empty room timeout — disconnecting session")
                    self.emit("empty_room_timeout", {})
                    self.disconnected.set()
                    return

    async def run(self, stop_event: asyncio.Event):
        """Connect to one LiveKit session; return when disconnected or stop_event fires."""
        empty_room_timeout = self._empty_room_timeout

        if self.pw_device is None:
            # PortAudio was built ALSA-only on this board and can't open any output.
            # Use aplay -D pipewire to route remote audio through PipeWire instead.
            logger.debug(
                "Using PaplayAudioOutput for remote audio (PortAudio unavailable)"
            )
            self.player = PaplayAudioOutput(on_frame_peak=self._update_spk)
        else:
            self.player = self.devices.open_output(output_device=self.pw_device)
        await self.player.start()
        logger.debug("Session player started")

        try:
            room_url = require_env("LIVEKIT_URL")
            await self.room.connect(room_url, get_token())
            room_name = require_env("LIVEKIT_ROOM")
            logger.info(
                f"Connected to {room_url}/{room_name} as {self.room.local_participant.identity}"
            )
            self.emit(
                "connected",
                {"room": room_name, "identity": self.room.local_participant.identity},
            )
            self.call_connected = True

            for p in self.room.remote_participants.values():
                self._participant_arrived.set()
                self.emit("participant_joined", {"identity": p.identity})

            if self._wait_for_participant and not self.room.remote_participants:
                logger.info(
                    f"Waiting for a participant to join (timeout {self._answer_timeout}s)…"
                )
                self.emit("waiting_for_participant", {"timeout": self._answer_timeout})
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(self._participant_arrived.wait()),
                        asyncio.create_task(stop_event.wait()),
                    ],
                    timeout=self._answer_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if stop_event.is_set() or not done:
                    if not done:
                        logger.info(
                            "Answer timeout — no participant joined, disconnecting"
                        )
                        self.emit("answer_timeout", {})
                    return

            if self._call_tone:
                asyncio.create_task(asyncio.to_thread(play_call_start))

            track = LocalAudioTrack.create_audio_track("microphone", self.mic.source)
            opts = TrackPublishOptions()
            opts.source = TrackSource.SOURCE_MICROPHONE
            await self.room.local_participant.publish_track(track, opts)
            logger.info("Microphone track published — full duplex active")

            self.tap_tasks.append(asyncio.create_task(self._tap_mic(track, stop_event)))
            self.tap_tasks.append(asyncio.create_task(self._volume_emitter(stop_event)))

            if empty_room_timeout > 0:
                self.tap_tasks.append(
                    asyncio.create_task(
                        self._empty_room_watchdog(empty_room_timeout, stop_event)
                    )
                )

            waiters = [
                asyncio.create_task(self.disconnected.wait()),
                asyncio.create_task(stop_event.wait()),
            ]
            try:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for w in waiters:
                    w.cancel()
        finally:
            await self.cleanup()

    async def cleanup(self):
        logger.debug("Cleaning up session tasks and player...")
        for t in self.tap_tasks:
            t.cancel()
        self.tap_tasks.clear()
        self.subscribed_tracks.clear()
        # Signal disconnection early so STT ungates while we finish cleanup.
        # The room "disconnected" event may not fire until room.disconnect() below.
        logger.debug("cleanup: emitting early 'disconnected' to ungate STT")
        self.emit("disconnected", {})
        if self.call_connected and self._call_tone:
            try:
                await asyncio.to_thread(play_call_end)
            except Exception:
                pass
        await self.room.disconnect()
        if self.player:
            await self.player.aclose()
        logger.debug("Session cleanup complete")


async def _poll_for_participant(
    room_name: str,
    timeout: float,
    stop_event: asyncio.Event,
    poll_interval: float = 2.0,
) -> bool:
    """Poll the LiveKit REST API until a remote participant appears or timeout/stop fires.

    Returns True if a participant was found, False on timeout or stop.
    """
    from livekit import api as lkapi
    from livekit.api import ListParticipantsRequest

    deadline = asyncio.get_event_loop().time() + timeout
    async with lkapi.LiveKitAPI() as svc:
        while not stop_event.is_set():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return False
            try:
                resp = await svc.room.list_participants(
                    ListParticipantsRequest(room=room_name)
                )
                others = [
                    p for p in resp.participants if p.identity != "headless-participant"
                ]
                if others:
                    return True
            except Exception as e:
                logger.debug("Poll participants error: %s", e)
            waiters = [
                asyncio.create_task(stop_event.wait()),
                asyncio.create_task(asyncio.sleep(min(poll_interval, remaining))),
            ]
            try:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for w in waiters:
                    w.cancel()
    return False


async def run_session(
    mic,
    devices: MediaDevices,
    pw_device: int,
    stop_event: asyncio.Event,
    on_event: Callable[[str, dict], None] | None = None,
    empty_room_timeout: int = 0,
    wait_for_participant: bool = True,
    answer_timeout: float = 60,
    call_tone: bool = True,
):
    """Connect to one LiveKit session; return when disconnected or stop_event fires."""
    manager = LiveKitSessionManager(
        mic,
        devices,
        pw_device,
        on_event,
        empty_room_timeout,
        wait_for_participant,
        answer_timeout,
        call_tone,
    )
    await manager.run(stop_event)


async def _async_main(
    ext_stop_event: asyncio.Event | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    connect_trigger: threading.Event | None = None,
    livekit_connected_flag: threading.Event | None = None,
    actions_config: ActionsConfig | None = None,
    mqtt_client: MQTTClient | None = None,
    stt_ready_event: threading.Event | None = None,
) -> None:
    logger.info(f"Browser join URL:\n  {browser_join_url()}")

    input_spec = (
        actions_config.audio.input_device
        if actions_config is not None
        else os.environ.get("INPUT_DEVICE", "").strip() or None
    )
    output_spec = (
        actions_config.audio.output_device
        if actions_config is not None
        else os.environ.get("OUTPUT_DEVICE", "").strip() or None
    )

    # Route PipeWire to the requested devices, then always talk to LiveKit
    # through the PipeWire virtual device — never open hw: devices directly.
    if input_spec or output_spec:
        await asyncio.to_thread(set_pipewire_defaults, input_spec, output_spec)
        logger.info(
            f"PipeWire routed — input: {input_spec or 'default'}, output: {output_spec or 'default'}"
        )

    pw_device = find_pipewire_device()
    if pw_device is None:
        # PortAudio on this board was compiled with ALSA only — no "pipewire"
        # virtual device is listed.  Pass None so LiveKit uses its own default.
        logger.warning(
            "PipeWire PortAudio device not found — using system default for LiveKit I/O"
        )
    else:
        in_info = sd.query_devices(pw_device)
        out_info = sd.query_devices(pw_device)
        logger.info(
            f"Input device:  {input_spec or in_info['name']} ({in_info['max_input_channels']} ch)"
        )
        logger.info(
            f"Output device: {output_spec or out_info['name']} ({out_info['max_output_channels']} ch)"
        )

    if on_event:
        on_event("starting", {})

    # Wait for AudioWatcher to configure hardware before executing startup actions
    # (otherwise sounds play through the old default, like HDMI)
    from alexa_custom.audio import check_newpie_ready

    _input_spec = actions_config.audio.input_device if actions_config else None
    _output_spec = actions_config.audio.output_device if actions_config else None
    logger.info("Waiting for audio hardware to initialize...")
    for _ in range(15):  # Wait up to 7.5 seconds
        ok, _ = await asyncio.to_thread(check_newpie_ready, _input_spec, _output_spec)
        if ok:
            # Extra settle time for PipeWire/WirePlumber to finalize routing
            await asyncio.sleep(2.0)
            break
        await asyncio.sleep(0.5)

    # Wait for STT backend to finish loading so "Sistema pronto" plays only
    # when the system is actually ready to hear the first wake word.
    if stt_ready_event is not None and not stt_ready_event.is_set():
        logger.info("Waiting for STT backend to initialize...")
        await asyncio.to_thread(stt_ready_event.wait, 60.0)

    # Execute startup actions
    if actions_config and actions_config.on_startup:
        # Prime the audio hardware with a short chime before the first speech
        from alexa_custom.audio import play_tone

        await asyncio.to_thread(play_tone, "startup")
        await asyncio.sleep(0.5)

        logger.info(f"Executing {len(actions_config.on_startup)} startup action(s)")
        from alexa_custom.actions import ActionContext, TelegramClient, _run_action

        # We don't have a connect_fn or connected_flag here in a way that _run_action
        # can use for livekit_join safely during early startup, but we can pass None.
        telegram_client = TelegramClient()
        _startup_ctx = ActionContext(
            telegram_client=telegram_client,
            mqtt_client=mqtt_client,
        )
        for action in actions_config.on_startup:
            try:
                await _run_action(action, _startup_ctx)
            except Exception as e:
                logger.error(f"Startup action {action.type} failed: {e}")

    if on_event:
        on_event("idle", {})

    # Use connection-type-appropriate sample rate from config (default: usb=48000, bt=16000).
    from alexa_custom.audio import check_newpie_ready, get_sample_rates

    _, conn_type = await asyncio.to_thread(
        check_newpie_ready, _input_spec, _output_spec
    )
    _audio_samplerates = get_sample_rates()
    samplerate = _audio_samplerates.get(conn_type, _audio_samplerates.get("usb", 48000))
    if conn_type == "bluetooth":
        logger.info(
            f"Bluetooth detected — using {samplerate}Hz sample rate for session"
        )

    devices = MediaDevices(
        input_sample_rate=samplerate, output_sample_rate=samplerate, num_channels=1
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

    async def _open_mic_async():
        if pw_device is not None:
            # open_input() calls asyncio.create_task() internally — must run on the event loop thread
            return devices.open_input(
                enable_aec=aec,
                noise_suppression=ns,
                high_pass_filter=hpf,
                auto_gain_control=agc,
                input_device=pw_device,
                queue_capacity=200,
            )
        # PortAudio has no input on this board — bypass it with parec.
        # Address the configured device by name (like STT does) rather than
        # relying on the PipeWire default source, which can drift on late-boot
        # routing / USB autosuspend (see docs/audio). resolve_capture_source
        # matches the friendly input_spec against `pactl list sources` to get
        # the exact source name parec's --device expects (None → default).
        from alexa_custom.stt_gating import resolve_capture_source

        source, _ = await asyncio.to_thread(resolve_capture_source, input_spec)
        cap = ParecAudioCapture(capture_device=source)
        await cap.start()
        return cap

    def _wrapped_on_event(event: str, data: dict) -> None:
        if livekit_connected_flag is not None:
            if event == "connected":
                logger.debug("livekit: connected — setting livekit_connected_flag")
                livekit_connected_flag.set()
            elif event == "disconnected":
                logger.debug("livekit: disconnected — clearing livekit_connected_flag")
                livekit_connected_flag.clear()
        if on_event:
            on_event(event, data)

    reconnect_delay = (
        actions_config.system.reconnect_delay
        if actions_config is not None
        else RECONNECT_DELAY
    )
    _base_reconnect_delay = reconnect_delay
    _ever_connected = False

    use_watchdog = should_use_watchdog()
    last_watchdog_ping = 0.0
    watchdog_interval = 10.0  # ping every 10 seconds

    # Compute STT heartbeat freshness threshold from systemd's WatchdogSec.
    # If the STT thread stamps more than `_heartbeat_freshness` seconds ago, the
    # ping is withheld so systemd restarts a deaf/hung assistant.
    _watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    _watchdog_sec = _watchdog_usec / 1_000_000 if _watchdog_usec > 0 else 0.0
    _heartbeat_freshness = (
        _watchdog_sec - watchdog_interval if _watchdog_sec > watchdog_interval else 0.0
    )

    # Grab a reference to the STT heartbeat holder so the ping loop can read it
    # without importing inside the hot path. Only gate when STT is running
    # (indicated by stt_ready_event being provided by the caller).
    _stt_heartbeat_ref: list[float] | None = None
    if stt_ready_event is not None:
        from alexa_custom.stt import _stt_heartbeat as _imported_hb

        _stt_heartbeat_ref = _imported_hb

    # Send initial systemd notification to signal startup complete.
    if use_watchdog:
        if _watchdog_sec > 0:
            logger.info(
                "Watchdog: WatchdogSec=%.0fs ping_interval=%.0fs heartbeat_freshness=%.0fs",
                _watchdog_sec,
                watchdog_interval,
                _heartbeat_freshness if _heartbeat_freshness > 0 else float("inf"),
            )
        sd_notify("READY=1")
        last_watchdog_ping = time.time()

    try:
        while not stop_event.is_set():
            # Periodically ping systemd watchdog to prevent auto-restart.
            # Only ping if enabled (Type=notify + WatchdogSec in systemd unit).
            # Ping is gated on STT heartbeat freshness: a hung STT thread stops
            # stamping, the heartbeat goes stale, and systemd triggers a restart.
            if use_watchdog and (time.time() - last_watchdog_ping) >= watchdog_interval:
                if _stt_heartbeat_fresh(_stt_heartbeat_ref, _heartbeat_freshness):
                    sd_notify("WATCHDOG=1")
                    last_watchdog_ping = time.time()
                else:
                    heartbeat_age = time.monotonic() - (_stt_heartbeat_ref or [0.0])[0]
                    logger.warning(
                        "Watchdog: STT heartbeat stale (%.0fs old, threshold=%.0fs)"
                        " — withholding ping",
                        heartbeat_age,
                        _heartbeat_freshness,
                    )

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

            connected_this_session = False
            _empty_room_timeout = (
                actions_config.system.empty_room_timeout if actions_config else 0
            )
            _wait_for_participant = (
                actions_config.system.wait_for_participant if actions_config else True
            )
            _answer_timeout = (
                actions_config.system.answer_timeout if actions_config else 60.0
            )

            def _on_event_interceptor(event: str, data: dict):
                nonlocal connected_this_session, _ever_connected
                if event == "connected":
                    connected_this_session = True
                    _ever_connected = True
                _wrapped_on_event(event, data)

            if _wait_for_participant:
                room_name = require_env("LIVEKIT_ROOM")
                logger.info(
                    f"Waiting for a participant in room '{room_name}' "
                    f"(polling, timeout {_answer_timeout}s)…"
                )
                _wrapped_on_event(
                    "room_status",
                    {"status": "waiting", "timeout": _answer_timeout},
                )
                found = await _poll_for_participant(
                    room_name, _answer_timeout, stop_event
                )
                if not found:
                    logger.info("Answer timeout — no participant appeared, closing")
                    _wrapped_on_event("room_status", {"status": "closed"})
                    _wrapped_on_event("answer_timeout", {})
                    if connect_trigger is not None:
                        continue
                    break
            else:
                _wrapped_on_event(
                    "reconnecting" if _ever_connected else "connecting", {}
                )

            if pw_device is not None:
                logger.info(
                    f"Opening microphone via PortAudio (AEC={aec} NS={ns} HPF={hpf} AGC={agc} rate={samplerate})..."
                )
            else:
                logger.info(
                    "Opening microphone via parec (PortAudio has no input on this board)..."
                )
            try:
                mic = await asyncio.wait_for(_open_mic_async(), timeout=15.0)
            except Exception as e:
                logger.error(f"Failed to open microphone: {e} — skipping session")
                _wrapped_on_event("room_status", {"status": "closed"})
                if connect_trigger is not None:
                    continue
                await asyncio.sleep(reconnect_delay)
                continue

            _call_tone = (
                actions_config.recognition.call_tone if actions_config else True
            )
            try:
                await run_session(
                    mic,
                    devices,
                    pw_device,
                    stop_event,
                    on_event=_on_event_interceptor,
                    empty_room_timeout=_empty_room_timeout,
                    wait_for_participant=False,
                    answer_timeout=_answer_timeout,
                    call_tone=_call_tone,
                )
            except Exception as e:
                logger.error(f"Session error: {e}")
            finally:
                await mic.aclose()
                _wrapped_on_event("room_status", {"status": "closed"})

            if livekit_connected_flag is not None:
                livekit_connected_flag.clear()

            if stop_event.is_set():
                break

            # In on-demand mode don't auto-reconnect; wait for another trigger.
            if connect_trigger is not None:
                reconnect_delay = _base_reconnect_delay
                logger.info("LiveKit session ended — waiting for next voice trigger")
                continue

            if connected_this_session:
                reconnect_delay = _base_reconnect_delay
            else:
                reconnect_delay = min(reconnect_delay * 2, 30)

            logger.info(f"Reconnecting in {reconnect_delay}s...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=reconnect_delay)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Shutting down LiveKit loop...")


def _mqtt_settings_from_config(config: ActionsConfig | None) -> dict:
    if config is not None and config.mqtt is not None:
        return {
            "host": config.mqtt.host,
            "port": str(config.mqtt.port),
            "prefix": config.mqtt.topic_prefix,
            "node_id": config.mqtt.node_id,
            "queue_max": config.mqtt.queue_max,
        }
    return {
        "host": None,
        "port": "1883",
        "prefix": "alexa",
        "node_id": None,
        "queue_max": 200,
    }


def make_mqtt_reload_callback(
    client_holder: list,  # list[MQTTClient | None] — mutable single-element container
    loop: asyncio.AbstractEventLoop,
    initial_config: ActionsConfig | None = None,
):
    """Return a reload callback that reconnects MQTT when broker settings change."""
    # Seed from the current config so the first reload of an *unrelated* setting
    # doesn't spuriously tear down and recreate the MQTT client.
    prev_settings: dict = (
        _mqtt_settings_from_config(initial_config) if initial_config is not None else {}
    )

    def _callback(new_config: ActionsConfig) -> None:
        nonlocal prev_settings
        current = _mqtt_settings_from_config(new_config)
        if current == prev_settings:
            return
        prev_settings = current
        logger.info("MQTT settings changed on reload — reconnecting MQTT client")

        old_client: MQTTClient | None = client_holder[0]
        if old_client is not None:
            asyncio.run_coroutine_threadsafe(old_client.stop(), loop)

        host = current["host"]
        if host:
            new_client = MQTTClient(
                host=host,
                port=int(current["port"]),
                topic_prefix=current["prefix"],
                node_id=current["node_id"],
            )
            asyncio.run_coroutine_threadsafe(new_client.run(), loop)
            client_holder[0] = new_client
        else:
            client_holder[0] = None

    return _callback


def ensure_setup() -> None:
    """Download Vosk model and the default Piper voice if missing."""
    from alexa_custom.setup import download_piper_voice, download_vosk
    from alexa_custom.stt import _MODEL_PATH
    from alexa_custom.tts import PIPER_VOICES_DIR

    if not os.path.isdir(_MODEL_PATH):
        logger.info(
            f"Vosk model not found at {_MODEL_PATH}. Downloading automatically..."
        )
        try:
            download_vosk()
        except Exception as e:
            logger.error(f"Failed to download Vosk model: {e}")

    default_voice = "it_IT-paola-medium"
    voice_onnx = PIPER_VOICES_DIR / f"{default_voice}.onnx"
    if not voice_onnx.is_file():
        logger.info(
            f"Piper voice not found at {voice_onnx}. Downloading automatically..."
        )
        try:
            download_piper_voice(default_voice)
        except Exception as e:
            logger.error(f"Failed to download Piper voice: {e}")


def main() -> None:
    import argparse
    import threading

    from alexa_custom import __version__

    parser = argparse.ArgumentParser(description="alexa-custom LiveKit client")
    parser.add_argument(
        "--version", action="version", version=f"alexa-custom {__version__}"
    )
    parser.add_argument(
        "--config",
        metavar="DIR",
        default="conf",
        help="Configuration directory (default: conf)",
    )
    parser.add_argument(
        "--web-port", type=int, default=None, help="Web dashboard port (default: 8080)"
    )
    parser.add_argument(
        "--hot-reload", action="store_true", help="Auto-restart on .py file changes"
    )
    args = parser.parse_args()

    conf_dir = Path(args.config)

    from alexa_custom.config import load_config, load_secrets

    secrets = load_secrets(conf_dir / "secrets.yaml")
    config = load_config(conf_dir / "config.yaml", secrets=secrets)

    ensure_setup()

    if args.hot_reload:
        logger.info("Hot-reload enabled (watching alexa_custom/*.py)")

    from alexa_custom.web import run_web
    import alexa_custom.audio_hw as audio_hw

    if config is not None:
        audio_hw.configure(config)

    input_spec = config.audio.input_device if config is not None else None
    output_spec = config.audio.output_device if config is not None else None
    output_volume = audio_hw.get_output_volume()
    input_gain = audio_hw.get_input_gain()
    room = os.environ.get("LIVEKIT_ROOM", "")

    # Optional display controller
    display_controller = None
    if config is not None and config.display is not None and config.display.enabled:
        from alexa_custom.display import DisplayController, get_display_backend

        dc = config.display
        os.environ.setdefault("ALEXA_DISPLAY_I2C_BUS", str(dc.i2c_bus))
        os.environ.setdefault("ALEXA_DISPLAY_I2C_ADDR", hex(dc.i2c_address))
        os.environ.setdefault("ALEXA_DISPLAY_I2C_WIDTH", str(dc.i2c_width))
        os.environ.setdefault("ALEXA_DISPLAY_I2C_HEIGHT", str(dc.i2c_height))
        os.environ.setdefault("ALEXA_DISPLAY_TRANSPORT", dc.transport)
        backend = get_display_backend(dc.backend, dc.transport)
        display_controller = DisplayController(backend)
        logger.info(
            "Display feedback enabled (backend=%s)",
            type(backend).__name__,
        )

    # Port: CLI flag > config.web.port > default 8080
    web_port = args.web_port or (config.web.port if config is not None else 8080)

    connect_trigger: threading.Event | None = None
    livekit_connected_flag: threading.Event | None = None
    stt_params: dict | None = None

    if config is not None:
        from alexa_custom.actions import TelegramClient
        from alexa_custom.tts import init_engine

        connect_trigger = threading.Event()
        livekit_connected_flag = threading.Event()
        stt_ready_event = threading.Event()

        init_engine(
            backend_type=config.tts.backend,
            voice=config.tts.voice,
            stt_gated_flag=livekit_connected_flag,
            preroll_ms=config.tts.preroll_ms,
        )

        async def _livekit_connect_fn_web() -> None:
            assert connect_trigger is not None
            connect_trigger.set()

        stt_params = {
            "config": config,
            "stop_event": threading.Event(),
            "telegram_client": TelegramClient(),
            "connect_fn": _livekit_connect_fn_web,
            "connected_flag": livekit_connected_flag,
            "stt_ready_event": stt_ready_event,
        }

        if config.llm is not None:
            logger.info(
                f"LLM enabled — backend: {config.llm.backend}, "
                f"model: {config.llm.model}, host: {config.llm.host}"
                + (", fallback on no match" if config.llm.fallback_on_no_match else "")
                + (", command learning" if config.llm.learn_commands else "")
            )
        else:
            logger.info("LLM disabled")

    async def _run_for_web(
        stop_threading: threading.Event,
        on_event: Callable,
        stop_asyncio: asyncio.Event,
    ) -> None:
        await _async_main(
            ext_stop_event=stop_asyncio,
            on_event=on_event,
            connect_trigger=connect_trigger,
            livekit_connected_flag=livekit_connected_flag,
            actions_config=config,
            stt_ready_event=stt_params["stt_ready_event"] if stt_params else None,
        )

    run_web(
        run_fn=_run_for_web,
        input_spec=input_spec,
        output_spec=output_spec,
        room=room,
        stt_params=stt_params,
        port=web_port,
        hot_reload=args.hot_reload,
        watch_paths=[conf_dir],
        conf_dir=conf_dir,
        output_volume=output_volume,
        input_gain=input_gain,
        shutdown_callback=None,
        extra_event_cb=display_controller.on_event if display_controller else None,
        extra_stt_event_cb=display_controller.on_stt_event
        if display_controller
        else None,
    )

    import time as _time
    import os as _os

    if display_controller is not None:
        display_controller._stop.set()
        display_controller._queue.put(("stop", None, None))
        display_controller._thread.join(timeout=3)
        try:
            from alexa_custom.display import BridgeDisplay

            logger.info("Display shutdown: connecting to Router...")
            bc = BridgeDisplay(host="127.0.0.1", port=7501)
            logger.info("Display shutdown: showing exit icon...")
            bc.show("starting")
            _time.sleep(1.0)
            logger.info("Display shutdown: clearing...")
            bc.clear()
            logger.info("Display shutdown: done")
        except Exception as exc:
            logger.warning("Display shutdown failed: %s", exc)

    _time.sleep(0.2)
    _os._exit(0)


if __name__ == "__main__":
    main()
