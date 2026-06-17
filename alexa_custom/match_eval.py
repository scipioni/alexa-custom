"""Text-level precision/recall harness for wake + command matching.

The audio-based wake_eval.py belongs to the removed two-stage Vosk pipeline.
This harness instead scores the *current* matchers (_match_wake_word and
match_trigger_with_score) at the transcript level: given a labelled corpus of
(transcript -> expected outcome) it reports precision, recall and false-wake
rate. No microphone, model, or threads — it runs in milliseconds and gates in
CI, so any matcher change can be measured against a fixed corpus.

Outcome model (mirrors stt._recognition_loop's cold/woken path):
  - a wake phrase is detected -> "woke"; a trailing command may one-breath fire
  - no wake phrase -> only with_wake=False triggers match (unless `woken`)

Corpus YAML schema (see tests/eval/corpus.yaml):
  wake_words: [str, ...]
  stt: {wake_match_threshold: float}
  recognition: {matching_threshold, matching_algorithm, min_word_overlap}
  triggers: [{commands: [str], with_wake: bool}, ...]
  cases:
    - {text: str, expect: "none"|"wake"|"<trigger phrase>", woken?: bool, note?: str}

CLI: python -m alexa_custom.match_eval [--corpus PATH] [--sweep]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from alexa_custom.actions import match_trigger_with_score
from alexa_custom.config import ActionsConfig, RecognitionConfig, STTConfig, Trigger
from alexa_custom.stt_phonetics import _match_wake_word

_DEFAULT_CORPUS = Path("tests/eval/corpus.yaml")


# ---------------------------------------------------------------------------
# Corpus model
# ---------------------------------------------------------------------------


@dataclass
class Case:
    text: str
    expect: str  # "none" | "wake" | "<trigger phrase>"
    woken: bool = False
    note: str = ""


@dataclass
class Outcome:
    woke: bool
    trigger: str | None
    score: float

    @property
    def fires(self) -> bool:
        return self.woke or self.trigger is not None


def load_corpus(path: Path) -> tuple[ActionsConfig, list[Case]]:
    """Build an ActionsConfig and a list of Cases from a corpus YAML file."""
    raw = yaml.safe_load(path.read_text())

    triggers: list[Trigger] = []
    for t in raw.get("triggers", []):
        commands = t["commands"]
        triggers.append(
            Trigger(
                commands=commands,
                phrase=commands[0],
                aliases=commands[1:],
                with_wake=t.get("with_wake", True),
                actions=[],
            )
        )

    stt_raw = raw.get("stt", {})
    rec_raw = raw.get("recognition", {})
    config = ActionsConfig(
        wake_words=raw["wake_words"],
        triggers=triggers,
        stt=STTConfig(
            wake_match_threshold=float(stt_raw.get("wake_match_threshold", 0.5))
        ),
        recognition=RecognitionConfig(
            matching_threshold=float(rec_raw.get("matching_threshold", 70.0)),
            matching_algorithm=rec_raw.get("matching_algorithm", "token_set_ratio"),
            min_word_overlap=float(rec_raw.get("min_word_overlap", 0.0)),
        ),
    )

    cases = [
        Case(
            text=c["text"],
            expect=str(c["expect"]),
            woken=bool(c.get("woken", False)),
            note=c.get("note", ""),
        )
        for c in raw.get("cases", [])
    ]
    return config, cases


# ---------------------------------------------------------------------------
# Classifier — faithful to stt._recognition_loop cold/woken path
# ---------------------------------------------------------------------------


def classify(transcript: str, config: ActionsConfig, woken: bool = False) -> Outcome:
    rec = config.recognition
    wake_phrase, residual = _match_wake_word(
        transcript, config.wake_words, threshold=config.stt.wake_match_threshold
    )
    if wake_phrase is not None:
        if residual:
            trig, score = match_trigger_with_score(
                residual,
                config.triggers,
                threshold=rec.matching_threshold,
                algorithm=rec.matching_algorithm,
                min_word_overlap=rec.min_word_overlap,
            )
            return Outcome(True, trig.phrase if trig else None, score)
        return Outcome(True, None, 0.0)

    candidates = [t for t in config.triggers if (not t.with_wake) or woken]
    if candidates:
        trig, score = match_trigger_with_score(
            transcript,
            candidates,
            threshold=rec.matching_threshold,
            algorithm=rec.matching_algorithm,
            min_word_overlap=rec.min_word_overlap,
        )
        if trig is not None:
            return Outcome(False, trig.phrase, score)
    return Outcome(False, None, 0.0)


def _is_correct(case: Case, out: Outcome) -> bool:
    if case.expect == "none":
        return not out.fires
    if case.expect == "wake":
        return out.woke and out.trigger is None
    return out.trigger == case.expect


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class Metrics:
    tp: int = 0  # positive case that fired
    fn: int = 0  # positive case that stayed silent
    fp: int = 0  # negative case that fired (false trigger)
    tn: int = 0  # negative case that stayed silent
    correct: int = 0  # fully-correct outcome (right trigger / right silence)
    total: int = 0
    false_fires: list[tuple[str, str]] = field(default_factory=list)  # (text, fired-as)
    misses: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def false_wake_rate(self) -> float:
        denom = self.fp + self.tn
        return self.fp / denom if denom else 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 1.0


def evaluate(config: ActionsConfig, cases: list[Case]) -> Metrics:
    m = Metrics()
    for case in cases:
        out = classify(case.text, config, woken=case.woken)
        m.total += 1
        positive = case.expect != "none"
        if positive:
            if out.fires:
                m.tp += 1
            else:
                m.fn += 1
                m.misses.append(case.text)
        else:
            if out.fires:
                m.fp += 1
                fired_as = out.trigger or "(wake)"
                m.false_fires.append((case.text, fired_as))
            else:
                m.tn += 1
        if _is_correct(case, out):
            m.correct += 1
    return m


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(m: Metrics, label: str = "") -> str:
    head = f"=== Matching Eval{': ' + label if label else ''} ==="
    lines = [
        head,
        f"  cases        : {m.total}",
        f"  precision    : {m.precision:.1%}   (tp={m.tp} fp={m.fp})",
        f"  recall       : {m.recall:.1%}   (tp={m.tp} fn={m.fn})",
        f"  false-wake   : {m.false_wake_rate:.1%}   (fp={m.fp} tn={m.tn})",
        f"  accuracy     : {m.accuracy:.1%}   ({m.correct}/{m.total} exact outcomes)",
    ]
    if m.false_fires:
        lines.append("  false fires:")
        lines += [f"    {text!r} -> {fired}" for text, fired in m.false_fires]
    if m.misses:
        lines.append("  misses:")
        lines += [f"    {text!r}" for text in m.misses]
    lines.append("=" * len(head))
    return "\n".join(lines)


def _sweep(config: ActionsConfig, cases: list[Case]) -> None:
    print(f"{'wake_match_threshold':>22}  {'prec':>6}  {'recall':>6}  {'false-wake':>10}")
    print("-" * 50)
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        config.stt.wake_match_threshold = thr
        m = evaluate(config, cases)
        print(
            f"{thr:>22.2f}  {m.precision:>6.1%}  {m.recall:>6.1%}  "
            f"{m.false_wake_rate:>10.1%}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(_DEFAULT_CORPUS))
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Sweep wake_match_threshold and print a precision/recall table.",
    )
    args = parser.parse_args()

    config, cases = load_corpus(Path(args.corpus))
    if args.sweep:
        _sweep(config, cases)
        return
    print(format_report(evaluate(config, cases)))


if __name__ == "__main__":
    main()
