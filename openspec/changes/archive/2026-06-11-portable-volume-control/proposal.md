## Why

Volume control (`set_output_volume`) relies on `wpctl set-volume @DEFAULT_AUDIO_SINK@`, which only works when the NewPie USB speakerphone is the system's default PipeWire sink. On the Arduino Uno Q (Debian Trixie, PipeWire 1.4.2), the NewPie is often NOT the default sink — WirePlumber fails to re-route after late USB discovery. Volume changes silently go to the wrong sink, leaving the NewPie at full blast regardless of the setting. This makes the assistant unusable in environments where consistent output volume is required.

## What Changes

- Add digital gain scaling in `_play_array()` and `_play_raw()` so volume is applied in the application layer, independent of PipeWire sink routing
- Add digital gain scaling in Piper streaming path (`_say_streaming()`) for the same reason
- Change `set_output_volume()` to set the PipeWire sink to 100% (unity) instead of the variable volume, since volume is now handled digitally
- Remove the double-attenuation risk where both `wpctl` and digital gain could apply

## Capabilities

### New Capabilities
- `portable-volume`: Application-level digital volume control that works regardless of PipeWire sink configuration, default routing, or WirePlumber behavior

### Modified Capabilities

None — this is a new capability, not a change to existing requirements.

## Impact

- `alexa_custom/audio_ops.py` — `_play_array()` and `_play_raw()` gain a `volume *` scaling factor before int16 conversion
- `alexa_custom/tts.py` — Piper streaming path scales samples before writing to paplay stdin
- `alexa_custom/audio_hw.py` — `set_output_volume()` sets wpctl to 1.0 instead of the variable volume; `_restore_hw_pcm()` unchanged
- No new dependencies. No config changes. No breaking API changes.
- On the dev system (Arch), wpctl still runs but at unity — behavior is identical from the user's perspective (volume slider maps 0-100% in both cases)
