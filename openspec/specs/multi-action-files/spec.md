# Capability: Multi-Action Files

## Purpose
Support splitting triggers, wake word overrides, and startup actions into multiple modular configuration files under a directory.

## Requirements

### Requirement: conf/actions/ directory auto-discovery
The system SHALL auto-discover all `.yaml` files in the configured `actions.dir` directory. `system.yaml` SHALL always be loaded first regardless of alphabetical order. All remaining `.yaml` files SHALL be loaded in ascending alphabetical order by filename. Non-`.yaml` files SHALL be ignored.

#### Scenario: system.yaml loaded before user.yaml
- **WHEN** `conf/actions/` contains `system.yaml` and `user.yaml`
- **THEN** `system.yaml` is loaded first and `user.yaml` second, regardless of filesystem ordering

#### Scenario: Multiple user files loaded alphabetically
- **WHEN** `conf/actions/` contains `home.yaml`, `learned.yaml`, and `user.yaml`
- **THEN** load order is: system.yaml → home.yaml → learned.yaml → user.yaml

#### Scenario: Non-yaml files ignored
- **WHEN** `conf/actions/` contains `notes.txt` and `system.yaml`
- **THEN** only `system.yaml` is loaded; `notes.txt` is silently ignored

#### Scenario: New file dropped into directory picked up on hot-reload
- **WHEN** a new `extra.yaml` is added to `conf/actions/` while the daemon is running
- **THEN** within `config_poll_interval` seconds the triggers from `extra.yaml` are active

### Requirement: First-match-wins trigger merge
All triggers from all action files SHALL be concatenated in load order into a single flat list. `match_trigger` SHALL return the first trigger whose phrase matches the spoken command. Earlier files therefore have higher matching priority.

#### Scenario: system.yaml trigger wins over user.yaml duplicate phrase
- **WHEN** both `system.yaml` and `user.yaml` define a trigger for "che ora è"
- **THEN** the `system.yaml` version is dispatched (loaded first, first match wins)

#### Scenario: user.yaml trigger active when no system.yaml match
- **WHEN** `user.yaml` defines "chiama stefano" and `system.yaml` does not
- **THEN** "chiama stefano" is dispatched from `user.yaml`

### Requirement: wake_triggers merged per wake word across all files
For each wake word, all `wake_triggers.<word>` lists from all files SHALL be concatenated in load order. The merged list is used as the per-group trigger list, with first-match-wins semantics.

#### Scenario: wake_triggers for same word merged from two files
- **WHEN** `system.yaml` defines `wake_triggers.galileo: [...]` and `user.yaml` also defines `wake_triggers.galileo: [...]`
- **THEN** both lists are merged; system.yaml entries are checked first

#### Scenario: wake_triggers for unknown wake word ignored
- **WHEN** a file defines `wake_triggers.nonexistent: [...]` and no wake word group named `nonexistent` exists
- **THEN** the entry is ignored and a debug log is emitted

### Requirement: on_startup defined only in system.yaml
The `on_startup` key SHALL be read exclusively from `system.yaml`. If any other action file defines `on_startup`, those entries SHALL be ignored with a debug log.

#### Scenario: on_startup from system.yaml executes at startup
- **WHEN** `system.yaml` defines `on_startup: [{type: say, text: "Sistema pronto"}]`
- **THEN** the TTS says "Sistema pronto" once after the daemon finishes initialising

#### Scenario: on_startup in user.yaml ignored
- **WHEN** `user.yaml` defines an `on_startup` key
- **THEN** those actions are NOT executed and a debug log notes the ignored key

### Requirement: actions.dir and actions.learn_file in conf/config.yaml
The `conf/config.yaml` file SHALL accept an `actions:` block with:

| Field | Type | Default | Description |
|---|---|---|---|
| `dir` | str | `"conf/actions"` | Directory to auto-discover action files from |
| `learn_file` | str | `"conf/actions/learned.yaml"` | File the `llm_learn` action appends new commands to |

#### Scenario: Custom actions directory configured
- **WHEN** `actions.dir: /etc/alexa/actions` is set
- **THEN** the system discovers action files from that directory instead of the default

#### Scenario: learn_file auto-created on first write
- **WHEN** `llm_learn` writes a new command and `learned.yaml` does not yet exist
- **THEN** `learned.yaml` is created with the new trigger; no error is raised

### Requirement: Hot-reload watches entire actions directory
The hot-reload watcher SHALL monitor `conf/actions/` for mtime changes across all `.yaml` files. Any file change SHALL trigger a full reload of all action files and invoke registered reload callbacks.

#### Scenario: Any action file change triggers reload
- **WHEN** `conf/actions/home.yaml` is edited and saved
- **THEN** all action files are reloaded (not just `home.yaml`) and the new trigger list is active within `config_poll_interval` seconds
