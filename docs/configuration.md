# Configuration Guide

Configuration lives in the `conf/` directory at the project root.

```
conf/
  config.yaml          main config (wake words, audio, STT, TTS, LLM, MQTT)
  secrets.yaml         credentials — git-ignored, restart required on change
  actions/
    system.yaml        startup message + system-level triggers (loaded first)
    user.yaml          your custom triggers (or any *.yaml file)
    learned.yaml       auto-created by the llm_learn action
```

---

## conf/secrets.yaml

Credentials and hostnames that should never be committed. Copy the example to get started:

```bash
cp conf.example/secrets.yaml conf/secrets.yaml
```

All values are optional — omit any section you don't use.

```yaml
livekit:
  url: wss://your-project.livekit.cloud
  api_key: YOUR_KEY
  api_secret: YOUR_SECRET
  room: your-room           # room name to join on livekit_join action

telegram:
  bot_token: "123456:TOKEN"
  chat_id: "12345678"       # default recipient for telegram actions

llm_host: http://192.168.1.10:11434   # Ollama base URL

mqtt:
  username: user            # broker credentials (omit if auth not required)
  password: pass
```

`load_secrets()` writes these values to `os.environ` so downstream code can read them as environment variables (`LIVEKIT_URL`, `LIVEKIT_API_KEY`, etc.). Changing `conf/secrets.yaml` requires a daemon restart.

---

## conf/config.yaml

Hot-reloaded every `system.config_poll_interval` seconds (default: 2). Copy the example:

```bash
cp conf.example/config.yaml conf/config.yaml
```

### Wake Words

```yaml
wake_words:
  - word: galileo           # the phrase to listen for
    lang: it-IT             # language tag (used for TTS responses)
    # aliases: ["ehi galileo", "hey galileo"]
  - word: assistente
```

### Recognition

```yaml
recognition:
  mode: two-stage           # two-stage (default) or single-stage
  command_timeout: 3.0      # seconds to listen for a command after wake word
  wake_tone: wake           # tone on wake: wake | startup | success | error | info | warning | none
```

### STT — Speech-to-Text

The two-stage pipeline uses a lightweight stage 1 for always-on wake detection and an independent stage 2 for command recognition. Backends can differ.

```yaml
stt:
  vad_silence_ms: 700       # idle ms before the command window closes (stage-2)

  stage1:                   # continuous wake-word detection (low CPU)
    backend: vosk           # vosk | sherpa-onnx

    # Vocabulary mode (Vosk only)
    vosk_grammar: false     # false = free-vocabulary (default, recommended)
                            #   Vosk decodes the full language; unrelated speech is
                            #   genuinely rejected; confidence scores are absolute.
                            # true = grammar mode: restricts decoder to wake-word
                            #   vocabulary only; lower CPU but no real reject path —
                            #   every segment is forced onto the nearest wake phrase.

    # Confidence gating (grammar mode only — ignored in free-vocab mode)
    confidence: 0.65        # minimum token confidence to accept wake word (0–1)
    confidence_mode: first  # how to aggregate per-token confidence:
                            #   first — only check first decoded token (fastest)
                            #   min   — every token must clear the bar (strictest)
                            #   mean  — average across tokens (moderate)

    # Software VAD (stage-1 force-finalize)
    vad_silence_ms: 500     # force-finalize after this many ms of silence
    rms_threshold: 0.02     # minimum RMS energy level to count as speech
    min_speech_ms: 200      # minimum sustained speech before silence timer starts

  stage2:                   # command recognition after wake word
    backend: vosk           # can use a higher-accuracy backend than stage1
    # model_path: models/it/kroko_128l
```

#### Inline command pass-through

In free-vocabulary mode (`vosk_grammar: false`), if the user speaks the wake word and a command in a single utterance — e.g. *"ehi galileo chiama mario"* — stage-1 extracts the trailing text and passes it directly to stage-2 dispatch, skipping the capture phase entirely. This eliminates one round-trip and makes same-breath commands instantaneous.

### TTS — Text-to-Speech

```yaml
tts:
  backend: piper            # piper | pico
  voice: it_IT-paola-medium # Piper voice (run 'alexa-setup --piper-voice <name>')
  preroll_ms: 400           # silence prepended to TTS to cover PipeWire cold-start
```

### Audio Hardware

```yaml
audio:
  card_name: NewPie         # ALSA card name substring for hardware PCM restore
  input_device: pipewire    # PipeWire source substring, or 'pipewire' for system default
  output_device: pipewire   # PipeWire sink substring, or 'pipewire' for system default
  output_volume: 0.5        # speaker volume 0.0–1.0 (persisted by WirePlumber via wpctl)
  input_gain: 1.0           # microphone gain multiplier
  mic_gain: 300             # ALSA PCM mic gain percent, applied by 'task audio:setup'
  post_playback_ms: 100     # STT gate hold after playback ends (echo decay)
  tone_preroll_ms: 300      # silence before tones to cover PipeWire cold-start

  sample_rates:
    usb: 48000
    bluetooth: 16000

  webrtc:                   # LiveKit WebRTC mic processing
    agc: true               # Automatic Gain Control
    aec: true               # Acoustic Echo Cancellation
    noise_suppression: true
    high_pass_filter: true
```

To pin to a specific device rather than the system default, use a substring of the device name shown by `alexa-devices` (e.g., `NewPie`). Use `pipewire` to follow WirePlumber's routing.

### LLM (Ollama)

```yaml
llm:
  backend: ollama
  # host is set in conf/secrets.yaml as 'llm_host'
  model: gemma3:2b          # model name as shown by 'ollama list'
  context_turns: 10         # conversation pairs kept in history
  context_window_secs: 60   # inactivity before history resets
  fallback_on_no_match: false  # route unmatched commands to LLM
  learn_commands: true      # enable the llm_learn action type
  request_timeout: 60.0
```

`llm_host` must be set in `conf/secrets.yaml` — the `llm:` block is silently disabled if the host is missing or unreachable.

### MQTT / Home Assistant

```yaml
mqtt:
  host: 127.0.0.1           # broker hostname; required to enable MQTT
  port: 1883
  topic_prefix: alexa
  node_id: living_room      # defaults to system hostname
  queue_max: 200
```

Omit the `mqtt:` block entirely to disable MQTT.

### Web Dashboard

```yaml
web:
  port: 8080
```

### Action Files

```yaml
actions:
  dir: conf/actions                        # directory for .yaml action files
  learn_file: conf/actions/learned.yaml   # file the llm_learn action writes to
```

### System Tuning

```yaml
system:
  reconnect_delay: 5          # seconds between LiveKit reconnect attempts
  config_poll_interval: 2     # hot-reload polling interval (seconds)
  empty_room_timeout: 0       # disconnect after N seconds with no participants (0 = never)
```

---

## conf/actions/

Action files are loaded in this order:

1. **`system.yaml`** — always first, highest priority
2. All other `*.yaml` files alphabetically

Only `system.yaml` may contain `on_startup` actions. `on_startup` in other files is ignored with a debug log.

### Trigger structure

```yaml
on_startup:
  - type: say
    text: Sistema pronto
    lang: it-IT

triggers:
  - phrase: che ora è
    actions:
      - type: shell
        command: date "+Sono le %H e %M"
        capture: true         # speak the command output via TTS

  - phrase: manda messaggio
    actions:
      - type: telegram
        message: Chiamata in arrivo

wake_triggers:               # triggers bound to a specific wake word
  galileo:
    - phrase: chiama stefano
      actions:
        - type: livekit_join
```

`wake_triggers` are merged per wake word across all action files. Triggers not bound to a wake word are global (match after any wake word).

### Action types

| Type | Required params | Description |
|------|----------------|-------------|
| `say` | `text`, `lang` | Speak text via TTS |
| `ask` | `question`, `answers` | Multi-turn dialogue |
| `shell` | `command` | Run a shell command (`capture: true` to speak output) |
| `livekit_join` | — | Join the configured LiveKit room |
| `telegram` | `message` | Send a Telegram message |
| `mqtt_publish` | `topic`, `payload` | Publish an MQTT message |
| `tone` | `name` | Play an audio tone (`wake`, `success`, `error`, `info`, `warning`) |
| `log` | `message` | Log a message (debug use) |
| `llm_ask` | — | Send the spoken command to the LLM and speak the reply |
| `llm_learn` | — | Interactive voice wizard to teach a new trigger |

---

## Hot-reload behaviour

- `conf/config.yaml` and all `conf/actions/*.yaml` files are watched for changes.
- Changes apply within `system.config_poll_interval` seconds (default: 2).
- **`conf/secrets.yaml` is never watched** — restart the daemon to apply credential changes.
- If a file has a syntax error, the previous valid config is kept and the error is logged.
- `alexa_custom/dashboard.html` is also watched — any edit triggers a browser reload within ~1 second (no daemon restart required).

---

## Migrating from the old flat config.yaml

The old root-level `config.yaml` with a top-level `env:` block is no longer supported. To migrate:

1. Move credentials from the old `env:` block into `conf/secrets.yaml`.
2. Move `triggers:` and `wake_triggers:` into `conf/actions/user.yaml`.
3. Move the remaining settings (audio, stt, tts, mqtt, etc.) into `conf/config.yaml` using the nested block format shown above.

See `conf.example/config.yaml` and `conf.example/secrets.yaml` for the full structure.
