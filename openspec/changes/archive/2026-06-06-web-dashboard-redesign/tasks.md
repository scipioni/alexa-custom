## 1. Extract HTML to standalone file

- [x] 1.1 Create `alexa_custom/dashboard.html` by extracting the current `_HTML` string content from `web.py`
- [x] 1.2 Replace `_HTML = """..."""` in `web.py` with `_HTML = (Path(__file__).parent / "dashboard.html").read_text()` and add `from pathlib import Path` import if not present
- [x] 1.3 Verify `alexa-client --web` still serves the dashboard (smoke test: `curl -s http://localhost:8080/ | head -5`)

## 2. CSS foundation — palette, typography, glassmorphism panels

- [x] 2.1 Add CSS custom properties to `:root` in `dashboard.html`: `--bg`, `--surface`, `--border`, `--wake`, `--match`, `--nomatch`, `--info`, `--text`, `--muted`
- [x] 2.2 Replace `background: #1a1a1a` body style with `background: var(--bg)` and switch font to `system-ui, -apple-system, sans-serif`
- [x] 2.3 Apply glassmorphism to all panel containers (`#left`, `#actions-section`, `#log-panel`, `#hist-section`, `#part-section`): `backdrop-filter: blur(12px)`, `background: var(--surface)`, `border: 1px solid var(--border)`, `border-radius: 12px`

## 3. CSS Grid layout

- [x] 3.1 Replace the `#main` flex layout with CSS Grid: `grid-template-columns: 240px 1fr 240px`; move history to the right column and actions to the left
- [x] 3.2 Add `#hero` STT card as a full-width row above the three-column grid (insert element in HTML, wire `setStt()` to update it)
- [x] 3.3 Move VU meters and controls to a sticky footer row below the grid; remove from `#bot` position above `#main`

## 4. Segmented VU meter

- [x] 4.1 Replace `<div class="vw"><div class="vb" id="mic-bar"></div></div>` with 20 `<span class="seg">` elements for each channel (MIC, SPK)
- [x] 4.2 Add CSS: `.seg` base style (dim, coloured by position via `:nth-child` thresholds); `.seg.on` at full opacity
- [x] 4.3 Rewrite `setVU(ch, lvl)` in JS to compute the active segment count and toggle `.on` on each span instead of setting `style.width`

## 5. Live personality animations

- [x] 5.1 Add `@keyframes` blocks: `glow-pulse` (orange box-shadow expand/fade), `flash-green` (background flash), `shake` (translateX left-right), `blink` (cursor opacity), `slide-in` (translateY -12px → 0 with opacity)
- [x] 5.2 Wire `glow-pulse` to wake word card: in `updateInteraction()`, add class `ww-active` (which applies the animation) when state is `wake`; cancel and remove on finish
- [x] 5.3 Wire `flash-green` to `#hero` on `matched` state in `setStt()`; use stored `setTimeout` id to handle re-triggers cleanly
- [x] 5.4 Wire `shake` to `#hero` on `nomatch` state in `setStt()`; same re-trigger guard
- [x] 5.5 Add blinking cursor: on `partial` state, append `<span class="cursor">▋</span>` to the transcription text in `#hero`; remove on any non-partial state
- [x] 5.6 Apply `slide-in` animation class to each new `<div class="he">` inserted in `addHistory()` and `addHistoryWake()`

## 6. Polish and verification

- [x] 6.1 Check all existing JS event handlers (`handle()`, `renderParts()`, `renderActions()`, `addLog()`) still reference correct element IDs after layout restructure
- [ ] 6.2 Verify `backdrop-filter` graceful degradation: disable in devtools and confirm layout/colours remain usable
- [x] 6.3 Run `task lint` and confirm no Python errors (only `web.py` changed on the Python side)
- [ ] 6.4 Smoke-test end-to-end: start `alexa-client --web`, open browser, trigger a wake word, confirm glow animation fires and hero card updates
