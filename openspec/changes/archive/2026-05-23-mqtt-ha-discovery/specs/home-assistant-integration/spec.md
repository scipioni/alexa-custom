## ADDED Requirements

### Requirement: Mapping voice commands to HA events
The system SHALL format voice command transcripts into a structure compatible with Home Assistant's event system or a generic sensor, including the original transcript and the wake word used.

#### Scenario: Command sent to HA
- **WHEN** a voice command is captured
- **THEN** the MQTT payload includes a `text` field with the transcript and a `wake_word` field

### Requirement: Remote-triggered action dispatch
The system SHALL expose an interface to trigger any valid action type (defined in `actions.py`) via an incoming MQTT message. The message payload MUST contain the action `type` and its required `params`.

#### Scenario: Remote tone play
- **WHEN** MQTT receives a payload `{"type": "tone", "params": {"name": "info"}}`
- **THEN** the system plays the corresponding audio tone
