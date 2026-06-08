## MODIFIED Requirements

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
