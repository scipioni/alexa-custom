## 1. Display font extraction

- [x] 1.1 Create `alexa_custom/display_fonts.py` and move the `_FONT5X7` byte data into it as `FONT5X7`
- [x] 1.2 Remove the module-level font from `display.py`; import it lazily inside `_Ssd1306` (at construction or first render), updating the reference at the former line 966 usage
- [x] 1.3 Add a guard test: a bare `import alexa_custom.display` does not materialize the font (assert the font symbol is not bound on the display module)
- [x] 1.4 Add/keep a test asserting OLED glyph rendering output is byte-identical to before
- [x] 1.5 Run `uv run pytest tests/test_display.py` — green

## 2. Audio runtime/diagnostic split

- [x] 2.1 Create `alexa_custom/audio_diagnostic.py`; move `list_devices`, `speakerphone`, `list_env_devices`, `setup_audio`, `audio_doctor` and their private helpers (`_find_alsa_card`, `_amixer_pcm_percent`, `_usb_ids_for_alsa_card`, `_find_pipewire_source`) out of `audio_hw.py`
- [x] 2.2 Have `audio_diagnostic.py` import the runtime names it needs from `audio_hw` (direction: diagnostics → runtime only)
- [x] 2.3 Update `audio.py` facade to re-export the moved names so `main`, `main_devices`, `main_test`, `setup_audio`, `main_doctor` resolve unchanged
- [x] 2.4 Confirm no internal module imports a moved CLI function directly (grep); fix any to go through the facade if found
- [x] 2.5 Run `uv run pytest tests/test_audio.py` — green

## 3. Validation

- [x] 3.1 `task lint` clean
- [x] 3.2 `task test` green (full suite)
- [ ] 3.3 Manually invoke `alexa-devices` and `alexa-audio-doctor` (or `task audio:status`/`audio:doctor`) to confirm CLI entry points still work after the split
