# Capability: Actions File

## Purpose
Manage learned and user-defined triggers in a separate actions file to decouple them from the main configuration.

## Requirements

### Requirement: actions.yaml schema with global and per-wake-word triggers
Each action file in `conf/actions/` SHALL support the following top-level keys:

- `triggers`: flat list of trigger entries; each trigger MAY include a `wake_words` field to declare its scope (see trigger-wake-words capability). Triggers with no `wake_words` field or `wake_words: [global]` are global fallbacks; triggers with `wake_words: []` are direct-match; triggers with named ids are scoped to those wake-word groups.
- `on_startup`: list of action entries — **only honoured in `system.yaml`; ignored in all other files**

A trigger entry MAY include an optional `follow_up` boolean field that overrides the global `recognition.follow_up` setting for that trigger (see the follow-up-conversation capability): `follow_up: true` forces a follow-up window after that command even when the global switch is off; `follow_up: false` suppresses the follow-up window even when the global switch is on; when the field is absent the trigger inherits the global setting.

The `wake_triggers` top-level key is no longer supported. The `direct_match` field on trigger entries is no longer supported.

#### Scenario: Global triggers loaded from user.yaml
- **WHEN** `conf/actions/user.yaml` contains a `triggers:` list with no `wake_words` field on entries
- **THEN** those triggers are available as global fallback for all wake word groups

#### Scenario: Per-wake-word triggers declared inline via wake_words
- **WHEN** `conf/actions/home.yaml` contains a trigger with `wake_words: [galileo]`
- **THEN** that trigger is appended to the `galileo` group's trigger list only

#### Scenario: Direct-match trigger declared via wake_words
- **WHEN** `conf/actions/user.yaml` contains a trigger with `wake_words: []`
- **THEN** that trigger is placed in `ActionsConfig.direct_triggers` and fires from stage-1 STT without a wake word

#### Scenario: Unknown wake word key in wake_triggers (removed key)
- **WHEN** any action file contains a `wake_triggers:` top-level key
- **THEN** the key is ignored with a warning log; triggers within it are not loaded

#### Scenario: Per-trigger follow_up override parsed
- **WHEN** a trigger entry sets `follow_up: false`
- **THEN** `Trigger.follow_up` is `False` and that command does not open a follow-up window even when `recognition.follow_up` is `true`

#### Scenario: Trigger without follow_up inherits global
- **WHEN** a trigger entry omits the `follow_up` field
- **THEN** `Trigger.follow_up` is `None` and follow-up behavior for that command is governed by `recognition.follow_up`

## Removed Requirements

### Requirement: direct_match flag on trigger entries
**Reason**: Replaced by `wake_words: []` semantics. The `direct_match: true` flag was a per-trigger boolean that caused stage-1 firing; `wake_words: []` is the canonical replacement.
**Migration**: Replace `direct_match: true` on a trigger with `wake_words: []`. Remove the `direct_match` key entirely from all trigger entries.

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
