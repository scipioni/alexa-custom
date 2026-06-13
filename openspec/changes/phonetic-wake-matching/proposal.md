## Why

Italian Vosk STT models systematically misrecognise wake words due to phonetic confusions (double consonants, palatal clusters, word boundary errors). Currently only exact alias matching or word-overlap fuzzy matching (sherpa-onnx only) are supported, causing real wake attempts to be silently dropped.

## What Changes

- Add a phonetic normalisation step for Italian (collapse double consonants, normalise common confusions like `sci→si`, `gli→li`, `gn→n`)
- Add a Levenshtein-based fuzzy matcher using `rapidfuzz` on phonetically normalised text for the Vosk free-vocab path
- Add `phonetic_matching` and `phonetic_threshold` config options to `RecognitionConfig`
- Wire the new matcher into the Vosk free-vocab wake word detection in `_recognition_loop`
- Keep existing exact-matching path as fast first-pass; phonetic match fires only on miss

## Capabilities

### New Capabilities
- `phonetic-wake-matching`: Phonetic approximate matching for Vosk free-vocab wake word detection, with Italian-specific normalisation and configurable Levenshtein threshold

### Modified Capabilities

*(none — no existing spec is changing)*

## Impact

- `alexa_custom/stt_phonetics.py`: new `_phonetic_normalize()`, `_phonetic_wake_match()`
- `alexa_custom/stt.py`: modify `_extract_wake_command()` call in Vosk free-vocab path
- `alexa_custom/config.py`: add fields to `RecognitionConfig`
- `rapidfuzz` already a dependency — no new packages
- No breaking changes; default thresholds preserve existing behaviour
