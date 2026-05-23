## Context

`alexa-custom` runs as a headless daemon. The existing `--tui` mode requires a local terminal (Textual), making it useless on headless deployments. The codebase already has a clean, internal event bus: three callbacks (`on_event`, `on_stt_event`, `on_audio_status`) plus a logging handler are the only coupling between the core subsystems and the UI layer. A web interface replaces the Textual rendering surface while leaving everything else untouched.

The LiveKit Rust FFI constraint (must run in its own event loop thread) is well-established by the TUI implementation and carries over unchanged.

## Goals / Non-Goals

**Goals:**
- LAN-accessible real-time dashboard via any browser, no install required
- Mirror the TUI information surface: connection status, participants, VU meters, STT state, live logs
- Basic control: restart the process
- Single new module (`web.py`); zero changes to LiveKit/STT/audio subsystems
- Works headlessly — `--web` is the normal startup mode, not a debug tool

**Non-Goals:**
- Authentication or TLS (LAN-only deployment assumption)
- Mobile-optimised layout
- Configuration editing via the web UI (future change)
- Replacing `--tui` (both modes remain available)
- Persisting log history across page reloads

## Decisions

### D1: aiohttp for HTTP + WebSocket server

**Chosen**: `aiohttp`
**Alternatives considered**:
- `fastapi` + `uvicorn`: heavier, two packages, overkill for a dashboard
- `websockets` + stdlib `http.server`: requires combining two packages; `http.server` is not async-native
- `tornado`: less common in the Python ecosystem today

**Rationale**: `aiohttp` handles both HTTP and WebSocket in one async-native package. It was already transitively installed (via livekit deps). The API surface needed is tiny: one GET route, one WebSocket route.

### D2: Single-page HTML embedded in web.py as a string constant

**Chosen**: Embed the entire frontend (HTML + CSS + JS) as a Python string constant in `web.py`
**Alternatives considered**:
- Separate static files on disk: requires managing paths, packaging complexity, not self-contained
- Jinja2 templates: extra dependency for no benefit at this scale

**Rationale**: The dashboard is a single screen with no build step. A self-contained module is simpler to deploy, test, and reason about. The HTML is ~150 lines — manageable inline.

### D3: asyncio.Queue as the thread→server bridge

**Chosen**: One `asyncio.Queue` fed by `loop.call_soon_threadsafe` from callback threads
**Rationale**: Direct mirror of how the TUI used `_call_threadsafe`. Keeps all WebSocket writes on the server's event loop. Avoids locks.

### D4: Throttle VU meter events to 4 fps via a pending-state coalesce

**Chosen**: `_pending_vu` dict updated on every `volume_update` / STT `level` event; a separate 250 ms `asyncio.sleep` loop drains it
**Rationale**: Audio threads emit ~10 VU events/sec per channel. Over WebSocket this is fine locally, but the browser's DOM update rate would be wasted CPU. Coalescing (keep-latest, not queue) prevents unbounded queue growth on slow clients. Non-VU events (status, STT state, log lines) queue immediately — they're low-frequency.

### D5: Restart via os.execv

**Chosen**: `os.execv(sys.executable, sys.argv)` when the server receives a restart control message
**Rationale**: Clean exec-replace of the process. Reuses the original command line, restores all env vars already in the process, avoids subprocess management complexity. Systemd or any process supervisor will see the process exit and restart it if configured to do so — `execv` bypasses that. This is intentional: restart-from-UI means "reload this process", not "let the supervisor decide".

### D6: --web runs its asyncio loop in the main thread

**Chosen**: `asyncio.run(web_main(...))` in the main thread; LiveKit in a daemon thread (same pattern as TUI)
**Rationale**: The web server needs a persistent event loop for WebSocket connections. `asyncio.run()` blocks the main thread identically to `AlexaTUI.run()`. Ctrl+C raises `KeyboardInterrupt` from `asyncio.run()`, which exits cleanly — no special signal handling needed.

## Risks / Trade-offs

- **No auth** → Any LAN host can view the dashboard and trigger restart. Acceptable for home/lab deployment; documented as a known limitation.
- **Embedded HTML maintainability** → Syntax errors in the HTML string are only caught at runtime. Mitigation: keep the HTML minimal; add a smoke test that instantiates the server and checks `GET /` returns 200.
- **VU throttling hides peaks** → 4 fps means a brief spike might not render. Acceptable — this is a status display, not an audio analyser.
- **os.execv restart** → Does not re-read `.env` or `config.yaml` from a new path if the working directory changed. Acceptable — the daemon is expected to always run from the same working directory.

## Migration Plan

1. Add `aiohttp` to `pyproject.toml` dependencies; move `textual` to an optional extra
2. Implement `alexa_custom/web.py`
3. Add `--web` / `--web-port` args and launch branch to `client.py`
4. Update `config.yaml.example` with `web:` section
5. No data migration required — this is a new optional mode

## Open Questions

- Should `web.enabled: true` in `config.yaml` auto-start the web interface without `--web` flag? (Deferred — keep explicit CLI flag for now)
