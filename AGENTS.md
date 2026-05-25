# alexa-custom

LiveKit headless audio client turning a USB conference speakerphone into a voice-activated smart assistant. Runs as a systemd user service on the target board.

## Target environment

- **Board**: Arduino Uno Q (Qualcomm Snapdragon 801, aarch64)
- **Target OS**: Debian 13 (Trixie) — `apt` for system packages
- **Dev OS**: Arch Linux — `pacman`/`yay` for dev tools
- **Audio server**: PipeWire 1.4.2 with PulseAudio compatibility socket
- **Python**: ≥ 3.13 (Taskfile references 3.14 venv path)

## Commands

```bash
task test          # run pytest
task lint          # ruff check + format --check
task format        # ruff format
task fix           # ruff fix + format + test
task run           # run alexa-client directly
task setup         # install systemd user service
```

Manual entry points:
```bash
alexa-client [--web] [--web-port PORT]   # main daemon
alexa-audio                              # mic→speaker loopback test
alexa-devices                            # list audio devices
alexa-setup                              # download/update STT models
```

## Audio I/O constraints (Arduino Uno Q)

PortAudio (used by `sounddevice` and `PyAudio`) has **no native PipeWire backend** on this board — it was compiled with ALSA only. The ALSA→PipeWire shim causes `sd.play()` + `sd.wait()` to **block forever**. Do not use PortAudio for any production I/O path.

### Playback
- **Use `pw-play`** (native PipeWire client) — connects directly to `/run/user/1000/pipewire-0`, exits cleanly when done.
- **Fallback**: `aplay -D pipewire` if `pw-play` is absent.
- Never use `sd.play()` / `PyAudio` streams for playback.

### Capture
- **Use `parec`** (pulseaudio-utils) — speaks the PulseAudio compat socket at `/run/user/1000/pulse/native`, addresses the USB NewPie mic by name, streams raw `s16le` 16 kHz stereo to stdout.
- Fallback: `pw-record`.
- Never use `sounddevice` or `PyAudio` for capture.

### Routing / device management
- **Use `pulsectl`** Python library — sets default sink/source, enforces the `pro-audio` profile on the USB card, reacts to PipeWire graph events via `AudioWatcher`.

### `sounddevice` — allowed uses only
- `sd.query_devices()` for device listing (`alexa-audio --list`, speakerphone diagnostic).
- `sd.Stream` for the `speakerphone` loopback utility (isolated, no STT gate interaction).

## Project structure

```
alexa_custom/
  client.py       main loop, LiveKit session, wake-word dispatch
  stt.py          speech-to-text pipeline (Vosk + sherpa-onnx)
  tts.py          text-to-speech (Piper)
  audio.py        PipeWire routing, AudioWatcher, device enumeration
  mqtt.py         MQTT client, Home Assistant Discovery
  actions.py      action dispatcher (livekit_join, ask, telegram, …)
  config.py       config dataclasses
  config_manager.py  hot-reload watcher (~4 s polling)
  web.py          aiohttp web dashboard
config.yaml       live config (credentials, triggers, wake words)
config.yaml.example
models/           bundled STT/TTS model files
docs/             extended notes (audio platform, hardware, setup)
kernel/           kernel build scripts/configs for the board
setup/            systemd service unit
```

## Configuration

Single `config.yaml` — hot-reloaded while the daemon is running:

```yaml
env:
  LIVEKIT_URL: wss://...
  LIVEKIT_API_KEY: ...
wake_words: [galileo]
command_timeout: 3.0
triggers:
  - phrase: "chiama"
    actions:
      - type: livekit_join
```

## Key dependencies

| Package | Role |
|---------|------|
| `livekit` / `livekit-api` | LiveKit room client |
| `vosk` | local wake-word + STT |
| `sherpa-onnx` | alternative STT backend |
| `piper-tts` | local TTS |
| `pulsectl` | PipeWire/PulseAudio routing |
| `sounddevice` | device enumeration only |
| `aiomqtt` | MQTT / Home Assistant |
| `aiohttp` | web dashboard |
