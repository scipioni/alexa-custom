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

from alexa_custom.actions import TelegramClient, dispatch, match_trigger, normalize_text
from alexa_custom.audio import is_playback_active, play_timeout_beep, play_wake_beep
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
)
from alexa_custom.stt_phonetics import (
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
    resolve_capture_source,
    start_capture,
    _iter_gated_audio,
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
    "resolve_capture_source",
    "start_capture",
    "_iter_gated_audio",
    "run_stt_worker",
    "_extract_wake_command",
    "capture_transcript",
    "start_stt_thread",
]

logger = logging.getLogger(__name__)

_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_STT_COOLDOWN = 1.0
_SHERPA_MODEL_PATH = os.environ.get("SHERPA_ONNX_PATH", "models/sherpa-onnx")

_STAGE1_VAD_SILENCE_MS = int(os.environ.get("STT_STAGE1_VAD_SILENCE_MS", "500"))
_STAGE1_RMS_THRESHOLD = float(os.environ.get("STT_STAGE1_RMS_THRESHOLD", "0.02"))
_STAGE1_MIN_SPEECH_MS = int(os.environ.get("STT_STAGE1_MIN_SPEECH_MS", "200"))
_VAD_SILENCE_MS = int(os.environ.get("STT_VAD_SILENCE_MS", "500"))


def _make_listen_fn(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None,
    vad_silence_ms: int | None,
) -> Callable:
    """Return an async listen function closed over the given capture context."""

    async def _listen_fn(
        timeout: float,
        flush_ms: int = 0,
        phrases: list[str] | None = None,
        start_after_playback: bool = False,
    ) -> str:
        if on_stt_event:
            on_stt_event("wake", {"word": "(reply)", "timeout": timeout})
        return await asyncio.to_thread(
            capture_transcript,
            proc,
            channels,
            backend,
            timeout,
            stop_event,
            on_stt_event,
            flush_ms=flush_ms,
            phrases=phrases,
            start_after_playback=start_after_playback,
            vad_silence_ms=vad_silence_ms,
        )

    return _listen_fn


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
        stage2_backend = get_stt_backend(current_config.stt.stage2)
        logger.info(
            f"STT stage2 backend ({current_config.stt.stage2.backend}) loaded in {time.monotonic() - t0:.1f}s"
        )
    except RuntimeError as e:
        logger.error(f"STT backend creation failed: {e}")
        return

    stage1_key = (
        current_config.stt.stage1.backend,
        current_config.stt.stage1.model_path,
    )
    stage2_key = (
        current_config.stt.stage2.backend,
        current_config.stt.stage2.model_path,
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
            )
            new_stage2_key = (
                current_config.stt.stage2.backend,
                current_config.stt.stage2.model_path,
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
                    time.sleep(2)
                    continue

            if new_stage2_key != stage2_key:
                try:
                    stage2_backend = get_stt_backend(current_config.stt.stage2)
                    stage2_key = new_stage2_key
                    logger.info("STT stage2 backend reloaded after config change")
                except RuntimeError as e:
                    logger.error(f"STT stage2 backend reload failed: {e}")
                    time.sleep(2)
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
    text: str, alias_map: dict[str, WakeWordGroup], fuzzy: bool = False
) -> tuple[WakeWordGroup | None, str]:
    """Return (group, command) if text begins with a known wake phrase, else (None, '').

    With fuzzy=True (sherpa-onnx single-stage path) uses _approx_wake_match to
    handle open-vocabulary transcription noise around wake words.
    """
    norm_text = normalize_text(text)
    for norm_phrase, group in alias_map.items():
        if norm_text.startswith(norm_phrase):
            command = text.lower().replace(norm_phrase, "", 1).strip()
            return group, command
    if fuzzy:
        group = _approx_wake_match(text, alias_map)
        if group:
            # Best-effort command extraction: strip matching phrase words from text
            norm_phrase = normalize_text(group.word)
            command = norm_text
            for w in norm_phrase.split():
                command = command.replace(w, "", 1).strip()
            return group, command
    return None, ""


def capture_transcript(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    timeout: float,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    flush_ms: int = 0,
    phrases: list[str] | None = None,
    start_after_playback: bool = False,
    vad_silence_ms: int | None = None,
) -> str:
    """Capture audio for a set duration and return the transcribed text."""
    assert proc.stdout is not None
    drained = _drain_pipe(proc)
    if drained:
        logger.debug(f"Drained {drained} bytes of stale audio before capture")

    if flush_ms > 0:
        bytes_to_flush = int(16000 * channels * 2 * (flush_ms / 1000))
        while bytes_to_flush > 0:
            chunk = _read_with_timeout(
                proc.stdout, min(_CHUNK * channels, bytes_to_flush), 0.05
            )
            if not chunk:
                break
            bytes_to_flush -= len(chunk)

    grammar = _phrases_to_grammar(phrases) if phrases else None
    if isinstance(backend, VoskSTT):
        backend.recreate(grammar)
    else:
        backend.reset()
    deadline = time.monotonic() + timeout
    transcript_parts: list[str] = []
    was_playing = False
    last_partial = ""
    last_activity = time.monotonic()
    got_speech = False

    while not stop_event.is_set() and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        raw_data = _read_with_timeout(
            proc.stdout, _CHUNK * channels, min(remaining, 1.0)
        )
        if not raw_data:
            if proc.poll() is not None:
                logger.warning("Capture pipe closed mid-listen (parec exited)")
                break
            continue

        if is_playback_active():
            was_playing = True
            continue

        if was_playing:
            _drain_pipe(proc)
            backend.reset()
            was_playing = False
            if start_after_playback:
                deadline = time.monotonic() + timeout
            last_partial = ""
            last_activity = time.monotonic()
            got_speech = False
            continue

        data = _downmix_to_mono(raw_data, channels)

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if backend.accept_waveform(data):
            text = backend.text()
            if text:
                logger.info(f"Capture match: '{text}'")
                if on_stt_event:
                    on_stt_event("partial", {"text": text})

                if phrases:
                    return text

                transcript_parts.append(text)
                got_speech = True
                last_activity = time.monotonic()
                last_partial = ""
        else:
            partial = backend.partial_text()
            if partial != last_partial:
                last_partial = partial
                if partial:
                    got_speech = True
                    last_activity = time.monotonic()
                    if on_stt_event:
                        full = " ".join(transcript_parts + [partial])
                        on_stt_event("partial", {"text": full})

        _effective_vad_ms = (
            vad_silence_ms if vad_silence_ms is not None else _VAD_SILENCE_MS
        )
        if (
            got_speech
            and (time.monotonic() - last_activity) * 1000 >= _effective_vad_ms
        ):
            break

    final_text = backend.finalize()
    if final_text:
        transcript_parts.append(final_text)

    return " ".join(transcript_parts).strip()


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
    for data in _iter_gated_audio(
        proc, channels, stop_event, on_playback_end=backend.reset, name="single-stage"
    ):
        if data is None:
            continue

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if on_stt_event:
                on_stt_event("gated", {})
            continue

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

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
        trigger = match_trigger(command, triggers)
        if trigger is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": command})
            if config.llm and config.llm.fallback_on_no_match:
                _fb_trigger = Trigger(
                    phrase="__llm_fallback__",
                    actions=[ActionEntry(type="llm_chat", params={})],
                )
                try:
                    _dloop.run_until_complete(
                        dispatch(
                            _fb_trigger,
                            telegram_client,
                            livekit_connect_fn,
                            livekit_connected=livekit_connected_flag.is_set(),
                            listen_fn=_listen_fn,
                            on_stt_event=on_stt_event,
                            actions_config=config,
                            wake_word=wake_group.word,
                            transcript=command,
                            mqtt_client=mqtt_client,
                        )
                    )
                except Exception as e:
                    logger.error("LLM fallback error: %s", e)
                _drain_pipe(proc)
                backend.reset()
            else:
                _play_timeout()
            continue

        if on_stt_event:
            on_stt_event("matched", {"transcript": command, "trigger": trigger.phrase})

        connected = livekit_connected_flag.is_set()
        try:
            _dloop.run_until_complete(
                dispatch(
                    trigger,
                    telegram_client,
                    livekit_connect_fn,
                    livekit_connected=connected,
                    listen_fn=_listen_fn,
                    on_stt_event=on_stt_event,
                    actions_config=config,
                    wake_word=wake_group.word,
                    transcript=command,
                )
            )
            _drain_pipe(proc)
            backend.reset()
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
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

    alias_map = _build_alias_map(config.wake_words)
    is_vosk = isinstance(stage1_backend, VoskSTT)
    is_kws = isinstance(stage1_backend, SherpaKeywordSpotter)
    vosk_use_grammar = config.stt.stage1.vosk_grammar

    def _make_stage1_recognizer() -> "vosk.KaldiRecognizer":
        if vosk_use_grammar:
            rec = vosk.KaldiRecognizer(
                vosk_model, 16000, _grammar_json(config.wake_words)
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

    if on_stt_event:
        on_stt_event(
            "listening",
            {"wake_words": [g.word for g in config.wake_words]},
        )

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    if is_vosk:

        def _on_playback_end() -> None:
            stage1.Reset()
    elif is_kws:

        def _on_playback_end() -> None:
            stage1_backend.reset()
    else:

        def _on_playback_end() -> None:
            nonlocal stage1_last_speech_t, stage1_speech_ms
            stage1_backend.reset()
            stage1_last_speech_t = 0.0
            stage1_speech_ms = 0.0

    for data in _iter_gated_audio(
        proc, channels, stop_event, on_playback_end=_on_playback_end, name="two-stage"
    ):
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
        if on_stt_event:
            on_stt_event("level", {"mic": rms})

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
            elif is_kws:
                stage1_backend.reset()
            else:
                stage1_backend.reset()
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
            continue

        if is_kws:
            if stage1_backend.accept_waveform(data):
                keyword = stage1_backend.text()
                wake_match = alias_map.get(normalize_text(keyword))
                if wake_match:
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

            if on_stt_event:
                partial = json.loads(stage1.PartialResult()).get("partial", "").strip()
                if partial:
                    on_stt_event("transcribing", {"text": partial})

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
                rms_gate = config.stt.stage1.rms_threshold

            stage1_last_speech_t = 0.0
            stage1_speech_ms = 0.0

            inline_cmd = ""
            if vosk_use_grammar:
                wake_match = _vosk_check_result(
                    data,
                    result,
                    alias_map,
                    config.stt.stage1.confidence,
                    config.stt.stage1.confidence_mode,
                    rms_gate,
                )
            else:
                text = result.get("text", "").strip()
                logger.debug("Stage1 Vosk free-vocab result: %r", text)
                wake_match, inline_cmd = (
                    _extract_wake_command(text, alias_map, fuzzy=True)
                    if text
                    else (None, "")
                )

            if wake_match is not None:
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
                    pre_transcript=inline_cmd,
                )
                logger.debug(
                    f"two-stage: dispatch returned — livekit_flag={livekit_connected_flag.is_set()} "
                    f"was_gated={was_gated}"
                )
                _drain_pipe(proc)
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
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
                backlog = _drain_pipe(proc)
                if backlog:
                    logger.debug(
                        f"two-stage: drained {backlog} backlog bytes after segment"
                    )
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
                    if wake_match:
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
            else:
                partial = stage1_backend.partial_text().strip()
                if partial and on_stt_event:
                    on_stt_event("transcribing", {"text": partial})


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
) -> None:
    logger.info(f"Wake word detected: '{wake_group.word}'")
    if on_stt_event:
        on_stt_event(
            "wake",
            {"word": wake_group.word, "timeout": config.recognition.command_timeout},
        )
    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
            "listening",
            loop=loop,
        )
    try:
        play_wake_beep(config.recognition.wake_tone)
    except Exception as e:
        logger.debug(f"Wake beep failed: {e}")

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
            flush_ms=300,
            vad_silence_ms=vad_silence_ms,
        )
    logger.info(f"Command transcript: '{transcript}'")

    _listen_fn = _make_listen_fn(
        proc, channels, backend, stop_event, on_stt_event, vad_silence_ms
    )
    _dloop = dispatch_loop

    if not transcript:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        if config.llm and config.llm.fallback_on_no_match:
            pass
        else:
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
        if config.llm and config.llm.fallback_on_no_match:
            _fb_trigger = Trigger(
                phrase="__llm_fallback__",
                actions=[ActionEntry(type="llm_chat", params={})],
            )
            try:
                _dloop.run_until_complete(
                    dispatch(
                        _fb_trigger,
                        telegram_client,
                        livekit_connect_fn,
                        livekit_connected=livekit_connected_flag.is_set(),
                        listen_fn=_listen_fn,
                        on_stt_event=on_stt_event,
                        actions_config=config,
                        wake_word=wake_group.word,
                        transcript=transcript,
                        mqtt_client=mqtt_client,
                    )
                )
            except Exception as e:
                logger.error("LLM fallback error: %s", e)
            _drain_pipe(proc)
            backend.reset()
        else:
            _play_timeout()
        return

    if on_stt_event:
        on_stt_event("matched", {"transcript": transcript, "trigger": trigger.phrase})

    connected = livekit_connected_flag.is_set()
    try:
        _dloop.run_until_complete(
            dispatch(
                trigger,
                telegram_client,
                livekit_connect_fn,
                livekit_connected=connected,
                listen_fn=_listen_fn,
                on_stt_event=on_stt_event,
                actions_config=config,
                wake_word=wake_group.word,
                transcript=transcript,
                mqtt_client=mqtt_client,
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
