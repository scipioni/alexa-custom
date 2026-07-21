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

### 2. HA → Client (Listening)

| Topic | Payload | Effect |
|---|---|---|
| `alexa/<node_id>/tts/set` | `Ciao!` (plain text, not JSON) | Speak via TTS |
| `alexa/<node_id>/action/run` | `{"type": "tone", "params": {"name": "info"}}` | Execute one action directly (bypasses trigger matching — `params` must be nested, unlike YAML's flattened shorthand) |
| `alexa/<node_id>/trigger/run` | `chiama assistenza` (plain text, not JSON) | Run a configured trigger from `conf/actions/user.yaml` by command phrase — matched with the same fuzzy/phonetic logic as a spoken command, so `patterns`/`on_reply`/`on_else`/`tag` all apply exactly as they would for real speech (ignores `with_wake` gating) |

> Note: there is no `config/set` topic — MQTT cannot update runtime config. Config changes go through `conf/config.yaml` / `conf/actions/user.yaml` hot-reload or the web dashboard.

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
