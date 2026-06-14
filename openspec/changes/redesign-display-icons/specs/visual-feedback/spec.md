## MODIFIED Requirements

### Requirement: Visual state indicator
The system SHALL provide real-time visual feedback on the Arduino UNO Q's built-in display hardware (LED matrix 8×13 and RGB LEDs) indicating the assistant's current operational state.

#### Scenario: Idle state shows smiley face
- **WHEN** the assistant is idle (no wake word detected, no active call)
- **THEN** the LED matrix SHALL display a smiley face bitmap and all RGB LEDs SHALL show blue

#### Scenario: Listening state shows sound wave
- **WHEN** the wake word is detected and the assistant is listening for a command
- **THEN** the LED matrix SHALL display an animated sound wave / VU-meter visualization and all RGB LEDs SHALL show green

#### Scenario: Transcribing shows processing
- **WHEN** the assistant is transcribing speech
- **THEN** the LED matrix SHALL display the animated sound wave visualization and all RGB LEDs SHALL show green with a slow blink (500ms)

#### Scenario: LLM thinking shows gear animation
- **WHEN** the assistant is waiting for an LLM response
- **THEN** the LED matrix SHALL show an animated rotating gear and all RGB LEDs SHALL show yellow

#### Scenario: Speaking shows sound wave
- **WHEN** the assistant is speaking (TTS playback active)
- **THEN** the LED matrix SHALL display the animated sound wave visualization (same as listening) and all RGB LEDs SHALL show red

#### Scenario: In-call gated shows call indicator
- **WHEN** a LiveKit call is active and STT is gated
- **THEN** the LED matrix SHALL display the call icon (☎) and all RGB LEDs SHALL show purple

#### Scenario: No match shows error briefly
- **WHEN** the assistant fails to match a command to any trigger
- **THEN** all RGB LEDs SHALL flash red three times, then return to idle state

### Requirement: Firmware RPC contract
The STM32U585 firmware SHALL expose specific RPC functions via ArduinoRouterBridge for the MPU to call.

#### Scenario: Set matrix icon
- **WHEN** Bridge.call("set_icon", icon_id) is invoked with a valid icon_id (0-8)
- **THEN** the firmware SHALL display the corresponding bitmap on the 8×13 LED matrix

#### Scenario: Scroll text on matrix
- **WHEN** Bridge.call("scroll_text", text, speed_ms) is invoked with a non-empty text string
- **THEN** the firmware SHALL scroll the text horizontally across the LED matrix at the specified speed (ms per column shift)

#### Scenario: Clear display
- **WHEN** Bridge.call("clear") is invoked
- **THEN** the firmware SHALL turn off all LEDs on the matrix and set both MCU RGB LEDs to off

#### Scenario: Set both MCU LEDs
- **WHEN** Bridge.call("set_leds", r0, g0, b0, r1, g1, b1) is invoked with 0-255 values
- **THEN** the firmware SHALL set LED 0 and LED 1 to the specified RGB colors

## ADDED Requirements

### Requirement: Startup scrolling text
The system SHALL display a scrolling text message on the LED matrix at startup before transitioning to the idle state.

#### Scenario: Firmware boot shows scrolling text
- **WHEN** the STM32 firmware starts (power-on or reset)
- **THEN** the LED matrix SHALL scroll "Coop. Galileo" horizontally from right to left

#### Scenario: Python daemon connects overrides startup text
- **WHEN** the Python daemon establishes a Bridge connection and reaches the connected state
- **THEN** the daemon SHALL call set_icon(ICON_IDLE) to transition to the idle smiley face
