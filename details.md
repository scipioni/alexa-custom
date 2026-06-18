# Serena — Technical Reference

> Package name: `alexa-custom` · CLI entry points: `alexa-*` · systemd: `alexa-custom.service`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Installation Guide](#2-installation-guide)
3. [Configuration Reference](#3-configuration-reference)
4. [CLI & Task Reference](#4-cli--task-reference)
5. [Audio Architecture](#5-audio-architecture)
6. [STT Pipeline](#6-stt-pipeline)
7. [Trigger & Action System](#7-trigger--action-system)
8. [Display Backends](#8-display-backends)
9. [MQTT & Home Assistant](#9-mqtt--home-assistant)
10. [Web Dashboard](#10-web-dashboard)
11. [Development](#11-development)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        alexa-custom daemon                       │
│                                                                   │
│  ┌──────────┐  ┌─────────────────┐  ┌──────────┐  ┌──────────┐ │
│  │ client.py │─▶│  stt.py         │─▶│ actions  │─▶│  tts.py  │ │
│  │ (main     │  │  (stage 1 + 2)  │  │ .py      │  │  (Piper) │ │
│  │  loop)    │  │                  │  │          │  │          │ │
│  └─────┬─────┘  └────────┬────────┘  └────┬─────┘  └────┬─────┘ │
│        │                 │                 │              │       │
│  ┌─────┴──────┐  ┌───────┴────────┐  ┌────┴─────┐  ┌────┴─────┐ │
│  │ config_    │  │  audio_hw.py   │  │  mqtt.py │  │  web.py  │ │
│  │ manager.py │  │  audio_ops.py  │  │          │  │(aiohttp) │ │
│  │ (hot-      │  │  audio_watcher │  │  ── HA   │  │          │ │
│  │  reload)   │  │                │  │  Discovery│  │dashboard │ │
│  └────────────┘  └───────┬────────┘  └──────────┘  └──────────┘ │
│                          │                                       │
│                    ┌─────┴──────┐                                │
│                    │  display.py │                                │
│                    │  (LED/OLED) │                                │
│                    └────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    │    Audio I/O        │
                    │  parec · pw-play   │
                    │  pulsectl · amixer │
                    └────────────────────┘
```

### Data Flow

1. **Capture**: `parec` streams raw s16le audio from the USB microphone
2. **STT Pipeline**: Single always-on free-vocabulary Vosk transcription model processes the audio stream continuously
3. **Trigger matching**: The transcript is matched against configured triggers (wake words, commands) using phonetic normalization + fuzzy matching
5. **Action dispatch**: Matched actions execute — LiveKit join, MQTT publish, shell command, Telegram, LLM chat, etc.
6. **TTS response**: Piper or Pico TTS synthesises speech, played back via `pw-play`
7. **Feedback**: Visual display (LED matrix, OLED, GPIO) updates to reflect state

### Threading Model

- **Main thread**: Event loop driving STT pipeline, trigger matching, action dispatch
- **Audio watcher thread**: `AudioWatcher` monitors PipeWire graph events via pulsectl
- **Web server thread**: aiohttp serves the dashboard on a separate asyncio loop
- **Config watcher thread**: Polls config files for changes every ~2 seconds
- **LLM calls**: Non-blocking HTTP requests to Ollama (offloaded via asyncio)

---

## 2. Installation Guide

### System Requirements

- **Board**: Arduino Uno Q (Qualcomm Snapdragon 801, aarch64) or any Linux system with PipeWire
- **OS**: Debian 13 (Trixie) or similar
- **RAM**: 2+ GB recommended
- **Audio**: PipeWire 1.4+ with PulseAudio compatibility socket

### System Dependencies

```bash
# Core
sudo apt install python3 python3-pip python3-venv
sudo apt install pipewire pipewire-pulse wireplumber
sudo apt install pulseaudio-utils    # parec, paplay
sudo apt install pipewire-bin        # pw-play, pw-metadata, wpctl
sudo apt install alsa-utils          # amixer

# Optional — LED matrix display (Arduino UNO Q)
sudo apt install gcc make            # compile uart_bridge

# Optional — development
sudo apt install git task             # task runner
```

### Python Environment

Requires **Python ≥ 3.13**.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional: `pip install smbus2` for I2C OLED display support.

### Model Download

```bash
alexa-setup
```

Downloads:
- Vosk Italian model (`models/it/vosk-model-small-it-0.22`)
- Piper TTS voice (`it_IT-paola-medium`)

### Audio Configuration

Run once after first boot:

```bash
task audio:setup
```

This command:
1. Removes stale `switch-on-connect` PipeWire config drop-ins (module not available on this board)
2. Installs udev rule to disable USB autosuspend for the NewPie
3. Switches NewPie from `pro-audio` to `analog-stereo` profile
4. Sets WirePlumber persistent default sink/source
5. Unmutes hardware PCM volume
6. Installs `alsa-pcm-unmute.service` (systemd user service) to re-apply PCM 100% on every boot
7. Restarts WirePlumber to activate routing

Verify with:

```bash
task audio:status
```

### Configuration Setup

```bash
mkdir -p conf/actions
cp conf.example/config.yaml conf/config.yaml
cp conf.example/secrets.yaml conf/secrets.yaml
cp conf.example/actions/system.yaml conf/actions/system.yaml
cp conf.example/actions/user.yaml conf/actions/user.yaml
```

Edit `conf/secrets.yaml` with your credentials (LiveKit, Telegram, LLM, MQTT).

Edit `conf/config.yaml` with your wake words and preferences.

### systemd Service

```bash
task setup
sudo loginctl enable-linger arduino
systemctl --user start alexa-custom
```

Useful commands:

```bash
systemctl --user status  alexa-custom   # check status
journalctl --user -fu    alexa-custom   # follow logs
systemctl --user restart alexa-custom   # restart
```

### First Run

```bash
alexa-client
```

Open http://localhost:8080 for the web dashboard.

---

## 3. Configuration Reference

Configuration is split across three locations in `conf/`:

| File | Purpose | Hot-reload |
|------|---------|-----------|
| `conf/config.yaml` | System settings and wake words | ~2 seconds |
| `conf/secrets.yaml` | Credentials (git-ignored) | Restart required |
| `conf/actions/*.yaml` | Triggers and extra wake word groups | ~2 seconds |

### conf/config.yaml

```yaml
# ---------------------------------------------------------------------------
# Wake words
# ---------------------------------------------------------------------------
wake_words:
  - word: ehi galileo       # the phrase to detect
    id: galileo             # stable id used by triggers in action files
    # aliases:
    #   - galileo
    # skip_unmatched_inline: false  # silently drop one-breath commands that
    #   don't match any trigger

# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
recognition:
  mode: two-stage           # two-stage | single-stage
  command_timeout: 3.0      # seconds to listen after wake word (two-stage only)
  # command_max_timeout: 8.0  # absolute cap; slides while user keeps speaking
  wake_tone: wake           # tone on wake: wake | startup | success | error | info | warning | none
  partial_matching: true    # scan Vosk partials for (wake+trigger) combos
  matching_algorithm: token_set_ratio  # token_set_ratio | levenshtein | ratio
  matching_threshold: 70.0             # similarity threshold (0-100)
  reply_matching_algorithm: levenshtein
  reply_matching_threshold: 80.0
  # follow_up: false          # re-open command window after a match
  # follow_up_timeout: 4.0
  # follow_up_max_turns: 5

# ---------------------------------------------------------------------------
# STT — speech-to-text
# ---------------------------------------------------------------------------
stt:
  backend: vosk            # speech-to-text backend
  vad_silence_ms: 900      # idle ms before command window closes
  rms_threshold: 0.02
  adaptive_rms: true
  adaptive_rms_margin: 0.01
  min_speech_ms: 200
  wake_match_threshold: 0.5

# ---------------------------------------------------------------------------
# TTS — text-to-speech
# ---------------------------------------------------------------------------
tts:
  backend: piper            # piper | pico
  voice: it_IT-paola-medium
  preroll_ms: 100

# ---------------------------------------------------------------------------
# Audio hardware
# ---------------------------------------------------------------------------
audio:
  input_device: pipewire    # PipeWire source name, or 'pipewire' for default
  output_device: pipewire   # PipeWire sink name, or 'pipewire' for default
  output_volume: 0.5
  input_gain: 1.0
  post_playback_ms: 300     # STT gate hold after playback ends
  sample_rates:
    usb: 48000
    bluetooth: 16000
    internal: 48000

# ---------------------------------------------------------------------------
# LLM (Ollama)
# ---------------------------------------------------------------------------
llm:
  backend: ollama
  model: ssfdre38/gemma4-nano
  context_turns: 10
  context_window_secs: 60
  fallback_on_no_match: false
  learn_commands: true
  request_timeout: 60.0

# ---------------------------------------------------------------------------
# MQTT / Home Assistant
# ---------------------------------------------------------------------------
# mqtt:
#   host: 127.0.0.1
#   port: 1883
#   topic_prefix: alexa
#   node_id: living_room

# ---------------------------------------------------------------------------
# Action files
# ---------------------------------------------------------------------------
actions:
  dir: conf/actions
  learn_file: conf/actions/learned.yaml
  # dump_triggers_dir: /tmp/trigger_dumps

# ---------------------------------------------------------------------------
# Visual display feedback
# ---------------------------------------------------------------------------
display:
  enabled: false
  backend: auto             # auto | bridge | gpio | mock | i2c
  matrix_brightness: 50
  led_brightness: 50
```

### conf/secrets.yaml

```yaml
livekit:
  url: wss://your-project.livekit.cloud
  api_key: YOUR_LIVEKIT_API_KEY
  api_secret: YOUR_LIVEKIT_API_SECRET
  room: your-room-name

telegram:
  bot_token: "123456789:AABBccDDeeFFggHH-your-token-here"
  chat_id: "123456789"

llm_host: http://127.0.0.1:11434

mqtt:
  username: ""
  password: ""
```

All values are optional. Omit sections you don't use.

### conf/actions/*.yaml

Action files are loaded alphabetically. `system.yaml` loads first (highest priority).

```yaml
# Extra wake word groups (merged with config.yaml)
wake_words:
  - word: "aiuto"
    id: help
    aliases:
      - "aiutami"

# Triggers
triggers:
  - phrase: "che ore sono ?"
    wake_words: []       # direct match — no wake word required
    aliases:
      - "che ora è ?"
    actions:
      - type: say
        text: "$(date +'Sono le %H e %M')"
```

**Trigger scoping** via the `wake_words` field:

| Value | Behaviour |
|---|---|
| Not specified | Active after any wake word (global) |
| `[]` (empty list) | Direct match — fires without a wake word |
| `[id]` | Active only after the named wake word group |

**Pattern matching** supports glob-style word patterns:

```yaml
- phrase: "accendi la luce"
  patterns:
    - "accend* * luc*"    # matches "accendi le luci", "accendere la luce", etc.
```

---

## 4. CLI & Task Reference

### CLI Entry Points

| Command | Description |
|---------|-------------|
| `alexa-client [--web-port PORT]` | Main daemon with web dashboard and config panel |
| `alexa-audio` | Microphone → speaker loopback test |
| `alexa-devices` | List detected audio devices |
| `alexa-test` | Audio test utility |
| `alexa-setup` | Download/update STT and TTS models |
| `alexa-audio-setup` | Configure audio routing |
| `alexa-audio-doctor` | Audio diagnostic checks |
| `alexa-wake-eval` | Wake word evaluation tool |
| `alexa-record` | WAV recording utility |
| `alexa-stt` | Direct STT testing via CLI |

### Task Commands

| Task | Description |
|------|-------------|
| `task test` | Run regression tests (pytest) |
| `task lint` | Ruff check + format --check |
| `task format` | Ruff format |
| `task fix` | Ruff fix + format + test |
| `task run` | Run alexa-client directly |
| `task start` | Start with hot-reload enabled |
| `task setup` | Install systemd user service |
| `task audio:setup` | Set NewPie as default, install PCM restore service, disable USB autosuspend |
| `task audio:restart` | Restart WirePlumber and restore routing/PCM |
| `task audio:status` | Display audio device status dashboard |
| `task audio:doctor` | Check all NewPie audio invariants |
| `task audio:test` | Play test WAV to verify speaker output |
| `task stt:analyze-dumps` | Analyze trigger-dump WAV files for false positives |
| `task display:compile` | Compile uart_bridge for direct UART access |
| `task display:test` | Test UART communication with STM32 |
| `task display:setup` | Compile uart_bridge + sudoers setup |
| `task display:flash` | Compile and flash STM32 display firmware |
| `task release:patch` | Bump PATCH version (0.3.0 → 0.3.1) |
| `task release:minor` | Bump MINOR version (0.3.0 → 0.4.0) |
| `task release:major` | Bump MAJOR version (1.0.0 → 2.0.0) |
| `task clean` | Remove __pycache__, build artifacts |

---

## 5. Audio Architecture

### Platform Constraints

The Arduino Uno Q's PortAudio was compiled with only the ALSA backend — no native PipeWire support. The ALSA→PipeWire shim causes `sd.play()` + `sd.wait()` to block forever. **PortAudio must not be used for any production I/O path.**

### Capture Path

```
USB Mic (NewPie) → ALSA → PipeWire → PulseAudio compat socket
                    ↓
              parec (pulseaudio-utils)
                    ↓
              s16le 16 kHz stereo → daemon
```

- **Command**: `parec --device=<source> --rate=16000 --format=s16le --channels=1`
- **Device selection**: By name, accessed via PulseAudio compat socket at `/run/user/1000/pulse/native`
- **Never use**: `sounddevice` or `PyAudio` for capture

### Playback Path

```
Piper TTS → s16le WAV file (temp) → pw-play <file> → PipeWire → ALSA → USB Speaker
```

- **Command**: `pw-play <temp.wav>` — native PipeWire client, exits cleanly on completion
- **Temp file**: Written to `/tmp/`, deleted after playback
- **Raw stdin unreliable**: `pw-play --raw --rate N --format f32 -` exits 0 but produces no audio on this board. Always write a temp WAV file.
- **Fallback**: `aplay -D pipewire` if `pw-play` is absent
- **Never use**: `sd.play()` or `PyAudio` for playback

### Routing & Device Management

- **Library**: `pulsectl` Python library wraps libpulse
- **Profile**: Always `analog-stereo` — never `pro-audio` (disables endpoints on NewPie)
- **Default routing**: Set via `pw-metadata` with `default.configured.audio.sink` / `default.configured.audio.source`
- **Volume control**: Applied digitally via `wpctl`; hardware PCM stays at 100% (unmuted by `amixer`)

### Known Issues & Workarounds

#### 1. ALSA Hardware Mixer Reset on Boot

**Problem**: When PipeWire initialises and takes ownership of the ALSA device, the kernel driver resets the NewPie's PCM mixer to 0%.

**Why `alsa-restore.service` doesn't help**: It runs before PipeWire starts, so PipeWire's init overwrites it.

**Fix**: `task audio:setup` installs `~/.config/systemd/user/alsa-pcm-unmute.service`, which:
- Polls until NewPie appears in `wpctl status`
- Forces NewPie as default routing
- Runs `amixer -c 0 sset PCM 100%` every 2 seconds for 20 seconds
- Catches WirePlumber's late ACP profile reset

**Ad-hoc**: `amixer -c 0 sset PCM 100%`

#### 2. Late Boot Routing

**Problem**: NewPie is discovered slightly after PipeWire/WirePlumber start. WirePlumber falls back to HDMI and doesn't reliably switch when NewPie appears.

**Fix**: The `alsa-pcm-unmute.service` polls and calls `pw-metadata` to force the active sink/source.

**Note**: `libpipewire-module-switch-on-connect` is NOT available on this board's PipeWire 1.4.2 build. The `ifexists nofail` flag doesn't work — it crashes PipeWire and `pipewire-pulse`. `task audio:setup` actively removes stale config drop-ins.

#### 3. USB Autosuspend (Mid-Session Audio Loss)

**Problem**: Linux suspends the NewPie USB device after inactivity. PipeWire reinitialises it on wake, resetting PCM to 0% and dropping routing.

**Fix**: `task audio:setup` installs `setup/99-newpie-no-autosuspend.rules` to `/etc/udev/rules.d/`, setting `autosuspend_delay_ms=-1` for the NewPie (USB ID `0a12:1260`).

**Ad-hoc recovery**: `task audio:restart`

#### 4. pulsectl Triggers PCM Reset

**Problem**: Opening any `pulsectl.Pulse()` connection causes `pipewire-pulse` to re-initialise the ALSA device, resetting hardware PCM to 0%.

**Fix**: Call `_restore_hw_pcm()` immediately after any pulsectl context closes. The function resolves the NewPie card dynamically and runs `amixer -c <card> sset PCM 100%`.

**Trigger points** (all already handled in code):
- After closing any `pulsectl.Pulse()` context
- Inside `AudioWatcher.run()` after opening the watcher connection
- Inside `AudioWatcher._check_and_enforce()` on device connect
- Inside `set_input_gain()` before calling `pactl set-source-volume`

**Rule**: Never open a `pulsectl.Pulse()` connection without calling `_restore_hw_pcm()` right after.

#### 5. pw-play Raw Stdin Unreliable

**Problem**: `pw-play --raw --rate N --format f32 -` exits 0 but produces no audio on PipeWire 1.4.2.

**Fix**: Write a temporary s16le WAV file and call `pw-play <tmp.wav>`. Delete the temp file after playback.

---

## 6. STT Pipeline

### Two-Stage Design

```
Audio Stream ──▶ Stage 1 (always-on, low CPU) ──▶ Wake word?
                                                    │
                                              Yes  │  No (continue)
                                                    ▼
                                           Stage 2 (command recognition)
                                                    │
                                              ┌─────┴─────┐
                                              ▼           ▼
                                        Trigger      No match
                                        Match         (re-arm stage 1)
                                           │
                                           ▼
                                      Action dispatch
```

### Speech-to-Text (STT) Pipeline

Serena runs a single always-on free-vocabulary Vosk transcription model that continuously transcribes captured audio chunks. Wake word detection and command recognition both happen by matching this single transcription model's output.

Key parameters under `stt`:
- `backend`: Must be `"vosk"`.
- `vad_silence_ms`: Force-finalize after this many ms of silence.
- `rms_threshold`: Minimum audio energy to consider as speech (default: 0.02).
- `adaptive_rms`: Dynamically adjust threshold based on room noise floor (default: true).
- `min_speech_ms`: Minimum speech duration in ms to avoid brief clicks (default: 200).
- `wake_match_threshold`: Similarity threshold (0.0 to 1.0) to match a wake word (default: 0.5).

### Speaking Patterns

| Mode | Pattern | Description |
|---|---|---|
| 1 | Wake → pause → beep → command | Traditional: say wake word, wait for beep, speak command |
| 2 | Wake + command (one breath) | Speak wake word and command together; no beep; fires immediately on silence |
| 3 | Partial match | Fires while user is still speaking, on a stable partial transcription |

### Trigger Matching

Triggers are matched against the transcribed command using a configurable algorithm:

| Algorithm | Description |
|-----------|-------------|
| `token_set_ratio` | Compares sets of tokens (handles reordering well) |
| `levenshtein` | Edit distance between strings |
| `ratio` | Simple similarity ratio |

Matching threshold (0–100) controls strictness.

**Word-glob patterns** can bypass fuzzy matching entirely:

```
accend* * luc*    → matches "accendi le luci", "accendere la luce", etc.
```

### Italian Phonetic Normalization

Custom phonetic matching handles Italian-specific linguistic features:

- **Digraphs**: `sci`/`sce`, `gn`, `gli`, `ch`/`gh`, `qu`
- **Geminate consonants**: Double consonants normalized for matching
- **Verb conjugations**: Root-based matching catches "accendere", "accendi", "accenda"
- **Article elision**: Handles "l'", "un'", "dell'" variations

---

## 7. Trigger & Action System

### Action File Format

```yaml
# on_startup (system.yaml only)
on_startup:
  - type: say
    text: "Sistema pronto"

# Extra wake word groups (optional)
wake_words:
  - word: "aiuto"
    id: help

# Triggers
triggers:
  - phrase: "che ore sono ?"       # display name / canonical form
    wake_words: []                 # scoping (see below)
    aliases:                       # alternative phrasings
      - "che ora è ?"
    patterns:                      # word-glob patterns (optional)
      - "che * * ora"
    actions:                       # list of actions to execute
      - type: say
        text: "$(date +'Sono le %H e %M')"
    follow_up: false               # override global follow-up setting
```

### Loading Order

Files in `conf/actions/` are loaded alphabetically. Convention:
- `system.yaml` — highest priority, system-level triggers (restart, help, time, etc.)
- `user.yaml` — user-defined custom triggers
- `learned.yaml` — auto-created by `llm_learn` action

### Action Types

| Type | Description | Example config |
|------|-------------|----------------|
| `say` | Speak text through TTS | `type: say; text: "Ciao"` |
| `shell` | Execute shell command | `type: shell; command: "date +%H:%M"` |
| `mqtt_publish` | Publish MQTT message | `type: mqtt_publish; topic: "home/light/set"; payload: "ON"` |
| `livekit_join` | Join a LiveKit room | `type: livekit_join` |
| `telegram` | Send Telegram message | `type: telegram; text: "Alert"` |
| `llm_chat` | Start LLM conversation | `type: llm_chat` |
| `llm_learn` | Teach new command via dialogue | `type: llm_learn` |
| `set_volume` | Adjust speaker volume | `type: set_volume; mode: absolute; value: 0.5` |
| `set_volume_from_transcript` | Parse volume from speech | `type: set_volume_from_transcript` |
| `calibrate_input_gain` | Voice-guided mic calibration | `type: calibrate_input_gain; sentence: "uno due tre"` |
| `record_and_playback` | Record and replay audio | `type: record_and_playback; params: {duration: 7.0}` |
| `meteo` | Weather forecast | `type: meteo; params: {city: "Verona"}` |
| `system_info` | System status report | `type: system_info` |
| `log` | Write to log | `type: log; message: "trigger fired"` |
| `tone` | Play audio tone | `type: tone; name: info` |
| `restart` | Restart the daemon | `type: restart` |
| `stop_listening` | Suspend wake detection | `type: stop_listening` |
| `start_listening` | Resume wake detection | `type: start_listening` |
| `ask` | Wait for voice reply and branch | `type: ask; text: "Vuoi chiamare?"; on_reply: [...]` |

### LLM Learning

When `llm_learn` is triggered:

1. Serena asks what command name to create
2. User speaks the phrase
3. Serena asks what action to perform
4. Dialogue continues until a complete trigger is built
5. The new trigger is appended to `conf/actions/learned.yaml`
6. The file is hot-reloaded automatically

---

## 8. Display Backends

Multiple display backends provide visual feedback on the Arduino UNO Q:

### LED Matrix (via RouterBridge)

- STM32 firmware in `setup/display_firmware/display_firmware.ino`
- Communication via `Arduino_RouterBridge` over UART → TCP port 7501
- Animated icons: scanning wave (listening), hourglass (thinking), checkmark (connected), cross (error)

**Flash firmware**:
```bash
arduino-cli lib install Arduino_RouterBridge ArduinoGraphics
arduino-cli compile --upload --fqbn arduino:zephyr:unoq \
  setup/display_firmware/display_firmware.ino
sudo systemctl restart arduino-router
```

**Router TCP port fix**: Some UNO Q board images have a systemd drop-in that removes the `--listen-port` flag. If `ss -tlnp | grep 7501` shows nothing, check `sudo systemctl cat arduino-router` for drop-ins.

### I2C OLED (SSD1306)

- Connect SSD1306 128×64 to Snapdragon I2C pins
- Backend: `i2c` in `config.yaml`
- Requires: `pip install smbus2`

### GPIO LEDs

- Uses `/sys/class/leds/`
- Works immediately on UNO Q (2 built-in MPU LEDs)

### UART Bridge

- Bypasses kernel driver via `/dev/mem` register access
- Compile: `gcc -o uart_bridge setup/display_firmware/uart_bridge.c`
- Run: `ALEXA_DISPLAY_CMD="sudo ./uart_bridge" alexa-client`

---

## 9. MQTT & Home Assistant

### Auto-Discovery

Serena uses Home Assistant's MQTT Discovery protocol to register itself automatically:
- **Media Player entity**: Shows call status and provides play/stop controls
- **Voice Assistant entity**: `conversation/agent` — accepts text commands and returns spoken responses

### Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Media Player | `media_player` | LiveKit call status, play/stop |
| Voice Assistant | `conversation/agent` | Text command input, spoken response |

### Bidirectional Communication

- **Outbound**: Voice commands forward to HA via MQTT (configured triggers with `mqtt_publish` action)
- **Inbound**: HA automations trigger local actions via MQTT messages

---

## 10. Web Dashboard

### Routes

| Route | Description |
|-------|-------------|
| `/` | Dashboard HTML |
| `/config` | Configuration panel (requires dev-mode toggle) |
| `/ws` | WebSocket for real-time updates |
| `/static/*` | Static assets (CSS, JS, favicon) |
| `/api/config` | GET/PUT config YAML |
| `/api/restart` | POST to restart daemon |
| `/api/history` | GET interaction history |

### WebSocket Events

Events streamed in real-time to the dashboard:

| Event | Payload | Description |
|-------|---------|-------------|
| `stt` | `{type, word, confidence}` | Wake word detection |
| `transcript` | `{text, partial}` | Speech-to-text transcription |
| `match` | `{phrase, score}` | Trigger match |
| `action` | `{type, status}` | Action execution |
| `room` | `{status, participants}` | LiveKit room state |
| `volume` | `{sink, source}` | Audio levels |
| `log` | `{level, message}` | Log entry |
| `cpu` | `{load, cores}` | System load |

### Configuration Panel

Access at http://localhost:8080/config (dev-mode toggle in sidebar):

- **Wake Words**: Add/remove individually with delete buttons
- **Recognition**: Adjust command timeout, matching thresholds, partial matching
- **STT**: Change backend and confidence thresholds per stage
- **Audio**: Set output volume (0–1) and input gain
- **TTS**: Choose backend (piper/pico) and voice

Features: client + server side validation, YAML comment preservation, file-locking for concurrent edit safety, hot-reload on save.

---

## 11. Development

### Running Tests

```bash
task test            # full regression suite
task test-stt-e2e    # end-to-end STT test (synthesises speech with Piper)
```

For targeted testing during development:

```bash
uv run pytest tests/test_wake_detection.py
uv run pytest tests/test_wake_detection.py -k "TestVoskCheckResult"
```

### Linting & Formatting

```bash
task lint            # ruff check + format --check
task format          # ruff format
task fix             # ruff fix + format + test (final validation)
```

### Release Process

Follows [Semantic Versioning](https://semver.org/):

| Bump | Command | When |
|------|---------|------|
| PATCH | `task release:patch` | Bug fixes, docs, refactors |
| MINOR | `task release:minor` | New backward-compatible features |
| MAJOR | `task release:major` | Breaking changes |

Rollback: `task release:rollback`

### Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `livekit` / `livekit-api` | core | LiveKit room client and REST API |
| `sounddevice` | core | Audio device enumeration only |
| `numpy` | core | Audio signal processing |
| `pulsectl` | core | PipeWire/PulseAudio routing |
| `vosk` | core | Local wake-word + STT |
| `pyyaml` | core | Config file parsing |
| `httpx` | core | HTTP client for LLM/Ollama |
| `aiomqtt` | core | MQTT / Home Assistant |
| `aiohttp` | core | Web dashboard server |
| `piper-tts` | core | Local text-to-speech |
| `rapidfuzz` | core | Fuzzy phonetic matching |
| `ruamel.yaml` | core | YAML round-trip editing (preserves comments) |
| `smbus2` | optional | I2C OLED display backend |

### Project Structure

```
├── alexa_custom/           # Main Python package
│   ├── client.py           # Main loop, LiveKit session, wake-word dispatch
│   ├── stt.py              # STT pipeline (Vosk)
│   ├── tts.py              # Text-to-speech (Piper)
│   ├── audio_hw.py         # Core audio state, PCM restore, routing
│   ├── audio_ops.py        # Playback operations (pw-play, WAV files, tones)
│   ├── audio_watcher.py    # Daemon thread monitoring PipeWire graph
│   ├── actions.py          # Action dispatcher
│   ├── config.py           # Typed config dataclasses and loaders
│   ├── config_manager.py   # Hot-reload config watcher
│   ├── mqtt.py             # MQTT client, Home Assistant Discovery
│   ├── web.py              # aiohttp web dashboard server
│   ├── dashboard.html      # Dashboard HTML (dark/light theme)
│   ├── display.py          # Display backends (bridge, gpio, i2c, mock)
│   ├── llm.py              # Ollama client, conversation engine
│   ├── record.py           # WAV recording utility
│   ├── stt_backends.py     # STT backend wrappers (Vosk)
│   ├── stt_capture.py      # Stage-2 command capture
│   ├── stt_gating.py       # Audio capture via parec, gating logic
│   ├── stt_phonetics.py    # Phonetic matching and normalization
│   └── static/             # Web assets (CSS, JS, favicon)
├── conf/                   # Live configuration (hot-reloaded)
├── conf.example/           # Example config templates
├── setup/                  # systemd service units, udev rules, firmware
├── docs/                   # Extended documentation
├── models/                 # STT/TTS model files (gitignored)
├── tests/                  # Regression tests
├── scripts/                # Utility scripts
├── pyproject.toml          # Package metadata and dependencies
└── Taskfile.yml            # Task automation
```

---

## 12. Troubleshooting

### Audio Issues

**No sound after boot**
```bash
amixer -c 0 sset PCM 100%        # restore hardware volume
task audio:status                # verify routing
```

**Audio drops mid-session**
```bash
task audio:restart               # restore routing and PCM
```

**Device not found**
```bash
alexa-devices                    # list available audio devices
lsusb | grep NewPie              # check USB detection
```

**No audio after `pulsectl.Pulse()` connection**
This is a known bug — PCM is reset by `pipewire-pulse`. The code handles this via `_restore_hw_pcm()`, but if you see silence after a routing change, run:
```bash
amixer -c 0 sset PCM 100%
```

### LiveKit Connection Issues

**Can't connect to room**
- Verify `conf/secrets.yaml` has the correct `url`, `api_key`, `api_secret`, and `room`
- Check network connectivity to the LiveKit server
- Ensure the room exists on the LiveKit project

**Room joins but no audio**
- Verify `wait_for_participant` setting — Serena only goes live when a remote participant is present
- Check the web dashboard room panel for participant count

### MQTT Issues

**Home Assistant not discovering entities**
- Verify MQTT broker settings in `conf/config.yaml` (MQTT section is commented out by default)
- Ensure the broker is reachable and credentials are correct
- Check HA logs for discovery events

### Permission Problems

**pw-play fails with permission error**
```bash
groups              # verify user is in 'audio' and 'pipewire' groups
sudo loginctl enable-linger $USER  # keep user service alive without login
```

**systemd service won't start**
```bash
journalctl --user -fu alexa-custom   # check logs
systemctl --user status alexa-custom  # check status
```

### Model Issues

**STT not working after setup**
```bash
alexa-setup --force                  # re-download models
ls models/                           # verify models directory contents
```

---

<p align="center">
  <a href="README.md">← Back to README</a>
</p>
