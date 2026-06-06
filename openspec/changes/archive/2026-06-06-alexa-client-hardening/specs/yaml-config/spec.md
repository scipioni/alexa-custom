## MODIFIED Requirements

### Requirement: Hot-reload watcher
The system SHALL monitor `config.yaml` for modifications using an asyncio-based polling watcher with a configurable interval (default 2 seconds, overridable via `config_poll_interval` in config.yaml). When a file modification is detected, the system SHALL reload the config. If the reload succeeds, all registered reload callbacks SHALL be invoked with the new config. If the reload fails due to a YAML parse error or `ConfigError`, the previous config SHALL remain active; the registered `on_config_error` callback SHALL be invoked with the error message if one is registered; no reload callbacks are invoked on failure.

#### Scenario: Config file edited and saved
- **WHEN** `config.yaml` is written to disk with a new trigger phrase
- **THEN** within two poll intervals the system's active trigger list includes the new phrase

#### Scenario: Malformed YAML on save
- **WHEN** `config.yaml` is overwritten with invalid YAML
- **THEN** the current config remains active, the `on_config_error` callback is invoked, an error is logged, and the system continues operating

#### Scenario: Watcher stopped cleanly
- **WHEN** the daemon receives SIGTERM
- **THEN** the watcher task is cancelled without raising unhandled exceptions

#### Scenario: Custom poll interval respected
- **WHEN** `config.yaml` sets `config_poll_interval: 5`
- **THEN** the watcher polls every 5 seconds instead of the default 2 seconds

### Requirement: ConfigManager callback registry
The system SHALL provide a `ConfigManager` class that holds the current `ActionsConfig`, runs the watcher task, allows subsystems to register reload callbacks, and supports an `on_config_error` callback slot. Reload callbacks SHALL receive the new `ActionsConfig` as their sole argument and SHALL be called sequentially after each successful reload. The `on_config_error` callback SHALL receive the error message string and SHALL be called after each failed reload.

#### Scenario: Subsystem registers reload callback
- **WHEN** a subsystem calls `config_manager.register_reload_callback(fn)`
- **THEN** `fn(new_config)` is called after every subsequent successful reload

#### Scenario: Error callback registered and invoked on failure
- **WHEN** a subsystem calls `config_manager.set_error_callback(fn)` and a subsequent reload fails
- **THEN** `fn(error_message)` is called with the parse error string
