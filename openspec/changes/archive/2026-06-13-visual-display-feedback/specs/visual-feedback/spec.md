## ADDED Requirements

### Requirement: Visual state indicator
The system SHALL provide real-time visual feedback on the Arduino UNO Q's built-in display hardware (LED matrix 8×13 and RGB LEDs) indicating the assistant's current operational state.

#### Scenario: Idle state shows standby indicator
- **WHEN** the assistant is idle (no wake word detected, no active call)
- **THEN** the LED matrix SHALL display the idle icon (◎) and all RGB LEDs SHALL show blue

#### Scenario: Listening state shows mic indicator
- **WHEN** the wake word is detected and the assistant is listening for a command
- **THEN** the LED matrix SHALL display the listening icon (🎤 shape) and all RGB LEDs SHALL show green

#### Scenario: Transcribing shows processing
- **WHEN** the assistant is transcribing speech
- **THEN** the LED matrix SHALL display the transcribing icon and all RGB LEDs SHALL show green with a slow blink (500ms)

#### Scenario: LLM thinking shows thinking indicator
- **WHEN** the assistant is waiting for an LLM response
- **THEN** the LED matrix SHALL show the thinking animation (rotating bar: │ ╱ ─ ╲) and all RGB LEDs SHALL show yellow

#### Scenario: Speaking shows speaking indicator
- **WHEN** the assistant is speaking (TTS playback active)
- **THEN** the LED matrix SHALL display the speaking icon (sound waves) and all RGB LEDs SHALL show red

#### Scenario: In-call gated shows call indicator
- **WHEN** a LiveKit call is active and STT is gated
- **THEN** the LED matrix SHALL display the call icon (☎) and all RGB LEDs SHALL show purple

#### Scenario: No match shows error briefly
- **WHEN** the assistant fails to match a command to any trigger
- **THEN** all RGB LEDs SHALL flash red three times, then return to idle state

### Requirement: Graceful fallback on PC / no hardware
The system SHALL work on any platform without physical display hardware, using a mock backend that logs display actions.

#### Scenario: Mock backend logs output
- **WHEN** running on a PC without `/sys/class/leds/` or Arduino Bridge
- **THEN** the display module SHALL use MockDisplay which writes state changes to logger.info with ASCII art representation

#### Scenario: Auto-fallback on GPIO failure
- **WHEN** the GPIO sysfs backend fails to write (e.g., permission denied)
- **THEN** the system SHALL fall back to MockDisplay without crashing

#### Scenario: Auto-fallback on Bridge failure
- **WHEN** the Bridge RPC call fails (e.g., firmware not flashed, timeout)
- **THEN** the system SHALL fall back to GpioLedDisplay (MPU LEDs only) if available, otherwise MockDisplay

### Requirement: Configurable enable
The display feature SHALL be configurable via config.yaml and disabled by default when the section is absent.

#### Scenario: Display section present and enabled
- **WHEN** config.yaml contains a `display:` section with `enabled: true`
- **THEN** the DisplayController SHALL be created and wired to state events

#### Scenario: Display section absent
- **WHEN** config.yaml has no `display:` section
- **THEN** no DisplayController SHALL be created and no display backend SHALL be initialized

#### Scenario: Display section present but disabled
- **WHEN** config.yaml contains `display:` with `enabled: false`
- **THEN** no DisplayController SHALL be created

### Requirement: Backend selection
The display backend SHALL be selected automatically with optional override in config.

#### Scenario: Auto backend selects Bridge first
- **WHEN** `display.backend` is set to `"auto"` and `arduino.app_utils.Bridge` is importable and responds to ping
- **THEN** BridgeDisplay SHALL be used

#### Scenario: Auto backend falls back to GPIO
- **WHEN** Bridge is unavailable but `/sys/class/leds/` is writable
- **THEN** GpioLedDisplay SHALL be used

#### Scenario: Explicit backend override
- **WHEN** `display.backend` is set to `"gpio"` or `"bridge"` or `"mock"`
- **THEN** the system SHALL use only that backend and fail gracefully if unavailable

### Requirement: Thread-safe event handling
The DisplayController SHALL receive events from any thread without blocking the caller.

#### Scenario: Event received from STT thread
- **WHEN** an STT event (e.g., "wake", "listening") is emitted from the STT thread
- **THEN** the event SHALL be pushed to the DisplayController's internal thread-safe queue and the caller SHALL return immediately

#### Scenario: Event received from LiveKit thread
- **WHEN** a LiveKit event (e.g., "connected", "disconnected") is emitted from the LiveKit worker thread
- **THEN** the event SHALL be pushed to the DisplayController's internal thread-safe queue and the caller SHALL return immediately

### Requirement: Firmware RPC contract
The STM32U585 firmware SHALL expose specific RPC functions via ArduinoRouterBridge for the MPU to call.

#### Scenario: Bridge ping
- **WHEN** Bridge.call("ping") is invoked from Python
- **THEN** the firmware SHALL return True

#### Scenario: Set matrix icon
- **WHEN** Bridge.call("set_matrix_icon", icon_id) is invoked with a valid icon_id (0-7)
- **THEN** the firmware SHALL display the corresponding bitmap on the 8×13 LED matrix

#### Scenario: Clear display
- **WHEN** Bridge.call("clear") is invoked
- **THEN** the firmware SHALL turn off all LEDs on the matrix and set both MCU RGB LEDs to off

#### Scenario: Set both MCU LEDs
- **WHEN** Bridge.call("set_leds", r0, g0, b0, r1, g1, b1) is invoked with 0-255 values
- **THEN** the firmware SHALL set LED 0 and LED 1 to the specified RGB colors
