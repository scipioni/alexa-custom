## Why

The current `alexa_custom` client lacks a native way to interface with external home automation systems, specifically Home Assistant. While it can send Telegram messages and run shell commands, it cannot publish recognized voice commands for external processing or receive external triggers (like TTS requests) via a standard protocol. Integrating MQTT with Home Assistant Discovery allows the client to become a first-class citizen in a smart home ecosystem, enabling seamless bidirectional communication and advanced automation.

## What Changes

- **MQTT Integration**: Add a persistent background MQTT client to handle communication with a broker.
- **Home Assistant Discovery**: Automatically register the client as a device in Home Assistant with entities for status, TTS, and command forwarding.
- **Voice Command Forwarding**: Always publish recognized voice transcripts to an MQTT topic, allowing Home Assistant to handle intents that aren't matched locally in `actions.yaml`.
- **Remote Action Execution**: Implement an MQTT listener that allows Home Assistant to trigger local client actions such as `say` (TTS), `tone` (chimes), and `livekit_join`.
- **Status Reporting**: Publish the client's current state (e.g., `idle`, `listening`, `speaking`, `gated`) to MQTT for real-time monitoring in Home Assistant.

## Capabilities

### New Capabilities
- `mqtt-integration`: Core MQTT connectivity, discovery registration, and state reporting.
- `home-assistant-integration`: Specific mapping of voice commands and remote actions to Home Assistant entities and topics.

### Modified Capabilities
- `action-dispatch`: Requirements are changing to allow actions to be triggered externally via MQTT, not just via local voice matching.
- `wake-word-detection`: Requirements are changing to include publishing status updates (e.g., "listening") during the detection/command window.

## Impact

- **Dependencies**: New dependency on `aiomqtt` for asynchronous MQTT communication.
- **Configuration**: New environment variables in `.env` for MQTT broker details (`MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`).
- **STT Pipeline**: `stt.py` will be updated to publish transcripts and state changes.
- **Action Dispatcher**: `actions.py` will be updated to handle incoming MQTT commands and support an `mqtt_publish` action type.
