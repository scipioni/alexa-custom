# Capability: Config Hardening

## Purpose
Move previously hardcoded operational knobs into `config.yaml` so they are tunable without code changes, while preserving full backward compatibility with existing deployments.

## Requirements

### Requirement: Audio and timing knobs in config.yaml
The system SHALL read all previously hardcoded audio timing constants and device identity from `config.yaml`. The following optional fields SHALL be supported with backward-compatible defaults:

| Field | Default | Was |
|---|---|---|
| `audio_card_name` | `"NewPie"` | hardcoded string |
| `audio_sample_rates.usb` | `48000` | hardcoded `_SAMPLERATE` dict |
| `audio_sample_rates.bluetooth` | `16000` | hardcoded |
| `audio_sample_rates.internal` | `48000` | hardcoded |
| `audio_post_playback_ms` | `100` | `AUDIO_POST_PLAYBACK_MS` env var |
| `audio_tone_preroll_ms` | `300` | `AUDIO_TONE_PREROLL_MS` env var |
| `audio_mic_gain` | `300` | hardcoded `pactl 300%` |
| `reconnect_delay` | `5` | hardcoded `_RECONNECT_DELAY` |
| `mqtt_queue_max` | `200` | unbounded |

All fields SHALL remain optional; existing `config.yaml` files with none of these fields SHALL continue to work identically.

#### Scenario: Default values apply when fields absent
- **WHEN** `config.yaml` exists but contains none of the new fields
- **THEN** the system behaves identically to the previous release (all defaults match prior hardcoded values)

#### Scenario: audio_card_name overrides default device search
- **WHEN** `config.yaml` sets `audio_card_name: ConferenceCam`
- **THEN** `audio.find_alexa_card()` searches for a card matching `conferencecam` (case-insensitive) instead of `newpie`

#### Scenario: audio_sample_rates.bluetooth override
- **WHEN** `config.yaml` sets `audio_sample_rates: {bluetooth: 8000}`
- **THEN** the session sample rate for a Bluetooth device is 8000 Hz

#### Scenario: audio_post_playback_ms tunable
- **WHEN** `config.yaml` sets `audio_post_playback_ms: 200`
- **THEN** the STT gate remains closed for 200 ms after each playback ends

#### Scenario: reconnect_delay tunable
- **WHEN** `config.yaml` sets `reconnect_delay: 10`
- **THEN** the client waits 10 seconds before reconnecting to LiveKit after a disconnection

### Requirement: STT thresholds in config.yaml
The system SHALL read STT sensitivity knobs from `config.yaml`. The following optional fields SHALL be supported:

| Field | Default | Was |
|---|---|---|
| `stt_vad_silence_ms` | `700` | `STT_VAD_SILENCE_MS` env var |
| `stt_stage1_vad_silence_ms` | `500` | `STT_STAGE1_VAD_SILENCE_MS` env var |
| `stt_stage1_rms_threshold` | `0.02` | `STT_STAGE1_RMS_THRESHOLD` env var |

Env-var overrides SHALL still be honoured if set, taking precedence over the config value, to preserve backward-compatibility for deployments that set thresholds via environment.

#### Scenario: stt_vad_silence_ms from config
- **WHEN** `config.yaml` sets `stt_vad_silence_ms: 1000`
- **THEN** the command capture window waits for 1000 ms of silence before finalising

#### Scenario: Env var overrides config value
- **WHEN** `config.yaml` sets `stt_vad_silence_ms: 1000` and `STT_VAD_SILENCE_MS=500` is in the environment
- **THEN** the effective value is 500 ms (env var wins)
