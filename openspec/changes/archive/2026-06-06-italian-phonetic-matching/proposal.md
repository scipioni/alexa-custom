## Why

`match_trigger()` uses `difflib.SequenceMatcher` on plain normalized text, which penalizes partial matches (extra words around the trigger phrase) and is blind to Italian phonetic substitutions (e.g., "ch"→"k", double consonants, "gli"→"li"). Voice commands in Italian are often transcribed with leading/trailing words or mild phonetic drift, causing misses at the default 0.70 threshold.

## What Changes

- A new `italian_phonetic()` normalization function reduces Italian text to a rough phoneme representation (consolidates digraphs, deduplicates geminates, etc.) before comparison.
- `match_trigger()` scores each trigger using `rapidfuzz.fuzz.token_set_ratio` on phonetically-normalized strings instead of `difflib.SequenceMatcher` on plain strings. Token-set ratio handles extra surrounding words and partial matches that SequenceMatcher misses.
- `rapidfuzz` added as a project dependency.

## Capabilities

### New Capabilities

- `italian-phonetic-normalization`: A deterministic, zero-dependency normalization step that maps Italian text to a canonical phoneme string, making acoustically equivalent variants compare as equal or near-equal.

### Modified Capabilities

- `action-dispatch`: The "Fuzzy phrase matching" requirement changes — matching algorithm switches from `difflib.SequenceMatcher` to `rapidfuzz.fuzz.token_set_ratio` on phonetically-normalized text; threshold semantics change from a 0–1 ratio to a 0–100 score.

## Impact

- `alexa_custom/actions.py` — `normalize_text()`, `match_trigger()`, and `_approx_wake_match()` updated; new `italian_phonetic()` function added.
- `pyproject.toml` / `requirements*.txt` — `rapidfuzz` added.
- No changes to config schema or public API.
