# serena-fall-bridge Specification

## Purpose

Bridge ONVIF_SUA's fall ("uomo a terra") detection to the companion Serena voice
assistant over the shared MQTT broker: forward a genuine fall-start as a one-shot
Serena command, speak per-camera sensor-active / sensor-fault / recovery
announcements, and do so without ever disrupting the underlying fall-detection
loop. The bridge is opt-in and fire-and-forget, so it also surfaces the
configuration and broker-connectivity faults it can observe on the publishing
side.

## Requirements

### Requirement: Opt-in Serena bridge configuration
The system SHALL expose a `serena` configuration block (env-defaulted, `settings.yaml`-authoritative like the existing `mqtt` block) with fields: `enabled` (default `false`), `topic_prefix` (Serena's MQTT topic prefix, default `alexa`), `node_id` (Serena's node id, default empty), `command_template` (default `caduta_{cam_name}`), `announce_ready` (default `true`), `announce_template` (default `sensore uomo a terra {cam_name} attivo`), `announce_fault` (default `false`), `announce_fault_template` (default `attenzione, sensore uomo a terra {cam_name} non attivo`), `announce_fault_interval_s` (default `300`), `announce_fault_grace_s` (default `60`), and `startup_alarm_max_age_s` (default `300`, the recency window for adopting an in-progress fall at startup — see "Adopt an in-progress fall at startup"). The bridge SHALL emit nothing unless `serena.enabled` is true, an MQTT broker host is configured, and `node_id` is non-empty.

The `enabled`, `announce_ready`, and `announce_fault` flags SHALL be interpreted with explicit boolean coercion applied to both their environment values (`SERENA_ENABLED`, `SERENA_ANNOUNCE_READY`, `SERENA_ANNOUNCE_FAULT`) and their YAML values: the case-insensitive strings `1`, `true`, `yes`, `on` (and a native YAML boolean `true`) resolve to true; every other value — including `0`, `false`, `no`, `off`, and the empty string — resolves to false. A raw non-empty string SHALL NOT be treated as true by virtue of being truthy.

The `command_template`, `announce_template`, and `announce_fault_template` SHALL each be validated at config load: they MAY reference only the `{cam_name}` placeholder. If any references another placeholder or contains malformed braces, the system SHALL log a warning at load and fall back to that field's default rather than allowing a formatting error to surface later. The `announce_fault_interval_s`, `announce_fault_grace_s`, and `startup_alarm_max_age_s` values SHALL be coerced to non-negative numbers, falling back to their defaults (`300` / `60` / `300`) on a non-numeric value; `announce_fault_interval_s` SHALL additionally be clamped up to a floor of `30` seconds (with a warning) so a misconfigured `0`/near-zero interval cannot produce a fault-announcement flood. A `announce_fault_grace_s` of `0` is a legitimate value that disables the startup/flap suppression window entirely — the first fault for an episode may then fire on the first periodic tick on which the camera is not-working, including during normal startup while the first rule check is still in flight. It SHALL NOT be clamped, but the system SHALL log a warning at config load when `announce_fault_grace_s` is `0` noting that startup/flap false "non attivo" announcements are possible.

#### Scenario: Zero grace warns and disables the suppression window
- **WHEN** `announce_fault_grace_s` is `0` and `announce_fault` is true
- **THEN** the system logs a warning at config load that the grace window is disabled, and the first fault announcement for a not-working camera may fire on the first periodic tick (no grace suppression), still subject to `announce_fault_interval_s`

#### Scenario: Disabled by default
- **WHEN** no `serena` block is present or `serena.enabled` is false
- **THEN** the system never publishes a Serena trigger and its fall-alarm state publishing is unchanged

#### Scenario: Falsey enabled string is treated as disabled
- **WHEN** `SERENA_ENABLED` (or `serena.enabled`) is set to `false`, `0`, `no`, `off`, or an empty string
- **THEN** the bridge is disabled and the system never publishes a Serena trigger

#### Scenario: Truthy enabled string is treated as enabled
- **WHEN** `SERENA_ENABLED` (or `serena.enabled`) is set to `true`, `1`, `yes`, or `on` (any case)
- **THEN** the bridge is enabled (subject to `mqtt_host` and `node_id` also being configured)

#### Scenario: Enabled but node_id missing
- **WHEN** `serena.enabled` is true but `node_id` is empty
- **THEN** the system does not publish a Serena trigger and logs a warning that the bridge is misconfigured

#### Scenario: Invalid command_template rejected at load
- **WHEN** `command_template` references a placeholder other than `{cam_name}` (e.g. `caduta {room}`) or contains malformed braces
- **THEN** the system logs a warning at config load and uses the default template `caduta_{cam_name}`, and no formatting error is raised when a fall later fires

### Requirement: Forward fall-start as a one-shot Serena command
When the fall bridge is enabled and a fall **starts** for a camera (the once-per-event `TumbleDetection action=start` transition, guarded so repeated starts while already active are ignored), the system SHALL publish exactly one message to Serena's command topic `<topic_prefix>/<node_id>/trigger/run`. The payload SHALL be the command produced from `command_template` with `{cam_name}` replaced by that camera's **trigger name** — the normalized voice name with spaces replaced by `_`, so the payload is a single space-free token (see "Serena voice name normalization and reserved-word constraint"). All cameras publish to the same single `trigger/run` topic; the camera identity is conveyed by the per-camera token, not by the topic. The message SHALL be published with `retain=False` and QoS 1, reusing the existing MQTT client. This emit SHALL be independent of and in addition to the existing retained state publish on `onvif/<cam>/alarms/fall`.

#### Scenario: Fall start emits one command
- **WHEN** camera `cucina` transitions to a fall (`action=start`) and the bridge is enabled with `node_id=serena`
- **THEN** the system publishes `caduta_cucina` to `alexa/serena/trigger/run` once, non-retained, QoS 1

#### Scenario: Distinct token per camera
- **WHEN** `command_template` is `caduta_{cam_name}` and cameras named `cucina` and `salotto` are configured
- **THEN** a fall on the first publishes payload `caduta_cucina` and a fall on the second publishes payload `caduta_salotto`, both to the same `alexa/serena/trigger/run` topic

#### Scenario: The emitted command is never utterable
- **WHEN** a camera's name normalizes to a multi-word voice name (e.g. `salotto 1`, `cucina piano terra`)
- **THEN** the emitted command still contains no space (`caduta_salotto_1`, `caduta_cucina_piano_terra`), so no spoken transcript can match the SOS trigger and the phrase a person would actually say in the room (`caduta salotto 1`) matches no trigger at all

#### Scenario: State publish still occurs
- **WHEN** a fall starts
- **THEN** the retained `"on"` is still published to `onvif/<cam>/alarms/fall` as before, in addition to the Serena command

### Requirement: Canonical "confirmed-working" predicate
The system SHALL evaluate a single per-camera **confirmed-working** predicate that all Serena announcement logic (active, fault, and recovery) shares, so the positive and negative paths can never disagree about the same camera. A camera is confirmed-working **iff** `stream_alive AND rule_enabled is True`, with one override: a **simulated** camera (`_cameras[ip]["simulated"] is True`) SHALL always evaluate as confirmed-working, mirroring `_refresh_detection_ok`, which reports a simulated camera as `stream_alive=True, rule_enabled=True`. The **fault** condition is the exact complement — NOT confirmed-working. Both the event-driven active announcement (`_refresh_detection_ok`) and the periodic fault driver SHALL derive working/fault state from this one predicate (e.g. a shared `_camera_working(ip)` helper) reading the same per-camera state under `_lock`; neither SHALL read raw `rule_enabled`/`stream_alive` in a way that bypasses the simulated override.

#### Scenario: Simulated camera is confirmed-working on every path
- **WHEN** a camera has `simulated: true` (raw `rule_enabled` may still be `"unknown"` and raw `stream_alive` `False`)
- **THEN** every Serena path treats it as confirmed-working: it MAY emit the active announcement and SHALL NEVER emit a fault announcement

### Requirement: Announce sensor-active on startup
When the bridge is enabled and `announce_ready` is true, the system SHALL cause Serena to speak a per-camera activation announcement once per camera when that camera is first **confirmed-working** (per "Canonical 'confirmed-working' predicate") after ONVIF_SUA starts, so a user hears truthful confirmation that each configured fall sensor is active. The announcement SHALL NOT fire merely because the stream connected, nor while the rule state is still unknown, nor when the rule is confirmed disabled. At most **one** active announcement (whether this first-confirm announcement or the fault-recovery notice defined below) SHALL be emitted for a single confirmed-working transition: when the fault driver emits a recovery notice it SHALL also mark the once-per-process guard satisfied, and the first-confirm path SHALL NOT additionally fire for that same transition.

The announcement SHALL be delivered by publishing the rendered phrase (from `announce_template` with `{cam_name}` replaced by that camera's configured name) to Serena's text-to-speech command topic `<topic_prefix>/<node_id>/tts/set`, non-retained, QoS 1, reusing the existing MQTT client. The announcement SHALL fire at most once per camera per process run: it SHALL NOT repeat on stream reconnects, keepalive ticks, rule-state flaps, or fall events.

The announcement SHALL be governed by the same emit preconditions as the fall command (enabled, broker host set, `node_id` non-empty, client connected) and SHALL be fault-isolated identically (see "Emit never disrupts fall detection").

#### Scenario: Announce once when stream is alive and rule confirmed enabled
- **WHEN** the bridge is enabled with `announce_ready` true, and camera `cucina`'s stream is alive and its tumble rule is confirmed enabled (`rule_enabled` becomes `True`)
- **THEN** the system publishes `sensore uomo a terra cucina attivo` to `<prefix>/<node_id>/tts/set` exactly once

#### Scenario: No announcement while rule state is unknown
- **WHEN** camera `cucina`'s stream is alive but the first rule check has not yet confirmed the rule (`rule_enabled` is `"unknown"`)
- **THEN** no activation announcement is published yet (even though `detection_ok` may already report `on`)

#### Scenario: No announcement when the rule is disabled
- **WHEN** camera `cucina`'s stream is alive but its tumble rule is confirmed disabled (`rule_enabled` is `False`)
- **THEN** no activation announcement is published; if the operator later enables the rule and the next check confirms it, the announcement is then published once

#### Scenario: Reconnect or rule-flap does not re-announce
- **WHEN** a camera that already announced later drops/reconnects its stream or its `rule_enabled` toggles again
- **THEN** no further activation announcement is published for that camera during the same process run

#### Scenario: Announcement disabled
- **WHEN** `announce_ready` is false (or the bridge is disabled)
- **THEN** no activation announcement is published, and fall-command behavior is unaffected

#### Scenario: Recovery after a fault does not double-announce "attivo"
- **WHEN** a camera was not-working past the grace window (fault announced at least once) and then becomes confirmed-working for the first time this process run
- **THEN** exactly **one** active announcement is published for that transition (the fault-recovery notice), and the once-per-process first-confirm path does not also publish a second identical announcement

### Requirement: Announce sensor-fault on degradation (opt-in, multi-shot)
When the bridge is enabled and `announce_fault` is true, the system SHALL cause Serena to speak a per-camera fault announcement while a configured camera is **not confirmed-working** (per "Canonical 'confirmed-working' predicate") — covering a dead/absent event stream, a rule confirmed disabled (`rule_enabled is False`), a rule still unverified (`rule_enabled == "unknown"`), and a camera that is offline or in auth-failed quarantine, but **never** a simulated camera (which the shared predicate reports confirmed-working). Unlike the once-per-process active announcement, the fault announcement SHALL be **multi-shot**: it repeats every `announce_fault_interval_s` seconds for as long as the camera remains not-working.

To avoid false alarms during normal startup and brief flaps, the first fault announcement for a fault episode SHALL be suppressed until the camera has remained not-working continuously for `announce_fault_grace_s` seconds. The announcement SHALL be delivered by publishing the rendered `announce_fault_template` (with `{cam_name}` replaced by that camera's configured name) to Serena's `<topic_prefix>/<node_id>/tts/set` topic, non-retained, QoS 1, under the same emit preconditions and fault-isolation as the other emits (see "Emit never disrupts fall detection"). Fault tracking SHALL be per camera and independent across cameras, and SHALL be driven by a periodic check that has visibility of **all configured cameras**, not only those currently connected.

When a camera that has emitted at least one fault announcement returns to confirmed-working, the system SHALL speak the active announcement (rendered `announce_template`) once as a recovery notice and reset that camera's fault-episode state, so a subsequent degradation announces again after the grace window. The recovery notice SHALL be governed by `announce_fault` alone — **not** by `announce_ready` — because it is part of the fault-tracking feature; it SHALL therefore fire even when `announce_ready` is false, so a `announce_ready: false, announce_fault: true` configuration hears "non attivo" repeats followed by a recovery "attivo" rather than ending on silence. Implementations SHALL NOT route the recovery through an emit helper that is itself gated on `announce_ready`. When `announce_fault` is false the system SHALL never speak a fault or fault-recovery announcement, and the active-on-first-confirm announcement (governed by `announce_ready`) is unaffected.

#### Scenario: Fault announced after grace when a camera never comes up
- **WHEN** `announce_fault` is true and a configured camera has not become confirmed-working for longer than `announce_fault_grace_s` after startup (e.g. offline, or its rule confirmed disabled)
- **THEN** the system publishes `attenzione, sensore uomo a terra <cam_name> non attivo` to `<prefix>/<node_id>/tts/set`

#### Scenario: Fault repeats on the configured interval
- **WHEN** a camera remains not-working and `announce_fault_interval_s` has elapsed since its last fault announcement
- **THEN** the system publishes the fault announcement again, and continues to do so every interval until the camera recovers or the process stops

#### Scenario: No fault announcement within the grace window
- **WHEN** a camera is not-working but has been so for less than `announce_fault_grace_s` (e.g. its first rule check is still in flight at startup)
- **THEN** no fault announcement is published yet

#### Scenario: Recovery notice on return to working
- **WHEN** a camera that already emitted at least one fault announcement becomes confirmed-working
- **THEN** the system publishes the active announcement (`sensore uomo a terra <cam_name> attivo`) once and re-arms fault tracking for that camera

#### Scenario: Recovery fires even when announce_ready is false
- **WHEN** `announce_ready` is false and `announce_fault` is true, and a camera that emitted at least one fault announcement returns to confirmed-working
- **THEN** the system still publishes the recovery active announcement once (the recovery path is gated on `announce_fault`, not `announce_ready`)

#### Scenario: Fault announcements are per-camera independent
- **WHEN** `cucina` is not-working while `salotto` is confirmed-working
- **THEN** the system repeats the fault announcement for `cucina` only, and never announces a fault for `salotto`

#### Scenario: Fault disabled by default
- **WHEN** `announce_fault` is false (the default) or the bridge is disabled
- **THEN** the system never publishes any fault or fault-recovery announcement, regardless of camera health

### Requirement: Emit never disrupts fall detection
The Serena emits (the fall command on `trigger/run`, and the active / fault / recovery announcements on `tts/set`) SHALL be fault-isolated from the detection loop. Each emit helper SHALL be a no-op when the MQTT client is not connected (`_mqtt_client is None`), mirroring the existing `_mqtt_publish` guard, and SHALL NOT let any exception (e.g. a template-formatting error or a transient publish failure) propagate into the caller. Any such failure SHALL be caught and logged, and the fall-alarm state publish on `onvif/<cam>/alarms/fall` and the surrounding detection loop SHALL be unaffected.

#### Scenario: MQTT client not yet connected
- **WHEN** a fall starts while the broker connection is not established (`_mqtt_client` is `None`) even though `mqtt_host` is configured
- **THEN** the emit is a silent no-op, the `"on"` state publish path is unaffected, and no exception reaches the detection loop

#### Scenario: Emit failure does not disrupt detection
- **WHEN** the phrase build or publish raises an exception during a fall
- **THEN** the exception is caught and logged, the retained `"on"` state is still published on `onvif/<cam>/alarms/fall`, and the detection loop continues without a reconnect stall

### Requirement: Bridge observability and delivery visibility
Because the Serena voice path is the sole call-for-help responder and the emit is fire-and-forget with no application-level acknowledgement, the system SHALL surface every failure mode it can observe on the publishing side. It cannot confirm that Serena received or acted on a command (that would require a Serena-side change, which is out of scope), but it SHALL make configuration and broker-connectivity faults visible rather than silent.

The system SHALL provide three layers:

- **(A) Commissioning visibility.** At initialization, when the bridge is enabled and configured, the system SHALL log the fully-resolved target topic `<topic_prefix>/<node_id>/trigger/run` exactly once, so an operator can confirm it matches Serena's actual `node_id` (which on Serena defaults to its hostname).
- **(B) Emit-time connectivity check.** Before publishing a fall command, the system SHALL check that the MQTT client is connected (`is_connected()`). If it is not connected, the system SHALL log an **error** noting the fall command may be lost, and still attempt the (buffered) publish. It SHOULD confirm broker receipt of the QoS-1 publish (e.g. `wait_for_publish(timeout)`), logging an error on timeout/failure. Because this emit runs synchronously on the per-camera detection read thread, the confirmation timeout SHALL be small and bounded (≤ 1 s) so a broker stall cannot block the read loop; the whole check stays inside the emit helper's `try/except`. This confirms delivery to the broker only, not to Serena.
- **(D) Retained diagnostic status.** When enabled, the system SHALL publish a retained Home Assistant diagnostic entity (reusing the existing discovery/state pattern used by the `detection_ok` sensor) reporting bridge health: whether it is enabled, whether the MQTT client is currently connected, and the resolved target topic (as an attribute). This lets an operator or HA automation detect a misconfigured or disconnected bridge continuously, not only at commissioning.

#### Scenario: Resolved topic logged at startup
- **WHEN** the bridge is enabled with a non-empty `node_id` and a configured broker host at initialization
- **THEN** the system logs the fully-resolved `<topic_prefix>/<node_id>/trigger/run` topic once

#### Scenario: Emit while broker disconnected is logged, not silent
- **WHEN** a fall starts while the MQTT client is not connected to the broker
- **THEN** the system logs an error that the fall command may be lost (and does not raise into the detection loop)

#### Scenario: Diagnostic status reflects bridge health
- **WHEN** the bridge is enabled
- **THEN** the system publishes a retained HA diagnostic entity whose state reflects the current MQTT connection status and whose attributes include the resolved target topic

### Requirement: No duplicate or spurious triggers
The system SHALL NOT publish a Serena command for events that are not genuine fall-start transitions. Repeated `action=start` while a camera is already in the alarm state, the 60 s keepalive state republications, and the retained state republished on broker/stream (re)connect SHALL NOT produce a Serena command. Because the emit is non-retained, a Serena reconnecting to the broker SHALL NOT receive a replayed command.

#### Scenario: Repeated starts while active are ignored
- **WHEN** a camera is already in the alarm state and further `action=start` events arrive
- **THEN** no additional Serena command is published

#### Scenario: Keepalive republish does not emit
- **WHEN** the 60 s keepalive loop republishes the current `"on"` state
- **THEN** no Serena command is published

#### Scenario: Reconnect does not replay a command
- **WHEN** the stream/broker reconnects and the current fall state is republished to the state topic
- **THEN** no Serena command is published, and (the command being non-retained) no prior command is replayed to Serena

### Requirement: Re-arm on clear
After a fall clears (`"off"`), the system SHALL be armed to emit a new Serena command on the next genuine fall-start transition for that camera.

#### Scenario: New fall after clear emits again
- **WHEN** camera `cucina` clears to `"off"` and later transitions to a new fall (`action=start`)
- **THEN** the system publishes the Serena command again for the new event

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

### Requirement: Independent per-camera handling
The system SHALL support two or more configured cameras and SHALL track alarm state, de-duplication, and re-arm **independently per camera**. A fall (and its Serena command) on one camera SHALL NOT suppress, delay, or alter the emission for a fall on any other camera. Each camera's command phrase SHALL be derived from that camera's own configured name.

#### Scenario: Concurrent falls on two cameras each emit
- **WHEN** cameras `cucina` and `salotto` both transition to a fall (`action=start`), whether simultaneously or overlapping
- **THEN** the system publishes one command for `cucina` (`caduta_cucina`) and one command for `salotto` (`caduta_salotto`), each exactly once

#### Scenario: One camera active does not block another
- **WHEN** `cucina` is already in the alarm state (already emitted, awaiting `"off"`) and `salotto` then transitions to a fall
- **THEN** the system still publishes the command for `salotto`, and does not re-emit for `cucina`

#### Scenario: Per-camera re-arm is independent
- **WHEN** `cucina` clears to `"off"` while `salotto` remains `"on"`
- **THEN** `cucina` is re-armed for its next fall and `salotto` still does not re-emit until it clears and falls again

### Requirement: Serena voice name normalization and reserved-word constraint
The camera name substituted for `{cam_name}` SHALL be rendered through a normalization step so it is friendly for both Serena's matching and Piper TTS: the name SHALL be lowercased, separator characters (`-`, `_`) SHALL be replaced with a single space, and runs of whitespace SHALL be collapsed and trimmed. Normalization SHALL be applied at render time only; the camera's stored/displayed name and its `onvif/<cam>/alarms/fall` state topic are unaffected. If normalization yields an empty string (e.g. a hand-edited name of only separators), the system SHALL fall back to the camera's raw stored name (or its IP if that is also empty) and log a warning, rather than emitting a phrase with a missing name.

The **fall command** SHALL additionally have every space in the normalized name replaced with `_`, so the rendered payload is a single space-free token (`salotto-1` → `caduta_salotto_1`). This is a correctness requirement, not cosmetic: the command is matched by Serena against the same trigger table a spoken transcript is matched against, so a command containing spaces is an ordinary utterable phrase and the SOS trigger it fires — a call plus a Telegram alert, configured `with_wake: false` — can be set off by anyone in the room saying it. A space-free token cannot be produced by the STT path, so the trigger is reachable only over MQTT. The **announcement templates** (active, fault, recovery) SHALL NOT apply this substitution and SHALL keep the spaced form, because Piper has to read them aloud.

A camera name SHALL NOT contain the substring `camera` (case-insensitive). Additionally, a camera name SHALL NOT be accepted if its **normalized voice name** collides with that of another already-configured camera (e.g. `salotto-1` and `salotto_1` both normalize to `salotto 1`), because Serena distinguishes cameras solely by the rendered phrase. The web rename and save endpoints SHALL reject a name that violates either rule with a user-facing error alert and SHALL NOT apply it — neither writing it to the device (ONVIF `SetHostname`) nor persisting it to `settings.yaml`. The shared persistence path (`_config_add_camera`) SHALL enforce both rules as a chokepoint, and config load SHALL log a warning for any already-configured camera whose name contains `camera` or whose normalized name collides with another camera's.

#### Scenario: Name normalized into phrase and announcements
- **WHEN** a camera's configured name is `salotto-1` and `command_template` is `caduta_{cam_name}`
- **THEN** the emitted fall command is `caduta_salotto_1` (space-free single token) and its active announcement is `sensore uomo a terra salotto 1 attivo` (spaces preserved for TTS)

#### Scenario: Rename to a name containing "camera" is rejected with an alert
- **WHEN** an operator tries to rename a camera to `Camera 0` (or any name whose sanitized form contains `camera`, e.g. `telecamera-2`)
- **THEN** the rename endpoint returns an error with a user-facing message, the device hostname and `settings.yaml` are left unchanged, and no voice name is derived from it

#### Scenario: Save of a name containing "camera" is rejected
- **WHEN** an operator saves a camera with a name whose sanitized form contains `camera`
- **THEN** the save endpoint returns an error alert and the camera is not persisted with that name

#### Scenario: Config-load warning for a reserved name
- **WHEN** `settings.yaml` is hand-edited so a camera's name contains `camera` and the process starts
- **THEN** the system logs a warning identifying that camera name as violating the reserved-word constraint

#### Scenario: Rename to a normalized-name collision is rejected
- **WHEN** camera A is configured as `salotto-1` and an operator renames/saves camera B to `salotto_1` (both normalize to `salotto 1`)
- **THEN** the endpoint returns an error alert, camera B is not persisted with that name, and the device hostname is left unchanged
