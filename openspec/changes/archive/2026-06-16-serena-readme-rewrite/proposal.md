## Why

The current README is a 353-line monolithic technical reference that opens with prerequisites and dumps full YAML config blocks before ever explaining what the project does. It tells, but doesn't sell. The project deserves a README that:

- Makes people **excited** to try it on first glance
- Communicates the "privacy-first, local voice assistant" value proposition instantly
- Distinguishes between **what it is** (captivating story) and **how it works** (technical reference)
- Gives the project a distinct brand identity ("Serena") separate from the package name

## What Changes

1. **Rewrite `README.md`** as a polished ~150-line "product page" under the Serena brand:
   - Logo + tagline + badges at top
   - Benefits-oriented feature grid
   - 7-command quick start (copy-paste friendly)
   - Simple ASCII architecture diagram
   - Web dashboard description + screenshot placeholder
   - Minimal configuration snippet (not the full reference)
   - Links to `details.md` and `docs/` for everything else

2. **Create `details.md`** as a comprehensive technical reference:
   - Architecture overview
   - Full installation guide (deps, venv, models, audio setup, systemd)
   - Complete configuration reference (every field in config.yaml, secrets.yaml, actions/)
   - CLI & task command reference
   - Audio architecture deep-dive (capture, playback, routing, all workarounds)
   - STT pipeline (two-stage detection, phonetics, thresholds)
   - Trigger & action system (all types, LLM learning)
   - Display backends (LED matrix, OLED, GPIO, UART)
   - MQTT & Home Assistant integration
   - Web dashboard routes and WebSocket events
   - Development guide (tests, linting, release)
   - Troubleshooting

3. **No code changes** — package name, CLI entry points, config files, and systemd service remain as `alexa-custom` / `alexa-*`. Brand rename is documentation-only.

## Capabilities

### New Capabilities

None. This is a documentation-only change — no new features.

### Modified Capabilities

None. No existing requirement changes.

## Impact

| Area | Impact |
|------|--------|
| `README.md` | Complete rewrite |
| `details.md` | New file created |
| `docs/` | No changes; links updated if needed |
| Source code | None |
| Config / CLI | None |
| Packaging | None |
