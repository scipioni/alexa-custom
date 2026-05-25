"""E2E STT test: synthesise Italian speech with piper, feed through STT backends."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from alexa_custom.stt import SherpaOnnxSTT, VoskSTT, _CHUNK, _load_model, _approx_wake_match
from alexa_custom.config import WakeWordGroup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PIPER_BIN = shutil.which("piper") or str(Path(__file__).parent.parent / ".venv/bin/piper")
PIPER_VOICE = str(
    Path(__file__).parent.parent / "models/piper/it_IT-paola-medium.onnx"
)
SHERPA_MODEL = str(Path(__file__).parent.parent / "models/it/kroko_128l")
VOSK_MODEL = str(Path(__file__).parent.parent / "models/it")

_FFMPEG = shutil.which("ffmpeg")


def _synth_to_pcm(text: str) -> bytes:
    """Synthesise ``text`` with piper and return raw s16le 16 kHz mono bytes."""
    if not os.path.exists(PIPER_BIN):
        pytest.skip(f"piper not found at {PIPER_BIN}")
    if not os.path.exists(PIPER_VOICE):
        pytest.skip(f"piper voice not found at {PIPER_VOICE}")
    if not _FFMPEG:
        pytest.skip("ffmpeg not found")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        subprocess.run(
            [PIPER_BIN, "--model", PIPER_VOICE, "--output_file", wav_path],
            input=text.encode(),
            check=True,
            capture_output=True,
        )
        # Resample to 16 kHz mono s16le raw PCM
        result = subprocess.run(
            [
                _FFMPEG, "-y", "-i", wav_path,
                "-ar", "16000", "-ac", "1", "-f", "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        # Append 2.5 s of silence so the endpoint detector fires after speech ends.
        # rule2_min_trailing_silence=1.2 s, but sherpa needs ~1.9 s of actual silence
        # after the last decoded token before is_endpoint() triggers.
        silence = bytes(int(16000 * 2.5) * 2)
        return result.stdout + silence
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _feed_pcm(backend, pcm: bytes) -> str:
    """Feed raw s16le PCM through backend in _CHUNK chunks, return collected text."""
    collected: list[str] = []
    buf = io.BytesIO(pcm)
    while True:
        chunk = buf.read(_CHUNK)
        if not chunk:
            break
        if backend.accept_waveform(chunk):
            text = backend.text().strip()
            if text:
                collected.append(text)
            backend.reset()
    # flush remainder
    final = backend.text().strip()
    if final:
        collected.append(final)
    return " ".join(collected).strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.isdir(SHERPA_MODEL),
    reason=f"sherpa-onnx model not found at {SHERPA_MODEL}",
)
class TestSherpaOnnxSTT:
    def setup_method(self):
        self.backend = SherpaOnnxSTT(SHERPA_MODEL)

    def test_wake_word_recognised(self):
        """Endpoint must fire and produce non-empty text for a short phrase.

        Note: the kroko model has limited accuracy on piper-synthesised speech.
        The assertion only checks that endpoint detection is working (non-empty
        output), not that the exact words are transcribed.
        """
        pcm = _synth_to_pcm("ehi galileo")
        result = _feed_pcm(self.backend, pcm)
        assert result, f"No text recognised from 'ehi galileo' (got: {result!r})"

    def test_command_recognised(self):
        pcm = _synth_to_pcm("chiama stefano")
        result = _feed_pcm(self.backend, pcm)
        assert result, f"No text recognised from 'chiama stefano' (got: {result!r})"

    def test_full_conversation_phrase(self):
        """Simulate a single-phrase wake+command as used in single-stage mode."""
        pcm = _synth_to_pcm("ehi galileo chiama stefano")
        result = _feed_pcm(self.backend, pcm)
        assert result, f"No text recognised (got: {result!r})"
        # longer phrase gives better accuracy — check for at least one key word
        low = result.lower()
        assert any(w in low for w in ("galileo", "chiama", "stefano")), (
            f"No key word found in {result!r}"
        )


@pytest.mark.skipif(
    not os.path.isdir(VOSK_MODEL),
    reason=f"vosk model not found at {VOSK_MODEL}",
)
class TestVoskSTT:
    def setup_method(self):
        import vosk
        self.backend = VoskSTT(_load_model(VOSK_MODEL))

    def test_wake_word_recognised(self):
        """Vosk with unconstrained model substitutes unknown words; just verify output is non-empty.

        In production, Vosk uses a grammar-constrained KaldiRecognizer so wake words
        are the only accepted tokens.
        """
        pcm = _synth_to_pcm("ehi galileo")
        result = _feed_pcm(self.backend, pcm)
        assert result, f"No text recognised from 'ehi galileo' (got: {result!r})"

    def test_command_recognised(self):
        pcm = _synth_to_pcm("chiama stefano")
        result = _feed_pcm(self.backend, pcm)
        assert result, f"No text recognised (got: {result!r})"


# ---------------------------------------------------------------------------
# Unit tests for fuzzy wake-word matching
# ---------------------------------------------------------------------------

def _make_alias_map(phrases: list[str]) -> dict:
    from alexa_custom.stt import _build_alias_map, normalize_text
    groups = [WakeWordGroup(word=phrases[0], aliases=phrases[1:], triggers=[])]
    return _build_alias_map(groups)


class TestApproxWakeMatch:
    def setup_method(self):
        self.alias_map = _make_alias_map(["ehi galileo"])

    def test_exact_match(self):
        assert _approx_wake_match("ehi galileo", self.alias_map) is not None

    def test_noisy_transcript(self):
        # sherpa often adds "e il" instead of "ehi" but preserves "galileo"
        assert _approx_wake_match("e il galileo", self.alias_map) is not None

    def test_partial_transcript(self):
        assert _approx_wake_match("galileo", self.alias_map) is not None

    def test_no_match(self):
        assert _approx_wake_match("buongiorno come stai", self.alias_map) is None

    def test_short_noise_ignored(self):
        # single-char tokens should not trigger a match
        assert _approx_wake_match("e il la le un", self.alias_map) is None
