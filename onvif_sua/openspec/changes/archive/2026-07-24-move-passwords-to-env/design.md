## Context

`onvif_sua/config.py` is the leaf config module. Today it resolves three secrets from `settings.yaml` (loaded into `_settings_doc`):

- **Camera common credential** — `cameras.credentials.{user,pass,port}` → `_COMMON_CRED` via `_load_static_cameras()`. Used by the persistent static workers.
- **Manual-scan credential(s)** — `scan.credentials` (a *list*) → `_cfg["cam_credentials"]`. Consumed by `_get_cred_fallbacks()` (which also tries `_COMMON_CRED` first). The GUI edits this list via the settings-page form (`saveCreds()` → `POST /api/config` with `cam_credentials`).
- **Web login password** — `web.password` (PBKDF2 hash) → `_cfg["web_password"]`. Defaulted to `_hash_password("Admin123")` when absent, checked by `_check_password` at `/api/login`, changed via `/api/change-password`.

Env vars are already the *default* layer for non-secret config, but `settings.yaml` overrides them, and nothing loads a `.env` file (no `python-dotenv`; `os.getenv` reads process env only). The app runs two ways — native `uv run onvif-sua` and Docker Compose (inline `environment:`, no `env_file`). A placeholder-password guard (`DEFAULT_PASSWORD_SENTINEL = "default_to_change"`, `_password_placeholder_flags()`) suppresses workers/scan until real passwords are set.

## Goals / Non-Goals

**Goals:**
- Source all three secrets from a single git-ignored `.env` file, working identically native and in Docker.
- Make `.env` the sole source for all three passwords (camera, scan, web login); remove them from `settings.yaml` and from GUI editing.
- Remove the in-GUI change-password flow; the login password is set only via `GUI_PASSWORD`.
- Preserve the placeholder-password safety guard against the new secret source.

**Non-Goals:**
- No change to the MQTT password (stays in `settings.yaml`) or the camera `port` (stays in `settings.yaml`).
- No change to MQTT topics/payloads, scan discovery behavior, or any route other than `/api/config` (`cam_credentials` field removed) and `/api/change-password` (removed).
- No support for multiple scan credentials — the list collapses to a single env-sourced credential (see decision below).

## Decisions

### Decision: `.env` loaded via `python-dotenv`, called once at startup
Add `python-dotenv` and call `load_dotenv()` before config is resolved. Place the call at the top of `onvif_sua/__main__.py` (the entrypoint) **and** guard config.py so a direct import still works — simplest is a `load_dotenv()` at the top of `__main__` since config values are read at import/`_load_settings_yaml` time. Use `load_dotenv(override=False)` so an explicitly-exported process env var still wins over `.env`. For Docker, add `env_file: .env` to `docker-compose.yml` (dotenv in-container is harmless/redundant but the `env_file` is the canonical Docker path). **Alternative considered:** shell-sourcing `.env` for native runs — rejected as error-prone and not self-contained.

### Decision: Camera + scan credentials become env-only; `settings.yaml` keeps only non-secrets
`_COMMON_CRED` is populated from `CAMERA_USER` (default `admin`) + `CAMERA_PASSWORD`, with `port` still read from `settings.yaml` `cameras.credentials.port`. `_cfg["cam_credentials"]` becomes a single-entry list built from `SCAN_USER`/`SCAN_PASSWORD`, defaulting to the camera credential. `_load_settings_yaml` stops reading `cameras.credentials.pass/user` and `scan.credentials`; `_save_settings_yaml` stops writing them (it must also strip any pre-existing secret keys from `_settings_doc` before writing, so an upgrade cleans the file). `_load_static_cameras` reads only `port` + `list` from the `cameras` block. **Alternative considered:** keep the multi-credential scan list via indexed env vars (`SCAN_PASSWORD_1..N`) — rejected as over-engineered; the deployment uses one common credential (the settings page already warns against multiple).

### Decision: Web password — env-only, GUI change-password removed
`_cfg["web_password"] = _hash_password(os.getenv("GUI_PASSWORD", DEFAULT_PASSWORD_SENTINEL))` at load; `_default_web_password()` is retired. `web.password` is no longer read in `_load_settings_yaml` nor written in `_save_settings_yaml` (and any legacy value is stripped on save). `POST /api/change-password` is deleted from `routes.py`, and the change-password card + `savePassword()` are removed from the settings page. This makes all three secrets single-source (env), matching the camera/scan model. **Alternative considered:** keeping an env boot value with a persistent GUI override — rejected by the user in favor of one source of truth; changing the password now means editing `.env` and restarting.

### Decision: Placeholder guard reads the env-sourced values
`_password_placeholder_flags()` changes its inputs only: `cameras` flag from the env camera password, `scan` flag from the effective env scan password (camera-or-scan). The sentinel string and the downstream suppression behavior are unchanged. An unset password is treated the same as the sentinel (not-configured → suppressed), so a fresh install without a `.env` fails safe rather than auth-storming the cameras.

### Decision: Trim the settings page to MQTT + scan-subnet only
Delete the scan-credentials card/form (`saveCreds()`) AND the change-password card (`savePassword()`) from `settings.html`/`settings.js`; drop the `cam_credentials` branch from `POST /api/config`'s allowed keys and remove `POST /api/change-password` from `routes.py`. The endpoint keeps MQTT + `scan_subnet`. The MQTT-password field stays (out of scope).

## Risks / Trade-offs

- **Existing deployments break on upgrade if no `.env` is created** → Mitigation: placeholder guard fails safe (workers/scan suppressed, GUI shows the existing password warning), README migration note, and `.env.example` shipped. No silent auth against cameras.
- **No in-GUI password change means an operator must edit `.env` + restart** → Mitigation: documented in README and on the (trimmed) settings page; accepted trade-off for single-source secrets. All three passwords now behave identically (env-only).
- **`.env` committed by accident** → Mitigation: add `.env` to `.gitignore`; only `.env.example` is committed.
- **`override=False` surprises someone who expects `.env` to win over a stale exported var** → Mitigation: documented in `.env.example` header; matches dotenv's conventional default.
- **Stale secrets left in an operator's `settings.yaml` after upgrade** → Mitigation: `_save_settings_yaml` actively strips `cameras.credentials.pass/user` and the `scan.credentials` block on write, so the first save cleans the file.

## Migration Plan

1. Ship `.env.example`, add `.env` to `.gitignore`, add `python-dotenv` to `pyproject.toml` + `uv.lock`, add `env_file: .env` to `docker-compose.yml`.
2. On upgrade, operator copies `.env.example` → `.env` and sets `CAMERA_PASSWORD`, optionally `SCAN_PASSWORD`, and `GUI_PASSWORD` (the new web login password).
3. First boot: all three passwords come from `.env`. Any legacy `web.password` hash and `cameras.credentials.pass`/`scan.credentials` in `settings.yaml` are ignored and stripped on the next `settings.yaml` write.
4. **Rollback**: revert the code and restore the pre-upgrade `settings.yaml` (which still holds the old secret blocks) — keep a backup before upgrading, since the first save under the new version strips those keys.

## Open Questions

- None. (Web-password precedence, single-scan-credential scope, and load mechanism resolved with the user.)
