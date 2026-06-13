## Context

Wake word detection in the Vosk free-vocab path (`_recognition_loop`, `vosk_use_grammar=false`) currently calls `_extract_wake_command(text, alias_map, fuzzy=False)`, which does an exact normalised string prefix match. Any STT transcription deviation — double/single consonant confusion, palatal cluster errors, word boundary splits — causes a silent miss. The sherpa-onnx path has `_approx_wake_match` (word-overlap heuristic) but this is not used for Vosk.

`rapidfuzz` (C-accelerated Levenshtein) is already a project dependency. The phonetic normalisation must be Italian-specific: Italian ASR models have predictable confusion patterns around geminate consonants, palatal sounds (`sci/sce`, `gli`, `gn`), and vowel weakening in unstressed positions.

## Goals / Non-Goals

**Goals:**
- Catch wake phrases misrecognised by Vosk free-vocab due to phonetic confusions
- Add configurable Levenshtein threshold via `RecognitionConfig`
- Keep exact match as zero-cost first pass; phonetic match only fires on miss
- Correctly extract the command portion of the transcript when a phonetic match succeeds

**Non-Goals:**
- No support for non-Italian phonetic normalisation (other languages use exact match only)
- No change to the Vosk grammar path (vosk_use_grammar=true) — grammar mode already constrains output
- No change to the sherpa-onnx path — it has its own fuzzy matcher
- No new external dependencies

## Decisions

**1. Italian phonetic normalisation rules**

Applied to both alias phrases and recognised text before Levenshtein comparison:

| Rule | Rationale |
|------|-----------|
| `(.)\1+ → \1` (collapse geminates) | Italian STT often hears single for double or vice versa |
| `sci → si`, `sce → se` | Palatal fricative common confusion |
| `gli → li`, `gni → ni` | Palatal lateral/nasal common confusion |
| `gn → n` | Velar nasal confusion |
| `chi → ci`, `che → ce` | Velar stop + palatal confusion |
| `ghi → gi`, `ghe → ge` | Same, voiced |
| `(a)` prefix optional | Dropped initial vowel in fast speech (e.g. `scoltami` for `ascoltami`) |

**2. `fuzz.ratio` with sliding prefix window**

The wake phrase must appear at the *start* of the utterance. We test a sliding window of word counts (from `len(wake_words)` to `len(wake_words)+2`) to handle word-boundary errors:

```
Wake:       "ascoltami assistente"   (2 parole)
Ricon.:     "ascolta insistente"     (2 parole) → finestra 2, ratio≈0.7 ✓
Ricon.:     "ascolta mi assistente"  (3 parole) → finestra 3, ratio≈0.8 ✓
```

The command is extracted from the original (non-normalised) text by skipping the matched word count.

**3. Default threshold of 0.6**

Tuned to catch common confusions without false positives:
- `ascolta insistente` vs `ascoltami assistente` → ~0.7 ✓
- `arresta il sistema` vs `ascoltami assistente` → ~0.4 ✗
- `scoltami assistente` vs `ascoltami assistente` → ~0.8 ✓

**4. Hook in `_extract_wake_command`**

Add a `phonetic` parameter (bool) and `phonetic_threshold` (float). When `phonetic=True` and exact match fails, fall through to `_phonetic_wake_match`. The Vosk free-vocab caller passes `config.recognition.phonetic_matching` and `config.recognition.phonetic_threshold`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **False positives**: phonetic normalisation makes distinct wake phrases collide | Low threshold (0.6) + exact match always tried first. If collision in alias_map, user can adjust threshold per phrase. |
| **Command extraction wrong**: phonetic match consumes wrong word count, producing garbage command | Sliding window tests 3 lengths; best ratio wins. Worst case: no match → standard timeout behaviour. |
| **Performance**: Levenshtein on every Vosk segment | `rapidfuzz.fuzz.ratio` is C-accelerated; text is <20 words. Cost is ~1µs per alias pair, negligible vs STT inference. |
| **Non-Italian wake words**: normalisation rules are Italian-specific | Phonetic matching is opt-in per group (default off, configurable). Non-Italian groups see no change. |
