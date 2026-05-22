## ADDED Requirements

### Requirement: Config-driven trigger-to-action mapping
The system SHALL load trigger phrases and action sequences from `actions.yaml`. Each trigger entry defines a `phrase` (matched against STT output) and a list of `actions` to execute sequentially.

#### Scenario: Single action on phrase match
- **WHEN** the recognized command matches a configured trigger phrase
- **THEN** all actions in that trigger's `actions` list are executed in order

#### Scenario: Multiple actions on one phrase
- **WHEN** a trigger defines two actions (e.g., telegram + livekit_join)
- **THEN** both actions execute sequentially in the listed order

#### Scenario: No actions.yaml present
- **WHEN** `actions.yaml` does not exist at startup
- **THEN** the process behaves as before (auto-connect to LiveKit, no wake word detection)

### Requirement: Fuzzy phrase matching
The system SHALL match the STT transcription against configured trigger phrases using `difflib.SequenceMatcher` with a configurable similarity threshold (default 0.70). The trigger with the highest score above the threshold is selected.

#### Scenario: Exact phrase match
- **WHEN** the transcription exactly matches a trigger phrase
- **THEN** that trigger is selected

#### Scenario: Inflected phrase match
- **WHEN** the transcription is `"chiamare"` and the trigger phrase is `"chiama"`
- **THEN** the trigger is selected if similarity exceeds the threshold

#### Scenario: No phrase meets threshold
- **WHEN** the transcription similarity to all trigger phrases is below 0.70
- **THEN** no action is dispatched and the system plays the timeout beep

### Requirement: livekit_join action type
The system SHALL support a `livekit_join` action type that connects to the configured LiveKit room. If already connected, the action is a no-op.

#### Scenario: Trigger LiveKit connection
- **WHEN** a `livekit_join` action is dispatched
- **THEN** the LiveKit client connects to the room specified in the action (or `LIVEKIT_ROOM` env var if not specified)

#### Scenario: Already connected
- **WHEN** a `livekit_join` action is dispatched and a LiveKit session is active
- **THEN** the action is skipped and a debug log entry is written

### Requirement: Graceful unknown action type
The system SHALL log a warning and skip any action entry with an unrecognized `type` field, without crashing or halting other actions in the sequence.

#### Scenario: Unknown action type in config
- **WHEN** `actions.yaml` contains `type: sms` (not implemented)
- **THEN** a warning is logged and the next action in the sequence continues
