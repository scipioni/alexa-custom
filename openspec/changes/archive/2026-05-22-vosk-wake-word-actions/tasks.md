## 1. Dependencies and Configuration

- [x] 1.1 Add `pyyaml>=6.0` and `httpx>=0.27` to `pyproject.toml` dependencies
- [x] 1.2 Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env.example`
- [x] 1.3 Create `actions.yaml.example` with wake words, command_timeout, and one trigger per action type

## 2. Config Loader (`alexa_custom/config.py`)

- [x] 2.1 Implement `load_actions_config(path)` that parses `actions.yaml` with PyYAML
- [x] 2.2 Validate required fields: `wake_words` (non-empty list), `triggers` (list of phrase+actions)
- [x] 2.3 Return a typed dataclass/dict; raise `ConfigError` with clear message on validation failure
- [x] 2.4 Return `None` (not error) when `actions.yaml` does not exist (backward-compat path)

## 3. Telegram Client (`alexa_custom/actions.py` — TelegramClient)

- [x] 3.1 Implement `TelegramClient` class with `async send_message(chat_id, text)` method
- [x] 3.2 Read `TELEGRAM_BOT_TOKEN` from env; log error and skip if absent
- [x] 3.3 Use `httpx.AsyncClient` with 5-second timeout; log error on failure, do not raise
- [x] 3.4 Structure class to allow future `start_polling(handler)` method (stub comment is enough)

## 4. Action Dispatcher (`alexa_custom/actions.py` — dispatch)

- [x] 4.1 Implement `match_trigger(transcript, triggers, threshold=0.70)` using `difflib.SequenceMatcher`; return best-match trigger or `None`
- [x] 4.2 Implement `async dispatch(trigger, telegram_client, livekit_connect_fn)` that executes actions sequentially
- [x] 4.3 Handle `telegram` action type: call `TelegramClient.send_message` with action-level or env-default `chat_id`
- [x] 4.4 Handle `livekit_join` action type: call provided `livekit_connect_fn`; no-op if already connected
- [x] 4.5 Log warning and skip for unrecognized action types without crashing

## 5. STT Pipeline (`alexa_custom/stt.py`)

- [x] 5.1 Implement `resolve_parec_source(input_spec)` to map `INPUT_DEVICE` env value to a PipeWire source name using `pactl list sources short`
- [x] 5.2 Implement `start_parec(source)` that returns a `subprocess.Popen` reading 16 kHz s16le mono audio
- [x] 5.3 Implement Stage 1 loop: `KaldiRecognizer` with grammar `["<word1>", ..., "[unk]"]`; read 4096-byte chunks from parec stdout
- [x] 5.4 Implement Stage 2 transition: on wake word result, switch to full-transcription `KaldiRecognizer` for `command_timeout` seconds
- [x] 5.5 Implement command window: collect transcription text; on final result or timeout, call `match_trigger` and dispatch
- [x] 5.6 Play wake beep (high tone) on Stage 2 open; play timeout beep (low tone) on window close without match
- [x] 5.7 Run entire pipeline in a `threading.Thread(daemon=True)`; accept a `threading.Event` stop signal
- [x] 5.8 Terminate `parec` subprocess cleanly when stop event is set

## 6. Audio Feedback Beeps (`alexa_custom/audio.py`)

- [x] 6.1 Add `play_beep(frequency_hz, duration_ms)` function using `numpy` + `sounddevice` (same pattern as existing `play_startup_chime`)
- [x] 6.2 Export `play_wake_beep()` (800 Hz, 150 ms) and `play_timeout_beep()` (400 Hz, 150 ms) convenience wrappers

## 7. LiveKit On-Demand Connect (`alexa_custom/client.py`)

- [x] 7.1 Extract `async _connect_once(mic, player, stop_event, on_event)` from `_async_main` as a standalone callable
- [x] 7.2 In `_async_main`: when `actions.yaml` is present, skip auto-connect; expose a `livekit_connect_fn` callback for the action dispatcher
- [x] 7.3 Ensure backward compat: when `actions.yaml` is absent, `_async_main` auto-connects as before

## 8. Wiring and Entry Point

- [x] 8.1 In `client.main()`: call `load_actions_config()`; if config present, start STT thread before the livekit worker
- [x] 8.2 Pass `stop_event`, `telegram_client`, and `livekit_connect_fn` into the STT pipeline
- [x] 8.3 In TUI mode (`--tui`): start STT thread alongside the livekit worker thread; route wake/dispatch events to TUI log panel

## 9. Documentation

- [x] 9.1 Add "Voice Actions" section to `README.md` covering `actions.yaml` setup, env vars, and example config
- [x] 9.2 Update project structure table in `README.md` with new modules
