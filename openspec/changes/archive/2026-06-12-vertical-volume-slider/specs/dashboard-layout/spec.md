## ADDED Requirements

### Requirement: Volume slider positioned next to SPK VU meter

The volume slider SHALL be displayed as a vertical slider positioned to the right of the SPK VU meter, at the same height (160px).

#### Scenario: Vertical slider renders in SPK column
- **WHEN** the dashboard loads
- **THEN** a vertical volume slider is displayed to the right of the SPK VU bar
- **AND** the slider height matches the VU bar height (160px)
- **AND** the standalone `#volume-control` row below the VU meters is absent

#### Scenario: Slider orientation is vertical
- **WHEN** user inspects the volume slider
- **THEN** the slider track runs vertically from bottom (0%) to top (100%)
- **AND** moving the thumb upward increases volume

#### Scenario: Percent label shows below vertical slider
- **WHEN** the dashboard loads
- **THEN** a percentage label is displayed below the vertical slider
- **AND** it updates in real-time as the slider is dragged

### Requirement: All existing volume behavior preserved

All existing volume slider behaviors SHALL be preserved despite the layout change.

#### Scenario: Beep plays on release
- **WHEN** user releases the vertical slider
- **THEN** a test tone plays at the appropriate frequency for the volume level

#### Scenario: External volume sync still works
- **WHEN** volume changes from a voice command or other client
- **THEN** the vertical slider position updates to reflect the new volume

#### Scenario: Gradient fill removed or adapted for vertical
- **WHEN** slider is at any position
- **THEN** the track MAY omit the custom gradient fill (simpler `accent-color` approach is acceptable)
- **AND** the thumb SHALL retain its color and glow based on volume level
