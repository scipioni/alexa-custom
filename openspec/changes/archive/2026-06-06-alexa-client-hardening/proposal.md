## Why

The alexa-client daemon has accumulated hardcoded values, silent failures, and abrupt restarts that make it fragile in production: device names, STT thresholds, timing constants, and audio rates are baked into code rather than config; `os.execv()` restarts kill threads without cleanup; Piper voices fail silently at first use; the MQTT outgoing queue is unbounded; and config parse errors are invisible on a headless device. This change makes the daemon configurable, observable, and resilient without adding new runtime dependencies.

## What Changes

- Move `audio_card_name`, STT RMS/VAD/silence thresholds, audio sample rates per device type, mic gain, config poll interval, reconnect delay, post-playback delay, and tone preroll into `config.yaml` with backward-compatible defaults
- Graceful shutdown sequence before `os.execv()` restarts: MQTT publishes `offline` LWT, LiveKit leaves the room, STT thread flushes and stops — then exec
- Validate Piper voice file exists and is loadable at `init_engine()` time; raise `ConfigError` immediately rather than deferring failure to first `say()`
- Bound the MQTT outgoing queue with a configurable `mqtt_queue_max` (default 200); drop oldest on overflow and log a warning
- When `config_manager` catches a `ConfigError` on hot-reload, play a spoken error via TTS (e.g. "Errore di configurazione") and log the message; retain the previous config

## Capabilities

### New Capabilities
- `config-hardening`: Extended `config.yaml` knobs covering audio device name, STT thresholds, timing constants, sample rates, and MQTT queue limit
- `graceful-shutdown`: Ordered teardown of MQTT, LiveKit, and STT before process restart
- `config-error-feedback`: Audible/spoken notification when a hot-reloaded config fails to parse

### Modified Capabilities
- `yaml-config`: New optional fields added to the config schema (backward-compatible)
- `mqtt-integration`: Bounded outgoing queue; clean offline publish on shutdown
- `text-to-speech`: Voice validated at init, not deferred to first call
- `audio-management`: `audio_card_name` sourced from config, not hardcoded

## Impact

- `alexa_custom/config.py` — new optional fields, updated defaults
- `alexa_custom/config_manager.py` — error feedback callback, graceful shutdown hook
- `alexa_custom/audio.py` — `audio_card_name` from config; timing constants from config
- `alexa_custom/stt.py` — STT thresholds and chunk size from config
- `alexa_custom/tts.py` — validate voice at `init_engine()`
- `alexa_custom/mqtt.py` — bounded queue, offline publish on shutdown
- `alexa_custom/client.py` — orchestrate graceful shutdown before `os.execv()`
- `config.yaml.example` — document all new fields
- No new runtime dependencies
