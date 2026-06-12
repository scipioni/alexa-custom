from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import numpy as np

from alexa_custom import audio_hw
from alexa_custom.audio_hw import (
    get_output_volume,
    get_post_playback_ms,
    get_tone_preroll_ms,
    save_volume_config,
)

logger = logging.getLogger(__name__)

# Resolved once at import time; None if the tool is absent (aplay fallback used).
_PW_PLAY: str | None = shutil.which("pw-play")

# Global flag to signal that playback is active and STT should ignore input
_playback_active = threading.Event()

# Serializes all internal playback so they don't overlap.
_audio_lock = threading.Lock()

# Current RMS level of local audio output (0.0–1.0)
_playback_level: float = 0.0


def get_playback_level() -> float:
    return _playback_level


def set_playback_level(level: float) -> None:
    global _playback_level
    _playback_level = level


def set_stt_gated_flag(flag: threading.Event):
    """Link an external event (like the STT gating flag) to our playback state."""
    global _playback_active
    _playback_active = flag


def is_playback_active() -> bool:
    """Check if any internal audio playback is currently in progress."""
    return _playback_active.is_set()


def _play_array(audio: np.ndarray, samplerate: int) -> None:
    """Play a float32 numpy array via pw-play (PipeWire) or aplay (ALSA fallback)."""
    import tempfile
    import wave as _wave

    channels = audio.shape[1] if audio.ndim > 1 else 1
    frames = audio.shape[0]
    duration_s = frames / samplerate
    # Headroom over the real duration; no upper cap (a 30 s cap would truncate
    # long TTS mid-playback).
    play_timeout = max(duration_s + 10, 8)

    volume = get_output_volume()
    pcm16 = np.clip(np.ascontiguousarray(audio) * volume * 32767, -32768, 32767).astype(
        np.int16
    )
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(tmp_fd)
        with _wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(pcm16.tobytes())

        cmd = (
            [_PW_PLAY, tmp_path]
            if _PW_PLAY
            else ["aplay", "-D", "pipewire", "-q", tmp_path]
        )

        with _audio_lock:
            _playback_active.set()
            try:
                result = subprocess.run(
                    cmd, timeout=play_timeout, check=False, capture_output=True
                )
                if result.returncode != 0:
                    logger.error(
                        f"_play_array: {cmd[0]} exited {result.returncode}: {result.stderr.decode(errors='replace').strip()}"
                    )
                post_playback_ms = get_post_playback_ms()
                if post_playback_ms > 0:
                    time.sleep(post_playback_ms / 1000.0)
            except Exception as e:
                logger.error(f"_play_array failed: {e}")
            finally:
                _playback_active.clear()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _play_raw(data: bytes, samplerate: int, channels: int) -> None:
    """Play raw float32 audio via pw-play (native PipeWire) or aplay (ALSA fallback)."""
    import tempfile
    import wave as _wave

    frames = len(data) // (channels * 4)
    duration_s = frames / samplerate
    # Headroom over the real duration; no upper cap (see _play_array).
    play_timeout = max(duration_s + 10, 8)

    volume = get_output_volume()
    samples = np.frombuffer(data, dtype=np.float32)
    pcm16 = np.clip(samples * volume * 32767, -32768, 32767).astype(np.int16)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(tmp_fd)
        with _wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(pcm16.tobytes())

        cmd = (
            [_PW_PLAY, tmp_path]
            if _PW_PLAY
            else ["aplay", "-D", "pipewire", "-q", tmp_path]
        )

        with _audio_lock:
            _playback_active.set()
            try:
                subprocess.run(
                    cmd, timeout=play_timeout, check=False, stderr=subprocess.DEVNULL
                )
                post_playback_ms = get_post_playback_ms()
                if post_playback_ms > 0:
                    time.sleep(post_playback_ms / 1000.0)
            except Exception as e:
                logger.error(f"_play_raw failed: {e}")
            finally:
                _playback_active.clear()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def play_wav_file(file_path: str) -> None:
    """Play a WAV file via pw-play (native PipeWire) or aplay (ALSA fallback).

    Output volume (``get_output_volume()``) is applied via pw-play's
    ``--volume`` flag — the single source of output-volume control. The aplay
    fallback has no volume control and plays at unity.
    """
    volume = get_output_volume()

    # Derive a duration-based timeout from the WAV header so long clips are not
    # truncated and a stalled player does not hang forever.
    play_timeout = 60.0
    try:
        import wave as _wave

        with _wave.open(file_path, "rb") as wf:
            rate = wf.getframerate()
            if rate:
                play_timeout = max(wf.getnframes() / rate + 10, 8)
    except Exception:
        pass

    if _PW_PLAY:
        cmd = [_PW_PLAY, "--volume", f"{volume:.3f}", file_path]
    else:
        cmd = ["aplay", "-D", "pipewire", "-q", file_path]

    with _audio_lock:
        _playback_active.set()
        try:
            subprocess.run(
                cmd, timeout=play_timeout, check=False, stderr=subprocess.DEVNULL
            )
            post_playback_ms = get_post_playback_ms()
            if post_playback_ms > 0:
                time.sleep(post_playback_ms / 1000.0)
        except Exception:
            pass
        finally:
            _playback_active.clear()


def record_wav_file(file_path: str, duration: float) -> None:
    """Record a WAV file from the default PipeWire source."""
    rate = 16000
    channels = 1
    parec = shutil.which("parec")
    if parec:
        import threading
        import wave

        cmd = [
            parec,
            "--rate",
            str(rate),
            "--channels",
            str(channels),
            "--format",
            "s16le",
            "--latency-msec=50",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def kill_after():
            time.sleep(duration)
            proc.terminate()

        threading.Thread(target=kill_after, daemon=True).start()
        pcm_data = proc.stdout.read()
        proc.wait()

        if not pcm_data:
            logger.error("Recording produced no audio (parec died immediately?)")
            return
        # A mid-frame SIGTERM can leave a trailing odd byte; trim to whole s16 samples.
        pcm_data = pcm_data[: len(pcm_data) // 2 * 2]

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)
        return

    pw_record = shutil.which("pw-record")
    if not pw_record:
        logger.error("No recording tool found (parec or pw-record)")
        return
    cmd = [
        pw_record,
        "--rate",
        str(rate),
        "--channels",
        str(channels),
        "--format",
        "s16",
        file_path,
    ]

    # pw-record runs until interrupted — it never exits on its own, so
    # subprocess.run(timeout=...) would always time out and SIGKILL it before
    # the WAV header is finalized (data chunk size left at 0). Use Popen + a
    # timed terminate() so it can close the file cleanly.
    proc = subprocess.Popen(cmd)
    try:
        time.sleep(duration)
        proc.terminate()  # SIGTERM lets pw-record write the final header
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    except Exception as e:
        logger.error(f"Recording failed: {e}")
        proc.kill()


def play_tone(name: str):
    """Play a predefined tone by name (startup, success, error, info, warning)."""
    samplerate = 48000
    channels = 2

    def _generate_note(
        freq: float, duration: float, volume: float = 0.60
    ) -> np.ndarray:
        n = int(samplerate * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
        wave += 0.3 * np.sin(2 * np.pi * freq * 2 * t).astype(np.float32)
        wave += 0.1 * np.sin(2 * np.pi * freq * 3 * t).astype(np.float32)
        wave /= np.max(np.abs(wave))
        fade_samples = int(samplerate * 0.02)
        envelope = np.ones(n, dtype=np.float32)
        if n > 2 * fade_samples:
            envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
            envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
        mono = wave * envelope * volume
        return np.column_stack([mono, mono])

    def _gap(duration: float) -> np.ndarray:
        return np.zeros((int(samplerate * duration), channels), dtype=np.float32)

    tones = {
        "startup": lambda: np.concatenate(
            [
                _gap(1.0),
                _generate_note(523.25, 0.14),  # C5
                _gap(0.03),
                _generate_note(659.25, 0.14),  # E5
                _gap(0.03),
                _generate_note(783.99, 0.14),  # G5
            ]
        ),
        "wake": lambda: np.concatenate(
            [
                _gap(0.5),
                _generate_note(440.00, 0.10, volume=0.6),  # A4
                _gap(0.02),
                _generate_note(554.37, 0.15, volume=0.6),  # C#5
            ]
        ),
        "success": lambda: np.concatenate(
            [
                _gap(0.5),
                _generate_note(783.99, 0.10),  # G5
                _gap(0.05),
                _generate_note(1046.50, 0.20),  # C6
            ]
        ),
        "error": lambda: np.concatenate(
            [
                _gap(0.5),
                _generate_note(261.63, 0.15, volume=0.6),  # C4
                _gap(0.05),
                _generate_note(233.08, 0.30, volume=0.6),  # Bb3 (dissonant)
            ]
        ),
        "info": lambda: np.concatenate([_gap(0.5), _generate_note(880.00, 0.15)]),  # A5
        "warning": lambda: np.concatenate(
            [
                _gap(0.5),
                _generate_note(1318.51, 0.10),  # E6
                _gap(0.05),
                _generate_note(1046.50, 0.10),  # C6
            ]
        ),
    }

    if name not in tones:
        logger.warning(f"Unknown tone name: {name}")
        return

    try:
        audio = tones[name]()
        tone_preroll_ms = get_tone_preroll_ms()
        if tone_preroll_ms > 0:
            preroll = np.zeros(
                (int(samplerate * tone_preroll_ms / 1000), channels), dtype=np.float32
            )
            audio = np.concatenate([preroll, audio])
        _play_array(audio, samplerate)
    except Exception as e:
        logger.error(f"play_tone({name}) failed: {e}")


def play_beep(frequency_hz: float, duration_ms: int) -> None:
    """Play a pure-tone beep through the PipeWire default sink via aplay or pw-play."""
    samplerate = 48000
    channels = 2
    n = int(samplerate * duration_ms / 1000)
    fade = min(int(samplerate * 0.01), n // 4)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = np.sin(2 * np.pi * frequency_hz * t).astype(np.float32) * 0.6
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    mono = wave * envelope
    audio = np.column_stack([mono, mono])
    tone_preroll_ms = get_tone_preroll_ms()
    if tone_preroll_ms > 0:
        preroll = np.zeros(
            (int(samplerate * tone_preroll_ms / 1000), channels), dtype=np.float32
        )
        audio = np.concatenate([preroll, audio])
    _play_array(audio, samplerate)


def play_wake_beep(name: str = "wake") -> None:
    if name.lower() == "none":
        return
    play_tone(name)


def play_timeout_beep() -> None:
    play_beep(400, 150)


def play_call_start() -> None:
    """Two rising tones — call connected."""
    play_beep(600, 120)
    play_beep(900, 180)


def play_call_end() -> None:
    """Two falling tones — call ended."""
    play_beep(900, 120)
    play_beep(600, 180)


def set_output_volume_direct(volume: float) -> None:
    """Set digital output volume without touching system mixer.

    Volume is applied as digital scaling in software (TTS, beeps, WAV playback).
    The system PipeWire volume is left at 100% to avoid double attenuation.
    """
    volume = max(0.0, min(1.0, volume))
    audio_hw.set_output_volume(None, None, volume)
    audio_hw._restore_hw_pcm()
    save_volume_config(volume)
