## Context

The dashboard is a single `dashboard.html` (~1400 lines) embedded in `web.py`. All state arrives via WebSocket JSON messages. The frontend is vanilla HTML/CSS/JS with no framework. Glassmorphism style with CSS custom properties for theming.

The existing animation palette includes: `flash-green`, `shake`, `glow-pulse`, `trig-flash`, `trig-reply-flash`, `llm-think-glow`, `llm-reply-flash`, `slide-in`, `orbit-spin`.

## Goals / Non-Goals

**Goals:**
- Make the dashboard feel alive and responsive
- Each enhancement must be self-contained in the frontend (except the timer tick)
- Preserve the existing glassmorphism aesthetic
- Maintain responsive layout (800px/1100px breakpoints)
- Zero regressions on existing functionality

**Non-Goals:**
- Frontend framework migration (React, Vue, etc.)
- Authentication or TLS changes
- New backend endpoints beyond the single `#tick` event
- Confidence score (deferred to future change)

## Decisions

### D1: SVG inline for donut chart

**Chosen**: SVG `circle` with `stroke-dasharray`/`stroke-dashoffset` driven by JS `requestAnimationFrame`
**Rationale**: No dependencies, animates at 60 fps on the GPU via browser compositing. The donut sits in the `room-status-body` area, replacing the current text-only timeout display.

Architecture:
```
WebSocket tick event (every 1s) → JS calculates remaining %
                                 → SVG circle stroke-dashoffset = circumference * (1 - remaining%)
                                 → numeric span counts down
```

**Backend change**: `web.py` `_system_stats_loop` (every 2s) is repurposed to also emit a `tick` message every 1s with `answer_remaining: N`. Alternatively, a dedicated 1s loop. The `room_status` event already carries `timeout` — the JS side can calculate locally using `Date.now()` at `waiting` event time, avoiding backend changes entirely.

**Chosen**: Client-side calculation. On `room_status: waiting` with `timeout: 60`, store `startTime = Date.now()`, `totalTimeout = 60`. On every `requestAnimationFrame` (or a 1s interval), calculate `elapsed = (Date.now() - startTime) / 1000`, `remaining = max(0, totalTimeout - elapsed)`. Donut stroke and countdown update. No backend tick needed.

### D2: Sound waves via CSS pseudo-elements + box-shadow

**Chosen**: CSS `@keyframes` animation on the hero icon with expanding `box-shadow` rings, amplitude controlled by JS toggling a CSS class that changes animation scale.
**Alternative considered**: Canvas/Web Audio API — overkill for a decorative effect.

Implementation:
```
.hero-icon {
  position: relative;
}
.hero-icon::before, .hero-icon::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid var(--wake);
  animation: wave-expand 1s ease-out infinite;
  opacity: 0;
}
.hero-icon::after { animation-delay: 0.5s; }

@keyframes wave-expand {
  0%   { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(2.5); opacity: 0; }
}
```

Volume reactivity: the `volume_update` MIC level is mapped to a CSS custom property `--wave-intensity` (0–1) that controls `animation-duration` and `opacity` via `calc()`. Higher MIC = faster, more opaque waves.

The waves are active only during `stt: wake`, `stt: partial`, `stt: transcribing` states (when the dot is orange with `◉`).

### D3: Theme/mode switch animation

**Chosen**: A two-phase animation using CSS transitions + a centered overlay:
1. On click, a clone of the button icon appears as a fixed overlay centered on screen
2. The overlay icon grows (scale 1→8) over 400ms while the theme/mode actually switches
3. The overlay fades out, the real button icon updates

Visual sequence for theme toggle:
```
☀ (click) → ☀ grows to center, becomes 🌙 during expansion → 🌙 shrinks back into button
```

CSS implementation:
```
@keyframes icon-morph {
  0%   { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  40%  { transform: translate(-50%, -50%) scale(6); opacity: 1; }
  60%  { transform: translate(-50%, -50%) scale(6); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1); opacity: 0; }
}
```

The page `background-color` and all `--text`, `--surface` etc. transitions are gated by `transition: background-color 0.5s ease, color 0.5s ease` on `body`, and on `:root` custom properties.

### D4: Smooth action transitions

**Chosen**: Replace instant `innerHTML` rewrites in `setStt()` with a two-phase approach:
1. Old content fades out (opacity 0, 150ms)
2. `innerHTML` is replaced
3. New content fades in (opacity 1, 200ms)

Wrap the hero content in an inner container so the hero card itself doesn't lose its border/bg animation. The `anim-match`, `anim-nomatch`, `llm-think-glow` classes remain on the hero outer card.

Trigger phrase flashing (`highlightTrigger`, `trig-hit`) gets a longer duration (800ms vs current 350ms) with a scale pulse.

### D5: Favicon

**Chosen**: Convert `docs/logo_alexa.png` to base64 data URI at build time, embed as `<link rel="icon" href="data:image/png;base64,...">` in the HTML `<head>`. No server route needed.

### D6: Fixed-scale sparkline

**Chosen**: `maxY = cpu_count` instead of `Math.max(..._sparkData)`. A `<line>` SVG element at `y = (cpu_count - 1) / cpu_count * height` with `stroke-dasharray="3,3"`. Area fill extends wider below the curve by using a higher-opacity fill gradient with a larger spread.

### D7: Restart in toggles card

**Chosen**: Remove the separate `#restart-card` div. Add a new button `⟳` inside `#toggles-body` alongside `</>` and `☀`. The button sends `sendCtrl('restart')`. On restarting, it shows a spinning animation (CSS `@keyframes spin`) and disables.

### D8: Status dot = WebSocket

**Chosen**: `wsInd()` now sets `#cdot.className`:
- `ws.readyState === WebSocket.OPEN` → `sdot ok` (green glow)
- reconnecting → `sdot warn` (orange)
- disconnected → `sdot` (dim)
`setSt()` no longer touches `#cdot`. The `#ws-ind` text span still shows "WS connected" / "WS reconnecting…".

## Risks / Trade-offs

- **Sound waves on low-end devices**: Two CSS animations running at 60fps with box-shadow may cause jank on the Snapdragon 801. Mitigation: use `will-change: transform` and hardware-accelerated properties (`opacity`, `transform` only, no `box-shadow` animation fallback).
- **Donut timer drift**: Client-side `Date.now()` calculation may drift if the page is backgrounded (browser throttles timers). Mitigation: the `room_status: waiting` event carries the authoritative `timeout`; a 1s `setInterval` re-syncs. Worst case: the donut pauses when tab is backgrounded and resumes on focus — acceptable.
- **Theme animation complexity**: The overlay icon approach adds ~30 lines of JS. If it feels sluggish, the simpler version is a 300ms `transition: all 0.3s` on the button with no overlay — still an improvement over instant swap.

## Migration Plan

1. Convert `docs/logo_alexa.png` to base64, embed in HTML `<head>`
2. Implement sparkline fixed scale + max line + wider fill
3. Move restart into toggles card
4. Rewire status dot to WS state
5. Implement donut timer (client-side)
6. Implement sound wave rings on hero dot
7. Implement smooth action transitions in `setStt()`
8. Implement theme/mode switch animation
9. Wire up all animations and test in browser

## Open Questions

- Sound wave color: should waves match the wake-word orange, or the MIC VU green? Orange for wake state, green for partial/transcribing? (Deferred to implementation — default to `--wake` orange.)
- Donut color: should it be green→yellow→red as time decreases (like a countdown) or a single color? (Deferred — implement with `--info` blue for v1.)
