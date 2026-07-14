## Why

On the Arduino Uno Q target, `config.audio.output_volume` and `config.audio.input_gain` do not produce the expected effect at runtime: output volume remains loud despite low values, and input gain appears to do nothing. Two structural problems are at the root:

1. `audio_hw.configure()` (the only function that updates the module-level `_OUTPUT_VOLUME` / `_INPUT_GAIN` globals from a `cfg` object) is defined but **never called** — config hot-reload does not propagate new audio values, and the AudioWatcher captures the values once at construction and never re-applies them.
2. `set_input_gain()` is a **software-only** no-op: it stores a value in a Python global that is then used by the capture pipeline to scale s16le PCM after the fact. The actual hardware source volume is only ever set by the one-shot `setup_audio` CLI (run at install time). On the NewPie this means the microphone preamp and AGC stay at whatever the device defaulted to, regardless of `config.audio.input_gain`.

A third problem compounds the output-volume symptom: the value is applied in **three places** (`wpctl set-volume` on the default sink, `--volume=` flag on `pw-play`, and digital scaling in `_play_array` / `tts.py`). The user can never tell which path is actually doing the work, and the wpctl path is the one that triggers the ALSA reinit/PCM-reset workaround documented in AGENTS.md.

The fix must not break development on Arch Linux, where the same code path runs against a different audio setup. The most fragile piece today is `_restore_hw_pcm()`, which is hardcoded to `amixer -c 0` — on a workstation with onboard audio at card 0 and a NewPie at a higher index, this would silently reset the user's speakers every time any `pulsectl` connection opens.

## What Changes

- Make `audio_hw.configure(cfg)` the single source of truth for audio parameter updates, and wire `config_manager` to call it on every hot-reload.
- Re-apply the current `output_volume` and `input_gain` to hardware each time the AudioWatcher detects a device transition (drop the "once" gate so the value always tracks the latest config).
- Change `set_input_gain()` from a software-only stub to a hardware-first operation: resolve the NewPie PipeWire source by name, then `pactl set-source-volume` against it. Software scaling in `stt_gating._apply_input_gain()` becomes a fallback used only when the source cannot be located.
- Collapse the three overlapping output-volume paths to a single one: digital scaling in `_play_array` / `tts.py`. Drop the `wpctl set-volume` call from `set_output_volume()` and the `--volume=` flag from `play_wav_file()`. This removes the trigger for the ALSA-reinit PCM-reset workaround for the output path.
- Make `_restore_hw_pcm()` portable: resolve the NewPie card index dynamically via `_find_alsa_card("NewPie")` and skip the call entirely when the card is absent. The pre-existing helper `audio_hw._find_alsa_card` is reused.
- Add tests covering: `set_input_gain` calls `pactl` when source is found, `set_input_gain` is a no-op when the source is missing, `_restore_hw_pcm` is a no-op when no NewPie is connected, and the hot-reload callback actually re-applies the values.
- Update `AGENTS.md` to reflect the simpler `_restore_hw_pcm` semantics and the dropped `wpctl` call (workaround #5 can be slimmed).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `audio-management`: The audio module gains explicit "apply at runtime" semantics for `output_volume` and `input_gain`, hardware-first input gain with software fallback, and a portable `_restore_hw_pcm` that no-ops when the NewPie is absent. The `configure(cfg)` requirement is clarified to be the single source of truth for hot-reload.

## Impact

- `alexa_custom/audio_hw.py` — modify `set_output_volume`, `set_input_gain`, `_restore_hw_pcm`, and wire `configure()` to be called.
- `alexa_custom/audio_watcher.py` — drop the "once" gate so volume/gain are re-applied on every device connect / enforce cycle.
- `alexa_custom/audio_ops.py` — drop the `pw-play --volume=` flag from `play_wav_file` (digital scaling in `_play_array` is unchanged and covers in-app audio).
- `alexa_custom/tts.py` — no code change; the existing digital scaling becomes the only path.
- `alexa_custom/client.py` — register a `config_manager` reload callback that calls `audio_hw.configure()` and re-applies the values.
- `tests/test_audio.py` — add tests for the new behavior.
- `AGENTS.md` — slim workaround #5 to reflect that `wpctl set-volume` is no longer called from this path.
- `openspec/specs/audio-management/spec.md` — delta spec for the modified requirements.
