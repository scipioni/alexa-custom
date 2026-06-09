## Why

The web dashboard (dev mode) crashes silently on connect because `setAudio()` references two DOM elements (`#mic-dev`, `#spk-dev`) that were removed in a layout restructure. This blocks the entire `hello` message handler — `renderActions()`, `setStt()`, `setRoomStatus()` are never called. The wake-word section should also display each wake word in its own panel with its triggers, rather than a single flat list.

## What Changes

- **Fix dashboard crash**: Remove or guard the dead `setAudio()` references to `#mic-dev`/`#spk-dev` so the `hello` handler completes
- **Split wake-word UI into two panels**: One panel per wake word ("galileo", "assistente"), each showing its own triggers + a "globali" subsection with shared global triggers (replicated in both panels)
- **Clean up unused CSS/JS**: Remove leftovers from the old footer layout (horizontal VU meter classes, RMS needle logic, unused IDs)

## Capabilities

### New Capabilities
- `wake-word-panels`: Display each configured wake word in a separate dashboard panel, with per-word triggers and global fallbacks listed per-panel

### Modified Capabilities
*(none — no spec-level behavior changes)*

## Impact

- `alexa_custom/dashboard.html`: JS fix + HTML/CSS restructuring for two-panel layout
