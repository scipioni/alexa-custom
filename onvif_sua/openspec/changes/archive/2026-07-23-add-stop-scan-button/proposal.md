## Why

The dashboard's `⏸ Pausa` button only freezes the client-side display refresh (`app.py`: the `paused` flag guards `refresh()` and nothing else). That is low value: alarm state reaches Home Assistant over MQTT regardless, and the view auto-refreshes anyway. Meanwhile a manual subnet scan (`POST /api/rescan` → `_subnet_scan_once`) runs to completion with no way to stop it, even when the operator started it by mistake or on the wrong subnet. This change repurposes the button into a **stop-scan** control: it aborts an in-progress manual scan, and is clickable only while a scan is actually running.

## What Changes

- **Track scan progress server-side**: a module-level `_scan_active` flag plus a cooperative cancel signal (`threading.Event`), set when `_subnet_scan_once` starts and cleared in a `finally` when it ends (normal completion or abort).
- **Make the scan abortable**: `_subnet_scan_once` checks the cancel signal between IP probes and returns early, cleanly, when it is set — cameras already discovered remain; no partial-teardown state.
- **New endpoint** `POST /api/scan/stop` (session-authenticated): sets the cancel signal and returns a status; a no-op (non-error) when no scan is running.
- **Expose scan state**: `GET /api/status` gains an additive `scan_active: bool` field. Existing consumers are unaffected.
- **Repurpose the button** (`web/static/app.js`, `web/templates/index.html`): replace the display-freeze pause with a **"⏹ Ferma scan"** button, `disabled` unless the latest `/api/status` reports `scan_active`; on click it `POST`s `/api/scan/stop`. To avoid enable lag from the slowed 15s status polling, the button is **optimistically enabled** the instant `triggerRescan()` fires, with the next status poll reconciling the true state.
- **Remove the display-freeze pause**: delete the `paused` flag and the `if(paused) return;` guard in `refresh()`; the display now always refreshes while visible. The visibility-based auto-pause (tab hidden) is unaffected — it uses its own `autoPaused` flag.

## Capabilities

### New Capabilities
- `scan-control`: server-side tracking and exposure of manual-scan progress (`scan_active`), the `POST /api/scan/stop` endpoint with cooperative cancellation, and the dashboard's stop-scan button (enabled only during a scan, optimistic-enable on rescan).

### Modified Capabilities
- `web-dashboard-polling`: the manual display-freeze pause is removed (the button is repurposed to scan-control); the visibility-based auto-pause requirement is restated without its dependency on the manual pause button.

## Impact

- **Depends on** `modularize-app-and-optimize-polling` and is applied **after** it: this change edits the new package's `scan.py`, `web/routes.py`, `web/templates/index.html`, and `web/static/app.js`.
- **Code**: `scan.py` (`_subnet_scan_once` gains the cancel-check loop + state flag), `web/routes.py` (new `/api/scan/stop`, `scan_active` added to `/api/status`), `web/static/app.js` + `web/templates/index.html` (button repurpose, remove `paused`).
- **External contracts**: `/api/status` response gains one additive boolean field; one new endpoint is added. MQTT topics/payloads, the scan's discovery behavior, and all other routes are unchanged.
- **Behavior removed**: the client-side display-freeze pause. No server behavior is removed.
