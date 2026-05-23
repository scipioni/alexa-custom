# Capability: MQTT Integration

## Purpose
Provide bidirectional communication with an MQTT broker for smart home integration.

## Requirements

### Requirement: Background MQTT client
The system SHALL maintain a persistent, asynchronous background connection to an MQTT broker. Connection parameters (host, port) MUST be configurable via environment variables.

#### Scenario: MQTT client connects at startup
- **WHEN** MQTT configuration is present in the environment
- **THEN** the client establishes a connection to the broker and starts its background loop

### Requirement: Home Assistant Discovery registration
On successful connection to the MQTT broker, the system SHALL publish Home Assistant MQTT Discovery payloads (retained) to register the client as a device. It MUST register a binary sensor for state, a text entity for TTS commands, and an event/sensor for voice commands.

#### Scenario: Auto-discovery on startup
- **WHEN** the client connects to the MQTT broker
- **THEN** it publishes discovery JSON payloads to topics matching `homeassistant/<component>/<node_id>/config`

### Requirement: State reporting via MQTT
The system SHALL publish its current operational state (e.g., `idle`, `listening`, `speaking`, `gated`) to a configured MQTT topic whenever the state changes.

#### Scenario: Status update on wake word detection
- **WHEN** a wake word is detected
- **THEN** the system publishes `listening` to the state topic before opening the command window

### Requirement: Voice command forwarding
Whenever the system transcribes a command (regardless of local `actions.yaml` match), it SHALL publish the transcript as a JSON payload to a configured MQTT topic.

#### Scenario: Transcription always published
- **WHEN** a voice command is transcribed after a wake word
- **THEN** a JSON payload containing the transcript text and wake word is published to MQTT

### Requirement: Remote action trigger (MQTT listener)
The system SHALL subscribe to MQTT command topics and execute corresponding local actions (e.g., `say`, `tone`, `livekit_join`) when specific payloads are received.

#### Scenario: HA triggers TTS
- **WHEN** a message is received on the `tts/set` topic
- **THEN** the system executes a local `say` action with the received text
