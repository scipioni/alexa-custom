## Context

The web dashboard (`dashboard.html`) uses a single `#actions-section` panel to display all wake words and their triggers in one flat list. The HTML was recently restructured to a 3-column layout (history | center | monitoring) but the wake-word rendering code was not updated accordingly. A crash in `setAudio()` blocks the entire `hello` handler, leaving the dashboard stuck at "Loading…".

Two wake words are configured: "galileo" (with per-word trigger "chiama stefano") and "assistente" (no per-word triggers). Both share global triggers from `system.yaml` and `user.yaml`.

## Goals / Non-Goals

**Goals:**
- Fix the silent crash on WS connect so the dashboard renders fully
- Display each wake word in its own visually separate panel
- Replicate global fallback triggers inside each wake-word panel with a "globali" label
- Remove dead code from the old footer-based layout

**Non-Goals:**
- No changes to the server-side Python code (`web.py`, `config.py`)
- No changes to the data model or config structure
- No changes to the other dashboard sections (history, monitoring, room status)

## Decisions

1. **Fix `setAudio()` by removing the body instead of guarding** — The function was only used to show device labels in the old footer. The new monitoring panel doesn't show per-device labels. Simply removing the body (or keeping it as a no-op) is cleaner than guarding with null checks.

2. **Two panels in HTML, not dynamic JS generation** — Create two hardcoded panel containers in the HTML (`#ww-panel-galileo`, `#ww-panel-assistente`) and populate them dynamically from the WebSocket data. This gives CSS control over layout, spacing, and responsive behavior.

3. **Global triggers replicated per-panel with `── globali ──` divider** — The `renderActions()` function receives the full config; it will generate two separate panel contents, injecting a "globali" subsection header between per-word triggers and global triggers.

4. **Remove dead CSS classes** — `.awk-group`, `.awk`, `.aglobal-hdr`, `.vu-row`, `.seg`, `.vu-rms-line`, `.vu-dev`, `.footer-divider` are no longer used. Keep only what renders the new panels.

## Risks / Trade-offs

- [Low] Global triggers are replicated in both panels — if the list grows long, panels could become tall. Mitigation: panels scroll independently via `overflow-y: auto`.
- [Low] The `#actions-section` panel is replaced by two separate panels; the panel header "WAKE WORDS" is no longer a single heading. Mitigation: each panel gets its own header with the wake word name.
