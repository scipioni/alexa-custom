## Why

The web dashboard volume slider has no effect on the slider position — dragging it changes system volume (audible beep at new level), but the slider snaps back to the previous value after ~2 seconds, and the WebSocket connection crashes on each drag. This makes the slider unusable and creates a broken UX.

## What Changes

- Add `_restore_hw_pcm` to the import from `audio_hw` in `audio_ops.py`
- Fix `set_output_volume_direct()` to write to `audio_hw._OUTPUT_VOLUME` instead of its own local module scope, so `get_output_volume()` returns the updated value
- Clean up: remove the stale `global _OUTPUT_VOLUME` declaration and any unused local variable from `audio_ops.py`

## Capabilities

### New Capabilities
None — this is a bug fix for an existing capability.

### Modified Capabilities
None — no spec-level requirement changes, only implementation fixes.

## Impact

- `alexa_custom/audio_ops.py` — two lines changed (import + volume write target)
- `alexa_custom/audio_hw.py` — no changes needed
