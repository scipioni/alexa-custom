## Why

The Arduino UNO Q board already has built-in visual output hardware (LED matrix 8×13, 4 RGB LEDs) that is completely unused by alexa-custom. Currently the assistant provides feedback only via audio (beeps/TTS), logs, web dashboard, and MQTT — but none of these give the operator an immediate, glanceable status at the board itself. Adding visual feedback makes the system more maintainable and user-friendly during headless operation.

## What Changes

- New Python module `alexa_custom/display.py` with a `DisplayBackend` ABC and three implementations: `GpioLedDisplay` (LEDs via `/sys/class/leds/`), `BridgeDisplay` (matrix + MCU LEDs via RPC), and `MockDisplay` (logger/ASCII art fallback for PC).
- New `DisplayConfig` dataclass and parser in `config.py` — section is optional, feature disabled when absent.
- New `DisplayController` class that receives state events via a thread-safe queue and drives the display backend.
- Minimal wiring in `web.py`: two optional keyword parameters (`extra_event_cb`, `extra_stt_event_cb`) — 100% backwards compatible.
- Wiring in `client.py` (`main()`) to create and connect `DisplayController`.
- New firmware sketch `setup/display_firmware/display_firmware.ino` for the STM32U585 that exposes RPC functions for the LED matrix and MCU-controlled RGB LEDs via `ArduinoRouterBridge`.
- Auto-selection logic: Bridge → GPIO → Mock, with configurable override.
- Dependency: `Pillow` (needed by `luma.oled` not used — only for future-proofing; no new runtime deps in this change).

## Capabilities

### New Capabilities
- `visual-feedback`: Real-time state indicator on the Arduino UNO Q's built-in LED matrix (8×13) and RGB LEDs (×4, two MPU-controlled via sysfs, two MCU-controlled via Bridge RPC). States map to distinct colors and matrix icons.

### Modified Capabilities
- (none)

## Impact

- **New file**: `alexa_custom/display.py` (~350 lines)
- **New file**: `setup/display_firmware/display_firmware.ino` (~150 lines)
- **Modified**: `alexa_custom/config.py` (+20 lines for `DisplayConfig` dataclass + parser)
- **Modified**: `alexa_custom/web.py` (+6 lines for extra callback parameters + chaining)
- **Modified**: `alexa_custom/client.py` (+15 lines in `main()` for wiring)
- **No impact** on existing state machine, audio pipeline, or event flow.
- **Zero new runtime dependencies** for the base install (`MockDisplay` is built-in). The GPIO backend uses standard sysfs (`/sys/class/leds/`). The Bridge backend imports `arduino.app_utils` which is preinstalled on the UNO Q image.
