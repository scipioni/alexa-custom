## Why

The volume slider on the live dashboard (dashboard.html) is visually invasive — a 24px glowing thumb, 12px thick track, bright green/amber/red color changes, and aggressive hover/drag animations (scale 1.3× + 26px box-shadow glow). It demands attention when it should be a calm background indicator that can be interacted with on demand. The slider remains fully functional via drag and voice commands.

## What Changes

- Reduce slider track height from 12px to 4–5px
- Reduce thumb size from 24px to 14–16px, remove all box-shadow glow
- Remove hover scale (1.15×) and glow (18px) effects
- Remove drag scale (1.3×) and glow (26px) effects
- Replace bright green/amber/red fill colors with a single muted accent (e.g., info blue at reduced opacity)
- Remove thumb border (2px solid color)
- Keep all JS event handlers, WebSocket messaging, and volume percentage label identical — functional zero-change

## Capabilities

### New Capabilities
- `volume-slider-visual`: Visual presentation of the volume slider — track dimensions, thumb size/glow, color scheme, hover/drag feedback, and overall visual weight on the dashboard

### Modified Capabilities

None — this is a visual-only refinement of an existing UI element. No spec-level behavior changes.

## Impact

- Single file: `alexa_custom/dashboard.html` — CSS section only
- No HTML structure changes
- No JavaScript changes
- No Python/backend changes
- No test changes needed
