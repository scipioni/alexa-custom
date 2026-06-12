## Context

The web dashboard volume slider (`alexa_custom/web.py` → `audio_ops.set_output_volume_direct()`) drifts from actual system volume due to two bugs in `alexa_custom/audio_ops.py`:

1. `_restore_hw_pcm()` is called but never imported — raises `NameError` on every slider interaction
2. `global _OUTPUT_VOLUME` writes to `audio_ops._OUTPUT_VOLUME`, but `get_output_volume()` reads from `audio_hw._OUTPUT_VOLUME` — slider snaps back after 2s

The volume *does* change (wpctl + beep), but the dashboard feedback loop is broken.

## Goals / Non-Goals

**Goals:**
- Web slider changes reflect immediately and persist in the dashboard
- No WebSocket crash on slider interaction
- All volume reads (`get_output_volume()`, playback scaling, system stats) return the post-slider value

**Non-Goals:**
- Refactoring the volume architecture (multiple module-scope globals)
- Changing how other callers (`actions.py`, `audio_watcher.py`) set volume
- Adding debouncing or smoothing to the slider

## Decisions

**Choice: Delegate to `set_output_volume()` with pulse=None**

`set_output_volume(pulse, output_spec, volume)` in `audio_hw.py` already does everything correctly — it writes to its own `_OUTPUT_VOLUME` global, runs `wpctl set-volume`, and calls `_restore_hw_pcm()`. The `pulse` parameter is unused in the function body, so `None` works fine.

This is preferred over direct module attribute assignment (`audio_hw._OUTPUT_VOLUME = ...`) because it keeps one canonical path for writing volume.

Changes to `set_output_volume_direct`:

```python
# After setting volume via set_output_volume(None, None, volume),
# call save_volume_config for persistence (set_output_volume doesn't do this).
```

**Import changes:**
- Remove `_restore_hw_pcm` from the import (not needed as a standalone call anymore)
- Add `set_output_volume` to the import from `audio_hw`

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| `set_output_volume` might later start using the `pulse` parameter | Function contract comment added; `None` is treated as skip-pulsectl. If pulse usage is added later, `set_output_volume_direct` will need an update. |
| `save_volume_config` needs to remain a separate call | Set it after `set_output_volume()` returns — preserves existing behavior |
