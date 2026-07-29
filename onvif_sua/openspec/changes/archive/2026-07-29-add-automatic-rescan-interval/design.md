## Context

`_subnet_scan_once` (`scan.py`) expands `scan.subnet`, TCP-probes each host on the ONVIF
candidate ports, authenticates with the common credential, and — for every device that answers
and is not already known — calls `_spawn_worker(cam)` with `static=False`. It sets `_scan_active`
for the duration and checks a `_scan_cancel` event between probes, which is what the dashboard's
stop button drives (`scan-control`).

Two properties of that function decide this design:

1. **A scan is a subnet-wide authentication burst.** The repo's other guards exist for the same
   reason: a placeholder password suppresses the scan entirely, and an IP whose credential was
   rejected is quarantined so it is never re-probed. Dahua's anti-intrusion lockout is the
   failure being avoided, and it locks the camera — the thing the whole service exists to watch.
2. **A scan adds cameras.** It is not a read-only probe. Anything that finds a device also
   starts a worker for it, publishes its MQTT/HA entities, and puts a row on the dashboard.

Removal is the other half. `api_remove_camera` deletes the config entry and tears down the
runtime camera, deliberately leaving **no** sticky block: `_removed_ips` is a transient
teardown guard, discarded as soon as teardown finishes, precisely so a later manual rescan can
rediscover the camera. That is correct for a manual rescan and wrong for an automatic one.

## Goals / Non-Goals

**Goals:**
- Run the existing scan periodically, opt-in, with the interval in `settings.yaml`.
- Measure the interval from the last scan rather than from a fixed clock tick.
- Keep the default behaviour bit-for-bit unchanged (`0` = disabled).
- Make an unattended scan safe: bounded frequency, no overlap, and no reversal of an
  operator's removal.
- Make the automatic path observable in the UI, not just the console.

**Non-Goals:**
- No change to what a scan *does* when it finds a new device (still a non-static worker).
- No per-subnet or per-camera interval; the single `scan.subnet` and one interval are reused.
- No scan at startup — the first automatic scan is one interval after boot.
- No persistence of scan history across restarts.
- Not a replacement for hostname resolution: a camera that must survive address changes should
  be configured by `hostname:` (see `hostname-camera-resolution`). This change is about
  *discovery*.

## Decisions

### The interval is measured from the last scan's completion, not on a fixed tick

`scan._last_scan_ts` is stamped when any scan ends, manual or automatic, and the due-check is
`now - _last_scan_ts >= interval`. A manual rescan therefore pushes the next automatic one a
full interval into the future.

- **Why not a plain `while True: sleep(interval)`?** It is simpler, but an operator who clicks
  rescan would routinely get a second, redundant subnet sweep moments later — two
  authentication bursts where one was asked for. Deriving from the last scan makes "rescan now"
  and "rescan periodically" compose instead of collide.
- The poll cadence is separate from the interval (`AUTO_RESCAN_TICK = 30 s`), so a change to
  `rescan_time_interval` via `POST /api/config` takes effect within one tick rather than after
  the old interval expires.

### `0` disables it, and that is the default

The historical behaviour is preserved by the shipped default, so existing deployments are
untouched by upgrading. A non-numeric or negative value also reads as disabled rather than
being coerced into some guessed cadence; the API additionally rejects a negative value with a
400 instead of silently treating it as "off", because that is an operator mistake worth
surfacing.

### 60 s floor, clamped with a warning

A non-zero interval below 60 s is raised to 60 s and logged once. This mirrors the existing
`_SERENA_INTERVAL_FLOOR` precedent for a knob whose small values are pathological rather than
merely aggressive.

- **Trade-off accepted:** an operator who wants a 20 s cadence for testing cannot have it
  without editing the constant. The floor protects the cameras, which is the asset the service
  cannot afford to lose; the alternative (trusting the value) risks locking out a fall-detection
  camera to save an operator a code edit.
- **Rejected:** making the floor itself configurable. It would be a knob whose only purpose is
  to defeat a safety limit.

### An automatic scan does not re-add an operator-removed camera

`state._operator_removed` holds the IPs removed through the API during this process run.
`_subnet_scan_once(automatic=True)` skips them; `automatic=False` clears the set first.

- **Why the asymmetry?** A manual rescan is an explicit request for a full refresh — the
  pre-existing "teardown leaves no sticky block" behaviour is exactly right there. An automatic
  scan carries no such intent: reverting a deletion within one interval would make the
  dashboard's remove button look broken, and the camera would return **with its MQTT and Home
  Assistant entities**, i.e. a room would reappear as monitored without anyone asking.
- **Why not reuse `_removed_ips`?** That set is a transient teardown guard, discarded when
  teardown completes and documented as deliberately non-sticky. Overloading it would break the
  manual-rescan rediscovery it exists to permit.
- **Why in-memory only?** A restart is itself an operator action that re-reads
  `settings.yaml`, and a removed camera has no entry there — so nothing re-adds it at boot. The
  set only needs to outlive the scan loop, not the process. Saving or renaming the camera
  clears its IP from the set, since both mean "wanted again".
- **Consequence accepted:** a camera removed and then genuinely wanted back requires a manual
  rescan (or a save). That is one click, and it is the direction that fails safe.

### Every exit path stamps the timestamp

The suppressed-by-placeholder-password return and the invalid-subnet return stamp
`_last_scan_ts` as well as the normal and aborted paths. Without this, a permanently failing
precondition would make the due-check true on every 30 s poll, re-entering the function — and
re-logging its warning — indefinitely.

### The skip is reported in the dashboard event log

Skipped cameras are recorded with `_record_event(ip, name, "Scanner/RemovedNotReadded", …)`,
one row per camera so the log's existing IP/name filters apply. From the dashboard the camera
is otherwise just absent, with the explanation buried in the service journal.

- The topic string is chosen so `catOf()` places it in the `Altro` category, which is **on by
  default**; a string matching the `sistema` keywords would have been hidden unless the
  operator enabled that filter.
- **Volume, accepted:** the row repeats on every automatic sweep while the device stays online
  — at the 60 s floor that is ~1400 rows/day per removed camera against a 2000-entry global
  log cap, which will crowd out real camera events. Emitting on first detection and on change
  (the dedupe the hostname resolver uses) is the obvious refinement; it was not applied because
  the requested behaviour was "show it when it happens".

### The stop button and `scan_active` cover the automatic scan too

`_subnet_scan_once` sets `_scan_active` and honours `_scan_cancel` regardless of mode, so an
automatic scan is visible in `GET /api/status` and can be stopped from the dashboard with no
new code. This is a behavioural extension of `scan-control`'s two existing requirements rather
than a separate mechanism, which is why this change modifies that capability instead of adding
one.

## Risks / Trade-offs

- **Two overlapping sweeps.** A deployment with `hostname:` cameras already sweeps every 10
  minutes for resolution; a short rescan interval means two independent sweeps of the same
  subnet. They are deliberately independent (resolution must not touch `scan_active`), so the
  cost is traffic and probe load. Documented in the README.
- **Unattended discovery adds cameras.** Any new ONVIF device on the subnet that accepts the
  common credential becomes a dashboard row and a set of MQTT entities without operator action.
  That is the feature, but it is a behavioural change from manual-only and worth stating.
- **Skip-event log volume** — see Decisions.
- **The removal skip is per-process.** A service restart forgets it; a camera removed before a
  restart and still online will be rediscovered by the first automatic scan after it. The
  config entry stays deleted, so it comes back as an unsaved discovery, not as a configured
  camera.
- **Interval changes take effect within 30 s, not instantly** — acceptable for a knob whose
  unit is minutes.

## Migration Plan

- Purely additive and opt-in: an existing `settings.yaml` without `scan.rescan_time_interval`
  behaves exactly as before. `_save_settings_yaml` writes the key back as `0` on the next save.
- To adopt: set `scan.rescan_time_interval` to a number of seconds ≥ 60 and restart, or `POST`
  it to `/api/config` for immediate effect.
- Rollback: set it to `0` (no restart needed — the loop re-reads it each tick and goes dormant).

## Open Questions

- **Should the skip-event log be deduped?** Left as-is deliberately (see Decisions); the volume
  math argues for first-detection-and-on-change, and that can be applied without a spec change
  if the log proves unusable in practice.
- **Should a removed camera's exclusion survive a restart?** It would need persisting, and the
  case is thin: the config entry is already gone, so what returns is an unsaved discovery.
  Deferred until an operator hits it.
