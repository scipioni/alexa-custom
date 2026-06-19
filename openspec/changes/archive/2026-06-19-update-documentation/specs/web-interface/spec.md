# Capability: Web Interface

## ADDED Requirements

### Requirement: Config panel with live editing

The dashboard SHALL include a configuration panel at `/config` (or as a modal/drawer in the main dashboard) that allows users to view and modify the following settings in real time:

- Wake words (add/remove)
- Recognition (wake_window, matching_threshold)
- STT (backend, vad_silence_ms, rms_threshold, adaptive_rms)
- Audio (output_volume, input_gain)
- TTS (backend, voice)

#### Scenario: Config panel renders
- **WHEN** a user navigates to the config section of the dashboard
- **THEN** they see labelled input fields with current values pre-filled

#### Scenario: Config saved and hot-reloaded
- **WHEN** a user modifies a value (e.g., wake_window: 10.0) and clicks save
- **THEN** the new value is written to `conf/config.yaml`
- **AND** the daemon hot-reloads the config within `config_poll_interval` seconds

#### Scenario: Invalid values rejected
- **WHEN** a user enters an out-of-range value (e.g., output_volume: 5.0)
- **THEN** the panel shows an inline validation error and does not save

#### Scenario: Display section visible in config
- **WHEN** `display.enabled` is available in config
- **THEN** the config panel shows display settings (enabled, backend, brightness)

### Requirement: Config panel respects dev-mode

The config panel SHALL only be accessible when dev-mode is active (toggled via a UI control). In non-dev mode, the panel SHALL be hidden or read-only.

#### Scenario: Dev mode toggle shows config panel
- **WHEN** the user toggles dev mode on
- **THEN** the config panel becomes visible/editable

#### Scenario: Dev mode off hides panel
- **WHEN** the user toggles dev mode off
- **THEN** the config panel is hidden or locked

### Requirement: Web interface serves /api/config endpoints

The REST API SHALL provide:
- `GET /api/config` — return current config as JSON
- `POST /api/config` — validate and save new config
- `GET /api/config/defaults` — return default config values
- `GET /api/health` — return daemon health status
- `GET /api/metrics` — return runtime metrics

#### Scenario: Config returned as JSON
- **WHEN** `GET /api/config` is called
- **THEN** the response body contains the current ActionsConfig as JSON
