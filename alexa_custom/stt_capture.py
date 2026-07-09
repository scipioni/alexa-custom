"""Command-utterance capture for the STT pipeline.

Separated from the wake-word orchestration in stt.py: once a wake word fires,
these helpers capture the following command utterance (with VAD-based
end-of-speech detection, playback gating, and optional grammar restriction) and
return the transcript. stt.py imports and re-exports them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from typing import Callable

from alexa_custom.audio import is_playback_active, play_timeout_beep
from alexa_custom.stt_backends import STTBackend, VoskSTT, _phrases_to_grammar
from alexa_custom.stt_gating import (
    _CHUNK,
    _apply_input_gain,
    _downmix_to_mono,
    _drain_pipe,
    _read_with_timeout,
    _rms_level,
)

logger = logging.getLogger(__name__)

# Idle ms after last speech before the command window closes (overridable per call).
_VAD_SILENCE_MS = int(os.environ.get("STT_VAD_SILENCE_MS", "500"))


def _make_listen_fn(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None,
    vad_silence_ms: int | None,
    confidence: float = 0.0,
    confidence_mode: str = "first",
) -> Callable:
    """Return an async listen function closed over the given capture context."""

    async def _listen_fn(
        timeout: float,
        flush_ms: int = 0,
        phrases: list[str] | None = None,
        start_after_playback: bool = False,
    ) -> str:
        if on_stt_event:
            on_stt_event(
                "wake",
                {"word": "(reply)", "timeout": timeout, "phrases": phrases or []},
            )
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
            confidence=confidence,
            confidence_mode=confidence_mode,
        )

    return _listen_fn


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
    hard_timeout: float | None = None,
    confidence: float = 0.0,
    confidence_mode: str = "first",
) -> str:
    """Capture audio for a set duration and return the transcribed text.

    `timeout` is the window of allowed inactivity: it bounds both the wait for
    speech to start and — when `hard_timeout` is set — slides forward while
    speech continues, so the user is not cut off mid-sentence. `hard_timeout`
    is the absolute cap on the whole capture.
    """
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
    try:
        return _capture_loop(
            proc,
            channels,
            backend,
            timeout,
            stop_event,
            on_stt_event,
            phrases=phrases,
            start_after_playback=start_after_playback,
            vad_silence_ms=vad_silence_ms,
            hard_timeout=hard_timeout,
            confidence=confidence,
            confidence_mode=confidence_mode,
        )
    finally:
        if grammar is not None and isinstance(backend, VoskSTT):
            # Restore the recognizer's base grammar (free-text None, or the
            # always-on wake/command grammar) — not unconditionally free-text.
            backend.restore_base()


def _capture_loop(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    timeout: float,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    phrases: list[str] | None = None,
    start_after_playback: bool = False,
    vad_silence_ms: int | None = None,
    hard_timeout: float | None = None,
    confidence: float = 0.0,
    confidence_mode: str = "first",
) -> str:
    deadline = time.monotonic() + timeout
    hard_deadline = (
        time.monotonic() + hard_timeout
        if hard_timeout is not None and hard_timeout > timeout
        else None
    )
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
                if hard_timeout is not None and hard_timeout > timeout:
                    hard_deadline = time.monotonic() + hard_timeout
            last_partial = ""
            last_activity = time.monotonic()
            got_speech = False
            continue

        data = _apply_input_gain(_downmix_to_mono(raw_data, channels))

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if backend.accept_waveform(data):
            text = backend.text()
            _conf = (
                backend.last_confidence(confidence_mode)
                if confidence > 0.0 and isinstance(backend, VoskSTT)
                else None
            )
            backend.reset()
            if text:
                # Grammar capture snaps noise onto an on_reply phrase; drop
                # low-confidence snaps and keep listening within the window.
                if _conf is not None and _conf < confidence:
                    logger.debug(
                        "Capture confidence gate rejected %r (conf=%.2f < %.2f)",
                        text,
                        _conf,
                        confidence,
                    )
                    last_partial = ""
                    continue

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

        if got_speech and hard_deadline is not None:
            deadline = min(hard_deadline, max(deadline, last_activity + timeout))

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
        _final_conf = (
            backend.last_confidence(confidence_mode)
            if confidence > 0.0 and isinstance(backend, VoskSTT)
            else None
        )
        if _final_conf is not None and _final_conf < confidence:
            logger.debug(
                "Capture finalize() confidence gate rejected %r (conf=%.2f < %.2f)",
                final_text,
                _final_conf,
                confidence,
            )
        else:
            transcript_parts.append(final_text)

    return " ".join(transcript_parts).strip()


def _play_timeout() -> None:
    logger.info("Command window timeout or no match")
    try:
        play_timeout_beep()
    except Exception as e:
        logger.debug(f"Timeout beep failed: {e}")
