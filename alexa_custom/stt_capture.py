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

# RMS energy floor (0..1) for the reply/command window's speech gate — see
# SherpaOnnxSTT.set_rms_gate. Feeds the decoder on a real answer yet ignores
# silence/ambient noise. 0.03 chosen after the NewPie switched to the `normal`
# profile lifted capture ~10x (replies now peak 0.3-0.45): at 0.015 the louder
# ambient floor was fed continuously, producing spurious partials that deferred
# the silence endpoint (a matched reply ran the full 5s window). Env-overridable
# for quick field tuning without a code edit; no effect on the vosk backend.
_REPLY_RMS_GATE = float(os.environ.get("STT_REPLY_RMS_GATE", "0.03"))


def _make_listen_fn(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None,
    vad_silence_ms: int | None,
    confidence: float = 0.0,
    confidence_mode: str = "first",
    fast_vad_ms: int = 0,
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
            fast_vad_ms=fast_vad_ms,
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
    fast_vad_ms: int = 0,
) -> str:
    """Capture audio for a set duration and return the transcribed text.

    `timeout` is the window of allowed inactivity: it bounds both the wait for
    speech to start and — when `hard_timeout` is set — slides forward while
    speech continues, so the user is not cut off mid-sentence. `hard_timeout`
    is the absolute cap on the whole capture.

    `fast_vad_ms` (>0, closed `phrases` set only): once the partial transcript
    already fully matches a complete reply phrase, end after this much silence
    instead of the full `vad_silence_ms` — so a recognised "sì"/"no" advances
    the ask immediately instead of waiting out the window (mirrors the wake
    loop's fast endpoint).
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
    # Bounded reply/command window: swap Silero's neural gate for an RMS energy
    # gate (no-op for Vosk). Silero drops quiet-but-real answers here — e.g. "no"
    # thinned by the 220 Hz HPF, captured at mic_peak ~0.12 yet classified as
    # non-speech — so feed the decoder on energy instead for the window, and
    # restore Silero in the finally. reset() does not clear it, so it survives
    # the mid-window playback-drain resets.
    backend.set_rms_gate(_REPLY_RMS_GATE)
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
            fast_vad_ms=fast_vad_ms,
        )
    finally:
        backend.set_rms_gate(None)
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
    fast_vad_ms: int = 0,
) -> str:
    # Closed-reply fast endpoint: normalized phrase set the partial is matched
    # against so a recognised complete reply can end the window early. Empty for
    # free-text captures (fast path disabled). normalize_text folds accents and
    # punctuation ("sì"/". Sì" -> "si"), matching how replies are matched later.
    _norm_phrases: set[str] = set()
    _normalize = None
    if phrases and fast_vad_ms > 0:
        from alexa_custom.actions import normalize_text as _normalize

        _norm_phrases = {n for p in phrases if (n := _normalize(p))}

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

    # --- Reply-window diagnostics (see the "sì"/"no" ask-reply investigation) ---
    # A reply window emits no other journal lines, so without these we cannot tell
    # a VAD-gated / silent window ('?'/'.' finalize) apart from an answer spoken too
    # early (drained on the playback-gate drop) or a mis-transcription.
    _diag = logger.isEnabledFor(logging.DEBUG)
    _t_start = time.monotonic()
    _capture_begin = _t_start  # advances to the playback-gate drop, if any
    _speech_first: float | None = None
    _peak_rms = 0.0
    _mean_rms_sum = 0.0
    _rms_n = 0
    _ended_by = "timeout"
    # Response-timing diagnostics: how long playback held the gate (when the user
    # could first answer) and how much decodable energy landed in that answerable
    # window afterward. Distinguishes "answered during playback → nothing in-window"
    # (fed≈0) from "energy was there but the decoder dropped it" (fed large,
    # speech NEVER). Frames at/above the reply RMS gate are the ones fed to the
    # sherpa decoder — mirror that count here from the same per-frame RMS.
    _play_peak_rms = (
        0.0  # peak energy WHILE playback held the gate (echo + any barge-in)
    )
    _fed_frames = 0
    _first_fed: float | None = None
    _last_fed: float | None = None
    if _diag:
        logger.debug(
            "Reply window open: timeout=%.1fs start_after_playback=%s grammar=%s",
            timeout,
            start_after_playback,
            phrases if phrases else "(free)",
        )

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
            if _diag:
                # Energy captured while the gate is up (dropped, not decoded).
                # Dominated by TTS echo, but a spike well above the echo floor
                # here + an empty result is the "answered during playback" tell.
                _play_peak_rms = max(
                    _play_peak_rms, _rms_level(_downmix_to_mono(raw_data, channels))
                )
            continue

        if was_playing:
            drained = _drain_pipe(proc)
            backend.reset()
            was_playing = False
            if start_after_playback:
                deadline = time.monotonic() + timeout
                if hard_timeout is not None and hard_timeout > timeout:
                    hard_deadline = time.monotonic() + hard_timeout
            last_partial = ""
            last_activity = time.monotonic()
            got_speech = False
            _capture_begin = time.monotonic()
            # Playback re-armed mid-window (e.g. clause-split TTS): the capture
            # window restarts here, so reset the per-window diagnostic trackers
            # too. Without this, first_fed/speech carry stale pre-arm times and
            # render negative against the new _capture_begin. _play_peak_rms is
            # intentionally kept (it accumulates across all playback periods).
            _speech_first = None
            _peak_rms = 0.0
            _mean_rms_sum = 0.0
            _rms_n = 0
            _fed_frames = 0
            _first_fed = None
            _last_fed = None
            if _diag:
                # An answer spoken during/right-at TTS end lands in `drained` and
                # is lost — a large drain here alongside an empty finalize is the
                # signature of "answered too early".
                logger.debug(
                    "Reply capture armed after playback (drained %d B ~%.0fms)",
                    drained,
                    drained / (16000 * channels * 2) * 1000,
                )
            continue

        data = _apply_input_gain(_downmix_to_mono(raw_data, channels))

        _rms = _rms_level(data)
        if _diag:
            _peak_rms = max(_peak_rms, _rms)
            _mean_rms_sum += _rms
            _rms_n += 1
            if _rms >= _REPLY_RMS_GATE:
                _now = time.monotonic()
                _fed_frames += 1
                if _first_fed is None:
                    _first_fed = _now
                _last_fed = _now
        if on_stt_event:
            on_stt_event("level", {"mic": _rms})

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

        if got_speech and _speech_first is None:
            _speech_first = time.monotonic()
            if _diag:
                logger.debug(
                    "Reply speech detected %.0fms into capture (partial=%r)",
                    (_speech_first - _capture_begin) * 1000,
                    last_partial or (transcript_parts[-1] if transcript_parts else ""),
                )

        if got_speech and hard_deadline is not None:
            deadline = min(hard_deadline, max(deadline, last_activity + timeout))

        _effective_vad_ms = (
            vad_silence_ms if vad_silence_ms is not None else _VAD_SILENCE_MS
        )
        # Fast endpoint: when the running transcript already fully matches a
        # complete reply phrase, don't wait out the full silence window — a
        # recognised "sì"/"no" should advance the ask right away. Kept as a
        # short silence (fast_vad_ms) rather than an instant return so a prefix
        # like "no" can still grow into "no grazie" before committing.
        if _norm_phrases and _normalize is not None and got_speech:
            _cur = " ".join(transcript_parts + ([last_partial] if last_partial else []))
            if _normalize(_cur) in _norm_phrases:
                _effective_vad_ms = min(_effective_vad_ms, fast_vad_ms)
        if (
            got_speech
            and (time.monotonic() - last_activity) * 1000 >= _effective_vad_ms
        ):
            _ended_by = "endpoint"
            break

    if stop_event.is_set():
        _ended_by = "stop"

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

    result = " ".join(transcript_parts).strip()
    if _diag:
        _mean_rms = _mean_rms_sum / _rms_n if _rms_n else 0.0
        _speech_at = (
            f"{(_speech_first - _capture_begin) * 1000:.0f}ms"
            if _speech_first is not None
            else "NEVER"
        )
        _armed_after = (_capture_begin - _t_start) * 1000  # playback-gate hold
        _first_fed_at = (
            f"{(_first_fed - _capture_begin) * 1000:.0f}ms"
            if _first_fed is not None
            else "-"
        )
        _last_fed_at = (
            f"{(_last_fed - _capture_begin) * 1000:.0f}ms"
            if _last_fed is not None
            else "-"
        )
        # Interpreting a failed ("" / punctuation raw) window:
        #  fed≈0            → no decodable energy after the gate opened → the
        #                     answer landed during playback (barge-in) or wasn't
        #                     spoken. Cross-check play_peak: a spike there means
        #                     you answered while the question was still playing.
        #  fed large + speech NEVER → real energy reached the decoder but it
        #                     produced nothing → decode/segmentation issue.
        #  armed_after      → ms the playback gate held before answering was
        #                     possible; anything said before this was discarded.
        logger.debug(
            "Reply window done: ended=%s elapsed=%.1fs armed_after=%.0fms "
            "speech@%s fed=%d first_fed@%s last_fed@%s "
            "mic_peak=%.3f mic_mean=%.3f play_peak=%.3f raw=%r result=%r",
            _ended_by,
            time.monotonic() - _capture_begin,
            _armed_after,
            _speech_at,
            _fed_frames,
            _first_fed_at,
            _last_fed_at,
            _peak_rms,
            _mean_rms,
            _play_peak_rms,
            final_text,
            result,
        )
    return result


def _play_timeout() -> None:
    logger.info("Command window timeout or no match")
    try:
        play_timeout_beep()
    except Exception as e:
        logger.debug(f"Timeout beep failed: {e}")
