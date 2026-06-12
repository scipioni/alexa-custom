## Design

### Data Flow

```
load_secrets() → os.environ (LIVEKIT_URL, TELEGRAM_BOT_TOKEN, ...)
                         ↓
                  WebServer.__init__
                    checks os.environ for each required key
                         ↓
                  WS "hello" message
                    { ..., livekit_configured: bool, telegram_configured: bool }
                         ↓
                  dashboard.js handle("hello")
                    calls _checkRoomConfig(m)
                         ↓
                  Room panel DOM updated:
                    rs-icon = "⚠️"
                    rs-label = "Calls disabled"
                    rs-sub = "Missing: LiveKit, Telegram"
```

### Check logic

Each service is "configured" if ALL its env vars are non-empty strings:

- **LiveKit**: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_ROOM`
- **Telegram**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

When both are configured, the room panel is untouched (shows normal status).
When at least one is missing, the room panel switches to warning mode.

### Files changed

| File | Change |
|------|--------|
| `web.py` | `__init__`: 2 boolean fields. `_handle_ws`: 2 fields in hello dict |
| `dashboard.html` | New `_checkRoomConfig()` function, called from `handle('hello')` |

### Not changing

- `client.py`, `config.py`, `stt.py`, `actions.py` — zero touch
- Dashboard HTML structure, CSS, layout — zero touch
- Any other WS message types — zero touch
