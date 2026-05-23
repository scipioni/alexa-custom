# Capability: Wake Word Detection

## Purpose
Listen for configured wake words in the background and trigger command listening mode.

## Requirements

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

### Requirement: Configurable wake word list
The system SHALL load wake words from the `wake_words` list in `actions.yaml`. At least one wake word MUST be defined.

#### Scenario: Multiple wake words configured
- **WHEN** `wake_words: ["galileo", "aiuto"]` is set in `actions.yaml`
- **THEN** either spoken word triggers command listening mode

#### Scenario: Missing wake word list
- **WHEN** `actions.yaml` is present but `wake_words` is empty or absent
- **THEN** the system logs an error and exits with a non-zero status

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window of configurable duration (default 3 seconds). If a command is recognized within the window, it is dispatched to the action system. If the window expires without a match, the system plays a timeout beep and returns to Stage 1.

#### Scenario: Command recognized within window
- **WHEN** the user speaks a configured trigger phrase within 3 seconds of the wake beep
- **THEN** the system dispatches the corresponding actions and returns to Stage 1

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `command_timeout` seconds
- **THEN** the system plays a timeout beep and resumes wake word listening

#### Scenario: Custom timeout configured
- **WHEN** `command_timeout: 5.0` is set in `actions.yaml`
- **THEN** the command window stays open for 5 seconds

### Requirement: Audio feedback
The system SHALL play distinct audio cues: a high beep on wake word detection (Stage 2 open), a confirmation tone on successful command match, and a low beep on timeout or no match.

#### Scenario: Wake detected feedback
- **WHEN** a wake word is detected
- **THEN** a short high-pitched beep plays within 200 ms

#### Scenario: Timeout feedback
- **WHEN** the command window closes without a match
- **THEN** a short low-pitched beep plays

### Requirement: Audio capture via parec
The system SHALL capture microphone audio for STT using a `parec` subprocess at 16000 Hz, 1 channel, s16le format. The subprocess MUST be terminated cleanly on process stop.

#### Scenario: parec uses configured input device
- **WHEN** `INPUT_DEVICE` env var is set
- **THEN** `parec` is started with the corresponding PipeWire source name

#### Scenario: parec terminated on shutdown
- **WHEN** the process receives SIGTERM or SIGINT
- **THEN** the `parec` subprocess is terminated before the process exits
