## 1. Fix blocking echo flush (capture_transcript)

- [x] 1.1 In `stt.py:capture_transcript`, replace `proc.stdout.read(bytes_to_flush)` with a bounded loop using `_read_with_timeout` that exits early on stall and runs no longer than `flush_ms` milliseconds

## 2. Remove duplicate Vosk display recognizer

- [x] 2.1 In `stt.py:_recognition_loop`, delete `display_rec` instantiation and all references (`AcceptWaveform`, `PartialResult`, `Reset`)
- [x] 2.2 Source UI partial text from `stage1.PartialResult()` in the same location where `display_rec.PartialResult()` was called; emit `transcribing` event with this partial

## 3. Wire stt_ready_event end-to-end

- [x] 3.1 In `client.py:main()`, create `stt_ready_event = threading.Event()` and add it to `stt_params` dict
- [x] 3.2 In `client.py:_run_for_web`, capture `stt_ready_event` from the `stt_params` closure and pass it to `_async_main` as `stt_ready_event=`
- [x] 3.3 In `web.py`, pass `stt_params["stt_ready_event"]` to `start_stt_thread` (the parameter already exists on `run_stt_worker`)

## 4. Wire empty_room_timeout into LiveKitSessionManager

- [x] 4.1 Add `empty_room_timeout: int = 0` parameter to `LiveKitSessionManager.__init__` and store as `self._empty_room_timeout`
- [x] 4.2 In `LiveKitSessionManager.run()`, replace the hardcoded `0.0` with `self._empty_room_timeout`
- [x] 4.3 In `run_session()`, accept `empty_room_timeout: int = 0` and forward it to `LiveKitSessionManager`
- [x] 4.4 In `_async_main()`, pass `actions_config.system.empty_room_timeout` (defaulting to `0`) to `run_session()`

## 5. Merge remote VU sampling into playback pump

- [x] 5.1 Add `on_frame_peak: Callable[[float], None] | None = None` parameter to `PaplayAudioOutput.__init__` and store it
- [x] 5.2 In `PaplayAudioOutput._pump_track`, after writing each frame to the process stdin, call `self.on_frame_peak(peak)` if set (compute peak the same way `calculate_peak` does)
- [x] 5.3 In `LiveKitSessionManager.__init__`, remove `_tap_remote` method and its `asyncio.create_task` call from `on_track_subscribed`
- [x] 5.4 In `LiveKitSessionManager.run()`, when constructing `PaplayAudioOutput`, pass `on_frame_peak=lambda p: self._update_spk(p)` and add `_update_spk` method that writes to `self.volumes["spk"]`
- [x] 5.5 Remove `_tap_remote` from `tap_tasks` management (cleanup loop)

## 6. Add STT thread watchdog

- [x] 6.1 In `web.py`, store the return value of `start_stt_thread(...)` in a variable (e.g., `stt_thread`)
- [x] 6.2 Add async `_stt_watchdog(stt_thread_holder, stt_params, on_stt_event)` coroutine that loops every 5 seconds, checks `stt_thread_holder[0].is_alive()`, and on death: broadcasts `stt_dead` event, creates a new `stop_event`, calls `start_stt_thread` with the original params, updates `stt_thread_holder[0]`
- [x] 6.3 Start `_stt_watchdog` as an `asyncio.create_task` in `_async_run` alongside the existing broadcast/vu/prune tasks
- [x] 6.4 Cancel the watchdog task in the `finally` block alongside the other tasks

## 7. Tests and verification

- [x] 7.1 Run `task test` and confirm no regressions
- [x] 7.2 Run `task lint` and fix any issues
