"""Tests for the confidence gate on capture_transcript's finalize() tail
(harden-serena-runtime task 6.3).

Mid-loop AcceptWaveform results were already confidence-gated, but the
finalize() flush at window expiry appended text unconditionally — letting a
noise snap that never produced an accepted final bypass the gate."""

import threading
from unittest.mock import MagicMock, patch

from alexa_custom.stt_backends import VoskSTT
from alexa_custom.stt_capture import _capture_loop


class _FakeStdout:
    def fileno(self):
        return -1


class _FakeProc:
    def __init__(self):
        self.stdout = _FakeStdout()

    def poll(self):
        return None


def _make_backend(final_text: str, confidence: float):
    backend = MagicMock(spec=VoskSTT)
    backend.accept_waveform.return_value = False
    backend.partial_text.return_value = ""
    backend.finalize.return_value = final_text
    backend.last_confidence.return_value = confidence
    return backend


class TestFinalizeConfidenceGate:
    def test_low_confidence_finalize_text_is_dropped(self):
        backend = _make_backend("rumore", confidence=0.2)
        with (
            patch("alexa_custom.stt_capture._read_with_timeout", return_value=b""),
            patch("alexa_custom.stt_capture.is_playback_active", return_value=False),
        ):
            result = _capture_loop(
                _FakeProc(),
                channels=1,
                backend=backend,
                timeout=0.01,
                stop_event=threading.Event(),
                confidence=0.6,
                confidence_mode="first",
            )
        assert result == ""

    def test_high_confidence_finalize_text_is_kept(self):
        backend = _make_backend("accendi luce", confidence=0.9)
        with (
            patch("alexa_custom.stt_capture._read_with_timeout", return_value=b""),
            patch("alexa_custom.stt_capture.is_playback_active", return_value=False),
        ):
            result = _capture_loop(
                _FakeProc(),
                channels=1,
                backend=backend,
                timeout=0.01,
                stop_event=threading.Event(),
                confidence=0.6,
                confidence_mode="first",
            )
        assert result == "accendi luce"

    def test_confidence_disabled_keeps_finalize_text_unconditionally(self):
        backend = _make_backend("qualunque cosa", confidence=0.0)
        with (
            patch("alexa_custom.stt_capture._read_with_timeout", return_value=b""),
            patch("alexa_custom.stt_capture.is_playback_active", return_value=False),
        ):
            result = _capture_loop(
                _FakeProc(),
                channels=1,
                backend=backend,
                timeout=0.01,
                stop_event=threading.Event(),
                confidence=0.0,
            )
        assert result == "qualunque cosa"
