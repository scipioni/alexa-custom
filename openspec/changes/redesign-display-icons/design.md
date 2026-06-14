## Context

The Arduino UNO Q has an STM32U585 coprocessor driving an 8×13 LED matrix and two RGB LEDs. Communication between the MPU (Snapdragon 801, Python daemon) and STM32 happens via ArduinoRouterBridge RPC over UART/TCP/Unix socket. The current firmware (`setup/display_firmware/display_firmware.ino`) stores icon bitmaps as `uint8_t[8][13]` PROGMEM arrays and renders them via `Arduino_LED_Matrix` library.

The architecture has two tiers of animation:
- **Firmware-level animation**: Ping-pong frame cycling in `loop()` (used by listening bar-scan and speaking wave)
- **Python-level state transitions**: `DisplayController` resolves events to state strings, then calls `backend.show(state)` which RPCs `set_icon(id)` to the firmware

## Goals / Non-Goals

**Goals:**
- Replace `ICON_IDLE` bitmap (eyes) with a smiley face
- Add `ICON_STARTUP` or repurpose `ICON_STARTING` to scroll "Coop. Galileo" text
- Replace `ICON_LISTENING` bar-scan animation with a sound-wave VU-meter animation
- Replace `ICON_THINKING` hourglass with rotating gear(s) animation
- Reuse the wave animation for `ICON_SPEAKING` (same icon ID as listening, or a separate ID pointing to the same bitmap set)
- Add a 5×7 pixel ASCII font to the firmware and a `scroll_text()` RPC
- Keep the RPC contract backward-compatible where possible

**Non-Goals:**
- No changes to RGB LED colors or STATE_COLORS mapping
- No changes to the I²C OLED backend (SSD1306)
- No changes to the mock or GPIO backends
- No changes to the config schema
- No changes to the Python event dispatch logic

## Decisions

### Decision 1: Firmware font — bundle a minimal 5×7 ASCII subset
- **Choice**: Embed a 5×7 pixel font (ASCII 0x20–0x7E, 95 chars × 5 bytes = 475 bytes) in PROGMEM
- **Rationale**: The same font already exists in Python (`alexa_custom/display_fonts.py`, 483 bytes). Reusing the same glyph data ensures visual consistency between the OLED and matrix. 475 bytes is negligible for the STM32U585 (2 MB flash).
- **Alternatives considered**: Custom-drawn letter bitmaps for each scrolling frame — bloated and inflexible; no font — can't scroll arbitrary text.

### Decision 2: Scroll engine in firmware `loop()`
- **Choice**: A new `scroll_text(text, speed_ms)` RPC sets a text buffer and scroll position. On each tick, `loop()` shifts a 13-column viewport over the rendered font bitmap, calling `draw_frame()`.
- **Rationale**: Keeping scroll timing in the firmware avoids network jitter from Python RPC calls. The existing `_anim_tick_ms` pattern is reused.
- **Alternatives considered**: Python-side frame compositing and sending each frame via RPC — too chatty; host-side pre-rendering — loses responsiveness.

### Decision 3: Wave animation — reuse the same icon ID for listening and speaking
- **Choice**: Map both `listening` and `speaking` states to the same icon ID (`ICON_LISTENING` / ICON_SPEAKING → same value). The animation frames are the same wave pattern. The RGB LED color differentiates the state (green vs red).
- **Rationale**: The user explicitly wants the same wave visualization for both. Avoids duplicating identical frame data in firmware.
- **Alternatives considered**: Separate icon IDs pointing to the same bitmap data — unnecessary indirection.

### Decision 4: Gear animation — 4-frame rotation cycle
- **Choice**: A single gear (5×7 pixels approx) animated over 4 rotation frames. The gear is centered on the matrix.
- **Rationale**: 4 frames at 150ms tick gives a smooth 670ms rotation cycle. Two gears side-by-side on 13 columns would be too cramped (6 cols each, need gap).
- **Alternatives considered**: Two gears — each would be ~4px wide, unrecognizable; single larger gear reads better.

### Decision 5: Startup text — firmware boots with "Coop. Galileo" scroll, overridable via RPC
- **Choice**: The firmware's `setup()` calls `scroll_text("Coop. Galileo", 100)` instead of `set_icon(ICON_IDLE)`. When the Python daemon connects, it can call `scroll_text()` with a new string or `set_icon(ICON_IDLE)` to transition out.
- **Rationale**: The text plays immediately on power-on, before Python is even running. Once the daemon connects and reaches `connected` state, it naturally transitions to the idle smiley.
- **Alternatives considered**: Python sends scroll text after connecting — adds a visible delay between power-on and text appearing.

### Decision 6: Icon ID renumbering
- **Choice**: Keep existing icon IDs for unchanged icons (gated=7, nomatch=4, connected=5, disconnected=6). Add a new `ICON_GEAR = 2` replacing hourglass at the old thinking slot. `ICON_WAVE` replaces both listening and speaking at ID 1 and 3 (both map to same wave animation via firmware logic or by using the same ID). Alternatively, keep `ICON_LISTENING = 1` for wave, and `ICON_SPEAKING = 3` also renders wave.
- **Rationale**: Minimizes unnecessary changes. The firmware switch statement can alias `ICON_SPEAKING` and `ICON_LISTENING` to the same `wave` animation function.

## Risks / Trade-offs

- **Firmware flash size increase**: ~500 bytes for font + ~200 bytes for new bitmaps. Well within STM32U585 limits (2 MB). **Mitigation**: Verify with `avr-size` after compile.
- **Scroll text timing**: If the scroll engine blocks RPC responses, the daemon might timeout on `ping()`. **Mitigation**: The scroll animation runs in `loop()` which already handles RPC dispatch. RPCs are handled between `delay(10)` calls — the existing architecture already prioritizes RPC responsiveness.
- **Text too long for 8 rows**: The font is 7 pixels tall on an 8-row matrix. **Decision**: Use the top 7 rows for text, leave bottom row blank or use as underline. Single-row scrolling is sufficient.
- **Gear not recognizable**: On an 8×13 matrix, a gear might look like a blurry circle. **Mitigation**: Use high-contrast frame transitions (alternating pixel patterns) to make rotation visible. Test visually on hardware.
