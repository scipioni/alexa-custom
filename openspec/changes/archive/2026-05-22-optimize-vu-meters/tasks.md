## 1. Implement Audio Tapping in client.py

- [x] 1.1 Implement a peak calculation utility using numpy
- [x] 1.2 Add `AudioStream` tapping for the local microphone track
- [x] 1.3 Add `AudioStream` tapping for subscribed remote audio tracks
- [x] 1.4 Implement a throttled event emitter for `volume_update` (10Hz)
- [x] 1.5 Ensure tapping tasks are correctly managed (started/cancelled) during session lifecycle

## 2. Update TUI Integration in tui.py

- [x] 2.1 Remove `LevelMonitor` class and `pw-record` subprocess logic
- [x] 2.2 Update `AlexaTUI._handle_event` to process `volume_update` events
- [x] 2.3 Connect `volume_update` data to the `mic-meter` and `spk-meter` widgets
- [x] 2.4 Clean up unused helper functions like `_audio_devices`

## 3. Verification

- [x] 3.1 Verify microphone VU meter response in TUI
- [x] 3.2 Verify speaker VU meter response in TUI during active audio
- [x] 3.3 Verify CPU usage reduction compared to subprocess-based monitoring
