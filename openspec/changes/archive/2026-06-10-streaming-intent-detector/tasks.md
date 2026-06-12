## 1. Config

- [x] 1.1 Add `partial_matching: bool = True`, `partial_stability_ms: int = 150`, `partial_stability_reads: int = 3` to `RecognitionConfig` in `alexa_custom/config.py`
- [x] 1.2 Add the three new keys to `conf/config.yaml` under `recognition:` as commented-out defaults with descriptions

## 2. Intent Map

- [x] 2.1 Add `build_intent_map(alias_map, global_triggers)` to `alexa_custom/stt_phonetics.py` — returns `dict[str, tuple[WakeWordGroup, Trigger]]` keyed by `normalize_text(wake_phrase + " " + trigger_phrase)` for all alias × trigger combos (use `_resolve_triggers` for per-group vs global trigger selection)
- [x] 2.2 Add unit tests for `build_intent_map` covering: per-group triggers shadow globals, aliases included, empty triggers returns empty map

## 3. Matching Function

- [x] 3.1 Add `_match_full_intent(partial, alias_map, intent_map)` to `alexa_custom/stt.py` — calls `_extract_wake_command(partial, alias_map, fuzzy=False)`, returns `(WakeWordGroup, Trigger, inline_cmd)` or `None`; exact normalized comparison against trigger phrases and aliases
- [x] 3.2 Add unit tests for `_match_full_intent` covering: full match returns tuple, wake-only returns None, unknown command returns None, trigger alias matched, fuzzy not applied

## 4. Stage-1 Loop Integration

- [x] 4.1 In `_run_stt_loop` (`alexa_custom/stt.py`): build `intent_map` from `alias_map` + global triggers at startup (alongside existing `alias_map` build)
- [x] 4.2 Rebuild `intent_map` in the hot-reload block when stage-1 config or wake words change
- [x] 4.3 Add stability tracking variables (`_partial_stable_key`, `_partial_stable_reads`, `_partial_stable_since`) as nonlocals in the Vosk free-vocab branch of `_run_stt_loop`
- [x] 4.4 Insert the partial-matching early-exit block in the Vosk free-vocab branch: guard on `config.recognition.partial_matching and not vosk_use_grammar`, call `_match_full_intent`, check stability, call `_wake_detected` with `pre_transcript=inline_cmd` and `backend=stage2_backend`, reset stage-1 state, `continue`
- [x] 4.5 Reset stability state in the existing `_reset_stage1()` inner function

## 5. Validation

- [x] 5.1 Run targeted tests: `uv run pytest tests/test_wake_detection.py tests/test_stt.py` — confirm no regressions
- [x] 5.2 Manual smoke test: say "ehi galileo chiama stefano" in one breath — verify action fires without waiting for VAD silence
- [x] 5.3 Manual smoke test: say "ehi galileo" alone — verify mode-1 fallback still works (beep plays, waits for command)
