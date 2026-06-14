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

    def test_prefix_of_phrase_word_matches_by_content_word(self):
        # _approx_wake_match alone scores 0.5 on "ascolta assistente" vs "ascoltami assistente"
        # because "assistente" matches — the Vosk path avoids this by using fuzzy=False
        am = _make_alias_map(["ascoltami assistente"])
        result = _approx_wake_match("ascolta assistente", am)
        # The function itself returns a match; protection is at the call-site (fuzzy=False for Vosk)
        assert result is not None


# ---------------------------------------------------------------------------
# Confuser tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# KeywordSpotter helpers (unit tests, no real model needed)
# ---------------------------------------------------------------------------


class TestSherpaOnnxSTTModelDetection:
    """Unit tests for model-type auto-detection — no real model required."""

    def _make_mock_sherpa(self, called_factories: list):
        import types

        mock_delegate = types.SimpleNamespace(
            create_stream=lambda: object(),
        )

        def make_factory(name):
            def factory(**kw):
                called_factories.append(name)
                return mock_delegate

            return staticmethod(factory)

        mock_recognizer = type(
            "OnlineRecognizer",
            (),
            {
                "from_transducer": make_factory("from_transducer"),
                "from_zipformer2_ctc": make_factory("from_zipformer2_ctc"),
                "from_paraformer": make_factory("from_paraformer"),
            },
        )
        mock_sherpa = types.ModuleType("sherpa_onnx")
        mock_sherpa.OnlineRecognizer = mock_recognizer
        return mock_sherpa

    def test_transducer_selected_when_joiner_present(self, monkeypatch, tmp_path):
        import sys

        called = []
        sys.modules["sherpa_onnx"] = self._make_mock_sherpa(called)
        model_dir = tmp_path / "m"
        model_dir.mkdir()
        for f in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
            (model_dir / f).write_bytes(b"")
        SherpaOnnxSTT(str(model_dir))
        assert called == ["from_transducer"]

    def test_zipformer2_ctc_selected_when_model_onnx_present(
        self, monkeypatch, tmp_path
    ):
        import sys

        called = []
        sys.modules["sherpa_onnx"] = self._make_mock_sherpa(called)
        model_dir = tmp_path / "m"
        model_dir.mkdir()
        for f in ("model.onnx", "tokens.txt"):
            (model_dir / f).write_bytes(b"")
        SherpaOnnxSTT(str(model_dir))
        assert called == ["from_zipformer2_ctc"]

    def test_paraformer_fallback_when_no_joiner_no_model_onnx(
        self, monkeypatch, tmp_path
    ):
        import sys

        called = []
        sys.modules["sherpa_onnx"] = self._make_mock_sherpa(called)
        model_dir = tmp_path / "m"
        model_dir.mkdir()
        for f in ("encoder.onnx", "decoder.onnx", "tokens.txt"):
            (model_dir / f).write_bytes(b"")
        SherpaOnnxSTT(str(model_dir))
        assert called == ["from_paraformer"]

    def test_paraformer_fallback_when_zipformer2_ctc_unavailable(
        self, monkeypatch, tmp_path
    ):
        import sys

        called = []
        mock_sherpa = self._make_mock_sherpa(called)
        del mock_sherpa.OnlineRecognizer.from_zipformer2_ctc
        sys.modules["sherpa_onnx"] = mock_sherpa
        model_dir = tmp_path / "m"
        model_dir.mkdir()
        for f in ("model.onnx", "tokens.txt"):
            (model_dir / f).write_bytes(b"")
        SherpaOnnxSTT(str(model_dir))
        assert called == ["from_paraformer"]


class TestTokenizeKeyword:
    def test_bpe_greedy_longest_match(self):
        # Simulates the kroko Italian model: multi-char subwords preferred
        from alexa_custom.stt import _tokenize_keyword

        vocab = {"ga": "ga", "li": "li", "le": "le", "o": "o", "g": "g", "a": "a"}
        assert _tokenize_keyword("galileo", vocab) == "ga li le o"

    def test_word_boundary_prefix_preferred(self):
        # ▁-prefixed token should be chosen for word-initial position
        from alexa_custom.stt import _tokenize_keyword

        vocab = {"▁ga": "▁ga", "ga": "ga", "li": "li", "le": "le", "o": "o"}
        result = _tokenize_keyword("galileo", vocab)
        assert result.startswith("▁ga"), f"Expected ▁ga prefix, got {result!r}"

    def test_multi_word_each_word_processed(self):
        from alexa_custom.stt import _tokenize_keyword

        vocab = {
            "▁e": "▁e",
            "hi": "hi",
            "ga": "ga",
            "li": "li",
            "le": "le",
            "o": "o",
            "h": "h",
            "i": "i",
        }
        result = _tokenize_keyword("ehi galileo", vocab)
        assert "ga" in result
        assert "le" in result

    def test_unknown_char_skipped(self):
        from alexa_custom.stt import _tokenize_keyword

        vocab = {"a": "a", "b": "b"}
        result = _tokenize_keyword("abz", vocab)
        assert result == "a b"

    def test_empty_word_returns_empty(self):
        from alexa_custom.stt import _tokenize_keyword

        assert _tokenize_keyword("", {}) == ""


class TestSherpaKeywordSpotterUnit:
    """Unit tests using a mock sherpa_onnx.KeywordSpotter — no real model."""

    def _make_mock_spotter(self, monkeypatch, keyword_hit: str = ""):
        import types
        import alexa_custom.stt as stt_mod

        mock_result = types.SimpleNamespace(keyword=keyword_hit)
        mock_stream = object()

        mock_kws_cls = type(
            "MockKWS",
            (),
            {
                "__init__": lambda self, **kw: None,
                "create_stream": lambda self: mock_stream,
                "is_ready": lambda self, s: False,
                "decode_stream": lambda self, s: None,
                "get_result": lambda self, s: mock_result,
                "reset_stream": lambda self, s: None,
            },
        )

        mock_sherpa = types.ModuleType("sherpa_onnx")
        mock_sherpa.KeywordSpotter = mock_kws_cls
        monkeypatch.setattr(
            stt_mod, "_load_token_vocab", lambda path: {c: c for c in "galileo "}
        )
        monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", mock_sherpa)
        return mock_stream

    def _make_env(self, tmp_path, keyword_hit: str):
        """Build a mock sherpa_onnx module + model dir for KWS tests."""
        import sys
        import types as _t

        mock_stream = _t.SimpleNamespace(
            accept_waveform=lambda sample_rate, waveform: None,
        )
        mock_result = _t.SimpleNamespace(keyword=keyword_hit)

        mock_sherpa_mod = _t.ModuleType("sherpa_onnx")
        mock_sherpa_mod.KeywordSpotter = type(
            "KWS",
            (),
            {
                "__init__": lambda self, **kw: None,
                "create_stream": lambda self: mock_stream,
                "is_ready": lambda self, s: False,
                "decode_stream": lambda self, s: None,
                "get_result": lambda self, s: mock_result,
                "reset_stream": lambda self, s: None,
            },
        )
        sys.modules["sherpa_onnx"] = mock_sherpa_mod

        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "tokens.txt").write_text("g 1\na 2\nl 3\ni 4\ne 5\no 6\n")
        for f in ("encoder.onnx", "decoder.onnx", "joiner.onnx"):
            (model_dir / f).write_bytes(b"")
        return model_dir

    def test_accept_waveform_returns_false_when_no_hit(self, tmp_path):
        from alexa_custom.stt import SherpaKeywordSpotter

        model_dir = self._make_env(tmp_path, keyword_hit="")
        spotter = SherpaKeywordSpotter(str(model_dir), ["galileo"])
        assert spotter.accept_waveform(b"\x00\x00" * 512) is False
        assert spotter.text() == ""

    def test_accept_waveform_returns_true_on_keyword_hit(self, tmp_path):
        from alexa_custom.stt import SherpaKeywordSpotter

        model_dir = self._make_env(tmp_path, keyword_hit="galileo")
        spotter = SherpaKeywordSpotter(str(model_dir), ["galileo"])
        assert spotter.accept_waveform(b"\x00\x00" * 512) is True
        assert spotter.text() == "galileo"


class TestVoskGrammar:
    def test_phrases_to_grammar_normalization(self):
        from alexa_custom.stt_backends import _phrases_to_grammar
        import json

        phrases = ["Che ora è", "caffè", "sì"]
        grammar_json = _phrases_to_grammar(phrases)
        parsed = json.loads(grammar_json)

        # Expected output must have normalized lowercase words, sorted and deduplicated, plus "[unk]"
        # "Che ora è" -> "che ora e"
        # "caffè" -> "caffe"
        # "sì" -> "si"
        assert parsed == ["caffe", "che ora e", "si", "[unk]"]

    def test_phrases_to_grammar_logging(self, caplog):
        from alexa_custom.stt_backends import _phrases_to_grammar
        import logging

        phrases = ["Che ora è", "caffè", "sì"]
        with caplog.at_level(logging.INFO, logger="alexa_custom.stt_backends"):
            _phrases_to_grammar(phrases, label="stage-1")

        # Log line names the stage, the token count, and the exact token list
        # (including the [unk] sink).
        assert any(
            "stage-1 grammar:" in record.message
            and "4 tokens" in record.message
            and "che ora e" in record.message
            and "caffe" in record.message
            and "[unk]" in record.message
            for record in caplog.records
        )

    def _grammar_fixtures(self):
        from alexa_custom.config import Trigger, WakeWordGroup

        wake = WakeWordGroup(
            word="ehi assistente",
            aliases=["ehi galileo"],
            triggers=[
                Trigger(phrase="scoped command", actions=[], wake_words=["help"])
            ],
        )
        global_trigger = Trigger(phrase="accendi la luce", actions=[], wake_words=None)
        direct_trigger = Trigger(phrase="chiama stefano", actions=[], wake_words=[])
        return wake, global_trigger, direct_trigger

    def test_grammar_all_includes_wake_gated_by_default(self):
        from alexa_custom.stt_backends import _grammar_json_all
        import json

        wake, global_trigger, direct_trigger = self._grammar_fixtures()
        parsed = json.loads(
            _grammar_json_all([wake], [global_trigger], [direct_trigger])
        )

        # Default (partial-matching) grammar: wake words, aliases, scoped +
        # global trigger phrases, direct triggers, and [unk].
        assert "ehi assistente" in parsed
        assert "ehi galileo" in parsed
        assert "scoped command" in parsed
        assert "accendi la luce" in parsed
        assert "chiama stefano" in parsed
        assert "[unk]" in parsed

    def test_grammar_all_excludes_wake_gated_when_disabled(self):
        from alexa_custom.stt_backends import _grammar_json_all
        import json

        wake, global_trigger, direct_trigger = self._grammar_fixtures()
        parsed = json.loads(
            _grammar_json_all(
                [wake], [global_trigger], [direct_trigger], include_wake_gated=False
            )
        )

        # Wake words and direct-match triggers remain; wake-gated command
        # phrases (scoped + global) are dropped to shrink the false-positive
        # surface. [unk] is always present.
        assert "ehi assistente" in parsed
        assert "ehi galileo" in parsed
        assert "chiama stefano" in parsed
        assert "[unk]" in parsed
        assert "scoped command" not in parsed
        assert "accendi la luce" not in parsed
