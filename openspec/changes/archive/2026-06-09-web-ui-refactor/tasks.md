## 1. Layout and CSS Refactor

- [x] 1.1 Update CSS custom properties for the new "electric" and "pill" styles.
- [x] 1.2 Refactor `#main` container to use the three-column grid.
- [x] 1.3 Move the History panel to the left column and style it.
- [x] 1.4 Move the STT hero card into the center column.
- [x] 1.5 Implement the Monitoring panel in the right column.
- [x] 1.6 Add media queries for basic responsiveness (collapsing panels on narrow screens).
- [x] 1.7 Add CSS for "glow and grow" animations (yellow for cards, green for action lines).

## 2. Component Refactoring

- [x] 2.1 Re-implement VU meters as vertical bars in the monitoring panel.
- [x] 2.2 Refactor Wake Word boxes into independent cards using Flexbox.
- [x] 2.3 Style the Restart button as a red-bordered pill.
- [x] 2.4 Update the Status Bar to include the Mode toggle (☀ and < />).
- [x] 2.5 Implement the "Grafico" section with an SVG sparkline.
- [x] 2.6 Refactor the "Room" component to be dynamic (expands and glows when active).

## 3. Backend and JavaScript Logic Updates

- [x] 3.1 Implement a background loop in `web.py` to broadcast `system_stats` (load average).
- [x] 3.2 Implement `toggleMode()` and `applyMode()` for User/Dev mode switching.
- [x] 3.3 Update `renderActions()` to dynamically create the new Wake Word cards.
- [x] 3.4 Update `setVU()` to handle the vertical segment orientation.
- [x] 3.5 Ensure `stt` event handlers correctly trigger the "glow and grow" animations.
- [x] 3.6 Update the "Status" text to change color based on the system state.

## 4. Verification

- [ ] 4.1 Verify responsiveness of the center column.
- [ ] 4.2 Verify User/Dev mode persistence.
- [ ] 4.3 Verify VU meter visual correctness.
- [ ] 4.4 Verify "electric" border animations for wake words.
- [ ] 4.5 Verify load average graph updates live.
