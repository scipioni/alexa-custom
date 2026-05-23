## 1. Dependencies & Packaging

- [x] 1.1 Add `aiohttp>=3.9` to `pyproject.toml` dependencies
- [x] 1.2 Move `textual>=0.70` to an optional extra in `pyproject.toml` (e.g. `[project.optional-dependencies] tui = ["textual>=0.70"]`)

## 2. Core WebSocket Server (web.py)

- [x] 2.1 Create `alexa_custom/web.py` with `WebServer` class holding an `asyncio.Queue`, a `set` of active WebSocket clients, and `_pending_vu` dict
- [x] 2.2 Implement `_enqueue(event_type, data)` using `loop.call_soon_threadsafe` — the thread-safe entry point used by all callbacks
- [x] 2.3 Implement `_broadcast_loop()` coroutine: drain queue and fan-out JSON to all WS clients; handle disconnected clients without crashing
- [x] 2.4 Implement VU throttle: separate `_vu_flush_loop()` coroutine with `asyncio.sleep(0.25)` that sends `_pending_vu` if non-empty then clears it
- [x] 2.5 Implement `on_event(event, data)`, `on_stt_event(event, data)`, `on_audio_status(connected, conn_type)` callbacks with same signatures as `tui.py`
- [x] 2.6 Implement `_WebLogHandler(logging.Handler)` that enqueues log records as `{"type": "log", ...}` messages and suppresses stdout handlers while active

## 3. HTTP Routes

- [x] 3.1 Implement `GET /` route returning the embedded HTML string with `Content-Type: text/html`
- [x] 3.2 Implement `GET /ws` WebSocket route: upgrade, send `hello` snapshot, register client, dispatch incoming control messages, deregister on close
- [x] 3.3 Handle `{"type": "control", "action": "restart"}`: broadcast `{"type": "restarting"}`, then call `os.execv(sys.executable, sys.argv)`

## 4. Embedded Frontend (HTML/JS in web.py)

- [x] 4.1 Write HTML skeleton: dark monospace theme, sections for status bar, participants panel, log panel, VU meters, STT status, restart button
- [x] 4.2 Write CSS: dark background (`#1a1a1a`), CSS-driven VU bar (width % driven by JS, green/yellow/red thresholds matching TUI), log entry styling
- [x] 4.3 Write JS WebSocket client: `connect()` with 2 s auto-reconnect on close/error
- [x] 4.4 Write JS event dispatcher: `handleEvent(msg)` routing each `type` to a DOM update function
- [x] 4.5 Implement DOM updates: `updateStatus`, `updateParticipants`, `updateVU`, `updateSTT`, `appendLog` functions
- [x] 4.6 Implement restart button: `sendControl('restart')` sends WS message; disable button and show "Restarting…" on click

## 5. Lifecycle & Shutdown

- [x] 5.1 Implement `async def run(run_fn, ...)` coroutine: starts aiohttp app, broadcast loop, VU flush loop, LiveKit thread, STT thread (mirrors `AlexaTUI.on_mount`)
- [x] 5.2 Implement graceful shutdown: on `KeyboardInterrupt` from `asyncio.run()`, stop aiohttp runner, close WS clients, set stop events
- [x] 5.3 Apply the `os._exit(0)` grace-period pattern (same as `--tui` branch) after `asyncio.run()` returns to force-exit LiveKit FFI threads

## 6. client.py Integration

- [x] 6.1 Add `--web` (store_true) and `--web-port` (int, default 8080) arguments to the argument parser
- [x] 6.2 Add `if args.web:` launch branch in `main()` mirroring the existing `if args.tui:` block, calling `web.run_web(...)`
- [x] 6.3 Pass `web_port` from CLI arg (with `config.web.port` as fallback) into `run_web`
- [x] 6.4 Export `run_web()` as the public entry point from `web.py`

## 7. Config & Documentation

- [x] 7.1 Add `web:` section to `config.yaml.example` with `port: 8080` and a comment explaining the `--web` flag
- [x] 7.2 Update `README.md` usage section to document `--web` and `--web-port` flags
