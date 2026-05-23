# Capability: YAML Config

## Purpose
Load, merge, and hot-reload configuration from `config.yaml`, providing environment variable injection and a callback registry for subsystem reloads.

## Requirements

### Requirement: Unified config.yaml with env section
The system SHALL load configuration from `config.yaml` when present. The file SHALL support an optional top-level `env:` key containing a flat string-to-string mapping of environment variables. Values in `env:` SHALL be written into `os.environ`, overwriting any existing values (including those previously set by `.env`). The `wake_words` key SHALL be a list of wake word group objects; each object SHALL have a required string `word` field, an optional `aliases` list of strings, and an optional `triggers` list following the existing trigger schema. A top-level `triggers` key SHALL be accepted as a global fallback and MAY be an empty list or absent. All other top-level keys are parsed using the existing actions config schema.

#### Scenario: env section populates os.environ
- **WHEN** `config.yaml` contains `env: { LIVEKIT_URL: wss://example.com }`
- **THEN** `os.environ["LIVEKIT_URL"]` equals `"wss://example.com"` after load

#### Scenario: env section overwrites .env value
- **WHEN** `.env` sets `TELEGRAM_BOT_TOKEN=old` and `config.yaml env:` sets `TELEGRAM_BOT_TOKEN: new`
- **THEN** `os.environ["TELEGRAM_BOT_TOKEN"]` equals `"new"` (config.yaml takes precedence)

#### Scenario: Wake word group with aliases parsed correctly
- **WHEN** `config.yaml` contains a wake word group with `word: galileo` and `aliases: [hey galileo]`
- **THEN** `config.wake_words[0].word` equals `"galileo"` and `config.wake_words[0].aliases` equals `["hey galileo"]`

#### Scenario: Wake word group with per-group triggers
- **WHEN** a wake word group defines its own `triggers` list
- **THEN** `config.wake_words[0].triggers` is a non-empty list of `Trigger` objects

#### Scenario: Wake word group without triggers uses global fallback
- **WHEN** a wake word group has no `triggers` key and the top-level `triggers` list is non-empty
- **THEN** `config.wake_words[0].triggers` is an empty list and `config.triggers` is non-empty

#### Scenario: Old flat wake_words list rejected
- **WHEN** `config.yaml` contains `wake_words: [galileo, assistente]` (flat strings)
- **THEN** a `ConfigError` is raised with a message indicating the new format is required

#### Scenario: config.yaml without env section
- **WHEN** `config.yaml` exists but has no `env:` key
- **THEN** the file is parsed using the actions config schema; `os.environ` is unchanged

### Requirement: Backward-compatible fallback to actions.yaml
The system SHALL fall back to loading `actions.yaml` when `config.yaml` does not exist. A deprecation warning SHALL be logged when the fallback is used. `.env` is always loaded as the lowest-priority source regardless of which primary config file is used.

#### Scenario: Only actions.yaml present
- **WHEN** `config.yaml` does not exist but `actions.yaml` does
- **THEN** triggers and wake words are loaded from `actions.yaml` and a deprecation warning is logged

#### Scenario: Neither config file present
- **WHEN** neither `config.yaml` nor `actions.yaml` exists
- **THEN** the system starts without trigger-based wake word detection (existing behavior)

#### Scenario: Both files present
- **WHEN** both `config.yaml` and `actions.yaml` exist
- **THEN** `config.yaml` is used exclusively and `actions.yaml` is ignored

### Requirement: Hot-reload watcher
The system SHALL monitor `config.yaml` for modifications using an asyncio-based polling watcher with a 2-second interval. When a file modification is detected, the system SHALL reload the config. If the reload succeeds, all registered reload callbacks SHALL be invoked with the new config. If the reload fails due to a YAML parse error, the previous config SHALL remain active and an error SHALL be logged; no callbacks are invoked.

#### Scenario: Config file edited and saved
- **WHEN** `config.yaml` is written to disk with a new trigger phrase
- **THEN** within 4 seconds the system's active trigger list includes the new phrase

#### Scenario: Malformed YAML on save
- **WHEN** `config.yaml` is overwritten with invalid YAML (e.g., mid-editor-save partial write)
- **THEN** the current config remains active, an error is logged, and the system continues operating

#### Scenario: Watcher stopped cleanly
- **WHEN** the daemon receives SIGTERM
- **THEN** the watcher task is cancelled without raising unhandled exceptions

### Requirement: ConfigManager callback registry
The system SHALL provide a `ConfigManager` class that holds the current `ActionsConfig`, runs the watcher task, and allows subsystems to register reload callbacks. Callbacks SHALL receive the new `ActionsConfig` as their sole argument and SHALL be called sequentially after each successful reload.

#### Scenario: Subsystem registers reload callback
- **WHEN** a subsystem calls `config_manager.register_reload_callback(fn)`
- **THEN** `fn(new_config)` is called after every subsequent successful reload

#### Scenario: MQTT settings change on reload
- **WHEN** `config.yaml env:` changes `MQTT_HOST` to a different value and the file is saved
- **THEN** the MQTT reload callback disconnects the existing client and connects a new one to the updated host

#### Scenario: Credential values not logged
- **WHEN** a reload applies new values from the `env:` section
- **THEN** log lines reference only the key names, not the values

### Requirement: Optional web section in config.yaml
The system SHALL support an optional top-level `web:` key in `config.yaml`. When present, it SHALL accept the following fields: `port` (integer, default `8080`) and `enabled` (boolean, default `false`). These values SHALL be accessible to the web interface module but SHALL NOT affect startup unless the `--web` CLI flag is explicitly passed.

#### Scenario: web.port read from config
- **WHEN** `config.yaml` contains `web: { port: 9090 }` and `--web` is passed
- **THEN** the HTTP server binds to port 9090 (CLI flag `--web-port` takes precedence if also provided)

#### Scenario: Missing web section uses defaults
- **WHEN** `config.yaml` has no `web:` key
- **THEN** the web interface uses port 8080 when started with `--web`
