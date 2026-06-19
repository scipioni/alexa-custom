# Capability: YAML Config

## MODIFIED Requirements

### Requirement: conf/config.yaml with nested subsystem blocks

The system SHALL load configuration from `conf/config.yaml`. The file SHALL use the following top-level blocks, all optional unless noted:

- `wake_words` (required): flat list of strings (NOT group objects with `word:`/`aliases:`)
- `recognition:`: wake_window, wake_tone, call_tone, matching_algorithm, matching_threshold, min_word_overlap, reply_matching_algorithm, reply_matching_threshold, follow_up, follow_up_timeout, follow_up_max_turns, follow_up_tone, post_dispatch_cooldown_ms, min_cmd_words, dispatch_timeout
- `audio:`: hardware and routing settings, INCLUDING gstreamer block with profiles AND webrtc block
- `stt:`: flat backend config (NO stage1/stage2 sub-blocks)
- `tts:`: backend and voice settings
- `llm:`: backend (ollama | openai), host, api_key, model, context_turns, context_window_secs, fallback_on_no_match, learn_commands, system_prompt, request_timeout, exit_phrases
- `mqtt:`: broker connection settings (credentials moved to secrets)
- `web:`: port, cpu_limit, history_file
- `system:`: reconnect_delay, config_poll_interval, empty_room_timeout, wait_for_participant, answer_timeout
- `actions:`: dir, learn_file, dump_triggers_dir
- `display:`: enabled, backend, transport, matrix_brightness, led_brightness, i2c_bus, i2c_address, i2c_width, i2c_height

#### Scenario: Flat wake words parsed
- **WHEN** `conf/config.yaml` contains `wake_words: ["ehi serena", "ascolta assistente"]`
- **THEN** `config.wake_words` equals `["ehi serena", "ascolta assistente"]`
- **AND** no `word:`/`aliases:` group parsing is performed

#### Scenario: Legacy group format warns
- **WHEN** `conf/config.yaml` contains `wake_words: [{word: "ehi galileo", aliases: ["hey galileo"]}]`
- **THEN** a deprecation warning is logged directing the user to the flat string format
- **AND** the phrases are still extracted for backward compatibility

#### Scenario: stt.stage1 warns
- **WHEN** `conf/config.yaml` contains `stt: {stage1: {backend: vosk}}`
- **THEN** a deprecation warning is logged: "stt.stage1 is removed — update to flat stt fields"
- **AND** config loading continues with defaults

### Requirement: recognition: block schema

The `recognition:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `wake_window` | `8.0` | Seconds after wake to listen for command |
| `wake_tone` | `"wake"` | Tone on wake: wake, startup, success, error, info, warning, none |
| `call_tone` | `true` | Play tones on call connect/disconnect |
| `matching_algorithm` | `"token_sort_ratio"` | Algorithm for fuzzy matching |
| `matching_threshold` | `75.0` | Similarity threshold 0–100 |
| `min_word_overlap` | `0.0` | Fraction of content words that must appear verbatim |
| `reply_matching_algorithm` | `"levenshtein"` | Algorithm for ask reply matching |
| `reply_matching_threshold` | `80.0` | Similarity threshold for replies 0–100 |
| `follow_up` | `false` | Re-open command window after match without re-waking |
| `follow_up_timeout` | `4.0` | Seconds of silence before follow-up closes |
| `follow_up_max_turns` | `5` | Max consecutive follow-up turns |
| `follow_up_tone` | `"info"` | Chime when follow-up opens |
| `post_dispatch_cooldown_ms` | `800` | Silence listening after dispatch to prevent echo re-trigger |
| `min_cmd_words` | `1` | Minimum word count in command for matching |
| `dispatch_timeout` | `90.0` | Timeout for action dispatch |

`mode`, `command_timeout`, `command_max_timeout`, `partial_matching`, `partial_stability_ms`, `partial_stability_reads` are REMOVED.

#### Scenario: recognition block parsed with new fields
- **WHEN** `recognition: {wake_window: 10.0, call_tone: false, follow_up: true}`
- **THEN** `config.recognition.wake_window` equals `10.0`
- **AND** `config.recognition.call_tone` equals `false`
- **AND** `config.recognition.follow_up` equals `true`

### Requirement: audio: block schema

The `audio:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `card_name` | `null` | Substring to identify audio card |
| `input_device` | `null` | PipeWire source name substring |
| `output_device` | `null` | PipeWire sink name substring |
| `output_volume` | `0.5` | Speaker volume 0.0–1.0 |
| `input_gain` | `1.0` | Microphone gain multiplier (software) |
| `sample_rates.usb` | `48000` | Sample rate for USB audio |
| `sample_rates.bluetooth` | `16000` | Sample rate for Bluetooth audio |
| `sample_rates.internal` | `48000` | Sample rate for internal audio |
| `post_playback_ms` | `100` | STT gate hold after playback ends |
| `tone_preroll_ms` | `50` | Silence before tones/beeps |
| `webrtc.agc` | `true` | LiveKit AGC |
| `webrtc.aec` | `true` | LiveKit AEC |
| `webrtc.noise_suppression` | `true` | LiveKit noise suppression |
| `webrtc.high_pass_filter` | `true` | LiveKit high-pass filter |
| `gstreamer.source` | `"pulsesrc"` | GStreamer audio source: pulsesrc, pipewiresrc |
| `gstreamer.noise_suppression` | `true` | Enable noise suppression in GStreamer pipeline |
| `gstreamer.noise_suppression_level` | `2` | 0=mild 1=moderate 2=high 3=very-high |
| `gstreamer.agc` | `true` | Enable AGC in GStreamer pipeline |
| `gstreamer.agc_target_level_dbfs` | `-3` | AGC target peak level in dBFS |
| `gstreamer.agc_compression_gain_db` | `9` | Max makeup gain by digital AGC |
| `gstreamer.high_pass_filter` | `true` | 80 Hz high-pass filter |
| `gstreamer.compressor` | `false` | Audio dynamic compressor |
| `gstreamer.compressor_threshold` | `0.1` | Compressor threshold 0.0–1.0 |
| `gstreamer.compressor_ratio` | `3.0` | Compression ratio |
| `gstreamer.profiles` | `{}` | Named profiles with GStreamer + STT overrides |

`mic_gain` is REMOVED (replaced by `input_gain`).

#### Scenario: GStreamer block parsed
- **WHEN** `audio.gstreamer.noise_suppression_level: 3` is set
- **THEN** `config.audio.gstreamer.noise_suppression_level` equals `3`

#### Scenario: Profile parsed
- **WHEN** `audio.gstreamer.profiles.sensitive.noise_suppression_level: 2` is set
- **THEN** `config.audio.gstreamer.profiles["sensitive"]["noise_suppression_level"]` equals `2`

### Requirement: LLMConfig dataclass

The system SHALL parse an `llm:` top-level key in `config.yaml` into a `LLMConfig` dataclass with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | — | `"ollama"` or `"openai"` |
| `host` | str | — | Base URL for OpenAI-compatible endpoint |
| `api_key` | str | `""` | API key (also settable in secrets.yaml) |
| `model` | str | — | Model name, e.g. `ssfdre38/gemma4-nano` |
| `context_turns` | int | `10` | Max exchange pairs kept in history |
| `context_window_secs` | int | `60` | Seconds of inactivity before history reset |
| `fallback_on_no_match` | bool | `false` | Route unmatched commands to LLM |
| `learn_commands` | bool | `true` | Enable `llm_learn` action type |
| `system_prompt` | str\|None | `None` | Optional system prompt override |
| `request_timeout` | float | `60.0` | HTTP request timeout in seconds |
| `exit_phrases` | list | `[stop, esci, basta, ...]` | Phrases that exit LLM chat mode |

#### Scenario: openai backend accepted
- **WHEN** `llm: {backend: openai, host: "https://api.openai.com/v1", model: gpt-4o}`
- **THEN** `config.llm.backend` equals `"openai"` without raising ConfigError

### Requirement: display: block schema

The `display:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable visual display feedback |
| `backend` | `"auto"` | auto, bridge, gpio, mock, i2c |
| `transport` | `"unix"` | auto, subprocess, unix, tcp |
| `matrix_brightness` | `50` | LED matrix brightness 0–100 |
| `led_brightness` | `50` | RGB LED brightness 0–100 |
| `i2c_bus` | `1` | I2C bus number |
| `i2c_address` | `0x3C` | I2C device address |
| `i2c_width` | `128` | I2C display width |
| `i2c_height` | `64` | I2C display height |

### Requirement: web: block schema

| Field | Default | Description |
|---|---|---|
| `port` | `8080` | HTTP server port |
| `cpu_limit` | `4` | CPU core count for dashboard display |
| `history_file` | `conf/history.jsonl` | Path to persistent interaction history file |

### Requirement: system: block schema

| Field | Default | Description |
|---|---|---|
| `reconnect_delay` | `5` | Seconds between LiveKit reconnect attempts |
| `config_poll_interval` | `2` | Hot-reload polling interval in seconds |
| `empty_room_timeout` | `0` | Seconds before disconnecting; 0 = never |
| `wait_for_participant` | `true` | Join room silently and wait for remote participant |
| `answer_timeout` | `60` | Seconds to wait for participant before giving up |

### Requirement: actions: block schema

| Field | Default | Description |
|---|---|---|
| `dir` | `conf/actions` | Directory for .yaml action files |
| `learn_file` | `conf/actions/learned.yaml` | File for llm_learn auto-generated triggers |
| `dump_triggers_dir` | `null` | Save pre-trigger audio WAV for debugging |

### Requirement: Trigger format uses commands + with_wake

Triggers SHALL use `commands: [...]` (flat list) and `with_wake: true/false` instead of the legacy `phrase`/`aliases`/`wake_words: []` format. Legacy format is accepted with deprecation warnings.

#### Scenario: commands field parsed
- **WHEN** `triggers: [{commands: ["chiama Stefano"], with_wake: false}]`
- **THEN** `trigger.commands == ["chiama Stefano"]` and `trigger.with_wake == false`

#### Scenario: Legacy wake_words: [] warns
- **WHEN** `triggers: [{phrase: "aiuto", wake_words: []}]`
- **THEN** a deprecation warning is logged: "use 'with_wake: false'"
- **AND** the trigger works as a direct match

## REMOVED Requirements

### Requirement: stt.stage1 and stt.stage2 sub-blocks
**Reason**: Replaced by flat stt block with single-model design.
**Migration**: Move stage1 fields to flat stt. Remove stage2 entirely (capture now uses the same model).

### Requirement: recognition.mode
**Reason**: Two-stage mode was removed; single model is always used.
**Migration**: Remove `recognition.mode` from config.yaml.

### Requirement: recognition.command_timeout, command_max_timeout, partial_matching, partial_stability_ms, partial_stability_reads
**Reason**: Replaced by recognition.wake_window and post_dispatch_cooldown_ms in the single-model pipeline.
**Migration**: Use `recognition.wake_window` instead of `command_timeout`.

### Requirement: wake_words as group objects with word:/aliases:
**Reason**: Replaced by flat string list `wake_words: ["phrase1", "phrase2"]`.
**Migration**: Flatten all `wake_words` entries into a single list of strings; move trigger routing to `with_wake:` field.

### Requirement: Trigger wake_words: [id] scoping
**Reason**: All triggers now fire after ANY wake word (or with `with_wake: false` for no wake word). Per-group scoping is removed.
**Migration**: Set `with_wake: true` (default) for triggers that need a wake word; set `with_wake: false` for direct match.
