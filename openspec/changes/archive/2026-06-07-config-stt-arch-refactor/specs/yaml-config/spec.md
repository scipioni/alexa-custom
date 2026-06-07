## REMOVED Requirements

### Requirement: Unified config.yaml with env section
**Reason**: Replaced by `conf/config.yaml` with nested blocks and `conf/secrets.yaml` for credentials. The flat `env:` section is removed; credentials are no longer embedded in the main config file.
**Migration**: Move all `env:` credential values to `conf/secrets.yaml`. Rename non-credential env settings (INPUT_DEVICE → `audio.input_device`, OUTPUT_DEVICE → `audio.output_device`, MIC_* → `audio.webrtc.*`).

### Requirement: Backward-compatible fallback to actions.yaml
**Reason**: No migration path is provided — this is a clean-break refactor. The root-level `actions.yaml` and legacy `actions_file:` key are removed.
**Migration**: Move `actions.yaml` to `conf/actions/user.yaml`.

### Requirement: Audio and timing knobs in config.yaml
**Reason**: Replaced by structured `audio:` block in `conf/config.yaml`. Flat `audio_*` top-level keys are removed.
**Migration**: Move all `audio_*` keys into the `audio:` block.

### Requirement: STT thresholds in config.yaml
**Reason**: Replaced by structured `stt:` block with `stage1:` and `stage2:` sub-blocks. Flat `stt_*` top-level keys are removed. Env-var overrides are no longer supported.
**Migration**: Move `stt_vad_silence_ms` → `stt.vad_silence_ms`, `stt_stage1_vad_silence_ms` → `stt.stage1.vad_silence_ms`, `stt_stage1_rms_threshold` → `stt.stage1.rms_threshold`.

## ADDED Requirements

### Requirement: conf/config.yaml with nested subsystem blocks
The system SHALL load configuration from `conf/config.yaml`. The file SHALL use the following top-level blocks, all optional unless noted:

- `wake_words` (required): list of wake word group objects (unchanged schema)
- `recognition:`: mode, command_timeout, wake_tone
- `audio:`: hardware and routing settings
- `stt:`: backend config with `stage1:` and `stage2:` sub-blocks
- `tts:`: backend and voice settings
- `llm:`: Ollama behavior settings (host moved to secrets)
- `mqtt:`: broker connection settings (credentials moved to secrets)
- `web:`: dashboard port
- `system:`: reconnect_delay, config_poll_interval, empty_room_timeout
- `actions:`: dir and learn_file paths

No flat legacy aliases are supported. The `env:` section is not accepted.

#### Scenario: Nested audio block parsed
- **WHEN** `conf/config.yaml` contains `audio: {output_volume: 0.3, card_name: NewPie}`
- **THEN** `config.audio.output_volume` equals `0.3` and `config.audio.card_name` equals `"NewPie"`

#### Scenario: env: section causes ConfigError
- **WHEN** `conf/config.yaml` contains a top-level `env:` key
- **THEN** a `ConfigError` is raised with a message directing the user to `conf/secrets.yaml`

### Requirement: audio: block schema
The `audio:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `card_name` | `"NewPie"` | Substring to identify the audio card |
| `input_device` | `null` | PipeWire source name substring or `"pipewire"` |
| `output_device` | `null` | PipeWire sink name substring or `"pipewire"` |
| `output_volume` | `0.5` | Speaker volume 0.0–1.0 |
| `input_gain` | `1.0` | Microphone gain multiplier |
| `sample_rates.usb` | `48000` | Sample rate for USB audio |
| `sample_rates.bluetooth` | `16000` | Sample rate for Bluetooth audio |
| `sample_rates.internal` | `48000` | Sample rate for internal audio |
| `post_playback_ms` | `100` | STT gate hold after playback ends |
| `tone_preroll_ms` | `300` | Silence before tones/beeps |
| `mic_gain` | `300` | ALSA mic gain percent (used by audio:setup task) |
| `webrtc.agc` | `true` | LiveKit AGC |
| `webrtc.aec` | `true` | LiveKit AEC |
| `webrtc.noise_suppression` | `true` | LiveKit noise suppression |
| `webrtc.high_pass_filter` | `true` | LiveKit high-pass filter |

#### Scenario: input_device and output_device replace env vars
- **WHEN** `audio.input_device: pipewire` and `audio.output_device: pipewire` are set
- **THEN** the STT capture and routing code uses these values instead of `INPUT_DEVICE` / `OUTPUT_DEVICE` env vars

### Requirement: recognition: block schema
The `recognition:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `mode` | `"two-stage"` | `"two-stage"` or `"single-stage"` |
| `command_timeout` | `3.0` | Seconds to listen for command after wake |
| `wake_tone` | `"wake"` | Tone name played on wake detection |

The `confidence` field is removed from this block; it moves to `stt.stage1.confidence`.

#### Scenario: recognition block parsed
- **WHEN** `recognition: {mode: two-stage, command_timeout: 5.0}`
- **THEN** `config.recognition.command_timeout` equals `5.0`

### Requirement: mqtt: block schema
The `mqtt:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `host` | `null` | MQTT broker hostname; null disables MQTT |
| `port` | `1883` | Broker port |
| `topic_prefix` | `"alexa"` | MQTT topic prefix |
| `node_id` | *(hostname)* | Node identifier for MQTT topics |
| `queue_max` | `200` | Max outgoing message queue depth |

MQTT credentials (username, password) come from `conf/secrets.yaml`, not this block.

#### Scenario: MQTT disabled when host absent
- **WHEN** the `mqtt:` block has no `host` field or `mqtt:` is absent entirely
- **THEN** no MQTT connection is attempted and MQTT-related actions are no-ops

### Requirement: system: block schema
The `system:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `reconnect_delay` | `5` | Seconds between LiveKit reconnect attempts |
| `config_poll_interval` | `2` | Hot-reload polling interval in seconds |
| `empty_room_timeout` | `0` | Seconds before disconnecting from empty LiveKit room; 0 = never |

#### Scenario: empty_room_timeout configured
- **WHEN** `system.empty_room_timeout: 30`
- **THEN** the daemon disconnects from LiveKit after 30 seconds with no other participants
