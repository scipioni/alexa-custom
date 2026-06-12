## 1. Digital gain in _play_array

- [x] 1.1 Add `volume = get_output_volume()` before the int16 conversion line
- [x] 1.2 Change `np.ascontiguousarray(audio) * 32767` to `np.ascontiguousarray(audio) * volume * 32767`

## 2. Digital gain in _play_raw

- [x] 2.1 Extract float32 buffer into a named variable before int16 conversion
- [x] 2.2 Multiply samples by `get_output_volume()` before the `* 32767` scaling

## 3. Digital gain in Piper streaming

- [x] 3.1 In `PiperTTS._say_streaming()`, read `get_output_volume()` before the write loop
- [x] 3.2 Scale `arr` by volume as float before `proc.stdin.write(arr.tobytes())`

## 4. wpctl set-volume uses unity

- [x] 4.1 In `set_output_volume()`, change `f"{volume:.4f}"` to `"1.0"` in the wpctl subprocess args
- [x] 4.2 Verify `_restore_hw_pcm()` still runs after the wpctl call

## 5. Verify

- [x] 5.1 Run `uv run pytest tests/test_audio.py` to confirm existing tests pass
- [x] 5.2 Run `uv run pytest tests/test_tts.py` to confirm TTS tests pass
- [x] 5.3 Run `ruff check + format --check` on all modified files
