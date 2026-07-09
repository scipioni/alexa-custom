# Delta: Graceful Shutdown

## ADDED Requirements

### Requirement: SIGTERM triggers ordered teardown
The daemon SHALL install a SIGTERM handler in the production (web-server) run path that invokes the same ordered shutdown sequence as internal restart triggers: signal the STT thread to stop, publish MQTT offline state, leave the LiveKit room gracefully, stop the audio watcher, clear the display, then exit. `systemctl stop` and `systemctl restart` SHALL therefore perform a clean teardown instead of an abrupt process kill.

#### Scenario: systemctl stop
- **WHEN** systemd sends SIGTERM to the daemon
- **THEN** the LiveKit room is disconnected (no ghost participant), MQTT publishes offline, STT and watcher threads are signalled to stop, the display is cleared, and the process exits within the systemd stop timeout

#### Scenario: SIGTERM during an active call
- **WHEN** SIGTERM arrives while a LiveKit session is active
- **THEN** the room disconnect is sent before process exit so the remote participant sees a clean departure
