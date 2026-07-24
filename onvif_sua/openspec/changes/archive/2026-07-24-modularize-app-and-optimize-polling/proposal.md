## Why

`app.py` is a 3167-line monolith mixing config, MQTT, ONVIF, scanning, the FastAPI web layer, and all HTML/CSS/JS templates in one file. This makes the code hard to navigate, review, and test, and every edit risks touching unrelated concerns. Splitting it into a proper `onvif_sua/` package — with **no change to observable behavior** — makes the project maintainable. While reorganizing, we also cut needless dashboard load: a fall-alarm panel pushes alarm state to Home Assistant over MQTT, so the web UI is a monitoring view, not the alarm path, and can poll far less aggressively (especially when the tab isn't even visible).

## What Changes

- Split `app.py` into an `onvif_sua/` package with focused modules:
  - `__main__.py` — entrypoint (`python -m onvif_sua`), replacing the `if __name__ == "__main__"` block.
  - `config.py` — env vars, `settings.yaml` load/save, `_cfg`, credential resolution.
  - `mqtt.py` — discovery + publish (device, detect, detection_ok, keepalive).
  - `connect.py` — `_try_connect`, `_get_services`, `_safe_close`/`_safe_unsubscribe` (a plain module at the package root, deliberately NOT an `onvif/` subpackage — see design, to avoid shadowing the third-party `onvif` library).
  - `scan.py` — `_probe_ip`, `_subnet_scan_once`, `_tcp_probe` (manual GUI rescan).
  - `web/app.py` — FastAPI instance, route wiring, auth (`_valid_session`, HMAC).
  - `web/routes.py` — `/api/*` endpoints.
  - `web/templates/` — `login.html`, `settings.html`, `index.html` (Jinja2), extracted from the `_html_*()` string builders.
  - `web/static/` — one CSS + JS pair **per page**, extracted verbatim from each page's own inline blocks: `login.css`/`login.js`, `settings.css`/`settings.js`, `index.css`/`index.js`. They are NOT merged into a single shared `app.css`/`app.js`: the three pages share no JS (`apiFetch` and the pollers exist only on the dashboard; login/settings use plain `fetch`), and a shared `index.js` loaded on `/login` would run dashboard-only pollers against DOM that doesn't exist there. Each page's template references only its own pair.
- Add a `pyproject.toml` (Python 3.13, `requires-python = ">=3.13"`) that declares the package, its dependencies (from the current `requirements.txt`), and a console-script entrypoint (`onvif-sua`). The project becomes installable into a uv-managed venv via `uv sync --frozen` (which installs the project editable and pins deps from the committed `uv.lock`).
- Support **two run modes** from the same package, with no duplicated logic. **Both modes use the same single install verb — `uv sync --frozen` — so neither re-resolves dependency ranges independently** (see the lockfile decision in `design.md`):
  1. **Native Python (uv venv)**: `uv venv --python 3.13` + `uv sync --frozen`, then run via `uv run onvif-sua` or `uv run python -m onvif_sua`.
  2. **Docker**: image runs `uv sync --frozen` (editable project + frozen deps) and runs the same entrypoint. Because the project is installed **editable**, the running code is read from the bind-mounted source, so code changes take effect on `docker compose restart` with no image rebuild after the first build.
- Add a `Taskfile.yml` ([go-task](https://taskfile.dev)) as the single command surface for both modes: setup/run/stop/logs tasks for the uv-native path and the Docker path (e.g. `task setup`, `task run`, `task docker:up`, `task docker:logs`).
- **BEHAVIOR-PRESERVING**: MQTT discovery/state topics and payloads, and every HTTP route's response (including the rendered GUI), stay byte-for-behavior identical to today.
- Slow dashboard polling: `refresh` 4s → 15s, `refreshAlarms` 3s → 12s.
- Pause polling when the tab is hidden: wire the existing `paused` guard to `document.hidden` / `visibilitychange` so a backgrounded or screen-off kiosk panel does zero polling work, and refresh immediately on becoming visible again.
- Update the Docker image (base to `python:3.13-slim`, `uv sync --frozen` to install the editable project + frozen deps, run the console entrypoint via `uv run`) and volume mounts to run the package instead of the single `app.py`. The bind-mounted source + editable install means code edits require only `docker compose restart`, never a rebuild, after the first build.

## Capabilities

### New Capabilities
- `application-structure`: The package layout, `pyproject.toml` packaging (Python 3.13), the console-script and `python -m onvif_sua` entrypoints, the two supported run modes (native pip install and Docker), module boundaries, and the invariant that MQTT output and HTTP/GUI responses are unchanged by the refactor.
- `web-dashboard-polling`: The dashboard's refresh cadence and visibility-aware pausing behavior.

### Modified Capabilities
<!-- None: no existing specs in openspec/specs/. -->

## Impact

- **Code**: `app.py` (removed, contents distributed into the new package); new `onvif_sua/` tree; new `pyproject.toml` (replaces `requirements.txt` as the dependency source of truth — `requirements.txt` may be kept as a thin pin or removed); new `Taskfile.yml`.
- **Runtime/deploy**: `Dockerfile` (base `python:3.13-slim`, `uv sync --frozen` for an editable install), `docker-compose.yml` (volume mounts, `command`/entrypoint), and any process manager that invokes `python app.py`. Native install path: `uv venv --python 3.13` + `uv sync --frozen` → `uv run onvif-sua`.
- **Config**: `SETTINGS_FILE` and env-var handling move into `config.py`; values and names unchanged.
- **External contracts (unchanged)**: MQTT topic/payload schema consumed by Home Assistant; the web dashboard's DOM/endpoints. Only the client-side polling intervals and visibility handling change.
