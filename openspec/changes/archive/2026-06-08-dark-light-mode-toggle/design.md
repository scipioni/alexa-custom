## Context

`alexa_custom/dashboard.html` is a single self-contained file — all CSS in a `<style>` block, all logic in a `<script>` block, no build step, no external dependencies. Colors are already uniformly defined as CSS custom properties on `:root` (dark values). Two JS strings contain hardcoded hex colors (`#94a3b8`, `#86efac`) that bypass the variable system; one CSS rule has a hardcoded `rgba(0,0,0,0.3)`.

## Goals / Non-Goals

**Goals:**
- Respect OS `prefers-color-scheme` by default
- Allow user to manually override and persist the choice via `localStorage`
- Toggle button lives in the status bar; uses icon to avoid adding text weight
- Light theme uses the existing CSS variable names — no new selectors anywhere else in the file
- All hardcoded colors in the file converted to variables so both themes are consistent

**Non-Goals:**
- No animation/transition on theme switch (adds complexity, can cause flicker on load)
- No per-component theming — one global theme switch only
- No server-side persistence of the preference

## Decisions

### D1: `data-theme` attribute on `<html>` vs. class on `<body>`

Chose `data-theme="light"` on `<html>` (default: absent = dark). The selector `[data-theme="light"]` in CSS overrides `:root` variables. `<html>` is the cleanest target (avoids `<body>` specificity interaction with backdrop-filter rules).

Alternatives considered:
- `class="light"` on `<body>`: same effect but more fragile with JS class manipulation
- Separate stylesheet: overkill for a single-file project

### D2: Default theme logic

```
1. Read localStorage.getItem('theme')
2. If set → apply it
3. Else → apply window.matchMedia('(prefers-color-scheme: light)').matches
4. Listen for system preference changes → update only if no localStorage override
```

This means a user who has never clicked the toggle sees their OS preference. A user who has clicked gets their explicit choice.

### D3: Hardcoded colors → new CSS variables

Two new semantic variables:
- `--transcribing: #94a3b8` (used in `setStt` for the transcribing state text)
- `--reply-trig: #86efac` (used in `renderActions` for `on_reply` trigger lines)

`#status-bar` background extracted to `--bar-bg`:
- Dark: `rgba(0,0,0,0.3)` (current hardcoded value)
- Light: `rgba(255,255,255,0.6)`

### D4: Light palette values

| Variable    | Dark (current)              | Light                        |
|-------------|-----------------------------|------------------------------|
| `--bg`      | `#0f0f13`                   | `#f1f5f9`                    |
| `--surface` | `rgba(255,255,255,0.04)`    | `rgba(0,0,0,0.04)`           |
| `--border`  | `rgba(255,255,255,0.08)`    | `rgba(0,0,0,0.12)`           |
| `--text`    | `#e2e8f0`                   | `#0f172a`                    |
| `--muted`   | `#64748b`                   | `#64748b` (unchanged)        |
| `--bar-bg`  | `rgba(0,0,0,0.3)` (new var) | `rgba(255,255,255,0.6)`      |
| `--transcribing` | `#94a3b8` (new var)   | `#475569`                    |
| `--reply-trig`   | `#86efac` (new var)   | `#16a34a`                    |

Semantic colors (`--wake`, `--match`, `--nomatch`, `--info`, `--llm`, `--amber`, `--llm-dim`, `--llm-border`) remain identical in both themes — they're already high-contrast enough.

### D5: Toggle button

Simple `<button id="btn-theme">` with `aria-label` in the status bar, right of the WS indicator. Content: `☀` in dark mode, `🌙` in light mode (updated by the toggle function). Styled consistently with the existing `panel-hdr button` style.

## Risks / Trade-offs

- **Flash of wrong theme (FOUT)**: If JS runs after render, user may briefly see the wrong theme. Mitigation: the theme-init script is a small inline `<script>` placed immediately after `<html>` (before `<body>`) so it runs before any paint.
- **`prefers-color-scheme` not supported in very old browsers**: Graceful — falls back to dark (the current default) with no error.

## Migration Plan

Single-file edit. No deployment step beyond the normal service restart. Rollback: revert `dashboard.html`.

## Open Questions

None — scope is fully defined.
