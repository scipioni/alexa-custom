## Why

Stage-2 command matching today relies solely on fuzzy phonetic similarity against each trigger's `phrase` and `aliases`. Covering all the ways a user might phrase a command (`"accendi le luci"`, `"accendimi le luci"`, `"vorrei che tu accenda tutte le luci del salotto"`) means enumerating many literal aliases. A single word-level pattern — "a word starting with `accend`, then any words, then `luci`" — expresses the whole family at once and matches more permissively, without loosening the fuzzy threshold globally.

## What Changes

- `Trigger` gains an optional `patterns: list[str]` field, parsed from `config.yaml` / `actions.yaml`.
- A **word-glob DSL** is introduced for pattern strings:
  - Pattern is a sequence of space-separated tokens.
  - `foo*` matches a transcript word that begins with `foo` (`*` is a glob wildcard inside a token — prefix/infix — **not** a character-level regex quantifier).
  - A standalone `*` token matches any number of intervening words (the "`.*`" gap).
  - Each literal token is matched **phonetically** via the existing `italian_phonetic()` + `get_similarity_score()` machinery against the configured `matching_threshold`, so `luci`≈`luce` still matches — robustness to STT noise is preserved.
  - Matching is a fuzzy ordered-subsequence walk: pattern tokens are aligned in order over the transcript tokens, with `*` swallowing gaps.
- `match_trigger()` tries patterns **first**; a pattern hit is definitive (that trigger is selected, no fuzzy scoring needed). When a trigger has no `patterns`, or none match, behavior falls back to today's fuzzy phrase/alias scoring.
- Fully backward-compatible: triggers without a `patterns` field behave exactly as today.

Out of scope (explicitly decided during exploration): no time-window / "in N seconds" constraint, no per-rule window field, no changes to stage-2 capture (`capture_transcript`), no word timestamps, no changes to stage-1 / wake-word detection, no always-on / wake-gate-bypass detection.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `action-dispatch`: the trigger-matching behavior gains a word-glob pattern path that is evaluated before, and takes precedence over, the existing fuzzy phrase matching.

## Impact

- **Code**: `alexa_custom/actions.py` (`match_trigger`, new glob-matcher helper; reuses `normalize_text`, `italian_phonetic`, `get_similarity_score`); `alexa_custom/config.py` (`Trigger` dataclass, trigger parsing).
- **Config**: new optional `patterns:` key on trigger entries in `config.yaml` and `actions.yaml`. No migration required for existing configs.
- **Tests**: `tests/test_actions.py` (glob DSL semantics, phonetic token matching, precedence over fuzzy, backward compatibility).
- **Dependencies**: none added — reuses existing `rapidfuzz` / phonetic stack.
