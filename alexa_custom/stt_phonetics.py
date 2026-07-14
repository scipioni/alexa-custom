from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alexa_custom.config import WakeWordGroup

from alexa_custom.actions import _word_token_match, normalize_text


def _isolated_keyword_match(text_tokens: list[str], phrase_words: list[str]) -> bool:
    """True when the transcript is NOTHING BUT the phrase's distinctive words.

    Reconciles two labelled behaviours that the all-words gate alone cannot:

    - isolated keyword → wake: "galileo" / "galile" said on its own is an
      intentional address even though the filler "ehi" was dropped (corpus:
      truncated-wake recall).
    - embedded keyword → silent: "a ogni tanto controlliamo serena standard"
      mentions the keyword mid-conversation and must NOT wake (the observed
      false-positive class the all-words gate was added for).

    "Distinctive" = phrase words of len >= 4 ("galileo", "serena"); short
    fillers ("ehi") don't count. Every transcript token must match a
    distinctive word — one extra surrounding word ("il galileo") makes the
    utterance conversation, not an address.
    """
    distinctive = [w for w in phrase_words if len(w) >= 4]
    if not distinctive or not text_tokens:
        return False
    return all(
        any(_word_token_match(pw, tw) for pw in distinctive) for tw in text_tokens
    )


def _word_overlap_score(phrase_words: list[str], text_words: set[str]) -> float:
    """Acoustic overlap of ``phrase_words`` with ``text_words``, weighted by length.

    Score is the fraction of the wake phrase's *characters* (not word count)
    that are covered by a matching transcript word. Longer words are inherently
    more distinctive, so a phrase's long keyword dominates while a short filler
    syllable contributes little: matching only "ehi" of "ehi galileo" scores
    3/10 = 0.3 (below the 0.5 default → no wake), whereas matching the
    distinctive "galileo" scores 7/10 = 0.7. This cuts false wakes from common
    short syllables without losing truncated-keyword recall ("galile"→wake).
    """
    total = sum(len(pw) for pw in phrase_words)
    if total == 0:
        return 0.0
    matched = sum(
        len(pw)
        for pw in phrase_words
        if any(_word_token_match(pw, tw) for tw in text_words)
    )
    return matched / total


def _wake_token_count(text: str, residual: str) -> int:
    """Number of transcript tokens forming the wake word (``text`` minus ``residual``).

    Used to slice a Vosk per-word confidence list down to just the wake-word
    portion, so a low-confidence trailing command can't drag the wake's
    confidence below the gate. Counts raw ``text`` tokens (these align 1:1 with
    Vosk's ``result`` word list) but compares them in normalized form against the
    residual. Never returns 0.
    """
    residual_words = set(normalize_text(residual).split())
    n = sum(1 for w in text.split() if normalize_text(w) not in residual_words)
    return n or 1


def _match_wake_word(
    text: str,
    wake_words: list[str],
    threshold: float = 0.5,
) -> tuple[str | None, str]:
    """Return (matched_wake_phrase, trailing_command) or (None, "").

    Tries exact prefix match first, then fuzzy word-overlap scoring.
    trailing_command is the portion of text after the wake word (stripped).
    """
    norm_text = normalize_text(text)
    text_words = set(norm_text.split())

    # 1. Exact prefix match
    for w in wake_words:
        norm_w = normalize_text(w)
        if norm_text.startswith(norm_w):
            rest = norm_text[len(norm_w) :]
            if rest and not rest.startswith(" "):
                continue  # prefix of a longer word, not a boundary
            return w, rest.strip()

    # 2. Fuzzy word-overlap match
    best_phrase: str | None = None
    best_score = 0.0
    for w in wake_words:
        norm_w = normalize_text(w)
        phrase_words = [x for x in norm_w.split() if len(x) >= 3]
        if not phrase_words:
            phrase_words = norm_w.split()
        # Every phrase word must have a phonetic match in the transcript
        # (blocks "ehi come stai" and keyword-in-conversation false wakes) —
        # UNLESS the transcript is the distinctive keyword alone, which is an
        # intentional address ("galileo" → wake for "ehi galileo").
        if not all(
            any(_word_token_match(pw, tw) for tw in text_words) for pw in phrase_words
        ) and not _isolated_keyword_match(norm_text.split(), phrase_words):
            continue
        score = _word_overlap_score(phrase_words, text_words)
        if score > best_score:
            best_score = score
            best_phrase = w

    if best_score >= threshold and best_phrase is not None:
        # Strip wake word tokens from transcript to get trailing command
        norm_w = normalize_text(best_phrase)
        wake_tokens = set(norm_w.split())
        command = " ".join(
            t
            for t in norm_text.split()
            if not any(_word_token_match(wt, t) for wt in wake_tokens)
        )
        return best_phrase, command

    return None, ""


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
    """Fuzzy wake-word match for open-vocabulary backends.

    Exact alias-map lookup first; if that misses, scores each phrase by the
    fraction of its significant words (len >= 3) that appear anywhere in the
    transcript.  Returns the best-scoring group if score >= threshold, else None.

    Example: phrase "ehi galileo", transcript "e il galileo"
      key words: ["ehi", "galileo"]  →  both present → 0.7 → match
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
        if not all(
            any(_word_token_match(pw, tw) for tw in text_words) for pw in phrase_words
        ) and not _isolated_keyword_match(norm_text.split(), phrase_words):
            continue
        score = _word_overlap_score(phrase_words, text_words)
        if score > best_score:
            best_score = score
            best_group = group

    return best_group if best_score >= threshold else None
