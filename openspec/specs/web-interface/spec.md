# Capability: Web Interface

## Purpose
Provide a browser-based dashboard for monitoring and controlling the Alexa Custom client, featuring real-time event streaming, live logs, VU meters, and remote restart capabilities.

## Requirements

### Requirement: HTTP server with embedded dashboard
The system SHALL serve a single-page HTML dashboard over HTTP. The HTML, CSS, and JavaScript SHALL be stored in `alexa_custom/dashboard.html` and loaded into memory at module import time via `(Path(__file__).parent / "dashboard.html").read_text()`. The loaded content SHALL be served at `GET /`. The server SHALL bind to `0.0.0.0` on the configured port (default `8080`) to allow LAN access.

#### Scenario: Dashboard served on startup
- **WHEN** `alexa-client` is started
- **THEN** `GET http://<host>:8080/` returns HTTP 200 with `Content-Type: text/html`

#### Scenario: Custom port via flag
- **WHEN** `alexa-client --web-port 9090` is started
- **THEN** the server listens on port 9090

### Requirement: WebSocket real-time event stream
The system SHALL accept WebSocket connections at `GET /ws`. On connect, the server SHALL immediately send a `hello` message containing the current state snapshot (connection status, room name, active participants). Subsequent events SHALL be broadcast to all connected clients as JSON messages.

#### Scenario: Client connects and receives hello
- **WHEN** a browser opens a WebSocket to `/ws`
- **THEN** the first message received has `type: "hello"` and includes current room and status

#### Scenario: Multiple clients receive all events
- **WHEN** two browsers are connected to `/ws` and a participant joins
- **THEN** both receive a `participant_joined` message

#### Scenario: Client disconnect does not crash server
- **WHEN** a WebSocket client disconnects mid-stream
- **THEN** the server removes the client from its set and continues serving remaining clients

### Requirement: VU meter throttling
The system SHALL throttle `volume_update` WebSocket messages to a maximum of 4 per second. The latest available values SHALL always be sent; intermediate values MAY be dropped.

#### Scenario: High-frequency audio levels throttled
- **WHEN** the audio subsystem emits 10 `volume_update` events per second
- **THEN** the WebSocket stream carries no more than 4 `volume_update` messages per second per client

### Requirement: Live log stream
The system SHALL capture Python `logging` records at DEBUG level and above and broadcast them to all connected WebSocket clients as `{"type": "log", "level": "...", "ts": "HH:MM:SS", "msg": "..."}` messages. Log records SHALL NOT be written to stdout (to avoid polluting a redirected log file with terminal escape codes).

#### Scenario: Log record broadcast to browser
- **WHEN** any module calls `logging.info("connected")`
- **THEN** a `{"type": "log", "level": "INFO", ...}` message is sent to all WebSocket clients

### Requirement: Restart control
The system SHALL accept a WebSocket control message `{"type": "control", "action": "restart"}` from any connected client. On receipt, the server SHALL broadcast `{"type": "restarting"}` to all clients and then execute `os.execv(sys.executable, sys.argv)` to replace the process image.

#### Scenario: Restart triggered from browser
- **WHEN** the browser sends `{"type": "control", "action": "restart"}` over WebSocket
- **THEN** clients receive `{"type": "restarting"}` and the process restarts with the same arguments

### Requirement: Clean shutdown on Ctrl+C
The system SHALL exit cleanly when `SIGINT` (Ctrl+C) is received. The aiohttp server SHALL stop accepting new connections, open WebSocket clients SHALL be closed, and the process SHALL exit with code 0. The LiveKit FFI thread SHALL be force-exited via `os._exit(0)` after a short grace period.

#### Scenario: Ctrl+C exits without traceback
- **WHEN** the user presses Ctrl+C while the client is running
- **THEN** the process exits cleanly with no unhandled exception printed to stderr

### Requirement: Auto-reconnecting browser client
The browser JavaScript client SHALL automatically attempt to reconnect to `/ws` after a 2-second delay when the WebSocket connection closes unexpectedly. The browser SHALL NOT reload the page under any normal operation; reconnection SHALL happen transparently.

#### Scenario: Server restarts and browser reconnects
- **WHEN** the process restarts and the server becomes available again
- **THEN** the browser reconnects within 3 seconds without a page refresh

### Requirement: No full-page reload on file changes
The WebSocket server SHALL NOT broadcast a `{"type": "reload"}` message when monitored files change. Configuration reloads (triggered by the `ConfigManager`) SHALL update state internally without instructing the browser to perform a full page reload. The browser JavaScript SHALL also not contain a `location.reload()` handler for any incoming WebSocket message type except `restarting`.

#### Scenario: Config file changed during runtime
- **WHEN** a monitored config file changes on disk (e.g., volume persisted to config.yaml)
- **THEN** the server processes the change internally and the web dashboard continues running without a page reload

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
