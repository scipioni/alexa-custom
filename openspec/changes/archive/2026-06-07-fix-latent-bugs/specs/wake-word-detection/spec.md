## MODIFIED Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words. When using the Vosk backend, recognition SHALL use grammar-mode recognition for efficiency. A single grammar-restricted recognizer SHALL be used for both wake-word matching and UI partial-text display during Stage 1; no second unrestricted recognizer SHALL run in parallel. Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking to prevent false triggers. The system SHALL report its listening status (e.g., `idle`, `listening`, `gated`) via MQTT. The STT backend is configurable: Vosk (default) or sherpa-onnx.

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

#### Scenario: UI partials sourced from grammar recognizer
- **WHEN** the user is speaking during Stage 1 listening
- **THEN** partial text displayed in the web UI comes from the grammar-restricted stage-1 recognizer's PartialResult, not a separate unrestricted recognizer

### Requirement: STT ready before startup TTS
The system SHALL NOT play startup audio actions (e.g., "Sistema pronto") until the STT backend has finished loading and is actively listening for wake words. A ready event SHALL be set by the STT worker once the capture process has started, and the startup action sequence SHALL wait on this event before proceeding.

#### Scenario: Startup TTS waits for STT
- **WHEN** the daemon starts and both the STT worker and the LiveKit async loop are initializing concurrently
- **THEN** the startup TTS ("Sistema pronto") does not play until the STT worker has set its ready event

#### Scenario: STT ready event timeout
- **WHEN** the STT worker fails to set the ready event within 60 seconds
- **THEN** the startup sequence proceeds anyway and logs a warning
