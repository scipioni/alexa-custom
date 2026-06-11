# Web Volume Control

## Purpose

This capability provides a web dashboard volume slider with test tone feedback for adjusting system output volume.

## Requirements

### Requirement: User can adjust output volume via web dashboard

The web dashboard SHALL provide an interactive volume slider control that allows users to adjust the system output volume from 0% to 100%.

#### Scenario: User adjusts volume using slider
- **WHEN** user drags volume slider to 75%
- **THEN** system volume is updated to 75%
- **AND** percentage display shows "75%"
- **AND** volume setting is persisted to config.yaml
- **AND** subsequent daemon restarts use the new volume

#### Scenario: User sets volume to 0%
- **WHEN** user drags slider to 0%
- **THEN** system volume is set to 0%
- **AND** percentage display shows "0%"
- **AND** no tone is played

#### Scenario: User sets volume to 100%
- **WHEN** user drags slider to 100%
- **THEN** system volume is set to 100%
- **AND** percentage display shows "100%"

### Requirement: Volume slider displays current volume percentage

The volume slider control SHALL display the current volume percentage next to the slider.

#### Scenario: Slider shows current volume
- **WHEN** user loads the dashboard
- **THEN** slider value matches the current volume from config.yaml
- **AND** percentage display shows the correct volume

#### Scenario: Slider updates during interaction
- **WHEN** user drags the slider
- **THEN** percentage display updates in real-time to show the slider value
- **AND** slider thumb reflects the current position

### Requirement: Test tone plays on slider release

When user releases the volume slider, the system SHALL play a test tone to provide audible confirmation of the volume level.

#### Scenario: Tones play on mouseup
- **WHEN** user drags slider and releases it (mouseup)
- **THEN** system plays a test tone with frequency based on volume level
- **AND** tone duration is 100ms
- **AND** tone volume is 60% of maximum

#### Scenario: Tone frequencies scale with volume
- **WHEN** user releases slider at low volume (<30%)
- **THEN** system plays a 330Hz tone
- **WHEN** user releases slider at medium volume (30-70%)
- **THEN** system plays a 440Hz tone
- **WHEN** user releases slider at high volume (>70%)
- **THEN** system plays a 523Hz tone

#### Scenario: No tone plays when volume is 0%
- **WHEN** user releases slider at 0%
- **THEN** system does not play any tone

#### Scenario: Tone plays on every volume change
- **WHEN** user releases slider to a new volume
- **THEN** system plays a tone regardless of volume level (except 0%)

### Requirement: Volume changes are persisted across sessions

Volume changes made via the web dashboard SHALL be persisted and restored on subsequent daemon starts.

#### Scenario: Volume persists after daemon restart
- **WHEN** user changes volume via dashboard
- **AND** daemon is restarted
- **THEN** volume setting is restored from config.yaml
- **AND** slider reflects the restored volume on next connection

### Requirement: Volume control respects existing volume infrastructure

Volume control via web dashboard SHALL use the existing audio control infrastructure and not interfere with livekit calls or other audio operations.

#### Scenario: Volume changes work during active LiveKit call
- **WHEN** user is in an active LiveKit call
- **AND** user changes volume via slider
- **THEN** call audio volume is adjusted accordingly
- **AND** no call disruption occurs

#### Scenario: Volume control is independent of input gain
- **WHEN** user adjusts output volume via slider
- **THEN** input gain remains unchanged
- **AND** microphone sensitivity is not affected
