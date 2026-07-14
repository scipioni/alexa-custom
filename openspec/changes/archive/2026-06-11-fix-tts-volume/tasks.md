## 1. Fix audio_ops.py — Remove software volume scaling

- [x] 1.1 In `_play_array()`, remove line `audio = audio * get_output_volume()` (the double-application fix)
- [x] 1.2 In `play_wav_file()`, keep `pw-play --volume=` flag as the sole mechanism for that path (already correct — no change needed)
- [x] 1.3 Run targeted tests to verify no regression in audio playback tests

## 2. Fix tts.py — Remove stale import and software scaling from streaming path

- [x] 2.1 In `_say_streaming()`, replace `_audio_module._OUTPUT_VOLUME` with `get_output_volume()` from `alexa_custom.audio_hw`
- [x] 2.2 Remove the `scaled_arr` variable and its int16 multiplication — write raw `arr` bytes to `paplay` stdin instead
- [x] 2.3 Update the RMS metering calculation to multiply by `get_output_volume()` so the VU meter still reflects the attenuated output level
- [x] 2.4 Remove the now-unnecessary `alexa_custom.audio as _audio_module` import — import from `audio_hw` and `audio_ops` directly instead

## 3. Verify end-to-end

- [x] 3.1 Run `task lint` to check for style issues
- [x] 3.2 Run targeted tests for audio and TTS — all pass
- [ ] 3.3 Manual verification: start the daemon, change volume via web slider, confirm TTS speech matches the expected level
