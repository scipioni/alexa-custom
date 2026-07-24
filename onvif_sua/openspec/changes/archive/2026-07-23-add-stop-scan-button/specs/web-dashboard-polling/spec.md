## REMOVED Requirements

### Requirement: Manual pause stops only status/events polling, never alarm polling
**Reason**: The manual `⏸ Pausa` button is repurposed into a stop-scan control (see the `scan-control` capability). The client-side display-freeze pause, its `paused` flag, and the `if(paused) return;` guard in `refresh()` are removed; `refresh()` now always runs while the tab is visible.
**Migration**: Delete the `paused` flag and its guard in `refresh()`; replace the button per the `scan-control` capability. No server-side or MQTT change is involved.

## MODIFIED Requirements

### Requirement: Pause polling when the tab is not visible
The dashboard SHALL stop polling (both `refresh` and `refreshAlarms`) while the page is hidden (`document.hidden` true), and SHALL resume when the page becomes visible again, performing an immediate refresh (`refresh()` + `refreshAlarms()`) on becoming visible so the view is current without waiting a full interval. This visibility-based auto-pause SHALL be tracked by a dedicated `autoPaused` flag.

#### Scenario: Backgrounded tab does no polling
- **WHEN** the browser tab is hidden or the kiosk screen is off (`document.hidden` becomes true)
- **THEN** no `refresh` or `refreshAlarms` network requests are made until the page becomes visible again

#### Scenario: Immediate refresh on becoming visible
- **WHEN** the page transitions from hidden to visible
- **THEN** `refresh` and `refreshAlarms` run once immediately, then continue on their normal intervals
