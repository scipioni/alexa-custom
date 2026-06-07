## MODIFIED Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words using the **stage-1 backend** (`stt.stage1`). When using the Vosk backend for stage 1, recognition SHALL use grammar-mode recognition for efficiency. Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking. The system SHALL report its listening status via MQTT. Both STT backends (stage 1 and stage 2) are loaded at daemon startup.

#### Scenario: Wake word detected
- **WHEN** a configured wake word is spoken clearly into the microphone
- **THEN** the system plays a wake acknowledgement beep, publishes `listening` to MQTT, and transitions to command listening mode using the stage-2 backend

#### Scenario: Non-wake-word speech ignored
- **WHEN** speech is detected that does not match any configured wake word
- **THEN** the system remains in stage-1 listening mode and takes no action

#### Scenario: STT starts without LiveKit
- **WHEN** the process starts and `conf/config.yaml` is present
- **THEN** wake word listening begins using the stage-1 backend before any LiveKit connection is established

#### Scenario: STT paused during call
- **WHEN** a LiveKit session is active
- **THEN** the stage-1 recogniser is gated, STT status shows "STT paused during call", and the system publishes `gated` to MQTT

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window using the **stage-2 backend** (`stt.stage2`). The window duration is `recognition.command_timeout`. All other behaviour (trigger matching, timeout beep, MQTT publish) is unchanged.

#### Scenario: Command captured using stage-2 backend
- **WHEN** wake word is detected with stage1=vosk and stage2=sherpa-onnx
- **THEN** the command window uses the sherpa-onnx model for transcription

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `recognition.command_timeout` seconds
- **THEN** the system plays a timeout beep and resumes wake word listening with stage-1

#### Scenario: Command matched using group triggers
- **WHEN** wake word group "galileo" has its own triggers and the user speaks a matching phrase
- **THEN** the corresponding actions are dispatched

#### Scenario: Custom timeout configured
- **WHEN** `recognition.command_timeout: 5.0` is set
- **THEN** the command window stays open for 5 seconds
