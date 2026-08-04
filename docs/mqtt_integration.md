# MQTT & Home Assistant Integration

The client registers itself with Home Assistant via **MQTT Discovery** on startup. No manual YAML configuration is needed in HA.

## Exposed Entities

- **Status (Sensor)**: `start` (once, when the daemon becomes operative), `idle`, `listening`, `speaking`, `gated` (during calls).
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
- `start`, `idle`, `listening`, `speaking`, `gated` (during calls)

`start` is published exactly once per daemon run, as soon as the STT worker
thread comes up — before the STT model loads or capture starts. The first
real `idle` follows once the recognition loop actually begins listening.

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

`trigger/run` also supports a `command_regex` match, tried first (before the
fuzzy matcher), for exact machine-generated payloads with named capture
groups — e.g. `onvif_sua` publishing `caduta_bagno` on
`hub/2q/trigger/run`/`serena/arduino/trigger/run` matches
`command_regex: "caduta_(?P<stanza>.+)"` and substitutes `<stanza>` → `bagno`
into the matched trigger's action params (e.g. a `say` action's `text`). See
"`command_regex`: capturing values from MQTT trigger/run" in
`docs/configuration.md`.

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
`mqtt.bridge_password` from `conf/secrets.yaml` (git-ignored), and this board's
hostname (`hostname`, overridable with `SERENA_BRIDGE_HOSTNAME=<name>`), into
`/etc/mosquitto/conf.d/serena-bridge.conf` (owner `mosquitto`, mode 640) and
restarts the broker. The hostname substitution means the same committed
template works unmodified on every board — no per-board topic edits.

The credentials cannot be split out of that file: a mosquitto **password file**
authenticates clients connecting *to* a broker, not what a bridge presents to a
remote one, and mosquitto tracks the current bridge per config file — putting
just `username`/`password` in a separate `conf.d` drop-in fails to start with
`Error: Invalid bridge configuration`. Hence the rendered-template approach.

### Topic mapping

The remote namespace root is this board's **hostname** (`2q` on the board this
was verified on — the stock default on every Arduino Uno Q), not the fixed
`arduino` local_id alias. `scripts/render-mqtt-bridge.sh` substitutes the
live `hostname` into the rendered bridge config automatically, so the examples
below use `2q` but any board renders its own value. The two directions
deliberately use **different remote namespaces**:

| Direction | Local topic | Topic on the master |
|---|---|---|
| out (QoS 0) | `serena/<hostname>/state`, `serena/<hostname>/command`, … | `hub/<hostname>/…` |
| in (QoS 0) | `serena/arduino/tts/set`, `action/run`, `trigger/run` | `cmd/serena/<hostname>/…` |

The reason is loop safety. The outbound rule forwards every local
`serena/<hostname>/*` message up, so anything republished locally by the
inbound rule is a candidate for being sent straight back to the master. In
practice mosquitto does not echo a message back onto the bridge it arrived on
— an inbound `cmd/serena/2q/trigger/run` was observed *not* reappearing as
`hub/2q/trigger/run` — but keeping the two directions in separate
remote namespaces means correctness does not depend on that behaviour at all: a
message the board publishes can never match the topic the board subscribes to.
Put commands and telemetry in one shared namespace and a single bridge-loop
regression makes the board speak forever.

Inbound stays at QoS 0 on purpose, so a command queued during an outage is never
replayed (a stale TTS request or action firing the moment the link returns).

Local topics must match `mqtt.topic_prefix` / `mqtt.node_id` from
`conf/config.yaml` — the template's outbound rule and the `hub`/`cmd` remote
prefixes use `@BRIDGE_HOSTNAME@`, filled in with this board's `hostname` at
render time (node_id defaults to hostname too, so they normally already
agree). If you want the remote namespace to use something other than this
board's actual hostname, render with
`SERENA_BRIDGE_HOSTNAME=<name> task mqtt:bridge-setup`.

### Speaking from the hub

```bash
mosquitto_pub -h serena.csgalileo.org -p 8883 \
  --cafile /etc/ssl/certs/ca-certificates.crt \
  -u <bridge_user> -P <bridge_pass> \
  -t cmd/serena/2q/tts/set -m "il sistema funziona perfettamente"
```

Same for the other two inbound topics — `cmd/serena/2q/trigger/run`
(payload = a trigger phrase, e.g. `che ore sono`) and
`cmd/serena/2q/action/run` (payload = an action JSON object). Replace `2q`
with the target board's own hostname.

Directly on the board, without the hub:

```bash
mosquitto_pub -t serena/arduino/tts/set -m "il sistema funziona perfettamente"
```

Watch what the board sends up (everything under its hub namespace):

```bash
mosquitto_sub -h serena.csgalileo.org -p 8883 \
  --cafile /etc/ssl/certs/ca-certificates.crt \
  -u <bridge_user> -P <bridge_pass> -v -t 'hub/2q/#'
```

### Operating notes

- **Check the link**: `ss -tn | grep 8883` shows the established bridge
  connection; TLS/auth failures appear in `sudo journalctl -u mosquitto`.
- **Bridge connected but nothing arrives remotely**: a live TCP connection on
  8883 only proves the TLS/auth handshake succeeded — it says nothing about
  whether the `topic` rules actually match. Confirm with `log_type all` +
  `connection_messages true` in a temporary conf.d drop-in, restart mosquitto,
  and look for `Bridge ... doing local SUBSCRIBE on topic <X>` — `<X>` must be
  the literal topic pattern with no stray characters. **Quoting a non-empty
  local-prefix/remote-prefix breaks the rule**: mosquitto only special-cases
  the exactly-empty pair `""` as "no prefix"; `"serena/2q"` is taken literally,
  quote characters and all, producing a subscription that can never match a
  real topic (`serena/2q/#`) — the rule then silently forwards nothing, with
  no error at startup. Verified on this board: `topic /# out 0 "serena/2q"
  hub/2q` matched nothing until the quotes were removed (`topic /# out 0
  serena/2q hub/2q`). Once fixed, confirm forwarding with `grep "sending
  PUBLISH" /var/log/mosquitto/mosquitto.log` (or subscribe to `hub/#` on the
  remote broker directly).
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
  hostname — the outbound `topic` rule and the `hub`/`cmd` remote prefixes are
  keyed by hostname, and `scripts/render-mqtt-bridge.sh` substitutes it
  automatically on each board (`task mqtt:bridge-setup` needs no per-board
  template edit for this). The client id defaults to hostname too, so if two
  boards share the stock `2q` hostname of a fresh Arduino Uno Q, give each a
  unique hostname (`sudo hostnamectl set-hostname <name>`) before bridging —
  otherwise both the client id collision (repeatedly kicking each other off
  the master) and the remote-namespace collision (`hub/2q/...` from both
  boards) hit at once.
- `queue_qos0_messages true` in the local config is what lets the bridge buffer
  anything at all: the daemon publishes at QoS 0 and MQTT delivers at
  `min(publish QoS, subscription QoS)`, so a QoS 1 bridge topic alone queues
  nothing. Measured across a master outage: 0/5 messages survived without it,
  5/5 with it.
- **If this board also runs onvif_sua** on the same local broker, its bridge
  rule (`topic onvif/# out 0 "" hub/2q`) is NOT part of this template — it was
  added directly to the rendered `/etc/mosquitto/conf.d/serena-bridge.conf`
  and belongs to that project. Re-running `task mqtt:bridge-setup` overwrites
  the whole rendered file from this template and silently drops that rule —
  re-add it (and fix its own prefix-concatenation bug: `hub/2q` needs a
  trailing slash, `hub/2q/`, or it collapses into `hub/2qonvif/#`) after any
  re-render.
