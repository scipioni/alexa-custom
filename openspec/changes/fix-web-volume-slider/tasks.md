## 1. Fix `set_output_volume_direct` in audio_ops.py

- [x] 1.1 Add `set_output_volume` to the import from `alexa_custom.audio_hw`
- [x] 1.2 `_restore_hw_pcm` was never imported — no-op
- [x] 1.3 Replaced body with delegation to `set_output_volume(None, None, volume)` + `save_volume_config`
- [x] 1.4 Verified `set_output_volume` doesn't call `save_volume_config` — kept the call after delegation

## 2. Verify the fix

- [x] 2.1 Run `ruff check` — all checks passed (format issue in `alexa-custom/` is pre-existing)
- [x] 2.2 Run `uv run pytest tests/` — blocked by vosk wheel missing on macOS (pre-existing); ruff check confirms import/syntax correctness
- [ ] 2.3 Start the daemon on the target board and drag the web volume slider — confirm slider stays at the set position and no WebSocket disconnect
