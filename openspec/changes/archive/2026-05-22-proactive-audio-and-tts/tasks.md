## 1. Proactive Audio Management

- [x] 1.1 Add `enforce_audio_state` to `audio.py` to handle profile switching and routing.
- [x] 1.2 Implement `AudioWatcher` daemon thread to monitor PipeWire events.
- [x] 1.3 Update `client.py` and `tui.py` to initialize and manage the `AudioWatcher` lifecycle.
- [x] 1.4 Generalize device discovery to use specs from `.env` (numeric IDs, substrings, virtual names).
- [x] 1.5 Fix `set_pipewire_defaults` to skip routing for virtual devices like `pipewire` or `default`.

## 2. Text-to-Speech (TTS)

- [x] 2.1 Create `alexa_custom/tts.py` with `TTSBackend` base class and `PicoTTS` implementation.
- [x] 2.2 Add `play_wav_file` helper to `audio.py` using `pw-play` or `aplay`.
- [x] 2.3 Add `say` action type to `dispatch` and `_run_action` in `actions.py`.
- [x] 2.4 Initialize TTS engine in `client.py` and integrate STT gating via shared event flags.

## 3. Terminal UI & User Feedback

- [x] 3.1 Add `AudioStatus` widget to `tui.py` for real-time connection monitoring.
- [x] 3.2 Update `VUMeter` to show `OFFLINE` state when hardware is missing.
- [x] 3.3 Add connection chime (two-tone beep) to `AudioWatcher` on successful detection.
- [x] 3.4 Optimize STT status messages to properly reflect gating during calls or speech.

## 4. Documentation

- [x] 4.1 Update `README.md` with sections for Proactive Audio Management and TTS.
- [x] 4.2 Document new `.env` configuration options and system dependencies.
- [x] 4.3 Add TTS usage examples to `actions.yaml.example`.
