## Context

The current implementation has three structural problems around `output_volume` and `input_gain`:

1. **`audio_hw.configure()` is dead code.** It is defined at `audio_hw.py:26` and re-exported from `audio.py:21` for "backward compatibility", but no live source file invokes it. The module-level globals `_OUTPUT_VOLUME` (line 18) and `_INPUT_GAIN` (line 19) keep their module-import defaults until `set_output_volume()` / `set_input_gain()` are called. Those are called only once per AudioWatcher device connect (`audio_watcher.py:77-82`), gated by `self._volume_set` / `self._gain_set`. Changing `config.yaml` and waiting for hot-reload therefore does not change runtime audio behaviour.

2. **Input gain is software-only.** `set_input_gain()` (`audio_hw.py:216-222`) only mutates `_INPUT_GAIN`. The capture pipeline in `stt_gating._apply_input_gain()` (`stt_gating.py:72-78`) reads the value and scales s16le PCM **after** `parec` has already captured it from the NewPie's mic. The NewPie's actual hardware mic gain / preamp is set only by the one-shot `setup_audio` CLI (`audio_hw.py:604-610`, `pactl set-source-volume`). If the user has never re-run `setup_audio` since changing `input_gain`, or if the NewPie re-enumerated with a different default, the hardware input stage is at whatever it last was, and the software scaling only changes the signal sent to the STT backend — which is invisible to the user.

3. **Output volume is applied in three places.** `set_output_volume()` (A) calls `wpctl set-volume @DEFAULT_AUDIO_SINK@`; `play_wav_file` (B) passes `--volume=…` to `pw-play`; `_play_array` and `tts.py` (C) multiply the audio by `get_output_volume()` in software. At `output_volume=0.3` the effective attenuation is the product of all three that are actually firing — which is non-obvious and varies by which playback path is in use.

The `wpctl set-volume` path is also the trigger for the ALSA-reinit PCM-reset workaround documented in `AGENTS.md` #5: WirePlumber re-initialises the ALSA chain on every volume change, the NewPie's `PCM` mixer resets to 0%, and `_restore_hw_pcm()` (line 67) is called to force it back to 100%. That workaround itself is hardcoded `amixer -c 0` — on a workstation where the NewPie is not card 0, this resets the wrong card's volume.

## Goals / Non-Goals

**Goals:**

- `output_volume` and `input_gain` values in `config.yaml` take effect at runtime, including after a hot-reload (no daemon restart required).
- `input_gain` actually changes the NewPie's hardware mic sensitivity, not just a software gain applied after capture.
- `output_volume` has a single, predictable effect on loudness — `0.3` means 30% loud, full stop.
- The change is safe on Arch dev: no surprise hardware volume resets on the workstation's own audio, no breakage when the NewPie is absent, no breakage when the NewPie is at a non-zero card index.
- AGENTS.md workaround #5 can be slimmed or its PCM-reset section removed for the output path.
- Existing tests in `tests/test_audio.py` continue to pass; new tests cover the new behaviour.

**Non-Goals:**

- No dashboard UI changes in this change (no sliders). The dashboard already exposes the current `input_gain` value as a read-only display element; that stays as-is. A future change can add runtime control via WebSocket.
- No changes to the capture pipeline itself (the `parec` invocation, downmix, gating logic). The capture path is unchanged; only what feeds into `_apply_input_gain` changes.
- No changes to the TTS engine or `piper-tts` integration.
- No changes to `setup_audio` CLI semantics — that remains a one-shot install-time configuration. The new runtime `set_input_gain` complements it but does not replace it.
- No new dependencies.

## Decisions

### D1: Single output-volume path — keep digital scaling only

Drop the `wpctl set-volume` call from `set_output_volume()` and the `--volume=` flag from `play_wav_file()`. Keep the digital scaling in `_play_array` (`audio_ops.py:58`), `tts.py:192`, and the equivalent path in any other playback code.

Rationale:
- Digital scaling is the most predictable (no PipeWire timing, no WirePlumber reinit, no `wpctl` semantic surprises).
- It has no effect on the system mixer, so it does not interfere with the user's other audio sessions on the workstation.
- It removes the trigger for the AGENTS.md #5 PCM-reset workaround on the output path.
- The one drawback (system-level volume control is not driven by `output_volume`) is acceptable because the digital path applies the same value to all audio we generate.

### D2: Input gain — hardware-first, software fallback

`set_input_gain()` now performs, in order:
1. Resolve the NewPie PipeWire source by name (reuse the inline block from `setup_audio` at `audio_hw.py:587-611`, refactored into a helper).
2. If a source is found, call `pactl set-source-volume <source> <pct>%` where `pct = int(gain * 100)`.
3. If `pulsectl.Pulse()` was opened during the resolution, call `_restore_hw_pcm()`.
4. Always update `_INPUT_GAIN` (for the software fallback path and for downstream consumers like the dashboard display).

The software scaling in `stt_gating._apply_input_gain()` becomes the **fallback** that activates only when the source cannot be located (e.g. NewPie unplugged at the moment of the call). It is no longer the primary mechanism.

Rationale:
- Matches user mental model: "input gain is the mic knob".
- Survives the NewPie being re-enumerated (the source name is re-resolved on each call, not cached).
- The fallback is still useful for unit tests and for the edge case where the daemon is running but the device is briefly missing.

### D3: Portability of `_restore_hw_pcm()` — dynamic NewPie card discovery

Replace the hardcoded `card=0` default with a runtime call to the existing `_find_alsa_card("NewPie")` helper. If it returns `None`, the function is a no-op.

```python
def _restore_hw_pcm() -> None:
    card = _find_alsa_card("NewPie")
    if card is None:
        return  # no NewPie connected → nothing to restore
    card_index, _ = card
    subprocess.run(
        ["amixer", "-c", str(card_index), "sset", "PCM", "100%"],
        capture_output=True, check=False,
    )
```

Rationale:
- Arch dev without a NewPie plugged in: no-op, no surprise resets of the workstation's audio.
- Arch dev with a NewPie at a non-zero card index: still works.
- Uno Q: identical behaviour to today (NewPie is card 0).
- One `os.listdir("/proc/asound")` per call — negligible.

The `setup/99-newpie-no-autosuspend.rules` udev rule and the `alsa-pcm-unmute.service` still run `amixer` directly; that is independent of this Python helper and is not touched.

### D4: Hot-reload — wire `configure()` via `ConfigManager.register_reload_callback`

In `client.py` (or wherever the `ConfigManager` and `AudioWatcher` are wired up), register a reload callback that:

1. Calls `audio_hw.configure(new_config)` to update `_OUTPUT_VOLUME` and `_INPUT_GAIN`.
2. Opens a `pulsectl.Pulse()` connection.
3. Calls `set_output_volume(pulse, output_spec, new_config.audio.output_volume)`.
4. Calls `set_input_gain(pulse, input_spec, new_config.audio.input_gain)`.
5. Calls `_restore_hw_pcm()`.

The `AudioWatcher` is modified to drop the `self._volume_set` / `self._gain_set` "once" gates, so that on every device-connect or enforce cycle it re-applies the current values from the module-level globals (which `configure()` keeps fresh). This makes the watcher and the reload callback two independent paths that converge on the same module state.

Rationale:
- Uses the existing `ConfigManager.register_reload_callback` API (`config_manager.py:21-22`); no new infrastructure.
- `configure()` becoming a real entry point also benefits future changes that want to mutate audio settings programmatically.

### D5: Test surface

Add to `tests/test_audio.py`:

- `test_set_input_gain_calls_pactl_when_source_found` — mock `pulsectl.Pulse`, mock `subprocess.run` for `pactl set-source-volume`, assert it is called with the right percentage.
- `test_set_input_gain_noop_when_source_not_found` — mock the source-list call to return no matching source, assert `pactl set-source-volume` is NOT called and `_INPUT_GAIN` is still updated.
- `test_restore_hw_pcm_noop_without_newpie` — mock `_find_alsa_card` to return `None`, assert `amixer` is not called.
- `test_configure_propagates_to_globals` — call `audio_hw.configure(cfg)` and assert `_OUTPUT_VOLUME` and `_INPUT_GAIN` match the new config.

The existing test `test_play_array_scales_by_output_volume` continues to pass unchanged (digital scaling path is preserved).

## Risks / Trade-offs

- **NewPie source name stability.** The source name from `pactl list sources` should be stable for the same USB device across reboots, but a few USB devices append a serial or hash. If the NewPie's source name is unstable on the Uno Q, the new `set_input_gain` will fail to locate it and silently fall back to software scaling. Mitigation: log a warning at INFO level when the source is not found, so the user can see the fallback in action. If this becomes a problem, we can switch to card-index-based matching (already used by `_find_alsa_card`).
- **`pactl set-source-volume` upper bound.** Some USB mics accept up to 100% only; some accept 150% or more. Today `setup_audio` does not cap (it computes `int(gain * 100)`). We follow the same convention and document the limitation. If a user reports clipping at high gain, we can add a cap to `set_input_gain` (e.g. `min(150, int(gain * 100))`).
- **Double-pulsectl open on hot-reload.** The reload callback opens a `pulsectl.Pulse()` connection, which itself triggers the ALSA reinit. We call `_restore_hw_pcm()` immediately after to compensate, but there is a small window in which a concurrent `pw-play` could clip. Acceptable for now (the same window exists today on every `set_output_volume` call); can be tightened later with a single shared connection.
- **Behavioural change for users who set `output_volume` expecting the system mixer to track it.** The system mixer no longer moves; only the in-app audio is attenuated. We will surface this in the change release notes and in `docs/configuration.md`.
- **Dropping `pw-play --volume=`.** This is a per-stream volume flag and is technically orthogonal to the sink volume, but dropping it simplifies the model and aligns with the digital-scaling-only decision. No other code in this repo passes a `--volume` flag to `pw-play`.

## Migration Plan

- Land in a single change, behind no feature flag (the prior behaviour is broken; there is no working state to preserve).
- Update `AGENTS.md` workaround #5 to reflect the simpler model.
- No config schema changes (existing `output_volume` and `input_gain` fields keep their meaning, only their effect changes).
- Rollback: revert the commit. No data migration, no persistent state beyond the config file.

## Open Questions

- Should the reload callback also push the values to the `AudioWatcher` instance (mutate `self.output_volume` and `self.input_gain`), or is it sufficient that `configure()` updates the module globals and the watcher reads them at enforce time? The current proposal is the latter (simpler, fewer moving parts). If we want the watcher to log a clear "re-applied volume" line on hot-reload, we may need the former.
- Should the dashboard's "input_gain" display (currently a static ×1.0 read-out) be re-labeled to indicate it is a config-time value, not a runtime signal level? Out of scope for this change but worth a follow-up.
