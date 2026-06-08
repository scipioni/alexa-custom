## Why

The web dashboard is locked to a dark theme with no user control, which creates accessibility and comfort issues for users in bright environments or those who prefer light-mode UIs. Adding a system-aware toggle respects OS preference by default and lets users override it persistently.

## What Changes

- Add a `[data-theme="light"]` CSS block overriding structural variables (`--bg`, `--surface`, `--border`, `--text`) while keeping semantic colors unchanged
- Add a `☀`/`🌙` toggle button to the status bar (right side)
- On load, apply theme from `localStorage` if set, otherwise fall back to `prefers-color-scheme`
- Persist manual choice to `localStorage`; clearing it reverts to OS preference
- Fix two hardcoded hex color values in JS-generated HTML (`#94a3b8`, `#86efac`) by replacing with CSS variables
- Fix one hardcoded `rgba(0,0,0,0.3)` in `#status-bar` CSS by converting to a variable

## Capabilities

### New Capabilities

- `theme-toggle`: User-facing dark/light mode toggle on the web dashboard, with system-preference awareness and localStorage persistence

### Modified Capabilities

- `web-interface`: The dashboard UI gains a theme control; no requirement changes, only new capability added

## Impact

- `alexa_custom/dashboard.html` only — single self-contained file, no new files, no Python changes, no dependencies
