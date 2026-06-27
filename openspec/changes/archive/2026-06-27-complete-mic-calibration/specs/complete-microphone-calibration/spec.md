## ADDED Requirements

### Requirement: calibrate_microphone_complete action registration
The system SHALL register a `calibrate_microphone_complete` action type in the action registry, callable from configuration triggers.

#### Scenario: Action is dispatched
- **WHEN** a trigger fires with `type: calibrate_microphone_complete`
- **THEN** the unified multi-stage calibration routine starts

### Requirement: Multi-stage calibration sequence
The system SHALL execute a two-stage calibration sequence:
1. **Stage 1 (Hardware Level)**: Run the standard adaptive 5-probe input gain calibration to set the ideal microphone hardware level.
2. **Stage 2 (Filter Level)**: Run a 3-probe GStreamer audio filter sweep at the newly calibrated gain level to determine the optimal noise suppression and AGC parameters.

#### Scenario: Normal execution flow
- **WHEN** the action is triggered
- **THEN** Stage 1 runs 5 probes of gain, then Stage 2 runs 3 probes of GStreamer filter parameters, and then the combined best settings are applied

### Requirement: Stage 2 GStreamer parameter probes
Stage 2 SHALL test exactly three distinct GStreamer configurations:
- **Probe 1 (Standard)**: `noise_suppression=True`, `noise_suppression_level=2`, `agc=True`
- **Probe 2 (Sensitive)**: `noise_suppression=True`, `noise_suppression_level=1`, `agc=True`
- **Probe 3 (DSP Bypass)**: `noise_suppression=False`, `noise_suppression_level=1`, `agc=True`

#### Scenario: Filter sweep
- **WHEN** Stage 1 concludes with a winning gain
- **THEN** GStreamer is dynamically reconfigured for each of the three configurations, recording and scoring the user's voice for each

### Requirement: Unified best settings persistence
The action SHALL save both the winning gain from Stage 1 and the winning GStreamer filter parameters from Stage 2 to `conf/state.yaml` so they persist across reboots.

#### Scenario: Successful calibration saved
- **WHEN** both stages complete
- **THEN** `conf/state.yaml` is updated with `input_gain` and `gstreamer_override` values
