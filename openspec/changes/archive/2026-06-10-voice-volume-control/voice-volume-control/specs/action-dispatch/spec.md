# Capability: Action Dispatch

## Purpose
Map recognized trigger phrases to a sequence of actions.

## ADDED Requirements

### Requirement: set_volume_from_transcript action type
The system SHALL support a `set_volume_from_transcript` action type that receives the raw STT transcript, extracts a volume percentage, and sets the system output volume. This SHALL use the existing `set_output_volume()` function and `save_volume_state()` for persistence.

#### Scenario: Action dispatched with transcript
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 80%"
- **THEN** the system extracts 80%, calls `set_output_volume(0.80)`, and saves the new volume state

#### Scenario: Transcript without recognizable number
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "alza il volume"
- **THEN** the action SHALL be a no-op (no volume change, no error)

#### Scenario: Volume at minimum
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 0%"
- **THEN** volume is set to 0.0 (muted)
