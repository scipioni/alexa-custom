## MODIFIED Requirements

### Requirement: SOS trigger on "aiuto agente"
When the user says a SOS wake word, the system SHALL:
1. Open a browser tab with a LiveKit room join link for the user
2. Spawn the AI agent as a local subprocess (or signal the cloud agent via MQTT/webhook)
3. NOT connect the device itself as a room participant
4. Play a confirmatory TTS message

#### Scenario: User activates SOS trigger
- **WHEN** the user says "emergenza" (or configured SOS trigger)
- **THEN** the device opens a browser tab for the LiveKit room
- **AND** the AI agent joins the same room as participant `ai-agent`
- **AND** the device does NOT join the room as `headless-participant`
- **AND** the device plays "Sto collegando l'assistente di emergenza" via local TTS
- **AND** the only participants are the browser user and the AI agent

### Requirement: AI agent stays for full conversation
The AI agent SHALL remain in the LiveKit room until the user says "disconnetti" or all human participants leave the room. Saying "sto bene" SHALL NOT cause the agent to disconnect.

#### Scenario: User says "sto bene"
- **WHEN** the user is in an SOS call with the AI agent
- **AND** the user says "sto bene"
- **THEN** the AI agent acknowledges ("Sono contento, resto comunque a disposizione")
- **AND** the agent SHALL remain in the room and continue listening

#### Scenario: User says "disconnetti"
- **WHEN** the user says "disconnetti"
- **THEN** the AI agent says "Arrivederci"
- **AND** the agent SHALL disconnect from the room
- **AND** the browser tab SHALL close or disconnect

#### Scenario: All participants leave
- **WHEN** all human participants leave the room
- **THEN** the AI agent SHALL disconnect automatically
