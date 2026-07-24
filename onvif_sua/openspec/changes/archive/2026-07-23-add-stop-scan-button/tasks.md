## 1. Backend: scan state + cancellation

- [x] 1.1 In `scan.py`, add module-level scan state: a `_scan_active: bool` flag and a cooperative `_scan_cancel` (`threading.Event`).
- [x] 1.2 In `_subnet_scan_once`: on entry clear `_scan_cancel` and set `_scan_active = True`; in a `finally` set `_scan_active = False`. Before each IP probe, check `_scan_cancel.is_set()` and `return` early (cleanly) when set, leaving already-discovered cameras intact.
- [x] 1.3 Confirm `_subnet_scan_once` still behaves identically when never cancelled (full-subnet completion path unchanged).

## 2. Backend: API

- [x] 2.1 Add `"scan_active": _scan_active` to the `GET /api/status` response (additive; no other field changes).
- [x] 2.2 Add `POST /api/scan/stop` in `web/routes.py`: session-authenticated; if `_scan_active`, set `_scan_cancel` and return `200 {"status":"stopping"}`; else return `200 {"status":"idle"}` (no-op, no error).

## 3. Frontend: repurpose the button

- [x] 3.1 In `web/static/app.js`, remove the display-freeze pause: delete the `paused` variable, the `if(paused) return;` guard in `refresh()`, and the old `togglePause()` label-swap logic.
- [x] 3.2 Give the button a stable `id` in `index.html` and relabel it "⏹ Ferma scan"; wire its click to `POST /api/scan/stop`.
- [x] 3.3 In `refresh()`, set the button's `disabled` state from `status.scan_active` on every poll.
- [x] 3.4 In `triggerRescan()`, optimistically enable the button immediately after firing `POST /api/rescan` (next status poll reconciles).
- [x] 3.5 Verify the visibility-based auto-pause still works and no longer references the removed manual pause.

## 4. Verification

- [x] 4.1 Trigger a rescan → button enables immediately; `GET /api/status` reports `scan_active: true`.
- [x] 4.2 Click stop mid-scan → scan exits before the next probe, `scan_active` returns to false, button disables; cameras discovered before the stop remain.
- [x] 4.3 Click stop while idle (or as a scan finishes) → `{"status":"idle"}`, no error, no side effects.
- [x] 4.4 Confirm `/api/status` change is purely additive and MQTT output is unaffected.
