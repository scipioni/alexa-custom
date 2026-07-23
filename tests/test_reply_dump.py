"""Reply-audio dump: when dump_dir is set, a reply window that captured real
speech writes a WAV (labelled MISS on an empty result) for offline analysis;
a silent window writes nothing."""

import threading
import wave
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


def _run(tmp_path, rms: float, partial: str):
    clock = [1000.0]

    def fake_read(*_a, **_k):
        clock[0] += 0.1
        return b"\x10\x20" * 160

    backend = MagicMock()
    backend.accept_waveform.return_value = False
    backend.partial_text.return_value = partial
    backend.finalize.return_value = partial

    with (
        patch("alexa_custom.stt_capture.time.monotonic", lambda: clock[0]),
        patch("alexa_custom.stt_capture._read_with_timeout", side_effect=fake_read),
        patch("alexa_custom.stt_capture.is_playback_active", return_value=False),
        patch("alexa_custom.stt_capture._rms_level", return_value=rms),
    ):
        return _capture_loop(
            _FakeProc(),
            channels=1,
            backend=backend,
            timeout=0.4,
            stop_event=threading.Event(),
            phrases=["si", "no"],
            vad_silence_ms=900,
            fast_vad_ms=200,
            dump_dir=str(tmp_path),
        )


class TestReplyDump:
    def test_failed_reply_with_speech_is_dumped_as_miss(self, tmp_path):
        # rms above the 0.03 floor + empty decode → a MISS dump is written.
        _run(tmp_path, rms=0.1, partial="")
        wavs = list(tmp_path.glob("reply_*.wav"))
        assert len(wavs) == 1
        assert "MISS" in wavs[0].name
        with wave.open(str(wavs[0]), "rb") as wf:  # valid, non-empty, mono 16k
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 16000
            assert wf.getnframes() > 0

    def test_silent_window_is_not_dumped(self, tmp_path):
        # rms below the floor → no speech present → nothing written.
        _run(tmp_path, rms=0.001, partial="")
        assert list(tmp_path.glob("reply_*.wav")) == []
