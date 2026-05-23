## MODIFIED Requirements

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
