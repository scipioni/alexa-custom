## Context

The system has two independent volume control mechanisms that stack multiplicatively:

1. **Software scaling** in Python — `_play_array()` multiplies float32 samples by `get_output_volume()`; `_say_streaming()` multiplies int16 samples by `_audio_module._OUTPUT_VOLUME`
2. **PipeWire sink volume** — `set_output_volume()` calls `wpctl set-volume @DEFAULT_AUDIO_SINK@`

Both are set to the same value, so the effective volume is `volume²` (quadratic). Additionally, the TTS streaming path reads `_OUTPUT_VOLUME` via a stale import binding (`from audio_hw import _OUTPUT_VOLUME` copies the float by value at import time), so it never reflects runtime volume changes.

The correct architecture: **one volume control, one source of truth**. PipeWire sink volume (`wpctl`) is the natural choice — it's hardware-accelerated, applies to all audio paths (including LiveKit calls), and is already the mechanism used for the web dashboard and voice presets.

## Goals / Non-Goals

**Goals:**
- TTS respects the output volume with a linear response
- All playback paths (TTS streaming, TTS fallback, tones, beeps, WAV files) produce consistent volume levels
- Single volume control mechanism — no double-application

**Non-Goals:**
- Changing how volume is stored or persisted
- Changing the volume slider UI or voice preset infrastructure
- Adding per-stream volume controls (e.g., separate TTS vs. notification volume)
- Changing the LiveKit volume path (that's handled by the LiveKit SDK)

## Decisions

### Decision 1: Remove software scaling, keep `wpctl` sink volume as the single mechanism

**Chosen**: Remove `audio = audio * get_output_volume()` from `_play_array()` and the equivalent int16 scaling from `_say_streaming()`. `wpctl set-volume @DEFAULT_AUDIO_SINK@` remains the single volume control.

**Rationale**:
- `wpctl` sink volume applies to ALL audio passing through the PipeWire graph, including `paplay` (via pipewire-pulse compat), `pw-play`, and LiveKit's audio output
- No double-application — one linear control
- No change to how the web slider or voice presets work — they already set `wpctl` volume + `_OUTPUT_VOLUME`; after the fix, setting `_OUTPUT_VOLUME` is still useful for persistence and UI display, but the actual audio attenuation is entirely in `wpctl`

**Alternatives considered**:
- Remove `wpctl` calls, keep only software scaling → would not affect LiveKit call audio or other non-Python audio paths
- Normalize to a single volume factor (e.g., `sqrt(volume)`) → hack, doesn't fix the architectural problem
- Use `pw-play --volume=` flag instead → only works for the `_play_array`/`play_wav_file` paths, not for the streaming TTS path using `paplay`

### Decision 2: Fix the stale import in `_say_streaming()`

**Chosen**: Switch `_say_streaming()` to use `get_output_volume()` instead of `_audio_module._OUTPUT_VOLUME`.

**Rationale**: `get_output_volume()` is a function that always reads the live value from `audio_hw._OUTPUT_VOLUME`. After Decision 1 (removing software scaling), we still need the volume value for RMS metering — the scaling line in `_say_streaming()` is removed, but the RMS calculation on line 197 already uses the local `scaled_arr` variable that will go away. The metering should report the actual output level, which we can get from the raw (unscaled) audio or simply report the volume setting.

**Alternatives considered**:
- Fix the import by re-importing or using `getattr` → more fragile, doesn't address the architectural problem
- Re-export via `audio_hw.get_output_volume` in `audio.py` → the function is already accessible, we just need to use it

## Risks / Trade-offs

- **[Removing software scaling]** If `wpctl set-volume` fails or is overridden by another process, there's no software fallback for volume control → Mitigation: `set_output_volume()` already logs failures, and the AudioWatcher re-applies volume on device reconnect
- **[Removing software scaling]** Perceived loudness of tones/beeps may change slightly since they were previously scaled twice → Mitigation: the effective volume at common levels (50%, 75%, 100%) will be audibly correct — this is fixing a bug, not changing behavior
- **[Timing]** The software scaling fix is in the streaming TTS path where audio should already start quickly; removing a multiplication operation per chunk has negligible performance impact
