## 1. Refactor: source-locator helper

- [x] 1.1 Extract the inline PipeWire source lookup from `setup_audio()` (`audio_hw.py:587-611`) into a module-level helper `_find_pipewire_source(input_spec: str | None) -> tuple[str | None, str | None]` returning `(pulse_source_name, alsa_card_id)`. Reuse the matching logic verbatim.
- [x] 1.2 Refactor `setup_audio()` to call the new helper; confirm the install-time behaviour is unchanged by running it on the Uno Q after the change lands.

## 2. Make `_restore_hw_pcm()` portable

- [x] 2.1 Change the signature of `_restore_hw_pcm()` to take no `card` argument (or keep the argument as an override for tests, defaulting to dynamic lookup).
- [x] 2.2 Replace the hardcoded `amixer -c 0` with `_find_alsa_card("NewPie")` lookup. If the lookup returns `None`, log a debug message and return without invoking `amixer`.
- [x] 2.3 Audit every existing call site of `_restore_hw_pcm()` (`audio_hw.py:162`, `audio_hw.py:213`, `audio_watcher.py:54`, `audio_watcher.py:76`, `audio.py:170`) and confirm none of them rely on the old card-0 default.
- [x] 2.4 Update `AGENTS.md` workaround #5: the "after every pulsectl interaction" rule still applies, but the PCM-reset-on-`wpctl-set-volume` sub-bullet can be removed since we no longer call `wpctl` from the runtime path.

## 3. `set_output_volume()` — drop the `wpctl` path

- [x] 3.1 Remove the `subprocess.run(["wpctl", "set-volume", ...])` call from `set_output_volume()` (`audio_hw.py:202-210`).
- [x] 3.2 Keep the `_OUTPUT_VOLUME = volume` global update and the early-return for `volume <= 0`.
- [x] 3.3 Keep the `_restore_hw_pcm()` call at the end of `set_output_volume()` (defensive; cheap with the new dynamic lookup).
- [x] 3.4 Update the docstring at `audio_hw.py:197` to reflect the new semantics ("Set the in-app output volume scalar; the system mixer is no longer touched").

## 4. `set_input_gain()` — hardware-first with software fallback

- [x] 4.1 Add the new source-locator call at the top of `set_input_gain()`.
- [x] 4.2 If a source is found, run `pactl set-source-volume <source> <pct>%` where `pct = int(gain * 100)`. Use `subprocess.run` with `check=False` and log a warning on non-zero returncode (matching the existing pattern in `setup_audio`).
- [x] 4.3 If the lookup required opening a `pulsectl.Pulse()` connection, call `_restore_hw_pcm()` after closing it.
- [x] 4.4 Always update `_INPUT_GAIN = max(0.0, gain)` at the end.
- [x] 4.5 Log at INFO level on success ("Mic gain set to N% on <source>") and at WARNING level on fallback ("NewPie source not found; input gain applies as software scaling only").
- [x] 4.6 Add a guard to prevent concurrent calls from racing on the global (mirror the lock used by `_audio_lock` in `audio_ops.py`, or use a simple module-level `_input_gain_lock`).

## 5. `play_wav_file()` — drop the `--volume=` flag

- [x] 5.1 In `audio_ops.py:155`, remove the `f"--volume={get_output_volume():.4f}"` argument. Pass `tmp_path` (or the file path) directly.
- [x] 5.2 Add a comment explaining that digital scaling in `_play_array` is the single source of output-volume attenuation, and that the system mixer is intentionally not driven by `output_volume`.

## 6. `AudioWatcher` — drop the "once" gate

- [x] 6.1 In `audio_watcher.py`, remove the `self._volume_set` and `self._gain_set` boolean flags and their associated `if not self._*_set:` guards (lines 41-42, 77-82).
- [x] 6.2 In `_check_and_enforce`, always call `set_output_volume(pulse, self.output_spec, self.output_volume)` and `set_input_gain(pulse, self.input_spec, self.input_gain)` on every device-connect or enforce cycle (gated only on `self.output_volume > 0` and `self.input_gain > 0` respectively).
- [x] 6.3 Confirm that the `audio_watcher` is not re-instantiated on config hot-reload (verify by reading the `ConfigManager` reload callback path); the watcher will pick up the new values from the module-level globals on the next enforce cycle.

## 7. Hot-reload — wire `audio_hw.configure()`

- [x] 7.1 In `client.py` (or wherever the `ConfigManager` is wired up — verify by reading `web.py:551-558` and `client.py:1010-1100`), register a `config_manager.register_reload_callback(...)` callable.
- [x] 7.2 The callback receives the new `ActionsConfig` and:
  - [x] 7.2.1 calls `audio_hw.configure(new_config)` to refresh `_OUTPUT_VOLUME` and `_INPUT_GAIN`
  - [x] 7.2.2 opens a `pulsectl.Pulse("alexa-reload")` context
  - [x] 7.2.3 calls `set_output_volume(pulse, output_spec, new_config.audio.output_volume)`
  - [x] 7.2.4 calls `set_input_gain(pulse, input_spec, new_config.audio.input_gain)`
  - [x] 7.2.5 closes the pulsectl context and calls `_restore_hw_pcm()`
  - [x] 7.2.6 logs at INFO level ("Audio config reloaded: output_volume=0.30, input_gain=1.50")
- [x] 7.3 Confirm the callback runs only inside the asyncio loop (or runs the pulsectl work in a thread to avoid blocking the watcher).

## 8. Tests

- [x] 8.1 Add `test_set_input_gain_calls_pactl_when_source_found` to `tests/test_audio.py`. Mock `pulsectl.Pulse`, `subprocess.run` for `pactl`, and assert `pactl set-source-volume` is called with the right `<pct>%` argument.
- [x] 8.2 Add `test_set_input_gain_noop_when_source_not_found`. Mock the source list to return no matching source, assert `pactl` is NOT called, assert `_INPUT_GAIN` is still updated.
- [x] 8.3 Add `test_restore_hw_pcm_noop_without_newpie`. Mock `_find_alsa_card` to return `None`, assert `amixer` is not invoked.
- [x] 8.4 Add `test_configure_propagates_to_globals`. Call `audio_hw.configure(cfg)` with a fake `AudioConfig(output_volume=0.3, input_gain=1.5)`, assert `_OUTPUT_VOLUME == 0.3` and `_INPUT_GAIN == 1.5`.
- [x] 8.5 Add `test_set_output_volume_no_longer_calls_wpctl`. Mock `subprocess.run`, call `set_output_volume(...)`, assert no invocation matches `["wpctl", "set-volume", ...]`.
- [x] 8.6 Verify the existing `test_play_array_scales_by_output_volume` and `test_play_wav_file_applies_volume` tests still pass. The second one (which asserts `--volume=0.2500` in the `pw-play` command) **will need to be updated** since the `--volume=` flag is being removed; replace it with a test that asserts the `pw-play` command does not contain `--volume`.

## 9. Docs

- [x] 9.1 Update `docs/configuration.md` to clarify that `output_volume` scales in-app audio in software and does not change the system mixer.
- [x] 9.2 Update `docs/configuration.md` (or `docs/audio.md` if it covers this) to clarify that `input_gain` is set on the NewPie's PipeWire source volume at runtime, with software scaling as a fallback when the source is unavailable.
- [x] 9.3 Slim `AGENTS.md` workaround #5 to reflect that `wpctl set-volume` is no longer called from the runtime path; the "after every pulsectl interaction" rule still applies for the remaining pulsectl opens (routing, source list, watcher events).

## 10. Manual verification (Uno Q)

- [ ] 10.1 Connect the NewPie, start the daemon with `output_volume: 0.3` in `config.yaml`, play a TTS line, confirm it is audibly quieter than `output_volume: 1.0`.
- [ ] 10.2 Set `input_gain: 2.0` in `config.yaml`, restart, speak into the mic, confirm the VU meter (or the STT confidence) reflects the higher level.
- [ ] 10.3 Edit `config.yaml` to change `output_volume` from 0.3 to 0.6 while the daemon is running, wait for hot-reload, play a TTS line, confirm the volume changed without a daemon restart.
- [ ] 10.4 Same for `input_gain`: edit while running, confirm the new value takes effect on the next STT cycle.

## 11. Manual verification (Arch dev)

- [ ] 11.1 With no NewPie connected, run `alexa-audio --list` and confirm no `amixer -c … sset PCM 100%` is invoked (verify by `strace -e trace=execve` or by checking that the workstation's existing audio settings are unchanged).
- [ ] 11.2 With a NewPie connected at a non-zero card index, run the daemon and confirm `_restore_hw_pcm()` targets the NewPie card, not card 0.
- [ ] 11.3 Confirm the existing `setup_audio` flow on Arch dev continues to work (the refactor in §1.1 should leave its behaviour unchanged).
