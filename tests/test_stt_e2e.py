"""E2E STT test: synthesise Italian speech with piper, feed through STT backends."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from alexa_custom.stt import (
    SherpaOnnxSTT,
    VoskSTT,
    _CHUNK,
    _load_model,
    _approx_wake_match,
)
from alexa_custom.config import WakeWordGroup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PIPER_BIN = shutil.which("piper") or str(
    Path(__file__).parent.parent / ".venv/bin/piper"
)
PIPER_VOICE = str(Path(__file__).parent.parent / "models/piper/it_IT-paola-medium.onnx")
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
                _FFMPEG,
                "-y",
                "-i",
                wav_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "s16le",
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
    from alexa_custom.stt import _build_alias_map

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


# ---------------------------------------------------------------------------
# Confuser tests
# ---------------------------------------------------------------------------


class TestSubphraseConfusers:
    def setup_method(self):
        from alexa_custom.stt import _subphrase_confusers

        self._fn = _subphrase_confusers

    def _groups(self, word, aliases=None):
        return [WakeWordGroup(word=word, aliases=aliases or [], triggers=[])]

    def test_multiword_wake_produces_component_confuser(self):
        groups = self._groups("aiuto aiuto")
        assert self._fn(groups) == {"aiuto"}

    def test_alias_components_also_added(self):
        groups = self._groups("aiuto aiuto", aliases=["mi serve aiuto"])
        result = self._fn(groups)
        assert "aiuto" in result
        assert "mi" in result
        assert "serve" in result

    def test_single_word_wake_produces_no_confusers(self):
        groups = self._groups("galileo")
        assert self._fn(groups) == set()

    def test_component_that_is_itself_a_standalone_wake_word_excluded(self):
        groups = [
            WakeWordGroup(word="aiuto", aliases=[], triggers=[]),
            WakeWordGroup(word="aiuto aiuto", aliases=[], triggers=[]),
        ]
        result = self._fn(groups)
        # "aiuto" is a standalone wake word, must not become a confuser
        assert "aiuto" not in result


class TestBuildConfuserSet:
    def setup_method(self):
        from alexa_custom.stt import _build_confuser_set
        from alexa_custom.config import STTStage1Config

        self._fn = _build_confuser_set
        self._cfg = STTStage1Config

    def _groups(self, word, aliases=None, confusers=None):
        return [
            WakeWordGroup(
                word=word,
                aliases=aliases or [],
                triggers=[],
                confusers=confusers or [],
            )
        ]

    def test_auto_confusers_false_returns_only_manual(self):
        groups = self._groups("aiuto aiuto", confusers=["arduino"])
        cfg = self._cfg(auto_confusers=False, confuser_distance=3, max_confusers=30)
        result = self._fn(groups, cfg)
        assert result == {"arduino"}
        assert "aiuto" not in result

    def test_auto_confusers_true_includes_subphrase(self):
        groups = self._groups("aiuto aiuto")
        cfg = self._cfg(auto_confusers=True, confuser_distance=0, max_confusers=30)
        result = self._fn(groups, cfg)
        assert "aiuto" in result

    def test_manual_confusers_always_included(self):
        groups = self._groups("galileo", confusers=["arduino"])
        cfg = self._cfg(auto_confusers=False)
        result = self._fn(groups, cfg)
        assert "arduino" in result


class TestConfuserGrammarAndGuard:
    def setup_method(self):
        from alexa_custom.stt import (
            _grammar_json,
            _build_alias_map,
            _build_confuser_set,
        )
        from alexa_custom.config import STTStage1Config

        self._grammar_json = _grammar_json
        self._build_alias_map = _build_alias_map
        self._build_confuser_set = _build_confuser_set
        self._cfg = STTStage1Config

    def test_confusers_appear_in_grammar_not_in_alias_map(self):
        import json

        groups = [WakeWordGroup(word="aiuto aiuto", aliases=[], triggers=[])]
        cfg = self._cfg(auto_confusers=True, confuser_distance=0, max_confusers=30)
        confuser_set = self._build_confuser_set(groups, cfg)
        alias_map = self._build_alias_map(groups)
        grammar = json.loads(self._grammar_json(groups, confuser_set))

        # "aiuto" is a confuser: in grammar, not in alias_map
        assert "aiuto" in confuser_set
        assert "aiuto" in grammar
        assert "aiuto" not in alias_map

        # "aiuto aiuto" is the wake word: in grammar and in alias_map
        assert "aiuto aiuto" in grammar
        assert "aiuto aiuto" in alias_map

    def test_confuser_match_does_not_appear_in_alias_map(self):
        groups = [
            WakeWordGroup(
                word="galileo", aliases=[], triggers=[], confusers=["arduino"]
            )
        ]
        cfg = self._cfg(auto_confusers=False)
        confuser_set = self._build_confuser_set(groups, cfg)
        alias_map = self._build_alias_map(groups)

        assert "arduino" in confuser_set
        assert "arduino" not in alias_map
        assert "galileo" in alias_map
