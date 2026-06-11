## Why

The volume slider on the web dashboard is functional but visually low-contrast (especially on dark theme) and only works one-way: moving the slider changes system volume, but volume changes from voice commands, shell, or other sources are never reflected in the UI. This creates a confusing experience where the slider shows a stale value.

## What Changes

- Redesign volume slider CSS: thicker track with gradient fill, dynamic color (green→amber→red matching VU meters), larger thumb with glow feedback
- Add bidirectional sync: when volume changes from any source (voice action, shell, another client), the slider updates automatically
- Synchronize `WebServer._output_volume` with actual system volume after slider changes
- Add `output_volume` field to periodic `system_stats` WebSocket broadcast so the frontend can detect external volume changes
- Add frontend logic to update slider from broadcast without re-triggering beep or set_volume

## Capabilities

### New Capabilities
- `web-volume-control`: Interactive volume slider on the web dashboard with visual fill, dynamic color feedback, and bidirectional sync with system volume

### Modified Capabilities
- (none — no existing capability's requirements changed; this is a new capability)

## Impact

- **Frontend**: `dashboard.html` — CSS overhaul of volume slider track/thumb, JS logic for detecting volume changes from `system_stats` broadcast, guard against re-triggering beep on external updates
- **Backend**: `web.py` — update `_output_volume` in `set_volume` handler, add `output_volume` to `_system_stats_loop` broadcast payload
- **No new dependencies**: uses existing CSS variables, WebSocket infrastructure, and `get_output_volume()` from `audio_hw.py`
- **User Experience**: slider is immediately more visible and always reflects true system volume regardless of how it was changed
