## ADDED Requirements

### Requirement: STT thread liveness monitoring
The system SHALL monitor the STT daemon thread for unexpected exits. A watchdog task SHALL check thread liveness at a fixed interval (≤ 10 seconds). When the thread is found dead, the system SHALL emit an `stt_dead` event to all connected WebSocket clients and attempt to restart the thread once per detection cycle.

#### Scenario: STT thread exits unexpectedly
- **WHEN** the STT thread terminates while the daemon is still running
- **THEN** within 10 seconds the watchdog detects the death, emits `stt_dead` to all WebSocket clients, and starts a new STT thread

#### Scenario: STT thread running normally
- **WHEN** the STT thread is alive
- **THEN** the watchdog takes no action and emits no events

#### Scenario: Repeated crashes
- **WHEN** the STT thread crashes repeatedly after each restart
- **THEN** the watchdog restarts it each detection cycle and continues emitting `stt_dead` events, giving the operator a visible signal without crashing the daemon

### Requirement: STT thread reference retained
The system SHALL retain a reference to the active STT thread so the watchdog can check `is_alive()`. The reference SHALL be updated whenever the thread is (re)started.

#### Scenario: Thread reference updated on restart
- **WHEN** the watchdog restarts the STT thread
- **THEN** the stored reference points to the new thread, not the dead one
