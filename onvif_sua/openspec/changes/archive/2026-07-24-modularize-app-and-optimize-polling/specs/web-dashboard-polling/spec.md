## ADDED Requirements

### Requirement: Reduced dashboard polling cadence
The dashboard SHALL poll status/events on an interval of 15 seconds and alarms on an interval of 12 seconds, replacing the previous 4-second and 3-second intervals. The alarm state remains authoritative via MQTT to Home Assistant; the web polling is a monitoring view only and its cadence SHALL NOT affect the MQTT alarm path.

#### Scenario: Status/events refresh at the slower cadence
- **WHEN** the dashboard is open and visible
- **THEN** the `refresh` cycle (status + events) runs approximately every 15 seconds

#### Scenario: Alarms refresh at the slower cadence
- **WHEN** the dashboard is open and visible
- **THEN** the `refreshAlarms` cycle runs approximately every 12 seconds

#### Scenario: MQTT alarm path is unaffected
- **WHEN** a fall alarm occurs
- **THEN** the alarm is published to Home Assistant over MQTT independent of the dashboard polling interval

### Requirement: Pause polling when the tab is not visible
The dashboard SHALL stop polling (both `refresh` and `refreshAlarms`) while the page is hidden (`document.hidden` true), and SHALL resume when the page becomes visible again, performing an immediate refresh on becoming visible so the view is current without waiting a full interval. This visibility-based auto-pause SHALL be tracked by a dedicated flag separate from the manual pause flag, and SHALL NOT conflict with the manual Pause/Resume button.

#### Scenario: Backgrounded tab does no polling
- **WHEN** the browser tab is hidden or the kiosk screen is off (`document.hidden` becomes true)
- **THEN** no `refresh` or `refreshAlarms` network requests are made until the page becomes visible again

#### Scenario: Immediate refresh on becoming visible
- **WHEN** the page transitions from hidden to visible
- **THEN** `refresh` and `refreshAlarms` run once immediately (subject to the manual-pause scope below), then continue on their normal intervals

#### Scenario: Manual pause is independent of visibility
- **WHEN** the user has manually paused with the Pause button and then the tab visibility changes
- **THEN** the manual pause state is preserved and auto-pause does not override the user's explicit choice

### Requirement: Manual pause stops only status/events polling, never alarm polling
The manual `⏸ Pausa`/`▶ Riprendi` button SHALL pause and resume only the `refresh` cycle (status + events). It SHALL NOT stop the `refreshAlarms` cycle: alarm polling continues on its interval regardless of the manual pause state. This preserves the existing behavior in `app.py`, where the `paused` flag guards `refresh()` only and `refreshAlarms()` has no such guard. Only the visibility-based auto-pause (see above) stops `refreshAlarms`.

#### Scenario: Manual pause leaves alarm polling running
- **WHEN** the user manually pauses with the Pause button while the tab remains visible
- **THEN** `refresh` (status + events) stops, but `refreshAlarms` continues to run on its 12-second interval

#### Scenario: Manual pause does not suppress the immediate alarm refresh on becoming visible
- **WHEN** the user has manually paused and the tab transitions from hidden to visible
- **THEN** `refreshAlarms` runs immediately (manual pause does not gate it), while the immediate `refresh` for status/events is suppressed because the manual pause remains in effect
