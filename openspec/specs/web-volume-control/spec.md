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

### Requirement: Volume slider has visible gradient fill

The volume slider SHALL display a gradient fill from left edge to the current slider position, using colors that change with volume level.

#### Scenario: Gradient fill visible at 50%
- **WHEN** slider is at 50%
- **THEN** the track is filled from 0% to 50% with a gradient
- **AND** the un-filled portion from 50% to 100% shows the background color

#### Scenario: Fill color changes with volume
- **WHEN** volume is below 70%
- **THEN** the fill gradient uses green tones (matching VU meter green)
- **WHEN** volume is between 70% and 85%
- **THEN** the fill gradient uses amber/yellow tones
- **WHEN** volume is above 85%
- **THEN** the fill gradient uses red tones

### Requirement: Slider thumb is large and responsive

The slider thumb SHALL be at least 24px in diameter with a border matching the fill color and a glow/shadow effect.

#### Scenario: Thumb scales on hover
- **WHEN** user hovers over the slider thumb
- **THEN** the thumb scales to 1.15x size
- **AND** the glow effect intensifies

#### Scenario: Thumb scales on active drag
- **WHEN** user is dragging the slider
- **THEN** the thumb scales to 1.3x size
- **AND** the glow effect is at maximum intensity

### Requirement: Slider updates from external volume changes

When system volume changes from any source other than the web slider (voice actions, shell, other clients), the slider SHALL update to reflect the new volume.

#### Scenario: Voice action changes volume
- **WHEN** user says "alza il volume" via voice command
- **THEN** within 3 seconds the slider on the dashboard updates to the new volume
- **AND** no tone is played by the dashboard
- **AND** no `set_volume` message is sent to the server

#### Scenario: Shell command changes volume
- **WHEN** user runs `wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.8` in the shell
- **THEN** within 3 seconds the slider on the dashboard updates to 80%
- **AND** the percentage display shows "80%"

#### Scenario: Second client changes volume
- **WHEN** user adjusts volume on a second browser tab
- **THEN** the first browser tab's slider updates within 3 seconds

### Requirement: Volume sync does not create feedback loops

When the dashboard receives a volume update from the server broadcast, it SHALL NOT send a new `set_volume` command or play a beep.

#### Scenario: External update does not re-trigger beep
- **WHEN** volume changes from a voice command
- **AND** the dashboard slider updates to reflect the new volume
- **THEN** no beep is played
- **AND** no `set_volume` control message is sent

### Requirement: WebServer._output_volume is kept in sync

The WebServer's `_output_volume` field SHALL be updated whenever volume is changed via the web slider, so that newly connecting clients receive the correct value in the `hello` message.

#### Scenario: New connection gets current volume
- **WHEN** user changes volume via slider to 75%
- **AND** a new browser tab connects to the dashboard
- **THEN** the `hello` message includes `output_volume: 0.75`
- **AND** the slider in the new tab displays 75%
