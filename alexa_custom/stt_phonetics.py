from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alexa_custom.config import WakeWordGroup, Trigger

from alexa_custom.actions import normalize_text


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


def build_intent_map(
    alias_map: dict[str, "WakeWordGroup"],
    global_triggers: list["Trigger"],
) -> dict[str, tuple["WakeWordGroup", "Trigger"]]:
    """Build a flat map of normalized (wake + trigger) strings → (group, trigger).

    Used by the streaming intent detector to match full intents in Vosk partials
    without waiting for VAD silence.
    """
    intent_map: dict[str, tuple[WakeWordGroup, Trigger]] = {}
    seen_groups: set[int] = set()
    for norm_wake, group in alias_map.items():
        group_id = id(group)
        triggers = _resolve_triggers(group, global_triggers)
        for trigger in triggers:
            for phrase in [trigger.phrase] + trigger.aliases:
                key = normalize_text(f"{norm_wake} {phrase}")
                intent_map[key] = (group, trigger)
        seen_groups.add(group_id)
    return intent_map
