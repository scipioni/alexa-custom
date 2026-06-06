## 1. Dependency

- [x] 1.1 Add `rapidfuzz` to `pyproject.toml` dependencies and install it in the venv

## 2. Implement italian_phonetic()

- [x] 2.1 Add `italian_phonetic(text: str) -> str` to `alexa_custom/actions.py` applying the 8 normalization rules in order (geminates, gli, gn, sch, sci/sce, ch+e/i, gh+e/i, qu)
- [x] 2.2 Add `import re` to `actions.py` if not already present

## 3. Update match_trigger()

- [x] 3.1 In `match_trigger()`, replace `difflib.SequenceMatcher` scoring with `rapidfuzz.fuzz.token_set_ratio` on `italian_phonetic()`-normalized strings; adjust threshold comparison from `>= 0.70` to `>= 70`
- [x] 3.2 Add a try/import guard: if `rapidfuzz` is unavailable log a warning and fall back to `difflib.SequenceMatcher` with threshold 0.70

## 4. Tests

- [x] 4.1 Add unit tests for `italian_phonetic()` covering: geminate reduction, `ch`→`k`, `gli`→`li`, `gn`→`n`, `qu`→`k`, diacritic passthrough
- [x] 4.2 Add unit tests for `match_trigger()` covering: extra-word match ("mi chiama" → "chiama"), phonetic-variant match ("ke fai" → "che fai"), below-threshold miss

## 5. Verify

- [x] 5.1 Run `task test` — confirm no regressions
- [x] 5.2 Run `task lint` — confirm clean
