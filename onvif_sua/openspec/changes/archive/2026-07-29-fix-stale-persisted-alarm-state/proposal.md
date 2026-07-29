## Why

`alarm.json` persists each camera's current fall-alarm state so a fall that was in
progress when the service restarted is not silently dropped. The recency window
(`serena_startup_alarm_max_age_s`, default 300 s) was applied only to the **Serena voice
emit**: the spec says a stale `"on"` must not synthesize a command, and that "the
retained state republish is unaffected".

That leaves a state nobody wants. A week-old `"on"` for a still-configured camera is
loaded verbatim into `_cam_alarms` and republished to MQTT on the first connect, so Home
Assistant shows the fall alarm **active** — and nothing can clear it: `_fire_stop` only
runs off a real `Stop` event, and that `Start`/`Stop` pair completed while the service
was down. The alarm latches until the next genuine fall completes.

It is also internally inconsistent: for the *same* persisted state the Serena bridge
correctly stays silent while Home Assistant reports an active fall. One of the two is
wrong about whether a person is on the floor.

Observed on a live install: `{"saved_at": "2026-07-29T10:31:04", "cucina": "on"}` was
still on disk 11 minutes later. It happened to be harmless only because that camera had
since been renamed and the orphan prune dropped it — rename it back and the install
boots with a latched alarm.

## What Changes

- Apply the existing recency window to the **loaded state**, not only to the synthesized
  Serena emit: an `"on"` older than `serena_startup_alarm_max_age_s` is loaded as
  `"off"`, so the connect-time republish actively clears the Home Assistant entity
  instead of re-asserting a fall that ended hours ago.
- An `alarm.json` with a missing or unparseable `saved_at` is treated as stale for this
  purpose: the age cannot be established, so an `"on"` is not trusted.
- `"off"` entries are unaffected at any age — only `"on"` is age-sensitive.
- Log the discarded entries with their age and the limit, so the transition from "alarm
  was on" to "alarm is off" is explained rather than looking like lost state.
- No new configuration: the window is the knob that already exists for exactly this
  question, which also removes the possibility of the two gates disagreeing.

## Capabilities

### Modified Capabilities
- `serena-fall-bridge`: the "Adopt an in-progress fall at startup" requirement gains the
  loaded-state half of the recency gate. Its "Stale persisted alarm does not emit"
  scenario currently asserts the republish is unaffected, which is the behaviour being
  corrected.

## Impact

- **Runtime**: `worker.py` `_load_alarm_file()` — compute freshness from the preserved
  `saved_at` and coerce a stale `"on"` to `"off"` before it reaches `_cam_alarms`, plus
  the diagnostic. The Serena adoption gate downstream is left in place: it becomes
  redundant for a stale file (the state is now already `"off"`) but still guards the
  emit independently.
- **Tests**: `tests/test_alarm_prune.py` extended from 4 to 11 tests. Note that two
  existing tests hardcoded a `saved_at` five days in the past while asserting that
  `"on"` was kept — they were pinning the buggy behaviour, and now build their timestamp
  relative to now.
- **Docs**: none required; the behaviour is internal to startup state loading.
- **Dependencies**: none.

## Open Questions

- **Does the camera re-signal a still-ongoing fall after a restart?** The Dahua CGI
  debounce logic implies `TumbleDetection` re-emits `Start` while the condition persists
  (`# else: già ON, start multipli ignorati`, and the stop timer is cancelled on every
  `Start`), which would make the whole startup-adoption mechanism largely redundant for
  a genuinely-still-fallen person. The adoption requirement asserts the opposite ("the
  `action=start` edge ... does not re-fire"). Unverified on hardware, and it does not
  block this change: age-gating the load is correct under either model. Worth settling
  with a raw event-stream capture, because if `Start` does repeat, the persisted-state
  mechanism could be simplified to MQTT/HA continuity only.
