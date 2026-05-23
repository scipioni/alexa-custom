# 🔍 Troubleshooting

## Audio Issues

### `OSError: PortAudio library not found`
**Fix**: Install the system library.
- Debian/Ubuntu: `sudo apt install libportaudio2`
- Arch: `sudo pacman -S portaudio`

### Microphone is missing or "only speaker works"
**Root Cause**: WirePlumber auto-switches back to A2DP (speaker-only) profile.
**Fix**: Verify your `30-speakerphone-policy.conf` contains:
```
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
```
Then restart: `systemctl --user restart wireplumber`

### No audio from NewPie (even if stream is open)
1. Check **physical volume** buttons on the device.
2. Check PipeWire volume: `wpctl set-volume @DEFAULT_SINK@ 1.0`
3. Force profile: `pactl set-card-profile <card_name> headset-head-unit`

---

## LiveKit Issues

### `LIVEKIT_API_KEY is not set`
**Fix**: Ensure your `.env` file is present in the current directory and contains all 4 credentials from the LiveKit Cloud dashboard.

### Client fails to connect (timeout)
**Fix**: Check your `LIVEKIT_URL`. It must start with `wss://`. Ensure your network allows traffic on port 443.

---

## MQTT Issues

### Device not appearing in Home Assistant
1. Verify `MQTT_HOST` is correct in `.env`.
2. Use `mosquitto_sub` to check if discovery messages are reaching the broker:
   ```bash
   mosquitto_sub -h <broker_ip> -t "homeassistant/#" -v
   ```
3. Check the client logs for "MQTT connection error".

---

## Permissions

### `Permission denied` on audio devices
**Fix**: Add your user to the audio group:
```bash
sudo usermod -aG audio $USER
# Log out and back in
```
