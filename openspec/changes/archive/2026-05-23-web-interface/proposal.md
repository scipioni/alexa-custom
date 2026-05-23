## Why

`alexa-custom` is deployed on headless servers where a terminal UI is unavailable. A browser-based dashboard provides real-time visibility and basic control without requiring SSH access or a local terminal.

## What Changes

- Add `alexa_custom/web.py`: aiohttp HTTP + WebSocket server serving an embedded single-page dashboard
- Add `--web` CLI flag to `alexa_custom/client.py` (alongside existing `--tui`)
- Add `--web-port` CLI flag (default: `8080`)
- Remove `textual` as a hard dependency (make it optional)
- Add `aiohttp` as a dependency

## Capabilities

### New Capabilities

- `web-interface`: Real-time browser dashboard over HTTP/WebSocket — connection status, participants, VU meters (throttled 4 fps), STT state, log stream, and a restart control

### Modified Capabilities

- `yaml-config`: Add optional `web.port` and `web.enabled` config keys

## Impact

- **`alexa_custom/client.py`**: new `--web` / `--web-port` args, new launch branch mirroring the `--tui` branch
- **`alexa_custom/web.py`**: new module (~400 LOC) embedding HTML/JS as a string constant
- **`pyproject.toml`**: `aiohttp` added; `textual` made optional (extra)
- **`config.yaml.example`**: document new `web:` section
- No changes to LiveKit, STT, or audio subsystems — event callbacks are unchanged
