## 1. STT Pipeline Documentation

- [ ] 1.1 Riscrivere `docs/stt-simple.md` come riferimento unico del pipeline: architettura a modello singolo, diagramma flusso, capture backend (parec vs GStreamer), trigger matching (pattern glob + fonetico + fuzzy), sleeping mode, follow-up, action ask reply matching, benchmark Vosk
- [ ] 1.2 Riscrivere `docs/stt.md` come panoramica concisa che descrive l'architettura a modello singolo, capture backend, profili audio, sleeping mode e follow-up, con rimando a stt-simple.md per i dettagli

## 2. Configuration Reference

- [ ] 2.1 Riscrivere `docs/configuration.md` con tutte le chiavi di configurazione: ogni chiave con valore di default in grassetto, sezioni per wake_words (flat list), recognition (tutti i campi), stt, tts, audio (con GStreamer, webrtc, profiles), llm (con openai e ollama), mqtt, web (cpu_limit, history_file), display, actions (dump_triggers_dir), system (wait_for_participant, answer_timeout)

## 3. Audio Backend Documentation

- [ ] 3.1 Aggiornare `docs/audio.md` con: AudioWatcher, PCM restore bug e workaround, GStreamer capture profiles con STT overrides, software vs hardware gain, autosuspend fix (systemd service + WirePlumber conf), switch-on-connect rimosso, tone_preroll_ms

## 4. Setup Documentation

- [ ] 4.1 Aggiornare `docs/setup_software.md`: aggiungere dipendenze GStreamer (gstreamer1.0-plugins-bad, python3-gst-1.0, gstreamer1.0-pulseaudio, gstreamer1.0-pipewire), comando `uv pip install -e ".[gstreamer]"`, tabella completa CLI e task
- [ ] 4.2 Aggiornare `docs/setup_hardware.md`: correggere pro-audio → analog-stereo, aggiungere profilo di cattura audio, notes su GStreamer backend

## 5. MQTT, LLM, Troubleshooting

- [ ] 5.1 Aggiornare `docs/mqtt_integration.md`: aggiungere topic `alexa/<node_id>/config/set`, action type `mqtt_publish`, interazione web dashboard ↔ MQTT
- [ ] 5.2 Aggiornare `docs/llm.md`: aggiungere backend openai, api_key, exit_phrases configurabili, LearnWizard, system_prompt per trigger
- [ ] 5.3 Aggiornare `docs/troubleshooting.md`: .env → conf/secrets.yaml, sezione watchdog STT, PCM reset, alexa-audio-doctor

## 6. README and Main Documentation

- [ ] 6.1 Riscrivere `README.md`: diagramma architetturale aggiornato, tabella CLI completa, tabella task completa, feature list aggiornata con display/LLM/web dashboard, dipendenze corrette
- [ ] 6.2 Riscrivere `details.md`: sezioni STT, audio, configurazione, CLI, display, MQTT, web dashboard aggiornate con stato reale del codice

## 7. Changelog

- [ ] 7.1 Aggiornare `CHANGELOG.md`: aggiungere voci per GStreamer profiles, OpenAI LLM, call_tone, RMS threshold profile overrides, serena-stt CLI, display feature, follow-up mode, sleeping mode, web config panel, italian phonetic matching, trigger patterns
