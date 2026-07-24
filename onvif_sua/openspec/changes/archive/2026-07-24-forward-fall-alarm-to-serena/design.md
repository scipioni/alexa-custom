## Context

Two independent services on the same LAN and MQTT broker:

- **ONVIF_SUA** (this repo) detects falls. In `onvif_sua/worker.py` the Dahua CGI stream handler fires `TumbleDetection action=start`; at `worker.py:509-522` this is guarded by `if not alarm_active:` (`# else: già ON, start multipli ignorati`), so `_mqtt_publish(cur, "on")` runs **exactly once per fall event**. `_fire_stop()` later publishes `"off"`. The retained state topic is also republished on connect (`worker.py:451`) and every 60 s by a keepalive loop — but neither of those passes through the start handler. The MQTT client (`onvif_sua/mqtt.py`, paho, `client_id="onvif-events"`) is already connected to the broker.
- **Serena** (alexa-custom) subscribes to `<topic_prefix>/<node_id>/trigger/run` (default prefix `alexa`, `node_id` = hostname or `state.yaml` override). An incoming payload becomes `{"command": payload}`, is matched against `config.triggers`, and dispatched on Serena's STT thread (reentrancy-safe path required by its Vosk/VAD backend). Serena's `ask` action already implements spoken prompt + reply capture with `on_reply` (yes/no) and `on_else` (silence/unclear) branches, and `on_else` may contain a nested `ask` (parsed recursively). `livekit_join` and `telegram` actions already exist; the exact "confirm → call + notify" pattern ships in `conf.example/actions/user.yaml` (`chiama assistenza`).

The gap is purely the *link*: nothing tells Serena a fall occurred. This change adds that link on the ONVIF_SUA side, keeping Serena's code untouched.

## Goals / Non-Goals

**Goals:**
- On a genuine fall-start, cause Serena to run its spoken confirmation naming the sensor, with the yes/no → call + Telegram flow and a no-answer fail-safe.
- On startup, once each camera's event stream connects, have Serena speak a per-camera "sensore uomo a terra \<name\> attivo" so the user hears that each fall sensor is working.
- Zero modifications to Serena source; the response is 100% authorable in Serena's `conf/actions/user.yaml`, and the startup announcement reuses Serena's existing `tts/set` command topic.
- Reuse ONVIF_SUA's existing MQTT client and the `alarm_active` edge guard (no new debounce/state code).
- Opt-in; no behavior change when disabled.

**Non-Goals:**
- No changes to the existing `onvif/<cam>/alarms/fall` state-topic contract.
- No dynamic value passing into a single generic Serena trigger (Serena's `trigger/run` carries only a match phrase); the sensor name is handled per-camera in YAML (see D3).
- No gating on the separate `camera_status/fall_sensor_online` liveness sensor (possible later).
- No new LiveKit/Telegram config — reuse Serena's existing env/config.

## Decisions

### D1: Emit the trigger inside the existing `alarm_active` start guard
Add a single call `_mqtt_publish_serena_trigger(cur)` right after `_mqtt_publish(cur, "on")` at `worker.py:521`, inside `if not alarm_active:`. This inherits the once-per-fall semantics for free: keepalive republishes and reconnect state-republishes do not enter this branch, and repeated `action=start` while already active are ignored. No separate edge-detection or cooldown code is required.
- **Alternative — a separate subscriber/bridge process:** rejected; more moving parts, and it would have to reconstruct the edge detection ONVIF_SUA already has.

### D2: Publish one-shot (non-retained) to Serena's `trigger/run`
`_mqtt_publish_serena_trigger()` publishes `payload = <command phrase>` to `<serena_prefix>/<serena_node>/trigger/run` with `retain=False`, QoS 1. Non-retained is essential: a retained command would be replayed to Serena on every reconnect and re-fire the confirmation. QoS 1 gives at-least-once delivery for a safety-relevant message; Serena's per-fall flow is effectively idempotent for the short window (livekit_join is a no-op if already connected).
- **Alternative — Serena's `action/run` JSON topic:** rejected; it builds a flat synthetic trigger that cannot express nested `on_reply`/`on_else`, so the yes/no + fail-safe flow can't be represented.

### D3: Per-camera command phrase carries the sensor identity
The command phrase is built from a template (default `caduta {cam_name}`) using the camera's configured `name` — the same name already used in the state topic. Serena has one `with_wake: false` trigger per camera whose `ask` text names that sensor. Serena's `trigger/run` conveys only a phrase (no variables), so per-camera phrasing is how the sensor name reaches the spoken prompt without any Serena code.
- Trade-off: N cameras → N Serena triggers. Acceptable for the small camera counts in scope; documented so operators can add a trigger when they add a camera.
- **Alternative — single generic phrase + dynamic name:** would require a code change in Serena (placeholder substitution). Explicitly out of scope per the zero-Serena-code goal.
- **Name hygiene (chosen: option B — normalize at render + reserved-word block).** The name flows into both the fuzzy match phrase and the Piper-spoken announcements, so it must be match- and speech-friendly. The GUI rename already restricts names to `[A-Za-z0-9-]` (`web/routes.py:90`), so exotic characters are largely gone already; a `_serena_voice_name()` helper additionally lowercases and turns `-`/`_` into spaces (`salotto-1` → `salotto 1`) before every `format(cam_name=...)`. Operators write the Serena YAML `commands` in this normalized form.
- **Reserved word `camera`.** Per product decision, a camera name must not contain `camera` (case-insensitive) — this pushes operators toward room-based names (`cucina`, `salotto`) that read naturally in "persona caduta sul sensore SUA \<name\>" and avoids device-jargon like `camera0`. Enforced with a user-facing alert at the two write points that mirror the existing name-conflict alert (`web/routes.py:102-107`): `api_rename_camera` (checked right after sanitization at `:90`, **before** the device `SetHostname` at `:116`) and `api_save_camera` (`:160`), plus the shared `_config_add_camera` chokepoint and a config-load warning for hand-edited YAML. Note (open to refinement): the check is a case-insensitive **substring**, so it also blocks `telecamera`; the default seeded `camera0` in `settings.yaml` must be renamed to a room name for the bridge to accept it.

### D4: The full confirmation/fail-safe flow lives in Serena YAML
The example trigger uses nested `ask`:
- outer `ask` → `on_reply` sì → `say` + `livekit_join` + `telegram`; `on_reply` no → `say "va bene, chiamata annullata"`.
- outer `ask.on_else` (silence/unclear) → **nested** `ask` (repeat the question); nested `ask.on_else` → `say "non ho ricevuto risposta, chiamo aiuto"` + `livekit_join` + `telegram` (fail-safe call).
This is verified against Serena's `handle_ask` (`on_else` runs on both timeout and unclear reply, via `_run_action`, which dispatches nested actions). Ships as copy-paste docs in this change.

### D5: Config surface (ONVIF_SUA)
`config.py` gains env-default keys and `settings.yaml` `serena:` parsing (authoritative, matching the existing MQTT pattern):
```yaml
serena:
  enabled: false
  topic_prefix: alexa          # Serena's MQTT topic_prefix
  node_id: ""                  # Serena's node_id (its hostname or state.yaml override)
  command_template: "caduta {cam_name}"
```
The emit is a no-op unless `serena.enabled` and `mqtt.host` are set and `node_id` is non-empty.

### D6: Startup "sensor active" announcement via Serena's `tts/set` topic
When enabled with `announce_ready` (default on), ONVIF_SUA publishes the rendered `announce_template` (default `sensore uomo a terra {cam_name} attivo`) to Serena's `<prefix>/<node_id>/tts/set` topic once per camera, the first time that camera is **confirmed fully working** — its event stream is alive **and** its tumble-detection rule is confirmed enabled. Serena already subscribes to `tts/set` and speaks the payload (`alexa_custom/mqtt.py:59,177` → `{"type":"say", ...}`), so no Serena code is needed — a plain `say`, distinct from the `trigger/run` confirmation flow.

- **Truthful "attivo" — the fire condition is `stream_alive AND rule_enabled is True`, not `detection_ok == "on"`.** `_compute_detection_ok` (`mqtt.py:158`) returns `"on"` when `stream_alive AND rule_enabled is not False` — so it is also `"on"` while `rule_enabled == "unknown"` (before the first rule check). Announcing on `detection_ok` would speak "attivo" without having actually verified the rule. The announcement therefore gates on the strict tri-state value `rule_enabled is True`, set by `_apply_rule_state` (`worker.py:686`) after `_do_rule_check` confirms the tumble rule is enabled on the camera.
- **Fire point:** inside `_refresh_detection_ok(ip)` (`mqtt.py:166`) — the single funnel already called on every stream-liveness change (`_mark_stream_seen`) and every rule-state change (`_apply_rule_state`). Under the existing lock, compute `announce_now = (not cam["serena_announced"]) and stream_alive and (rule_enabled is True)`; if so, set `cam["serena_announced"] = True` and, outside the lock, call `_mqtt_announce_serena_active(name)`. Whichever of {stream-alive, rule-confirmed} completes the pair last triggers it.
- **Cross-thread flag:** the once-per-process guard lives in the shared per-camera state `_cameras[ip]["serena_announced"]` (set under `_lock`), not a thread-local, because the two inputs arrive on different execution contexts — stream liveness on the attach OS thread, rule confirmation on the asyncio rule-check task.
- **Latency is small:** the first rule check "runs immediately" (`_rule_check_task`, `worker.py:743`), so the confirmation typically arrives within seconds of startup — only *subsequent* checks are `RULE_CHECK_INTERVAL`-spaced. If the rule is genuinely disabled, no announcement is made (correct — the sensor is not active); it will fire later if the operator enables the rule and the next check confirms it.
- **Once per camera per process:** the flag suppresses re-announcing on stream reconnects, keepalive ticks, and rule-state flaps. Staggered cameras each announce as they are confirmed; Serena serializes the `say`s on its STT thread. Simulated cameras (which `_refresh_detection_ok` reports as `stream_alive=True, rule_enabled=True`) announce like real ones.
- **Alternative — announce on stream-connect / on `detection_ok`:** rejected. Stream-connect only proves reachability, not that fall detection is enabled; `detection_ok` counts `"unknown"` as on. Both would let ONVIF claim "attivo" when the rule is not actually verified.
- **Delivery caveat:** `tts/set` is non-retained; if Serena is not yet subscribed when the camera is confirmed at boot, the announcement is lost (same fire-and-forget limitation as the fall command — see `problem.md`). Lower stakes for a confirmation chime; not mitigated beyond the shared connectivity checks.

### D7: Fault "sensor NOT active" announcement — opt-in, multi-shot, with recovery
The positive announcement (D6) only ever speaks good news, so a camera that never comes up is audibly silent — a weak signal for a life-safety system. `announce_fault` (default off) adds the negative side. Rationale for the shape:

- **Multi-shot, not once:** a not-working fall sensor is a persistent hazard, so the announcement repeats every `announce_fault_interval_s` (default 300 s) until the camera recovers, rather than firing once and being forgotten. The user asked for this explicitly.
- **Fault = NOT (`stream_alive AND rule_enabled is True`)** — the exact complement of the D6 confirmed-working condition. This deliberately includes `rule_enabled == "unknown"`, `rule_enabled is False`, a dead stream, and offline/auth-failed cameras. Any state that isn't provably active is treated as a fault.
- **Grace window (`announce_fault_grace_s`, default 60 s):** suppresses the first announcement until the camera has been not-working continuously for the grace period, so normal startup (first rule check in flight) and brief flaps don't produce a false "non attivo". This is why fault can't reuse the purely event-driven D6 funnel.
- **Driver — a periodic loop over ALL configured cameras.** Unlike D6 (event-driven on stream/rule change), fault needs a periodic tick to (a) enforce the interval and (b) cover cameras that never emit any event because they never connected. The 60 s alarm-keepalive loop is the natural host **iff** it iterates the full configured camera list; if it only visits connected cameras, add a small dedicated periodic task over `config` cameras. Per-camera state (`_cameras[ip]`): `serena_fault_since` (float|None — when it entered the current fault episode, for grace), `serena_fault_last_ts` (last fault emit, for interval), `serena_fault_announced` (bool — did this episode emit ≥1 fault, drives recovery).
- **Recovery notice:** when a camera with `serena_fault_announced` returns to confirmed-working, speak the *active* template (`announce_template`) once and clear the episode state (`serena_fault_since=None`, `serena_fault_last_ts=0`, `serena_fault_announced=False`), re-arming for a future degradation. This keeps the audible story coherent ("attivo" … "non attivo" ×N … "attivo") instead of ending on silence. Gated on `announce_fault` (it is part of the fault-tracking feature).
- **Interaction with D6:** D6's `serena_announced` (first-confirm, once per process) is independent and still handled event-driven in `_refresh_detection_ok`; the periodic fault driver never touches it. A camera confirmed within grace → D6 fires, no fault episode. A camera not confirmed within grace → fault episodes drive both the "non attivo" repeats and the eventual recovery "attivo".
- **Fault-isolation & preconditions** are identical to the other emits (`_mqtt_client` connected, enabled, `node_id` set; all wrapped in `try/except`).

## Risks / Trade-offs

- **[Retained command re-fires on reconnect]** → Publish with `retain=False`. Pinned by a spec scenario.
- **[Wrong/empty Serena node_id → command goes nowhere]** → Require non-empty `node_id` to emit; log a one-time warning when enabled but unconfigured. Document that `node_id` must match Serena's (hostname or `state.yaml`).
- **[Broker mismatch]** → If the two services use different brokers, nothing arrives. Documented as an external contract; both already default to `localhost:1883`.
- **[Phrase must match a Serena trigger]** → If the phrase doesn't match any `config.triggers`, Serena logs a no-match and beeps. Mitigation: ship exact example phrases/triggers; keep the template and the YAML `commands` list in sync (documented).
- **[Fail-safe call on no-answer may dial unwanted]** → Deliberate product choice (person may be incapacitated); bounded by the two-ask sequence and `livekit_join`'s already-connected no-op. Operator can edit the inner `on_else` in YAML.
- **[Extra emit adds coupling ONVIF→Serena]** → Kept minimal and opt-in; ONVIF only needs Serena's topic prefix + node_id, nothing about Serena internals.
- **[Fault announcement is noisy / cries wolf]** → Off by default (`announce_fault: false`); grace window suppresses startup/flap false alarms; interval is operator-tunable. A genuinely-down sensor repeating every few minutes is the intended behavior for a safety device.
- **[Fault repeats forever while a camera is intentionally offline]** → Documented; operator can disable the rule expectation by removing the camera from config or setting `announce_fault: false`. (No auto-mute, by design — a silently-dropped safety sensor is the failure mode we are guarding against.)

## Migration Plan

1. Land ONVIF_SUA code (opt-in, `serena.enabled: false` default) — no behavior change.
2. Configure `settings.yaml` `serena:` block on the ONVIF_SUA host (enable, set Serena's `node_id`, confirm same broker).
3. On the Serena host, add the per-camera fall trigger(s) to `conf/actions/user.yaml` (from the shipped example); ensure `LIVEKIT_ROOM` + Telegram are configured. Serena hot-reloads config.
4. Rollback: set `serena.enabled: false` and restart ONVIF_SUA; optionally remove the Serena trigger. No other behavior affected.

## Open Questions

- **Startup with a person already down** (fall began before ONVIF_SUA started): the start event only fires on a fresh `action=start`, so a pre-existing fall won't emit until the detector re-triggers. Acceptable? Or emit once on first observed `"on"` at connect? Current lean: only on true start transitions.
- **Cooldown**: the `alarm_active` guard already prevents re-emits until an `off`. Do we also want a minimum re-arm interval to avoid rapid off/on flapping producing repeated calls? Deferred; add later if observed.
- **Multiple cameras falling near-simultaneously**: Serena serializes dispatch on its STT thread, so the second confirmation queues behind the first. Acceptable.
