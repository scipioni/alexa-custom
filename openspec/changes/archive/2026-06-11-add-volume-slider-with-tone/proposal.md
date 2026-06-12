## Why

Users need a visual, interactive way to control output volume directly from the web dashboard. Currently, volume can only be changed via `config.yaml` or command-line tools, making it difficult to adjust during live use. Additionally, users want audible feedback (tone playback) to verify volume levels, similar to Windows volume control.

## What Changes

- Add a new volume slider control to the web dashboard monitoring section
- Support full volume range (0-100%) with visual percentage display
- Play test tone on slider release (mouseup) to provide audible feedback
- Add WebSocket control actions `set_volume` and `beep` for server-side volume/tone control
- Update `audio_ops.py` with `set_output_volume_direct()` function for web control
- Modify `web.py` to handle volume control actions from the UI

## Capabilities

### New Capabilities

- **web-volume-control**: Interactive volume adjustment from web dashboard with real-time visual feedback and tone confirmation

### Modified Capabilities

None - this is a new capability that doesn't modify existing requirements.

## Impact

- **Frontend**: `dashboard.html` - Add volume slider UI, CSS styling, and JavaScript event handlers
- **Backend**: `web.py` - Add `_handle_control()` handler for `set_volume` and `beep` actions
- **Audio Ops**: `audio_ops.py` - Add `set_output_volume_direct()` function that calls `wpctl` and persists volume to config
- **Dependencies**: No new dependencies required - uses existing `wpctl`, `subprocess`, and audio tone functions
- **User Experience**: Users can now adjust volume on-the-fly from the dashboard with audible confirmation