"""Regression gate over the labelled matching corpus (tests/eval/corpus.yaml).

Runs the real wake + command matchers against the corpus and asserts the
operating point: zero false triggers (precision 100%) and no recognition loss
(recall 100%). New real-world false wakes should be added to the corpus, not
worked around here — this test then guards them forever.
"""

from __future__ import annotations

from pathlib import Path

from alexa_custom.match_eval import classify, evaluate, load_corpus

_CORPUS = Path(__file__).parent / "eval" / "corpus.yaml"


def _load():
    return load_corpus(_CORPUS)


def test_no_false_triggers():
    config, cases = _load()
    m = evaluate(config, cases)
    assert m.fp == 0, f"false triggers: {m.false_fires}"
    assert m.precision == 1.0


def test_no_recognition_loss():
    config, cases = _load()
    m = evaluate(config, cases)
    assert m.fn == 0, f"missed expected matches: {m.misses}"
    assert m.recall == 1.0


def test_every_case_exact_outcome():
    config, cases = _load()
    m = evaluate(config, cases)
    assert m.accuracy == 1.0, f"{m.total - m.correct} cases with wrong outcome"


def test_short_wake_component_alone_is_silent():
    # The specific false-wake class char-coverage scoring fixes.
    config, _ = _load()
    assert classify("ehi come stai oggi", config).fires is False


def test_truncated_keyword_still_wakes():
    config, _ = _load()
    assert classify("galile", config).woke is True
