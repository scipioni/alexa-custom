## 1. Phonetic Normalisation

- [x] 1.1 Add `_phonetic_normalize(text: str) -> str` to `stt_phonetics.py` with Italian-specific rules (collapse double consonants, palatal normalisation, prefix elision)
- [x] 1.2 Add `_phonetic_wake_match(text, alias_map, threshold) -> tuple[WakeWordGroup | None, str]` to `stt_phonetics.py` using `rapidfuzz.fuzz.ratio` with sliding prefix window for command extraction

## 2. Configuration

- [x] 2.1 Add `phonetic_matching: bool = True` field to `RecognitionConfig` in `config.py`
- [x] 2.2 Add `phonetic_threshold: float = 0.6` field to `RecognitionConfig`
- [x] 2.3 Parse `phonetic_matching` and `phonetic_threshold` from raw YAML in `_parse_recognition_config()`

## 3. Wiring in STT Pipeline

- [x] 3.1 Add `phonetic` and `phonetic_threshold` parameters to `_extract_wake_command()` in `stt.py`; call `_phonetic_wake_match()` when exact match fails and `phonetic=True`
- [x] 3.2 Update Vosk free-vocab call site in `_recognition_loop` to pass `phonetic=config.recognition.phonetic_matching` and `phonetic_threshold=config.recognition.phonetic_threshold`

## 4. Tests

- [x] 4.1 Add tests for `_phonetic_normalize`: double consonants, palatal clusters, word boundary cases
- [x] 4.2 Add tests for `_phonetic_wake_match`: above-threshold hit, below-threshold rejection, command extraction, exact match still takes priority
