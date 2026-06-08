## ADDED Requirements

### Requirement: System-preference-aware default theme
The dashboard SHALL read the OS color scheme preference on load using `window.matchMedia('(prefers-color-scheme: light)')`. If no user override is stored, it SHALL apply the matched theme. Changes to the OS preference during an active session SHALL be reflected immediately, unless the user has a stored override.

#### Scenario: Dark OS preference, no override
- **WHEN** the user's OS is set to dark mode and no `localStorage` key is present
- **THEN** the dashboard loads in dark theme

#### Scenario: Light OS preference, no override
- **WHEN** the user's OS is set to light mode and no `localStorage` key is present
- **THEN** the dashboard loads in light theme

#### Scenario: OS preference changes during session
- **WHEN** the user switches OS theme while the dashboard is open and has no stored override
- **THEN** the dashboard theme updates to match the new OS preference

### Requirement: Persistent manual theme override
The dashboard SHALL persist the user's explicit theme choice to `localStorage` under the key `theme` with value `"dark"` or `"light"`. The stored value SHALL take precedence over the OS preference on all subsequent loads.

#### Scenario: User overrides theme
- **WHEN** the user clicks the theme toggle button
- **THEN** the theme switches and `localStorage.getItem('theme')` returns the new value

#### Scenario: Override persists across reload
- **WHEN** the user has clicked the toggle and reloads the page
- **THEN** the dashboard loads in the last manually selected theme, ignoring OS preference

### Requirement: Inline theme-init script prevents flash
The dashboard SHALL include a minimal inline `<script>` block in the `<head>`, before any styled content, that applies the correct `data-theme` attribute to `<html>` synchronously. This script SHALL run before the first paint to prevent a flash of incorrect theme.

#### Scenario: No theme flash on load
- **WHEN** the page is loaded with a light-mode localStorage override
- **THEN** the page renders in light mode from the first paint (no visible dark-to-light transition)

### Requirement: Theme toggle button in status bar
The dashboard SHALL include a button with `id="btn-theme"` and an appropriate `aria-label` in the status bar, positioned after the WS indicator. The button content SHALL reflect the current theme: `☀` when in dark mode (offering to switch to light), `🌙` when in light mode (offering to switch to dark).

#### Scenario: Button icon matches current theme
- **WHEN** the dashboard is in dark mode
- **THEN** `#btn-theme` displays `☀`

#### Scenario: Toggle switches theme
- **WHEN** the user clicks `#btn-theme`
- **THEN** the theme toggles and the button icon updates accordingly

### Requirement: Light theme palette
The dashboard SHALL define a `[data-theme="light"]` CSS block that overrides the structural CSS variables. The following values SHALL apply in light mode:

| Variable         | Light value                  |
|------------------|------------------------------|
| `--bg`           | `#f1f5f9`                    |
| `--surface`      | `rgba(0,0,0,0.04)`           |
| `--border`       | `rgba(0,0,0,0.12)`           |
| `--text`         | `#0f172a`                    |
| `--bar-bg`       | `rgba(255,255,255,0.6)`      |
| `--transcribing` | `#475569`                    |
| `--reply-trig`   | `#16a34a`                    |

Semantic colors (`--wake`, `--match`, `--nomatch`, `--info`, `--llm`, `--amber`, `--llm-dim`, `--llm-border`) SHALL remain unchanged in light mode.

#### Scenario: Light mode background
- **WHEN** `data-theme="light"` is set on `<html>`
- **THEN** `--bg` resolves to `#f1f5f9` and the page background is visibly light

### Requirement: Hardcoded colors extracted to CSS variables
Three hardcoded color values in the current file SHALL be replaced with CSS variables so both themes render consistently:

- `rgba(0,0,0,0.3)` in `#status-bar` background CSS → `var(--bar-bg)`
- `#94a3b8` in `setStt` JS (transcribing state inline style) → `var(--transcribing)` or equivalent CSS class
- `#86efac` in `renderActions` JS (on_reply trigger inline style) → `var(--reply-trig)` or equivalent CSS class

#### Scenario: Transcribing text visible in light mode
- **WHEN** the STT state is `transcribing` and the dashboard is in light mode
- **THEN** the transcribing text is readable (not near-white on white)

#### Scenario: Reply trigger readable in light mode
- **WHEN** the dashboard is in light mode and an `on_reply` trigger is rendered
- **THEN** the trigger text is readable (not light green on white)
