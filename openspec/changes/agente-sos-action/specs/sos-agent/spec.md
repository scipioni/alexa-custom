## ADDED Requirements

### Requirement: Agente SOS MQTT subscription
The Agente SOS SHALL subscribe to MQTT topic `sos/request` and connect to the LiveKit room specified in the payload.

#### Scenario: MQTT message received
- **WHEN** the Agente SOS receives an MQTT message on `sos/request`
- **THEN** it SHALL parse the JSON payload for the `room` field
- **AND** join the specified LiveKit room using a valid JWT token

### Requirement: Safety greeting
When the Agente SOS joins the room and detects the user participant, it SHALL initiate a voice conversation starting with a safety greeting.

#### Scenario: Agent joins and greets
- **WHEN** the Agente SOS joins the room and a user participant is connected
- **THEN** the agent SHALL speak: "Sono l'assistente di emergenza. Tutto bene? Hai bisogno di aiuto?"

#### Scenario: No user in room
- **WHEN** the Agente SOS joins the room
- **AND** no user participant is present within 10 seconds
- **THEN** the agent SHALL log a warning and disconnect

### Requirement: User indicates safety
If the user responds positively (e.g. "sì", "tutto bene", "ok"), the Agente SOS SHALL confirm and leave the room.

#### Scenario: User says everything is fine
- **WHEN** the Agente SOS asks "Tutto bene?"
- **AND** the user responds affirmatively
- **THEN** the agent SHALL say "Ok, mi chiami se serve. Buona giornata."
- **AND** disconnect from the room

### Requirement: User needs help
If the user indicates they need help (e.g. "no", "aiuto", "chiama"), the Agente SOS SHALL:
1. Place an outbound phone call to the configured emergency number via Twilio
2. Send a Telegram notification with the SOS details

#### Scenario: User needs help — phone call
- **WHEN** the user responds negatively or requests help
- **THEN** the Agente SOS SHALL initiate a Twilio voice call to the configured emergency number
- **AND** say "SOS" to the user while the call is being placed

#### Scenario: User needs help — notification
- **WHEN** the user responds negatively or requests help
- **AND** the phone call is initiated or fails
- **THEN** the Agente SOS SHALL send a Telegram notification with:
  - Text indicating an SOS request was triggered
  - Room name for human operator to join
  - Timestamp

### Requirement: Twilio outbound call
The Agente SOS SHALL use the Twilio API to place an outbound call to a pre-configured emergency phone number.

#### Scenario: Twilio call placed
- **WHEN** the Agente SOS decides to call for help
- **THEN** it SHALL use `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` environment variables
- **AND** call the number in `SOS_PHONE_NUMBER` environment variable
- **AND** play a pre-recorded or TTS message stating there is an emergency

### Requirement: Telegram notification
The Agente SOS SHALL send a Telegram notification when help is needed, using the Telegram bot configured in the environment.

#### Scenario: Telegram sent
- **WHEN** help is needed
- **THEN** the Agente SOS SHALL send a Telegram message
- **AND** disconnect from the room after sending
