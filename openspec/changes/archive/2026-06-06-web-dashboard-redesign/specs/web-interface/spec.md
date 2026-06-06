## MODIFIED Requirements

### Requirement: HTTP server with embedded dashboard
The system SHALL serve a single-page HTML dashboard over HTTP when started with `--web`. The HTML, CSS, and JavaScript SHALL be stored in `alexa_custom/dashboard.html` and loaded into memory at module import time via `(Path(__file__).parent / "dashboard.html").read_text()`. The loaded content SHALL be served at `GET /`. The server SHALL bind to `0.0.0.0` on the configured port (default `8080`) to allow LAN access.

#### Scenario: Dashboard served on startup
- **WHEN** `alexa-client --web` is started
- **THEN** `GET http://<host>:8080/` returns HTTP 200 with `Content-Type: text/html`

#### Scenario: Custom port via flag
- **WHEN** `alexa-client --web --web-port 9090` is started
- **THEN** the server listens on port 9090

## ADDED Requirements

### Requirement: Glassmorphism visual style
The dashboard SHALL use a glassmorphism visual design: panels with `backdrop-filter: blur(12px)`, semi-transparent backgrounds (`rgba(255,255,255,0.04)`), `1px` borders at `rgba(255,255,255,0.08)`, and `12px` border-radius. The colour palette SHALL be defined as CSS custom properties on `:root` including `--wake` (orange), `--match` (green), `--nomatch` (red), `--bg` (near-black), `--surface`, `--border`, `--text`, and `--muted`. The font SHALL be the system font stack (`system-ui, -apple-system, sans-serif`) with no external font dependency.

#### Scenario: Panels render with glass effect in supported browsers
- **WHEN** the dashboard is opened in a browser that supports `backdrop-filter`
- **THEN** panels display with a frosted-glass blur behind their content

#### Scenario: Layout degrades gracefully without backdrop-filter
- **WHEN** the dashboard is opened in a browser without `backdrop-filter` support
- **THEN** panels render with their flat `rgba` background colour and the layout is fully functional

### Requirement: Segmented VU meter
Each audio channel (MIC, SPK) SHALL display a segmented equalizer-style level meter with 20 segments. Segments SHALL be coloured by threshold: segments 1–14 use the `--match` (green) colour, segments 15–17 use amber (`#facc15`), and segments 18–20 use `--nomatch` (red). Active segments SHALL display at full opacity; inactive segments SHALL display at 10% opacity. The active segment count SHALL update on every `volume_update` WebSocket message.

#### Scenario: Low level shows green segments only
- **WHEN** a `volume_update` message carries a level that maps to 8 active segments
- **THEN** segments 1–8 are fully opaque green and segments 9–20 are dim

#### Scenario: High level activates red segments
- **WHEN** a `volume_update` message carries a level that maps to 19 active segments
- **THEN** segments 18–19 are fully opaque red

### Requirement: STT hero card with CSS layout
The dashboard layout SHALL use CSS Grid with a full-width STT hero card spanning the top of the main area, above a three-column panel row (wake words | logs | history). The hero card SHALL display the current STT state, active wake word, and live transcription text. Layout SHALL use `grid-template-columns: 240px 1fr 240px` for the panel row.

#### Scenario: Hero card spans full width
- **WHEN** the dashboard is loaded
- **THEN** the STT hero card occupies the full width above the three panel columns

### Requirement: Live personality animations
The dashboard SHALL play CSS keyframe animations in response to STT state changes received over WebSocket:

- On `stt: wake` — the active wake word card SHALL display an orange pulsing glow ring animation.
- On `stt: matched` — the STT hero card SHALL flash green (opacity pulse from full to background and back).
- On `stt: nomatch` — the STT hero card SHALL play a horizontal shake animation.
- On `stt: partial` — the transcription text SHALL display with a blinking cursor appended.
- On history row insertion — the new row SHALL slide in from above with a CSS transition.

Animations SHALL be implemented as CSS `@keyframes` classes added/removed via JavaScript. A re-trigger of the same animation (new event before prior animation completes) SHALL cancel the prior timeout and restart cleanly.

#### Scenario: Wake word fires and card pulses
- **WHEN** a `{"type": "stt", "state": "wake", "word": "galileo"}` message is received
- **THEN** the galileo wake word card gains the glow-pulse animation class for its duration then returns to rest

#### Scenario: Matched trigger flashes green
- **WHEN** a `{"type": "stt", "state": "matched"}` message is received
- **THEN** the STT hero card plays a green flash animation

#### Scenario: No-match shakes red
- **WHEN** a `{"type": "stt", "state": "nomatch"}` message is received
- **THEN** the STT hero card plays a horizontal shake animation

#### Scenario: Partial text shows blinking cursor
- **WHEN** a `{"type": "stt", "state": "partial", "text": "chiama"}` message is received
- **THEN** the hero card displays `"chiama▋"` with a CSS blink animation on the cursor character

#### Scenario: History row slides in
- **WHEN** a new entry is prepended to the history panel
- **THEN** the row slides in from above via a CSS transform transition
