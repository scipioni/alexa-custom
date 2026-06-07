## Why

Six latent bugs and reliability gaps were found during code review: a config value that parses but never activates, a doubled CPU cost during idle listening, a startup-sequencing guard that is dead code in production, a daemon thread that can die silently leaving the system deaf, a blocking read that can hang the STT thread indefinitely, and dual LiveKit AudioStream consumers on the same track that can split frames between playback and the VU meter. None of these surface as obvious failures, making them easy to miss and hard to diagnose in the field.

## What Changes

- **Wire `empty_room_timeout`**: Pass the config value into `LiveKitSessionManager` so `_empty_room_watchdog` actually starts when the setting is non-zero.
- **Remove `display_rec`**: Drop the second unrestricted Vosk recognizer used only for UI partials during wake-word listening; read partials from the grammar-restricted `stage1` recognizer instead.
- **Wire `stt_ready_event` end-to-end**: Create the event in `main()`, pass it through `stt_params` to `start_stt_thread`, and thread it into `_async_main` via `_run_for_web` so startup TTS waits until STT backends are loaded.
- **Add STT thread watchdog**: Store the thread reference and monitor liveness; emit an `stt_dead` event to the web UI and attempt a restart when the thread exits unexpectedly.
- **Fix blocking flush in `capture_transcript`**: Replace the unbounded `proc.stdout.read(bytes_to_flush)` with a time-bounded loop using `_read_with_timeout`.
- **Remove `_tap_remote` / merge VU sampling into playback pump**: Delete the separate `AudioStream` consumer created for VU metering on remote tracks; sample frame levels inside `PaplayAudioOutput._pump_track` instead.

## Capabilities

### New Capabilities

- `stt-thread-watchdog`: Liveness monitoring for the STT daemon thread with UI notification and auto-restart on unexpected exit.

### Modified Capabilities

- `audio-level-monitoring`: VU level sampling for remote (speaker) tracks moves from a dedicated `AudioStream` consumer (`_tap_remote`) into the existing playback pump loop.
- `wake-word-detection`: Removes the parallel unrestricted Vosk recognizer used for display partials; partial text now sourced from the grammar-restricted stage-1 recognizer.

## Impact

- `alexa_custom/client.py`: `LiveKitSessionManager.__init__` gains an `empty_room_timeout` parameter; `run()` wires it to the watchdog; `_tap_remote` and its task management removed; `main()` creates `stt_ready_event` and passes it through.
- `alexa_custom/stt.py`: `_recognition_loop` drops `display_rec`; `capture_transcript` flush replaced with bounded reads; `start_stt_thread` accepts `stt_ready_event`.
- `alexa_custom/audio.py` (`PaplayAudioOutput`): `_pump_track` samples peak level per frame and exposes it via callback or shared state for the VU emitter.
- `alexa_custom/web.py`: `start_stt_thread` call gains `stt_ready_event`; watchdog task detects STT thread death and broadcasts `stt_dead` to connected clients.
