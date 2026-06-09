## Why

The web dashboard works but feels static. The sparkline has no reference line, the restart button is isolated, the status dot shows connection instead of WebSocket state, and the call timer is plain text. Most importantly, the dashboard lacks personality — animations for the transcript dot, smooth transitions between action states, and animated theme/mode switches would make it feel alive.

## What Changes

Eight UI enhancements to `dashboard.html` (frontend only except for the call timer donut which needs a WebSocket tick):

1. **Favicon** — serve `docs/logo_alexa.png` as `favicon.ico`
2. **Fixed-scale sparkline** — CPU graph uses `cpu_count` as max Y, shows a subtle max-load dashed line, wider area fill
3. **Restart in toggles card** — move restart button into the existing toggles row as a refresh icon (⟳)
4. **Status dot = WebSocket** — the green dot reflects WS connection state, not LiveKit connection
5. **Call timer donut** — the 60-second answer timeout renders as an SVG donut countdown + numeric seconds, consuming as time passes
6. **Transcript sound waves** — the hero dot animates concentric wave rings whose amplitude follows the MIC volume level during `partial`/`wake` states
7. **Smooth action transitions** — morphing animations between STT states (`matched` → `wake` for ask, `nomatch` fade, etc.) with CSS transitions instead of hard cuts
8. **Animated theme/mode switch** — clicking the theme or mode button triggers a centered icon morph animation while the page theme transitions

## Capabilities

### Modified Capabilities

- `web-interface`: Dashboard HTML/CSS/JS overhaul — glassmorphism skin preserved, eight interaction and visual enhancements added

## Impact

- **`alexa_custom/dashboard.html`**: major CSS + JS changes, SVG additions, new animations
- **`alexa_custom/web.py`**: minor — add `#tick` event for donut countdown (no structural changes)
- **`docs/logo_alexa.png`**: used as favicon source
- No changes to STT, audio, LiveKit, or config subsystems
