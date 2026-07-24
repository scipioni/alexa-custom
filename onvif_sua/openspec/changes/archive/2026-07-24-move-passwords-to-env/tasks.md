## 1. Dependency & .env loading

- [x] 1.1 Add `python-dotenv` to `pyproject.toml` `dependencies` and refresh `uv.lock` (`uv lock`).
- [x] 1.2 Call `load_dotenv(override=False)` before any config value is read. Placed at the top of `onvif_sua/config.py` (the leaf module imported before any `os.getenv`) rather than `__main__.py`, because `__main__` imports `config` — and its module-level `os.getenv` reads — before `main()` runs.
- [x] 1.3 Add `env_file: .env` to the `onvif-events` service in `docker-compose.yml`.
- [x] 1.4 Add `.env` to `.gitignore` (create the file if missing) so only `.env.example` is committed.

## 2. Camera & scan credentials from env (config.py)

- [x] 2.1 Populate `_COMMON_CRED` from `CAMERA_USER` (default `admin`) + `CAMERA_PASSWORD`, keeping `port` sourced from `settings.yaml` `cameras.credentials.port`.
- [x] 2.2 Build `_cfg["cam_credentials"]` as a single-entry list from `SCAN_USER`/`SCAN_PASSWORD`, defaulting each to the camera credential when unset.
- [x] 2.3 In `_load_settings_yaml`, stop reading `cameras.credentials.pass/user` and the entire `scan.credentials` block.
- [x] 2.4 In `_load_static_cameras`, read only `port` + `list` from the `cameras` block (no `pass`/`user`).
- [x] 2.5 In `_save_settings_yaml`, stop writing camera/scan passwords AND strip any pre-existing `cameras.credentials.pass/user` and `scan.credentials` keys from `_settings_doc` before writing (upgrade cleanup).

## 3. Web login password (env-only)

- [x] 3.1 Set `_cfg["web_password"] = _hash_password(GUI_PASSWORD)` at load; retire `_default_web_password()`. Stop reading `web.password` in `_load_settings_yaml` and stop writing it in `_save_settings_yaml` (strip any legacy `web.password` key on save).
- [x] 3.2 Remove `POST /api/change-password` from `onvif_sua/web/routes.py`.

## 4. Placeholder-password guard

- [x] 4.1 Update `_password_placeholder_flags()` to evaluate the env-sourced camera password (`cameras` flag) and the effective env scan password (`scan` flag); treat an unset password as the sentinel (fail-safe suppression).
- [x] 4.2 Confirm `GET /api/status` still exposes `password_warning` with `cameras`/`scan` flags unchanged in shape.

## 5. Trim settings-page password editing

- [x] 5.1 In `onvif_sua/web/routes.py`, drop `cam_credentials` from the allowed keys of `POST /api/config` (silently ignore if submitted).
- [x] 5.2 In `settings.html`, remove the scan-credentials card/form (the `cam_pass` input + "Salva credenziali" button) AND the change-password card.
- [x] 5.3 In `settings.js`, remove `saveCreds()`, the credential-display logic, and `savePassword()`; leave the MQTT handler intact.

## 6. Docs & examples

- [x] 6.1 Add `.env.example` documenting `CAMERA_USER`, `CAMERA_PASSWORD`, `SCAN_USER`, `SCAN_PASSWORD`, `GUI_PASSWORD`, with a header noting exported vars win (`override=False`).
- [x] 6.2 Update `settings.yaml.example` to remove `cameras.credentials.pass/user` and `scan.credentials`, keeping `cameras.credentials.port`, `cameras.list`, and a note that passwords live in `.env`.
- [x] 6.3 Update `README.md` with the `.env` setup + migration note: move camera/scan passwords into `.env`, set `GUI_PASSWORD` for the web login, note that the login password is changed by editing `.env` + restart (no in-GUI change), and that legacy `settings.yaml` password keys are ignored/stripped.

## 7. Verification

- [x] 7.1 Native `uv run` with a `.env`: camera/scan credentials resolve from env; an exported var overrides the `.env` value.
- [x] 7.2 Login works with `GUI_PASSWORD`; a legacy `web.password` hash in `settings.yaml` is ignored and stripped on the next save; `POST /api/change-password` returns not-found and no change-password form is shown.
- [x] 7.3 With `CAMERA_PASSWORD` unset or `default_to_change`: `password_warning.cameras` is true, workers suppressed, manual rescan refused; with real passwords both flags clear.
- [x] 7.4 A GUI save writes `settings.yaml` with no camera/scan password keys (pre-existing secret keys are stripped); MQTT password and camera port are unaffected.
- [x] 7.5 `POST /api/config` with `cam_credentials` in the body does not persist them; the settings page shows no scan-credentials form.
