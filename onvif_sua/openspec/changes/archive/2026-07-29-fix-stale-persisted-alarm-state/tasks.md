## 1. Gate the loaded alarm state by recency

- [x] 1.1 In `worker.py` `_load_alarm_file()`, derive `fresh` from the already-preserved `_alarm_saved_at` and `_cfg["serena_startup_alarm_max_age_s"]`, requiring `_alarm_saved_at > 0` so a missing/unparseable `saved_at` is explicitly stale rather than incidentally so.
- [x] 1.2 Coerce a persisted `"on"` to `"off"` when not fresh, before it reaches `_cam_alarms`, so the derived global `Alarm uomo a terra` and the connect-time republish both see the corrected value.
- [x] 1.3 Leave `"off"` entries untouched at any age (no diagnostic), so an ordinary restart stays quiet.
- [x] 1.4 Log the discarded cameras with the state's age and the configured limit, distinctly from the existing not-configured prune, so a startup that clears an alarm explains itself.
- [x] 1.5 Leave the downstream Serena adoption gate in place — redundant for a stale file now, but it guards the emit independently of the load path.

## 2. Tests

- [x] 2.1 Update `tests/test_alarm_prune.py` to build `saved_at` relative to now. Two existing tests hardcoded a timestamp five days in the past while asserting that `"on"` was kept: they were pinning the behaviour being fixed and would otherwise fail for the right reason.
- [x] 2.2 Stale `"on"` → loaded as `"off"`, global alarm not latched, discard logged.
- [x] 2.3 Fresh `"on"` → still loaded as `"on"` (restart recovery preserved), including just inside the window boundary.
- [x] 2.4 Stale `"off"` → unchanged and no diagnostic.
- [x] 2.5 Missing `saved_at` and unparseable `saved_at` → both treated as stale.
- [x] 2.6 A widened `serena_startup_alarm_max_age_s` keeps an older alarm, pinning that the window is the single knob.
- [x] 2.7 Mixed file: a stale `"on"` and an `"off"` for two configured cameras resolve independently and the camera set is untouched.
- [x] 2.8 Run `uv run pytest tests/` and confirm the suite passes (222 passed).

## 3. Sync & finalize

- [x] 3.1 Mirror `worker.py` into the `onvif_sua/` package copy.
- [x] 3.2 Verify against the real `alarm.json` observed on the install (`cucina = "on"`, 685 s old, camera configured) that the state loads as `"off"` and the global alarm is `off`.
- [x] 3.3 Sync the `serena-fall-bridge` delta into `openspec/specs/serena-fall-bridge/spec.md`.
- [x] 3.4 Run `openspec validate fix-stale-persisted-alarm-state --strict` and confirm it reports valid.
