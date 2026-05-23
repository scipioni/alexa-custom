## 1. Setup and Dependencies

- [x] 1.1 Add `aiomqtt` to `pyproject.toml` and install dependencies
- [x] 1.2 Add MQTT configuration variables to `.env.example` and load them in `alexa_custom/_env.py`

## 2. Core MQTT Infrastructure

- [x] 2.1 Create `alexa_custom/mqtt.py` with an `MQTTClient` wrapper
- [x] 2.2 Implement the background MQTT loop and reconnection logic
- [x] 2.3 Implement thread-safe message publishing for the STT thread
- [x] 2.4 Implement Home Assistant Discovery payload generation and publishing on connect

## 3. STT and State Integration

- [x] 3.1 Update `stt.py` to publish state changes (`idle`, `listening`, `speaking`, `gated`) to MQTT
- [x] 3.2 Update `stt.py` to publish command transcripts to the MQTT command topic
- [x] 3.3 Ensure the MQTT client is properly initialized and started in `alexa_custom/setup.py`

## 4. Action Dispatch and Remote Control

- [x] 4.1 Add `mqtt_publish` action type to `actions.py`
- [x] 4.2 Implement an MQTT message listener in `mqtt.py` that dispatches received commands to local actions
- [x] 4.3 Update `actions.py` to support external action triggering from the MQTT listener

## 5. Testing and Validation

- [ ] 5.1 Verify MQTT Discovery payloads appear in a broker (e.g., using `mosquitto_sub`)
- [ ] 5.2 Verify Home Assistant automatically detects the new device and entities
- [ ] 5.3 Test end-to-end voice command forwarding to HA
- [ ] 5.4 Test remote-triggered TTS and tones from HA
