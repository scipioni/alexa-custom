## Context

Today `POST /api/rescan` (`app.py:2170-2177`) schedules `_subnet_scan_once()` on the main loop via `asyncio.run_coroutine_threadsafe(...)` and discards the returned future, so the scan is fire-and-forget and cannot be stopped. No scan-in-progress state is tracked or exposed; `GET /api/status` (`app.py:1829-1837`) returns only `scan_subnet`, `cameras`, `event_log`. Separately, the `⏸ Pausa` button toggles a `paused` flag whose only effect is `if(paused) return;` at the top of `refresh()` — a client-side display freeze.

This change is applied on top of `modularize-app-and-optimize-polling`, so the code lives in the `onvif_sua/` package: scan logic in `scan.py`, routes in `web/routes.py`, the dashboard in `web/templates/index.html` + `web/static/app.js`.

## Goals / Non-Goals

**Goals:**
- Let an operator abort an in-progress manual subnet scan from the dashboard.
- Enable the stop button only while a scan is running; keep it cheap to detect.
- Cleanly repurpose the existing button and remove the now-obsolete display-freeze pause.

**Non-Goals:**
- No change to what the scan probes or discovers, or to the scan trigger (`/api/rescan`).
- No automatic/periodic scanning (it stays disabled).
- No change to MQTT topics/payloads or any other route's contract.
- No cancellation of individual in-flight probe I/O (see cooperative-cancel decision).

## Decisions

### Decision: Cooperative stop flag checked between probes
Add a module-level `threading.Event` (e.g. `_scan_cancel`) and a `_scan_active: bool` flag alongside the scan code. `_subnet_scan_once` sets `_scan_active = True` on entry, clears the cancel event, and in a `finally` sets `_scan_active = False`. Its per-IP loop checks `_scan_cancel.is_set()` before each probe and `return`s early when set. **Alternative considered:** keep the future from `run_coroutine_threadsafe` and call `.cancel()` — rejected: it can interrupt a probe mid-socket/ONVIF call, leaving sockets/subscriptions half-open and needing fragile cleanup. The cooperative check exits at a known-safe point, so already-discovered cameras and their state stay intact.

### Decision: `scan_active` is an additive field on `/api/status`
`/api/status` gains `"scan_active": _scan_active`. Additive only — existing Home Assistant/dashboard consumers ignore unknown fields. The dashboard already polls `/api/status` in `refresh()`, so the button state rides on the existing poll with no new endpoint for state. **Alternative considered:** a dedicated `GET /api/scan/state` poll — rejected as unnecessary traffic given `refresh()` already carries status.

### Decision: `POST /api/scan/stop` sets the cancel event
Session-authenticated (like `/api/rescan`). If `_scan_active` is true, set `_scan_cancel` and return `200 {"status":"stopping"}`; if no scan is running, return `200 {"status":"idle"}` (no-op, not an error — the button could be clicked in a race as a scan finishes). The endpoint only signals; the scan coroutine performs the actual early exit on its own loop.

### Decision: Button enable driven by `scan_active`, optimistic-enable on rescan
In `app.js`, `refresh()` reads `status.scan_active` and sets the button's `disabled` accordingly. Because `refresh()` now polls every 15s (from the modularize change), the button could lag up to a full interval; to keep it responsive, `triggerRescan()` optimistically enables the button the moment it fires `POST /api/rescan`, and the next status poll reconciles (disables it once `scan_active` reads false). This is sufficient per product decision — a brief over-enabled window at most results in a harmless no-op stop call. **Alternative considered:** faster/dedicated polling of scan state — rejected as unnecessary complexity for a manual, infrequent action.

### Decision: Remove the display-freeze pause entirely
Delete the `paused` flag and the `if(paused) return;` guard in `refresh()`; `refresh()` always runs while the tab is visible. The visibility-based auto-pause (stop polling when `document.hidden`) is independent — it uses its own `autoPaused` flag — and is retained, restated without its former "does not conflict with the manual pause button" coupling.

## Risks / Trade-offs

- **Button state lag under 15s polling** → optimistic-enable on rescan-start covers the common case; a stale-enabled button only yields a no-op `idle` stop response. Accepted.
- **Race: stop clicked as scan finishes** → `/api/scan/stop` is idempotent and returns `idle` when nothing is running; the cancel event is cleared at the next scan start. No error surfaced.
- **Long-running probe delays the cancel** → the scan reacts at the next between-probe check, not mid-probe. Worst case is one probe's duration of latency. Accepted (matches the cooperative-cancel decision).
- **Ordering vs the refactor** → this change assumes the `onvif_sua/` package layout; it must be applied after `modularize-app-and-optimize-polling` is implemented.

## Open Questions

- None. (Button-state responsiveness resolved: optimistic-enable is sufficient.)
