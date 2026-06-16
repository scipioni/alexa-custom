## ADDED Requirements

### Requirement: Caregiver Telegram notification on distress
When the AI agent detects that the user is in distress (e.g., says "non sto bene", "aiuto", "chiama aiuto"), the system SHALL send a Telegram message to a pre-configured caregiver chat ID containing a LiveKit room join link.

#### Scenario: User says "non sto bene" during SOS call
- **WHEN** the user is in an SOS LiveKit room with the AI agent
- **AND** the user says "non sto bene" or similar distress phrase
- **THEN** the system sends a Telegram message to the caregiver
- **AND** the Telegram message SHALL contain a join link to the current LiveKit room
- **AND** the agent SHALL stay in the room and continue the conversation
- **AND** the system SHALL NOT send duplicate notifications for repeated distress utterances in the same session

#### Scenario: User says "non sto bene" when no caregiver is configured
- **WHEN** the user says "non sto bene"
- **AND** no caregiver Telegram chat ID is configured
- **THEN** a warning SHALL be logged
- **AND** the agent SHALL offer an alternative (e.g., "Mi dispiace, non posso chiamare nessuno al momento")

### Requirement: Caregiver joins as human participant
The caregiver SHALL be able to open the Telegram link and join the LiveKit room as a real human participant with their own audio stream, enabling direct conversation with the user and the AI agent.

#### Scenario: Caregiver opens join link
- **WHEN** the caregiver opens the Telegram join link
- **THEN** a browser tab opens with the LiveKit room
- **AND** the caregiver joins with identity `caregiver-<timestamp>`
- **AND** the caregiver can speak and hear both the user and the AI agent

### Requirement: Single notification per session
The system SHALL only send one caregiver notification per SOS session, regardless of how many times the user expresses distress.

#### Scenario: Repeated distress expression
- **WHEN** the user says "non sto bene"
- **AND** a caregiver notification has already been sent in this session
- **THEN** the system SHALL NOT send another Telegram message
- **AND** the agent SHALL reassure the user ("Ho già avvisato, stanno arrivando")
