## ADDED Requirements

### Requirement: Deferred display font loading
The display font resources SHALL NOT be materialized at module import time. They SHALL be loaded only when a display backend that renders glyphs (the SSD1306 OLED backend) is instantiated. On deployments where no OLED backend is constructed (headless, display-disabled, or non-OLED backends such as the LED matrix or mock), importing the display module SHALL NOT allocate the font data.

#### Scenario: Headless import does not load the font
- **WHEN** the display module is imported on a host with no OLED display and no OLED backend is instantiated
- **THEN** the font byte data is not materialized in memory

#### Scenario: OLED backend loads the font on demand
- **WHEN** the SSD1306 OLED backend is instantiated
- **THEN** the font resources are available and glyph rendering produces identical output to before this change

#### Scenario: Rendered glyphs unchanged
- **WHEN** the same text is rendered through the OLED backend before and after this change
- **THEN** the produced pixel/byte output is identical
