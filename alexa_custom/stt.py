from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
import unicodedata
from typing import Awaitable, Callable, TYPE_CHECKING

import numpy as np
import vosk

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom.actions import TelegramClient, dispatch, match_trigger
from alexa_custom.audio import play_timeout_beep, play_wake_beep
from alexa_custom.config import ActionsConfig, Trigger, WakeWordGroup

logger = logging.getLogger(__name__)

_CHUNK = 4096
_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_STT_COOLDOWN = 1.0


def normalize_text(text: str) -> str:
    """Lowercase and remove diacritics (e.g., 'sì' -> 'si')."""
    if not text:
        return ""
    # Normalize to NFD (decomposed) to separate diacritics from base characters
    nfd = unicodedata.normalize("NFD", text.lower())
    # Filter out non-spacing marks (Mn category)
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    # Back to NFC (composed)
    return unicodedata.normalize("NFC", stripped).strip()


def resolve_capture_source(input_spec: str | None) -> tuple[str | None, int]:
    """Map INPUT_DEVICE value to a PipeWire source name and channel count via pactl."""
    channels = 1
    if not input_spec:
        return None, channels
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, timeout=5
        )
        needle = input_spec.lower()
        source_name = None
        found = False
        for line in out.splitlines():
            if "Name: " in line:
                name = line.split(": ")[1].strip()
                if needle in name.lower() and "monitor" not in name.lower():
                    source_name = name
                    found = True
            if found and "Channels: " in line:
                try:
                    channels = int(line.split(":")[1].strip())
                except Exception:
                    channels = 1
                return source_name, channels

        logger.warning(f"No PipeWire source matching {input_spec!r} — using default")
    except Exception as e:
        logger.warning(f"resolve_capture_source failed: {e} — using default")
    return None, channels


def start_capture(source: str | None, channels: int = 1) -> subprocess.Popen:
    """Start a low-latency recording process (parec)."""
    import shutil

    tool = shutil.which("parec")
    if not tool:
        tool = shutil.which("pw-record")
        if not tool:
            raise RuntimeError("Neither parec nor pw-record found on system")

    is_pw = "pw-record" in tool
    cmd = [
        tool,
        "--rate=16000",
        f"--channels={channels}",
        "--format=s16le" if not is_pw else "--format=s16",
    ]

    if is_pw:
        cmd.extend(["--media-type=audio", "--media-role=communication"])
        if source:
            cmd.append(f"--target={source}")
    else:
        # Crucial: very low latency helps 'parec' start flowing on PipeWire
        cmd.append("--latency-msec=1")
        if source:
            cmd.append(f"--device={source}")

    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _load_model() -> vosk.Model:
    if not os.path.isdir(_MODEL_PATH):
        raise RuntimeError(
            f"Vosk model not found at {_MODEL_PATH!r}. Run 'alexa-setup' to download it."
        )
    vosk.SetLogLevel(-1)
    return vosk.Model(_MODEL_PATH)


def _grammar_json(groups: list[WakeWordGroup]) -> str:
    phrases = [p for g in groups for p in [g.word] + g.aliases]
    return json.dumps(phrases + ["[unk]"])


def _build_alias_map(groups: list[WakeWordGroup]) -> dict[str, WakeWordGroup]:
    return {
        normalize_text(phrase): group
        for group in groups
        for phrase in [group.word] + group.aliases
    }


def _resolve_triggers(group: WakeWordGroup, fallback: list[Trigger]) -> list[Trigger]:
    return group.triggers if group.triggers else fallback


def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    n = len(samples)
    if n == 0:
        return 0.0
    return float(np.linalg.norm(samples)) / (32768.0 * n**0.5)


def _downmix_to_mono(data: bytes, channels: int) -> bytes:
    """Take the loudest signal across all channels to ensure mono-downmix is high-gain."""
    if channels <= 1:
        return data
    samples = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)
    # Use max absolute value across channels to avoid diluting the signal with empty jacks.
    idx = np.argmax(np.abs(samples), axis=1)
    mono = samples[np.arange(len(samples)), idx]
    return mono.tobytes()


def run_stt_worker(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Entry point for the STT daemon thread.

    ``config`` may be a bare ActionsConfig or a zero-argument callable that
    returns the current ActionsConfig.  The callable form allows the caller to
    supply a live getter so the STT loop picks up hot-reloaded config on the
    next capture-process restart.
    """
    _get_config: Callable[[], ActionsConfig]
    if callable(config) and not isinstance(config, ActionsConfig):
        _get_config = config  # type: ignore[assignment]
    else:

        def _get_config():
            return config  # type: ignore[return-value]

    try:
        model = _load_model()
    except RuntimeError as e:
        logger.error(f"STT startup failed: {e}")
        return

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    source, channels = resolve_capture_source(input_spec)

    current_config = _get_config()
    logger.info(
        f"STT: wake words={[g.word for g in current_config.wake_words]}, "
        f"timeout={current_config.command_timeout}s, "
        f"source={source or 'default'} ({channels} ch)"
    )

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    _dispatch_loop = asyncio.new_event_loop()
    try:
        while not stop_event.is_set():
            # Re-read config on every outer iteration so hot-reload propagates when
            # the capture process restarts (e.g., after an error or device reset).
            current_config = _get_config()
            loop_fn = (
                _single_stage_loop
                if current_config.recognition_mode == "single-stage"
                else _recognition_loop
            )
            proc: subprocess.Popen | None = None
            try:
                proc = start_capture(source, channels)
                loop_fn(
                    proc=proc,
                    channels=channels,
                    model=model,
                    config=current_config,
                    stop_event=stop_event,
                    telegram_client=telegram_client,
                    livekit_connect_fn=livekit_connect_fn,
                    livekit_connected_flag=livekit_connected_flag,
                    on_stt_event=on_stt_event,
                    mqtt_client=mqtt_client,
                    loop=loop,
                    dispatch_loop=_dispatch_loop,
                )
            except Exception as e:
                logger.error(f"STT error: {e}")
                time.sleep(2)
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
    finally:
        _dispatch_loop.close()


def _extract_wake_command(
    text: str, alias_map: dict[str, WakeWordGroup]
) -> tuple[WakeWordGroup | None, str]:
    """Return (group, command) if text begins with a known wake phrase, else (None, '')."""
    norm_text = normalize_text(text)
    for norm_phrase, group in alias_map.items():
        if norm_text.startswith(norm_phrase):
            command = text.lower().replace(norm_phrase, "", 1).strip()
            return group, command
    return None, ""


def capture_transcript(
    proc: subprocess.Popen,
    channels: int,
    model: vosk.Model,
    timeout: float,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> str:
    """Capture audio for a set duration and return the transcribed text."""
    stage2 = vosk.KaldiRecognizer(model, 16000)
    deadline = time.monotonic() + timeout
    transcript_parts: list[str] = []

    assert proc.stdout is not None
    while not stop_event.is_set() and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        raw_data = proc.stdout.read(_CHUNK * channels)
        if not raw_data:
            break

        data = _downmix_to_mono(raw_data, channels)

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if stage2.AcceptWaveform(data):
            result = json.loads(stage2.Result())
            text = result.get("text", "").strip()
            if text:
                transcript_parts.append(text)
                logger.info(f"Capture partial: '{text}'")
                if on_stt_event:
                    on_stt_event("partial", {"text": " ".join(transcript_parts)})
        else:
            if on_stt_event:
                partial = json.loads(stage2.PartialResult()).get("partial", "").strip()
                if partial:
                    full = " ".join(transcript_parts + [partial])
                    on_stt_event("partial", {"text": full})

    # Collect final partial
    final = json.loads(stage2.FinalResult())
    final_text = final.get("text", "").strip()
    if final_text:
        transcript_parts.append(final_text)

    return " ".join(transcript_parts).strip()


def _single_stage_loop(
    proc: subprocess.Popen,
    channels: int,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: "MQTTClient | None" = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Single-stage: full transcription always; wake word + command in one phrase."""
    rec = vosk.KaldiRecognizer(model, 16000)
    cooldown_until = 0.0
    alias_map = _build_alias_map(config.wake_words)

    if on_stt_event:
        on_stt_event("listening", {"wake_words": [g.word for g in config.wake_words]})

    async def _listen_fn(timeout: float) -> str:
        # Emit event for UI to show we are listening for a reply
        if on_stt_event:
            on_stt_event("wake", {"word": "(reply)", "timeout": timeout})
        return await asyncio.to_thread(
            capture_transcript,
            proc,
            channels,
            model,
            timeout,
            stop_event,
            on_stt_event,
        )

    assert proc.stdout is not None
    while not stop_event.is_set():
        # Adjust chunk size for multi-channel
        raw_data = proc.stdout.read(_CHUNK * channels)
        if not raw_data:
            break

        data = _downmix_to_mono(raw_data, channels)

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if on_stt_event:
                on_stt_event("gated", {})
            continue

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if time.monotonic() < cooldown_until:
            rec.Reset()
            continue

        if not rec.AcceptWaveform(data):
            if on_stt_event:
                partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                if partial:
                    on_stt_event("transcribing", {"text": partial})
            continue

        result = json.loads(rec.Result())
        text = result.get("text", "").strip()
        if not text:
            continue

        wake_group, command = _extract_wake_command(text, alias_map)
        if wake_group is None:
            continue

        logger.info(f"Single-stage: wake='{wake_group.word}' command='{command}'")
        if on_stt_event:
            on_stt_event("wake", {"word": wake_group.word, "timeout": 0})

        try:
            play_wake_beep()
        except Exception as e:
            logger.debug(f"Wake beep failed: {e}")

        if not command:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": ""})
            _play_timeout()
            continue

        triggers = _resolve_triggers(wake_group, config.triggers)
        trigger = match_trigger(command, triggers)
        if trigger is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": command})
            _play_timeout()
            continue

        if on_stt_event:
            on_stt_event("matched", {"transcript": command, "trigger": trigger.phrase})

        connected = livekit_connected_flag.is_set()
        try:
            _dloop = dispatch_loop or asyncio.new_event_loop()
            _dloop.run_until_complete(
                dispatch(
                    trigger,
                    telegram_client,
                    livekit_connect_fn,
                    livekit_connected=connected,
                    listen_fn=_listen_fn,
                    on_stt_event=on_stt_event,
                )
            )
            # Restore UI state after dispatch/dialogue
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
        except Exception as e:
            logger.error(f"Action dispatch failed: {e}")


def _recognition_loop(
    proc: subprocess.Popen,
    channels: int,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    alias_map = _build_alias_map(config.wake_words)
    stage1 = vosk.KaldiRecognizer(model, 16000, _grammar_json(config.wake_words))
    stage1.SetWords(True)
    cooldown_until = 0.0
    was_gated = False

    if on_stt_event:
        on_stt_event("listening", {"wake_words": [g.word for g in config.wake_words]})

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    assert proc.stdout is not None
    while not stop_event.is_set():
        raw_data = proc.stdout.read(_CHUNK * channels)
        if not raw_data:
            break

        data = _downmix_to_mono(raw_data, channels)

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if not was_gated:
                logger.info("STT gated (call active)")
                if on_stt_event:
                    on_stt_event("gated", {})
                if mqtt_client:
                    mqtt_client.publish_threadsafe(
                        f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                        "gated",
                        loop=loop,
                    )
                was_gated = True
            continue

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if was_gated:
            logger.info("STT resumed (call ended)")
            was_gated = False
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
            if mqtt_client:
                mqtt_client.publish_threadsafe(
                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                    "idle",
                    loop=loop,
                )

        if time.monotonic() < cooldown_until:
            stage1.Reset()
            continue

        if stage1.AcceptWaveform(data):
            result = json.loads(stage1.Result())
            text = result.get("text", "").strip()
            words = result.get("result", [])
            conf = words[0].get("conf", 0.0) if words else 0.0
            logger.debug(f"Stage1 result: {text!r} conf={conf:.2f}")
            # Grammar mode may not constrain output on all model/version combos.
            # Explicitly check the result is exactly one of the wake words.
            norm_text = normalize_text(text)
            wake_match = alias_map.get(norm_text)
            if wake_match is not None and conf >= config.wake_confidence:
                _wake_detected(
                    wake_group=wake_match,
                    proc=proc,
                    channels=channels,
                    model=model,
                    config=config,
                    stop_event=stop_event,
                    telegram_client=telegram_client,
                    livekit_connect_fn=livekit_connect_fn,
                    livekit_connected_flag=livekit_connected_flag,
                    on_stt_event=on_stt_event,
                    mqtt_client=mqtt_client,
                    loop=loop,
                    dispatch_loop=dispatch_loop,
                )
                # Re-create stage1 recognizer after command window
                stage1 = vosk.KaldiRecognizer(
                    model, 16000, _grammar_json(config.wake_words)
                )
                stage1.SetWords(True)
                if on_stt_event:
                    on_stt_event(
                        "listening", {"wake_words": [g.word for g in config.wake_words]}
                    )
                if mqtt_client:
                    mqtt_client.publish_threadsafe(
                        f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                        "idle",
                        loop=loop,
                    )
        else:
            if on_stt_event:
                partial = json.loads(stage1.PartialResult()).get("partial", "").strip()
                if partial:
                    on_stt_event("transcribing", {"text": partial})


def _wake_detected(
    wake_group: WakeWordGroup,
    proc: subprocess.Popen,
    channels: int,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    logger.info(f"Wake word detected: '{wake_group.word}'")
    if on_stt_event:
        on_stt_event(
            "wake", {"word": wake_group.word, "timeout": config.command_timeout}
        )
    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
            "listening",
            loop=loop,
        )
    try:
        play_wake_beep()
    except Exception as e:
        logger.debug(f"Wake beep failed: {e}")

    transcript = capture_transcript(
        proc, channels, model, config.command_timeout, stop_event, on_stt_event
    )
    logger.info(f"Command transcript: '{transcript}'")

    if not transcript:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        _play_timeout()
        return

    if mqtt_client:
        payload = json.dumps(
            {"text": transcript, "wake_word": wake_group.word, "timestamp": time.time()}
        )
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/command",
            payload,
            loop=loop,
        )

    triggers = _resolve_triggers(wake_group, config.triggers)
    trigger = match_trigger(transcript, triggers)
    if trigger is None:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": transcript})
        _play_timeout()
        return

    if on_stt_event:
        on_stt_event("matched", {"transcript": transcript, "trigger": trigger.phrase})

    async def _listen_fn(timeout: float) -> str:
        # Emit event for UI to show we are listening for a reply
        if on_stt_event:
            on_stt_event("wake", {"word": "(reply)", "timeout": timeout})
        return await asyncio.to_thread(
            capture_transcript,
            proc,
            channels,
            model,
            timeout,
            stop_event,
            on_stt_event,
        )

    # Dispatch using the persistent loop (we're in a daemon thread, not async context)
    connected = livekit_connected_flag.is_set()
    try:
        _dloop = dispatch_loop or asyncio.new_event_loop()
        _dloop.run_until_complete(
            dispatch(
                trigger,
                telegram_client,
                livekit_connect_fn,
                livekit_connected=connected,
                listen_fn=_listen_fn,
                on_stt_event=on_stt_event,
            )
        )
    except Exception as e:
        logger.error(f"Action dispatch failed: {e}")


def _play_timeout() -> None:
    logger.info("Command window timeout or no match")
    try:
        play_timeout_beep()
    except Exception as e:
        logger.debug(f"Timeout beep failed: {e}")


def start_stt_thread(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> threading.Thread:
    t = threading.Thread(
        target=run_stt_worker,
        args=(
            config,
            stop_event,
            telegram_client,
            livekit_connect_fn,
            livekit_connected_flag,
            on_stt_event,
            mqtt_client,
            loop,
        ),
        daemon=True,
        name="stt",
    )
    t.start()
    return t
