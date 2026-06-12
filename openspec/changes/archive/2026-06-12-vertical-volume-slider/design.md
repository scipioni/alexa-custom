## Context

The web dashboard has a VU meter section at the bottom with two columns (MIC, SPK), each showing a 20-segment vertical bar with a dB readout below. Below that is a separate `#volume-control` row with a horizontal range slider and percentage label. The volume slider is visually disconnected from the SPK VU bar it controls.

## Goals / Non-Goals

**Goals:**
- Move the volume slider into the SPK column as a vertical slider
- Match the VU bar's 160px height so the two elements align visually
- Remove the standalone `#volume-control` row
- Preserve all existing behavior (beep on release, gradient fill, external sync)

**Non-Goals:**
- No changes to backend (web.py, audio_hw.py, audio_ops.py)
- No changes to WebSocket messages
- No changes to the MIC column

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Vertical slider technique | `writing-mode: vertical-lr; direction: rtl;` on existing `<input type="range">` | Standard cross-browser approach. No JS audio-context canvas needed. Keeps the native range input semantics. |
| Fill gradient | Replace CSS `linear-gradient(to right, ...)` with a vertical gradient using `--vol-pct` mapped to `top` | The current `--vol-pct` / `--vol-color` custom properties can be reused; just change gradient direction to `to bottom` and apply from top. Or simpler: use `accent-color` approach since the vertical slider won't easily support a custom track fill gradient without more complex styling. |
| SPK column layout | Flex row inside the existing `.vu-row-v` | Keeps the existing CSS structure. `.vu-row-v` becomes a container holding two flex children: the VU bar and the vertical slider. |
| Width of slider column | ~30px (narrower than VU bar's 40px) | Vertical range slider doesn't need the full width; too wide would look unbalanced against the 40px VU bar. |
| Percent label | Below the vertical slider, same column | Aligns vertically below the slider track, keeping the label close to the control. |
| SPK dB readout | Split: dB below VU bar, percent below slider | Current spec says dB readout is for level, percent is for volume — they belong with their respective controls. |

## Risks / Trade-offs

- **Custom fill on vertical slider** → The current `linear-gradient(to right, ...)` approach won't translate cleanly to vertical orientation. The simpler approach is to drop the custom fill and use `accent-color` + CSS variable for the thumb. Risk is visual regression — but the thumb color and glow already provide strong volume feedback.
- **Writing-mode vertical slider** → On some mobile/touch environments, `writing-mode: vertical-lr` can behave differently. This board is headless (no touch), so acceptable.
- **Slider dragging UX** → The existing `oninput`/`onmouseup` handlers work fine with the vertical orientation; no JS changes needed.
