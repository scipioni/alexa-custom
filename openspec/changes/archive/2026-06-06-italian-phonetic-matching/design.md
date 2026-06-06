## Context

`match_trigger()` in `actions.py` compares normalized transcriptions to trigger phrases using `difflib.SequenceMatcher.ratio()` with a threshold of 0.70. Two failure modes are common with Italian voice commands:

1. **Extra surrounding words**: STT transcripts often include leading articles or particles ("mi chiama" instead of "chiama", "sì voglio" instead of "sì"). `SequenceMatcher` on full strings penalizes these heavily even when the trigger word is clearly present.

2. **Phonetic spelling variants**: Italian orthography is regular but ASR models can produce alternative spellings for the same sound ("ch" vs "k", "gli" vs "li", double vs single consonants). `SequenceMatcher` treats these as distinct character sequences.

`_approx_wake_match()` in `stt.py` (used for sherpa-onnx open-vocabulary wake words) has the same plain-text bias but is a separate code path not touched here.

## Goals / Non-Goals

**Goals:**
- Handle common Italian STT transcription noise (extra words, phonetic variants) without requiring a new ML model.
- No change to the `config.yaml` schema or public API surface.
- Minimal added latency (matching happens per-command, not in the audio loop).

**Non-Goals:**
- Full Italian phoneme-to-grapheme mapping (Metaphone/Soundex for Italian — over-engineered for this use case).
- Changing `_approx_wake_match()` wake-word detection — that path already uses word-overlap scoring and is tuned separately.
- Cloud-based NLU or embedding-based matching.

## Decisions

### D1: `rapidfuzz.fuzz.token_set_ratio` over `difflib.SequenceMatcher`

`token_set_ratio` takes the intersection of token sets and the sorted union, scores each independently, and returns the highest. This means "mi chiama" vs "chiama" scores 100 (the trigger word is fully contained). `SequenceMatcher` on the same pair scores ~0.67 (below the threshold).

Alternative considered: `token_sort_ratio` — handles reordering but still penalizes extra tokens. Rejected: `token_set_ratio` is a strict superset.

Alternative considered: keep `difflib` and add token-overlap pre-filtering. Rejected: more code, no better than `rapidfuzz` which handles both in one call.

`rapidfuzz` is pure-Python with an optional C extension, small, well-maintained, and already in many Python audio/NLP stacks. No heavyweight ML dependency.

### D2: Apply `italian_phonetic()` before `token_set_ratio`

`italian_phonetic()` is a deterministic regex-based rewrite that maps common Italian spelling variants to a canonical phoneme-approximate form:
- Geminate consonants → single (`ll`→`l`, `pp`→`p`, etc.)
- `gli` → `li`, `gn` → `n`
- `ch`+e/i → `k`+e/i, `gh`+e/i → `g`+e/i
- `sci`/`sce` → `si`/`se`
- `qu` → `k`

Applied to both sides of the comparison, so "chiamami" and "kiamami" normalize to the same string, and `token_set_ratio` then scores them 100.

Alternative considered: only apply phonetic normalization. Rejected: still fails on extra-word case without token-set ratio.

Alternative considered: only apply `token_set_ratio` without phonetic normalization. Accepted as a meaningful improvement on its own, but combining both catches more edge cases at negligible extra cost.

### D3: Threshold stays at 70 (out of 100)

`token_set_ratio` returns 0–100; the existing threshold semantics map directly (0.70 → 70). No config change needed.

### D4: `italian_phonetic()` placed in `actions.py`, not `stt.py`

It belongs next to `normalize_text()` and `match_trigger()` — all text normalization lives in `actions.py`. `stt.py` imports `match_trigger` from there already.

## Risks / Trade-offs

[`token_set_ratio` is more permissive] → A very short trigger word (e.g., "sì") inside a long transcript always scores 100. Mitigation: the token-set algorithm uses the sorted intersection, so a 1-token trigger vs a 10-token transcript scores based on the 1-token match, which is already the desired behaviour (we want "sì" to match even with surrounding words).

[Phonetic normalization false positives] → "chiama" and "diama" both reduce to "kiama"/"diama" — different. Risk is low because the rule set is conservative (no vowel merging, no consonant-cluster collapse beyond what's listed).

[`rapidfuzz` not installed] → `match_trigger()` guards with a try/import and falls back to `difflib.SequenceMatcher` with a warning if `rapidfuzz` is absent. Dependency added to `pyproject.toml` so this should never happen in practice.
