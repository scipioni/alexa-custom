# Capability: Web Interface

## ADDED Requirements

### Requirement: No full-page reload on file changes
The WebSocket server SHALL NOT broadcast a `{"type": "reload"}` message when monitored files change. Configuration reloads (triggered by the `ConfigManager`) SHALL update state internally without instructing the browser to perform a full page reload. The browser JavaScript SHALL also not contain a `location.reload()` handler for any incoming WebSocket message type except `restarting`.

#### Scenario: Config file changed during runtime
- **WHEN** a monitored config file changes on disk (e.g., volume persisted to config.yaml)
- **THEN** the server processes the change internally and the web dashboard continues running without a page reload

## MODIFIED Requirements

### Requirement: Auto-reconnecting browser client
The browser JavaScript client SHALL automatically attempt to reconnect to `/ws` after a 2-second delay when the WebSocket connection closes unexpectedly. The browser SHALL NOT reload the page under any normal operation; reconnection SHALL happen transparently.

#### Scenario: Server restarts and browser reconnects
- **WHEN** the process restarts and the server becomes available again
- **THEN** the browser reconnects within 3 seconds without a page refresh
