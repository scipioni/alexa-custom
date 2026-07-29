## MODIFIED Requirements

### Requirement: Adopt an in-progress fall at startup
Because the Serena voice path is the sole call-for-help responder, a fall that was already active when ONVIF_SUA (re)started SHALL NOT be silently dropped. The fall command is normally bound to the `action=start` edge, which does not re-fire for a fall whose onset preceded the process; the persisted `"on"` in `alarm.json` is the only surviving evidence. When the bridge is enabled, on the **first** successful stream connect of the process for a camera (the existing `first_attach` guard) whose loaded alarm state is `"on"` and no fall-start has fired this run (`alarm_active` is still false), the system SHALL synthesize exactly one Serena fall command for that camera and adopt the episode (set `alarm_active` true) so subsequent `action=start` events and stream reconnects do not re-emit and a later `"off"`/`_fire_stop` re-arms normally.

To avoid re-triggering on a stale alarm (e.g. the process crashed between `start` and the `_fire_stop` write, or the person recovered during the outage), the synthesized emit SHALL be **recency-gated**: it fires only if the persisted state was saved within `serena_startup_alarm_max_age_s` (default `300`). This requires preserving `alarm.json`'s `saved_at` timestamp at load. A persisted `"on"` older than the window SHALL NOT emit.

The same window SHALL gate the **loaded state itself**, not only the synthesized emit: a persisted `"on"` older than `serena_startup_alarm_max_age_s` SHALL be loaded as `"off"`. The recency window is therefore the single answer to "how old may a persisted alarm be before it stops being evidence that a person is on the floor", and the two consumers of that state cannot disagree about it.

Gating only the emit is insufficient. `_fire_stop` — the only path that clears an alarm — is armed by a real `action=stop` event, so a `Start`/`Stop` pair that completed while the service was down leaves nothing able to clear a persisted `"on"`. Loaded verbatim, that state is re-asserted by the connect-time republish onto a **retained** MQTT topic, so Home Assistant reports an active fall indefinitely — while the bridge, correctly gated, stays silent about the same state. One of the two would be wrong about whether someone needs help.

An `alarm.json` whose `saved_at` is absent or unparseable SHALL be treated as stale for this purpose: the age cannot be established, so an `"on"` is not trusted. A persisted `"off"` SHALL be loaded unchanged regardless of age — only `"on"` is age-sensitive. When a persisted `"on"` is discarded, the system SHALL log the affected cameras with the state's age and the configured limit, so the alarm clearing at startup is explained rather than appearing as lost state.

#### Scenario: Fresh in-progress fall at startup emits once
- **WHEN** the bridge is enabled, `alarm.json` has `cucina = "on"` saved within `serena_startup_alarm_max_age_s`, and the camera's stream connects for the first time this run
- **THEN** the system publishes the Serena fall command for `cucina` exactly once, adopts the episode (`alarm_active` true), and does not re-emit on subsequent `action=start` events or reconnects

#### Scenario: Stale persisted alarm does not emit
- **WHEN** `alarm.json` has `cucina = "on"` but it was saved longer ago than `serena_startup_alarm_max_age_s`
- **THEN** no Serena fall command is synthesized at startup

#### Scenario: No persisted alarm means no startup emit
- **WHEN** `alarm.json` has `cucina = "off"` or no entry for the camera at startup
- **THEN** no Serena fall command is synthesized at startup

#### Scenario: A stale persisted alarm is loaded as off
- **WHEN** `alarm.json` has `cucina = "on"` saved longer ago than `serena_startup_alarm_max_age_s` and `cucina` is still configured
- **THEN** the loaded state for `cucina` is `"off"`, the global fall alarm is not latched on by it, and the connect-time republish therefore reports the alarm as off rather than active

#### Scenario: A fresh persisted alarm is still loaded as on
- **WHEN** `alarm.json` has `cucina = "on"` saved within `serena_startup_alarm_max_age_s`
- **THEN** the loaded state for `cucina` is `"on"` and the global fall alarm is on, so a fall in progress across a restart is preserved

#### Scenario: A persisted alarm with no usable timestamp is not trusted
- **WHEN** `alarm.json` has `cucina = "on"` but its `saved_at` is absent or cannot be parsed
- **THEN** the loaded state for `cucina` is `"off"`

#### Scenario: A stale off is loaded unchanged and silently
- **WHEN** `alarm.json` has `cucina = "off"` saved longer ago than the window
- **THEN** the loaded state is `"off"` and no discard diagnostic is logged for it

#### Scenario: Widening the window keeps an older alarm
- **WHEN** `serena_startup_alarm_max_age_s` is configured larger than a persisted alarm's age
- **THEN** that `"on"` is loaded as `"on"`, and the startup emit gate accepts it as well — the two never disagree about the same state

#### Scenario: The discard is explained in the log
- **WHEN** a persisted `"on"` is discarded as stale
- **THEN** the log names the affected cameras, the age of the state, and the configured limit
