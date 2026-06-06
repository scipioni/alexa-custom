## ADDED Requirements

### Requirement: Audible feedback on config parse failure
When a hot-reload of `config.yaml` fails due to a parse or validation error, the system SHALL play a spoken error message through the default audio output to alert the operator on the headless device.

The spoken text SHALL be `"Errore di configurazione"` (Italian, matching the assistant's configured locale). The TTS call SHALL be non-blocking and best-effort — if TTS is unavailable or busy, the system SHALL log the error and continue without blocking the config watcher loop.

The previous valid config SHALL remain active. The error message and full parse error details SHALL be logged at ERROR level regardless of whether TTS playback succeeds.

#### Scenario: Malformed YAML triggers spoken error
- **WHEN** `config.yaml` is saved with a YAML syntax error
- **THEN** within 4 seconds the system plays "Errore di configurazione" through the speaker and logs the parse error

#### Scenario: Valid config after previous error resumes normally
- **WHEN** a previously failing `config.yaml` is corrected and saved
- **THEN** the new config is loaded successfully, no error is spoken, and the system operates on the corrected config

#### Scenario: TTS unavailable does not block watcher
- **WHEN** the TTS engine is busy during a config parse failure
- **THEN** the error is logged and the watcher loop continues polling without deadlock

### Requirement: Config error callback registration
`ConfigManager` SHALL support registering an `on_config_error` callback. The callback SHALL receive the error message string and SHALL be called from the watcher task after retaining the previous config. Only one callback SHALL be active at a time (last-write-wins).

#### Scenario: Callback invoked on parse error
- **WHEN** an `on_config_error` callback is registered and config reload fails
- **THEN** the callback is called with the error message string

#### Scenario: No callback registered — error only logged
- **WHEN** no `on_config_error` callback is registered and config reload fails
- **THEN** the error is logged and the system continues; no exception is raised
