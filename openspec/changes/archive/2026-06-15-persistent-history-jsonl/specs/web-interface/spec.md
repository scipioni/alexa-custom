## ADDED Requirements

### Requirement: Interactive persistent history cards
The web dashboard interface SHALL display unified interaction history cards populated with data loaded from the persistent backend history upon connection.

#### Scenario: Load history on handshake
- **WHEN** the dashboard page loads and connects to the WebSocket server
- **THEN** it receives the last N persistent interaction sessions as a list inside the "hello" handshake payload and immediately renders them in the HISTORY panel

#### Scenario: Receive real-time session update
- **WHEN** a new completed interaction session is broadcast by the server via a "history_item" message
- **THEN** the client UI prepends a new history card to the top of the history list, keeping up to MAX_HIST entries

### Requirement: Front-end false positive flagging
The web dashboard interface SHALL display a "Flag FP" interactive element on each history card, allowing users to mark noise or false activations.

#### Scenario: Click flag FP button
- **WHEN** the user clicks the "Flag FP" button next to a history item
- **THEN** the client sends a control WebSocket message requesting to flag that specific session ID and visually updates the card to a "Flagged" state (e.g., dimming the text, highlighting with a warning border, and disabling the button)

#### Scenario: Synchronize flagging across clients
- **WHEN** a client receives a "history_flagged" websocket message from the server
- **THEN** it locates the corresponding card in the DOM and updates its visual representation to the "Flagged" state

### Requirement: Front-end clear history request
The web dashboard interface SHALL bind the existing "clear" button in the history header to empty both the local DOM and the backend's persistent storage.

#### Scenario: Click clear history button
- **WHEN** the user clicks the "clear" button in the HISTORY section header
- **THEN** the client clears all cards from the local list and sends a "clear_history" control WebSocket command to the server
