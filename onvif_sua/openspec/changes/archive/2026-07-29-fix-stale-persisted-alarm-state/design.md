## Context

`_load_alarm_file()` (`worker.py`) runs once at startup. It reads `alarm.json`, pops
`saved_at` into the module global `_alarm_saved_at`, prunes entries for cameras no longer
in `settings.yaml`, loads the rest into `state._cam_alarms`, and derives the global
`_alarms["Alarm uomo a terra"]` from them.

Two consumers then read that state:

1. **The MQTT/Home Assistant republish.** On the first successful stream connect,
   `_mqtt_publish(cur, _cam_alarms.get(cur, "off"))` re-asserts the camera's alarm topic.
   Because the topic is retained, this is what Home Assistant shows until something
   changes it.
2. **The Serena startup adoption** (`worker.py:503`), which fires one synthesized fall
   command if the state is `"on"` **and** `time.time() - _alarm_saved_at` is within
   `serena_startup_alarm_max_age_s`.

Only (2) was recency-gated. `_fire_stop` — the only thing that turns an alarm off — runs
from a `threading.Timer` armed by a real `action=stop` event, so a `Start`/`Stop` pair
that completed while the process was down leaves nothing able to clear a persisted `"on"`.

## Goals / Non-Goals

**Goals:**
- Stop a stale persisted `"on"` from presenting as an active fall in Home Assistant.
- Keep genuine restart recovery: an `"on"` from seconds ago must still be adopted.
- Make the two consumers agree about the same persisted state.

**Non-Goals:**
- Not removing `alarm.json` or the adoption mechanism.
- No new configuration key.
- Not changing what `_fire_stop`, the 10 s debounce, or the retained-topic scheme do.
- Not resolving whether Dahua re-emits `Start` for an ongoing fall (see the proposal's
  open question) — this change is correct either way.

## Decisions

### Reuse `serena_startup_alarm_max_age_s` rather than adding a key

The value already answers precisely "how old may a persisted alarm be before it is no
longer evidence that someone is on the floor". Sharing it makes the two gates
structurally unable to disagree, which is the inconsistency being fixed.

- **Why not a new `tuning.alarm_max_age_s`?** Two knobs answering one question drift
  apart, and the interesting failure — the state loads `"on"` while the bridge refuses to
  announce it — is exactly what two independent windows would reintroduce.
- The name is now slightly narrow, since the value governs more than the Serena emit.
  Renaming it would be a breaking config change for a cosmetic gain; not worth it. The
  spec text is where that scope is recorded.
- It is normalized by `_normalize_serena_config()` on every config load regardless of
  `serena.enabled`, so it is always available — the gate does not depend on the bridge
  being on.

### A stale `"on"` becomes `"off"`, rather than being dropped

Dropping the key would leave `_cam_alarms` without an entry; `_mqtt_publish(cur,
_cam_alarms.get(cur, "off"))` would still publish `"off"`, so the end state matches.
Writing `"off"` explicitly is preferred because `_cam_alarms` is also read by the
keepalive loop, `/api/alarms` and `/alarm.json`, and an explicit `"off"` makes those
agree with what was published instead of relying on each reader's default.

### Only `"on"` is age-sensitive

A stale `"off"` asserts nothing dangerous, so it is loaded unchanged and produces no
diagnostic. Gating it would add log noise for the common case (every ordinary restart
loads `"off"` entries).

### Missing or unparseable `saved_at` counts as stale

`_alarm_saved_at` is already `0.0` in both cases, so `time.time() - 0` is enormous and
fails the window naturally; the implementation additionally tests `_alarm_saved_at > 0`
so the intent is explicit rather than incidental. An `alarm.json` that cannot say when it
was written cannot support the claim that a fall is still in progress.

### The Serena gate stays

It becomes redundant when the file is stale — the state is already `"off"`, so the
adoption condition fails on that alone. It is kept because it guards a different thing
(whether to *emit*, given whatever state was loaded) and removing it would make the emit
depend entirely on the load path having gated correctly.

## Risks / Trade-offs

- **A real fall spanning a long outage is dropped.** If someone falls and the service is
  down for more than the window (default 5 min), the alarm no longer reappears at boot.
  That is the intended trade: after 5 minutes the persisted flag is no longer evidence of
  anything, and a fall detector that reports a stale fall is worse than one that reports
  none — the operator stops trusting the alarm. Widening the window is a one-line config
  change for installs that want more.
- **A camera stuck in a genuine ongoing fall relies on the camera re-signalling.** If
  Dahua does *not* re-emit `Start` (the adoption requirement's assumption) and the outage
  exceeded the window, the alarm stays off until the next fall. This is the same exposure
  the Serena gate already accepted; this change extends it to the HA state, making the
  two consistent.
- **Behaviour visible on the next restart of every install.** An install currently
  carrying a stale `"on"` will see the alarm clear at boot and log the reason. That is
  the fix, but it will look like state loss to anyone who had adapted to the old
  behaviour.

## Migration Plan

- No config or file-format change; `alarm.json` is read and written exactly as before.
- No action required to adopt. The first restart after upgrading discards any stale
  `"on"` and logs it.
- Rollback: revert the `_load_alarm_file` change. The file itself is unaffected either
  way, so there is no persisted state to unwind.
