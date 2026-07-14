## ADDED Requirements

### Requirement: Document all config keys with defaults
La documentazione SHALL elencare OGNI chiave di configurazione in `conf/config.yaml` con il relativo valore di default evidenziato (grassetto).

#### Scenario: Wake words documented
- **WHEN** un utente cerca come configurare wake words
- **THEN** trova `wake_words:` come flat list di stringhe, non più formato a gruppi con `word:`/`aliases:`

#### Scenario: Recognition section complete
- **WHEN** un utente cerca `recognition.*`
- **THEN** trova tutte le chiavi: `wake_window: **8.0**`, `wake_tone: **wake**`, `call_tone: **true**`, `matching_algorithm: **token_sort_ratio**`, `matching_threshold: **75.0**`, `min_word_overlap: **0.0**`, `reply_matching_algorithm: **levenshtein**`, `reply_matching_threshold: **80.0**`, `follow_up: **false**`, `follow_up_timeout: **4.0**`, `follow_up_max_turns: **5**`, `follow_up_tone: **info**`, `post_dispatch_cooldown_ms: **800**`, `min_cmd_words: **1**`, `dispatch_timeout: **90.0**`

#### Scenario: STT section complete
- **WHEN** un utente cerca `stt.*`
- **THEN** trova: `backend: **vosk**`, `model_path`, `num_threads: **2**`, `vad_silence_ms: **900**`, `rms_threshold: **0.02**`, `adaptive_rms: **true**`, `adaptive_rms_margin: **0.01**`, `min_speech_ms: **200**`, `wake_match_threshold: **0.5**`, `mono_capture: **false**`, `capture_backend: **parec**`

#### Scenario: Audio section complete
- **WHEN** un utente cerca `audio.*`
- **THEN** trova: `card_name`, `input_device`, `output_device`, `output_volume: **0.5**`, `input_gain: **1.0**`, `post_playback_ms: **100**`, `tone_preroll_ms: **50**`, `sample_rates.usb: **48000**`, `sample_rates.bluetooth: **16000**`, `sample_rates.internal: **48000**`, `webrtc.agc: **true**`, `webrtc.aec: **true**`, `webrtc.noise_suppression: **true**`, `webrtc.high_pass_filter: **true**`, `gstreamer.source: **pulsesrc**`, `gstreamer.noise_suppression: **true**`, `gstreamer.noise_suppression_level: **2**`, `gstreamer.agc: **true**`, `gstreamer.agc_target_level_dbfs: **-3**`, `gstreamer.agc_compression_gain_db: **9**`, `gstreamer.high_pass_filter: **true**`, `gstreamer.compressor: **false**`, `gstreamer.compressor_threshold: **0.1**`, `gstreamer.compressor_ratio: **3.0**`, `gstreamer.profiles`

#### Scenario: LLM section complete
- **WHEN** un utente cerca `llm.*`
- **THEN** trova: `backend: **ollama**` (anche `openai`), `host` (in secrets.yaml), `api_key`, `model: **ssfdre38/gemma4-nano**`, `context_turns: **10**`, `context_window_secs: **60**`, `fallback_on_no_match: **false**`, `learn_commands: **true**`, `system_prompt`, `request_timeout: **60.0**`, `exit_phrases`

#### Scenario: Display, Web, System, Actions sections complete
- **WHEN** un utente cerca `display.*`, `web.*`, `system.*`, `actions.*`
- **THEN** trova documentati: `display.enabled: **false**`, `display.backend: **auto**`, `display.transport: **unix**`, `display.matrix_brightness: **50**`, `display.led_brightness: **50**`, `web.port: **8080**`, `web.cpu_limit: **4**`, `web.history_file: **conf/history.jsonl**`, `system.reconnect_delay: **5**`, `system.config_poll_interval: **2**`, `system.empty_room_timeout: **0**`, `system.wait_for_participant: **true**`, `system.answer_timeout: **60**`, `actions.dir: **conf/actions**`, `actions.learn_file: **conf/actions/learned.yaml**`, `actions.dump_triggers_dir`

### Requirement: Document all action types
La documentazione SHALL elencare TUTTE le action type con parametri obbligatori e opzionali.

#### Scenario: Action types table present
- **WHEN** un utente cerca quali action type sono disponibili
- **THEN** trova una tabella completa con: `log`, `telegram`, `livekit_join`, `say`, `ask`, `tone`, `set_volume`, `set_volume_from_transcript`, `shell`, `mqtt_publish`, `llm_chat`, `llm_learn`, `meteo`, `stop_listening`, `start_listening`, `system_info`, `restart`, `calibrate_input_gain`, `record_and_playback`, `set_audio_profile`

### Requirement: Document CLI and task commands
La documentazione SHALL elencare tutti i comandi CLI (`alexa-*`, `serena-*`) e tutti i comandi task.

#### Scenario: CLI table present
- **WHEN** un utente cerca i comandi disponibili
- **THEN** trova: `alexa-client`, `serena`, `alexa-audio`, `alexa-devices`, `serena-test`, `alexa-setup`, `alexa-audio-setup`, `alexa-audio-doctor`, `alexa-wake-eval`, `alexa-record`, `serena-stt`

#### Scenario: Task table present
- **WHEN** un utente cerca i comandi task
- **THEN** trova: `test`, `test-stt-e2e`, `eval`, `lint`, `format`, `fix`, `run`, `start`, `release:patch`, `release:minor`, `release:major`, `release:rollback`, `setup:gstreamer`, `setup`, `audio:setup`, `audio:restart`, `audio:status`, `audio:doctor`, `audio:test`, `stt:analyze-dumps`, `display:compile`, `display:test`, `display:setup`, `display:flash`, `clean`
