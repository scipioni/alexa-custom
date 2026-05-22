from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from typing import Awaitable, Callable

import numpy as np
import vosk

from alexa_custom.actions import TelegramClient, dispatch, match_trigger
from alexa_custom.audio import play_timeout_beep, play_wake_beep
from alexa_custom.config import ActionsConfig

logger = logging.getLogger(__name__)

_CHUNK = 4096
_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_STT_COOLDOWN = 1.0


def resolve_parec_source(input_spec: str | None) -> str | None:
    """Map INPUT_DEVICE value to a PipeWire source name via pactl."""
    if not input_spec:
        return None
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"], text=True, timeout=5
        )
        needle = input_spec.lower()
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[1]
                if needle in name.lower() and "monitor" not in name.lower():
                    return name
        logger.warning(f"No PipeWire source matching {input_spec!r} — using default")
    except Exception as e:
        logger.warning(f"resolve_parec_source failed: {e} — using default")
    return None


def start_parec(source: str | None) -> subprocess.Popen:
    cmd = [
        "parec",
        "--rate=16000",
        "--channels=1",
        "--format=s16le",
        "--latency-msec=100",
    ]
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


def _grammar_json(wake_words: list[str]) -> str:
    return json.dumps(wake_words + ["[unk]"])


def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2))) / 32768.0


def run_stt_worker(
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> None:
    """Entry point for the STT daemon thread."""
    try:
        model = _load_model()
    except RuntimeError as e:
        logger.error(f"STT startup failed: {e}")
        return

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    source = resolve_parec_source(input_spec)

    logger.info(
        f"STT: wake words={config.wake_words}, timeout={config.command_timeout}s, "
        f"source={source or 'default'}"
    )

    loop_fn = (
        _single_stage_loop
        if config.recognition_mode == "single-stage"
        else _recognition_loop
    )

    while not stop_event.is_set():
        proc: subprocess.Popen | None = None
        try:
            proc = start_parec(source)
            loop_fn(
                proc=proc,
                model=model,
                config=config,
                stop_event=stop_event,
                telegram_client=telegram_client,
                livekit_connect_fn=livekit_connect_fn,
                livekit_connected_flag=livekit_connected_flag,
                on_stt_event=on_stt_event,
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


def _extract_wake_command(text: str, wake_words: list[str]) -> tuple[str, str]:
    """Return (wake_word, command) if text begins with a wake word, else ('', '')."""
    lower = text.lower()
    for word in wake_words:
        if lower.startswith(word.lower()):
            command = text[len(word) :].strip()
            return word, command
    return "", ""


def _single_stage_loop(
    proc: subprocess.Popen,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> None:
    """Single-stage: full transcription always; wake word + command in one phrase."""
    rec = vosk.KaldiRecognizer(model, 16000)
    cooldown_until = 0.0

    if on_stt_event:
        on_stt_event("listening", {"wake_words": config.wake_words})

    assert proc.stdout is not None
    while not stop_event.is_set():
        data = proc.stdout.read(_CHUNK)
        if not data:
            break

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if on_stt_event:
                on_stt_event("gated", {})
            continue

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

        wake_word, command = _extract_wake_command(text, config.wake_words)
        if not wake_word:
            continue

        logger.info(f"Single-stage: wake='{wake_word}' command='{command}'")
        if on_stt_event:
            on_stt_event("wake", {"word": wake_word, "timeout": 0})

        try:
            play_wake_beep()
        except Exception as e:
            logger.debug(f"Wake beep failed: {e}")

        if not command:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": ""})
            _play_timeout()
            continue

        trigger = match_trigger(command, config.triggers)
        if trigger is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": command})
            _play_timeout()
            continue

        if on_stt_event:
            on_stt_event("matched", {"transcript": command, "trigger": trigger.phrase})

        connected = livekit_connected_flag.is_set()
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                dispatch(
                    trigger,
                    telegram_client,
                    livekit_connect_fn,
                    livekit_connected=connected,
                )
            )
            loop.close()
        except Exception as e:
            logger.error(f"Action dispatch failed: {e}")


def _recognition_loop(
    proc: subprocess.Popen,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> None:
    stage1 = vosk.KaldiRecognizer(model, 16000, _grammar_json(config.wake_words))
    stage1.SetWords(True)
    display_rec = vosk.KaldiRecognizer(model, 16000) if on_stt_event else None
    cooldown_until = 0.0
    was_gated = False

    if on_stt_event:
        on_stt_event("listening", {"wake_words": config.wake_words})

    assert proc.stdout is not None
    while not stop_event.is_set():
        data = proc.stdout.read(_CHUNK)
        if not data:
            break

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if not was_gated:
                logger.info("STT gated (call active)")
                if on_stt_event:
                    on_stt_event("gated", {})
                was_gated = True
            continue

        if was_gated:
            logger.info("STT resumed (call ended)")
            was_gated = False
            if on_stt_event:
                on_stt_event("listening", {"wake_words": config.wake_words})

        if time.monotonic() < cooldown_until:
            stage1.Reset()
            if display_rec:
                display_rec.Reset()
            continue

        # Feed display recognizer and emit live partial text.
        if display_rec is not None:
            display_rec.AcceptWaveform(data)
            partial = json.loads(display_rec.PartialResult()).get("partial", "").strip()
            if partial:
                on_stt_event("transcribing", {"text": partial})  # type: ignore[misc]

        if stage1.AcceptWaveform(data):
            result = json.loads(stage1.Result())
            text = result.get("text", "").strip()
            words = result.get("result", [])
            conf = words[0].get("conf", 0.0) if words else 0.0
            logger.debug(f"Stage1 result: {text!r} conf={conf:.2f}")
            # Grammar mode may not constrain output on all model/version combos.
            # Explicitly check the result is exactly one of the wake words.
            wake_match = next(
                (w for w in config.wake_words if w.lower() == text.lower()), ""
            )
            if wake_match and conf >= config.wake_confidence:
                _wake_detected(
                    wake_text=wake_match,
                    proc=proc,
                    model=model,
                    config=config,
                    stop_event=stop_event,
                    telegram_client=telegram_client,
                    livekit_connect_fn=livekit_connect_fn,
                    livekit_connected_flag=livekit_connected_flag,
                    on_stt_event=on_stt_event,
                )
                # Re-create both recognizers after command window
                stage1 = vosk.KaldiRecognizer(
                    model, 16000, _grammar_json(config.wake_words)
                )
                stage1.SetWords(True)
                display_rec = (
                    vosk.KaldiRecognizer(model, 16000) if on_stt_event else None
                )
                if on_stt_event:
                    on_stt_event("listening", {"wake_words": config.wake_words})


def _wake_detected(
    wake_text: str,
    proc: subprocess.Popen,
    model: vosk.Model,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
) -> None:
    logger.info(f"Wake word detected: '{wake_text}'")
    if on_stt_event:
        on_stt_event("wake", {"word": wake_text, "timeout": config.command_timeout})
    try:
        play_wake_beep()
    except Exception as e:
        logger.debug(f"Wake beep failed: {e}")

    stage2 = vosk.KaldiRecognizer(model, 16000)
    deadline = time.monotonic() + config.command_timeout
    transcript_parts: list[str] = []

    assert proc.stdout is not None
    while not stop_event.is_set() and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        proc.stdout._rbufsize = 0  # type: ignore[attr-defined]
        data = proc.stdout.read(_CHUNK)
        if not data:
            break

        if stage2.AcceptWaveform(data):
            result = json.loads(stage2.Result())
            text = result.get("text", "").strip()
            if text:
                transcript_parts.append(text)
                logger.info(f"Command partial: '{text}'")
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

    transcript = " ".join(transcript_parts).strip()
    logger.info(f"Command transcript: '{transcript}'")

    if not transcript:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        _play_timeout()
        return

    trigger = match_trigger(transcript, config.triggers)
    if trigger is None:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": transcript})
        _play_timeout()
        return

    if on_stt_event:
        on_stt_event("matched", {"transcript": transcript, "trigger": trigger.phrase})

    # Dispatch in a fresh event loop (we're in a daemon thread, not async context)
    connected = livekit_connected_flag.is_set()
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            dispatch(
                trigger,
                telegram_client,
                livekit_connect_fn,
                livekit_connected=connected,
            )
        )
        loop.close()
    except Exception as e:
        logger.error(f"Action dispatch failed: {e}")


def _play_timeout() -> None:
    logger.info("Command window timeout or no match")
    try:
        play_timeout_beep()
    except Exception as e:
        logger.debug(f"Timeout beep failed: {e}")


def start_stt_thread(
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
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
        ),
        daemon=True,
        name="stt",
    )
    t.start()
    return t
