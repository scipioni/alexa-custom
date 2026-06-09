## Why

The current web dashboard, while functional, uses a layout where panels are rigidly sized and some key monitoring elements (like VU meters) are pushed into the footer. The STT transcription area is separate from the main interaction context. This refactor aims to move towards a more flexible, three-column responsive design inspired by the provided sketches, allowing for a better user experience on different screen sizes and a clearer distinction between "User" and "Developer" views.

## What Changes

- **Layout Overhaul**: Transition to a permanent three-column layout: History (Left), Main/Interaction (Center), and Controls/Monitoring (Right).
- **Responsive Center Column**: The main interaction area (Transcription + Wake Word boxes) will use Flexbox/CSS Grid to stack and wrap based on screen width.
- **Vertical VU Meters**: Relocate VU meters from the footer to the monitoring column and rotate them vertically.
- **Wake Word & Action Cards**: Refactor into independent cards that "glow and grow" (with yellow electric borders) when activated. Action lines (green) will also feature this activation effect.
- **Dynamic Room Card**: A new interactive component that expands and glows to show participants when activated, reverting to an emoji-only state when idle.
- **Live System Stats (Grafico)**: Add a real-time visualization of system load average (derived from `htop`-like data) in the dashboard.
- **Enhanced Status Indicator**: A dynamic status element that changes color based on the system's current mode (listening vs. off).
- **User/Dev Mode Toggle**: Switch between a clean "User" view and a technical "Developer" view using the icons from the sketch (`☀` and `< />`).

## Capabilities

### New Capabilities
- None. This is primarily a refactoring of the existing interface.

### Modified Capabilities
- `web-interface`: Modify the layout, responsiveness, and mode-switching requirements.

## Impact

- **Frontend**: Significant changes to `alexa_custom/dashboard.html` (HTML, CSS, and JS).
- **Backend**: No significant backend changes required, though `alexa_custom/web.py` assets will be updated.
- **Assets**: New icons or CSS effects for "electric" borders and "User/Dev" mode.
