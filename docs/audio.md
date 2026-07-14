# 🔊 Host Audio Backend Report

This document provides a detailed overview of the host system's audio backend architecture, running audio services, hardware sound cards, USB-connected devices, and instructions on how to query these diagnostics.

---

## 1. System-Level Audio Architecture

The host system runs a modern, low-latency **PipeWire** audio graph managed by **WirePlumber** for session and routing management.

```
┌─────────────────────────────────────────────────────────┐
│                    Host Audio Clients                   │
└────────────┬───────────────────────────────┬────────────┘
             │                               │
             ▼ (PortAudio ALSA virtual API)  ▼ (PulseAudio API emulation)
┌────────────────────────────────────────────┬────────────┐
│                    PipeWire (pipewire-pulse)            │
├─────────────────────────────────────────────────────────┤
│            WirePlumber (Session & Route Manager)        │
└────────────┬───────────────────────────────┬────────────┘
             │                               │
             ▼ (ALSA Drivers)                ▼ (ALSA Drivers)
┌───────────────────────────┐   ┌─────────────────────────┐
│     NewPie USB Audio      │   │  ArduinoImolaHPH LOUT   │
│   (Playback + Capture)    │   │  (MultiMedia Playback)  │
└───────────────────────────┘   └─────────────────────────┘
```

### Active Processes & Roles
The following audio services are actively running under the host user session:

- **`pipewire`**: The core sound server managing the unified multimedia processing graph.
- **`pipewire -c filter-chain.conf`**: An active DSP filter chain (used for acoustic echo cancellation, noise suppression, or virtual device configurations).
- **`wireplumber`**: The modular session manager that enforces routing policies and configures endpoints.
- **`pipewire-pulse`**: The PulseAudio compatibility daemon, providing PulseAudio API emulation for legacy and modern clients alike.

---

## 2. Hardware Sound Cards (ALSA Level)

The Linux kernel discovers and exposes two primary hardware audio cards. The playback and capture capabilities are symmetrical:

### Playback Hardware Devices (`aplay -l`)
* **Card 0: NewPie** `[NewPie]` | Device 0: `USB Audio [USB Audio]`
  * Subdevices: 1/1
* **Card 1: ArduinoImolaHPH** `[Arduino-Imola-HPH-LOUT]` 
  * Device 0: `MultiMedia1` (Subdevices: 1/1)
  * Device 1: `MultiMedia2` (Subdevices: 1/1)
  * Device 2: `MultiMedia3` (Subdevices: 1/1)
  * Device 3: `MultiMedia4` (Subdevices: 1/1)

### Capture Hardware Devices (`arecord -l`)
* **Card 0: NewPie** `[NewPie]` | Device 0: `USB Audio [USB Audio]`
  * Subdevices: 1/1
* **Card 1: ArduinoImolaHPH** `[Arduino-Imola-HPH-LOUT]`
  * Device 0: `MultiMedia1` (Subdevices: 1/1)
  * Device 1: `MultiMedia2` (Subdevices: 1/1)
  * Device 2: `MultiMedia3` (Subdevices: 1/1)
  * Device 3: `MultiMedia4` (Subdevices: 1/1)

---

## 3. USB-Connected Audio Hardware

The primary external USB audio device integrated into this setup is:

- **Device Name**: `NewPie`
- **USB Hardware Identity**: `Cambridge Silicon Radio, Ltd NewPie` (USB ID `0a12:1260` on Bus 001, Device 004)
- **Interface Protocol**: USB Audio Class 1.0/2.0 standard.

---

## 4. WirePlumber Device & Endpoint Configuration

WirePlumber registers and maps the physical hardware cards to the following core devices, sinks, and sources:

### WirePlumber Registered Devices
- **`NewPie`** [alsa]
- **`Built-in Audio`** [alsa] (onboard HDMI, fallback)

### WirePlumber Audio Sinks (Playback Endpoints)
- **`NewPie Analog Stereo`** (default when configured)
- **`Built-in Audio HDMI Digital Stereo Output`** (fallback when NewPie absent)

### WirePlumber Audio Sources (Capture Endpoints)
- **`NewPie Analog Stereo`** (default when configured)

> **Note**: WirePlumber assigns node IDs dynamically at runtime — they change on every reboot. Never hardcode them in scripts. Use node names with `pw-metadata` or `@DEFAULT_SINK@` / `@DEFAULT_SOURCE@` aliases with `wpctl`.

---

## 5. Host Sounddevice / PortAudio Mapping

The python environment maps physical sound cards and virtual interfaces through `sounddevice` (PortAudio). Here is the active system device index mapping:

| Index | Device Name | API | Channels (In / Out) |
|-------|-------------|-----|----------------------|
| **0** | `NewPie: USB Audio (hw:0,0)` | ALSA | 2 In / 2 Out |
| **1** | `Arduino-Imola-HPH-LOUT: - (hw:1,1)` | ALSA | 0 In / 8 Out |
| **2** | `Arduino-Imola-HPH-LOUT: - (hw:1,3)` | ALSA | 0 In / 2 Out |
| **3** | `sysdefault` | ALSA | 128 In / 128 Out |
| **4** | `front` | ALSA | 0 In / 2 Out |
| **5** | `surround40` | ALSA | 0 In / 2 Out |
| **6** | `iec958` | ALSA | 0 In / 2 Out |
| **7** | `spdif` | ALSA | 2 In / 2 Out |
| **8\*** | `default` | ALSA | 128 In / 128 Out |
| **9** | `dmix` | ALSA | 0 In / 2 Out |

*\* Note: Index 8 is currently configured as the system default PortAudio device.*

---

## 6. Diagnostic & Retrieval Instructions

To query or update the host information documented in this report, run the following diagnostic commands on the host terminal:

### 1. Identify USB Connected Audio Devices
To scan the host's USB bus and find physical audio controllers (such as the `NewPie` device):
```bash
lsusb
```

### 2. Verify ALSA Hardware Sinks and Sources
To list physical hardware recording (capture) and playback sound cards registered by the Linux kernel:
```bash
# List playback devices
aplay -l

# List capture/microphone devices
arecord -l
```

### 3. Check Active Audio Services
To verify if PipeWire, WirePlumber, or PulseAudio layers are running under the user session:
```bash
ps aux | grep -E 'pipewire|wireplumber|pulse' | grep -v grep
```

### 4. Query WirePlumber Endpoints & Status
To inspect the WirePlumber session manager, including active devices, sinks, sources, default targets, and volumes:
```bash
wpctl status
```

### 5. Inspect Python Sounddevice Index Mapping
To view how PortAudio (used by the companion app) indexes the host-level physical and virtual ALSA audio devices:
```bash
.venv/bin/python3 -m sounddevice
```

---

## 7. Configuring and Switching Default Devices

### The Automated Way (Recommended)
If you have `task` installed, run setup once (after first boot):
```bash
task audio:setup
```
This sets default routing, unmutes PCM, and installs `alsa-pcm-unmute.service` — a user systemd service that handles boot-time PCM restoration and routing on every subsequent boot. See section 11 for details.

### The Manual Way
To configure the USB audio card (`NewPie`) as the default playback and capture device manually:

#### Set Default Sink/Source (Immediate + Persistent)
Use `pw-metadata` with node names — these are stable across reboots, unlike numeric IDs which change every boot:
```bash
# Set default playback to NewPie
pw-metadata -n default 0 default.audio.sink '{"name":"alsa_output.usb-0a12_NewPie_SABINESMICDFU-00.analog-stereo"}' 'Spa:String:JSON'

# Set default recording to NewPie
pw-metadata -n default 0 default.audio.source '{"name":"alsa_input.usb-0a12_NewPie_SABINESMICDFU-00.analog-stereo"}' 'Spa:String:JSON'
```

WirePlumber stores these names in its persistent state (`~/.local/state/wireplumber/`) and re-applies them on the next boot.

---

## 8. AudioWatcher Background Thread

The system runs an `AudioWatcher` background thread that monitors PipeWire events via `pulsectl` and proactively manages audio routing.

**Responsibilities**:
1. On every PulseAudio event (device connect/disconnect), calls `_check_and_enforce()` which re-applies NewPie as the default sink/source.
2. Opens a `pulsectl.Pulse()` connection on startup and immediately calls `_restore_hw_pcm()`.
3. Reacts to `sink_changed`, `source_changed`, and `card_changed` events — catches mid-session routing changes caused by USB reconnection or HDMI hotplug.

**Rule**: Never open a `pulsectl.Pulse()` connection without calling `_restore_hw_pcm()` right after. The `AudioWatcher` enforces this automatically.

## 9. GStreamer Capture Profiles

When `stt.capture_backend: gstreamer`, capture can use named profiles defined under `audio.gstreamer.profiles`. Each profile overrides:

- **GStreamer params**: noise_suppression_level, agc_target_level_dbfs, agc_compression_gain_db, etc.
- **STT params**: rms_threshold, vad_silence_ms (applied to the recognition loop after capture restart)

Profiles are switched at runtime via the `set_audio_profile` action type:

```yaml
triggers:
  - commands: ["microfono sensibile"]
    actions:
      - type: set_audio_profile
        profile: sensitive
        say: "Microfono impostato su sensibile"
```

The active profile name is stored in `conf/state.yaml` and restored on daemon start. The GStreamer capture pipeline restarts automatically when the profile changes, applying the new parameters.

## 10. Software vs Hardware Gain

`audio.input_gain` (**1.0**) is applied **in software** — a numpy multiplication on the captured int16 buffer before VAD/Vosk processing. It does NOT modify the ALSA hardware PCM mixer, the PipeWire source volume, or the PulseAudio source volume.

This is intentional:
- Software gain is instant (no ALSA/PulseAudio round-trip).
- It survives `pulsectl.Pulse()` context opens (hardware PCM gets reset to 0%).
- It can be changed at runtime without audio pipeline restarts.
- Negative values invert the signal (useful for diagnosing phase issues).

Hardware PCM volume is always set to 100% by `_restore_hw_pcm()` and left there. All volume/gain control is done digitally.

## 11. Persisting PCM Volume and Routing Across Reboots

On this board, the USB audio driver resets the NewPie's hardware `PCM` mixer to `0%` every time PipeWire initializes and takes ownership of the ALSA device. Additionally, WirePlumber may route to HDMI on boot if NewPie isn't ready when routing decisions are made.

**Why naive approaches fail**:
- `alsa-restore.service` runs before PipeWire starts — PipeWire's init resets PCM back to 0% afterwards.
- A service that runs `amixer` immediately after `wireplumber.service` starts still loses the race — PipeWire may retry the ALSA device open 1–2 seconds later, resetting PCM again.
- A service that runs once when NewPie first appears still loses the race — WirePlumber's ACP (ALSA Card Profile) profile initialization completes asynchronously a few seconds later and resets PCM to 0 again with no journal trace.
- WirePlumber's "Default Configured Devices" state saves NewPie as the preference but doesn't reliably switch away from HDMI once HDMI has become active.

**The fix**: `task audio:setup` installs `~/.config/systemd/user/alsa-pcm-unmute.service`, which:
1. Polls `wpctl status` every second until "NewPie Analog Stereo" appears (up to 30s)
2. Forces NewPie as active routing via `pw-metadata`
3. Then runs `amixer -c 0 sset PCM 100%` every 2 seconds for 20 seconds — catching WirePlumber's late ACP reset whenever it occurs in that window

To check it ran correctly after a reboot:
```bash
systemctl --user status alsa-pcm-unmute.service
amixer -c 0 sget PCM | grep Mono
wpctl status | grep -E '\* .*NewPie'
```

---

## 14. Auto-Switching to NewPie on Boot (Fixing Late Discovery Silence)

On headless systems, the USB audio interface is often discovered by the kernel **slightly after** PipeWire and WirePlumber have already started up. Because the USB card didn't exist at the exact millisecond WirePlumber booted, WirePlumber falls back to the built-in HDMI sink. When the USB device is registered a second later, WirePlumber retains HDMI as the default active sink.

**The fix**: the `alsa-pcm-unmute.service` (installed by `task audio:setup`) handles routing too — it polls until NewPie appears, then calls `pw-metadata` to force it as the active sink/source. See section 11.

**`libpipewire-module-switch-on-connect` — not available on this board**: This PipeWire module would force an immediate switch to any newly connected device, but it is not compiled into the PipeWire 1.4.2 build on this board. The `ifexists nofail` conf flags do **not** work on this build — PipeWire and `pipewire-pulse` crash if the drop-in is present. `task audio:setup` actively removes any stale copies of `99-switch-on-connect.conf` from both `pipewire.conf.d/` and `pipewire-pulse.conf.d/` to prevent this.

To confirm NewPie is the active default after a reboot:
```bash
wpctl status | grep -E '\* .*NewPie'
```

---

## 15. Mid-Session Audio Loss (USB Autosuspend)

Linux may suspend the NewPie USB device after a period of inactivity. When PipeWire reinitializes it on wake, the ALSA PCM mixer resets to `0%` and routing may revert to HDMI — identical to the boot-time problem but happening mid-session.

**Symptom**: audio stops working during a live session; `task audio:restart` restores it.

**Diagnosis**:
```bash
journalctl --user -u wireplumber -n 50 --no-pager
```
Look for WirePlumber re-discovering or re-initializing the NewPie around the time audio dropped.

**The fix** (two parts):

1. **Systemd system service** (`newpie-autosuspend.service` installed by `task audio:setup`): disables autosuspend after `multi-user.target`, avoiding the boot crash that occurred when the old udev rule fired during USB enumeration at power-on.
2. **WirePlumber no-suspend config** (`51-newpie-no-suspend.conf` in `~/.config/wireplumber/wireplumber.conf.d/`): keeps the NewPie source always active so native PipeWire clients (e.g. `pipewiresrc`) can connect and receive data immediately.

`task audio:setup` removes any stale udev rules (`99-newpie-no-autosuspend.rules`) to prevent the boot crash.

To verify autosuspend is disabled:
```bash
cat /sys/bus/usb/devices/*/power/autosuspend_delay_ms
```
The NewPie's entry should show `-1`.

---

## 16. pulsectl Mid-Session PCM Reset

**Any** `pulsectl.Pulse()` connection (volume set, routing query, etc.) causes pipewire-pulse to open a PulseAudio client, which triggers PipeWire to re-open the ALSA device. This resets the NewPie's hardware PCM mixer to `0%` — the same reset that happens at boot — making all subsequent audio silent until PCM is restored.

**Symptom**: audio works from the shell (`pw-play file.wav`) but Python code using pulsectl produces no sound.

**The fix**: `_restore_hw_pcm()` in `audio.py` runs `amixer -c 0 sset PCM 100%` immediately after any `pulsectl.Pulse()` context closes. It is called:
- In `AudioWatcher._check_and_enforce()` after the device first connects and volume is set
- In `main_test()` after `set_output_volume`

---

## 17. pw-play Raw Stdin Piping (Unreliable on This Board)

`pw-play --raw --rate N --format f32 -` (reading raw PCM from stdin) is **not reliably supported** on PipeWire 1.4.2 on this board. `pw-play` returns exit code 0 but produces no audio. The only reliable path is `pw-play <wav_file>`.

**The fix**: `_play_array()` and `_play_raw()` in `audio.py` write a temporary s16le WAV file and call `pw-play <tmp.wav>`, mirroring how `task audio:test` works. The temp file is deleted after playback.

