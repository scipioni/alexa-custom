## Context

alexa-custom runs on the Arduino UNO Q board which has two processors: a Qualcomm QRB2210 MPU (Linux, runs alexa-custom in Python) and an STM32U585 MCU (Zephyr, controls hardware peripherals). The board includes a built-in 8×13 LED matrix and 4 RGB LEDs — two controlled by the MPU via `/sys/class/leds/`, two by the MCU via RPC through `ArduinoRouterBridge`.

Currently, all user feedback is audio-only (beeps, TTS) plus web dashboard/MQTT — nothing visible on the board itself. This design adds a non-invasive visual feedback layer that reuses the existing event flow without modifying state machines or audio pipelines.

## Goals / Non-Goals

**Goals:**
- Provide glanceable status feedback on the UNO Q's built-in LED matrix and RGB LEDs
- Follow existing abstraction patterns (ABC + factory, like `STTBackend`)
- Zero changes to the existing event flow, state machine, or audio pipeline
- Work on PC without hardware (MockDisplay logger fallback)
- Graceful degradation: Bridge → GPIO → Mock
- Configurable via config.yaml with opt-in default

**Non-Goals:**
- Touchscreen or rich display support
- Replacing the web dashboard or audio cues
- Adding new hardware dependencies (uses only what's already on the board)
- Real-time audio visualization (VU meter on matrix)
- Animation framework (simple bitmap icons + blink only)

## Decisions

### 1. ABC + factory pattern (same as STTBackend/TTSBackend)

**Decision**: Define `DisplayBackend` ABC with three implementations: `BridgeDisplay`, `GpioLedDisplay`, `MockDisplay`. Factory function `get_display_backend()` selects automatically.

**Rationale**: Matches existing codebase patterns exactly. Testable, mockable, extensible. Each backend is isolated.

### 2. Two-event callback wiring (extra_event_cb / extra_stt_event_cb)

**Decision**: Add two optional keyword parameters to `run_web()` and `WebServer`. Inside `WebServer.run()`, chain them to the existing `self.on_event` and `self.on_stt_event`.

**Rationale**: Minimal footprint (~6 lines). 100% backwards compatible (default None = no-op). The display controller doesn't need to know about web.py internals. Alternative considered was a pub-sub event bus, but that's over-engineering for two callback chains.

### 3. Separate thread with queue (not asyncio)

**Decision**: `DisplayController` runs its own `threading.Thread` with a `queue.Queue`. The `on_event`/`on_stt_event` callbacks just push to the queue and return immediately.

**Rationale**: Events come from multiple threads (STT thread, LiveKit thread, asyncio loop). A thread-safe queue is the simplest correct solution. The display backend (`Bridge.call`) may block on I2C/UART — a dedicated thread prevents blocking the caller.

### 4. GPIO via sysfs (not libgpiod or python-periphery)

**Decision**: Write to `/sys/class/leds/{color}:user/brightness` with `open().write()`.

**Rationale**: Zero dependencies. Works on any Linux with the LED class driver. The UNO Q Debian image exposes exactly these paths. `libgpiod` would be cleaner but requires an extra apt package.

### 5. BridgeDisplay uses `from arduino.app_utils import Bridge` (not pip)

**Decision**: Import the preinstalled module. Wrap in try/except with comprehensive fallback.

**Rationale**: The module is part of the board's Debian image. It's not on PyPI and has no pip package. On PC the import fails → clean fallback to MockDisplay.

### 6. Firmware RPC over ArduinoRouterBridge (not raw serial)

**Decision**: The STM32 sketch registers functions via `Bridge.provide()` and the Python side calls them via `Bridge.call()`.

**Rationale**: The Bridge library handles serialization (MsgPack), routing, and connection management. Raw serial would require framing, CRC, and reconnection logic. The Bridge is the documented, supported path.

### 7. One spec-driven change (not incremental GPIO-first)

**Decision**: Implement all three backends (Bridge, GPIO, Mock) in one change plus the firmware sketch.

**Rationale**: The GPIO backend is trivial (~20 lines) and the firmware is a single file. Splitting into two changes would add coordination overhead with no real benefit. The firmware is flashed once and then the Bridge backend works transparently.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Bridge RPC timeout blocks display thread | Low | Medium | Queue has 200 maxsize; render loop has timeout guard; Bridge.call has built-in timeout in the library |
| sysfs LED paths differ on kernel versions | Low | Low | try/except around file open; fallback to Mock on any IOError |
| Firmware flash corrupts existing sketch | Low | Medium | Include `task display:setup` that verifies flash (Bridge.call("ping")) before/after |
| App Lab environment blocks `/sys/class/leds/` writes | Medium | Low | Permission denied → auto-fallback to Mock; document `sudo` fix |
| STT event rate exceeds display refresh (e.g., level events) | Low | Low | DisplayController filters out `"level"` events; only state-change events reach the queue |
| Matrix burn-in from static icon | Very Low | Low | Animation (even on idle, very slow breathing pulse of the idle icon every 30s) |

## Open Questions

- (none — all resolved during exploration)
