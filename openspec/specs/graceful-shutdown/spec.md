# Capability: Graceful Shutdown

## Purpose
Ensure that all subsystems are torn down in a predictable, ordered sequence before any process restart, preventing resource leaks, orphaned connections, and message loss.

## Requirements

### Requirement: Ordered teardown before process restart
The system SHALL perform an ordered shutdown sequence before any `os.execv()` restart, regardless of the restart trigger (config hot-reload, source file change, or web dashboard restart command). The sequence SHALL be:

1. Signal the STT thread to stop (set stop event)
2. Publish MQTT offline state and disconnect cleanly
3. Leave the LiveKit room gracefully
4. Wait up to 300 ms for pending async tasks to drain
5. Execute `os.execv()` to replace the process

#### Scenario: Config hot-reload triggers graceful restart
- **WHEN** a source file change is detected by the source watcher
- **THEN** MQTT publishes offline, LiveKit leaves the room, STT is signalled to stop, and only then `os.execv()` is called

#### Scenario: Web dashboard restart triggers graceful restart
- **WHEN** the web dashboard receives a restart control message
- **THEN** the same shutdown sequence executes before `os.execv()`

#### Scenario: Shutdown completes within timeout
- **WHEN** a restart is triggered
- **THEN** the entire shutdown sequence (MQTT + LiveKit + drain) completes within 1 second before `os.execv()`

### Requirement: Single shutdown callback shared across restart sites
The system SHALL expose a single async shutdown callback created in the main async entrypoint and passed to all subsystems that may trigger a restart. No subsystem SHALL call `os.execv()` directly; all SHALL invoke the shared callback.

#### Scenario: ConfigManager uses shutdown callback
- **WHEN** `ConfigManager` detects a source file change
- **THEN** it calls the injected `shutdown_callback` coroutine rather than calling `os.execv()` directly

#### Scenario: WebServer uses shutdown callback
- **WHEN** `WebServer` receives a restart control message over WebSocket
- **THEN** it calls the injected `shutdown_callback` coroutine rather than calling `os.execv()` directly

### Requirement: SIGTERM triggers ordered teardown
The daemon SHALL install a SIGTERM handler in the production (web-server) run path that invokes the same ordered shutdown sequence as internal restart triggers: signal the STT thread to stop, publish MQTT offline state, leave the LiveKit room gracefully, stop the audio watcher, clear the display, then exit. `systemctl stop` and `systemctl restart` SHALL therefore perform a clean teardown instead of an abrupt process kill.

#### Scenario: systemctl stop
- **WHEN** systemd sends SIGTERM to the daemon
- **THEN** the LiveKit room is disconnected (no ghost participant), MQTT publishes offline, STT and watcher threads are signalled to stop, the display is cleared, and the process exits within the systemd stop timeout

#### Scenario: SIGTERM during an active call
- **WHEN** SIGTERM arrives while a LiveKit session is active
- **THEN** the room disconnect is sent before process exit so the remote participant sees a clean departure
