## ADDED Requirements

### Requirement: Scroll arbitrary text on LED matrix
The firmware SHALL support displaying a scrolling text string on the 8×13 LED matrix via RPC, rendering each character using a built-in 5×7 pixel bitmap font.

#### Scenario: Scroll text left to right
- **WHEN** Bridge.call("scroll_text", "Hello", 100) is invoked
- **THEN** the firmware SHALL render "Hello" left-to-right: start with characters entering from the right edge, scroll across, and exit at the left edge
- **AND** each column shift SHALL occur every 100 milliseconds

#### Scenario: Scroll speed parameter
- **WHEN** Bridge.call("scroll_text", "Test", 200) is invoked
- **THEN** the scroll speed SHALL be slower than with speed_ms=50

#### Scenario: Empty text clears scroll
- **WHEN** Bridge.call("scroll_text", "") is invoked
- **THEN** the LED matrix SHALL clear immediately and stop any active scrolling

#### Scenario: RPC returns to normal icons after scroll
- **WHEN** Bridge.call("set_icon", icon_id) is invoked while text is scrolling
- **THEN** the scrolling SHALL stop immediately and the icon SHALL be displayed

### Requirement: Firmware font
The firmware SHALL embed a 5×7 pixel bitmap font covering ASCII 0x20–0x7E in PROGMEM for scroll text rendering.

#### Scenario: Printable ASCII characters render
- **WHEN** scroll_text is called with any string containing printable ASCII characters
- **THEN** each character SHALL be rendered using the 5×7 glyph data
- **AND** characters SHALL be separated by one blank column

#### Scenario: Unsupported characters skipped
- **WHEN** scroll_text is called with characters outside the printable ASCII range
- **THEN** those characters SHALL be rendered as a blank column (skipped)
