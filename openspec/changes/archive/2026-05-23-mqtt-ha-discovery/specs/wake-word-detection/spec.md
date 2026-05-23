## MODIFIED Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words using Vosk grammar-mode recognition. Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking to prevent false triggers. The system SHALL report its listening status (e.g., `idle`, `listening`, `gated`) via MQTT.

#### Scenario: Wake word detected
- **WHEN** a configured wake word is spoken clearly into the microphone
- **THEN** the system plays a wake acknowledgement beep, publishes `listening` to MQTT, and transitions to command listening mode

#### Scenario: Non-wake-word speech ignored
- **WHEN** speech is detected that does not match any configured wake word
- **THEN** the system remains in Stage 1 listening mode and takes no action

#### Scenario: STT starts without LiveKit
- **WHEN** the process starts and `actions.yaml` is present
- **THEN** wake word listening begins before any LiveKit connection is established

#### Scenario: STT paused during call
- **WHEN** a LiveKit session is active
- **THEN** the recognizer is gated, STT status shows "STT paused during call", and the system publishes `gated` to MQTT

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window of configurable duration (default 3 seconds). If a command is recognized within the window, it is dispatched to the action system and published to MQTT. If the window expires without a match, the system plays a timeout beep and returns to Stage 1.

#### Scenario: Command recognized within window
- **WHEN** the user speaks a configured trigger phrase within 3 seconds of the wake beep
- **THEN** the system dispatches the corresponding actions, publishes the transcript to MQTT, and returns to Stage 1

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `command_timeout` seconds
- **THEN** the system plays a timeout beep, publishes an empty or "timeout" status to MQTT, and resumes wake word listening

#### Scenario: Custom timeout configured
- **WHEN** `command_timeout: 5.0` is set in `actions.yaml`
- **THEN** the command window stays open for 5 seconds
