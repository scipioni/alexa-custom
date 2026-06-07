## 1. Directory Layout and File Scaffolding

- [x] 1.1 Create `conf/` directory at project root
- [x] 1.2 Create `conf/actions/` sub-directory
- [x] 1.3 Add `conf/secrets.yaml` to `.gitignore`
- [x] 1.4 Write `conf/secrets.yaml.example` with all supported keys and placeholder values
- [x] 1.5 Create `conf/secrets.yaml` from current `config.yaml env:` credentials (LiveKit, Telegram, LLM host)
- [x] 1.6 Create `conf/actions/system.yaml` with: `on_startup` (Sistema pronto), predefined triggers (che ora è, che giorno è, riavvia, chatta con me, impara nuovo comando)
- [x] 1.7 Create `conf/actions/user.yaml` from current `actions.yaml` (drop `on_startup` — it moves to system.yaml)
- [x] 1.8 Remove root-level `config.yaml`, `actions.yaml`, `actions.yaml.example` after new files are verified

## 2. config.py — New Dataclasses

- [x] 2.1 Add `AudioConfig` dataclass: card_name, input_device, output_device, output_volume, input_gain, sample_rates, post_playback_ms, tone_preroll_ms, mic_gain, webrtc (agc, aec, noise_suppression, high_pass_filter)
- [x] 2.2 Add `STTStage1Config` dataclass: backend, model_path, confidence, vad_silence_ms, rms_threshold, min_speech_ms
- [x] 2.3 Add `STTStage2Config` dataclass: backend, model_path
- [x] 2.4 Add `STTConfig` dataclass: vad_silence_ms, stage1: STTStage1Config, stage2: STTStage2Config
- [x] 2.5 Add `TTSConfig` dataclass: backend, voice, preroll_ms (unchanged fields, new wrapper)
- [x] 2.6 Add `RecognitionConfig` dataclass: mode, command_timeout, wake_tone (confidence removed — in STTStage1Config)
- [x] 2.7 Add `MQTTConfig` dataclass: host, port, topic_prefix, node_id, queue_max
- [x] 2.8 Add `WebConfig` dataclass: port
- [x] 2.9 Add `SystemConfig` dataclass: reconnect_delay, config_poll_interval, empty_room_timeout
- [x] 2.10 Add `ActionsDirectoryConfig` dataclass: dir, learn_file
- [x] 2.11 Add `SecretsConfig` dataclass: livekit (url, api_key, api_secret, room), telegram (bot_token, chat_id), llm_host, mqtt (username, password)
- [x] 2.12 Replace all flat fields in `ActionsConfig` with sub-config fields; keep wake_words, triggers, on_startup at top level

## 3. config.py — Parsing Functions

- [x] 3.1 Write `load_secrets(path)` → `SecretsConfig`: parse `conf/secrets.yaml`, apply to `os.environ`, merge `llm.host` stub for later LLM config merge
- [x] 3.2 Write `_parse_audio_config(raw)` → `AudioConfig`
- [x] 3.3 Write `_parse_stt_config(raw)` → `STTConfig` (with stage1/stage2 sub-parsers)
- [x] 3.4 Write `_parse_tts_config(raw)` → `TTSConfig`
- [x] 3.5 Write `_parse_recognition_config(raw)` → `RecognitionConfig`
- [x] 3.6 Write `_parse_mqtt_config(raw)` → `MQTTConfig | None`
- [x] 3.7 Write `_parse_system_config(raw)` → `SystemConfig`
- [x] 3.8 Write `_parse_actions_dir_config(raw)` → `ActionsDirectoryConfig`
- [x] 3.9 Rewrite `_parse_actions_config()` to use all new sub-parsers; raise `ConfigError` if `env:` key is present
- [x] 3.10 Update `load_config()` to load from `conf/config.yaml`; merge `secrets.llm_host` into `LLMConfig` (disable LLM if host missing)
- [x] 3.11 Remove legacy flat key parsing, env-var fallback aliases, and `actions_file` (singular) key support
- [x] 3.12 Remove `load_web_config()` — web port now in `WebConfig` accessed via `config.web.port`

## 4. config.py — Multi-File Action Loading

- [x] 4.1 Write `_load_actions_dir(dir_path, system_file)` → `ActionsData`: load system.yaml first, then glob remaining .yaml alphabetically; skip non-existent files with a warning
- [x] 4.2 In `_load_actions_dir`: read `on_startup` only from the first (system.yaml) file; log debug and ignore `on_startup` in subsequent files
- [x] 4.3 In `_load_actions_dir`: merge `triggers` by concatenation in load order
- [x] 4.4 In `_load_actions_dir`: merge `wake_triggers` per word by concatenation in load order; log debug for unknown wake words
- [x] 4.5 Update `load_config()` to call `_load_actions_dir()` instead of `_parse_actions_file()`
- [x] 4.6 Update `llm_learn` action in `actions.py` to write to `config.actions.learn_file` instead of `config.actions_file`; auto-create file if absent with YAML header comment

## 5. config_manager.py — Directory Watching

- [x] 5.1 Extend the hot-reload watcher to scan `conf/actions/` for mtime changes across all `.yaml` files in addition to `conf/config.yaml`
- [x] 5.2 Ensure `conf/secrets.yaml` is NOT watched (changes require restart)
- [x] 5.3 Update `config_poll_interval` source to use `config.system.config_poll_interval`
- [x] 5.4 Update `actions_file` watch path reference to use `config.actions.dir`

## 6. stt.py — Two-Backend Pipeline

- [x] 6.1 Update `run_stt_worker` to load `stage1_backend = get_stt_backend(config.stt.stage1)` and `stage2_backend = get_stt_backend(config.stt.stage2)` independently at startup
- [x] 6.2 Update backend reload logic to track `(stage1_backend_key, stage2_backend_key)` tuple; reload only the changed backend on config change
- [x] 6.3 Update `_recognition_loop` signature to accept `stage1_backend` and `stage2_backend`; use `stage1_backend` for continuous wake detection, pass `stage2_backend` to `_wake_detected`
- [x] 6.4 Update `_wake_detected` to accept and use `stage2_backend` (passed to `capture_transcript`)
- [x] 6.5 Update `_single_stage_loop` to use `stage2_backend` as the single backend
- [x] 6.6 Move `stt.stage1.confidence` from `_recognition_loop` config access (`config.wake_confidence`) to `config.stt.stage1.confidence`
- [x] 6.7 Move stage-1 VAD params to `config.stt.stage1.*` (vad_silence_ms, rms_threshold, min_speech_ms); remove env-var fallback overrides
- [x] 6.8 Update `capture_transcript` VAD to use `config.stt.vad_silence_ms` (no env-var fallback)
- [x] 6.9 Update `resolve_capture_source` to read `config.audio.input_device` instead of `os.environ.get("INPUT_DEVICE")`

## 7. audio.py, tts.py — Config Attribute Updates

- [x] 7.1 Update `audio.py configure()` to read from `config.audio.*` sub-object (card_name, sample_rates, post_playback_ms, tone_preroll_ms, mic_gain)
- [x] 7.2 Update `set_output_volume` call sites to use `config.audio.output_volume`
- [x] 7.3 Update `set_input_gain` call sites to use `config.audio.input_gain`
- [x] 7.4 Update `AudioWatcher` instantiation to pass `config.audio.output_volume` and `config.audio.input_gain`
- [x] 7.5 Update `tts.py init_engine()` call sites to use `config.tts.backend`, `config.tts.voice`, `config.tts.preroll_ms`
- [x] 7.6 Update WebRTC env vars (MIC_AGC, MIC_AEC etc.) to be set from `config.audio.webrtc.*` by `load_secrets()` or `load_config()`

## 8. client.py, web.py — Attribute Access

- [x] 8.1 Update `client.py` to call `load_secrets()` before `load_config()`; remove references to `env:` section
- [x] 8.2 Update `web.py` to use `config.web.port` instead of `load_web_config()`
- [x] 8.3 Update all `config.stt_backend`, `config.tts_backend`, `config.audio_card_name` etc. references throughout `client.py`, `web.py`, `actions.py` to use sub-config fields
- [x] 8.4 Update `config.reconnect_delay` → `config.system.reconnect_delay`
- [x] 8.5 Update `config.mqtt_queue_max` → `config.mqtt.queue_max` (guard for `config.mqtt is None`)
- [x] 8.6 Update `config.command_timeout` → `config.recognition.command_timeout`
- [x] 8.7 Update `config.wake_tone` → `config.recognition.wake_tone`
- [x] 8.8 Update `config.wake_confidence` → `config.stt.stage1.confidence`

## 9. Taskfile and Setup

- [x] 9.1 Update `Taskfile.yml` `task run` to load from `conf/config.yaml`
- [x] 9.2 Update `Taskfile.yml` `task audio:setup` — remove `wpctl set-volume @DEFAULT_SINK@ 1.0` line (volume now set from config at startup, not forced to 1.0 by setup)
- [x] 9.3 Update `setup/alsa-pcm-unmute.service` if it references config paths
- [x] 9.4 Write `conf/config.yaml` from current root-level `config.yaml` translated to new nested schema
- [x] 9.5 Write `conf/config.yaml.example` covering all supported keys with comments

## 10. Tests

- [x] 10.1 Update all test fixtures that build `ActionsConfig` directly to use new sub-config dataclasses
- [x] 10.2 Add tests for `load_secrets()`: full file, partial file, missing file
- [x] 10.3 Add tests for `_load_actions_dir()`: system-first ordering, on_startup restriction, wake_triggers merge, unknown wake word ignored
- [x] 10.4 Add tests for `_parse_stt_config()`: stage1/stage2 independence, confidence field, vad params
- [x] 10.5 Add test: `env:` key in `conf/config.yaml` raises `ConfigError`
- [x] 10.6 Run `task fix` and confirm all tests pass
