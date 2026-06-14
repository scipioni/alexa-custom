## Why

The current LED matrix icons are utilitarian and don't reflect the project's identity. A cohesive, expressive set of animations — smiley idle, scrolling brand name at boot, wave visualization during audio, rotating gears during thinking — will make the device feel polished and alive.

## What Changes

- **Idle state**: Replace the eye bitmap with a smiley face on the 8×13 LED matrix
- **Boot/startup**: Add a scrolling text animation showing "Coop. Galileo" when the firmware starts and when the Python daemon connects (replaces `ICON_STARTING` checkmark)
- **Listening**: Replace the scanning bar animation with a sound-wave / VU-meter-style animation
- **Thinking**: Replace the static hourglass with an animated gear(s) rotation
- **Speaking**: Use the same wave animation as listening (unified audio visualization)
- **RPC contract**: Add a `scroll_text(text)` RPC to the firmware for scrolling text display
- **Firmware**: Add a 5×7 pixel font to the STM32 firmware for text rendering

## Capabilities

### New Capabilities
- `scrolling-text-display`: Scrolling text animation on the 8×13 LED matrix, with configurable text string and scroll speed. Covers the firmware font engine, scroll buffer, and RPC interface.

### Modified Capabilities
- `visual-feedback`: Icon bitmaps and animations change for idle (→ smiley), listening (→ sound wave), thinking (→ rotating gear(s)), and speaking (→ same wave). New idle scenario replaces ◎ with smiley. Listening and speaking scenarios now share the wave animation. Thinking replaces hourglass with gear animation.

## Impact

- **Firmware** (`setup/display_firmware/display_firmware.ino`): New bitmap arrays, new `scroll_text` RPC, font data table, scroll engine in `loop()`, new/modified animation frames for wave and gear
- **Python** (`alexa_custom/display.py`): `STATE_ICON_IDS` mapping may change if icon IDs are reordered. `ICON_STARTING` behavior changes from static checkmark to scrolling text. New `scroll_text(text)` call on `BridgeDisplay`.
- **Specs** (`openspec/specs/visual-feedback/spec.md`): Scenarios for idle, listening, thinking, speaking states updated with new icon descriptions
- **Build**: Firmware binary size increases due to font data
