# Software Installation

## Prerequisites

- **Python**: 3.13+
- **Audio**: PipeWire 1.x + WirePlumber 0.5.x
- **Libraries**: `pulseaudio-utils`, `alsa-utils`

---

## 1. System Dependencies

```bash
# Core dependencies
sudo apt-get install pulseaudio-utils alsa-utils python3-venv

# GStreamer backend (optional, for stt.capture_backend: gstreamer)
sudo apt-get install gstreamer1.0-plugins-bad  gstreamer1.0-pulseaudio \
                     gstreamer1.0-pipewire   gir1.2-gstreamer-1.0   \
                     libgstreamer1.0-dev      python3-gst-1.0

# Enable user lingering
sudo loginctl enable-linger $(whoami)

# Install Task runner
curl -1sLf 'https://dl.cloudsmith.io/public/task/task/setup.deb.sh' | sudo -E bash
sudo apt install task
```

---

## 2. Virtual Environment & Package

```bash
git clone <repo-url> && cd serena/
python3 -m venv .venv
source .venv/bin/activate
pip install uv
uv pip install -e .                     # base install
# uv pip install -e ".[gstreamer]"       # with GStreamer backend
# uv pip install -e ".[i2c]"             # with I2C display support
```

---

## 3. Configuration

```bash
cp conf.example/config.yaml conf/config.yaml
cp conf.example/secrets.yaml conf/secrets.yaml
cp conf.example/actions/user.yaml conf/actions/user.yaml
cp conf.example/actions/system.yaml conf/actions/system.yaml
```

Edit `conf/secrets.yaml` with your credentials. See [`docs/configuration.md`](configuration.md) for all options.

---

## 4. STT Models

```bash
alexa-setup                 # downloads default small Italian Vosk model
alexa-setup --large         # high-accuracy model (~1.2 GB)
alexa-setup --force         # overwrite existing model
```

---

## 5. Audio Setup (NewPie USB speakerphone)

```bash
task audio:setup             # configures routing, PCM volume, autosuspend
task audio:status            # verify NewPie is detected and configured
task audio:test              # play test WAV
```

---

## 6. Verification

```bash
# Loopback test
alexa-audio

# List audio devices
alexa-devices

# Audio diagnostics
alexa-audio-doctor

# Run the daemon
serena --hot-reload          # or: alexa-client
```

---

## 7. CLI Commands Reference

| Command | Entry point | Description |
|---|---|---|
| `alexa-client [--web-port PORT]` | `client.py:main` | Main daemon |
| `serena` | `client.py:main` | Alias for alexa-client |
| `alexa-audio [--list]` | `audio.py:main` | Speakerphone loopback / device list |
| `alexa-devices` | `audio.py:main_devices` | List all audio devices |
| `serena-test` | `audio.py:main_test` | Audio test utility |
| `alexa-setup [--large] [--force]` | `setup.py:main` | Download STT/TTS models |
| `alexa-audio-setup` | `audio.py:setup_audio` | Configure audio routing |
| `alexa-audio-doctor` | `audio.py:main_doctor` | Audio diagnostics |
| `alexa-wake-eval` | `wake_eval.py:main` | Wake word evaluation |
| `alexa-record` | `record.py:main` | Record audio |
| `serena-stt` | `stt_cli.py:main` | STT CLI utility |

---

## 8. Task Commands Reference

### Development

| Task | Description |
|---|---|
| `task test` | Run pytest |
| `task test-stt-e2e` | End-to-end STT test |
| `task eval [-- --sweep]` | Score wake+command matching |
| `task lint` | ruff check + format --check |
| `task format` | ruff format |
| `task fix` | ruff fix + format + test |
| `task run [--args]` | Run daemon directly |
| `task start` | Start with hot-reload (`serena --hot-reload`) |
| `task clean` | Clean temp files |

### Audio

| Task | Description |
|---|---|
| `task audio:setup` | Configure NewPie routing, PCM, autosuspend |
| `task audio:restart` | Restart WirePlumber + restore PCM |
| `task audio:status` | NewPie status dashboard |
| `task audio:doctor` | Check audio invariants (pass/fail) |
| `task audio:test` | Play test WAV |

### Display

| Task | Description |
|---|---|
| `task display:compile` | Compile uart_bridge |
| `task display:test` | Test UART communication |
| `task display:setup` | Compile + sudoers entry |
| `task display:flash` | Flash STM32 display firmware |

### STT

| Task | Description |
|---|---|
| `task stt:analyze-dumps [--args]` | Analyze trigger-dump WAVs |

### Release

| Task | Description |
|---|---|
| `task release:patch` | Bump x.y.Z+1, commit, tag |
| `task release:minor` | Bump x.Y+1.0, commit, tag |
| `task release:major` | Bump X+1.0.0, commit, tag |
| `task release:rollback` | Delete latest tag, revert commit |

### Setup

| Task | Description |
|---|---|
| `task setup` | Install systemd user service |
| `task setup:gstreamer` | Install GStreamer packages + PyGObject |

---

## 9. Systemd Service

```bash
task setup                           # install service
systemctl --user start serena        # start
systemctl --user stop serena         # stop
systemctl --user status serena       # check status
journalctl --user -fu serena         # follow logs
```
