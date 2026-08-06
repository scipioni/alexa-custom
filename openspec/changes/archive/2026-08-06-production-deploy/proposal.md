## Why

Both `serena` (root) and `onvif_sua` currently only support dev-checkout-based
installs: `uv sync`/`task setup` inside a full git clone, with systemd units and
setup scripts (`setup/`, `scripts/`) that assume the checkout is present on the
target board. Deploying to production boards needs a repeatable, checkout-free
path: versioned packages pulled from a private index, plus a guided bootstrap
that wires up the full runtime (USB audio, local MQTT broker + bridge to the
master, and both apps as systemd user services) without needing the source
tree or dev tooling on the board.

## What Changes

- New Taskfile targets in root `serena` and in `onvif_sua` to build wheels and
  publish them to a private, Gitea/GitLab-hosted PyPI-compatible package
  registry, versioned via the existing `release:patch`/`release:minor`/
  `release:major` flow. Registry credentials come from `conf/secrets.yaml`
  (new `pypi:` block), never committed.
- New top-level `production/` folder, decoupled from the dev checkout:
  - Its own Taskfile (or scripts) that `pip`/`uv pip install`s `alexa-custom`
    and `onvif-sua` from the private index into standalone per-app venvs
    under the invoking user's home — no git clone of either repo required.
  - Checkout-independent ports of the audio setup (`task audio:setup`), local
    MQTT broker setup (`task mqtt:setup`), and MQTT bridge setup
    (`task mqtt:bridge-setup`) logic — same behavior, no dependency on the
    `serena` repo being present.
  - systemd **user** unit templates for both apps, `ExecStart`/
    `WorkingDirectory` pointing at the production venvs, mirroring the
    `%h`-relative, no-sudo pattern already used by `setup/serena.service` and
    `onvif_sua/onvif-sua-user.service` (just retargeted at the new venv
    layout instead of a checkout's `.venv`).
  - `production/README.md` documenting the end-to-end procedure: publish a
    release → bootstrap a fresh board → verify both services are running.
- Scope is intentionally just serena + onvif-sua + audio + local MQTT broker
  + bridge + systemd-user services, matching what's requested — Home
  Assistant (`task ha:setup`) stays out of scope.
- **BREAKING**: none for existing dev workflows — `task setup` and the
  current git-checkout install remain unchanged. This adds a second, separate
  install path for production boards; it does not replace the dev path.

## Capabilities

### New Capabilities
- `package-publishing`: Taskfile automation (in both `serena` and
  `onvif_sua`) to build and publish wheels to a private PyPI-compatible
  registry, reusing the existing version-bump/release flow.
- `production-provisioning`: a self-contained `production/` bundle (install
  scripts, systemd user unit templates, README) that bootstraps a fresh board
  — both packages installed from the private index, audio configured, local
  MQTT broker + bridge set up, both apps running as systemd `--user`
  services — with no dev checkout on the board.

### Modified Capabilities
(none — this is purely additive; no existing spec's requirements change)

## Impact

- **Affected code**: root `Taskfile.yml`, `onvif_sua/Taskfile.yml`, new
  `production/` directory tree, `conf/secrets.yaml.example` (new `pypi:`
  credentials block), `pyproject.toml` in both projects (publish/repository
  config).
- **Affected systems**: production boards (systemd `--user`, `uv`/`pip`, no
  git); a private package registry becomes a new operational dependency —
  must exist, be reachable from boards, and have credentials provisioned
  before a production install can run.
- **Depends on / mirrors**: `setup/serena.service` and
  `onvif_sua/onvif-sua-user.service` (unit shape, not reused directly — venv
  path differs); existing `mqtt:setup`/`mqtt:bridge-setup`/`audio:setup` task
  logic (ported for the no-checkout context, so it can drift from the dev
  Taskfile versions over time — design.md should call out how the two stay
  in sync, e.g. a shared script sourced by both, or an explicit
  cross-reference comment).
- **Out of scope**: Home Assistant provisioning (`task ha:setup`) is not part
  of the production bundle.
