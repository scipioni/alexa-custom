# Capability: Action Dispatch

## REMOVED Requirements

### Requirement: set_volume_from_transcript action type
**Reason**: Replaced by three fixed preset triggers (`Volume basso`, `Volume medio`, `Volume alto`) that use the existing `set_volume` action type with absolute values. The transcript-parsing approach added unnecessary complexity (`number_parser` module, separate action handler) with no advantage over simple YAML-configured presets.
**Migration**: Any existing usage of `type: set_volume_from_transcript` in YAML action files must be replaced with `type: set_volume` entries using `mode: absolute` and a fixed `value`. The `set_volume_from_transcript` handler and `number_parser` module are removed.

#### Scenario: Action dispatched with transcript
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 80%"
- **THEN** the system extracts 80%, calls `set_output_volume(0.80)`, and saves the new volume state

#### Scenario: Transcript without recognizable number
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "alza il volume"
- **THEN** the action SHALL be a no-op (no volume change, no error)

#### Scenario: Volume at minimum
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 0%"
- **THEN** volume is set to 0.0 (muted)
