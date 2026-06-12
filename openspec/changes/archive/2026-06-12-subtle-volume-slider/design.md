## Context

The volume slider lives in `alexa_custom/dashboard.html` inside the MONITOR panel (right column, 252px), grouped with VU meters and CPU stats. Currently it uses:

- A 12px height track with `linear-gradient` fill
- A 24px circular thumb with 2px colored border and `box-shadow: 0 0 12px` glow
- Hover: `scale(1.15)` + glow 18px
- Drag: `scale(1.3)` + glow 26px + `.dragging` CSS class
- Color: green (<70%), amber (70-85%), red (>85%) — using `--match`, `--amber`, `--nomatch` CSS vars

The `--vol-color` and `--vol-pct` CSS custom properties control fill/thumb appearance dynamically via JS `_setSliderFill()`.

All interactive logic lives in `initVolumeSlider()`, `playBeepForVolume()`, and `_setSliderFill()` — none of these will be touched.

The CPU stat bars in the same panel already demonstrate the desired visual language: 2px height, no glow, subdued color.

## Goals / Non-Goals

**Goals:**
- Reduce the visual weight of the volume slider so it blends into the dashboard
- Keep all slider functionality identical (drag, real-time percentage, beep, WebSocket command)
- Use only CSS changes — zero HTML or JS modifications

**Non-Goals:**
- Moving the slider to a different position in the layout
- Changing the slider's HTML structure or JavaScript event model
- Changing how volume is read or set on the backend
- Any Python/backend changes

## Decisions

### Decision 1: CSS-only approach
All changes are confined to the `<style>` block of `dashboard.html`. The HTML `<input type="range">` and its `oninput` / `onmouseup` / `onmousedown` handlers remain untouched.

### Decision 2: Track height → 4px
Matching the visual weight of the CPU stat separator bars already in the MONITOR panel. 4px is thin enough to be unobtrusive but thick enough to show the fill level at a glance.

### Decision 3: Thumb → 14px, no border, no shadow
14px is the smallest size that remains comfortably draggable with a mouse. No border eliminates the visual "ring" that draws the eye. No box-shadow eliminates the glow entirely.

### Decision 4: Single muted accent color
Replace the green/amber/red gradient with a single color — `var(--info)` at reduced opacity or a new `--volume-fill` CSS variable. This matches the dashboard's existing accent system and removes the alarm-like color transitions.

Alternatives considered:
- Keeping the color gradient but desaturating it: more complex CSS, still draws attention
- Grayscale fill: too difficult to read volume level at a glance

### Decision 5: No hover/drag transform or glow
Remove the `.dragging` class visual effects entirely. The hover pseudo-class keeps at most an opacity change or a 10% darker thumb fill — enough to signal interactivity without demanding it.

### Decision 6: Keep percentage label
The `#volume-percent` span remains. It is the primary readout for voice-commanded volume changes. Its styling can stay as-is, or be reduced to 10px / muted to match other labels.

## Risks / Trade-offs

- **[Usability]** Smaller thumb may feel less precise for fine-grained drag → Mitigation: the percentage label updates in real-time during drag, providing precise numeric feedback
- **[Consistency]** The new look differs from the VU meters (which use bright match/amber/nomatch colors) → Mitigation: VU meters indicate live audio signal level where color-coding is meaningful; volume level is a static setting, so subdued treatment is appropriate
- **[Regression]** CSS changes could accidentally affect other elements using `--vol-color` or `--vol-pct` vars → Mitigation: these vars are only referenced by the slider element; a grep confirms no other uses

## Open Questions

- What exact color should the muted fill be? Options: `var(--info)` at full saturation, `var(--info)` at 60% opacity, or a new `--volume-fill` var (e.g., `#60a5fa` at 0.6 opacity)
- Should the percentage label (`50%`) also be styled down (smaller, muted), or stay as-is?
