# Capability: YAML Config

## Purpose
Load, merge, and hot-reload configuration from `config.yaml`, providing environment variable injection and a callback registry for subsystem reloads.

## Requirements

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

### Requirement: Hot-reload watcher
The system SHALL monitor `config.yaml` for modifications using an asyncio-based polling watcher with a configurable interval (default 2 seconds, overridable via `config_poll_interval` in config.yaml). When a file modification is detected, the system SHALL reload the config. If the reload succeeds, all registered reload callbacks SHALL be invoked with the new config. If the reload fails due to a YAML parse error or `ConfigError`, the previous config SHALL remain active; the registered `on_config_error` callback SHALL be invoked with the error message if one is registered; no reload callbacks are invoked on failure.

#### Scenario: Config file edited and saved
- **WHEN** `config.yaml` is written to disk with a new trigger phrase
- **THEN** within two poll intervals the system's active trigger list includes the new phrase

#### Scenario: Malformed YAML on save
- **WHEN** `config.yaml` is overwritten with invalid YAML
- **THEN** the current config remains active, the `on_config_error` callback is invoked, an error is logged, and the system continues operating

#### Scenario: Watcher stopped cleanly
- **WHEN** the daemon receives SIGTERM
- **THEN** the watcher task is cancelled without raising unhandled exceptions

#### Scenario: Custom poll interval respected
- **WHEN** `config.yaml` sets `config_poll_interval: 5`
- **THEN** the watcher polls every 5 seconds instead of the default 2 seconds

### Requirement: ConfigManager callback registry
The system SHALL provide a `ConfigManager` class that holds the current `ActionsConfig`, runs the watcher task, allows subsystems to register reload callbacks, and supports an `on_config_error` callback slot. Reload callbacks SHALL receive the new `ActionsConfig` as their sole argument and SHALL be called sequentially after each successful reload. The `on_config_error` callback SHALL receive the error message string and SHALL be called after each failed reload.

#### Scenario: Subsystem registers reload callback
- **WHEN** a subsystem calls `config_manager.register_reload_callback(fn)`
- **THEN** `fn(new_config)` is called after every subsequent successful reload

#### Scenario: Error callback registered and invoked on failure
- **WHEN** a subsystem calls `config_manager.set_error_callback(fn)` and a subsequent reload fails
- **THEN** `fn(error_message)` is called with the parse error string

#### Scenario: MQTT settings change on reload
- **WHEN** `config.yaml env:` changes `MQTT_HOST` to a different value and the file is saved
- **THEN** the MQTT reload callback disconnects the existing client and connects a new one to the updated host

#### Scenario: Credential values not logged
- **WHEN** a reload applies new values from the `env:` section
- **THEN** log lines reference only the key names, not the values

### Requirement: Optional web section in config.yaml
The system SHALL support an optional top-level `web:` key in `config.yaml`. When present, it SHALL accept the following fields: `port` (integer, default `8080`). These values SHALL be accessible to the web interface module and used by default.

#### Scenario: web.port read from config
- **WHEN** `config.yaml` contains `web: { port: 9090 }`
- **THEN** the HTTP server binds to port 9090 (CLI flag `--web-port` takes precedence if also provided)

#### Scenario: Missing web section uses defaults
- **WHEN** `config.yaml` has no `web:` key
- **THEN** the web interface uses port 8080 by default

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

### Requirement: `LLMConfig` dataclass
The system SHALL parse an `llm:` top-level key in `config.yaml` into a `LLMConfig` dataclass with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | — | Must be `"ollama"` |
| `host` | str | — | Ollama base URL, e.g. `http://192.168.1.10:11434` |
| `model` | str | — | Model name, e.g. `llama3.2` |
| `context_turns` | int | `10` | Max exchange pairs kept in history |
| `context_window_secs` | int | `60` | Seconds of inactivity before history reset |
| `fallback_on_no_match` | bool | `true` | Route unmatched commands to LLM |
| `learn_commands` | bool | `true` | Enable `llm_learn` action type |
| `system_prompt` | str\|None | `None` | Optional system prompt override |
| `request_timeout` | float | `10.0` | HTTP request timeout in seconds |

#### Scenario: Minimal llm block parsed
- **WHEN** `llm: {backend: ollama, host: "http://localhost:11434", model: llama3.2}`
- **THEN** `config.llm.host` equals `"http://localhost:11434"` and all optional fields have defaults

#### Scenario: Invalid backend rejected
- **WHEN** `llm: {backend: openai, host: "...", model: "..."}`
- **THEN** a `ConfigError` is raised indicating only `"ollama"` is supported

