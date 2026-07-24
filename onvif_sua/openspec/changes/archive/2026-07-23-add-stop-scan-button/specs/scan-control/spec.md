## ADDED Requirements

### Requirement: Manual-scan progress is tracked and exposed
The service SHALL track whether a manual subnet scan is currently running and SHALL expose it as an additive boolean `scan_active` field in the `GET /api/status` response. The flag SHALL become true when `_subnet_scan_once` begins and SHALL be cleared when it ends, whether it completes normally or is aborted. Adding this field SHALL NOT change any other field of the status response.

#### Scenario: scan_active is true while a scan runs
- **WHEN** a manual scan has been triggered and is still probing the subnet
- **THEN** `GET /api/status` returns `scan_active: true`

#### Scenario: scan_active is false when idle
- **WHEN** no manual scan is running
- **THEN** `GET /api/status` returns `scan_active: false`

#### Scenario: scan_active clears after the scan ends
- **WHEN** a scan finishes normally or is aborted
- **THEN** the next `GET /api/status` returns `scan_active: false`

### Requirement: A manual scan can be stopped via the API
The service SHALL provide a session-authenticated `POST /api/scan/stop` endpoint that requests cancellation of an in-progress manual subnet scan by setting a cooperative stop signal. `_subnet_scan_once` SHALL check this signal before each IP probe and SHALL terminate early and cleanly when it is set, leaving cameras already discovered (and their state) intact. If no scan is in progress, the endpoint SHALL be a no-op that returns a non-error status. The endpoint SHALL only signal cancellation; it SHALL NOT interrupt a probe already in flight.

#### Scenario: Stop while a scan is running
- **WHEN** `POST /api/scan/stop` is called while a scan is in progress
- **THEN** the endpoint returns a success status indicating stopping, and the scan exits before its next IP probe, after which `scan_active` becomes false

#### Scenario: Stop while idle is a no-op
- **WHEN** `POST /api/scan/stop` is called and no scan is running
- **THEN** the endpoint returns a non-error status indicating nothing to stop, and no error is raised

#### Scenario: Already-discovered cameras are preserved on abort
- **WHEN** a scan is aborted partway through the subnet
- **THEN** cameras discovered before the abort remain in the registry and their state is unchanged

### Requirement: Dashboard button stops a running scan and is enabled only during a scan
The dashboard SHALL replace the previous display-freeze pause button with a stop-scan control that is disabled unless a manual scan is in progress and that, on click, calls `POST /api/scan/stop`. The button's enabled/disabled state SHALL be driven by the `scan_active` field returned by status polling. When the operator triggers a rescan, the button MAY be optimistically enabled immediately, with the next status poll reconciling the true state.

#### Scenario: Button disabled when no scan is running
- **WHEN** the dashboard is loaded and `scan_active` is false
- **THEN** the stop-scan button is disabled

#### Scenario: Button optimistically enabled on rescan
- **WHEN** the operator triggers a rescan
- **THEN** the stop-scan button is enabled immediately without waiting for the next status poll

#### Scenario: Button reflects scan_active from polling
- **WHEN** a status poll reports `scan_active: true`
- **THEN** the stop-scan button is enabled; and when a later poll reports `scan_active: false`, the button is disabled again

#### Scenario: Clicking the button stops the scan
- **WHEN** the operator clicks the enabled stop-scan button
- **THEN** the dashboard calls `POST /api/scan/stop` and the running scan is stopped
