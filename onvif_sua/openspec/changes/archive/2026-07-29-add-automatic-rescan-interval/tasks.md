> **Retroactive change.** The implementation shipped before this change was written, so the
> tasks below were already done when it was authored and are checked off with the file
> references that prove it. The one piece of work this change actually performed is task 6.1 —
> bringing the main `scan-control` spec back in line with the code, which is why it exists.

## 1. Interval configuration

- [x] 1.1 Add the `RESCAN_TIME_INTERVAL` env default and `_cfg["rescan_time_interval"]` (default `0` = disabled) in `config.py`, and register the key in `_INT_KEYS` so the API coerces it.
- [x] 1.2 Add `_rescan_interval()` (`config.py:162`): coerce on every read so a runtime change takes effect without a restart; return `0.0` for zero/negative/non-numeric; clamp a non-zero value up to `_RESCAN_INTERVAL_FLOOR = 60.0` and warn once.
- [x] 1.3 Read `scan.rescan_time_interval` from the `settings.yaml` `scan:` block in `_load_settings_yaml`.
- [x] 1.4 Round-trip the key in `_save_settings_yaml` so a GUI save never drops it.
- [x] 1.5 Update the `config.py` header comment that asserted the scanner "never runs on its own".

## 2. Scanner: automatic mode

- [x] 2.1 Add the `automatic: bool = False` parameter to `_subnet_scan_once` and label the log line `automatico`/`manuale` accordingly.
- [x] 2.2 Add `scan._last_scan_ts`, stamped in the `finally` on every exit path (completed, aborted, invalid subnet) so a failing scan cannot make the due-check fire in a tight loop.
- [x] 2.3 Stamp it on the placeholder-password early return too — that return precedes the `try`, so it would otherwise be re-entered and re-logged on every poll.

## 3. Removal durability

- [x] 3.1 Add `state._operator_removed` (IPs removed via the API this run), documented as distinct from the transient `_removed_ips` teardown guard.
- [x] 3.2 Skip those IPs in `_subnet_scan_once` when `automatic=True` (`scan.py:381`); a manual scan clears the set first.
- [x] 3.3 Record the removal in `api_remove_camera`, and discard it in `api_save_camera` and `api_rename_camera` (both mean "wanted again").
- [x] 3.4 Report each skipped camera in the dashboard event log via `_record_event(..., "Scanner/RemovedNotReadded", ...)` (`scan.py:388`), one row per camera so the log's IP/name filters apply.
- [x] 3.5 Add the `TOPIC_MAP` pill entry in `web/static/index.js`, and verify the topic string resolves to a category that is **visible by default** (`Altro`, not the off-by-default `sistema`).
- [x] 3.6 Bump `web.asset_version` so long-running dashboards refetch the JS.

## 4. Periodic loop

- [x] 4.1 Add `_auto_rescan_due(now)` in `worker.py` as a pure function of the three gates (enabled, no scan running, interval elapsed) so the decision is testable without sleeping.
- [x] 4.2 Add `_auto_rescan_loop()` (`worker.py:1245`) polling every `AUTO_RESCAN_TICK = 30 s` so an interval change applies promptly; initialise `_last_scan_ts` to process start so the first automatic scan is one interval after boot, never at boot.
- [x] 4.3 Register it as `asyncio.create_task(_auto_rescan_loop(), name="auto-rescan")` and log the effective cadence (or "disabilitato") at startup.

## 5. API surface

- [x] 5.1 Expose `rescan_interval` and `rescan_in` additively in `GET /api/status` (`rescan_in` is `null` when disabled).
- [x] 5.2 Accept `rescan_time_interval` in `POST /api/config`, return the effective (clamped) value, and reject a negative value with a 400.

## 6. Spec & documentation

- [x] 6.1 Sync this change's `scan-control` delta into `openspec/specs/scan-control/spec.md` — the main spec still describes a manual-only scanner, which no longer matches the code, the README, or `config.py`.
- [x] 6.2 Document the feature in `README.md`: the from-last-scan semantics, `0` = disabled, the 60 s floor and why, the removal-durability rule, and the overlap with the hostname-resolution sweep.
- [x] 6.3 Document the key in `settings.yaml` with a note that a GUI save strips comments but keeps the key.
- [x] 6.4 Note in `.env.example` that the scan credential is now also used by an unattended sweep.

## 7. Tests

- [x] 7.1 Interval parsing: disabled by default, junk/negative disables, valid values pass through, below-floor clamps and warns once, round-trips through a save, and is read from the `scan:` block (`tests/test_auto_rescan.py`).
- [x] 7.2 The three due-check gates, plus the "a manual scan defers the next automatic one" case.
- [x] 7.3 Automatic vs manual removal handling: automatic skips, manual re-adds and clears the set, and the API records/clears the mark.
- [x] 7.4 The event-log row: recorded once per skipped camera, with the device-reported name, without a live camera row, and never for a manual scan.
- [x] 7.5 Timestamp stamping on the suppressed-password and invalid-subnet paths.
- [x] 7.6 The status and config API surface, including the negative-value rejection.
- [x] 7.7 Guard added in `tests/conftest.py`: an autouse fixture points `config.SETTINGS_FILE` at a temp path for every test, because `web/routes.py` binds its own `_save_settings_yaml` reference at import and a test reached the real file.
- [x] 7.8 Run `uv run pytest tests/` and confirm the suite passes (215 passed).

## 8. Sync & finalize

- [x] 8.1 Mirror the edited top-level duplicate `*.py` files into the canonical `onvif_sua/` package copies (`config.py`, `scan.py`, `state.py`, `worker.py`, `web/routes.py`, `web/static/index.js`).
- [x] 8.2 Run `openspec validate add-automatic-rescan-interval --strict` and confirm it reports valid.
