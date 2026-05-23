## Why

The current flat `wake_words` list treats all wake words as equivalent entry points to a single shared trigger table. This prevents building context-aware assistants where different wake words should invoke different command sets (e.g., "galileo" for home automation, "assistente" for communication).

## What Changes

- **BREAKING** `wake_words` in `config.yaml` changes from a flat list of strings to a list of wake word group objects, each with a `word`, optional `aliases`, and optional `triggers`
- Add a top-level `triggers` list as a global fallback used when a wake word group defines no triggers of its own
- `config.py` gains a `WakeWordGroup` dataclass; `ActionsConfig` is updated accordingly
- `stt.py` resolves the detected wake word to its group and uses that group's trigger list (or the fallback) for command matching

## Capabilities

### New Capabilities

*(none)*

### Modified Capabilities

- `wake-word-detection`: Wake word detection now resolves to a named group; command window uses per-group triggers with global fallback
- `yaml-config`: `wake_words` schema changes from flat string list to list of group objects; top-level `triggers` becomes an optional global fallback

## Impact

- **`alexa_custom/config.py`**: new `WakeWordGroup` dataclass; `ActionsConfig.wake_words` changes type from `list[str]` to `list[WakeWordGroup]`; `ActionsConfig.triggers` becomes an optional global fallback (may be empty)
- **`alexa_custom/stt.py`**: grammar built from all words + aliases across all groups; wake detection maps matched text back to its `WakeWordGroup`; trigger lookup uses group triggers with fallback to global
- **`config.yaml.example`**: updated to illustrate new schema with aliases and per-group triggers
- **`tests/`**: any tests referencing `config.wake_words` as a list of strings need updating
