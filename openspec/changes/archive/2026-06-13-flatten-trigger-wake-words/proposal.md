## Why

The current action-file schema requires authors to split trigger definitions across two separate top-level keys (`triggers` for global scope and `wake_triggers` for per-wake-word scope), and relies on a `direct_match: true` flag scattered across individual trigger entries. This makes it hard to see at a glance which wake word a trigger belongs to, impossible to assign one trigger to multiple specific wake words, and requires knowing the schema split before writing any trigger.

## What Changes

- **NEW**: `Trigger` gains an optional `wake_words` field (list of strings).
  - absent or `[global]` → trigger is active after any wake word (same as current global `triggers:`)
  - `[]` (empty list) → trigger fires without a wake word from stage-1 STT (replaces `direct_match: true`)
  - `[id1, id2, ...]` → trigger is scoped to those specific wake-word group IDs
- **BREAKING**: `wake_triggers:` top-level key in action files is removed; use `wake_words` on each trigger instead.
- **BREAKING**: `direct_match: true` flag on triggers is removed; use `wake_words: []` instead.
- **NEW**: `ActionsConfig.direct_triggers: list[Trigger]` field holds triggers resolved to direct-match scope.
- **KEPT**: Inline `triggers:` inside `wake_words:` groups in `config.yaml` are unchanged.
- `ActionsData.wake_triggers` dict is removed from the internal data model.
- **NEW**: Action files (`conf/actions/*.yaml`) MAY define a top-level `wake_words:` list to declare additional wake word groups, using the same schema as `config.yaml`. Groups are merged in load order; duplicate ids are skipped with a warning.
- **BREAKING**: `conf/user.yaml` (the special file next to `config.yaml` used solely for extra wake word groups) is removed. Its content should be moved to a `wake_words:` key in any `conf/actions/*.yaml` file (e.g. `conf/actions/user.yaml`).
- `conf.example/` is refactored to reflect the new schema end-to-end: `user.yaml` removed, `actions/user.yaml` rewritten as a self-contained example using `wake_words:` + flat `triggers:` with `wake_words` fields.
- All documentation (`docs/`, `CLAUDE.md`) is updated to reflect the new trigger schema, removal of `conf/user.yaml`, and the unified `wake_words` field.

## Capabilities

### New Capabilities

- `trigger-wake-words`: Per-trigger wake-word scoping via `wake_words` field — replaces the `wake_triggers` dict and `direct_match` flag with a unified, flat trigger list.

### Modified Capabilities

- `actions-file`: The action-file schema changes — `wake_triggers` key removed, `direct_match` flag removed, `wake_words` field added to trigger entries, top-level `wake_words:` list added for defining new wake word groups.
- `action-dispatch`: Direct-match trigger resolution moves from `direct_match: bool` flag to `wake_words: []` semantics; `ActionsConfig.direct_triggers` replaces the per-trigger flag check.

## Impact

- `alexa_custom/config.py`: `Trigger` dataclass, `ActionsData`, `ActionsConfig`, `_parse_triggers`, `_load_actions_dir`, `_parse_actions_config`, `_merge_user_wake_words` (removed)
- `alexa_custom/client.py`: direct-match trigger lookup (currently filters on `trigger.direct_match`)
- `alexa_custom/actions.py`: any code referencing `direct_match` on trigger objects
- `conf.example/user.yaml`: removed (content moves to `conf.example/actions/user.yaml`)
- `conf.example/actions/user.yaml`: updated to new schema; gains `wake_words:` section
- `conf.example/config.yaml`: remove reference to `conf/user.yaml` in comments; update `wake_triggers` / `direct_match` references
- `tests/test_actions.py`, `tests/test_*.py`: test fixtures using `direct_match` or `wake_triggers`
- `docs/`: update any documentation referencing `wake_triggers`, `direct_match`, or `conf/user.yaml`
- `CLAUDE.md`: update Configuration section schema examples to reflect new trigger format
