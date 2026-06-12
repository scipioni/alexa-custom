# Capability: Voice Volume Control

## Purpose
Adjust the system output volume through voice commands mapped to trigger actions, with persistence across daemon restarts.

## ADDED Requirements

### Requirement: set_volume action type
The system SHALL support a `set_volume` action type that adjusts the system output volume. The action SHALL accept a `mode` parameter (`"up"`, `"down"`, or `"absolute"`), a `step` parameter (float, default 0.1) for relative modes, and a `value` parameter (float, default 0.5) for absolute mode. The effective volume SHALL be clamped to the range [0.0, 1.0].

#### Scenario: Increase volume by step
- **WHEN** a `set_volume` action with `mode: up` and `step: 0.1` is dispatched
- **THEN** the system increases `_OUTPUT_VOLUME` by 0.1, clamped to 1.0

#### Scenario: Decrease volume by step
- **WHEN** a `set_volume` action with `mode: down` and `step: 0.1` is dispatched
- **THEN** the system decreases `_OUTPUT_VOLUME` by 0.1, clamped to 0.0

#### Scenario: Absolute volume set
- **WHEN** a `set_volume` action with `mode: absolute` and `value: 0.7` is dispatched
- **THEN** the system sets `_OUTPUT_VOLUME` to exactly 0.7

#### Scenario: Clamp at upper bound
- **WHEN** volume is 0.95 and a `mode: up` action with `step: 0.1` is dispatched
- **THEN** the resulting volume is 1.0

#### Scenario: Clamp at lower bound
- **WHEN** volume is 0.03 and a `mode: down` action with `step: 0.1` is dispatched
- **THEN** the resulting volume is 0.0

### Requirement: Volume change goes through set_output_volume
The `set_volume` action SHALL call `audio_hw.set_output_volume()` (which wraps `wpctl set-volume` and restores ALSA hardware PCM) so that both the software gain multiplier (`_OUTPUT_VOLUME`) and the PipeWire hardware sink volume are updated atomically.

#### Scenario: Hardware volume follows software volume
- **WHEN** a `set_volume` action changes `_OUTPUT_VOLUME` to 0.6
- **THEN** `set_output_volume(pulse, None, 0.6)` is called, which runs `wpctl set-volume` and `_restore_hw_pcm()`

### Requirement: Confirmation tone on change
The `set_volume` action SHALL play a short confirmation tone when the volume actually changes. If the volume is already at the boundary (0.0 or 1.0) and no change occurs, the tone SHALL NOT play.

#### Scenario: Tone played on successful change
- **WHEN** volume changes from 0.5 to 0.6
- **THEN** the system plays the "info" tone

#### Scenario: No tone when already at maximum
- **WHEN** volume is 1.0 and an `up` action is dispatched
- **THEN** no tone is played

### Requirement: Volume state persistence
The system SHALL persist the last user-set volume to `conf/state.yaml` as `output_volume` immediately after each change. On daemon startup, the state file SHALL be loaded and its value SHALL override the `audio.output_volume` from `config.yaml`. If the state file is absent or malformed, the system SHALL fall back to the config.yaml value without error.

#### Scenario: Volume saved after voice change
- **WHEN** a `set_volume` action changes the volume to 0.6
- **THEN** `conf/state.yaml` contains `output_volume: 0.6`

#### Scenario: Volume restored on restart
- **WHEN** the daemon restarts and `conf/state.yaml` contains `output_volume: 0.6`
- **THEN** `_OUTPUT_VOLUME` is initialized to 0.6 regardless of `config.yaml:audio.output_volume`

#### Scenario: State file absent on first boot
- **WHEN** `conf/state.yaml` does not exist at startup
- **THEN** the system uses `config.yaml:audio.output_volume` and logs a debug message

#### Scenario: Malformed state file ignored
- **WHEN** `conf/state.yaml` contains unparseable content
- **THEN** the system logs a warning and falls back to `config.yaml:audio.output_volume`

### Requirement: Phrase-triggered volume commands
The system SHALL include two pre-configured trigger entries in the user actions file that map Italian voice phrases to the `set_volume` action. The trigger "alza il volume" SHALL increase volume by 10%, and "abbassa il volume" SHALL decrease volume by 10%. A confirmation tone SHALL play after each successful change.

#### Scenario: "alza il volume" increases volume
- **WHEN** the user says "alza il volume"
- **THEN** volume increases by 0.1 and the "info" tone plays

#### Scenario: "abbassa il volume" decreases volume
- **WHEN** the user says "abbassa il volume"
- **THEN** volume decreases by 0.1 and the "info" tone plays
