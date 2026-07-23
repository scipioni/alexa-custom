"""Fast endpoint for ask-reply windows.

Once the running partial already fully matches a complete reply phrase, the
capture window should end after ``fast_vad_ms`` of silence instead of waiting
out the full ``vad_silence_ms`` (or the whole timeout) — so a recognised
"sì"/"no" advances the ask immediately. Mirrors the wake loop's fast endpoint.
"""

import threading
from unittest.mock import MagicMock, patch

from alexa_custom.stt_capture import _capture_loop


class _FakeStdout:
    def fileno(self):
        return -1


class _FakeProc:
    def __init__(self):
        self.stdout = _FakeStdout()

    def poll(self):
        return None


def _run(fast_vad_ms: int, partial: str, phrases: list[str]) -> tuple[str, float]:
    """Drive _capture_loop with a controlled clock; return (result, elapsed_s).

    The clock advances 100 ms per captured chunk. The backend yields a fixed
    partial every chunk (sherpa-style: accept_waveform always False), so the
    partial changes once then stays put — last_activity freezes and the silence
    timer runs from the first chunk.
    """
    clock = [1000.0]

    def fake_read(*_a, **_k):
        clock[0] += 0.1  # 100 ms per chunk
        return b"\x10\x20" * 160  # non-empty audio frame

    backend = MagicMock()
    backend.accept_waveform.return_value = False
    backend.partial_text.return_value = partial
    backend.finalize.return_value = partial

    with (
        patch("alexa_custom.stt_capture.time.monotonic", lambda: clock[0]),
        patch("alexa_custom.stt_capture._read_with_timeout", side_effect=fake_read),
        patch("alexa_custom.stt_capture.is_playback_active", return_value=False),
        patch("alexa_custom.stt_capture._rms_level", return_value=0.1),
    ):
        start = clock[0]
        result = _capture_loop(
            _FakeProc(),
            channels=1,
            backend=backend,
            timeout=5.0,
            stop_event=threading.Event(),
            phrases=phrases,
            vad_silence_ms=900,
            fast_vad_ms=fast_vad_ms,
        )
    return result, clock[0] - start


class TestReplyFastEndpoint:
    def test_matching_partial_ends_after_fast_vad(self):
        # "sì" fully matches the closed reply set → end after ~fast_vad_ms.
        result, elapsed = _run(fast_vad_ms=200, partial="sì", phrases=["si", "no"])
        assert result == "sì"
        assert elapsed < 0.5  # well under the 900 ms full silence window

    def test_disabled_fast_vad_waits_full_silence_window(self):
        # fast_vad_ms=0 disables the fast path: same matching partial now waits
        # the full vad_silence_ms before the endpoint fires.
        result, elapsed = _run(fast_vad_ms=0, partial="sì", phrases=["si", "no"])
        assert result == "sì"
        assert elapsed >= 0.9

    def test_non_matching_partial_waits_full_silence_window(self):
        # A free-form partial that matches no reply phrase gets no fast path,
        # even with fast_vad_ms set — it waits the full window.
        result, elapsed = _run(
            fast_vad_ms=200, partial="forse più tardi", phrases=["si", "no"]
        )
        assert elapsed >= 0.9
