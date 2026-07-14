"""Fast-VAD endpointing (stt.fast_vad_ms) and TTS synthesis cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from alexa_custom.match_eval import load_corpus
from alexa_custom.stt import _fast_partial_hit
from alexa_custom.tts import PiperTTS

_CORPUS = Path(__file__).parent / "eval" / "corpus.yaml"


def _config():
    config, _ = load_corpus(_CORPUS)
    return config


# ---------------------------------------------------------------------------
# _fast_partial_hit — decides whether the partial transcript is already a
# complete, matchable utterance (fires the endpoint after fast_vad_ms)
# ---------------------------------------------------------------------------


def test_fast_hit_on_wake_only_partial():
    assert _fast_partial_hit("ehi galileo", _config(), woken=False) is True


def test_fast_hit_on_one_breath_partial():
    assert (
        _fast_partial_hit("ehi galileo accendi la luce", _config(), woken=False) is True
    )


def test_fast_hit_on_command_while_woken():
    assert _fast_partial_hit("che ore sono", _config(), woken=True) is True


def test_no_fast_hit_on_gated_command_when_not_woken():
    # "che ore sono" is with_wake: true — must not fast-fire outside the window
    # (the direct trigger "chiama stefano" is the only wake-free candidate).
    assert _fast_partial_hit("che ore sono", _config(), woken=False) is False


def test_fast_hit_on_direct_trigger_without_wake():
    assert _fast_partial_hit("chiama stefano", _config(), woken=False) is True


def test_no_fast_hit_on_free_form_speech():
    # Free-form utterances (LLM fallback) keep the long endpoint.
    assert (
        _fast_partial_hit("che tempo fa domani a roma", _config(), woken=True) is False
    )


def test_no_fast_hit_on_incomplete_wake():
    assert _fast_partial_hit("ehi", _config(), woken=False) is False


# ---------------------------------------------------------------------------
# PiperTTS LRU cache
# ---------------------------------------------------------------------------


class _FakeChunk:
    def __init__(self):
        self.audio_int16_array = np.ones(160, dtype=np.int16)
        self.sample_rate = 16000


class _FakeVoice:
    def __init__(self):
        self.calls = 0

    def synthesize(self, clause):
        self.calls += 1
        yield _FakeChunk()


def _make_tts() -> tuple[PiperTTS, _FakeVoice]:
    import collections

    tts = object.__new__(PiperTTS)
    tts._voice = _FakeVoice()
    tts._samplerate = 16000
    tts._cache = collections.OrderedDict()
    return tts, tts._voice


def test_tts_cache_second_synthesis_is_free():
    tts, voice = _make_tts()
    out1 = list(tts._synthesize("sistema pronto"))
    assert voice.calls == 1
    out2 = list(tts._synthesize("sistema pronto"))
    assert voice.calls == 1  # served from cache
    assert len(out1) == len(out2)
    np.testing.assert_array_equal(out1[0][0], out2[0][0])


def test_tts_cache_skips_long_texts():
    tts, voice = _make_tts()
    long_text = "parola " * 60  # > _CACHE_MAX_TEXT_LEN
    list(tts._synthesize(long_text))
    list(tts._synthesize(long_text))
    assert voice.calls == 2  # never cached


def test_tts_cache_not_populated_on_aborted_synthesis():
    tts, voice = _make_tts()
    gen = tts._synthesize("sistema pronto")
    next(gen)
    gen.close()  # playback aborted mid-stream
    assert "sistema pronto" not in tts._cache
    list(tts._synthesize("sistema pronto"))
    assert voice.calls == 2


def test_tts_cache_evicts_oldest():
    tts, _ = _make_tts()
    for i in range(PiperTTS._CACHE_MAX_ENTRIES + 5):
        list(tts._synthesize(f"frase numero {i}"))
    assert len(tts._cache) == PiperTTS._CACHE_MAX_ENTRIES
    assert "frase numero 0" not in tts._cache
    assert f"frase numero {PiperTTS._CACHE_MAX_ENTRIES + 4}" in tts._cache


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_fast_vad_ms_default_and_override(tmp_path):
    from alexa_custom.config import load_config

    base = "wake_words:\n  - test\nlivekit:\n  url: ws://x\n  room: r\n"
    p = tmp_path / "config.yaml"

    p.write_text(base)
    cfg = load_config(str(p))
    assert cfg.stt.fast_vad_ms == 400

    p.write_text(base + "stt:\n  fast_vad_ms: 0\n")
    cfg = load_config(str(p))
    assert cfg.stt.fast_vad_ms == 0
