## ADDED Requirements

### Requirement: Checkout-free package install
The system SHALL provide a `production/` bundle, fetchable independently of a
full `serena` git checkout, that installs both `alexa-custom` and
`onvif-sua` from the configured private registry into standalone per-app
`uv`-managed venvs.

#### Scenario: Fresh board install with no source checkout
- **WHEN** an operator fetches only the `production/` directory onto a fresh board (e.g. via `git sparse-checkout`) and runs the install task
- **THEN** `~/apps/alexa-custom/.venv` and `~/apps/onvif-sua/.venv` are created, each with its respective package installed from the private index, and no `alexa_custom/` or `onvif_sua/` Python source directory exists on the board

### Requirement: Selectable package version, default latest
The install/update tasks SHALL accept an optional version override per
package; when omitted, the latest version published to the registry is
installed.

#### Scenario: Installing a pinned version
- **WHEN** an operator runs the install task with an explicit version for a package
- **THEN** exactly that version of the package is installed, not the latest

#### Scenario: Installing without a version override
- **WHEN** an operator runs the install task with no version specified
- **THEN** the latest version published to the registry is installed

### Requirement: Audio setup without a checkout dependency
`production/` SHALL provide an `audio:setup` task that configures the
attached USB conference speakerphone (device-agnostic USB-audio matching, per
existing behavior) with the same effect as the root repo's `task
audio:setup`, without requiring the `serena` checkout to be present.

#### Scenario: Running audio setup from the production bundle
- **WHEN** an operator runs `task audio:setup` from inside `production/` on a board with a USB conference speakerphone attached
- **THEN** the device is configured as the default sink/source, hardware mixers are unmuted, the no-autosuspend udev rule is installed, and the restore service is enabled — matching the effect of the root Taskfile's `audio:setup`

### Requirement: MQTT broker and bridge setup without a checkout dependency
`production/` SHALL provide `mqtt:setup` and `mqtt:bridge-setup` tasks that
reproduce the root repo's local Mosquitto broker install and its bridge
configuration to the master broker, without requiring the `serena` checkout.

#### Scenario: Installing the local broker
- **WHEN** an operator runs `task mqtt:setup` from inside `production/`
- **THEN** Mosquitto is installed and enabled as a system service with the shipped configuration, matching the root Taskfile's `mqtt:setup`

#### Scenario: Configuring the bridge to the master broker
- **WHEN** an operator runs `task mqtt:bridge-setup` from inside `production/` with bridge credentials available in `production/.env`
- **THEN** the bridge configuration is rendered and Mosquitto is restarted, connecting to the master broker with the same topic-forwarding rules as the root Taskfile's `mqtt:bridge-setup`

### Requirement: systemd user services for both apps, no sudo
`production/` SHALL install and enable `systemd --user` units for both
`alexa-custom` and `onvif-sua`, with `WorkingDirectory`/`ExecStart` pointing
at the production venv paths, requiring no `sudo` and no dedicated system
user for either app process.

#### Scenario: Installing both services
- **WHEN** an operator runs the systemd-install task from inside `production/` after the packages have been installed
- **THEN** `~/.config/systemd/user/alexa-custom.service` and `~/.config/systemd/user/onvif-sua.service` exist, `systemctl --user daemon-reload` has run, and both units are enabled but not started

### Requirement: One-shot guided bootstrap
`production/` SHALL provide a single task that runs the provisioning sequence
(package install → config initialization → audio setup → local MQTT broker
install → systemd install) in the correct order, and SHALL stop short of
starting either service so the operator can review or edit configuration and
secrets first. The MQTT **bridge** setup SHALL NOT be part of this automatic
sequence — it requires bridge credentials that only exist once the operator
has edited the freshly-seeded `secrets.yaml`, so it stays a separate,
explicitly-run step for the same reason it is not auto-chained in the root
repo's own `task setup`.

#### Scenario: Running the full bootstrap on a fresh board
- **WHEN** an operator runs the bootstrap task on a fresh board with `production/.env` filled in
- **THEN** every step through systemd install completes in order, both services end up installed and enabled but not started, and the task's final output tells the operator to edit secrets, then run the bridge-setup task, then start the services

#### Scenario: Bridge setup deferred until secrets are edited
- **WHEN** an operator runs the bridge-setup task immediately after bootstrap, before editing the seeded `secrets.yaml`
- **THEN** the task fails with a clear "missing bridge credentials" error rather than rendering a broken bridge config

### Requirement: Documented end-to-end procedure
`production/README.md` SHALL document the complete procedure: publishing a
release, fetching `production/` onto a board, filling in credentials and
configuration, running the bootstrap, and verifying both services are
running.

#### Scenario: Following the README with no prior context
- **WHEN** an operator with registry credentials already provisioned follows `production/README.md` step by step on a fresh board
- **THEN** they end up with both services running, verifiable via `systemctl --user status` and the existing MQTT state-topic and web-UI checks

### Requirement: Non-destructive uninstall
`production/` SHALL provide an uninstall task that removes only the systemd
user units for both apps, leaving installed venvs, configuration, secrets,
and data untouched by default.

#### Scenario: Uninstalling the services
- **WHEN** an operator runs the uninstall task from inside `production/`
- **THEN** both systemd user services are stopped, disabled, and their unit files removed, while `~/apps/alexa-custom` and `~/apps/onvif-sua` (venvs, config, data) remain on disk

### Requirement: Drift guard between dev and production setup scripts
The root repo SHALL provide a `check:drift` task that compares each forked
file under `production/setup/` against its source-of-truth counterpart under
`setup/`/`scripts/`, failing if any pair differs.

#### Scenario: Detecting drift after an unported change
- **WHEN** a source-of-truth file such as `setup/usb-audio-restore.sh` is modified but its `production/setup/` counterpart is not updated to match
- **THEN** `task check:drift` fails and names the diverged file(s)

#### Scenario: No drift present
- **WHEN** every forked file under `production/setup/` is byte-identical to its source-of-truth counterpart
- **THEN** `task check:drift` passes
