## 1. Configuration Schema Updates

- [x] 1.1 Add `matching_algorithm: str = "token_set_ratio"` to `RecognitionConfig` dataclass in `alexa_custom/config.py`
- [x] 1.2 Add `matching_threshold: float = 70.0` to `RecognitionConfig` dataclass in `alexa_custom/config.py`
- [x] 1.3 Update `_parse_recognition_config` in `alexa_custom/config.py` to parse these keys, validating that `matching_algorithm` is one of `token_set_ratio`, `levenshtein`, or `ratio`
- [x] 1.4 Update `conf/config.yaml` to document these new options under `recognition:` with their default values
- [x] 1.5 Add `reply_matching_algorithm: str = "levenshtein"` and `reply_matching_threshold: float = 80.0` to `RecognitionConfig`, with the same algorithm validation
- [x] 1.6 Document the reply keys in `conf/config.yaml` and `conf.example/config.yaml` (note: 1.4 touched only `conf/config.yaml`; mirror the global keys into `conf.example/config.yaml` too)

## 2. Scorer Selection & Levenshtein Fallback

- [x] 2.1 Implement `levenshtein_distance(s1: str, s2: str) -> int` in `alexa_custom/actions.py` as a pure-Python edit distance function
- [x] 2.2 Implement `get_similarity_score(a: str, b: str, algorithm: str) -> float` in `alexa_custom/actions.py` to calculate similarity based on the chosen algorithm
- [x] 2.3 Update `match_trigger` in `alexa_custom/actions.py` to accept `algorithm` and `threshold` and use `get_similarity_score`
- [x] 2.4 Add the short-phrase exact-match guard: when the phonetically-normalized trigger phrase/alias is < 4 chars, require exact equality with the normalized transcription (score 100/0), regardless of algorithm

## 3. STT Loop Integration

- [x] 3.1 In `_single_stage_loop` inside `alexa_custom/stt.py`, pass `algorithm=config.recognition.matching_algorithm` and `threshold=config.recognition.matching_threshold` when calling `match_trigger`
- [x] 3.2 In `_wake_detected` inside `alexa_custom/stt.py`, pass `algorithm=config.recognition.matching_algorithm` and `threshold=config.recognition.matching_threshold` when calling `match_trigger`
- [x] 3.3 Wire the same global keys into the remaining wake-command `match_trigger` call sites in `stt.py` (`skip_unmatched_inline` check in `_recognition_loop`) — these gate the same trigger lists and must score consistently
- [x] 3.4 In `_run_action` (`alexa_custom/actions.py`, `on_reply` matching), pass `algorithm=config.recognition.reply_matching_algorithm` and `threshold=config.recognition.reply_matching_threshold`; thread the recognition config (or the two values) into the reply-matching path

## 4. Testing & Verification

- [x] 4.1 Create new unit tests in `tests/test_actions.py` verifying the pure-Python Levenshtein fallback and `get_similarity_score` for all algorithms
- [x] 4.2 Create integration tests in `tests/test_actions.py` verifying `match_trigger` with custom algorithms and thresholds
- [x] 4.3 Add tests for the short-phrase guard: `"si"` vs `"si"` matches; `"si"` vs `"se"` and `"si"` vs `"si grazie"` do not, under every algorithm
- [x] 4.4 Add a test that reply matching uses the reply keys while wake-command matching uses the global keys (per-context independence)
- [x] 4.5 Run the full test suite (`uv run pytest`) to ensure no regressions are introduced
