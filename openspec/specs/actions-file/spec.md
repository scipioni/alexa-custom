# Capability: Actions File

## Purpose
Manage learned and user-defined triggers in a separate actions file to decouple them from the main configuration.

## Requirements

### Requirement: actions.yaml schema with global and per-wake-word triggers
Each action file in `conf/actions/` SHALL support the same top-level keys as the previous `actions.yaml`, with one addition:

- `triggers`: list of global fallback triggers (unchanged schema)
- `wake_triggers`: mapping of wake word string → list of triggers (unchanged schema)
- `on_startup`: list of action entries — **only honoured in `system.yaml`; ignored in all other files**

#### Scenario: Global triggers loaded from user.yaml
- **WHEN** `conf/actions/user.yaml` contains a `triggers:` list
- **THEN** those triggers are available as global fallback for all wake word groups

#### Scenario: Per-wake-word triggers loaded from home.yaml
- **WHEN** `conf/actions/home.yaml` contains `wake_triggers.galileo:` with a trigger list
- **THEN** those triggers are appended to the `galileo` group's trigger list (after system.yaml's entries)

#### Scenario: Unknown wake word key in wake_triggers
- **WHEN** any action file has `wake_triggers.unknown_word:` and no matching group exists in `conf/config.yaml`
- **THEN** the entry is silently ignored and a debug log is emitted

### Requirement: Atomic writes to learn_file
`ActionsFileStore.save()` SHALL write to a temporary file in the same directory as `learn_file` and atomically rename it over the target path. This applies to `conf/actions/learned.yaml` by default.

#### Scenario: Concurrent hot-reload during write to learned.yaml
- **WHEN** the learning agent writes a new command while the hot-reload watcher polls
- **THEN** the watcher reads either the old complete file or the new complete file — never a partial write

### Requirement: learn_file auto-created on first write
If the `learn_file` does not exist when the `llm_learn` action writes a new command, the system SHALL create the file with appropriate YAML structure (header comment + triggers list).

#### Scenario: learned.yaml created on first llm_learn
- **WHEN** `llm_learn` is triggered for the first time and `conf/actions/learned.yaml` does not exist
- **THEN** the file is created with the new trigger as its first entry; no error is raised
