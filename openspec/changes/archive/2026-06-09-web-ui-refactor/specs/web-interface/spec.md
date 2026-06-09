## ADDED Requirements

### Requirement: User and Developer Mode Toggle
The dashboard SHALL provide a UI toggle to switch between "User" and "Developer" modes.
- **User Mode**: Focuses on interaction; the Log panel and technical details are hidden.
- **Developer Mode**: Shows the Log panel and technical details.
The mode preference SHALL be persisted in `localStorage`.

#### Scenario: Switching to Developer Mode
- **WHEN** the user clicks the mode toggle icon (e.g., `< />`)
- **THEN** the Log panel becomes visible and the body gains a `.dev-mode` class

#### Scenario: Mode preference persists on reload
- **WHEN** the user sets the mode to "Developer" and reloads the page
- **THEN** the dashboard initializes in "Developer" mode

### Requirement: Electric Activation Animations
When a Wake Word card or an Action line is activated, it SHALL play a "glow and grow" animation.
- **Activation State**: The element SHALL scale up slightly (e.g., `scale(1.05)`) and display a yellow "electric" drop-shadow/glow.
- **Action Lines**: Individual action trigger lines SHALL glow green and grow slightly when their corresponding phrase is matched.

#### Scenario: Wake word activation
- **WHEN** a `stt: wake` event is received for a specific word
- **THEN** the corresponding card scales up and gains a yellow electric glow

### Requirement: Dynamic Room Card
The Room status card SHALL have two distinct states:
- **Idle State**: Displays only a representative emoji (e.g., 🏠) and its basic label. Participants are hidden.
- **Active State**: When a call is active, the card SHALL grow larger, display a glow effect, and reveal the list of active participants.

#### Scenario: Room activates on call
- **WHEN** a call becomes active (`room_status: in_call`)
- **THEN** the Room card expands to show participants and begins to glow

### Requirement: Live System Stats (Grafico)
The dashboard SHALL include a "Grafico" section that displays a live sparkline or bar chart of the system load average (1m, 5m, 15m) updated every 2 seconds.

#### Scenario: Stats update periodically
- **WHEN** a `system_stats` message is received over WebSocket
- **THEN** the Grafico visualization updates to reflect the new load average values

### Requirement: Status Indicator Colors
The "Status" text indicator SHALL change color based on the system state:
- **Listening**: Green (or `--match`)
- **Switched Off / Inactive**: Grey (or `--muted`)
- **Error**: Red (or `--nomatch`)

#### Scenario: Status color changes on state update
- **WHEN** the system enters `listening` mode
- **THEN** the status indicator text turns green

## MODIFIED Requirements

### Requirement: Segmented VU meter
Each audio channel (MIC, SPK) SHALL display a segmented equalizer-style level meter with 20 segments. Segments SHALL be oriented vertically in the right panel. Segments SHALL be coloured by threshold: segments 1–14 use the `--match` (green) colour, segments 15–17 use amber (`#facc15`), and segments 18–20 use `--nomatch` (red). Active segments SHALL display at full opacity; inactive segments SHALL display at 10% opacity. The active segment count SHALL update on every `volume_update` WebSocket message.

#### Scenario: Low level shows green segments only
- **WHEN** a `volume_update` message carries a level that maps to 8 active segments
- **THEN** segments 1–8 are fully opaque green and segments 9–20 are dim

#### Scenario: High level activates red segments
- **WHEN** a `volume_update` message carries a level that maps to 19 active segments
- **THEN** segments 18–19 are fully opaque red

### Requirement: STT hero card with CSS layout
The dashboard layout SHALL use a three-column CSS Grid: History (Left, 240px) | Main Interaction (Center, 1fr) | Controls and Monitoring (Right, 240px). The STT hero card SHALL be integrated into the top of the center column and SHALL display the current STT state, active wake word, and live transcription text.

#### Scenario: Hero card part of center column
- **WHEN** the dashboard is loaded
- **THEN** the STT hero card appears at the top of the center column, between the History and Controls columns
