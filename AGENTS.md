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
task run           # run serena-client directly
task setup         # install systemd user service
```

Manual entry points:
```bash
serena-client [--web-port PORT]            # main daemon (web dashboard with config panel)
serena                                   # alias for serena-client
serena-audio                             # mic→speaker loopback test
serena-devices                           # list audio devices
serena-setup                             # download/update STT models
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
- `sd.query_devices()` for device listing (`serena-audio --list`, speakerphone diagnostic).
- `sd.Stream` for the `speakerphone` loopback utility (isolated, no STT gate interaction).

## Host Audio Management & Workarounds

This headless host runs a modern **PipeWire** audio graph managed by **WirePlumber**. To keep audio routing and hardware stable, keep these core behaviors in mind:

### Device-agnostic USB audio detection

The audio stack does not hardcode product names — everything matches "any USB audio device", so swapping the conference hardware (NewPie → Yealink → EMEET OfficeCore Luna) requires no config edits: plug it in and run `task audio:restart` (or reboot).

- **PipeWire objects**: USB audio cards/nodes are always named `alsa_card.usb-*` / `alsa_input.usb-*` / `alsa_output.usb-*` — the Taskfile, `setup/usb-audio-restore.sh`, and the WirePlumber no-suspend rule match on these prefixes.
- **ALSA**: USB sound cards expose `/proc/asound/cardN/usbid` — used by `_find_alsa_card("auto")`.
- **udev/sysfs**: USB audio devices carry an audio-class (`01`) interface — used by `setup/99-usb-audio-no-autosuspend.rules` and `setup/usb-audio-autosuspend.service`.
- **Daemon config**: `audio.card_name/input_device/output_device: auto` resolves to the first USB card/source/sink. A name substring still works to pin a specific device.
- **Profile selection** (`setup/usb-audio-restore.sh`, installed to `~/.local/bin/serena-usb-audio-restore` by `task audio:setup`): prefers `output:analog-stereo+input:analog-stereo`, then `output:analog-stereo+input:mono-fallback`, then any other combined `output:*+input:*` profile, then `pro-audio`. The choice is written to WirePlumber's state file (`~/.local/state/wireplumber/default-profile`) so it persists across reboots. At boot the restore service **respects an existing entry** in that state file, so a manual override (e.g. `pro-audio` for a direct-USB SP92) survives; `task audio:setup` re-runs selection and overwrites it.
- **Keep-alive**: `audio.keep_sink_alive: auto` starts a background silent stream when the output is a USB sink, keeping Bluetooth-dongle radio links (BT51-style) awake.

Device-specific quirks below still apply when that hardware is present.

### 0. Yealink SP92 / BT51 Device Profile

#### SP92 (direct USB)
- **Correct profile**: `pro-audio` — the only profile that exposes the built-in microphone array. `output:analog-stereo+input:mono-fallback` maps to the headset jack only (all-zero if nothing plugged in).
- **pro-audio places nodes under Filters, not Sources** — PulseAudio clients (`parec`, `pulsesrc`) connect but receive all-zero audio because PipeWire never transitions the Filter node out of SUSPENDED for PA clients. **Do not use `parec` or `pulsesrc` to capture from the SP92.**
- **Correct capture backend**: `pipewiresrc` via `gst-launch-1.0` subprocess. `gst-launch-1.0` runs its own GLib main loop so `pipewiresrc` can target Filter nodes directly. Set `gst_profile: yealink` in `conf/state.yaml`. The daemon dispatches to `_start_capture_gst_subprocess()` when `source: pipewiresrc`.
- **USB audio topology**: Capture PCM from OutputTerminal 7 ← FeatureUnit 6 ← InputTerminal 5 (Echo-canceling speakerphone, 0x0405). Onboard DSP always active — NS and beamforming applied before USB.
- **No ALSA capture gain control** for the built-in mic path (`amixer sget Headset` targets the sidetone path, not the main capture stream). Use WebRTC AGC in the yealink GStreamer profile.
- `task audio:setup` selects the best combined `output:*+input:*` profile automatically (for BT51 that is `output:analog-stereo+input:mono-fallback`) and writes it to `~/.local/state/wireplumber/default-profile` (WirePlumber's state file). `pactl set-card-profile` cannot set some combined profiles by name on PipeWire 1.4.x — it returns "No such entity" and would silently fall back to `pro-audio`. For SP92 direct USB, set `pro-audio` manually after `task audio:setup` — the boot-time restore service respects the manual choice:
  ```bash
  pactl set-card-profile "$(pactl list cards short | grep -i Yealink | cut -f2 | head -1)" pro-audio
  ```

#### BT51 (USB Bluetooth dongle paired with SP92)
- **Device class**: USB Audio class (`bInterfaceClass 1`), NOT a USB Bluetooth adapter. The Bluetooth link between BT51 and SP92 is managed entirely by the BT51 firmware — Linux BlueZ has no visibility into it and cannot control the HFP state.
- **PipeWire placement**: BT51 input appears under **Audio/Source** (not Filters) — `pulsesrc` works directly. Native format: `s16le 1ch 16000Hz` (HFP wideband).
- **Correct profile**: `output:analog-stereo+input:mono-fallback` — this activates both the speaker (analog-stereo) and microphone (mono-fallback) paths. The "Headset Microphone" port in this profile is the SP92 Bluetooth mic (not a physical headset jack). **Do NOT use `pro-audio`** for BT51: the Bluetooth SCO audio link goes idle when nothing plays through the sink, causing the capture to return only USB clock noise.
- **Bluetooth link activation**: The BT51 maintains the Bluetooth audio link as long as either the sink or the source is active. The daemon's continuous capture (always-on STT) is sufficient to keep it alive once opened. `task audio:setup` writes `output:analog-stereo+input:mono-fallback` to WirePlumber's state file for any detected Yealink card, so the profile persists across reboots.
- **USB clock artifacts**: When the Bluetooth SCO link is idle at startup, the capture stream briefly contains narrowband interference at 128 Hz, 175 Hz, and 390 Hz (USB superframe harmonics). The `highpass_cutoff_hz: 220` setting in the yealink profile uses `audiocheblimit` (4-pole Chebyshev HPF) to reject the 128/175 Hz artifacts. `audiocheblimit` requires F32LE format — the pipeline converts with surrounding `audioconvert` elements.
- **AGC must be disabled** (`agc: false` in the yealink profile) — two independently verified failure modes:
  1. WebRTC AGC amplifies the noise floor when no real speech arrives, causing 128/175 Hz artifacts to grow from inaudible to peak 0.49 in 8 seconds.
  2. **First-command-after-idle garbling** (verified via trigger dumps 2026-07-03): during idle the SP92's hardware noise gate sends *digital zeros*; WebRTC AGC winds its gain to maximum, and the first utterance after minutes of silence arrives overshot/clipped (onset peak 0.99 vs 0.78 normal, RMS decaying 0.36→0.22 while AGC re-adapts) — Vosk mangles the leading word ("che ore sono" → "il ore sono" / "eur solo"). The second attempt always works because AGC has re-adapted. If this symptom reappears, check that `agc: true` hasn't crept back in via `conf/state.yaml`'s `gstreamer_override` (web-UI calibration writes there and it overrides the profile).

  SP92 hardware AGC handles level normalisation; use `audio.input_gain` (PulseAudio source volume) for extra gain, not WebRTC AGC.
- **GStreamer profile: `yealink`** — `source: pulsesrc`, NS disabled, AGC disabled, `highpass_cutoff_hz: 220`. Set in `conf/state.yaml` (`gst_profile: yealink`).

#### Serena configuration

Both SP92 and BT51 use the same named GStreamer profile (`yealink`) but with different `source` values and PipeWire profiles.

**BT51 (USB Bluetooth dongle) — recommended setup:**

1. Plug in BT51 (pair SP92 first via its own pairing button).
2. Run `task audio:setup` — detects the USB audio card, selects `output:analog-stereo+input:mono-fallback` (best available combined profile), installs no-suspend rule.
3. In `conf/state.yaml`, set the active profile:
   ```yaml
   gst_profile: yealink
   ```
4. In `conf/config.yaml`, confirm the yealink profile uses `pulsesrc` (default):
   ```yaml
   audio:
     gstreamer:
       profiles:
         yealink:
           source: pulsesrc
           agc: false
           highpass_cutoff_hz: 220
   ```
5. Restart the daemon — BT51 input appears under Sources, `pulsesrc` connects directly, HPF rejects USB clock artifacts on startup.

**SP92 (direct USB, no BT51) — manual steps:**

1. Plug SP92 directly via USB.
2. Run `task audio:setup` (auto-selects `output:analog-stereo+input:mono-fallback` — wrong for SP92, fix below).
3. Manually set the correct profile (persisted by WirePlumber; the boot-time restore service respects it):
   ```bash
   pactl set-card-profile "$(pactl list cards short | grep -i Yealink | cut -f2 | head -1)" pro-audio
   ```
4. In `conf/state.yaml`:
   ```yaml
   gst_profile: yealink
   ```
5. In `conf/config.yaml`, override the yealink profile to use `pipewiresrc` (required for Filter nodes):
   ```yaml
   audio:
     gstreamer:
       profiles:
         yealink:
           source: pipewiresrc
           noise_suppression: false
           agc: true          # SP92-direct has no usable capture gain control, so WebRTC
           #   AGC is the only leveling option here. CAUTION (untested on SP92-direct):
           #   if the first command after idle comes out garbled, this is the same
           #   AGC-winds-up-on-digital-zeros failure verified on BT51 — prefer
           #   agc: false + higher audio.input_gain.
           highpass_cutoff_hz: 0
   ```
6. Restart the daemon — SP92 node appears under Filters, `gst-launch-1.0` subprocess with `pipewiresrc` captures real audio.

### 1. NewPie Device Profile
- **Prefer `output:analog-stereo+input:analog-stereo`** — with this profile, both sink and source appear under **Sources/Sinks** in `wpctl status` and are managed by WirePlumber's session policy — PulseAudio clients (parec, pulsesrc in GStreamer) can wake them on demand.
- **If the combined profile is unavailable** (e.g. NewPie 32, USB 2757:4010), fall back to `pro-audio` — on that hardware revision nodes still appear under **Sources/Sinks**, not Filters, so PulseAudio clients work correctly.
- **Do not use `pro-audio` on the original NewPie** (USB 0a12:1260) — it places nodes under **Filters**, not **Sources**. PulseAudio clients connect but the node stays **suspended** and emits no audio. This silently breaks the STT capture pipeline and all `parec`/`pulsesrc`/`pw-record` capture.
- `task audio:setup` handles profile selection automatically: tries `output:analog-stereo+input:analog-stereo` first, falls back to `pro-audio`.
- **Use `pulsesrc`** for the GStreamer capture pipeline (`audio.gstreamer.source`). `pipewiresrc` stalls after the first 10 ms buffer when driven from Python — GStreamer's PipeWire source requires a GLib main loop that isn't running in the daemon. `pulsesrc` (PulseAudio compat socket) is the reliable choice. `pipewiresrc` only works from `gst-launch-1.0` which runs its own GLib main loop.

### 2. The ALSA Hardware Mixer Reset Bug (Crucial)
- **Problem**: When PipeWire initializes and takes ownership of the ALSA device (on boot or restart), the kernel driver resets the NewPie's `PCM` mixer to `0%`.
- **Why `alsa-restore.service` is not enough**: it runs before PipeWire starts, so PipeWire's init overwrites it. `sudo alsactl store` alone does not solve the boot-time reset.
- **The Permanent Fix**: `task audio:setup` installs `~/.config/systemd/user/alsa-pcm-unmute.service`, which runs `~/.local/bin/serena-usb-audio-restore`: polls until a USB audio card appears in `pactl list cards`, applies the persisted card profile, forces the USB device as default routing, then re-applies 100%/unmute to every volume-capable mixer control every 2 seconds for 20 seconds — catching WirePlumber's late ACP profile reset which happens silently a few seconds after the device appears. Run once:
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
- **Fix**: The `alsa-pcm-unmute.service` (see section 2) handles this too — it polls until the USB audio device appears (with WirePlumber-restart retries for slow Bluetooth-dongle links), then calls `pw-metadata` to force it as the active sink/source.
- **`libpipewire-module-switch-on-connect` is NOT available** on this board's PipeWire 1.4.2 build. The `ifexists nofail` conf flag does not work on this build — it still crashes PipeWire and `pipewire-pulse`. `task audio:setup` actively removes any stale `99-switch-on-connect.conf` drop-ins from `~/.config/pipewire/`.

### 4. Mid-Session Audio Loss (USB Autosuspend)
- **Problem**: Linux suspends the NewPie USB device after inactivity; PipeWire reinitializes it on wake, resetting PCM to 0% and dropping routing — same symptoms as the boot-time bug but mid-session.
- **Fix**: `task audio:setup` installs `setup/99-usb-audio-no-autosuspend.rules` to `/etc/udev/rules.d/`, setting `autosuspend_delay_ms=-1` for any USB device exposing an audio-class interface (device-agnostic — covers NewPie, Yealink, EMEET, ...). A boot-time system service (`usb-audio-autosuspend.service`) applies the same setting after multi-user.target for devices already connected at power-on.
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
- Run once after first boot: `task audio:setup` — sets default routing, unmutes hardware mixers, installs `alsa-pcm-unmute.service`, disables USB autosuspend.
- `task audio:restart`: restarts WirePlumber and restores USB audio routing/mixer levels (use when audio drops mid-session).
- `task audio:status`: displays a status dashboard for the connected USB audio device.
- `task audio:doctor`: checks every audio invariant and reports pass/fail.
- `task audio:test`: plays a test WAV to verify speaker output.

### 8. Testing hot-plug behaviour (replug ≠ unbind)
- `echo <dev> > /sys/bus/usb/drivers/usb/unbind` / `bind` removes the ALSA/PipeWire card but does **NOT** emit udev `ACTION=="add"` events and does not reset `power/` attributes — it tests PipeWire recovery only, not the udev rules.
- To exercise the udev path (autosuspend + the `SYSTEMD_USER_WANTS=alsa-pcm-unmute.service` replug trigger): `sudo udevadm trigger --action=add /sys/bus/usb/devices/<dev>`.
- On physical replug, WirePlumber can bring the card up with an **output-only profile** (input marked unavailable while a Bluetooth dongle relinks) — the udev-triggered restore service run is what repairs profile + routing.

## STT recognition & latency notes

- **Latency budget**: perceived response ≈ silence-endpoint wait + ~130 ms Vosk decode. `stt.vad_silence_ms: 900` is the fragmentation-safe endpoint for free-form speech.
- **Fast endpoint** (`stt.fast_vad_ms: 400`, `_fast_partial_hit()` in `stt.py`): when the Vosk *partial* transcript already fully matches a wake word or a complete trigger, the endpoint fires after 400 ms of silence instead of 900 ms (measured on-board: wake at 402 ms after speech end). Free-form utterances (LLM fallback) never match, so they keep the long endpoint. Overridable per GStreamer profile; 0 disables.
- **Wake-match semantics** (`stt_phonetics.py`): all phrase words must phonetically match the transcript, EXCEPT when the transcript is *nothing but* the phrase's distinctive keyword (len ≥ 4) — an isolated "galileo" wakes "ehi galileo" (truncated-wake recall), but "il galileo" or the keyword inside conversation stays silent (false-wake protection). Both behaviours are pinned by `tests/eval/corpus.yaml`.
- **The matching regression gate is `task eval`** (`tests/eval/corpus.yaml` + `tests/test_match_eval.py`), asserting 100% precision / 100% recall. Add every new real-world false wake or missed phrase to the corpus — never work around it in code.
- **Trigger-audio diagnosis**: enable `actions.dump_triggers_dir` in `conf/config.yaml` to dump an 8 s pre-trigger WAV on every match (the rolling buffer is byte-budgeted — do not size it in chunks, capture backends deliver anywhere from ~320 B to 4 KB per read). Analyze with `task stt:analyze-dumps`. A *successful* match's dump usually also contains the failed attempt just before it.
- **RMS probes of the mic are inconclusive on quiet rooms**: the SP92's hardware NS gates silence to digital zero, so "all zeros" ≠ dead link. Confirm the mic is alive from the daemon's live `DEBUG Transcript:` journal lines instead.
- **End-to-end pipeline tests without a mic**: `serena-stt --play file.wav` replays a WAV through the REAL recognition loop (`start_stt_thread` → `_recognition_loop`), including fast-endpoint behaviour — synthesize test phrases with Piper, resample to 16 kHz mono, append ≥2 s of silence. Note: `python -m alexa_custom.stt_cli` does nothing (no `__main__` guard) — call `stt_cli.main()` or the `serena-stt` script.
- **Microphone calibration** (`calibrate_microphone_complete`, voice command "calibra microfono"): sweeps hardware gain, then GStreamer NS variants, scoring every winner across ALL configured `conditions` (near speech, far speech, room noise — worst-case aggregation by default). Candidates are built on top of the resolved active profile (device-critical params like `highpass_cutoff_hz` stay in force during probes) and **never enable WebRTC AGC** unless `allow_agc: true`. GStreamer param precedence: `state.yaml gstreamer_override` (calibration result) > named profile > base config — except while the temporary "calibration" profile is probing.

## TTS performance notes

- **Piper is slower than realtime on this board**: ~1.9 s to first audio for a short phrase (RTF 1.3–1.75, medium voice). Mitigations already in place — clause-splitting streams audio to `paplay` per clause, ORT warm-up at load, and an LRU cache in `PiperTTS` (32 entries, texts ≤ 200 chars) that makes repeated prompts instant. Volume is applied at playback time, so cached audio follows volume changes.
- If uncached synthesis latency matters more than voice quality, an `it_IT-*-low` voice is ~2× faster.

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
setup/              systemd units, udev rules, usb-audio-restore.sh
tests/eval/         corpus.yaml — labelled matching corpus (task eval regression gate)
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
  fast_vad_ms: 400         # early endpoint when the partial already matches (see STT notes)
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
