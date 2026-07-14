"""Tests for stalled-but-alive capture detection in _iter_gated_audio
(harden-serena-runtime task 5.1)."""

import threading
from unittest.mock import patch

from alexa_custom.stt_gating import _iter_gated_audio


class _FakeProc:
    """Duck-typed Popen: stdout has a fileno(), poll() always returns None
    (process alive), and no bytes ever arrive."""

    def __init__(self):
        self.stdout = _FakeStdout()

    def poll(self):
        return None


class _FakeStdout:
    def fileno(self):
        return -1  # never actually read; _read_with_timeout is patched


class TestCaptureStallDetection:
    def test_alive_but_silent_capture_returns_after_threshold(self):
        """A capture process that never delivers bytes, but stays alive,
        must be treated as stalled and the iterator must return (triggering
        the existing restart-capture path) once capture_stall_secs elapses."""
        proc = _FakeProc()
        stop_event = threading.Event()

        # Simulate monotonic clock advancing well past the stall threshold
        # on every _read_with_timeout call, without a real 30s test sleep.
        fake_time = [0.0]

        def _advancing_monotonic():
            fake_time[0] += 5.0
            return fake_time[0]

        with (
            patch("alexa_custom.stt_gating._read_with_timeout", return_value=b""),
            patch(
                "alexa_custom.stt_gating.time.monotonic",
                side_effect=_advancing_monotonic,
            ),
        ):
            results = list(
                _iter_gated_audio(
                    proc,
                    channels=1,
                    stop_event=stop_event,
                    capture_stall_secs=30.0,
                )
            )

        # The iterator must have returned (not run forever) with no data yielded.
        assert results == []

    def test_silence_within_threshold_does_not_stall(self):
        """Zero-filled/no-data reads that stay under the threshold must not
        trigger a stall — only genuinely wedged captures should restart."""
        proc = _FakeProc()
        stop_event = threading.Event()
        call_count = [0]

        def _read_with_timeout_stub(*_args, **_kwargs):
            call_count[0] += 1
            if call_count[0] >= 3:
                stop_event.set()
            return b""

        fake_time = [0.0]

        def _slow_monotonic():
            fake_time[0] += 1.0  # well under a 30s threshold after 3 calls
            return fake_time[0]

        with (
            patch(
                "alexa_custom.stt_gating._read_with_timeout",
                side_effect=_read_with_timeout_stub,
            ),
            patch(
                "alexa_custom.stt_gating.time.monotonic",
                side_effect=_slow_monotonic,
            ),
        ):
            results = list(
                _iter_gated_audio(
                    proc,
                    channels=1,
                    stop_event=stop_event,
                    capture_stall_secs=30.0,
                )
            )

        # Loop exited because stop_event was set, not because of a stall.
        assert results == []
        assert call_count[0] == 3

    def test_zero_disables_stall_detection(self):
        """capture_stall_secs=0 must disable the stall check entirely."""
        proc = _FakeProc()
        stop_event = threading.Event()
        call_count = [0]

        def _read_with_timeout_stub(*_args, **_kwargs):
            call_count[0] += 1
            if call_count[0] >= 5:
                stop_event.set()
            return b""

        fake_time = [0.0]

        def _fast_monotonic():
            fake_time[0] += 100.0  # would trip a nonzero threshold immediately
            return fake_time[0]

        with (
            patch(
                "alexa_custom.stt_gating._read_with_timeout",
                side_effect=_read_with_timeout_stub,
            ),
            patch(
                "alexa_custom.stt_gating.time.monotonic",
                side_effect=_fast_monotonic,
            ),
        ):
            results = list(
                _iter_gated_audio(
                    proc,
                    channels=1,
                    stop_event=stop_event,
                    capture_stall_secs=0,
                )
            )

        assert results == []
        assert call_count[0] == 5
