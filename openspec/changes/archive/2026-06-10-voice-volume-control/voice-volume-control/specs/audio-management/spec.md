# Capability: Audio Management

## Purpose
Proactively manage PipeWire hardware profiles and routing to ensure reliable audio operation in a headless environment.

## ADDED Requirements

### Requirement: Volume state persistence across restarts
The system SHALL persist the output volume level to `conf/state.yaml` after every change and SHALL restore it during daemon startup. Volume SHALL be stored as a `output_volume` key with a float value in the 0.0–1.0 range.

#### Scenario: Volume saved after voice command
- **WHEN** the volume is changed to 0.80 via voice command
- **THEN** `conf/state.yaml` is updated with `output_volume: 0.8`

#### Scenario: Volume restored on daemon start
- **WHEN** the daemon starts and `conf/state.yaml` contains `output_volume: 0.8`
- **THEN** the system applies 0.8 as the initial output volume
