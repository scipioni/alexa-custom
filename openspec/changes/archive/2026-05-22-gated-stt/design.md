# Design: Gated STT during calls

## Architecture Overview

The STT worker runs in a dedicated thread. It will now incorporate a check for the `livekit_connected_flag` and a `cooldown_until` timer.

### Logic Flow

```
[ STT Loop ]
     │
     ▼
[ Read Audio Chunk ]
     │
     ├─▶ [ Calculate RMS for VU Meter ]
     │
     ▼
[ Is Call Active? ] ── YES ──▶ [ Set Cooldown = Now + 1.0s ]
     │                         [ Emit "gated" event ]
     │                         [ Continue Loop ]
     ▼
[ Is Cooldown Active? ] ─ YES ─▶ [ Continue Loop ]
     │
     ▼
[ Process with Vosk ]
```

## Implementation Details

### `stt.py`
- Add `_STT_COOLDOWN = 1.0` constant.
- In `_recognition_loop` and `_single_stage_loop`:
    - Track `cooldown_until: float = 0.0`.
    - Check `livekit_connected_flag.is_set()`.
    - If set:
        - `cooldown_until = time.monotonic() + _STT_COOLDOWN`.
        - If state changed to gated, emit `on_stt_event("gated", {})`.
    - If `time.monotonic() < cooldown_until`:
        - Discard audio data.
        - Call `rec.Reset()` to clear partial results from the transition.
    - Else:
        - Proceed with `rec.AcceptWaveform(data)`.

### `tui.py`
- Add `gated` state to `STTStatus` widget.
- Update `render()` to show a "Gated" message (e.g., `[dim]⏸[/] [dim]STT paused during call[/]`).
- Add `_handle_stt_event` mapping for the `gated` event.

## Performance Impact
- **CPU**: Discarding audio before `AcceptWaveform` eliminates the most expensive part of the STT thread during calls.
- **Latency**: The 1.0s cooldown ensures we don't catch the tail end of the call, but it's short enough to feel snappy once the call is truly over.

## Alternatives Considered
- **Closing the Pipe**: Closing `parec` entirely and restarting it.
    - *Decision*: Rejected. Re-opening audio devices can cause "pops" or delays. Keeping the pipe open but discarding data is smoother.
- **Lowering Vosk priority**: Letting the OS throttle the thread.
    - *Decision*: Rejected. Doesn't solve the false-trigger issue.
