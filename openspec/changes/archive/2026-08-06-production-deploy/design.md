## Context

Today both apps are installed the same way, dev and prod alike: clone
`serena`, run `task setup` (root) or `task setup && task install:systemd`
(`onvif_sua`), which creates a `uv`-managed `.venv` inside the checkout and
points a `systemd --user` unit at `%h/serena/.venv/bin/...` (see
`setup/serena.service`, `onvif_sua/onvif-sua-user.service`). Audio, the local
MQTT broker, and the bridge to the master broker are wired up by further Task
targets (`audio:setup`, `mqtt:setup`, `mqtt:bridge-setup`) that shell out to
scripts under `setup/`/`scripts/`, all of which assume the checkout — and a
dev toolchain (`uv`, `git`, ruff, pytest, ...) — is present on the board.

Production boards should not need any of that: no git checkout, no dev
dependency group, no build tools beyond `uv`/`pip` themselves. They should
pull pinned, versioned releases of `alexa-custom` and `onvif-sua` from a
private package registry and run them exactly like today — `systemd --user`,
no sudo for the app processes themselves — with a guided bootstrap replacing
the current "read the README, run six Task targets in order" procedure.

## Goals / Non-Goals

**Goals:**
- Build+publish `alexa-custom` and `onvif-sua` wheels from their existing
  `uv`/`pyproject.toml` setups to a private PyPI-compatible registry
  (Gitea or GitLab package registry — see Open Questions), versioned by the
  existing `release:patch`/`minor`/`major` flow.
- A `production/` bundle, independent of a `serena` git checkout, that a
  fresh board can fetch and run to end up with: both apps installed from the
  private index into per-app venvs, USB audio configured, local Mosquitto
  broker installed + bridged to the master, and both apps running as
  `systemd --user` services — matching current on-board behavior exactly.
- Keep the *names* the user already knows (`task audio:setup`,
  `task mqtt:setup`, `task mqtt:bridge-setup`) so the mental model transfers,
  even though they now live in a different Taskfile.

**Non-Goals:**
- Standing up the actual private registry instance (Gitea/GitLab) — that's
  an infra prerequisite, not part of this change. This change only makes the
  tooling registry-agnostic (any PyPI-compatible simple index + upload API).
- Home Assistant provisioning (`task ha:setup`) — explicitly out of scope.
- Fleet orchestration (pushing installs to N boards at once, central
  inventory, etc.) — one board at a time, run locally on that board.
- Replacing or changing the existing dev-checkout install path — `task setup`
  keeps working exactly as it does today.

## Decisions

### 1. Registry: any PyPI-compatible "simple" index, targeted via `uv publish` / `uv pip install --index-url`

Both Gitea's and GitLab's package registries implement the standard PyPI
`simple` index API and the standard upload API, so nothing registry-specific
needs to be hardcoded. `uv publish` (already required — `uv` is a hard
prerequisite everywhere else in this repo) reads `UV_PUBLISH_URL` /
`UV_PUBLISH_USERNAME` / `UV_PUBLISH_PASSWORD` from the environment; `uv pip
install --index-url` accepts embedded credentials the same way. No new tool
(e.g. `twine`) is added as a dependency.

*Alternative considered*: `twine upload`. Rejected — it would be the only
non-`uv` publishing tool in either Taskfile, for no behavioral gain.

### 2. Credentials live in `conf/secrets.yaml` (dev/publish side) and `production/.env` (board side)

Publishing happens on a maintainer's machine, which already has
`conf/secrets.yaml` for MQTT/LiveKit/Telegram secrets — a new `pypi:` block
(`index_url`, `username`, `password`) fits the existing pattern and is read
with the same `awk`-block extraction already used by `mqtt:test-tts`/
`mqtt:trigger`. The production bundle has no `conf/secrets.yaml` (no
checkout), so it gets its own `production/.env` (created from a committed
`production/.env.example`, gitignored), holding `PYPI_INDEX_URL` /
`PYPI_USERNAME` / `PYPI_PASSWORD`, exported before any `uv pip install`.

### 3. Production layout: `~/apps/<name>/{.venv, conf-or-settings, data}`, one dir per app

```
~/apps/alexa-custom/.venv/bin/serena
~/apps/alexa-custom/conf/{config.yaml, actions/, secrets.yaml}
~/apps/onvif-sua/.venv/bin/onvif-sua
~/apps/onvif-sua/{settings.yaml, .env, data/}
```

Mirrors the current per-app directory shape (each app already keeps its venv
+ config + data together), just rooted at `~/apps/<name>` instead of
`~/serena` / `~/serena/onvif_sua`. systemd unit templates point
`WorkingDirectory`/`ExecStart` at these paths.

*Alternative considered*: one shared venv for both apps. Rejected — the two
have already-pinned, independently-versioned dependency sets (see
`pyproject.toml` in each); a shared venv would force them to move in lockstep
and reintroduces exactly the kind of coupling the wheel split avoids.

### 4. `production/` ships its own Taskfile + forked copies of the OS-level setup scripts

The Python code is what the wheels carry; everything else `audio:setup`/
`mqtt:setup`/`mqtt:bridge-setup` touch — udev rules, systemd unit files,
`mosquitto-*.conf`, the bridge-render script — is **not** Python package
data and was never going to ship in a wheel. `production/setup/` gets its own
copies of exactly those files, referenced by a new `production/Taskfile.yml`
that reimplements the same-named tasks against `~/apps/...` paths instead of
checkout-relative ones.

Each forked file carries a header comment pointing back at its source of
truth (e.g. `# forked from ../../setup/usb-audio-restore.sh — keep in sync`),
and a new `task check:drift` (root Taskfile) diffs every
`production/setup/*` file against its source counterpart, failing loudly on
divergence. This is a guardrail, not a fix — seed Decisions/Risks below.

*Alternative considered*: symlink `production/setup/` files into `setup/`.
Rejected — `production/` must be fetchable on its own (see Decision 5)
without pulling in the rest of the repo; symlinks across that boundary would
dangle for anyone who only fetches `production/`.

### 5. Fetching `production/` on a board with no full checkout: git sparse-checkout of just that path

`production/` stays inside the same `serena` GitHub repo (single source of
truth, versioned alongside the code it deploys), but a board only needs:

```bash
git clone --filter=blob:none --no-checkout git@github.com:scipioni/serena.git ~/serena-prod
cd ~/serena-prod && git sparse-checkout set production && git checkout main
```

`git pull` later picks up new production-bundle revisions without ever
materializing `alexa_custom/`, `onvif_sua/`, or any dev tooling. Documented
in `production/README.md` as the primary method; a plain tarball attached to
a GitHub Release is noted as a no-git fallback for boards that shouldn't talk
to GitHub at all.

*Alternative considered*: a separate repo just for `production/`. Rejected —
splits the deploy tooling from the code it deploys, doubling the places a
release needs a matching change.

### 6. Versioning: `VERSION=` Task var, default `latest`, pinned exact version for reproducible/rollback installs

`task pypi:install` (and `task update`) accept `VERSION={{.VERSION}}` (default
empty → `uv pip install alexa-custom onvif-sua` picks latest from the index);
passing `VERSION=0.5.2` installs that exact release. Rollback is "re-run
install with an older `VERSION=`" — no separate rollback mechanism needed.

## Risks / Trade-offs

- **[Risk] Forked setup scripts drift from `setup/`/`scripts/` originals over
  time** → Mitigated by `task check:drift` (Decision 4), but this is a
  guardrail that only fires when someone remembers to run it (or it's wired
  into CI) — not a structural fix. Accepted for this change; a shared-source
  refactor (e.g. root Taskfile also reading from `production/setup/`) is a
  candidate for a later change if drift proves to be a recurring problem.
- **[Risk] Private registry read access at install time, not just publish
  time** → most self-hosted registries require auth for both. Mitigated by
  Decision 2's `production/.env`; if the eventual registry does allow
  anonymous read, `PYPI_USERNAME`/`PYPI_PASSWORD` simply go unused — no
  redesign needed either way.
- **[Trade-off] Two Taskfiles with identically-named tasks** (root
  `Taskfile.yml` and `production/Taskfile.yml` both define `audio:setup`,
  `mqtt:setup`, `mqtt:bridge-setup`) — intentional (Decision 4's rationale),
  but must be documented clearly so nobody runs the wrong one from the wrong
  directory. `production/README.md` states explicitly "run these from inside
  `production/`, not the `serena` checkout."
- **[Risk] No registry exists yet** → this change ships the tooling; a real
  install can't be exercised end-to-end until the registry is provisioned.
  See Open Questions.

## Migration Plan

Additive only — no migration of already-deployed boards is required by this
change. Existing boards keep running exactly as installed (dev-checkout +
`task setup`). Rollout for *new* production boards:

1. Provision the private registry (outside this change's scope) and record
   its URL/credentials.
2. `task release:publish` (root) / `task publish` (`onvif_sua`) once, to get
   an initial release into the registry.
3. On a fresh board: sparse-checkout `production/`, fill in
   `production/.env`, run `task bootstrap` (or the individual steps), review
   config/secrets, start both services.
4. Verify both against the same checks used today (`systemctl --user
   status`, `journalctl --user -fu`, MQTT state topic, web UI).

Rollback: re-run the bootstrap with an older `VERSION=` (Decision 6), or
`task uninstall` (removes the two systemd user units; leaves venvs/config/data
untouched, same "safe by default" pattern as the existing
`onvif_sua uninstall:systemd`).

## Open Questions

- **Which registry, and its URL** — Gitea or GitLab package registry was the
  chosen shape, but no instance exists yet. Needs to be stood up and its
  `index_url` recorded in `conf/secrets.yaml.example` / `production/.env.example`
  before `tasks.md` items touching real credentials can be verified
  end-to-end.
- **Anonymous read vs. authenticated read** for `pip install` from the
  registry — assumed authenticated (safer default); confirm once the
  registry exists and relax if it turns out to allow anonymous read on the
  internal network.
- **CI wiring for `task check:drift`** — this design proposes the task but
  leaves whether/how it runs automatically (pre-commit hook? GitHub Actions?
  manual pre-release step?) to `tasks.md`/implementation.
