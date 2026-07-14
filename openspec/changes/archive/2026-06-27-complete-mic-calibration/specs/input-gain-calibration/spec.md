## ADDED Requirements

### Requirement: calibrate_microphone_complete integration link
The input gain calibration logic SHALL be reusable and linkable so that it can be executed as Stage 1 of the complete calibration action.

#### Scenario: Stage 1 reuses gain probes
- **WHEN** `calibrate_microphone_complete` begins
- **THEN** it executes the adaptive 5-probe sequence defined in `input-gain-calibration`
