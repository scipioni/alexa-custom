## ADDED Requirements

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
