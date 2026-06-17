from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import subprocess
import threading
import time
from typing import Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom import metrics
from alexa_custom.actions import (
    ActionContext,
    TelegramClient,
    dispatch,
    match_trigger_with_score,
)
from alexa_custom.audio import play_wake_beep
from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    Trigger,
)

from alexa_custom.stt_backends import (
    STTBackend,
    VoskSTT,
    SherpaOnnxSTT,
    _load_model,
    _MODEL_PATH,
    get_stt_backend,
    _phrases_to_grammar,
    _grammar_json,
)
from alexa_custom.stt_phonetics import (
    _match_wake_word,
    _approx_wake_match,
    _resolve_triggers,
    _build_alias_map,
)
from alexa_custom.stt_gating import (
    _CHUNK,
    _rms_level,
    _read_with_timeout,
    _drain_pipe,
    _downmix_to_mono,
    _apply_input_gain,
    resolve_capture_source,
    start_capture,
    _iter_gated_audio,
)
from alexa_custom.stt_capture import (
    _make_listen_fn,
    capture_transcript,
    _play_timeout,
)

__all__ = [
    "STTBackend",
    "VoskSTT",
    "SherpaOnnxSTT",
    "_load_model",
    "_MODEL_PATH",
    "get_stt_backend",
    "_phrases_to_grammar",
    "_grammar_json",
    "_approx_wake_match",
    "_resolve_triggers",
    "_build_alias_map",
    "_CHUNK",
    "_rms_level",
    "_read_with_timeout",
    "_drain_pipe",
    "_downmix_to_mono",
    "_apply_input_gain",
    "resolve_capture_source",
    "start_capture",
    "_iter_gated_audio",
    "run_stt_worker",
    "capture_transcript",
    "start_stt_thread",
    "_stt_heartbeat",
]

logger = logging.getLogger(__name__)

_stt_sleeping = False

# Stamped on every recognition iteration; client.py gates systemd WATCHDOG pings on this.
_stt_heartbeat: list[float] = [0.0]


def get_wake_up_phrases(config: ActionsConfig) -> str:
    phrases = [
        t.phrase
        for t in config.triggers
        if any(a.type == "start_listening" for a in t.actions)
    ]
    return ", ".join(sorted(set(phrases)))


def set_stt_sleeping(sleeping: bool) -> None:
    global _stt_sleeping
    logger.info("STT: set sleeping state to %s", sleeping)
    _stt_sleeping = sleeping


def is_stt_sleeping() -> bool:
    return _stt_sleeping


def _get_backend_key(cfg: ActionsConfig) -> tuple:
    return (cfg.stt.backend, cfg.stt.model_path, cfg.stt.num_threads)


def _dump_trigger_wav(
    audio_buf: "collections.deque[bytes]",
    channels: int,
    label: str,
    dump_dir: str,
) -> None:
    import re
    import wave
    from datetime import datetime

    os.makedirs(dump_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe = re.sub(r"[^\w\-]", "_", label)[:40]
    path = os.path.join(dump_dir, f"{ts}_{safe}.wav")
    try:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for chunk in audio_buf:
                wf.writeframes(chunk)
        logger.info("Trigger dump: %s", path)
    except Exception as e:
        logger.warning("Trigger dump failed: %s", e)


def _log_activation_phrases(config: ActionsConfig) -> None:
    lines = ["Activation phrases:"]
    for w in config.wake_words:
        lines.append(f"  [wake]     {w!r}")
    for t in config.triggers:
        tag = "direct" if not t.with_wake else "wake-gated"
        cmd = t.commands[0] if t.commands else t.phrase
        lines.append(f"  [{tag}]  {cmd!r}  → {[a.type for a in t.actions]}")
    logger.info("\n".join(lines))


def _follow_up_active(trigger: "Trigger | None", config: ActionsConfig) -> bool:
    """Return whether a follow-up window should open after dispatching trigger.

    Per-trigger follow_up overrides the global flag.
    llm_chat-only triggers manage their own conversation loop; suppress the
    outer follow-up window for them to avoid double-looping.
    """
    if not config.recognition.follow_up and (
        trigger is None or trigger.follow_up is None
    ):
        return False
    explicit = (
        trigger.follow_up
        if trigger is not None and trigger.follow_up is not None
        else config.recognition.follow_up
    )
    if not explicit:
        return False
    if trigger is not None and all(a.type == "llm_chat" for a in trigger.actions):
        return False
    return True


def _recognition_loop(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
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
    """Single-model transcribe→match→gate→tone→dispatch recognition loop."""
    assert dispatch_loop is not None

    wake_deadline: float = 0.0
    _dispatch_ended_at: list[float] = [0.0]
    _eff_rms = config.stt.rms_threshold
    _noise_floor: list[float] = []
    speech_ms: float = 0.0
    last_speech_t: float = 0.0
    was_gated = False
    _last_partial: str = ""

    _audio_buf: collections.deque[bytes] = collections.deque(
        maxlen=int(8 * 16000 * 2 * channels // 4096) + 1
    )

    _listen_fn = _make_listen_fn(
        proc, channels, backend, stop_event, on_stt_event, config.stt.vad_silence_ms
    )
    _ctx = ActionContext(
        telegram_client=telegram_client,
        livekit_connect_fn=livekit_connect_fn,
        livekit_connected=livekit_connected_flag.is_set(),
        listen_fn=_listen_fn,
        mqtt_client=mqtt_client,
        on_stt_event=on_stt_event,
        actions_config=config,
    )

    def woken() -> bool:
        return time.monotonic() < wake_deadline

    def _reset_vad() -> None:
        nonlocal speech_ms, last_speech_t
        speech_ms = 0.0
        last_speech_t = 0.0

    def _publish_state(state: str) -> None:
        if mqtt_client:
            mqtt_client.publish_threadsafe(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                state,
                loop=loop,
            )

    def _dispatch_trigger(
        trigger: Trigger,
        wake_phrase: str | None,
        transcript: str,
        score: float,
    ) -> None:
        nonlocal wake_deadline

        if config.dump_triggers_dir:
            _dump_trigger_wav(
                _audio_buf, channels, trigger.phrase, config.dump_triggers_dir
            )

        metrics.inc("commands_matched")
        if on_stt_event:
            on_stt_event(
                "matched",
                {
                    "transcript": transcript,
                    "phrase": trigger.commands[0]
                    if trigger.commands
                    else trigger.phrase,
                    "score": score,
                    "actions": [
                        {"type": a.type, "params": a.params} for a in trigger.actions
                    ],
                },
            )
        if mqtt_client:
            mqtt_client.publish_threadsafe(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/command",
                json.dumps(
                    {
                        "text": transcript,
                        "wake_word": wake_phrase or "",
                        "timestamp": time.time(),
                    }
                ),
                loop=loop,
            )

        try:
            _ctx.livekit_connected = livekit_connected_flag.is_set()
            dispatch_loop.run_until_complete(
                asyncio.wait_for(
                    dispatch(
                        trigger,
                        _ctx,
                        wake_word=wake_phrase or "",
                        transcript=transcript,
                    ),
                    timeout=config.recognition.dispatch_timeout,
                )
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Dispatch timed out after %.0fs — resetting and resuming",
                config.recognition.dispatch_timeout,
            )
        except Exception as e:
            logger.error("Action dispatch failed: %s", e)

        _drain_pipe(proc)
        backend.reset()
        _reset_vad()
        _dispatch_ended_at[0] = time.monotonic()

        if _follow_up_active(trigger, config) and not livekit_connected_flag.is_set():
            wake_deadline = time.monotonic() + config.recognition.follow_up_timeout
            try:
                play_wake_beep(config.recognition.follow_up_tone)
            except Exception:
                pass
        else:
            wake_deadline = 0.0

        if on_stt_event:
            on_stt_event("listening", {"wake_words": config.wake_words})
        _publish_state("idle")

    if on_stt_event:
        on_stt_event("listening", {"wake_words": config.wake_words})
    _publish_state("idle")

    for data in _iter_gated_audio(
        proc,
        channels,
        stop_event,
        on_playback_end=backend.reset,
        name="single-model",
        post_playback_ms=config.audio.post_playback_ms,
        dispatch_ended_at=_dispatch_ended_at,
    ):
        _stt_heartbeat[0] = time.monotonic()

        if livekit_connected_flag.is_set():
            if not was_gated:
                logger.info("STT gated (call active)")
                if on_stt_event:
                    on_stt_event("gated", {})
                _publish_state("gated")
                was_gated = True
            backend.reset()
            _reset_vad()
            continue

        if was_gated:
            logger.info("STT resumed (call ended)")
            was_gated = False
            backend.reset()
            _reset_vad()
            if on_stt_event:
                on_stt_event("listening", {"wake_words": config.wake_words})
            _publish_state("idle")

        if data is None:
            continue

        rms = _rms_level(data)

        if config.stt.adaptive_rms and speech_ms == 0.0:
            _noise_floor.append(rms)
            if len(_noise_floor) > 50:
                _noise_floor.pop(0)
                _eff_rms = (
                    sum(_noise_floor) / len(_noise_floor)
                ) + config.stt.adaptive_rms_margin

        if on_stt_event:
            on_stt_event(
                "level",
                {
                    "mic": rms,
                    "rms_threshold": _eff_rms,
                    "confidence": None,
                    "adaptive": config.stt.adaptive_rms,
                },
            )

        _post_s = config.recognition.post_dispatch_cooldown_ms / 1000.0
        if (
            _post_s > 0
            and _dispatch_ended_at[0] > 0
            and time.monotonic() - _dispatch_ended_at[0] < _post_s
        ):
            backend.reset()
            _reset_vad()
            continue

        now = time.monotonic()
        if rms > _eff_rms:
            last_speech_t = now
            speech_ms += (len(data) / 2) / 16000.0 * 1000.0

        if config.dump_triggers_dir:
            _audio_buf.append(data)

        endpoint = backend.accept_waveform(data)

        if on_stt_event and rms > _eff_rms:
            partial = backend.partial_text()
            if partial and partial != _last_partial:
                on_stt_event("transcribing", {"text": partial})
            _last_partial = partial

        vad_fire = (
            speech_ms >= config.stt.min_speech_ms
            and last_speech_t > 0
            and (now - last_speech_t) * 1000.0 >= config.stt.vad_silence_ms
        )

        if vad_fire and not endpoint:
            text = backend.finalize().strip()
            _reset_vad()
            _last_partial = ""
        elif endpoint:
            text = backend.text().strip()
            backend.reset()
            _reset_vad()
            _last_partial = ""
        else:
            continue

        if not text:
            continue

        logger.debug("Transcript: %r", text)

        # --- Wake word detection ---
        wake_phrase, residual = _match_wake_word(
            text,
            config.wake_words,
            threshold=config.stt.wake_match_threshold,
        )

        if wake_phrase is not None:
            if is_stt_sleeping():
                # Sleeping: only react if residual matches a start_listening trigger
                wake_up_candidates = [
                    t
                    for t in config.triggers
                    if any(a.type == "start_listening" for a in t.actions)
                ]
                if residual and wake_up_candidates:
                    trig, score = match_trigger_with_score(
                        residual,
                        wake_up_candidates,
                        algorithm=config.recognition.matching_algorithm,
                        threshold=config.recognition.matching_threshold,
                        min_word_overlap=config.recognition.min_word_overlap,
                    )
                    if trig is not None:
                        wake_deadline = (
                            time.monotonic() + config.recognition.wake_window
                        )
                        try:
                            play_wake_beep(config.recognition.wake_tone)
                        except Exception:
                            pass
                        _dispatch_trigger(trig, wake_phrase, residual, score)
                        continue
                logger.info("Sleeping — wake up with: %s", get_wake_up_phrases(config))
                continue

            metrics.inc("wake_detections")
            wake_deadline = time.monotonic() + config.recognition.wake_window
            logger.info(
                "Wake: %r  residual=%r  window=+%.0fs",
                wake_phrase,
                residual,
                config.recognition.wake_window,
            )
            if config.dump_triggers_dir:
                _dump_trigger_wav(
                    _audio_buf,
                    channels,
                    f"wake_{wake_phrase}",
                    config.dump_triggers_dir,
                )
            _publish_state("listening")

            if not residual:
                if on_stt_event:
                    on_stt_event(
                        "wake",
                        {
                            "word": wake_phrase,
                            "timeout": config.recognition.wake_window,
                        },
                    )
                try:
                    play_wake_beep(config.recognition.wake_tone)
                except Exception as e:
                    logger.debug("Wake beep failed: %s", e)
                continue

            # One-breath: residual present — try to match a command immediately
            trig, score = match_trigger_with_score(
                residual,
                config.triggers,
                algorithm=config.recognition.matching_algorithm,
                threshold=config.recognition.matching_threshold,
                min_word_overlap=config.recognition.min_word_overlap,
            )
            if trig is not None:
                logger.info(
                    "One-breath: %r → %r (score=%.0f)", residual, trig.phrase, score
                )
                if on_stt_event:
                    on_stt_event("wake", {"word": wake_phrase, "timeout": 0})
                try:
                    play_wake_beep(config.recognition.wake_tone)
                except Exception as e:
                    logger.debug("Wake beep failed: %s", e)
                _dispatch_trigger(trig, wake_phrase, residual, score)
            else:
                # Wake word recognised but command not matched — open window, wait
                if on_stt_event:
                    on_stt_event(
                        "wake",
                        {
                            "word": wake_phrase,
                            "timeout": config.recognition.wake_window,
                        },
                    )
                try:
                    play_wake_beep(config.recognition.wake_tone)
                except Exception as e:
                    logger.debug("Wake beep failed: %s", e)
            continue

        # --- Command matching ---
        if is_stt_sleeping():
            continue

        candidates = [t for t in config.triggers if not t.with_wake or woken()]
        if not candidates:
            continue

        if (
            config.recognition.min_cmd_words > 0
            and len(text.split()) < config.recognition.min_cmd_words
        ):
            continue

        # Exit phrase: close wake window early
        if woken() and config.llm:
            from alexa_custom.llm import is_exit_phrase

            if is_exit_phrase(text, config.llm.exit_phrases):
                logger.debug("Exit phrase %r — closing wake window", text)
                wake_deadline = 0.0
                continue

        trig, score = match_trigger_with_score(
            text,
            candidates,
            algorithm=config.recognition.matching_algorithm,
            threshold=config.recognition.matching_threshold,
            min_word_overlap=config.recognition.min_word_overlap,
        )

        if trig is None:
            if woken():
                logger.info("No match while woken: %r (score=%.0f)", text, score)
                if on_stt_event:
                    on_stt_event("nomatch", {"transcript": text, "score": score})
                if config.llm and config.llm.fallback_on_no_match:
                    _fb = Trigger(
                        commands=["__llm_fallback__"],
                        phrase="__llm_fallback__",
                        actions=[ActionEntry(type="llm_chat", params={})],
                    )
                    try:
                        _ctx.livekit_connected = livekit_connected_flag.is_set()
                        dispatch_loop.run_until_complete(
                            asyncio.wait_for(
                                dispatch(_fb, _ctx, wake_word="", transcript=text),
                                timeout=config.recognition.dispatch_timeout,
                            )
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "LLM fallback dispatch timed out after %.0fs",
                            config.recognition.dispatch_timeout,
                        )
                    except Exception as e:
                        logger.error("LLM fallback error: %s", e)
                    _drain_pipe(proc)
                    backend.reset()
                    _reset_vad()
                    _dispatch_ended_at[0] = time.monotonic()
                    if on_stt_event:
                        on_stt_event("listening", {"wake_words": config.wake_words})
                    _publish_state("idle")
                else:
                    _play_timeout()
            continue

        # start_listening triggers are pointless when already awake
        if (
            any(a.type == "start_listening" for a in trig.actions)
            and not is_stt_sleeping()
        ):
            logger.info(
                "start_listening trigger %r ignored: system is already awake",
                trig.phrase,
            )
            continue

        if trig.with_wake:
            logger.info("Command: %r → %r (score=%.0f)", text, trig.phrase, score)
        else:
            logger.info("Direct: %r → %r (score=%.0f)", text, trig.phrase, score)

        try:
            play_wake_beep(config.recognition.wake_tone)
        except Exception as e:
            logger.debug("Command beep failed: %s", e)

        _dispatch_trigger(trig, None, text, score)


def run_stt_worker(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: "MQTTClient | None" = None,
    loop: asyncio.AbstractEventLoop | None = None,
    stt_ready_event: threading.Event | None = None,
) -> None:
    """Entry point for the STT daemon thread."""
    _stt_heartbeat[0] = time.monotonic()

    if callable(config) and not isinstance(config, ActionsConfig):
        _get_config: Callable[[], ActionsConfig] = config  # type: ignore[assignment]
    else:

        def _get_config() -> ActionsConfig:
            return config  # type: ignore[return-value]

    current_config = _get_config()
    source, channels = resolve_capture_source(current_config.audio.input_device)

    logger.info(
        "STT: wake_words=%r backend=%s vad_silence_ms=%d source=%s (%d ch)",
        current_config.wake_words,
        current_config.stt.backend,
        current_config.stt.vad_silence_ms,
        source or "default",
        channels,
    )
    _log_activation_phrases(current_config)

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    try:
        t0 = time.monotonic()
        backend = get_stt_backend(current_config.stt)
        logger.info(
            "STT backend (%s) loaded in %.1fs",
            current_config.stt.backend,
            time.monotonic() - t0,
        )
    except RuntimeError as e:
        logger.error("STT backend creation failed: %s", e)
        return

    backend_key = _get_backend_key(current_config)
    _dispatch_loop = asyncio.new_event_loop()

    try:
        while not stop_event.is_set():
            current_config = _get_config()

            new_key = _get_backend_key(current_config)
            if new_key != backend_key:
                try:
                    t0 = time.monotonic()
                    backend = get_stt_backend(current_config.stt)
                    backend_key = new_key
                    logger.info(
                        "STT backend reloaded (%.1fs) after config change",
                        time.monotonic() - t0,
                    )
                except RuntimeError as e:
                    logger.error("STT backend reload failed: %s", e)
                    stop_event.wait(2)
                    continue

            proc: subprocess.Popen | None = None
            try:
                proc = start_capture(source, channels)
                if stt_ready_event is not None and not stt_ready_event.is_set():
                    stt_ready_event.set()
                    logger.info("STT ready — listening for wake words")
                _recognition_loop(
                    proc=proc,
                    channels=channels,
                    backend=backend,
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
                logger.error("STT error: %s", e, exc_info=True)
                stop_event.wait(2)
            else:
                if not stop_event.is_set():
                    logger.info("Capture ended unexpectedly — restarting in 2s")
                    stop_event.wait(2.0)
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
    finally:
        _dispatch_loop.close()


def start_stt_thread(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: "MQTTClient | None" = None,
    loop: asyncio.AbstractEventLoop | None = None,
    stt_ready_event: threading.Event | None = None,
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
            stt_ready_event,
        ),
        daemon=True,
        name="stt",
    )
    t.start()
    return t
