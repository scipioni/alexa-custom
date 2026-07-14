## 1. Config surface

- [x] 1.1 Add `patterns: list[str] = field(default_factory=list)` to the `Trigger` dataclass in `alexa_custom/config.py`
- [x] 1.2 Parse an optional `patterns` key in trigger parsing (~line 327): validate it is a list, coerce items to strings (mirror the `aliases` handling), default to `[]` when absent
- [x] 1.3 Confirm both inline `config.yaml` triggers and `actions.yaml` triggers pick up `patterns` (shared parsing path)

## 2. Glob matcher

- [x] 2.1 Add a helper in `alexa_custom/actions.py` (e.g. `_match_glob_pattern(pattern: str, transcript: str) -> bool`) implementing the fuzzy ordered-subsequence walk
- [x] 2.2 Tokenize pattern and transcript on whitespace; phonetically normalize transcript words via `italian_phonetic()`
- [x] 2.3 Implement token semantics: standalone `*` = zero-or-more word gap (with backtracking so later anchors align); `foo*` = phonetic prefix match; literal token = phonetic similarity ≥ `matching_threshold` via `get_similarity_score()` with `matching_algorithm`
- [x] 2.4 Add a `_trigger_matches_patterns(trigger, transcript, algorithm, threshold) -> bool` wrapper that returns True if any of the trigger's patterns match

## 3. Wire into match_trigger

- [x] 3.1 In `match_trigger()`, before fuzzy scoring, iterate triggers and return the first whose `patterns` match (definitive)
- [x] 3.2 If no pattern matches, run the existing fuzzy best-score selection unchanged over the full trigger list
- [x] 3.3 Thread `algorithm`/`threshold` (already parameters of `match_trigger`) into the pattern check; log pattern hits like fuzzy hits

## 4. Tests

- [x] 4.1 `tests/test_actions.py`: prefix wildcard + word gap matches (`accend* * luci` vs `accendi le luci del salotto`)
- [x] 4.2 Standalone `*` matching a single intervening word and zero words
- [x] 4.3 Phonetic tolerance on a literal token (`luci` pattern vs `luce` transcript)
- [x] 4.4 Order enforcement: `luci accendi` does NOT match `accend* * luci`
- [x] 4.5 Precedence: pattern hit wins over a higher-scoring fuzzy trigger
- [x] 4.6 Backward compatibility: trigger with no `patterns` behaves identically to today (existing fuzzy scenarios still pass)
- [x] 4.7 Config parsing test: `patterns` absent → `[]`; non-list `patterns` → ConfigError

## 5. Docs & validation

- [x] 5.1 Document the `patterns` key (syntax + an example) in config comments / `docs/`
- [x] 5.2 Run `task test` and `task lint` for final validation
