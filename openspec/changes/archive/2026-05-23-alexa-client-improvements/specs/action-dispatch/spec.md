## MODIFIED Requirements

### Requirement: livekit_join action type
The system SHALL support a `livekit_join` action type that connects to the configured LiveKit room. If already connected, the action is a no-op. The connection attempt SHALL employ an exponential backoff strategy if the initial connection fails.

#### Scenario: Trigger LiveKit connection
- **WHEN** a `livekit_join` action is dispatched
- **THEN** the LiveKit client connects to the room specified in the action (or `LIVEKIT_ROOM` env var if not specified)

#### Scenario: Already connected
- **WHEN** a `livekit_join` action is dispatched and a LiveKit session is active
- **THEN** the action is skipped and a debug log entry is written

#### Scenario: Connection failure backoff
- **WHEN** a `livekit_join` action is dispatched and the connection fails
- **THEN** the system SHALL wait before retrying, doubling the wait time on each subsequent failure (e.g., 2s, 4s, 8s) up to a maximum delay of 30 seconds.
