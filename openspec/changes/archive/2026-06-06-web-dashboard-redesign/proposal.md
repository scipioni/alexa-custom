## Why

The current dashboard is a functional but visually plain terminal-style readout — no animations, flat bars, and all markup embedded as a string in `web.py`. State transitions (wake word firing, trigger matched, no match) produce no visual feedback beyond a text label change, making it hard to read at a glance.

## What Changes

- `alexa_custom/dashboard.html` extracted as a standalone file; `web.py` loads it at module import via `Path(__file__).parent / "dashboard.html"`.
- Full CSS redesign: glassmorphism panels (`backdrop-filter: blur`, semi-transparent borders, rounded corners), system font stack (`system-ui`/`-apple-system`/`sans-serif`), dark near-black background (`#0f0f13`), CSS custom properties for the accent palette.
- VU meters replaced with segmented equalizer-style bars (20 segments per channel), color-shifting green → amber → red.
- Live personality animations wired to WebSocket state events:
  - Wake word card pulses with an orange glow ring on `stt: wake`.
  - Hero STT card flashes green on `matched`, shakes red on `nomatch`.
  - Partial transcription streams in with a blinking cursor.
  - History rows slide in from the top on insertion.
- Layout promoted to CSS Grid; STT hero card spans full width above the three-column panel row.
- No new runtime dependencies; no CDN; no build step.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `web-interface`: The requirement that HTML/CSS/JS be embedded as a string constant in `web.py` changes — the dashboard is now served from `alexa_custom/dashboard.html`, loaded at startup. Visual and animation requirements are added.

## Impact

- `alexa_custom/web.py` — `_HTML` string constant replaced by a `Path` read; no other logic changes.
- `alexa_custom/dashboard.html` — new file (extracted + redesigned from `_HTML`).
- No changes to WebSocket protocol, Python server logic, config schema, or any other module.
