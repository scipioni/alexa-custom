## Why

While `Token Set Ratio` (bag-of-tokens) matching is highly effective for long, natural-language command phrases by ignoring word ordering and extra filler words, it is ill-suited for short reply phrases (e.g., "si", "no" in multi-turn `ask` triggers). For short reply phrases, strict character edit-distance (Levenshtein) is far superior and yields fewer false-positives and more intuitive matches. Making the trigger-matching algorithm and threshold configurable allows users to tune the voice assistant to their specific workflow requirements and locale quirks.

## What Changes

- Add four new configuration keys under the `recognition` block in `conf/config.yaml`:
  - `matching_algorithm`: trigger matching strategy for wake-word commands (`token_set_ratio` | `levenshtein` | `ratio`). Defaults to `token_set_ratio`.
  - `matching_threshold`: required similarity threshold as a percentage (`0`–`100`) for wake-word commands. Defaults to `70`.
  - `reply_matching_algorithm`: matching strategy for `on_reply` phrases in interactive `ask` loops. Defaults to `levenshtein` — replies are short and safety-sensitive, so strict matching is the correct default independent of the global setting.
  - `reply_matching_threshold`: similarity threshold for reply matching. Defaults to `80`.
- Update `match_trigger` to dynamically select the requested matching algorithm and apply the custom threshold.
- Wire the reply-matching call site (`_run_action` → `match_trigger(transcript, action.on_reply)`) to the reply-specific keys, and the wake-trigger call sites in `stt.py` to the global keys.
- Guard against degenerate percentage scores on very short phrases: when the phonetically-normalized trigger phrase is shorter than 4 characters, matching requires exact equality (a percentage threshold is effectively binary at that length — one edit on a 2-character word is a 50-point swing).
- Implement a pure-Python Levenshtein distance fallback algorithm to ensure 100% portability on headless devices when `rapidfuzz` is not installed or when running tests without external C-extensions.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `action-dispatch`: Extend fuzzy phrase matching to support configurable algorithms (`token_set_ratio`, `levenshtein`, `ratio`) and threshold, rather than being hardcoded to `token_set_ratio` and 70.

## Impact

- **`alexa_custom/config.py`**: Extend `RecognitionConfig` and `_parse_recognition_config` to parse and store `matching_algorithm`, `matching_threshold`, `reply_matching_algorithm`, and `reply_matching_threshold`.
- **`alexa_custom/actions.py`**: Update `match_trigger()` and introduce a robust dynamic scorer selection including a pure-Python Levenshtein distance fallback and the short-phrase exact-match guard; pass reply-specific algorithm/threshold at the `on_reply` call site in `_run_action`.
- **`conf/config.yaml`**: Document the new configuration options with default values.
- **`tests/test_actions.py`**: Add comprehensive tests for different algorithms, thresholds, and fallback paths.
