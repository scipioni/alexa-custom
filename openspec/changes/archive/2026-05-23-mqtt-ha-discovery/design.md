## Context

The `alexa_custom` client is a Python-based voice assistant that currently uses Vosk for local STT and wake word detection. It can execute local actions (Telegram, TTS, Shell) based on matching phrases in `actions.yaml`. The goal is to extend this into the MQTT ecosystem to allow bidirectional communication with Home Assistant.

## Goals / Non-Goals

**Goals:**
- Implement a persistent, asynchronous MQTT client using `aiomqtt`.
- Register the device automatically in Home Assistant using MQTT Discovery.
- Forward all voice transcripts to MQTT.
- Allow Home Assistant to trigger local actions (`say`, `tone`, `livekit_join`).
- Support a new local action type `mqtt_publish`.
- Maintain low latency for voice-to-MQTT command forwarding.

**Non-Goals:**
- Implementation of MQTT security (TLS/Auth) is deferred (as requested).
- Multi-room audio synchronization.
- Complex intent parsing locally (deferred to Home Assistant).

## Decisions

### 1. Library Choice: `aiomqtt`
- **Decision**: Use `aiomqtt` (formerly `gmqtt`) for MQTT communication.
- **Rationale**: It is native `asyncio`, which matches the project's existing architecture (LiveKit, STT, etc.).
- **Alternatives**: `paho-mqtt` (requires manual thread management or a complex loop wrapper for `asyncio`).

### 2. MQTT Client Lifecycle
- **Decision**: Start the MQTT client as a background task in the main `asyncio` loop. Provide a thread-safe way for the STT worker thread to publish messages.
- **Rationale**: The STT pipeline runs in a separate daemon thread to ensure low-latency audio capture. The MQTT client needs to live in the main `asyncio` loop to interact with other components.
- **Implementation**: Use `asyncio.run_coroutine_threadsafe` or a thread-safe queue for the STT thread to send data to the MQTT task.

### 3. Home Assistant Discovery Strategy
- **Decision**: Group all entities under a single "Alexa Custom" device identifier based on a unique node ID (defaulting to the hostname or a config value).
- **Entities**:
  - `sensor`: State (`idle`, `listening`, `speaking`, `gated`)
  - `text`: TTS Input (Command topic: `tts/set`)
  - `event`: Voice Command (Topic: `command`)

### 4. Hybrid Action Execution
- **Decision**: The `stt.py` worker will publish the transcript to MQTT immediately upon transcription. It will then continue with local `match_trigger` logic.
- **Rationale**: Ensures HA gets the command as fast as possible, while still allowing local actions (like a "beep" or a "Telegram message") to fire without waiting for HA.

## Risks / Trade-offs

- **Risk**: MQTT connection loss could block the STT worker if not handled carefully.
  - **Mitigation**: Use a non-blocking queue for outgoing MQTT messages; if the broker is down, messages are dropped or queued without blocking the voice loop.
- **Risk**: Race conditions between local actions and HA-triggered actions (e.g., both trying to speak at once).
  - **Mitigation**: Implement a simple lock/gate in the action dispatcher to ensure only one `say` action runs at a time.
