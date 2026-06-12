## Why

TTS playback (Piper streaming path via `paplay`) ignores the system output volume because it reads a stale import-time copy of `_OUTPUT_VOLUME` instead of the live value. Beeps, tones, and the TTS WAV-fallback path work correctly — only the primary streaming TTS path is broken. Additionally, even after fixing the stale read, all audio paths apply volume twice (software scaling + PipeWire sink volume), producing a quadratic response that makes low-volume settings much quieter than expected.

## What Changes

- Fix the stale import bug in `tts.py` so the Piper streaming path reads the live output volume via `get_output_volume()` instead of the frozen module attribute `audio._OUTPUT_VOLUME`
- Remove the redundant software volume scaling from the TTS streaming path, relying solely on PipeWire sink volume (`wpctl set-volume`) for volume control
- Remove the redundant software volume scaling from `_play_array()` in `audio_ops.py`, relying solely on PipeWire sink volume
- Keep `play_wav_file()`'s `pw-play --volume=` flag as the single volume mechanism for that path
- All playback paths now produce linear volume response matching the volume slider/preset value

## Capabilities

### New Capabilities
*(none — this is a bug fix and architectural cleanup, not a new capability)*

### Modified Capabilities
- `piper-streaming-playback`: The streaming path SHALL apply the system output volume linearly. Currently the spec is silent on volume behavior; no requirements are changed, but the behavior is now specified.
- `audio-management`: Volume state persistence and restoration requirements are unaffected — the fix only changes HOW volume is applied, not WHERE it's stored or how it's restored.

## Impact

- `alexa_custom/tts.py` — remove software scaling from `_say_streaming()`, switch to `get_output_volume()` (the fix also resolves the stale import bug)
- `alexa_custom/audio_ops.py` — remove software scaling from `_play_array()`, remove the redundant `pw-play --volume=` flag from `play_wav_file()`
- Volume slider (web) and voice presets continue to work identically — they set `wpctl sink volume` which is now the single source of truth
- RMS level metering in `_say_streaming()` continues to use the scaled (post-volume) audio for accurate playback level display
