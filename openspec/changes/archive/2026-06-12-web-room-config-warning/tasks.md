# Tasks: web-room-config-warning

## Implementation Tasks

- [x] Add `_livekit_ok` and `_telegram_ok` fields to `WebServer.__init__` in `web.py`
- [x] Add `livekit_configured` and `telegram_configured` to the WS `hello` message in `_handle_ws`
- [x] Add `_checkRoomConfig()` JS function and call it from `handle('hello')` in `dashboard.html`
