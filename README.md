# LiveKit Headless Audio Client

Headless Python client for joining LiveKit audio conferences using the NewLine NewPie conference speakerphone. Supports both **USB** and **Bluetooth** connections. USB is recommended — it's plug-and-play with no profile configuration required.

## Requirements

- Python 3.13+
- PipeWire 1.x + WirePlumber 0.5.x
- PortAudio (`libportaudio2` on Debian/Ubuntu, `portaudio` on Arch/Fedora)
- BlueZ Bluetooth stack *(Bluetooth only)*

## Installation

```bash
# System dependencies (Debian/Ubuntu/Armbian)
sudo apt-get install libportaudio2 portaudio19-dev python3-venv

# Python virtual environment and dependencies
python3 -m venv .venv
.venv/bin/pip install -e .
```

---

## Arduino Uno Q — First-Time Setup (Factory Board)

On a fresh Arduino Uno Q board two things are missing from the factory image and must be fixed before `alexa-client` will run.

### 1. Install the PipeWire ALSA plugin

The factory image ships PipeWire but not the ALSA plugin that exposes it as a virtual sounddevice. Without it, `sounddevice` only sees raw `hw:` devices and the client fails with *"PipeWire ALSA device not found"*.

```bash
sudo apt-get install pipewire-alsa portaudio19-dev
```

Verify it worked — you should now see a `pipewire` entry:

```bash
python3 -c "import sounddevice as sd; [print(i, d['name']) for i, d in enumerate(sd.query_devices())]"
# ...
# 2 pipewire
```

### 2. Switch the NewPie card to `pro-audio` profile

PipeWire defaults the NewPie USB device to `input:analog-stereo`, which exposes only a microphone source — no speaker sink. The client fails with *"PipeWire sink not found for OUTPUT_DEVICE='NewPie'"*. Switch to `pro-audio` to get both:

```bash
pactl set-card-profile alsa_card.usb-0a12_NewPie_SABINESMICDFU-00 pro-audio
```

Confirm both sink and source are now visible:

```bash
pactl list sinks short   # should include ...NewPie...pro-output-0
pactl list sources short # should include ...NewPie...pro-input-0
```

**Make it persistent across reboots** with a WirePlumber rule:

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/40-newpie-pro-audio.conf << 'EOF'
monitor.alsa.rules = [
  {
    matches = [ { device.name = "alsa_card.usb-0a12_NewPie_SABINESMICDFU-00" } ]
    actions = {
      update-props = { device.profile = "pro-audio" }
    }
  }
]
EOF
systemctl --user restart wireplumber
```

### 3. Download the Vosk speech recognition model

```bash
wget https://alphacephei.com/vosk/models/vosk-model-small-it-0.22.zip
unzip vosk-model-small-it-0.22.zip
mv vosk-model-small-it-0.22 model-it
```

### 4. Continue with normal setup

With those fixes in place, follow the [USB Setup](#usb-setup-recommended) and [LiveKit Configuration](#livekit-configuration) sections below to finish installation.

---

## USB Setup (Recommended)

Plug in the NewPie USB cable. Linux enumerates it as a standard USB Audio Class device — no drivers or profile configuration needed. Verify it appears:

```bash
pactl list cards short   # should show an alsa_card.usb-... entry for NewPie
wpctl status             # confirm NewPie sink and source are listed
```

Set it as the default audio device:

```bash
wpctl set-default <newpie-sink-id>
wpctl set-default <newpie-source-id>
```

Run the loopback test to confirm full-duplex at 48 kHz:

```bash
.venv/bin/alexa-audio
```

---

## Bluetooth Setup

Steps to set up a fresh headless Linux system for full-duplex Bluetooth conference audio.

### 1. Verify PipeWire is running

```bash
pactl info | grep "Server Name"
# Expected: PulseAudio (on PipeWire 1.x.x)
```

If not running:

```bash
sudo apt-get install pipewire pipewire-pulse wireplumber
systemctl --user enable --now pipewire pipewire-pulse wireplumber
```

### 2. Disable logind seat monitoring (headless systems only)

WirePlumber won't manage Bluetooth audio on a headless system without this override:

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/10-headless-bluetooth.conf << 'EOF'
monitor.bluez.properties = {
  monitor.bluez.seat-monitoring = disabled
}
EOF
```

### 3. Lock the Bluetooth profile to headset mode

By default WirePlumber auto-switches from HSP/HFP (mic + speaker) back to A2DP (speaker only, no mic) when a microphone stream closes. For a conference speakerphone this breaks full-duplex. The two config files below fix it permanently:

```bash
# Force headset-head-unit (mSBC) profile on every Bluetooth connect
cat > ~/.config/wireplumber/wireplumber.conf.d/20-default-profile.conf << 'EOF'
monitor.bluez.rules = [
  {
    matches = [ { device.name = "~bluez_card.*" } ]
    actions = {
      update-props = { device.profile = "headset-head-unit" }
    }
  }
]
EOF

# Disable the auto-restore to A2DP when the mic stream closes
cat > ~/.config/wireplumber/wireplumber.conf.d/30-speakerphone-policy.conf << 'EOF'
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
EOF
```

**Available Bluetooth profiles:**

| Profile | Codec | Sample rate | Microphone | Use for |
|---------|-------|-------------|------------|---------|
| `headset-head-unit` | mSBC | 16 kHz | Yes | Conference calls (recommended) |
| `headset-head-unit-cvsd` | CVSD | 8 kHz | Yes | Fallback if device lacks mSBC |
| `a2dp-sink` | SBC/SBC-XQ | 44–48 kHz | No | Music playback only |

### 4. Enable Bluetooth auto-power on boot

```bash
sudo sed -i 's/^#AutoEnable=true/AutoEnable=true/' /etc/bluetooth/main.conf
```

### 5. Pair and connect the speakerphone

```bash
bluetoothctl
  power on
  agent on
  scan on
  pair   XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  trust  XX:XX:XX:XX:XX:XX
  quit
```

### 6. Apply configuration and switch profile

```bash
systemctl --user restart wireplumber
sleep 2

# Find your card name (format: bluez_card.XX_XX_XX_XX_XX_XX)
pactl list cards short

# Switch to mSBC headset profile
pactl set-card-profile bluez_card.XX_XX_XX_XX_XX_XX headset-head-unit
```

Replace `XX_XX_XX_XX_XX_XX` with your device MAC address using underscores (e.g. `28_36_38_3E_59_D0`).

### 7. Set as default audio device

```bash
wpctl status
# Note the numeric IDs shown for the Bluetooth sink and source, then:
wpctl set-default <sink-id>
wpctl set-default <source-id>
```

### 8. Verify

```bash
pactl list cards | grep "Active Profile"
pactl info | grep -E "Default Sink|Default Source"

# Expected:
# Active Profile: headset-head-unit
# Default Sink: bluez_output.XX_XX_XX_XX_XX_XX.1
# Default Source: bluez_input.XX_XX_XX_XX_XX_XX.0
```

After a reboot or Bluetooth reconnect, WirePlumber restores the `headset-head-unit` profile and default sink/source automatically from its state files — no manual steps needed.

---

## NewPie: Daily Use

### Test audio (mic → speaker loopback)

```bash
.venv/bin/alexa-audio
```

The script runs a preflight check (verifies the device is connected and the profile is correct), then opens a loopback stream. Speak into the mic and you should hear yourself through the speaker. Press Ctrl+C to stop.

```bash
# List all detected audio devices and active BT profile
.venv/bin/alexa-audio --list
```

### Check status

```bash
wpctl status
pactl info | grep -E "Default Sink|Default Source"
pactl list cards | grep -A 3 "Active Profile"
```

### Manual profile fix (if device reverts to A2DP)

```bash
pactl set-card-profile bluez_card.XX_XX_XX_XX_XX_XX headset-head-unit
```

---

## LiveKit Configuration

> `meet.livekit.io` is a browser client app, not a LiveKit server. You need your own
> LiveKit Cloud project with a server URL, API key, and API secret.

### 1. Create a free LiveKit Cloud project

1. Sign up at [https://cloud.livekit.io](https://cloud.livekit.io)
2. Create a new project
3. From the project dashboard copy:
   - **Server URL** — e.g. `wss://your-project.livekit.cloud`
   - **API Key**
   - **API Secret**

### 2. Configure `.env`

```bash
cp .env.example .env
nano .env
```

```ini
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_ROOM=your-room-name
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret

# Optional: override audio devices (index or name substring).
# Defaults to the PipeWire default sink/source when unset.
#INPUT_DEVICE=pipewire
#OUTPUT_DEVICE=pipewire
```

The `.env` file is git-ignored — never commit credentials.

To find the right values, run `alexa-devices` and use either the numeric index or any unique substring of the device name:

```ini
# by index
INPUT_DEVICE=3
OUTPUT_DEVICE=3

# by name substring (case-insensitive)
INPUT_DEVICE=NewPie
OUTPUT_DEVICE=NewPie
```

### 3. Run

```bash
.venv/bin/alexa-client
```

At startup the script validates credentials and prints a **browser join URL**:

```
Browser join URL:
  https://meet.livekit.io/custom/?liveKitUrl=wss%3A%2F%2F...&token=...
```

Open that URL on any browser or device to join the same room as the speakerphone. The client reconnects automatically if the room drops — stop it with Ctrl+C or SIGTERM.

> **Note:** The URL uses the `/custom/` path on meet.livekit.io, which is required for connecting to a custom LiveKit server. The `liveKitUrl` and `token` parameters are URL-encoded.

---

## Project Structure

```
alexa-custom/
├── alexa_custom/
│   ├── __init__.py
│   ├── _env.py         # .env loader
│   ├── audio.py        # NewPie preflight check and loopback test
│   └── client.py       # LiveKit conference client with auto-reconnect
├── pyproject.toml      # Package metadata and dependencies
├── .env                # Credentials — git-ignored, fill this in
├── .env.example        # Credentials template
├── .gitignore
└── README.md

~/.config/wireplumber/wireplumber.conf.d/
├── 10-headless-bluetooth.conf   # Disable logind seat monitoring
├── 20-default-profile.conf      # Force headset-head-unit on BT connect
└── 30-speakerphone-policy.conf  # Disable auto-restore to A2DP
```

---

## Troubleshooting

### `OSError: PortAudio library not found` on startup

`sounddevice` and `livekit-rtc` both require the PortAudio shared library at runtime. Install it for your distro:

| Distro | Command |
|--------|---------|
| Debian / Ubuntu / Armbian | `sudo apt install libportaudio2` |
| Arch / EndeavourOS | `sudo pacman -S portaudio` |
| Fedora | `sudo dnf install portaudio` |
| Alpine | `sudo apk add portaudio` |

---

### `LIVEKIT_API_KEY is not set` on startup

Fill in all four values in `.env`. The script validates credentials before opening audio devices and will exit immediately with the name of the missing variable.

### Microphone not working / only speaker works / profile keeps reverting to A2DP

**Root cause:** WirePlumber's default policy auto-switches from `headset-head-unit` (HSP/HFP — mic + speaker, 16 kHz) back to `a2dp-sink` (A2DP — speaker only, no mic) the moment the microphone stream closes. On a conference speakerphone this happens continuously and breaks full-duplex audio.

**Fix:** `30-speakerphone-policy.conf` disables the auto-switch:

```bash
cat ~/.config/wireplumber/wireplumber.conf.d/30-speakerphone-policy.conf
```

Expected content:

```
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
```

If the file is missing or wrong, recreate it:

```bash
cat > ~/.config/wireplumber/wireplumber.conf.d/30-speakerphone-policy.conf << 'EOF'
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
EOF
systemctl --user restart wireplumber
```

Verify the profile stayed on `headset-head-unit` after restart:

```bash
pactl list cards | grep "Active Profile"
# Expected: Active Profile: headset-head-unit
```

### Bluetooth device not appearing in `wpctl status`

```bash
bluetoothctl info XX:XX:XX:XX:XX:XX   # check connection state
journalctl --user -u wireplumber -n 50  # check WirePlumber errors
```

### Stream opens but no audio from speakerphone speaker

First check the **physical volume** on the NewPie device — press the volume-up button several times and confirm the mute indicator is off. The software audio pipeline (PipeWire → Bluetooth SCO → NewPie) can be fully working while the physical speaker volume is at zero.

Verify the software side:

```bash
# Confirm profile and volume at PipeWire level
pactl list cards | grep "Active Profile"
wpctl status | grep NewPie          # should show * NewPie [vol: 1.00]
wpctl set-volume <sink-id> 1.0      # force to 100% if needed

# Quick loopback test: speak into mic, hear yourself in speaker
.venv/bin/alexa-audio

# If profile reverted to A2DP (no mic), force it back
pactl set-card-profile bluez_card.XX_XX_XX_XX_XX_XX headset-head-unit
```

> **Note:** `bluez5.profile = "off"` in `pw-dump` output is a misleading PipeWire internal property — it does **not** mean audio is broken. Verify audio is actually flowing by checking `hciconfig hci0` for increasing SCO TX packet counts while audio plays.

```bash
# Confirm SCO packets are being sent (count should increase while playing)
hciconfig hci0 | grep "TX bytes"
```

### Permission errors

```bash
sudo usermod -aG audio $USER
# Log out and back in
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `livekit` | LiveKit real-time SDK |
| `livekit-api` | JWT token generation |
| `sounddevice` | Audio I/O via PortAudio |
| `numpy` | Audio buffer handling |
| `pulsectl` | PipeWire/PulseAudio introspection |
| `libportaudio2` | System audio library (apt) |

## License

Apache-2.0
# alexa-custom
