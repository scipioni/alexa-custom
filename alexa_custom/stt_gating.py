from __future__ import annotations

import fcntl
import logging
import os
import select
import subprocess
import threading
import time
import numpy as np
from typing import Iterator, Callable

from alexa_custom.audio import is_playback_active
from alexa_custom.audio_hw import get_software_input_gain

logger = logging.getLogger(__name__)

_CHUNK = 4096


def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    n = len(samples)
    if n == 0:
        return 0.0
    return float(np.linalg.norm(samples)) / (32768.0 * n**0.5)


def _read_with_timeout(stdout, nbytes: int, timeout: float) -> bytes:
    """Best-effort read of up to ``nbytes`` from ``stdout`` within ``timeout`` seconds.

    Returns b'' if nothing arrived in the window. Prevents the recognizer thread
    from hanging forever when parec stalls (USB unplug, sink reset, etc.).
    """
    if stdout is None:
        return b""
    fd = stdout.fileno()
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    try:
        return os.read(fd, nbytes)
    except OSError:
        return b""


def _drain_pipe(proc: subprocess.Popen, max_bytes: int = 1 << 20) -> int:
    """Non-blocking: discard any audio already buffered in the capture pipe.

    Used to wipe acoustic echo / stale frames accumulated while playback was
    holding STT gated, before we hand fresh audio to the recognizer.
    """
    if proc.stdout is None:
        return 0
    fd = proc.stdout.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    drained = 0
    try:
        while drained < max_bytes:
            try:
                chunk = os.read(fd, 8192)
            except BlockingIOError:
                break
            if not chunk:
                break
            drained += len(chunk)
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
    return drained


def _apply_input_gain(data: bytes) -> bytes:
    """Scale s16le PCM bytes by the configured input gain (no-op when gain == 1.0)."""
    gain = get_software_input_gain()
    if abs(gain - 1.0) < 1e-6:
        return data
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return np.clip(arr * gain, -32768, 32767).astype(np.int16).tobytes()


def _downmix_to_mono(data: bytes, channels: int) -> bytes:
    """Take the loudest signal across all channels to ensure mono-downmix is high-gain."""
    if channels <= 1:
        return data
    frame_bytes = channels * 2  # s16le: 2 bytes per sample
    data = data[: len(data) // frame_bytes * frame_bytes]  # align to frame boundary
    if not data:
        return b""
    samples = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)
    # Use max absolute value across channels to avoid diluting the signal with empty jacks.
    idx = np.argmax(np.abs(samples), axis=1)
    mono = samples[np.arange(len(samples)), idx]
    return mono.tobytes()


def resolve_capture_source(input_spec: str | None = None) -> tuple[str | None, int]:
    """Map audio.input_device value to a PipeWire source name and channel count via pactl.

    An input_spec of 'auto' matches the first USB audio source (PipeWire names
    them alsa_input.usb-*), regardless of vendor.
    """
    if input_spec is None:
        input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    channels = 1
    if not input_spec:
        return None, channels
    auto = input_spec.strip().lower() == "auto"
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, timeout=5
        )
        needle = input_spec.lower()
        source_name = None
        found = False
        for line in out.splitlines():
            if "Name: " in line:
                name = line.split(": ", 1)[1].strip()
                matches = (
                    name.startswith("alsa_input.usb-")
                    if auto
                    else needle in name.lower()
                )
                if matches and "monitor" not in name.lower():
                    source_name = name
                    found = True
                elif found:
                    # Moved past the matched source block without finding spec — return now.
                    return source_name, channels
            if found and "Sample Specification:" in line:
                # e.g. "s16le 2ch 48000Hz"
                for part in line.split():
                    if part.endswith("ch"):
                        try:
                            channels = int(part[:-2])
                        except ValueError:
                            pass
                return source_name, channels

        logger.warning(f"No PipeWire source matching {input_spec!r} — using default")
    except Exception as e:
        logger.warning(f"resolve_capture_source failed: {e} — using default")
    return None, channels


def _start_capture_parec(source: str | None, channels: int = 1) -> subprocess.Popen:
    """Start a low-latency parec recording process."""
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
        if source:
            cmd.append(f"--target={source}")
    else:
        # Crucial: very low latency helps 'parec' start flowing on PipeWire
        cmd.append("--latency-msec=1")
        if source:
            cmd.append(f"--device={source}")

    # bufsize=0 keeps proc.stdout as raw FileIO so os.read (used by _drain_pipe
    # and _read_with_timeout) and the wake-loop's proc.stdout.read() see the
    # same byte stream — no Python-side BufferedReader holding stale frames.
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )


def start_capture(
    source: str | None, channels: int = 1, config=None
) -> subprocess.Popen:
    """Start audio capture — parec (default) or GStreamer pipeline.

    Pass config (ActionsConfig) to allow the gstreamer backend to be selected
    via config.stt.capture_backend == 'gstreamer'.  When using GStreamer the
    active named profile (persisted in state.yaml) is resolved and merged with
    the base GStreamerCaptureConfig before the pipeline is built.
    """
    if (
        config is not None
        and getattr(config.stt, "capture_backend", "parec") == "gstreamer"
    ):
        import dataclasses

        from alexa_custom.stt_gst_capture import start_capture_gst
        from alexa_custom.config import resolve_gst_profile
        from alexa_custom.audio_hw import (
            get_active_gst_profile,
            load_gstreamer_overrides,
        )

        profile = get_active_gst_profile()
        gst_cfg = resolve_gst_profile(config.audio.gstreamer, profile)
        # Calibration results (state.yaml gstreamer_override) take precedence
        # over the named profile: profiles set device-critical defaults, the
        # calibration sweep refines the NS/AGC keys on top of them. Skipped
        # while the temporary "calibration" profile is active — each probe
        # must control its own params, not inherit the previous winner's.
        if profile != "calibration":
            overrides = load_gstreamer_overrides() or {}
            valid = {
                f.name for f in dataclasses.fields(gst_cfg) if f.name != "profiles"
            }
            applied = {k: v for k, v in overrides.items() if k in valid}
            if applied:
                gst_cfg = dataclasses.replace(gst_cfg, **applied)
        return start_capture_gst(source, gst_cfg)
    return _start_capture_parec(source, channels)


def _iter_gated_audio(
    proc: subprocess.Popen,
    channels: int,
    stop_event: threading.Event,
    on_playback_end: Callable[[], None] | None = None,
    name: str = "stt",
    post_playback_ms: float = 100.0,
    dispatch_ended_at: list[float] | None = None,
    restart_event: threading.Event | None = None,
    capture_stall_secs: float = 30.0,
) -> Iterator[bytes | None]:
    """Yield downmixed mono chunks; yield None once per playback-end drain.

    Handles parec-exit (returns), read stalls, and playback-gate filtering.
    After TTS ends, drains the pipe backlog, calls on_playback_end to reset
    backend state, and yields None so the caller can issue a continue.

    dispatch_ended_at: single-element list[float] shared with the recognition
    loop. After a synchronous dispatch (_wake_detected), the loop sets
    dispatch_ended_at[0] = time.monotonic() so the hold-off fires even when
    the iterator was blocked during playback and never saw was_playing=True.
    """
    was_playing = False
    _stall_logged = False
    playback_ended_at = 0.0
    post_playback_s = post_playback_ms / 1000.0
    # Name the actual capture backend so a stall/exit log points at the right
    # subsystem (GStreamerCapture is a duck-typed Popen; parec/pw-record are
    # real subprocesses). Avoids the "parec stall?" message when running gst.
    _type_name = type(proc).__name__
    backend_label = (
        "gstreamer"
        if _type_name == "GStreamerCapture"
        else "gst-launch"
        if _type_name == "GstLaunchCapture"
        else "playback"
        if _type_name in ("_RealTimePopen", "_WavFilePopen")
        else "parec"
    )
    # Stamp when the first PCM buffer actually reaches the recognizer, so a
    # capture that reaches PLAYING but never emits audio is unambiguous in the
    # log (vs one that simply has a slow cold start).
    _capture_started_at = time.monotonic()
    _first_buffer_logged = False
    _last_data_at = time.monotonic()
    assert proc.stdout is not None
    while not stop_event.is_set():
        if restart_event is not None and restart_event.is_set():
            logger.info("restart_event set — stopping capture for profile reload")
            return
        raw_data = _read_with_timeout(proc.stdout, _CHUNK * channels, 2.0)
        if raw_data and not _first_buffer_logged:
            logger.info(
                "%s: first %s audio buffer (%d bytes) after %.0f ms",
                name,
                backend_label,
                len(raw_data),
                (time.monotonic() - _capture_started_at) * 1000.0,
            )
            _first_buffer_logged = True
        if not raw_data:
            if proc.poll() is not None:
                logger.warning(
                    "%s: %s capture process exited — restarting capture",
                    name,
                    backend_label,
                )
                return
            if not _stall_logged:
                logger.debug(
                    "%s: read timeout (%s stall?) — no audio for 2s, waiting",
                    name,
                    backend_label,
                )
                _stall_logged = True
            if (
                capture_stall_secs > 0
                and time.monotonic() - _last_data_at > capture_stall_secs
            ):
                logger.error(
                    "%s: %s capture alive but silent for %.0fs — restarting capture",
                    name,
                    backend_label,
                    capture_stall_secs,
                )
                return
            continue
        _stall_logged = False
        _last_data_at = time.monotonic()

        if is_playback_active():
            was_playing = True
            continue

        if was_playing:
            logger.debug("%s: playback ended — draining pipe and resetting", name)
            _drain_pipe(proc)
            was_playing = False
            playback_ended_at = time.monotonic()
            if on_playback_end is not None:
                on_playback_end()
            yield None
            continue

        _external_ended = dispatch_ended_at[0] if dispatch_ended_at else 0.0
        if time.monotonic() - max(playback_ended_at, _external_ended) < post_playback_s:
            continue

        yield _apply_input_gain(_downmix_to_mono(raw_data, channels))
