# 🤖 MQTT & Home Assistant Integration

This project transforms your speakerphone into a smart "Media Player" and "Voice Assistant" entity in Home Assistant.

## MQTT Discovery

When the client starts, it automatically registers itself with Home Assistant via **MQTT Discovery**. No manual YAML configuration is needed in HA.

### Exposed Entities
- **Status (Sensor)**: Reports `idle`, `listening`, `speaking`, or `gated` (during calls).
- **Last Command (Sensor)**: Shows the text of the last voice command recognized.
- **Speak Text (Text)**: A text input in HA. Type a message and the speakerphone will say it.

---

## Bidirectional Communication

### 1. Client → Home Assistant (Publishing)
Every time you say a command (e.g., "Galileo, accendi la luce"), the client publishes a JSON payload to `alexa/<node_id>/command`. 
- **Hybrid Model**: If the phrase matches a local trigger in `actions.yaml`, it executes locally. **Regardless**, the transcript is always sent to MQTT so HA can trigger complex automations.

### 2. Home Assistant → Client (Listening)
The client listens on `alexa/<node_id>/action/run` for remote instructions. You can send any valid action type as a JSON payload:

**Example Payload to trigger a chime:**
```json
{
  "type": "tone",
  "params": {"name": "success"}
}
```

**Example Payload to join the LiveKit room:**
```json
{
  "type": "livekit_join"
}
```

---

## Automation Example (Home Assistant)

You can use the forwarded voice command in an HA automation:

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
