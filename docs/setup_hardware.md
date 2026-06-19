# 🛠 Hardware Setup Guide

This guide covers setting up your Linux system and audio hardware for the `alexa-custom` client.

## Recommended Hardware
- **Speakerphone**: NewLine NewPie (USB or Bluetooth)
- **Host**: Headless Linux (e.g., Arduino Uno Q, Raspberry Pi, Armbian)

---

## USB Setup (Plug-and-Play)

USB is the most reliable method and requires zero profile configuration.

1. **Connect**: Plug the NewPie into a USB port.
2. **Verify**:
   ```bash
   pactl list cards short   # should show alsa_card.usb-... for NewPie
   wpctl status             # confirm NewPie sink and source are listed
   ```
3. **Set Default** (or use `task audio:setup`):
   ```bash
   wpctl set-default <newpie-sink-id>
   wpctl set-default <newpie-source-id>
   ```

4. **GStreamer Capture (Optional)**: For noise suppression and AGC via webrtcdsp, install GStreamer packages (`task setup:gstreamer`) and set `stt.capture_backend: gstreamer` in config. See [`docs/stt-simple.md`](stt-simple.md).

---

## Bluetooth Setup (Full-Duplex)

To use Bluetooth for conference audio (mic + speaker), you must force the `headset-head-unit` (mSBC) profile.

### 1. Headless Configuration
WirePlumber needs an override to manage Bluetooth on headless systems:
```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/10-headless-bluetooth.conf << 'EOF'
monitor.bluez.properties = {
  monitor.bluez.seat-monitoring = disabled
}
EOF
```

### 2. Force Headset Profile
Prevent PipeWire from reverting to A2DP (speaker only):
```bash
# Force mSBC on connect
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

# Disable auto-switch back to A2DP
cat > ~/.config/wireplumber/wireplumber.conf.d/30-speakerphone-policy.conf << 'EOF'
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
EOF
```

---

## Arduino Uno Q — Special Fixes

If using the factory board image, apply these fixes:

### 1. PipeWire ALSA Plugin
Expose PipeWire as a virtual ALSA device:
```bash
sudo apt-get install pipewire-alsa portaudio19-dev
```

### 2. Analog-Stereo Profile (NOT pro-audio)
Use `analog-stereo` profile, NOT `pro-audio`. The `pro-audio` profile disables playback/capture endpoints on the NewPie hardware, making the device unusable for voice applications.

The recommended approach is to run `task audio:setup` which handles everything automatically:
```bash
task audio:setup
```

This configures:
- `analog-stereo` profile for NewPie
- Persistent default sink/source via `pw-metadata`
- Hardware PCM volume restore service (`alsa-pcm-unmute.service`)
- USB autosuspend disabled via systemd service (`newpie-autosuspend.service`)
- WirePlumber no-suspend config for native PipeWire clients
- Removes stale `switch-on-connect` drop-in configs

### 3. Audio Capture Profiles

When using `stt.capture_backend: gstreamer`, you can configure named capture profiles under `audio.gstreamer.profiles` in `config.yaml`. These profiles switch at runtime via voice command using the `set_audio_profile` action. See [`docs/configuration.md`](configuration.md) for profile syntax.

### 4. Display Feedback (Optional)

The Arduino UNO Q has a built-in LED matrix. See [`docs/display_setup.md`](display_setup.md) for setup instructions.
