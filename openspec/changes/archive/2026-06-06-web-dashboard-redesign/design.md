## Context

The dashboard is a single-page app embedded as `_HTML` in `alexa_custom/web.py`. It uses a flat terminal aesthetic (Courier New, basic CSS bar meters, no transitions), with state updates written as plain `innerHTML` swaps. The WebSocket protocol and Python server logic are stable and not changing.

The redesign targets two concerns simultaneously: a modern glassmorphism visual layer and CSS/JS-driven live personality that makes state transitions visible at a glance.

## Goals / Non-Goals

**Goals:**
- Extract HTML/CSS/JS to `alexa_custom/dashboard.html`; `web.py` loads it once at import
- Glassmorphism panel style, system font stack, CSS custom property palette
- Segmented VU meter bars (20 segments, colour-shift by level)
- CSS keyframe animations triggered by WebSocket events: wake glow, matched flash, nomatch shake, history slide-in
- Streaming partial transcription with blinking cursor
- CSS Grid layout with full-width STT hero card

**Non-Goals:**
- Changes to WebSocket message protocol or Python server logic
- New runtime Python or JS dependencies
- Build tooling (Vite, webpack, etc.)
- Mobile-specific responsive breakpoints (LAN desktop dashboard)

## Decisions

### D1 — Separate file, not inline string

`dashboard.html` lives in `alexa_custom/` alongside `web.py`. `web.py` reads it at module level:

```python
_HTML = (Path(__file__).parent / "dashboard.html").read_text()
```

**Why over alternatives:**
- Inline string (current): no editor support, no syntax highlighting, hard to diff
- Jinja2 template: adds a dependency and template syntax for a static file
- Served from a `static/` directory: requires a separate route, complicates packaging

Single file, loaded once, zero overhead.

### D2 — CSS custom properties for the accent palette

All colours defined as `--var` on `:root`. No Tailwind, no preprocessor.

```css
:root {
  --bg:      #0f0f13;
  --surface: rgba(255,255,255,0.04);
  --border:  rgba(255,255,255,0.08);
  --wake:    #fb923c;
  --match:   #4ade80;
  --nomatch: #f87171;
  --info:    #60a5fa;
  --text:    #e2e8f0;
  --muted:   #64748b;
}
```

Keeps theming changes to one place; browser support is universal.

### D3 — CSS keyframes, no JS animation library

Animations are CSS `@keyframes` attached via `classList.add()`/`remove()` in JS. After the animation duration, JS removes the class so it can fire again.

```js
function flash(el, cls, duration) {
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), duration);
}
```

**Why over alternatives:**
- GSAP/anime.js: unnecessary dependency for a handful of transitions
- Web Animations API: more verbose, same capability
- CSS transitions alone: can't re-trigger on same-state updates

### D4 — Segmented VU meter (20 segments, inline SVG-free)

20 `<span>` elements per channel, each coloured by threshold:
- Segments 1–14: `--match` (green)
- Segments 15–17: `#facc15` (amber)
- Segments 18–20: `--nomatch` (red)

Active segments lit at full opacity; inactive at 10%. JS sets the cutoff index on each `volume_update`.

**Why not a Canvas/SVG meter:** Overkill. 20 spans + CSS is ~10 lines of JS and renders at 60fps without a repaint budget concern.

### D5 — CSS Grid layout

```
┌─────────────────────────────────────┐
│ header (status bar)                 │
├─────────────────────────────────────┤
│ hero STT card (full width)          │
├──────────┬──────────────┬───────────┤
│ wake     │     logs     │  history  │
│ words    │              │           │
├──────────┴──────────────┴───────────┤
│ VU meters + controls                │
└─────────────────────────────────────┘
```

`grid-template-rows: auto auto 1fr auto` on `body`. Three-column middle row uses `grid-template-columns: 240px 1fr 240px`.

**Why swapped history/actions positions:** logs are widest content; flanking them with the narrower panels keeps the eye on the high-frequency stream.

## Risks / Trade-offs

- **`dashboard.html` must ship with the package** — `pyproject.toml` needs `package-data` entry for `*.html` if the project is ever installed from a wheel. Low risk for a service that runs from source.
- **`backdrop-filter` not available in all browsers** — panels degrade to flat `rgba` background without the blur. Acceptable; the layout and colour work regardless.
- **Animation class cleanup** — if `setTimeout` fires while a new event of the same type arrives, the class is removed prematurely. Fix: store the timeout ID per element and cancel before re-adding.

## Open Questions

_(none — all decisions resolved during explore session)_
