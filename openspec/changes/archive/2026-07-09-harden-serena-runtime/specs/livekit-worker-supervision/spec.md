# Capability: LiveKit Worker Supervision

## ADDED Requirements

### Requirement: Supervised LiveKit worker loop
The LiveKit worker loop SHALL be wrapped in an exception handler. On any uncaught exception, the system SHALL log the full traceback to the standard logger at ERROR level (reaching the journal under systemd), emit the existing dashboard error event, and restart the worker loop after a backoff delay (initial 5 s, doubling to a 60 s cap, reset after 10 minutes of healthy operation). The worker SHALL NOT terminate silently.

#### Scenario: Transient network error at session setup
- **WHEN** LiveKit API construction or participant polling raises a transient exception (e.g. DNS failure)
- **THEN** the traceback is logged to the journal, the dashboard receives an error event, and the worker loop restarts after the backoff delay and can subsequently place and receive calls

#### Scenario: Backoff on repeated failures
- **WHEN** the worker loop fails repeatedly in succession
- **THEN** consecutive restart delays double up to 60 s and the daemon (web, STT, audio watcher) keeps running throughout

### Requirement: Terminal configuration errors are loud but non-fatal
When the worker loop fails due to missing required environment/configuration (e.g. `require_env` for LIVEKIT variables), the system SHALL log a CRITICAL message to the journal identifying the missing variable(s) and SHALL stop retrying the worker, while the rest of the daemon (web dashboard, STT, audio watcher) continues running.

#### Scenario: Missing LIVEKIT env var
- **WHEN** the daemon starts without `LIVEKIT_ROOM` set
- **THEN** a CRITICAL journal line names the missing variable, the worker does not retry-loop, and the web dashboard and STT remain functional

### Requirement: Watchdog ping coverage in all main-loop states
When the systemd watchdog is active, the main loop SHALL send `sd_notify("WATCHDOG=1")` (subject to the existing STT-heartbeat freshness gate) from every long-lived wait state: the idle trigger-wait loop, participant polling, and in-session waiting. No reachable steady state of a healthy daemon SHALL starve the watchdog.

#### Scenario: Idle daemon with watchdog enabled
- **WHEN** the daemon idles in the trigger-wait loop for longer than `WatchdogSec` with a fresh STT heartbeat
- **THEN** watchdog pings continue on the normal interval and systemd does not restart the process

#### Scenario: Long LiveKit session with watchdog enabled
- **WHEN** a call is active for longer than `WatchdogSec`
- **THEN** watchdog pings continue for the duration of the session
