## ADDED Requirements

### Requirement: STT loop heartbeat
The STT daemon thread SHALL stamp a monotonic "last alive" timestamp on every iteration of its main recognition loop, including iterations spent waiting for audio. The timestamp SHALL be readable from the main async loop's thread without acquiring a lock that the STT thread holds across blocking work (i.e. a plain monotonic value updated in place is sufficient).

#### Scenario: Heartbeat advances during normal listening
- **WHEN** the STT thread is idle-listening for audio with no wake word detected
- **THEN** the heartbeat timestamp continues to advance each loop iteration

#### Scenario: Heartbeat stalls while the thread is hung
- **WHEN** the STT thread is blocked inside a single turn (e.g. a wedged dispatch) for longer than one loop iteration
- **THEN** the heartbeat timestamp stops advancing for the duration of the block

### Requirement: Systemd watchdog ping gated on heartbeat freshness
When the systemd watchdog is active (`WATCHDOG_USEC` present in the environment), the main loop SHALL send `sd_notify("WATCHDOG=1")` only if the STT heartbeat is fresher than a freshness threshold. The freshness threshold SHALL be strictly less than the systemd `WatchdogSec` so that a stalled heartbeat lets the watchdog timer expire and systemd restarts the process. When the systemd watchdog is inactive, heartbeat gating SHALL have no effect on behavior.

#### Scenario: Fresh heartbeat keeps the service alive
- **WHEN** the systemd watchdog is active and the STT heartbeat was stamped within the freshness threshold
- **THEN** the main loop sends `WATCHDOG=1` on its normal ping interval and systemd does not restart the process

#### Scenario: Stale heartbeat triggers a restart
- **WHEN** the systemd watchdog is active and the STT heartbeat has not advanced for longer than the freshness threshold
- **THEN** the main loop withholds `WATCHDOG=1`, the systemd watchdog timer expires, and systemd restarts the process

#### Scenario: Watchdog disabled is a no-op
- **WHEN** the systemd watchdog is inactive (no `WATCHDOG_USEC`)
- **THEN** heartbeat staleness has no effect and the main loop runs unchanged
