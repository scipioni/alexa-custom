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
3. **Set Default**:
   ```bash
   wpctl set-default <newpie-sink-id>
   wpctl set-default <newpie-source-id>
   ```

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

If using the factory board image, apply these two fixes:

### 1. PipeWire ALSA Plugin
Expose PipeWire as a virtual ALSA device:
```bash
sudo apt-get install pipewire-alsa portaudio19-dev
```

### 2. Persistent `pro-audio` Profile
Required for the USB card to expose both sink and source:
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
