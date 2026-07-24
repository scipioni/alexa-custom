## ADDED Requirements

### Requirement: Package layout and entrypoint
The service SHALL be organized as an `onvif_sua/` Python package and SHALL be startable with `python -m onvif_sua`. The package SHALL separate concerns into modules: configuration/settings (`config.py`), MQTT (`mqtt.py`), ONVIF connection handling (`connect.py`), network scanning (`scan.py`), and the web layer (`web/`), with the startup sequence living in a `main()` function invoked by `__main__.py`. The ONVIF connection module SHALL be a plain module named `connect.py` at the package root and SHALL NOT be an `onvif/` subpackage, to avoid shadowing the third-party `onvif` library the code depends on.

#### Scenario: Service starts via the package entrypoint
- **WHEN** `python -m onvif_sua` is run with the same environment and `settings.yaml` as before
- **THEN** the service loads settings, initializes MQTT, starts the web server and save loop, and enters its main loop exactly as the previous `app.py` did

### Requirement: Installable package with a console entrypoint
The project SHALL provide a `pyproject.toml` targeting Python 3.13 (`requires-python = ">=3.13"`) that declares the package, its runtime dependencies, and a console-script entrypoint named `onvif-sua`. The console script, `python -m onvif_sua`, and an in-process call to `main()` SHALL all use the same startup logic with no duplication.

The `>=3.13` floor is an intentional deployment constraint, not an accident of convenience: this service is operated alongside a companion piece of software that requires Python 3.13, and both are intended to run on a shared 3.13 toolchain/environment. Because 3.13 is a hard floor, every runtime dependency (notably `onvif-zeep-async` and its `zeep` stack) SHALL be confirmed to install and import on Python 3.13 before the floor is relied upon; if any dependency lacks a 3.13-compatible release, that MUST be surfaced and resolved (pin/patch/replace) rather than silently lowering the floor.

#### Scenario: Native install and run in a uv venv
- **WHEN** a user creates a Python 3.13 virtualenv with `uv venv --python 3.13`, installs with `uv sync --frozen` (the single install verb used by both run modes; not `uv pip install -e .`), and then runs `uv run onvif-sua`
- **THEN** the service starts identically to `uv run python -m onvif_sua`, with the same behavior as the previous `app.py`

#### Scenario: All dependencies resolve and import on Python 3.13
- **WHEN** the package and its full dependency set are installed into a Python 3.13 environment
- **THEN** every runtime dependency (including `onvif-zeep-async`/`zeep`, `fastapi`, `uvicorn`, `requests`, `paho-mqtt`, `PyYAML`) installs with a 3.13-compatible wheel/build and imports without error, so the shared-3.13 constraint with the companion software holds

#### Scenario: Dependencies come from pyproject
- **WHEN** the package is installed from `pyproject.toml`
- **THEN** all runtime dependencies (fastapi, uvicorn, onvif-zeep-async, requests, paho-mqtt, PyYAML) are installed without needing `requirements.txt`

### Requirement: Both native and Docker run modes are supported
The service SHALL be runnable in two modes from the same package and entrypoint: (1) a native Python install via `pyproject.toml`, and (2) a Docker container that installs the package. Both modes SHALL produce identical runtime behavior.

To make "identical runtime behavior" reproducible, the repository SHALL commit a `uv.lock` (produced by `uv lock`) that pins every runtime (and transitive) dependency to an exact version. `pyproject.toml` SHALL hold dependency *ranges* (the maintained intent), while the committed `uv.lock` SHALL be the single reproducibility source of truth. Both the native install and the Docker build SHALL install from `uv.lock` (via `uv sync --frozen`) rather than re-resolving the `pyproject.toml` ranges independently, so the two modes cannot drift to different resolved versions when built at different times.

#### Scenario: Native mode
- **WHEN** the package is installed into a uv-managed Python 3.13 virtualenv and started via the console script or module entrypoint
- **THEN** the service runs with the same MQTT output, HTTP routes, and GUI as in Docker mode

#### Scenario: Docker mode
- **WHEN** the container image (built from the same `pyproject.toml`) is started
- **THEN** the service runs with the same MQTT output, HTTP routes, and GUI as in native mode

#### Scenario: Both modes resolve to the same pinned dependency versions
- **WHEN** the native venv and the Docker image are built at different times from the committed lockfile
- **THEN** both install the exact same version of every dependency (as pinned in the lockfile), so no dependency-version drift can occur between the two run modes regardless of when each was built

#### Scenario: Concerns live in their designated modules
- **WHEN** a maintainer looks for settings/credential resolution, MQTT publish/discovery, ONVIF connect/close, or subnet scanning
- **THEN** each is found in `config.py`, `mqtt.py`, `connect.py`, and `scan.py` respectively, and no single module reconstitutes the previous monolith

### Requirement: MQTT output is unchanged by the refactor
The refactor SHALL NOT change any MQTT topic, unique_id, discovery payload, or state payload produced by the service. Home Assistant integrations depending on the current MQTT contract MUST continue to work without reconfiguration.

#### Scenario: Discovery and state payloads match pre-refactor output
- **WHEN** a camera connects, changes state, and publishes detection/keepalive after the refactor
- **THEN** the published topics, unique_ids, and payloads are identical to those produced by the pre-refactor `app.py` for the same inputs

#### Scenario: MQTT parity is verified deterministically
- **WHEN** the discovery + state publish functions are driven for one fixed camera (fixed name and fixed configuration) through a stub MQTT client that records each `publish(topic, payload, qos, retain)` call instead of connecting to a broker, both before and after the refactor
- **THEN** the recorded ordered list of `(topic, payload)` calls after the refactor is byte-identical to the committed pre-refactor baseline, so parity does not depend on a live broker or ad-hoc capture

### Requirement: HTTP routes and rendered GUI are unchanged by the refactor
The refactor SHALL preserve every HTTP route (path, method, request and response shape) and the rendered GUI, except for the client-side polling behavior defined in the `web-dashboard-polling` capability. Templates SHALL be served from `web/templates/` and CSS/JS from `web/static/`.

CSS and JS SHALL be extracted as **one CSS + JS pair per page** — `login.css`/`login.js`, `settings.css`/`settings.js`, `index.css`/`index.js` — each extracted verbatim from that page's own inline `<style>`/`<script>` block, and each page's template SHALL reference **only its own pair**. The assets SHALL NOT be merged into a single shared `app.css`/`app.js`: the pages share no client-side code (the `apiFetch` helper and the `refresh`/`refreshAlarms` pollers exist only on the dashboard; login and settings use plain `fetch`), so page-specific JavaScript SHALL NOT be loaded on a page it does not belong to. In particular, the dashboard pollers SHALL NOT execute on the login or settings pages.

Each route's existing authentication behavior SHALL be preserved exactly. In particular, the alarm-data endpoints `/api/alarms` and `/alarm.json` are **already unauthenticated in the pre-refactor `app.py`** (no `_valid_session` check) and SHALL remain unauthenticated after the refactor — this is behavior-preserving and explicitly out of scope to change; it is called out so the pre-existing exposure is recorded as a known, accepted fact rather than a regression introduced here.

`Jinja2Templates` and `StaticFiles` SHALL resolve their directories from the package installation location (e.g. `Path(__file__).resolve().parent / "web" / "templates"` and `.../ "web" / "static"`, or `importlib.resources.files("onvif_sua.web")`), and SHALL NOT rely on the current working directory or any CWD-relative path. The build backend SHALL be **setuptools**, and the `web/templates/` and `web/static/` trees SHALL be declared as package data via an explicit `[tool.setuptools.package-data]` entry — `"onvif_sua" = ["web/templates/*.html", "web/static/*"]` — so they are copied into the built wheel and present after installation (an implicit or VCS/`MANIFEST.in`-dependent mechanism SHALL NOT be relied upon). This SHALL hold for a non-editable install (`uv pip install .`) with no source bind-mount, not only for editable/bind-mounted layouts.

#### Scenario: Existing endpoints respond identically
- **WHEN** any `/api/*` endpoint or page route is requested after the refactor with the same session/auth and inputs
- **THEN** the response status, headers relevant to behavior, and body are equivalent to the pre-refactor response

#### Scenario: Dashboard renders equivalently
- **WHEN** the login, settings, and index pages are rendered after templates and static assets are extracted
- **THEN** the delivered DOM is equivalent to the pre-refactor pages apart from the polling constants and visibility handling

#### Scenario: Render parity is verified against committed deterministic baselines
- **WHEN** the `/`, `/login`, and `/settings` pages are captured via an in-process test client using a fixed session and a fixed committed `settings.yaml`, both before and after the refactor
- **THEN** each extracted `static/*.css`/`*.js` file is byte-identical to the inline block it was moved from, and each page's HTML matches the committed baseline except for each moved inline block being replaced by its `<link>`/`<script src="...?v=...">` reference and the intentional polling/`asset_version` deltas

#### Scenario: Page-specific assets do not execute on other pages
- **WHEN** the login page and the settings page are loaded after extraction, each referencing only its own CSS/JS pair
- **THEN** no dashboard-only JavaScript runs on them — there are no JavaScript console errors and no `/api/*` polling requests originate from the login or settings pages

#### Scenario: Non-editable install serves templates and static assets
- **WHEN** the package is installed with a non-editable `uv pip install .` (no source bind-mount) and started via the console entrypoint
- **THEN** template pages render and `/static/*` assets are served successfully, resolved from the installed package location rather than the current working directory (no `TemplateNotFound` or `Directory ... does not exist` error)

### Requirement: Static assets are served publicly and support cache revalidation
The `/static` mount SHALL NOT be gated by the per-route `_valid_session` check — a `StaticFiles` mount is a separate sub-application that is unauthenticated by default, so no session guard applies to it and none SHALL be added. This is acceptable because the extracted CSS/JS contain no secrets and the login page (which is not session-gated) depends on its stylesheet.

Static assets SHALL support cache revalidation so that future edits to polling constants (or any CSS/JS) reach long-running kiosk sessions. The cache-busting version token SHALL be sourced from `settings.yaml`: a `web.asset_version` key (a string) SHALL be loaded by `config.py` into the runtime config, defaulting to a fixed value (`"1"`) when the key is absent, and SHALL be exposed to the templates as a Jinja2 global named `asset_version`. Every `/static/*` asset reference in the templates SHALL carry `?v={{ asset_version }}` (e.g. `/static/index.js?v={{ asset_version }}`). Bumping `web.asset_version` in `settings.yaml` and restarting the service SHALL change every static asset URL so kiosks re-fetch. The settings load/save path SHALL round-trip `web.asset_version` — the GUI's settings save MUST NOT drop the key. This settings-sourced token is the primary mechanism and SHALL be documented in the deploy steps; `StaticFiles` `Last-Modified`/`ETag` revalidation MAY additionally apply but is not required to satisfy this requirement.

#### Scenario: Unauthenticated login page loads its stylesheet
- **WHEN** an unauthenticated client requests the login page and then its referenced `/static` stylesheet/script
- **THEN** the `/static` assets are returned with a 200 response (not redirected to `/login`), so the login form is styled and functional without a session

#### Scenario: Asset version is sourced from settings.yaml
- **WHEN** `settings.yaml` sets `web.asset_version: "7"` and the pages are rendered
- **THEN** every `/static/*` reference in the delivered HTML carries `?v=7` (e.g. `/static/index.js?v=7`), and when the key is absent the default (`"1"`) is used instead

#### Scenario: Edited polling constants reach a long-running kiosk
- **WHEN** a static asset containing polling constants is edited, `web.asset_version` in `settings.yaml` is bumped to a new value, the service is restarted, and a kiosk that already cached the old asset reloads the dashboard
- **THEN** the new `?v=` value on every `/static/*` URL causes the kiosk to fetch the updated asset rather than silently serving the stale cached copy

#### Scenario: GUI settings save preserves the asset version
- **WHEN** the operator saves configuration through the settings GUI while `web.asset_version` is set in `settings.yaml`
- **THEN** `web.asset_version` is round-tripped and remains present in `settings.yaml` after the save (it is not dropped)

### Requirement: Taskfile provides setup and run commands for both modes
The repository SHALL include a `Taskfile.yml` (go-task) that exposes tasks to set up and run each mode: the uv-native path (create venv + install, run) and the Docker path (build, up, down, logs). Tasks SHALL only invoke the documented uv/docker commands and SHALL NOT introduce behavior that differs from running those commands directly.

#### Scenario: Set up and run the native mode via Task
- **WHEN** an operator runs the native setup task and then the native run task
- **THEN** a uv-managed Python 3.13 venv is created, the package is installed, and the service starts via `onvif-sua`

#### Scenario: Set up and run the Docker mode via Task
- **WHEN** an operator runs the Docker up task (building if needed)
- **THEN** the container is built/started and serves the dashboard, equivalent to running the underlying `docker compose` commands directly

### Requirement: Deployment runs the installed package
The container image SHALL be based on `python:3.13-slim`, install dependencies and the package with `uv sync --frozen` from the committed `uv.lock`, and run the `onvif-sua` console entrypoint (via `uv run`, or with the venv's `bin` on `PATH`). Existing environment variables, the `settings.yaml` mount, and the `./data` mount SHALL remain unchanged in name and meaning.

The project SHALL be installed in **editable** mode (as `uv sync` does by default) and the container SHALL bind-mount the host package source over the editable target (`./onvif_sua:/app/onvif_sua:ro`). As a result, after the first image build, editing host code and running `docker compose restart` SHALL cause the change to take effect **without an image rebuild**; the running package SHALL be the bind-mounted source, not a frozen in-image copy. The bind-mount SHALL cover only the package source (plus `settings.yaml` and `./data`) and SHALL NOT mount over the image's virtualenv or `pyproject.toml`. Changing dependencies still requires regenerating `uv.lock` and rebuilding the image; only code edits are rebuild-free.

#### Scenario: Container boots and serves after the deploy change
- **WHEN** the updated `Dockerfile`/`docker-compose.yml` is deployed
- **THEN** the container installs the package via `uv sync --frozen`, starts via the `onvif-sua` entrypoint, serves the dashboard, and connects to MQTT using the same configuration as before

#### Scenario: Code edit takes effect on restart without a rebuild
- **WHEN** the image has already been built once, a developer edits a file under the bind-mounted `onvif_sua/` source (e.g. a polling constant in `web/static/index.js` or Python in a module), and runs `docker compose restart`
- **THEN** the running container serves the edited code without any image rebuild, because the project is installed editable and the interpreter imports from the bind-mounted source
