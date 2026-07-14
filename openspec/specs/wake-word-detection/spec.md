# Capability: Wake Word Detection

## Purpose
Listen for configured wake words in the background and trigger command listening mode.

## Requirements

### Requirement: Continuous wake word listening
The system SHALL run a background STT pipeline that listens continuously for configured wake words using the **stage-1 backend** (`stt.stage1`). When using the Vosk backend for stage 1, recognition SHALL use grammar-mode recognition for efficiency. The grammar SHALL include both wake-word phrases and confuser phrases (see `wake-word-confusers` capability). When a stage-1 result matches a confuser phrase the recogniser SHALL be reset silently without entering command mode.

For the Vosk stage-1 backend, acceptance of a wake-word match SHALL additionally require:
- **Aggregated confidence**: the acceptance confidence SHALL be computed across **all tokens** of the matched wake phrase according to `stt.stage1.confidence_mode` (`first` | `min` | `mean`), not solely the first token. The aggregated confidence SHALL meet or exceed `stt.stage1.confidence`. When `confidence_mode` is unset it SHALL default to a value that preserves prior behaviour for single-token wake words.
- **RMS energy pre-gate**: audio whose RMS energy is below `stt.stage1.rms_threshold` SHALL NOT be accepted as a wake word, so that quiet far-field cross-talk does not reach a wake decision.

Recognition SHALL be automatically gated (paused) when a LiveKit call is active or when the TTS engine is speaking. The system SHALL report its listening status via MQTT. Both STT backends (stage 1 and stage 2) are loaded at daemon startup.

#### Scenario: Wake word detected
- **WHEN** a configured wake word is spoken clearly into the microphone
- **THEN** the system plays a wake acknowledgement beep, publishes `listening` to MQTT, and transitions to command listening mode using the stage-2 backend

#### Scenario: Non-wake-word speech ignored
- **WHEN** speech is detected that does not match any configured wake word or confuser phrase
- **THEN** the system remains in stage-1 listening mode and takes no action

#### Scenario: Confuser phrase silently rejected
- **WHEN** speech matches a confuser phrase (automatic or manual)
- **THEN** stage-1 is reset silently, no beep plays, MQTT state remains `idle`, and command mode is NOT entered

#### Scenario: Low-confidence discriminative token rejected
- **WHEN** a multi-word wake phrase is decoded where the leading token is confident but a later discriminative token (e.g. "galileo") is below threshold, and `confidence_mode` is `min` or `mean`
- **THEN** the aggregated confidence falls below `stt.stage1.confidence` and the system does NOT enter command mode

#### Scenario: Quiet cross-talk gated by RMS
- **WHEN** stage-1 receives speech whose RMS energy is below `stt.stage1.rms_threshold`
- **THEN** the audio is not accepted as a wake word regardless of grammar decode result

#### Scenario: STT starts without LiveKit
- **WHEN** the process starts and `conf/config.yaml` is present
- **THEN** wake word listening begins using the stage-1 backend before any LiveKit connection is established

#### Scenario: STT paused during call
- **WHEN** a LiveKit session is active
- **THEN** the stage-1 recogniser is gated, STT status shows "STT paused during call", and the system publishes `gated` to MQTT

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

### Requirement: Configurable wake word list
The system SHALL load wake words from the `wake_words` list in `actions.yaml`. At least one wake word MUST be defined.

#### Scenario: Multiple wake words configured
- **WHEN** `wake_words: ["galileo", "aiuto"]` is set in `actions.yaml`
- **THEN** either spoken word triggers command listening mode

#### Scenario: Missing wake word list
- **WHEN** `actions.yaml` is present but `wake_words` is empty or absent
- **THEN** the system logs an error and exits with a non-zero status

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window using the **stage-2 backend** (`stt.stage2`). The window duration is `recognition.command_timeout`. All other behaviour (trigger matching, timeout beep, MQTT publish) is unchanged.

#### Scenario: Command captured using stage-2 backend
- **WHEN** wake word is detected with stage1=vosk and stage2=vosk
- **THEN** the command window uses the Vosk model for transcription

#### Scenario: Command matched using group triggers
- **WHEN** wake word group "galileo" has its own triggers and the user speaks a matching phrase
- **THEN** the corresponding actions are dispatched

#### Scenario: Command matched using global fallback triggers
- **WHEN** wake word group "assistente" has no triggers defined and the user speaks a phrase matching a global trigger
- **THEN** the corresponding actions are dispatched using the global fallback trigger list

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `recognition.command_timeout` seconds
- **THEN** the system plays a timeout beep and resumes wake word listening with stage-1

#### Scenario: Custom timeout configured
- **WHEN** `recognition.command_timeout: 5.0` is set
- **THEN** the command window stays open for 5 seconds

#### Scenario: No triggers anywhere
- **WHEN** a wake word group has no triggers and the global triggers list is also empty
- **THEN** the command window opens, nothing matches, the timeout beep plays, and the system returns to Stage 1

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
PipeWire source name

#### Scenario: parec terminated on shutdown
- **WHEN** the process receives SIGTERM or SIGINT
- **THEN** the `parec` subprocess is terminated before the process exits
