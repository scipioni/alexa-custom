## Why

The subnet scanner is manual-only by deliberate design: it is the operator's discovery tool,
and it starts a camera worker for **every** ONVIF device it finds, so running it unattended
has consequences that had to be thought through rather than assumed. With cameras moving to
DHCP there is now a reason to run it unattended — a device that appears, or reappears at a
new address, should be picked up without someone clicking "🔍 Rescan subnet".

This change adds an opt-in periodic rescan and, critically, makes the automatic path safe to
leave running: an automatic scan must not authenticate against every host so often that it
trips the Dahua anti-intrusion lockout, and it must not silently undo an operator's removal.

**This change is retroactive**: the behaviour it describes is already implemented and tested
(see Impact for file references). It exists because the implementation shipped ahead of its
spec, leaving `openspec/specs/scan-control/spec.md` describing a manual-only scanner that no
longer matches the code, the README, or `config.py`'s own comments. Writing it down is the
work.

## What Changes

- Add `scan.rescan_time_interval` to `settings.yaml`: seconds that must pass **since the last
  scan** (manual or automatic) before another one starts. `0` — the default — keeps the
  historical manual-only behaviour exactly.
- Measure the interval from the last scan's completion rather than on a fixed tick, so a
  manual rescan pushes the next automatic one a full interval out instead of one firing
  seconds later.
- Clamp any non-zero interval up to a 60 s floor, with a warning: a sweep authenticates
  against every host on the subnet, and a short interval is precisely the repeated
  wrong-credential burst that trips the camera lockout.
- Skip the automatic scan while a scan is already running, and keep the existing
  placeholder-password suppression.
- **Do not re-add a camera the operator explicitly removed.** Because a scan spawns a worker
  for every device it finds, an automatic scan would otherwise revert a dashboard deletion
  within one interval and the camera would come back on its own, with its MQTT/Home Assistant
  entities. A manual rescan still rediscovers everything — that is the operator asking.
- Report each skipped camera in the dashboard event log (`Scanner/RemovedNotReadded`), not
  only on the console: from the operator's side the camera is simply online-and-absent, and
  the reason is otherwise invisible in the UI.
- Expose the automatic-rescan state additively: `rescan_interval` and `rescan_in` in
  `GET /api/status`, and `rescan_time_interval` accepted by `POST /api/config` so it can be
  changed without a restart.

## Capabilities

### Modified Capabilities
- `scan-control`: the scanner is no longer manual-only. `scan_active` and the cooperative
  stop signal now also cover an automatic scan, and the capability gains the interval
  configuration, the removal-durability rule, and the status fields that drive the UI.

### New Capabilities
<!-- None. This extends scan-control rather than introducing a separate capability: it is the
     same scanner, the same stop signal and the same `scan_active` flag, with a second
     trigger. -->

## Impact

- **Config**: `config.py` — `RESCAN_TIME_INTERVAL` env default, `_cfg["rescan_time_interval"]`,
  `_rescan_interval()` accessor with the 60 s floor (`config.py:162`), read from the
  `settings.yaml` `scan:` block and round-tripped on save.
- **Scanner**: `scan.py` — `_subnet_scan_once(automatic=False)` gains the mode flag, the
  `_last_scan_ts` completion stamp on every exit path, the operator-removal skip
  (`scan.py:381`) and its event-log row (`scan.py:388`).
- **Worker lifecycle**: `worker.py` — `_auto_rescan_due()` (the three gates, pure and
  testable), `_auto_rescan_loop()` (`worker.py:1245`) registered as the `auto-rescan` task.
- **Runtime state**: `state.py` — `_operator_removed`, the set of IPs removed via the API this
  run; distinct from the transient `_removed_ips` teardown guard.
- **Web**: `web/routes.py` — `api_remove_camera` records the removal, `api_save_camera` and
  `api_rename_camera` clear it, `api_status` exposes `rescan_interval`/`rescan_in`,
  `api_config_post` accepts and validates the interval. `web/static/index.js` — pill mapping
  for the new event topic.
- **Config file & docs**: `settings.yaml`, `README.md`, `.env.example`.
- **Tests**: `tests/test_auto_rescan.py` (27 tests) — interval parsing/floor/round-trip, the
  three due-check gates, automatic-vs-manual removal handling, the event-log row, timestamp
  stamping on suppressed and invalid-subnet paths, and the status/config API surface.
- **Dependencies**: none added.
