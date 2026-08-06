## 1. Publishing: credentials and config scaffolding

- [x] 1.1 Add a `pypi:` block (`index_url`, `username`, `password`) to `conf.example/secrets.yaml`, documented as "private PyPI-compatible registry (Gitea/GitLab package registry or equivalent)"
- [x] 1.2 Add pypi credentials for onvif_sua — as a dedicated `onvif_sua/.pypi.env.example` (separate from `.env.example`, which IS deployed to production boards and must never carry publish credentials)
- [x] 1.3 Document in both READMEs that `pypi.index_url` accepts any PyPI-compatible simple index (no registry-specific assumptions)

## 2. Publishing: root `serena` Taskfile

- [x] 2.1 Add a `build` task to root `Taskfile.yml` (root currently has none) that runs `uv build`, mirroring `onvif_sua`'s existing `build` task
- [x] 2.2 Add a `release:publish` task that reads `pypi.index_url`/`username`/`password` from `conf/secrets.yaml` (same `awk`-block extraction pattern as `mqtt:test-tts`), exports `UV_PUBLISH_URL`/`UV_PUBLISH_USERNAME`/`UV_PUBLISH_PASSWORD`, and runs `uv publish`
- [x] 2.3 `release:publish` fails fast with an explicit error (before any network call) if the `pypi:` block or any required field is missing
- [x] 2.4 Confirm `task release:patch`/`minor`/`major` remain unchanged (version bump stays a separate, explicit step from publish) — verified via `task --list`, untouched in the diff

## 3. Publishing: `onvif_sua` Taskfile

- [x] 3.1 Add a `publish` task alongside the existing `build`/`install` tasks, same credential-reading/`uv publish` pattern as root's `release:publish` (reads `.pypi.env`, see 1.2)
- [x] 3.2 Verify `requirements.lock` regeneration (already part of `build`) still runs before publish — `publish` depends on `task: build`

## 4. `production/` directory scaffold

- [x] 4.1 Create `production/` with `Taskfile.yml`, `README.md`, `.env.example`, `.gitignore` (ignoring `.env`) — Taskfile/README done in this pass (section 7/8); scaffold directories created now
- [x] 4.2 Create `production/templates/` for config templates and systemd unit templates
- [x] 4.3 Create `production/setup/` for forked OS-level setup scripts

## 5. `production/`: config and systemd unit templates

- [x] 5.1 Copy `conf.example/config.yaml` and `conf.example/actions/` into `production/templates/alexa-custom/`; also added `secrets.yaml.example` (same shape as `conf.example/secrets.yaml` minus the `pypi:` block — needed for `config:init` to seed a board's own secrets file)
- [x] 5.2 Copy `onvif_sua/settings.yaml.example` and `onvif_sua/.env.example` into `production/templates/onvif-sua/`
- [x] 5.3 Write `production/templates/alexa-custom.service` — mirrors `setup/serena.service`, `ExecStart=%h/apps/alexa-custom/.venv/bin/serena`, `WorkingDirectory=%h/apps/alexa-custom`
- [x] 5.4 Write `production/templates/onvif-sua.service` — mirrors `onvif_sua/onvif-sua-user.service`, paths under `%h/apps/onvif-sua`

## 6. `production/`: ported setup scripts (audio, MQTT broker, bridge)

- [x] 6.1 Copy `setup/usb-audio-restore.sh`, `setup/99-usb-audio-no-autosuspend.rules`, `setup/usb-audio-autosuspend.service`, `setup/alsa-pcm-unmute.service`, and `setup/51-usb-audio-no-suspend.conf` (added — needed for full audio:setup parity, missing from the original task list) into `production/setup/`. Header comments turned out to conflict with byte-identical drift-checking (6.4), so the source-of-truth map lives in one place instead: `production/setup/SOURCES.md`
- [x] 6.2 Copy `setup/mosquitto-serena.conf` and `setup/mosquitto-bridge.conf.template` into `production/setup/`, same `SOURCES.md` mapping
- [x] 6.3 Copy `scripts/render-mqtt-bridge.sh` into `production/setup/` — corrected from the original task wording: bridge credentials stay in the board's own `conf/secrets.yaml` (`mqtt.bridge_username`/`bridge_password`, same as today), NOT `production/.env` (that's registry credentials, a different concern). Only the default `SECRETS`/`TEMPLATE` paths change, to `~/apps/alexa-custom/conf/secrets.yaml` and the sibling template file
- [x] 6.4 Add `check:drift` task to root `Taskfile.yml` — diffs the 7 files from 6.1–6.2 (not `render-mqtt-bridge.sh`, which has a permanent documented default-path difference) and fails listing any diverged file

## 7. `production/Taskfile.yml`: install and provisioning tasks

- [x] 7.1 `pypi:install` — creates `~/apps/alexa-custom/.venv` and `~/apps/onvif-sua/.venv` (`uv venv --python 3.13` each, skipped if already present), then `uv pip install --python <venv>/bin/python --upgrade --index-url ...` into each; accepts `ALEXA_CUSTOM_VERSION`/`ONVIF_SUA_VERSION` Task vars, defaulting to latest. Verified: dry-run with a fake index reached the real network call and failed only on DNS, confirming the bash logic is correct
- [x] 7.2 `config:init` — `cp -n` templates from `production/templates/` into `~/apps/alexa-custom/conf/` and `~/apps/onvif-sua/{settings.yaml,.env}`, `chmod 600` the `.env`/secrets files, never clobbering existing files. Verified with a real run against this dev machine's `$HOME` (cleaned up after)
- [x] 7.3 `audio:setup` — ported from root's `audio:setup`, invoking `production/setup/` scripts, no dependency on a `serena` checkout (legacy NewPie-specific cleanup lines dropped — irrelevant to a fresh board)
- [x] 7.4 `mqtt:setup` — ported from root's `mqtt:setup`, installs Mosquitto using `production/setup/mosquitto-serena.conf`
- [x] 7.5 `mqtt:bridge-setup` — ported from root's `mqtt:bridge-setup`, runs `production/setup/render-mqtt-bridge.sh` against `~/apps/alexa-custom/conf/secrets.yaml`, restarts Mosquitto. **Deliberately NOT part of `bootstrap`'s automatic chain** — see 7.7's note and the updated `production-provisioning` spec
- [x] 7.6 `systemd:install` — copies `production/templates/alexa-custom.service` and `onvif-sua.service` to `~/.config/systemd/user/`, `daemon-reload`, `enable` (not `--now`) for both; guards on both venv binaries existing first
- [x] 7.7 `bootstrap` — runs 7.1 → 7.2 → 7.3 → 7.4 → 7.6 (**not** 7.5/`mqtt:bridge-setup`, corrected from the original plan: it needs bridge credentials that only exist once the operator edits the just-seeded `secrets.yaml`, exactly why the root Taskfile never auto-chains it either), ends with guidance to edit secrets, run `mqtt:bridge-setup`, then start services
- [x] 7.8 `update` — re-runs `pypi:install` (which already upgrades) for both venvs (respecting `ALEXA_CUSTOM_VERSION`/`ONVIF_SUA_VERSION`), then `systemctl --user restart` both
- [x] 7.9 `uninstall` — stops/disables/removes both systemd user units only; leaves `~/apps/*` untouched
- [x] 7.10 `systemd:status`/`systemd:logs`/`systemd:start`/`systemd:stop` convenience tasks mirroring the existing `ha:status`-style helpers

## 8. Documentation

- [x] 8.1 Write `production/README.md`: prerequisites, publishing a release, fetching `production/` via git sparse-checkout (plus the tarball-release fallback), filling in `.env`/config, running `bootstrap`, starting/verifying both services, updating, uninstalling
- [x] 8.2 Cross-link `production/README.md` from the root `README.md` (both the new "📦 Releasing & Publishing" section and the "📚 Documentation" table) and `onvif_sua/README.md`
- [x] 8.3 Note in both root and `onvif_sua` READMEs that `task check:drift` must pass before publishing a release if any `setup/`/`scripts/` file touched by the production bundle was changed

## 9. Verification

- [x] 9.1 Run `task check:drift` immediately after creating the `production/setup/` forks — passed (files identical at creation time)
- [x] 9.2 Verified `production/Taskfile.yml`: `task --list` parses cleanly; `task --dry` on every task shows no errors; `bash -n` on every embedded shell block passes; `config:init` and the start of `pypi:install` (through the real `uv venv`/`uv pip install` network call, which failed only on an intentionally-fake DNS name) were run for real against this dev machine's `$HOME` and cleaned up afterward
- [x] 9.3 **Deferred** — no private registry instance exists yet (see design.md Open Questions) and no spare board is available in this session. Cannot be completed until both exist; tracked as follow-up, not silently skipped
