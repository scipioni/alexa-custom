from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alexa_custom.config import WakeWordGroup, Trigger

from alexa_custom.actions import normalize_text

logger = logging.getLogger(__name__)


def _lev_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, lb + 1):
            temp = dp[j]
            dp[j] = prev if a[i - 1] == b[j - 1] else 1 + min(dp[j], dp[j - 1], prev)
            prev = temp
    return dp[lb]


def _ipa(words: list[str], lang: str = "it") -> dict[str, str] | None:
    """Return IPA strings for a list of words via espeak-ng.

    Returns None when espeak-ng is unavailable (caller should fall back to
    orthographic distance).  Returns a partial dict (missing words skipped)
    on partial failure.
    """
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n".join(words))
            fname = f.name
        result = subprocess.run(
            ["espeak-ng", f"-v{lang}", "--ipa", "-q", f"-f{fname}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        os.unlink(fname)
        lines = [
            ln.strip().replace("ˈ", "").replace("ˌ", "").replace(" ", "")
            for ln in result.stdout.splitlines()
        ]
        return {w: ipa for w, ipa in zip(words, lines) if ipa}
    except Exception as exc:
        logger.debug(
            "espeak-ng unavailable, falling back to orthographic distance: %s", exc
        )
        return None


def _phonetic_confusers(
    groups: list[WakeWordGroup],
    distance: int,
    max_count: int,
    existing: set[str],
) -> set[str]:
    """Return corpus words within IPA phoneme distance of any wake phrase."""
    if distance <= 0:
        return set()

    corpus_path = os.path.join(os.path.dirname(__file__), "data", "it_corpus.txt")
    try:
        with open(corpus_path) as f:
            corpus = [
                line.strip() for line in f if line.strip() and not line.startswith("#")
            ]
    except OSError:
        logger.warning("it_corpus.txt not found, skipping phonetic confusers")
        return set()

    wake_phrases = [normalize_text(p) for g in groups for p in [g.word] + g.aliases]
    # Only single-word wake phrases are worth comparing phonetically
    wake_words_single = [p for p in wake_phrases if len(p.split()) == 1]
    if not wake_words_single:
        return set()

    all_words = list(set(corpus + wake_words_single))
    ipa_result = _ipa(all_words)
    # Fall back to orthographic keys when espeak-ng is unavailable.
    # Italian spelling is phonetically regular enough for a useful approximation.
    if ipa_result is None:
        logger.debug(
            "phonetic confusers: using orthographic distance (espeak-ng absent)"
        )
        ipa_map: dict[str, str] = {w: w for w in all_words}
    else:
        ipa_map = ipa_result

    candidates: list[tuple[int, str]] = []
    for word in corpus:
        norm = normalize_text(word)
        if norm in existing or norm in {normalize_text(p) for p in wake_phrases}:
            continue
        word_key = ipa_map.get(norm, "")
        if not word_key:
            continue
        min_dist = min(
            _lev_distance(word_key, ipa_map.get(w, ""))
            for w in wake_words_single
            if ipa_map.get(w)
        )
        if min_dist <= distance:
            candidates.append((min_dist, norm))

    candidates.sort()
    if len(candidates) > max_count:
        dropped = [w for _, w in candidates[max_count:]]
        logger.debug(
            "phonetic confusers: capped at %d, dropped: %s", max_count, dropped
        )
    return {w for _, w in candidates[:max_count]}


def _subphrase_confusers(groups: list[WakeWordGroup]) -> set[str]:
    """Return tokens from multi-word wake phrases that are not standalone wake words/aliases."""
    all_phrases: set[str] = {
        normalize_text(p) for g in groups for p in [g.word] + g.aliases
    }
    confusers: set[str] = set()
    for g in groups:
        for phrase in [g.word] + g.aliases:
            tokens = normalize_text(phrase).split()
            if len(tokens) > 1:
                for token in tokens:
                    if token not in all_phrases:
                        confusers.add(token)
    return confusers


def _build_confuser_set(
    groups: list[WakeWordGroup],
    stage1_cfg,
) -> set[str]:
    """Compute the full confuser set from sub-phrase, phonetic, and manual sources."""
    manual: set[str] = {normalize_text(c) for g in groups for c in g.confusers}

    if not stage1_cfg.auto_confusers:
        if manual:
            logger.debug(
                "confusers (manual only, auto_confusers=false): %s", sorted(manual)
            )
        return manual

    sub = _subphrase_confusers(groups)
    remaining = max(0, stage1_cfg.max_confusers - len(sub) - len(manual))
    phonetic = _phonetic_confusers(
        groups, stage1_cfg.confuser_distance, remaining, sub | manual
    )

    result = manual | sub | phonetic
    logger.debug(
        "confusers: total=%d manual=%d sub-phrase=%d phonetic=%d — %s",
        len(result),
        len(manual),
        len(sub),
        len(phonetic),
        sorted(result),
    )
    return result


def _build_alias_map(groups: list[WakeWordGroup]) -> dict[str, WakeWordGroup]:
    return {
        normalize_text(phrase): group
        for group in groups
        for phrase in [group.word] + group.aliases
    }


def _approx_wake_match(
    text: str,
    alias_map: dict[str, WakeWordGroup],
    threshold: float = 0.5,
) -> WakeWordGroup | None:
    """Fuzzy wake-word match for open-vocabulary backends (sherpa-onnx).

    Exact alias-map lookup first; if that misses, scores each phrase by the
    fraction of its significant words (len >= 3) that appear anywhere in the
    transcript.  Returns the best-scoring group if score >= threshold, else None.

    Example: phrase "ehi galileo", transcript "e il galileo"
      key words: ["ehi", "galileo"]  →  "galileo" in transcript → 0.5 → match
    """
    norm_text = normalize_text(text)

    if norm_text in alias_map:
        return alias_map[norm_text]

    text_words = set(norm_text.split())
    best_group: WakeWordGroup | None = None
    best_score = 0.0

    for norm_phrase, group in alias_map.items():
        phrase_words = [w for w in norm_phrase.split() if len(w) >= 3]
        if not phrase_words:
            phrase_words = norm_phrase.split()
        matched = sum(
            1
            for pw in phrase_words
            if any(pw in tw or (len(tw) >= 3 and tw in pw) for tw in text_words)
        )
        score = matched / len(phrase_words)
        if score > best_score:
            best_score = score
            best_group = group

    return best_group if best_score >= threshold else None


def _resolve_triggers(group: WakeWordGroup, fallback: list[Trigger]) -> list[Trigger]:
    # Per-group triggers take priority (listed first for scoring), global triggers
    # are always appended so they work regardless of which wake word is active.
    return group.triggers + fallback
