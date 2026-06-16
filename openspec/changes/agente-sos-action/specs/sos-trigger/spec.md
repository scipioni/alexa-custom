## ADDED Requirements

### Requirement: SOS trigger on "aiuto agente"
When the user says "aiuto agente", the system SHALL NOT run the `agent_session` action. Instead it SHALL:
1. Connect the device to the configured LiveKit room
2. Publish an MQTT SOS signal to notify the cloud agent
3. Play a confirmatory tone or TTS message

#### Scenario: User says "aiuto agente" with MQTT connected
- **WHEN** the user says "aiuto agente"
- **THEN** the device joins the LiveKit room
- **AND** an MQTT message `sos/request` is published with the room name
- **AND** the device is in the room waiting for the Agente SOS to join

#### Scenario: User says "aiuto agente" without MQTT connection
- **WHEN** the user says "aiuto agente"
- **AND** the MQTT client is not connected
- **THEN** the device still joins the LiveKit room
- **AND** a warning is logged
- **AND** the device waits for the Agente SOS (which may never arrive)

### Requirement: SOS trigger MQTT topic
The system SHALL publish to MQTT topic `sos/request` with payload containing the room name and timestamp.

#### Scenario: MQTT publish format
- **WHEN** the SOS trigger fires
- **THEN** an MQTT message is published to `sos/request`
- **AND** the payload SHALL be JSON with fields `room` (string) and `timestamp` (int)

### Requirement: Fallback TTS on trigger
The system SHALL play a local TTS message after triggering, before the Agente SOS joins, to inform the user.

#### Scenario: TTS fallback played
- **WHEN** the device joins the room and publishes MQTT
- **THEN** it plays "Sto collegando l'assistente di emergenza" via local TTS
