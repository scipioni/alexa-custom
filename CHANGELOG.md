# Changelog

## 0.4.0 (unreleased)

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

### Changed
- USB autosuspend fix: WirePlumber conf instead of udev rule (`autosuspend_delay_ms=-1`).
- Audio setup: `task audio:setup` installs systemd service + WirePlumber conf instead of udev rules.
- MQTT: published entities changed from Media Player + Voice Assistant to Sensor + Text.
- Display: RouterBridge → UART bridge (`uart_bridge.c` via `/dev/mem`).
- Web dashboard: `/config` panel now validates client-side and server-side, uses `ruamel.yaml` for comment preservation.
- Systemd service renamed from `alexa-custom.service` to `serena.service`.

### Fixed
- pulsectl PCM reset: `_restore_hw_pcm()` called after every pulsectl context close to restore NewPie hardware mixer volume
