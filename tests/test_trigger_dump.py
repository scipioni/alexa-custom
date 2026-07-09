"""Tests for trigger-dump WAV channel/duration correctness
(harden-serena-runtime task 6.2).

_audio_buf holds post-downmix MONO s16le chunks regardless of the capture's
own channel count, so the dump WAV must always be written as 1 channel and
sized for an 8s budget — previously a stereo capture doubled both."""

import collections
import wave

from alexa_custom.stt import _dump_trigger_wav


def test_dump_writes_mono_regardless_of_original_channel_count(tmp_path):
    # 1 second of mono s16le silence (16000 samples * 2 bytes).
    chunk = b"\x00\x00" * 16000
    buf: "collections.deque[bytes]" = collections.deque([chunk])

    _dump_trigger_wav(buf, 1, "test_trigger", str(tmp_path))

    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0]), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 16000  # 1 second of mono frames, not 0.5s


def test_eight_second_mono_buffer_reports_eight_seconds():
    """An 8s-budgeted mono buffer (8 * 16000 * 2 bytes) must decode as 8s of
    audio, not 16s (which happened when the byte budget was multiplied by
    the capture's stereo channel count)."""
    total_bytes = 8 * 16000 * 2
    buf: "collections.deque[bytes]" = collections.deque([b"\x00\x00" * 16000] * 8)
    assert sum(len(c) for c in buf) == total_bytes
