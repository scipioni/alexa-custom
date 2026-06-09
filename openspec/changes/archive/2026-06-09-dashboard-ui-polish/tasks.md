## 1. Favicon

- [x] 1.1 Convert `docs/logo_alexa.png` to base64 data URI and embed as `<link rel="icon">` in `dashboard.html` `<head>`

## 2. Fixed-scale sparkline with max load line

- [x] 2.1 Change `updateSparkline()` to use `cpu_count` as fixed max Y instead of `Math.max(..._sparkData)`
- [x] 2.2 Add a dashed `<line>` SVG element at y-position corresponding to load=1.0 with `stroke="var(--muted)" stroke-dasharray="3,3"`
- [x] 2.3 Increase area fill opacity gradient below the curve for a wider visual base

## 3. Restart in toggles card

- [x] 3.1 Remove `#restart-card` div and its styling from HTML/CSS
- [x] 3.2 Add a new button inside `#toggles-body` with text `⟳` that calls `sendCtrl('restart')`
- [x] 3.3 Style the restart button uniformly with existing toggle buttons (same size, hover effect)
- [x] 3.4 Add a CSS `@keyframes spin` animation and apply it to the restart button while restarting

## 4. Status dot = WebSocket state

- [x] 4.1 In `wsInd()` function, add logic to set `#cdot.className` to `sdot ok` when WS is open, `sdot warn` when reconnecting, `sdot` when disconnected
- [x] 4.2 Remove `#cdot` class manipulation from `setSt()` — the status dot no longer reflects LiveKit connection
- [x] 4.3 Ensure the WS indicator text (`#ws-ind`) still shows "WS connected" / "WS reconnecting…"

## 5. Call timer donut

- [x] 5.1 Add SVG donut HTML structure in the `room-status-body` area, hidden by default
- [x] 5.2 On `room_status: waiting` with `timeout > 0`, store `startTime = Date.now()` and `totalTimeout = timeout`, show the donut
- [x] 5.3 Implement a `requestAnimationFrame` or `setInterval` loop that calculates `remaining%` and updates `stroke-dashoffset` on the SVG circle
- [x] 5.4 Add a numeric countdown span next to/below the donut showing remaining seconds (e.g. `42s`)
- [x] 5.5 On `room_status: in_call` or `closed`, hide the donut and reset
- [x] 5.6 Add CSS for the donut: stroke color using `var(--info)`, track color `var(--border)`, size ~48px

## 6. Transcript sound waves

- [x] 6.1 Add `::before` and `::after` pseudo-elements on `.hero-icon` with `border-radius: 50%`, `border: 2px solid var(--wake)`, `animation: wave-expand`
- [x] 6.2 Create `@keyframes wave-expand` from `scale(1) opacity(0.6)` to `scale(2.5) opacity(0)`, duration ~1s
- [x] 6.3 Add a CSS class `.wave-active` that enables the wave animations (waves are hidden by default)
- [x] 6.4 In `setStatusListening()`, toggle `.wave-active` class on the hero icon when `listening === true`
- [x] 6.5 Map `volume_update.mic` level to a CSS custom property `--wave-intensity` on the hero element that controls animation speed (higher MIC = faster waves)

## 7. Smooth action transitions

- [x] 7.1 Wrap hero text content in an inner `<span>` container to separate card animations from content transitions
- [x] 7.2 Before `innerHTML` replacement in `setStt()`, add a 150ms fade-out on the inner container
- [x] 7.3 After `innerHTML` replacement, add a 200ms fade-in on the inner container
- [x] 7.4 Increase `highlightTrigger()` flash duration from 3000ms to 4000ms with a scale pulse keyframe
- [x] 7.5 Add a vertical slide transition for the ask-reply flow: matched text slides up and fades as the new wake state slides in

## 8. Animated theme/mode switch

- [x] 8.1 Create `@keyframes icon-morph` that scales an overlay icon from 1→6→1 while changing the icon character mid-animation
- [x] 8.2 In `toggleTheme()`, before applying the new theme: create a fixed-position clone of the button at screen center, start the morph animation, apply the theme at the animation midpoint (40%), clean up the overlay after animation ends
- [x] 8.3 In `toggleMode()`, same technique with `</>` → `👤` icon
- [x] 8.4 Add `transition: background-color 0.5s ease, color 0.5s ease` to `body` and key `:root` custom properties for smooth crossfade between themes

## 9. Verification

- [ ] 9.1 Manual smoke test: load dashboard, confirm all 8 features render correctly
- [ ] 9.2 Manual test: trigger a wake word and verify sound waves animate on the hero dot
- [ ] 9.3 Manual test: trigger an ask action and verify smooth transitions between states
- [ ] 9.4 Manual test: toggle theme and mode, verify icon morph animation plays
- [ ] 9.5 Manual test: call waiting state, verify donut countdown consumes correctly
- [ ] 9.6 Manual test: restart from browser, verify button shows spin animation and reconnects
- [x] 9.7 Run `task lint` to ensure no formatting regressions
- [x] 9.8 Run `task test` to ensure no functional regressions
