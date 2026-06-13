from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from typing import Awaitable, Callable, TYPE_CHECKING

import vosk

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom import metrics
from alexa_custom.actions import (
    ActionContext,
    TelegramClient,
    dispatch,
    match_trigger,
    normalize_text,
)
from alexa_custom.audio import play_wake_beep
from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    Trigger,
    WakeWordGroup,
)

# ---------------------------------------------------------------------------
# Sibling imports and re-exports for 100% backward compatibility
# ---------------------------------------------------------------------------
from alexa_custom.stt_backends import (
    STTBackend,
    VoskSTT,
    SherpaOnnxSTT,
    SherpaKeywordSpotter,
    _load_model,
    _tokenize_keyword,
    get_stt_backend,
    _vosk_confidence,
    _vosk_check_result,
    _phrases_to_grammar,
    _grammar_json,
    _grammar_json_all,
)
from alexa_custom.stt_phonetics import (
    _approx_wake_match,
    _resolve_triggers,
    _build_alias_map,
    build_intent_map,
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
    "SherpaKeywordSpotter",
    "_load_model",
    "_tokenize_keyword",
    "get_stt_backend",
    "_vosk_confidence",
    "_vosk_check_result",
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
    "_extract_wake_command",
    "_match_full_intent",
    "capture_transcript",
    "start_stt_thread",
    "_stt_heartbeat",
]

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_STT_COOLDOWN = 1.0
_SHERPA_MODEL_PATH = os.environ.get("SHERPA_ONNX_PATH", "models/sherpa-onnx")

_STAGE1_VAD_SILENCE_MS = int(os.environ.get("STT_STAGE1_VAD_SILENCE_MS", "500"))
_STAGE1_RMS_THRESHOLD = float(os.environ.get("STT_STAGE1_RMS_THRESHOLD", "0.02"))
_STAGE1_MIN_SPEECH_MS = int(os.environ.get("STT_STAGE1_MIN_SPEECH_MS", "200"))


_stt_sleeping = False

# Heartbeat stamped by the recognition loops on every iteration.
# The main async loop (client.py) gates systemd WATCHDOG=1 pings on freshness.
# Single-element list so writes are atomic under the GIL.
_stt_heartbeat: list[float] = [0.0]


def get_wake_up_phrases(config: ActionsConfig) -> str:
    wake_up_phrases = []
    for t in getattr(config, "direct_triggers", []):
        if any(a.type == "start_listening" for a in t.actions):
            wake_up_phrases.append(t.phrase)
    for t in getattr(config, "triggers", []):
        if any(a.type == "start_listening" for a in t.actions):
            wake_up_phrases.append(t.phrase)
    for g in getattr(config, "wake_words", []):
        for t in g.triggers:
            if any(a.type == "start_listening" for a in t.actions):
                wake_up_phrases.append(t.phrase)
    return ", ".join(sorted(list(set(wake_up_phrases))))


def set_stt_sleeping(sleeping: bool) -> None:
    global _stt_sleeping
    logger.info(f"STT: set sleeping state to {sleeping}")
    _stt_sleeping = sleeping


def is_stt_sleeping() -> bool:
    return _stt_sleeping


def run_stt_worker(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    stt_ready_event: threading.Event | None = None,
) -> None:
    """Entry point for the STT daemon thread."""
    _stt_heartbeat[0] = time.monotonic()

    _get_config: Callable[[], ActionsConfig]
    if callable(config) and not isinstance(config, ActionsConfig):
        _get_config = config  # type: ignore[assignment]
    else:

        def _get_config():
            return config  # type: ignore[return-value]

    current_config = _get_config()
    input_spec = current_config.audio.input_device
    source, channels = resolve_capture_source(input_spec)

    logger.info(
        f"STT: wake words={[g.word for g in current_config.wake_words]}, "
        f"timeout={current_config.recognition.command_timeout}s, "
        f"source={source or 'default'} ({channels} ch), "
        f"stage1={current_config.stt.stage1.backend} stage2={current_config.stt.stage2.backend}"
    )

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    try:
        t0 = time.monotonic()
        _kws_keywords = [
            p for g in current_config.wake_words for p in [g.word] + g.aliases
        ]
        stage1_backend = get_stt_backend(
            current_config.stt.stage1, keywords=_kws_keywords
        )
        logger.info(
            f"STT stage1 backend ({current_config.stt.stage1.backend}) loaded in {time.monotonic() - t0:.1f}s"
        )
        t0 = time.monotonic()
        stage2_grammar = (
            _grammar_json_all(current_config.wake_words, current_config.triggers)
            if current_config.stt.stage2.vosk_grammar
            else None
        )
        stage2_backend = get_stt_backend(
            current_config.stt.stage2, grammar=stage2_grammar
        )
        logger.info(
            f"STT stage2 backend ({current_config.stt.stage2.backend}) loaded in {time.monotonic() - t0:.1f}s"
        )
    except RuntimeError as e:
        logger.error(f"STT backend creation failed: {e}")
        return

    stage1_key = (
        current_config.stt.stage1.backend,
        current_config.stt.stage1.model_path,
        current_config.stt.stage1.vosk_grammar,
        hash(
            (
                tuple(g.word for g in current_config.wake_words),
                tuple(t.phrase for g in current_config.wake_words for t in g.triggers),
                tuple(t.phrase for t in current_config.triggers),
            )
        )
        if current_config.stt.stage1.vosk_grammar
        else 0,
    )
    stage2_key = (
        current_config.stt.stage2.backend,
        current_config.stt.stage2.model_path,
        current_config.stt.stage2.vosk_grammar,
        hash(
            (
                tuple(g.word for g in current_config.wake_words),
                tuple(t.phrase for g in current_config.wake_words for t in g.triggers),
                tuple(t.phrase for t in current_config.triggers),
            )
        )
        if current_config.stt.stage2.vosk_grammar
        else 0,
    )

    _dispatch_loop = asyncio.new_event_loop()
    try:
        while not stop_event.is_set():
            current_config = _get_config()
            loop_fn = (
                _single_stage_loop
                if current_config.recognition.mode == "single-stage"
                else _recognition_loop
            )

            new_stage1_key = (
                current_config.stt.stage1.backend,
                current_config.stt.stage1.model_path,
                current_config.stt.stage1.vosk_grammar,
                hash(
                    (
                        tuple(g.word for g in current_config.wake_words),
                        tuple(
                            t.phrase
                            for g in current_config.wake_words
                            for t in g.triggers
                        ),
                        tuple(t.phrase for t in current_config.triggers),
                        tuple(t.phrase for t in current_config.direct_triggers),
                    )
                )
                if current_config.stt.stage1.vosk_grammar
                else 0,
            )
            new_stage2_key = (
                current_config.stt.stage2.backend,
                current_config.stt.stage2.model_path,
                current_config.stt.stage2.vosk_grammar,
                hash(
                    (
                        tuple(g.word for g in current_config.wake_words),
                        tuple(t.phrase for t in current_config.triggers),
                    )
                )
                if current_config.stt.stage2.vosk_grammar
                else 0,
            )

            if new_stage1_key != stage1_key:
                try:
                    _kws_keywords = [
                        p
                        for g in current_config.wake_words
                        for p in [g.word] + g.aliases
                    ]
                    stage1_backend = get_stt_backend(
                        current_config.stt.stage1, keywords=_kws_keywords
                    )
                    stage1_key = new_stage1_key
                    logger.info("STT stage1 backend reloaded after config change")
                except RuntimeError as e:
                    logger.error(f"STT stage1 backend reload failed: {e}")
                    stop_event.wait(2)
                    continue

            if new_stage2_key != stage2_key:
                try:
                    stage2_grammar = (
                        _grammar_json_all(
                            current_config.wake_words, current_config.triggers
                        )
                        if current_config.stt.stage2.vosk_grammar
                        else None
                    )
                    stage2_backend = get_stt_backend(
                        current_config.stt.stage2, grammar=stage2_grammar
                    )
                    stage2_key = new_stage2_key
                    logger.info("STT stage2 backend reloaded after config change")
                except RuntimeError as e:
                    logger.error(f"STT stage2 backend reload failed: {e}")
                    stop_event.wait(2)
                    continue

            proc: subprocess.Popen | None = None
            try:
                proc = start_capture(source, channels)
                if stt_ready_event is not None and not stt_ready_event.is_set():
                    stt_ready_event.set()
                    logger.info("STT ready — listening for wake words")
                loop_fn(
                    proc=proc,
                    channels=channels,
                    stage1_backend=stage1_backend,
                    stage2_backend=stage2_backend,
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
                logger.error(f"STT error: {e}", exc_info=True)
                stop_event.wait(2)
            else:
                # loop_fn returned without raising: capture ended (e.g. parec EOF
                # on mic unplug / pipewire restart). start_capture() succeeds even
                # when the device is gone, so without this backoff the while loop
                # respawns parec tens of times per second.
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


def _extract_wake_command(
    text: str, alias_map: dict[str, WakeWordGroup], fuzzy: bool = False
) -> tuple[WakeWordGroup | None, str]:
    """Return (group, command) if text begins with a known wake phrase, else (None, '').

    With fuzzy=True (sherpa-onnx single-stage path) uses _approx_wake_match to
    handle open-vocabulary transcription noise around wake words.
    """
    norm_text = normalize_text(text)
    for norm_phrase, group in alias_map.items():
        if norm_text.startswith(norm_phrase):
            rest = norm_text[len(norm_phrase) :]
            if rest and not rest.startswith(" "):
                continue  # prefix of a longer word — not a valid wake boundary
            return group, rest.strip()
    if fuzzy:
        group = _approx_wake_match(text, alias_map)
        if group:
            # Best-effort command extraction: drop any token that belongs to the
            # group's wake phrases (canonical word + aliases). Token-level removal
            # avoids substring mangling (e.g. "ehi" turning "ehilà" into "là") and
            # works even when an alias matched rather than the canonical word.
            wake_tokens = {
                w
                for phrase in [group.word, *group.aliases]
                for w in normalize_text(phrase).split()
            }
            command = " ".join(t for t in norm_text.split() if t not in wake_tokens)
            return group, command
    return None, ""


def _match_full_intent(
    partial: str,
    alias_map: dict[str, WakeWordGroup],
    intent_map: dict[str, tuple[WakeWordGroup, Trigger]],
) -> tuple[WakeWordGroup, Trigger, str] | None:
    """Return (group, trigger, inline_cmd) if partial matches a complete (wake + trigger) intent.

    Uses exact matching only — fuzzy is never applied on partial transcripts.
    Returns None if only a wake word is present or the command is not a known trigger.
    """
    wake_group, inline_cmd = _extract_wake_command(partial, alias_map, fuzzy=False)
    if wake_group is None or not inline_cmd:
        return None
    norm_cmd = normalize_text(inline_cmd)
    for norm_wake, group in alias_map.items():
        if group is not wake_group:
            continue
        key = normalize_text(f"{norm_wake} {norm_cmd}")
        if key in intent_map:
            matched_group, trigger = intent_map[key]
            return matched_group, trigger, inline_cmd
    return None


def _single_stage_loop(
    proc: subprocess.Popen,
    channels: int,
    stage1_backend: STTBackend,
    stage2_backend: STTBackend,
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
    backend = stage2_backend
    cooldown_until = 0.0
    alias_map = _build_alias_map(config.wake_words)
    _eff_vad_ms = config.stt.vad_silence_ms

    if on_stt_event:
        on_stt_event("listening", {"wake_words": [g.word for g in config.wake_words]})

    _listen_fn = _make_listen_fn(
        proc, channels, backend, stop_event, on_stt_event, _eff_vad_ms
    )
    _dloop = dispatch_loop
    assert _dloop is not None, "dispatch_loop must be provided to _single_stage_loop"
    _ctx = ActionContext(
        telegram_client=telegram_client,
        livekit_connect_fn=livekit_connect_fn,
        livekit_connected=livekit_connected_flag.is_set(),
        listen_fn=_listen_fn,
        mqtt_client=mqtt_client,
        on_stt_event=on_stt_event,
        actions_config=config,
    )

    _adaptive_rms = config.stt.stage1.adaptive_rms
    _adaptive_rms_margin = config.stt.stage1.adaptive_rms_margin
    _eff_stage1_rms = config.stt.stage1.rms_threshold
    _noise_floor_buffer: list[float] = []

    for data in _iter_gated_audio(
        proc,
        channels,
        stop_event,
        on_playback_end=backend.reset,
        name="single-stage",
        post_playback_ms=config.audio.post_playback_ms,
    ):
        _stt_heartbeat[0] = time.monotonic()
        if data is None:
            continue

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if on_stt_event:
                on_stt_event("gated", {})
            continue

        rms = _rms_level(data)
        if _adaptive_rms:
            _noise_floor_buffer.append(rms)
            if len(_noise_floor_buffer) > 50:
                _noise_floor_buffer.pop(0)
                _eff_stage1_rms = (
                    sum(_noise_floor_buffer) / len(_noise_floor_buffer)
                ) + _adaptive_rms_margin

        if on_stt_event:
            on_stt_event(
                "level",
                {
                    "mic": rms,
                    "rms_threshold": _eff_stage1_rms,
                    "confidence": None,
                    "adaptive": _adaptive_rms,
                },
            )

        if time.monotonic() < cooldown_until:
            backend.reset()
            continue

        if not backend.accept_waveform(data):
            if on_stt_event:
                partial = backend.partial_text()
                if partial:
                    on_stt_event("transcribing", {"text": partial})
            continue

        text = backend.text()
        if not text:
            backlog = _drain_pipe(proc)
            if backlog:
                logger.debug(
                    f"single-stage: drained {backlog} backlog bytes after empty segment"
                )
            backend.reset()
            continue

        wake_group, command = _extract_wake_command(
            text, alias_map, fuzzy=not isinstance(backend, VoskSTT)
        )
        if wake_group is None:
            backlog = _drain_pipe(proc)
            if backlog:
                logger.debug(
                    f"single-stage: drained {backlog} backlog bytes after non-wake segment"
                )
            backend.reset()
            continue

        if is_stt_sleeping():
            temp_triggers = _resolve_triggers(wake_group, config.triggers)
            temp_trigger = (
                match_trigger(
                    command,
                    temp_triggers,
                    algorithm=config.recognition.matching_algorithm,
                    threshold=config.recognition.matching_threshold,
                )
                if command
                else None
            )
            has_start_listening = temp_trigger is not None and any(
                a.type == "start_listening" for a in temp_trigger.actions
            )
            if not has_start_listening:
                phrases_str = get_wake_up_phrases(config)
                logger.info(f"sleeping... wait for wake up {phrases_str}")
                backend.reset()
                continue

        logger.info(f"Single-stage: wake='{wake_group.word}' command='{command}'")
        if on_stt_event:
            on_stt_event("wake", {"word": wake_group.word, "timeout": 0})

        try:
            play_wake_beep(config.recognition.wake_tone)
        except Exception as e:
            logger.debug(f"Wake beep failed: {e}")

        if not command:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": ""})
            _play_timeout()
            continue

        triggers = _resolve_triggers(wake_group, config.triggers)
        trigger = match_trigger(
            command,
            triggers,
            algorithm=config.recognition.matching_algorithm,
            threshold=config.recognition.matching_threshold,
        )
        if trigger is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": command})
            if config.llm and config.llm.fallback_on_no_match:
                _fb_trigger = Trigger(
                    phrase="__llm_fallback__",
                    actions=[ActionEntry(type="llm_chat", params={})],
                )
                try:
                    _ctx.livekit_connected = livekit_connected_flag.is_set()
                    _dloop.run_until_complete(
                        asyncio.wait_for(
                            dispatch(
                                _fb_trigger,
                                _ctx,
                                wake_word=wake_group.word,
                                transcript=command,
                            ),
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
            else:
                _play_timeout()
            continue

        metrics.inc("commands_matched")
        if on_stt_event:
            on_stt_event("matched", {"transcript": command, "trigger": trigger.phrase})

        try:
            _ctx.livekit_connected = livekit_connected_flag.is_set()
            _dloop.run_until_complete(
                asyncio.wait_for(
                    dispatch(
                        trigger, _ctx, wake_word=wake_group.word, transcript=command
                    ),
                    timeout=config.recognition.dispatch_timeout,
                )
            )
            _drain_pipe(proc)
            backend.reset()
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
        except asyncio.TimeoutError:
            logger.warning(
                "Dispatch timed out after %.0fs — resetting and resuming",
                config.recognition.dispatch_timeout,
            )
            _drain_pipe(proc)
            backend.reset()
        except Exception as e:
            logger.error(f"Action dispatch failed: {e}")


def _recognition_loop(
    proc: subprocess.Popen,
    channels: int,
    stage1_backend: STTBackend,
    stage2_backend: STTBackend,
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
    _eff_stage1_vad_ms = config.stt.stage1.vad_silence_ms
    _eff_stage1_rms = config.stt.stage1.rms_threshold
    _eff_stage1_min_speech_ms = config.stt.stage1.min_speech_ms
    _eff_vad_ms = config.stt.vad_silence_ms

    _adaptive_rms = config.stt.stage1.adaptive_rms
    _adaptive_rms_margin = config.stt.stage1.adaptive_rms_margin
    _noise_floor_buffer: list[float] = []

    alias_map = _build_alias_map(config.wake_words)
    intent_map = build_intent_map(alias_map, config.triggers)
    is_vosk = isinstance(stage1_backend, VoskSTT)
    is_kws = isinstance(stage1_backend, SherpaKeywordSpotter)
    vosk_use_grammar = config.stt.stage1.vosk_grammar

    def _make_stage1_recognizer() -> "vosk.KaldiRecognizer":
        if vosk_use_grammar:
            rec = vosk.KaldiRecognizer(
                vosk_model,
                16000,
                _grammar_json_all(
                    config.wake_words, config.triggers, config.direct_triggers
                ),
            )
        else:
            rec = vosk.KaldiRecognizer(vosk_model, 16000)
        rec.SetWords(True)
        return rec

    if is_vosk:
        vosk_model = stage1_backend.model
        stage1 = _make_stage1_recognizer()
    else:
        stage1 = None
    cooldown_until = 0.0
    was_gated = False
    stage1_last_speech_t = 0.0
    stage1_speech_ms = 0.0
    _partial_stable_key: tuple | None = None
    _partial_stable_reads: int = 0
    _partial_stable_since: float = 0.0

    if on_stt_event:
        on_stt_event(
            "listening",
            {"wake_words": [g.word for g in config.wake_words]},
        )

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    def _reset_stage1_state() -> None:
        nonlocal stage1_last_speech_t, stage1_speech_ms
        nonlocal _partial_stable_key, _partial_stable_reads, _partial_stable_since
        stage1_last_speech_t = 0.0
        stage1_speech_ms = 0.0
        _partial_stable_key = None
        _partial_stable_reads = 0
        _partial_stable_since = 0.0

    if is_vosk:

        def _on_playback_end() -> None:
            assert stage1 is not None
            stage1.Reset()
            _reset_stage1_state()
    elif is_kws:

        def _on_playback_end() -> None:
            stage1_backend.reset()
    else:

        def _on_playback_end() -> None:
            stage1_backend.reset()
            _reset_stage1_state()

    _dispatch_ended_at: list[float] = [0.0]

    for data in _iter_gated_audio(
        proc,
        channels,
        stop_event,
        on_playback_end=_on_playback_end,
        name="two-stage",
        post_playback_ms=config.audio.post_playback_ms,
        dispatch_ended_at=_dispatch_ended_at,
    ):
        _stt_heartbeat[0] = time.monotonic()
        if data is None:
            continue

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

        rms = _rms_level(data)

        # Adaptive RMS tracking
        if _adaptive_rms and not was_gated and stage1_speech_ms == 0:
            _noise_floor_buffer.append(rms)
            if len(_noise_floor_buffer) > 50:  # ~1 second rolling window
                _noise_floor_buffer.pop(0)
                _current_noise_floor = sum(_noise_floor_buffer) / len(
                    _noise_floor_buffer
                )
                _eff_stage1_rms = _current_noise_floor + _adaptive_rms_margin

        if on_stt_event:
            on_stt_event(
                "level",
                {
                    "mic": rms,
                    "rms_threshold": _eff_stage1_rms,
                    "confidence": config.stt.stage1.confidence
                    if is_vosk and vosk_use_grammar
                    else None,
                    "adaptive": _adaptive_rms,
                },
            )

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
            if is_vosk:
                stage1.Reset()
                _reset_stage1_state()
            elif is_kws:
                stage1_backend.reset()
            else:
                stage1_backend.reset()
                _reset_stage1_state()
            continue

        if is_kws:
            if stage1_backend.accept_waveform(data):
                keyword = stage1_backend.text()
                wake_match = alias_map.get(normalize_text(keyword))
                if wake_match and not is_stt_sleeping():
                    logger.debug(f"Stage1 KWS hit: {keyword!r}")
                    _wake_detected(
                        wake_group=wake_match,
                        proc=proc,
                        channels=channels,
                        backend=stage2_backend,
                        config=config,
                        stop_event=stop_event,
                        telegram_client=telegram_client,
                        livekit_connect_fn=livekit_connect_fn,
                        livekit_connected_flag=livekit_connected_flag,
                        on_stt_event=on_stt_event,
                        mqtt_client=mqtt_client,
                        loop=loop,
                        dispatch_loop=dispatch_loop,
                        vad_silence_ms=_eff_vad_ms,
                    )
                    _drain_pipe(proc)
                    _dispatch_ended_at[0] = time.monotonic()
                    if on_stt_event:
                        on_stt_event(
                            "listening",
                            {"wake_words": [g.word for g in config.wake_words]},
                        )
                    if mqtt_client:
                        mqtt_client.publish_threadsafe(
                            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                            "idle",
                            loop=loop,
                        )
                elif wake_match and is_stt_sleeping():
                    phrases_str = get_wake_up_phrases(config)
                    logger.info(f"sleeping... wait for wake up {phrases_str}")
                else:
                    logger.debug(
                        "Stage1 KWS hit but keyword %r not in alias_map — ignoring",
                        keyword,
                    )
                    stage1_backend.reset()
        elif is_vosk:
            chunk_ms = len(data) / (16000 * 2) * 1000
            if rms > _eff_stage1_rms:
                stage1_last_speech_t = time.monotonic()
                stage1_speech_ms += chunk_ms

            partial = json.loads(stage1.PartialResult()).get("partial", "").strip()
            if on_stt_event and partial:
                on_stt_event("transcribing", {"text": partial})

            if partial and config.recognition.partial_matching:
                intent_result = _match_full_intent(partial, alias_map, intent_map)
                if intent_result is not None and not is_stt_sleeping():
                    intent_key = (intent_result[0].word, intent_result[1].phrase)
                    if intent_key == _partial_stable_key:
                        _partial_stable_reads += 1
                        elapsed_ms = (time.monotonic() - _partial_stable_since) * 1000
                        if (
                            _partial_stable_reads
                            >= config.recognition.partial_stability_reads
                            and elapsed_ms >= config.recognition.partial_stability_ms
                        ):
                            wake_group, trigger, inline_cmd = intent_result
                            logger.debug("Streaming intent fired: %r", partial)
                            _reset_stage1_state()
                            stage1.Reset()
                            _wake_detected(
                                wake_group=wake_group,
                                proc=proc,
                                channels=channels,
                                pre_transcript=inline_cmd,
                                backend=stage2_backend,
                                config=config,
                                stop_event=stop_event,
                                telegram_client=telegram_client,
                                livekit_connect_fn=livekit_connect_fn,
                                livekit_connected_flag=livekit_connected_flag,
                                on_stt_event=on_stt_event,
                                mqtt_client=mqtt_client,
                                loop=loop,
                                dispatch_loop=dispatch_loop,
                                vad_silence_ms=_eff_vad_ms,
                            )
                            _drain_pipe(proc)
                            _dispatch_ended_at[0] = time.monotonic()
                            if on_stt_event:
                                on_stt_event(
                                    "listening",
                                    {"wake_words": [g.word for g in config.wake_words]},
                                )
                            if mqtt_client:
                                mqtt_client.publish_threadsafe(
                                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                                    "idle",
                                    loop=loop,
                                )
                            continue
                    else:
                        _partial_stable_key = intent_key
                        _partial_stable_reads = 1
                        _partial_stable_since = time.monotonic()
                else:
                    _partial_stable_key = None
                    _partial_stable_reads = 0
                    _partial_stable_since = 0.0

            vad_triggered = (
                stage1_speech_ms >= _eff_stage1_min_speech_ms
                and stage1_last_speech_t > 0
                and (time.monotonic() - stage1_last_speech_t) * 1000
                >= _eff_stage1_vad_ms
            )
            endpoint_fired = stage1.AcceptWaveform(data)

            if not endpoint_fired and not vad_triggered:
                continue

            if vad_triggered and not endpoint_fired:
                result = json.loads(stage1.FinalResult())
                rms_gate = 0.0  # speech already confirmed by software VAD
                logger.debug("Stage1 Vosk force-finalized by software VAD")
            else:
                result = json.loads(stage1.Result())
                # The chunk that fires the Vosk endpoint is usually trailing
                # silence, so gating its RMS would reject valid wakes. Skip the
                # chunk gate when the speech tracker already saw enough speech
                # across the utterance.
                rms_gate = (
                    0.0
                    if stage1_speech_ms >= _eff_stage1_min_speech_ms
                    else config.stt.stage1.rms_threshold
                )

            stage1_last_speech_t = 0.0
            stage1_speech_ms = 0.0

            inline_cmd = ""
            vosk_text = result.get("text", "").strip()
            if vosk_use_grammar:
                wake_match, inline_cmd = _vosk_check_result(
                    data,
                    result,
                    alias_map,
                    config.stt.stage1.confidence,
                    config.stt.stage1.confidence_mode,
                    rms_gate,
                )
            else:
                text = vosk_text
                logger.debug("Stage1 Vosk free-vocab result: %r", text)
                wake_match, inline_cmd = (
                    _extract_wake_command(text, alias_map, fuzzy=False)
                    if text
                    else (None, "")
                )

            if wake_match is not None and not is_stt_sleeping():
                if wake_match.skip_unmatched_inline:
                    if not inline_cmd:
                        logger.debug(
                            "skip_unmatched_inline: standalone wake %r with no command — skipping",
                            wake_match.word,
                        )
                        if on_stt_event:
                            on_stt_event(
                                "skipped",
                                {"word": wake_match.word, "text": ""},
                            )
                        _reset_stage1_state()
                        stage1.Reset()
                        continue
                    triggers = _resolve_triggers(wake_match, config.triggers)
                    if not match_trigger(
                        inline_cmd,
                        triggers,
                        algorithm=config.recognition.matching_algorithm,
                        threshold=config.recognition.matching_threshold,
                    ):
                        logger.debug(
                            "skip_unmatched_inline: inline %r didn't match any trigger for %r",
                            inline_cmd,
                            wake_match.word,
                        )
                        if on_stt_event:
                            on_stt_event(
                                "skipped",
                                {"word": wake_match.word, "text": inline_cmd},
                            )
                        _reset_stage1_state()
                        stage1.Reset()
                        continue
                _wake_detected(
                    wake_group=wake_match,
                    proc=proc,
                    channels=channels,
                    backend=stage2_backend,
                    config=config,
                    stop_event=stop_event,
                    telegram_client=telegram_client,
                    livekit_connect_fn=livekit_connect_fn,
                    livekit_connected_flag=livekit_connected_flag,
                    on_stt_event=on_stt_event,
                    mqtt_client=mqtt_client,
                    loop=loop,
                    dispatch_loop=dispatch_loop,
                    vad_silence_ms=_eff_vad_ms,
                    pre_transcript=inline_cmd,
                )
                logger.debug(
                    f"two-stage: dispatch returned — livekit_flag={livekit_connected_flag.is_set()} "
                    f"was_gated={was_gated}"
                )
                _drain_pipe(proc)
                _dispatch_ended_at[0] = time.monotonic()
                _reset_stage1_state()
                stage1 = _make_stage1_recognizer()
                if on_stt_event:
                    on_stt_event(
                        "listening",
                        {"wake_words": [g.word for g in config.wake_words]},
                    )
                if mqtt_client:
                    mqtt_client.publish_threadsafe(
                        f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                        "idle",
                        loop=loop,
                    )
            else:
                if vosk_use_grammar and vosk_text and config.wake_words:
                    _direct_triggers = config.direct_triggers
                    _dm_trigger = None
                    if _direct_triggers:
                        _vosk_words = len(vosk_text.split())
                        _dm_candidates = [
                            t
                            for t in _direct_triggers
                            if _vosk_words >= len(normalize_text(t.phrase).split())
                        ]
                        _dm_trigger = (
                            match_trigger(
                                vosk_text,
                                _dm_candidates,
                                algorithm=config.recognition.matching_algorithm,
                                threshold=config.recognition.matching_threshold,
                            )
                            if _dm_candidates
                            else None
                        )
                        if _dm_trigger is not None:
                            logger.info(
                                "Direct-match trigger: %r -> %r",
                                vosk_text,
                                _dm_trigger.phrase,
                            )
                            _reset_stage1_state()
                            stage1 = _make_stage1_recognizer()
                            _wake_detected(
                                wake_group=config.wake_words[0],
                                proc=proc,
                                channels=channels,
                                backend=stage2_backend,
                                config=config,
                                stop_event=stop_event,
                                telegram_client=telegram_client,
                                livekit_connect_fn=livekit_connect_fn,
                                livekit_connected_flag=livekit_connected_flag,
                                on_stt_event=on_stt_event,
                                mqtt_client=mqtt_client,
                                loop=loop,
                                dispatch_loop=dispatch_loop,
                                vad_silence_ms=_eff_vad_ms,
                                pre_transcript=vosk_text,
                                pre_trigger=_dm_trigger,
                            )
                            _drain_pipe(proc)
                            _dispatch_ended_at[0] = time.monotonic()
                            if on_stt_event:
                                on_stt_event(
                                    "listening",
                                    {"wake_words": [g.word for g in config.wake_words]},
                                )
                            if mqtt_client:
                                mqtt_client.publish_threadsafe(
                                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                                    "idle",
                                    loop=loop,
                                )
                            continue
                    if _dm_trigger is None and is_stt_sleeping() and vosk_text:
                        phrases_str = get_wake_up_phrases(config)
                        logger.info(f"sleeping... wait for wake up {phrases_str}")
                _drain_pipe(proc)
                _reset_stage1_state()
                stage1.Reset()
        else:
            chunk_ms = len(data) / (16000 * 2) * 1000
            if rms > _eff_stage1_rms:
                stage1_last_speech_t = time.monotonic()
                stage1_speech_ms += chunk_ms

            vad_triggered = (
                stage1_speech_ms >= _eff_stage1_min_speech_ms
                and stage1_last_speech_t > 0
                and (time.monotonic() - stage1_last_speech_t) * 1000
                >= _eff_stage1_vad_ms
            )
            endpoint_fired = stage1_backend.accept_waveform(data)

            if endpoint_fired or vad_triggered:
                if vad_triggered and not endpoint_fired:
                    text = stage1_backend.finalize().strip()
                    trigger_src = "vad"
                else:
                    text = stage1_backend.text().strip()
                    stage1_backend.reset()
                    trigger_src = "endpoint"
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
                if text:
                    logger.debug(f"Stage1 result (sherpa/{trigger_src}): {text!r}")
                    wake_match = _approx_wake_match(text, alias_map)
                    if wake_match and not is_stt_sleeping():
                        _wake_detected(
                            wake_group=wake_match,
                            proc=proc,
                            channels=channels,
                            backend=stage2_backend,
                            config=config,
                            stop_event=stop_event,
                            telegram_client=telegram_client,
                            livekit_connect_fn=livekit_connect_fn,
                            livekit_connected_flag=livekit_connected_flag,
                            on_stt_event=on_stt_event,
                            mqtt_client=mqtt_client,
                            loop=loop,
                            dispatch_loop=dispatch_loop,
                            vad_silence_ms=_eff_vad_ms,
                        )
                        _drain_pipe(proc)
                        _dispatch_ended_at[0] = time.monotonic()
                        stage1_last_speech_t = 0.0
                        stage1_speech_ms = 0.0
                        if on_stt_event:
                            on_stt_event(
                                "listening",
                                {"wake_words": [g.word for g in config.wake_words]},
                            )
                        if mqtt_client:
                            mqtt_client.publish_threadsafe(
                                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                                "idle",
                                loop=loop,
                            )
                    elif wake_match and is_stt_sleeping():
                        phrases_str = get_wake_up_phrases(config)
                        logger.info(f"sleeping... wait for wake up {phrases_str}")
            else:
                partial = stage1_backend.partial_text().strip()
                if partial and on_stt_event:
                    on_stt_event("transcribing", {"text": partial})


def _follow_up_active(trigger: "Trigger | None", config: ActionsConfig) -> bool:
    """Return whether a follow-up window should open after dispatching *trigger*.

    Per-trigger follow_up override takes precedence over the global flag.
    llm_chat-only triggers manage their own multi-turn loop, so we suppress the
    outer follow-up window for them to avoid double-looping.
    """
    if not config.recognition.follow_up and (
        trigger is None or trigger.follow_up is None
    ):
        return False
    if trigger is not None and trigger.follow_up is not None:
        explicit = trigger.follow_up
    else:
        explicit = config.recognition.follow_up
    if not explicit:
        return False
    # Suppress for llm_chat-only triggers — they run their own conversation loop.
    if trigger is not None and all(a.type == "llm_chat" for a in trigger.actions):
        return False
    return True


def _wake_detected(
    wake_group: WakeWordGroup,
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
    vad_silence_ms: int | None = None,
    pre_transcript: str = "",
    pre_trigger: "Trigger | None" = None,
) -> None:
    if pre_trigger is not None:
        logger.info(f"Direct trigger: '{pre_trigger.phrase}'")
        if on_stt_event:
            on_stt_event("direct", {"phrase": pre_trigger.phrase})
    else:
        logger.info(f"Wake word detected: '{wake_group.word}'")
        metrics.inc("wake_detections")
        if on_stt_event:
            on_stt_event(
                "wake",
                {
                    "word": wake_group.word,
                    "timeout": config.recognition.command_timeout,
                },
            )
        try:
            play_wake_beep(config.recognition.wake_tone)
        except Exception as e:
            logger.debug(f"Wake beep failed: {e}")
    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
            "listening",
            loop=loop,
        )

    if pre_transcript:
        logger.info(f"Inline command from stage-1: '{pre_transcript}'")
        transcript = pre_transcript
    else:
        transcript = capture_transcript(
            proc,
            channels,
            backend,
            config.recognition.command_timeout,
            stop_event,
            on_stt_event,
            flush_ms=config.stt.flush_ms,
            vad_silence_ms=vad_silence_ms,
            hard_timeout=config.recognition.command_max_timeout,
        )
    logger.info(f"Command transcript: '{transcript}'")

    _listen_fn = _make_listen_fn(
        proc, channels, backend, stop_event, on_stt_event, vad_silence_ms
    )
    _dloop = dispatch_loop
    if _dloop is None:
        logger.error("_wake_detected: dispatch_loop is None — cannot dispatch actions")
        return
    _ctx = ActionContext(
        telegram_client=telegram_client,
        livekit_connect_fn=livekit_connect_fn,
        livekit_connected=livekit_connected_flag.is_set(),
        listen_fn=_listen_fn,
        mqtt_client=mqtt_client,
        on_stt_event=on_stt_event,
        actions_config=config,
    )

    if not transcript:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        _play_timeout()
        return

    def _handle_command(
        cmd: str, forced_trigger: "Trigger | None" = None
    ) -> "Trigger | None":
        """Match and dispatch one command turn. Returns the matched trigger or None."""
        if mqtt_client:
            payload = json.dumps(
                {"text": cmd, "wake_word": wake_group.word, "timestamp": time.time()}
            )
            mqtt_client.publish_threadsafe(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/command",
                payload,
                loop=loop,
            )

        if forced_trigger is not None:
            trig = forced_trigger
        else:
            triggers = _resolve_triggers(wake_group, config.triggers)
            trig = match_trigger(
                cmd,
                triggers,
                algorithm=config.recognition.matching_algorithm,
                threshold=config.recognition.matching_threshold,
            )

        if trig is not None and is_stt_sleeping():
            has_start_listening = any(a.type == "start_listening" for a in trig.actions)
            if not has_start_listening:
                phrases_str = get_wake_up_phrases(config)
                logger.info(f"sleeping... wait for wake up {phrases_str}")
                return None

        if trig is not None and not is_stt_sleeping():
            if any(a.type == "start_listening" for a in trig.actions):
                logger.info(
                    "start_listening trigger '%s' ignored: system is already awake",
                    trig.phrase,
                )
                return None

        if trig is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": cmd})
            if config.llm and config.llm.fallback_on_no_match:
                _fb_trigger = Trigger(
                    phrase="__llm_fallback__",
                    actions=[ActionEntry(type="llm_chat", params={})],
                )
                try:
                    _ctx.livekit_connected = livekit_connected_flag.is_set()
                    _dloop.run_until_complete(
                        asyncio.wait_for(
                            dispatch(
                                _fb_trigger,
                                _ctx,
                                wake_word=wake_group.word,
                                transcript=cmd,
                            ),
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
            else:
                _play_timeout()
            return None

        metrics.inc("commands_matched")
        if on_stt_event:
            on_stt_event("matched", {"transcript": cmd, "trigger": trig.phrase})

        if trig.wake_words == []:
            try:
                play_wake_beep(config.recognition.wake_tone)
            except Exception as e:
                logger.debug(f"Direct match beep failed: {e}")

        try:
            _ctx.livekit_connected = livekit_connected_flag.is_set()
            _dloop.run_until_complete(
                asyncio.wait_for(
                    dispatch(trig, _ctx, wake_word=wake_group.word, transcript=cmd),
                    timeout=config.recognition.dispatch_timeout,
                )
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Dispatch timed out after %.0fs — resetting and resuming",
                config.recognition.dispatch_timeout,
            )
            _drain_pipe(proc)
            backend.reset()
        except Exception as e:
            logger.error(f"Action dispatch failed: {e}")

        return trig

    matched_trigger = _handle_command(transcript, forced_trigger=pre_trigger)

    # Follow-up conversation loop: re-listen without requiring the wake word.
    turns = 0
    while (
        _follow_up_active(matched_trigger, config)
        and not livekit_connected_flag.is_set()
        and turns < config.recognition.follow_up_max_turns
    ):
        turns += 1
        _drain_pipe(proc)
        try:
            play_wake_beep(config.recognition.follow_up_tone)
        except Exception as e:
            logger.debug(f"Follow-up tone failed: {e}")
        if mqtt_client:
            mqtt_client.publish_threadsafe(
                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                "listening",
                loop=loop,
            )
        if on_stt_event:
            on_stt_event(
                "listening", {"wake_words": [g.word for g in config.wake_words]}
            )

        follow_up_transcript = capture_transcript(
            proc,
            channels,
            backend,
            config.recognition.follow_up_timeout,
            stop_event,
            on_stt_event,
            flush_ms=config.stt.flush_ms,
            vad_silence_ms=vad_silence_ms,
        )
        if not follow_up_transcript:
            logger.debug("Follow-up: silence — closing window")
            break

        from alexa_custom.llm import is_exit_phrase

        exit_phrases = config.llm.exit_phrases if config.llm else None
        if is_exit_phrase(follow_up_transcript, exit_phrases):
            logger.debug(
                "Follow-up: exit phrase '%s' — closing window", follow_up_transcript
            )
            break

        logger.info("Follow-up turn %d: '%s'", turns, follow_up_transcript)
        matched_trigger = _handle_command(follow_up_transcript)


def start_stt_thread(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
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
