from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import json
import logging
import os
import queue
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
from alexa_custom.audio import play_wake_beep_async
from alexa_custom.config import (
    ActionEntry,
    ActionsConfig,
    Trigger,
)

from alexa_custom.stt_backends import (
    STTBackend,
    VoskSTT,
    _load_model,
    _MODEL_PATH,
    get_stt_backend,
    _phrases_to_grammar,
    _grammar_json,
    _vosk_confidence,
    _vosk_check_result,
)
from alexa_custom.stt_phonetics import (
    _match_wake_word,
    _wake_token_count,
    _approx_wake_match,
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
    "_load_model",
    "_MODEL_PATH",
    "get_stt_backend",
    "_phrases_to_grammar",
    "_grammar_json",
    "_vosk_confidence",
    "_vosk_check_result",
    "_loop_grammar",
    "_approx_wake_match",
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


def _loop_grammar(cfg: ActionsConfig) -> str | None:
    """Grammar for the always-on recognizer, or None for free-text.

    When ``stt.vosk_grammar`` is set, restrict the recognizer to the wake words
    plus every trigger command/alias so it can only emit phrases the matcher
    accepts — an omitted phrase is physically unrecognisable. Confidence gating
    (``stt.confidence``) then rejects whatever the constrained model snapped out
    of noise.
    """
    if not cfg.stt.vosk_grammar:
        return None
    phrases: list[str] = list(cfg.wake_words)
    for t in cfg.triggers:
        phrases.extend(t.commands or [t.phrase])
        phrases.extend(t.aliases)
    return _phrases_to_grammar(phrases, label="wake-loop")


def _get_backend_key(cfg: ActionsConfig) -> tuple:
    return (
        cfg.stt.backend,
        cfg.stt.model_path,
        cfg.stt.num_threads,
        cfg.stt.vosk_grammar,
        _loop_grammar(cfg),
    )


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


def _fast_partial_hit(partial: str, config: ActionsConfig, woken: bool) -> bool:
    """True when the partial transcript already fully matches a wake word or a
    dispatchable trigger.

    Used by the fast-VAD path: when the recognizer's partial result is already
    a complete, matchable utterance, the endpoint fires after
    ``stt.fast_vad_ms`` of silence instead of the full ``vad_silence_ms`` —
    cutting ~500 ms off every wake/command. Free-form speech (LLM fallback)
    never matches here, so it keeps the long, fragmentation-safe endpoint.
    """
    wake_phrase, residual = _match_wake_word(
        partial, config.wake_words, threshold=config.stt.wake_match_threshold
    )
    if wake_phrase is not None:
        if not residual:
            return True
        trig, _ = match_trigger_with_score(
            residual,
            config.triggers,
            algorithm=config.recognition.matching_algorithm,
            threshold=config.recognition.matching_threshold,
            min_word_overlap=config.recognition.min_word_overlap,
        )
        return trig is not None

    candidates = [t for t in config.triggers if not t.with_wake or woken]
    if not candidates:
        return False
    trig, _ = match_trigger_with_score(
        partial,
        candidates,
        algorithm=config.recognition.matching_algorithm,
        threshold=config.recognition.matching_threshold,
        min_word_overlap=config.recognition.min_word_overlap,
    )
    return trig is not None


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
    capture_restart_event: threading.Event | None = None,
) -> None:
    """Single-model transcribe→match→gate→tone→dispatch recognition loop."""
    assert dispatch_loop is not None

    wake_deadline: float = 0.0
    _dispatch_ended_at: list[float] = [0.0]
    _noise_floor: list[float] = []
    speech_ms: float = 0.0
    last_speech_t: float = 0.0
    was_gated = False
    _last_partial: str = ""
    # Decoder hygiene during idle: hardware-NS speakerphones (SP92) gate a
    # quiet room to digital zeros, and minutes of pure zeros are pathological
    # input for Vosk's adaptive decoder state. Reset the recognizer after
    # every _IDLE_RESET_S of continuous sub-threshold audio so the first real
    # utterance after idle decodes from a clean slate.
    _IDLE_RESET_S = 30.0
    _last_voice_t: float = time.monotonic()
    _last_idle_reset: float = time.monotonic()

    from alexa_custom.audio_hw import get_profile_stt_overrides as _get_stt_overrides

    _profile_stt = _get_stt_overrides()
    _eff_rms = float(_profile_stt.get("rms_threshold", config.stt.rms_threshold))
    _vad_silence_ms = int(_profile_stt.get("vad_silence_ms", config.stt.vad_silence_ms))
    _fast_vad_ms = int(_profile_stt.get("fast_vad_ms", config.stt.fast_vad_ms))
    if _fast_vad_ms >= _vad_silence_ms:
        _fast_vad_ms = 0  # fast path can never fire before the normal endpoint
    if _profile_stt:
        logger.debug(
            "Profile STT overrides active: rms_threshold=%.4f vad_silence_ms=%d",
            _eff_rms,
            _vad_silence_ms,
        )

    # Rolling pre-trigger buffer for dump_triggers_dir, budgeted in BYTES.
    # Chunk sizes vary by capture backend (parec ~4 KB reads, GStreamer ~320-byte
    # 10 ms buffers), so a chunk-count maxlen silently shrinks the window — a
    # 63-chunk cap held ~1.2 s of gst audio instead of the intended 8 s.
    # The buffer always holds post-downmix MONO s16le chunks (_iter_gated_audio
    # downmixes before yielding), regardless of the capture's own channel
    # count — so the budget and dump WAV must always be sized for 1 channel,
    # not the capture `channels` (which was doubling both for stereo sources).
    _audio_buf: collections.deque[bytes] = collections.deque()
    _audio_buf_bytes = 0
    _audio_buf_max = 8 * 16000 * 2

    def _buffer_dump_audio(chunk: bytes) -> None:
        nonlocal _audio_buf_bytes
        _audio_buf.append(chunk)
        _audio_buf_bytes += len(chunk)
        while _audio_buf_bytes > _audio_buf_max:
            _audio_buf_bytes -= len(_audio_buf.popleft())

    _listen_fn = _make_listen_fn(
        proc,
        channels,
        backend,
        stop_event,
        on_stt_event,
        _vad_silence_ms,
        confidence=config.stt.confidence,
        confidence_mode=config.stt.confidence_mode,
        fast_vad_ms=_fast_vad_ms,
        dump_dir=config.dump_triggers_dir,
        rms_gate=config.stt.reply_rms_gate,
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

    # Actions triggered externally (MQTT action/run, trigger/run) must not run
    # concurrently with this thread's own continuous capture — anything using
    # listen_fn (e.g. "ask") reaches into the same VAD/STT backend object the
    # recognition loop below is feeding audio into, and the two are not
    # reentrant: running both at once corrupts the backend's internal state
    # (observed as "RuntimeError: NULL input supplied for input h"). So
    # external requests are queued here as zero-arg jobs and actually run from
    # inside the main for-loop below, on this same thread, using the same
    # dispatch_loop.run_until_complete() mechanism a matched voice trigger
    # uses — never from the MQTT callback's own (different) asyncio loop.
    _external_actions: queue.SimpleQueue = queue.SimpleQueue()

    async def _on_mqtt_command(action_data: dict) -> None:
        result_future: concurrent.futures.Future = concurrent.futures.Future()

        if "command" in action_data:
            # trigger/run: match against conf/actions/user.yaml exactly like a
            # real recognized transcript, so on_reply/on_else/patterns/tag all
            # behave the same as when the phrase is actually spoken.
            text = str(action_data.get("command") or "").strip()
            if not text:
                logger.warning("MQTT trigger/run: empty command")
                return
            trig, score = match_trigger_with_score(
                text,
                config.triggers,
                algorithm=config.recognition.matching_algorithm,
                threshold=config.recognition.matching_threshold,
                min_word_overlap=config.recognition.min_word_overlap,
            )
            if trig is None:
                logger.warning(
                    "MQTT trigger/run: no trigger matched %r (score=%.0f)",
                    text,
                    score,
                )
                return

            def _job_trigger(
                trig=trig, text=text, score=score, fut=result_future
            ) -> None:
                try:
                    _dispatch_trigger(trig, None, text, score)
                finally:
                    if not fut.done():
                        fut.set_result(None)

            job = _job_trigger
        else:
            action_type = action_data.get("type")
            if not action_type:
                logger.warning("MQTT command missing 'type'/'command': %r", action_data)
                return
            trigger = Trigger(
                commands=[],
                actions=[
                    ActionEntry(
                        type=action_type, params=action_data.get("params") or {}
                    )
                ],
            )

            def _job_action(trigger=trigger, fut=result_future) -> None:
                _dispatch_external_action(trigger, fut)

            job = _job_action

        _external_actions.put(job)
        await asyncio.wrap_future(result_future)

    if mqtt_client:
        mqtt_client.set_on_command(_on_mqtt_command)

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
            # _audio_buf holds post-downmix mono chunks regardless of the
            # capture's channel count — always dump as 1 channel.
            _dump_trigger_wav(_audio_buf, 1, trigger.phrase, config.dump_triggers_dir)

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

        _timeout = (
            trigger.dispatch_timeout
            if trigger.dispatch_timeout is not None
            else config.recognition.dispatch_timeout
        )

        async def _dispatch_with_heartbeat() -> None:
            # Keep the watchdog heartbeat fresh for legitimate long dispatches
            # (e.g. LLM conversations with reply windows) by stamping while
            # the dispatch coroutine is actually yielding control back to the
            # loop. A dispatch wedged in a non-yielding call (e.g. a
            # synchronous subprocess without a timeout) blocks this loop too,
            # so the stamp correctly stops advancing in that case.
            async def _stamp_periodically() -> None:
                while True:
                    await asyncio.sleep(5.0)
                    _stt_heartbeat[0] = time.monotonic()

            stamp_task = asyncio.ensure_future(_stamp_periodically())
            try:
                await dispatch(
                    trigger,
                    _ctx,
                    wake_word=wake_phrase or "",
                    transcript=transcript,
                )
            finally:
                stamp_task.cancel()

        try:
            _ctx.livekit_connected = livekit_connected_flag.is_set()
            dispatch_loop.run_until_complete(
                asyncio.wait_for(_dispatch_with_heartbeat(), timeout=_timeout)
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Dispatch timed out after %.0fs — resetting and resuming",
                _timeout,
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
                play_wake_beep_async(config.recognition.follow_up_tone)
            except Exception:
                pass
        else:
            wake_deadline = 0.0

        if on_stt_event:
            on_stt_event("listening", {"wake_words": config.wake_words})
        _publish_state("idle")

    def _dispatch_external_action(
        trigger: Trigger, result_future: concurrent.futures.Future
    ) -> None:
        """Run an MQTT-triggered action on this thread, via dispatch_loop —
        mirrors _dispatch_trigger's dispatch mechanics minus the voice-match
        bookkeeping (trigger dump, matched event, command topic publish,
        follow-up wake window), which don't apply to an external request."""
        _timeout = config.recognition.dispatch_timeout

        async def _dispatch_with_heartbeat() -> None:
            async def _stamp_periodically() -> None:
                while True:
                    await asyncio.sleep(5.0)
                    _stt_heartbeat[0] = time.monotonic()

            stamp_task = asyncio.ensure_future(_stamp_periodically())
            try:
                await dispatch(trigger, _ctx, wake_word="", transcript="")
            finally:
                stamp_task.cancel()

        try:
            _ctx.livekit_connected = livekit_connected_flag.is_set()
            dispatch_loop.run_until_complete(
                asyncio.wait_for(_dispatch_with_heartbeat(), timeout=_timeout)
            )
        except Exception as e:
            logger.error("MQTT-triggered action dispatch failed: %s", e)
            if not result_future.done():
                result_future.set_exception(e)
        else:
            if not result_future.done():
                result_future.set_result(None)
        finally:
            _drain_pipe(proc)
            backend.reset()
            _reset_vad()
            _dispatch_ended_at[0] = time.monotonic()
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
        restart_event=capture_restart_event,
        capture_stall_secs=config.stt.capture_stall_secs,
    ):
        _stt_heartbeat[0] = time.monotonic()

        while True:
            try:
                _ext_job = _external_actions.get_nowait()
            except queue.Empty:
                break
            _ext_job()

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
                _adaptive = (
                    sum(_noise_floor) / len(_noise_floor)
                ) + config.stt.adaptive_rms_margin
                # Profile rms_threshold acts as a floor: the adaptive
                # mechanism may raise the threshold in a loud room, but never
                # drops below the calibrated profile value (which sets the
                # minimum sensitivity ceiling for a quiet room).
                _eff_rms = max(
                    _adaptive, float(_profile_stt.get("rms_threshold", _adaptive))
                )

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
            _last_voice_t = now
            speech_ms += (len(data) / 2) / 16000.0 * 1000.0
        elif (
            speech_ms == 0.0
            and now - max(_last_voice_t, _last_idle_reset) >= _IDLE_RESET_S
        ):
            # Long idle, no utterance in progress: clear decoder state built
            # up from gated silence/zeros before real speech arrives.
            backend.reset()
            _last_idle_reset = now

        if config.dump_triggers_dir:
            _buffer_dump_audio(data)

        endpoint = backend.accept_waveform(data)

        if on_stt_event and rms > _eff_rms:
            partial = backend.partial_text()
            if partial and partial != _last_partial:
                on_stt_event("transcribing", {"text": partial})
            _last_partial = partial

        _silence_ms = (now - last_speech_t) * 1000.0 if last_speech_t > 0 else 0.0
        _speech_done = speech_ms >= config.stt.min_speech_ms and last_speech_t > 0

        vad_fire = _speech_done and _silence_ms >= _vad_silence_ms

        # Fast endpoint: when the partial transcript is already a complete
        # wake/trigger match, fire after fast_vad_ms instead of waiting the
        # full vad_silence_ms. Free-form utterances never match and keep the
        # long endpoint.
        if (
            not vad_fire
            and not endpoint
            and _fast_vad_ms > 0
            and _speech_done
            and _silence_ms >= _fast_vad_ms
        ):
            _p = backend.partial_text()
            if _p and _fast_partial_hit(_p, config, woken()):
                logger.debug(
                    "Fast endpoint: partial %r after %.0f ms silence",
                    _p,
                    _silence_ms,
                )
                vad_fire = True

        if vad_fire and not endpoint:
            text = backend.finalize().strip()
            # finalize() flushed the decoder (InputFinished); reset so the
            # next utterance starts on a clean pipeline instead of feeding a
            # flushed recognizer.
            backend.reset()
            _vad_speech_ms = speech_ms
            _reset_vad()
            _last_partial = ""
        elif endpoint:
            text = backend.text().strip()
            _vad_speech_ms = speech_ms
            backend.reset()
            _reset_vad()
            _last_partial = ""
        else:
            continue

        if not text:
            if on_stt_event and _vad_speech_ms >= 50.0:
                on_stt_event("vad_empty", {"speech_ms": round(_vad_speech_ms)})
            continue

        # --- Wake word detection ---
        wake_phrase, residual = _match_wake_word(
            text,
            config.wake_words,
            threshold=config.stt.wake_match_threshold,
        )

        # --- Acoustic confidence gate ---
        # In grammar mode the recognizer snaps noise onto the closest phrase;
        # the per-word `conf` is the only signal that separates that from a real
        # utterance. 0.0 disables the gate (free-text default). When a wake word
        # matched, score only its tokens (transcript minus the trailing command)
        # — this mirrors the offline eval harness (_vosk_check_result), so
        # first/min/mean behave identically online and offline, and a low-
        # confidence trailing command can't sink an otherwise-clear wake. The
        # command/direct-trigger path (no wake word) is scored over the full
        # transcript, since there is no wake portion to isolate.
        _conf = None
        if config.stt.confidence > 0.0 and isinstance(backend, VoskSTT):
            _n_words = (
                _wake_token_count(text, residual) if wake_phrase is not None else None
            )
            _conf = backend.last_confidence(
                config.stt.confidence_mode, n_words=_n_words
            )
            if _conf < config.stt.confidence:
                logger.debug(
                    "Confidence gate rejected %r (conf=%.2f < %.2f, mode=%s, wake=%s)",
                    text,
                    _conf,
                    config.stt.confidence,
                    config.stt.confidence_mode,
                    wake_phrase,
                )
                metrics.inc("confidence_rejections")
                continue

        logger.debug("Transcript: %r (conf=%s)", text, _conf)

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
                            play_wake_beep_async(config.recognition.wake_tone)
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
                # _audio_buf holds post-downmix mono chunks — always dump 1ch.
                _dump_trigger_wav(
                    _audio_buf,
                    1,
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
                    play_wake_beep_async(config.recognition.wake_tone)
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
                    play_wake_beep_async(config.recognition.wake_tone)
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
                    play_wake_beep_async(config.recognition.wake_tone)
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
            play_wake_beep_async(config.recognition.wake_tone)
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
    if (
        current_config.stt.mono_capture
        or current_config.stt.capture_backend == "gstreamer"
    ):
        channels = 1

    logger.info(
        "STT: wake_words=%r backend=%s vad_silence_ms=%d source=%s (%d ch)",
        current_config.wake_words,
        current_config.stt.backend,
        current_config.stt.vad_silence_ms,
        source or "default",
        channels,
    )
    if current_config.stt.backend == "sherpa-onnx":
        # No other startup line records these, and they're not in the
        # backend-reload key — log them so we can confirm a restart actually
        # picked up a config change (see the "sì"/"no" ask-reply VAD tuning).
        logger.info(
            "STT sherpa VAD gate: threshold=%.2f min_speech_ms=%d min_silence_ms=%d",
            current_config.stt.sherpa_vad_threshold,
            current_config.stt.sherpa_vad_min_speech_ms,
            current_config.stt.sherpa_vad_min_silence_ms,
        )
    _log_activation_phrases(current_config)

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    backend = None
    _load_backoff = 10.0
    while backend is None and not stop_event.is_set():
        try:
            t0 = time.monotonic()
            backend = get_stt_backend(
                current_config.stt, grammar=_loop_grammar(current_config)
            )
            logger.info(
                "STT backend (%s) loaded in %.1fs (grammar=%s, confidence=%.2f/%s)",
                current_config.stt.backend,
                time.monotonic() - t0,
                current_config.stt.vosk_grammar,
                current_config.stt.confidence,
                current_config.stt.confidence_mode,
            )
        except Exception as e:
            logger.error(
                "STT backend creation failed: %s — retrying in %.0fs",
                e,
                _load_backoff,
                exc_info=True,
            )
            stop_event.wait(_load_backoff)
            _load_backoff = min(_load_backoff * 2, 60.0)

    if backend is None:
        # stop_event was set while waiting on a retry — clean shutdown.
        return

    backend_key = _get_backend_key(current_config)
    _dispatch_loop = asyncio.new_event_loop()

    from alexa_custom.audio_hw import gst_profile_change_event

    try:
        while not stop_event.is_set():
            current_config = _get_config()

            # Re-resolve the capture source on every (re)start: after a device
            # unplug/replug — or a swap for a different speakerphone — the node
            # name can change, and capture must reattach to the new node. Keep
            # the previous name while the device is absent so the retry loop
            # reconnects as soon as it reappears.
            new_source, new_channels = resolve_capture_source(
                current_config.audio.input_device
            )
            if new_source is not None and new_source != source:
                logger.info("Capture source changed: %s -> %s", source, new_source)
                source, channels = new_source, new_channels
                if (
                    current_config.stt.mono_capture
                    or current_config.stt.capture_backend == "gstreamer"
                ):
                    channels = 1

            new_key = _get_backend_key(current_config)
            if new_key != backend_key:
                try:
                    t0 = time.monotonic()
                    backend = get_stt_backend(
                        current_config.stt, grammar=_loop_grammar(current_config)
                    )
                    backend_key = new_key
                    logger.info(
                        "STT backend reloaded (%.1fs) after config change",
                        time.monotonic() - t0,
                    )
                except Exception as e:
                    logger.error("STT backend reload failed: %s", e, exc_info=True)
                    stop_event.wait(2)
                    continue

            proc: subprocess.Popen | None = None
            try:
                proc = start_capture(source, channels, config=current_config)
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
                    capture_restart_event=gst_profile_change_event,
                )
            except Exception as e:
                logger.error("STT error: %s", e, exc_info=True)
                stop_event.wait(2)
            else:
                if not stop_event.is_set():
                    if gst_profile_change_event.is_set():
                        gst_profile_change_event.clear()
                        logger.info("GStreamer profile changed — restarting capture")
                    else:
                        logger.info("Capture ended unexpectedly — restarting in 2s")
                        stop_event.wait(2.0)
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "Capture process ignored SIGTERM — sending SIGKILL"
                        )
                        proc.kill()
                        try:
                            proc.wait(timeout=2)
                        except Exception:
                            pass
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
