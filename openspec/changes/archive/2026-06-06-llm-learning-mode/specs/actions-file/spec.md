## ADDED Requirements

### Requirement: `actions.yaml` schema with global and per-wake-word triggers
The system SHALL support an `actions.yaml` file with two optional top-level keys:
- `triggers`: list of global fallback triggers (same schema as the existing `triggers:` key in `config.yaml`)
- `wake_triggers`: mapping of wake word string → list of triggers (per-wake-word overrides)

#### Scenario: Global triggers loaded from actions.yaml
- **WHEN** `actions.yaml` contains a `triggers:` list and `config.yaml` has `actions_file: actions.yaml`
- **THEN** those triggers are available as global fallback for all wake word groups

#### Scenario: Per-wake-word triggers loaded from actions.yaml
- **WHEN** `actions.yaml` contains `wake_triggers.galileo:` with a trigger list
- **THEN** those triggers override the global list for the `galileo` wake word group

#### Scenario: Unknown wake word key in wake_triggers
- **WHEN** `actions.yaml` has `wake_triggers.unknown_word:` and no matching group exists in `config.yaml`
- **THEN** the entry is silently ignored and a debug log is emitted

### Requirement: `actions_file` key in `config.yaml`
The system SHALL accept an optional `actions_file:` top-level key in `config.yaml` specifying a path (relative to `config.yaml` or absolute) to an `actions.yaml` file. When present and the file exists, the loader merges its contents into the active config.

#### Scenario: actions_file path resolved relative to config.yaml
- **WHEN** `config.yaml` is at `/home/user/alexa/config.yaml` and `actions_file: actions.yaml`
- **THEN** the system loads `/home/user/alexa/actions.yaml`

#### Scenario: actions_file absent or path does not exist
- **WHEN** `actions_file:` is set but the referenced file does not exist
- **THEN** the system starts normally with a warning log; no error is raised

### Requirement: Merge strategy — `actions.yaml` appends after inline config
The loader SHALL append triggers from `actions.yaml` **after** any inline triggers already present in `config.yaml` or the wake word group. Inline entries take matching precedence (fuzzy match finds the first best score).

#### Scenario: Inline trigger wins over actions.yaml trigger with same phrase
- **WHEN** both `config.yaml` and `actions.yaml` define a trigger for "test"
- **THEN** both are present in the active list; whichever scores highest in fuzzy match is dispatched

#### Scenario: actions.yaml-only trigger active
- **WHEN** `config.yaml` has no inline triggers and `actions.yaml` has triggers
- **THEN** `actions.yaml` triggers are the active trigger list

### Requirement: Hot-reload watches `actions.yaml`
The hot-reload watcher SHALL also monitor `actions.yaml` (when configured). A change to `actions.yaml` alone SHALL trigger a config reload and invoke all registered reload callbacks.

#### Scenario: actions.yaml updated on disk
- **WHEN** a new trigger is appended to `actions.yaml` and saved
- **THEN** within `config_poll_interval` seconds the new trigger is active

### Requirement: Atomic writes to `actions.yaml`
`ActionsFileStore.save()` SHALL write to a temporary file in the same directory and rename it over the target, ensuring the file is never in a partially-written state.

#### Scenario: Concurrent hot-reload during write
- **WHEN** the agent writes a new command while the hot-reload watcher polls
- **THEN** the watcher either reads the old complete file or the new complete file — never a partial write
