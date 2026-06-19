## Why

La documentazione (README.md, docs/*.md, conf.example/*.yaml) è ferma a uno stato precedente a numerosi refactoring e nuove feature. Descrive un'architettura STT a due stadi con gruppi di wake word e formati di trigger legacy, non menziona il backend GStreamer, i profili di cattura audio, i nuovi comandi CLI (alexa-audio-setup, alexa-audio-doctor, serena-stt), i comandi task, e omette molte chiavi di configurazione con i relativi valori di default. Un nuovo sviluppatore che leggesse la doc oggi ne uscirebbe con un'immagine sbagliata del sistema.

## What Changes

- **docs/stt-simple.md**: riscritta come riferimento unico del pipeline STT — architettura a modello singolo, backend GStreamer vs parec, profili di cattura, trigger matching con pattern glob + fonetica + fuzzy scoring, algoritmo e soglie, direct triggers (with_wake), ask action reply matching, VAD gating, sleeping mode, exit phrases, configurazione completa con default.
- **docs/stt.md**: riscritta come panoramica concisa che rimanda a stt-simple.md per i dettagli. Aggiunte sezioni su GStreamer capture backend, profili audio, sleeping mode, follow-up.
- **docs/configuration.md**: riscritta con tutte le chiavi di configurazione — ogni chiave con valore di default evidenziato. Aggiunte sezioni mancanti: `stt.capture_backend`, `audio.gstreamer.*` (source, noise_suppression, agc, high_pass_filter, compressor, profiles), `audio.webrtc.*`, `recognition.*` (call_tone, follow_up*, matching_algorithm, matching_threshold, min_word_overlap, post_dispatch_cooldown_ms, min_cmd_words, dispatch_timeout), `llm.*` (backend, model, api_key, system_prompt, exit_phrases), `display.*`, `web.*` (cpu_limit, history_file), `actions.*` (dump_triggers_dir), `system.*` (config_poll_interval, answer_timeout). Tabella completa delle action type con tutti i parametri. Tutti i comandi CLI e task.
- **docs/audio.md**: aggiornata con AudioWatcher, GStreamer capture profiles, PCM restore dopo pulsectl, software vs hardware gain, tone_preroll_ms, autosuspend fix (systemd service + WirePlumber conf), nuovo fix per switch-on-connect rimosso, capture profiles con STT overrides.
- **docs/setup_software.md**: aggiunte dipendenze GStreamer (gstreamer1.0-plugins-bad, python3-gst-1.0, gstreamer1.0-pulseaudio, gstreamer1.0-pipewire), `uv pip install -e ".[gstreamer]"`, tutti i comandi CLI alexa-* e serena-*, tutti i comandi task.
- **docs/setup_hardware.md**: corretto `pro-audio` → `analog-stereo` (pro-audio disabilita gli endpoint sulla NewPie). Aggiunto profilo di cattura e considerazioni GStreamer.
- **docs/mqtt_integration.md**: aggiunto topic `alexa/<node_id>/config/set`, action type `mqtt_publish`, interazione web dashboard ↔ MQTT.
- **docs/llm.md**: aggiunto backend `openai`, chiave `api_key`, exit_phrases configurabili, `LearnWizard`, system_prompt per trigger.
- **docs/troubleshooting.md**: aggiornato `.env` → `conf/secrets.yaml`, aggiunta sezione watchdog, PCM reset, alexa-audio-doctor.
- **README.md**: riscritta — diagramma architetturale aggiornato (singolo modello Vosk + GStreamer/parec + AudioWatcher + web dashboard + display + LLM), tabella completa CLI, tabella completa task, feature list aggiornata, dipendenze corrette (openai invece di httpx, no sherpa-onnx).
- **details.md**: riscritta — sezioni STT, audio, configurazione, CLI, display, MQTT, web dashboard aggiornate con lo stato reale del codice.
- **CHANGELOG.md**: aggiunte voci mancanti per GStreamer profiles, OpenAI LLM backend, call_tone, RMS threshold profile overrides, serena-stt CLI, display feature, follow-up mode, sleeping mode, web config panel.

## Capabilities

### New Capabilities
- `stt-pipeline-docs`: Documentazione aggiornata del pipeline STT a modello singolo con GStreamer capture, profili audio, trigger matching moderno
- `config-reference-all`: Riferimento completo di tutte le chiavi di configurazione con valori di default, action types, CLI e task commands
- `audio-backend-docs`: Documentazione aggiornata del backend audio (AudioWatcher, GStreamer, PCM restore, profili)
- `cli-and-task-reference`: Documentazione di tutti i comandi CLI (alexa-*, serena-*) e task
- `changelog-update`: Storico delle modifiche aggiornato fino alla data corrente

### Modified Capabilities
- `single-model-stt`: I requisiti documentativi cambiano perché ora include GStreamer capture backend, profili audio, sleeping mode
- `yaml-config`: I requisiti documentativi cambiano perché ora include tutte le nuove chiavi (gstreamer, display, llm, web history, actions.dump_triggers_dir)
- `audio-management`: La documentazione del sistema audio ora deve coprire AudioWatcher, PCM restore, autosuspend fix
- `web-interface`: Documentazione deve includere cpu_limit, history_file, config panel

## Impact

- File modificati: README.md, CHANGELOG.md, details.md, docs/stt.md, docs/stt-simple.md, docs/configuration.md, docs/audio.md, docs/setup_software.md, docs/setup_hardware.md, docs/mqtt_integration.md, docs/llm.md, docs/troubleshooting.md
- Nessun file di codice modificato
- Nessuna API, dipendenza o sistema modificato
- I conf.example/*.yaml sono già aggiornati e non richiedono modifiche
