## 1. Config Schema (config.py)

- [x] 1.1 Add `WakeWordGroup` dataclass with fields `word: str`, `aliases: list[str]`, `triggers: list[Trigger]`
- [x] 1.2 Update `ActionsConfig` — change `wake_words` from `list[str]` to `list[WakeWordGroup]`; keep `triggers: list[Trigger]` as global fallback (default empty)
- [x] 1.3 Add `_parse_wake_word_groups(raw, source)` function: validate each entry is a dict with required `word` string, parse optional `aliases` and `triggers`, log warning on duplicate aliases
- [x] 1.4 Update `_parse_actions_config` to call `_parse_wake_word_groups` instead of the current flat-list parse; reject bare strings with a clear error
- [x] 1.5 Update `load_config` error messages referencing old wake_words format

## 2. STT Updates (stt.py)

- [x] 2.1 Update `_grammar_json` signature from `list[str]` to `list[WakeWordGroup]`; flatten `word` + `aliases` from all groups
- [x] 2.2 Add `_build_alias_map(groups: list[WakeWordGroup]) -> dict[str, WakeWordGroup]` — maps `normalize_text(phrase) → group` for word and all aliases
- [x] 2.3 Add `_resolve_triggers(group: WakeWordGroup, fallback: list[Trigger]) -> list[Trigger]` — returns `group.triggers or fallback`
- [x] 2.4 Update two-stage wake detection loop: replace `next(w for w in config.wake_words ...)` lookup with `alias_map.get(norm_text)`; rebuild alias map after each hot-reload
- [x] 2.5 Update `_extract_wake_command` (single-stage): change signature to accept `alias_map: dict[str, WakeWordGroup]`; return `(WakeWordGroup | None, str)` instead of `(str, str)`
- [x] 2.6 Update all `match_trigger(command, config.triggers)` call sites to use `_resolve_triggers(matched_group, config.triggers)`
- [x] 2.7 Update `on_stt_event("listening", ...)` payload: `wake_words` key should list primary `word` values (not aliases)
- [x] 2.8 Rebuild alias map whenever config is reloaded (hot-reload path in the STT loop)

## 3. Config Example & Tests

- [x] 3.1 Update `config.yaml.example` — replace flat `wake_words` list with group objects showing `word`, `aliases`, and per-group `triggers`; add global `triggers` fallback section with comment
- [x] 3.2 Update `tests/test_config.py` — fix any `ActionsConfig(wake_words=[...])` constructions to use `WakeWordGroup` objects
