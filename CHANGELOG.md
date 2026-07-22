# Changelog

## [0.4.1] - 2026-07-22

### Added
- add trigger/run topic to fire configured triggers by phrase

### Fixed
- recognize short "sì"/"no" ask replies on sherpa-onnx backend
- stop leaking sherpa-onnx OnlineStream objects each utterance
- explicitly bind mosquitto listener to 0.0.0.0
- serialize MQTT-triggered actions with the recognition loop's own thread
- wire up MQTT command dispatch and fix aiomqtt subscriber crash
- final back 3mm and front 5mm
- handle curated and missing unreleased sections in changelog


## 0.4.0 - 2026-07-14

### Added
- **Web configuration panel** — manage wake words, recognition thresholds, STT/TTS backends, and audio settings from the browser dashboard at `/config`. Changes are validated, preserve YAML formatting via `ruamel.yaml`, and trigger hot-reload immediately.
  - `GET /api/config` — fetch current configuration as JSON
  - `POST /api/config` — partial configuration updates
  - `PUT /api/config` — full configuration replace
  - `GET /api/config/defaults` — factory default values
- **Wake word management UI** — add/remove individual wake words from the dashboard
- **Client-side and server-side validation** — inputs validated before save; invalid values show toast errors with highlighted fields
- **File locking** — `fcntl.flock` prevents concurrent edit conflicts on `config.yaml`
- **Atomic writes** — temporary file + `Path.replace()` prevents corruption on failed writes
- **GStreamer capture backend** — selectable via `stt.capture_backend: gstreamer`. Uses `pulsesrc` + `webrtcdsp` (noise suppression, AGC, high-pass) + `audiodynamic` (compressor). Native C++ audio processing before STT.
- **OpenAI-compatible LLM backend** — `llm.backend: openai` supported alongside `ollama`. API key from `secrets.yaml`.
- **Capture profiles** — per-backend tuning for sample rate, format, channels, and VAD thresholds via `audio.profiles`. STT can override via `stt.capture_profile`.
- **`call_tone` action type** — plays a configurable ringtone during LiveKit calls.
- **RMS threshold profile overrides** — per-profile `rms_threshold` for different backends.
- **`serena-stt` CLI** — standalone STT mode: capture + transcribe only, for testing.
- **Display feedback** — LED matrix/OLED/GPIO via `display` config section. Animated icons (listening, thinking, success, error).
- **Follow-up mode** — re-open command window after match for chained commands (`recognition.follow_up`, `follow_up_timeout`, `follow_up_max_turns`).
- **Sleeping mode** — low-power STT state after inactivity; relaxed wake threshold.
- **`task audio:doctor`** — comprehensive audio invariant check for NewPie.
- **`task test-stt-e2e`** — end-to-end STT test using Piper-synthesised speech.
- **`task release:rollback`** — rollback last version bump.
- **sherpa-onnx STT backend (opt-in)** — Kroko Zipformer streaming transducer with Silero VAD gate via `stt.backend: sherpa-onnx`; `serena-setup --sherpa-onnx-model` downloads models.
- **Fast-VAD endpointing** — early endpoint (`stt.fast_vad_ms`) when the partial transcript already fully matches a wake word or trigger (~500 ms lower perceived latency); isolated-keyword wake matching; TTS LRU cache for repeated prompts.
- **Device-agnostic USB audio stack** — any USB conference speakerphone is auto-detected with hot-plug recovery (NewPie, Yealink SP92/BT51, EMEET); configurable keep-alive noise stream, disabled by default.
- **Multi-condition microphone calibration** — sweeps hardware gain and GStreamer variants, scoring across all configured conditions with worst-case aggregation.
- **Persistent interaction history cap** — web history bounded to a configurable entry count.

### Changed
- USB autosuspend fix: WirePlumber conf instead of udev rule (`autosuspend_delay_ms=-1`).
- Audio setup: `task audio:setup` installs systemd service + WirePlumber conf instead of udev rules.
- MQTT: published entities changed from Media Player + Voice Assistant to Sensor + Text.
- Display: RouterBridge → UART bridge (`uart_bridge.c` via `/dev/mem`).
- Web dashboard: `/config` panel now validates client-side and server-side, uses `ruamel.yaml` for comment preservation.
- Systemd service renamed from `alexa-custom.service` to `serena.service`.

### Fixed
- pulsectl PCM reset: `_restore_hw_pcm()` called after every pulsectl context close to restore NewPie hardware mixer volume
- Wake/command beep no longer blocks dispatch (~1.3 s lower perceived latency per command); the response TTS queues behind the tone instead of pre-empting it
- WebRTC AGC disabled in the yealink profile (BT51 first-command-after-idle garbling); trigger dump buffer byte-budgeted
- Runtime hardening: MQTT reconnect, hot-reload, LiveKit supervision, STT capture recovery and thread watchdog
- Glob pattern matching bounds the implicit word-gap; wake phonetics match silent-h and looser truncation; short ask-reply phrases match word-level
