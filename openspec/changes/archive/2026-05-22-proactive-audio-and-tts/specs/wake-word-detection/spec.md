## MODIFIED Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words using Vosk grammar-mode recognition. Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking to prevent false triggers.

#### Scenario: Wake word detected
- **WHEN** a configured wake word is spoken clearly into the microphone
- **THEN** the system plays a wake acknowledgement beep and transitions to command listening mode

#### Scenario: Non-wake-word speech ignored
- **WHEN** speech is detected that does not match any configured wake word
- **THEN** the system remains in Stage 1 listening mode and takes no action

#### Scenario: STT starts without LiveKit
- **WHEN** the process starts and `actions.yaml` is present
- **THEN** wake word listening begins before any LiveKit connection is established

#### Scenario: STT paused during call
- **WHEN** a LiveKit session is active
- **THEN** the recognizer is gated and STT status shows "STT paused during call"
