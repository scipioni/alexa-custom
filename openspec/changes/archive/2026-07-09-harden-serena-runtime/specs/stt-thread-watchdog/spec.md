# Delta: STT Thread Watchdog

## MODIFIED Requirements

### Requirement: STT thread liveness monitoring
The system SHALL monitor the STT daemon thread for unexpected exits. A watchdog task SHALL check thread liveness at a fixed interval (≤ 10 seconds). When the thread is found dead, the system SHALL emit an `stt_dead` event to all connected WebSocket clients, log the death at ERROR level, and attempt to restart the thread. Restarts after repeated consecutive crashes SHALL back off (initial delay ≤ 10 s, doubling to a 60 s cap, reset after the thread stays alive for 10 minutes) so an unrecoverable failure (e.g. missing model) does not reload the model every detection cycle. The restarted thread SHALL be started with the same event-callback chain as the original thread (including display and dashboard consumers).

#### Scenario: STT thread exits unexpectedly
- **WHEN** the STT thread terminates while the daemon is still running
- **THEN** within 10 seconds the watchdog detects the death, emits `stt_dead` to all WebSocket clients, logs an ERROR, and starts a new STT thread

#### Scenario: STT thread running normally
- **WHEN** the STT thread is alive
- **THEN** the watchdog takes no action and emits no events

#### Scenario: Repeated crashes back off
- **WHEN** the STT thread crashes repeatedly after each restart
- **THEN** consecutive restart delays double up to 60 s, each attempt logs an ERROR, and the daemon keeps running

#### Scenario: Restarted thread keeps the full event chain
- **WHEN** the watchdog restarts the STT thread
- **THEN** display and dashboard consumers continue to receive STT events exactly as before the restart

### Requirement: STT loop heartbeat
The STT daemon thread SHALL stamp a monotonic "last alive" timestamp on every iteration of its main recognition loop, including iterations spent waiting for audio. During trigger dispatch, the dispatch path SHALL also stamp the heartbeat around its await points so that a legitimate long-running dispatch (up to `recognition.dispatch_timeout`) keeps the heartbeat fresh, while a genuinely wedged dispatch stops stamping and lets the heartbeat go stale. The timestamp SHALL be readable from the main async loop's thread without acquiring a lock that the STT thread holds across blocking work (i.e. a plain monotonic value updated in place is sufficient).

#### Scenario: Heartbeat advances during normal listening
- **WHEN** the STT thread is idle-listening for audio with no wake word detected
- **THEN** the heartbeat timestamp continues to advance each loop iteration

#### Scenario: Heartbeat advances during a legitimate long dispatch
- **WHEN** a trigger dispatch (e.g. an LLM conversation with reply windows) runs for up to `recognition.dispatch_timeout` seconds while making progress
- **THEN** the heartbeat continues to advance and a configured systemd watchdog does not restart the daemon

#### Scenario: Heartbeat stalls while the thread is hung
- **WHEN** the STT thread is blocked inside a single non-progressing operation (e.g. a wedged dispatch await) for longer than the freshness threshold
- **THEN** the heartbeat timestamp stops advancing for the duration of the block
