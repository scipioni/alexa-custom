## MODIFIED Requirements

### Requirement: Config-driven trigger-to-action mapping
The system SHALL load trigger phrases and action sequences from `actions.yaml`. Each trigger entry defines a `phrase` (matched against STT output) and a list of `actions` to execute sequentially. In addition to local triggers, all recognized phrases SHALL be published to MQTT for external processing.

#### Scenario: Single action on phrase match
- **WHEN** the recognized command matches a configured trigger phrase
- **THEN** all actions in that trigger's `actions` list are executed in order

#### Scenario: Multiple actions on one phrase
- **WHEN** a trigger defines two actions (e.g., telegram + livekit_join)
- **THEN** both actions execute sequentially in the listed order

#### Scenario: No actions.yaml present
- **WHEN** `actions.yaml` does not exist at startup
- **THEN** the process behaves as before (auto-connect to LiveKit, no wake word detection)

### Requirement: mqtt_publish action type
The system SHALL support an `mqtt_publish` action type that allows publishing a specific `payload` to a specific `topic` on the configured MQTT broker.

#### Scenario: Trigger HA script via MQTT
- **WHEN** an `mqtt_publish` action is executed with `topic: "home/script/lights"` and `payload: "toggle"`
- **THEN** the message is sent to the MQTT broker
