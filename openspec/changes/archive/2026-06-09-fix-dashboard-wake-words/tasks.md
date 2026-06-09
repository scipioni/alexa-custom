## 1. Fix dashboard crash

- [x] 1.1 Remove dead `#mic-dev` / `#spk-dev` references from `setAudio()` in `dashboard.html` — replace with no-op or remove the function body

## 2. Split wake-word section into two panels

- [x] 2.1 Replace the single `#actions-section` panel in `dashboard.html` HTML with two panel containers (`#ww-panel-galileo`, `#ww-panel-assistente`) in the center column
- [x] 2.2 Update `renderActions()` JS to generate per-panel content — each panel gets its word's triggers + "globali" subsection with global triggers
- [x] 2.3 Update `updateInteraction()` JS to target both panel containers for wake-word highlight animations (`.ww-card` → selectors inside each panel)
- [x] 2.4 Remove unused CSS classes from the old layout (`.awk-group`, `.vu-row`, `.seg`, `.vu-rms-line`, `.footer-divider`, etc.)

## 3. Verify

- [x] 3.1 Run `task lint` to check for formatting issues
- [x] 3.2 Run `task test` to verify no regressions
