## 1. Firmware — text scrolling engine

- [x] 1.1 Add 5×7 bitmap font data (ASCII 0x20–0x7E) to `display_firmware.ino` in PROGMEM
- [x] 1.2 Implement `scroll_text(text, speed_ms)` RPC that stores text and starts scroll state
- [x] 1.3 Implement scroll tick logic in `loop()`: shift a 13-column viewport over the rendered text, advancing every `speed_ms` milliseconds
- [x] 1.4 Ensure `set_icon()` call aborts active scroll and switches to icon display

## 2. Firmware — new icon bitmaps

- [x] 2.1 Add smiley face bitmap (`uint8_t[8][13]`) for `ICON_IDLE`
- [x] 2.2 Add sound wave animation frames (6 frames) for `ICON_LISTENING` / `ICON_SPEAKING`
- [x] 2.3 Add rotating gear animation frames (4 frames) for `ICON_THINKING`
- [x] 2.4 Wire `setup()` to call `scroll_text("Coop. Galileo", 100)` instead of `set_icon(ICON_IDLE)`

## 3. Firmware — icon ID mapping

- [x] 3.1 Ensure `ICON_LISTENING` and `ICON_SPEAKING` both render the same wave animation (same frame data via aliased switch case)
- [x] 3.2 Remove or replace unused bitmap arrays (idle_eye, hourglass, bar-scan frames, old speak frames)

## 4. Python — display.py updates

- [x] 4.1 Add `scroll_text(text, speed_ms=100)` method to `_BridgeClient`
- [x] 4.2 Handled by firmware boot scroll — daemon transition to idle naturally aborts scroll when `set_icon(ICON_IDLE)` is called
- [x] 4.3 Verify `STATE_ICON_IDS` mapping aligns with new firmware icon order

## 5. Testing

- [x] 5.1 Run existing display tests: `uv run pytest tests/test_display.py`
- [ ] 5.2 Flash firmware to Arduino UNO Q and verify all animations visually
- [ ] 5.3 Verify scrolling text appears on boot and transitions to idle when daemon connects

## 6. Documentation

- [ ] 6.1 Sync delta specs to main specs (`/opsx-sync` after implementation)
