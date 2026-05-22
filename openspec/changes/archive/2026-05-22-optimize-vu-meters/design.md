# Design: Direct Audio Level Calculation

## Architecture Overview

The optimization shifts volume monitoring from the OS level (PipeWire subprocesses) to the application level (LiveKit audio frames).

```
[ LiveKit Audio Stream ] ──▶ [ Peak Calculator ] ──▶ [ Throttler ] ──▶ [ TUI Event ]
```

## Implementation Details

### 1. LiveKit Tapping (`client.py`)

We will use `AudioStream` to iterate over audio frames for both local and remote tracks.

**Microphone (Input):**
- Create an `AudioStream` from the `LocalAudioTrack`.
- Run an async task that reads frames, calculates peak, and throttles updates to 100ms.

**Speaker (Output):**
- Since the `player` (output) mixes multiple tracks, we can tap the `AudioFrame` stream from the room's remote participants or ideally, the output sink itself if LiveKit provides a combined stream.
- Alternatively, we calculate the max peak across all subscribed remote tracks.

### 2. Event Payload

The `on_event` callback will receive a new event type: `volume_update`.

```json
{
  "event": "volume_update",
  "data": {
    "mic": 0.45,
    "spk": 0.12
  }
}
```

### 3. TUI Integration (`tui.py`)

- Remove `LevelMonitor` class and its `pw-record` subprocesses.
- Update `AlexaTUI._handle_event` to catch `volume_update` and update the `VUMeter` widgets directly.

### 4. Performance Considerations

- **Numpy Efficiency**: Use `np.max(np.abs(samples))` for fast calculation.
- **Throttling**: Use `asyncio.sleep` or a timestamp check to ensure we don't spam the TUI loop more than 10-15 times per second.
- **Task Management**: Ensure tapping tasks are cancelled when the session ends or reconnects.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Increased CPU from frame iteration | Throttle updates; processing raw bytes is cheap compared to spawning shells. |
| Latency in VU meter response | 100ms (10Hz) is standard for UI meters and feels "real-time". |
| Accessing combined output stream | If LiveKit doesn't provide a mixed output stream easily, we'll sum/max the peaks of active remote tracks. |
