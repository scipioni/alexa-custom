## Why

The `che giorno è` trigger currently uses `$(date +'Oggi è %A %d %B %Y')` to produce its response. `%A` and `%B` are locale-dependent — the systemd user service runs with `LANG=C` on the target board, so day/month names are emitted in English instead of Italian. Fixing this at the system level (locale generation, environment variables) adds brittle Debian-side dependencies. A self-contained action type solves it unconditionally.

## What Changes

- Add a new action type `say_date` registered in the action registry
- The action accepts a `format` parameter with `{weekday}`, `{day}`, `{month}`, `{year}` placeholders
- Italian day and month names are hardcoded in Python — zero locale dependency
- Update `conf/actions/system.yaml` to use `say_date` instead of `$(date +...)` for the `che giorno è` trigger
- Update `conf.example/actions/system.yaml` to match

## Capabilities

### New Capabilities

- `say-date-action`: A new action type that speaks the current date with hardcoded Italian day/month names, locale-independent

### Modified Capabilities

- None — no spec-level behavior changes to existing capabilities

## Impact

- `alexa_custom/actions.py` — add handler for `say_date` type
- `conf/actions/system.yaml` — change `che giorno è` trigger action from `say` with shell template to `say_date`
- `conf.example/actions/system.yaml` — same change (reference config)
- `tests/test_actions.py` — add tests for the new action type
