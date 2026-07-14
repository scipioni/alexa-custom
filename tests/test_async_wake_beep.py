"""Tests for the non-blocking wake/command beep (play_wake_beep_async)."""

import threading
import time
from unittest.mock import patch

from alexa_custom.audio_ops import play_wake_beep_async


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
