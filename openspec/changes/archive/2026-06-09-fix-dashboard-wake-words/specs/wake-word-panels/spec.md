## ADDED Requirements

### Requirement: Dashboard displays one panel per wake word
The dashboard SHALL display each configured wake word in a separate visual panel. Each panel SHALL be titled with the wake word name and show:
- The wake word name as a header
- Any per-word triggers (from `wake_triggers` in action files) listed under the word
- A "globali" divider followed by the global fallback triggers

#### Scenario: Two wake words configured
- **WHEN** config has `wake_words: [{word: "galileo"}, {word: "assistente"}]`
- **THEN** the dashboard SHALL render two panels: "GALILEO" and "ASSISTENTE"

#### Scenario: Per-word trigger shown only in its panel
- **WHEN** "galileo" has per-word trigger "chiama stefano"
- **WHEN** "assistente" has no per-word triggers
- **THEN** "chiama stefano" SHALL appear only in the "GALILEO" panel
- **THEN** "ASSISTENTE" panel SHALL have no per-word trigger listed (only globali)

#### Scenario: Global triggers replicated in each panel
- **WHEN** global triggers exist (e.g., "test", "che ora è")
- **THEN** each wake-word panel SHALL display the global triggers under a "globali" section

### Requirement: Dashboard renders without crashing
The dashboard SHALL connect to the WebSocket and process the `hello` message without JavaScript errors, rendering all sections (status bar, hero card, wake-word panels, history, room status, monitoring).

#### Scenario: hello message received
- **WHEN** the WebSocket receives a `hello` message with complete `actions_config`
- **THEN** the wake-word panels SHALL populate with wake words and triggers
- **THEN** the status bar SHALL show the connection status
- **THEN** the room status SHALL update
- **THEN** no JavaScript errors SHALL be thrown
