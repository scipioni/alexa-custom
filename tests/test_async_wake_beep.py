"""Tests for the non-blocking wake/command beep (play_wake_beep_async)."""

import threading
import time
from unittest.mock import patch

from alexa_custom.audio_ops import _audio_lock, play_wake_beep_async


def _wait_lock_free(timeout: float = 2.0) -> bool:
    """Wait until _audio_lock is released by the background beep thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _audio_lock.acquire(blocking=False):
            _audio_lock.release()
            return True
        time.sleep(0.01)
    return False


def test_none_tone_starts_no_thread():
    """wake_tone: none must not spawn a thread nor touch the playback path."""
    with (
        patch("alexa_custom.audio_ops.play_tone") as mock_tone,
        patch("threading.Thread") as mock_thread,
    ):
        play_wake_beep_async("none")
        play_wake_beep_async("NONE")
        mock_tone.assert_not_called()
        mock_thread.assert_not_called()


def test_returns_before_playback_finishes():
    """The call must return immediately while playback runs in background."""
    started = threading.Event()
    release = threading.Event()

    def slow_tone(name):
        started.set()
        release.wait(timeout=5)

    with patch("alexa_custom.audio_ops.play_tone", side_effect=slow_tone):
        t0 = time.monotonic()
        play_wake_beep_async("wake")
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1, f"async beep blocked for {elapsed:.3f}s"
        assert started.wait(timeout=2), "background playback never started"
        release.set()
    assert _wait_lock_free(), "_audio_lock not released after tone finished"


def test_playback_goes_through_sync_path():
    """The background thread must run the regular play_wake_beep path (lock,
    echo gate and temp-file cleanup all live there)."""
    called = threading.Event()
    names = []

    def record_tone(name):
        names.append(name)
        called.set()

    with patch("alexa_custom.audio_ops.play_tone", side_effect=record_tone):
        play_wake_beep_async("success")
        assert called.wait(timeout=2)
        assert names == ["success"]
    assert _wait_lock_free(), "_audio_lock not released after tone finished"


def test_tts_queues_behind_beep():
    """The audio slot is reserved synchronously at call time: playback started
    right after the match (e.g. a Piper cache hit) must find _audio_lock held
    and queue behind the tone instead of pre-empting it."""
    started = threading.Event()
    release = threading.Event()

    def blocking_tone(name):
        started.set()
        release.wait(timeout=5)

    with patch("alexa_custom.audio_ops.play_tone", side_effect=blocking_tone):
        play_wake_beep_async("wake")
        # Immediately after the call — before the tone thread even runs — the
        # slot must already be reserved.
        assert not _audio_lock.acquire(blocking=False), (
            "_audio_lock free right after play_wake_beep_async — "
            "TTS could pre-empt the tone"
        )
        assert started.wait(timeout=2)
        release.set()
    assert _wait_lock_free(), "_audio_lock not released after tone finished"


def test_beep_skipped_when_audio_active():
    """If audio is already playing, the beep is skipped, not queued."""
    assert _audio_lock.acquire(blocking=False), "lock unexpectedly busy"
    try:
        with patch("alexa_custom.audio_ops.play_tone") as mock_tone:
            play_wake_beep_async("wake")
            time.sleep(0.05)
            mock_tone.assert_not_called()
    finally:
        _audio_lock.release()
