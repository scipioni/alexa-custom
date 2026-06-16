## Why

When a user says "aiuto agente" the current system spawns a local AI agent subprocess on the Arduino and opens a browser tab — neither appropriate for a headless voice-only appliance. The user needs a hands-free emergency assistant: the device (Serena) should connect to a LiveKit room where a cloud-hosted Agente SOS joins on demand. If the user is unsafe, the agent must call for help (phone call + notification).

## What Changes

- **Trigger change**: "aiuto agente" switches from `agent_session` (local subprocess + browser) to a new flow: LiveKit room join + MQTT signal
- **New action type** or modified trigger wiring: the device joins the fixed `LIVEKIT_ROOM` on "aiuto agente", publishes an MQTT SOS signal
- **New cloud-side component**: Agente SOS — a standalone service running on a cloud VM that:
  - Subscribes to an MQTT topic for SOS requests
  - Joins the LiveKit room on signal
  - Initiates a voice conversation ("Tutto bene? Hai bisogno di aiuto?")
  - If user needs help: places a phone call (Twilio) + sends notification (Telegram)
  - If user is fine: says goodbye and leaves the room
- **Existing `livekit_join` path reused**: no changes needed to the core LiveKit connection mechanism
- **No changes to `agent.py`**: the local agent stays for potential future use but the SOS path bypasses it

## Capabilities

### New Capabilities
- `sos-agent`: Cloud-hosted emergency AI agent that joins LiveKit rooms on MQTT signal, converses with user, and initiates help calls
- `sos-trigger`: Arduino-side action wiring that publishes an MQTT SOS signal on "aiuto agente" and connects the device to the LiveKit room

### Modified Capabilities
- *None* — no existing capability changes at the spec level

## Impact

- `conf/actions/system.yaml`: change "aiuto agente" trigger from `agent_session` to the new SOS action
- `alexa_custom/actions.py`: register a new action or modify trigger dispatch for the SOS flow
- `alexa_custom/client.py`: minimal — the `livekit_join` path already exists
- **New package**: `agente_sos/` — cloud-side service (can live in this repo or a separate one)
- **New dependency**: `twilio` for outbound phone calls (cloud side)
- **New config**: MQTT topic for SOS signaling, SOS phone number, Telegram chat ID
