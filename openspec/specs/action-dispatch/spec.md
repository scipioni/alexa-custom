# Capability: Action Dispatch

## Purpose
Map recognized trigger phrases to a sequence of actions.

## Requirements

### Requirement: Config-driven trigger-to-action mapping
The system SHALL load trigger phrases and action sequences from `config.yaml` (falling back to `actions.yaml` with a deprecation warning when `config.yaml` is absent). Each trigger entry defines a `phrase` (matched against STT output) and a list of `actions` to execute sequentially. In addition to local triggers, all recognized phrases SHALL be published to MQTT for external processing. The active trigger list SHALL be updated without process restart when the config file changes on disk.

#### Scenario: Single action on phrase match
- **WHEN** the recognized command matches a configured trigger phrase
- **THEN** all actions in that trigger's `actions` list are executed in order

#### Scenario: Multiple actions on one phrase
- **WHEN** a trigger defines two actions (e.g., telegram + livekit_join)
- **THEN** both actions execute sequentially in the listed order

#### Scenario: No config file present
- **WHEN** neither `config.yaml` nor `actions.yaml` exists at startup
- **THEN** the process behaves as before (auto-connect to LiveKit, no wake word detection)

#### Scenario: Trigger list updated after hot reload
- **WHEN** a new trigger phrase is added to `config.yaml` and the file is saved
- **THEN** the next recognized command is matched against the updated trigger list (including the new phrase)

### Requirement: mqtt_publish action type
The system SHALL support an `mqtt_publish` action type that allows publishing a specific `payload` to a specific `topic` on the configured MQTT broker.

#### Scenario: Trigger HA script via MQTT
- **WHEN** an `mqtt_publish` action is executed with `topic: "home/script/lights"` and `payload: "toggle"`
- **THEN** the message is sent to the MQTT broker

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
The system SHALL support a `livekit_join` action type that connects to the configured LiveKit room. If already connected, the action is a no-op. The connection attempt SHALL employ an exponential backoff strategy if the initial connection fails.

#### Scenario: Trigger LiveKit connection
- **WHEN** a `livekit_join` action is dispatched
- **THEN** the LiveKit client connects to the room specified in the action (or `LIVEKIT_ROOM` env var if not specified)

#### Scenario: Already connected
- **WHEN** a `livekit_join` action is dispatched and a LiveKit session is active
- **THEN** the action is skipped and a debug log entry is written

#### Scenario: Connection failure backoff
- **WHEN** a `livekit_join` action is dispatched and the connection fails
- **THEN** the system SHALL wait before retrying, doubling the wait time on each subsequent failure (e.g., 2s, 4s, 8s) up to a maximum delay of 30 seconds.

### Requirement: say action type
The system SHALL support a `say` action type in the trigger sequence. This action converts a provided `text` parameter into audible speech using the configured TTS backend.

#### Scenario: Sequence with voice feedback
- **WHEN** a trigger defines multiple actions starting with `say`
- **THEN** the system speaks the text first, then proceeds to subsequent actions (e.g., telegram or livekit_join)

### Requirement: Graceful unknown action type
The system SHALL log a warning and skip any action entry with an unrecognized `type` field, without crashing or halting other actions in the sequence.

#### Scenario: Unknown action type in config
- **WHEN** the config file contains `type: sms` (not implemented)
- **THEN** a warning is logged and the next action in the sequence continues
