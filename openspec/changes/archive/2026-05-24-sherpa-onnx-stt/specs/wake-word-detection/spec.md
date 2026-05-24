# Delta Spec: wake-word-detection (sherpa-onnx-stt change)

## MODIFIED Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words. Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking to prevent false triggers. The system SHALL report its listening status (e.g., `idle`, `listening`, `gated`) via MQTT. The STT backend is configurable: Vosk (default) or sherpa-onnx.

#### Scenario: Wake word detected
- **WHEN** a configured wake word is spoken clearly into the microphone
- **THEN** the system plays a wake acknowledgement beep, publishes `listening` to MQTT, and transitions to command listening mode

#### Scenario: Non-wake-word speech ignored
- **WHEN** speech is detected that does not match any configured wake word
- **THEN** the system remains in Stage 1 listening mode and takes no action

#### Scenario: STT starts without LiveKit
- **WHEN** the process starts and `config.yaml` is present
- **THEN** wake word listening begins before any LiveKit connection is established

#### Scenario: STT paused during call
- **WHEN** a LiveKit session is active
- **THEN** the recognizer is gated, STT status shows "STT paused during call", and the system publishes `gated` to MQTT
