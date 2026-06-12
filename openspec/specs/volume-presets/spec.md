# Capability: Volume Presets

## Purpose
Provide three voice-activated volume presets that set the system output volume to fixed levels.

## Requirements

### Requirement: Trigger phrase "Volume basso" sets volume to 10%
The system SHALL provide a global trigger `Volume basso` that, when matched, sets the output volume to 0.10 (10%).

#### Scenario: "Volume basso" matches and sets low volume
- **WHEN** the STT transcription is "volume basso"
- **THEN** the trigger `Volume basso` is selected and the output volume is set to 0.10

### Requirement: Trigger phrase "Volume medio" sets volume to 50%
The system SHALL provide a global trigger `Volume medio` that, when matched, sets the output volume to 0.50 (50%).

#### Scenario: "Volume medio" matches and sets medium volume
- **WHEN** the STT transcription is "volume medio"
- **THEN** the trigger `Volume medio` is selected and the output volume is set to 0.50

### Requirement: Trigger phrase "Volume alto" sets volume to 90%
The system SHALL provide a global trigger `Volume alto` that, when matched, sets the output volume to 0.90 (90%).

#### Scenario: "Volume alto" matches and sets high volume
- **WHEN** the STT transcription is "volume alto"
- **THEN** the trigger `Volume alto` is selected and the output volume is set to 0.90

### Requirement: All presets confirm with a tone
Each preset volume action SHALL play a confirmation tone after applying the volume change, using the existing `play_tone("info")` behaviour built into the `set_volume` action handler.

#### Scenario: Confirmation tone plays after volume change
- **WHEN** the output volume has been changed by any preset trigger
- **THEN** a confirmation tone is played
