# Production Deployment

Bootstraps a fresh board with `serena` (alexa-custom) and `onvif-sua` running
as `systemd --user` services — **no git checkout of either project's source,
no sudo for the app processes themselves, no dedicated system user.** Both
packages are pulled from a private PyPI-compatible package registry.

This is a separate, standalone Taskfile from the ones in the repo root and in
`onvif_sua/` — see "Why a separate Taskfile?" below. Task names deliberately
match the ones you already know (`audio:setup`, `mqtt:setup`,
`mqtt:bridge-setup`) — same effect, just running without a checkout.

## Prerequisites

- A private PyPI-compatible registry already exists and you have its URL
  (and read credentials, if it requires auth for installs) — see the root
  `README.md`'s "📦 Releasing & Publishing" section for how a release gets
  published there in the first place.
- `uv` installed on the board (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- `git` installed on the board (only used to fetch this `production/`
  directory — see below; not needed afterwards).
- Debian 13 (Trixie) or similar, systemd, PipeWire — same target environment
  as the rest of this repo.

## 1. Publish a release (once, from a dev machine)

```bash
# root repo
task release:patch      # or minor/major
task build
task release:publish

# onvif_sua
cd onvif_sua
task publish             # builds + publishes in one step
```

## 2. Fetch `production/` onto the board — no full checkout

```bash
git clone --filter=blob:none --no-checkout git@github.com:scipioni/serena.git ~/serena-prod
cd ~/serena-prod
git sparse-checkout set production
git checkout main
cd production
```

Only `production/` is materialized on disk — `alexa_custom/`, `onvif_sua/`,
and every dev dependency stay un-fetched. `git pull` later picks up new
production-bundle revisions the same way.

**No-git fallback**: download the `production/` folder from a tarball
attached to a GitHub Release instead, if this board shouldn't talk to
GitHub at all. Extract it anywhere and `cd` into it — everything below is
identical either way.

## 3. Configure and bootstrap

```bash
cp .env.example .env
$EDITOR .env              # PYPI_INDEX_URL (+ PYPI_USERNAME/PASSWORD if the registry requires auth for reads)

task bootstrap             # installs both packages, seeds config, sets up audio + local MQTT broker,
                            # installs (but does not start) both systemd --user services
```

`bootstrap` runs, in order: `pypi:install` → `config:init` → `audio:setup` →
`mqtt:setup` → `systemd:install`. It deliberately stops there — see step 4.

## 4. Edit secrets, connect the bridge, start

```bash
$EDITOR ~/apps/alexa-custom/conf/secrets.yaml   # livekit / telegram / mqtt.bridge_username+password
$EDITOR ~/apps/alexa-custom/conf/config.yaml    # wake words, recognition, audio device
$EDITOR ~/apps/onvif-sua/settings.yaml
$EDITOR ~/apps/onvif-sua/.env                   # CAMERA_PASSWORD, GUI_PASSWORD, ...

task mqtt:bridge-setup     # connects this board's local broker to the master
                            # (fails clearly if bridge_username/password are still empty)

task systemd:start
task systemd:status        # both should show active (running)
task systemd:logs          # follow both together
```

Verify the same way you would on a dev checkout: `journalctl --user -fu
alexa-custom` for `DEBUG Transcript:` lines, the MQTT `state` topic reporting
`{"state": "idle", ...}`, and the onvif-sua web UI on `:8081`.

## Updating

```bash
task update ALEXA_CUSTOM_VERSION=0.5.0 ONVIF_SUA_VERSION=1.1.0   # or omit both for "latest"
```

Reinstalls from the registry into the existing venvs and restarts both
services. Config/secrets/data are untouched.

## Uninstalling

```bash
task uninstall
```

Removes only the two `systemd --user` unit files. `~/apps/alexa-custom` and
`~/apps/onvif-sua` (venvs, config, secrets, data) are left on disk — a
subsequent `task bootstrap` picks up right where you left off (`config:init`
never overwrites existing files).

## Layout this creates

```
~/apps/alexa-custom/
  .venv/                       installed from the private registry
  conf/{config.yaml, secrets.yaml, actions/}
~/apps/onvif-sua/
  .venv/
  settings.yaml
  .env
  data/
~/.config/systemd/user/{alexa-custom,onvif-sua}.service
```

## Why a separate Taskfile?

The root `Taskfile.yml` and `onvif_sua/Taskfile.yml` both already have
`audio:setup`/`mqtt:setup`/`mqtt:bridge-setup`-shaped tasks, but every one of
them shells out to files under `setup/`/`scripts/` relative to a full git
checkout. Since a production board deliberately has no such checkout (that's
the whole point — see Prerequisites), this directory carries its own copies
of exactly the non-Python assets those tasks need (`setup/` here — see
`setup/SOURCES.md` for the source-of-truth mapping) and its own Taskfile that
points at `~/apps/...` instead of a checkout path.

Because these are forked files, they can drift from the originals. Run `task
check:drift` in the **root** repo (not here) after changing anything under
its `setup/`/`scripts/` that this bundle also carries a copy of — it fails
loudly if the two sides disagree.
