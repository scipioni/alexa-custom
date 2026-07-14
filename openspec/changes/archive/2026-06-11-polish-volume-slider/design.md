## Context

The volume slider was added in a previous change with functional one-way control (slider → system). Two issues remain:

1. **Low visibility**: The 6px track uses `--bar-bg` (near-black on dark theme), the thumb is 16px, there is no track fill indication. Users reported the slider is hard to see.
2. **No reverse sync**: Volume changes from voice actions (`actions.py`), shell `wpctl`, or other clients are never reflected in the dashboard. `WebServer._output_volume` is set once at construction and never updated.

The dashboard already runs a `_system_stats_loop` every 2 seconds that broadcasts CPU/ram data to all WebSocket clients. This is the ideal carrier for volume sync.

## Goals / Non-Goals

**Goals:**
- Redesign volume slider with thicker track (12px), gradient fill, dynamic color (green→amber→red), larger thumb (24px), and glow feedback
- Add bidirectional sync: slider updates from any volume source, not just web drag
- Update `WebServer._output_volume` on slider change so new WebSocket connections get the correct value
- Guard against feedback loops (external volume update must not re-trigger beep or set_volume)

**Non-Goals:**
- Touch/gesture support beyond standard browser range input
- Mobile-specific layout changes
- Continuous tone during drag (remains on mouseup only)
- Volume presets or quick-select buttons
- Real-time volume visualization (VU meter style)

## Decisions

### 1. Bidirectional sync via system_stats broadcast
**Decision**: Add `output_volume` to the existing `system_stats` WebSocket message broadcast every 2 seconds. The frontend compares the broadcast value against the current slider position and updates the slider if they differ, without sending a new `set_volume` or playing a beep.

**Rationale**:
- Leverages existing infrastructure — no new message types, no callback wiring
- Works for ALL volume change sources: voice actions, shell, other clients, web slider
- < 2s latency is acceptable for volume sync
- Simple frontend guard against feedback loops (compare values, skip if already matching)

**Alternatives Considered**:
- Callback from audio_hw to WebServer: Requires wiring through module boundaries, more invasive
- Dedicated `volume_changed` WebSocket message: More immediate but adds a new message type
- Polling from frontend: Duplicates server-side loop

### 2. Slider visual redesign — CSS gradient fill
**Decision**: Use `background: linear-gradient(to right, ...)` on the range input with a CSS custom property `--vol-pct` updated on every `input` event. No extra DOM elements.

**Rationale**:
- Pure CSS, no extra markup
- Updates smoothly during drag
- Color changes at volume thresholds matching VU meter convention (green < 70%, amber 70-85%, red > 85%)
- Works in both dark and light theme via existing CSS variables (`--match`, `--amber`, `--nomatch`)

**Alternatives Considered**:
- Pseudo-element overlay on track: Unreliable across browsers for range inputs
- Canvas-based custom slider: Overkill, breaks native accessibility
- Third-party slider library: Unnecessary dependency

### 3. Thumb size and glow
**Decision**: Enlarge thumb to 24px with a 2px border matching the fill color and a shadow/glow that intensifies with volume level. Scale to 1.15 on hover, 1.3 on active drag.

**Rationale**:
- More visible and easier to grab, especially on touch/pointer screens
- Glow intensity proportional to volume gives intuitive visual feedback
- Border provides contrast against the filled track

### 4. No change to tone behavior
**Decision**: Tone remains on mouseup only, with frequency scaling by volume level (330/440/523 Hz). No changes from existing behavior.

**Rationale**:
- Users find the tone useful and it's not part of this change's scope
- Keeping it unchanged reduces risk

## Risks / Trade-offs

- **[Risk] 2-second sync latency might feel sluggish**
  - **Mitigation**: The web slider path is still instant (optimistic UI + immediate wpctl). Latency only applies to externally-triggered volume changes, which are inherently less frequent.
- **[Risk] Gradient fill CSS may not render identically across browsers**
  - **Mitigation**: Use standard `linear-gradient` syntax. Degrades gracefully to flat color on very old browsers.
- **[Risk] Thumb enlargement could overlap with adjacent elements in the monitoring panel**
  - **Mitigation**: Increase `#volume-control` padding and min-height to accommodate 24px thumb + glow.
- **[Risk] Volume sync on reconnect**
  - **Mitigation**: `hello` message already includes `output_volume` — the frontend calls `initVolumeSlider()` on connect, so a fresh page load always shows correct volume.
