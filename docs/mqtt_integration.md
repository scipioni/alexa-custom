# MQTT & Home Assistant Integration

The client registers itself with Home Assistant via **MQTT Discovery** on startup. No manual YAML configuration is needed in HA.

## Exposed Entities

- **Status (Sensor)**: `idle`, `listening`, `speaking`, `gated` (during calls).
- **Last Command (Sensor)**: Text of the last recognized voice command.
- **Speak Text (Text)**: Type a message in HA → the speakerphone says it (plain text, not JSON).

> Note: The client publishes **Sensor** and **Text** entities, not Media Player or Voice Assistant entities.

---

## Bidirectional Communication

### 1. Client → HA (Publishing)

Every recognized command publishes to `alexa/<node_id>/command` as JSON:

```json
{"text": "accendi la luce", "wake_word": "ehi galileo", "timestamp": 1234567890.1}
```

State changes publish to `alexa/<node_id>/state`:
- `idle`, `listening`, `speaking`, `gated` (during calls)

Only **transitions** are published. `idle` is the resting state the daemon
returns to from several places (the `say` handler and the recognition loop both
do), so a single spoken reply used to emit `speaking`, `idle`, `idle`. The
duplicate is now dropped in `MQTTClient.publish()` and counted as
`mqtt_state_deduped` (visible on the dashboard's `/metrics`). Consumers must
therefore treat "no new state" as "unchanged", not as idle-again. The
deduplication baseline is cleared on every broker (re)connect, so a subscriber
that missed state during an outage still receives the current value afterwards.

`offline` is published once on graceful shutdown, bypassing the deduplication.

### 2. HA → Client (Listening)

| Topic | Payload | Effect |
|---|---|---|
| `alexa/<node_id>/tts/set` | `Ciao!` (plain text, not JSON) | Speak via TTS |
| `alexa/<node_id>/action/run` | `{"type": "tone", "params": {"name": "info"}}` | Execute one action directly (bypasses trigger matching — `params` must be nested, unlike YAML's flattened shorthand) |
| `alexa/<node_id>/trigger/run` | `chiama assistenza` (plain text, not JSON) | Run a configured trigger from `conf/actions/user.yaml` by command phrase — matched with the same fuzzy/phonetic logic as a spoken command, so `patterns`/`on_reply`/`on_else`/`tag` all apply exactly as they would for real speech (ignores `with_wake` gating) |

> Note: there is no `config/set` topic — MQTT cannot update runtime config. Config changes go through `conf/config.yaml` / `conf/actions/user.yaml` hot-reload or the web dashboard.

### `node_id` vs `local_id`

`mqtt.node_id` is meant to be **unique per board** (HA entity uniqueness, bridge
namespace isolation — see "Additional boards" below). `mqtt.local_id` (default
`arduino`) is a **fixed alias**, equivalent to `node_id`, that stays the same
across every board. The client treats `<topic_prefix>/<node_id>/...` and
`<topic_prefix>/<local_id>/...` as the same address:

- Command topics (`tts/set`, `action/run`, `trigger/run`) are subscribed under
  **both** ids — a command published to either is handled identically.
- Outgoing publishes (`state`, `command`) go out under **both** ids too.

This lets a bridge/automation template hardcoded to `<topic_prefix>/arduino/...`
keep working unmodified even when `node_id` is set to something board-specific
(e.g. `galileo`). If `local_id` equals `node_id`, nothing is duplicated.

---

## Testing from the CLI

Two Taskfile helpers wrap `mosquitto_pub`/`mosquitto_sub` for quick manual testing — both resolve `mqtt.host`/`port`/`topic_prefix`/`node_id` from `conf/config.yaml` and print the exact `mosquitto_pub` command they run:

```bash
task mqtt:test-tts -- "il sistema funziona"   # speak arbitrary text via tts/set
task mqtt:trigger -- "chiama assistenza"      # fire a configured trigger via trigger/run
```

Equivalent raw commands (assuming `topic_prefix: alexa`, `node_id: living_room`):

```bash
mosquitto_pub -h <broker_host> -t "alexa/living_room/tts/set" -m "il sistema funziona"
mosquitto_pub -h <broker_host> -t "alexa/living_room/trigger/run" -m "chiama assistenza"
```

If a published command produces no audio, the broker side is rarely the problem
— check the daemon log first: `Received MQTT message on …/tts/set` followed by
`TTS (Piper/…)` and then **no** `TTS playback:` line means the audio device is
wedged, not MQTT (see "Small paplay Buffers Wedge the USB Playback PCM" in
AGENTS.md).

## Action Type

Use `mqtt_publish` in triggers:

```yaml
triggers:
  - commands: ["accendi la luce"]
    actions:
      - type: mqtt_publish
        topic: home/light/set
        payload: "ON"
        retain: false
```

## Automation Example (HA)

```yaml
alias: "Voice Control: Kitchen Lights"
trigger:
  - platform: mqtt
    topic: "alexa/living_room/command"
condition:
  - condition: template
    value_template: "{{ 'cucina' in trigger.payload_json.text }}"
action:
  - service: light.toggle
    target:
      entity_id: light.kitchen
```

---

## Central Hub (mosquitto bridge to the master broker)

The board runs its own anonymous broker on `1883`; the daemon only ever talks to
that local one. A mosquitto **bridge** links it to the central master over TLS,
so the hub can reach the board without exposing anything on the LAN.

Config lives in two files:

| File | Contents |
|---|---|
| `setup/mosquitto-serena.conf` | local listener, `queue_qos0_messages` — committed, symlinked/copied to `/etc/mosquitto/conf.d/serena.conf` |
| `setup/mosquitto-bridge.conf.template` | the whole `connection` block and topic rules — committed **without** credentials |

`task mqtt:bridge-setup` renders the template with `mqtt.bridge_username` /
`mqtt.bridge_password` from `conf/secrets.yaml` (git-ignored) into
`/etc/mosquitto/conf.d/serena-bridge.conf` (owner `mosquitto`, mode 640) and
restarts the broker.

The credentials cannot be split out of that file: a mosquitto **password file**
authenticates clients connecting *to* a broker, not what a bridge presents to a
remote one, and mosquitto tracks the current bridge per config file — putting
just `username`/`password` in a separate `conf.d` drop-in fails to start with
`Error: Invalid bridge configuration`. Hence the rendered-template approach.

### Topic mapping

The two directions deliberately use **different remote namespaces**:

| Direction | Local topic | Topic on the master |
|---|---|---|
| out (QoS 0) | `serena/arduino/state`, `serena/arduino/command`, … | `hub/serena/arduino/…` |
| in (QoS 0) | `serena/arduino/tts/set`, `action/run`, `trigger/run` | `cmd/serena/arduino/…` |

The reason is loop safety. The outbound rule forwards every local `serena/#`
message up, so anything republished locally by the inbound rule is a candidate
for being sent straight back to the master. In practice mosquitto does not echo a
message back onto the bridge it arrived on — an inbound
`cmd/serena/arduino/trigger/run` was observed *not* reappearing as
`hub/serena/arduino/trigger/run` — but keeping the two directions in separate
remote namespaces means correctness does not depend on that behaviour at all: a
message the board publishes can never match the topic the board subscribes to.
Put commands and telemetry in one shared namespace and a single bridge-loop
regression makes the board speak forever.

Inbound stays at QoS 0 on purpose, so a command queued during an outage is never
replayed (a stale TTS request or action firing the moment the link returns).

Local topics must match `mqtt.topic_prefix` / `mqtt.local_id` from
`conf/config.yaml` — the template's prefixes are `serena/arduino/`, matching
the `local_id` default. Since the client mirrors every topic across `node_id`
and `local_id` (see "`node_id` vs `local_id`" above), the template needs no
changes even when `node_id` differs per board — only change `topic_prefix` /
`local_id` if you deviate from their defaults.

### Speaking from the hub

```bash
mosquitto_pub -h serena.csgalileo.org -p 8883 \
  --cafile /etc/ssl/certs/ca-certificates.crt \
  -u <bridge_user> -P <bridge_pass> \
  -t cmd/serena/arduino/tts/set -m "il sistema funziona perfettamente"
```

Same for the other two inbound topics — `cmd/serena/arduino/trigger/run`
(payload = a trigger phrase, e.g. `che ore sono`) and
`cmd/serena/arduino/action/run` (payload = an action JSON object).

Directly on the board, without the hub:

```bash
mosquitto_pub -t serena/arduino/tts/set -m "il sistema funziona perfettamente"
```

Watch what the board sends up (everything under its hub namespace):

```bash
mosquitto_sub -h serena.csgalileo.org -p 8883 \
  --cafile /etc/ssl/certs/ca-certificates.crt \
  -u <bridge_user> -P <bridge_pass> -v -t 'hub/serena/#'
```

### Operating notes

- **Check the link**: `ss -tn | grep 8883` shows the established bridge
  connection; TLS/auth failures appear in `sudo journalctl -u mosquitto`.
- **Connect by hostname, never IP**: the master's Let's Encrypt cert has no IP
  SAN, so an IP address fails hostname verification.
- **After changing any `topic` rule**, wipe the remote session once. With
  `cleansession false` the master *keeps* the old subscriptions and adds the new
  ones, which silently defeats the in/out split (an obsolete
  `serena/living_room/# both 0` rule once delivered every topic twice):

  ```bash
  sed -i 's/^cleansession false/cleansession true/' setup/mosquitto-bridge.conf.template
  task mqtt:bridge-setup      # connects clean, master drops the old subscriptions
  sed -i 's/^cleansession true/cleansession false/' setup/mosquitto-bridge.conf.template
  task mqtt:bridge-setup
  ```

- **Additional boards** need a unique `remote_clientid` *and* a unique
  `node_id` (leave `local_id` at its `arduino` default on every board — the
  bridge template's hardcoded `serena/arduino/...` local topics keep matching
  without per-board edits): the default client id derives from the hostname,
  which is `2q` on every stock Arduino Uno Q, and two boards sharing it repeatedly kick each
  other off the master.
- `queue_qos0_messages true` in the local config is what lets the bridge buffer
  anything at all: the daemon publishes at QoS 0 and MQTT delivers at
  `min(publish QoS, subscription QoS)`, so a QoS 1 bridge topic alone queues
  nothing. Measured across a master outage: 0/5 messages survived without it,
  5/5 with it.
