# Capability: Web Interface

## Purpose
Provide a browser-based dashboard for monitoring and controlling the Alexa Custom client, featuring real-time event streaming, live logs, VU meters, and remote restart capabilities.

## Requirements

### Requirement: HTTP server with embedded dashboard
The system SHALL serve a single-page HTML dashboard over HTTP when started with `--web`. The HTML, CSS, and JavaScript SHALL be embedded in `web.py` as a string constant and served at `GET /`. The server SHALL bind to `0.0.0.0` on the configured port (default `8080`) to allow LAN access.

#### Scenario: Dashboard served on startup
- **WHEN** `alexa-client --web` is started
- **THEN** `GET http://<host>:8080/` returns HTTP 200 with `Content-Type: text/html`

#### Scenario: Custom port via flag
- **WHEN** `alexa-client --web --web-port 9090` is started
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
The system SHALL capture Python `logging` records at DEBUG level and above and broadcast them to all connected WebSocket clients as `{"type": "log", "level": "...", "ts": "HH:MM:SS", "msg": "..."}` messages. Log records SHALL NOT be written to stdout when `--web` is active (to avoid polluting a redirected log file with terminal escape codes).

#### Scenario: Log record broadcast to browser
- **WHEN** any module calls `logging.info("connected")`
- **THEN** a `{"type": "log", "level": "INFO", ...}` message is sent to all WebSocket clients

### Requirement: Restart control
The system SHALL accept a WebSocket control message `{"type": "control", "action": "restart"}` from any connected client. On receipt, the server SHALL broadcast `{"type": "restarting"}` to all clients and then execute `os.execv(sys.executable, sys.argv)` to replace the process image.

#### Scenario: Restart triggered from browser
- **WHEN** the browser sends `{"type": "control", "action": "restart"}` over WebSocket
- **THEN** clients receive `{"type": "restarting"}` and the process restarts with the same arguments

### Requirement: Clean shutdown on Ctrl+C
The system SHALL exit cleanly when `SIGINT` (Ctrl+C) is received. The aiohttp server SHALL stop accepting new connections, open WebSocket clients SHALL be closed, and the process SHALL exit with code 0. The LiveKit FFI thread SHALL be force-exited via `os._exit(0)` after a short grace period (same pattern as `--tui`).

#### Scenario: Ctrl+C exits without traceback
- **WHEN** the user presses Ctrl+C while `--web` is running
- **THEN** the process exits cleanly with no unhandled exception printed to stderr

### Requirement: Auto-reconnecting browser client
The browser JavaScript client SHALL automatically attempt to reconnect to `/ws` after a 2-second delay when the WebSocket connection closes unexpectedly.

#### Scenario: Server restarts and browser reconnects
- **WHEN** the process restarts and the server becomes available again
- **THEN** the browser reconnects within 3 seconds without a page refresh
