## Why

The volume slider currently sits on its own row below the VU meters, wasting vertical space and breaking the visual connection between speaker level and volume control. Moving it into the SPK column — as a vertical slider parallel to the VU bar — makes the dashboard tighter and the relationship between level and volume intuitive at a glance.

## What Changes

- SPK column becomes a two-column layout: VU bar (left) + vertical volume slider (right), same height
- The standalone `#volume-control` row below the VU block is removed
- The range input is rotated to vertical orientation
- Percent label moves below the vertical slider, inline with the SPK dB readout
- Slider fill-color gradient adapted for vertical orientation

## Capabilities

### New Capabilities
- *(none — layout change only)*

### Modified Capabilities
- *(none — no requirement or behavior changes)*

## Impact

- `alexa_custom/dashboard.html`: HTML structure, CSS, and JS changes
- No changes to web.py, audio_ops.py, audio_hw.py, or any backend
