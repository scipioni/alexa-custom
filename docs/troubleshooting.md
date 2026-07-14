# Troubleshooting

## Audio Issues

### `OSError: PortAudio library not found`
- Debian/Ubuntu: `sudo apt install libportaudio2`
- Arch: `sudo pacman -S portaudio`

### No audio from NewPie
1. Check **physical volume** buttons on the device.
2. Check PipeWire volume: `wpctl set-volume @DEFAULT_SINK@ 1.0`
3. Run `task audio:status` to verify NewPie is the default sink/source.
4. Run `task audio:doctor` for a full audio diagnostic.
5. If PCM was reset: `amixer -c 0 sset PCM 100%`
6. If audio dropped mid-session: `task audio:restart`

### Microphone missing or speaker only (Bluetooth)
**Root Cause**: WirePlumber switches to A2DP (speaker-only) profile.
**Fix**: Ensure `30-speakerphone-policy.conf` contains:
```
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
```
Then: `systemctl --user restart wireplumber`

### Python code using pulsectl produces no sound
**Root Cause**: `pulsectl.Pulse()` connection resets ALSA hardware PCM to 0%.
**Fix**: Ensure `_restore_hw_pcm()` is called after the pulsectl context closes — the daemon does this automatically via `AudioWatcher`.

---

## LiveKit Issues

### `LIVEKIT_API_KEY is not set`
**Fix**: Ensure `conf/secrets.yaml` is present with the required LiveKit credentials (not `.env`). Secrets are loaded from `conf/secrets.yaml`, not from a `.env` file.

### Client fails to connect (timeout)
**Fix**: Check `LIVEKIT_URL` in `conf/secrets.yaml`. Must start with `wss://`. Ensure port 443 is allowed on your network.

---

## STT Issues

### STT stops responding (watchdog restart)
The STT worker thread has a watchdog that detects if the recognition loop freezes for more than ~15 seconds. If it fires, check:
- Is CPU pegged at 100%? Vosk uses ~70% on one core; check for other processes.
- Is the audio capture pipeline stalled? Run `serena-audio-doctor`.
- Are there Vosk decode errors in the journal? `journalctl --user -u serena -n 50`.

### Utterances chopped / VAD too aggressive
Raise `stt.vad_silence_ms` (e.g. **900** ms). See `docs/stt-simple.md`.

### Wake word not detected
- Lower `stt.wake_match_threshold` (default: **0.5**).
- Add phonetic variants to `wake_words:` list.

---

## MQTT Issues

### Device not appearing in Home Assistant
1. Verify `mqtt.host` is correct in `conf/config.yaml`.
2. Check credentials in `conf/secrets.yaml`.
3. Use `mosquitto_sub` to check discovery messages:
   ```bash
   mosquitto_sub -h <broker_ip> -t "homeassistant/#" -v
   ```

---

## Permissions

### `Permission denied` on audio devices
```bash
sudo usermod -aG audio $USER
# Log out and back in
```

### `Permission denied` on /dev/mem (display)
```bash
task display:setup    # compiles uart_bridge and installs sudoers entry
```
