# Configuration Guide

Configuration lives in the `conf/` directory at the project root. All files are YAML.

```
conf/
  config.yaml          main configuration (hot-reloaded)
  secrets.yaml         credentials — git-ignored, restart required
  state.yaml           runtime state (volume, active profile) — auto-managed
  actions/
    system.yaml        startup message + system triggers (loaded first)
    user.yaml          your custom triggers (or any *.yaml file)
    learned.yaml       auto-created by the llm_learn action
```

---

## conf/secrets.yaml

Credentials and hostnames never committed. Copy the example:

```bash
cp conf.example/secrets.yaml conf/secrets.yaml
```

```yaml
livekit:
  url: wss://your-project.livekit.cloud
  api_key: YOUR_KEY
  api_secret: YOUR_SECRET
  room: your-room
  # meet_url: https://meet.livekit.io  # optional — base URL for the browser join
  #                                    # link (self-hosted meet frontend); defaults
  #                                    # to meet.livekit.io if omitted

telegram:
  bot_token: "123456:TOKEN"
  chat_id: "12345678"

llm_host: http://127.0.0.1:11434    # Ollama or OpenAI-compatible endpoint
# llm_api_key: sk-your-key           # required for OpenAI, optional for Ollama

mqtt:
  username: user
  password: pass
```

Values are written to `os.environ` and readable as `LIVEKIT_URL`, `TELEGRAM_BOT_TOKEN`, etc. Changing secrets requires a daemon restart.

---

## conf/config.yaml

Hot-reloaded every `system.config_poll_interval` seconds (**2**). Default values shown in **bold**.

### Wake words — `wake_words`

Flat list of strings. Extra phrases can be added from `conf/actions/*.yaml` via a `wake_words:` key.

```yaml
wake_words:
  - "ehi serena"
  - "ascolta assistente"
```

### Recognition — `recognition`

```yaml
recognition:
  wake_window: 8.0                     # command window after wake (seconds)
  wake_tone: "wake"                    # tone on wake: wake | startup | success | error | info | warning | none
  call_tone: true                      # play tones on call connect/disconnect
  matching_algorithm: "token_sort_ratio" # token_sort_ratio | token_set_ratio | levenshtein | ratio
  matching_threshold: 75.0             # similarity 0–100
  min_word_overlap: 0.0                # fraction of content words required verbatim (0=off)
  reply_matching_algorithm: "levenshtein" # algorithm for ask replies
  reply_matching_threshold: 80.0
  follow_up: false                     # re-open window after match without re-waking
  follow_up_timeout: 4.0               # silence before follow-up closes
  follow_up_max_turns: 5               # max consecutive follow-up turns
  follow_up_tone: "info"               # chime when follow-up opens
  post_dispatch_cooldown_ms: 800       # silence after dispatch (echo prevention)
  min_cmd_words: 1                     # minimum words in command before matching
  dispatch_timeout: 90.0               # action dispatch timeout
```

> **Removed keys**: `mode`, `command_timeout`, `command_max_timeout`, `partial_matching`, `partial_stability_ms`, `partial_stability_reads` — all replaced by the single-model design.

### Speech-to-Text — `stt`

Single always-on model. No stage2. `vosk` (default) or `sherpa-onnx` (opt-in — see `docs/stt-simple.md`'s backend benchmark for the load-time/CPU/latency trade-offs before switching).

```yaml
stt:
  backend: "vosk"                      # vosk (default) | sherpa-onnx
  model_path: null                     # override default model path (sherpa-onnx: a
                                        #   Kroko model dir, default models/it/kroko_64l)
  num_threads: 2                       # ONNX threads (vosk ignores)
  vad_silence_ms: 900                  # milliseconds of silence before endpoint
  rms_threshold: 0.02                  # minimum RMS energy for speech
  adaptive_rms: true                   # dynamic threshold adjustment
  adaptive_rms_margin: 0.01
  min_speech_ms: 200                   # minimum sustained speech before VAD starts
  wake_match_threshold: 0.5            # fraction of wake-phrase tokens required
  mono_capture: false                  # force parec mono capture
  capture_backend: "parec"             # parec (default) | gstreamer
  sherpa_vad_threshold: 0.5            # sherpa-onnx only: internal Silero VAD gate threshold
  sherpa_vad_min_speech_ms: 100        # sherpa-onnx only: VAD onset debounce
  sherpa_vad_min_silence_ms: 400       # sherpa-onnx only: VAD gate hangover
```

### Text-to-Speech — `tts`

```yaml
tts:
  backend: "piper"                     # piper | pico
  voice: "it_IT-paola-medium"          # Piper voice name
  preroll_ms: 100                      # silence prepended (covers PipeWire cold-start)
```

### Audio Hardware — `audio`

```yaml
audio:
  card_name: null                      # ALSA card name substring
  input_device: null                   # PipeWire source substring (null=default)
  output_device: null                  # PipeWire sink substring (null=default)
  output_volume: 0.5                   # 0.0–1.0 (digital, not system mixer)
  input_gain: 1.0                      # software gain multiplier (≥0.0, post-capture)
  post_playback_ms: 100                # STT gate hold after playback (echo decay)
  tone_preroll_ms: 50                  # silence before tones (PipeWire cold-start)

  sample_rates:
    usb: 48000
    bluetooth: 16000
    internal: 48000

  webrtc:
    agc: true                          # Automatic Gain Control
    aec: true                          # Acoustic Echo Cancellation
    noise_suppression: true
    high_pass_filter: true

  gstreamer:                           # only used when stt.capture_backend: gstreamer
    source: "pulsesrc"                 # pulsesrc (default) | pipewiresrc (experimental)
    noise_suppression: true
    noise_suppression_level: 2         # 0=mild 1=moderate 2=high 3=very-high
    agc: true
    agc_target_level_dbfs: -3
    agc_compression_gain_db: 9
    high_pass_filter: true             # 80 Hz (removes USB power hum)
    compressor: false
    compressor_threshold: 0.1          # 0.0–1.0 (normalized)
    compressor_ratio: 3.0
    profiles: {}                       # named profiles with GStreamer + STT overrides
```

**GStreamer profiles** override pipeline params AND STT params (`rms_threshold`, `vad_silence_ms`). Switch at runtime via `set_audio_profile` action:

```yaml
audio:
  gstreamer:
    profiles:
      normal:
        noise_suppression_level: 2
        agc_target_level_dbfs: -3
        rms_threshold: 0.02
        vad_silence_ms: 900
      sensitive:
        noise_suppression_level: 2
        agc_compression_gain_db: 30
        rms_threshold: 0.008
        vad_silence_ms: 1200
```

### LLM — `llm`

Supports any OpenAI-compatible endpoint (Ollama, OpenAI API, LM Studio, vLLM).

```yaml
llm:
  backend: "ollama"                    # ollama | openai
  model: "ssfdre38/gemma4-nano"       # model name
  context_turns: 10                    # conversation pairs in history
  context_window_secs: 60              # inactivity before history reset
  fallback_on_no_match: false          # route unmatched commands to LLM
  learn_commands: true                 # enable llm_learn action type
  request_timeout: 60.0                # HTTP timeout
  system_prompt: null                  # optional system prompt override
  exit_phrases:
    - "stop"
    - "esci"
    - "basta"
    - "fine"
    - "fermati"
    - "chiudi"
    - "exit"
    - "quit"
    - "annulla"
    - "cancella"
```

`llm_host` and `llm_api_key` go in `conf/secrets.yaml`. The `llm:` block is disabled if host is missing.

### MQTT — `mqtt`

Omit this section to disable MQTT.

```yaml
mqtt:
  host: 127.0.0.1                     # required to enable MQTT
  port: 1883
  topic_prefix: "alexa"
  node_id: "living_room"              # defaults to hostname
  queue_max: 200                       # max queued messages while broker unreachable
```

### Web Dashboard — `web`

```yaml
web:
  port: 8080
  cpu_limit: 4                         # CPU cores for dashboard display
  history_file: "conf/history.jsonl"   # persistent interaction history
  history_max_entries: 100             # trim to this many most-recent entries
                                        # on every append (0 = keep everything)
```

### Display — `display`

Visual feedback on Arduino UNO Q LED matrix. Omit to disable.

```yaml
display:
  enabled: false
  backend: "auto"                      # auto | bridge | gpio | mock | i2c
  transport: "unix"                    # auto | subprocess | unix | tcp
  matrix_brightness: 50                # 0–100
  led_brightness: 50                   # 0–100
```

Action files — `actions`

```yaml
actions:
  dir: "conf/actions"                  # directory for .yaml action files
  learn_file: "conf/actions/learned.yaml" # llm_learn writes here
  # dump_triggers_dir: /tmp/trigger_dumps  # save pre-trigger audio WAV for debugging
```

### System Tuning — `system`

```yaml
system:
  reconnect_delay: 5                   # seconds between LiveKit reconnect attempts
  config_poll_interval: 2              # hot-reload polling
  empty_room_timeout: 0                # disconnect after N seconds empty (0=never)
  wait_for_participant: true           # poll LK API before joining; connect only when caller appears
  answer_timeout: 60                   # seconds to wait for participant before giving up
```

`wait_for_participant: true` → `livekit_join` polls the LiveKit REST API for a remote participant before actually connecting. `answer_timeout` limits the wait.

---

## conf/actions/

Action files load in this order:
1. **`system.yaml`** — always first (highest priority). Only this file can contain `on_startup`.
2. All other `*.yaml` files alphabetically.

### Trigger structure

```yaml
# File-level extra wake words (flat list, merged with config.yaml)
wake_words:
  - "aiuto"

triggers:
  - commands: ["che ore sono"]
    with_wake: false                     # direct match, no wake word needed
    actions:
      - type: say
        text: "$(date +'Sono le %H e %M')"
        lang: "it-IT"

  - commands: ["accendi le luci"]
    patterns:                            # tested before fuzzy scoring
      - "accend* * luc*"
    tag: luci                            # optional grouping tag
    actions:
      - type: mqtt_publish
        topic: home/light/set
        payload: "ON"

  - commands: ["buonanotte"]
    follow_up: false                     # override global follow-up per trigger
    actions:
      - type: say
        text: "Buonanotte!"
```

Trigger fields:

| Field | Default | Description |
|---|---|---|
| `commands` | required | List of recognised phrases (first is canonical) |
| `actions` | required | List of action entries |
| `with_wake` | `true` | `false` = fires without wake word |
| `patterns` | `[]` | Word-glob patterns (definitive match) |
| `follow_up` | global | Per-trigger override of `recognition.follow_up` |
| `min_word_overlap` | global | Per-trigger override of word-overlap guard |
| `tag` | `""` | Optional grouping tag |

### All action types

| Type | Required params | Optional params | Description |
|---|---|---|---|
| `say` | `text` | `lang` (**it-IT**) | Speak text via TTS. Supports `$(shell command)` expansion |
| `ask` | `text`, `lang` | `timeout` (**5.0**), `on_reply`, `on_else` | Speak question, listen for reply, match against reply triggers |
| `tone` | — | `name` (**info**) | Play tone: wake, startup, success, error, info, warning, none |
| `log` | — | `message` | Log a message (debug) |
| `livekit_join` | — | — | Join configured LiveKit room |
| `telegram` | — | `chat_id` (env fallback), `text` | Send Telegram message. `$room` → LiveKit room URL |
| `mqtt_publish` | — | `topic`, `payload`, `retain` (**false**) | Publish MQTT message |
| `shell` | — | `command` | Execute shell command |
| `llm_chat` | — | `system_prompt` | Multi-turn LLM chat via listen/speak loop |
| `llm_learn` | — | — | Voice wizard to teach a new trigger |
| `meteo` | — | `city`, `days`, `lang`, `latitude`, `longitude` | Weather forecast via Open-Meteo |
| `set_volume` | — | `mode` (**absolute**), `value` (**0.5**), `step` (**0.1**) | Output volume control |
| `set_volume_from_transcript` | — | — | Extract percentage from transcript, set volume |
| `set_audio_profile` | — | `profile` (required), `say`, `lang` | Switch GStreamer capture profile |
| `system_info` | — | — | Read CPU temp, load, memory, uptime → speak |
| `calibrate_input_gain` | — | `sentence`, `gain_low` (**0.4**), `gain_mid` (**0.7**), `gain_high` (**1.2**), `listen_timeout` (**6.0**), `settle_ms` (**500**) | 5-probe mic gain calibration |
| `record_and_playback` | — | `duration` (**7.0**), `lang` | Record audio and play back with RMS score |
| `stop_listening` | — | — | Put STT to sleep |
| `start_listening` | — | — | Wake STT from sleep |
| `restart` | — | — | Restart the daemon process |

---

## Hot-reload behaviour

- `conf/config.yaml` and all `conf/actions/*.yaml` are polled every `system.config_poll_interval` seconds (**2**).
- `conf/secrets.yaml` is **not** hot-reloaded — restart required.
- On parse error, previous valid config is preserved and the error is logged.
- `alexa_custom/dashboard.html` is also watched — any edit reloads the browser within ~1s.
