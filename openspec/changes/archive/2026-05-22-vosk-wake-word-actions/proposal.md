## Why

The device sits in a living room but requires manual interaction to initiate calls or send notifications. Adding always-on wake word detection with programmable actions transforms it into a hands-free voice-activated assistant — triggering LiveKit calls or Telegram messages with a spoken phrase.

## What Changes

- Add continuous Vosk speech-to-text pipeline running independently of LiveKit
- Add two-stage wake word detection: grammar-mode for low-CPU wake word listening, full transcription for command recognition
- Add `actions.yaml` config file: defines wake words, trigger phrases, and action sequences
- Add action types: `telegram` (send message via Bot API) and `livekit_join` (connect on demand)
- Add audio feedback: distinct beeps for wake word detected, command recognized, and timeout/no-match
- Change LiveKit client: connect on demand (triggered by action) rather than at startup
- Add new modules: `stt.py`, `actions.py`, `config.py`

## Capabilities

### New Capabilities

- `wake-word-detection`: Continuous low-CPU Vosk-based wake word listening with configurable word list and two-stage command recognition window
- `action-dispatch`: Config-driven action dispatcher mapping recognized phrases to sequences of typed actions (telegram, livekit_join); extensible for future action types
- `telegram-notify`: Outbound Telegram Bot API integration for sending messages on trigger; structured for future inbound command support

### Modified Capabilities

- `audio-level-monitoring`: Audio capture now uses a `parec` subprocess at 16 kHz for STT; existing VU meter tap via `AudioStream` is unchanged but the audio subsystem gains a second independent capture path

## Impact

- **New files**: `alexa_custom/stt.py`, `alexa_custom/actions.py`, `alexa_custom/config.py`, `actions.yaml`, `actions.yaml.example`
- **Modified**: `alexa_custom/client.py` (on-demand connect), `alexa_custom/audio.py` (beep sounds), `pyproject.toml` (add `pyyaml`, `httpx`)
- **New env vars**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Dependencies**: `pyyaml>=6.0`, `httpx>=0.27`
- **No breaking changes** to existing `alexa-client` CLI behavior when `actions.yaml` is absent
