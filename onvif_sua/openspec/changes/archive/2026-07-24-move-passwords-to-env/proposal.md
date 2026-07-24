## Why

All three secrets the deployment cares about — the camera common credential, the manual-scan credential, and the web GUI login password — currently live in `settings.yaml` (the camera/scan passwords in plaintext, the web password as a PBKDF2 hash). That file is bind-mounted writable and edited by the GUI, so secrets sit next to non-secret config and are easy to commit or leak. Moving them to a `.env` file gives a single, git-ignored secret surface that works identically for native (`uv run`) and Docker runs.

## What Changes

- **New `.env` secret surface**, auto-loaded via `python-dotenv` at startup (native `uv run`) and via `env_file: .env` in `docker-compose.yml` (Docker). A committed `.env.example` documents the variables.
- **Camera common credential** (`cameras.credentials.pass` → `_COMMON_CRED`) comes from `CAMERA_USER` (default `admin`) + `CAMERA_PASSWORD`. **BREAKING**: it is no longer read from or written to `settings.yaml`; the `cameras` block keeps only non-secret fields (`port`, the camera `list`).
- **Manual-scan credential** (`_cfg["cam_credentials"]`) comes from `SCAN_USER` + `SCAN_PASSWORD`, defaulting to the camera credential when unset. **BREAKING**: the `scan.credentials` block is dropped from `settings.yaml`, and **in-GUI editing of scan credentials is removed** (the settings-page credentials form / `saveCreds()` and the `cam_credentials` branch of `POST /api/config`).
- **Web GUI login password**: sourced solely from `GUI_PASSWORD` (plaintext), hashed in memory at load. **BREAKING**: the in-GUI change-password flow is **removed** (`POST /api/change-password`, the settings-page change-password card, and `savePassword()`), and `web.password` is no longer read from or written to `settings.yaml`. To change the login password, edit `.env` and restart.
- **Safety guard preserved**: the placeholder-password check (`DEFAULT_PASSWORD_SENTINEL = "default_to_change"`) now evaluates the `.env`-sourced camera/scan passwords, so camera workers and the manual scan stay suppressed until a real password is set.
- **Docs**: add `.env.example`; update `settings.yaml.example` and `README.md` to state that passwords now live in `.env`.
- **Out of scope**: the MQTT password (`mqtt.pass`) stays in `settings.yaml`; the camera `port` stays in `settings.yaml` (not a secret).

## Capabilities

### New Capabilities
- `credential-config`: how the three secrets (camera credential, scan credential, web login password) are sourced solely from `.env`, loaded in both run modes, with in-GUI password editing removed, and gated by the placeholder-password safety guard.

### Modified Capabilities
<!-- None: no existing main-spec capability changes its requirements. The scan-control spec is unaffected (only the credential SOURCE changes, not scan behavior). -->

## Impact

- **Dependencies**: add `python-dotenv` to `pyproject.toml` (and `uv.lock`).
- **Code**: `onvif_sua/config.py` (env sourcing for `_COMMON_CRED`, `_cfg["cam_credentials"]`, `web_password` from `GUI_PASSWORD`; `_load_settings_yaml`/`_save_settings_yaml` stop reading/writing camera+scan+web passwords; `_load_static_cameras`; `_password_placeholder_flags`), `onvif_sua/__main__.py` (`load_dotenv()` at startup), `onvif_sua/web/routes.py` (remove `cam_credentials` editing from `POST /api/config`; remove `POST /api/change-password`), `onvif_sua/web/templates/settings.html` + `onvif_sua/web/static/settings.js` (remove the scan-credentials form AND the change-password card/handler).
- **Config/ops**: `docker-compose.yml` (`env_file: .env`), new `.env.example`, updated `settings.yaml.example` and `README.md`.
- **External contracts**: `POST /api/config` no longer accepts `cam_credentials` (GUI form removed); `POST /api/change-password` is removed. No MQTT topic/payload change. Existing deployments must create a `.env` with real passwords on upgrade (migration note in README).
- **Migration**: on first run after upgrade, operators move their camera/scan passwords into `.env` and set `GUI_PASSWORD` to their desired web login password; the old `web.password` hash in `settings.yaml` is ignored and stripped on the next save.
