# LiveKit Headless Audio Client

A headless Python client that turns a USB conference speakerphone into a voice-activated smart assistant.

Optimized for **PipeWire** and fully integrated with **Home Assistant**.

---

## Quick Start

```bash
# 1. Install system dependencies
sudo apt install -y pulseaudio-utils pipewire python3-venv

# 2. Setup virtual environment
python -m venv .venv
.venv/bin/pip install -e .

# 3. Download STT models
alexa-setup

# 4. Configure USB audio (run once after first boot)
task audio:setup            # sets NewPie as default, installs PCM restore service
task audio:status           # verify routing and endpoints

# 5. Create config
mkdir -p conf/actions
cp conf.example/config.yaml conf/config.yaml
cp conf.example/secrets.yaml conf/secrets.yaml
# Edit conf/secrets.yaml — add LiveKit, Telegram, LLM credentials
# Edit conf/config.yaml  — set wake words, audio device, STT backend

# 6. Install as a systemd service (recommended for headless use)
task setup
sudo loginctl enable-linger arduino   # keep service alive when SSH disconnects
systemctl --user start alexa-custom

# 7. Or run manually
alexa-client                # web dashboard at http://<host>:8080
```

---

## Configuration

Configuration lives in the `conf/` directory:

| File | Purpose | Hot-reload |
|------|---------|-----------|
| `conf/config.yaml` | Wake words, audio, STT, TTS, LLM, MQTT | Yes (~2 s) |
| `conf/secrets.yaml` | Credentials (git-ignored) | Restart required |
| `conf/actions/*.yaml` | Voice triggers and startup actions | Yes (~2 s) |

### conf/secrets.yaml

```yaml
livekit:
  url: wss://your-project.livekit.cloud
  api_key: YOUR_KEY
  api_secret: YOUR_SECRET
  room: your-room

telegram:
  bot_token: "123456:TOKEN"
  chat_id: "12345678"

llm_host: http://192.168.1.10:11434   # Ollama host
```

### conf/config.yaml (key blocks)

```yaml
wake_words:
  - word: galileo
    lang: it-IT

  # For emergency-style wake words, prefer multi-word phrases so a single
  # utterance in conversation does not trigger the assistant:
  # - word: "aiuto aiuto"
  #   aliases: ["aiutami"]

recognition:
  command_timeout: 3.0      # seconds to listen after wake word

stt:
  stage1:                   # continuous wake-word detection (low CPU)
    backend: vosk
    vosk_grammar: false     # false = free-vocabulary (recommended); true = grammar mode (lower CPU, no reject path)
    confidence: 0.65        # minimum confidence threshold (grammar mode only)
    confidence_mode: first  # first | min | mean (grammar mode only)
    vad_silence_ms: 500     # force-finalize after N ms of silence
    rms_threshold: 0.02     # minimum energy level to count as speech
  stage2:                   # command recognition after wake
    backend: vosk

audio:
  input_device: pipewire    # or 'NewPie' to pin to the USB mic
  output_device: pipewire   # or 'NewPie' to pin to the USB speaker
  output_volume: 0.5

tts:
  backend: piper
  voice: it_IT-paola-medium

system:
  wait_for_participant: true  # poll room before joining; connect only when a caller appears
  answer_timeout: 60          # seconds to poll before returning to idle
```

### conf/actions/

Action files are loaded alphabetically with `system.yaml` first (highest priority):

- **`system.yaml`** — startup message, system-level triggers (restart, help, etc.)
- **`user.yaml`** (or any name) — your custom triggers and wake-word shortcuts

```yaml
# conf/actions/system.yaml
on_startup:
  - type: say
    text: Sistema pronto
    lang: it-IT

triggers:
  - phrase: che ora è
    actions:
      - type: shell
        command: date +%H:%M
```

See `conf.example/config.yaml` and `conf.example/secrets.yaml` for the full reference.

---

## Key Features

- **Two-stage STT**: Lightweight wake-word detection (stage 1) → full command recognition (stage 2). Backends configurable independently. Free-vocabulary mode gives Vosk a genuine reject path so unrelated speech is not forced onto a wake phrase. Inline command pass-through: if the command follows the wake word in a single breath, stage-2 dispatch fires immediately without a second capture round-trip.
- **Polite LiveKit join**: With `wait_for_participant: true` (default), saying the join trigger polls the LiveKit room via the REST API and only connects when a remote participant is actually present — STT stays active throughout. Disconnects cleanly if nobody joins within `answer_timeout` seconds.
- **Hot-reload**: Edit `conf/config.yaml`, any action file, or `dashboard.html` while the daemon is running — config changes apply within ~2 seconds, HTML changes reload the browser within ~1 second.
- **Multi-file actions**: Drop `.yaml` files into `conf/actions/` for modular command sets; `system.yaml` always loads first.
- **LLM learning**: Say "impara nuovo comando" to teach the assistant a new trigger via voice dialogue (stored in `conf/actions/learned.yaml`).
- **Bidirectional MQTT**: Home Assistant Discovery support. Forward voice commands to HA and trigger local actions via MQTT.
- **Web Dashboard**: Real-time browser UI — VU meters with RMS needle, STT status with wake-word badge, room status panel (closed / waiting / in call), live logs, restart button.
- **PipeWire native**: Direct integration without PortAudio shims.

---

## Commands

| Command | Description |
|---------|-------------|
| `alexa-client` | Start the assistant daemon |
| `alexa-client --web-port 9090` | Start with dashboard on a custom port |
| `alexa-audio` | Microphone → speaker loopback test |
| `alexa-devices` | List detected audio devices |
| `alexa-setup` | Download/update STT and TTS models |

## Task Automation

| Task | Description |
|------|-------------|
| `task audio:setup` | Set NewPie as default, install PCM restore service |
| `task audio:restart` | Restart WirePlumber and restore routing/PCM |
| `task audio:status` | Show audio device status dashboard |
| `task audio:test` | Play a test WAV to verify speaker output |
| `task test` | Run regression tests |
| `task lint` / `task format` | Code quality checks and formatting |

---

## Project Structure

```
conf/
  config.yaml         main config (hot-reloaded)
  secrets.yaml        credentials (git-ignored)
  actions/
    system.yaml       startup + system triggers (loaded first)
    user.yaml         your custom triggers
    learned.yaml      auto-created by llm_learn

alexa_custom/
  client.py           main loop, LiveKit session
  stt.py              two-stage STT pipeline (Vosk / sherpa-onnx)
  tts.py              TTS engine (Piper)
  audio.py            PipeWire routing, AudioWatcher, device enumeration
  actions.py          action dispatcher
  config.py           typed config dataclasses and loaders
  config_manager.py   hot-reload watcher
  mqtt.py             MQTT / Home Assistant Discovery
  web.py              aiohttp web dashboard
```

---

## Documentation

- **[Hardware Setup](docs/setup_hardware.md)** — PipeWire, Bluetooth, device-specific fixes
- **[Software Installation](docs/setup_software.md)** — Dependencies, venv, STT models
- **[Configuration](docs/configuration.md)** — Full config reference
- **[MQTT & Home Assistant](docs/mqtt_integration.md)** — Auto-discovery and remote control
- **[Troubleshooting](docs/troubleshooting.md)** — Common audio, connection, and permission fixes

---

## License

Apache-2.0
