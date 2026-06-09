## Context

The current dashboard uses a fixed-width layout with a hero section at the top and three panels below (Actions, Logs, History/Participants/Room). VU meters are in the footer. This structure doesn't scale well to mobile and doesn't provide a clean "User" view.

## Goals / Non-Goals

**Goals:**
- Implement a three-column responsive layout.
- Move VU meters to the right monitoring panel and orient them vertically.
- Integrate the STT hero card into the center column.
- Implement a User/Developer mode toggle.
- Refactor wake word actions into responsive cards.
- Implement "glow and grow" animations for active elements.
- Add live system load average graph.

**Non-Goals:**
- Changes to the STT or LLM backends.
- Changes to the WebSocket protocol.
- Significant backend logic changes in `web.py`.

## Decisions

### 1. Three-Column CSS Grid
- **Decision**: Use `grid-template-columns: 240px 1fr 240px` for the main layout.
- **Rationale**: Provides a stable structure for History and Controls while allowing the center interaction area to flex.

### 2. Vertical VU Meters
- **Decision**: Re-implement VU meters using vertical `display: flex` with `flex-direction: column-reverse`.
- **Rationale**: Matches the sketch aesthetics and saves horizontal space in the monitoring column.

### 3. User/Dev Mode Toggles
- **Decision**: Use a `.dev-mode` class on the `body` to control visibility. Use `☀` and `< />` icons as toggles.
- **Rationale**: Direct implementation of the sketch UI elements.

### 4. Electric Animations
- **Decision**: Use CSS transitions on `transform` and `filter: drop-shadow()`.
- **Rationale**: Performant way to achieve the "glow and grow" effect without reflows.

### 5. Live System Stats (Grafico)
- **Decision**: Use `os.getloadavg()` in `web.py` to gather load data and send it via a new `system_stats` WebSocket message. On the frontend, use a simple SVG-based sparkline.
- **Rationale**: Minimal overhead and no external JS chart libraries needed.

### 6. Dynamic Room Card
- **Decision**: Manage the Room card state based on existing `room_status` messages. Use CSS transitions for the height and opacity of the participants list.
- **Rationale**: Reuses existing data flows while adding the requested visual dynamism.

## Risks / Trade-offs

- **[Risk]** Layout breaking on very small mobile screens. → **Mitigation**: Use media queries to hide the History panel or Monitoring panel if the width is below a certain threshold (e.g., 600px).
- **[Risk]** `os.getloadavg()` is not available on all platforms (though standard on Linux). → **Mitigation**: Fallback to a placeholder or zero if unavailable.
- **[Trade-off]** Adding more WebSocket messages (system stats) increases network traffic. → **Mitigation**: Keep the update frequency low (e.g., every 5 seconds).
