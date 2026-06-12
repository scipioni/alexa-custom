## ADDED Requirements

### Requirement: Visual weight reduction
The volume slider SHALL have reduced visual weight compared to the current implementation. The slider MUST remain fully interactive — draggable, providing real-time percentage feedback, and sending the `set_volume` command on release — with no functional changes to any JavaScript event handlers.

#### Scenario: Track height is reduced
- **WHEN** the dashboard renders the volume slider
- **THEN** the track height SHALL be between 4px and 5px, down from the current 12px

#### Scenario: Thumb size is reduced without glow
- **WHEN** the dashboard renders the volume slider
- **THEN** the thumb SHALL be between 14px and 16px, down from the current 24px, and SHALL NOT have any box-shadow glow effect

#### Scenario: Interactive behavior unchanged
- **WHEN** a user drags the slider thumb
- **THEN** the percentage label SHALL update in real time, and on mouse release the `set_volume` WebSocket message SHALL be sent, identical to current behavior

### Requirement: No hover or drag amplification
The slider SHALL NOT scale up or glow on hover or drag. Hover and drag states MUST be visually calm — at most a subtle color/darkness change of the thumb, with no transform scaling and no box-shadow glow.

#### Scenario: Hover does not amplify
- **WHEN** the user hovers over the slider thumb
- **THEN** the thumb SHALL NOT scale up and SHALL NOT produce any box-shadow glow

#### Scenario: Drag does not amplify
- **WHEN** the user drags the slider thumb
- **THEN** the thumb SHALL NOT scale up and SHALL NOT produce any box-shadow glow

### Requirement: Subdued color scheme
The slider track fill and thumb SHALL use a single muted accent color instead of the current bright green/amber/red gradient. The color MUST still indicate the approximate volume level, but with reduced saturation and no aggressive transitions.

#### Scenario: Single muted fill color
- **WHEN** the slider renders at any volume level
- **THEN** the fill and thumb SHALL use a single muted color (e.g., info blue at reduced saturation or a neutral accent), not a bright green-to-red gradient

### Requirement: No thumb border
The slider thumb SHALL NOT have a visible border.

#### Scenario: Border removed
- **WHEN** the slider renders
- **THEN** the thumb SHALL have no border (border: none or border: 0px)
