## 1. Rewrite PiperTTS.say() streaming path

- [x] 1.1 In `PiperTTS.say()`, replace chunk collection with a `paplay --raw` subprocess opened with `stdin=PIPE`; hold `_audio_lock` and set `_playback_active` before the first write
- [x] 1.2 Write preroll zero bytes (`preroll_ms * samplerate // 1000 * 2` bytes of `b'\x00'`) to paplay stdin before the first chunk
- [x] 1.3 For each chunk from `self._voice.synthesize(text)`, extract s16le bytes and write to paplay stdin
- [x] 1.4 Close paplay stdin, call `proc.wait()`, then clear `_playback_active`

## 2. Fallback when paplay absent

- [x] 2.1 At the top of `PiperTTS.say()`, check `shutil.which("paplay")`; if absent, fall back to the existing collect-all → WAV → `aplay -D pipewire` path
- [x] 2.2 Verify `shutil` is imported in `tts.py`

## 3. Cleanup

- [x] 3.1 Remove the numpy concatenation and WAV-write code from the main (paplay) path of `PiperTTS.say()`
- [x] 3.2 Remove the now-unused `_read_wav_as_float32` import/usage from the Piper path (keep it if PicoTTS still needs it — check)

## 4. Verify

- [x] 4.1 Run `task test` — confirm no regressions
- [x] 4.2 Run `task lint` — confirm clean
- [ ] 4.3 Manual smoke test: trigger a TTS response and confirm audio plays with correct preroll and no gaps
