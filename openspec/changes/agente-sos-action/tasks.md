## 1. Arduino: SOS trigger action

- [ ] 1.1 Register new `sos_trigger` action type in `alexa_custom/actions.py` that: plays TTS, calls `livekit_connect_fn`, publishes MQTT SOS signal with room name
- [ ] 1.2 Change `conf/actions/system.yaml` "aiuto agente" from `agent_session` to `sos_trigger`

## 2. Cloud: Agente SOS service scaffold

- [ ] 2.1 Create `agente_sos/` package with entry point, config, logging
- [ ] 2.2 Implement MQTT subscriber on `sos/request` topic
- [ ] 2.3 Implement LiveKit room joiner (JWT token generation, room connect)
- [ ] 2.4 Implement voice pipeline: Vosk STT → Groq LLM → Piper TTS
- [ ] 2.5 Implement safety conversation flow: greet, listen, assess
- [ ] 2.6 Implement Twilio outbound call on help-needed path
- [ ] 2.7 Implement Telegram notification on help-needed path

## 3. Integration & config

- [ ] 3.1 Add environment variables doc for SOS config (`SOS_PHONE_NUMBER`, `TWILIO_*`, etc.)
- [ ] 3.2 Test full end-to-end flow: voice trigger → room join → agent conversation
