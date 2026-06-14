## Why

The assistant has no way to report its own hardware health by voice. On the target board (Snapdragon 801) CPU temperature and load are relevant diagnostics, and there is currently no action to read and speak system vitals.

## What Changes

- Add a `system_info` action handler in `alexa_custom/actions.py` that reads CPU temperature, load average, free memory, and uptime, then speaks a single natural Italian sentence via the existing TTS engine.
- Add an example trigger for `"come sta il sistema"` in `conf/actions/user.yaml` (commented out, consistent with existing examples).

## Capabilities

### New Capabilities

- `system-info-action`: Voice-triggered system health report — CPU temp, load average, free RAM, uptime — spoken in Italian with no configuration params.

### Modified Capabilities

<!-- none -->

## Impact

- `alexa_custom/actions.py`: new `@registry.register("system_info")` handler
- `conf/actions/user.yaml`: new commented-out example trigger
- No new dependencies (reads `/proc` and `/sys` directly)
- No breaking changes
