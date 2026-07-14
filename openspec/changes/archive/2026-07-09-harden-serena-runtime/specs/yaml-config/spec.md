# Delta: YAML Config

## MODIFIED Requirements

### Requirement: Hot-reload watcher
The system SHALL monitor `config.yaml` for modifications using an asyncio-based polling watcher with a configurable interval (default 2 seconds, overridable via `config_poll_interval` in config.yaml). The watcher SHALL run in the default production daemon (the plain `serena` entry point as launched by `serena.service`), not only when a development flag such as `--hot-reload` is passed; the `--hot-reload` flag SHALL govern only the development-time source-file (`.py`) auto-restart watcher. When a file modification is detected, the system SHALL reload the config. Reloads SHALL preserve the secrets overrides (`conf/secrets.yaml` values such as `llm_host` and `llm_api_key`) captured at startup, so a reload never silently disables a subsystem that depends on secrets. Web-UI configuration saves SHALL trigger the same reload path unconditionally. If the reload succeeds, all registered reload callbacks SHALL be invoked with the new config. If the reload fails due to a YAML parse error or `ConfigError`, the previous config SHALL remain active; the registered `on_config_error` callback SHALL be invoked with the error message if one is registered; no reload callbacks are invoked on failure.

#### Scenario: Config file edited and saved
- **WHEN** `config.yaml` is written to disk with a new trigger phrase
- **THEN** within two poll intervals the system's active trigger list includes the new phrase

#### Scenario: Config edited under the production systemd service
- **WHEN** the daemon runs via `serena.service` (no `--hot-reload` flag) and `config.yaml` is edited on disk
- **THEN** the change takes effect within two poll intervals without a daemon restart

#### Scenario: Secrets preserved across reload
- **WHEN** the LLM is configured via `conf/secrets.yaml` (`llm_host`) and a config reload occurs (file edit or web-UI save)
- **THEN** the reloaded config retains the secrets-provided values and the LLM keeps working

#### Scenario: Web-UI save triggers reload
- **WHEN** a configuration change is saved from the web dashboard config panel
- **THEN** the running daemon applies the new configuration via the reload path without requiring `--hot-reload`

#### Scenario: Malformed YAML on save
- **WHEN** `config.yaml` is overwritten with invalid YAML
- **THEN** the current config remains active, the `on_config_error` callback is invoked, an error is logged, and the system continues operating

#### Scenario: Watcher stopped cleanly
- **WHEN** the daemon receives SIGTERM
- **THEN** the watcher task is cancelled without raising unhandled exceptions

#### Scenario: Custom poll interval respected
- **WHEN** `config.yaml` sets `config_poll_interval: 5`
- **THEN** the watcher polls every 5 seconds instead of the default 2 seconds
