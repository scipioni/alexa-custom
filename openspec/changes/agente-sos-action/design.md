## Context

The project runs on an Arduino Uno Q (Snapdragon 801, aarch64, Debian 13). It is a headless voice assistant using PipeWire audio, LiveKit for real-time voice, and local STT/TTS for wake-word and trigger recognition.

Currently "aiuto agente" triggers `agent_session` which spawns `agent.py` as a local subprocess and opens a browser tab. Neither is appropriate for a headless appliance. The user needs a cloud-hosted emergency AI agent (Agente SOS) that joins the same LiveKit room on demand.

Audio constraints are well-documented: PortAudio has no PipeWire backend on this board, `parec` is used for capture, `pw-play` for playback, and `pulsectl` for routing with PCM reset workarounds.

## Goals / Non-Goals

**Goals:**
- "aiuto agente" makes the Arduino device join the LiveKit room and signal the cloud agent via MQTT
- Cloud Agente SOS joins the room, greets the user, assesses safety
- If unsafe: outbound phone call (Twilio) + notification (Telegram)
- If safe: agent says goodbye and leaves
- Zero change to the existing LiveKit connection infrastructure
- Minimal change to Arduino-side Python code

**Non-Goals:**
- No changes to `agent.py` or the local agent subprocess model
- No changes to the audio pipeline (capture/playback/routing)
- No changes to the wake word detection or STT pipeline on the Arduino
- No persistence/state storage for SOS sessions (stateless per-call)

## Decisions

### 1. MQTT-based signaling (Arduino → Cloud)
**Why**: MQTT already exists in the project (`aiomqtt`, Home Assistant discovery, Telegram integration). Adding a new signaling channel (webhook, REST API) would add unnecessary infrastructure. The Arduino already publishes MQTT messages.

**Topic**: `sos/request` with payload `{"room": "<room_name>", "timestamp": <unix>}`

### 2. Cloud agent uses the same STT/TTS/LLM stack as `agent.py`
**Why**: The current `agent.py` already has a working Vosk → Groq LLM → Piper TTS pipeline for LiveKit rooms. The cloud agent should reuse this pattern. The difference is it runs on the cloud VM instead of the Arduino, and it subscribes to MQTT instead of being spawned as a subprocess.

### 3. Twilio for outbound calls
**Why**: Industry standard, Python SDK, supports both voice calls and SMS. The call goes to a pre-configured emergency contact number.

### 4. Telegram for notifications
**Why**: Already integrated in the project. The Arduino-side Telegram client can send the notification, or the cloud agent can do it directly. Decision: cloud agent sends notifications directly to avoid coupling.

### 5. All Twilio credentials and phone numbers live in environment variables
**Why**: Follows existing pattern (`LIVEKIT_API_KEY`, `GROQ_API_KEY`, etc.). No config file changes for secrets.

## Risks / Trade-offs

- **[Risk] MQTT broker unreachable**: If the MQTT broker is down, the SOS signal never reaches the cloud agent. *Mitigation*: the Arduino can retry MQTT publish and fall back to a direct webhook if configured.
- **[Risk] Cloud agent fails to join room**: If the cloud VM is down or LiveKit is unreachable, the user gets no response. *Mitigation*: the Arduino plays a local TTS fallback ("Mi dispiace, il servizio di emergenza non è disponibile").
- **[Risk] Twilio call fails**: If the outbound call fails (busy, disconnected, no credit). *Mitigation*: retry logic + Telegram notification as secondary channel.
- **[Trade-off] Same LiveKit room**: Using the same room for SOS and normal calls could cause audio conflicts. *Mitigation*: the Agente SOS only joins when signaled, and leaves after the conversation ends.
- **[Trade-off] Voice-only conversation**: The agent relies entirely on voice — no UI feedback. *Risk*: user might not understand they're being addressed by an AI. *Mitigation*: clear greeting ("Sono l'assistente di emergenza").
