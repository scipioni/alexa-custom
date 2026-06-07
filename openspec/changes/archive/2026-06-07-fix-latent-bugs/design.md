## Context

`alexa-custom` runs as a headless voice assistant daemon. Its critical path is: audio capture (parec) → STT worker thread → wake-word detection → command dispatch → TTS playback. Any silent failure in this path leaves the system deaf with no user-visible indication.

Six bugs were found during review. All are in `client.py`, `stt.py`, and `web.py`. None require new dependencies or data model changes. The fixes are targeted and low-risk individually; the design question is ordering and how they interact.

Current state of the affected components:
- `LiveKitSessionManager` receives `mic`, `devices`, `pw_device`, `on_event` — no config reference.
- `_recognition_loop` instantiates `display_rec` (full Vosk) alongside `stage1` (grammar Vosk) and runs both on every chunk.
- `stt_ready_event` exists in `_async_main`'s signature but is never passed by its callers in production.
- `start_stt_thread` returns a `Thread`; the return value is discarded in `web.py`.
- `capture_transcript` uses `proc.stdout.read(n)` for the echo flush (blocking), unlike every other read in that file.
- `LiveKitSessionManager` creates a second `AudioStream` per remote track via `_tap_remote` for VU metering, separate from the one `PaplayAudioOutput._pump_track` opens for playback.

## Goals / Non-Goals

**Goals:**
- `empty_room_timeout` from config activates the existing watchdog.
- STT startup gate (`stt_ready_event`) works in production mode.
- STT thread death is visible in the web UI and triggers a restart attempt.
- Echo flush in `capture_transcript` cannot block indefinitely.
- Remote-track VU metering uses a single `AudioStream` shared with playback.
- `display_rec` eliminated; UI partials still work via `stage1`.

**Non-Goals:**
- Changing STT backend selection, wake-word logic, or trigger dispatch.
- Altering the web UI layout or adding new UI panels.
- Changing MQTT reporting for these states.

## Decisions

### D1: Pass `empty_room_timeout` as a scalar, not the full config

`LiveKitSessionManager` is constructed in `run_session()`, which is called from the reconnect loop. Passing the full `ActionsConfig` would let the manager drift out of sync when config hot-reloads mid-session. A single `int` value captured at session-start time is simpler and avoids the stale-config problem. The watchdog already uses only this one value.

*Alternative considered*: Pass a `Callable[[], int]` getter so it could hot-reload. Rejected — the empty-room timeout changing mid-call is not a useful scenario and adds complexity.

### D2: VU sampling via callback on `PaplayAudioOutput`

`PaplayAudioOutput._pump_track` already iterates every frame. Add an optional `on_frame_peak: Callable[[float], None]` callback parameter. `LiveKitSessionManager` passes a lambda that updates `self.volumes["spk"]`. Remove `_tap_remote` and its task.

The alternative is sharing an `asyncio.Queue` or `threading.Event`. A callback is simpler: no queue, no extra task, no synchronisation concern — the pump task and the volume emitter are both on the same event loop.

`PaplayAudioOutput` is currently ALSA-board-only, but the design applies equally to the PortAudio player path (which is not exercised on the target board). Add the callback to `PaplayAudioOutput` only; the PortAudio path (`devices.open_output()`) is out of scope — it already handles its own VU via `_tap_mic` and the existing remote tap was the anomaly.

### D3: `stt_ready_event` created in `main()`, stored in `stt_params`

`main()` already constructs `stt_params` and passes it to `run_web`. Adding `stt_ready_event` to `stt_params` keeps the plumbing in one place. `start_stt_thread` in `web.py` reads it from `stt_params`. `_run_for_web` in `client.py` reads it from the closure. Both currently ignore `stt_ready_event`; both get it wired.

### D4: STT watchdog as a periodic task in the web server's async run loop

`web.py`'s `_async_run` already has `broadcast_task`, `vu_task`, `prune_task`. Adding a `watchdog_task` that checks `stt_thread.is_alive()` every 5 seconds fits the existing pattern without introducing new threads or locks.

On death detected:
1. Emit `stt_dead` event to all WebSocket clients (shows in the dashboard).
2. Attempt one restart: create a fresh `stop_event`, call `start_stt_thread` again, store the new thread.
3. Log the restart at WARNING level.

Restart is attempted once per detection cycle. If the thread keeps dying, the watchdog keeps restarting it and keeps emitting `stt_dead` — giving the operator a signal without crashing the whole daemon.

*Alternative*: Restart in the STT thread itself (outer loop with infinite retry). Rejected — the thread already has a retry loop for parec failures; thread-level crashes (OOM, import error) would not be caught there. An external watchdog catches both.

### D5: Bounded echo flush using `_read_with_timeout` loop

Replace `proc.stdout.read(bytes_to_flush)` with:

```python
remaining = flush_ms / 1000.0
chunk_timeout = 0.05  # 50 ms per chunk
while remaining > 0 and bytes_to_flush > 0:
    chunk = _read_with_timeout(proc.stdout, min(_CHUNK, bytes_to_flush), chunk_timeout)
    if not chunk:
        break
    bytes_to_flush -= len(chunk)
    remaining -= chunk_timeout
```

`_read_with_timeout` already exists and is used everywhere else. The loop exits early if parec stalls (returns `b""`) rather than blocking. Maximum wall-clock cost is `flush_ms` ms, same as before on healthy hardware.

### D6: Grammar-restricted partials sufficient for `display_rec` replacement

`stage1.PartialResult()` returns a JSON string with `"partial": "..."`. With a grammar like `["galileo", "[unk]"]`, partials during the utterance show the recognized tokens so far — e.g. `"gali"`, `"galileo"`. This is adequate for the live transcription overlay in the web UI. The overlay currently shows whatever partial text arrives; grammar-constrained tokens are readable and visually useful.

The `display_rec` path showed *all* speech regardless of wake-word relevance. Removing it means the UI only shows text that matches the grammar during stage-1. This is a slight behaviour change (less text shown during non-wake speech) that is acceptable and arguably better UX.

## Risks / Trade-offs

- **D2 — PortAudio player VU gap**: On dev machines where `pw_device` is not None, `devices.open_output()` is used instead of `PaplayAudioOutput`. The remote VU (spk meter) will drop to 0 since `_tap_remote` is removed and the PortAudio player has no callback hook. The VU emitter can fall back to 0 for spk while mic still works. This is acceptable: the target board never uses the PortAudio path, and the dev-machine dashboard is best-effort.

  Mitigation: Gate the VU callback wiring on `isinstance(self.player, PaplayAudioOutput)`. When using the PortAudio player, keep a minimal `_tap_remote` only on that path. This keeps the target-board path clean.

- **D4 — Watchdog restart race**: If the STT thread is in the middle of a slow model-load when the watchdog checks `is_alive()`, it will appear alive — no false positive. If it crashes during model load (before `stt_ready_event.set()`), the watchdog catches it within 5s and restarts. The new thread re-loads the model. If the model itself is corrupt, the restart loop generates one restart attempt per 5s — noisy but bounded by the watchdog's single-attempt-per-cycle design.

- **D6 — Grammar partial latency**: Vosk's grammar recognizer may produce fewer intermediate partials than the unrestricted one, making the UI feel slightly less "live". This is unverifiable without testing on the board; if it proves noticeable, the fix is to lower `_STAGE1_VAD_SILENCE_MS` slightly or add a display-only partial from `stage1.PartialResult()` on every chunk regardless of grammar match.

## Migration Plan

All changes are backward-compatible. No config schema changes. Deployment is a service restart (`systemctl --user restart alexa-custom`). Rollback is `git revert` + restart. No database or persistent state is affected.

Order of implementation matters for D3 (stt_ready_event): wire `start_stt_thread` before `_run_for_web` to avoid a window where the event exists but the thread doesn't set it.

## Open Questions

- **D2 PortAudio fallback**: Accept 0 spk VU on dev machines, or keep `_tap_remote` gated on the PortAudio path? (Recommend: accept 0; the board is the only production target.)
- **D4 restart limit**: Should the watchdog cap restarts (e.g., 3 per hour) to avoid a tight crash-loop? (Recommend: no cap initially; the 5s check interval is a natural rate limiter and the operator sees repeated `stt_dead` events.)
