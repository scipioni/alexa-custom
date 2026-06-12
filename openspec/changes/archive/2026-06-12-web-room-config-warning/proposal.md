## Why

When LiveKit or Telegram credentials are missing from `conf/secrets.yaml`, the web dashboard's room panel still shows "Closed — No active call" with no indication that calls are permanently unavailable. The user only discovers this when an action fails at runtime.

## What Changes

- Read `os.environ` (populated by `load_secrets()`) in `WebServer.__init__` to determine LiveKit/Telegram configuration status
- Send `livekit_configured` and `telegram_configured` booleans in the WS `hello` message
- New JS function `_checkRoomConfig()` overwrites the room panel's icon, label, and subtitle when config is missing
- No new HTML/CSS, no layout changes — existing room panel DOM reused

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `web-interface`: Room panel reflects LiveKit/Telegram config status when secrets are missing

## Impact

- `alexa_custom/web.py`: ~6 lines in `__init__`, 2 fields in WS hello
- `alexa_custom/dashboard.html`: ~12 lines JS, no HTML/CSS changes
