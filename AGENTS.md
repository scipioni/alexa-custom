# alexa-custom

LiveKit headless audio client turning a USB conference speakerphone into a voice-activated smart assistant. Runs as a systemd user service on the target board.

## Target environment

- **Board**: Arduino Uno Q (Qualcomm Snapdragon 801, aarch64)
- **Target OS**: Debian 13 (Trixie) — `apt` for system packages
- **Dev OS**: Arch Linux — `pacman`/`yay` for dev tools
- **Audio server**: PipeWire 1.4.2 with PulseAudio compatibility socket
- **Python**: ≥ 3.13 (Taskfile references 3.14 venv path)

## Git

When creating commits, do **not** add a `Co-Authored-By` trailer.

## Semantic Versioning

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (MAJOR.MINOR.PATCH).

| Bump type | When to use | Command |
|-----------|-------------|---------|
| **PATCH** (0.3.0 → 0.3.1) | Bug fixes, refactors, docs, performance — anything that doesn't add or remove public API | `task release:patch` |
| **MINOR** (0.3.0 → 0.4.0) | New features that are backward-compatible | `task release:minor` |
| **MAJOR** (1.0.0 → 2.0.0) | Breaking changes to API, configuration, or behaviour | `task release:major` |

Only commits prefixed with `feat:` or `fix:` appear in the auto-generated changelog entry.

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
alexa-client [--web-port PORT]             # main daemon (web dashboard with config panel)
serena                                   # alias for alexa-client
alexa-audio                              # mic→speaker loopback test
alexa-devices                            # list audio devices
alexa-setup                              # download/update STT models
serena-stt                               # STT diagnostic (same pipeline as daemon, live mic)
serena-stt --record FILE                 # record mic to WAV while listening
serena-stt --play FILE                   # replay saved WAV through STT pipeline
serena-stt --calibrate-gstreamer         # one-shot GStreamer parameter calibration (prints JSON)
serena-calibrate-mcp                     # MCP server for calibration (keeps Vosk resident; faster)
```

### Targeted Testing
The full test suite can take up to 40+ seconds to run. During iterative development, **do not run the full test suite**. Run only the specific test files or test cases relevant to your changes:
- Run a single test file:
  ```bash
  uv run pytest tests/test_wake_detection.py
  ```
- Run a specific test class or function:
  ```bash
  uv run pytest tests/test_wake_detection.py -k "TestVoskCheckResult"
  ```
Only use `task test` or `task fix` for final validation.

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
- **Use `pulsectl`** Python library — sets default sink/source, reacts to PipeWire graph events via `AudioWatcher`.

### `sounddevice` — allowed uses only
- `sd.query_devices()` for device listing (`alexa-audio --list`, speakerphone diagnostic).
- `sd.Stream` for the `speakerphone` loopback utility (isolated, no STT gate interaction).

## Host Audio Management & Workarounds

This headless host runs a modern **PipeWire** audio graph managed by **WirePlumber**. To keep audio routing and hardware stable, keep these core behaviors in mind:

### 0. Yealink SP92 / BT51 Device Profile

#### SP92 (direct USB)
- **Correct profile**: `pro-audio` — the only profile that exposes the built-in microphone array. `output:analog-stereo+input:mono-fallback` maps to the headset jack only (all-zero if nothing plugged in).
- **pro-audio places nodes under Filters, not Sources** — PulseAudio clients (`parec`, `pulsesrc`) connect but receive all-zero audio because PipeWire never transitions the Filter node out of SUSPENDED for PA clients. **Do not use `parec` or `pulsesrc` to capture from the SP92.**
- **Correct capture backend**: `pipewiresrc` via `gst-launch-1.0` subprocess. `gst-launch-1.0` runs its own GLib main loop so `pipewiresrc` can target Filter nodes directly. Set `gst_profile: yealink` in `conf/state.yaml`. The daemon dispatches to `_start_capture_gst_subprocess()` when `source: pipewiresrc`.
- **USB audio topology**: Capture PCM from OutputTerminal 7 ← FeatureUnit 6 ← InputTerminal 5 (Echo-canceling speakerphone, 0x0405). Onboard DSP always active — NS and beamforming applied before USB.
- **No ALSA capture gain control** for the built-in mic path (`amixer sget Headset` targets the sidetone path, not the main capture stream). Use WebRTC AGC in the yealink GStreamer profile.
- `task audio:setup` sets `pro-audio` profile when a Yealink card is detected.

#### BT51 (USB Bluetooth dongle paired with SP92)
- **Device class**: USB Audio class (`bInterfaceClass 1`), NOT a USB Bluetooth adapter. The Bluetooth link between BT51 and SP92 is managed entirely by the BT51 firmware — Linux BlueZ has no visibility into it and cannot control the HFP state.
- **PipeWire placement**: BT51 input appears under **Audio/Source** (not Filters) — `pulsesrc` works directly. Native format: `s16le 1ch 16000Hz` (HFP wideband).
- **Correct profile**: `output:analog-stereo+input:mono-fallback` — this activates both the speaker (analog-stereo) and microphone (mono-fallback) paths. The "Headset Microphone" port in this profile is the SP92 Bluetooth mic (not a physical headset jack). **Do NOT use `pro-audio`** for BT51: the Bluetooth SCO audio link goes idle when nothing plays through the sink, causing the capture to return only USB clock noise.
- **Bluetooth link activation**: The BT51 maintains the Bluetooth audio link as long as either the sink or the source is active. The daemon's continuous capture (always-on STT) is sufficient to keep it alive once opened. `task audio:setup` sets `output:analog-stereo+input:mono-fallback` when a Yealink card is detected.
- **USB clock artifacts**: When the Bluetooth SCO link is idle at startup, the capture stream briefly contains narrowband interference at 128 Hz, 175 Hz, and 390 Hz (USB superframe harmonics). The `highpass_cutoff_hz: 220` setting in the yealink profile uses `audiocheblimit` (4-pole Chebyshev HPF) to reject the 128/175 Hz artifacts. `audiocheblimit` requires F32LE format — the pipeline converts with surrounding `audioconvert` elements.
- **AGC must be disabled** (`agc: false` in the yealink profile): WebRTC AGC amplifies the noise floor when no real speech arrives, causing 128/175 Hz artifacts to grow from inaudible to peak 0.49 in 8 seconds. SP92 hardware AGC handles level normalisation.
- **GStreamer profile: `yealink`** — `source: pulsesrc`, NS disabled, AGC disabled, `highpass_cutoff_hz: 220`. Set in `conf/state.yaml` (`gst_profile: yealink`).

### 1. NewPie Device Profile
- **Prefer `output:analog-stereo+input:analog-stereo`** — with this profile, both sink and source appear under **Sources/Sinks** in `wpctl status` and are managed by WirePlumber's session policy — PulseAudio clients (parec, pulsesrc in GStreamer) can wake them on demand.
- **If the combined profile is unavailable** (e.g. NewPie 32, USB 2757:4010), fall back to `pro-audio` — on that hardware revision nodes still appear under **Sources/Sinks**, not Filters, so PulseAudio clients work correctly.
- **Do not use `pro-audio` on the original NewPie** (USB 0a12:1260) — it places nodes under **Filters**, not **Sources**. PulseAudio clients connect but the node stays **suspended** and emits no audio. This silently breaks the STT capture pipeline and all `parec`/`pulsesrc`/`pw-record` capture.
- `task audio:setup` handles profile selection automatically: tries `output:analog-stereo+input:analog-stereo` first, falls back to `pro-audio`.
- **Use `pulsesrc`** for the GStreamer capture pipeline (`audio.gstreamer.source`). `pipewiresrc` stalls after the first 10 ms buffer when driven from Python — GStreamer's PipeWire source requires a GLib main loop that isn't running in the daemon. `pulsesrc` (PulseAudio compat socket) is the reliable choice. `pipewiresrc` only works from `gst-launch-1.0` which runs its own GLib main loop.

### 2. The ALSA Hardware Mixer Reset Bug (Crucial)
- **Problem**: When PipeWire initializes and takes ownership of the ALSA device (on boot or restart), the kernel driver resets the NewPie's `PCM` mixer to `0%`.
- **Why `alsa-restore.service` is not enough**: it runs before PipeWire starts, so PipeWire's init overwrites it. `sudo alsactl store` alone does not solve the boot-time reset.
- **The Permanent Fix**: `task audio:setup` installs `~/.config/systemd/user/alsa-pcm-unmute.service`, which polls until NewPie appears in `pactl list cards`, forces NewPie as default routing, then unmutes the hardware volume every 2 seconds for 20 seconds — catching WirePlumber's late ACP profile reset which happens silently a few seconds after the device appears. Run once:
  ```bash
  task audio:setup
  ```
- **Workaround (adhoc)**: To manually restore volume in a live session (card number resolved dynamically):
  ```bash
  CARD_NUM=$(grep -m1 "NewPie" /proc/asound/cards | awk '{print $1}')
  amixer -c "${CARD_NUM:-0}" sset PCM 100% 2>/dev/null || amixer -c "${CARD_NUM:-0}" sset 'Playback Volume' 100%
  ```
- **Note on mixer control name**: Original NewPie exposes a `PCM` control; NewPie 32 exposes `Playback Volume`. Both `task audio:setup` and `alsa-pcm-unmute.service` try `PCM` first and fall back to `Playback Volume` automatically.

### 3. Late Boot Routing (USB device discovered after PipeWire starts)
- **Problem**: NewPie is discovered slightly after PipeWire/WirePlumber start; WirePlumber falls back to HDMI and does not reliably switch when NewPie later appears, even with persistent default-device state saved.
- **Fix**: The `alsa-pcm-unmute.service` (see section 2) handles this too — it polls until NewPie appears, then calls `pw-metadata` to force it as the active sink/source.
- **`libpipewire-module-switch-on-connect` is NOT available** on this board's PipeWire 1.4.2 build. The `ifexists nofail` conf flag does not work on this build — it still crashes PipeWire and `pipewire-pulse`. `task audio:setup` actively removes any stale `99-switch-on-connect.conf` drop-ins from `~/.config/pipewire/`.

### 4. Mid-Session Audio Loss (USB Autosuspend)
- **Problem**: Linux suspends the NewPie USB device after inactivity; PipeWire reinitializes it on wake, resetting PCM to 0% and dropping routing — same symptoms as the boot-time bug but mid-session.
- **Fix**: `task audio:setup` installs `setup/99-newpie-no-autosuspend.rules` to `/etc/udev/rules.d/`, setting `autosuspend_delay_ms=-1` for any device whose USB product name matches `NewPie*` (covers all hardware revisions).
- **Ad-hoc recovery**: `task audio:restart`.

### 5. pulsectl Triggers PCM Reset (Critical for Python Code)
- **Problem**: Opening any `pulsectl.Pulse()` connection causes pipewire-pulse to re-initialise the ALSA device, resetting the NewPie's hardware PCM mixer to 0% — making all subsequent audio silent even though `pw-play file.wav` from the shell works fine.
- **Fix**: Call `_restore_hw_pcm()` immediately after any pulsectl context closes — it resolves the NewPie card dynamically (no hardcoded card 0) and runs `amixer -c <card> sset PCM 100%`:
  - After closing any `pulsectl.Pulse()` context (outside the `with` block).
  - Inside `AudioWatcher.run()` right after opening the watcher connection.
  - Inside `AudioWatcher._check_and_enforce()` on device connect.
  - Inside `set_input_gain()` before calling `pactl set-source-volume`.
- **Rule**: Never open a `pulsectl.Pulse()` connection without calling `_restore_hw_pcm()` right after. The daemon no longer calls `wpctl set-volume`; output volume is applied digitally in software instead.

### 6. pw-play Raw Stdin Unreliable on This Board
- **Problem**: `pw-play --raw --rate N --format f32 -` exits 0 but produces no audio on PipeWire 1.4.2. `-a` (media-type flag) requires an argument and causes pw-play to exit with error, also silently swallowed.
- **Fix**: `_play_array()` and `_play_raw()` write a temporary s16le WAV file and call `pw-play <tmp.wav>`. Temp file is deleted after playback. Never pipe raw audio to pw-play stdin.

### 7. Automated Audio Tasks
- Run once after first boot: `task audio:setup` — sets default routing, unmutes PCM, installs `alsa-pcm-unmute.service`, disables USB autosuspend.
- `task audio:restart`: restarts WirePlumber and restores NewPie routing/PCM (use when audio drops mid-session).
- `task audio:status`: displays a status dashboard for the NewPie.
- `task audio:test`: plays a test WAV to verify speaker output.

## Project structure

```
alexa_custom/
  client.py           main loop, LiveKit session, wake-word dispatch
  stt.py              speech-to-text pipeline (Vosk)
  stt_cli.py          serena-stt entry point (diagnostic + calibration modes)
  stt_backends.py     Vosk backend abstraction
  stt_gating.py       RMS/VAD gating, capture source resolution
  stt_gst_capture.py  GStreamer capture pipeline
  tts.py              text-to-speech (Piper)
  audio.py            PipeWire routing, AudioWatcher, device enumeration
  audio_ops.py        low-level playback helpers (pw-play, tones)
  mcp_calibrate.py    serena-calibrate-mcp MCP server (keeps Vosk resident)
  mqtt.py             MQTT client, Home Assistant Discovery
  actions.py          action dispatcher (livekit_join, ask, telegram, …)
  config.py           config dataclasses
  config_manager.py   hot-reload watcher (~4 s polling)
  web.py              aiohttp web dashboard
conf/               live config (gitignored; copy from conf.example/)
conf.example/       example config shipped with the repo
models/             bundled STT/TTS model files
docs/               extended notes (audio platform, hardware, setup)
  stt-simple.md     STT pipeline, GStreamer calibration, config reference
kernel/             kernel build scripts/configs for the board
setup/              systemd service unit
.claude/
  settings.json     MCP server registration (serena-calibrate, headroom)
  skills/           agent skills (calibrate-gstreamer, …)
```

## Configuration

Split across two locations — both hot-reloaded while the daemon is running:

`conf/config.yaml` — system settings and wake words:
```yaml
wake_words:
  - "ehi galileo"          # flat list of wake phrases
recognition:
  wake_window: 8.0         # seconds to listen after wake word
stt:
  backend: vosk            # vosk (single always-on model)
  vad_silence_ms: 900
```

`conf/actions/user.yaml` — triggers (and optional extra wake phrases):
```yaml
wake_words:                  # extra phrases added to the flat wake list
  - "aiuto"

triggers:
  - commands:
      - "chiama"             # with_wake absent → fires after any wake word
    actions:
      - type: livekit_join

  - commands:
      - "chiama Stefano"
    with_wake: false         # direct match — fires without a wake word
    actions:
      - type: livekit_join

  - commands:
      - "chiama assistenza"  # with_wake: true (default) — fires after any wake word
    actions:
      - type: livekit_join
```

### Web Configuration Panel

Access via the web dashboard (http://localhost:8080/config):
- **Wake Words**: Add/remove wake phrases (flat string list)
- **Recognition**: Adjust wake window, matching thresholds
- **Speech-to-Text**: Change STT backend, RMS threshold, adaptive RMS
- **Audio**: Set output volume and input gain
- **Text-to-Speech**: Configure TTS backend and voice

**Features**:
- Developer-only feature (controlled by dev-mode toggle)
- Real-time validation before saving
- Hot-reload on save (restarts daemon)
- Reset button to restore original values
- Preserves YAML formatting and comments
- File locking prevents concurrent edits

## Key dependencies

| Package | Role |
|---------|------|
| `livekit` / `livekit-api` | LiveKit room client |
| `vosk` | local wake-word + STT |
| `piper-tts` | local TTS |
| `pulsectl` | PipeWire/PulseAudio routing |
| `sounddevice` | device enumeration only |
| `aiomqtt` | MQTT / Home Assistant |
| `aiohttp` | web dashboard |
| `mcp` *(optional: `[calibrate]`)* | MCP server for `serena-calibrate-mcp` |
| `PyGObject` *(optional: `[gstreamer]`)* | GStreamer Python bindings for capture pipeline |
