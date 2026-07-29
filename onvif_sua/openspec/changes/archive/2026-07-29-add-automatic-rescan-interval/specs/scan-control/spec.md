## ADDED Requirements

### Requirement: A subnet scan may run automatically on a configured interval

The service SHALL support an opt-in periodic subnet scan configured by
`scan.rescan_time_interval` in `settings.yaml`, expressed in seconds. The value SHALL be the
time that must pass **since the last scan completed** — manual or automatic — before another
scan starts, so an operator-triggered rescan defers the next automatic one by a full interval
rather than a fixed clock tick deciding it.

A value of `0` SHALL disable automatic scanning, and SHALL be the default: with no such key in
`settings.yaml` the scanner runs only when the operator asks, exactly as before this change. A
value that is negative or not a number SHALL also disable it rather than being coerced into a
guessed cadence.

A non-zero interval below a 60-second floor SHALL be raised to that floor, with a warning
naming both the requested and the effective value. A scan authenticates against every host on
the configured subnet, so a short interval is a repeated subnet-wide credential burst — the
pattern that trips the camera anti-intrusion lockout the placeholder-password and
auth-quarantine guards already exist to avoid.

An automatic scan SHALL NOT start while a scan is already running, and SHALL remain subject to
the existing placeholder-password suppression. Every scan attempt SHALL record its completion
time, including one refused by the placeholder-password guard or by an invalid subnet, so a
persistently failing precondition cannot make the service re-enter the scan — and re-log its
warning — on every check.

The interval SHALL be readable from `settings.yaml` and changeable at runtime without a
restart, and SHALL be preserved when the service rewrites `settings.yaml`.

#### Scenario: Automatic scanning is off by default
- **WHEN** `settings.yaml` has no `scan.rescan_time_interval`, or has it set to `0`
- **THEN** no scan ever starts on its own, and the scanner runs only from the operator's rescan control

#### Scenario: A scan runs once the interval has elapsed
- **WHEN** the configured interval has passed since the last scan completed
- **THEN** a subnet scan starts automatically

#### Scenario: A scan does not run before the interval has elapsed
- **WHEN** less than the configured interval has passed since the last scan
- **THEN** no automatic scan starts

#### Scenario: A manual rescan defers the next automatic one
- **WHEN** the operator triggers a rescan partway through an interval
- **THEN** the next automatic scan is due a full interval after that manual scan, not at the moment the original interval would have expired

#### Scenario: An interval below the floor is clamped
- **WHEN** a non-zero interval shorter than 60 seconds is configured
- **THEN** 60 seconds is used instead and the clamp is logged

#### Scenario: An invalid interval disables automatic scanning
- **WHEN** the interval is negative or not a number
- **THEN** automatic scanning is disabled rather than run at a guessed cadence

#### Scenario: No overlap with a scan already in progress
- **WHEN** the interval elapses while a scan is still running
- **THEN** no second scan is started

#### Scenario: A refused scan does not retry on every check
- **WHEN** an automatic scan is refused because a placeholder password is still set, or because the configured subnet is invalid
- **THEN** its completion time is still recorded, so the next attempt waits a full interval instead of repeating on every check

#### Scenario: The interval survives a configuration save
- **WHEN** the service rewrites `settings.yaml`
- **THEN** the configured `scan.rescan_time_interval` is still present in the saved file

### Requirement: An automatic scan does not undo an operator's removal

The service SHALL remember the cameras removed through the API during the current run, and an
**automatic** scan SHALL NOT re-add them. A **manual** rescan SHALL still rediscover them, and
SHALL clear that memory: an operator-triggered rescan is an explicit request for a full refresh.
Saving or renaming a camera SHALL clear its entry from that memory, since both mean the camera
is wanted again.

This asymmetry exists because a scan starts a camera worker for every ONVIF device it finds. An
unattended scan would otherwise re-add a camera the operator deleted — within one interval,
together with its MQTT and Home Assistant entities — making a room appear as monitored again
without anyone asking, and making the dashboard's remove control look broken.

Each camera skipped for this reason SHALL be reported in the dashboard event log, not only in
the service log: from the dashboard the camera is otherwise simply online and absent, with no
visible explanation and no hint that a manual rescan is the remedy. The report SHALL identify
the camera by address and by the name the device reports, and SHALL be visible under the
dashboard's default event-category filters.

This memory SHALL NOT need to outlive the process: a removed camera has no `cameras.list` entry,
so nothing re-creates it at startup.

#### Scenario: An automatic scan skips a removed camera
- **WHEN** an automatic scan finds a camera the operator removed, still online and answering
- **THEN** no worker is started for it and it does not reappear on the dashboard as a camera row

#### Scenario: A manual rescan rediscovers a removed camera
- **WHEN** the operator triggers a rescan after removing a camera
- **THEN** the camera is rediscovered and added, and it is no longer excluded from later automatic scans

#### Scenario: The skip is visible in the dashboard event log
- **WHEN** an automatic scan skips a removed camera
- **THEN** an event is recorded naming that camera's address and reported name, stating that it was removed by the operator and that a manual rescan will rediscover it

#### Scenario: Each skipped camera is reported separately
- **WHEN** an automatic scan skips more than one removed camera
- **THEN** one event is recorded per camera, so the log's address and name filters apply to each

#### Scenario: The skip report does not require a live camera row
- **WHEN** the skipped camera has no runtime entry, having been torn down on removal
- **THEN** the event is still recorded

#### Scenario: Saving a camera makes it eligible again
- **WHEN** a previously removed camera is saved
- **THEN** later automatic scans no longer skip it

#### Scenario: A manual scan reports no skips
- **WHEN** the operator triggers a rescan
- **THEN** no skip events are recorded, because nothing is skipped

### Requirement: The automatic-rescan state is exposed to the dashboard

`GET /api/status` SHALL additively report the effective interval in seconds (after the floor is
applied, `0` when disabled) and the seconds remaining until the next automatic scan, the latter
being absent when automatic scanning is disabled. Adding these fields SHALL NOT change any
other field of the status response.

`POST /api/config` SHALL accept `rescan_time_interval`, persist it, and return the effective
value after clamping so the caller sees what will actually be used. A negative value SHALL be
rejected with a client error rather than silently treated as "disabled".

#### Scenario: Status reports the interval and the countdown
- **WHEN** automatic scanning is enabled and a scan ran recently
- **THEN** `GET /api/status` reports the effective interval and the seconds remaining before the next scan

#### Scenario: Status reports no countdown when disabled
- **WHEN** automatic scanning is disabled
- **THEN** `GET /api/status` reports the interval as `0` and no remaining time

#### Scenario: The interval can be changed without a restart
- **WHEN** `POST /api/config` sets `rescan_time_interval`
- **THEN** the value is persisted, the response reports the effective value after clamping, and the new cadence applies without restarting the service

#### Scenario: A negative interval is rejected
- **WHEN** `POST /api/config` sets a negative `rescan_time_interval`
- **THEN** the request is rejected with a client error and a diagnostic

## MODIFIED Requirements

### Requirement: Manual-scan progress is tracked and exposed
The service SHALL track whether a subnet scan is currently running and SHALL expose it as an additive boolean `scan_active` field in the `GET /api/status` response. The flag SHALL become true when `_subnet_scan_once` begins and SHALL be cleared when it ends, whether it completes normally or is aborted. This SHALL apply to an automatically triggered scan exactly as it does to an operator-triggered one, so a periodic scan is visible in the status response while it runs. Adding this field SHALL NOT change any other field of the status response.

#### Scenario: scan_active is true while a scan runs
- **WHEN** a manual scan has been triggered and is still probing the subnet
- **THEN** `GET /api/status` returns `scan_active: true`

#### Scenario: scan_active is false when idle
- **WHEN** no manual scan is running
- **THEN** `GET /api/status` returns `scan_active: false`

#### Scenario: scan_active clears after the scan ends
- **WHEN** a scan finishes normally or is aborted
- **THEN** the next `GET /api/status` returns `scan_active: false`

#### Scenario: An automatic scan is reported as active too
- **WHEN** a periodic scan started by the configured interval is probing the subnet
- **THEN** `GET /api/status` returns `scan_active: true` for its duration, and `false` once it ends

### Requirement: A manual scan can be stopped via the API
The service SHALL provide a session-authenticated `POST /api/scan/stop` endpoint that requests cancellation of an in-progress subnet scan by setting a cooperative stop signal. `_subnet_scan_once` SHALL check this signal before each IP probe and SHALL terminate early and cleanly when it is set, leaving cameras already discovered (and their state) intact. If no scan is in progress, the endpoint SHALL be a no-op that returns a non-error status. The endpoint SHALL only signal cancellation; it SHALL NOT interrupt a probe already in flight. An automatically triggered scan SHALL be stoppable by the same endpoint and the same signal, so the operator is never unable to halt a sweep in progress.

#### Scenario: Stop while a scan is running
- **WHEN** `POST /api/scan/stop` is called while a scan is in progress
- **THEN** the endpoint returns a success status indicating stopping, and the scan exits before its next IP probe, after which `scan_active` becomes false

#### Scenario: Stop while idle is a no-op
- **WHEN** `POST /api/scan/stop` is called and no scan is running
- **THEN** the endpoint returns a non-error status indicating nothing to stop, and no error is raised

#### Scenario: Already-discovered cameras are preserved on abort
- **WHEN** a scan is aborted partway through the subnet
- **THEN** cameras discovered before the abort remain in the registry and their state is unchanged

#### Scenario: An automatic scan can be stopped
- **WHEN** `POST /api/scan/stop` is called while a periodic scan is probing the subnet
- **THEN** that scan exits before its next IP probe, exactly as a manual one would
