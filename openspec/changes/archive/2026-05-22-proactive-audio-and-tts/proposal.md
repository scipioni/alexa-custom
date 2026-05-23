## Why

The system previously relied on manual configuration of PipeWire profiles and routing, which was brittle across reboots and device reconnects. Additionally, the assistant lacked a "voice," limiting user interaction to logs and Telegram messages.

## What Changes

- **Proactive Audio Management**: A background thread now monitors PipeWire events and automatically enforces correct hardware profiles (e.g., mSBC for Bluetooth) and routing.
- **Interchangeable TTS**: A new TTS module with a backend interface allows the assistant to speak using Pico TTS (Italian).
- **STT Gating**: The speech-to-text pipeline now automatically pauses while the assistant is speaking to prevent self-triggering.
- **Enhanced TUI**: The terminal UI now includes a dedicated audio status widget and visual feedback for disconnected devices.

## Capabilities

### New Capabilities
- `audio-management`: Real-time monitoring and proactive enforcement of PipeWire state, including automatic profile switching and persistent routing.
- `text-to-speech`: Backend-agnostic TTS system with support for voice actions and localized output (Italian).

### Modified Capabilities
- `wake-word-detection`: Integrated gating mechanism to pause recognition during system speech or active calls.
- `action-dispatch`: Expanded to support the new `say` action type for voice feedback.

## Impact

- `alexa_custom/audio.py`: Added `AudioWatcher`, `enforce_audio_state`, and `play_wav_file`.
- `alexa_custom/tts.py`: New module for TTS backend architecture.
- `alexa_custom/actions.py`: Added `say` action handler.
- `alexa_custom/stt.py`: Optimized gating logic and event emission.
- `alexa_custom/client.py`: Refactored main loop and session management for better audio robustness.
- `alexa_custom/tui.py`: Added `AudioStatus` widget and integrated watcher events.
