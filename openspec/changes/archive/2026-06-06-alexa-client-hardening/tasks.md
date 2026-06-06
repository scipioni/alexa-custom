## 1. Config Schema — New Fields

- [x] 1.1 Add `audio_card_name: str = "NewPie"` to `ActionsConfig` in `config.py`
- [x] 1.2 Add `audio_sample_rates: dict = {"usb": 48000, "bluetooth": 16000, "internal": 48000}` to `ActionsConfig`
- [x] 1.3 Add `audio_post_playback_ms: int = 100`, `audio_tone_preroll_ms: int = 300`, `audio_mic_gain: int = 300` to `ActionsConfig`
- [x] 1.4 Add `reconnect_delay: int = 5` and `mqtt_queue_max: int = 200` to `ActionsConfig`
- [x] 1.5 Add `stt_vad_silence_ms: int = 700`, `stt_stage1_vad_silence_ms: int = 500`, `stt_stage1_rms_threshold: float = 0.02` to `ActionsConfig`
- [x] 1.6 Add `config_poll_interval: int = 2` to `ActionsConfig`
- [x] 1.7 Parse all new optional fields in `_parse_actions_config()` with their defaults
- [x] 1.8 Update `config.yaml.example` with all new fields and comments

## 2. Audio Module — Config-Driven Constants

- [x] 2.1 Add `configure(cfg: ActionsConfig)` function to `audio.py` that updates `_POST_PLAYBACK_MS`, `_TONE_PREROLL_MS`, `_SAMPLERATE`, and the default card name from config
- [x] 2.2 Replace hardcoded `"NewPie"` default in `find_alexa_card()`, `set_pipewire_defaults()`, and `AudioWatcher` with the module-level configurable default (set by `configure()`)
- [x] 2.3 Replace hardcoded `pactl 300%` in `setup_audio()` with the configured `audio_mic_gain` value
- [x] 2.4 Call `audio.configure(config)` from `_async_main()` after initial config load and after each successful hot-reload

## 3. STT Module — Config-Driven Thresholds

- [x] 3.1 Pass `vad_silence_ms`, `stage1_vad_silence_ms`, and `stage1_rms_threshold` as explicit parameters to `_recognition_loop()` and `capture_transcript()` (sourced from config)
- [x] 3.2 Keep module-level env-var globals as fallback defaults; env-var value overrides config value when both are set
- [x] 3.3 Call STT functions with config-derived threshold values from `client.py`

## 4. TTS Module — Validate Voice at Init

- [x] 4.1 In `init_engine()`, check `voice_path.exists()` before attempting `PiperVoice.load()`
- [x] 4.2 Wrap `PiperVoice.load()` in a try/except inside `init_engine()`; on failure log the error and fall back to `PicoTTS` instead of raising

## 5. MQTT Module — Bounded Queue and Offline Publish

- [x] 5.1 Replace `asyncio.Queue()` with `asyncio.Queue(maxsize=cfg.mqtt_queue_max)` in `MQTTClient.__init__()`
- [x] 5.2 In `publish()` / `publish_threadsafe()`, catch `QueueFull`; on overflow drop the oldest item with `get_nowait()`, log a warning, then retry `put_nowait()`
- [x] 5.3 Add `publish_offline()` async method to `MQTTClient` that publishes the offline/unavailable state payload and calls `disconnect()` with a 500 ms timeout
- [x] 5.4 Pass `mqtt_queue_max` from config when constructing `MQTTClient` in `client.py`

## 6. ConfigManager — Error Callback and Poll Interval

- [x] 6.1 Add `set_error_callback(fn: Callable[[str], None] | None)` method to `ConfigManager`
- [x] 6.2 In the reload error path of `_poll_loop()`, call `self._on_config_error(message)` if set, after retaining the previous config
- [x] 6.3 Read `config_poll_interval` from the loaded config and use it for the watcher sleep interval (default 2 seconds)

## 7. Graceful Shutdown

- [x] 7.1 Add `async def _graceful_shutdown(stt_stop, mqtt_client, livekit_manager)` in `client.py` implementing the ordered teardown: STT stop → MQTT offline → LiveKit leave → 300 ms drain → `os.execv()`
- [x] 7.2 Create a `shutdown_callback` closure in `_async_main()` that calls `_graceful_shutdown()` with the live references
- [x] 7.3 Pass `shutdown_callback` to `ConfigManager` and replace the direct `os.execv()` call in the source watcher with `asyncio.create_task(shutdown_callback())`
- [x] 7.4 Pass `shutdown_callback` to `WebServer` and replace the direct `os.execv()` call in `_handle_control()` with `asyncio.create_task(shutdown_callback())`

## 8. Config Error Feedback — TTS on Parse Failure

- [x] 8.1 In `_async_main()`, after TTS engine is initialised, register an `on_config_error` callback on `ConfigManager` that calls `tts.get_engine().say("Errore di configurazione")` in a `threading.Thread` (daemon=True, non-blocking)
- [x] 8.2 Ensure the callback catches all exceptions (TTS failure must not propagate to the watcher loop)

## 9. Integration and Testing

- [x] 9.1 Run `task lint` and resolve any type or style errors introduced by the new fields and function signatures
- [x] 9.2 Run `task test` and confirm all existing tests pass
- [ ] 9.3 Manually verify: start daemon, edit `config.yaml` with a syntax error, confirm spoken error plays and previous config is retained
- [ ] 9.4 Manually verify: change a source file, confirm MQTT offline is published and LiveKit leaves before process restarts
- [ ] 9.5 Manually verify: change `audio_card_name` in config, confirm device search uses the new name
